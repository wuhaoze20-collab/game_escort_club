"""Neo4j 图数据库连接封装层。

在整个知识图谱里的位置：最底层——只负责「怎么连、怎么跑一条 Cypher」，
不关心业务语义（业务语义在 schema.py 与 sync.py）。

设计原则（和其他外部依赖一致）：
    · 懒加载：只有真正用到图谱时才建立连接，启动时不连
    · 失败不致命：图谱不可用时返回空/False，绝不让下单、结单这些主流程挂掉
    · 连接复用：驱动是长连接对象，进程内单例复用，不要每次查询都新建

连接参数从 backend/.env 读取（与 DASHSCOPE_API_KEY 同一套机制）：
    NEO4J_URI=bolt://127.0.0.1:7687
    NEO4J_USER=neo4j
    NEO4J_PASSWORD=你的密码
"""

import os

# 进程内单例
_driver = None
_env_loaded = False

# 默认值：本机 Neo4j 的标准 Bolt 地址
DEFAULT_URI = "bolt://127.0.0.1:7687"
DEFAULT_USER = "neo4j"


def _load_env():
    """加载 backend/.env（只做一次）。失败不致命，静默降级。"""
    global _env_loaded
    if _env_loaded:
        return
    _env_loaded = True
    try:
        from dotenv import load_dotenv
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        load_dotenv(os.path.join(base_dir, ".env"))
    except Exception as e:
        print(f"[kg] 读取 .env 失败（不影响其它功能）：{e}")


def uri() -> str:
    _load_env()
    return (os.getenv("NEO4J_URI") or "").strip() or DEFAULT_URI


def user() -> str:
    _load_env()
    return (os.getenv("NEO4J_USER") or "").strip() or DEFAULT_USER


def password() -> str:
    _load_env()
    return (os.getenv("NEO4J_PASSWORD") or "").strip()


def configured() -> bool:
    """是否配置了密码。

    没有密码就没法连，此时前端只提示"未配置"，
    而不是抛一堆连接异常出来。
    """
    return bool(password())


def available() -> bool:
    """neo4j 驱动是否可导入。

    用 find_spec 探测而不真正 import：既省开销，
    也让「驱动有没有装」这件事能被静态检查看清。
    """
    try:
        import importlib.util
        return importlib.util.find_spec("neo4j") is not None
    except Exception:
        return False


def get_driver():
    """懒加载并返回 Neo4j 驱动（单例）。

    注意：GraphDatabase.driver() 本身不建立网络连接，
    真正的连接在第一次执行查询时发生，所以这里很轻。
    """
    global _driver
    if _driver is not None:
        return _driver

    from neo4j import GraphDatabase

    _driver = GraphDatabase.driver(
        uri(),
        auth=(user(), password()),
        connection_timeout=5,
    )
    return _driver


def reset():
    """丢弃当前驱动（改完密码、或连接异常后调用，下次重新建立）。"""
    global _driver
    try:
        if _driver is not None:
            _driver.close()
    except Exception:
        pass
    _driver = None


def is_ready() -> bool:
    """图谱是否真的可用：能连上、能执行一条最简单的查询。

    注意不要退化成「进程内单例是否为 None」——那样在读取的第一个瞬间
    永远返回 False，前端会误报成「图谱没启用」。这里让它真的打一次往返。
    （Chroma 那边就踩过这个坑。）
    """
    if not available() or not configured():
        return False
    try:
        return run("RETURN 1 AS ok", mode="r") is not None
    except Exception:
        return False


def run(cypher: str, params: dict = None, mode: str = "w"):
    """执行一条 Cypher 并把结果取回。

    参数：
        cypher: Cypher 语句，参数用 $name 占位
        params: 参数字典（**必须用参数化，不要拼字符串**，否则会有 Cypher 注入）
        mode:   "w" = 写（用事务函数，提交）
                "r" = 只读（用 execute_read，Neo4j 会路由到只读副本）

    返回：
        list[dict]，每条记录一个字典；失败时抛异常（由调用方决定是否兜底）

    为什么统一走 execute_read / execute_write 而不是 session.run：
    前者内置了事务重试（网络抖动、死锁会自动重试），更稳。
    """
    drv = get_driver()

    def _work(tx):
        result = tx.run(cypher, **(params or {}))
        return [rec.data() for rec in result]

    with drv.session() as sess:
        if mode == "r":
            return sess.execute_read(_work)
        return sess.execute_write(_work)


def run_safe(cypher: str, params: dict = None, mode: str = "w", tag: str = ""):
    """安全版 run：任何异常都被吞掉并打印，返回空列表。

    给「顺带同步图谱」这类场景用——图谱写失败绝不能拖垮主业务
    （下单、结单这些是用户的核心操作，不能因为图数据库抖动就失败）。
    """
    try:
        return run(cypher, params, mode) or []
    except Exception as e:
        print(f"[kg] 图谱操作失败{'（' + tag + '）' if tag else ''}：{type(e).__name__}: {e}")
        return []


def stats() -> dict:
    """图谱实况：是否可用、节点数、关系数、各标签计数。给前端状态栏用。"""
    info = {
        "driver_available": available(),
        "configured": configured(),
        "uri": uri(),
        "user": user(),
        "ready": False,
        "nodes": 0,
        "rels": 0,
        "labels": [],
        "error": "",
    }
    if not info["driver_available"]:
        info["error"] = "未安装 neo4j 驱动（pip install neo4j）"
        return info
    if not info["configured"]:
        info["error"] = "未配置 NEO4J_PASSWORD（见 backend/.env）"
        return info

    try:
        # 分两次查节点数与关系数：早先用 CALL { } 子查询一条查完，
        # 但新版 Neo4j 对不带变量作用域的 CALL 子查询发了弃用警告，
        # 拆开写反而更干净，也不影响性能（各是一次 count 聚合）。
        node_rows = run("MATCH (n) RETURN count(n) AS c", mode="r")
        rel_rows = run("MATCH ()-[r]->() RETURN count(r) AS c", mode="r")
        info["nodes"] = int(node_rows[0]["c"]) if node_rows else 0
        info["rels"] = int(rel_rows[0]["c"]) if rel_rows else 0

        label_rows = run(
            "MATCH (n) UNWIND labels(n) AS lb "
            "RETURN lb AS label, count(*) AS c ORDER BY c DESC",
            mode="r",
        )
        info["labels"] = [{"label": r["label"], "count": int(r["c"])} for r in label_rows]
        info["ready"] = True
    except Exception as e:
        info["error"] = f"{type(e).__name__}: {e}"
    return info
