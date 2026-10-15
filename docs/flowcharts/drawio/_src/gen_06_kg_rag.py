# -*- coding: utf-8 -*-
"""生成 06-知识图谱RAG.drawio（4 页）。

代码依据：
  backend/kg/schema.py            —— NODE_TYPES / REL_TYPES 全集、字段口径
  backend/kg/sync.py              —— 全量 sync_all / 增量 sync_order、逐类实体同步
  backend/kg/store.py             —— Neo4j 连接封装：get_driver / run / run_safe / is_ready / stats
  backend/kg/api.py               —— /api/kg 对外接口、MAX_GRAPH_NODES
  backend/main.py                 —— init_knowledge_graph() 启动时旁路初始化
  backend/api/order_api.py        —— _kg_sync() 订单状态变化时增量入图
  backend/rag/graph_retriever.py  —— 图谱召回通道：实体链接 → 可见性 → 兜底 → 事实收集 → 渲染
  backend/rag/pipeline.py         —— ModularRAG.query() 里图谱这一路的位置
  backend/rag/fusion.py           —— 加权 RRF 与图谱通道的 RRF 贡献
  backend/ai_rag.py               —— CHANNEL_WEIGHT
  backend/config_service.py       —— kg_* / rag_* 系统参数定义

所有统计数字（节点类别数、关系条数、各类阈值与常量）都在生成时从源码现读，
本文件不写死任何一个这样的数字——见下面 _load_* / _const / _config_default 一组函数。
"""

import ast
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DRAWIO_DIR = os.path.dirname(HERE)                       # docs/flowcharts/drawio
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))  # 项目根
BACKEND = os.path.join(ROOT, "backend")
OUT = os.path.join(DRAWIO_DIR, "06-知识图谱RAG.drawio")

sys.path.insert(0, HERE)
from drawio_kit import Page, write_drawio  # noqa: E402


# ——————————————————————————————————————————————
# 现查：从源码里读真实值
# ——————————————————————————————————————————————

def _load_module(path, name):
    """按文件路径加载一个模块（不解析整个包，避免拉起数据库依赖）。"""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read_source(path):
    with open(path, "r", encoding="utf-8") as fp:
        return fp.read()


def _const(path, name):
    """从源码里现读一个模块级常量（兼容 X = ... 与 X: T = ...）。"""
    tree = ast.parse(_read_source(path))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == name:
                    return ast.literal_eval(node.value)
        elif isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == name:
            return ast.literal_eval(node.value)
    raise KeyError("源码里找不到常量：%s（%s）" % (name, path))


def _config_default(key):
    """从 config_service.CONFIG_META 里现读某个系统参数的 default 值。

    整张 CONFIG_META 里含有变量引用，不能整体 literal_eval，
    所以按 key 定位到那一项再取值。
    """
    tree = ast.parse(_read_source(os.path.join(BACKEND, "config_service.py")))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "CONFIG_META":
            for k, v in zip(node.value.keys, node.value.values):
                if isinstance(k, ast.Constant) and k.value == key:
                    for kk, vv in zip(v.keys, v.values):
                        if isinstance(kk, ast.Constant) and kk.value == "default":
                            return ast.literal_eval(vv)
    raise KeyError("CONFIG_META 里找不到：%s" % key)


def _units(text):
    """粗略估算文本宽度（中文按 1，ASCII 按 0.55）。"""
    return sum(1.0 if ord(ch) > 0x2E80 else 0.55 for ch in text)


def _pack(parts, max_units=46.0, sep=" · "):
    """把片段按估算宽度打包成多行，避免在英文标识中间断开。"""
    lines, cur = [], ""
    for part in parts:
        if cur and _units(cur + sep + part) > max_units:
            lines.append(cur)
            cur = part
        else:
            cur = part if not cur else cur + sep + part
    if cur:
        lines.append(cur)
    return lines


schema = _load_module(os.path.join(BACKEND, "kg", "schema.py"), "kg_schema")
gd = _load_module(os.path.join(BACKEND, "rag", "graph_retriever.py"), "rag_graph_retriever")
fm = _load_module(os.path.join(BACKEND, "rag", "fusion.py"), "rag_fusion")

# —— 图谱字典（P1）——
NODE_TYPES = schema.NODE_TYPES                 # 现查：标签 → 元信息
REL_TYPES = schema.REL_TYPES                   # 现查：关系定义全集
N_NODES = len(NODE_TYPES)
N_RELS = len(REL_TYPES)
N_REL_NAMES = len({m["rel"] for m in REL_TYPES.values()})
N_ENUMS = len(schema.FIELD_ENUMS)
N_UNITS = len(schema.FIELD_UNITS)
NODE_CN = {lb: m["name"] for lb, m in NODE_TYPES.items()}
NODE_KEY = {lb: m["key"] for lb, m in NODE_TYPES.items()}
NODE_COLOR = {lb: m["color"] for lb, m in NODE_TYPES.items()}

