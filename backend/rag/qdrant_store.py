"""Qdrant 向量存储封装层。

在 RAG 流程中的位置：数据准备阶段（写入向量）+ 推理问答阶段（向量召回）。

与 chroma_store.py 是**平级**的两个向量库后端，函数名、参数、返回值口径完全一致，
调用方（ai_rag.sync_*、VectorRetriever._hits_from_*）只需换一个 import 即可切换。

为什么两个都留着：
    同一个 embedding 模型、同一个距离度量（cosine）下，两边的召回结果应该高度一致；
    并存之后可以在系统参数里一键切换，对比「召回一致性」与「写入/查询/占用」等工程指标。

运行形态：本地嵌入式模式（QdrantClient(path=...)），数据落磁盘，不需要起服务端。
    注意 Qdrant 本地模式会对持久化目录加进程级文件锁 —— 同一个目录不能被两个进程
    同时打开（例：旧后端进程没退就重开一个会报 already accessed），本模块用进程内单例
    避免同进程重复打开。

数据分工（与 Chroma 完全一致）：
    · ai_chunks  —— 片段元数据的唯一真相源（标题、角色、父子关系、正文）
    · ai_vectors —— 向量在 MySQL 里的备份（换库时可从这里重灌，不必重调 embedding）
    · Qdrant     —— 只存「向量 + 用于过滤的最小 payload」，负责快速召回 chunk_id
"""

import atexit
import os
from pathlib import Path
from typing import Iterable, Optional

# Qdrant 本地持久化目录：backend/qdrant_db
_BACKEND_DIR = Path(__file__).resolve().parent.parent
PERSIST_DIR = str(_BACKEND_DIR / "qdrant_db")

# 集合名：与 Chroma 同名，两边各自独立存放
COLLECTION_NAME = "ai_chunks"

# 单次写入批量
WRITE_BATCH = 200

# 进程内单例
_client = None


def available() -> bool:
    """qdrant_client 是否可导入（未安装时返回 False，调用方据此降级回 MySQL）。

    用 find_spec 探测而不真正 import：既避免无用的导入开销，
    也让「是否安装」这件事可以被静态检查工具看清。
    """
    try:
        import importlib.util
        return importlib.util.find_spec("qdrant_client") is not None
    except Exception:
        return False


def is_ready() -> bool:
    """本地客户端能否正常创建（打不开时返回 False，前端据此提示不可用）。"""
    try:
        return _get_client() is not None
    except Exception:
        return False


def _get_client():
    """懒加载 Qdrant 本地嵌入式客户端（单例）。

    本地模式不做网络连接，所以这里不会因为「服务没起」而失败；
    失败只会来自目录权限或文件锁。
    """
    global _client
    if _client is not None:
        return _client

    from qdrant_client import QdrantClient

    os.makedirs(PERSIST_DIR, exist_ok=True)
    _client = QdrantClient(path=PERSIST_DIR)
    return _client


def _close_client():
    """解释器退出前显式关掉客户端。

    不做这一步时，QdrantClient.__del__ 会在解释器关闭后期才被触发，
    那时 import 机制已经拆掉，会往 stderr 抛一串
    "Exception ignored in ... sys.meta_path is None, Python is likely shutting down" 噪音。
    注册 atexit 后，关闭动作发生在解释器还能正常 import 的阶段。
    """
    global _client
    c = _client
    _client = None
    if c is not None:
        try:
            c.close()
        except Exception:
            pass


atexit.register(_close_client)


def _collection_exists() -> bool:
    """集合是否已建立。老版本没有 collection_exists 时退回列举判断。"""
    c = _get_client()
    try:
        return bool(c.collection_exists(COLLECTION_NAME))
    except Exception:
        try:
            return COLLECTION_NAME in [x.name for x in c.get_collections().collections]
        except Exception:
            return False


def _ensure_collection(dim: int) -> None:
    """确保集合存在，且向量维度与待写入的一致。

    Qdrant 必须在建集合时就固定向量维度（不像 Chroma 能自动推断），
    所以维度从第一批写入的向量里取。已经存在但维度不符时抛错而不是静默重建 ——
    换 embedding 模型属于破坏性操作，交给调用方用 force 显式清空重建。
    """
    from qdrant_client.models import Distance, VectorParams

    c = _get_client()
    dim = int(dim)

    if not _collection_exists():
        c.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )
        return

    try:
        info = c.get_collection(COLLECTION_NAME)
        cur = int(info.config.params.vectors.size)
    except Exception:
        # 结构读不出来（版本差异等）就不拦，交给写入时的真实报错
        return

    if cur != dim:
        raise RuntimeError(
            f"Qdrant 集合向量维度不符（现有 {cur} 维，待写入 {dim} 维）。"
            "换了 embedding 模型时，请勾选「强制重建索引」，或先清空向量库"
        )


def count() -> int:
    """集合内向量条数；不可用时返回 -1。"""
    try:
        c = _get_client()
        if not _collection_exists():
            return 0
        return int(c.count(COLLECTION_NAME).count)
    except Exception:
        return -1


