# -*- coding: utf-8 -*-
"""生成 05-模块化RAG架构.drawio（3 页）。

代码依据（每一页都在页标题里注明）：
  页 1  backend/rag/pipeline.py  —— ModularRAG.__init__ 组装的模块、query() 的 ①~⑥ 步、
                                    模块开关（ai_rag.py 的 module_*_enabled）、
                                    生成环节在 backend/ai_service.py 的 chat()
  页 2  backend/rag/ 下 13 个 .py 模块  —— 模块级 import（谁 import 谁）、
                                    Document 数据结构的数据流、chroma_store / qdrant_store 双后端、
                                    谁读 MySQL 谁读向量库；兼容层 backend/ai_rag.py
  页 3  backend/kg/ 下 4 个 .py 模块（schema / store / sync / api）—— 包内依赖、
                                    图谱层与 RAG 层的关系（rag/graph_retriever.py → kg.store，单向）、
                                    存储分层（MySQL / 向量库 / Neo4j）

依赖关系全部按「真实 import / 真实调用」画：
  · pipeline.py 第 16~23 行模块级 import 8 个模块 → 页 1 的编排顺序 + 页 2 的 8 条半径
  · keyword_retriever / vector_retriever / graph_retriever 内 `from .document import Document`
  · vector_retriever 内 `from . import chroma_store as cs` / `from . import qdrant_store as qs`
  · graph_retriever 内 `from kg import store`（重复 3 处）
  · rag/__init__.py 汇总导出；ai_rag.py 第 1129 行 `from rag import VectorRetriever, ModularRAG`
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from drawio_kit import Page, write_drawio  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "05-模块化RAG架构.drawio")

pages = []

# ============================================================
# 页 1：模块化 RAG 编排总览（ModularRAG）
# 依据 backend/rag/pipeline.py
# ============================================================
p = Page("00 模块化RAG编排总览（ModularRAG）")
p.label("t1", "模块化 RAG 编排总览：ModularRAG 组装了哪些模块、query() 的执行顺序、模块开关与生成边界"
              " —— 代码依据 backend/rag/pipeline.py",
        40, 16, 1140, 34, bold=True)

# 主链路
p.node("n_in", "用户提问 question + role + username", 420, 70, 300, kind="start")
p.node("n_sw", "读取 7 个模块开关\n（ai_rag.py module_*_enabled，每次查询重新读取）", 410, 165, 340)
p.node("n_rw", "① 查询改写 QueryRewriter.rewrite()\n同义词扩展 / 分解 / 后退 / HyDE / 多查询", 400, 270, 360)
p.node("n_multi", "② 多路召回 Multi-Retrieval\n每个查询变体各跑一遍关键词 + 向量；图谱只用原始问题", 400, 375, 360)

# 三路召回
p.node("k_kw", "KeywordRetriever.retrieve()\nFAQ BM25 关键词匹配\n（开关 rag_module_keyword_retrieval）",
       40, 490, 290)
p.node("k_vec", "VectorRetriever.retrieve()\ndocument / image / faq 三通道独立召回\n"
                "（开关 rag_module_vector_retrieval）", 350, 490, 340)
p.node("k_graph", "GraphRetriever.retrieve()\n仅用原始问题（实体链接）\n"
                  "（开关 rag_module_graph_retrieval）", 710, 490, 300)

p.node("n_empty", "三路结果全空？", 430, 620, 260, 110, kind="decision")
p.node("n_ret_empty", "返回空字符串（不注入参考资料）", 830, 630, 280, kind="end",
       fill="#F8CECC", stroke="#B85450")

# 融合 / 重排 / Self-RAG
p.node("n_fuse", "③ 结果融合 FusionModule.fuse()\n加权 RRF（rag_rrf_k）\n（开关 rag_module_fusion）",
       400, 770, 360)
p.node("n_rmode", "④ 重排序模式\nrag_rerank_mode = rule | semantic\n（开关 rag_module_rerank）",
       440, 880, 280, 110, kind="decision")
p.node("r_rule", "Reranker.rerank()（rule，默认）\nRRF分 + 向量分 + 关键词分 + 来源加成", 60, 900, 320)
p.node("r_sem", "CrossEncoderReranker.rerank()（semantic）\n调大模型逐条打相关性分（多 1 次 API 调用）",
       730, 900, 340)
p.node("n_selfrag", "④.5 Self-RAG 相关性过滤？\nai_self_rag_enabled + ai_self_rag_relevance_filter",
       410, 1030, 360, 110, kind="decision")
p.node("s_filter", "ai_service.self_rag_filter_relevance()\nISREL 打分 1~5，过滤 ≤ 阈值的片段",
       820, 1050, 320, kind="external")

# 收尾
p.node("n_debug", "⑤ 填充调试信息 _fill_debug()\n（前端「RAG 调试」页展示检索全过程）", 400, 1180, 360)
p.node("n_ctx", "⑥ 上下文构建 ContextBuilder.build()\n渲染引用块（受 top_k / max_chars 限制）", 400, 1290, 360)
p.node("n_ret", "返回格式化上下文文本 str\n（query() 只做「检索 + 增强」）", 420, 1400, 320, kind="end")
p.node("n_gen", "生成 Generate 不在本类\nbackend/ai_service.py chat()：\n拼 Prompt → 千问大模型生成答案",
       820, 1310, 320, kind="external")
p.node("n_ans", "返回答案给用户", 820, 1420, 320, kind="end")

# 右侧说明：组装了哪些模块 + 开关 + 参数
p.node("note_mod", "ModularRAG.__init__ 组装的模块（pipeline.py）\n"
                   "· rewriter = QueryRewriter\n"
                   "· vector_retriever = VectorRetriever\n"
                   "· keyword_retriever = KeywordRetriever\n"
                   "· graph_retriever = GraphRetriever\n"
                   "· fusion = FusionModule(rrf_k, channel_weights)\n"
                   "· reranker = Reranker\n"
                   "· cross_encoder = CrossEncoderReranker\n"
                   "  （与 reranker 二选一）\n"
                   "· context_builder = ContextBuilder", 1180, 70, 420, kind="note")
p.node("note_sw", "模块开关（ai_rag.py 读取，可独立关闭）\n"
                  "· rag_module_query_rewrite\n"
                  "· rag_module_vector_retrieval\n"
                  "· rag_module_keyword_retrieval\n"
                  "· rag_module_graph_retrieval\n"
                  "· rag_module_fusion\n"
                  "· rag_module_rerank\n"
                  "· rag_module_automerge\n"
                  "关闭后果：\n"
                  "· fusion 降级 _simple_merge()\n"
                  "· rerank 降级直接用融合结果", 1180, 320, 420, kind="note")
p.node("note_param", "融合 / 重排相关参数\n"
                     "· rag_rrf_k —— RRF 平滑常数\n"
                     "· rag_weight_document / _image / _faq / _graph\n"
                     "· rag_rerank_mode = rule | semantic\n"
                     "· ai_self_rag_enabled / ai_self_rag_relevance_filter", 1180, 590, 420, kind="note")

# 连线
p.edge("n_in", "n_sw")
p.edge("n_sw", "n_rw")
p.edge("n_rw", "n_multi")
p.edge("n_multi", "k_kw")
p.edge("n_multi", "k_vec")
p.edge("n_multi", "k_graph")
p.edge("k_kw", "n_empty")
p.edge("k_vec", "n_empty")
p.edge("k_graph", "n_empty")
p.edge("n_empty", "n_ret_empty", "是（全空）")
p.edge("n_empty", "n_fuse", "否")
p.edge("n_fuse", "n_rmode")
p.edge("n_rmode", "r_rule", "rule（默认）")
p.edge("n_rmode", "r_sem", "semantic")
p.edge("r_rule", "n_selfrag")
p.edge("r_sem", "n_selfrag")
p.edge("n_selfrag", "s_filter", "开启")
p.edge("n_selfrag", "n_debug", "关闭")
p.edge("s_filter", "n_debug")
p.edge("n_debug", "n_ctx")
p.edge("n_ctx", "n_ret")
p.edge("n_ret", "n_gen", "context 拼进 Prompt", dashed=True)
p.edge("n_gen", "n_ans")
pages.append(p)

# ============================================================
# 页 2：backend/rag/ 模块依赖与数据流
# 依据 backend/rag/ 下 13 个 .py 模块
# ============================================================
p = Page("01 backend-rag模块依赖与数据流")
p.label("t2", "backend/rag/ 模块依赖与数据流：模块级 import 关系 · Document 数据载体 · "
              "chroma_store / qdrant_store 双后端 · 谁读 MySQL 谁读向量库 —— 依据 backend/rag/*.py",
        40, 16, 1080, 34, bold=True)
p.label("lg", "实线 = 模块级 import / 调用依赖；虚线 = 运行时延迟导入 / 旁路或说明性引用",
        1120, 30, 520, 30)

p.label("z1", "① rag 包内部依赖：pipeline.py 是唯一编排者", 40, 282, 900, 30)
p.label("z2", "② 跨包 / 外部依赖与数据来源", 40, 572, 900, 30)
p.label("z3", "③ 底层库 / 无内部依赖的模块", 340, 852, 900, 30)

# 入口：兼容层
p.node("ext", "backend/ai_rag.py（兼容层 / ETL / 参数读取）\n"
              "search() · build_rag_context() · sync_chroma() · sync_qdrant() · collect_sources()",
       300, 70, 460, kind="external")
# 编排器
p.node("pipeline", "rag/pipeline.py\nModularRAG（编排器）\n"
                   "组装各检索 / 融合 / 重排 / 构建模块\n+ _simple_merge / _fill_debug", 540, 190, 360)

# 内部模块（两行）
p.node("rw", "query_rewriter.py\nQueryRewriter.rewrite()\n→ query_optimizer", 40, 320, 220)
p.node("vec", "vector_retriever.py\nVectorRetriever.retrieve()\nchroma / qdrant / mysql 三后端", 290, 320, 240)
p.node("kw", "keyword_retriever.py\nKeywordRetriever.retrieve()\nFAQ BM25（读 AiFaq）", 540, 320, 220)
p.node("graph", "graph_retriever.py\nGraphRetriever.retrieve()\nNeo4j：实体链接 → 一跳邻域", 790, 320, 220)

p.node("fusion", "fusion.py\nFusionModule.fuse()\n加权 RRF（无内部依赖）", 40, 470, 220)
p.node("rr", "reranker.py\nReranker.rerank()（rule）\n读 ai_rag._rerank_weights", 290, 470, 220)
p.node("cer", "cross_encoder_reranker.py\nCrossEncoderReranker.rerank()\n调 ai_service 大模型打分", 540, 470, 240)
p.node("ctx", "context_builder.py\nContextBuilder.build()\n调 ai_service 渲染引用块", 790, 470, 220)

# 共享数据结构 + 双后端
p.node("document", "document.py\nDocument 数据结构\ncontent / metadata / score /\nsource_type / chunk", 1080, 320, 260)
p.node("chroma", "chroma_store.py\nChroma 客户端\nquery / upsert_rows /\nall_ids / count", 1080, 470, 260)
p.node("qdrant", "qdrant_store.py\nQdrant 客户端\nquery / upsert_rows /\nall_ids / count", 1370, 470, 260)
p.node("caption", "image_captioner.py\n图片 → 图注文本\n（千问 VL + MD5 缓存）", 1080, 620, 280)

# 外部 / 底层
p.node("kgstore", "Neo4j 图数据库\n（kg.store 连接）\nbolt://127.0.0.1:7687", 40, 620, 240, kind="data")
p.node("aisvc", "backend/ai_service.py\n_faq_score · self_rag_filter_relevance\nrender_placeholders · chat()",
       340, 620, 300, kind="external")
p.node("qopt", "query_optimizer.py\ngenerate_queries()\n同义扩展 / HyDE / 分解", 660, 620, 240, kind="external")
p.node("mysql", "MySQL（models.py）\nAiChunk / AiVector / AiFaq / AiImageCaption", 40, 780, 340, kind="data")

# 说明性便签
p.node("note_req", "外部依赖库：chromadb（Chroma）/ qdrant_client（Qdrant）/ neo4j（图库）/ "
                   "requests / PIL / python-dotenv", 340, 890, 480, kind="note")
p.node("note_std", "仅依赖标准库：dataclasses / typing / json / re / hashlib / os / atexit"
                   "（fusion.py、document.py 无内部依赖）", 880, 890, 420, kind="note")
p.node("note_flow", "Document 数据流（rag/document.py）\n"
                    "· 产出：VectorRetriever / GraphRetriever / KeywordRetriever 的 retrieve()\n"
                    "· 载体：content / metadata / score / source_type / chunk\n"
                    "· 消费：FusionModule.fuse() 的 pool、ContextBuilder.build() 的渲染", 1080, 760, 520, kind="note")

# 连线：叶子 → 库 / 说明
# （exit_x/exit_y/entry_x/entry_y 只用来约束正交折线的出/入锚点，
#   让走线落到空走廊、不穿过无关方框；依赖关系本身一字未改。）
p.edge("ext", "pipeline", "build_rag_context() → ModularRAG.query()")
p.edge("ext", "vec", "search() → VectorRetriever.retrieve()")
p.edge("ext", "chroma", "sync_chroma()", dashed=True,
       exit_x=1.0, exit_y=0.5, entry_x=0.7, entry_y=0.0)
p.edge("ext", "qdrant", "sync_qdrant()", dashed=True,
       exit_x=0.5, exit_y=1.0, entry_x=0.5, entry_y=0.0)
p.edge("ext", "caption", "collect_sources()", dashed=True,
       exit_x=1.0, exit_y=0.5, entry_x=0.85, entry_y=0.0)

p.edge("pipeline", "rw", exit_x=0.0, exit_y=0.5, entry_x=0.5, entry_y=0.0)
p.edge("pipeline", "vec")
p.edge("pipeline", "kw")
p.edge("pipeline", "graph")
p.edge("pipeline", "fusion", exit_x=0.0, exit_y=0.6, entry_x=1.0, entry_y=1.0)
p.edge("pipeline", "rr", exit_x=0.35, exit_y=1.0, entry_x=0.5, entry_y=0.0)
p.edge("pipeline", "cer", exit_x=0.65, exit_y=1.0, entry_x=1.0, entry_y=0.5)
p.edge("pipeline", "ctx", exit_x=0.35, exit_y=1.0, entry_x=0.5, entry_y=0.0)

p.edge("kw", "document", "from .document",
       exit_x=0.5, exit_y=1.0, entry_x=0.0, entry_y=0.8)
p.edge("vec", "document", "from .document",
       exit_x=0.5, exit_y=1.0, entry_x=0.0, entry_y=0.8)
p.edge("graph", "document", "from .document（延迟）",
       exit_x=0.5, exit_y=1.0, entry_x=0.0, entry_y=0.7)
p.edge("vec", "chroma", "from . import chroma_store", dashed=True,
       exit_x=0.5, exit_y=1.0, entry_x=0.5, entry_y=0.0)
p.edge("vec", "qdrant", "from . import qdrant_store", dashed=True,
       exit_x=0.5, exit_y=1.0, entry_x=0.5, entry_y=0.0)

p.edge("graph", "kgstore", "from kg import store",
       exit_x=0.0, exit_y=0.0, entry_x=0.95, entry_y=0.0)
p.edge("rw", "qopt", "import query_optimizer",
       exit_x=1.0, exit_y=0.0, entry_x=0.6, entry_y=0.0)
p.edge("qopt", "aisvc", "import ai_service")
p.edge("aisvc", "ext", "import ai_rag",
       exit_x=0.65, exit_y=0.0, entry_x=0.5, entry_y=1.0)
p.edge("aisvc", "mysql", "读 AiFaq / AiPrompt")
p.edge("rr", "ext", "from ai_rag import _rerank_weights",
       exit_x=0.35, exit_y=0.0, entry_x=0.85, entry_y=1.0)
p.edge("kw", "aisvc", "_faq_score()",
       exit_x=0.0, exit_y=0.5, entry_x=0.6, entry_y=0.0)
p.edge("cer", "aisvc", "大模型打分")
p.edge("ctx", "aisvc", "render_placeholders()")
p.edge("caption", "aisvc", "VL 调用",
       exit_x=0.0, exit_y=0.0, entry_x=1.0, entry_y=0.0)
p.edge("caption", "mysql", "读写 AiImageCaption",
       exit_x=0.5, exit_y=1.0, entry_x=1.0, entry_y=0.5)
p.edge("vec", "mysql", "按 chunk_id 回填 AiChunk",
       exit_x=0.0, exit_y=0.5, entry_x=0.75, entry_y=0.0)
p.edge("kw", "mysql", "读 AiFaq",
       exit_x=0.0, exit_y=0.5, entry_x=0.75, entry_y=0.0)

p.edge("chroma", "note_req", dashed=True,
       exit_x=0.0, exit_y=0.5, entry_x=1.0, entry_y=0.5)
p.edge("qdrant", "note_req", dashed=True)
p.edge("caption", "note_req", dashed=True)
p.edge("fusion", "note_std", dashed=True,
       exit_x=0.5, exit_y=1.0, entry_x=0.6, entry_y=0.0)
p.edge("document", "note_std", dashed=True,
       exit_x=0.0, exit_y=0.5, entry_x=0.45, entry_y=0.0)
pages.append(p)

# ============================================================
# 页 3：backend/kg/ 模块与整体分层
# 依据 backend/kg/ 下 4 个 .py 模块（schema / store / sync / api）
# ============================================================
p = Page("02 backend-kg模块与整体分层")
p.label("t3", "backend/kg/ 模块与整体分层：包内依赖 · 图谱层与 RAG 层的单向依赖 · "
              "存储分层（MySQL / 向量库 / Neo4j）—— 依据 backend/kg/*.py",
        40, 16, 1180, 34, bold=True)
p.label("lg3", "实线 = import / 调用依赖；虚线 = 说明性引用", 1240, 34, 420, 30)

p.label("z1", "① backend/kg/ 包内依赖", 20, 205, 700, 30)
p.label("z2", "② 图谱层 ↔ RAG 层（rag 向下依赖 kg，反向不存在）", 20, 385, 900, 30)
p.label("z3", "③ 存储分层", 20, 555, 900, 30)

# 调用方
p.node("caller_rebuild", "POST /api/kg/rebuild（仅管理员）", 460, 90, 340, kind="io")
p.node("caller_incr", "main.py 启动 init_knowledge_graph()\n"
                      "下单 / 评价 / 打赏 / 提现 等接口\n"
                      "→ sync.sync_order / sync_rating / sync_tip / ...", 860, 90, 400, kind="io")
# kg 包内
p.node("kg_api", "kg/api.py\nFastAPI router，前缀 /api/kg\n"
                 "5 个端点：stats / graph / node / search / rebuild", 40, 90, 360)
p.node("kg_init", "kg/__init__.py\nfrom . import store, schema, sync", 40, 240, 360)
p.node("kg_sync", "kg/sync.py\n从 MySQL 业务表同步到图谱\n"
                  "sync_all / sync_order / sync_rating /\nsync_tip / sync_withdrawal / sync_punishments",
       460, 240, 380)
p.node("kg_schema", "kg/schema.py\n图谱字典：节点 / 关系 / 字段\n敏感字段标注（fields 第二项）", 900, 240, 380)
# 与 RAG 层的关系
p.node("rag_graph", "rag/graph_retriever.py\nRAG 的图谱召回通道（第三路）\n"
                    "实体链接 → 一跳邻域 → 渲染事实", 40, 420, 380)
p.node("kg_store", "kg/store.py\nNeo4j 连接封装\nrun() / run_safe() / stats()", 480, 420, 380)
p.node("note_nodep", "kg/schema.py 模块级无 import\n（纯常量定义，不依赖任何模块）", 920, 420, 360, kind="note")
# 存储分层
p.node("mysql", "MySQL（业务真相源）\nmodels.py：User / BossInfo / PlayerInfo /\n"
                "Order / PlayerRating / TipRecord / ...", 40, 590, 380, kind="data")
p.node("neo4j", "Neo4j 知识图谱\nbolt://127.0.0.1:7687\n（旁路：写失败只打日志）", 480, 590, 380, kind="data")
p.node("vecdb", "向量库（只服务 rag 检索）\nChroma（主用）/ Qdrant（对比）\nkg 层不涉及向量库", 920, 590, 380, kind="data")
p.node("note_store", "分层约定\n"
                     "· MySQL —— 业务真相源；图谱与向量库都由它派生\n"
                     "· 向量库 —— 只被 rag 的 VectorRetriever 读取\n"
                     "· Neo4j —— 图谱旁路，所有写入走 store.run_safe()，失败不致命\n"
                     "· 依赖单向：rag/graph_retriever.py → kg.store；kg 层不 import rag", 40, 780, 760, kind="note")

# 连线
# （exit_x/exit_y/entry_x/entry_y 只用来约束正交折线的出/入锚点，依赖关系不变。）
p.edge("caller_rebuild", "kg_api", "HTTP 请求")
p.edge("caller_incr", "kg_sync", "增量同步")
p.edge("kg_api", "kg_sync", "rebuild → sync_all()")
p.edge("kg_api", "kg_store", "stats / graph 查询")
p.edge("kg_api", "kg_schema", "字段中文名 / 敏感标注",
       exit_x=0.5, exit_y=1.0, entry_x=0.5, entry_y=0.0)
p.edge("kg_init", "kg_store", "from . import store")
p.edge("kg_init", "kg_schema", "from . import schema",
       exit_x=1.0, exit_y=0.0, entry_x=0.5, entry_y=0.0)
p.edge("kg_init", "kg_sync", "from . import sync")
p.edge("kg_sync", "kg_store", "store.run_safe()")
p.edge("kg_sync", "kg_schema", "schema.NODE_TYPES")
p.edge("kg_sync", "mysql", "读业务表")
p.edge("kg_store", "neo4j", "neo4j.GraphDatabase.driver")
p.edge("kg_schema", "note_nodep", dashed=True)
p.edge("rag_graph", "kg_store", "from kg import store（单向依赖）")
pages.append(p)

write_drawio(OUT, pages)
print("已生成：%s" % OUT)
print("页数：%d" % len(pages))
