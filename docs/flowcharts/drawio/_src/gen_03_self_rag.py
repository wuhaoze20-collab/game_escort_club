# -*- coding: utf-8 -*-
"""生成 03-Self-RAG.drawio（4 页）。

Self-RAG 在本项目里不是独立模块，而是散在三个位置的「反思点」。
本脚本把三个反思点展开成 4 页。

代码依据（逐条已核对）：
  backend/ai_service.py     —— self_rag_should_retrieve()  L827~866   （反思点1 判断器）
                               self_rag_filter_relevance() L869~927   （反思点2 判断器）
                               self_rag_verify_answer()    L930~985   （反思点3 判断器）
                               build_system_prompt(skip_rag=) L652 / L697~699
  backend/api/ai_api.py     —— 反思点1 调用点 L128~139；反思点3 调用点 L206~227
  backend/rag/pipeline.py   —— 反思点2 调用点「④.5」段 L238~292
                               （④ 重排序 L215~236、⑥ 上下文构建 L318）
  backend/config_service.py —— 5 个 Self-RAG 系统参数及默认值 L378~397
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from drawio_kit import Page, write_drawio  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "03-Self-RAG.drawio")

pages = []

# ============================================================
# 页 1：Self-RAG 三个反思点总览
# ============================================================
p = Page("00 Self-RAG三个反思点总览")
p.label("t1",
        "Self-RAG 三个反思点总览 —— 代码依据 backend/api/ai_api.py · backend/rag/pipeline.py · backend/ai_service.py",
        40, 16, 1200, 34, bold=True)

# —— 在线主链路 ——
p.node("m1", "用户提问\nPOST /api/ai/chat", 40, 78, 150, 56, kind="start")
p.node("m2", "反思点1 · 检索前判断\n要不要查知识库？", 230, 74, 210)
p.node("m3", "检索\n多路召回 → RRF 融合 → 重排序", 480, 74, 250)
p.node("m4", "反思点2 · ISREL\n检索后相关性过滤", 770, 74, 230)
p.node("m5", "增强与生成\n上下文构建 → 大模型生成", 1040, 74, 240)
p.node("m6", "反思点3 · ISSUP\n生成后验证回答", 1320, 74, 220)
p.node("m7", "返回答案", 1580, 78, 130, 56, kind="end")
p.chain(["m1", "m2", "m3", "m4", "m5", "m6", "m7"])

# —— 三个反思点的落地位置 ——
p.group("g1", "反思点1 · 检索前判断（Retrieve）", 40, 250, 460, 470)
p.node("g1a", "开关链：ai_self_rag_enabled（默认 False）\n→ ai_self_rag_retrieve_check（默认 True）",
       60, 310, 420)
p.node("g1b", "调用 ai_service.self_rag_should_retrieve(question, model)", 60, 425, 420)
p.node("g1c", "判断「不需要检索」→ skip_rag=True\nbuild_system_prompt 跳过检索，只保留平台资料",
       60, 540, 420)
p.node("g1d", "调用点：backend/api/ai_api.py L128~139", 60, 640, 420, kind="note")

p.group("g2", "反思点2 · 检索后相关性过滤（ISREL）", 540, 250, 460, 470)
p.node("g2a", "生效条件：ai_self_rag_enabled 且\nai_self_rag_relevance_filter（默认 True）",
       560, 310, 420)
p.node("g2b", "阈值来源：ai_self_rag_relevance_threshold（默认 3）", 560, 425, 420)
p.node("g2c", "调用 ai_service.self_rag_filter_relevance(\nquestion, contexts, threshold)",
       560, 540, 420)
p.node("g2d", "调用点：backend/rag/pipeline.py 的 ④.5 段（L238~292）", 560, 640, 420, kind="note")

p.group("g3", "反思点3 · 生成后验证（ISSUP）", 1040, 250, 460, 470)
p.node("g3a", "开关：ai_self_rag_verify_answer（默认 False）", 1060, 310, 420)
p.node("g3b", "调用 ai_service.self_rag_verify_answer(\nquestion, answer, contexts, model)",
       1060, 425, 420)
p.node("g3c", "验证不通过只记录 issue 与日志，不阻断返回", 1060, 540, 420)
p.node("g3d", "调用点：backend/api/ai_api.py L206~227", 1060, 640, 420, kind="note")

p.edge("m2", "g1a", "展开见第 2 页", dashed=True,
       exit_x=0.5, exit_y=1, entry_x=0.5, entry_y=0)
p.edge("m4", "g2a", "展开见第 3 页", dashed=True,
       exit_x=0.5, exit_y=1, entry_x=0.5, entry_y=0)
p.edge("m6", "g3a", "展开见第 4 页", dashed=True,
       exit_x=0.5, exit_y=1, entry_x=0.5, entry_y=0)
p.chain(["g1a", "g1b", "g1c"])
p.chain(["g2a", "g2b", "g2c"])
p.chain(["g3a", "g3b", "g3c"])
p.edge("g1c", "g1d", "代码依据", dashed=True)
p.edge("g2c", "g2d", "代码依据", dashed=True)
p.edge("g3c", "g3d", "代码依据", dashed=True)

p.node("nt1",
       "说明：三个反思点互相独立，各由自己的系统参数控制。总开关 ai_self_rag_enabled 打开后，"
       "反思点2 才可能生效（还要再开 ai_self_rag_relevance_filter）；"
       "5 个参数的默认值见 backend/config_service.py L378~397。",
       40, 770, 1000, kind="note")
pages.append(p)

# ============================================================
# 页 2：反思点1 · 检索前判断
# ============================================================
p = Page("01 反思点1-检索前判断")
p.label("t2",
        "反思点1 · 检索前判断（要不要查知识库）—— 代码依据 backend/api/ai_api.py L128~139 + "
        "backend/ai_service.py self_rag_should_retrieve() L827~866",
        40, 16, 1400, 34, bold=True)

p.node("p1", "用户提问：POST /api/ai/chat", 460, 90, 340, 56, kind="start")
p.node("p2", "读取开关 ai_self_rag_enabled\n（ai_api.py L128 · 默认值见 config_service.py L379）",
       460, 190, 340)
p.node("d1", "ai_self_rag_enabled\n为真？（L131）", 480, 320, 300, 110, kind="decision")
p.node("p3", "读取开关 ai_self_rag_retrieve_check\n（L131 · 默认值见 config_service.py L383）",
       460, 470, 340)
p.node("d2", "ai_self_rag_retrieve_check\n为真？（L131）", 480, 590, 300, 110, kind="decision")
p.node("p4", "调用大模型判断：\nai_service.self_rag_should_retrieve(\ntext, model=model)（L133）",
       460, 740, 340, kind="external")
p.node("d3", "返回的 need_retrieve\n为真？（L134）", 480, 880, 300, 110, kind="decision")
p.node("p5", "skip_rag = True（L134）", 460, 1030, 340)
p.node("p6", "build_system_prompt(skip_rag=True)：\nctx 置空，只保留平台资料（ai_service.py L697~699）",
       460, 1140, 340)
p.node("pEnd2", "直接生成回答\n（省 embedding 调用）", 460, 1290, 340, 66, kind="end")

p.node("nSkip", "跳过本次检索前判断\nskip_rag 保持 False（默认值）", 900, 337, 340)
p.node("p7", "skip_rag = False\n（need_retrieve 为真，照常检索）", 900, 875, 340)
p.node("p8", "照常走知识库检索：\nModularRAG.query()（backend/rag/pipeline.py）", 900, 1140, 340)
p.node("p9", "进入检索 → 生成\n（见 01-基础RAG 的「推理问答」页）", 900, 1290, 340, 66, kind="end")

p.node("err1", "调用抛异常 → 打印「检索前判断失败，正常检索」\n（ai_api.py L138~139）skip_rag 保持 False",
       40, 690, 380, kind="error")

p.node("nt1", "判断链路全部内联在 backend/api/ai_api.py L128~139 里，\n"
              "没有独立模块；判断器实现见 backend/ai_service.py\n"
              "的 self_rag_should_retrieve()（L827~866）。",
       1340, 90, 360, kind="note")
p.node("nt2", "判断器内部兜底（backend/ai_service.py）：\n"
              "· 大模型调用失败 → need_retrieve=True（L852~853）\n"
              "· 返回结果 JSON 解析失败 → need_retrieve=True（L863~866）\n"
              "判不准时一律回退「照常检索」，宁可多查也不漏查。",
       1340, 740, 360, kind="note")

p.edge("p1", "p2")
p.edge("p2", "d1")
p.edge("d1", "nSkip", "否（默认关闭）", exit_x=1, exit_y=0.5, entry_x=0, entry_y=0.5)
p.edge("d1", "p3", "是")
p.edge("p3", "d2")
p.edge("d2", "nSkip", "否", exit_x=1, exit_y=0.5, entry_x=0.5, entry_y=1)
p.edge("d2", "p4", "是")
p.edge("p4", "d3")
p.edge("p4", "err1", "调用抛异常", dashed=True,
       exit_x=0, exit_y=0.5, entry_x=1, entry_y=0.5)
p.edge("p4", "nt2", "内部兜底", dashed=True,
       exit_x=0.5, exit_y=1, entry_x=0.5, entry_y=0)
p.edge("err1", "nSkip", "回退为照常检索", dashed=True,
       exit_x=1, exit_y=0.5, entry_x=1, entry_y=0.5)
p.edge("d3", "p7", "是：需要检索", exit_x=1, exit_y=0.5, entry_x=0, entry_y=0.5)
p.edge("d3", "p5", "否：不需要检索")
p.edge("p5", "p6")
p.edge("p6", "pEnd2", "不注入知识库资料")
p.edge("p7", "p8", exit_x=0.5, exit_y=1, entry_x=0, entry_y=0.5)
p.edge("nSkip", "p8", "照常检索", exit_x=1, exit_y=0.5, entry_x=1, entry_y=0.5)
p.edge("p8", "p9")
p.edge("p1", "nt1", "", dashed=True, exit_x=1, exit_y=0.5, entry_x=0, entry_y=0.5)
pages.append(p)

# ============================================================
# 页 3：反思点2 · 检索后相关性过滤（ISREL）
# ============================================================
p = Page("02 反思点2-检索后相关性过滤")
p.label("t3",
        "反思点2 · 检索后相关性过滤（ISREL）—— 代码依据 backend/rag/pipeline.py 的 ④.5 段（L238~292）+ "
        "backend/ai_service.py self_rag_filter_relevance() L869~927",
        40, 16, 1500, 34, bold=True)

p.node("r0", "④ 重排序完成\nfinal_ordered 就绪（pipeline.py L215~236）", 420, 70, 380, 56, kind="start")
p.node("r1", "进入 ④.5 Self-RAG 相关性过滤（ISREL）\n（pipeline.py L238）", 420, 180, 380)
p.node("r2", "读取开关 ai_self_rag_enabled（L241）\n默认值见 config_service.py L379（False）", 420, 290, 380)
p.node("d1", "ai_self_rag_enabled 且\nai_self_rag_relevance_filter\n都为真？（L242~244）",
       440, 400, 440, 150, kind="decision")
p.node("eSkip", "跳过 ISREL\n沿用重排序结果", 900, 420, 340, 66, kind="end")
p.node("r3", "遍历候选：final_ordered[:tk*2]，逐个处理（L252）\nfinal_ordered 为空则整段跳过（L244）\n（tk = 配置的 top_k，见 L156）", 420, 580, 380)
p.node("d2", "该候选的文本载体是哪一种？（L255~263）", 440, 700, 340, 130, kind="decision")

p.node("nFaq", "FAQ 行 → 文本「问：… 答：…」（L257~258）", 40, 900, 320)
p.node("nChunk", "chunk 正文 → chunk.content（L259~260）", 390, 900, 320)
p.node("nGraph", "图谱事实 → graph_doc 的 content（L261~262）", 740, 900, 320)
p.node("nOther", "三种都不是 → continue\n跳过该候选（L263~264）", 1090, 900, 320, kind="error")
p.node("eOther", "该候选被排除\n不打分、也不进入最终结果", 1090, 1030, 320, 66, kind="end")
p.node("nt2", "代码注释（L246~249）：\n"
              "三路来源的文本载体不同，都要认出来；\n"
              "只认 chunk 的话，FAQ 行与图谱事实会被当成空文本\n"
              "跳过打分，随后被过滤后的集合排除——\n"
              "图谱事实就是这样被无声丢掉的。",
       1460, 740, 380, kind="note")

p.node("r5", "得到该候选的文本 text（L258 / L260 / L262）", 440, 1030, 340)
p.node("d3", "text 去空白后非空？（L265）", 440, 1140, 340, 110, kind="decision")
p.node("eEmpty", "空文本 → 跳过该候选\n不进入打分集合（L265）", 900, 1150, 340, 66, kind="end")
p.node("r6", "入列：candidate_texts.append(text[:300])\n同时记下 candidate_keys（L266~267）",
       420, 1300, 380)
p.node("d4", "len(candidate_texts) > 1？（L269）", 440, 1430, 340, 130, kind="decision")
p.node("eFew", "候选不足 2 条\n跳过打分，保留原排序（L269）", 900, 1450, 340, 66, kind="end")
p.node("r7", "读取阈值 ai_self_rag_relevance_threshold\n（L271~272 · 默认值 3）", 420, 1600, 380)
p.node("r8", "调用大模型逐条打 1~5 分：\nai_service.self_rag_filter_relevance(\n……, threshold=rel_threshold)（L274~276）",
       420, 1710, 380, kind="external")
p.node("d5", "filtered 非空？（L278）", 440, 1850, 340, 110, kind="decision")
p.node("eEmpty2", "过滤为空 → 回退原排序\n（final_ordered 保持不变）", 900, 1860, 340, 66, kind="end")
p.node("r9", "按大模型分数降序重排 final_ordered（L279~288）", 420, 2000, 380)
p.node("r10", "debug[self_rag_relevance_filtered] = len(filtered)\n（L289~290）", 420, 2110, 380)
p.node("rEnd", "进入 ⑥ 上下文构建（L318）", 420, 2220, 380, 56, kind="end")
p.node("err1", "异常兜底：打印「Self-RAG 相关性过滤失败，使用原排序」\n（L291~292）→ 沿用原排序",
       1320, 1710, 380, kind="error")

p.edge("r0", "r1")
p.edge("r1", "r2")
p.edge("r2", "d1")
p.edge("d1", "eSkip", "否", exit_x=1, exit_y=0.5, entry_x=0, entry_y=0.5)
p.edge("d1", "r3", "是")
p.edge("r3", "d2")
p.edge("d2", "nFaq", "FAQ 行", exit_x=0.2, exit_y=1, entry_x=0.5, entry_y=0)
p.edge("d2", "nChunk", "chunk 正文", exit_x=0.4, exit_y=1, entry_x=0.5, entry_y=0)
p.edge("d2", "nGraph", "图谱事实", exit_x=0.6, exit_y=1, entry_x=0.5, entry_y=0)
p.edge("d2", "nOther", "都不是", exit_x=0.8, exit_y=1, entry_x=0.5, entry_y=0)
p.edge("d2", "nt2", "文本载体", dashed=True,
       exit_x=1, exit_y=0.5, entry_x=0, entry_y=0.5)
p.edge("nFaq", "r5", "", exit_x=0.5, exit_y=1, entry_x=0.15, entry_y=0)
p.edge("nChunk", "r5", "", exit_x=0.5, exit_y=1, entry_x=0.5, entry_y=0)
p.edge("nGraph", "r5", "", exit_x=0.5, exit_y=1, entry_x=0.85, entry_y=0)
p.edge("nOther", "eOther")
p.edge("r5", "d3")
p.edge("d3", "eEmpty", "否（空文本）", exit_x=1, exit_y=0.5, entry_x=0, entry_y=0.5)
p.edge("d3", "r6", "是")
p.edge("r6", "d4")
p.edge("d4", "eFew", "否", exit_x=1, exit_y=0.5, entry_x=0, entry_y=0.5)
p.edge("d4", "r7", "是")
p.edge("r7", "r8")
p.edge("r8", "d5")
p.edge("r8", "err1", "调用抛异常", dashed=True,
       exit_x=1, exit_y=0.5, entry_x=0, entry_y=0.5)
p.edge("d5", "eEmpty2", "否", exit_x=1, exit_y=0.5, entry_x=0, entry_y=0.5)
p.edge("d5", "r9", "是")
p.edge("err1", "rEnd", "沿用原排序（跳过 debug 记录）", dashed=True,
       exit_x=0, exit_y=1, entry_x=0, entry_y=0.5)
p.edge("r9", "r10")
p.edge("r10", "rEnd")
pages.append(p)

# ============================================================
# 页 4：反思点3 · 生成后验证
# ============================================================
p = Page("03 反思点3-生成后验证")
p.label("t4",
        "反思点3 · 生成后验证（回答有没有被知识库支持）—— 代码依据 backend/api/ai_api.py L206~227 + "
        "backend/ai_service.py self_rag_verify_answer() L930~985",
        40, 16, 1400, 34, bold=True)

p.node("v1", "大模型生成完成（result 的 ok 为 True · L208）", 420, 90, 380)
p.node("d1", "启用 Self-RAG 且\nai_self_rag_verify_answer 为真？\n（L208~210）",
       440, 200, 440, 150, kind="decision")
p.node("eSkip", "跳过生成后验证\n直接返回答案", 900, 232, 380, 66, kind="end")
p.node("d2", "skip_rag 为真？（L210）\n（本轮已跳过检索就不用验证）", 440, 360, 340, 130,
       kind="decision")
p.node("v2", "重新检索用于验证：\nai_rag.build_rag_context(db, current_user, text)（L214）",
       420, 530, 380)
p.node("d3", "verify_ctx 非空？（L215）", 440, 660, 340, 110, kind="decision")
p.node("eNoCtx", "无检索内容\n不验证，直接返回答案", 900, 682, 380, 66, kind="end")
p.node("v3", "拆行取片段：只保留非空、且不以「【」开头的行\n（L217~218）", 420, 830, 380)
p.node("v4", "调用 ai_service.self_rag_verify_answer(\nquestion, answer, ctx_lines, model)（L219~220）",
       420, 940, 380, kind="external")
p.node("d4", "supported 为真？（L223）", 440, 1080, 340, 110, kind="decision")
p.node("v5", "验证通过：只累加 verify 的 tokens（L222）", 420, 1240, 380)
p.node("v6", "不通过：只打印「回答未被知识库支持」并记录 issues\n（L224~225）· 不自动修正回答（L225）",
       1340, 1240, 380, kind="error")
p.node("v7", "返回答案（L246）", 420, 1380, 380, 56, kind="end")
p.node("err1", "异常兜底：打印「回答验证失败」→ 不影响返回\n（L226~227）", 1340, 940, 380,
       kind="error")
p.node("nt1", "开关默认值（backend/config_service.py L394~397）：\n"
              "ai_self_rag_verify_answer 默认 False。\n"
              "代码注释：最耗 token，建议调试时开启。",
       1340, 150, 380, kind="note")

p.edge("v1", "d1")
p.edge("v1", "nt1", "", dashed=True, exit_x=1, exit_y=0.5, entry_x=0, entry_y=0.5)
p.edge("d1", "eSkip", "否（默认）", exit_x=1, exit_y=0.5, entry_x=0, entry_y=0.5)
p.edge("d1", "d2", "是")
p.edge("d2", "eSkip", "是", exit_x=1, exit_y=0.5, entry_x=0.7, entry_y=1)
p.edge("d2", "v2", "否")
p.edge("v2", "d3")
p.edge("d3", "eNoCtx", "否", exit_x=1, exit_y=0.5, entry_x=0, entry_y=0.5)
p.edge("d3", "v3", "是")
p.edge("v3", "v4")
p.edge("v4", "d4")
p.edge("v4", "err1", "调用抛异常", dashed=True,
       exit_x=1, exit_y=0.5, entry_x=0, entry_y=0.5)
p.edge("d4", "v5", "是")
p.edge("d4", "v6", "否", exit_x=1, exit_y=0.5, entry_x=0, entry_y=0.5)
p.edge("v5", "v7")
p.edge("v6", "v7", "不阻断返回", dashed=True)
p.edge("err1", "v7", "同样返回答案", dashed=True,
       exit_x=0.5, exit_y=1, entry_x=1, entry_y=0.5)
pages.append(p)

write_drawio(OUT, pages)
print("已生成：%s" % OUT)
print("页数：%d" % len(pages))
for _p in pages:
    print("  页「%s」：节点 %d 个，连线 %d 条"
          % (_p.name, len(_p._geom), len(_p._edges)))
