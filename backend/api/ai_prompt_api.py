# -*- coding: utf-8 -*-
"""AI 提示词与问答库的管理接口。

权限划分（刻意不同）：
· `ai_prompts`（系统提示词段落）—— **仅管理员**。这段文本里含各角色权限清单与
  提示注入防御规则，属于系统级配置，不适合让所有客服看到/改动。
· `ai_faqs`（问答库）—— **管理员 + 客服**。问答内容是面向用户的业务口径，
  客服最清楚用户常问什么，应当由他们维护（与「台词管理」同一思路）。

设计要点：
1. 提示词的**出厂内容**留在 `ai_service.PROMPT_SECTIONS`，这里提供「恢复默认」
   把它写回数据库，因此改坏了随时能还原。
2. 每次保存 `version += 1` 并记录 `updated_by`，配合 ai_messages 可回溯
   "哪一版提示词答错了"。
3. FAQ 答案里的 `{config_key}` 占位符会做**保存时校验**：引用了不存在的参数
   直接 400 报错，而不是等注入时静默留下 `{typo}` 让 AI 照念。
"""

import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import ai_service
import config_service
from auth import require_roles
from database import get_db
from models import AiFaq, AiFaqMiss, AiPrompt, User
from schemas import (AiFaqBatchImport, AiFaqCreate, AiFaqUpdate,
                     AiPromptUpdate)

router = APIRouter(prefix="/api/ai", tags=["AI 提示词与问答库"])

VALID_ROLES = ("", "admin", "service", "boss", "player")
ROLE_LABELS = {"": "全角色", "admin": "管理员", "service": "客服",
               "boss": "老板", "player": "打手"}

_PLACEHOLDER_RE = re.compile(r"\{([a-z][a-z0-9_]*)(%?)\}")


def _check_role(role: str) -> str:
    role = (role or "").strip()
    if role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"无效的角色：{role or '(空)'}")
    return role


def _check_placeholders(*texts: str):
    """校验占位符引用的都是真实存在的系统参数，避免写出永远不会被替换的 {xxx}"""
    bad = set()
    for t in texts:
        for m in _PLACEHOLDER_RE.finditer(t or ""):
            key = m.group(1)
            if key not in config_service.CONFIG_META:
                bad.add(key)
    if bad:
        raise HTTPException(
            status_code=400,
            detail="以下占位符不是有效的系统参数，请检查拼写：" + "、".join(sorted(bad))
                   + "（可用参数见「系统设置 → 系统参数」页）",
        )


# ══════════════════════════════════════════════
# 提示词段落
# ══════════════════════════════════════════════

def _serialize_prompt(row: AiPrompt, defaults: dict) -> dict:
    d = defaults.get(row.section_key, {})
    return {
        "section_key": row.section_key,
        "title": row.title or d.get("title", ""),
        "content": row.content,
        "role": row.role or "",
        "role_label": ROLE_LABELS.get(row.role or "", row.role or "全角色"),
        "priority": int(row.priority or 0),
        "enabled": int(row.enabled or 0),
        "version": int(row.version or 1),
        "updated_by": row.updated_by or "",
        "updated_at": row.updated_at.strftime("%Y-%m-%d %H:%M") if row.updated_at else "",
        # 出厂内容一并返回，前端「恢复默认」前可以先对比差异
        "default_content": d.get("content", ""),
        "modified": bool(d) and (row.content or "").strip() != d.get("content", "").strip(),
    }


