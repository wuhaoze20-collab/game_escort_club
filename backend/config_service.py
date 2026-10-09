"""系统参数读取层。

业务规则（抽成比例、冷却天数、各类上限等）集中存于 `system_config` 表，
后台可改、无需改代码与重启。

设计要点（重要）：
1. **默认值兜底**：每条参数在 `CONFIG_META` 里都有出厂值。数据库缺行、值非法、
   或类型转换失败时一律回退默认值，保证业务永不因配置问题而崩溃。
   但**同时会通过 `ops_alerts` 留痕**，后台「系统参数」页能看到 —— 否则连不上库
   或参数被写坏时会静默按默认值运行，管理员还以为在用自己设的值。
2. **短 TTL 缓存**：默认缓存 10 秒，避免每次请求都查库；写入时立即失效，
   因此改完参数马上生效。若有人直接改数据库，最多 10 秒后也会生效。
3. 值统一以字符串存在库里，按 `value_type` 转换后返回。
"""

import json
import time

import ops_alerts
from models import SystemConfig

# 缓存存活秒数（直接改库时最多延迟这么久生效）
CACHE_TTL_SECONDS = 10

# `ai_extra_instruction` 的出厂内容：把高频问题的标准答法写进提示词。
#
# 为什么不靠模型自由发挥：涉及价格、优惠、资金安全的问题，必须按平台口径回答。
# 写在提示词里比每次让模型"临场判断"稳定得多，也避免它编造不存在的优惠。
# 后台可在「系统设置 → 系统参数」里整段改写或清空（清空后本节不再注入）。
DEFAULT_AI_EXTRA_INSTRUCTION = """【常见问答标准答法】（优先照这里的口径回答，比自由发挥更准）
· 问"能便宜点吗 / 打个折" → "价格是平台统一定价，我这边没有调整权限；可以关注「店铺公告」里的活动，有优惠都会写在那里～"
· 问"能不能私下转账 / 加微信交易" → "平台不支持私下交易哦，全部通过平台下单才有资金保障，也才能评价和投诉。"
· 问"你是什么 / 你是谁" → "我是布鲁斯，「大狗嚼电竞」的在线客服助手，平台业务相关的问题都可以问我～"
· 问"找人工客服 / 要真人" → "人工客服请通过平台内渠道联系，我这边能回答平台业务相关的问题～"
· 问与平台无关的话题（写代码、聊天、翻译、闲聊） → "这个我不太擅长，我只负责平台业务相关的问题～"

【资金安全】
· 平台任何人员（包括管理员）都**不会**向你索要密码、验证码、银行卡号或支付密码。
· 遇到要求转账到私人账户的情况，一律提醒用户"请勿私下转账，谨防上当受骗"。

【语气】
称呼用户用"你"，不要用"亲""宝子"。回答尽量控制在 3 句话内，能给步骤就给步骤。

【补充指示的优先级】
以下内容属于**风格与话术偏好**：在不违反上文「界面与操作路径」「权限」两节的前提下生效；
若与那两节冲突，一律以那两节为准。"""

