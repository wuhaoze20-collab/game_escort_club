from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from database import get_db
from models import Order, PlayerInfo, PlayerRating, User
from schemas import RatingCreateRequest, RatingReplyRequest, ReviewDecisionRequest, ReviewRequest, RatingResponse
from auth import get_current_user, require_roles

router = APIRouter(prefix="/api/rating", tags=["打手评价"])

# 组装评价数据（带老板/打手昵称与头像）
def _rating_profile(db: Session, r: PlayerRating):
    boss_user = db.query(User).filter(User.username == r.boss_username).first()
    player_user = db.query(User).filter(User.username == r.player_username).first()
    return {
        "id": r.id,
        "player_username": r.player_username,
        "player_nickname": (player_user.nickname or player_user.username) if player_user else r.player_username,
        "player_avatar": player_user.avatar if player_user else "",
        "boss_username": r.boss_username,
        "boss_nickname": (boss_user.nickname or boss_user.username) if boss_user else r.boss_username,
        "boss_avatar": boss_user.avatar if boss_user else "",
        "order_id": r.order_id,
        "rating": r.rating,
        "comment": r.comment,
        "reply": r.reply,
        "reply_time": r.reply_time,
        "review_status": r.review_status,
        "review_reason": r.review_reason,
        "review_note": r.review_note,
        "review_time": r.review_time,
        "created_at": r.created_at
    }

# 重新计算打手好评率（仅统计有效评价：normal状态，好评=4星及以上）
def recalc_good_rate(db: Session, player_username: str):
    player = db.query(PlayerInfo).filter(PlayerInfo.username == player_username).first()
    if not player:
        return
    all_ratings = db.query(PlayerRating).filter(
        PlayerRating.player_username == player_username,
        PlayerRating.review_status == "normal"
    ).all()
    total = len(all_ratings)
    good = sum(1 for r in all_ratings if r.rating >= 4)
    player.good_rate = round(good / total * 100, 1) if total > 0 else 100.0

