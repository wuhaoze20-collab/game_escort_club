from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from database import get_db
from models import PlayerInfo, SalaryRecord, TipRecord, User, WithdrawalRecord
from schemas import WithdrawCreateRequest, WithdrawProcessRequest, WithdrawResponse
from auth import require_roles
import config_service
import ops_alerts

router = APIRouter(prefix="/api/withdraw", tags=["提现管理"])


# 把一条提现记录同步进知识图谱（申请 / 审核结果都走这里）
def _kg_sync_withdrawal(db: Session, wd: WithdrawalRecord) -> None:
    """旁路操作：图谱写失败绝不能影响提现主流程，所以整段包在 try 里。

    审核通过或驳回后再调一次，图谱上的 status 会刷新成最新结果——
    「这个打手提过几次现、批了没有」靠它回答。
    """
    try:
        from kg import sync as kg_sync
        kg_sync.sync_withdrawal(db, wd)
    except Exception as e:
        print(f"[kg] 提现入图失败（提现 {getattr(wd, 'id', '?')}）："
              f"{type(e).__name__}: {e}")


# 提现冷却期取自 system_config（默认 30 天）：入账金额需满该天数才可提现
def calc_available_amount(db: Session, player_username: str) -> int:
    """计算打手可提现金额。

    三重约束：
    1. 只有过了冷却期的收入才可提现；
    2. 不能超过打手实际后台金额（权威余额），否则会透支；
    3. 在途（待审核）的申请会占用额度，避免同一笔钱被重复申请。
    结果保证不为负。

    关于「期初结余」：backend_amount 是权威余额，但它与「收入记录累计」可能不等 ——
    差额来自建库时预设的历史余额（没有任何 income 记录支撑）。这部分余额必然早于
    所有记录存在，按定义已过冷却期，因此计入可提现基数；否则这些账户明明后台有钱，
    却因为查不到对应的收入记录而一分都提不出来。

    注意：**已批准的提现不在此处扣减**。approve_withdraw() 已经把它从
    backend_amount 扣掉了，这里再减一次就是重复扣减 —— 这正是此前
    可提现金额出现负数的原因之一。
    """
    now = datetime.now()
    cooldown_days = config_service.withdraw_cooldown_days(db)
    cutoff = now - timedelta(days=cooldown_days)

    player = db.query(PlayerInfo).filter(PlayerInfo.username == player_username).first()
    backend_amount = player.backend_amount if player else 0

    # 全部收入记录（用于推算期初结余）
    all_salary = db.query(SalaryRecord).filter(
        SalaryRecord.player_username == player_username).all()
    all_tips = db.query(TipRecord).filter(
        TipRecord.player_username == player_username).all()
    records_income = sum(s.player_income for s in all_salary) + sum(t.amount for t in all_tips)

    # 其中已过冷却期的部分
    matured_income = sum(s.player_income for s in all_salary
                         if s.settlement_time and s.settlement_time <= cutoff)
    matured_income += sum(t.amount for t in all_tips
                          if t.created_at and t.created_at <= cutoff)

    # 已批准的提现：已从 backend_amount 扣除，此处不再减（避免重复扣减）
    approved_total = sum(w.amount for w in db.query(WithdrawalRecord).filter(
        WithdrawalRecord.player_username == player_username,
        WithdrawalRecord.status == "approved"
    ).all())

    # 在途（待审核）申请占用额度
    pending_total = sum(w.amount for w in db.query(WithdrawalRecord).filter(
        WithdrawalRecord.player_username == player_username,
        WithdrawalRecord.status == "pending"
    ).all())

    # 期初结余：后台余额里没有收入记录支撑的部分，视为已过冷却期
    opening_balance = max(0, backend_amount - (records_income - approved_total))

    # 可用基数为「已到期收入 + 期初结余」，再受实际余额封顶、扣掉在途申请
    raw = min(matured_income + opening_balance, backend_amount) - pending_total
    if raw < 0:
        # 界面必须显示 0（不能给用户看负数），但**账目已经不一致这个事实要留痕**，
        # 否则只剩一个 0，谁也不知道数据出了问题。
        ops_alerts.record(
            f"withdraw_negative:{player_username}",
            f"打手 {player_username} 的可提现额算出负值 {raw} 分（已按 0 显示）："
            f"已到期收入={matured_income} 期初结余={opening_balance} "
            f"后台金额={backend_amount} 在途提现={pending_total}。"
            f"通常意味着 backend_amount 与收入记录不一致"
        )
        print(f"[withdraw] {player_username} 可提现额算出负值 {raw}，已归零")
        return 0
    return raw

# 打手查询可提现金额
@router.get("/available")
def get_available_amount(
    current_user: User = Depends(require_roles("player")),
    db: Session = Depends(get_db)
):
    player = db.query(PlayerInfo).filter(PlayerInfo.username == current_user.username).first()
    if not player:
        raise HTTPException(status_code=404, detail="用户信息不存在")
    # calc_available_amount 内部已保证「不超过后台金额」且「不为负」
    available = calc_available_amount(db, current_user.username)
    return {
        "available_amount": available,
        "backend_amount": player.backend_amount,
        "pending_amount": sum(w.amount for w in db.query(WithdrawalRecord).filter(
            WithdrawalRecord.player_username == current_user.username,
            WithdrawalRecord.status == "pending"
        ).all()),
        "cooldown_days": config_service.withdraw_cooldown_days(db)
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
    
    # calc_available_amount 内部已保证「不超过后台金额」且「不为负」
    available = calc_available_amount(db, current_user.username)
    if request.amount > available:
        cooldown = config_service.withdraw_cooldown_days(db)
        raise HTTPException(status_code=400, detail=f"可提现金额不足（当前可提现¥{available / 100:.2f}，含{cooldown}天冷却期限制）")
    
    withdraw = WithdrawalRecord(
        player_username=current_user.username,
        amount=request.amount,
        status="pending"
    )
    db.add(withdraw)
    db.commit()
    db.refresh(withdraw)
    _kg_sync_withdrawal(db, withdraw)   # 提现申请入知识图谱
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
    _kg_sync_withdrawal(db, withdraw)   # 审核结果刷新图谱
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
    _kg_sync_withdrawal(db, withdraw)   # 审核结果刷新图谱
    return withdraw
