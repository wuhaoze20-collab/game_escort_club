# -*- coding: utf-8 -*-
"""AI 知识库（长篇文档）与向量检索的管理接口。

职责：
· 知识库文档的增删改查 —— **仅管理员**。这些是面向用户的协议与规则文本，法律含义强，
   与「提示词管理」同一考虑：属于系统级内容，不适合交给客服改。
· 向量索引的重建 / 统计 / 检索测试 —— 仅管理员。

两个刻意的设计选择：
1. 文档的**管理**仅管理员，但文档的**阅读**对所有已登录角色开放（`/library` 一组接口）。
   用户协议本来就是给用户看的；这个页面同时兼作"改完文档肉眼确认效果"的入口。
2. 文档带 `role` 字段：空 = 所有角色都可检索可阅读；填了角色则只有该角色看得到
   （例如《打手服务规范与行为准则》只给打手看）。

⚠️ 修改文档后索引会**立即失效**（见 `_invalidate`）。宁可让这篇文档暂时检索不到，
也不能让 AI 拿着过期条款回答用户 —— 所以不提供"静默过期"的选项。
"""

import json
import re
import os
import random
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

import ai_rag
from auth import require_roles
from database import get_db
from models import AiChunk, AiEvalFixedSet, KbDocument, User
from schemas import AiRagSearchRequest, KbDocumentCreate, KbDocumentUpdate

router = APIRouter(prefix="/api/ai/kb", tags=["AI 知识库与向量检索"])

VALID_ROLES = ("", "admin", "service", "boss", "player")
ROLE_LABELS = {"": "全角色", "admin": "管理员", "service": "客服",
               "boss": "老板", "player": "打手"}

# doc_key 限制为英文/数字/下划线/短横线：它同时是检索来源 key，
# 允许中文或空格会在日志、调试输出和 URL 里造成麻烦
_DOC_KEY_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_\-]{1,49}$")


def _check_role(role: str) -> str:
    role = (role or "").strip()
    if role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"无效的角色：{role or '(空)'}")
    return role


def _check_doc_key(key: str) -> str:
    key = (key or "").strip()
    if not _DOC_KEY_RE.match(key):
        raise HTTPException(
            status_code=400,
            detail="文档标识只能由字母开头、包含字母/数字/下划线/短横线，长度 2~50"
                   "（它会作为检索来源 key，不能用中文或空格）",
        )
    return key


def _serialize_doc(d: KbDocument, with_content: bool = True) -> dict:
    out = {
        "id": d.id,
        "doc_key": d.doc_key,
        "title": d.title or "",
        "category": d.category or "",
        "role": d.role or "",
        "role_label": ROLE_LABELS.get(d.role or "", d.role or "全角色"),
        "enabled": int(d.enabled or 0),
        "sort_order": int(d.sort_order or 0),
        "version": int(d.version or 1),
        "chars": len(d.content or ""),
        "updated_by": d.updated_by or "",
        "updated_at": d.updated_at.strftime("%Y-%m-%d %H:%M") if d.updated_at else "",
    }
    if with_content:
        out["content"] = d.content or ""
    return out


def _invalidate(db, doc_key: str):
    """文档变更后删掉它的向量片段，并返回受影响片段数。

    不自动重建：重建要调 embedding 接口（有成本、可能失败、耗时随文档变长而增加），
    放在保存请求里会让接口超时。改为让管理员显式点「重建索引」——
    且 hash 跳过机制保证只对改动过的片段花钱。
    """
    n = ai_rag.drop_source(db, "document", doc_key)
    db.commit()
    return n


# ══════════════════════════════════════════════
# 文档管理（仅管理员）
# ══════════════════════════════════════════════

