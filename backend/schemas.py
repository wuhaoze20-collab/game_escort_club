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
    intro: str = ""
    
    class Config:
        from_attributes = True

# 打手公开信息（老板点单可见，不含后台金额等敏感信息）
class PlayerPublicInfo(BaseModel):
    username: str
    order_count: int
    complaint_count: int
    good_rate: float
    intro: str = ""
    
    class Config:
        from_attributes = True

# 更新打手自我介绍请求
class IntroUpdateRequest(BaseModel):
    intro: str

# 创建评价请求
class RatingCreateRequest(BaseModel):
    order_id: int
    rating: int  # 1-5星
    comment: str = ""

# 评价响应
class RatingResponse(BaseModel):
    id: int
    player_username: str
    boss_username: str
    order_id: int
    rating: int
    comment: str
    created_at: datetime
    
    class Config:
        from_attributes = True

# 本月盈利统计响应
class MonthlyProfitResponse(BaseModel):
    month: str  # 如 2026-09
    total_profit: int  # 本月俱乐部抽成总额（分）
    order_count: int  # 本月完成订单数
    total_amount: int  # 本月订单总额（分）
    player_payout: int  # 本月打手发放总额（分）
    records: list = []  # 盈利明细

# 创建订单请求
class CreateOrderRequest(BaseModel):
    boss_username: str
    game_type: str
    duration_min: int
    total_amount: int
    player_username: Optional[str] = None  # 老板点单可直接指定打手

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
