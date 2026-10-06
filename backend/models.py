from sqlalchemy import (Column, Integer, String, Float, DateTime, Text,
                        ForeignKey, Numeric, UniqueConstraint)
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
    good_rate = Column(Float, default=None)  # 好评率（无评价时为None，前端显示"-"）
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
    config_value = Column(Text, nullable=False)  # 统一以字符串存储，读取时按 value_type 转换
    # ⚠️ 必须是 Text 而非 String(255)：ai_extra_instruction 这类参数要放整段提示词文本，
    #    255 会直接报 Data too long（历史上踩过）。新增参数若内容可能很长，都用这一列。
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
    tools_used = Column(String(255), default="")  # 本条回答用到的工具名（逗号分隔，便于审计）
    created_at = Column(DateTime, default=datetime.now)


# AI 系统提示词分段表（把原先硬编码在 ai_service.py 里的提示词搬进数据库）
#
# 为什么搬进库：提示词需要反复试错（改一句效果差很多），硬编码意味着每次都要改代码 +
# 重启后端，迭代速度被拖死。搬进库后管理员可在「提示词管理」页直接改、立即生效、可回滚。
#
# 设计要点：
# · 默认值仍保留在 ai_service.PROMPT_SECTIONS 里作为出厂内容与兜底（表为空时用代码默认值），
#   因此本表为空不会导致 AI 失效。
# · `role` 为空表示对所有角色生效；填了角色则只注入给该角色（用于角色专属话术）。
# · `priority` 决定拼接顺序，小的在前。仅影响本表内部顺序；动态块（角色菜单、
#   平台资料、当前时间）固定排在本表所有段落之后。
# · `version` 每次保存 +1，配合 ai_messages 可回溯"哪一版提示词答错了"。
class AiPrompt(Base):
    __tablename__ = "ai_prompts"

    id = Column(Integer, primary_key=True, index=True)
    section_key = Column(String(50), unique=True, index=True, nullable=False)  # 段落标识
    title = Column(String(100), default="")  # 后台显示名
    content = Column(Text, nullable=False)  # 段落正文
    role = Column(String(20), default="")  # ''=全角色；admin/service/boss/player=仅该角色
    priority = Column(Integer, default=100)  # 拼接顺序（小在前）
    enabled = Column(Integer, default=1)  # 1=注入 0=不注入
    version = Column(Integer, default=1)  # 每次保存 +1
    updated_by = Column(String(50), default="")  # 最后修改人
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


# AI 问答库（FAQ）：按关键词命中后只注入相关几条，替代"每次塞全部资料"
#
# 为什么需要：`build_knowledge_base()` 会把 8 个内容模块全部塞进提示词。资料一多，
# 既贵（每次请求都带全文）又会让模型"中间迷失"（长提示词中段利用率下降）。
# 把高频业务规则做成 FAQ + 关键词命中，只注入 Top N 条，更省也更准。
class AiFaq(Base):
    __tablename__ = "ai_faqs"

    id = Column(Integer, primary_key=True, index=True)
    question = Column(String(255), nullable=False)  # 标准问法（后台显示用）
    keywords = Column(String(255), default="")  # 逗号分隔的关键词，用于匹配用户提问
    answer = Column(Text, nullable=False)  # 标准答法（命中后原样注入提示词）
    category = Column(String(50), default="")  # 分类（价格/资金/账号…），便于管理
    role = Column(String(20), default="")  # ''=全角色；否则仅该角色命中
    enabled = Column(Integer, default=1)
    hit_count = Column(Integer, default=0)  # 命中次数，用于发现"该补哪类问答"
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


# AI 未命中提问记录：关键词匹配有一条固有短板 —— 管理员不知道"哪些提问没被覆盖"，
# 于是问答库只能越写越多却不知道补哪里。这里把没命中任何 FAQ 的提问聚合记下来，
# 管理员在「问答库」页就能看到"用户实际在问什么"，据此新增问答。
#
# 按提问原文聚合（同一句只累加 count），因此不会无限膨胀；后台可一键清空。
class AiFaqMiss(Base):
    __tablename__ = "ai_faq_misses"

    id = Column(Integer, primary_key=True, index=True)
    question = Column(String(255), unique=True, index=True, nullable=False)  # 提问原文（截断）
    role = Column(String(20), default="")  # 首次记录时的提问角色
    count = Column(Integer, default=1)  # 累计出现次数
    last_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
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


