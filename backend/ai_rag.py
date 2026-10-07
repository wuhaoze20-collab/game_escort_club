# -*- coding: utf-8 -*-
"""知识库向量检索（RAG）。

流程：数据准备（收集+分块） → 索引构建（向量化+存库） → 检索（向量+关键词） → 提示词注入。

长文档存 docs/agreements/*.docx，FAQ 存 ai_faqs 表；修改后后台点「重建索引」。
向量以 JSON 存 TEXT 列、余弦用纯 Python 算（片段量级几百条，无需外部向量库）。
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

# 多路召回通道权重（PDF：FAQ 是人工维护的权威问答，权重高；长文档权重标准）
CHANNEL_WEIGHT = {"document": 1.0, "faq": 1.2}

# 父子分块
_CHILD_INDEX_OFFSET = 100000  # 子块 chunk_index 偏移，避免与父块(0~99999)冲突
_AUTOMERGE_RATIO = 0.5        # 同一父块命中子块超50%时合并返回整章

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

def _embed_url() -> str:
    return (os.getenv("QWEN_EMBED_URL") or "").strip() or DEFAULT_EMBED_URL

def _timeout() -> int:
    try:
        return int(os.getenv("QWEN_TIMEOUT") or EMBED_TIMEOUT)
    except ValueError:
        return EMBED_TIMEOUT


# ——————————————————————————————————————————————
# 第一阶段：数据准备（收集 + 分块）
# ——————————————————————————————————————————————

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
    """收集所有待索引内容：文档目录下的所有支持格式文件 + FAQ 问答库。

    返回 [{"source_type", "source_key", "title", "role", "content"}]
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


# ——————————————————————————————————————————————
# 第二阶段：索引构建（向量化 + 重建 + 管理）
# ——————————————————————————————————————————————

def md5_text(text: str) -> str:
    """内容 MD5，用于判断是否变化（没变就不重新向量化，省 API 费用）。"""
    return hashlib.md5((text or "").encode("utf-8")).hexdigest()


def embed_texts(texts: list, model: str = None) -> list:
    """批量调用千问 embedding 接口，文本列表 → 向量列表。失败抛异常。"""
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
    """余弦相似度：点积 / 模长乘积，范围 -1~1。纯 Python 实现（几百条够用）。"""
    s = na = nb = 0.0
    for x, y in zip(a, b):
        s += x * y; na += x * x; nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return s / ((na ** 0.5) * (nb ** 0.5))


