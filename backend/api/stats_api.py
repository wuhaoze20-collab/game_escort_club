from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
from models import Order, SalaryRecord, User
from auth import require_roles

router = APIRouter(prefix="/api/stats", tags=["数据统计"])

# 本月总盈利统计（仅管理员可查看）
@router.get("/monthly-profit")
def get_monthly_profit(
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db)
):
    now = datetime.now()
    # 本月起始：当月1号 00:00
    month_start = datetime(now.year, now.month, 1, 0, 0, 0)
    
    # 本月已结算（完成）的工资记录
    records = db.query(SalaryRecord).filter(
        SalaryRecord.settlement_time >= month_start
    ).all()
    
    total_profit = sum(r.club_commission for r in records)  # 俱乐部抽成 = 盈利
    total_amount = sum(r.order_total for r in records)      # 订单总额
    player_payout = sum(r.player_income for r in records)   # 打手发放总额
    
    # 本月完成订单数
    order_count = db.query(Order).filter(
        Order.status == "completed",
        Order.end_time >= month_start
    ).count()
    
    # 明细（按打手汇总）
    summary = {}
    for r in records:
        if r.player_username not in summary:
            summary[r.player_username] = {
                "player_username": r.player_username,
                "order_count": 0,
                "total_amount": 0,
                "profit": 0,
                "payout": 0
            }
        summary[r.player_username]["order_count"] += 1
        summary[r.player_username]["total_amount"] += r.order_total
        summary[r.player_username]["profit"] += r.club_commission
        summary[r.player_username]["payout"] += r.player_income
    
    return {
        "month": now.strftime("%Y-%m"),
        "total_profit": total_profit,
        "order_count": order_count,
        "total_amount": total_amount,
        "player_payout": player_payout,
        "records": list(summary.values())
    }
