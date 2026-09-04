from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime

# 登录请求
class LoginRequest(BaseModel):
    username: str
    password: str

# 登录响应
class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict

# 内容配置更新
class ContentConfigUpdate(BaseModel):
    value: Any

# 老板信息响应
class BossInfoResponse(BaseModel):
    username: str
    consume_amount: int
    balance: int
    order_count: int
    
    class Config:
        from_attributes = True

# 打手信息响应
class PlayerInfoResponse(BaseModel):
    username: str
    order_count: int
    complaint_count: int
    good_rate: float
    backend_amount: int
    
    class Config:
        from_attributes = True

# 创建订单请求
class CreateOrderRequest(BaseModel):
    boss_username: str
    game_type: str
    duration_min: int
    total_amount: int

# 分配打手请求
class AssignPlayerRequest(BaseModel):
    player_username: str

# 订单响应
class OrderResponse(BaseModel):
    id: int
    order_no: str
    boss_username: str
    player_username: Optional[str] = None
    game_type: str
    duration_min: int
    total_amount: int
    status: str
    created_at: datetime
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    class Config:
        from_attributes = True

# 工资记录响应
class SalaryRecordResponse(BaseModel):
    id: int
    order_id: int
    player_username: str
    order_total: int
    club_commission: int
    player_income: int
    settlement_time: datetime
    payout_status: str
    
    class Config:
        from_attributes = True
