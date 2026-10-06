# -*- coding: utf-8 -*-
"""知识库向量检索（RAG）。

职责：
· 把 `docs/agreements/` 下的 Word 长文档（协议/规范）与 `ai_faqs`（问答库）切成片段、
  调用千问 embedding 接口向量化、存进 `ai_chunks`；
· 提问时把问题也向量化，与库中片段算余弦相似度，取最相关的若干条注入提示词；
· 与原有的**关键词匹配**做 RRF 融合，保证打开 RAG 后召回不会比原来更差。

长文档管理：直接编辑 docs/agreements/ 下的 .docx 文件，然后在后台点「重建索引」。
不再使用数据库 kb_documents 表存储长文档。

关键设计约束：
1. **绝不因为检索失败而让 AI 失效**。embedding 接口挂了、索引没建、表被清空 ——
   一律退回关键词匹配，最差也就是回到没有 RAG 时的效果。见 `build_rag_context`。
2. 同步 `requests` + 必须设 `timeout`（同 ai_service）。**不要在 async def 里调用本模块**。
3. **不引入任何新依赖**。MySQL 8.2 没有 VECTOR 列类型（那是 MySQL 9.0 才引入的），
   所以向量以 JSON 数组存 TEXT 列、余弦用纯 Python 算。在几十~几百个片段这个量级上，
   这比引入 faiss/chromadb 更简单也更可靠，且不会给部署增加负担。
   片段数上万时再考虑 MySQL 9 的 VECTOR 或外部向量库，届时 `dim`/`model` 两列可用来
   识别并重建旧向量。
4. **成本控制**：`content_hash` 没变就不重新向量化。「重建索引」因此可以随时点，
   对没改动的内容零花费。
5. **阈值保护**：低于 `ai_rag_min_score` 的片段一律不注入。塞进不相关内容比不塞更糟 ——
   模型会照着错内容编。
"""

import hashlib
import json
import os
import re

import requests

import config_service

# 千问 Embedding 的 OpenAI 兼容接口（与 ai_service 的 chat 接口同域）
DEFAULT_EMBED_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
DEFAULT_EMBED_MODEL = "text-embedding-v3"
# text-embedding-v3 的固定维度。存进 ai_chunks.dim，换模型时可识别维度不匹配的旧向量
EMBED_DIM = 1024
# 单次请求最多提交多少个片段。千问 embedding 的 input 数组有上限（随版本变化），
# 这里取一个保守值，大了也不会错，只是多几次请求
EMBED_BATCH = 10
EMBED_TIMEOUT = 30
# RRF（Reciprocal Rank Fusion）的平滑常数。60 是原论文推荐值，对排名差异不敏感
RRF_K = 60


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
# 向量化
# ——————————————————————————————————————————————

def embed_texts(texts: list, model: str = None) -> list:
    """批量取向量，返回 list[list[float]]，顺序与入参一致。

    **失败一律抛异常**（不吞掉）：调用方需要知道"这次没拿到向量"才能决定降级。
    """
    import ai_service  # 延迟导入，复用同一套密钥读取逻辑（含 .env 懒加载）

    api_key = ai_service.get_api_key()
    if not api_key:
        raise RuntimeError("未配置 DASHSCOPE_API_KEY，无法调用向量化接口")

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
                detail = ((body.get("error") or {}).get("message")
                          or body.get("message") or "")
            except Exception:
                detail = (resp.text or "")[:120]
            raise RuntimeError(f"向量化接口返回 HTTP {resp.status_code}"
                               f"{('：' + detail) if detail else ''}")

        data = resp.json().get("data") or []
        # 接口不保证返回顺序，按 index 排回去，否则向量会和正文错位（且不会报错！）
        data = sorted(data, key=lambda d: d.get("index", 0))
        if len(data) != len(batch):
            raise RuntimeError(f"向量化接口返回条数不符（期望 {len(batch)}，实际 {len(data)}）")
        out.extend(d.get("embedding") or [] for d in data)

    for v in out:
        if not v:
            raise RuntimeError("向量化接口返回了空向量")
    return out


