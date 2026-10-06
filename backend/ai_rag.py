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
    """把长文本切成片段。

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
    """重建向量索引，返回统计信息。

    · 内容 hash 与模型维度都没变的片段**直接跳过**，不调用 embedding 接口（省钱省时）
    · 源内容里已不存在的片段会被删除
    · 向量化中途失败时**保留已成功的部分并返回 errors**（不整批回滚）——
      因为 hash 跳过机制让重跑天然可以断点续传，重跑一次即可补齐
    """
    from models import AiChunk

    model = _embed_model(db)
    size = _chunk_size(db)

    # ① 规划出"应该有哪些片段"
    plan = []
    for src in collect_sources(db):
        for idx, chunk in enumerate(chunk_text(src["content"], size)):
            plan.append({
                "source_type": src["source_type"],
                "source_key": src["source_key"],
                "chunk_index": idx,
                "title": src["title"],
                "role": src["role"],
                "content": chunk,
                "content_hash": md5_text(chunk),
            })

    existing = {(r.source_type, r.source_key, int(r.chunk_index or 0)): r
                for r in db.query(AiChunk).all()}
    wanted = {(p["source_type"], p["source_key"], p["chunk_index"]) for p in plan}

    # ② 删掉已不存在的片段
    removed = 0
    for key, row in list(existing.items()):
        if key not in wanted:
            db.delete(row)
            existing.pop(key, None)
            removed += 1

    # ③ 挑出需要（重新）向量化的片段
    skipped = 0
    pending = []
    for p in plan:
        key = (p["source_type"], p["source_key"], p["chunk_index"])
        row = existing.get(key)
        if (row is not None and not force
                and row.content_hash == p["content_hash"]
                and int(row.dim or 0) == EMBED_DIM
                and (row.model or "") == model):
            # 内容与模型都没变 → 只同步可能改过的展示字段，不花向量钱
            if (row.title or "") != p["title"] or (row.role or "") != p["role"] \
                    or int(row.enabled or 0) != 1:
                row.title = p["title"]
                row.role = p["role"]
                row.enabled = 1
            skipped += 1
            continue
        pending.append((key, row, p))

    # ④ 分批向量化（失败即停，已完成的保留）
    added = updated = 0
    errors = ""
    for i in range(0, len(pending), EMBED_BATCH):
        group = pending[i:i + EMBED_BATCH]
        try:
            vecs = embed_texts([p["content"] for _, _, p in group], model)
        except Exception as e:
            errors = str(e)
            break
        for (key, row, p), vec in zip(group, vecs):
            if row is None:
                row = AiChunk(source_type=p["source_type"], source_key=p["source_key"],
                              chunk_index=p["chunk_index"], content=p["content"])
                db.add(row)
                added += 1
            else:
                updated += 1
            row.title = p["title"]
            row.role = p["role"]
            row.content = p["content"]
            row.content_hash = p["content_hash"]
            row.embedding = json.dumps(vec)
            row.dim = EMBED_DIM
            row.model = model
            row.enabled = 1

    db.commit()

    return {
        "model": model, "dim": EMBED_DIM,
        "total": len(plan), "added": added, "updated": updated,
        "skipped": skipped, "removed": removed,
        "pending": max(0, len(pending) - added - updated),
        "errors": errors,
    }


# ——————————————————————————————————————————————
# 检索
# ——————————————————————————————————————————————

def search(db, question: str, role: str, top_k: int = 4,
           min_score: float = 0.35) -> list:
    """向量检索。**失败抛异常**（由 build_rag_context 兜底降级）。

    返回 [{"score": float, "chunk": AiChunk}]，按相似度降序。
    """
    from models import AiChunk

    question = (question or "").strip()
    if not question:
        return []

    qv = embed_texts([question], _embed_model(db))[0]

    rows = (db.query(AiChunk)
            .filter(AiChunk.enabled == 1)
            .filter(AiChunk.role.in_(["", role or ""]))
            .all())

    hits = []
    for r in rows:
        if not r.embedding:
            continue
        try:
            vec = json.loads(r.embedding)
        except Exception:
            continue
        # 维度不匹配（换过模型又没重建索引）：跳过，否则算出来的是垃圾分数且不会报错
        if not isinstance(vec, list) or len(vec) != len(qv):
            continue
        score = _cosine(qv, vec)
        if score >= min_score:
            hits.append({"score": round(score, 4), "chunk": r})

    hits.sort(key=lambda x: -x["score"])
    return hits[:max(1, int(top_k))]


def stats(db) -> dict:
    """索引概况，供后台「知识库索引」页展示。"""
    from models import AiChunk
    rows = db.query(AiChunk).all()
    by_type = {}
    for r in rows:
        by_type[r.source_type] = by_type.get(r.source_type, 0) + 1
    ready = [r for r in rows if r.embedding]
    return {
        "total_chunks": len(rows),
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

    判定方式：把每个来源重新切一遍片段，与 ai_chunks 里现存的逐条比对
    （数量、content_hash、维度、模型）。**只做本地计算，不调用 embedding 接口**，
    因此后台页面可以随时刷新查看。
    """
    from models import AiChunk

    existing = {}
    for r in db.query(AiChunk).all():
        existing[(r.source_type, r.source_key, int(r.chunk_index or 0))] = r

    size = _chunk_size(db)
    model = _embed_model(db)
    out = []
    seen = set()
    for src in collect_sources(db):
        st, sk = src["source_type"], src["source_key"]
        seen.add((st, sk))
        chunks = chunk_text(src["content"], size)
        missing = 0
        for idx, ch in enumerate(chunks):
            row = existing.get((st, sk, idx))
            if (row is None or not row.embedding
                    or row.content_hash != md5_text(ch)
                    or int(row.dim or 0) != EMBED_DIM
                    or (row.model or "") != model):
                missing += 1
        if missing:
            out.append({
                "source_type": st, "source_key": sk, "title": src["title"],
                "expected": len(chunks), "outdated": missing,
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
    """检索并渲染成提示词片段。**任何失败都退回关键词匹配，绝不抛异常。**

    为什么做 RRF 融合而不是二选一：
    · 向量检索擅长"换个说法也能找到"（用户问"钱什么时候到账"，文档写"结算周期"），
      但短句、专有名词、精确术语上反而不如字面匹配；
    · 关键词匹配正好相反。
    两者排名用 RRF（Reciprocal Rank Fusion）融合 —— 它只看排名不看分数，
    因此不需要在"关键词得分"和"余弦相似度"这两个量纲完全不同的分数之间找换算系数。

    **安全性**：即使向量检索完全失败（没配 Key、索引没建、接口挂了），关键词结果仍会
    照常输出，所以打开本功能不会让召回比原来更差。
    """
    import ai_service
    from models import AiChunk, AiFaq

    question = (question or "").strip()
    if not question:
        return ""
    role = getattr(user, "role", "") or ""

    kw_hits = _keyword_faq_hits(db, question, role)

    vec_hits, vector_error = [], ""
    try:
        vec_hits = search(db, question, role,
                          top_k=_top_k(db) if top_k is None else max(1, int(top_k)),
                          min_score=(_min_score(db) if min_score is None
                                     else float(min_score)))
    except Exception as e:
        vector_error = str(e)
        print(f"[rag] 向量检索失败，本轮退回关键词匹配：{e}")

    if not kw_hits and not vec_hits:
        if record_miss:
            ai_service._record_faq_miss(db, question, role)
        return ""

    # —— RRF 融合 ——
    # 候选池：key → {"faq": AiFaq 行 或 None, "chunk": AiChunk 行 或 None}
    pool = {}
    ranks = {}

    for rank, (_, r) in enumerate(kw_hits):
        key = ("faq", str(r.id), 0)
        pool.setdefault(key, {})["faq"] = r
        ranks[key] = ranks.get(key, 0.0) + 1.0 / (RRF_K + rank + 1)

    for rank, hit in enumerate(vec_hits):
        c = hit["chunk"]
        key = (c.source_type, c.source_key, int(c.chunk_index or 0))
        pool.setdefault(key, {})["chunk"] = c
        ranks[key] = ranks.get(key, 0.0) + 1.0 / (RRF_K + rank + 1)

    ordered = sorted(ranks.items(), key=lambda kv: -kv[1])

    # —— 调试信息（「知识库检索测试」页用；正式问答不传 debug，零开销）——
    # 没有这些分列数据就无法调试检索质量：只看 AI 的最终回答，永远分不清是
    # "根本没检索到" 还是 "检索到了但模型没用"。
    if debug is not None:
        # 这里也过一遍 render_placeholders：否则「检索测试」页会把 {xxx%} 原样显示出来，
        # 管理员会误以为占位符没被替换（实际注入提示词时已替换）
        debug.update({
            "vector_error": vector_error,
            "keyword_hits": [{"id": r.id,
                              "question": ai_service.render_placeholders(r.question, db),
                              "score": int(s)}
                             for s, r in kw_hits],
            "vector_hits": [{
                "source_type": h["chunk"].source_type,
                "source_key": h["chunk"].source_key,
                "chunk_index": int(h["chunk"].chunk_index or 0),
                "title": h["chunk"].title or "",
                "score": h["score"],
                "content": ai_service.render_placeholders(h["chunk"].content or "", db),
            } for h in vec_hits],
            "fused_keys": [{
                "source_type": k[0], "source_key": k[1], "chunk_index": k[2],
                "rrf": round(v, 6),
            } for k, v in ordered],
            "injected_items": 0,
            "injected_chars": 0,
        })

    # —— 渲染（最多 top_k 条，且受 ai_rag_max_chars 总长限制）——
    top_k_cap = _top_k(db) if top_k is None else max(1, int(top_k))
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
            # 文档正文同样过一遍占位符：管理员在长文档里写 {club_commission_rate%}
            # 时能自动跟随系统参数，避免文档里的数字悄悄过期
            text = (f"· 【{chunk.title or '知识库'}】\n  "
                    + ai_service.render_placeholders(chunk.content, db))
        else:
            continue

        # 至少保留第一条，否则限量太小时会一条都进不去、检索等于白做
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

    # 命中计数与调用方的 session 一起在本次请求末尾 commit
    for r in picked_faqs:
        try:
            r.hit_count = int(r.hit_count or 0) + 1
        except Exception:
            pass

    header = "【知识库检索结果（与用户本轮提问相关，优先按这里的口径回答）】"
    if vector_error:
        # 让管理员在后台能看出"这轮为什么只用了关键词"，而不是静默降级
        print(f"[rag] 本轮仅关键词匹配（向量检索不可用）：{vector_error}")
    return header + "\n" + "\n".join(lines)
