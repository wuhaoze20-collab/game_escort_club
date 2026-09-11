from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Order, PlayerInfo, PlayerRating, User
from schemas import RatingCreateRequest, RatingReplyRequest, ReviewDecisionRequest, ReviewRequest, RatingResponse, ComplaintRequest
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
    # 无评价 → None（前端显示"-"）；有评价 → 好评比例
    player.good_rate = round(good / total * 100, 1) if total > 0 else None

# 结单后3天未评价的完成订单自动默认好评（后台线程定时调用）
def auto_default_rating(db: Session):
    cutoff = datetime.now() - timedelta(days=3)
    orders = db.query(Order).filter(
        Order.status == "completed",
        Order.end_time.isnot(None),
        Order.end_time <= cutoff
    ).all()
    added = 0
    for o in orders:
        exists = db.query(PlayerRating).filter(PlayerRating.order_id == o.id).first()
        if exists:
            continue
        db.add(PlayerRating(
            player_username=o.player_username,
            boss_username=o.boss_username,
            order_id=o.id,
            rating=5,
            comment="系统默认好评（结单3天未评价）",
            review_status="normal",
            created_at=o.end_time + timedelta(days=3)
        ))
        recalc_good_rate(db, o.player_username)
        added += 1
    if added:
        db.commit()
        print(f"[auto_default_rating] 已自动补 {added} 条默认好评")
    return added

# 老板投诉已结单订单：自动改为差评（打手可申诉，申诉成功则撤销）
@router.post("/complaint", response_model=RatingResponse)
def complaint_order(
    request: ComplaintRequest,
    current_user: User = Depends(require_roles("boss")),
    db: Session = Depends(get_db)
):
    if not request.reason.strip():
        raise HTTPException(status_code=400, detail="请填写投诉原因")
    order = db.query(Order).filter(
        Order.id == request.order_id,
        Order.boss_username == current_user.username
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在或不属于当前老板")
    if order.status != "completed":
        raise HTTPException(status_code=400, detail="仅已结单订单可投诉")
    if not order.player_username:
        raise HTTPException(status_code=400, detail="订单未分配打手，无法投诉")

    rating = db.query(PlayerRating).filter(PlayerRating.order_id == order.id).first()
    if rating:
        if rating.review_status == "removed":
            raise HTTPException(status_code=400, detail="该订单评价已处理，无法投诉")
        if rating.comment.startswith("【老板投诉】"):
            raise HTTPException(status_code=400, detail="该订单已投诉过，请等待处理")
        # 已有评价改为差评
        rating.rating = 1
        rating.comment = f"【老板投诉】{request.reason}（原评价：{rating.comment or '无'}）"
    else:
        rating = PlayerRating(
            player_username=order.player_username,
            boss_username=current_user.username,
            order_id=order.id,
            rating=1,
            comment=f"【老板投诉】{request.reason}",
            review_status="normal"
        )
        db.add(rating)
    # 打手投诉次数 +1
    player = db.query(PlayerInfo).filter(PlayerInfo.username == order.player_username).first()
    if player:
        player.complaint_count += 1
    db.flush()
    recalc_good_rate(db, order.player_username)
    db.commit()
    db.refresh(rating)
    return rating

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

    # 先把新评价刷入会话，再重算好评率（Session autoflush=False，
    # 若不 flush，重算查询看不到刚插入的记录，导致好评率滞后）
    db.flush()
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
    # 近期评价不显示系统自动默认好评（仅展示真实评价；
    # 默认好评仍计入好评率计算，见 recalc_good_rate）
    ratings = [r for r in ratings if r.comment != "系统默认好评（结单3天未评价）"]
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

    # 复查期间该评价从对外列表隐藏，好评率也应同步剔除（进入审核前计算一次）
    db.flush()
    recalc_good_rate(db, rating.player_username)

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
        # 申诉成功：撤销投诉差评，扣回打手投诉次数
        if rating.comment.startswith("【老板投诉】"):
            player = db.query(PlayerInfo).filter(PlayerInfo.username == rating.player_username).first()
            if player and player.complaint_count > 0:
                player.complaint_count -= 1
    else:
        rating.review_status = "normal"
    rating.review_note = request.note
    rating.review_time = datetime.now()

    # 先刷入新状态再重算好评率（autoflush=False 下不 flush 会读到旧状态，
    # 导致"驳回保留"后好评率仍沿用审核期口径）
    db.flush()
    recalc_good_rate(db, rating.player_username)
    
    db.commit()
    db.refresh(rating)
    return rating
