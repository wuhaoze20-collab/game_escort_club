"""
模块7：检索后优化 —— 语义级重排序（Cross-Encoder / Semantic Reranking）。

与规则式重排序（reranker.py）的区别：
    规则式：RRF分 + 向量分 + 关键词分 + 来源加成，纯加权打分，零成本但不理解语义
    语义级：调用大模型，让模型逐个判断"这段内容能否回答用户的问题"，输出0-1相关性分数
            更精准，但每次检索多1次API调用，增加约1-2秒延迟

工作流程：
    1. 取融合后的 top_n 个候选片段（默认10个，太多会超token）
    2. 构造提示词：问题 + 编号后的候选片段列表
    3. 要求大模型输出 JSON：{"scores": [0.85, 0.3, 0.92, ...]}
    4. 解析分数，按相关性降序重新排序
    5. 取 top_k 个作为最终结果

使用示例：
    reranker = CrossEncoderReranker(db)
    reranked = reranker.rerank(ordered, pool, question, top_k=4)
    # 返回重新排序后的 [(key, semantic_score)] 列表
"""

import json
import re
from typing import List, Tuple

# 图谱事实的保底加成。精确标识符（账户名、订单号）命中给强加成，
# 昵称/游戏名/标签这类模糊命中，以及"本人兜底"命中给弱加成。
_GRAPH_BONUS_STRONG = 0.35
_GRAPH_BONUS_WEAK = 0.15


def _graph_hit_is_strong(pool: dict, key) -> bool:
    """这条候选是不是「精确标识符命中的图谱事实」。

    账户名、订单号是用户在问题里写出来的确定标识，命中就是命中；
    昵称、游戏名、标签只是字面包含，可能碰巧撞上，所以不算强命中。
    """
    g = (pool.get(key) or {}).get("graph")
    if g is None:
        return False
    field = (getattr(g, "metadata", None) or {}).get("match_field")
    return field in ("username", "order_no")


