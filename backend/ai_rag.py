# -*- coding: utf-8 -*-
"""知识库向量检索（RAG）—— 按两阶段组织代码。

RAG 核心流程分为两大阶段：

┌─────────────────────────────────────────────────────────────┐
│ 第一阶段：数据准备（ETL）—— 离线执行，后台点「重建索引」触发  │
│   1.1 加载（Load）   ：读取多格式文档（Word/PDF/HTML/MD/CSV…）│
│   1.2 清洗与切分（Chunk）：按语义边界切分，父子分块（父块不向量化）│
│   1.3 向量化与存储（Embed）：Embedding 模型转向量，存入 ai_vectors 表 │
├─────────────────────────────────────────────────────────────┤
│ 第二阶段：推理问答 —— 用户提问时实时执行                        │
│   2.1 检索（Retrieve）：问题向量化 → 多路召回（文档+FAQ通道）→ 加权RRF融合 │
│   2.2 增强（Augment） ：检索上下文 + 历史对话 + 系统提示词 → 拼成完整 Prompt │
│   2.3 生成（Generate）：Prompt 输入大模型 → 基于上下文生成答案（在 ai_service.py） │
└─────────────────────────────────────────────────────────────┘

数据来源：长文档存 docs/agreements/，FAQ 存 ai_faqs 表。
向量以 JSON 存 MySQL TEXT 列、余弦用纯 Python 算（片段量级几百条，无需外部向量库）。
"""

import hashlib
import json
import os
import re

import requests

import config_service

# ——————————————————————————————————————————————
# 常量
# ——————————————————————————————————————————————

DEFAULT_EMBED_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
DEFAULT_EMBED_MODEL = "text-embedding-v3"
EMBED_DIM = 1024
EMBED_BATCH = 10
EMBED_TIMEOUT = 30
RRF_K = 60  # RRF 平滑常数，原论文推荐值

# 多路召回通道权重：
# · FAQ 是人工维护的权威问答，权重最高一档；
# · 图谱只在问题里真的出现具体实体时才产出，含金量高；
# · 图片的 content 是它自己的图注（画面描述 + 图内文字 OCR），一旦命中就说明
#   "提问里说的东西确实出现在某张图里"，比通用条款更贴合提问，故略高于文档。
CHANNEL_WEIGHT = {"document": 1.0, "image": 1.1, "faq": 1.2, "graph": 1.3}

# 父子分块
_CHILD_INDEX_OFFSET = 100000  # 子块 chunk_index 偏移，避免与父块(0~99999)冲突
_AUTOMERGE_RATIO = 0.5        # 同一父块命中子块超50%时合并返回整章

# Chroma 单次召回的候选条数默认值（可在系统参数 rag_chroma_candidates 里调）
CHROMA_FETCH_LIMIT = 50

# 句子边界 / 章节边界
_SENT_RE = re.compile(r"(?<=[。；！？])\s*")
_CHAPTER_RE = re.compile(r"(?=第[一二三四五六七八九十百零〇\d]+章)")

# 长文档目录（backend/ai_rag.py → 上两级 → 项目根 → docs/agreements/）
AGREEMENTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "agreements"
)


# ——————————————————————————————————————————————
# 配置读取（全部走 config_service，带默认值兜底）
# ——————————————————————————————————————————————

def _enabled(db) -> bool:
    try:
        return bool(config_service.get_config("ai_rag_enabled", db))
    except Exception:
        return False

def _embed_model(db) -> str:
    try:
        return (str(config_service.get_config("ai_rag_embedding_model", db) or "").strip()
                or DEFAULT_EMBED_MODEL)
    except Exception:
        return DEFAULT_EMBED_MODEL

def _top_k(db) -> int:
    try:
        return max(1, int(config_service.get_config("ai_rag_top_k", db)))
    except Exception:
        return 4

def _min_score(db) -> float:
    try:
        return float(config_service.get_config("ai_rag_min_score", db))
    except Exception:
        return 0.35

def _chunk_size(db) -> int:
    try:
        return max(120, int(config_service.get_config("ai_rag_chunk_size", db)))
    except Exception:
        return 500

def _max_chars(db) -> int:
    try:
        return max(0, int(config_service.get_config("ai_rag_max_chars", db)))
    except Exception:
        return 3000

def _child_chunk_size(db) -> int:
    """父子分块的子块字符数。

    配置填 0 时按「文档分块字符数 × 0.3」自动派生（保持原有行为），
    这样不改这个参数的人不会受影响；填了具体值就用具体值。
    子块是真正被向量化、用来检索的最小单位，它的大小直接决定检索粒度。
    """
    try:
        v = int(config_service.get_config("ai_rag_child_chunk_size", db) or 0)
    except Exception:
        v = 0
    if v <= 0:
        v = int(_chunk_size(db) * 0.3)
    return max(60, v)

def _automerge_ratio(db) -> float:
    """AutoMerging 触发比例：同一章里命中的子块占比超过它就返回整章。"""
    try:
        v = float(config_service.get_config("rag_automerge_ratio", db))
    except Exception:
        v = _AUTOMERGE_RATIO
    return min(1.0, max(0.0, v))

def _vector_backend(db) -> str:
    """向量检索后端：chroma / qdrant（均为 HNSW 索引召回）或 mysql（全表扫描兜底）。

    选中的向量库实际不可用时自动降级为 mysql，
    避免因为一个可选依赖缺失就让整个问答流程失败。
    """
    try:
        v = str(config_service.get_config("rag_vector_backend", db) or "").strip().lower()
    except Exception:
        v = ""
    if v not in ("chroma", "qdrant", "mysql"):
        v = "chroma"
    if v in ("chroma", "qdrant"):
        try:
            if v == "chroma":
                from rag import chroma_store as cs
                ok = cs.available()
            else:
                from rag import qdrant_store as qs
                ok = qs.available()
            if not ok:
                return "mysql"
        except Exception:
            return "mysql"
    return v