def _cosine(a: list, b: list) -> float:
    """纯 Python 余弦相似度。片段量级不大时足够快，且省掉一个 numpy 依赖。"""
    s = na = nb = 0.0
    for x, y in zip(a, b):
        s += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return s / ((na ** 0.5) * (nb ** 0.5))


def md5_text(text: str) -> str:
    return hashlib.md5((text or "").encode("utf-8")).hexdigest()


# ——————————————————————————————————————————————
# 分块
# ——————————————————————————————————————————————

# 条款类中文文档的天然边界：第X条 / 第X章 / 第X节
_CLAUSE_RE = re.compile(r"(?=第[一二三四五六七八九十百零〇\d]+[条章节])")
# 句子边界（用于超长单元强制二次切分）
_SENT_RE = re.compile(r"(?<=[。；！？])\s*")


def _split_units(text: str) -> list:
    """把正文切成语义单元：先按空行分段，段内再按「第X条/章/节」切。"""
    units = []
    for para in re.split(r"\n\s*\n", text or ""):
        para = para.strip()
        if not para:
            continue
        for part in _CLAUSE_RE.split(para):
            part = part.strip()
            if part:
                units.append(part)
    return units


def _hard_split(unit: str, size: int) -> list:
    """单个单元本身就超过 size 时（罕见），按句号/分号二次切分再打包。"""
    pieces, buf = [], ""
    for sent in _SENT_RE.split(unit):
        sent = (sent or "").strip()
        if not sent:
            continue
        if len(sent) > size:
            if buf:
                pieces.append(buf)
                buf = ""
            # 连单句都超长（极少见）：硬切
            for k in range(0, len(sent), size):
                pieces.append(sent[k:k + size])
            continue
        if not buf:
            buf = sent
        elif len(buf) + 1 + len(sent) <= size:
            buf = buf + sent
        else:
            pieces.append(buf)
            buf = sent
    if buf:
        pieces.append(buf)
    return pieces


def chunk_text(text: str, size: int = 500) -> list:
    """把长文本切成片段（普通分块，用于FAQ等小单元）。

    为什么不用固定字数硬切：中文长文档硬切会在句子甚至词语中间断开，片段语义支离破碎，
    向量也就没意义了（而且检索出来的片段读起来是残句，直接注入提示词更糟）。
    这里先按语义边界切单元，再把相邻单元打包到接近 size 为止。
    """
    text = (text or "").strip()
    if not text:
        return []
    size = max(120, int(size or 500))

    chunks, buf = [], ""
    for unit in _split_units(text):
        if len(unit) > size:
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.extend(_hard_split(unit, size))
            continue
        if not buf:
            buf = unit
        elif len(buf) + 1 + len(unit) <= size:
            buf = buf + "\n" + unit
        else:
            chunks.append(buf)
            buf = unit
    if buf:
        chunks.append(buf)
    return chunks


# 父子分块的章节边界：第X章
_CHAPTER_RE = re.compile(r"(?=第[一二三四五六七八九十百零〇\d]+章)")
# 父子分块：子块偏移量，避免与父块的 chunk_index 冲突
_CHILD_INDEX_OFFSET = 100000
# AutoMerging 阈值：同一父块下命中子块占比超过此值时，自动合并为父块
_AUTOMERGE_RATIO = 0.5


def chunk_parent_child(text: str, child_size: int = 150) -> list:
    """父子分块（Parent-Child / Small-to-Big Chunking）。

    策略：
    · 父块：按「第X章」切分，每章一个父块（上下文完整，用于返回给大模型）
    · 子块：每个父块内按句号/分号切成小片段（检索精准，用于建向量索引）
    · FAQ 不做父子分块，走普通分块

    返回 [(parent_content, [child_content, ...]), ...]
    """
    text = (text or "").strip()
    if not text:
        return []
    child_size = max(60, int(child_size or 150))

    # 按第X章切父块
    parents = []
    for chap in _CHAPTER_RE.split(text):
        chap = chap.strip()
        if chap:
            parents.append(chap)

    if not parents:
        # 没有章节结构的文档：整篇作为一个父块
        parents = [text]

    result = []
    for parent in parents:
        # 父块内按句子切子块，再打包到接近 child_size
        children = []
        buf = ""
        for sent in _SENT_RE.split(parent):
            sent = (sent or "").strip()
            if not sent:
                continue
            if len(sent) > child_size:
                if buf:
                    children.append(buf)
                    buf = ""
                for k in range(0, len(sent), child_size):
                    children.append(sent[k:k + child_size])
                continue
            if not buf:
                buf = sent
            elif len(buf) + 1 + len(sent) <= child_size:
                buf = buf + sent
            else:
                children.append(buf)
                buf = sent
        if buf:
            children.append(buf)
        if not children:
            children = [parent]
        result.append((parent, children))
    return result