# —— 召回通道的常量（P3）——
MAX_EDGES_PER_REL = gd._MAX_EDGES_PER_REL
MAX_LINES = gd._MAX_LINES
MATCH_SCORE = gd.GraphRetriever._MATCH_SCORE
MATCH_SCORE_LINES = _pack(
    ["%s %s" % (k, v) for k, v in MATCH_SCORE.items()], max_units=22
)
SELF_REF_PATTERN = gd._SELF_REF_RE.pattern
LABEL_HINTS = gd._LABEL_KEYWORD_HINTS
SENSITIVE_FIELDS = sorted(gd._SENSITIVE_FIELDS)
REL_PRIORITY = gd._REL_PRIORITY

_prio_groups = {}
for _rel, _p in REL_PRIORITY.items():
    _prio_groups.setdefault(_p, []).append(_rel)
PRIORITY_LINE = "\n".join(
    _pack(["%d：%s" % (p, " / ".join(_prio_groups[p])) for p in sorted(_prio_groups)], max_units=44)
)

# —— 融合参数（P4）——
_fusion_default = fm.FusionModule()
RRF_K = _fusion_default.rrf_k
FUSION_WEIGHTS = _fusion_default.channel_weights
CHANNEL_WEIGHT = _const(os.path.join(BACKEND, "ai_rag.py"), "CHANNEL_WEIGHT")
W_GRAPH = _config_default("rag_weight_graph")
W_FAQ = _config_default("rag_weight_faq")
W_IMAGE = _config_default("rag_weight_image")
W_DOC = _config_default("rag_weight_document")
RAG_GRAPH_LIMIT = _config_default("rag_graph_limit")
KG_NODE_LIMIT = _config_default("kg_graph_node_limit")

# —— 接口层（P2）——
MAX_GRAPH_NODES = _const(os.path.join(BACKEND, "kg", "api.py"), "MAX_GRAPH_NODES")
NEO4J_URI = "bolt://127.0.0.1:7687"          # store.DEFAULT_URI


def _cn(label):
    """节点标签的中文名（现查 schema.NODE_TYPES）。"""
    return NODE_CN.get(label, label)


pages = []

# ============================================================
# 页 1：图谱 Schema —— 节点类型与关系类型
# ============================================================
p = Page("01 图谱Schema（节点类型与关系类型）")
p.label("t1",
        "知识图谱 Schema：%d 类节点 × %d 条关系定义 —— 代码依据 backend/kg/schema.py"
        % (N_NODES, N_RELS),
        40, 16, 1240, 34, bold=True)

p.group("g1",
        "① 节点类型 NODE_TYPES（%d 类 · 每类一个业务主键 key）" % N_NODES,
        40, 64, 430, 800)
for _i, (_lb, _meta) in enumerate(NODE_TYPES.items()):
    p.node("nd%d" % _i,
           "%s %s\nkey: %s" % (_lb, _meta["name"], _meta["key"]),
           70, 110 + _i * 84, 370, 62,
           kind="data", fill="#F5F5F5", stroke=_meta["color"])

p.group("g2",
        "② 关系类型 REL_TYPES（%d 条定义 · %d 个关系名 · 起点 —关系→ 终点）"
        % (N_RELS, N_REL_NAMES),
        500, 64, 780, 1310)
for _i, (_key, _meta) in enumerate(REL_TYPES.items()):
    _y = 108 + _i * 84
    _st, _en = _meta["start"], _meta["end"]
    p.node("rs%d" % _i, "%s %s" % (_st, _cn(_st)), 530, _y, 190, 52,
           kind="end", fill="#FFFFFF", stroke=NODE_COLOR.get(_st, "#82B366"))
    p.node("rr%d" % _i, "%s\n%s" % (_meta["rel"], _meta["name"]), 760, _y - 4, 250,
           kind="process", stroke=_meta["color"])
    p.node("re%d" % _i, "%s %s" % (_en, _cn(_en)), 1050, _y, 190, 52,
           kind="end", fill="#FFFFFF", stroke=NODE_COLOR.get(_en, "#82B366"))
    p.edge("rs%d" % _i, "rr%d" % _i)
    p.edge("rr%d" % _i, "re%d" % _i)

