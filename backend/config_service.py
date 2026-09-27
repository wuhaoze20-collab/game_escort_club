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

# 参数元数据：默认值 + 类型 + 后台显示信息
# 注意：这里的默认值是"出厂值"，运行时一律以数据库为准
CONFIG_META: dict[str, dict] = {
    # ——— 资金与抽成 ———
    "club_commission_rate": {
        "default": 0.3, "type": "float", "label": "俱乐部抽成比例",
        "desc": "0~1 的小数，0.3 表示抽成 30%。订单结单时按此拆分俱乐部与打手收入",
    },
    "tip_max_rate": {
        "default": 0.3, "type": "float", "label": "打赏上限比例",
        "desc": "0~1 的小数，单笔订单累计打赏不得超过订单金额的该比例",
    },
    "withdraw_cooldown_days": {
        "default": 30, "type": "int", "label": "提现冷却天数",
        "desc": "打手收入入账后需满多少天才能申请提现",
    },
    "recharge_max_amount": {
        "default": 10000000, "type": "int", "label": "单次充值上限（分）",
        "desc": "单位：分。默认 10000000 = 10 万元",
    },
    # ——— 登录安全 ———
    "login_max_failed_attempts": {
        "default": 5, "type": "int", "label": "登录失败锁定阈值",
        "desc": "连续输错密码多少次后锁定账户",
    },
    "login_lock_minutes": {
        "default": 10, "type": "int", "label": "锁定时长（分钟）",
        "desc": "账户被锁定后需等待多少分钟才能再次登录",
    },
    "token_expire_minutes": {
        "default": 60 * 24, "type": "int", "label": "登录令牌有效期（分钟）",
        "desc": "JWT 有效期，默认 1440 分钟 = 24 小时",
    },
    # ——— 订单校验 ———
    "order_min_amount": {
        "default": 100, "type": "int", "label": "订单金额下限（分）",
        "desc": "单位：分。默认 100 = 1 元",
    },
    "order_max_amount": {
        "default": 5000000, "type": "int", "label": "单笔订单金额上限（分）",
        "desc": "单位：分。默认 5000000 = 5 万元",
    },
    "order_max_duration_min": {
        "default": 1440, "type": "int", "label": "单笔订单时长上限（分钟）",
        "desc": "单位：分钟。默认 1440 = 24 小时",
    },
    "order_remark_max_len": {
        "default": 500, "type": "int", "label": "下单备注字数上限",
        "desc": "老板下单备注的最大字符数",
    },
    "order_service_note_max_len": {
        "default": 50, "type": "int", "label": "业务量说明字数上限",
        "desc": "如“50级”“3层”等业务量说明的最大字符数",
    },
    "game_type_max_len": {
        "default": 50, "type": "int", "label": "游戏类型字数上限",
        "desc": "订单游戏类型字段的最大字符数",
    },
    # ——— 资料校验 ———
    "nickname_max_len": {
        "default": 20, "type": "int", "label": "昵称字数上限",
        "desc": "用户昵称的最大字符数",
    },
    "tag_max_len": {
        "default": 20, "type": "int", "label": "标签字数上限",
        "desc": "打手标签的最大字符数",
    },
    "violation_nickname": {
        "default": "违规昵称", "type": "str", "label": "违规昵称占位文案",
        "desc": "昵称被审核打回后，展示给该用户的替代昵称",
    },
    # ——— 打手等级 ———
    "tech_levels": {
        "default": ["985", "211", "大专", "魔王护", "明星护"], "type": "json",
        "label": "技术陪等级列表", "desc": "JSON 数组，顺序即由低到高",
    },
    "level_types": {
        "default": ["娱乐陪", "技术陪"], "type": "json",
        "label": "打手等级大类", "desc": "JSON 数组，打手等级的两大类",
    },
    # ——— AI 客服（千问）———
    "ai_enabled": {
        "default": True, "type": "bool", "label": "启用 AI 客服",
        "desc": "关闭后前端不显示聊天入口；仍需在 backend/.env 配置 DASHSCOPE_API_KEY 才能真正对话",
    },
    "ai_model": {
        "default": "qwen-plus", "type": "str", "label": "千问模型名",
        "desc": "如 qwen-plus（均衡）、qwen-turbo（快且便宜）、qwen-max（最强）",
    },
    "ai_daily_limit": {
        "default": 30, "type": "int", "label": "每人每日提问上限",
        "desc": "按用户按自然日统计，防止接口被刷导致费用失控；0 表示不限制",
    },
    "ai_temperature": {
        "default": 0.3, "type": "float", "label": "回答随机度",
        "desc": "0~2。客服场景建议偏低（0.2~0.5）以保证回答稳定、少发挥",
    },
    "ai_max_tokens": {
        "default": 800, "type": "int", "label": "单次回答最大长度",
        "desc": "模型单次回复的最大 token 数，调大可回答更详细但更慢更贵",
    },
    "ai_extra_instruction": {
        "default": "", "type": "str", "label": "额外指示（附加到系统提示词末尾）",
        "desc": "可写临时话术要求，如「最近有活动，记得提醒老板充值有赠送」。留空则不加",
    },
    "ai_history_rounds": {
        "default": 6, "type": "int", "label": "携带的历史轮数",
        "desc": "每次请求带上前多少轮对话作为上下文，越大越连贯但越贵",
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
            "label": meta["label"],
            "description": meta["desc"],
            "default_value": _dump(meta["default"], meta["type"]),
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