def _vector_candidates(db) -> int:
    """向量库单次召回的候选条数（Chroma / Qdrant 共用这一项配置）。

    后续还会按角色 / 通道 / min_score 阈值过滤，所以要多取一些留出被筛掉的余量。
    """
    try:
        return max(5, int(config_service.get_config("rag_chroma_candidates", db)))
    except Exception:
        return CHROMA_FETCH_LIMIT

# 兼容旧函数名。两个后端共用同一项配置，键名仍为 rag_chroma_candidates，
# 这样前端读写逻辑和库里已有的值都不用动。
_chroma_candidates = _vector_candidates

def _to_bool(v) -> bool:
    """把配置值宽松地转成布尔（兼容 True/1/'1'/'true'/'on' 等写法）。"""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")

def _rrf_k(db) -> int:
    """RRF 融合的平滑常数 k（公式 1/(k+排名)）。"""
    try:
        return max(1, int(config_service.get_config("rag_rrf_k", db)))
    except Exception:
        return RRF_K

def _channel_weights(db) -> dict:
    """多路召回的通道权重，形如 {"document":1.0, "image":1.1, "faq":1.2, "graph":1.3}。

    图谱这一路权重略高于 FAQ，是因为它只在问题里真的出现具体实体时才产出，
    一旦出现就说明用户在问"某个具体的人/单"，这种事实比通用条款更贴合提问。
    图片这一路略高于文档：图注命中意味着提问里的东西真的出现在某张图上。
    """
    try:
        doc_w = float(config_service.get_config("rag_weight_document", db))
    except Exception:
        doc_w = CHANNEL_WEIGHT["document"]
    try:
        img_w = float(config_service.get_config("rag_weight_image", db))
    except Exception:
        img_w = CHANNEL_WEIGHT.get("image", 1.1)
    try:
        faq_w = float(config_service.get_config("rag_weight_faq", db))
    except Exception:
        faq_w = CHANNEL_WEIGHT["faq"]
    try:
        graph_w = float(config_service.get_config("rag_weight_graph", db))
    except Exception:
        graph_w = CHANNEL_WEIGHT.get("graph", 1.3)
    return {"document": doc_w, "image": img_w, "faq": faq_w, "graph": graph_w}

def _graph_limit(db) -> int:
    """图谱通道每次最多注入几条事实。"""
    try:
        return max(1, int(config_service.get_config("rag_graph_limit", db)))
    except Exception:
        return 3

def _keyword_limit(db) -> int:
    """关键词（BM25）通道每次最多召回几条 FAQ。"""
    try:
        return max(1, int(config_service.get_config("rag_keyword_limit", db)))
    except Exception:
        return 20

def _rerank_weights(db) -> dict:
    """规则式重排序的加权系数（RRF 分 / 向量分 / 关键词分 / FAQ 来源加成）。"""
    def _f(key, default):
        try:
            return float(config_service.get_config(key, db))
        except Exception:
            return default
    return {
        "rrf": _f("rag_rerank_weight_rrf", 0.4),
        "vec": _f("rag_rerank_weight_vec", 0.3),
        "kw": _f("rag_rerank_weight_kw", 0.15),
        "source_bonus": _f("rag_rerank_source_bonus", 0.1),
    }


# —— RAG 模块开关读取（每个模块可独立关闭，便于调试对比）——
def _module_enabled(db, key: str, default: bool = True) -> bool:
    """读取某个 RAG 模块开关，默认开启。"""
    try:
        return bool(config_service.get_config(key, db))
    except Exception:
        return default


def module_query_rewrite_enabled(db) -> bool:
    return _module_enabled(db, "rag_module_query_rewrite", True)


def module_vector_retrieval_enabled(db) -> bool:
    return _module_enabled(db, "rag_module_vector_retrieval", True)


def module_keyword_retrieval_enabled(db) -> bool:
    return _module_enabled(db, "rag_module_keyword_retrieval", True)


def module_graph_retrieval_enabled(db) -> bool:
    """知识图谱召回通道开关。

    关掉之后 RAG 只剩向量 + 关键词两路，关系型问题（"这个老板找过谁"）
    就只能靠向量相似度硬猜。图谱不可用时这一路本来就会自己返回空，
    这个开关是给"想对比接入图谱前后的效果"准备的。
    """
    return _module_enabled(db, "rag_module_graph_retrieval", True)


def module_fusion_enabled(db) -> bool:
    return _module_enabled(db, "rag_module_fusion", True)


def module_rerank_enabled(db) -> bool:
    return _module_enabled(db, "rag_module_rerank", True)


def module_automerge_enabled(db) -> bool:
    return _module_enabled(db, "rag_module_automerge", True)

def _embed_url() -> str:
    return (os.getenv("QWEN_EMBED_URL") or "").strip() or DEFAULT_EMBED_URL

def _timeout() -> int:
    try:
        return int(os.getenv("QWEN_TIMEOUT") or EMBED_TIMEOUT)
    except ValueError:
        return EMBED_TIMEOUT


# ══════════════════════════════════════════════════════════════
# 第一阶段：数据准备（ETL）
# ══════════════════════════════════════════════════════════════
# 离线执行，管理员在后台点「重建索引」时触发。
# 把原始文档变成"可检索的向量片段"，分三步：加载 → 切分 → 向量化。

# ── 1.1 加载（Load）：读取多格式文档，统一转为纯文本 ──
# 支持 Word(.docx)、PDF、HTML、Markdown(.md)、CSV、JSON、TXT 等。
# 每个文档返回 (标题, 正文文本, 角色限制)，角色限制用于按用户角色过滤检索结果。