p.node("n1",
       "字段口径（与节点、关系同源，都在 schema.py）\n"
       "· fields：字段 → (中文名, 是否敏感)；敏感 = 只有 admin 可见\n"
       "· FIELD_ENUMS %d 条：库内取值 → 中文（pending → 待派单）\n"
       "· FIELD_UNITS %d 条：fen 分→元 · coin 大狗币 · percent 百分数\n"
       "· 取定义入口：node_meta() / is_sensitive() / rel_name()\n"
       "· 节点的业务主键 key 就是 MERGE 的锚点：同一笔订单同步十次也只有一份"
       % (N_ENUMS, N_UNITS),
       40, 890, 430, kind="note")
p.node("n2",
       "业务上以 Order 为中心连成链：\n"
       "(Boss) -PLACED→ (Order) -FOR_GAME→ (Game)\n"
       "(Player) -SERVED→ (Order)、(Player) -HAS_TAG→ (Tag)\n"
       "(Boss) -HIRED→ (Player) —— 由订单推导出来的「人—人」关系\n"
       "Rating / Tip / Withdrawal / Punishment\n记录的都是「一单结束之后发生的事」",
       40, 1100, 430, kind="note")
pages.append(p)

# ============================================================
# 页 2：图谱构建与同步 —— MySQL → Neo4j
# ============================================================
p = Page("02 图谱构建与同步（MySQL → Neo4j）")
p.label("t2",
        "图谱构建与同步：MySQL 业务表 → Neo4j 图谱 —— 代码依据 backend/kg/sync.py、backend/kg/store.py、"
        "backend/main.py、backend/kg/api.py",
        40, 16, 1440, 34, bold=True)

p.group("g1",
        "① 三个触发入口（backend/main.py · backend/kg/api.py · backend/api/order_api.py）",
        40, 64, 1440, 230)
p.node("a1", "① 后端启动\nmain.py 模块级调用 init_knowledge_graph()",
       70, 118, 340, kind="start")
p.node("a2", "② 管理员点「重建图谱」\nPOST /api/kg/rebuild（require_roles 校验，仅 admin）",
       440, 118, 340, kind="start")
p.node("a3", "③ 订单状态变化\norder_api._kg_sync(db, order)\n下单 / 接单 / 结单等状态变更处调用",
       810, 118, 340, kind="start")
p.node("a4",
       "旁路原则：\n_kg_sync 整段包在 try 里，\n失败只打印一行日志，\n绝不影响下单 / 结单主流程。\n"
       "开关：kg_enabled、\nkg_auto_sync_order\n任一为 False 直接 return",
       1190, 110, 260, kind="note")

p.group("g2",
        "② 启动自检：三关都过才继续；任一关不过只打一行日志、本次跳过（backend/main.py "
        "init_knowledge_graph()）",
        40, 314, 1440, 340)
p.node("b1", "store.py 三道前置检查\navailable() / configured() / is_ready()",
       70, 368, 360, kind="process")
p.node("b2", "三关都过？", 480, 355, 250, 120, kind="decision")
p.node("b3", "否：只打印一行 [kg] 日志\n本次跳过知识图谱，后端照常启动",
       790, 370, 330, kind="error")
p.node("b4", "后端照常启动\n不影响下单等主流程", 1180, 375, 260, kind="end")
p.node("b5", "kg_sync.is_empty() ？", 480, 500, 300, 110, kind="decision")
p.node("b6", "否：不写入，只打印\n[kg] 知识图谱就绪：\n当前节点数 / 关系数\n（store.stats()）",
       830, 505, 330, kind="note")
p.node("b7", "是：kg_sync.sync_all(db)\nforce=False（非清空式全量同步）",
       70, 505, 330, kind="process")
p.edge("b1", "b2")
p.edge("b2", "b3", "否")
p.edge("b3", "b4")
p.edge("b2", "b5", "是")
p.edge("b5", "b6", "否（已有数据）")
p.edge("b5", "b7", "是（图谱为空）")

p.group("g3",
        "③ sync_all(db, force)：全量同步 —— 逐类实体 / 逐类关系同步（backend/kg/sync.py）",
        40, 674, 1440, 670)
p.node("s1",
       "ensure_constraints()：给 NODE_TYPES 里 %d 类节点的业务主键建唯一约束\n"
       "CREATE CONSTRAINT kg_<标签>_key IF NOT EXISTS（有约束才有索引，MERGE 才不扫全图）" % N_NODES,
       110, 734, 560, kind="process")
p.node("s2",
       "force=True 时先 clear()：按 NODE_TYPES 逐个标签 DETACH DELETE\n"
       "（只删本项目用到的标签，不碰库里别的东西）",
       110, 824, 560, kind="process")
p.node("s3", "① 老板：User.role == 'boss' → sync_boss()",
       110, 914, 560, kind="process")
p.node("s4",
       "② 打手：User.role == 'player' → sync_player() + sync_player_tags()\n"
       "（标签先删后建：审核通过 / 驳回 / 删除都能对上）",
       110, 1004, 560, kind="process")