# 参数元数据：默认值 + 类型 + 后台显示信息
# 注意：这里的默认值是"出厂值"，运行时一律以数据库为准
CONFIG_META: dict[str, dict] = {
    # ——— 资金与抽成 ———
    "club_commission_rate": {
        "default": 0.3, "type": "float", "group": "资金与抽成", "label": "俱乐部抽成比例",
        "desc": "0~1 的小数，0.3 表示抽成 30%。订单结单时按此拆分俱乐部与打手收入",
    },
    "tip_max_rate": {
        "default": 0.3, "type": "float", "group": "资金与抽成", "label": "打赏上限比例",
        "desc": "0~1 的小数，单笔订单累计打赏不得超过订单金额的该比例",
    },
    "withdraw_cooldown_days": {
        "default": 30, "type": "int", "group": "资金与抽成", "label": "提现冷却天数",
        "desc": "打手收入入账后需满多少天才能申请提现",
    },
    "recharge_max_amount": {
        "default": 10000000, "type": "int", "group": "资金与抽成", "label": "单次充值上限（分）",
        "desc": "单位：分。默认 10000000 = 10 万元",
    },
    # ——— 登录安全 ———
    "login_max_failed_attempts": {
        "default": 5, "type": "int", "group": "登录安全", "label": "登录失败锁定阈值",
        "desc": "连续输错密码多少次后锁定账户",
    },
    "login_lock_minutes": {
        "default": 10, "type": "int", "group": "登录安全", "label": "锁定时长（分钟）",
        "desc": "账户被锁定后需等待多少分钟才能再次登录",
    },
    "token_expire_minutes": {
        "default": 60 * 24, "type": "int", "group": "登录安全", "label": "登录令牌有效期（分钟）",
        "desc": "JWT 有效期，默认 1440 分钟 = 24 小时",
    },
    # ——— 订单校验 ———
    "order_min_amount": {
        "default": 100, "type": "int", "group": "订单校验", "label": "订单金额下限（分）",
        "desc": "单位：分。默认 100 = 1 元",
    },
    "order_max_amount": {
        "default": 5000000, "type": "int", "group": "订单校验", "label": "单笔订单金额上限（分）",
        "desc": "单位：分。默认 5000000 = 5 万元",
    },
    "order_max_duration_min": {
        "default": 1440, "type": "int", "group": "订单校验", "label": "单笔订单时长上限（分钟）",
        "desc": "单位：分钟。默认 1440 = 24 小时",
    },
    "order_remark_max_len": {
        "default": 500, "type": "int", "group": "订单校验", "label": "下单备注字数上限",
        "desc": "老板下单备注的最大字符数",
    },
    "order_service_note_max_len": {
        "default": 50, "type": "int", "group": "订单校验", "label": "业务量说明字数上限",
        "desc": "如“50级”“3层”等业务量说明的最大字符数",
    },
    "game_type_max_len": {
        "default": 50, "type": "int", "group": "订单校验", "label": "游戏类型字数上限",
        "desc": "订单游戏类型字段的最大字符数",
    },
    # ——— 资料校验 ———
    "nickname_max_len": {
        "default": 20, "type": "int", "group": "资料校验", "label": "昵称字数上限",
        "desc": "用户昵称的最大字符数",
    },
    "tag_max_len": {
        "default": 20, "type": "int", "group": "资料校验", "label": "标签字数上限",
        "desc": "打手标签的最大字符数",
    },
    "violation_nickname": {
        "default": "违规昵称", "type": "str", "group": "资料校验", "label": "违规昵称占位文案",
        "desc": "昵称被审核打回后，展示给该用户的替代昵称",
    },
    # ——— 打手等级 ———
    "tech_levels": {
        "default": ["985", "211", "大专", "魔王护", "明星护"], "type": "json", "group": "打手等级",
        "label": "技术陪等级列表", "desc": "JSON 数组，顺序即由低到高",
    },
    "level_types": {
        "default": ["娱乐陪", "技术陪"], "type": "json", "group": "打手等级",
        "label": "打手等级大类", "desc": "JSON 数组，打手等级的两大类",
    },
    # ——— AI 客服（千问）———
    "ai_enabled": {
        "default": True, "type": "bool", "group": "AI 客服", "label": "启用 AI 客服",
        "desc": "关闭后前端不显示聊天入口；仍需在 backend/.env 配置 DASHSCOPE_API_KEY 才能真正对话",
    },
    "ai_model": {
        "default": "qwen-plus", "type": "str", "group": "AI 客服", "label": "千问模型名",
        "desc": "如 qwen-plus（均衡）、qwen-turbo（快且便宜）、qwen-max（最强）",
    },
    "ai_daily_limit": {
        "default": 30, "type": "int", "group": "AI 客服", "label": "每人每日提问上限",
        "desc": "按用户按自然日统计，防止接口被刷导致费用失控；0 表示不限制",
    },
    "ai_temperature": {
        "default": 0.3, "type": "float", "group": "AI 客服", "label": "回答随机度",
        "desc": "0~2。客服场景建议偏低（0.2~0.5）以保证回答稳定、少发挥",
    },
    "ai_max_tokens": {
        "default": 800, "type": "int", "group": "AI 客服", "label": "单次回答最大长度",
        "desc": "模型单次回复的最大 token 数，调大可回答更详细但更慢更贵",
    },
    "ai_extra_instruction": {
        "default": DEFAULT_AI_EXTRA_INSTRUCTION, "type": "str", "group": "AI 客服", "label": "额外指示（附加到系统提示词末尾）",
        "desc": "出厂内容为常见问答标准答法与语气要求。可整段改写或清空；留空则本节不注入提示词",
    },
    "ai_history_rounds": {
        "default": 6, "type": "int", "group": "AI 客服", "label": "携带的历史轮数",
        "desc": "每次请求带上前多少轮对话作为上下文，越大越连贯但越贵",
    },
    "ai_faq_top_n": {
        "default": 4, "type": "int", "group": "AI 客服", "label": "问答库命中条数上限",
        "desc": "按提问关键词从「问答库」挑出最相关的几条注入提示词；0 表示关闭按需注入",
    },
    # ——— AI 知识库向量检索（RAG）———
    # 出厂**默认关闭**：向量检索要多调一次 embedding 接口（有成本、有失败可能），
    # 且只有把「知识库索引」页里的文档索引建好之后才有意义。管理员在那页验证过
    # 检索质量、确认召回正确后再打开，避免上线即踩坑。
    "ai_rag_enabled": {
        "default": False, "type": "bool", "group": "AI 知识库", "label": "启用知识库向量检索",
        "desc": "打开后按提问从「知识库索引」的文档中检索相关片段注入提示词。"
                "需先在「知识库索引」页点「重建索引」；embedding 调用失败会自动退回关键词匹配",
    },
    "ai_rag_top_k": {
        "default": 4, "type": "int", "group": "AI 知识库", "label": "向量检索片段条数上限",
        "desc": "每次提问最多注入几个相关片段；调大召回更全但提示词更长更贵",
    },
    "ai_rag_min_score": {
        "default": 0.35, "type": "float", "group": "AI 知识库", "label": "向量检索相似度门槛",
        "desc": "0~1 的余弦相似度。低于此分数的片段**不注入** —— 塞进不相关内容比不塞更糟，"
                "模型会照着错内容编。中文短句建议 0.3~0.45",
    },
    "ai_rag_embedding_model": {
        "default": "text-embedding-v3", "type": "str", "group": "AI 知识库", "label": "向量化模型",
        "desc": "千问 Embedding 模型名。换模型后旧向量维度不同，必须点「重建索引」全量重算",
    },
    "ai_rag_chunk_size": {
        "default": 500, "type": "int", "group": "AI 知识库", "label": "文档分块字符数",
        "desc": "长篇文档按此长度切成片段再向量化。太小会丢上下文，太大会稀释相关性",
    },
    "ai_rag_max_chars": {
        "default": 3000, "type": "int", "group": "AI 知识库", "label": "检索片段总字数上限",
        "desc": "单次注入的检索结果总长度上限，防止一次命中过多把提示词撑爆",
    },

    # —— RAG 模块开关（检索流程中每个环节可独立关闭，便于调试和对比效果）——
    "rag_module_query_rewrite": {
        "default": True, "type": "bool", "group": "RAG 模块开关", "label": "查询改写模块",
        "desc": "关闭后直接用原始问题检索，不经过查询优化器（省一次大模型调用）",
    },
    "rag_module_vector_retrieval": {
        "default": True, "type": "bool", "group": "RAG 模块开关", "label": "向量检索模块",
        "desc": "关闭后不做向量语义检索，只用关键词匹配",
    },
    "rag_module_keyword_retrieval": {
        "default": True, "type": "bool", "group": "RAG 模块开关", "label": "关键词检索模块",
        "desc": "关闭后不做 FAQ 关键词匹配，只用向量语义检索",
    },
    "rag_module_fusion": {
        "default": True, "type": "bool", "group": "RAG 模块开关", "label": "RRF 融合模块",
        "desc": "关闭后两路结果简单合并（向量在前关键词在后），不做加权 RRF 排序",
    },
    "rag_module_rerank": {
        "default": True, "type": "bool", "group": "RAG 模块开关", "label": "重排序模块",
        "desc": "关闭后跳过检索后重排序，直接用 RRF 融合结果构建上下文",
    },
    "rag_rerank_mode": {
        "default": "rule", "type": "select", "group": "RAG 模块开关", "label": "重排序模式",
        "options": [
            {"value": "rule", "label": "规则式（零成本，加权打分）"},
            {"value": "semantic", "label": "语义级 Cross-Encoder（大模型打分，更精准）"},
        ],
        "desc": "规则式：RRF+向量+关键词加权打分，零成本；语义级：调用大模型判断每段相关性，更精准但多1次API调用",
    },
    "rag_rerank_candidate_limit": {
        "default": 10, "type": "int", "group": "RAG 模块开关", "label": "语义重排序候选数",
        "desc": "语义级重排序时，送给大模型打分的最大候选片段数（太多会超token，建议8-12）",
    },
    "rag_module_automerge": {
        "default": True, "type": "bool", "group": "RAG 模块开关", "label": "AutoMerging 自动合并",
        "desc": "关闭后命中子块时不自动合并为整章，只返回命中的子块片段",
    },

    # —— 查询优化（检索前）：默认全关，需要时手动开启，每个开关都会多调一次大模型 ——
    "ai_query_rewrite_enabled": {
        "default": False, "type": "bool", "group": "查询优化", "label": "查询重写",
        "desc": "把口语化问题改写成标准检索查询",
    },
    "ai_query_decompose_enabled": {
        "default": False, "type": "bool", "group": "查询优化", "label": "子查询分解",
        "desc": "把复杂问题拆成多个子问题分别检索",
    },
    "ai_query_stepback_enabled": {
        "default": False, "type": "bool", "group": "查询优化", "label": "后退提示",
        "desc": "生成更抽象的问题获取背景规则",
    },
    "ai_query_expand_enabled": {
        "default": False, "type": "bool", "group": "查询优化", "label": "查询扩展",
        "desc": "补充同义词/相关关键词，扩大召回覆盖面",
    },
    "ai_query_hyde_enabled": {
        "default": False, "type": "bool", "group": "查询优化", "label": "HyDE 假设文档",
        "desc": "先生成假设答案，用答案措辞做向量检索",
    },

    # —— Self-RAG（自我反思检索）：让大模型自己判断要不要检索、内容有没有用、回答靠不靠谱 ——
    # 每个开关都会多调一次大模型，按需开启
    "ai_self_rag_enabled": {
        "default": False, "type": "bool", "group": "Self-RAG", "label": "启用 Self-RAG",
        "desc": "总开关。打开后大模型会自我反思：是否需要检索、检索内容是否相关、回答是否被支持",
    },
    "ai_self_rag_retrieve_check": {
        "default": True, "type": "bool", "group": "Self-RAG", "label": "检索前判断",
        "desc": "大模型先判断问题是否需要检索知识库，不需要则跳过检索直接回答（省 embedding 调用）",
    },
    "ai_self_rag_relevance_filter": {
        "default": True, "type": "bool", "group": "Self-RAG", "label": "检索后相关性过滤",
        "desc": "大模型对检索到的每个片段打分（1-5），过滤掉不相关的，减少噪音",
    },
    "ai_self_rag_relevance_threshold": {
        "default": 3, "type": "int", "group": "Self-RAG", "label": "相关性过滤阈值",
        "desc": "大模型打分1-5，低于此分数的片段被过滤。默认3（过滤≤2分）；调为2更宽松（只过滤完全不相关），调为4更严格",
    },
    "ai_self_rag_verify_answer": {
        "default": False, "type": "bool", "group": "Self-RAG", "label": "生成后回答验证",
        "desc": "大模型检查回答是否被知识库支持，不支持则修正（最耗 token，建议调试时开启）",
    },
}

