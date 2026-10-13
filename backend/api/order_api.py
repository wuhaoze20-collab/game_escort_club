import uuid
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from database import get_db
from models import Order, SalaryRecord, BossInfo, PlayerInfo, User
from schemas import CreateOrderRequest, AssignPlayerRequest, OrderResponse, SalaryRecordResponse
from auth import get_current_user, require_roles
from api.notification_api import create_notification
import config_service

router = APIRouter(prefix="/api/order", tags=["订单管理"])


def _rate(db: Session) -> float:
    """俱乐部抽成比例，取自 system_config（后台可改，默认 0.3）"""
    return config_service.commission_rate(db)


def _kg_sync(db: Session, order: Order) -> None:
    """把订单同步进知识图谱（「后续新订单都存进图谱」的落点）。

    在每个订单状态变更接口的 db.commit() 之后调用：
    下单时建立 Boss-Order 链路，接单时补上 Player 与 SERVED / HIRED 关系，
    结单时把状态刷新成最新。

    **这是旁路操作**：图谱写失败绝不能影响下单、结单这些主流程，
    所以整段包在 try 里，失败只打印一行日志。
    """
    try:
        if not config_service.get_config("kg_enabled", db):
            return
        if not config_service.get_config("kg_auto_sync_order", db):
            return
        from kg import sync as kg_sync
        kg_sync.sync_order(db, order)
    except Exception as e:
        print(f"[kg] 订单入图失败（订单 {getattr(order, 'order_no', '?')}）："
              f"{type(e).__name__}: {e}")

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

    # ---- 服务端参数校验（防止构造非法请求）；各项限额取自 system_config，后台可调 ----
    max_game_len = int(config_service.get_config("game_type_max_len", db))
    max_duration = int(config_service.get_config("order_max_duration_min", db))
    min_amount = int(config_service.get_config("order_min_amount", db))
    max_amount = int(config_service.get_config("order_max_amount", db))
    max_remark_len = int(config_service.get_config("order_remark_max_len", db))
    max_note_len = int(config_service.get_config("order_service_note_max_len", db))

    game_type = (request.game_type or "").strip()
    if not game_type:
        raise HTTPException(status_code=400, detail="请选择游戏类型")
    if len(game_type) > max_game_len:
        raise HTTPException(status_code=400, detail=f"游戏类型不能超过{max_game_len}个字符")
    if request.duration_min < 1:
        raise HTTPException(status_code=400, detail="服务时长必须大于0分钟")
    if request.duration_min > max_duration:
        raise HTTPException(status_code=400, detail=f"单笔订单服务时长不能超过{max_duration}分钟（{max_duration // 60}小时）")
    if not isinstance(request.total_amount, (int, float)) or request.total_amount < min_amount:
        raise HTTPException(status_code=400, detail=f"订单金额不能小于{min_amount / 100:g}元")
    if request.total_amount > max_amount:
        raise HTTPException(status_code=400, detail=f"单笔订单金额不能超过{max_amount / 100:g}元")
    if request.remark and len(request.remark) > max_remark_len:
        raise HTTPException(status_code=400, detail=f"下单备注不能超过{max_remark_len}个字符")
    if request.service_note and len(request.service_note) > max_note_len:
        raise HTTPException(status_code=400, detail=f"业务量说明不能超过{max_note_len}个字符")
    # 大狗币余额列是 DECIMAL(10,2)，SQLAlchemy 读出来是 Decimal。
    # ⚠️ Decimal 与 float 直接相减会抛 TypeError，所以这里**不能**用 round(x / 100, 2)，
    #    必须同样用 Decimal 计算（早期代码是 round(...)，在余额支持小数后会崩）。
    coins_required = (Decimal(request.total_amount) / Decimal(100)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)

    # 检查大狗币余额是否足够
    if (boss.balance or 0) < coins_required:
        raise HTTPException(status_code=400, detail=f"大狗币余额不足，需要 {coins_required:.2f} 大狗币，当前余额 {boss.balance:.2f}，请先充值")
    
    # 生成订单号
    order_no = "ORD" + datetime.now().strftime("%Y%m%d%H%M%S") + uuid.uuid4().hex[:4].upper()
    
    order = Order(
        order_no=order_no,
        boss_username=request.boss_username,
        game_type=game_type,
        duration_min=request.duration_min,
        total_amount=request.total_amount,
        service_note=request.service_note or "",
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
    
    # 发送订单通知：指定打手 → 通知打手；未指定 → 通知客服派单
    if order.status == "pending_accept":
        p_user = db.query(User).filter(User.username == order.player_username).first()
        if p_user:
            b_user = db.query(User).filter(User.username == order.boss_username).first()
            boss_name = b_user.nickname if b_user and b_user.nickname else order.boss_username
            create_notification(db, p_user.id, "新订单", f"老板 {boss_name} 给您指派了新订单 {order.order_no}，请及时确认", "info", "player-orders")
    else:
        for su in db.query(User).filter(User.role == "service").all():
            create_notification(db, su.id, "新订单待派单", f"有新的待派单订单 {order.order_no}，请及时派单", "info", "order-manage")
    
    db.commit()
    db.refresh(order)
    _kg_sync(db, order)   # 新订单入知识图谱
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
    
    # 打手拒单时金额已退回老板余额；再次派单需重新冻结，否则会产生"双倍退款/免费服务"资金漏洞
    if order.status == "rejected":
        coins_required = order.total_amount // 100
        boss = db.query(BossInfo).filter(BossInfo.username == order.boss_username).first()
        if not boss or boss.balance < coins_required:
            raise HTTPException(status_code=400, detail=f"老板大狗币余额不足，无法重新派单，需要 {coins_required} 大狗币，请先充值")
        boss.balance -= coins_required
    
    order.player_username = request.player_username
    order.status = "assigned"
    
    # 通知老板派单成功、打手有新订单
    b_user = db.query(User).filter(User.username == order.boss_username).first()
    p_user = db.query(User).filter(User.username == order.player_username).first()
    player_name = p_user.nickname if p_user and p_user.nickname else order.player_username
    if b_user:
        create_notification(db, b_user.id, "派单成功", f"客服已为您派单：打手 {player_name}，订单 {order.order_no}，等待开始服务", "success", "order")
    if p_user:
        create_notification(db, p_user.id, "新订单", f"您有新的派单订单 {order.order_no}，请及时接单", "info", "player-orders")
    
    db.commit()
    db.refresh(order)
    _kg_sync(db, order)   # 订单状态变更后刷新图谱
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
    _kg_sync(db, order)   # 订单状态变更后刷新图谱
    
    # 给老板发通知
    boss_user = db.query(User).filter(User.username == order.boss_username).first()
    if boss_user:
        player_user = db.query(User).filter(User.username == current_user.username).first()
        player_name = player_user.nickname if player_user and player_user.nickname else current_user.username
        create_notification(
            db, boss_user.id,
            title="接单成功",
            content=f"打手 {player_name} 已接受您的订单 {order.order_no}，即将开始服务",
            type="success",
            link="order"
        )
    
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
    
    # 通知老板订单被拒、金额退回
    b_user = db.query(User).filter(User.username == order.boss_username).first()
    p_user = db.query(User).filter(User.username == current_user.username).first()
    player_name = p_user.nickname if p_user and p_user.nickname else current_user.username
    if b_user:
        create_notification(db, b_user.id, "打手拒单", f"打手 {player_name} 拒绝了订单 {order.order_no}，大狗币已退回您的余额", "warning", "order")
    
    db.commit()
    db.refresh(order)
    _kg_sync(db, order)   # 订单状态变更后刷新图谱
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
    
    # 通知老板服务开始
    b_user = db.query(User).filter(User.username == order.boss_username).first()
    p_user = db.query(User).filter(User.username == order.player_username).first()
    player_name = p_user.nickname if p_user and p_user.nickname else order.player_username
    if b_user:
        create_notification(db, b_user.id, "服务开始", f"打手 {player_name} 已开始为您服务，订单 {order.order_no}", "info", "order")
    
    db.commit()
    db.refresh(order)
    _kg_sync(db, order)   # 订单状态变更后刷新图谱
    return order

# 结算订单（完成订单并生成工资记录，金额入账）
# 返回生成的 SalaryRecord，调用方应直接复用它，避免重复计算金额导致口径不一致
def settle_order(db: Session, order: Order) -> SalaryRecord:
    order.status = "completed"
    order.end_time = datetime.now()
    
    # 计算结算
    club_commission = int(order.total_amount * _rate(db))
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

    return salary


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
    
    # 通知老板确认结单
    b_user = db.query(User).filter(User.username == order.boss_username).first()
    p_user = db.query(User).filter(User.username == current_user.username).first()
    player_name = p_user.nickname if p_user and p_user.nickname else current_user.username
    if b_user:
        create_notification(db, b_user.id, "待确认结单", f"打手 {player_name} 已提交结单申请，订单 {order.order_no}，请确认结单", "warning", "order")
    
    db.commit()
    db.refresh(order)
    _kg_sync(db, order)   # 订单状态变更后刷新图谱
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
    
    salary = settle_order(db, order)
    
    # 通知打手订单完成、金额入账（金额直接复用结算结果，避免口径不一致）
    p_user = db.query(User).filter(User.username == order.player_username).first()
    if p_user:
        create_notification(db, p_user.id, "订单完成", f"订单 {order.order_no} 已确认结单，本次收入 {salary.player_income / 100:.2f} 元已入账后台金额", "success", "player-orders")
    
    db.commit()
    db.refresh(order)
    _kg_sync(db, order)   # 订单状态变更后刷新图谱
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
    
    salary = settle_order(db, order)
    
    # 通知打手订单完成、金额入账（金额直接复用结算结果，避免口径不一致）
    p_user = db.query(User).filter(User.username == order.player_username).first()
    if p_user:
        create_notification(db, p_user.id, "订单完成", f"订单 {order.order_no} 已完成结算，本次收入 {salary.player_income / 100:.2f} 元已入账后台金额", "success", "player-orders")
    
    db.commit()
    db.refresh(order)
    _kg_sync(db, order)   # 订单状态变更后刷新图谱
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
    
    # 通知打手订单已取消
    p_user = db.query(User).filter(User.username == order.player_username).first() if order.player_username else None
    if p_user:
        create_notification(db, p_user.id, "订单已取消", f"订单 {order.order_no} 已取消，请知悉", "warning", "player-orders")
    
    db.commit()
    db.refresh(order)
    _kg_sync(db, order)   # 订单状态变更后刷新图谱
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
