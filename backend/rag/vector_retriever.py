"""
模块2：向量检索（Vector Retrieval）。

基于千问 embedding（text-embedding-v3，1024维）+ 纯 Python 余弦相似度。
支持父子分块 + AutoMerging（同一章命中子块超50%时返回整章）。
在 RAG 流程中的位置：推理问答阶段的核心检索步骤，语义相似度召回。
"""

from typing import List, Optional
from .document import Document


class VectorRetriever:
    """向量检索器。

    执行流程：
        ① 问题向量化：embed_texts([question]) → 1024维查询向量
        ② 全量扫描：从 ai_vectors 表读所有向量，逐条算余弦相似度
           （片段量级几百~几千条，纯 Python 计算足够快，无需 FAISS 等外部向量库）
        ③ 角色过滤：按用户角色（admin/service/boss/player）过滤受限文档
        ④ AutoMerging：同一父块（整章）下命中的子块超过 50% 时，
           自动替换为父块（返回整章上下文，避免碎片化）
        ⑤ 排序截断：按相似度降序，取 Top-K，过滤低于 min_score 的结果

    使用示例：
        retriever = VectorRetriever(db)
        docs = retriever.retrieve("怎么退款", role="boss", top_k=4)
        # 返回：[Document(content=..., score=0.85, ...), ...]
    """

    def __init__(self, db):
        """初始化向量检索器。

        参数：
            db: 数据库会话
        """
        self.db = db

    def retrieve(self, question: str, role: str, top_k: int = 4,
                 min_score: float = 0.35, source_types=None,
                 automerge: bool = True) -> List[Document]:
        """向量相似度检索，返回 Document 列表（按相似度降序）。

        参数：
            question: 用户提问文本
            role: 当前用户角色，用于过滤受限文档
            top_k: 返回最相关的前 K 条（默认 4）
            min_score: 最低相似度阈值，低于此值的结果被过滤（默认 0.35）
            source_types: 限定检索通道，None=全部；["document"]=仅长文档；["faq"]=仅问答库
                          用于多路召回时各通道独立检索，再在 FusionModule 中 RRF 融合
            automerge: 是否启用 AutoMerging（同一章命中超50%子块时返回整章），默认 True

        返回：
            Document 列表，按相似度降序。
            Document.metadata 包含：
                merged: 是否触发了 AutoMerging（子块→父块）
                hit_ratio: 该父块下命中子块的比例（仅 merged=True 时有意义）

        异常：向量化失败时抛异常，由调用方 ModularRAG 兜底（降级为无 RAG 回答）。
        """
        import json
        from models import AiChunk, AiVector
        # 延迟导入 ai_rag 中的工具函数，避免循环导入
        from ai_rag import embed_texts, _embed_model, _cosine, _AUTOMERGE_RATIO

        question = (question or "").strip()
        if not question:
            return []
        allowed_types = set(source_types) if source_types else None

        # ① 问题向量化
        qv = embed_texts([question], _embed_model(self.db))[0]

        # ② 从 ai_vectors 表读所有向量，关联 ai_chunks 获取元数据
        vec_rows = self.db.query(AiVector).all()
        chunk_ids = [v.chunk_id for v in vec_rows]
        chunks_by_id = {}
        if chunk_ids:
            q = self.db.query(AiChunk).filter(AiChunk.id.in_(chunk_ids))
            if allowed_types:
                q = q.filter(AiChunk.source_type.in_(list(allowed_types)))
            for c in q.all():
                chunks_by_id[c.id] = c

        # 逐条算余弦相似度，分父子块收集
        child_hits = []
        faq_hits = []
        for v in vec_rows:
            chunk = chunks_by_id.get(v.chunk_id)
            if chunk is None or int(chunk.enabled or 0) != 1:
                continue
            if allowed_types and (chunk.source_type or "") not in allowed_types:
                continue
            # ③ 角色过滤
            if (chunk.role or "") not in ("", role or ""):
                continue
            try:
                vec = json.loads(v.embedding)
            except Exception:
                continue
            if not isinstance(vec, list) or len(vec) != len(qv):
                continue
            score = _cosine(qv, vec)
            if score >= min_score:
                if chunk.parent_id:
                    child_hits.append((round(score, 4), chunk))
                else:
                    faq_hits.append((round(score, 4), chunk))

        child_hits.sort(key=lambda x: -x[0])
        faq_hits.sort(key=lambda x: -x[0])

        # ④ AutoMerging：统计每个父块下子块总数与命中数
        all_children = (self.db.query(AiChunk)
                        .filter(AiChunk.enabled == 1)
                        .filter(AiChunk.parent_id.isnot(None)).all())
        child_count_by_parent = {}
        for c in all_children:
            child_count_by_parent[c.parent_id] = child_count_by_parent.get(c.parent_id, 0) + 1

        parent_hits = {}
        for score, child in child_hits:
            pid = child.parent_id
            if pid not in parent_hits:
                parent_hits[pid] = {"max_score": score, "hit_count": 0}
            parent_hits[pid]["max_score"] = max(parent_hits[pid]["max_score"], score)
            parent_hits[pid]["hit_count"] += 1

        parent_rows = {}
        if parent_hits:
            for pr in self.db.query(AiChunk).filter(AiChunk.id.in_(list(parent_hits.keys()))).all():
                parent_rows[pr.id] = pr

        # 组装结果
        results = []
        if automerge:
            # AutoMerging 开启：命中子块时返回父块（整章），保证上下文完整
            for pid, info in parent_hits.items():
                total = child_count_by_parent.get(pid, 1)
                ratio = info["hit_count"] / total if total > 0 else 0
                parent_row = parent_rows.get(pid)
                if parent_row:
                    results.append(Document(
                        content=parent_row.content or "",
                        metadata={"merged": ratio >= _AUTOMERGE_RATIO,
                                  "hit_ratio": round(ratio, 2)},
                        score=info["max_score"],
                        source_type=parent_row.source_type or "document",
                        chunk=parent_row,
                    ))
        else:
            # AutoMerging 关闭：直接返回命中的子块（不合并为整章）
            for score, child in child_hits:
                results.append(Document(
                    content=child.content or "",
                    metadata={"merged": False, "hit_ratio": 0.0},
                    score=score,
                    source_type=child.source_type or "document",
                    chunk=child,
                ))

        for score, faq in faq_hits:
            results.append(Document(
                content=faq.content or "",
                metadata={"merged": False, "hit_ratio": 1.0},
                score=score,
                source_type=faq.source_type or "faq",
                chunk=faq,
            ))

        # ⑤ 排序截断
        results.sort(key=lambda x: -x.score)
        return results[:max(1, int(top_k))]