def _read_docx(filepath: str) -> tuple:
    """读取 Word 文件，返回 (title, content)。标题取第一个 Heading/Title 段落。"""
    from docx import Document
    doc = Document(filepath)
    title = ""
    paragraphs = []
    for p in doc.paragraphs:
        text = (p.text or "").strip()
        if not text:
            paragraphs.append("")
            continue
        style_name = (p.style.name or "") if p.style else ""
        if not title and ("Heading" in style_name or "Title" in style_name or "标题" in style_name):
            title = text
            continue
        paragraphs.append(text)
    if not title:
        title = os.path.splitext(os.path.basename(filepath))[0]
    return title, "\n".join(paragraphs).strip()


def _read_file(filepath: str) -> tuple:
    """通用文件读取，支持 .docx/.txt/.html/.htm/.pdf，返回 (title, content)。"""
    ext = os.path.splitext(filepath)[1].lower()
    fname = os.path.basename(filepath)
    title = os.path.splitext(fname)[0]

    if ext == ".docx":
        return _read_docx(filepath)

    if ext == ".txt":
        for enc in ("utf-8", "gbk", "gb2312", "latin-1"):
            try:
                with open(filepath, "r", encoding=enc) as f:
                    return title, f.read().strip()
            except (UnicodeDecodeError, UnicodeError):
                continue
        raise ValueError(f"TXT 编码无法识别：{fname}")

    if ext in (".html", ".htm"):
        from html.parser import HTMLParser
        class _TextExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self.parts = []
                self._skip = False
                self._title = ""
                self._in_title = False
            def handle_starttag(self, tag, attrs):
                if tag in ("script", "style"):
                    self._skip = True
                if tag == "title":
                    self._in_title = True
                if tag in ("p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6"):
                    self.parts.append("\n")
            def handle_endtag(self, tag):
                if tag in ("script", "style"):
                    self._skip = False
                if tag == "title":
                    self._in_title = False
            def handle_data(self, data):
                if self._in_title:
                    self._title += data
                elif not self._skip:
                    self.parts.append(data)
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            html_content = f.read()
        parser = _TextExtractor()
        parser.feed(html_content)
        text = re.sub(r"\n{3,}", "\n\n", "".join(parser.parts)).strip()
        if parser._title.strip():
            title = parser._title.strip()
        return title, text

    if ext == ".pdf":
        try:
            import pdfplumber
            parts = []
            with pdfplumber.open(filepath) as pdf:
                for page in pdf.pages:
                    t = page.extract_text()
                    if t:
                        parts.append(t)
            return title, "\n".join(parts).strip()
        except ImportError:
            pass
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(filepath)
            return title, "\n".join(p.extract_text() or "" for p in reader.pages).strip()
        except ImportError:
            pass
        raise ValueError(f"PDF 解析需要 pdfplumber 或 PyPDF2：{fname}")

    if ext == ".md":
        # Markdown：纯文本读取，简单清理标记符号（#、**、[]() 等）
        for enc in ("utf-8", "gbk", "latin-1"):
            try:
                with open(filepath, "r", encoding=enc) as f:
                    raw = f.read()
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        # 去掉标题标记 #、加粗 **、链接 []() 保留文字、代码块标记
        text = re.sub(r"^#{1,6}\s*", "", raw, flags=re.MULTILINE)
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        text = re.sub(r"```[^\n]*", "", text)
        text = re.sub(r"`([^`]+)`", r"\1", text)
        # 第一个 # 标题作为文档标题
        m = re.search(r"^#\s+(.+)$", raw, flags=re.MULTILINE)
        if m:
            title = m.group(1).strip()
        return title, text.strip()

    if ext in (".csv", ".json"):
        # CSV/JSON：按纯文本读取，保留原始内容供检索
        for enc in ("utf-8", "gbk", "latin-1"):
            try:
                with open(filepath, "r", encoding=enc) as f:
                    return title, f.read().strip()
            except (UnicodeDecodeError, UnicodeError):
                continue
        raise ValueError(f"文件编码无法识别：{fname}")

    raise ValueError(f"不支持的文件类型：{ext}")


# 支持的文档扩展名
_DOC_EXTENSIONS = (".docx", ".txt", ".html", ".htm", ".pdf", ".md", ".csv", ".json")


