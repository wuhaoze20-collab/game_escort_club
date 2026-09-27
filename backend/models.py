from sqlalchemy import Column, Integer, String, Float, DateTime, Text, ForeignKey, Numeric
from datetime import datetime
from database import Base

# 用户表（统一存储四种角色）
class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False)  # admin/service/boss/player
    role_name = Column(String(20), nullable=False)
    nickname = Column(String(50), default="")  # 当前展示昵称（空则显示用户名）
    avatar = Column(String(255), default="")  # 当前展示头像文件名（frontend/avatars/ 下）
    pending_nickname = Column(String(50), default="")  # 待审核昵称
    pending_avatar = Column(String(255), default="")  # 待审核头像
    nickname_status = Column(String(20), default="approved")  # approved/pending
    avatar_status = Column(String(20), default="approved")  # approved/pending
    reject_reason = Column(String(255), default="")  # 头像/昵称打回原因
    failed_attempts = Column(Integer, default=0)  # 连续输错密码次数（用于登录锁定）
    lock_until = Column(DateTime, nullable=True)  # 登录锁定截止时间（None=未锁定）
    account_status = Column(String(20), default="approved")  # 注册审核状态 pending/approved/rejected
    created_at = Column(DateTime, default=datetime.now)

# 内容配置表（公告、须知、价格、充值、会员、支付方式统一存储）
class ContentConfig(Base):
    __tablename__ = "content_config"
    
    id = Column(Integer, primary_key=True, index=True)
    config_key = Column(String(50), unique=True, index=True, nullable=False)  # notice/orderGuide/price/recharge/member/payment
    config_value = Column(Text, nullable=False)  # JSON格式存储内容
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

# 老板信息表
class BossInfo(Base):
    __tablename__ = "boss_info"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    consume_amount = Column(Integer, default=0)  # 累计消费（单位：分）
    balance = Column(Numeric(10, 2), nullable=False, default=0)  # 大狗币余额（1大狗币 = 1元，保留两位小数）
    order_count = Column(Integer, default=0)  # 点单次数
    created_at = Column(DateTime, default=datetime.now)

# 打手信息表
class PlayerInfo(Base):
    __tablename__ = "player_info"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    order_count = Column(Integer, default=0)  # 接单次数
    complaint_count = Column(Integer, default=0)  # 投诉次数
    good_rate = Column(Float, default=100.0)  # 好评率
    backend_amount = Column(Integer, default=0)  # 后台金额（单位：分，金额以分计故为整数）
    intro = Column(Text, default="")  # 打手自我介绍
    level_type = Column(String(20), default="娱乐陪")  # 等级大类：娱乐陪 / 技术陪
    tech_level = Column(String(20), default="")  # 技术陪细分：985/211/大专/魔王护/明星护
    created_at = Column(DateTime, default=datetime.now)

# 打手标签表（打手添加，管理员/客服审核通过后对外展示）
class PlayerTag(Base):
    __tablename__ = "player_tags"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), index=True, nullable=False)  # 标签所属打手
    tag = Column(String(50), nullable=False)  # 标签内容
    status = Column(String(20), default="pending")  # pending/approved/rejected
    note = Column(Text, default="")  # 审核备注
    created_at = Column(DateTime, default=datetime.now)
    processed_at = Column(DateTime, nullable=True)  # 审核时间

# 订单表
class Order(Base):
    __tablename__ = "orders"
    
    id = Column(Integer, primary_key=True, index=True)
    order_no = Column(String(50), unique=True, index=True, nullable=False)
    boss_username = Column(String(50), nullable=False)
    player_username = Column(String(50), nullable=True)
    game_type = Column(String(50), nullable=False)
    duration_min = Column(Integer, nullable=False)  # 服务时长（分钟）
    total_amount = Column(Integer, nullable=False)  # 订单总金额（分）
    service_note = Column(String(50), default="")  # 业务量说明（如 50级 / 3层 / 满级），非时长业务使用
    remark = Column(Text, default="")  # 老板下单备注（打手接单参考）
    # 订单状态流转：pending(待派单) → pending_accept(待打手确认) → assigned(已接单)
    #             → processing(服务中) → pending_settlement(待确认结单) → completed(已完成)
    # 分支：rejected(打手拒单，可重新派单) / cancelled(已取消)
    status = Column(String(20), default="pending")
    created_at = Column(DateTime, default=datetime.now)
    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime, nullable=True)

# 工资结算记录表
class SalaryRecord(Base):
    __tablename__ = "salary_records"
    
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), unique=True, nullable=False)
    player_username = Column(String(50), nullable=False)
    order_total = Column(Integer, nullable=False)  # 订单原始金额（分）
    club_commission = Column(Integer, nullable=False)  # 俱乐部抽成（分）
    player_income = Column(Integer, nullable=False)  # 打手收入（分）
    settlement_time = Column(DateTime, default=datetime.now)
    payout_status = Column(String(20), default="unpaid")  # unpaid/paid

