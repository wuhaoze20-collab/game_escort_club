"""
模块5：上下文构建（Context Building / Compression）。

把融合后的检索结果格式化为大模型能理解的引用块，
受 top_k 条数和 max_chars 总字符双重限制。
在 RAG 流程中的位置：检索融合之后，生成之前，把原始片段变成 Prompt 的一部分。
"""

from typing import Tuple


class ContextBuilder:
    """上下文构建器。

    把 FusionModule 融合后的结果渲染成大模型能理解的引用块文本。
    渲染格式：
        【知识库检索结果（与用户本轮提问相关，优先按这里的口径回答）】
        · 问：xxx
          答：xxx
        · 【文档标题】
          文档内容...

    受双重限制：
        - top_k：最多注入多少条片段
        - max_chars：注入的总字符数上限（防止超过 LLM 上下文窗口）

    使用示例：
        builder = ContextBuilder(db)
        context, picked_faqs = builder.build(ordered, pool, top_k=4, max_chars=2000)
        # context: 格式化后的引用块文本
        # picked_faqs: 被选中的 FAQ 行列表（用于更新 hit_count）
    """

    def __init__(self, db):
        """初始化上下文构建器。

        参数：
            db: 数据库会话（用于渲染占位符，如 {平台名} → 实际值）
        """
        self.db = db

    def build(self, ordered: list, pool: dict, top_k: int,
              max_chars: int, debug: dict = None) -> Tuple[str, list]:
        """渲染检索结果为上下文文本。

        参数：
            ordered: FusionModule 返回的 [(key, rrf_score)] 排序列表
            pool: FusionModule 返回的 {key: {"faq":..., "chunk":...}} 对象映射
            top_k: 最多注入的片段条数
            max_chars: 注入的总字符数上限（0 或 None 表示不限制）
            debug: 调试信息字典（可选，用于记录注入条数和字符数）

        返回：
            (context_text, picked_faqs)
            context_text: 格式化后的引用块文本，无内容时返回空字符串
            picked_faqs: 被选中的 FAQ 行列表（用于后续更新 hit_count 统计）
        """
        import ai_service

        lines, used, picked_faqs = [], 0, []

        for key, _score in ordered:
            # top_k 条数限制
            if len(lines) >= top_k:
                break
            item = pool.get(key) or {}
            faq_row, chunk = item.get("faq"), item.get("chunk")
            graph_doc = item.get("graph")

            if faq_row is not None:
                # FAQ 格式：问：xxx\n  答：xxx
                text = ("· 问：" + ai_service.render_placeholders(faq_row.question, self.db)
                        + "\n  答：" + ai_service.render_placeholders(faq_row.answer, self.db))
            elif chunk is not None:
                # 文档格式：· 【标题】\n  内容
                text = (f"· 【{chunk.title or '知识库'}】\n  "
                        + ai_service.render_placeholders(chunk.content, self.db))
            elif graph_doc is not None:
                # 图谱格式：GraphRetriever 已经渲染好"主谓宾"列表了，直接用。
                # 这里不再做占位符替换——图谱内容是库里的真实字段值，
                # 没有 {平台名} 这类占位符，硬套 render_placeholders 反而会误伤。
                text = graph_doc.content
            else:
                continue

            # max_chars 字符数限制（第一条不受限制，保证至少有一条）
            if max_chars and lines and used + len(text) > max_chars:
                break
            lines.append(text)
            used += len(text)
            if faq_row is not None:
                picked_faqs.append(faq_row)

        # 调试信息：记录实际注入的条数和字符数
        if debug is not None:
            debug["injected_items"] = len(lines)
            debug["injected_chars"] = used

        if not lines:
            return "", picked_faqs

        return ("【知识库检索结果（与用户本轮提问相关，优先按这里的口径回答）】\n"
                + "\n".join(lines)), picked_faqs