p.node("s5",
       "③ 订单：Order 全量 → sync_order()\n"
       "(Boss)-[:PLACED]->(Order)、(Player)-[:SERVED]->(Order)\n"
       "(Order)-[:FOR_GAME]->(Game)、(Boss)-[:HIRED]->(Player)",
       110, 1094, 560, kind="process")
p.node("s6",
       "④ 评价（必须在订单之后，靠订单号连 Order）→ sync_rating()\n"
       "(Boss)-[:RATED]->(Rating)-[:ABOUT]->(Player)\n"
       "(Rating)-[:FOR_ORDER]->(Order)\n"
       "投诉型评价再补派生边 (Boss)-[:COMPLAINED]->(Player)",
       110, 1205, 560, kind="process")
p.node("s7",
       "⑤ 打赏 → sync_tip()\n"
       "(Boss)-[:TIPPED]->(Tip)-[:TO]->(Player)、(Tip)-[:FOR_ORDER]->(Order)",
       790, 734, 560, kind="process")
p.node("s8",
       "⑥ 提现 → sync_withdrawal()：(Player)-[:WITHDREW]->(Withdrawal)\n"
       "（提现没有对应订单，所以图上是一条只挂人的单边链）",
       790, 824, 560, kind="process")
p.node("s9",
       "⑦ 处罚通告 sync_punishments()\n"
       "读 content_config 的 punishment，按 md5(level|desc)[:16] 当主键\n"
       "从「」里提账号 → (Boss|Player)-[:PUNISHED]->(Punishment)\n"
       "提不到目标就只建节点（照样能被全文检索和统计命中）",
       790, 914, 560, kind="process")
p.node("s10",
       "⑧⑨⑩ 现场聚合，不另存一份计数（避免两份数据对不上）\n"
       "Game.order_count / HIRED.order_count / Player.tip_amount",
       790, 1046, 560, kind="process")
p.node("s11",
       "返回统计字典 result\n"
       "bosses / players / tags / orders / games / ratings /\n"
       "tips / withdrawals / punishments / errors / elapsed_ms / stats",
       790, 1136, 560, kind="process")
p.node("s12",
       "本次同步完成\n（增量写入 Neo4j；某类实体失败只记进 errors，不中断其余实体）",
       790, 1250, 560, kind="end")
p.edge("b7", "s1", "进入 sync_all 内部")
p.chain(["s1", "s2", "s3", "s4", "s5", "s6"])
p.edge("s6", "s7")
p.chain(["s7", "s8", "s9", "s10", "s11"])
p.edge("s11", "s12")

p.group("g4",
        "④ 最底层 store.py：只负责「怎么连、怎么跑一条 Cypher」，不关心业务语义（backend/kg/store.py）",
        40, 1364, 1440, 345)
p.node("st1",
       "run_safe(cypher, params, mode, tag)\n异常吞掉并打印，返回 []\n（给「顺带同步图谱」这类场景用）",
       90, 1424, 300, kind="process")
p.node("st2",
       "run(cypher, params, mode)\nmode='w' → execute_write\nmode='r' → execute_read\n"
       "统一走事务函数（内置重试）",
       460, 1424, 320, kind="process")
p.node("st3", "get_driver()\n懒加载 · 进程内单例\nconnection_timeout=5",
       850, 1424, 300, kind="process")
p.node("st4", "Neo4j Server\n%s\n（backend/.env）" % NEO4J_URI,
       1210, 1424, 240, kind="data")
p.edge("st1", "st2", "内部调用")
p.edge("st2", "st3", "取驱动")
p.edge("st3", "st4", "建连")
p.node("n3",
       "参数化传参（$name 占位），绝不拼字符串——否则会有 Cypher 注入\n"
       "is_ready()：真的打一次往返（RETURN 1 AS ok），不是判断单例是否为 None\n"
       "（退化成判单例的话，前端会在第一个瞬间误报「图谱没启用」）",
       90, 1550, 480, kind="note")
p.node("n4",
       "stats()：MATCH (n) 数节点、MATCH ()-[r]->() 数关系、\n"
       "UNWIND labels(n) 按标签分组计数\n"
       "失败时只回 error 字段，前端状态栏据此提示「未配置 / 连不上」",
       640, 1550, 480, kind="note")

p.node("n5",
       "⑤ 对外接口 backend/kg/api.py（前缀 /api/kg）：GET /stats（实况 + 节点/关系元信息）· "
       "GET /graph（可视化图数据）· GET /node/{label}/{key}（明细 + 一跳邻居）· GET /search（关键词）· "
       "POST /rebuild（全量重建，仅 admin）\n"
       "graph 单次返回节点数上限 MAX_GRAPH_NODES = %d；系统参数 kg_graph_node_limit 默认 %d，"
       "控制图谱页一次最多渲染多少节点" % (MAX_GRAPH_NODES, KG_NODE_LIMIT),
       40, 1729, 1440, kind="note")