def rebuild_index(db, force: bool = False) -> dict:
    """重建向量索引。内容 hash 没变的片段跳过（零花费），失败即停保留已完成部分。

    流程：①规划（收集+分块）→ ②清理（删旧片段）→ ③父块（不向量化）→ ④子块+FAQ（向量化写入ai_vectors）→ ⑤提交
    """
    from models import AiChunk, AiVector
    model = _embed_model(db)
    child_size = max(60, int(_chunk_size(db) * 0.3))

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
                         "is_parent": False})

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
                          content_hash=p["content_hash"])
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
    return {
        "model": model, "dim": EMBED_DIM,
        "total": len(plan),
        "parent_chunks": sum(1 for p in plan if p.get("is_parent")),
        "child_chunks": sum(1 for p in plan if not p.get("is_parent")),
        "added": added, "updated": updated, "skipped": skipped, "removed": removed,
        "pending": max(0, len(pending) - added - updated), "errors": errors,
    }


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
    return {
        "total_chunks": len(rows), "parent_chunks": parent_count, "child_chunks": child_count,
        "ready_chunks": ready_count, "missing_chunks": len(rows) - ready_count,
        "by_type": by_type, "chars": sum(len(r.content or "") for r in rows),
        "models": models, "dims": dims,
        "last_built": max((v.updated_at for v in vec_rows if v.updated_at), default=None),
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
    return int(n or 0)


def pending_sources(db) -> list:
    """检测哪些来源与索引不一致（需重建索引）。只做本地计算，不调 embedding 接口。"""
    from models import AiChunk, AiVector
    existing = {(r.source_type, r.source_key, int(r.chunk_index or 0)): r
                for r in db.query(AiChunk).all()}
    # 预加载所有向量记录，按 chunk_id 索引
    vec_by_chunk = {v.chunk_id: v for v in db.query(AiVector).all()}
    child_size = max(60, int(_chunk_size(db) * 0.3))
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


# ——————————————————————————————————————————————
# 第三阶段：检索（向量 + 关键词）
# ——————————————————————————————————————————————

def search(db, question: str, role: str, top_k: int = 4,
           min_score: float = 0.35, source_types=None) -> list:
    """向量检索（父子分块版）。失败抛异常，由 build_rag_context 兜底。

    流程：问题向量化 → 从 ai_vectors 读所有向量 → 关联 ai_chunks 算余弦 → AutoMerging 子块→父块 → 合并FAQ。
    返回 [{"score", "chunk", "merged", "hit_ratio"}]，按相似度降序。

    source_types：限定检索的数据源通道，None=全部，可选 ["document"]（长文档）
    或 ["faq"]（问答库），用于多路召回时各通道独立检索。
    """
    from models import AiChunk, AiVector
    question = (question or "").strip()
    if not question:
        return []
    allowed_types = set(source_types) if source_types else None

    qv = embed_texts([question], _embed_model(db))[0]

    # 从 ai_vectors 表读所有向量，关联 ai_chunks 获取元数据
    vec_rows = db.query(AiVector).all()
    chunk_ids = [v.chunk_id for v in vec_rows]
    chunks_by_id = {}
    if chunk_ids:
        q = db.query(AiChunk).filter(AiChunk.id.in_(chunk_ids))
        if allowed_types:
            q = q.filter(AiChunk.source_type.in_(list(allowed_types)))
        for c in q.all():
            chunks_by_id[c.id] = c

    child_hits = []
    faq_hits = []
    for v in vec_rows:
        chunk = chunks_by_id.get(v.chunk_id)
        if chunk is None or int(chunk.enabled or 0) != 1:
            continue
        if allowed_types and (chunk.source_type or "") not in allowed_types:
            continue
        if (chunk.role or "") not in ("", role or ""):
            continue
        try:
            vec = json.loads(v.embedding)
        except Exception:
            continue
        if not isinstance(vec, list) or len(vec) != len(qv):
            continue
        score = _cosine(qv, vec)
        if score >= min_score:
            if chunk.parent_id:
                child_hits.append((round(score, 4), chunk))
            else:
                faq_hits.append((round(score, 4), chunk))

    child_hits.sort(key=lambda x: -x[0])
    faq_hits.sort(key=lambda x: -x[0])

    # AutoMerging：统计每个父块下子块总数与命中数
    all_children = (db.query(AiChunk)
                    .filter(AiChunk.enabled == 1)
                    .filter(AiChunk.parent_id.isnot(None)).all())
    child_count_by_parent = {}
    for c in all_children:
        child_count_by_parent[c.parent_id] = child_count_by_parent.get(c.parent_id, 0) + 1

    parent_hits = {}
    for score, child in child_hits:
        pid = child.parent_id
        if pid not in parent_hits:
            parent_hits[pid] = {"max_score": score, "hit_count": 0}
        parent_hits[pid]["max_score"] = max(parent_hits[pid]["max_score"], score)
        parent_hits[pid]["hit_count"] += 1

    parent_rows = {}
    if parent_hits:
        for pr in db.query(AiChunk).filter(AiChunk.id.in_(list(parent_hits.keys()))).all():
            parent_rows[pr.id] = pr

    result = []
    for pid, info in parent_hits.items():
        total = child_count_by_parent.get(pid, 1)
        ratio = info["hit_count"] / total if total > 0 else 0
        parent_row = parent_rows.get(pid)
        if parent_row:
            # 无论是否达到 AutoMerging 阈值，都返回父块（保证上下文完整）
            result.append({"score": info["max_score"], "chunk": parent_row,
                           "merged": ratio >= _AUTOMERGE_RATIO,
                           "hit_ratio": round(ratio, 2)})

    for score, faq in faq_hits:
        result.append({"score": score, "chunk": faq, "merged": False, "hit_ratio": 1.0})

    result.sort(key=lambda x: -x["score"])
    return result[:max(1, int(top_k))]


def _keyword_faq_hits(db, question: str, role: str, limit: int = 20) -> list:
    """关键词匹配（只查 FAQ），复用 ai_service 的打分算法。返回 [(score, faq_row)]。"""
    import ai_service
    from models import AiFaq
    rows = (db.query(AiFaq)
            .filter(AiFaq.enabled == 1)
            .filter(AiFaq.role.in_(["", role or ""])).all())
    scored = []
    for r in rows:
        s = ai_service._faq_score(question, ai_service._split_keywords(r.keywords))
        if s > 0:
            scored.append((s, r))
    scored.sort(key=lambda x: (-x[0], x[1].id))
    return scored[:limit]


# ——————————————————————————————————————————————
# 第四阶段：提示词注入（双路召回 + RRF 融合 + 渲染）
# ——————————————————————————————————————————————

def build_rag_context(db, user, question: str, record_miss: bool = True,
                      top_k: int = None, min_score: float = None,
                      debug: dict = None) -> str:
    """检索并渲染成提示词片段。任何失败都退回关键词匹配，绝不抛异常。

    流程：①查询优化（生成多个查询）→ ②双路召回（每个查询都跑关键词+向量）
         → ③RRF 融合 → ④调试信息（可选）→ ⑤渲染成文字注入提示词。
    """
    import ai_service
    import query_optimizer

    question = (question or "").strip()
    if not question:
        return ""
    role = getattr(user, "role", "") or ""

    # ① 查询优化
    queries = query_optimizer.generate_queries(db, question, debug)
    if not queries:
        queries = [{"query": question, "type": "original"}]

    # ② 多路召回：文档通道（向量）+ FAQ通道（关键词BM25 + 向量），各通道独立检索
    all_kw_hits = []   # FAQ 关键词命中：[(score, faq_row, query_index, rank)]
    all_vec_hits = []  # 向量命中：[{"score", "chunk", "channel", "query_index", "rank", ...}]
    vector_errors = []
    tk = _top_k(db) if top_k is None else max(1, int(top_k))
    ms = _min_score(db) if min_score is None else float(min_score)

    for qi, qinfo in enumerate(queries):
        q = qinfo["query"]
        use_ch = qinfo.get("channels", ["keyword", "vector"])

        # FAQ 通道 —— 关键词 BM25（精确匹配；仅支持关键词通道的查询）
        if "keyword" in use_ch:
            for rank, (s, r) in enumerate(_keyword_faq_hits(db, q, role)):
                all_kw_hits.append((s, r, qi, rank))

        # 向量通道 —— 文档通道与 FAQ 通道各自独立召回
        if "vector" in use_ch:
            for channel, stypes in (("document", ["document"]), ("faq", ["faq"])):
                try:
                    for rank, h in enumerate(search(db, q, role, top_k=tk,
                                                    min_score=ms, source_types=stypes)):
                        all_vec_hits.append({
                            "score": h["score"], "chunk": h["chunk"], "channel": channel,
                            "query_index": qi, "rank_in_query": rank,
                            "merged": h.get("merged", False),
                            "hit_ratio": h.get("hit_ratio", 0),
                        })
                except Exception as e:
                    vector_errors.append(f"[{qinfo.get('type','?')}/{channel}] {e}")
                    print(f"[rag] 向量检索失败（{channel}，查询{qi}: {q[:30]}）：{e}")

    if not all_kw_hits and not all_vec_hits:
        if record_miss:
            ai_service._record_faq_miss(db, question, role)
        return ""

    # ③ 加权 RRF 融合（用排名不用原始分数，统一量纲；再乘通道权重；同一文档多次命中累加）
    pool = {}
    ranks = {}
    for _s, r, _qi, rank in all_kw_hits:
        key = ("faq", str(r.id), 0)
        pool.setdefault(key, {})["faq"] = r
        contribution = 1.0 / (RRF_K + rank + 1) * CHANNEL_WEIGHT["faq"]
        ranks[key] = ranks.get(key, 0.0) + contribution
    for h in all_vec_hits:
        c = h["chunk"]
        key = (c.source_type, c.source_key, int(c.chunk_index or 0))
        pool.setdefault(key, {})["chunk"] = c
        contribution = (1.0 / (RRF_K + h["rank_in_query"] + 1)
                        * CHANNEL_WEIGHT.get(h["channel"], 1.0))
        ranks[key] = ranks.get(key, 0.0) + contribution
    ordered = sorted(ranks.items(), key=lambda kv: -kv[1])

    # ④ 调试信息
    if debug is not None:
        per_query = []
        for qi, qinfo in enumerate(queries):
            q_kw = [(s, r) for s, r, qidx, _ in all_kw_hits if qidx == qi]
            q_vec = [h for h in all_vec_hits if h["query_index"] == qi]
            per_query.append({
                "query": qinfo["query"], "type": qinfo.get("type", "?"),
                "keyword_hits": [{"id": r.id,
                                  "question": ai_service.render_placeholders(r.question, db),
                                  "score": int(s)} for s, r in q_kw[:5]],
                "vector_hits": [{
                    "title": h["chunk"].title or "", "score": h["score"],
                    "merged": h.get("merged", False), "hit_ratio": h.get("hit_ratio", 0),
                    "content": ai_service.render_placeholders(h["chunk"].content or "", db)[:100],
                } for h in q_vec[:5]],
            })
        debug.update({
            "vector_error": "; ".join(vector_errors) if vector_errors else "",
            "all_queries": [{"query": q["query"], "type": q.get("type", "?")} for q in queries],
            "per_query_results": per_query,
            "fused_keys": [{"source_type": k[0], "source_key": k[1], "chunk_index": k[2],
                            "rrf": round(v, 6)} for k, v in ordered[:20]],
            "injected_items": 0, "injected_chars": 0,
        })

    # ⑤ 渲染（受 top_k 条数和 max_chars 总字符双重限制）
    limit = _max_chars(db)
    lines, used, picked_faqs = [], 0, []
    for key, _score in ordered:
        if len(lines) >= tk:
            break
        item = pool.get(key) or {}
        faq_row, chunk = item.get("faq"), item.get("chunk")
        if faq_row is not None:
            text = ("· 问：" + ai_service.render_placeholders(faq_row.question, db)
                    + "\n  答：" + ai_service.render_placeholders(faq_row.answer, db))
        elif chunk is not None:
            text = (f"· 【{chunk.title or '知识库'}】\n  "
                    + ai_service.render_placeholders(chunk.content, db))
        else:
            continue
        if limit and lines and used + len(text) > limit:
            break
        lines.append(text); used += len(text)
        if faq_row is not None:
            picked_faqs.append(faq_row)

    if debug is not None:
        debug["injected_items"] = len(lines)
        debug["injected_chars"] = used

    if not lines:
        return ""

    for r in picked_faqs:
        try:
            r.hit_count = int(r.hit_count or 0) + 1
        except Exception:
            pass

    if vector_errors:
        print(f"[rag] 本轮部分查询向量检索不可用：{'; '.join(vector_errors)}")
    return "【知识库检索结果（与用户本轮提问相关，优先按这里的口径回答）】\n" + "\n".join(lines)