# ——————————————————————————————————————————————
# 收集待索引内容
# ——————————————————————————————————————————————

# 长文档（用户协议/服务规范等）以 Word 文件形式存放在项目根目录的 docs/agreements/
# 不再使用数据库 kb_documents 表。修改协议直接编辑 .docx 文件，然后点「重建索引」。
AGREEMENTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "agreements")


def _read_docx(filepath: str) -> tuple:
    """读取一个 Word 文件，返回 (title, content)。

    标题取第一个 Heading 段落；没有则用文件名（不含扩展名）。
    正文为所有段落文本按换行拼接。
    """
    from docx import Document
    doc = Document(filepath)
    title = ""
    paragraphs = []
    for p in doc.paragraphs:
        text = (p.text or "").strip()
        if not text:
            paragraphs.append("")
            continue
        # 第一个标题样式段落（Title/Heading）作为文档标题
        style_name = (p.style.name or "") if p.style else ""
        if not title and ("Heading" in style_name or "Title" in style_name or "标题" in style_name):
            title = text
            continue
        paragraphs.append(text)
    if not title:
        title = os.path.splitext(os.path.basename(filepath))[0]
    content = "\n".join(paragraphs).strip()
    return title, content


def collect_sources(db) -> list:
    """收集所有需要索引的原始内容。

    返回 [{"source_type", "source_key", "title", "role", "content"}]：
    · source_type='document' ← docs/agreements/ 下的 Word 长文档
    · source_type='faq'      ← ai_faqs 的一条问答（本身就是最小语义单元，不再切分）
    """
    from models import AiFaq

    out = []

    # ① 从 docs/agreements/ 读取 Word 长文档
    if os.path.isdir(AGREEMENTS_DIR):
        docx_files = sorted(f for f in os.listdir(AGREEMENTS_DIR) if f.lower().endswith(".docx"))
        for fname in docx_files:
            fpath = os.path.join(AGREEMENTS_DIR, fname)
            try:
                title, content = _read_docx(fpath)
            except Exception as e:
                print(f"[rag] 读取 Word 文件失败 {fname}: {e}")
                continue
            if not content:
                continue
            source_key = os.path.splitext(fname)[0]
            out.append({
                "source_type": "document",
                "source_key": source_key,
                "title": title,
                "role": "",  # Word 文档默认所有角色可见
                "content": content,
            })
    else:
        print(f"[rag] 协议文档目录不存在：{AGREEMENTS_DIR}")

    # ② 从数据库读取 FAQ 问答库
    try:
        faqs = db.query(AiFaq).filter(AiFaq.enabled == 1).order_by(AiFaq.id.asc()).all()
    except Exception as e:
        print(f"[rag] 读取 ai_faqs 失败：{e}")
        faqs = []
    for f in faqs:
        # 问法与答法一起索引：用户提问的措辞往往和"标准问法"更接近，
        # 把问法也放进去能明显提高召回（答法则提供回答依据）
        out.append({
            "source_type": "faq",
            "source_key": str(f.id),
            "title": (f.question or "")[:100],
            "role": f.role or "",
            "content": f"问：{f.question}\n答：{f.answer}",
        })
    return out


# ——————————————————————————————————————————————
# 重建索引
# ——————————————————————————————————————————————