pages.append(p)

# ============================================================
# 页 3：图谱召回 —— 从问题到事实
# ============================================================
p = Page("03 图谱召回（从问题到事实）")
p.label("t3",
        "图谱召回 GraphRetriever：从原始问题到图谱事实 —— 代码依据 backend/rag/graph_retriever.py",
        40, 16, 1440, 34, bold=True)

p.group("g1",
        "① 入口与前置检查 —— GraphRetriever.retrieve(question, role, username, limit)",
        40, 64, 1440, 300)
p.node("a1",
       "用户提问\nquestion（原始问题）+ role + username\n（role 决定可见性，username 收敛到本人）",
       80, 118, 360, kind="start")
p.node("a2", "question 非空？", 490, 110, 240, 110, kind="decision")
p.node("a3", "返回 []", 790, 125, 200, kind="end")
p.node("a4",
       "三关（from kg import store）\nstore.is_ready()：驱动在 / 密码配了 / 连得上\n任一关不过 → 返回 []",
       80, 240, 360, kind="process")
p.node("a5",
       "否：返回 []\n（RAG 少这一路照样能答，只是答不了关系型问题）",
       790, 245, 340, kind="end")
p.node("a6",
       "失败降级：图谱没配、连不上、\nCypher 报错，一律返回空列表，\n绝不抛异常。",
       1180, 110, 290, kind="note")
p.edge("a1", "a2")
p.edge("a2", "a3", "否")
p.edge("a2", "a4", "是")
p.edge("a4", "a5", "否（不可用）")

p.group("g2",
        "② 实体链接 _link_entities(question, role, username)：先让 Neo4j 找候选，再判命中字段与可见性",
        40, 384, 1440, 300)
p.node("b1",
       "一条 Cypher（不把全图拉回 Python 比对）\n"
       "MATCH (n) WHERE $q CONTAINS n.username / n.order_no\n"
       "/ n.nickname(len>=2) / n.name / n.tag_key\n"
       "RETURN elementId(n), labels(n), properties(n) LIMIT 20",
       80, 440, 400, kind="process")
p.node("b2",
       "_best_match()：按字段顺序取第一个命中\n"
       "_MATCH_SCORE（字段 → 分数，按此顺序判命中）：\n"
       + "\n".join(MATCH_SCORE_LINES) + "\n"
       "_whole_word_hit()：必须作为独立词命中\n"
       "（边界 [A-Za-z0-9_]：dashou 不会跟 dashou_10 一起中招）",
       530, 440, 400, kind="process")
p.node("b3",
       "_visible(role, label, props, username)\n"
       "admin / service：节点级全量可见（金额遮蔽见⑤）\n"
       "boss：只可见自己那个 Boss 节点\n"
       "player：只可见自己那个 Player 节点\n"
       "（与 backend/kg/api.py 口径一致）",
       980, 440, 400, kind="process")
p.node("b4",
       "命中但没有权限 → blocked = True\n（它用来阻止下面的「本人兜底」答非所问）",
       530, 590, 400, kind="error")
p.node("b5",
       "可见的进 seeds：\n{node_id, label, key, node_name, match_score, match_field}",
       80, 590, 400, kind="process")
p.edge("a4", "b1", "是")
p.edge("b1", "b2", "逐条判命中")
p.edge("b2", "b3", "有命中字段")
p.edge("b3", "b4", "不可见")
p.edge("b3", "b5", "可见")
p.edge("b4", "c1")

p.group("g3",
        "③ 两级兜底（seeds 为空时）与截断 —— 两个兜底都要求 blocked = False",
        40, 704, 1440, 370)
p.node("c1", "seeds 为空？\n且 blocked = False", 80, 760, 320, 130, kind="decision")
p.node("c2",
       "兜底 1 · 本人兜底\n"
       "role ∈ (boss, player) 且问题里有自称词\n"
       "_SELF_REF_RE = %s\n"
       "→ 取本人节点：score 0.6，match_field = 'self'" % SELF_REF_PATTERN,
       460, 760, 460, kind="process")
p.node("c3",
       "兜底 2 · 标签关键词（_LABEL_KEYWORD_HINTS）\n"
       + "\n".join("%s → %s" % (pat, lb) for pat, lb in LABEL_HINTS) +
       "\n→ 取该类最近 3 条：score 0.5，match_field = 'label_hint'",
       960, 760, 420, kind="process")
p.node("c4", "seeds 按 match_score 降序\n取前 5 个（seeds[:5]）",
       80, 920, 320, kind="process")