# 进程内缓存：{key: (值, 写入时间)}
_cache: dict[str, tuple[object, float]] = {}


def invalidate_cache() -> None:
    """清空缓存（写入参数后调用）"""
    _cache.clear()


def _coerce(raw: str, value_type: str, key: str):
    """把库里的字符串按类型转换；失败则抛异常由调用方兜底"""
    if value_type == "int":
        return int(float(raw))  # 容忍 "30.0" 这类写法
    if value_type == "float":
        return float(raw)
    if value_type == "bool":
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    if value_type == "json":
        return json.loads(raw)
    return raw


def get_config(key: str, db=None, default=None):
    """读取单个参数（带缓存与默认值兜底）。

    db 可传可不传：不传时自行开一个会话，便于在非请求上下文（启动初始化）中调用。
    """
    meta = CONFIG_META.get(key)
    fallback = default if default is not None else (meta or {}).get("default")

    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[1] < CACHE_TTL_SECONDS:
        return hit[0]

    value = fallback
    row = None
    own_session = False
    try:
        if db is None:
            from database import SessionLocal
            db = SessionLocal()
            own_session = True
        row = db.query(SystemConfig).filter(SystemConfig.config_key == key).first()
    except Exception as e:  # 查库失败不应影响业务，直接用默认值
        # 但必须留痕：否则连不上库时会静默按出厂默认跑，管理员还以为在用后台设的值
        ops_alerts.record(f"config_read:{key}",
                          f"读取系统参数 {key} 失败，已临时使用默认值 {fallback!r}：{e}")
        print(f"[config] 读取 {key} 失败，使用默认值 {fallback!r}：{e}")
    finally:
        if own_session and db is not None:
            try:
                db.close()
            except Exception:
                pass

    if row is not None and row.config_value is not None:
        try:
            value = _coerce(row.config_value, row.value_type or (meta or {}).get("type", "str"), key)
        except Exception as e:
            ops_alerts.record(f"config_bad_value:{key}",
                              f"系统参数 {key} 的值 {row.config_value!r} 不是合法的 "
                              f"{row.value_type}，已临时按默认值 {fallback!r} 运行。"
                              f"请到「系统参数」页修正该项")
            print(f"[config] 参数 {key} 的值 {row.config_value!r} 无法转为 "
                  f"{row.value_type}，回退默认值 {fallback!r}：{e}")
            value = fallback

    _cache[key] = (value, now)
    return value