def rebuild_index(db, force: bool = False) -> dict:
    """重建向量索引（父子分块版），返回统计信息。

    分块策略：
    · document 类型：父子分块——父块按「第X章」切（不向量化，用于返回大模型），
      子块按句子切（向量化，用于检索）
    · faq 类型：普通块（直接向量化）

    · 内容 hash 与模型维度都没变的片段**直接跳过**，不调用 embedding 接口（省钱省时）
    · 源内容里已不存在的片段会被删除
    · 向量化中途失败时**保留已成功的部分并返回 errors**（不整批回滚）
    """
    from models import AiChunk

    model = _embed_model(db)
    child_size = max(60, int(_chunk_size(db) * 0.3))  # 子块约为原chunk_size的30%

    # ① 规划出"应该有哪些片段"
    # plan 格式：{"key": (source_type, source_key, chunk_index), "parent_id": None或父块key,
    #           "title", "role", "content", "content_hash", "is_parent": bool}
    plan = []
    for src in collect_sources(db):
        if src["source_type"] == "document":
            # 父子分块
            for p_idx, (parent_content, children) in enumerate(
                    chunk_parent_child(src["content"], child_size)):
                parent_key = (src["source_type"], src["source_key"], p_idx)
                # 父块（不向量化）
                plan.append({
                    "key": parent_key,
                    "parent_id": None,
                    "title": src["title"],
                    "role": src["role"],
                    "content": parent_content,
                    "content_hash": md5_text(parent_content),
                    "is_parent": True,
                })
                # 子块（向量化）
                for c_idx, child_content in enumerate(children):
                    child_chunk_index = _CHILD_INDEX_OFFSET + p_idx * 1000 + c_idx
                    plan.append({
                        "key": (src["source_type"], src["source_key"], child_chunk_index),
                        "parent_key": parent_key,
                        "title": src["title"],
                        "role": src["role"],
                        "content": child_content,
                        "content_hash": md5_text(child_content),
                        "is_parent": False,
                    })
        else:
            # FAQ：普通块，直接向量化
            plan.append({
                "key": (src["source_type"], src["source_key"], 0),
                "parent_id": None,
                "title": src["title"],
                "role": src["role"],
                "content": src["content"],
                "content_hash": md5_text(src["content"]),
                "is_parent": False,
            })

    existing = {(r.source_type, r.source_key, int(r.chunk_index or 0)): r
                for r in db.query(AiChunk).all()}
    wanted = {p["key"] for p in plan}

    # ② 删掉已不存在的片段
    removed = 0
    for key, row in list(existing.items()):
        if key not in wanted:
            db.delete(row)
            existing.pop(key, None)
            removed += 1

    # ③ 第一遍：创建/更新父块（不向量化），记录父块id
    parent_id_map = {}  # parent_key -> parent_row.id
    skipped = 0
    for p in plan:
        if not p.get("is_parent"):
            continue
        key = p["key"]
        row = existing.get(key)
        if (row is not None and not force
                and row.content_hash == p["content_hash"]
                and (row.title or "") == p["title"]
                and (row.role or "") == p["role"]):
            skipped += 1
        else:
            if row is None:
                row = AiChunk(source_type=p["key"][0], source_key=p["key"][1],
                              chunk_index=p["key"][2], content=p["content"])
                db.add(row)
            row.title = p["title"]
            row.role = p["role"]
            row.content = p["content"]
            row.content_hash = p["content_hash"]
            row.parent_id = None
            row.embedding = None  # 父块不向量化
            row.dim = 0
            row.model = ""
            row.enabled = 1
        db.flush()  # 获取父块id
        parent_id_map[key] = row.id

    # ④ 第二遍：创建/更新子块和FAQ块（向量化）
    pending = []  # [(key, row, p)]
    for p in plan:
        if p.get("is_parent"):
            continue
        key = p["key"]
        row = existing.get(key)
        # 确定 parent_id
        parent_id = None
        if "parent_key" in p:
            parent_id = parent_id_map.get(p["parent_key"])
        if (row is not None and not force
                and row.content_hash == p["content_hash"]
                and int(row.dim or 0) == EMBED_DIM
                and (row.model or "") == model
                and (row.parent_id or 0) == (parent_id or 0)):
            # 内容与模型都没变 → 只同步展示字段
            if (row.title or "") != p["title"] or (row.role or "") != p["role"] \
                    or int(row.enabled or 0) != 1:
                row.title = p["title"]
                row.role = p["role"]
                row.enabled = 1
            skipped += 1
            continue
        pending.append((key, row, p, parent_id))

    # ⑤ 分批向量化（失败即停，已完成的保留）
    added = updated = 0
    errors = ""
    for i in range(0, len(pending), EMBED_BATCH):
        group = pending[i:i + EMBED_BATCH]
        try:
            vecs = embed_texts([p["content"] for _, _, p, _ in group], model)
        except Exception as e:
            errors = str(e)
            break
        for (key, row, p, parent_id), vec in zip(group, vecs):
            if row is None:
                row = AiChunk(source_type=key[0], source_key=key[1],
                              chunk_index=key[2], content=p["content"])
                db.add(row)
                added += 1
            else:
                updated += 1
            row.title = p["title"]
            row.role = p["role"]
            row.content = p["content"]
            row.content_hash = p["content_hash"]
            row.parent_id = parent_id
            row.embedding = json.dumps(vec)
            row.dim = EMBED_DIM
            row.model = model
            row.enabled = 1

    db.commit()

    parent_count = sum(1 for p in plan if p.get("is_parent"))
    child_count = sum(1 for p in plan if not p.get("is_parent"))
    return {
        "model": model, "dim": EMBED_DIM,
        "total": len(plan), "parent_chunks": parent_count, "child_chunks": child_count,
        "added": added, "updated": updated,
        "skipped": skipped, "removed": removed,
        "pending": max(0, len(pending) - added - updated),
        "errors": errors,
    }