p.node("c5",
       "两个兜底都要求 blocked = False：\n"
       "问题里提到了别的实体、只是当前角色看不到时，\n"
       "兜底会把「看看 laoban 的余额」悄悄换成「你自己的记录」，\n"
       "答非所问，还容易让人误以为看到了别人的数据。",
       460, 920, 460, kind="note")
p.node("c6",
       "本人兜底还要求问题里有自称词：\n"
       "少了这一条，任何一道 boss / player 的题\n"
       "（「大狗币兑换比例是多少」）都会被兜底命中，\n"
       "把本人的订单列表塞进毫不相关的上下文。",
       960, 920, 420, kind="note")
p.edge("b5", "c1")
p.edge("c1", "c2", "是")
p.edge("c2", "c3", "仍为空")
p.edge("c3", "c4", "排序后截断")
p.edge("c1", "c4", "否（已有 seeds）")

p.group("g4", "④ 取一跳邻域 _collect_facts(seeds, limit)", 40, 1094, 1440, 410)
p.node("d0", "seeds 为空？", 800, 1150, 300, 110, kind="decision")
p.node("d0e", "是：返回 []", 1180, 1170, 220, kind="end")
p.node("d1",
       "一条 Cypher 取一跳邻域（双向）\n"
       "MATCH (n)-[r]-(m) WHERE elementId(n) IN $ids\n"
       "RETURN type(r) AS rel, startNode(r) = n AS out,\n"
       "labels(m), properties(m), elementId(m)",
       80, 1140, 620, kind="process")
p.node("d2",
       "按种子节点分组；没有边的节点也保留\n"
       "（处罚通告只有属性、没有邻居——跳过它，「有哪些处罚通告」就永远召回不到）",
       80, 1260, 620, kind="process")
p.node("d3",
       "再补种子自身的 properties\n（渲染时要按角色遮蔽敏感字段，所以现取）",
       80, 1340, 620, kind="process")
p.node("d4",
       "每条事实一个 fact；上限 limit = rag_graph_limit（默认 %d）\n"
       "limit 为 None 时走 _limit() 读系统参数" % RAG_GRAPH_LIMIT,
       80, 1420, 620, kind="process")
p.node("d5",
       "facts 为空 → 返回 []\n（任何一步异常都被吞掉并打印，绝不让 RAG 挂掉）",
       800, 1310, 600, kind="note")
p.edge("c4", "d0")
p.edge("d0", "d0e", "是")
p.edge("d0", "d1", "否")
p.chain(["d1", "d2", "d3", "d4"])
p.edge("d4", "r1", "facts 进入渲染")

p.group("g5",
        "⑤ 渲染成人话 _render(fact, role) / _render_props / _fmt —— 把结构化事实变成大模型读得懂的句子",
        40, 1524, 1440, 620)
p.node("r1",
       "表头：「· 【图谱事实】<标签中文名> <node_name>（关键属性）」\n"
       "_render_props 只取 _KEY_FIELDS 登记字段、按登记顺序输出\n"
       "_NAME_FIELD 里的「名字」字段跳过，不出现「订单 ORD123（订单号 ORD123）」这种重复",
       80, 1580, 660, kind="process")
p.node("r2",
       "按关系类型分组，组间顺序由 _REL_PRIORITY 决定（数字越小越先占行数预算）\n"
       + PRIORITY_LINE + "\n"
       "（事后单据类关系信息密度高、条数少，提到前面；订单类条数多、单条信息量低，排最后）",
       80, 1680, 660, kind="process")
p.node("r3",
       "节制三条（都是实测踩出来的）\n"
       "① 同一类关系最多 _MAX_EDGES_PER_REL = %d 条，其余折成「共 N 条，此处仅列前 %d 条」\n"
       "② 整条事实不超过 _MAX_LINES = %d 行，防止一条事实独占上下文预算\n"
       "③ 只有表头、且种子自身属性为空 → 这条事实丢掉"
       % (MAX_EDGES_PER_REL, MAX_EDGES_PER_REL, MAX_LINES),
       80, 1820, 660, kind="process")
p.node("r4",
       "敏感字段遮蔽（与 backend/kg/api.py 口径一致）\n"
       "_SENSITIVE_FIELDS 对非 admin 直接跳过——不是显示 0，而是根本不出现\n"
       "（0 会被误读成「他余额是 0」）\n"
       "例外：本人兜底命中（match_field = 'self'）按本人放行",
       800, 1580, 620, kind="process")
p.node("r5",
       "_fmt() 的单位与显示口径\n"
       "金额字段库里存的是「分」→ 先换成元；balance → 大狗币\n"
       "good_rate = -1 是哨兵值（还没有任何评价）→ 显示「—」\n"
       "status / review_status / is_complaint 查中文映射表",
       800, 1710, 620, kind="process")
