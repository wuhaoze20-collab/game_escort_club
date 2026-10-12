"""
模块4：结果融合（Fusion - 加权 RRF）。

多路召回结果融合，支持加权 RRF（Reciprocal Rank Fusion）：用排名而非原始分数，
统一不同检索器的量纲。在 RAG 流程中的位置：多路召回之后，把向量检索和关键词检索
的结果合并排序。

RRF 公式：score(d) = Σ 1 / (k + rank(d))，k 通常取 60。
加权：不同通道乘以不同权重（FAQ 1.2，文档 1.0）。
"""

from typing import Tuple


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
            channel_weights: 各通道权重，默认带 document / faq / graph 三路
                            FAQ 权重更高，因为人工维护的问答库更权威；
                            图谱权重居中，它只在问题提到具体实体时才有输出
        """
        self.rrf_k = rrf_k
        self.channel_weights = channel_weights or {
            "document": 1.0, "faq": 1.2, "graph": 1.3,
        }

    def fuse(self, all_kw_hits: list, all_vec_hits: list,
             all_graph_hits: list = None) -> Tuple[list, dict]:
        """加权 RRF 融合，返回 (ordered, pool)。

        参数：
            all_kw_hits: 关键词命中列表，每条为 (score, faq_row, query_index, rank)
            all_vec_hits: 向量命中列表，每条为字典：
                {"score", "chunk", "channel", "query_index", "rank_in_query", ...}
            all_graph_hits: 图谱命中列表（Document 对象，source_type="graph"）。
                这一路没有"查询变体"的概念——实体链接是对原始问题做的，
                所以按列表顺序当作排名即可。

        返回：
            ordered: [(key, rrf_score)] 按 RRF 分数降序排列
                     key = (source_type, source_key, chunk_index)
                     图谱的 key 形如 ("graph", <elementId>, 0)
            pool: {key: {"faq": ..., "chunk": ..., "graph": ...}} 命中对象映射
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

        # 图谱通道的 RRF 贡献。
        # 图谱这一路天然不会有"两路撞同一条"的情况（一个节点一条事实），
        # 所以排名直接用列表下标，不需要像向量那样按查询变体分组。
        for rank, doc in enumerate(all_graph_hits or []):
            meta = getattr(doc, "metadata", None) or {}
            node_id = str(meta.get("node_id") or getattr(doc, "content", "")[:24])
            key = ("graph", node_id, 0)
            pool.setdefault(key, {})["graph"] = doc
            contribution = (1.0 / (self.rrf_k + rank + 1)
                            * self.channel_weights.get("graph", 1.0))
            ranks[key] = ranks.get(key, 0.0) + contribution

        # 按 RRF 分数降序排列
        ordered = sorted(ranks.items(), key=lambda kv: -kv[1])
        return ordered, pool