# ——————————————————————————————————————————————
# 检索
# ——————————————————————————————————————————————

def search(db, question: str, role: str, top_k: int = 4,
           min_score: float = 0.35) -> list:
    """向量检索（父子分块版）。**失败抛异常**（由 build_rag_context 兜底降级）。

    检索逻辑：
    1. 只检索有向量的块（子块 + FAQ块），父块不参与检索
    2. 命中子块后找到所属父块
    3. AutoMerging：同一父块下命中子块占比超过50%时，自动合并为整个父块
    4. 否则返回命中子块对应的父块（去重）
    5. FAQ块直接返回

    返回 [{"score": float, "chunk": AiChunk}]，按相似度降序。
    chunk 可能是父块（合并后）或FAQ块。
    """
    from models import AiChunk

    question = (question or "").strip()
    if not question:
        return []

    qv = embed_texts([question], _embed_model(db))[0]

    # 只检索有向量的块（子块 parent_id IS NOT NULL + FAQ块 parent_id IS NULL 但有向量）
    rows = (db.query(AiChunk)
            .filter(AiChunk.enabled == 1)
            .filter(AiChunk.embedding.isnot(None))
            .filter(AiChunk.role.in_(["", role or ""]))
            .all())

    # 计算所有子块和FAQ块的相似度
    child_hits = []  # [(score, child_row)]
    faq_hits = []    # [(score, faq_row)]
    for r in rows:
        if not r.embedding:
            continue
        try:
            vec = json.loads(r.embedding)
        except Exception:
            continue
        if not isinstance(vec, list) or len(vec) != len(qv):
            continue
        score = _cosine(qv, vec)
        if score >= min_score:
            if r.parent_id:
                child_hits.append((round(score, 4), r))
            else:
                faq_hits.append((round(score, 4), r))

    # 按相似度降序
    child_hits.sort(key=lambda x: -x[0])
    faq_hits.sort(key=lambda x: -x[0])

    # —— AutoMerging：子块 → 父块 ——
    # 统计每个父块下的子块总数
    all_children = (db.query(AiChunk)
                    .filter(AiChunk.enabled == 1)
                    .filter(AiChunk.parent_id.isnot(None))
                    .all())
    child_count_by_parent = {}
    for c in all_children:
        pid = c.parent_id
        child_count_by_parent[pid] = child_count_by_parent.get(pid, 0) + 1

    # 统计每个父块下命中的子块数和最高相似度
    parent_hits = {}  # parent_id -> {"max_score": float, "hit_count": int, "children": [rows]}
    for score, child in child_hits:
        pid = child.parent_id
        if pid not in parent_hits:
            parent_hits[pid] = {"max_score": score, "hit_count": 0, "children": []}
        parent_hits[pid]["max_score"] = max(parent_hits[pid]["max_score"], score)
        parent_hits[pid]["hit_count"] += 1
        parent_hits[pid]["children"].append(child)

    # 获取父块行
    parent_ids = list(parent_hits.keys())
    parent_rows = {}
    if parent_ids:
        for pr in db.query(AiChunk).filter(AiChunk.id.in_(parent_ids)).all():
            parent_rows[pr.id] = pr

    # 决定返回父块还是子块
    result = []
    for pid, info in parent_hits.items():
        total = child_count_by_parent.get(pid, 1)
        ratio = info["hit_count"] / total if total > 0 else 0
        if ratio >= _AUTOMERGE_RATIO:
            # 命中超过50% → AutoMerging，返回整个父块
            parent_row = parent_rows.get(pid)
            if parent_row:
                result.append({"score": info["max_score"], "chunk": parent_row,
                               "merged": True, "hit_ratio": round(ratio, 2)})
        else:
            # 否则返回命中的子块对应的父块（去重，每个父块只返回一次）
            parent_row = parent_rows.get(pid)
            if parent_row:
                result.append({"score": info["max_score"], "chunk": parent_row,
                               "merged": False, "hit_ratio": round(ratio, 2)})

    # FAQ块直接加入
    for score, faq in faq_hits:
        result.append({"score": score, "chunk": faq, "merged": False, "hit_ratio": 1.0})

    result.sort(key=lambda x: -x["score"])
    return result[:max(1, int(top_k))]