p.node("r6",
       "输出 [Document]\n"
       "content = 渲染后的多行事实文本\n"
       "source_type = 'graph'，score = fact['match_score']\n"
       "metadata = node_id / label / key / node_name / match_score / match_field",
       800, 1840, 620, kind="process")
p.node("r7",
       "return docs → pipeline 的 all_graph_hits → FusionModule.fuse()\n"
       "（图谱这一路没有「查询变体」的概念：实体链接是对原始问题做的，按列表顺序当作排名）",
       80, 1970, 1340, kind="process")
p.node("r8", "本页结束：图谱召回给出事实文本，是否被用由④页的融合与过滤决定",
       80, 2070, 1340, 66, kind="end")
p.chain(["r1", "r2", "r3", "r4", "r5", "r6", "r7"])
p.edge("r7", "r8")
pages.append(p)

# ============================================================
# 页 4：图谱在模块化 RAG 中的位置
# ============================================================
p = Page("04 图谱在模块化RAG中的位置")
p.label("t4",
        "图谱在模块化 RAG 中的位置：三路召回中的一路 —— 代码依据 backend/rag/pipeline.py、"
        "backend/rag/fusion.py",
        40, 16, 1440, 34, bold=True)

p.group("g1",
        "① ModularRAG.query()：图谱是②多路召回里并列的一路（backend/rag/pipeline.py）",
        40, 64, 1440, 290)
p.node("a1", "用户提问\nquestion + role + username", 80, 118, 340, kind="start")
p.node("a2", "读取各环节的模块开关\n（ModularRAG 每次查询重新实例化，改完参数下次提问即生效）",
       80, 220, 340, kind="process")
p.node("a3",
       "① 查询改写 QueryRewriter.rewrite()\n"
       "产出多个查询变体（original / 同义扩展 / HyDE / 多查询）\n"
       "关闭改写时只用 original 变体，channels = [keyword, vector]",
       480, 118, 420, kind="process")
p.node("a4",
       "② 多路召回：对「每个查询变体」分别跑\n"
       "关键词 KeywordRetriever（FAQ BM25）\n"
       "向量 VectorRetriever（document / image / faq 三通道）",
       480, 230, 420, kind="process")
p.node("a5",
       "「图谱不跟着变体分裂」：它只用原始问题跑一次。\n"
       "原因：实体链接靠的是问题里出现的账户名 / 订单号 / 游戏名\n"
       "这些字面标识，而改写后的变体往往已经不含这些标识，\n"
       "拿变体去匹配只会白跑几趟 Neo4j。",
       960, 118, 460, kind="note")
p.edge("a1", "a2", "读开关")
p.edge("a2", "a3")
p.edge("a3", "a4")
p.edge("a4", "b1")

p.group("g2",
        "② 图谱这一路的开关与产出（backend/rag/pipeline.py + backend/rag/graph_retriever.py）",
        40, 374, 1440, 300)
p.node("b1",
       "use_graph = module_graph_retrieval_enabled(db)\n系统参数 rag_module_graph_retrieval",
       80, 430, 320, 130, kind="decision")
p.node("b2",
       "关闭 → 整路跳过：\nall_graph_hits 保持 []，\n后面的融合里就没有 graph 这一路",
       470, 440, 320, kind="error")
p.node("b3", "二路召回照常：向量 + 关键词", 470, 555, 320, 60, kind="end")
p.node("b4",
       "开启 → GraphRetriever.retrieve(\nquestion, role, username=username)\n只用原始问题跑一次",
       870, 430, 300, kind="process")
p.node("b5",
       "返回 [Document]，\nsource_type = 'graph'；\n平时是空列表 —— 不稀释另外两路",
       870, 550, 300, kind="process")
p.node("b6",
       "空列表是常态：\n只有问题里出现具体实体\n（账户名 / 订单号 / 游戏名 / 标签）\n才产出事实。\n"
       "所以图谱这一路的开启与关闭，\n不影响日常问答的召回质量。",
       1220, 430, 260, kind="note")
p.edge("b1", "b2", "关闭")
p.edge("b2", "b3")
p.edge("b1", "b4", "开启")
p.edge("b4", "b5")

p.group("g3",
        "③ 融合进 RRF：图谱通道权重最高（backend/rag/fusion.py + backend/ai_rag.py）",
        40, 694, 1440, 350)
p.node("c1", "三路结果是否全空？", 80, 750, 300, 110, kind="decision")
p.node("c2", "是：返回 ''（不注入参考资料）", 430, 765, 260, 70, kind="end")
p.node("c3",
       "FusionModule.fuse(kw_hits, vec_hits, graph_hits)\n"
       "rrf_k = %d（RRF_K 常量，_rrf_k(db) 读系统参数）" % RRF_K,
       80, 890, 460, kind="process")
