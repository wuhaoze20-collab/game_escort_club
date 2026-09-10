from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey
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
    balance = Column(Integer, default=0)  # 大狗币余额（1大狗币 = 1元，点单/打赏消耗）
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
    backend_amount = Column(Integer, default=0)  # 后台金额（单位：分，订单大狗币按1:1折算为人民币）
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
    remark = Column(Text, default="")  # 老板下单备注（打手接单参考）
    status = Column(String(20), default="pending")  # pending/pending_accept/assigned/processing/completed/cancelled/rejected
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