def stats(db) -> dict:
    """索引概况，供后台「知识库索引」页展示。"""
    from models import AiChunk
    rows = db.query(AiChunk).all()
    by_type = {}
    parent_count = 0
    child_count = 0
    for r in rows:
        by_type[r.source_type] = by_type.get(r.source_type, 0) + 1
        if r.parent_id is None and r.source_type == "document":
            parent_count += 1
        elif r.parent_id is not None:
            child_count += 1
    ready = [r for r in rows if r.embedding]
    return {
        "total_chunks": len(rows),
        "parent_chunks": parent_count,
        "child_chunks": child_count,
        "ready_chunks": len(ready),
        "missing_chunks": len(rows) - len(ready),
        "by_type": by_type,
        "chars": sum(len(r.content or "") for r in rows),
        "models": sorted({(r.model or "") for r in rows if r.model}),
        "dims": sorted({int(r.dim or 0) for r in rows if r.dim}),
        "last_built": max((r.updated_at for r in rows if r.updated_at), default=None),
    }


def drop_source(db, source_type: str, source_key: str) -> int:
    """删掉某个来源的全部片段（不 commit）。

    在文档/问答被修改或删除时调用 —— **目的是让 AI 立刻查不到旧内容**。
    宁可让这篇文档暂时检索不到（等管理员重建索引），也不能让 AI 拿着过期条款回答用户。
    """
    from models import AiChunk
    n = (db.query(AiChunk)
         .filter(AiChunk.source_type == source_type)
         .filter(AiChunk.source_key == str(source_key))
         .delete(synchronize_session=False))
    return int(n or 0)