def collect_sources(db) -> list:
    """收集所有待索引内容：知识库文档 + 知识库图片 + FAQ 问答库。

    返回 [{"source_type", "source_key", "title", "role", "content"[, "asset_path"]}]

    source_type 目前有三类：
        document —— docs/agreements/ 下的多格式文档
        image    —— kb_images/ 下的图片。多模态 RAG 的核心一步：图片本身无法被
                    文本向量命中，先让千问 VL 把它转成图注文本（描述 + 图内文字 +
                    标签），再作为普通文本源流进后面的分块 / 向量化 / 检索管线。
        faq      —— ai_faqs 表里人工维护的问答
    """
    from models import AiFaq
    out = []

    # 文档目录：支持 .docx/.txt/.html/.htm/.pdf，跳过 Word 临时文件（~$ 开头）
    if os.path.isdir(AGREEMENTS_DIR):
        for fname in sorted(f for f in os.listdir(AGREEMENTS_DIR)
                            if f.lower().endswith(_DOC_EXTENSIONS)
                            and not f.startswith("~$")):
            try:
                title, content = _read_file(os.path.join(AGREEMENTS_DIR, fname))
            except Exception as e:
                print(f"[rag] 读取文件失败 {fname}: {e}")
                continue
            if not content:
                continue
            out.append({
                "source_type": "document",
                "source_key": os.path.splitext(fname)[0],
                "title": title, "role": "", "content": content,
            })
    else:
        print(f"[rag] 协议文档目录不存在：{AGREEMENTS_DIR}")

    # 知识库图片（多模态 RAG · 路线 A）
    # 先让千问 VL 把图片"翻译"成结构化文本（概括 + 画面描述 + 图内文字 OCR +
    # 检索标签），再当作一个普通文本源交给后面的管线 —— 检索侧一行都不用改。
    # 图注带缓存（ai_image_captions，键 = 文件名 + 图片文件 MD5）：
    # 图片内容没变就直接读缓存、一次接口都不调，所以「重建索引」点多少次都不花钱。
    try:
        from rag import image_captioner
        for fname in image_captioner.list_image_files():
            cap = image_captioner.get_caption(db, fname)
            if not cap.get("ok") or not (cap.get("caption") or "").strip():
                if cap.get("error"):
                    print(f"[rag] 图片图注生成失败 {fname}：{cap['error']}")
                continue
            stem = os.path.splitext(fname)[0]
            out.append({
                "source_type": "image",
                "source_key": stem,
                "title": stem,
                "role": "",
                "content": cap["caption"],
                # 前端据此拼 /kbimg/<文件名> 显示缩略图
                "asset_path": fname,
            })
            if not cap.get("from_cache"):
                print(f"[rag] 已生成图注：{fname}（模型 {cap.get('model') or '-'}）")
    except Exception as e:
        print(f"[rag] 收集知识库图片失败：{e}")

    # FAQ（问法+答法一起索引，问法措辞更接近用户提问）
    try:
        faqs = db.query(AiFaq).filter(AiFaq.enabled == 1).order_by(AiFaq.id.asc()).all()
    except Exception as e:
        print(f"[rag] 读取 ai_faqs 失败：{e}")
        faqs = []
    for f in faqs:
        out.append({
            "source_type": "faq",
            "source_key": str(f.id),
            "title": (f.question or "")[:100],
            "role": f.role or "",
            "content": f"问：{f.question}\n答：{f.answer}",
        })
    return out


# ── 1.2 清洗与切分（Chunk）：把长文本切成语义完整的片段 ──
# 为什么不按字数硬切：中文硬切会在句子中间断开，语义支离破碎，向量就没意义了。
# 策略：先按"第X条/章/节"等语义边界切，再把相邻片段打包到接近 chunk_size。
# 父子分块：父块（整章）不向量化，用于返回给大模型时上下文完整；
#           子块（句子级）向量化，用于检索时精准命中。

def _hard_split(unit: str, size: int) -> list:
    """按句子切分再打包到接近 size；单句超长时按字符硬切兜底。"""
    pieces, buf = [], ""
    for sent in _SENT_RE.split(unit):
        sent = (sent or "").strip()
        if not sent:
            continue
        if len(sent) > size:
            if buf:
                pieces.append(buf); buf = ""
            for k in range(0, len(sent), size):
                pieces.append(sent[k:k + size])
            continue
        if not buf:
            buf = sent
        elif len(buf) + 1 + len(sent) <= size:
            buf = buf + sent
        else:
            pieces.append(buf); buf = sent
    if buf:
        pieces.append(buf)
    return pieces


def chunk_parent_child(text: str, child_size: int = 150) -> list:
    """父子分块：父块按「第X章」切（不向量化，返回大模型），子块按句子切（向量化，检索用）。

    返回 [(parent_content, [child_content, ...]), ...]
    """
    text = (text or "").strip()
    if not text:
        return []
    child_size = max(60, int(child_size or 150))

    parents = [c.strip() for c in _CHAPTER_RE.split(text) if c.strip()]
    if not parents:
        parents = [text]

    result = []
    for parent in parents:
        children = _hard_split(parent, child_size) or [parent]
        result.append((parent, children))
    return result


# ── 1.3 向量化与存储（Embed & Store）：文本块 → 向量 → 存入 MySQL ──
# 用千问 text-embedding-v3 模型（1024维）把每个文本块转成向量。
# 向量以 JSON 数组存 MySQL 的 ai_vectors 表（TEXT 列），无需外部向量数据库。
# rebuild_index() 是入口：收集所有文档 → 分块 → 批量向量化 → 写入/更新数据库。
# 同时维护文档级元数据（ai_vector_sources 表），支持按来源删除、统计、增量重建。

def md5_text(text: str) -> str:
    """内容 MD5，用于判断是否变化（没变就不重新向量化，省 API 费用）。"""
    return hashlib.md5((text or "").encode("utf-8")).hexdigest()


def embed_texts(texts: list, model: str = None) -> list:
    """【1.3 向量化】批量调用千问 embedding 接口，文本列表 → 1024维向量列表。

    在 RAG 流程中的位置：数据准备阶段的最后一步，把切好的文本块转成向量。
    检索阶段也会调用它（把用户问题转成向量，再和库里的向量算余弦相似度）。

    参数：
        texts: 要向量化的文本列表（批量处理，每批 EMBED_BATCH 条）
        model: embedding 模型名，默认 text-embedding-v3（1024维）

    返回：
        与 texts 等长的向量列表，每个向量是 1024 个 float 的 list。

    异常：API Key 未配置、超时、连接失败、HTTP 非200 时抛 RuntimeError。
    """
    import ai_service
    api_key = ai_service.get_api_key()
    if not api_key:
        raise RuntimeError("未配置 DASHSCOPE_API_KEY")

    model = (model or DEFAULT_EMBED_MODEL).strip() or DEFAULT_EMBED_MODEL
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    out = []
    for i in range(0, len(texts), EMBED_BATCH):
        batch = [t if t.strip() else "（空）" for t in texts[i:i + EMBED_BATCH]]
        try:
            resp = requests.post(
                _embed_url(), headers=headers,
                json={"model": model, "input": batch, "dimensions": EMBED_DIM},
                timeout=_timeout(),
            )
        except requests.exceptions.Timeout:
            raise RuntimeError("向量化服务响应超时")
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"无法连接向量化服务（{type(e).__name__}）")

        if resp.status_code != 200:
            detail = ""
            try:
                body = resp.json()
                detail = ((body.get("error") or {}).get("message") or body.get("message") or "")
            except Exception:
                detail = (resp.text or "")[:120]
            raise RuntimeError(f"向量化接口 HTTP {resp.status_code}{('：' + detail) if detail else ''}")

        data = sorted(resp.json().get("data") or [], key=lambda d: d.get("index", 0))
        if len(data) != len(batch):
            raise RuntimeError(f"向量化返回条数不符（期望 {len(batch)}，实际 {len(data)}）")
        out.extend(d.get("embedding") or [] for d in data)

    for v in out:
        if not v:
            raise RuntimeError("向量化接口返回了空向量")
    return out


