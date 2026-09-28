# -*- coding: utf-8 -*-
"""AI 工具（Function Calling）—— 让 AI 从"会说"变成"会做"。

为什么需要这一层
----------------
提示词工程的天花板是"回答得准"，但用户问"我那单到哪了""我能提多少"时，
AI 手上没有实时数据，只能让用户自己去页面看。给它工具后，它可以真的查库后回答。

三条铁律（本模块的设计核心）
----------------------------
1. **身份只来自令牌，绝不接受 AI "听来"的参数。**
   所有工具函数都只接收 (db, user)，而 user 是接口层用 current_user 传进来的。
   **函数签名里没有 username 参数** —— 这样就算模型被诱导去"查别人的余额"，
   它也无从表达这个意图。这是防越权的根本，比在提示词里写"不要查别人"可靠得多。
2. **权限与 HTTP 接口同源。** TOOL_ROLES 里的角色必须与各接口上的 require_roles
   一致；`run_tool` 每次执行前都要再校验一次（模型可能编造工具名或越权调用）。
3. **只读。** 这里全部是查询工具，没有下单/提现/拉黑这类写操作。
   写操作必须由用户在界面上二次确认，不能让 AI 直接改库。

维护提示：新增工具时同步更新 TOOLS（给模型看的声明）与 TOOL_ROLES（权限），
并在 README 的工具表里登记。
"""

from datetime import datetime

MONEY_PER_YUAN = 100  # 订单/工资/打赏等金额单位为「分」

ORDER_STATUS_LABELS = {
    "pending": "待派单",
    "pending_accept": "待打手确认",
    "assigned": "已派单",
    "processing": "服务中",
    "pending_settlement": "待老板确认结单",
    "completed": "已完成",
    "rejected": "打手已拒单",
    "cancelled": "已取消",
}

# 工具 → 允许调用的角色。务必与对应 HTTP 接口的 require_roles 保持一致。
TOOL_ROLES = {
    "query_my_orders": ("boss", "player"),
    "query_my_balance": ("boss", "player"),
    "query_price": ("admin", "service", "boss", "player"),
    "query_my_withdrawals": ("player",),
    "query_monthly_profit": ("admin",),
}

