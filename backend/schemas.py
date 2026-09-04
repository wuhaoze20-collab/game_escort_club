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

# 资料修改请求（昵称/头像提交审核）
class ProfileUpdateRequest(BaseModel):
    nickname: Optional[str] = ""  # 新昵称（提交审核）
    avatar: Optional[str] = ""  # 新头像文件名（提交审核，来自头像库）

# 资料审核请求（管理员打回/通过）
class ProfileReviewRequest(BaseModel):
    field: str  # nickname / avatar
    action: str  # approve / reject
    note: str = ""  # 打回原因

# 内容配置更新
class ContentConfigUpdate(BaseModel):
    value: Any

# 老板信息响应
class BossInfoResponse(BaseModel):
    username: str
    nickname: str = ""
    avatar: str = ""
    consume_amount: int
    balance: int
    order_count: int
    
    class Config:
        from_attributes = True

# 打手信息响应
class PlayerInfoResponse(BaseModel):
    username: str
    nickname: str = ""
    avatar: str = ""
    order_count: int
    complaint_count: int
    good_rate: float
    backend_amount: int
    intro: str = ""
    level_type: str = "娱乐陪"
    tech_level: str = ""
    
    class Config:
        from_attributes = True

# 打手公开信息（老板点单可见，不含后台金额等敏感信息）
class PlayerPublicInfo(BaseModel):
    username: str
    nickname: str = ""
    avatar: str = ""
    order_count: int
    complaint_count: int
    good_rate: float
    intro: str = ""
    level_type: str = "娱乐陪"
    tech_level: str = ""
    tags: list = []  # 审核通过的标签
    
    class Config:
        from_attributes = True

# 更新打手自我介绍请求
class IntroUpdateRequest(BaseModel):
    intro: str

# 更新打手等级请求
class LevelUpdateRequest(BaseModel):
    level_type: str  # 娱乐陪 / 技术陪
    tech_level: str = ""  # 985/211/大专/魔王护/明星护

# 打手添加标签请求
class TagCreateRequest(BaseModel):
    tag: str

# 打手标签响应
class TagResponse(BaseModel):
    id: int
    username: str
    tag: str
    status: str
    note: str = ""
    created_at: datetime
    processed_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

# 标签审核请求
class TagDecisionRequest(BaseModel):
    action: str  # approve/reject
    note: str = ""

# 老板充值请求
class RechargeRequest(BaseModel):
    amount: int  # 充值金额（元），1:1 到账大狗币
    payment: str  # 支付方式

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
    reply: str = ""
    reply_time: Optional[datetime] = None
    review_status: str = "normal"
    review_reason: str = ""
    review_note: str = ""
    created_at: datetime
    
    class Config:
        from_attributes = True

# 打手回复评价请求
class RatingReplyRequest(BaseModel):
    reply: str

# 打手复查申请请求
class ReviewRequest(BaseModel):
    reason: str

# 管理员复查审核请求
class ReviewDecisionRequest(BaseModel):
    action: str  # approve=移除评价 / reject=保留评价
    note: str = ""

# 打赏请求
class TipCreateRequest(BaseModel):
    order_id: int
    amount: int  # 打赏金额（分）

# 打赏记录响应
class TipResponse(BaseModel):
    id: int
    order_id: int
    boss_username: str
    player_username: str
    amount: int
    created_at: datetime
    
    class Config:
        from_attributes = True

# 提现请求
class WithdrawCreateRequest(BaseModel):
    amount: int  # 提现金额（分）

# 提现记录响应
class WithdrawResponse(BaseModel):
    id: int
    player_username: str
    amount: int
    status: str
    note: str = ""
    created_at: datetime
    processed_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

# 提现审核请求
class WithdrawProcessRequest(BaseModel):
    note: str = ""

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
    remark: str = ""  # 老板下单备注（打手接单参考）

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
    remark: str = ""
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