def get_all_configs(db) -> list[dict]:
    """读取全部参数，供后台设置页展示（含元信息）"""
    rows = {r.config_key: r for r in db.query(SystemConfig).all()}
    result = []
    for key, meta in CONFIG_META.items():
        row = rows.get(key)
        current = row.config_value if row else _dump(meta["default"], meta["type"])
        result.append({
            "config_key": key,
            "config_value": current,
            "value_type": meta["type"],
            "group": meta.get("group", "其他"),
            "label": meta["label"],
            "description": meta["desc"],
            "default_value": _dump(meta["default"], meta["type"]),
            "options": meta.get("options"),  # select 类型的选项列表
        })
    return result


def _dump(value, value_type: str) -> str:
    """把 Python 值序列化成库里存的字符串"""
    if value_type == "json":
        return json.dumps(value, ensure_ascii=False)
    if value_type == "bool":
        return "1" if value else "0"
    return str(value)


def set_config(db, key: str, raw_value) -> str:
    """写入参数（校验类型合法性），返回实际存入库的字符串。

    校验失败直接抛 ValueError，由接口层转为 400。
    """
    meta = CONFIG_META.get(key)
    if meta is None:
        raise ValueError(f"未知参数：{key}")

    text = str(raw_value).strip()
    value_type = meta["type"]

    # 校验：转不过去就拒绝，避免把非法值写进库
    try:
        parsed = _coerce(text, value_type, key)
    except Exception:
        raise ValueError(f"参数值格式不正确，应为 {value_type} 类型")

    # 额外业务校验
    if value_type == "float" and key.endswith("_rate"):
        if not (0 <= parsed <= 1):
            raise ValueError("比例必须在 0~1 之间（如 0.3 表示 30%）")
    if value_type == "int" and parsed < 0:
        raise ValueError("该参数不能为负数")
    if value_type == "json" and not isinstance(parsed, list):
        raise ValueError("该参数应为 JSON 数组，如 [\"A\", \"B\"]")
    if value_type == "json" and isinstance(parsed, list) and not parsed:
        raise ValueError("数组不能为空")

    row = db.query(SystemConfig).filter(SystemConfig.config_key == key).first()
    if row is None:
        row = SystemConfig(config_key=key, value_type=value_type,
                           label=meta["label"], description=meta["desc"])
        db.add(row)
    row.config_value = text
    row.value_type = value_type
    row.label = meta["label"]
    row.description = meta["desc"]
    db.commit()
    invalidate_cache()
    return text