def pending_sources(db) -> list:
    """哪些来源的内容与索引不一致（即「需要重建索引」）。

    判定方式：把每个来源重新切一遍片段（父子分块），与 ai_chunks 里现存的逐条比对
    （数量、content_hash、维度、模型）。**只做本地计算，不调用 embedding 接口**，
    因此后台页面可以随时刷新查看。
    """
    from models import AiChunk

    existing = {}
    for r in db.query(AiChunk).all():
        existing[(r.source_type, r.source_key, int(r.chunk_index or 0))] = r

    child_size = max(60, int(_chunk_size(db) * 0.3))
    model = _embed_model(db)
    out = []
    seen = set()
    for src in collect_sources(db):
        st, sk = src["source_type"], src["source_key"]
        seen.add((st, sk))
        # 用父子分块重新规划
        expected_keys = set()
        if st == "document":
            for p_idx, (parent_content, children) in enumerate(
                    chunk_parent_child(src["content"], child_size)):
                expected_keys.add((st, sk, p_idx))
                for c_idx, _ in enumerate(children):
                    child_idx = _CHILD_INDEX_OFFSET + p_idx * 1000 + c_idx
                    expected_keys.add((st, sk, child_idx))
        else:
            expected_keys.add((st, sk, 0))

        missing = 0
        for key in expected_keys:
            row = existing.get(key)
            if row is None:
                missing += 1
                continue
            # 父块只检查 content_hash
            if key[2] < _CHILD_INDEX_OFFSET and st == "document":
                if row.content_hash != md5_text(row.content or ""):
                    missing += 1
            else:
                # 子块和FAQ检查向量
                if (not row.embedding
                        or int(row.dim or 0) != EMBED_DIM
                        or (row.model or "") != model):
                    missing += 1
        if missing:
            out.append({
                "source_type": st, "source_key": sk, "title": src["title"],
                "expected": len(expected_keys), "outdated": missing,
            })
    # 已被删除的来源：索引里还留着碎片
    orphans = {}
    for (st, sk, _idx) in existing:
        if (st, sk) not in seen:
            orphans[(st, sk)] = orphans.get((st, sk), 0) + 1
    for (st, sk), n in orphans.items():
        out.append({"source_type": st, "source_key": sk, "title": "",
                    "expected": 0, "outdated": n})
    return out



# ——————————————————————————————————————————————
# 提示词注入（向量 + 关键词 融合）
# ——————————————————————————————————————————————

def _keyword_faq_hits(db, question: str, role: str, limit: int = 20) -> list:
    """原有的关键词匹配（复用 ai_service 的实现，保持口径完全一致）"""
    import ai_service
    from models import AiFaq

    rows = (db.query(AiFaq)
            .filter(AiFaq.enabled == 1)
            .filter(AiFaq.role.in_(["", role or ""]))
            .all())
    scored = []
    for r in rows:
        s = ai_service._faq_score(question, ai_service._split_keywords(r.keywords))
        if s > 0:
            scored.append((s, r))
    scored.sort(key=lambda x: (-x[0], x[1].id))
    return scored[:limit]


