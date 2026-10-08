"""
模块4：结果融合（Fusion - 加权 RRF）。

多路召回结果融合，支持加权 RRF（Reciprocal Rank Fusion）：用排名而非原始分数，
统一不同检索器的量纲。在 RAG 流程中的位置：多路召回之后，把向量检索和关键词检索
的结果合并排序。

RRF 公式：score(d) = Σ 1 / (k + rank(d))，k 通常取 60。
加权：不同通道乘以不同权重（FAQ 1.2，文档 1.0）。
"""

from typing import List, Tuple, Dict, Any


class FusionModule:
    """多路结果融合器。

    支持的融合策略：
        - 加权 RRF（当前实现）：用排名计算分数，不同通道乘以不同权重
        - 可扩展：加权融合、简单拼接去重等

    为什么用 RRF 而不是直接加分数：
        - 向量检索分数是 0~1 的余弦相似度，关键词检索分数是 BM25 整数，量纲不同
        - RRF 只用排名（rank），不用原始分数，天然统一量纲
        - 高排名（rank小）的文档贡献大，低排名的贡献趋近于0，鲁棒性好

    使用示例：
        fusion = FusionModule(rrf_k=60, channel_weights={"document":1.0, "faq":1.2})
        ordered, pool = fusion.fuse(all_kw_hits, all_vec_hits)
        # ordered: [(key, rrf_score)] 按 RRF 分数降序
        # pool: {key: {"faq": faq_row, "chunk": chunk_row}}
    """

    def __init__(self, rrf_k: int = 60, channel_weights: dict = None):
        """初始化融合器。

        参数：
            rrf_k: RRF 常数（默认 60，用于平滑，排名靠后的贡献衰减）
            channel_weights: 各通道权重，默认 {"document": 1.0, "faq": 1.2}
                            FAQ 权重更高，因为人工维护的问答库更权威
        """
        self.rrf_k = rrf_k
        self.channel_weights = channel_weights or {"document": 1.0, "faq": 1.2}

    def fuse(self, all_kw_hits: list, all_vec_hits: list) -> Tuple[list, dict]:
        """加权 RRF 融合，返回 (ordered, pool)。

        参数：
            all_kw_hits: 关键词命中列表，每条为 (score, faq_row, query_index, rank)
            all_vec_hits: 向量命中列表，每条为字典：
                {"score", "chunk", "channel", "query_index", "rank_in_query", ...}

        返回：
            ordered: [(key, rrf_score)] 按 RRF 分数降序排列
                     key = (source_type, source_key, chunk_index)
            pool: {key: {"faq": faq_row, "chunk": chunk_row}} 命中对象映射
                  用于后续 ContextBuilder 渲染时获取原始内容
        """
        pool = {}
        ranks = {}

        # 关键词通道（FAQ）的 RRF 贡献
        for _s, r, _qi, rank in all_kw_hits:
            key = ("faq", str(r.id), 0)
            pool.setdefault(key, {})["faq"] = r
            # RRF 贡献 = 1 / (k + rank + 1) × 通道权重
            # +1 是因为 rank 从 0 开始，公式中 rank 从 1 开始
            contribution = 1.0 / (self.rrf_k + rank + 1) * self.channel_weights["faq"]
            ranks[key] = ranks.get(key, 0.0) + contribution

        # 向量通道（文档/FAQ）的 RRF 贡献
        for h in all_vec_hits:
            c = h["chunk"]
            key = (c.source_type, c.source_key, int(c.chunk_index or 0))
            pool.setdefault(key, {})["chunk"] = c
            channel = h.get("channel", c.source_type or "document")
            contribution = (1.0 / (self.rrf_k + h["rank_in_query"] + 1)
                            * self.channel_weights.get(channel, 1.0))
            ranks[key] = ranks.get(key, 0.0) + contribution

        # 按 RRF 分数降序排列
        ordered = sorted(ranks.items(), key=lambda kv: -kv[1])
        return ordered, pool