@router.get("/documents")
def list_documents(
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    """扫描文档目录返回文件列表（与 collect_sources 索引来源保持一致）。"""
    items = []
    doc_dir = ai_rag.AGREEMENTS_DIR
    if os.path.isdir(doc_dir):
        for fname in sorted(f for f in os.listdir(doc_dir)
                            if f.lower().endswith(ai_rag._DOC_EXTENSIONS)
                            and not f.startswith("~$")):
            doc_key = os.path.splitext(fname)[0]
            try:
                title, content = ai_rag._read_file(os.path.join(doc_dir, fname))
            except Exception:
                title, content = doc_key, ""
            items.append({
                "doc_key": doc_key,
                "title": title or doc_key,
                "chars": len(content or ""),
                "role": "",
                "role_label": "全角色",
                "filename": fname,
            })
    return {"total": len(items), "items": items}


@router.post("/documents")
def create_document(
    request: KbDocumentCreate,
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    key = _check_doc_key(request.doc_key)
    title = (request.title or "").strip()
    content = (request.content or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="请填写文档标题")
    if not content:
        raise HTTPException(status_code=400, detail="文档正文不能为空")
    if db.query(KbDocument).filter(KbDocument.doc_key == key).first():
        raise HTTPException(status_code=400, detail=f"文档标识已存在：{key}")

    row = KbDocument(
        doc_key=key, title=title[:100], content=content,
        category=(request.category or "").strip()[:50],
        role=_check_role(request.role),
        enabled=1 if request.enabled is None else (1 if int(request.enabled) else 0),
        sort_order=int(request.sort_order or 0),
        version=1, updated_by=current_user.username,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"message": "已新增文档。请点「重建索引」后它才会被 AI 检索到",
            "item": _serialize_doc(row)}


@router.put("/documents/{doc_key}")
def update_document(
    doc_key: str,
    request: KbDocumentUpdate,
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    row = db.query(KbDocument).filter(KbDocument.doc_key == doc_key).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"文档不存在：{doc_key}")

    changed = content_changed = False
    if request.title is not None:
        t = request.title.strip()
        if not t:
            raise HTTPException(status_code=400, detail="文档标题不能为空")
        if t[:100] != (row.title or ""):
            row.title = t[:100]
            changed = True
    if request.content is not None:
        c = request.content.strip()
        if not c:
            raise HTTPException(status_code=400, detail="文档正文不能为空；不想让它生效请把「启用」关掉")
        if c != (row.content or ""):
            row.content = c
            changed = content_changed = True
    if request.category is not None:
        row.category = request.category.strip()[:50]
    if request.role is not None:
        r = _check_role(request.role)
        if r != (row.role or ""):
            row.role = r
            changed = content_changed = True   # role 变了要让旧片段失效，否则会串角色
    if request.enabled is not None:
        e = 1 if int(request.enabled) else 0
        if e != int(row.enabled or 0):
            row.enabled = e
            changed = content_changed = True
    if request.sort_order is not None:
        row.sort_order = int(request.sort_order)

    if changed:
        row.version = int(row.version or 1) + 1
        row.updated_by = current_user.username
    db.commit()

    if content_changed:
        _invalidate(db, row.doc_key)
    db.refresh(row)

    msg = "已保存"
    if content_changed:
        msg = "已保存。正文有改动，原索引已失效，请点「重建索引」后 AI 才能检索到新内容"
    return {"message": msg, "index_stale": content_changed,
            "item": _serialize_doc(row)}


@router.delete("/documents/{doc_key}")
def delete_document(
    doc_key: str,
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    """删除文档文件，同时清除其向量索引片段。"""
    doc_dir = ai_rag.AGREEMENTS_DIR
    deleted_file = None
    if os.path.isdir(doc_dir):
        for fname in os.listdir(doc_dir):
            if os.path.splitext(fname)[0] == doc_key and fname.lower().endswith(ai_rag._DOC_EXTENSIONS):
                os.remove(os.path.join(doc_dir, fname))
                deleted_file = fname
                break
    n = ai_rag.drop_source(db, "document", doc_key)
    db.commit()
    if not deleted_file and n == 0:
        raise HTTPException(status_code=404, detail=f"文档不存在：{doc_key}")
    return {"message": f"已删除文档 {deleted_file or doc_key}，同时清掉 {n} 个索引片段"}


# ══════════════════════════════════════════════
# 文档阅读（所有已登录角色；按 role 过滤）
# ══════════════════════════════════════════════

@router.get("/library")
def list_library(
    current_user: User = Depends(require_roles("admin", "service", "boss", "player")),
    db: Session = Depends(get_db),
):
    role = current_user.role or ""
    rows = (db.query(KbDocument)
            .filter(KbDocument.enabled == 1)
            .filter(KbDocument.role.in_(["", role]))
            .order_by(KbDocument.sort_order.asc(), KbDocument.id.asc()).all())
    return {"total": len(rows),
            "items": [_serialize_doc(d, with_content=False) for d in rows]}


@router.get("/library/{doc_key}")
def read_document(
    doc_key: str,
    current_user: User = Depends(require_roles("admin", "service", "boss", "player")),
    db: Session = Depends(get_db),
):
    role = current_user.role or ""
    row = (db.query(KbDocument)
           .filter(KbDocument.doc_key == doc_key)
           .filter(KbDocument.enabled == 1)
           .filter(KbDocument.role.in_(["", role]))
           .first())
    # 用"查不到"代替"存在但不属于你的角色"，不泄露其他角色规则文档的存在性
    # （与 rating_api 的归属校验同一思路）
    if not row:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"item": _serialize_doc(row)}


# ══════════════════════════════════════════════
# 索引：重建 / 统计 / 片段查看 / 检索测试（仅管理员）
# ══════════════════════════════════════════════
# 文件上传（仅管理员）：上传后自动存入 docs/agreements/ 并重建索引
# ══════════════════════════════════════════════

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".html", ".htm", ".txt", ".md", ".csv", ".json"}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB


def _extract_text_from_file(filepath: str, ext: str) -> str:
    """从上传的文件中提取纯文本，用于 RAG 索引。"""
    ext = ext.lower()
    if ext == ".docx":
        from docx import Document
        doc = Document(filepath)
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    elif ext in (".html", ".htm"):
        from html.parser import HTMLParser
        class _TextExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self.parts = []
                self._skip = False
            def handle_starttag(self, tag, attrs):
                if tag in ("script", "style"):
                    self._skip = True
            def handle_endtag(self, tag):
                if tag in ("script", "style"):
                    self._skip = False
                if tag in ("p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6"):
                    self.parts.append("\n")
            def handle_data(self, data):
                if not self._skip:
                    self.parts.append(data)
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            html_content = f.read()
        parser = _TextExtractor()
        parser.feed(html_content)
        text = "".join(parser.parts)
        return re.sub(r"\n{3,}", "\n\n", text).strip()
    elif ext == ".txt":
        for enc in ("utf-8", "gbk", "gb2312", "latin-1"):
            try:
                with open(filepath, "r", encoding=enc) as f:
                    return f.read().strip()
            except (UnicodeDecodeError, UnicodeError):
                continue
        raise HTTPException(status_code=400, detail="TXT 文件编码无法识别，请转为 UTF-8")
    elif ext == ".pdf":
        # 尝试常见 PDF 库，哪个装了用哪个
        try:
            import pdfplumber
            text_parts = []
            with pdfplumber.open(filepath) as pdf:
                for page in pdf.pages:
                    t = page.extract_text()
                    if t:
                        text_parts.append(t)
            return "\n".join(text_parts).strip()
        except ImportError:
            pass
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(filepath)
            return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        except ImportError:
            pass
        raise HTTPException(
            status_code=400,
            detail="PDF 解析需要安装 pdfplumber 或 PyPDF2："
                   "pip install pdfplumber"
        )
    else:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型：{ext}")


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    """上传文档到知识库：保存到 docs/agreements/，自动提取文本并重建向量索引。

    支持 .pdf / .docx / .html / .htm / .txt，最大 20MB。
    文件名（不含扩展名）作为 source_key，自动参与 RAG 检索。
    """
    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型 {ext}，支持：{' / '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    # 读取文件内容并检查大小
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail=f"文件过大，最大 {MAX_FILE_SIZE // 1024 // 1024}MB")
    if not content:
        raise HTTPException(status_code=400, detail="文件内容为空")

    # 确保目录存在
    os.makedirs(ai_rag.AGREEMENTS_DIR, exist_ok=True)
    save_path = os.path.join(ai_rag.AGREEMENTS_DIR, filename)

    # 保存原始文件
    with open(save_path, "wb") as f:
        f.write(content)

    # 提取文本（验证文件可解析）
    try:
        text = _extract_text_from_file(save_path, ext)
    except HTTPException:
        # 解析失败，删除已保存的文件
        try:
            os.remove(save_path)
        except OSError:
            pass
        raise
    except Exception as e:
        try:
            os.remove(save_path)
        except OSError:
            pass
        raise HTTPException(status_code=400, detail=f"文件解析失败：{e}")

    if not text or len(text.strip()) < 10:
        try:
            os.remove(save_path)
        except OSError:
            pass
        raise HTTPException(status_code=400, detail="文件中未提取到有效文本（可能是扫描件/图片PDF）")

    # 自动重建索引（新文件会被 collect_sources 收集到）
    try:
        result = ai_rag.rebuild_index(db, force=False)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件已保存，但重建索引失败：{e}")

    source_key = os.path.splitext(filename)[0]
    return {
        "message": f"上传成功：{filename}（提取 {len(text)} 字符），索引已更新",
        "filename": filename,
        "source_key": source_key,
        "chars": len(text),
        "index_result": result,
    }


# ══════════════════════════════════════════════
# 索引管理（仅管理员）
# ══════════════════════════════════════════════

@router.post("/rebuild")
def rebuild(
    force: bool = False,
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    """重建向量索引。

    `force=true` 时连未改动的内容也重新向量化（换了模型、怀疑向量损坏时用）。
    默认只处理内容变过的片段，因此可以随时点、对没改的内容零花费。
    """
    if not ai_rag._enabled(db) and not force:
        # 不阻止，只提醒：允许管理员在正式启用前先把索引建好并用检索测试验证
        pass
    try:
        result = ai_rag.rebuild_index(db, force=force)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"重建索引失败：{e}")

    if result["errors"]:
        raise HTTPException(
            status_code=502,
            detail=f"向量化中途失败：{result['errors']}。"
                   f"已完成的 {result['added'] + result['updated']} 段已保存，"
                   f"请检查后端 .env 的 DASHSCOPE_API_KEY 与网络后**再点一次**重建"
                   f"（未改动的片段会跳过，不会重复付费）",
        )
    return {"message": f"索引重建完成：新增 {result['added']} 段、更新 {result['updated']} 段、"
                       f"跳过 {result['skipped']} 段、删除 {result['removed']} 段",
            "result": result}


@router.get("/stats")
def index_stats(
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    s = ai_rag.stats(db)
    pending = ai_rag.pending_sources(db)
    return {
        "enabled": ai_rag._enabled(db),
        "top_k": ai_rag._top_k(db),
        "min_score": ai_rag._min_score(db),
        "embedding_model": ai_rag._embed_model(db),
        "chunk_size": ai_rag._chunk_size(db),
        "max_chars": ai_rag._max_chars(db),
        "total_chunks": s["total_chunks"],
        "ready_chunks": s["ready_chunks"],
        "missing_chunks": s["missing_chunks"],
        "chars": s["chars"],
        "by_type": s["by_type"],
        "models": s["models"],
        "dims": s["dims"],
        "last_built": (s["last_built"].strftime("%Y-%m-%d %H:%M")
                       if s["last_built"] else ""),
        "pending_sources": pending,
        "pending_total": len(pending),
        # 向量存储：当前用的哪种后端，以及 Chroma 集合的实际情况
        # chroma 不可用时前端应提示「已自动降级为 MySQL 全表扫描」
        "vector_backend": s["vector_backend"],
        "chroma": s.get("chroma") or {},
    }


@router.get("/chunks")
def list_chunks(
    source_type: str = "document",
    source_key: str = "",
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    """查看某个来源被切成了哪些片段 —— 分块效果不好时靠它定位。"""
    from models import AiVector
    q = db.query(AiChunk).filter(AiChunk.source_type == source_type)
    if source_key:
        q = q.filter(AiChunk.source_key == source_key)
    rows = q.order_by(AiChunk.source_key.asc(), AiChunk.chunk_index.asc()).all()
    # 预加载向量状态
    vec_by_chunk = {v.chunk_id: v for v in db.query(AiVector).all()}
    return {"total": len(rows), "items": [{
        "id": r.id,
        "source_type": r.source_type,
        "source_key": r.source_key,
        "chunk_index": int(r.chunk_index or 0),
        "title": r.title or "",
        "role": r.role or "",
        "chars": len(r.content or ""),
        "content": r.content or "",
        "ready": vec_by_chunk.get(r.id) is not None,
        "dim": int(vec_by_chunk[r.id].dim or 0) if vec_by_chunk.get(r.id) else 0,
        "model": vec_by_chunk[r.id].model or "" if vec_by_chunk.get(r.id) else "",
        "updated_at": r.updated_at.strftime("%Y-%m-%d %H:%M") if r.updated_at else "",
    } for r in rows]}


@router.post("/search")
def search_test(
    request: AiRagSearchRequest,
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    """检索测试：把"关键词命中 / 向量命中 / 最终注入提示词的文本"全列出来。

    没有这个页面就无法调试检索质量 —— 只看 AI 的最终回答，永远分不清是
    "没检索到" 还是 "检索到了但模型没用"。
    """
    question = (request.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="请输入要测试的提问")
    role = _check_role(request.role) if request.role else (current_user.role or "")

    # 优先用该角色的真实账号，这样 role 过滤与真实问答完全一致
    sample = db.query(User).filter(User.role == role).first()
    if sample is None:
        class _Stub:
            pass
        sample = _Stub()
        sample.username = sample.nickname = f"（无{ROLE_LABELS.get(role, role)}账号）"
        sample.role = role
        sample.role_name = ROLE_LABELS.get(role, role)

    debug = {}
    text = ai_rag.build_rag_context(
        db, sample, question, record_miss=False,
        top_k=request.top_k, min_score=request.min_score,
        debug=debug,
    )
    db.commit()   # 把命中的 hit_count 落库

    return {
        "question": question,
        "role": role,
        "role_label": ROLE_LABELS.get(role, role),
        "sample_user": getattr(sample, "username", "") or "",
        "enabled": ai_rag._enabled(db),
        "top_k": ai_rag._top_k(db) if request.top_k is None else request.top_k,
        "min_score": ai_rag._min_score(db) if request.min_score is None else request.min_score,
        "vector_error": debug.get("vector_error", ""),
        "keyword_hits": debug.get("keyword_hits", []),
        "vector_hits": debug.get("vector_hits", []),
        "fused_keys": debug.get("fused_keys", []),
        "injected_items": debug.get("injected_items", 0),
        "injected_chars": debug.get("injected_chars", 0),
        "injected_text": text,
    }


# ══════════════════════════════════════════════
# RAG 量化评估（仅管理员）
# ══════════════════════════════════════════════

# 进程内缓存最近一次评估结果，避免前端刷新时重复跑评估
_last_eval_result: dict = {}


@router.get("/eval/questions")
def list_eval_questions(
    role: str = None,
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    """获取测试题库列表（从数据库读取，支持按角色筛选）。"""
    from models import AiEvalQuestion
    query = db.query(AiEvalQuestion)
    if role:
        query = query.filter(AiEvalQuestion.role == role)
    rows = query.order_by(AiEvalQuestion.id.asc()).all()
    return {
        "total": len(rows),
        "items": [{
            "id": r.id,
            "question": r.question,
            "ground_truth": r.ground_truth,
            "role": r.role,
            "category": r.category,
            "query_type": r.query_type or "fact",
            "enabled": r.enabled,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in rows],
    }


@router.post("/eval/questions")
def create_eval_question(
    data: dict,
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    """新增一道测试题。"""
    from models import AiEvalQuestion
    from rag_eval import _guess_category, QUERY_TYPES
    question = (data.get("question") or "").strip()
    ground_truth = (data.get("ground_truth") or "").strip()
    role = data.get("role", "boss")
    if not question or not ground_truth:
        raise HTTPException(status_code=400, detail="问题和标准答案不能为空")
    if role not in ("boss", "player", "admin", "service"):
        raise HTTPException(status_code=400, detail="角色必须是 boss/player/admin/service")
    query_type = data.get("query_type", "fact")
    if query_type not in QUERY_TYPES:
        raise HTTPException(status_code=400, detail="查询类型必须是 fact/reason/compare")
    q = AiEvalQuestion(
        question=question,
        ground_truth=ground_truth,
        role=role,
        category=data.get("category") or _guess_category(question),
        query_type=query_type,
        enabled=int(data.get("enabled", 1)),
    )
    db.add(q)
    db.commit()
    db.refresh(q)
    return {"message": "添加成功", "id": q.id}


@router.put("/eval/questions/{qid}")
def update_eval_question(
    qid: int,
    data: dict,
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    """修改一道测试题。"""
    from models import AiEvalQuestion
    q = db.query(AiEvalQuestion).filter(AiEvalQuestion.id == qid).first()
    if not q:
        raise HTTPException(status_code=404, detail="题目不存在")
    if "question" in data:
        q.question = data["question"].strip()
    if "ground_truth" in data:
        q.ground_truth = data["ground_truth"].strip()
    if "role" in data:
        q.role = data["role"]
    if "category" in data:
        q.category = data["category"]
    if "query_type" in data:
        from rag_eval import QUERY_TYPES
        if data["query_type"] not in QUERY_TYPES:
            raise HTTPException(status_code=400, detail="查询类型必须是 fact/reason/compare")
        q.query_type = data["query_type"]
    if "enabled" in data:
        q.enabled = int(data["enabled"])
    db.commit()
    return {"message": "修改成功"}


@router.delete("/eval/questions/{qid}")
def delete_eval_question(
    qid: int,
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    """删除一道测试题。"""
    from models import AiEvalQuestion
    q = db.query(AiEvalQuestion).filter(AiEvalQuestion.id == qid).first()
    if not q:
        raise HTTPException(status_code=404, detail="题目不存在")
    db.delete(q)
    db.commit()
    return {"message": "删除成功"}


# ============================================================
# 评估数据集构建：分层抽样
#
# 评估数据集要满足三条原则，而抽题方式直接决定前两条能不能成立：
#   覆盖性 —— 事实型 / 推理型 / 对比型查询全覆盖
#   代表性 —— 贴合真实用户查询分布
#
# 纯等概率随机抽样做不到这两点：题库里"只有 1 道题的类型"被整类漏掉的
# 概率高达 75%（C(19,5)/C(20,5) ≈ 0.75），而等概率抽样还隐含假设
# "四类角色的提问量相同"，与线上实际情况不符。
# 所以改成两层分层抽样：先保题型覆盖，再按真实角色分布配额。
# ============================================================

# 真实提问样本少于这个数就不拿它当配额依据（退回均匀分配）
MIN_ROLE_SAMPLES = 10


def _real_role_weights(db) -> dict:
    """统计真实用户提问的角色分布，作为抽题配额依据。

    按「会话数」而不是「消息数」统计：一个用户可能在一个会话里连问十几条，
    按消息数会让活跃用户被过度放大，会话数更接近"有多少个提问场景"。
    """
    from sqlalchemy import func
    from models import AiConversation

    rows = (db.query(User.role, func.count(AiConversation.id))
              .join(AiConversation, AiConversation.username == User.username)
              .group_by(User.role).all())
    weights = {str(r): int(c or 0) for r, c in rows if r and c}
    total = sum(weights.values())
    # 样本太少不足为据（几条自测数据就能把配比带偏），退回均匀分配
    if total < MIN_ROLE_SAMPLES:
        return {}
    return weights


def _largest_remainder(weights: dict, total: int) -> dict:
    """按权重把 total 个名额分给各项（最大余数法）。

    不能直接 round(权重占比 × 总数)：各项四舍五入后之和常常不等于总数
    （都进位就超了、都舍去就不够）。最大余数法先各自取整发基础名额，
    剩余名额按小数部分从大到小补，保证总数刚好等于 total。
    """
    items = [(k, max(0.0, float(v or 0))) for k, v in weights.items()]
    if not items:
        return {}
    s = sum(v for _, v in items)
    if s <= 0:
        # 权重全为 0：退化为均匀分配
        base = {k: total // len(items) for k, _ in items}
        rest = total - sum(base.values())
        for k, _ in items:
            if rest <= 0:
                break
            base[k] += 1
            rest -= 1
        return base

    raw = {k: v / s * total for k, v in items}
    base = {k: int(v) for k, v in raw.items()}
    rest = total - sum(base.values())
    for k, _ in sorted(raw.items(), key=lambda kv: -(kv[1] - int(kv[1]))):
        if rest <= 0:
            break
        base[k] += 1
        rest -= 1
    return base


def _stratified_sample(pool: list, n: int, role_weights: dict = None) -> list:
    """分层抽样：题型保底 → 角色保底 → 按真实分布配额。

    对应评估数据集的两条原则：
      覆盖性 —— 事实型/推理型/对比型各保底 1 道，每个角色的题也保底 1 道
      代表性 —— 剩余名额按真实用户提问的角色分布分配

    层内随机取题。名额不够时按"题型保底 > 角色保底 > 真实配额 > 随机填充"
    的顺序退让。

    参数：
        pool: 候选题列表（每项含 id / role / query_type）
        n: 要抽几道
        role_weights: 各角色真实提问权重；空 dict 表示退回均匀分配
    """
    pool = [q for q in pool if q.get("id")]
    n = max(1, min(int(n), len(pool)))
    picked, chosen = [], set()

    def take(candidates):
        """从候选里随机取一道还没选过的题；取不到返回 None。"""
        rest = [q for q in candidates if q["id"] not in chosen]
        if not rest:
            return None
        q = random.choice(rest)
        chosen.add(q["id"])
        picked.append(q)
        return q

    # —— 第一层：题型保底（覆盖性）——
    # 每类先占 1 个名额，避免"唯一的对比型题没抽到 → 整类缺失"。
    by_type = {}
    for q in pool:
        by_type.setdefault(q.get("query_type") or "fact", []).append(q)
    # 题数少的类型优先保底：名额有限时先救"更容易被整类漏掉"的那类
    for qtype in sorted(by_type, key=lambda t: len(by_type[t])):
        if len(picked) >= n:
            break
        take(by_type[qtype])

    # —— 第二层：角色保底（覆盖性）——
    # 每个角色的题至少露一次面。真实分布里"客服提问很少"（实测 service
    # 占比个位数），只按权重配额的话客服题会长期一道都考不到，等于客服
    # 场景没人监控。所以先各保 1 道，剩余名额再按真实分布分配。
    by_role = {}
    for q in pool:
        by_role.setdefault(q.get("role") or "boss", []).append(q)
    roles = [r for r in by_role if by_role[r]]
    for r in sorted(roles, key=lambda x: len(by_role[x])):  # 题少的角色先保
        if len(picked) >= n:
            break
        take(by_role[r])

    # —— 第三层：角色真实分布配额（代表性）——
    if roles and len(picked) < n:
        left = n - len(picked)
        weights = role_weights or {r: 1 for r in roles}
        quota = _largest_remainder({r: weights.get(r, 0) for r in roles}, left)
        # 名额多的先抽，避免后面名额被占满
        for r in sorted(roles, key=lambda x: -quota.get(x, 0)):
            for _ in range(quota.get(r, 0)):
                if len(picked) >= n:
                    break
                take(by_role[r])

    # —— 兜底：某角色题库不够 / 配额落空时，全池随机补满 ——
    while len(picked) < n:
        if take(pool) is None:
            break
    return picked


# ============================================================
# 固定题集：抽一次就固定住，后续评估一直复用同一批题
#
# 为什么不每次重抽：题库里各题难度差异很大（实测标准差约 0.25），
# 抽 5 题时，两次评估光凭"抽题运气"就能差出约 0.16，比参数优化通常
# 带来的提升（0.05~0.10）还大 —— 那样 A/B 对比反映的是抽题差异，
# 不是参数效果。固定下来之后，两次评估的题目完全一致，对比才可信。
#
# V4.7.0 起每次抽题新增一行并保留历史（不再覆盖），带版本号，
# 这样"上个月那次评估用的是哪批题"才还原得出来。
# ============================================================

def _safe_json(raw) -> dict:
    """把表里存的 JSON 字符串安全解析成 dict（脏数据不抛异常）。"""
    try:
        val = json.loads(raw or "{}")
        return val if isinstance(val, dict) else {}
    except Exception:
        return {}


def _fixed_set_payload(db) -> dict:
    """组装固定题集的响应：抽取信息 + 题目详情（按当前题库实时展开）。"""
    from rag_eval import get_test_questions

    pool = get_test_questions(db, role=None)  # 当前启用的全部题目（带 id）
    id_map = {q["id"]: q for q in pool}
    row = db.query(AiEvalFixedSet).order_by(AiEvalFixedSet.id.desc()).first()

    if row is None:
        return {"exists": False, "sample_size": 0, "created_at": "",
                "created_by": "", "total_pool": len(pool),
                "questions": [], "missing": []}

    try:
        ids = json.loads(row.question_ids or "[]")
    except Exception:
        ids = []

    questions, missing = [], []
    for qid in ids:
        q = id_map.get(qid)
        if q is None:
            missing.append(qid)  # 题目被删除或被禁用了
        else:
            questions.append({"id": q["id"], "question": q["question"],
                              "role": q["role"], "category": q["category"],
                              "query_type": q.get("query_type") or "fact"})

    # 本次题集的实际构成：实时统计，题目被禁用后这里会同步反映
    role_dist, qtype_dist = {}, {}
    for q in questions:
        role_dist[q["role"]] = role_dist.get(q["role"], 0) + 1
        qtype_dist[q["query_type"]] = qtype_dist.get(q["query_type"], 0) + 1

    return {
        "exists": bool(ids),
        "sample_size": row.sample_size or len(ids),
        "version": row.version or 0,
        "created_at": row.created_at.strftime("%Y-%m-%d %H:%M") if row.created_at else "",
        "created_by": row.created_by or "",
        "total_pool": len(pool),
        "questions": questions,
        "missing": missing,
        "role_dist": role_dist,
        "query_type_dist": qtype_dist,
    }


@router.get("/eval/fixed-set")
def get_fixed_set(
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    """读取当前固定的评估题集。"""
    return _fixed_set_payload(db)


@router.post("/eval/fixed-set")
def draw_fixed_set(
    sample_size: int = 10,
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    """重新抽一批固定题集（保留历史，不再覆盖）。

    抽样方式（V4.7.0 起改为分层抽样）：
      · 先按查询类型保底 —— 事实型/推理型/对比型每类至少 1 道（覆盖性）
      · 剩余名额按真实用户提问的角色分布分配（代表性）
      · 层内随机，避免每次都抽到同一批

    抽完即固定：之后每次评估都用这批题，直到再次调用本接口。
    每次抽题新增一行并递增版本号，历史版本仍可在「题集版本」里查到。
    """
    from rag_eval import get_test_questions

    pool = get_test_questions(db, role=None)
    if not pool:
        raise HTTPException(status_code=400, detail="题库为空，无法抽题")

    n = max(1, min(int(sample_size or 10), len(pool)))
    weights = _real_role_weights(db)
    picked = _stratified_sample(pool, n, weights)

    # 版本号 = 上一版 + 1（首次为 1）
    last = db.query(AiEvalFixedSet).order_by(AiEvalFixedSet.id.desc()).first()
    next_version = (int(last.version or 0) + 1) if last else 1

    role_dist, qtype_dist = {}, {}
    for q in picked:
        role_dist[q["role"]] = role_dist.get(q["role"], 0) + 1
        qt = q.get("query_type") or "fact"
        qtype_dist[qt] = qtype_dist.get(qt, 0) + 1

    row = AiEvalFixedSet(
        question_ids=json.dumps([q["id"] for q in picked]),
        sample_size=len(picked),
        version=next_version,
        role_dist=json.dumps(role_dist, ensure_ascii=False),
        query_type_dist=json.dumps(qtype_dist, ensure_ascii=False),
        created_at=datetime.now(),
        created_by=current_user.username,
    )
    db.add(row)
    db.commit()

    return _fixed_set_payload(db)


@router.get("/eval/fixed-set/history")
def get_fixed_set_history(
    limit: int = 20,
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    """列出历史题集版本（最新在前）。

    题目在库里可能被改过或删过，所以这里同时返回抽题当时存下的分布快照，
    用于回溯"那一版到底考了什么"。
    """
    rows = (db.query(AiEvalFixedSet)
              .order_by(AiEvalFixedSet.id.desc())
              .limit(max(1, min(int(limit or 20), 100))).all())
    out = []
    for r in rows:
        try:
            ids = json.loads(r.question_ids or "[]")
        except Exception:
            ids = []
        out.append({
            "version": r.version or 0,
            "sample_size": r.sample_size or len(ids),
            "question_ids": ids,
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "",
            "created_by": r.created_by or "",
            "role_dist": _safe_json(r.role_dist),
            "query_type_dist": _safe_json(r.query_type_dist),
        })
    return {"total": len(out), "items": out}


@router.get("/eval/role-distribution")
def get_role_distribution(
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    """真实用户提问的角色分布 vs 题库的角色分布。

    用来回答"这套评估到底代不代表真实用户"：真实分布从 AI 会话统计，
    题库分布从当前启用的题目统计。两者偏差大，说明评估的构成和线上
    实际场景不一致，就该调整题库配额（而不是靠抽样去补）。
    """
    from sqlalchemy import func
    from models import AiConversation
    from rag_eval import get_test_questions

    rows = (db.query(User.role, func.count(AiConversation.id))
              .join(AiConversation, AiConversation.username == User.username)
              .group_by(User.role).all())
    real = {str(r): int(c or 0) for r, c in rows if r and c}
    real_total = sum(real.values())

    pool = get_test_questions(db, role=None)
    bank = {}
    for q in pool:
        bank[q["role"]] = bank.get(q["role"], 0) + 1
    bank_total = sum(bank.values())

    def _pct(dist, total):
        if not total:
            return {}
        return {k: round(v * 100.0 / total, 1) for k, v in dist.items()}

    return {
        "real": real,
        "real_pct": _pct(real, real_total),
        "real_total": real_total,
        "bank": bank,
        "bank_pct": _pct(bank, bank_total),
        "bank_total": bank_total,
        # 真实样本够不够作为抽样配额依据（不够则抽样退回均匀分配）
        "used_for_sampling": real_total >= MIN_ROLE_SAMPLES,
        "min_samples": MIN_ROLE_SAMPLES,
    }


@router.post("/eval/run")
def run_eval(
    generate_answer: bool = True,
    role: str = "boss",
    sample_size: int = 10,
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    """运行 RAG 量化评估，返回三个核心指标的得分。

    参数：
        generate_answer: 是否调用大模型生成答案并计算端到端语义相似度（默认 True，较慢）
        role: 以哪个角色的题库评估（boss/player/service/admin）；
              传空或 all 表示评估全部启用的题目；
              传 random 表示用「固定题集」里的题评估（题集在「随机选题」页抽取）
        sample_size: 已废弃，保留仅为兼容旧调用；抽题数量改在「随机选题」页设置

    评估指标：
        - Context Precision：检索到的片段中，与标准答案相关的占比
        - Context Recall：标准答案的关键信息，有多少被检索到了
        - 语义相似度：AI 答案 vs 标准答案（仅 generate_answer=True 时计算）
    """
    global _last_eval_result
    from rag_eval import evaluate_rag, get_test_questions

    try:
        if role == "random":
            # 混合随机检测：用「固定题集」里的题，而不是每次重新抽。
            # 每次重抽会让两次评估的题目不同，指标差异里就混进了题目难度差异，
            # 分不清是参数改动带来的还是抽题运气。题集由「随机选题」页控制。
            all_q = get_test_questions(db, role=None)
            if not all_q:
                raise HTTPException(status_code=400, detail="题库为空，无法评估")
            fixed = _fixed_set_payload(db)
            if not fixed["exists"]:
                raise HTTPException(
                    status_code=400,
                    detail="尚未抽取固定题集，请先到「随机选题」页抽题")
            id_map = {q["id"]: q for q in all_q}
            test_set = [id_map[q["id"]] for q in fixed["questions"]
                        if q["id"] in id_map]
            if not test_set:
                raise HTTPException(
                    status_code=400,
                    detail="固定题集里的题目已被删除或禁用，请重新抽题")
            # 每题仍用自己的 role 去检索（q_role 在 evaluate_rag 内决定）
            result = evaluate_rag(db, test_set=test_set, role="random",
                                  generate_answer=generate_answer,
                                  fixed_set_version=fixed.get("version", 0))
        else:
            # role 为空或 all 时不按角色过滤；否则校验角色合法性
            role = _check_role(role) if role and role != "all" else "all"
            result = evaluate_rag(db, test_set=None, role=role,
                                  generate_answer=generate_answer)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"评估失败：{e}")

    _last_eval_result = result
    return result


@router.get("/eval/last")
def get_last_eval(
    current_user: User = Depends(require_roles("admin")),
):
    """获取最近一次评估结果（不重新跑）。"""
    if not _last_eval_result:
        return {"available": False, "message": "还没有运行过评估，请先点「运行评估」"}
    return {"available": True, "result": _last_eval_result}


@router.get("/eval/history")
def list_eval_history(
    limit: int = 20,
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    """获取最近的评估历史记录列表（不含逐题详情）。"""
    import rag_eval
    history = rag_eval.get_eval_history(db, limit=limit)
    return {"total": len(history), "items": history}


@router.get("/eval/history/{eval_id}")
def get_eval_detail(
    eval_id: int,
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    """获取单次评估的完整详情（含逐题详情）。"""
    import rag_eval
    detail = rag_eval.get_eval_detail(db, eval_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"评估记录 {eval_id} 不存在")
    return detail


@router.get("/eval/compare")
def compare_eval(
    a: int,
    b: int,
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    """A/B 对比两次评估结果，返回各指标差异。

    参数：
        a: 第一次评估的 ID
        b: 第二次评估的 ID

    返回：
        两次评估的基本信息 + 5 个指标的数值对比 + 变化量（B - A）
        自动按时间排序：ID 小（时间旧）的为 A（优化前），ID 大（时间新）的为 B（优化后）
    """
    import rag_eval
    detail_a = rag_eval.get_eval_detail(db, a)
    detail_b = rag_eval.get_eval_detail(db, b)
    if not detail_a:
        raise HTTPException(status_code=404, detail=f"评估记录 {a} 不存在")
    if not detail_b:
        raise HTTPException(status_code=404, detail=f"评估记录 {b} 不存在")

    # 自动按 ID（即时间先后）排序：旧的是 A（优化前），新的是 B（优化后）
    if detail_a.get("id", 0) > detail_b.get("id", 0):
        detail_a, detail_b = detail_b, detail_a

    metrics = [
        ("avg_precision", "检索精确率"),
        ("avg_recall", "检索召回率"),
        ("avg_similarity", "端到端相似度"),
        ("avg_faithfulness", "忠实度"),
        ("avg_answer_relevancy", "答案相关性"),
    ]
    comparison = []
    for key, label in metrics:
        va = detail_a.get(key)
        vb = detail_b.get(key)
        diff = None
        if va is not None and vb is not None:
            diff = round(vb - va, 4)
        comparison.append({
            "key": key,
            "label": label,
            "value_a": va,
            "value_b": vb,
            "diff": diff,
            "better": "up" if (diff is not None and diff > 0) else ("down" if (diff is not None and diff < 0) else "same"),
        })

    return {
        "a": {"id": detail_a.get("id"), "created_at": detail_a.get("created_at"),
              "rerank_mode": detail_a.get("rerank_mode"),
              "role": detail_a.get("role"), "total": detail_a.get("total"),
              "config_snapshot": detail_a.get("config_snapshot", {})},
        "b": {"id": detail_b.get("id"), "created_at": detail_b.get("created_at"),
              "rerank_mode": detail_b.get("rerank_mode"),
              "role": detail_b.get("role"), "total": detail_b.get("total"),
              "config_snapshot": detail_b.get("config_snapshot", {})},
        "metrics": comparison,
    }