# 列出所有提示词段落（仅管理员）
@router.get("/prompts")
def list_prompts(
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    defaults = {s["key"]: s for s in ai_service.PROMPT_SECTIONS}
    rows = db.query(AiPrompt).order_by(AiPrompt.priority.asc(), AiPrompt.id.asc()).all()
    # 库为空时（例如有人清了表）用出厂段落兜底展示，避免页面空白
    if not rows:
        return {
            "total": len(ai_service.PROMPT_SECTIONS),
            "source": "default",
            "items": [dict(
                section_key=s["key"], title=s.get("title", ""), content=s["content"],
                role=s.get("role", ""), role_label="全角色",
                priority=s.get("priority", 100), enabled=1, version=1,
                updated_by="system", updated_at="", default_content=s["content"],
                modified=False,
            ) for s in ai_service.PROMPT_SECTIONS],
        }
    return {"total": len(rows), "source": "database",
            "items": [_serialize_prompt(r, defaults) for r in rows]}


# 修改某个段落（仅管理员）
@router.put("/prompts/{section_key}")
def update_prompt(
    section_key: str,
    request: AiPromptUpdate,
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    row = db.query(AiPrompt).filter(AiPrompt.section_key == section_key).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"提示词段落不存在：{section_key}")

    content = row.content
    if request.content is not None:
        content = request.content.strip()
        if not content:
            raise HTTPException(status_code=400,
                                detail="段落内容不能为空；如果不想让它生效，请把「启用」关掉")
    _check_placeholders(content)

    changed = False
    if request.content is not None and content != row.content:
        row.content = content
        changed = True
    if request.title is not None and request.title.strip() != (row.title or ""):
        row.title = request.title.strip()[:100]
        changed = True
    if request.role is not None:
        r = _check_role(request.role)
        if r != (row.role or ""):
            row.role = r
            changed = True
    if request.priority is not None and int(request.priority) != int(row.priority or 0):
        row.priority = int(request.priority)
        changed = True
    if request.enabled is not None:
        e = 1 if int(request.enabled) else 0
        if e != int(row.enabled or 0):
            row.enabled = e
            changed = True

    if changed:
        row.version = int(row.version or 1) + 1
        row.updated_by = current_user.username
    db.commit()
    db.refresh(row)

    defaults = {s["key"]: s for s in ai_service.PROMPT_SECTIONS}
    return {"message": "已保存" if changed else "内容无变化",
            "item": _serialize_prompt(row, defaults)}


# 恢复出厂内容（仅管理员）
@router.post("/prompts/{section_key}/reset")
def reset_prompt(
    section_key: str,
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    d = {s["key"]: s for s in ai_service.PROMPT_SECTIONS}.get(section_key)
    if not d:
        raise HTTPException(status_code=400,
                            detail=f"「{section_key}」没有出厂内容可恢复（自定义段落只能删除或停用）")
    row = db.query(AiPrompt).filter(AiPrompt.section_key == section_key).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"提示词段落不存在：{section_key}")

    row.content = d["content"]
    row.title = d.get("title", row.title)
    row.priority = d.get("priority", row.priority)
    row.role = d.get("role", "")
    row.enabled = 1
    row.version = int(row.version or 1) + 1
    row.updated_by = current_user.username
    db.commit()
    db.refresh(row)
    return {"message": "已恢复出厂内容", "item": _serialize_prompt(row, {section_key: d})}


# 预览：按角色（可选带一句提问）真正拼一次系统提示词，用于调试提示词效果
@router.get("/prompts/preview")
def preview_prompt(
    role: str = "boss",
    question: str = "",
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    role = _check_role(role)
    # 优先用该角色的真实账号（能看到真实昵称/菜单），没有就退回一个临时对象
    sample = db.query(User).filter(User.role == role).first()
    if sample:
        prompt = ai_service.build_system_prompt(db, sample, (question or "").strip())
        shown_as = sample.username
    else:
        class _Stub:
            pass
        s = _Stub()
        s.username = s.nickname = f"（无{ROLE_LABELS.get(role, role)}账号，用占位名预览）"
        s.role = role
        s.role_name = ROLE_LABELS.get(role, role)
        prompt = ai_service.build_system_prompt(db, s, (question or "").strip())
        shown_as = "(占位)"

    faq_hits = []
    if (question or "").strip():
        from models import AiFaq as _F
        rows = (db.query(_F).filter(_F.enabled == 1)
                .filter(_F.role.in_(["", role])).all())
        scored = []
        for r in rows:
            s = ai_service._faq_score(question, ai_service._split_keywords(r.keywords))
            if s > 0:
                scored.append((s, r.question))
        scored.sort(key=lambda x: -x[0])
        faq_hits = [q for _, q in scored]

    return {
        "role": role,
        "role_label": ROLE_LABELS.get(role, role),
        "sample_user": shown_as,
        "question": question or "",
        "length": len(prompt),
        "faq_hit_count": len(faq_hits),
        "faq_hits": faq_hits,
        "prompt": prompt,
    }


# ══════════════════════════════════════════════
# 问答库
# ══════════════════════════════════════════════

def _serialize_faq(r: AiFaq) -> dict:
    return {
        "id": r.id,
        "question": r.question,
        "keywords": r.keywords or "",
        "answer": r.answer,
        "category": r.category or "",
        "role": r.role or "",
        "role_label": ROLE_LABELS.get(r.role or "", r.role or "全角色"),
        "enabled": int(r.enabled or 0),
        "hit_count": int(r.hit_count or 0),
        "updated_at": r.updated_at.strftime("%Y-%m-%d %H:%M") if r.updated_at else "",
    }


@router.get("/faqs")
def list_faqs(
    current_user: User = Depends(require_roles("admin", "service")),
    db: Session = Depends(get_db),
):
    rows = (db.query(AiFaq)
            .order_by(AiFaq.category.asc(), AiFaq.id.asc()).all())
    return {"total": len(rows), "items": [_serialize_faq(r) for r in rows]}


# 未命中提问：问答库的反馈闭环 —— 看用户实际在问什么，据此补问答
@router.get("/faqs/misses")
def list_faq_misses(
    current_user: User = Depends(require_roles("admin", "service")),
    db: Session = Depends(get_db),
):
    rows = (db.query(AiFaqMiss)
            .order_by(AiFaqMiss.count.desc(), AiFaqMiss.last_at.desc())
            .limit(100).all())
    return {"total": len(rows), "items": [{
        "id": r.id,
        "question": r.question,
        "role": r.role or "",
        "role_label": ROLE_LABELS.get(r.role or "", r.role or "全角色"),
        "count": int(r.count or 0),
        "last_at": r.last_at.strftime("%Y-%m-%d %H:%M") if r.last_at else "",
    } for r in rows]}


@router.delete("/faqs/misses/{miss_id}")
def delete_faq_miss(
    miss_id: int,
    current_user: User = Depends(require_roles("admin", "service")),
    db: Session = Depends(get_db),
):
    row = db.query(AiFaqMiss).filter(AiFaqMiss.id == miss_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="记录不存在")
    db.delete(row)
    db.commit()
    return {"message": "已删除"}


@router.post("/faqs/misses/clear")
def clear_faq_misses(
    current_user: User = Depends(require_roles("admin", "service")),
    db: Session = Depends(get_db),
):
    n = db.query(AiFaqMiss).delete()
    db.commit()
    return {"message": f"已清空 {n} 条记录", "cleared": n}


@router.post("/faqs")
def create_faq(
    request: AiFaqCreate,
    current_user: User = Depends(require_roles("admin", "service")),
    db: Session = Depends(get_db),
):
    q = (request.question or "").strip()
    a = (request.answer or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="请填写标准问法")
    if not a:
        raise HTTPException(status_code=400, detail="请填写标准答法")
    role = _check_role(request.role)
    _check_placeholders(a)
    row = AiFaq(question=q[:255], answer=a, keywords=(request.keywords or "").strip()[:255],
                category=(request.category or "").strip()[:50], role=role,
                enabled=1 if request.enabled is None else (1 if request.enabled else 0))
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"message": "已新增", "item": _serialize_faq(row)}


@router.put("/faqs/{faq_id}")
def update_faq(
    faq_id: int,
    request: AiFaqUpdate,
    current_user: User = Depends(require_roles("admin", "service")),
    db: Session = Depends(get_db),
):
    row = db.query(AiFaq).filter(AiFaq.id == faq_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="问答不存在")

    if request.question is not None:
        q = request.question.strip()
        if not q:
            raise HTTPException(status_code=400, detail="标准问法不能为空")
        row.question = q[:255]
    if request.answer is not None:
        a = request.answer.strip()
        if not a:
            raise HTTPException(status_code=400, detail="标准答法不能为空")
        _check_placeholders(a)
        row.answer = a
    if request.keywords is not None:
        row.keywords = request.keywords.strip()[:255]
    if request.category is not None:
        row.category = request.category.strip()[:50]
    if request.role is not None:
        row.role = _check_role(request.role)
    if request.enabled is not None:
        row.enabled = 1 if int(request.enabled) else 0
    db.commit()
    db.refresh(row)
    return {"message": "已保存", "item": _serialize_faq(row)}


@router.delete("/faqs/{faq_id}")
def delete_faq(
    faq_id: int,
    current_user: User = Depends(require_roles("admin", "service")),
    db: Session = Depends(get_db),
):
    row = db.query(AiFaq).filter(AiFaq.id == faq_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="问答不存在")
    db.delete(row)
    db.commit()
    return {"message": "已删除"}


# 批量导入：每行一条，格式「标准问法|标准答法|关键词|分类|角色」（后三项可省略）
@router.post("/faqs/batch-import")
def batch_import_faqs(
    request: AiFaqBatchImport,
    current_user: User = Depends(require_roles("admin", "service")),
    db: Session = Depends(get_db),
):
    raw = request.content or ""
    if not raw.strip():
        raise HTTPException(status_code=400, detail="导入内容不能为空")

    existing = {r.question for r in db.query(AiFaq).all()}
    added = skipped = 0
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        while len(parts) < 5:
            parts.append("")
        q, a, kw, cat, role = parts[:5]
        if not q or not a:
            skipped += 1
            continue
        if q in existing:
            skipped += 1
            continue
        if role and role not in VALID_ROLES:
            skipped += 1
            continue
        if _PLACEHOLDER_RE.search(a):
            try:
                _check_placeholders(a)
            except HTTPException:
                skipped += 1
                continue
        db.add(AiFaq(question=q[:255], answer=a, keywords=kw[:255],
                     category=cat[:50], role=role, enabled=1))
        existing.add(q)
        added += 1
    db.commit()
    return {"message": f"导入完成：新增 {added} 条，跳过 {skipped} 条",
            "added": added, "skipped": skipped}
