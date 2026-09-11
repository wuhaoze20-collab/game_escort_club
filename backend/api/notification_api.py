from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Notification, User
from auth import get_current_user

router = APIRouter(prefix="/api/notification", tags=["消息通知"])

# 获取当前用户的消息列表
@router.get("/list")
def get_notifications(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    notifications = db.query(Notification).filter(
        Notification.user_id == current_user.id
    ).order_by(Notification.created_at.desc()).limit(50).all()
    
    result = []
    for n in notifications:
        result.append({
            "id": n.id,
            "title": n.title,
            "content": n.content,
            "type": n.type,
            "is_read": n.is_read,
            "link": n.link,
            "created_at": n.created_at.strftime("%Y-%m-%d %H:%M")
        })
    return result

# 获取未读消息数
@router.get("/unread-count")
def get_unread_count(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    count = db.query(Notification).filter(
        Notification.user_id == current_user.id,
        Notification.is_read == 0
    ).count()
    return {"count": count}

# 标记消息为已读
@router.post("/{notification_id}/read")
def mark_as_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    notification = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == current_user.id
    ).first()
    if not notification:
        raise HTTPException(status_code=404, detail="消息不存在")
    notification.is_read = 1
    db.commit()
    return {"message": "已标记为已读"}

# 全部标记为已读
@router.post("/read-all")
def mark_all_as_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db.query(Notification).filter(
        Notification.user_id == current_user.id,
        Notification.is_read == 0
    ).update({"is_read": 1})
    db.commit()
    return {"message": "全部已读"}

# 工具函数：创建消息
def create_notification(db: Session, user_id: int, title: str, content: str, type: str = "info", link: str = ""):
    notification = Notification(
        user_id=user_id,
        title=title,
        content=content,
        type=type,
        link=link
    )
    db.add(notification)
    db.commit()
    return notification
