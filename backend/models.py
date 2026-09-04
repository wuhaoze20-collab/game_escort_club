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
    balance = Column(Integer, default=0)  # 账户余额（单位：分）
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
    backend_amount = Column(Integer, default=0)  # 后台金额（单位：分）
    intro = Column(Text, default="")  # 打手自我介绍
    created_at = Column(DateTime, default=datetime.now)

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
    status = Column(String(20), default="pending")  # pending/assigned/processing/completed/cancelled
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
    created_at = Column(DateTime, default=datetime.now)
