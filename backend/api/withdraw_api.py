from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from database import get_db
from models import PlayerInfo, SalaryRecord, TipRecord, User, WithdrawalRecord
from schemas import WithdrawCreateRequest, WithdrawProcessRequest, WithdrawResponse
from auth import require_roles

router = APIRouter(prefix="/api/withdraw", tags=["提现管理"])

# 提现冷却期（天）：入账金额需满30天才可提现
COOLDOWN_DAYS = 30

# 计算打手可提现金额（已过30天冷却期的收入 + 打赏 - 已批准提现）
def calc_available_amount(db: Session, player_username: str) -> int:
    now = datetime.now()
    cutoff = now - timedelta(days=COOLDOWN_DAYS)
    
    # 已过冷却期的订单收入
    matured_salary = db.query(SalaryRecord).filter(
        SalaryRecord.player_username == player_username,
        SalaryRecord.settlement_time <= cutoff
    ).all()
    salary_total = sum(s.player_income for s in matured_salary)
    
    # 已过冷却期的打赏
    matured_tips = db.query(TipRecord).filter(
        TipRecord.player_username == player_username,
        TipRecord.created_at <= cutoff
    ).all()
    tip_total = sum(t.amount for t in matured_tips)
    
    # 已批准 + 待审核中的提现金额都要占用可提现额度，
    # 否则打手可在同一笔收入上并发提交多笔申请，突破30天冷却期
    withdrawn = db.query(WithdrawalRecord).filter(
        WithdrawalRecord.player_username == player_username,
        WithdrawalRecord.status.in_(["pending", "approved"])
    ).all()
    withdrawn_total = sum(w.amount for w in withdrawn)
    
    return salary_total + tip_total - withdrawn_total

# 打手查询可提现金额
@router.get("/available")
def get_available_amount(
    current_user: User = Depends(require_roles("player")),
    db: Session = Depends(get_db)
):
    player = db.query(PlayerInfo).filter(PlayerInfo.username == current_user.username).first()
    if not player:
        raise HTTPException(status_code=404, detail="用户信息不存在")
    available = calc_available_amount(db, current_user.username)
    # 可提现金额不能超过后台总金额
    available = min(available, player.backend_amount)
    return {
        "available_amount": available,
        "backend_amount": player.backend_amount,
        "cooldown_days": COOLDOWN_DAYS
    }

# 打手发起提现申请
@router.post("/create", response_model=WithdrawResponse)
def create_withdraw(
    request: WithdrawCreateRequest,
    current_user: User = Depends(require_roles("player")),
    db: Session = Depends(get_db)
):
    if request.amount <= 0:
        raise HTTPException(status_code=400, detail="提现金额必须大于0")
    
    player = db.query(PlayerInfo).filter(PlayerInfo.username == current_user.username).first()
    if not player:
        raise HTTPException(status_code=404, detail="用户信息不存在")
    
    available = calc_available_amount(db, current_user.username)
    available = min(available, player.backend_amount)
    if request.amount > available:
        raise HTTPException(status_code=400, detail=f"可提现金额不足（当前可提现¥{available / 100:.2f}，含30天冷却期限制）")
    
    withdraw = WithdrawalRecord(
        player_username=current_user.username,
        amount=request.amount,
        status="pending"
    )
    db.add(withdraw)
    db.commit()
    db.refresh(withdraw)
    return withdraw

# 打手查看自己的提现记录
@router.get("/my", response_model=List[WithdrawResponse])
def get_my_withdrawals(
    current_user: User = Depends(require_roles("player")),
    db: Session = Depends(get_db)
):
    return db.query(WithdrawalRecord).filter(
        WithdrawalRecord.player_username == current_user.username
    ).order_by(WithdrawalRecord.created_at.desc()).all()

# 管理员/客服查看所有提现申请
@router.get("/list", response_model=List[WithdrawResponse])
def get_withdraw_list(
    current_user: User = Depends(require_roles("admin", "service")),
    db: Session = Depends(get_db)
):
    return db.query(WithdrawalRecord).order_by(WithdrawalRecord.created_at.desc()).all()

# 管理员/客服批准提现
@router.post("/{withdraw_id}/approve", response_model=WithdrawResponse)
def approve_withdraw(
    withdraw_id: int,
    request: WithdrawProcessRequest,
    current_user: User = Depends(require_roles("admin", "service")),
    db: Session = Depends(get_db)
):
    withdraw = db.query(WithdrawalRecord).filter(WithdrawalRecord.id == withdraw_id).first()
    if not withdraw:
        raise HTTPException(status_code=404, detail="提现申请不存在")
    if withdraw.status != "pending":
        raise HTTPException(status_code=400, detail="该申请已处理")
    
    # 扣减打手后台金额
    player = db.query(PlayerInfo).filter(PlayerInfo.username == withdraw.player_username).first()
    if player:
        if player.backend_amount < withdraw.amount:
            raise HTTPException(status_code=400, detail="打手后台金额不足，无法批准")
        player.backend_amount -= withdraw.amount
    
    withdraw.status = "approved"
    withdraw.note = request.note
    withdraw.processed_at = datetime.now()
    db.commit()
    db.refresh(withdraw)
    return withdraw

# 管理员/客服拒绝提现
@router.post("/{withdraw_id}/reject", response_model=WithdrawResponse)
def reject_withdraw(
    withdraw_id: int,
    request: WithdrawProcessRequest,
    current_user: User = Depends(require_roles("admin", "service")),
    db: Session = Depends(get_db)
):
    withdraw = db.query(WithdrawalRecord).filter(WithdrawalRecord.id == withdraw_id).first()
    if not withdraw:
        raise HTTPException(status_code=404, detail="提现申请不存在")
    if withdraw.status != "pending":
        raise HTTPException(status_code=400, detail="该申请已处理")
    
    withdraw.status = "rejected"
    withdraw.note = request.note
    withdraw.processed_at = datetime.now()
    db.commit()
    db.refresh(withdraw)
    return withdraw
