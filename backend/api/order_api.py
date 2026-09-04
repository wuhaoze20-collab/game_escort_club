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
    
    # 订单金额必须为整数元（1大狗币 = 1元）
    if request.total_amount % 100 != 0:
        raise HTTPException(status_code=400, detail="订单金额须为整数元（大狗币按1:1结算）")
    coins_required = request.total_amount // 100
    
    # 检查大狗币余额是否足够
    if boss.balance < coins_required:
        raise HTTPException(status_code=400, detail=f"大狗币余额不足，需要 {coins_required} 大狗币，当前余额 {boss.balance}，请先充值")
    
    # 生成订单号
    order_no = "ORD" + datetime.now().strftime("%Y%m%d%H%M%S") + uuid.uuid4().hex[:4].upper()
    
    order = Order(
        order_no=order_no,
        boss_username=request.boss_username,
        game_type=request.game_type,
        duration_min=request.duration_min,
        total_amount=request.total_amount,
        remark=request.remark,
        status="pending"
    )
    
    # 老板点单直接指定打手：校验打手存在，订单进入"待打手确认"状态
    if request.player_username:
        player = db.query(PlayerInfo).filter(PlayerInfo.username == request.player_username).first()
        if not player:
            raise HTTPException(status_code=404, detail="打手账户不存在")
        order.player_username = request.player_username
        order.status = "pending_accept"
    
    db.add(order)
    
    # 冻结老板大狗币
    boss.balance -= coins_required
    
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
    if order.status not in ["pending", "pending_accept", "rejected"]:
        raise HTTPException(status_code=400, detail="当前状态的订单不能人工派单")
    
    # 检查打手是否存在
    player = db.query(PlayerInfo).filter(PlayerInfo.username == request.player_username).first()
    if not player:
        raise HTTPException(status_code=404, detail="打手账户不存在")
    
    order.player_username = request.player_username
    order.status = "assigned"
    db.commit()
    db.refresh(order)
    return order

# 打手接受订单（根据老板备注自行决定是否接单）
@router.post("/{order_id}/accept", response_model=OrderResponse)
def accept_order(
    order_id: int,
    current_user: User = Depends(require_roles("player")),
    db: Session = Depends(get_db)
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    # 只能接自己的待确认订单
    if order.player_username != current_user.username:
        raise HTTPException(status_code=403, detail="只能处理指派给自己的订单")
    if order.status != "pending_accept":
        raise HTTPException(status_code=400, detail="只有待确认状态的订单可以接单")
    
    order.status = "assigned"
    db.commit()
    db.refresh(order)
    return order

# 打手拒绝订单（退回老板余额）
@router.post("/{order_id}/reject", response_model=OrderResponse)
def reject_order(
    order_id: int,
    current_user: User = Depends(require_roles("player")),
    db: Session = Depends(get_db)
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    # 只能拒自己的待确认订单
    if order.player_username != current_user.username:
        raise HTTPException(status_code=403, detail="只能处理指派给自己的订单")
    if order.status != "pending_accept":
        raise HTTPException(status_code=400, detail="只有待确认状态的订单可以拒绝")
    
    order.status = "rejected"
    
    # 退回老板大狗币（1:1）
    boss = db.query(BossInfo).filter(BossInfo.username == order.boss_username).first()
    if boss:
        boss.balance += order.total_amount // 100
    
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

# 结算订单（完成订单并生成工资记录，金额入账）
def settle_order(db: Session, order: Order):
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

# 打手提交结单申请（服务完成后，等待老板确认，金额尚未入账）
@router.post("/{order_id}/submit-settlement", response_model=OrderResponse)
def submit_settlement(
    order_id: int,
    current_user: User = Depends(require_roles("player")),
    db: Session = Depends(get_db)
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status != "processing":
        raise HTTPException(status_code=400, detail="只有服务中的订单可以提交结单")
    # 只能提交自己的订单
    if order.player_username != current_user.username:
        raise HTTPException(status_code=403, detail="只能提交自己的订单")
    
    order.status = "pending_settlement"
    db.commit()
    db.refresh(order)
    return order

# 老板确认结单（金额转入打手账户；管理员/客服也可代为确认）
@router.post("/{order_id}/confirm-settlement", response_model=OrderResponse)
def confirm_settlement(
    order_id: int,
    current_user: User = Depends(require_roles("admin", "service", "boss")),
    db: Session = Depends(get_db)
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status != "pending_settlement":
        raise HTTPException(status_code=400, detail="只有待确认结单的订单可以确认")
    # 老板只能确认自己的订单
    if current_user.role == "boss" and order.boss_username != current_user.username:
        raise HTTPException(status_code=403, detail="只能确认自己的订单")
    
    settle_order(db, order)
    db.commit()
    db.refresh(order)
    return order

# 完成订单并结算（管理员/客服直接完成）
@router.post("/{order_id}/complete", response_model=OrderResponse)
def complete_order(
    order_id: int,
    current_user: User = Depends(require_roles("admin", "service")),
    db: Session = Depends(get_db)
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status not in ["processing", "pending_settlement"]:
        raise HTTPException(status_code=400, detail="当前状态的订单不能直接完成")
    
    settle_order(db, order)
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
    if order.status not in ["pending", "pending_accept", "assigned"]:
        raise HTTPException(status_code=400, detail="进行中或已完成的订单不能取消")
    
    # 老板角色只能取消自己的订单
    if current_user.role == "boss" and order.boss_username != current_user.username:
        raise HTTPException(status_code=403, detail="只能取消自己的订单")
    
    order.status = "cancelled"
    
    # 退回老板大狗币（1:1）
    boss = db.query(BossInfo).filter(BossInfo.username == order.boss_username).first()
    if boss:
        boss.balance += order.total_amount // 100
    
    db.commit()
    db.refresh(order)
    return order

# 获取订单列表（带老板/打手昵称与头像）
@router.get("/list")
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
    
    orders = query.order_by(Order.created_at.desc()).all()
    result = []
    for o in orders:
        boss_user = db.query(User).filter(User.username == o.boss_username).first()
        player_user = db.query(User).filter(User.username == o.player_username).first() if o.player_username else None
        result.append({
            "id": o.id,
            "order_no": o.order_no,
            "boss_username": o.boss_username,
            "boss_nickname": (boss_user.nickname or boss_user.username) if boss_user else o.boss_username,
            "boss_avatar": boss_user.avatar if boss_user else "",
            "player_username": o.player_username,
            "player_nickname": (player_user.nickname or player_user.username) if player_user else "",
            "player_avatar": player_user.avatar if player_user else "",
            "game_type": o.game_type,
            "duration_min": o.duration_min,
            "total_amount": o.total_amount,
            "remark": o.remark,
            "status": o.status,
            "created_at": o.created_at,
            "start_time": o.start_time,
            "end_time": o.end_time
        })
    return result

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