def _cosine(a: list, b: list) -> float:
    """余弦相似度：点积 / 模长乘积，范围 -1~1。纯 Python 实现（几百条够用）。

    数学公式：
        cos(θ) = (a · b) / (||a|| × ||b||)
               = sum(a_i × b_i) / (sqrt(sum(a_i²)) × sqrt(sum(b_i²)))

    与 L2 归一化的关系（文档2核心知识点）：
        如果两个向量都已经做了 L2 归一化（模长=1），则余弦相似度 = 点积（内积）。
        这是 FAISS 等向量数据库实现余弦检索的标准做法：入库时归一化，检索时用内积索引。
        我们当前未做归一化，每次检索都完整计算余弦（含模长），数据量小时无性能问题。

    返回值含义：
        1.0 = 完全相同方向（语义最相似）
        0.0 = 正交（无关）
        -1.0 = 完全相反方向
        文本 embedding 向量通常都是正值，实际范围约 0.3~0.95。
    """
    s = na = nb = 0.0
    for x, y in zip(a, b):
        s += x * y; na += x * x; nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return s / ((na ** 0.5) * (nb ** 0.5))


def rebuild_index(db, force: bool = False) -> dict:
    """【1.3 向量化与存储 · 入口函数】重建向量索引。

    在 RAG 流程中的位置：数据准备阶段（ETL）的总入口，管理员在后台点「重建索引」时调用。
    一次性完成：加载所有文档 → 分块 → 向量化 → 存入 MySQL。

    幂等设计：每个片段计算 content_hash（MD5），内容没变的跳过向量化（零 API 花费）。
    失败即停：向量化中途出错时保留已完成部分，下次重建从断点继续。

    执行流程（5步）：
        ① 规划：collect_sources() 收集所有文档+FAQ → chunk_parent_child() 父子分块
        ② 清理：删除本次不再出现的旧片段（文档被删/改名时）
        ③ 父块写入：整章内容存 AiChunk 表，不向量化（用于检索命中后返回完整上下文）
        ④ 子块+FAQ 向量化：调用 embed_texts() 转成 1024维向量，写入 AiVector 表
        ⑤ 提交：事务提交，返回统计信息（新增/更新/跳过/失败数量）

    参数：
        db: 数据库会话
        force: True 时忽略 hash 比较，全部重新向量化（默认 False，增量更新）

    返回：
        dict，含 total/added/updated/skipped/failed 等统计字段。
    """
    from models import AiChunk, AiVector
    model = _embed_model(db)
    child_size = _child_chunk_size(db)

    # ① 规划
    plan = []
    for src in collect_sources(db):
        if src["source_type"] == "document":
            for p_idx, (parent_content, children) in enumerate(
                    chunk_parent_child(src["content"], child_size)):
                parent_key = (src["source_type"], src["source_key"], p_idx)
                plan.append({"key": parent_key, "parent_id": None, "title": src["title"],
                             "role": src["role"], "content": parent_content,
                             "content_hash": md5_text(parent_content), "is_parent": True})
                for c_idx, child_content in enumerate(children):
                    plan.append({
                        "key": (src["source_type"], src["source_key"],
                                _CHILD_INDEX_OFFSET + p_idx * 1000 + c_idx),
                        "parent_key": parent_key, "title": src["title"], "role": src["role"],
                        "content": child_content, "content_hash": md5_text(child_content),
                        "is_parent": False,
                    })
        else:
            plan.append({"key": (src["source_type"], src["source_key"], 0),
                         "parent_id": None, "title": src["title"], "role": src["role"],
                         "content": src["content"], "content_hash": md5_text(src["content"]),
                         "is_parent": False,
                         # 图片源才有这一项（指向 kb_images/ 下的文件名）；FAQ 等文本源为空
                         "asset_path": src.get("asset_path", "")})

    existing = {(r.source_type, r.source_key, int(r.chunk_index or 0)): r
                for r in db.query(AiChunk).all()}
    wanted = {p["key"] for p in plan}

    # ② 清理：删除不需要的 chunk，同时级联删除对应 vector
    removed = 0
    for key, row in list(existing.items()):
        if key not in wanted:
            db.query(AiVector).filter(AiVector.chunk_id == row.id).delete(
                synchronize_session=False)
            db.delete(row); existing.pop(key, None); removed += 1

    # ③ 父块（不向量化，先建以便子块关联 parent_id）
    parent_id_map = {}
    skipped = 0
    for p in plan:
        if not p.get("is_parent"):
            continue
        key = p["key"]
        row = existing.get(key)
        if (row is not None and not force and row.content_hash == p["content_hash"]
                and (row.title or "") == p["title"] and (row.role or "") == p["role"]):
            skipped += 1
        else:
            if row is None:
                row = AiChunk(source_type=p["key"][0], source_key=p["key"][1],
                              chunk_index=p["key"][2], content=p["content"])
                db.add(row)
            row.title = p["title"]; row.role = p["role"]; row.content = p["content"]
            row.content_hash = p["content_hash"]; row.parent_id = None
            row.asset_path = p.get("asset_path", "") or ""
            row.enabled = 1
        db.flush()
        parent_id_map[key] = row.id

    # ④ 子块 + FAQ（收集待向量化，检查 ai_vectors 表是否已有有效向量）
    pending = []
    for p in plan:
        if p.get("is_parent"):
            continue
        key = p["key"]
        row = existing.get(key)
        parent_id = parent_id_map.get(p["parent_key"]) if "parent_key" in p else None
        # 先确保 chunk 行存在（用于获取 id）
        if row is None:
            row = AiChunk(source_type=key[0], source_key=key[1],
                          chunk_index=key[2], content=p["content"],
                          content_hash=p["content_hash"],
                          asset_path=p.get("asset_path", "") or "")
            db.add(row); db.flush()
            existing[key] = row
        # 检查 ai_vectors 表是否已有有效向量
        vec_row = db.query(AiVector).filter(AiVector.chunk_id == row.id).first()
        has_valid_vec = (vec_row is not None and not force
                         and int(vec_row.dim or 0) == EMBED_DIM
                         and (vec_row.model or "") == model)
        if (row.content_hash == p["content_hash"] and has_valid_vec
                and (row.parent_id or 0) == (parent_id or 0)):
            if ((row.title or "") != p["title"] or (row.role or "") != p["role"]
                    or int(row.enabled or 0) != 1):
                row.title = p["title"]; row.role = p["role"]; row.enabled = 1
            skipped += 1
            continue
        row.title = p["title"]; row.role = p["role"]; row.content = p["content"]
        row.content_hash = p["content_hash"]; row.parent_id = parent_id; row.enabled = 1
        row.asset_path = p.get("asset_path", "") or ""
        pending.append((key, row, p, parent_id))

    # ⑤ 分批向量化，写入 ai_vectors 表（upsert）
    added = updated = 0
    errors = ""
    for i in range(0, len(pending), EMBED_BATCH):
        group = pending[i:i + EMBED_BATCH]
        try:
            vecs = embed_texts([p["content"] for _, _, p, _ in group], model)
        except Exception as e:
            errors = str(e); break
        for (key, row, p, parent_id), vec in zip(group, vecs):
            vec_row = db.query(AiVector).filter(AiVector.chunk_id == row.id).first()
            if vec_row is None:
                vec_row = AiVector(chunk_id=row.id, embedding=json.dumps(vec),
                                   dim=EMBED_DIM, model=model)
                db.add(vec_row); added += 1
            else:
                vec_row.embedding = json.dumps(vec); vec_row.dim = EMBED_DIM
                vec_row.model = model; updated += 1

    db.commit()

    # ⑥ 同步向量到 Chroma（后端选 chroma 时）；MySQL 的 ai_vectors 仍然保留作为备份
    result = {
        "model": model, "dim": EMBED_DIM,
        "total": len(plan),
        "parent_chunks": sum(1 for p in plan if p.get("is_parent")),
        "child_chunks": sum(1 for p in plan if not p.get("is_parent")),
        "added": added, "updated": updated, "skipped": skipped, "removed": removed,
        "pending": max(0, len(pending) - added - updated), "errors": errors,
    }
    backend = _vector_backend(db)
    result["vector_backend"] = backend
    if backend == "chroma":
        result["chroma"] = sync_chroma(db, force=force)
    elif backend == "qdrant":
        result["qdrant"] = sync_qdrant(db, force=force)
    return result


