from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Quote, User
from auth import get_current_user, require_roles
from schemas import QuoteCreate, QuoteUpdate, QuoteBatchImport

router = APIRouter(prefix="/api/quote", tags=["台词管理"])

# 管理端角色（可增删改台词、查看停用项）
MANAGE_ROLES = ("admin", "service")


def _serialize(q: Quote) -> dict:
    return {
        "id": q.id,
        "text": q.text,
        "source": q.source or "",
        "enabled": int(q.enabled or 0),
        "sort_order": int(q.sort_order or 0),
    }


# 台词列表：管理员/客服可见全部（含停用），其他登录用户仅见启用的（顶部台词栏轮换用）
@router.get("/list")
def list_quotes(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Quote)
    if current_user.role not in MANAGE_ROLES:
        query = query.filter(Quote.enabled == 1)
    rows = query.order_by(Quote.sort_order.asc(), Quote.id.asc()).all()
    return {"total": len(rows), "items": [_serialize(q) for q in rows]}


# 新增台词
@router.post("/create")
def create_quote(
    request: QuoteCreate,
    current_user: User = Depends(require_roles(*MANAGE_ROLES)),
    db: Session = Depends(get_db),
):
    text = (request.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="台词内容不能为空")
    if len(text) > 255:
        raise HTTPException(status_code=400, detail="台词内容不能超过255个字符")

    # 未指定排序时排到末尾
    if request.sort_order is None:
        max_order = db.query(Quote).count()
        sort_order = max_order
    else:
        sort_order = request.sort_order

    q = Quote(
        text=text,
        source=(request.source or "").strip()[:100],
        enabled=1 if request.enabled is None else (1 if request.enabled else 0),
        sort_order=sort_order,
    )
    db.add(q)
    db.commit()
    db.refresh(q)
    return {"message": "台词已新增", "item": _serialize(q)}


# 修改台词（部分字段）
@router.put("/{quote_id}")
def update_quote(
    quote_id: int,
    request: QuoteUpdate,
    current_user: User = Depends(require_roles(*MANAGE_ROLES)),
    db: Session = Depends(get_db),
):
    q = db.query(Quote).filter(Quote.id == quote_id).first()
    if not q:
        raise HTTPException(status_code=404, detail="台词不存在")

    if request.text is not None:
        text = request.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="台词内容不能为空")
        if len(text) > 255:
            raise HTTPException(status_code=400, detail="台词内容不能超过255个字符")
        q.text = text
    if request.source is not None:
        q.source = request.source.strip()[:100]
    if request.enabled is not None:
        q.enabled = 1 if request.enabled else 0
    if request.sort_order is not None:
        q.sort_order = request.sort_order

    db.commit()
    db.refresh(q)
    return {"message": "台词已更新", "item": _serialize(q)}


# 删除台词
@router.delete("/{quote_id}")
def delete_quote(
    quote_id: int,
    current_user: User = Depends(require_roles(*MANAGE_ROLES)),
    db: Session = Depends(get_db),
):
    q = db.query(Quote).filter(Quote.id == quote_id).first()
    if not q:
        raise HTTPException(status_code=404, detail="台词不存在")
    db.delete(q)
    db.commit()
    return {"message": "台词已删除"}


# 批量导入：每行一条，支持 "台词|出处" 或仅台词；已存在（正文+出处完全相同）的自动跳过
@router.post("/batch-import")
def batch_import_quotes(
    request: QuoteBatchImport,
    current_user: User = Depends(require_roles(*MANAGE_ROLES)),
    db: Session = Depends(get_db),
):
    raw = request.content or ""
    if not raw.strip():
        raise HTTPException(status_code=400, detail="导入内容不能为空")

    existing = {(q.text, q.source or "") for q in db.query(Quote).all()}
    max_order = db.query(Quote).count()
    added = 0
    skipped = 0
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if "|" in line:
            text, _, source = line.partition("|")
            text, source = text.strip(), source.strip()
        else:
            text, source = line, ""
        if not text:
            continue
        if (text, source) in existing:
            skipped += 1
            continue
        db.add(Quote(text=text[:255], source=source[:100], enabled=1, sort_order=max_order + added))
        existing.add((text, source))
        added += 1

    db.commit()
    return {"message": f"导入完成：新增 {added} 条，跳过重复 {skipped} 条",
            "added": added, "skipped": skipped}
