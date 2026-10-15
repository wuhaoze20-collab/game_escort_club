# -*- coding: utf-8 -*-
"""生成 04-多模态RAG.drawio（3 页）。

代码依据（每一页都在页标题里注明）：
  页1  backend/rag/image_captioner.py            —— 图片 → 中文图注（四段结构）
       backend/ai_rag.py  collect_sources()      —— source_type = document / image / faq
       backend/ai_rag.py  rebuild_index()        —— ① 规划（只有 document 走父子分块）
       backend/rag/pipeline.py ModularRAG.query()—— ② 多路召回 ~ ⑥ 上下文构建
  页2  backend/rag/image_captioner.py            —— is_image / ensure_dir / list_image_files /
                                                   file_md5 / _safe_name / _prepare_data_uri /
                                                   vl_model / _call_vl / get_caption / drop_caption
       backend/models.py  AiImageCaption         —— ai_image_captions 表结构
       backend/api/ai_rag_api.py                 —— GET /images、POST /images/upload、
                                                   POST /images/{file_name}/recaption、
                                                   DELETE /images/{file_name}
  页3  backend/rag/pipeline.py                   —— 三路向量通道 document / image / faq
       backend/rag/vector_retriever.py           —— retrieve(..., source_types=[...])
       backend/rag/fusion.py                     —— contribution = 1/(rrf_k+rank+1) × weight
       backend/ai_rag.py  CHANNEL_WEIGHT         —— image 1.1
       backend/ai_rag.py  _channel_weights()     —— rag_weight_image 覆盖默认值
       backend/config_service.py                 —— rag_weight_image.default = 1.1

核实过的真实取值（不写代码里查不到的数字，行号为核实当时所见）：
  image_captioner.py:44   DEFAULT_VL_MODEL = "qwen3-vl-plus"
  image_captioner.py:46   VL_TIMEOUT = 90
  image_captioner.py:51   _MAX_SIDE = 1280
  image_captioner.py:52   _JPEG_QUALITY = 85
  image_captioner.py:216  "temperature": 0.1
  image_captioner.py:217  "max_tokens": 1200
  config_service.py:193   "ai_vl_model" default = "qwen3-vl-plus"
  ai_rag.py:47            CHANNEL_WEIGHT = {"document": 1.0, "image": 1.1, "faq": 1.2, "graph": 1.3}
  config_service.py:312   "rag_weight_image" default = 1.1
  ai_rag.py:40            RRF_K = 60   （config_service.py:303 rag_rrf_k default = 60）
  ai_rag.py:37            EMBED_DIM = 1024

排版注意（踩过的坑，别改回去）：
  · 文本里一律不用英文双引号 —— drawio_kit 的 _esc 只转义 & < >，裸 " 会截断 XML 属性；
    引用字符串字面量统一用中文引号“”。文本里也不出现 < / >，否则 draw.io 的 html=1 会当标签吞掉。
  · 椭圆（start/end）上下两端可用宽度远小于名义宽，文字行数要压到 2 行以内、并加宽到 400 左右，
    否则文字会跑到椭圆外面（校验器和 kit 的 auto_height 都按矩形算，发现不了这件事）。
  · 菱形之间的短横段（约 90px）只放“命中 / 否 / 失败 / 成功”这类短标签，
    长标签会压到相邻节点的图形上。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from drawio_kit import Page, write_drawio  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "04-多模态RAG.drawio")

pages = []

# ============================================================
# 页 1：核心页 —— 图片 → 中文图注 → 走原文本管线（检索逻辑不变）
# ============================================================
p = Page("00 多模态RAG核心链路（图片→图注→原文本管线）")
p.label(
    "t1",
    "多模态 RAG 核心链路：图片 → 视觉模型生成中文图注 → 作为 source_type=“image” 的普通文本源，"
    "流进【原有】分块 / 向量化 / 多路召回管线 —— 检索逻辑不变\n"
    "依据 backend/rag/image_captioner.py · backend/ai_rag.py collect_sources() / rebuild_index() · backend/rag/pipeline.py",
    40, 16, 1200, 48, bold=True)

# —— ① 图片入库与图注生成 ——
p.group("gA", "① 管理员上传图片 → 生成中文图注（依据 backend/rag/image_captioner.py）",
        40, 74, 1230, 200)
p.node("a1", "管理员上传图片\nPOST /api/ai/kb/images/upload", 70, 120, 270, kind="io")
p.node("a2", "文件名清洗 + 落盘\n_safe_name() / ensure_dir()", 380, 120, 250)
p.node("a3", "图注生成 get_caption()\n调视觉模型 · 带 MD5 缓存", 670, 120, 250)
p.node("a4", "图注缓存 ai_image_captions\n键 = 文件名 + 图片文件 MD5", 1000, 120, 250, kind="data")
p.chain(["a1", "a2", "a3"], ["上传", ""])
p.edge("a3", "a4", "命中/写回")

# —— ② 图注作为一类文本来源，进入原有管线 ——
p.group("gB",
        "② 图注作为 source_type=“image” 的普通文本源，流进【原有】文本管线 —— 检索逻辑一个字都没改（依据见页首）",
        40, 340, 1230, 300)
p.node("b1", "① collect_sources()\n汇总三类来源\ndocument / image / faq", 70, 405, 215)
p.node("b2", "② 分块 + 向量化\n图注走 else 分支：\n整段成为 1 个 chunk", 305, 405, 215)
p.node("b3", "③ 写入索引\nai_chunks / ai_vectors", 540, 405, 215)
p.node("b4", "④ 多路召回\ndocument / image / faq\n三通道各自独立", 775, 405, 215)
p.node("b5", "⑤ RRF 融合 → 重排 → 上下文构建\n（与纯文本 RAG 同一套代码）", 1015, 405, 240, kind="end")
p.chain(["b1", "b2", "b3", "b4", "b5"])
p.edge("a3", "b1", "图注文本 cap[“caption”]",
       exit_x=0.5, exit_y=1, entry_x=0.5, entry_y=0)

p.node("nt1", "本页要点：图片没有自己的检索链路。\n"
              "· 图注生成后就是一段普通中文文本，和文档走同一套：\n"
              "  分块 → 向量化 → 多路召回 → RRF 融合 → 重排 → 上下文构建；\n"
              "· 代码里没有任何“图片专用检索算法”，检索侧只多了一个 source_type 取值；\n"
              "· 唯一的分叉在 rebuild_index() 里：只有 document 走父子分块，image / faq 走 else 分支。",
        40, 670, 860, 150, kind="note")
p.node("nt2", "② 里为什么只有 document 被分块\n"
              "rebuild_index() 里：\n"
              "  若 source_type == “document” → chunk_parent_child()\n"
              "  否则 → 整段内容作为单个 chunk\n"
              "（图片是一段图注，本身已经很短，再切没有意义）",
        920, 670, 320, 185, kind="note")
pages.append(p)

# ============================================================
# 页 2：图注生成与缓存（image_captioner.py）
# ============================================================
p = Page("01 图注生成与缓存（image_captioner）")
p.label(
    "t2",
    "图注生成与缓存：目录扫描 → MD5 比对 → 图片转 data URI → 调视觉模型 → 写回 ai_image_captions\n"
    "依据 backend/rag/image_captioner.py（get_caption 为主入口）· backend/models.py AiImageCaption · backend/api/ai_rag_api.py",
    40, 16, 1200, 48, bold=True)

p.node("m1", "重建索引 / 上传图片时\n逐张调用 get_caption(db, fname)",
       60, 74, 400, kind="start")
p.node("m2", "list_image_files()\n扫描 kb_images/，is_image() 判定格式", 60, 185, 360)
p.node("m3", "file_md5(path)\n图片文件二进制 MD5 —— 缓存键", 60, 275, 360)
p.node("m4", "缓存行存在 且 未传 force\n且 file_hash == 当前 MD5\n且 caption 非空？",
       70, 375, 320, 120, kind="decision")
p.node("m5", "命中：直接返回旧图注\nfrom_cache=True，零 API 花费", 480, 385, 380, kind="end")
p.node("m6", "_prepare_data_uri(path)\n长边压到 1280 · JPEG 质量 85\n透明通道铺白底 · GIF 取首帧",
       60, 535, 360)
p.node("m7", "vl_model(db)\n读系统参数 ai_vl_model，默认 qwen3-vl-plus", 60, 646, 360)
p.node("m8", "调千问 VL 生成图注\nPOST VL_URL · temperature 0.1 · max_tokens 1200",
       60, 736, 360, kind="external")
p.node("m9", "调用成功？", 70, 852, 320, 110, kind="decision")
p.node("m10", "该图本次跳过：有旧缓存则沿用旧图注\n单张失败不中断整次重建索引",
       480, 862, 380, kind="end", fill="#F8CECC", stroke="#B85450")
p.node("m11", "写回 ai_image_captions（upsert）\nfile_name / file_hash / caption / model",
       60, 1002, 360)
p.node("m12", "ai_image_captions\nfile_name / file_hash / caption / model",
       480, 1002, 380, kind="data")
p.node("m13", "返回 {ok, caption, from_cache, model, error}\n交回 collect_sources()",
       60, 1102, 420, kind="end")
p.chain(["m1", "m2", "m3", "m4"])
p.edge("m4", "m5", "命中")
p.edge("m4", "m6", "否（没算过 / 传了 force）")
p.chain(["m6", "m7", "m8", "m9"])
p.edge("m9", "m10", "失败")
p.edge("m9", "m11", "成功")
p.edge("m11", "m12", "upsert", dashed=True)
p.edge("m11", "m13", "返回")

p.node("n1", "缓存键 = 文件名 + 图片文件二进制 MD5\n\n"
             "· 图片没换 → 一次接口都不调；\n"
             "· 图片换了内容（MD5 变）→ 只重算这一张；\n"
             "· 反复点「重建索引」，图库没动 = 零花费。\n\n"
             "与 ai_chunks.content_hash 是两回事：\n"
             "判断“要不要重调接口”看的是图片文件变没变，\n"
             "不是图注文本变没变。",
       900, 170, 360, 260, kind="note")
p.node("n2", "图注结构（CAPTION_PROMPT 要求四段）\n\n"
             "一、一句话概括\n"
             "二、画面内容（只描述看得见的）\n"
             "三、图中文字：逐条抄录，检索的关键\n"
             "四、关键信息：可用于检索的标签词\n\n"
             "为什么描述 + OCR + 标签一次产出：\n"
             "分三次调用 = 三倍费用、三倍失败点；\n"
             "千问 VL 本来就能在一次回答里一起给出。",
       900, 460, 360, 280, kind="note")
p.node("n3", "删除与重算（backend/api/ai_rag_api.py）\n"
             "接口前缀 /api/ai/kb\n\n"
             "· POST /images/{file_name}/recaption\n"
             "  强制重算：get_caption(..., force=True)\n"
             "· DELETE /images/{file_name}\n"
             "  删文件 + drop_caption() + drop_source()\n\n"
             "索引片段必须一起删，否则留下孤儿片段：\n"
             "AI 还会引用它，前端却显示不出缩略图。",
       900, 780, 360, 250, kind="note")
pages.append(p)

# ============================================================
# 页 3：检索侧 —— 图片是独立的一路向量通道
# ============================================================
p = Page("02 检索侧：图片是独立的一路向量通道")
p.label(
    "t3",
    "检索侧：图片单独占一路向量通道 source_types=[“image”]，与 document 不混合；融合时 image 通道乘自己的权重\n"
    "依据 backend/rag/pipeline.py · backend/rag/vector_retriever.py · backend/rag/fusion.py · "
    "backend/ai_rag.py CHANNEL_WEIGHT / _channel_weights() · backend/config_service.py rag_weight_image",
    40, 16, 1160, 48, bold=True)

p.node("r1", "用户提问\nModularRAG.query()", 40, 80, 320, kind="start")
p.node("r2", "② 多路召回：每个查询变体\n对三个向量通道各跑一遍", 420, 80, 420)
p.node("c1", "channel = “document”\nsource_types = [“document”]", 40, 200, 300)
p.node("c2", "channel = “image”\nsource_types = [“image”]", 380, 200, 300,
       fill="#FFF2CC", stroke="#D6B656")
p.node("c3", "channel = “faq”\nsource_types = [“faq”]", 720, 200, 300)
p.node("r3", "VectorRetriever.retrieve(q, role, top_k=tk, min_score=ms,\n"
             "source_types=stypes, automerge=use_automerge)\n"
             "每个通道各查一次：角色过滤 · 向量后端召回 · AutoMerging",
       40, 320, 620)
p.node("r4", "每个通道只返回自己那一类的候选，互不混合\n"
             "all_vec_hits 里用 channel 字段标记这条来自哪一路",
       40, 431, 620)
p.node("r5", "③ 加权 RRF 融合 FusionModule.fuse(all_kw_hits, all_vec_hits, all_graph_hits)",
       40, 521, 620)
p.node("r6", "contribution = 1/(rrf_k + rank + 1) × channel_weights[channel]\n"
             "rrf_k = 60（系统参数 rag_rrf_k）· image 通道权重 = 1.1（rag_weight_image）",
       40, 595, 620)
p.node("r7", "④ 重排 → ⑤ 上下文构建 → 交千问大模型生成答案", 40, 685, 620, kind="end")

p.edge("r1", "r2")
p.edge("r2", "c1")
p.edge("r2", "c2")
p.edge("r2", "c3")
p.edge("c1", "r3")
p.edge("c2", "r3")
p.edge("c3", "r3")
p.chain(["r3", "r4", "r5", "r6", "r7"])

p.node("n4", "为什么 image 必须单独占一路\n（pipeline.py 注释里的原话）\n\n"
             "· 图注的语义分布与文档正文不同；\n"
             "· 混进 document 通道，两边的相似度分数不可比；\n"
             "· 也会让「图片这一路到底有没有被召回到」\n"
             "  在调试信息里看不出来。\n\n"
             "注意：这是复用原有 RAG 管线的第三个向量通道，\n"
             "不是新建的检索链路 —— 检索算法一个都没加。",
       700, 320, 440, 260, kind="note")
p.node("n5", "image 通道的权重从哪来\n\n"
             "ai_rag.CHANNEL_WEIGHT =\n"
             "  {“document”: 1.0, “image”: 1.1, “faq”: 1.2, “graph”: 1.3}\n\n"
             "运行时由 _channel_weights(db) 读系统参数覆盖，\n"
             "图片这一路读的是 rag_weight_image\n"
             "（config_service.py 里它的 default 同为 1.1）。\n"
             "调大更倾向返回图片，调小图片就排到文档后面。",
       700, 610, 440, 260, kind="note")
p.node("n6", "命中图片之后\n\n"
             "image 通道命中的 chunk 带 asset_path\n"
             "（指向 kb_images/ 下的文件名），\n"
             "前端据此拼 /kbimg/{文件名} 显示缩略图；\n"
             "图注文本本身随 chunk.content 一起进上下文。",
       700, 900, 440, 180, kind="note")
pages.append(p)

write_drawio(OUT, pages)
print("已生成：%s" % OUT)
print("页数：%d" % len(pages))
for i, pg in enumerate(pages):
    n_vertex = sum(1 for c in pg._cells if 'vertex="1"' in c)
    print("  页%d「%s」：节点 %d 个，连线 %d 条"
          % (i + 1, pg.name, n_vertex, len(pg._edges)))