def sync_chroma(db, force: bool = False) -> dict:
    """把 MySQL 里的向量全量同步到 Chroma 向量库。

    在 RAG 流程中的位置：数据准备阶段（ETL）的最后一步，紧随向量写入 MySQL 之后。
    幂等：Chroma 里已有的按 id 覆盖，MySQL 里已不存在的从 Chroma 删除。

    为什么保留 MySQL 这一份：
        ai_chunks 是片段元数据的唯一真相源；ai_vectors 作为可回退的备份。
        Chroma 损坏或需要换 embedding 模型时，可以直接从 MySQL 重建，不必重调接口。

    参数：
        db: 数据库会话
        force: True 时先清空集合再全量写入（换模型/维度、或索引疑似损坏时用）

    返回：
        dict{ok, error, written, removed, total}
    """
    from models import AiChunk, AiVector
    from rag import chroma_store as cs

    if not cs.available():
        return {"ok": False, "error": "chromadb 未安装，已跳过同步",
                "written": 0, "removed": 0, "total": 0}

    try:
        if force:
            cs.clear()

        # 只同步「已启用」的片段；父块本来就没有向量，不会出现在 ai_vectors 里
        rows = (db.query(AiVector, AiChunk)
                .join(AiChunk, AiVector.chunk_id == AiChunk.id)
                .all())

        ids, embs, metas = [], [], []
        wanted = set()
        for v, c in rows:
            if int(c.enabled or 0) != 1:
                continue
            try:
                vec = json.loads(v.embedding or "null")
            except Exception:
                continue
            # 维度与当前模型不一致的旧向量跳过（等重新向量化）
            if not isinstance(vec, list) or len(vec) != EMBED_DIM:
                continue
            cid = int(c.id)
            wanted.add(str(cid))
            ids.append(str(cid))
            embs.append(vec)
            metas.append({
                "chunk_id": cid,
                "source_type": c.source_type or "",
                "source_key": c.source_key or "",
                "chunk_index": int(c.chunk_index or 0),
                "parent_id": int(c.parent_id or 0),
                "role": c.role or "",
                "enabled": 1,
            })

        written = cs.upsert_rows(ids, embs, metas) if ids else 0

        # 清理 Chroma 中已失效的 id（源文档被删、片段被切分替换等）
        removed = 0
        try:
            stale = [x for x in cs.all_ids() if x not in wanted]
            if stale:
                removed = cs.delete_ids(stale)
        except Exception:
            removed = 0

        return {"ok": True, "error": "", "written": written,
                "removed": removed, "total": cs.count()}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "written": 0, "removed": 0, "total": 0}


