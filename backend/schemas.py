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

# 忘记密码重置请求（无需登录）
class ResetPasswordRequest(BaseModel):
    username: str
    new_password: str

# 修改密码请求（需登录）
class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

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
    good_rate: Optional[float] = None
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
    good_rate: Optional[float] = None
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

# 注册请求
class RegisterRequest(BaseModel):
    username: str
    password: str
    role: str  # boss/player/service
    nickname: str = ""
    intro: str = ""  # 打手自我介绍
    level_type: str = "娱乐陪"  # 娱乐陪/技术陪
    tech_level: str = ""  # 985/211/大专/魔王护/明星护

# 注册审核决策请求
class RegistrationDecisionRequest(BaseModel):
    user_id: int
    action: str  # approve/reject
    note: str = ""

# 老板投诉订单请求
class ComplaintRequest(BaseModel):
    order_id: int
    reason: str

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

# 创建订单请求
class CreateOrderRequest(BaseModel):
    boss_username: str
    game_type: str
    duration_min: int
    total_amount: int
    player_username: Optional[str] = None  # 老板点单可直接指定打手
    service_note: str = ""  # 业务量说明（如 50级 / 3层），非时长业务使用
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
    service_note: str = ""
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

# ——— 台词管理 ———
class QuoteCreate(BaseModel):
    text: str
    source: str = ""
    enabled: Optional[bool] = True
    sort_order: Optional[int] = None  # 不传则自动排到末尾

class QuoteUpdate(BaseModel):
    text: Optional[str] = None
    source: Optional[str] = None
    enabled: Optional[bool] = None
    sort_order: Optional[int] = None

# 批量导入：每行一条，支持 "台词|出处"
class QuoteBatchImport(BaseModel):
    content: str

# ——— 系统参数 ———
class SystemConfigUpdate(BaseModel):
    value: str  # 统一按字符串提交，后端按参数类型校验并转换

# ——— AI 客服 ———
class AiChatRequest(BaseModel):
    message: str
    conversation_id: Optional[int] = None  # 不传则自动新建会话

class AiMessageResponse(BaseModel):
    id: int
    role: str
    content: str
    error: str = ""
    created_at: datetime
    
    class Config:
        from_attributes = True

class AiConversationResponse(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    
    class Config:
        from_attributes = True

class AiChatResponse(BaseModel):
    conversation_id: int
    reply: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    remaining_today: int = -1  # -1 表示不限制
    model: str = ""

# ——— 拉黑申请（客服发起，管理员审核） ———
class BanRequestCreate(BaseModel):
    username: str
    reason: str = ""

class BanDecisionRequest(BaseModel):
    note: str = ""
