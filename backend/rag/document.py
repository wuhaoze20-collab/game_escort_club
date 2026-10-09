"""
RAG 基础数据结构模块。

定义统一的 Document 类，封装向量检索和关键词检索的结果，
便于融合模块统一处理。
"""

from dataclasses import dataclass, field
from typing import Dict, Any


@dataclass
class Document:
    """检索到的文档/片段数据结构。

    统一封装向量检索和关键词检索的结果，便于融合模块处理。

    属性：
        content: 文本内容
        metadata: 附加信息（来源、是否 AutoMerging 等）
        score: 相关性分数（用于排序）
        source_type: 来源类型（document / faq）
        chunk: 原始 ORM 对象（AiChunk 或 AiFaq）
    """
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    source_type: str = ""
    chunk: Any = None

    def __hash__(self):
        """使 Document 可哈希，便于去重"""
        return hash(self.content)