def sync_qdrant(db, force: bool = False) -> dict:
    """把 MySQL 里的向量全量同步到 Qdrant 向量库。

    与 sync_chroma 完全同构：**不调 embedding 接口**，直接读 ai_vectors 里的现成向量，
    所以从 Chroma 切到 Qdrant 后点一次「重建索引」就能灌完，不额外消耗 API 额度。
    幂等：已有的按 id 覆盖，MySQL 里已不存在的从 Qdrant 删除。

    参数：
        db: 数据库会话
        force: True 时先清空集合再全量写入（换模型/维度、或索引疑似损坏时用）

    返回：
        dict{ok, error, written, removed, total}
    """
    from models import AiChunk, AiVector
    from rag import qdrant_store as qs

    if not qs.available():
        return {"ok": False, "error": "qdrant-client 未安装，已跳过同步",
                "written": 0, "removed": 0, "total": 0}

    try:
        if force:
            qs.clear()

        # 只同步「已启用」的片段；父块本来就没有向量，不会出现在 ai_vectors 里
        rows = (db.query(AiVector, AiChunk)
                .join(AiChunk, AiVector.chunk_id == AiChunk.id)
                .all())

        ids, embs, metas = [], [], []
        wanted = set()
        for v, c in rows:
            if int(c.enabled or 0) != 1:
                continue
            try:
                vec = json.loads(v.embedding or "null")
            except Exception:
                continue
            # 维度与当前模型不一致的旧向量跳过（等重新向量化）
            if not isinstance(vec, list) or len(vec) != EMBED_DIM:
                continue
            cid = int(c.id)
            wanted.add(str(cid))
            ids.append(str(cid))
            embs.append(vec)
            metas.append({
                "chunk_id": cid,
                "source_type": c.source_type or "",
                "source_key": c.source_key or "",
                "chunk_index": int(c.chunk_index or 0),
                "parent_id": int(c.parent_id or 0),
                "role": c.role or "",
                "enabled": 1,
            })

        written = qs.upsert_rows(ids, embs, metas) if ids else 0

        # 清理 Qdrant 中已失效的 id（源文档被删、片段被切分替换等）
        removed = 0
        try:
            stale = [x for x in qs.all_ids() if x not in wanted]
            if stale:
                removed = qs.delete_ids(stale)
        except Exception:
            removed = 0

        return {"ok": True, "error": "", "written": written,
                "removed": removed, "total": qs.count()}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "written": 0, "removed": 0, "total": 0}


def stats(db) -> dict:
    """索引概况：总片段数、父/子块数、已向量化数、模型/维度、最后更新时间。"""
    from models import AiChunk, AiVector
    rows = db.query(AiChunk).all()
    by_type = {}
    parent_count = child_count = 0
    for r in rows:
        by_type[r.source_type] = by_type.get(r.source_type, 0) + 1
        if r.parent_id is None and r.source_type == "document":
            parent_count += 1
        elif r.parent_id is not None:
            child_count += 1
    # 已向量化数量从 ai_vectors 表统计
    vec_rows = db.query(AiVector).all()
    ready_count = len(vec_rows)
    models = sorted({(v.model or "") for v in vec_rows if v.model})
    dims = sorted({int(v.dim or 0) for v in vec_rows if v.dim})

    # 向量后端信息：让管理员能在界面上看到「现在用的是谁、索引里有多少条」
    backend = _vector_backend(db)
    chroma_info = {}
    try:
        from rag import chroma_store as cs
        chroma_info = cs.stats()
    except Exception as e:
        chroma_info = {"available": False, "ready": False, "count": -1,
                       "path": "", "size_mb": 0.0, "collection": "", "error": str(e)}

    qdrant_info = {}
    try:
        from rag import qdrant_store as qs
        qdrant_info = qs.stats()
    except Exception as e:
        qdrant_info = {"available": False, "ready": False, "count": -1,
                       "path": "", "size_mb": 0.0, "collection": "", "error": str(e)}

    return {
        "total_chunks": len(rows), "parent_chunks": parent_count, "child_chunks": child_count,
        "ready_chunks": ready_count, "missing_chunks": len(rows) - ready_count,
        "by_type": by_type, "chars": sum(len(r.content or "") for r in rows),
        "models": models, "dims": dims,
        "last_built": max((v.updated_at for v in vec_rows if v.updated_at), default=None),
        "vector_backend": backend,
        "chroma": chroma_info,
        "qdrant": qdrant_info,
    }


def drop_source(db, source_type: str, source_key: str) -> int:
    """删除某个来源的全部片段（不 commit）。文档被改/删时调用，让 AI 立刻查不到旧内容。"""
    from models import AiChunk, AiVector
    chunks = (db.query(AiChunk)
              .filter(AiChunk.source_type == source_type)
              .filter(AiChunk.source_key == str(source_key)).all())
    chunk_ids = [c.id for c in chunks]
    if chunk_ids:
        db.query(AiVector).filter(AiVector.chunk_id.in_(chunk_ids)).delete(
            synchronize_session=False)
    n = (db.query(AiChunk)
         .filter(AiChunk.source_type == source_type)
         .filter(AiChunk.source_key == str(source_key))
         .delete(synchronize_session=False))

    # 同步清掉向量库里的对应向量，否则 AI 仍能检索到已删除的内容。
    # 失败不阻断主流程（重建索引时会做一次全量对齐）。
    if chunk_ids:
        be = _vector_backend(db)
        ids = [str(i) for i in chunk_ids]
        try:
            if be == "chroma":
                from rag import chroma_store as cs
                cs.delete_ids(ids)
            elif be == "qdrant":
                from rag import qdrant_store as qs
                qs.delete_ids(ids)
        except Exception:
            pass
    return int(n or 0)