# 老板对已完成的订单评价（一单一评）
@router.post("/create", response_model=RatingResponse)
def create_rating(
    request: RatingCreateRequest,
    current_user: User = Depends(require_roles("boss")),
    db: Session = Depends(get_db)
):
    # 校验评分范围
    if request.rating < 1 or request.rating > 5:
        raise HTTPException(status_code=400, detail="评分必须在1-5星之间")
    
    # 校验订单存在
    order = db.query(Order).filter(Order.id == request.order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    
    # 只能评价自己的订单
    if order.boss_username != current_user.username:
        raise HTTPException(status_code=403, detail="只能评价自己的订单")
    
    # 只能评价已完成的订单
    if order.status != "completed":
        raise HTTPException(status_code=400, detail="订单完成后才能评价")
    
    # 订单必须分配过打手
    if not order.player_username:
        raise HTTPException(status_code=400, detail="订单未分配打手，无法评价")
    
    # 防止重复评价
    existing = db.query(PlayerRating).filter(PlayerRating.order_id == order.id).first()
    if existing:
        raise HTTPException(status_code=400, detail="该订单已评价，不能重复评价")
    
    rating = PlayerRating(
        player_username=order.player_username,
        boss_username=current_user.username,
        order_id=order.id,
        rating=request.rating,
        comment=request.comment
    )
    db.add(rating)
    
    # 重新计算该打手的好评率
    recalc_good_rate(db, order.player_username)
    
    db.commit()
    db.refresh(rating)
    return rating

# 查询某打手的有效评价列表（所有登录用户可看，已移除的评价不显示）
@router.get("/player/{player_username}")
def get_player_ratings(
    player_username: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # 校验打手存在
    player = db.query(PlayerInfo).filter(PlayerInfo.username == player_username).first()
    if not player:
        raise HTTPException(status_code=404, detail="打手不存在")
    
    ratings = db.query(PlayerRating).filter(
        PlayerRating.player_username == player_username,
        PlayerRating.review_status == "normal"
    ).order_by(PlayerRating.created_at.desc()).all()
    return [_rating_profile(db, r) for r in ratings]

# 打手查看自己的全部评价（含复查中/已移除状态）
@router.get("/my-reviews")
def get_my_reviews(
    current_user: User = Depends(require_roles("player")),
    db: Session = Depends(get_db)
):
    ratings = db.query(PlayerRating).filter(
        PlayerRating.player_username == current_user.username
    ).order_by(PlayerRating.created_at.desc()).all()
    return [_rating_profile(db, r) for r in ratings]

# 查询当前老板给自己的评价历史（老板可见自己评价过的记录）
@router.get("/my")
def get_my_ratings(
    current_user: User = Depends(require_roles("boss")),
    db: Session = Depends(get_db)
):
    ratings = db.query(PlayerRating).filter(
        PlayerRating.boss_username == current_user.username
    ).order_by(PlayerRating.created_at.desc()).all()
    return [_rating_profile(db, r) for r in ratings]

# 打手回复评价（仅被评价的打手本人，可修改自己的回复）
@router.put("/{rating_id}/reply", response_model=RatingResponse)
def reply_rating(
    rating_id: int,
    request: RatingReplyRequest,
    current_user: User = Depends(require_roles("player")),
    db: Session = Depends(get_db)
):
    rating = db.query(PlayerRating).filter(PlayerRating.id == rating_id).first()
    if not rating:
        raise HTTPException(status_code=404, detail="评价不存在")
    
    # 只能回复自己被评价的记录
    if rating.player_username != current_user.username:
        raise HTTPException(status_code=403, detail="只能回复自己的评价")
    
    rating.reply = request.reply
    rating.reply_time = datetime.now()
    db.commit()
    db.refresh(rating)
    return rating

# 打手对评价提交复查申请（被移除的评价不能再次申请）
@router.post("/{rating_id}/review-request", response_model=RatingResponse)
def request_review(
    rating_id: int,
    request: ReviewRequest,
    current_user: User = Depends(require_roles("player")),
    db: Session = Depends(get_db)
):
    if not request.reason.strip():
        raise HTTPException(status_code=400, detail="请填写复查申请理由")
    
    rating = db.query(PlayerRating).filter(PlayerRating.id == rating_id).first()
    if not rating:
        raise HTTPException(status_code=404, detail="评价不存在")
    
    # 只能申请自己被评价的记录
    if rating.player_username != current_user.username:
        raise HTTPException(status_code=403, detail="只能申请自己的评价")
    
    if rating.review_status == "reviewing":
        raise HTTPException(status_code=400, detail="该评价已在复查中，请等待管理员审核")
    if rating.review_status == "removed":
        raise HTTPException(status_code=400, detail="该评价已被移除，不能重复申请")
    
    rating.review_status = "reviewing"
    rating.review_reason = request.reason
    rating.review_note = ""
    rating.review_time = datetime.now()
    db.commit()
    db.refresh(rating)
    return rating

# 管理员/客服查看复查申请列表
@router.get("/review-list")
def get_review_list(
    current_user: User = Depends(require_roles("admin", "service")),
    db: Session = Depends(get_db)
):
    ratings = db.query(PlayerRating).filter(
        PlayerRating.review_status == "reviewing"
    ).order_by(PlayerRating.review_time.desc()).all()
    return [_rating_profile(db, r) for r in ratings]

# 管理员审核复查：approve=移除评价 / reject=保留评价
@router.post("/{rating_id}/review-decision", response_model=RatingResponse)
def review_decision(
    rating_id: int,
    request: ReviewDecisionRequest,
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db)
):
    if request.action not in ["approve", "reject"]:
        raise HTTPException(status_code=400, detail="无效的操作类型")
    
    rating = db.query(PlayerRating).filter(PlayerRating.id == rating_id).first()
    if not rating:
        raise HTTPException(status_code=404, detail="评价不存在")
    if rating.review_status != "reviewing":
        raise HTTPException(status_code=400, detail="该评价不在复查中")
    
    if request.action == "approve":
        rating.review_status = "removed"
    else:
        rating.review_status = "normal"
    rating.review_note = request.note
    rating.review_time = datetime.now()
    
    # 重新计算打手好评率
    recalc_good_rate(db, rating.player_username)
    
    db.commit()
    db.refresh(rating)
    return rating
