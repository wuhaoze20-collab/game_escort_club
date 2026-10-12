"""
RAG 模块化包。

按照 Modular RAG 架构，把检索增强生成流程拆成可插拔模块：
    1. QueryRewriter    - 查询改写
    2. VectorRetriever  - 向量检索
    3. KeywordRetriever - 关键词检索
    4. GraphRetriever   - 知识图谱检索（关系型问题）
    5. FusionModule     - 结果融合（加权 RRF）
    6. ContextBuilder   - 上下文构建

主类 ModularRAG 负责组装编排，执行完整查询流程。

使用示例：
    from rag import ModularRAG, VectorRetriever, KeywordRetriever
    rag = ModularRAG(db)
    context = rag.query("怎么退款", role="boss")
"""

from .document import Document
from .query_rewriter import QueryRewriter
from .vector_retriever import VectorRetriever
from .keyword_retriever import KeywordRetriever
from .graph_retriever import GraphRetriever
from .fusion import FusionModule
from .reranker import Reranker
from .cross_encoder_reranker import CrossEncoderReranker
from .context_builder import ContextBuilder
from .pipeline import ModularRAG

__all__ = [
    "Document",
    "QueryRewriter",
    "VectorRetriever",
    "KeywordRetriever",
    "GraphRetriever",
    "FusionModule",
    "Reranker",
    "CrossEncoderReranker",
    "ContextBuilder",
    "ModularRAG",
]
