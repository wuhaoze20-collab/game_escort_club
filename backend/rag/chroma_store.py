"""Chroma 向量存储封装层。

在 RAG 流程中的位置：数据准备阶段（写入向量）+ 推理问答阶段（向量召回）。

改造前：向量以 JSON 字符串存在 MySQL 的 ai_vectors.embedding（TEXT 列），
        检索时把整张表读进内存、逐条 json.loads、用纯 Python 算余弦 —— O(N) 全表扫描。
改造后：向量写入 Chroma（本地持久化 + HNSW 近似最近邻索引），检索走索引召回。

数据分工（重要）：
    · ai_chunks        —— 片段元数据的唯一真相源（标题、角色、父子关系、正文）
    · ai_vectors       —— 保留为备份与回退路径，MySQL 后端仍可读取
    · Chroma           —— 只存「向量 + 用于过滤的最小元数据」，负责快速召回 chunk_id

    这样父母分块 / AutoMerging / 角色过滤 / 通道过滤的既有逻辑全部不用改，
    Chroma 只替换「向量 → 候选片段」这一步，其余仍从 MySQL 读。
"""

import os
from pathlib import Path
from typing import Iterable, Optional

# Chroma 本地持久化目录：backend/chroma_db
_BACKEND_DIR = Path(__file__).resolve().parent.parent
PERSIST_DIR = str(_BACKEND_DIR / "chroma_db")

# 集合名：一个项目一个集合，所有片段（文档子块 / FAQ）都存这里，
# 靠 metadata 里的 source_type / role 做过滤区分通道
COLLECTION_NAME = "ai_chunks"

# 单次写入批量（Chroma 对单次 upsert 的条数较敏感，分批更稳）
WRITE_BATCH = 200

# 进程内单例
_client = None
_collection = None


def available() -> bool:
    """chromadb 是否可导入（未安装时返回 False，调用方据此降级回 MySQL）。

    用 find_spec 探测而不真正 import：既避免无用的导入开销，
    也让「是否安装」这件事可以被静态检查工具看清。
    """
    try:
        import importlib.util
        return importlib.util.find_spec("chromadb") is not None
    except Exception:
        return False


def is_ready() -> bool:
    """集合是否真的可用：能创建 client 并拿到集合对象。

    注意不要退化成「进程内单例是否为 None」——那样在读取的第一个瞬间
    永远返回 False，前端会误报成「Chroma 没启用」。这里让它触发懒加载，
    以「集合能否打开」为判据；打不开（磁盘损坏、版本不兼容等）时返回 False。
    """
    try:
        return _get_collection() is not None
    except Exception:
        return False


def _get_collection():
    """懒加载并返回 Chroma 集合（单例）。

    首次调用时创建 PersistentClient 与集合。
    distance 用 cosine 空间：distance = 1 - 余弦相似度，便于和原实现口径对齐。
    """
    global _client, _collection
    if _collection is not None:
        return _collection

    import chromadb

    os.makedirs(PERSIST_DIR, exist_ok=True)
    _client = chromadb.PersistentClient(path=PERSIST_DIR)
    _collection = _client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    return _collection


def count() -> int:
    """集合内向量条数；不可用时返回 -1。"""
    try:
        return int(_get_collection().count())
    except Exception:
        return -1


def all_ids() -> list:
    """列出集合内全部 id（用于同步时清理已失效的向量）。"""
    col = _get_collection()
    total = col.count()
    if total <= 0:
        return []
    got = col.get(include=[], limit=total)
    return [str(x) for x in (got.get("ids") or [])]


def upsert_rows(ids: Iterable[str], embeddings: list, metadatas: list) -> int:
    """批量写入（存在则覆盖）。返回写入条数。"""
    ids = [str(x) for x in ids]
    if not ids:
        return 0
    col = _get_collection()
    total = 0
    for i in range(0, len(ids), WRITE_BATCH):
        col.upsert(
            ids=ids[i:i + WRITE_BATCH],
            embeddings=embeddings[i:i + WRITE_BATCH],
            metadatas=metadatas[i:i + WRITE_BATCH],
        )
        total += len(ids[i:i + WRITE_BATCH])
    return total


def delete_ids(ids: Iterable[str]) -> int:
    """按 id 批量删除。返回删除条数。"""
    ids = [str(x) for x in ids]
    if not ids:
        return 0
    col = _get_collection()
    col.delete(ids=ids)
    return len(ids)


def clear() -> None:
    """清空集合（删除后重建，用于换 embedding 模型或强制全量重建）。"""
    global _collection
    try:
        if _client is not None:
            _client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    _collection = None
    _get_collection()


def query(embedding: list, n_results: int, where: Optional[dict] = None) -> list:
    """向量召回。

    参数：
        embedding: 查询向量（1024 维，与写入时同一模型）
        n_results: 期望返回条数
        where: Chroma 过滤条件（enabled / role / source_type）

    返回：
        [(chunk_id:int, score:float), ...]，score 为余弦相似度（已由距离换算），
        按相似度降序。集合为空或不可用时返回 []。
    """
    col = _get_collection()
    total = col.count()
    if total <= 0:
        return []

    kwargs = {
        "query_embeddings": [embedding],
        "n_results": max(1, min(int(n_results), total)),
        "include": ["distances"],
    }
    if where:
        kwargs["where"] = where

    res = col.query(**kwargs)
    ids = (res.get("ids") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]

    out = []
    for cid, dist in zip(ids, dists):
        try:
            out.append((int(cid), 1.0 - float(dist)))
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
