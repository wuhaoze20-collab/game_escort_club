"""
模块1：查询改写（Query Rewriting）。

封装 query_optimizer，支持查询扩展、分解、后退提示、HyDE、多查询生成等技术。
在 RAG 流程中的位置：检索前的预处理，把用户原始问题变成多个更易检索的查询变体。
"""

from typing import List, Dict


class QueryRewriter:
    """查询改写器。

    对用户原始问题进行查询优化，生成多个查询变体，提高召回率。
    支持的优化技术（在 query_optimizer.py 中实现）：
        - rewrite: 查询改写（同义替换、角度变换）
        - decompose: 子查询分解（复杂问题拆成子问题）
        - stepback: 后退提示（先问更基础的问题）
        - expand: 查询扩展（增加关键词）
        - hyde: 假设性文档嵌入（先生成假设答案再检索）

    使用示例：
        rewriter = QueryRewriter(db)
        queries = rewriter.rewrite("怎么退款")
        # 返回：[{"query":"怎么退款","type":"original"},
        #        {"query":"退款流程是什么","type":"rewrite"}]
    """

    def __init__(self, db):
        """初始化查询改写器。

        参数：
            db: 数据库会话（用于读取系统参数中的优化开关）
        """
        self.db = db

    def rewrite(self, question: str, debug: dict = None) -> List[Dict]:
        """对原始问题进行查询优化，返回查询变体列表。

        参数：
            question: 用户原始问题
            debug: 调试信息字典（可选，用于记录优化过程）

        返回：
            查询变体列表，每个元素为：
                {"query": str, "type": str, "channels": list}
            type 取值：original / rewrite / decompose / stepback / expand / hyde
            channels：该查询适用的检索通道（["keyword"] / ["vector"] / ["keyword","vector"]）
        """
        import query_optimizer
        queries = query_optimizer.generate_queries(self.db, question, debug)
        if not queries:
            queries = [{"query": question, "type": "original"}]
        return queries