def ensure_defaults(db) -> int:
    """补齐缺失的参数行（幂等，不覆盖已有值）。返回新增条数。"""
    existing = {r.config_key for r in db.query(SystemConfig).all()}
    added = 0
    for key, meta in CONFIG_META.items():
        if key in existing:
            continue
        db.add(SystemConfig(
            config_key=key,
            config_value=_dump(meta["default"], meta["type"]),
            value_type=meta["type"],
            label=meta["label"],
            description=meta["desc"],
        ))
        added += 1
    if added:
        db.commit()
        invalidate_cache()
    return added


# ——— 语义化快捷方法（业务代码用这些，避免到处写字符串 key）———

def commission_rate(db=None) -> float:
    return float(get_config("club_commission_rate", db))


def tip_max_rate(db=None) -> float:
    return float(get_config("tip_max_rate", db))


def withdraw_cooldown_days(db=None) -> int:
    return int(get_config("withdraw_cooldown_days", db))


def login_max_failed_attempts(db=None) -> int:
    return int(get_config("login_max_failed_attempts", db))


def login_lock_minutes(db=None) -> int:
    return int(get_config("login_lock_minutes", db))


def tech_levels(db=None) -> list:
    return list(get_config("tech_levels", db))


def level_types(db=None) -> list:
    return list(get_config("level_types", db))
