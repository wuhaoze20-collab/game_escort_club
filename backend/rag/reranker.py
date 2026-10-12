"""
模块6：检索后优化 —— 重排序（Re-ranking）。

在 FusionModule 融合之后、ContextBuilder 构建上下文之前，对候选片段做二次排序。
为什么需要重排序：
    RRF 融合只用了"排名"信息，丢失了原始相似度分数的绝对值。
    两个片段排名都是第1，但一个相似度 0.9，一个 0.4，RRF 给它们的贡献一样。
    重排序把向量分数、关键词分数、来源类型、标题匹配等多维度信息综合起来，
    让真正相关的内容排到更前面。

重排序策略（规则式，零额外成本，实时计算）：
    综合分 = RRF分(归一化) × 0.4
           + 向量最高相似度 × 0.3
           + 关键词最高分数(归一化) × 0.15
           + 来源类型加成 × 0.1
           + 标题匹配加分 × 0.05

使用示例：
    reranker = Reranker(db)
    reranked = reranker.rerank(ordered, pool, all_vec_hits, all_kw_hits, question)
    # 返回重新排序后的 [(key, score)] 列表
"""

import re
from typing import List, Tuple


class Reranker:
    """检索后重排序器。

    对融合后的候选片段做多维度综合打分，重新排序。
    不调用外部 API，纯规则计算，零成本实时完成。
    """

    def __init__(self, db):
        """初始化重排序器。

        参数：
            db: 数据库会话（用于渲染占位符、获取配置）
        """
        self.db = db

    def rerank(self, ordered: list, pool: dict,
               all_vec_hits: list, all_kw_hits: list,
               question: str, top_k: int = None) -> List[Tuple[tuple, float]]:
        """对融合结果做重排序，返回重新排序后的 [(key, score)] 列表。

        参数：
            ordered: FusionModule 返回的 [(key, rrf_score)] 排序列表
            pool: FusionModule 返回的 {key: {"faq":..., "chunk":...}} 对象映射
            all_vec_hits: 向量检索命中列表（用于提取每个片段的最高向量分数）
            all_kw_hits: 关键词检索命中列表（用于提取每个片段的最高关键词分数）
            question: 用户原始问题（用于标题匹配加分）
            top_k: 只返回前 K 个，None 表示全部返回

        返回：
            重新排序后的 [(key, combined_score)] 列表，按综合分降序。
        """
        if not ordered:
            return []

        question = (question or "").strip()

        # 读取加权公式的系数（管理员可在「RAG 调试 → RAG 参数 → 重排序打分」里调）
        from ai_rag import _rerank_weights
        w = _rerank_weights(self.db)

        # ① 收集每个 key 的最高向量分数和最高关键词分数
        vec_score_by_key = {}
        for h in all_vec_hits:
            c = h.get("chunk")
            if c is None:
                continue
            key = (c.source_type, c.source_key, int(c.chunk_index or 0))
            s = float(h.get("score", 0))
            if key not in vec_score_by_key or s > vec_score_by_key[key]:
                vec_score_by_key[key] = s

        kw_score_by_key = {}
        for _s, r, _qi, _rank in all_kw_hits:
            key = ("faq", str(r.id), 0)
            s = float(_s)
            if key not in kw_score_by_key or s > kw_score_by_key[key]:
                kw_score_by_key[key] = s

        # 图谱通道的"相关度"：GraphRetriever 把实体匹配的可信度放在了 doc.score 里
        # （账户名/订单号命中=1.0，昵称=0.9，游戏名=0.8，标签=0.7）。
        # 这里把它并入 vec_score_by_key —— 它和余弦相似度同为 0~1 的相关度，
        # 语义上可以共用「向量分」这一项权重，不必再单独开一个系数。
        for key, _rrf in ordered:
            g = (pool.get(key) or {}).get("graph")
            if g is None:
                continue
            s = float(getattr(g, "score", 0) or 0)
            if key not in vec_score_by_key or s > vec_score_by_key[key]:
                vec_score_by_key[key] = s

        # ② 归一化 RRF 分数（除以最大值，缩放到 0~1）
        max_rrf = max((score for _, score in ordered), default=1.0)
        if max_rrf <= 0:
            max_rrf = 1.0

        # ③ 归一化关键词分数（BM25 分数范围不定，用最大值归一化）
        max_kw = max(kw_score_by_key.values(), default=1.0)
        if max_kw <= 0:
            max_kw = 1.0

        # ④ 对每个候选项计算综合分
        scored = []
        for key, rrf_score in ordered:
            item = pool.get(key) or {}
            chunk = item.get("chunk")
            faq_row = item.get("faq")

            # RRF 分（归一化到 0~1）
            rrf_norm = rrf_score / max_rrf

            # 向量最高相似度（已经是 0~1）
            vec_score = vec_score_by_key.get(key, 0.0)

            # 关键词最高分数（归一化到 0~1）
            kw_norm = kw_score_by_key.get(key, 0.0) / max_kw

            # 来源类型加成：FAQ 人工维护，更权威（加成分值可在参数里调）
            source_type = key[0] if len(key) > 0 else ""
            source_bonus = w["source_bonus"] if source_type == "faq" else 0.0

            # 标题匹配加分：问题中的关键词出现在标题/问题中
            title_bonus = self._title_match_bonus(
                question, chunk, faq_row)

            # 综合分（加权求和，各项权重见「重排序打分」参数组）
            combined = (
                rrf_norm * w["rrf"]
                + vec_score * w["vec"]
                + kw_norm * w["kw"]
                + source_bonus
                + title_bonus
            )

            scored.append((key, combined))

        # ⑤ 按综合分降序排列
        scored.sort(key=lambda x: -x[1])

        if top_k is not None and top_k > 0:
            scored = scored[:top_k]

        return scored

    def _title_match_bonus(self, question: str, chunk, faq_row) -> float:
        """计算标题匹配加分：问题关键词出现在标题/FAQ问题中时加分。

        参数：
            question: 用户问题
            chunk: AiChunk 对象（文档片段）
            faq_row: AiFaq 对象（问答库条目）

        返回：
            0.0 ~ 0.05 的加分
        """
        if not question:
            return 0.0

        # 提取问题中的关键词（2字以上的中文/英文词）
        keywords = self._extract_keywords(question)
        if not keywords:
            return 0.0

        # 获取标题文本
        title = ""
        if faq_row is not None:
            title = getattr(faq_row, "question", "") or ""
        elif chunk is not None:
            title = getattr(chunk, "title", "") or ""

        if not title:
            return 0.0

        # 统计命中的关键词比例
        hit = sum(1 for kw in keywords if kw in title)
        ratio = hit / len(keywords) if keywords else 0.0
        return ratio * 0.05   # 最多加 0.05

    @staticmethod
    def _extract_keywords(text: str) -> list:
        """从文本中提取简单关键词（2字以上的连续中文字符或英文单词）。

        不依赖 jieba 等分词库，用正则做简单提取，够用即可。
        """
        text = (text or "").strip()
        if not text:
            return []
        # 提取 2~8 字的中文连续片段，或 3 字母以上的英文单词
        cn = re.findall(r"[\u4e00-\u9fa5]{2,8}", text)
        en = re.findall(r"[a-zA-Z]{3,}", text)
        return list(set(cn + en))
