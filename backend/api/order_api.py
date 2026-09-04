import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from database import get_db
from models import Order, SalaryRecord, BossInfo, PlayerInfo, User
from schemas import CreateOrderRequest, AssignPlayerRequest, OrderResponse, SalaryRecordResponse
from auth import get_current_user, require_roles

router = APIRouter(prefix="/api/order", tags=["订单管理"])

# 俱乐部抽成比例（30%）
CLUB_COMMISSION_RATE = 0.3

# 创建订单（管理员、客服、老板可创建）
@router.post("/create", response_model=OrderResponse)
def create_order(
    request: CreateOrderRequest,
    current_user: User = Depends(require_roles("admin", "service", "boss")),
    db: Session = Depends(get_db)
):
    # 老板角色只能给自己下单
    if current_user.role == "boss" and request.boss_username != current_user.username:
        raise HTTPException(status_code=403, detail="只能为自己下单")
    
    # 检查老板是否存在
    boss = db.query(BossInfo).filter(BossInfo.username == request.boss_username).first()
    if not boss:
        raise HTTPException(status_code=404, detail="老板账户不存在")
    
    # 检查余额是否足够
    if boss.balance < request.total_amount:
        raise HTTPException(status_code=400, detail="老板余额不足")
    
    # 生成订单号
    order_no = "ORD" + datetime.now().strftime("%Y%m%d%H%M%S") + uuid.uuid4().hex[:4].upper()
    
    order = Order(
        order_no=order_no,
        boss_username=request.boss_username,
        game_type=request.game_type,
        duration_min=request.duration_min,
        total_amount=request.total_amount,
        status="pending"
    )
    db.add(order)
    
    # 冻结老板余额
    boss.balance -= request.total_amount
    
    db.commit()
    db.refresh(order)
    return order

# 分配打手（管理员、客服可操作）
@router.post("/{order_id}/assign", response_model=OrderResponse)
def assign_player(
    order_id: int,
    request: AssignPlayerRequest,
    current_user: User = Depends(require_roles("admin", "service")),
    db: Session = Depends(get_db)
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status != "pending":
        raise HTTPException(status_code=400, detail="只有待接单状态的订单可以分配打手")
    
    # 检查打手是否存在
    player = db.query(PlayerInfo).filter(PlayerInfo.username == request.player_username).first()
    if not player:
        raise HTTPException(status_code=404, detail="打手账户不存在")
    
    order.player_username = request.player_username
    order.status = "assigned"
    db.commit()
    db.refresh(order)
    return order

# 开始服务
@router.post("/{order_id}/start", response_model=OrderResponse)
def start_order(
    order_id: int,
    current_user: User = Depends(require_roles("admin", "service", "player")),
    db: Session = Depends(get_db)
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status != "assigned":
        raise HTTPException(status_code=400, detail="只有已分配状态的订单可以开始服务")
    
    # 打手角色只能开始自己的订单
    if current_user.role == "player" and order.player_username != current_user.username:
        raise HTTPException(status_code=403, detail="只能开始自己的订单")
    
    order.status = "processing"
    order.start_time = datetime.now()
    db.commit()
    db.refresh(order)
    return order

# 完成订单并结算
@router.post("/{order_id}/complete", response_model=OrderResponse)
def complete_order(
    order_id: int,
    current_user: User = Depends(require_roles("admin", "service")),
    db: Session = Depends(get_db)
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status != "processing":
        raise HTTPException(status_code=400, detail="只有进行中的订单可以完成")
    
    order.status = "completed"
    order.end_time = datetime.now()
    
    # 计算结算
    club_commission = int(order.total_amount * CLUB_COMMISSION_RATE)
    player_income = order.total_amount - club_commission
    
    # 生成工资记录
    salary = SalaryRecord(
        order_id=order.id,
        player_username=order.player_username,
        order_total=order.total_amount,
        club_commission=club_commission,
        player_income=player_income
    )
    db.add(salary)
    
    # 增加打手后台金额和接单次数
    player = db.query(PlayerInfo).filter(PlayerInfo.username == order.player_username).first()
    if player:
        player.backend_amount += player_income
        player.order_count += 1
    
    # 增加老板消费和点单次数
    boss = db.query(BossInfo).filter(BossInfo.username == order.boss_username).first()
    if boss:
        boss.consume_amount += order.total_amount
        boss.order_count += 1
    
    db.commit()
    db.refresh(order)
    return order

# 取消订单
@router.post("/{order_id}/cancel", response_model=OrderResponse)
def cancel_order(
    order_id: int,
    current_user: User = Depends(require_roles("admin", "service", "boss")),
    db: Session = Depends(get_db)
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status not in ["pending", "assigned"]:
        raise HTTPException(status_code=400, detail="进行中或已完成的订单不能取消")
    
    # 老板角色只能取消自己的订单
    if current_user.role == "boss" and order.boss_username != current_user.username:
        raise HTTPException(status_code=403, detail="只能取消自己的订单")
    
    order.status = "cancelled"
    
    # 退回老板余额
    boss = db.query(BossInfo).filter(BossInfo.username == order.boss_username).first()
    if boss:
        boss.balance += order.total_amount
    
    db.commit()
    db.refresh(order)
    return order

# 获取订单列表
@router.get("/list", response_model=List[OrderResponse])
def get_order_list(
    status: str = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(Order)
    
    # 老板只能看自己的订单
    if current_user.role == "boss":
        query = query.filter(Order.boss_username == current_user.username)
    # 打手只能看自己的订单
    elif current_user.role == "player":
        query = query.filter(Order.player_username == current_user.username)
    
    if status:
        query = query.filter(Order.status == status)
    
    return query.order_by(Order.created_at.desc()).all()

# 获取工资记录列表
@router.get("/salary/list", response_model=List[SalaryRecordResponse])
def get_salary_list(
    current_user: User = Depends(require_roles("admin", "service", "player")),
    db: Session = Depends(get_db)
):
    query = db.query(SalaryRecord)
    # 打手只能看自己的工资记录
    if current_user.role == "player":
        query = query.filter(SalaryRecord.player_username == current_user.username)
    
    return query.order_by(SalaryRecord.settlement_time.desc()).all()
