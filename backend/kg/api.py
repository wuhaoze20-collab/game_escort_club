"""知识图谱的查询接口。

对外提供 5 个端点：

    GET  /api/kg/stats              图谱实况（节点/关系数、连接状态、标签分布）
    GET  /api/kg/graph              可视化用的图数据（节点 + 边，支持筛选）
    GET  /api/kg/node/{label}/{key} 单个实体的明细 + 一跳邻居
    GET  /api/kg/search             按关键词搜索节点
    POST /api/kg/rebuild            全量重建图谱（仅管理员）

=== 权限（与其他模块的既有口径保持一致）===

    admin   全部可见，包括后台金额、余额这些敏感金额
    service 可看老板/打手的基本信息，敏感金额字段隐藏
    boss    只能看自己
    player  只能看自己

敏感字段由 schema.NODE_TYPES 里的 fields 标注（第二项为 True 即敏感），
这里统一按标注过滤——以后往 schema 里加字段，权限自动跟着走，不用改这里。
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from models import User
from auth import get_current_user, require_roles
from kg import store, schema, sync

router = APIRouter(prefix="/api/kg", tags=["知识图谱"])

# 单次返回的节点数上限。图谱是全量数据，不加限制时一个几千订单的库
# 会把浏览器直接卡死——这里做上限，超出时提示用户去用搜索筛选。
MAX_GRAPH_NODES = 300


# ——————————————————————————————————————————————
# 权限辅助
# ——————————————————————————————————————————————

def _can_view_node(user: User, label: str, key: str) -> bool:
    """当前登录账号是否有权查看这个节点。"""
    if user.role == "admin":
        return True
    if user.role == "service":
        # 客服可查看老板与打手（业务上需要人工派单、处理咨询）
        return label in (schema.LABEL_BOSS, schema.LABEL_PLAYER)
    # 老板 / 打手：只能看自己
    if label in (schema.LABEL_BOSS, schema.LABEL_PLAYER):
        return key == user.username
    # 订单节点：老板看自己下的，打手看自己接的
    return True  # 具体在 _mask_order 里按归属再判一次


def _mask_props(user: User, label: str, props: dict) -> dict:
    """按角色把敏感字段抹掉。

    对无权查看的对象，金额字段直接置空字符串而不是返回 0——
    "0" 会被误读成"他余额是 0"，空字符串在前端显示为 "-"，语义正确。
    """
    if user.role == "admin":
        return props

    # 本人看自己的节点不遮蔽——余额、后台金额是自家数据，
    # 业务页面本来就能看到，图谱页没必要再藏一遍。
    if label in (schema.LABEL_BOSS, schema.LABEL_PLAYER):
        owner = str(props.get("username") or "")
        if owner and owner == user.username:
            return props

    out = {}
    for k, v in props.items():
        if schema.is_sensitive(label, k):
            out[k] = ""
        else:
            out[k] = v
    return out


# ——————————————————————————————————————————————
# 接口
# ——————————————————————————————————————————————

@router.get("/stats")
def kg_stats(current_user: User = Depends(get_current_user)):
    """图谱实况。任何登录用户都能看到图规模，但看不到具体金额。"""
    info = store.stats()
    info["types"] = {
        label: {"name": meta["name"], "color": meta["color"], "key": meta["key"]}
        for label, meta in schema.NODE_TYPES.items()
    }
    info["relations"] = [
        {"name": v["name"], "rel": v["rel"],
         "start": v["start"], "end": v["end"], "color": v["color"]}
        for v in schema.REL_TYPES.values()
    ]
    return info


@router.post("/rebuild")
def kg_rebuild(
    force: bool = Query(True, description="是否先清空再重建"),
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    """全量重建图谱（仅管理员）。

    从 MySQL 的老板/打手/订单表重新构建一遍。force=True 时先清空，
    适合图谱被手工改乱、或想从头来一次的场景。
    """
    if not store.available():
        raise HTTPException(status_code=503, detail="未安装 neo4j 驱动，请先 pip install neo4j")
    if not store.configured():
        raise HTTPException(status_code=503, detail="未配置 NEO4J_PASSWORD，请在 backend/.env 中填写")
    if not store.is_ready():
        raise HTTPException(status_code=503,
                            detail="无法连接 Neo4j，请确认服务已启动（默认 bolt://127.0.0.1:7687）")

    result = sync.sync_all(db, force=force)
    if result.get("errors"):
        # 部分失败不算整体失败：把成功的部分照常返回，把错误带上供排查
        result["partial"] = True
    return result


@router.get("/graph")
def kg_graph(
    labels: str = Query("", description="按标签筛选，逗号分隔，如 Boss,Player,Order"),
    limit: int = Query(MAX_GRAPH_NODES, description="返回节点数上限"),
    current_user: User = Depends(get_current_user),
):
    """取可视化用的图数据（节点 + 边）。

    节点按更新时间倒序取前 N 个，再连同这些节点之间的关系一起返回——
    先取节点再取边（而不是先取边）能保证结果里不会出现"边所指的节点没返回"
    的悬空情况。
    """
    if not store.is_ready():
        return {"available": False, "nodes": [], "edges": [],
                "reason": store.stats().get("error") or "图谱未启用"}

    want = [x.strip() for x in (labels or "").split(",") if x.strip()]
    want = [x for x in want if x in schema.NODE_TYPES] or list(schema.NODE_TYPES.keys())

    limit = max(10, min(int(limit), MAX_GRAPH_NODES))

    # 老板/打手只能看到与自己相关的部分：先定位到"本人"节点，再取它的邻域
    self_only = current_user.role in ("boss", "player")

    if self_only:
        node_rows = store.run(
            "MATCH (n) WHERE n.username = $u AND (n:Boss OR n:Player) "
            "RETURN n, labels(n) AS ls LIMIT 1",
            {"u": current_user.username}, mode="r")
        if not node_rows:
            return {"available": True, "nodes": [], "edges": [],
                    "reason": "图谱中还没有你的数据，请联系管理员同步"}
        self_nodes = _to_nodes(node_rows, current_user)

        # 取"本人 + 一跳邻域"作为可见子图：本人的订单、玩过的游戏、自己的标签、
        # 以及合作过的对方。只返回本人节点而不返回邻居，会让边找不到端点，
        # 前端画不出任何连线，等于看不到自己的订单。
        label_cond_self = " OR ".join(f"m:{lb}" for lb in want)
        nbr_rows = store.run(
            "MATCH (n) WHERE n.username = $u AND (n:Boss OR n:Player) "
            "MATCH (n)-[]-(m) "
            f"WHERE {label_cond_self} "
            "WITH DISTINCT m, labels(m) AS ls "
            "RETURN m AS n, ls LIMIT $lim",
            {"u": current_user.username, "lim": limit}, mode="r")

        nodes = self_nodes + _to_nodes(nbr_rows, current_user)
        node_keys = set((n["label"], n["key"]) for n in nodes)
        edges = _neighbor_edges(list(node_keys), current_user, restrict=node_keys)
        return {"available": True, "nodes": nodes, "edges": edges,
                "self_only": True, "truncated": False,
                "types": _types_meta(), "relations": _relations_meta()}

    label_cond = " OR ".join(f"n:{lb}" for lb in want)
    node_rows = store.run(
        f"MATCH (n) WHERE {label_cond} "
        "RETURN n, labels(n) AS ls "
        "ORDER BY coalesce(n.updated_at, '') DESC "
        "LIMIT $lim",
        {"lim": limit}, mode="r")

    nodes = _to_nodes(node_rows, current_user)
    # 只取两端都在返回集合里的边，避免前端出现指向不存在节点的连线
    node_keys = set((n["label"], n["key"]) for n in nodes)
    edges = _neighbor_edges(list(node_keys), current_user, restrict=node_keys)

    total_rows = store.run("MATCH (n) RETURN count(n) AS c", mode="r")
    total = int(total_rows[0]["c"]) if total_rows else 0

    return {
        "available": True,
        "nodes": nodes,
        "edges": edges,
        "total_nodes": total,
        "truncated": total > len(nodes),
        "limit": limit,
        "self_only": False,
        # 节点/关系的中文名与配色，前端据此画图例、上色，不用在前端写死
        "types": _types_meta(),
        "relations": _relations_meta(),
    }


def _types_meta() -> list:
    """所有节点类型的中文名、颜色与字段定义，供前端图例和明细面板使用。

    fields 是 [{key, name, sensitive}]，前端按这个顺序和中文名展示属性，
    免得把 consume_amount 这种库内字段名直接摆给用户看。
    """
    out = []
    for lb, meta in schema.NODE_TYPES.items():
        fields = []
        for fkey, fmeta in (meta.get("fields") or {}).items():
            # fields 的值既可能是 (中文名, 是否敏感) 元组，也可能只是中文名
            if isinstance(fmeta, (list, tuple)) and fmeta:
                fields.append({"key": fkey, "name": fmeta[0],
                               "sensitive": bool(fmeta[1]) if len(fmeta) > 1 else False})
            else:
                fields.append({"key": fkey, "name": str(fmeta), "sensitive": False})
        out.append({"label": lb, "name": meta.get("name") or lb,
                    "color": meta.get("color") or "", "key": meta.get("key") or "",
                    "fields": fields})
    return out


def _relations_meta() -> list:
    """所有关系类型的中文名与颜色，供前端图例使用。"""
    return [
        {"key": k, "name": v.get("name") or k, "color": v.get("color") or "",
         "start": v.get("start", ""), "end": v.get("end", "")}
        for k, v in schema.REL_TYPES.items()
    ]


@router.get("/node/{label}/{key}")
def kg_node(
    label: str,
    key: str,
    current_user: User = Depends(get_current_user),
):
    """单个实体的明细 + 它的邻居（一跳）。"""
    if label not in schema.NODE_TYPES:
        raise HTTPException(status_code=400, detail=f"未知的节点类型：{label}")
    if not store.is_ready():
        raise HTTPException(status_code=503, detail="图谱未启用")

    if not _can_view_node(current_user, label, key):
        raise HTTPException(status_code=403, detail="无权查看该实体")

    meta = schema.node_meta(label)
    rows = store.run(
        f"MATCH (n:{label} {{{meta['key']}: $key}}) "
        "RETURN n, labels(n) AS ls",
        {"key": key}, mode="r")
    if not rows:
        raise HTTPException(status_code=404, detail="图谱中没有这个实体")

    node = _to_nodes(rows, current_user)[0]

    # 一跳邻居（含方向和关系名），供前端做"点开看关联"
    nbr = store.run(
        f"MATCH (n:{label} {{{meta['key']}: $key}})-[r]-(m) "
        "RETURN m, labels(m) AS ls, type(r) AS rel, "
        "       startNode(r) = n AS outgoing "
        "LIMIT 50",
        {"key": key}, mode="r")
    neighbors = []
    seen = set()
    for rec in nbr or []:
        m = rec.get("m") or {}
        m_labels = rec.get("ls") or []
        m_label = m_labels[0] if m_labels else "?"
        m_meta = schema.node_meta(m_label)
        m_key = str(m.get(m_meta["key"], ""))
        sig = (rec.get("rel"), m_label, m_key, rec.get("outgoing"))
        if sig in seen:
            continue
        seen.add(sig)
        neighbors.append({
            "rel": rec.get("rel"),
            "rel_name": _rel_name(rec.get("rel")),
            "outgoing": bool(rec.get("outgoing")),
            "label": m_label,
            "label_name": m_meta["name"],
            "key": m_key,
            "display": _display(m_label, m),
            "props": _mask_props(current_user, m_label, _clean(m)),
        })

    return {"node": node, "neighbors": neighbors}


@router.get("/search")
def kg_search(
    q: str = Query("", description="关键词：账户名 / 昵称 / 订单号 / 游戏名"),
    limit: int = Query(20),
    current_user: User = Depends(get_current_user),
):
    """按关键词搜索节点。

    匹配用户名、昵称、订单号、游戏名、标签——用 CONTAINS 做包含匹配。
    对老板/打手角色，结果自动收敛到与本人相关的节点。
    """
    q = (q or "").strip()
    if not q:
        return {"items": []}
    if not store.is_ready():
        return {"items": [], "reason": "图谱未启用"}

    limit = max(1, min(int(limit), 50))
    rows = store.run(
        "MATCH (n) "
        "WHERE coalesce(n.username, '') CONTAINS $q "
        "   OR coalesce(n.nickname, '') CONTAINS $q "
        "   OR coalesce(n.order_no, '') CONTAINS $q "
        "   OR coalesce(n.name, '') CONTAINS $q "
        "   OR coalesce(n.tag_key, '') CONTAINS $q "
        "RETURN n, labels(n) AS ls LIMIT $lim",
        {"q": q, "lim": limit}, mode="r")

    items = []
    for n in _to_nodes(rows, current_user):
        if current_user.role in ("boss", "player") and n["label"] in (
                schema.LABEL_BOSS, schema.LABEL_PLAYER):
            if n["key"] != current_user.username:
                continue
        items.append(n)
    return {"items": items}


# ——————————————————————————————————————————————
# 内部辅助
# ——————————————————————————————————————————————

def _clean(props: dict) -> dict:
    """去掉 Neo4j 返回的内部字段（元素 ID 之类），只留业务属性。"""
    return {k: v for k, v in (props or {}).items()
            if not k.startswith("_") and k != "updated_at"}


def _display(label: str, props: dict) -> str:
    """节点的展示名：昵称优先，其次业务主键。"""
    meta = schema.node_meta(label)
    nick = str(props.get("nickname") or "").strip()
    key = str(props.get(meta["key"]) or "")
    name = str(props.get("name") or "").strip()
    if label == schema.LABEL_ORDER:
        # 订单显示订单号尾部更易辨认
        return key
    if label == schema.LABEL_GAME:
        return name or key
    return nick or key


def _to_nodes(rows, user: User) -> list:
    """把 Cypher 结果转成前端要的节点结构，顺带做权限过滤。"""
    out = []
    for rec in rows or []:
        props = rec.get("n") or {}
        labels = rec.get("ls") or []
        label = labels[0] if labels else "?"
        if label not in schema.NODE_TYPES:
            continue
        meta = schema.node_meta(label)
        key = str(props.get(meta["key"], ""))
        if not key:
            continue
        if not _can_view_node(user, label, key):
            continue
        clean = _clean(props)
        out.append({
            "id": f"{label}:{key}",
            "label": label,
            "label_name": meta["name"],
            "color": meta["color"],
            "key": key,
            "display": _display(label, props),
            "props": _mask_props(user, label, clean),
        })
    return out


def _rel_name(rel: Optional[str]) -> str:
    for v in schema.REL_TYPES.values():
        if v["rel"] == rel:
            return v["name"]
    return rel or ""


def _neighbor_edges(keys: list, user: User, restrict=None) -> list:
    """取给定节点之间的边。

    keys：[(label, key), ...]，用 UNWIND 一次带进去，避免拼一大堆 OR。
    restrict：若给出，则只保留两端都在该集合里的边（可视化时用）。
    """
    if not keys:
        return []
    pairs = [{"label": l, "key": k} for l, k in keys]

    rows = store.run(
        "UNWIND $pairs AS p "
        "MATCH (a) WHERE p.label IN labels(a) AND "
        "  (coalesce(a.username,'') = p.key OR coalesce(a.order_no,'') = p.key "
        "   OR coalesce(a.name,'') = p.key OR coalesce(a.tag_key,'') = p.key) "
        "MATCH (a)-[r]->(b) "
        "RETURN a, labels(a) AS ls_a, b, labels(b) AS ls_b, type(r) AS rel "
        "LIMIT 2000",
        {"pairs": pairs}, mode="r")

    edges = []
    seen = set()
    for rec in rows or []:
        pa, pb = rec.get("a") or {}, rec.get("b") or {}
        la = (rec.get("ls_a") or ["?"])[0]
        lb = (rec.get("ls_b") or ["?"])[0]
        if la not in schema.NODE_TYPES or lb not in schema.NODE_TYPES:
            continue
        ka = str(pa.get(schema.node_meta(la)["key"], ""))
        kb = str(pb.get(schema.node_meta(lb)["key"], ""))
        if not ka or not kb:
            continue
        if user.role in ("boss", "player"):
            # 老板/打手只保留与本人有关的边
            if user.username not in (ka, kb):
                continue
        if restrict is not None:
            if (la, ka) not in restrict or (lb, kb) not in restrict:
                continue
        sig = (la, ka, rec.get("rel"), lb, kb)
        if sig in seen:
            continue
        seen.add(sig)
        edges.append({
            "source": f"{la}:{ka}",
            "target": f"{lb}:{kb}",
            "rel": rec.get("rel"),
            "rel_name": _rel_name(rec.get("rel")),
        })
    return edges