# 打手评价表（老板结单后评价，其他老板点单可见）
class PlayerRating(Base):
    __tablename__ = "player_ratings"
    
    id = Column(Integer, primary_key=True, index=True)
    player_username = Column(String(50), index=True, nullable=False)  # 被评价打手
    boss_username = Column(String(50), nullable=False)  # 评价的老板
    order_id = Column(Integer, ForeignKey("orders.id"), unique=True, nullable=False)  # 关联订单，一单一评
    rating = Column(Integer, nullable=False)  # 评分 1-5 星
    comment = Column(Text, default="")  # 评价内容
    reply = Column(Text, default="")  # 打手回复
    reply_time = Column(DateTime, nullable=True)  # 回复时间
    review_status = Column(String(20), default="normal")  # normal/reviewing/removed 复查状态
    review_reason = Column(Text, default="")  # 打手复查申请理由
    review_note = Column(Text, default="")  # 管理员审核备注
    review_time = Column(DateTime, nullable=True)  # 审核时间
    created_at = Column(DateTime, default=datetime.now)

# 打赏记录表（老板结单后打赏打手）
class TipRecord(Base):
    __tablename__ = "tip_records"
    
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)  # 关联订单
    boss_username = Column(String(50), nullable=False)  # 打赏的老板
    player_username = Column(String(50), index=True, nullable=False)  # 被打赏打手
    amount = Column(Integer, nullable=False)  # 打赏金额（分）
    created_at = Column(DateTime, default=datetime.now)

# 提现记录表（打手提现，带30天冷却期）
class WithdrawalRecord(Base):
    __tablename__ = "withdrawal_records"
    
    id = Column(Integer, primary_key=True, index=True)
    player_username = Column(String(50), index=True, nullable=False)  # 提现打手
    amount = Column(Integer, nullable=False)  # 提现金额（分）
    status = Column(String(20), default="pending")  # pending/approved/rejected
    note = Column(Text, default="")  # 管理员审核备注
    created_at = Column(DateTime, default=datetime.now)
    processed_at = Column(DateTime, nullable=True)  # 审核时间

# 消息通知表
class Notification(Base):
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    title = Column(String(100), nullable=False)
    content = Column(Text, default="")
    type = Column(String(20), default="info")
    is_read = Column(Integer, default=0)
    link = Column(String(255), default="")
    created_at = Column(DateTime, default=datetime.now)

# 台词表（顶部台词栏随机轮换；由后台增删改查维护，不再硬编码在前端）
class Quote(Base):
    __tablename__ = "quotes"
    
    id = Column(Integer, primary_key=True, index=True)
    text = Column(String(255), nullable=False)  # 台词正文
    source = Column(String(100), default="")  # 出处（如《英雄联盟》）
    enabled = Column(Integer, default=1)  # 1=启用 0=停用（停用不参与轮换）
    sort_order = Column(Integer, default=0)  # 排序（小在前）
    created_at = Column(DateTime, default=datetime.now)

# 系统参数表（业务规则集中存储，后台可改，无需改代码重启）
class SystemConfig(Base):
    __tablename__ = "system_config"
    
    id = Column(Integer, primary_key=True, index=True)
    config_key = Column(String(50), unique=True, index=True, nullable=False)
    config_value = Column(String(255), nullable=False)  # 统一以字符串存储，读取时按 value_type 转换
    value_type = Column(String(20), default="str")  # int/float/str/bool/json
    label = Column(String(100), default="")  # 后台显示名
    description = Column(String(255), default="")  # 说明（含单位）
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

# AI 客服会话表（每个用户可有多个会话；同一时刻只有一个「当前会话」）
class AiConversation(Base):
    __tablename__ = "ai_conversations"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), index=True, nullable=False)  # 会话归属用户
    title = Column(String(100), default="新对话")  # 由首条提问生成，便于识别
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

# AI 客服消息表（一问一答都存这里，便于回看与统计用量）
class AiMessage(Base):
    __tablename__ = "ai_messages"
    
    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("ai_conversations.id"), index=True, nullable=False)
    role = Column(String(20), nullable=False)  # user / assistant
    content = Column(Text, nullable=False)
    prompt_tokens = Column(Integer, default=0)  # 本次实际消耗（assistant 消息上记录）
    completion_tokens = Column(Integer, default=0)
    error = Column(String(255), default="")  # 调用失败时的原因（便于排查）
    created_at = Column(DateTime, default=datetime.now)

# 拉黑申请表（客服发起，需管理员审核通过才真正执行拉黑）
# 说明：拉黑是不可逆操作（余额转入公司账户 + 写处罚通告 + 注销账号），
#       因此客服只能提交申请，由管理员审核；管理员自己拉黑则直接执行、不入此表。
#       单独建表而非在 users 上加列：同一账号可能被多次申请（驳回后可再申请），需要留history。
class BanRequest(Base):
    __tablename__ = "ban_requests"
    
    id = Column(Integer, primary_key=True, index=True)
    target_username = Column(String(50), index=True, nullable=False)  # 被申请拉黑的账号
    target_role = Column(String(20), default="")  # boss / player，便于列表展示
    requested_by = Column(String(50), nullable=False)  # 发起人（客服）
    reason = Column(Text, default="")  # 申请理由
    status = Column(String(20), default="pending")  # pending / approved / rejected
    note = Column(Text, default="")  # 管理员审核备注
    processed_by = Column(String(50), default="")  # 审核人
    created_at = Column(DateTime, default=datetime.now)
    processed_at = Column(DateTime, nullable=True)