# 给模型看的工具声明（OpenAI / 千问兼容格式）
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_my_orders",
            "description": ("查询**当前用户自己**的订单（不需要也不能指定用户名）。"
                            "凡是问到『我的订单』『我那单到哪了』『有没有待接的单』"
                            "『这单什么状态』这类**涉及具体订单状态**的问题，"
                            "**必须先调用本工具拿到真实订单再回答**，不要只讲操作路径。"),
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "可选，按状态过滤。取值：pending/pending_accept/assigned/"
                                       "processing/pending_settlement/completed/rejected/cancelled。"
                                       "不填则返回最近的订单。",
                    },
                    "limit": {"type": "integer", "description": "返回条数，默认 5，最多 10"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_my_balance",
            "description": ("查询**当前用户自己**的余额（不能指定他人）。"
                            "老板返回大狗币余额；打手返回后台金额与可提现金额。"
                            "用户问『我还有多少钱』『能提多少』时使用。"),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_price",
            "description": ("查询平台价目表（游戏 / 段位 / 单价）。"
                            "用户问『XX 多少钱』『价格表』时使用。"),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string",
                                "description": "可选，按游戏名或段位过滤，如『无畏契约』『钻石』"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_my_withdrawals",
            "description": ("查询**当前打手自己**的提现记录与可提现金额（不能查他人）。"
                            "凡是问到『我的提现到哪了』『为什么还没到账』『我提了多少钱』"
                            "『我还有多少能提』这类**涉及具体状态或数字**的问题，"
                            "**必须先调用本工具拿到真实记录再回答**，不要只讲操作路径。"),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_monthly_profit",
            "description": "查询本月盈利、订单总额与打手发放总额。**仅管理员**可用。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def available_tools(role: str) -> list:
    """按角色筛出可用的工具声明（不把无权限的工具暴露给模型，减少它乱猜的机会）"""
    allowed = {n for n, roles in TOOL_ROLES.items() if role in roles}
    if not allowed:
        return []
    return [t for t in TOOLS if t["function"]["name"] in allowed]


def _yuan(cents) -> str:
    """分 -> 元的可读字符串"""
    try:
        return f"{int(cents or 0) / MONEY_PER_YUAN:.2f}"
    except Exception:
        return "0.00"


def _coins(v) -> str:
    """大狗币（DECIMAL）-> 可读字符串"""
    try:
        return f"{float(v or 0):.2f}"
    except Exception:
        return "0.00"


# ══════════════════════════════════════════════
# 各工具实现：签名一律是 (db, user, **args) —— 没有 username 参数
# ══════════════════════════════════════════════

def _tool_query_my_orders(db, user, status="", limit=5):
    from models import Order
    try:
        limit = max(1, min(10, int(limit or 5)))
    except Exception:
        limit = 5
    q = db.query(Order).filter(Order.boss_username == user.username) if user.role == "boss" \
        else db.query(Order).filter(Order.player_username == user.username)
    if status:
        status = str(status).strip()
        if status not in ORDER_STATUS_LABELS:
            # 抛 ValueError 而不是返回提示文本：让 run_tool 统一判定为 ok=False，
            # 与"权限不足""参数类型错"保持同一语义（ok=False 表示模型该看消息或改口）
            raise ValueError(f"状态参数无效：{status}。有效取值："
                             + "、".join(ORDER_STATUS_LABELS))
        q = q.filter(Order.status == status)
    rows = q.order_by(Order.id.desc()).limit(limit).all()
    if not rows:
        return ("你目前没有" + (f"状态为「{ORDER_STATUS_LABELS[status]}」的" if status else "")
                + "订单。")
    lines = [f"你最近的订单（共显示 {len(rows)} 条）："]
    for o in rows:
        who = ("打手：" + o.player_username) if user.role == "boss" else ("老板：" + o.boss_username)
        lines.append(f"· 订单号 {o.order_no}（{o.game_type}）　状态："
                     f"{ORDER_STATUS_LABELS.get(o.status, o.status)}　金额：{_yuan(o.total_amount)} 元　{who}")
    return "\n".join(lines)


def _tool_query_my_balance(db, user):
    from models import BossInfo, PlayerInfo
    if user.role == "boss":
        b = db.query(BossInfo).filter(BossInfo.username == user.username).first()
        if not b:
            return "你的老板账户信息不存在，请联系管理员。"
        return (f"你的大狗币余额是 {_coins(b.balance)} 枚（1 大狗币 = 1 元），"
                f"累计消费 {_yuan(b.consume_amount)} 元，累计点单 {b.order_count or 0} 次。")
    p = db.query(PlayerInfo).filter(PlayerInfo.username == user.username).first()
    if not p:
        return "你的打手账户信息不存在，请联系管理员。"
    # 可提现金额复用与提现接口同一套算法，避免两处口径不一致
    try:
        from api.withdraw_api import calc_available_amount
        available = calc_available_amount(db, user.username)
        avail_text = f"当前可提现 {_yuan(available)} 元"
    except Exception:
        avail_text = "可提现金额请到「提现中心」查看"
    return (f"你的后台金额是 {_yuan(p.backend_amount)} 元，{avail_text}。"
            f"累计接单 {p.order_count or 0} 次，好评率 "
            f"{('%.1f%%' % p.good_rate) if p.good_rate is not None else '暂无评价'}。")


def _tool_query_price(db, user, keyword=""):
    import json
    from models import ContentConfig
    row = db.query(ContentConfig).filter(ContentConfig.config_key == "price").first()
    if not row or not row.config_value:
        return "平台价目表暂时没有配置，请在「价格预览」页面查看或联系人工客服。"
    try:
        items = json.loads(row.config_value)
    except Exception:
        return "价目表数据格式异常，请到「价格预览」页面查看。"
    if not isinstance(items, list):
        return "价目表数据格式异常，请到「价格预览」页面查看。"
    if keyword:
        k = str(keyword).strip().lower()
        items = [i for i in items
                 if k in str(i.get("game", "")).lower() or k in str(i.get("rank", "")).lower()]
    if not items:
        return (f"价目表里没有找到与「{keyword}」匹配的项目，"
                f"完整价目请看「店铺运营 → 价格预览」。")
    lines = ["平台价目："]
    for i in items[:20]:
        # unit 本身已含单位（如「元/小时」），不要再补「元/」，否则会输出「25 元/元/小时」
        lines.append(f"· {i.get('game', '')}　{i.get('rank', '')}　{i.get('price', '')} {i.get('unit', '')}")
    if len(items) > 20:
        lines.append(f"（共 {len(items)} 项，此处只列前 20 项）")
    return "\n".join(lines)


def _tool_query_my_withdrawals(db, user):
    from models import WithdrawalRecord
    from api.withdraw_api import calc_available_amount
    labels = {"pending": "审核中", "approved": "已通过", "rejected": "已驳回"}
    try:
        available = calc_available_amount(db, user.username)
    except Exception:
        available = None
    rows = (db.query(WithdrawalRecord)
            .filter(WithdrawalRecord.player_username == user.username)
            .order_by(WithdrawalRecord.id.desc()).limit(5).all())
    head = f"可提现金额：{_yuan(available)} 元。" if available is not None else ""
    if not rows:
        return head + "你目前没有提现记录。"
    lines = [head + f"你最近的提现申请（共显示 {len(rows)} 条）："]
    for w in rows:
        when = w.created_at.strftime("%Y-%m-%d %H:%M") if w.created_at else ""
        lines.append(f"· {_yuan(w.amount)} 元　状态：{labels.get(w.status, w.status)}　申请时间：{when}"
                     + (f"　备注：{w.note}" if getattr(w, "note", "") else ""))
    return "\n".join(lines)


def _tool_query_monthly_profit(db, user):
    from models import Order, SalaryRecord
    now = datetime.now()
    month_start = datetime(now.year, now.month, 1)
    records = db.query(SalaryRecord).filter(SalaryRecord.settlement_time >= month_start).all()
    profit = sum(r.club_commission for r in records)
    total = sum(r.order_total for r in records)
    payout = sum(r.player_income for r in records)
    count = (db.query(Order)
             .filter(Order.status == "completed", Order.end_time >= month_start).count())
    return (f"{now.strftime('%Y 年 %m 月')}：本月盈利（俱乐部抽成）{_yuan(profit)} 元，"
            f"订单总额 {_yuan(total)} 元，打手发放 {_yuan(payout)} 元，已完成订单 {count} 单。")


_IMPL = {
    "query_my_orders": _tool_query_my_orders,
    "query_my_balance": _tool_query_my_balance,
    "query_price": _tool_query_price,
    "query_my_withdrawals": _tool_query_my_withdrawals,
    "query_monthly_profit": _tool_query_monthly_profit,
}


def run_tool(name: str, args: dict, db, user) -> dict:
    """执行一个工具。**永不抛异常**，一律返回 {"ok": bool, "result": str}。

    result 会被原样作为 tool 消息喂回模型，所以里面的措辞模型会照着回答。
    失败时也要给出可读原因，避免模型收到空内容后开始编造。
    """
    if name not in _IMPL:
        return {"ok": False, "result": f"没有名为 {name} 的工具。"}
    allowed = TOOL_ROLES.get(name, ())
    role = getattr(user, "role", "") or ""
    if role not in allowed:
        # 二次校验：即使模型编造/越权调用，也在这里被拦住
        return {"ok": False,
                "result": "你没有权限查询这个信息。如果用户坚持，请说明该信息需要"
                          "其他角色（" + "、".join(allowed) + "）才能查看。"}
    try:
        text = _IMPL[name](db, user, **(args or {}))
        return {"ok": True, "result": text}
    except TypeError as e:
        # 参数不匹配（模型给了不存在的参数名，例如试图传 username 查别人的数据）
        return {"ok": False, "result": f"工具参数不正确：{e}"}
    except ValueError as e:
        # 参数取值非法（如状态写了不存在的值）——把合法取值告诉模型，让它自己纠正
        return {"ok": False, "result": str(e)}
    except Exception as e:
        return {"ok": False, "result": f"查询失败（{type(e).__name__}），请稍后再试或联系人工客服。"}