def pending_sources(db) -> list:
    """检测哪些来源与索引不一致（需重建索引）。只做本地计算，不调 embedding 接口。"""
    from models import AiChunk, AiVector
    existing = {(r.source_type, r.source_key, int(r.chunk_index or 0)): r
                for r in db.query(AiChunk).all()}
    # 预加载所有向量记录，按 chunk_id 索引
    vec_by_chunk = {v.chunk_id: v for v in db.query(AiVector).all()}
    child_size = _child_chunk_size(db)
    model = _embed_model(db)
    out = []
    seen = set()

    for src in collect_sources(db):
        st, sk = src["source_type"], src["source_key"]
        seen.add((st, sk))
        expected_keys = set()
        if st == "document":
            for p_idx, (_pc, children) in enumerate(chunk_parent_child(src["content"], child_size)):
                expected_keys.add((st, sk, p_idx))
                for c_idx in range(len(children)):
                    expected_keys.add((st, sk, _CHILD_INDEX_OFFSET + p_idx * 1000 + c_idx))
        else:
            expected_keys.add((st, sk, 0))

        missing = 0
        for key in expected_keys:
            row = existing.get(key)
            if row is None:
                missing += 1; continue
            if key[2] < _CHILD_INDEX_OFFSET and st == "document":
                # 父块不向量化，只检查内容 hash
                if row.content_hash != md5_text(row.content or ""):
                    missing += 1
            else:
                # 子块/FAQ：检查 ai_vectors 表是否有有效向量
                vec = vec_by_chunk.get(row.id)
                if (vec is None or int(vec.dim or 0) != EMBED_DIM
                        or (vec.model or "") != model):
                    missing += 1
        if missing:
            out.append({"source_type": st, "source_key": sk, "title": src["title"],
                        "expected": len(expected_keys), "outdated": missing})

    # 已被删除的来源（索引里还留着碎片）
    orphans = {}
    for (st, sk, _idx) in existing:
        if (st, sk) not in seen:
            orphans[(st, sk)] = orphans.get((st, sk), 0) + 1
    for (st, sk), n in orphans.items():
        out.append({"source_type": st, "source_key": sk, "title": "",
                    "expected": 0, "outdated": n})
    return out


# ══════════════════════════════════════════════════════════════
# 第二阶段：推理问答（用户提问时实时执行）
# ══════════════════════════════════════════════════════════════
# 用户提问 → 检索相关片段 → 拼成 Prompt → 大模型生成答案。
# 本文件负责 2.1 检索 和 2.2 增强；2.3 生成在 ai_service.py 中调用大模型完成。

# ── 2.1 检索（Retrieve）：问题向量化 → 多路召回 → 加权 RRF 融合 ──
# 多路召回：
#   · 文档通道：长文档的子块向量，余弦相似度检索（语义匹配）
#   · FAQ 通道：人工维护的权威问答，关键词 BM25 + 向量双通道（精确匹配）
# 加权 RRF 融合：两个通道各自排序，用 Reciprocal Rank Fusion 合并，
#   FAQ 权重 1.2（权威问答优先），文档权重 1.0。
# 查询优化：在检索前可对问题进行改写/分解/扩展/HyDE（在 query_optimizer.py）。

# ============================================================
# 模块化 RAG 架构（Modular RAG）
# 各模块已独立到 rag/ 包中：
#   rag/document.py         - Document 数据结构
#   rag/query_rewriter.py   - QueryRewriter（查询改写）
#   rag/vector_retriever.py - VectorRetriever（向量检索）
#   rag/keyword_retriever.py- KeywordRetriever（关键词检索）
#   rag/fusion.py           - FusionModule（结果融合）
#   rag/context_builder.py  - ContextBuilder（上下文构建）
#   rag/pipeline.py         - ModularRAG（主类编排器）
# 本文件保留数据准备阶段（ETL）和兼容层函数。
# ============================================================

from rag import VectorRetriever, ModularRAG


# ============================================================
# 兼容层（旧函数接口，内部调用 rag 包中的模块化类，保持向后兼容）
# ============================================================

def search(db, question: str, role: str, top_k: int = 4,
           min_score: float = 0.35, source_types=None) -> list:
    """【兼容层】向量相似度检索（旧接口）。

    内部调用 rag.VectorRetriever.retrieve()，返回旧格式 [{"score", "chunk", "merged", "hit_ratio"}]。
    新代码建议直接使用 VectorRetriever 类。
    """
    retriever = VectorRetriever(db)
    docs = retriever.retrieve(question, role, top_k, min_score, source_types)
    return [{"score": d.score, "chunk": d.chunk,
             "merged": d.metadata.get("merged", False),
             "hit_ratio": d.metadata.get("hit_ratio", 0)} for d in docs]


def build_rag_context(db, user, question: str, record_miss: bool = True,
                      top_k: int = None, min_score: float = None,
                      debug: dict = None) -> str:
    """【兼容层】完整 RAG 流程（旧接口）。

    内部调用 rag.ModularRAG.query()，返回格式化后的上下文文本。
    新代码建议直接使用 ModularRAG 类。
    """
    import ai_service
    question = (question or "").strip()
    if not question:
        return ""
    role = getattr(user, "role", "") or ""
    # 图谱这一路要靠账户名把老板/打手的可见范围收敛到本人
    uname = getattr(user, "username", "") or ""

    rag = ModularRAG(db)
    context = rag.query(question, role, top_k, min_score, debug, uname)

    # 未命中记录（用于统计知识库覆盖率）
    if not context and record_miss:
        ai_service._record_faq_miss(db, question, role)

    return context

