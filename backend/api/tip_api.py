from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from database import get_db
from models import BossInfo, Order, PlayerInfo, TipRecord, User
from schemas import TipCreateRequest, TipResponse
from auth import require_roles
from api.notification_api import create_notification
import config_service

router = APIRouter(prefix="/api/tip", tags=["打赏管理"])

# 老板对已完成订单打赏打手
@router.post("/create", response_model=TipResponse)
def create_tip(
    request: TipCreateRequest,
    current_user: User = Depends(require_roles("boss")),
    db: Session = Depends(get_db)
):
    if request.amount <= 0:
        raise HTTPException(status_code=400, detail="打赏金额必须大于0")
    
    order = db.query(Order).filter(Order.id == request.order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    
    # 只能打赏自己的订单
    if order.boss_username != current_user.username:
        raise HTTPException(status_code=403, detail="只能打赏自己的订单")
    
    # 只能打赏已完成的订单
    if order.status != "completed":
        raise HTTPException(status_code=400, detail="订单完成后才能打赏")
    
    # 订单必须分配过打手
    if not order.player_username:
        raise HTTPException(status_code=400, detail="订单未分配打手，无法打赏")
    
    # 打赏上限：累计打赏不超过订单金额的设定比例（system_config，默认 30%）
    tip_rate = config_service.tip_max_rate(db)
    max_tip = int(order.total_amount * tip_rate)
    already_tipped = sum(t.amount for t in db.query(TipRecord).filter(TipRecord.order_id == order.id).all())
    if already_tipped + request.amount > max_tip:
        raise HTTPException(status_code=400, detail=f"该订单累计打赏不能超过订单金额的{tip_rate * 100:g}%（上限¥{max_tip / 100:.2f}，已打赏¥{already_tipped / 100:.2f}）")
    
    # 打赏金额必须为整数元（大狗币1:1结算）
    if request.amount % 100 != 0:
        raise HTTPException(status_code=400, detail="打赏金额须为整数元（大狗币按1:1结算）")
    coins_required = request.amount // 100

    # 检查老板大狗币余额
    boss_info = db.query(BossInfo).filter(BossInfo.username == current_user.username).first()
    if not boss_info or boss_info.balance < coins_required:
        raise HTTPException(status_code=400, detail=f"大狗币余额不足，需要 {coins_required} 大狗币，请先充值")
    
    # 扣老板大狗币，增加打手后台金额（自动按1:1折算为人民币）
    boss_info.balance -= coins_required
    player = db.query(PlayerInfo).filter(PlayerInfo.username == order.player_username).first()
    if player:
        player.backend_amount += request.amount
    
    tip = TipRecord(
        order_id=order.id,
        boss_username=current_user.username,
        player_username=order.player_username,
        amount=request.amount
    )
    db.add(tip)
    
    # 通知打手收到打赏
    p_user = db.query(User).filter(User.username == order.player_username).first()
    if p_user:
        create_notification(db, p_user.id, "收到打赏", f"老板 {current_user.nickname or current_user.username} 为您打赏 {request.amount // 100:.0f} 元，已计入后台金额", "success", "player-orders")
    
    db.commit()
    db.refresh(tip)
    # 打赏入知识图谱：让「谁给谁打赏过」这类问题能走图谱这一路
    try:
        from kg import sync as kg_sync
        kg_sync.sync_tip(db, tip)
    except Exception as e:
        print(f"[kg] 打赏入图失败（打赏 {tip.id}）：{type(e).__name__}: {e}")
    return tip

# 打手查看自己的打赏记录
@router.get("/player/me", response_model=List[TipResponse])
def get_my_tips(
    current_user: User = Depends(require_roles("player")),
    db: Session = Depends(get_db)
):
    return db.query(TipRecord).filter(
        TipRecord.player_username == current_user.username
    ).order_by(TipRecord.created_at.desc()).all()
