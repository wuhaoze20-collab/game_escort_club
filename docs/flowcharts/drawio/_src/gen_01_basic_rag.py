# -*- coding: utf-8 -*-
"""生成 01-基础RAG.drawio（3 页）。

代码依据：
  backend/ai_rag.py         —— 两个阶段的划分、collect_sources / chunk_parent_child /
                               embed_texts / rebuild_index / sync_chroma / sync_qdrant
  backend/rag/pipeline.py   —— ModularRAG.query() 的 ①~⑥ 步
  backend/rag/fusion.py     —— 加权 RRF 融合
  backend/rag/context_builder.py —— 引用块渲染
  backend/api/ai_rag_api.py —— POST /api/ai/kb/rebuild 入口
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from drawio_kit import Page, write_drawio  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "01-基础RAG.drawio")

pages = []

# ============================================================
# 页 1：基础 RAG 总览（两阶段）
# 布局刻意把「存储底座」夹在两个阶段中间：
# ① 写入 → ③ 存储 → ② 读取，所有连线都是短的竖线，不会横穿画面。
# ============================================================
p = Page("00 基础RAG总览（两阶段）")
p.label("t1", "基础 RAG 全景：数据准备（离线 ETL） → 推理问答（在线 Retrieve / Augment / Generate）"
              "　—— 代码依据 backend/ai_rag.py、backend/rag/pipeline.py",
        40, 16, 1160, 34, bold=True)

p.group("g1", "① 数据准备（离线 ETL）— 管理员点「重建索引」POST /api/ai/kb/rebuild", 40, 60, 1240, 180)
p.node("a1", "数据源\n文档 / 图片 / FAQ", 70, 120, 180, 66, kind="io")
p.node("a2", "加载 + 父子分块", 330, 120, 160, 66)
p.node("a3", "向量化\ntext-embedding-v3 · 1024 维", 570, 120, 220, 66)
p.node("a5", "千问\nEmbedding API", 870, 120, 130, 66, kind="external")
p.node("a4", "写入 / 更新索引", 1080, 120, 180, 66)
p.edge("a1", "a2", "加载与分块")
p.edge("a2", "a3")
p.edge("a3", "a5", "调用")
p.edge("a5", "a4", "返回向量")

p.group("g3", "③ 存储底座（① 写入，② 读取）", 40, 300, 1240, 250)
p.node("d2", "向量库：Chroma（主用）\nQdrant（对比 · 可切换）", 480, 365, 320, 72, kind="data")
p.node("d1", "MySQL（26 张业务表）\nai_chunks / ai_vectors", 890, 365, 320, 72, kind="data")
p.node("d3", "Neo4j 知识图谱\nbolt://127.0.0.1:7687", 890, 480, 320, 72, kind="data")
p.edge("a4", "d1", "写入 MySQL", dashed=True)
p.edge("d1", "d2", "同步向量库", dashed=True)
p.edge("d1", "d3", "同步图谱", dashed=True)

p.group("g2", "② 推理问答（在线 · Retrieve → Augment → Generate）", 40, 580, 1240, 300)
p.node("q1", "用户提问\n（含 role 与 username）", 70, 650, 220, 66, kind="start")
p.node("q2", "查询改写", 310, 650, 160, 60)
p.node("q3", "多路召回\n向量 + 关键词 + 图谱", 510, 650, 200, 60)
p.node("q4", "RRF 加权融合", 750, 650, 180, 60)
p.node("q5", "重排序", 970, 650, 170, 60)
p.node("q5b", "Self-RAG 相关性过滤\nai_self_rag_enabled", 970, 760, 200, 66)
p.node("q6", "上下文构建", 730, 760, 190, 66)
p.node("q7", "ai_service.chat()\n拼装 Prompt 并生成答案", 470, 760, 210, 66, kind="external")
p.node("q8", "返回答案", 220, 762, 190, 62, kind="end")
p.chain(["q1", "q2", "q3", "q4", "q5", "q5b", "q6", "q7", "q8"])
# 从向量库底部向下进入「多路召回」，避免折线从节点体内穿出
p.edge("d2", "q3", "检索时读取", dashed=True,
       exit_x=0.5, exit_y=1, entry_x=0.5, entry_y=0)
pages.append(p)

# ============================================================
# 页 2：第一阶段 · 数据准备（索引构建）
# ============================================================
p = Page("01 数据准备（第一阶段 / 索引构建）")
p.label("t2", "第一阶段 · 数据准备（ETL）：重建向量索引 —— 代码依据 backend/ai_rag.py rebuild_index()",
        40, 16, 980, 34, bold=True)

p.node("src1", "知识库文档 docs/agreements/\n.docx / .txt / .html / .htm / .pdf", 60, 180, 320, 66, kind="io")
p.node("src2", "知识库图片 kb_images/\n经千问 VL 转成图注文本", 60, 270, 320, 66, kind="io")
p.node("src3", "FAQ 问答库 ai_faqs 表（人工维护）", 60, 360, 320, 66, kind="io")

p.node("s1", "管理员点「重建索引」\nPOST /api/ai/kb/rebuild", 620, 70, 300, 66, kind="start")
p.node("s2", "① 规划：collect_sources()\n汇总所有待索引来源", 620, 180, 300, 66)
p.node("s5", "父子分块 chunk_parent_child()\n父块按「第X章」切（不向量化）\n子块按句子硬切（向量化）", 620, 290, 300, 80)
p.node("s3", "② 清理：删除本次不再出现的旧片段\n（文档被删 / 改名时）", 620, 410, 300, 66)
p.node("s4", "③ 父块写入 AiChunk 表\n整章内容，不向量化", 620, 510, 300, 66)
p.node("s6", "子块内容 MD5 未变化？\ncontent_hash 命中", 640, 620, 260, 110, kind="decision")
p.node("sSkip", "跳过该块\n幂等，省 API 费用", 170, 780, 280, 66, kind="external")
p.node("s7", "④ 子块 + FAQ 向量化 embed_texts()", 620, 780, 300, 66)
p.node("s8", "千问 Embedding API\ntext-embedding-v3 · 1024 维", 980, 780, 260, 66, kind="external")
p.node("s9", "⑤ 写入 AiVector 表并提交事务", 620, 880, 300, 66)
p.node("s10", "rag_vector_backend\n= chroma 还是 qdrant？", 620, 990, 300, 110, kind="decision")
p.node("s11", "sync_chroma() → Chroma 集合", 980, 980, 260, 66, kind="data")
p.node("s12", "sync_qdrant() → Qdrant 集合", 980, 1060, 260, 66, kind="data")
p.node("s13", "返回统计：新增 / 更新 / 跳过 / 失败", 170, 1150, 750, 60, kind="end")
p.node("nt1", "说明：\n· 图片与 FAQ 走同一条管线，检索逻辑不变\n"
              "· Neo4j 图谱不在本链路：由 main.py 的\n"
              "  init_knowledge_graph() 与 POST /api/kg/rebuild\n"
              "  独立同步（见 06-知识图谱RAG.drawio）", 1280, 180, 340, 220, kind="note")

p.edge("src1", "s2", "扫描目录", dashed=True)
p.edge("src2", "s2", "VL 图注", dashed=True)
p.edge("src3", "s2", "读表", dashed=True)
p.edge("s1", "s2", "触发")
p.edge("s2", "s5", "分块")
p.edge("s5", "s3")
p.edge("s3", "s4")
p.edge("s4", "s6")
p.edge("s6", "sSkip", "是（已存在）")
p.edge("s6", "s7", "否（内容变化）")
# 「计入跳过」这条旁路走左侧空走廊下行，避免折线纵穿 s8/s9/s10
p.edge("sSkip", "s13", "计入跳过", exit_x=0.5, exit_y=1, entry_x=0, entry_y=0.5)
p.edge("s7", "s8", "调用")
p.edge("s8", "s9", "返回向量")
p.edge("s9", "s10")
p.edge("s10", "s11", "chroma")
p.edge("s10", "s12", "qdrant")
# 两个 sync 目标从右侧 60px 空走廊下行进入 s13，不穿过 s10
p.edge("s11", "s13", exit_x=0, exit_y=0.5, entry_x=1, entry_y=0.35)
p.edge("s12", "s13", exit_x=0.5, exit_y=1, entry_x=1, entry_y=0.6)
pages.append(p)

# ============================================================
# 页 3：第二阶段 · 推理问答
# ============================================================
p = Page("02 推理问答（第二阶段 / 检索-增强-生成）")
p.label("t3", "第二阶段 · 推理问答：检索 → 增强 → 生成 —— 代码依据 backend/rag/pipeline.py ModularRAG.query()",
        40, 16, 1080, 34, bold=True)

p.node("s1", "用户提问（role + username）", 500, 70, 300, 60, kind="start")
p.node("s2", "读取 7 个模块开关\n（系统参数，每次查询重新读取）", 500, 165, 300, 66)
p.node("s3", "① 查询改写 QueryRewriter.rewrite()\n同义词扩展 / HyDE / 多查询生成", 490, 265, 320, 66)
p.node("s4", "② 多路召回（每个查询变体各跑一遍）", 490, 365, 320, 66)
p.node("k1", "关键词检索 KeywordRetriever\nFAQ BM25 精确匹配", 60, 475, 300, 80)
p.node("k2", "向量检索 VectorRetriever\ndocument / image / faq 三通道独立召回", 400, 475, 320, 80)
p.node("k3", "图谱检索 GraphRetriever\n仅用原始问题 · 实体链接 → 可见性过滤", 760, 475, 320, 80)
p.node("nt2", "向量为什么开三通道：\n图片 content 是图注（画面描述 + 图内文字），\n语义分布与文档正文不同，混在一起分数不可比。\n\n父子分块命中子块 > 50% 时自动合并返回父块\n（AutoMerging，阈值 ai_automerge_ratio）",
       1130, 470, 340, 200, kind="note")
p.node("s5", "三路结果是否全空？", 540, 610, 240, 110, kind="decision")
p.node("sEmpty", "返回空字符串\n（不注入参考资料）", 900, 630, 240, 66, kind="end",
       fill="#F8CECC", stroke="#B85450")
p.node("s6", "③ 加权 RRF 融合 FusionModule\nrrf_k=60；document 1.0 / image 1.1 / faq 1.2 / graph 1.3",
       440, 775, 440, 80)
p.node("s7", "④ 重排序模式 rag_rerank_mode = ?", 510, 890, 300, 110, kind="decision")
p.node("r1", "Reranker（规则式）\nRRF分 + 向量分 + 关键词分 + 来源加成", 60, 910, 360, 80)
p.node("r2", "CrossEncoderReranker（语义级）\n调大模型逐条打相关性分", 890, 910, 360, 80)
p.node("s8", "Self-RAG 相关性过滤是否开启？\nai_self_rag_enabled + ai_self_rag_relevance_filter",
       450, 1045, 400, 110, kind="decision")
p.node("s9", "ISREL 打分 1~5，过滤 ≤ 阈值片段\nai_service.self_rag_filter_relevance()", 900, 1075, 360, 80)
p.node("s10", "⑥ 上下文构建 ContextBuilder.build()\n渲染引用块，受 top_k / max_chars 限制", 470, 1210, 380, 80)
p.node("s11", "填充调试信息 debug\n（前端「RAG 调试」页展示全过程）", 470, 1320, 380, 66)
p.node("s12", "ai_service.chat()：拼装 Prompt\n系统提示词段落 + 检索上下文 + 历史对话", 470, 1420, 380, 80, kind="external")
p.node("s13", "千问大模型生成答案", 470, 1530, 300, 60, kind="external")
p.node("s14", "返回答案 · FAQ 命中次数 +1", 470, 1620, 300, 60, kind="end")

p.edge("s1", "s2")
p.edge("s2", "s3")
p.edge("s3", "s4")
p.edge("s4", "k1")
p.edge("s4", "k2")
p.edge("s4", "k3")
p.edge("k1", "s5")
p.edge("k2", "s5")
p.edge("k3", "s5")
p.edge("s5", "sEmpty", "是")
p.edge("s5", "s6", "否")
p.edge("s6", "s7")
p.edge("s7", "r1", "rule（默认）")
p.edge("s7", "r2", "semantic")
p.edge("r1", "s8")
p.edge("r2", "s8")
p.edge("s8", "s9", "开启")
p.edge("s8", "s10", "关闭")
p.edge("s9", "s10")
p.edge("s10", "s11")
p.edge("s11", "s12")
p.edge("s12", "s13")
p.edge("s13", "s14")
pages.append(p)

write_drawio(OUT, pages)
print("已生成：%s" % OUT)
print("页数：%d" % len(pages))