class CrossEncoderReranker:
    """语义级重排序器：用大模型判断候选片段与问题的相关性。"""

    def __init__(self, db):
        self.db = db

    def rerank(self, ordered: list, pool: dict, question: str,
               top_k: int = 4, candidate_limit: int = 10) -> List[Tuple[tuple, float]]:
        """对融合结果做语义级重排序。

        参数：
            ordered: FusionModule 返回的 [(key, rrf_score)] 排序列表
            pool: FusionModule 返回的 {key: {"faq":..., "chunk":...}} 对象映射
            question: 用户原始问题
            top_k: 最终返回前 K 个
            candidate_limit: 送给大模型打分的最大候选数（太多会超token，默认10）

        返回：
            重新排序后的 [(key, semantic_score)] 列表，按语义相关性降序。
            如果大模型调用失败，回退到原始 ordered 顺序（不影响可用性）。
        """
        if not ordered:
            return []

        # 取前 candidate_limit 个候选（太多会超token，也增加延迟）
        candidates = ordered[:candidate_limit]
        if not candidates:
            return []

        # 提取每个候选的文本内容
        items = []
        for idx, (key, _rrf) in enumerate(candidates):
            item = pool.get(key) or {}
            chunk = item.get("chunk")
            faq_row = item.get("faq")
            graph_doc = item.get("graph")
            # 优先用FAQ的问答对，其次文档片段，最后图谱事实
            if faq_row is not None:
                text = f"问：{getattr(faq_row, 'question', '')}\n答：{getattr(faq_row, 'answer', '')}"
            elif chunk is not None:
                title = getattr(chunk, 'title', '') or ''
                content = getattr(chunk, 'content', '') or ''
                text = f"【{title}】\n{content}" if title else content
            elif graph_doc is not None:
                # 图谱事实已经是渲染好的人话了，直接送进大模型判断相关性
                text = getattr(graph_doc, 'content', '') or ''
            else:
                text = ""
            # 截断，避免单条太长
            text = text[:300]
            items.append({"key": key, "text": text, "index": idx})

        # 构造提示词，让大模型批量打分
        prompt = self._build_prompt(question, items)

        # 调用大模型
        try:
            import ai_service
            messages = [
                {"role": "system", "content": "你是一个专业的文本相关性评估专家。请严格按照要求输出JSON，不要输出任何其他内容。"},
                {"role": "user", "content": prompt},
            ]
            result = ai_service.chat(
                messages,
                temperature=0.1,  # 低温，保证打分稳定
                max_tokens=500,   # 只需要输出分数，不需要太长
            )
            if not result.get("ok"):
                print(f"[cross_encoder] 大模型调用失败，回退规则式排序：{result.get('error', '')}")
                return ordered[:top_k]

            scores = self._parse_scores(result["reply"], len(items))
        except Exception as e:
            print(f"[cross_encoder] 语义重排序异常，回退规则式排序：{e}")
            return ordered[:top_k]

        # 按语义分数重新排序
        #
        # 图谱事实额外给一点加成：大模型打分时只看"问题 vs 这段文字"，
        # 而图谱事实是一串订单号、账户名、状态的结构化罗列，字面上跟问题
        # 重合度不高，容易被判成"部分相关"；但它其实是**拿账户名/订单号
        # 精确命中**出来的硬证据，不是相似度猜测。不加这个加成，
        # 「laoban 找过哪些打手」这种问题会被通用条款文档挤到后面去。
        scored = []
        for i, item in enumerate(items):
            score = scores[i] if i < len(scores) else 0.0
            g = (pool.get(item["key"]) or {}).get("graph")
            if g is not None:
                field = (getattr(g, "metadata", None) or {}).get("match_field")
                score += (_GRAPH_BONUS_STRONG if field in ("username", "order_no")
                          else _GRAPH_BONUS_WEAK)
            scored.append((item["key"], score))

        scored.sort(key=lambda x: -x[1])

        # 精确标识符命中的图谱事实直接置顶。
        # 理由同上：账户名/订单号是硬证据，不该被"看起来像"的通用条款文档压住——
        # 上下文预算有限，排第二就可能被截断，用户的问题反而没被回答。
        strong = [it for it in scored if _graph_hit_is_strong(pool, it[0])]
        if strong:
            rest = [it for it in scored if not _graph_hit_is_strong(pool, it[0])]
            scored = strong + rest

        # 记录调试信息
        self._last_scores = [(items[i]["key"], scores[i] if i < len(scores) else 0.0)
                             for i in range(len(items))]

        return scored[:top_k]

    def _build_prompt(self, question: str, items: list) -> str:
        """构造打分提示词。

        给模型看问题和N个候选片段，要求模型输出每个片段的相关性分数。
        """
        parts = [
            f"用户问题：{question}",
            "",
            "下面是若干候选文本片段，请判断每个片段与用户问题的相关性。",
            "评分标准：",
            "- 1.0：完全相关，这段内容直接回答了用户的问题",
            "- 0.7：大部分相关，包含关键信息但可能不够完整",
            "- 0.4：部分相关，提到了相关主题但没有直接回答",
            "- 0.0：完全不相关",
            "",
            "候选片段：",
        ]
        for item in items:
            parts.append(f"[{item['index']}] {item['text']}")
            parts.append("")

        parts.append(f"请输出JSON格式，包含一个scores数组，共{len(items)}个分数，每个分数对应上面的编号。")
        parts.append('示例：{"scores": [0.9, 0.3, 0.75]}')
        parts.append("只输出JSON，不要输出其他内容。")

        return "\n".join(parts)

    def _parse_scores(self, reply: str, expected_count: int) -> List[float]:
        """解析大模型返回的分数。

        尝试多种解析方式：
        1. 直接解析JSON
        2. 从文本中提取JSON块
        3. 用正则提取数字
        4. 全部失败则返回全0.5（中性分）

        关于「分数个数」：模型偶尔会少返回几个（候选多时尤其明显）。
        早先的实现要求 `len(scores) >= expected_count`，只要少一个就整批放弃、
        退化成全 0.5 —— 而全 0.5 排完序等于原序不动，这一轮重排序就白跑了。
        现在改成按数量补足：返回几个就用几个，缺的位置补 0.0（视作未评价）。
        """
        reply = (reply or "").strip()
        if not reply:
            return [0.5] * expected_count

        def _fit(scores) -> List[float]:
            """截到 expected_count 个，不足的补 0.0。"""
            out = []
            for s in scores[:expected_count]:
                try:
                    v = float(s)
                except (TypeError, ValueError):
                    v = 0.0
                out.append(min(1.0, max(0.0, v)))
            if len(out) < expected_count:
                out.extend([0.0] * (expected_count - len(out)))
            return out

        # 方式1：直接解析JSON
        try:
            data = json.loads(reply)
            scores = data.get("scores", [])
            if isinstance(scores, list) and scores:
                return _fit(scores)
        except Exception:
            pass

        # 方式2：提取JSON块（模型可能输出了```json ... ```）
        try:
            match = re.search(r'\{[^{}]*"scores"[^{}]*\}', reply, re.DOTALL)
            if match:
                data = json.loads(match.group())
                scores = data.get("scores", [])
                if isinstance(scores, list) and scores:
                    return _fit(scores)
        except Exception:
            pass

        # 方式3：正则提取所有数字（0-1之间的小数）
        try:
            nums = re.findall(r'0?\.\d+|1\.0|1|0', reply)
            floats = [float(n) for n in nums if 0 <= float(n) <= 1]
            if len(floats) >= expected_count:
                return _fit(floats)
        except Exception:
            pass

        # 全部失败：返回中性分0.5
        print(f"[cross_encoder] 无法解析分数，返回中性分。原始回复：{reply[:100]}")
        return [0.5] * expected_count

    def get_last_scores(self) -> list:
        """获取最近一次重排序的详细分数（用于调试展示）。"""
        return getattr(self, "_last_scores", [])
