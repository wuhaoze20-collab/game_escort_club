# -*- coding: utf-8 -*-
"""生成 02-AdvancedRAG全景图.drawio（**只有 1 页**：四层级从左到右一张大图）。

层级划分（四个竖带 group）：
  层级1 · 检索前优化   backend/query_optimizer.py、backend/rag/query_rewriter.py
  层级2 · 检索中优化   backend/rag/vector_retriever.py、keyword_retriever.py、
                       graph_retriever.py、fusion.py
  层级3 · 检索后优化   backend/rag/reranker.py、cross_encoder_reranker.py、context_builder.py
  层级4 · 量化评估     backend/rag_eval.py

代码依据（每个节点、每条箭头都能在代码里找到出处）：
  backend/api/ai_api.py          —— AI 对话接口：Self-RAG 检索前判断（ai_self_rag_enabled /
                                    ai_self_rag_retrieve_check）、生成后回答验证
                                    （ai_self_rag_verify_answer）
  backend/ai_service.py          —— build_system_prompt()：ai_rag_enabled 决定走
                                    ai_rag.build_rag_context() 还是 build_faq_context()；chat()
  backend/ai_rag.py              —— build_rag_context() 兼容层；参数读取 _top_k / _min_score /
                                    _max_chars / _keyword_limit / _rrf_k / _channel_weights /
                                    _graph_limit / _rerank_weights
  backend/rag/pipeline.py        —— ModularRAG.query() 的 ①~⑥ 步（含 ④.5 Self-RAG 相关性过滤）
  backend/query_optimizer.py     —— rewrite_query / decompose_query / step_back_query /
                                    expand_query / hyde_document / generate_queries
  backend/rag/query_rewriter.py  —— QueryRewriter.rewrite()
  backend/rag/vector_retriever.py、keyword_retriever.py、graph_retriever.py、fusion.py
  backend/rag/reranker.py、cross_encoder_reranker.py、context_builder.py
  backend/rag_eval.py            —— evaluate_rag() 与 Context Precision / Context Recall /
                                    端到端相似度 / Faithfulness / Answer Relevancy
  backend/api/ai_rag_api.py      —— /api/ai/kb/eval/* 评估接口、_stratified_sample() 分层抽样
                                    （POST /eval/fixed-set、POST /eval/run、GET /eval/compare 等）
  backend/config_service.py      —— CONFIG_META 里各开关的出厂默认值
  backend/models.py              —— ai_eval_history / ai_eval_questions / ai_eval_fixed_set

版面说明（避免连线穿框的做法，因为 drawio_kit 不支持折点）：
  · 每个竖带 = 节点列(260) + 走线通道(60) + 便签列(310)；竖带之间留 80 px 通道，
    竖向跨带的连线走「竖带之间的空白通道」，所以不会穿到别的节点/便签上。
  · 每个竖带最后一行是「满宽行」（节点横跨两列、便签放在节点下方），
    这样它出边的锚点在便签列右侧，跨带连线就只经过空白通道。
  · 同一列里的跳行连线（例如「三路开关 → 关键词召回」）锚在列的左/右边缘，
    竖向走线贴着列边界的空白处。
  · 行高由 drawio_kit.auto_height() 实算，所以文字不会超框，行距 40 px 也不会重叠。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from drawio_kit import Page, write_drawio, auto_height, FS  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "02-AdvancedRAG全景图.drawio")

# ——————————————————————————————————————————————
# 版面常量（px）
# ——————————————————————————————————————————————
BAND_Y = 120          # 四个竖带的顶边
Y0 = 200              # 每个竖带里第一行的 y（给分区标题留足 2 行的高度）
GAP = 40              # 行间距（>=30 的要求）
NODE_W = 260          # 竖带里节点列宽
NOTE_W = 310          # 竖带里便签列宽
CHANNEL = 60          # 节点列与便签列之间的走线通道
BAND_W = 30 + NODE_W + CHANNEL + NOTE_W + 30      # = 690
WIDE_W = NODE_W + CHANNEL + NOTE_W                # 满宽行的宽度 = 630
NOTE_DY = 20          # 满宽行里「便签在节点下方」的间距

RED_FILL, RED_STROKE = "#F8CECC", "#B85450"


def h_of(text, w, kind="process"):
    """和 drawio_kit.node() 一致的高度估算（保证不超框）。"""
    pad = 30 if kind == "io" else 18
    return auto_height(text, w, FS, pad=pad)


def place_rows(specs, x_node, w_node, x_note=None, w_note=NOTE_W,
               y0=Y0, gap=GAP):
    """把一行行（节点 + 便签）竖向排开。spec["wide"]=True 表示满宽行（便签在下方）。"""
    placed = []
    y = y0
    for s in specs:
        if s.get("wide"):
            hn = h_of(s["text"], WIDE_W, s.get("kind", "process"))
            ht = h_of(s["note"], WIDE_W) if s.get("note") else 0
            placed.append((s, y, hn, ht, True))
            y += hn + (NOTE_DY + ht if ht else 0) + gap
        elif s.get("in_note_col"):
            # 放在「便签列」里的节点（本行节点列留空）：让分支线从列边绕行，不从中间纵穿
            ht = h_of(s["text"], w_note, s.get("kind", "process"))
            placed.append((s, y, 0, ht, False))
            y += max(ht, 44) + gap
        else:
            hn = h_of(s["text"], w_node, s.get("kind", "process"))
            ht = h_of(s["note"], w_note) if s.get("note") else 0
            placed.append((s, y, hn, ht, False))
            y += max(hn, ht, 44) + gap
    return placed, y - gap


# ——————————————————————————————————————————————
# 内容定义
# ——————————————————————————————————————————————

# —— 入口列（AI 对话接口 → 是否启用 Advanced 链路）——
ENTRY_SPECS = [
    # 注意：drawio_kit 的连线 id 是 e1、e2…，所以节点 id 不能用 e+数字，否则 id 重复
    {"id": "en0", "kind": "start",
     "text": "用户查询进入\nAI 对话接口：role 角色 + username 账户名"},
    {"id": "en1", "kind": "decision",
     "text": "Self-RAG 判断：本轮是否需要检索？\n"
             "ai_self_rag_enabled\n+ ai_self_rag_retrieve_check"},
    {"id": "en2", "kind": "end", "fill": RED_FILL, "stroke": RED_STROKE,
     "text": "否 → 跳过知识库检索\n直接回答（省 embedding 调用）"},
    {"id": "en3", "kind": "decision",
     "text": "ai_rag_enabled ?"},
    {"id": "en4", "kind": "end", "fill": RED_FILL, "stroke": RED_STROKE,
     "text": "关 → build_faq_context()\n只按关键词匹配问答库\n（绕过本图整条链路）"},
    {"id": "en5", "kind": "note",
     "text": "username 的用途\n"
             "图谱通道靠它把老板/打手的可见范围\n"
             "收敛到本人；评估时按题目角色取\n"
             "该角色的第一个真实账户"},
]

# —— 层级1 · 检索前优化 ——
L1_SPECS = [
    {"id": "l1_gate", "kind": "decision",
     "text": "rag_module_query_rewrite = ?",
     "note": "开 → QueryRewriter.rewrite() 调 query_optimizer.generate_queries()，"
             "产出多个查询变体\n"
             "关 → queries = [{query: 原问题, type: original}]，绕过整个查询优化器"},
    {"id": "l1_sum", "kind": "process",
     "text": "generate_queries() 汇总查询变体",
     "note": "返回 [{query, type, channels}]，按 query 文本去重；原问题始终保留\n"
             "type 取值：original / rewritten / subquery / stepback / expanded / hyde\n"
             "HyDE 只走向量通道（channels 仅 vector）\n"
             "子问题数上限 ai_query_max_sub（未在 CONFIG_META 注册，代码兜底 3，范围 1~5）"},
    {"id": "l1_rw", "kind": "process",
     "text": "① 查询重写 rewrite_query()",
     "note": "开关 ai_query_rewrite_enabled（出厂默认 False）\n"
             "开 → 调大模型把口语化问题改写成标准检索查询，type = rewritten\n"
             "关 → 返回原问题，不产生改写变体（省一次大模型调用）"},
    {"id": "l1_dc", "kind": "process",
     "text": "② 子查询分解 decompose_query()",
     "note": "开关 ai_query_decompose_enabled（出厂默认 False）\n"
             "开 → 基于「改写后的问题」拆成多个子问题（每行一个，上限 ai_query_max_sub），"
             "type = subquery\n"
             "关 → 返回 [原问题]，不产生子查询"},
    {"id": "l1_sb", "kind": "process",
     "text": "③ 后退提示 step_back_query()",
     "note": "开关 ai_query_stepback_enabled（出厂默认 False）\n"
             "开 → 生成更抽象的后退问题以取回背景规则，type = stepback\n"
             "关 → 返回空字符串，不追加该变体"},
    {"id": "l1_ex", "kind": "process",
     "text": "④ 查询扩展 expand_query()",
     "note": "开关 ai_query_expand_enabled（出厂默认 False）\n"
             "开 → 原问题 + 补充同义词关键词，type = expanded（关键词与向量两通道都用）\n"
             "关 → 返回空字符串，不追加"},
    # ↓ 竖带最后一行做成满宽行：出边锚点在便签列右侧，跨带连线只走空白通道
    {"id": "l1_hy", "kind": "process", "wide": True,
     "text": "⑤ HyDE 假设文档 hyde_document()",
     "note": "开关 ai_query_hyde_enabled（出厂默认 False）　"
             "开 → 先生成假设答案，再用答案措辞走向量检索，type = hyde（仅向量通道）　"
             "关 → 返回空字符串，不追加"},
]

# —— 层级2 · 检索中优化 ——
L2_SPECS = [
    {"id": "l2_gate", "kind": "decision",
     "text": "rag_module_* 三路召回开关",
     "note": "rag_module_vector_retrieval / rag_module_keyword_retrieval / "
             "rag_module_graph_retrieval（出厂默认均 True）\n"
             "关某一路 → 该路本轮不参与召回，其余照常；\n"
             "每个查询变体再按自身 channels 决定走哪几路"},
    {"id": "l2_vec", "kind": "process",
     "text": "向量检索 VectorRetriever",
     "note": "参数 rag_vector_backend（默认 chroma，可选 qdrant / mysql）"
             "+ rag_chroma_candidates（默认 50，两个向量库共用）"
             "+ ai_rag_min_score（默认 0.35，低于此分的候选被丢弃）\n"
             "开 → 问题向量化后查 HNSW 索引；document / image / faq 三通道各自独立召回\n"
             "兜底：向量库异常自动回退 MySQL 全表扫描 _hits_from_mysql()"},
    {"id": "l2_am", "kind": "process",
     "text": "AutoMerging 父子块合并（在向量检索内）",
     "note": "参数 rag_module_automerge（出厂默认 True）+ rag_automerge_ratio（默认 0.5）\n"
             "开 → 同一父块（整章）命中子块占比达标时改返回整章，保证上下文完整\n"
             "关 → 直接返回命中的子块片段"},
    {"id": "l2_kw", "kind": "process",
     "text": "关键词检索 KeywordRetriever",
     "note": "参数 rag_keyword_limit（默认 20）\n"
             "开 → 遍历启用 FAQ，用 ai_service._faq_score() 打分，返回 FAQ BM25 风格精确匹配\n"
             "关 → 跳过该通道，只用其余几路"},
    {"id": "l2_gr", "kind": "process",
     "text": "图谱检索 GraphRetriever",
     "note": "参数 rag_graph_limit（默认 3）；还需图谱可用（kg_enabled 默认 True 且 Neo4j 连得上）\n"
             "开 → 实体链接（账户名 / 订单号 / 昵称 / 游戏名 / 标签）→ 取一跳邻域 → 渲染事实；"
             "只吃原始问题，不跟查询变体分裂\n"
             "关 / 未命中 → 返回空列表，不抛异常（RAG 少了这一路照样能答）"},
    {"id": "l2_check", "kind": "decision",
     "text": "三路结果是否全空？",
     "note": "依据 backend/rag/pipeline.py：三路命中全空时\n"
             "直接返回空字符串，不注入任何参考资料"},
    # ↓ 这一行的「节点列」故意留空：把「是」分支的终点放到便签列，
    #   这样「否 → 融合」那条件线从节点列中间的空档下行，不会纵穿它
    {"id": "l2_empty", "kind": "end", "in_note_col": True,
     "fill": RED_FILL, "stroke": RED_STROKE,
     "text": "返回空字符串\n（不注入参考资料）"},
    # ↓ 满宽行
    {"id": "l2_fusion", "kind": "process", "wide": True,
     "text": "加权 RRF 融合 FusionModule.fuse()",
     "note": "参数 rag_rrf_k（默认 60）+ 通道权重 rag_weight_document 1.0 / image 1.1 / "
             "faq 1.2 / graph 1.3　｜　"
             "开（rag_module_fusion）→ 用排名算 RRF 分再乘通道权重，多路合并去重，输出 ordered + pool　｜　"
             "关 → _simple_merge()：图谱 → 向量 → 关键词直接拼接，不做 RRF 排序"},
]

# —— 层级3 · 检索后优化 ——
L3_SPECS = [
    {"id": "l3_gate", "kind": "decision",
     "text": "rag_module_rerank = ?",
     "note": "开 → 进入检索后重排序，模式由 rag_rerank_mode 决定（rule / semantic，默认 rule）\n"
             "关 → final_ordered = ordered，rerank_type = off（直接用 RRF 融合结果）"},
    {"id": "l3_rule", "kind": "process",
     "text": "Reranker（规则式）",
     "note": "rag_rerank_mode = rule（出厂默认）\n"
             "综合分 = RRF 归一化分 × rag_rerank_weight_rrf(0.4) + 向量最高分 × "
             "rag_rerank_weight_vec(0.3) + 关键词归一化分 × rag_rerank_weight_kw(0.15) + "
             "FAQ 来源加成 rag_rerank_source_bonus(0.1) + 标题匹配加分（最多 0.05）\n"
             "不调外部 API，纯规则实时计算"},
    {"id": "l3_sem", "kind": "process",
     "text": "CrossEncoderReranker（语义级）",
     "note": "rag_rerank_mode = semantic\n"
             "取前 rag_rerank_candidate_limit（默认 10）条候选，调大模型逐条打相关性分；"
             "账户名 / 订单号精确命中的图谱事实直接置顶\n"
             "大模型调用失败 → 回退 ordered[:top_k]，不影响可用性"},
    {"id": "l3_selfrag", "kind": "decision",
     "text": "ai_self_rag_enabled 且\nai_self_rag_relevance_filter ?",
     "note": "依据 backend/rag/pipeline.py ④.5 段\n"
             "开 → ai_service.self_rag_filter_relevance() 对片段打 1~5 分，"
             "低于 ai_self_rag_relevance_threshold（默认 3）的被过滤\n"
             "关 → 保留重排序结果，不做相关性过滤"},
    # ↓ 满宽行
    {"id": "l3_ctx", "kind": "process", "wide": True,
     "text": "上下文构建 ContextBuilder.build()",
     "note": "参数 ai_rag_top_k（默认 4，注入条数上限）+ ai_rag_max_chars（默认 3000，注入总字数上限）　｜　"
             "按 top_k 条数与 max_chars 字数双重截断，渲染引用块（FAQ / 文档 / 图谱三种格式）　｜　"
             "被选中的 FAQ 命中次数 hit_count + 1"},
]

# —— 生成列（上下文构建之后）——
GEN_SPECS = [
    {"id": "g1", "kind": "external",
     "text": "ai_service.chat() 拼装 Prompt\n（系统提示词 + 检索上下文 + 历史对话）"},
    {"id": "g2", "kind": "external",
     "text": "千问大模型生成答案"},
    {"id": "g3", "kind": "decision",
     "text": "ai_self_rag_enabled\n+ ai_self_rag_verify_answer ?"},
    {"id": "g4", "kind": "process",
     "text": "self_rag_verify_answer()\n校验回答是否被知识库支持\n不支持则标记 issues"},
    {"id": "g5", "kind": "end",
     "text": "返回答案\nFAQ 命中次数 + 1"},
]

# —— 层级4 · 量化评估（完整闭环）——
L4_SPECS = [
    {"id": "l4_fixed", "kind": "start",
     "text": "① 固定题集分层抽样\nPOST /api/ai/kb/eval/fixed-set",
     "note": "参数 sample_size 默认 10\n"
             "_stratified_sample()：题型保底（fact / reason / compare 各至少 1 道）→ "
             "角色保底（每个角色至少 1 道）→ 剩余名额按真实会话分布配额"
             "（_real_role_weights；真实样本 < MIN_ROLE_SAMPLES=10 则退回均匀分配）\n"
             "抽一次即固定并递增版本，写入 ai_eval_fixed_set（历史版本保留）"},
    {"id": "l4_run", "kind": "process",
     "text": "② 逐题跑「检索 + 生成」\nPOST /api/ai/kb/eval/run",
     "note": "role = random 时用固定题集，role = all / 空 时用全部启用题目\n"
             "每题按自己的 role 走同一条链路：ModularRAG.query() + ai_service.chat()"
             "（temperature = 0.0，结果可复现）\n"
             "图谱通道按题目角色取该角色的第一个真实账户作为 username"},
    {"id": "l4_score", "kind": "process",
     "text": "③ 多指标打分\nrag_eval.evaluate_rag()",
     "note": "Context Precision（相关片段占比，阈值 0.65）+ Context Recall"
             "（标准答案句子被覆盖比例，阈值 0.65）\n"
             "端到端：avg_similarity + Faithfulness + Answer Relevancy\n"
             "语义模型 BAAI/bge-small-zh-v1.5（本地无缓存时回退千问 embedding API）"},
    {"id": "l4_ab", "kind": "process",
     "text": "④ A/B 对比\nGET /api/ai/kb/eval/compare?a=&b=",
     "note": "对比两次评估的 5 个指标（检索精确率 / 检索召回率 / 端到端相似度 / 忠实度 / "
             "答案相关性）及差值（B − A），并按 id 自动排序（旧的为 A）\n"
             "结果带 config_snapshot —— 取 CONFIG_META 中「AI 知识库 / RAG 模块开关 / "
             "查询优化 / Self-RAG」分组的参数快照"},
    {"id": "l4_hist", "kind": "data",
     "text": "⑤ 历史留档\nai_eval_history、ai_eval_questions、ai_eval_fixed_set",
     "note": "GET /eval/history、GET /eval/history/{eval_id}、GET /eval/last\n"
             "每次评估自动写入 ai_eval_history（含 question_ids、fixed_set_version、"
             "config_snapshot、逐题明细）"},
    {"id": "l4_feedback", "kind": "process",
     "text": "⑥ 诊断结论回灌系统参数\n（依据 compare 的 diff 与 better）",
     "note": "把得分低的环节定位到对应开关（如 Recall 低 → ai_query_rewrite_enabled / "
             "rag_module_graph_retrieval；Precision 低 → ai_rag_min_score / "
             "rag_rerank_source_bonus），改完再抽题 → 再评估，闭环回到第①步\n"
             "这些开关都由 backend/config_service.py 的 CONFIG_META 定义；"
             "ModularRAG 每次查询都重新实例化，读到的即最新参数 —— 改完下一轮生效"},
]

# ——————————————————————————————————————————————
# 版面计算
# ——————————————————————————————————————————————
L1_X, L2_X, L3_X, L4_X = 360, 1130, 1900, 3050
ENTRY_X, ENTRY_W = 40, 280
GEN_X, GEN_W = 2670, 300

entry_rows, entry_bottom = place_rows(ENTRY_SPECS, ENTRY_X, ENTRY_W)
gen_rows, gen_bottom = place_rows(GEN_SPECS, GEN_X, GEN_W)


def band_rows(specs, bx):
    return place_rows(specs, bx + 30, NODE_W, bx + 30 + NODE_W + CHANNEL, NOTE_W)


l1_rows, l1_bottom = band_rows(L1_SPECS, L1_X)
l2_rows, l2_bottom = band_rows(L2_SPECS, L2_X)
l3_rows, l3_bottom = band_rows(L3_SPECS, L3_X)
l4_rows, l4_bottom = band_rows(L4_SPECS, L4_X)

BAND_BOTTOM = max(l1_bottom, l2_bottom, l3_bottom, l4_bottom) + 40
BAND_H = ((BAND_BOTTOM - BAND_Y) // 10 + 1) * 10
FOOTER_Y = BAND_Y + BAND_H + 40

# ——————————————————————————————————————————————
# 画图
# ——————————————————————————————————————————————
p = Page("02 Advanced RAG 全景图（四层级单页）")

p.label("title",
        "Advanced RAG 全景图（单页 · 从左到右贯穿四个层级）｜ "
        "依据 backend/rag/pipeline.py、backend/query_optimizer.py、backend/rag/*.py、"
        "backend/rag_eval.py、backend/api/ai_rag_api.py、backend/config_service.py",
        40, 16, 3520, 40, bold=True)


def draw_rows(rows, x_node, w_node, x_note, w_note):
    for spec, y, hn, ht, is_wide in rows:
        if is_wide:
            p.node(spec["id"], spec["text"], x_node, y, WIDE_W, hn,
                   kind=spec.get("kind", "process"),
                   fill=spec.get("fill"), stroke=spec.get("stroke"))
            if spec.get("note"):
                p.node(spec["id"] + "_n", spec["note"], x_node, y + hn + NOTE_DY,
                       WIDE_W, ht, kind="note")
            continue
        if spec.get("in_note_col"):
            p.node(spec["id"], spec["text"], x_note, y, w_note, ht,
                   kind=spec.get("kind", "process"),
                   fill=spec.get("fill"), stroke=spec.get("stroke"))
            continue
        p.node(spec["id"], spec["text"], x_node, y, w_node, hn,
               kind=spec.get("kind", "process"),
               fill=spec.get("fill"), stroke=spec.get("stroke"))
        if spec.get("note"):
            p.node(spec["id"] + "_n", spec["note"], x_note, y, w_note, ht, kind="note")


DOWN = dict(exit_x=0.5, exit_y=1.0, entry_x=0.5, entry_y=0.0)      # 同列上下相接
RIGHT = dict(exit_x=1.0, exit_y=0.5, entry_x=1.0, entry_y=0.5)     # 贴列右缘跳行
LEFT = dict(exit_x=0.0, exit_y=0.5, entry_x=0.0, entry_y=0.5)      # 贴列左缘跳行
CROSS = dict(exit_x=1.0, exit_y=0.5, entry_x=0.0, entry_y=0.5)     # 竖向跨带（走带间通道）

# —— 四个竖带（先画底框，再画框内节点，节点才压在框上面）——
p.group("g_l1", "层级1 · 检索前优化 ｜ backend/query_optimizer.py、"
                "backend/rag/query_rewriter.py",
        L1_X, BAND_Y, BAND_W, BAND_H)
draw_rows(l1_rows, L1_X + 30, NODE_W, L1_X + 30 + NODE_W + CHANNEL, NOTE_W)

p.group("g_l2", "层级2 · 检索中优化 ｜ backend/rag/vector_retriever.py、keyword_retriever.py、"
                "graph_retriever.py、fusion.py",
        L2_X, BAND_Y, BAND_W, BAND_H)
draw_rows(l2_rows, L2_X + 30, NODE_W, L2_X + 30 + NODE_W + CHANNEL, NOTE_W)

p.group("g_l3", "层级3 · 检索后优化 ｜ backend/rag/reranker.py、"
                "cross_encoder_reranker.py、context_builder.py",
        L3_X, BAND_Y, BAND_W, BAND_H)
draw_rows(l3_rows, L3_X + 30, NODE_W, L3_X + 30 + NODE_W + CHANNEL, NOTE_W)

p.group("g_l4", "层级4 · 量化评估 ｜ backend/rag_eval.py",
        L4_X, BAND_Y, BAND_W, BAND_H)
draw_rows(l4_rows, L4_X + 30, NODE_W, L4_X + 30 + NODE_W + CHANNEL, NOTE_W)

# —— 入口列 / 生成列（不在四个竖带内）——
draw_rows(entry_rows, ENTRY_X, ENTRY_W, None, NOTE_W)
draw_rows(gen_rows, GEN_X, GEN_W, None, NOTE_W)

# —— 入口链路 ——
p.edge("en0", "en1", **DOWN)
p.edge("en1", "en2", "否（跳过检索）", **DOWN)
p.edge("en1", "en3", "是 / 未开启", **LEFT)
p.edge("en3", "en4", "关", **DOWN)
p.edge("en3", "l1_gate", "开 → ModularRAG.query()", **CROSS)

# —— 层级1 链路 ——
p.edge("l1_gate", "l1_sum", **DOWN)
p.edge("l1_sum", "l1_rw", **DOWN)
p.edge("l1_rw", "l1_dc", **DOWN)
p.edge("l1_dc", "l1_sb", **DOWN)
p.edge("l1_sb", "l1_ex", **DOWN)
p.edge("l1_ex", "l1_hy", **DOWN)
p.edge("l1_hy", "l2_gate", "查询变体列表 queries", **CROSS)

# —— 层级2 链路（多路召回 + 融合）——
p.edge("l2_gate", "l2_vec", **DOWN)
p.edge("l2_gate", "l2_kw", "关键词通道", **RIGHT)
p.edge("l2_gate", "l2_gr", "图谱通道", **RIGHT)
p.edge("l2_vec", "l2_am", "命中子块", **DOWN)
p.edge("l2_am", "l2_check", **RIGHT)
p.edge("l2_kw", "l2_check", **RIGHT)
p.edge("l2_gr", "l2_check", **DOWN)
# 「是」分支的终点在便签列 → 从 check 右侧出、绕节点列右缘下行，再左入终点左边
p.edge("l2_check", "l2_empty", "是", exit_x=1.0, exit_y=0.5, entry_x=0.0, entry_y=0.5)
# 「否」分支走节点列中间的空档，不碰任何节点
p.edge("l2_check", "l2_fusion", "否", **DOWN)
p.edge("l2_fusion", "l3_gate", "ordered + pool（融合候选池）", **CROSS)

# —— 层级3 链路（检索后优化）——
p.edge("l3_gate", "l3_rule", "rule（默认）", **DOWN)
p.edge("l3_gate", "l3_sem", "semantic", **RIGHT)
p.edge("l3_rule", "l3_selfrag", **RIGHT)
p.edge("l3_sem", "l3_selfrag", **DOWN)
p.edge("l3_selfrag", "l3_ctx", "开启 / 关闭都进入", **DOWN)
p.edge("l3_ctx", "g1", "格式化上下文文本", **CROSS)

# —— 生成链路 ——
p.edge("g1", "g2", **DOWN)
p.edge("g2", "g3", **DOWN)
p.edge("g3", "g4", "开（默认 False）", **DOWN)
p.edge("g3", "g5", "关", **LEFT)
p.edge("g4", "g5", **DOWN)

# —— 层级4 闭环 ——
p.edge("l4_fixed", "l4_run", **DOWN)
p.edge("l4_run", "l4_score", **DOWN)
p.edge("l4_score", "l4_ab", **DOWN)
p.edge("l4_ab", "l4_hist", **DOWN)
p.edge("l4_hist", "l4_feedback", **DOWN)
p.edge("l4_feedback", "l4_fixed", "⑥ 改参数 → 重新抽题评估（闭环）", dashed=True, **LEFT)
p.edge("g5", "l4_fixed", "评估逐题复用同一条「检索 + 生成」链路",
       dashed=True, **CROSS)

# —— 页脚说明 ——
p.node("f1", "依据文件（本题每个节点与箭头均可回溯到源码）：\n"
             "backend/api/ai_api.py（Self-RAG 检索前判断 / 生成后回答验证）\n"
             "backend/ai_service.py（build_system_prompt 的两种模式、chat）\n"
             "backend/ai_rag.py（build_rag_context 兼容层 + 各参数读取函数）\n"
             "backend/rag/pipeline.py（ModularRAG.query ①~⑥ 步）\n"
             "backend/rag_eval.py、backend/api/ai_rag_api.py（评估接口与分层抽样）\n"
             "backend/config_service.py（CONFIG_META 开关与出厂默认值）",
       40, FOOTER_Y, 1180, None, kind="note")

p.node("f2", "读图方向：用户查询进入 → 层级1 检索前优化 → 层级2 检索中"
             "（多路召回 + 加权 RRF 融合）→ 层级3 检索后优化 → 上下文构建 / 生成 → "
             "层级4 量化评估。\n"
             "每个优化点右侧的便签写「开 → 走哪条路径 / 关 → 绕过哪一步」；\n"
             "框内出现的开关名、参数名、接口路径、模块文件名都保留源码英文原文；\n"
             "所有默认值都取自 backend/config_service.py 的 CONFIG_META。",
       1260, FOOTER_Y, 1100, None, kind="note")

p.node("f3", "闭环：层级4 的⑥把诊断结论回灌到系统参数（CONFIG_META 里的开关），"
             "层级1~3 与 ModularRAG 每次查询都重新读取参数，\n"
             "下一轮提问 / 评估立即生效 —— 即「评估 → 调参 → 再评估」。\n"
             "虚线只用于旁路与回灌（非主链路）。",
       2400, FOOTER_Y, 1180, None, kind="note")

write_drawio(OUT, [p])
print("已生成：%s" % OUT)
print("页数：%d" % 1)
print("节点数：%d" % len(p._geom))
print("连线条数：%d" % len(p._edges))
