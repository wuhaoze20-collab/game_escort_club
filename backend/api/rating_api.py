from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from database import get_db
from models import Order, PlayerInfo, PlayerRating, User
from schemas import RatingCreateRequest, RatingResponse
from auth import get_current_user, require_roles

router = APIRouter(prefix="/api/rating", tags=["打手评价"])

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
    
    # 重新计算该打手的好评率（好评=4星及以上 / 总评价数）
    player = db.query(PlayerInfo).filter(PlayerInfo.username == order.player_username).first()
    if player:
        all_ratings = db.query(PlayerRating).filter(PlayerRating.player_username == player.username).all()
        total = len(all_ratings)
        good = sum(1 for r in all_ratings if r.rating >= 4)
        player.good_rate = round(good / total * 100, 1) if total > 0 else 100.0
    
    db.commit()
    db.refresh(rating)
    return rating

# 查询某打手的评价列表（所有登录用户可看）
@router.get("/player/{player_username}", response_model=List[RatingResponse])
def get_player_ratings(
    player_username: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # 校验打手存在
    player = db.query(PlayerInfo).filter(PlayerInfo.username == player_username).first()
    if not player:
        raise HTTPException(status_code=404, detail="打手不存在")
    
    return db.query(PlayerRating).filter(
        PlayerRating.player_username == player_username
    ).order_by(PlayerRating.created_at.desc()).all()

# 查询当前老板给自己的评价历史（老板可见自己评价过的记录）
@router.get("/my", response_model=List[RatingResponse])
def get_my_ratings(
    current_user: User = Depends(require_roles("boss")),
    db: Session = Depends(get_db)
):
    return db.query(PlayerRating).filter(
        PlayerRating.boss_username == current_user.username
    ).order_by(PlayerRating.created_at.desc()).all()
