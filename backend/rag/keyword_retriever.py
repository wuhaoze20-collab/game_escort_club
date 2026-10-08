"""
模块3：关键词检索（Keyword Retrieval - BM25 风格）。

基于 FAQ 关键词匹配，精确召回人工维护的问答库。
在 RAG 流程中的位置：与向量检索并行的另一路召回，互补语义检索的不足。
"""

from typing import List
from .document import Document


class KeywordRetriever:
    """关键词检索器（BM25 风格）。

    遍历所有启用的 FAQ，用 ai_service._faq_score() 对关键词匹配度打分，
    按分数降序返回。与向量检索互补：向量检索擅长语义相似，关键词检索擅长精确匹配。

    使用示例：
        retriever = KeywordRetriever(db)
        docs = retriever.retrieve("怎么退款", role="boss")
        # 返回：[Document(content="退款流程", score=8.5, chunk=faq_row), ...]
    """

    def __init__(self, db):
        """初始化关键词检索器。

        参数：
            db: 数据库会话
        """
        self.db = db

    def retrieve(self, question: str, role: str, limit: int = 20) -> List[Document]:
        """关键词匹配（只查 FAQ），返回 Document 列表（按分数降序）。

        参数：
            question: 用户提问文本
            role: 当前用户角色，用于过滤受限 FAQ
            limit: 返回最大条数（默认 20）

        返回：
            Document 列表，按 BM25 分数降序。
            Document.metadata 包含：faq_row（原始 AiFaq 对象）
        """
        import ai_service
        from models import AiFaq

        rows = (self.db.query(AiFaq)
                .filter(AiFaq.enabled == 1)
                .filter(AiFaq.role.in_(["", role or ""])).all())
        scored = []
        for r in rows:
            # 复用 ai_service 的 FAQ 打分算法（关键词匹配 + 权重）
            s = ai_service._faq_score(question, ai_service._split_keywords(r.keywords))
            if s > 0:
                scored.append((s, r))
        scored.sort(key=lambda x: (-x[0], x[1].id))
        return [Document(
            content=r.question or "",
            metadata={"faq_row": r},
            score=float(s),
            source_type="faq",
            chunk=r,
        ) for s, r in scored[:limit]]