def all_ids() -> list:
    """列出集合内全部 id（用于同步时清理已失效的向量）。"""
    c = _get_client()
    if not _collection_exists():
        return []

    out = []
    offset = None
    while True:
        points, offset = c.scroll(
            collection_name=COLLECTION_NAME,
            limit=1000,
            offset=offset,
            with_payload=False,
            with_vectors=False,
        )
        out.extend(str(p.id) for p in points)
        if offset is None:
            break
    return out


def upsert_rows(ids: Iterable[str], embeddings: list, metadatas: list) -> int:
    """批量写入（存在则覆盖）。返回写入条数。

    point id 直接用 chunk_id（正整数），省掉一层「向量库 id ↔ chunk_id」的映射；
    payload 只放过滤与回溯需要的最小字段。
    """
    from qdrant_client.models import PointStruct

    ids = [str(x) for x in ids]
    if not ids or not embeddings:
        return 0

    _ensure_collection(len(embeddings[0]))

    c = _get_client()
    total = 0
    for i in range(0, len(ids), WRITE_BATCH):
        points = []
        for cid, vec, meta in zip(ids[i:i + WRITE_BATCH],
                                  embeddings[i:i + WRITE_BATCH],
                                  metadatas[i:i + WRITE_BATCH]):
            try:
                pid = int(cid)
            except Exception:
                continue
            if pid <= 0 or not isinstance(vec, list) or not vec:
                continue
            points.append(PointStruct(id=pid, vector=list(vec), payload=dict(meta)))
        if points:
            c.upsert(collection_name=COLLECTION_NAME, points=points)
            total += len(points)
    return total


def delete_ids(ids: Iterable[str]) -> int:
    """按 id 批量删除。返回删除条数。"""
    ids = [str(x) for x in ids]
    if not ids:
        return 0

    c = _get_client()
    if not _collection_exists():
        return 0

    pids = []
    for x in ids:
        try:
            pids.append(int(x))
        except Exception:
            continue
    if not pids:
        return 0

    c.delete(collection_name=COLLECTION_NAME, points_selector=pids)
    return len(pids)


def clear() -> None:
    """清空集合（用于换 embedding 模型或强制全量重建）。

    这里只删集合，不立刻重建 —— 下一次写入会按新维度自动建好。
    """
    try:
        c = _get_client()
        if _collection_exists():
            c.delete_collection(COLLECTION_NAME)
    except Exception:
        pass


def _build_filter(where: Optional[dict]):
    """把 Chroma 风格的过滤条件 dict 转成 Qdrant 的 Filter。

    两个后端共用同一份过滤语义，调用方就不必关心自己用的是谁。支持的结构：

        {"enabled": 1}
        {"source_type": {"$in": ["document", "faq"]}}
        {"$and": [上述若干条]}

    返回 None 表示不加过滤。
    """
    from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchAny

    if not where:
        return None

    must = []

    def _walk(node):
        if not isinstance(node, dict):
            return
        if "$and" in node:
            for sub in (node.get("$and") or []):
                _walk(sub)
            return
        for key, val in node.items():
            if isinstance(val, dict):
                if "$in" in val:
                    opts = list(val.get("$in") or [])
                    if opts:
                        must.append(FieldCondition(key=key, match=MatchAny(any=opts)))
                elif "$eq" in val:
                    must.append(FieldCondition(key=key, match=MatchValue(value=val["$eq"])))
                continue
            must.append(FieldCondition(key=key, match=MatchValue(value=val)))

    _walk(where)
    return Filter(must=must) if must else None


def query(embedding: list, n_results: int, where: Optional[dict] = None) -> list:
    """向量召回。

    参数：
        embedding: 查询向量（1024 维，与写入时同一模型）
        n_results: 期望返回条数
        where: Chroma 风格的过滤条件 dict（见 _build_filter），内部转成 Qdrant Filter

    返回：
        [(chunk_id:int, score:float), ...]，按相似度降序。集合为空或不可用时返回 []。

    口径说明：集合用 COSINE 距离，Qdrant 返回的 score 本身就是余弦相似度
    （不是 distance），与 chroma_store 里 1-distance 的结果一致，
    因此下游的 min_score 阈值可以在两个后端之间直接共用。
    """
    c = _get_client()
    if not _collection_exists():
        return []

    total = count()
    if total <= 0:
        return []

    res = c.query_points(
        collection_name=COLLECTION_NAME,
        query=list(embedding),
        limit=max(1, min(int(n_results), total)),
        query_filter=_build_filter(where),
        with_payload=False,
        with_vectors=False,
    ).points

    out = []
    for p in res:
        try:
            out.append((int(p.id), float(p.score)))
        except Exception:
            continue
    return out


def stats() -> dict:
    """集合适况：条数、持久化目录、磁盘占用、collection 名。"""
    import os as _os

    info = {
        "available": available(),
        "ready": is_ready(),
        "collection": COLLECTION_NAME,
        "path": PERSIST_DIR,
        "count": count(),
        "size_mb": 0.0,
        "error": "",
    }
    try:
        total_bytes = 0
        for root, _dirs, files in _os.walk(PERSIST_DIR):
            for f in files:
                try:
                    total_bytes += _os.path.getsize(_os.path.join(root, f))
                except Exception:
                    continue
        info["size_mb"] = round(total_bytes / 1024 / 1024, 2)
    except Exception as e:
        info["error"] = str(e)
    return info