def build_rag_context(db, user, question: str, record_miss: bool = True,
                      top_k: int = None, min_score: float = None,
                      debug: dict = None) -> str:
    """检索并渲染成提示词片段（支持查询优化：重写+分解+后退）。**任何失败都退回关键词匹配，绝不抛异常。**

    查询优化流程：
    1. 用 query_optimizer 生成多个查询（原问题+改写+子查询+后退）
    2. 对每个查询分别做关键词匹配和向量检索
    3. 所有查询的检索结果用 RRF 融合（同一文档被多个查询命中，分数累加）
    4. 取 top_k 条注入提示词

    为什么做 RRF 融合而不是二选一：
    · 向量检索擅长"换个说法也能找到"，但短句、专有名词上不如字面匹配；
    · 关键词匹配正好相反。
    · 多查询检索让召回更全面，RRF 让多次命中的文档排名更靠前。

    **安全性**：即使向量检索完全失败（没配 Key、索引没建、接口挂了），关键词结果仍会
    照常输出，所以打开本功能不会让召回比原来更差。
    """
    import ai_service
    import query_optimizer
    from models import AiChunk, AiFaq

    question = (question or "").strip()
    if not question:
        return ""
    role = getattr(user, "role", "") or ""

    # —— ① 查询优化：生成多个检索查询 ——
    queries = query_optimizer.generate_queries(db, question, debug)
    if not queries:
        queries = [{"query": question, "type": "original"}]

    # —— ② 对每个查询分别检索 ——
    all_kw_hits = []   # [(score, faq_row, query_index, rank_in_query)]
    all_vec_hits = []  # [{"score", "chunk", "query_index", "rank_in_query", "merged", "hit_ratio"}]
    vector_errors = []

    tk = _top_k(db) if top_k is None else max(1, int(top_k))
    ms = _min_score(db) if min_score is None else float(min_score)

    for qi, qinfo in enumerate(queries):
        q = qinfo["query"]
        # 关键词匹配
        kw = _keyword_faq_hits(db, q, role)
        for rank, (s, r) in enumerate(kw):
            all_kw_hits.append((s, r, qi, rank))
        # 向量检索
        try:
            vec = search(db, q, role, top_k=tk, min_score=ms)
            for rank, h in enumerate(vec):
                all_vec_hits.append({
                    "score": h["score"], "chunk": h["chunk"],
                    "query_index": qi, "rank_in_query": rank,
                    "merged": h.get("merged", False),
                    "hit_ratio": h.get("hit_ratio", 0),
                })
        except Exception as e:
            vector_errors.append(f"[{qinfo.get('type','?')}] {e}")
            print(f"[rag] 向量检索失败（查询{qi}: {q[:30]}），本轮该查询退回关键词匹配：{e}")

    if not all_kw_hits and not all_vec_hits:
        if record_miss:
            ai_service._record_faq_miss(db, question, role)
        return ""

    # —— ③ RRF 融合（所有查询的排名都算入，同一文档多次命中分数累加）——
    pool = {}
    ranks = {}

    for _s, r, _qi, rank in all_kw_hits:
        key = ("faq", str(r.id), 0)
        pool.setdefault(key, {})["faq"] = r
        ranks[key] = ranks.get(key, 0.0) + 1.0 / (RRF_K + rank + 1)

    for h in all_vec_hits:
        c = h["chunk"]
        key = (c.source_type, c.source_key, int(c.chunk_index or 0))
        pool.setdefault(key, {})["chunk"] = c
        ranks[key] = ranks.get(key, 0.0) + 1.0 / (RRF_K + h["rank_in_query"] + 1)

    ordered = sorted(ranks.items(), key=lambda kv: -kv[1])

    # —— ④ 调试信息（「知识库检索测试」页用）——
    if debug is not None:
        # 按查询分组展示检索结果
        per_query = []
        for qi, qinfo in enumerate(queries):
            q_kw = [(s, r) for s, r, qidx, _ in all_kw_hits if qidx == qi]
            q_vec = [h for h in all_vec_hits if h["query_index"] == qi]
            per_query.append({
                "query": qinfo["query"],
                "type": qinfo.get("type", "?"),
                "keyword_hits": [{"id": r.id,
                                  "question": ai_service.render_placeholders(r.question, db),
                                  "score": int(s)}
                                 for s, r in q_kw[:5]],
                "vector_hits": [{
                    "title": h["chunk"].title or "",
                    "score": h["score"],
                    "merged": h.get("merged", False),
                    "hit_ratio": h.get("hit_ratio", 0),
                    "content": ai_service.render_placeholders(h["chunk"].content or "", db)[:100],
                } for h in q_vec[:5]],
            })
        debug.update({
            "vector_error": "; ".join(vector_errors) if vector_errors else "",
            "all_queries": [{"query": q["query"], "type": q.get("type", "?")} for q in queries],
            "per_query_results": per_query,
            "fused_keys": [{
                "source_type": k[0], "source_key": k[1], "chunk_index": k[2],
                "rrf": round(v, 6),
            } for k, v in ordered[:20]],
            "injected_items": 0,
            "injected_chars": 0,
        })

    # —— ⑤ 渲染（最多 top_k 条，且受 ai_rag_max_chars 总长限制）——
    top_k_cap = tk
    limit = _max_chars(db)
    lines, used, picked_faqs = [], 0, []
    for key, _score in ordered:
        if len(lines) >= top_k_cap:
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
        lines.append(text)
        used += len(text)
        if faq_row is not None:
            picked_faqs.append(faq_row)

    if debug is not None:
        debug["injected_items"] = len(lines)
        debug["injected_chars"] = used

    if not lines:
        return ""

    # 命中计数
    for r in picked_faqs:
        try:
            r.hit_count = int(r.hit_count or 0) + 1
        except Exception:
            pass

    header = "【知识库检索结果（与用户本轮提问相关，优先按这里的口径回答）】"
    if vector_errors:
        print(f"[rag] 本轮部分查询向量检索不可用：{'; '.join(vector_errors)}")
    return header + "\n" + "\n".join(lines)