# 知识库文档表（长篇纯文本：用户服务协议、打手服务规范、退款与争议规则等）
#
# 为什么不塞进 content_config：
# · content_config 的 8 个模块是**结构化 JSON**，前端有对应的表格/卡片渲染函数，
#   而且每轮都被 build_knowledge_base() 全量注入提示词。长文档是**纯文本**、动辄上万字，
#   全量注入既贵，又会让模型"中间迷失"（长提示词中段利用率下降）。
# · 长文档的正确用法是「切成片段 + 按提问检索相关片段」，因此需要被独立索引
#   （见 ai_rag.py）。混进 content_config 会同时破坏前端的结构化渲染和
#   content_api 的 VALID_CONFIG_KEYS 白名单校验。
class KbDocument(Base):
    __tablename__ = "kb_documents"

    id = Column(Integer, primary_key=True, index=True)
    doc_key = Column(String(50), unique=True, index=True, nullable=False)  # 文档标识
    title = Column(String(100), nullable=False)  # 文档标题
    category = Column(String(50), default="")  # 分类（协议条款/服务规范/交易规则…）
    content = Column(Text, nullable=False)  # 正文（纯文本，用换行分段）
    role = Column(String(20), default="")  # ''=所有角色可见；否则仅该角色
    enabled = Column(Integer, default=1)  # 1=可被检索与查看 0=停用
    sort_order = Column(Integer, default=0)  # 排序（小在前）
    version = Column(Integer, default=1)  # 每次保存 +1
    updated_by = Column(String(50), default="")  # 最后修改人
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


# AI 知识库向量索引表（RAG 检索层）
#
# 为什么需要向量检索：`content_config` 的内容可以全量塞进提示词（总共才 3 千字符），
# 但长篇文档不行 —— 三份协议类文档就上万字。全量注入会让提示词膨胀十几倍，
# 既贵又降低模型对中段内容的利用率。向量检索能只把"和本轮提问真正相关的几个片段"
# 送进提示词。
#
# 存储方式（**MySQL 8.2 没有 VECTOR 列类型**，那是 MySQL 9.0 才引入的）：
# · 向量以 JSON 数组存进 TEXT 列，相似度在 Python 里算余弦。
# · 语料量级（几千到几万字符 → 几十到几百个 chunk）下，暴力遍历比引入
#   faiss/chromadb 更简单可靠，也不增加部署负担。
# · 若将来 chunk 数上万，再换 MySQL 9 的 VECTOR 或外部向量库；
#   届时 `model` + `dim` 两列可用于识别并重建旧向量。
#
# `content_hash` 是关键的成本控制：只有内容真的变了才重新调用 embedding 接口，
# 否则后台每保存一次文档都要把整库重算一遍（又慢又花钱）。
class AiChunk(Base):
    __tablename__ = "ai_chunks"

    id = Column(Integer, primary_key=True, index=True)
    source_type = Column(String(30), nullable=False)  # document / faq
    source_key = Column(String(120), nullable=False)  # kb_documents.doc_key 或 faq:{id}
    chunk_index = Column(Integer, default=0)  # 同一来源内的片段序号
    parent_id = Column(Integer, nullable=True)  # 父子分块：子块指向父块id；NULL=父块或普通块
    title = Column(String(100), default="")  # 片段所属文档标题（检索结果展示用）
    role = Column(String(20), default="")  # 冗余自来源，''=全角色；否则仅该角色可检索到
    content = Column(Text, nullable=False)  # 片段正文（注入提示词的就是它）
    content_hash = Column(String(32), nullable=False)  # md5(content)，用于跳过未变内容
    embedding = Column(Text)  # 向量 JSON 数组；NULL 表示尚未向量化（父块不向量化）
    dim = Column(Integer, default=0)  # 向量维度（换模型时用于识别不匹配的旧数据）
    model = Column(String(50), default="")  # 生成该向量的模型名
    enabled = Column(Integer, default=1)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        UniqueConstraint("source_type", "source_key", "chunk_index",
                         name="uk_ai_chunk_src"),
    )