p.node("c4",
       "图谱通道的 RRF 贡献\n"
       "key = ('graph', node_id, 0)\n"
       "rank = 列表下标（一个节点一条事实，\n不会与向量路撞同一条）\n"
       "contribution = 1 / (rrf_k + rank + 1) × graph 权重",
       600, 890, 380, kind="process")
p.node("c5",
       "通道权重 _channel_weights(db)（读系统参数，兜底 CHANNEL_WEIGHT）\n"
       "rag_weight_graph %s ＞ rag_weight_faq %s ＞\n"
       "rag_weight_image %s ＞ rag_weight_document %s\n"
       "图谱最高：它只在问题真的出现具体实体时才产出，\n"
       "一旦命中就说明用户在问某个具体的人 / 单"
       % (W_GRAPH, W_FAQ, W_IMAGE, W_DOC),
       1000, 880, 480, kind="note")
p.edge("b5", "c1")
p.edge("c1", "c2", "是")
p.edge("c1", "c3", "否")
p.edge("c3", "c4")

p.group("g4",
        "④ 融合之后的两个存亡点：图谱事实只存 graph 文档，认不出来就会被无声丢掉",
        40, 1064, 1440, 410)
p.node("d1",
       "④ 重排序（module_rerank_enabled）\n"
       "rag_rerank_mode = rule → Reranker.rerank()\n"
       "rag_rerank_mode = semantic → CrossEncoderReranker.rerank()\n"
       "图谱的 key ('graph', node_id, 0) 一路带到 ContextBuilder",
       80, 1120, 660, kind="process")
p.node("d2",
       "④.5 Self-RAG 相关性过滤（ai_self_rag_relevance_filter）\n"
       "取候选文本时必须认 pool[key]['graph']——\n"
       "图谱事实没有 chunk / faq，只有 graph 文档，\n"
       "认不出来就会被当「空文本」跳过，随后被过滤掉",
       800, 1120, 620, kind="process")
p.node("d3",
       "融合模块关闭（module_fusion_enabled = False）时的旁路\n"
       "不走 RRF 加权，直接 _simple_merge()：\n"
       "图谱排最前（含金量最高）→ 向量 → 关键词\n"
       "（保留这条路径是为了做对比测试）",
       80, 1250, 660, kind="note")
p.node("d4",
       "⑤⑥ 调试与上下文构建\n"
       "_fill_debug 里图谱单独列一段 graph_hits（它不对应任何查询变体）\n"
       "ContextBuilder.build() 渲染引用块 → 拼进 Prompt\n"
       "→ 大模型生成答案，返回答案",
       800, 1250, 620, kind="process")
p.node("d5",
       "图谱这一路的价值：回答「这个老板找过哪几个打手」「这单后来被打赏了多少」这类关系型问题\n"
       "答案不在任何一段文字里，而在实体之间的边上",
       80, 1380, 1340, kind="end")
p.node("n1",
       "本页只展开图谱这一路；三路召回的完整流程见 01-基础RAG 的「02 推理问答」页",
       40, 1470, 1340, 40, kind="label")
p.edge("c4", "d1")
p.edge("d1", "d2", "④.5")
p.edge("d2", "d4", "⑤⑥")
p.edge("d4", "d5")
pages.append(p)

write_drawio(OUT, pages)

# 自检：产物必须能被 XML 解析器直接解析。
# 节点文字里若混进英文双引号会直接破坏 value="..." 属性，这里当场报错而不是留到校验阶段。
import xml.etree.ElementTree as _ET  # noqa: E402

_ET.parse(OUT)
print("自检：XML 解析通过（未压缩 mxGraphModel，UTF-8）")

print("已生成：%s" % OUT)
print("页数：%d" % len(pages))
for _p in pages:
    print("  页「%s」：节点 %d 个，连线 %d 条" % (_p.name, len(_p._geom), len(_p._edges)))
print("—— 现查到的真实值 ——")
print("  NODE_TYPES  : %d 类（%s）" % (N_NODES, "、".join(NODE_TYPES.keys())))
print("  REL_TYPES   : %d 条定义 / %d 个关系名" % (N_RELS, N_REL_NAMES))
print("  FIELD_ENUMS : %d 条；FIELD_UNITS：%d 条" % (N_ENUMS, N_UNITS))
print("  graph 通道权重：%s（RRF_K=%d）" % (CHANNEL_WEIGHT.get("graph"), RRF_K))
print("  MAX_GRAPH_NODES：%d；kg_graph_node_limit：%d" % (MAX_GRAPH_NODES, KG_NODE_LIMIT))
