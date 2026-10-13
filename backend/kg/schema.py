"""知识图谱的模型定义（图谱的"字典"）。

这里集中声明「图里有哪些节点、哪些关系、每个字段是什么意思」，
同步逻辑（sync.py）、查询接口（api.py）、前端画图都从这里取定义，
避免同一套语义在三个地方各写一遍、改一处忘一处。

=== 图谱长什么样 ===

以一笔订单为中心，图谱把三类业务实体连起来：

    (Boss) --PLACED--> (Order) --FOR_GAME--> (Game)
                         ^
                         | SERVED
                         |
                      (Player) --HAS_TAG--> (Tag)

    (Boss) --HIRED--> (Player)      # 由订单推导：这位老板点过这位打手

每个节点都有一个业务主键 `key`（老板/打手用 username，订单用 order_no，
游戏用游戏名，标签用"打手名:标签名"），MERGE 靠这个 key 保证幂等——
同一笔订单同步十次，图里也只有一份。
"""

# ——————————————————————————————————————————————
# 节点标签
# ——————————————————————————————————————————————

LABEL_BOSS = "Boss"
LABEL_PLAYER = "Player"
LABEL_ORDER = "Order"
LABEL_GAME = "Game"
LABEL_TAG = "Tag"
LABEL_RATING = "Rating"
LABEL_TIP = "Tip"
LABEL_WITHDRAWAL = "Withdrawal"
LABEL_PUNISHMENT = "Punishment"

# 节点定义：标签 → 元信息
#   name    中文显示名
#   key     业务主键字段（MERGE 与 API 定位都用它）
#   color   前端画图配色
#   fields  字段 → (中文名, 是否敏感)
#           「敏感」= 只有管理员能看（后台金额这类，普通角色要屏蔽）
NODE_TYPES = {
    LABEL_BOSS: {
        "name": "老板",
        "key": "username",
        "color": "#3b82f6",
        "fields": {
            "username": ("账户名", False),
            "nickname": ("昵称", False),
            "avatar": ("头像", False),
            "balance": ("大狗币余额", True),
            "consume_amount": ("累计消费", True),
            "order_count": ("点单次数", False),
            "blacklisted": ("已拉黑", False),
        },
    },
    LABEL_PLAYER: {
        "name": "打手",
        "key": "username",
        "color": "#10b981",
        "fields": {
            "username": ("账户名", False),
            "nickname": ("昵称", False),
            "avatar": ("头像", False),
            "level_type": ("等级大类", False),
            "tech_level": ("技术陪细分", False),
            "order_count": ("接单次数", False),
            "complaint_count": ("投诉次数", False),
            "good_rate": ("好评率", False),
            "backend_amount": ("后台金额", True),
            "blacklisted": ("已拉黑", False),
        },
    },
    LABEL_ORDER: {
        "name": "订单",
        "key": "order_no",
        "color": "#f59e0b",
        "fields": {
            "order_no": ("订单号", False),
            "game_type": ("游戏类型", False),
            "duration_min": ("服务时长(分钟)", False),
            "total_amount": ("订单金额(分)", True),
            "service_note": ("业务量说明", False),
            "remark": ("下单备注", False),
            "status": ("订单状态", False),
            "created_at": ("下单时间", False),
            "start_time": ("开始服务时间", False),
            "end_time": ("结束时间", False),
        },
    },
    LABEL_GAME: {
        "name": "游戏",
        "key": "name",
        "color": "#8b5cf6",
        "fields": {
            "name": ("游戏名称", False),
            "order_count": ("订单数", False),
        },
    },
    LABEL_TAG: {
        "name": "打手标签",
        "key": "tag_key",
        "color": "#ec4899",
        "fields": {
            "tag_key": ("标签主键", False),
            "name": ("标签内容", False),
            "status": ("审核状态", False),
        },
    },
    # 以下四类来自 V4.11.0：把「一单结束之后发生的事」也接进图谱。
    # 订单只记录"服务发生了"，评价/打赏/投诉/提现记录的是"结果如何"——
    # 没有这几类节点，图谱答不出「谁给谁打赏过」「这个打手被投诉几次」。
    LABEL_RATING: {
        "name": "评价",
        "key": "rating_id",
        "color": "#eab308",
        "fields": {
            "rating_id": ("评价ID", False),
            "rating": ("星级", False),
            "comment": ("评价内容", False),
            "reply": ("打手回复", False),
            "is_complaint": ("是否投诉", False),
            "review_status": ("复查状态", False),
            "created_at": ("评价时间", False),
        },
    },
    LABEL_TIP: {
        "name": "打赏",
        "key": "tip_id",
        "color": "#f43f5e",
        "fields": {
            "tip_id": ("打赏ID", False),
            "amount": ("打赏金额(分)", True),
            "created_at": ("打赏时间", False),
        },
    },
    LABEL_WITHDRAWAL: {
        "name": "提现",
        "key": "wd_id",
        "color": "#06b6d4",
        "fields": {
            "wd_id": ("提现ID", False),
            "amount": ("提现金额(分)", True),
            "status": ("提现状态", False),
            "note": ("审核备注", False),
            "created_at": ("申请时间", False),
            "processed_at": ("审核时间", False),
        },
    },
    LABEL_PUNISHMENT: {
        "name": "处罚通告",
        "key": "punish_key",
        "color": "#dc2626",
        "fields": {
            "punish_key": ("通告主键", False),
            "level": ("处罚等级", False),
            "desc": ("处罚说明", False),
            "date": ("公示日期", False),
            "target": ("涉及账号", False),
        },
    },
}

# ——————————————————————————————————————————————
# 关系类型
# ——————————————————————————————————————————————

REL_PLACED = "PLACED"
REL_SERVED = "SERVED"
REL_FOR_GAME = "FOR_GAME"
REL_HAS_TAG = "HAS_TAG"
REL_HIRED = "HIRED"
REL_RATED = "RATED"
REL_ABOUT = "ABOUT"
REL_FOR_ORDER = "FOR_ORDER"
REL_COMPLAINED = "COMPLAINED"
REL_TIPPED = "TIPPED"
REL_TO = "TO"
REL_WITHDREW = "WITHDREW"
REL_PUNISHED = "PUNISHED"

# 关系定义：(起点标签, 关系名, 终点标签) → {name: 中文名, color: 前端配色}
REL_TYPES = {
    "(Boss)-[PLACED]->(Order)": {
        "start": LABEL_BOSS, "rel": REL_PLACED, "end": LABEL_ORDER,
        "name": "下单", "color": "#3b82f6",
    },
    "(Player)-[SERVED]->(Order)": {
        "start": LABEL_PLAYER, "rel": REL_SERVED, "end": LABEL_ORDER,
        "name": "接单", "color": "#10b981",
    },
    "(Order)-[FOR_GAME]->(Game)": {
        "start": LABEL_ORDER, "rel": REL_FOR_GAME, "end": LABEL_GAME,
        "name": "所属游戏", "color": "#8b5cf6",
    },
    "(Player)-[HAS_TAG]->(Tag)": {
        "start": LABEL_PLAYER, "rel": REL_HAS_TAG, "end": LABEL_TAG,
        "name": "持有标签", "color": "#ec4899",
    },
    "(Boss)-[HIRED]->(Player)": {
        "start": LABEL_BOSS, "rel": REL_HIRED, "end": LABEL_PLAYER,
        "name": "雇佣过", "color": "#f97316",
    },
    # —— V4.11.0 新增：订单之后发生的事 ——
    "(Boss)-[RATED]->(Rating)": {
        "start": LABEL_BOSS, "rel": REL_RATED, "end": LABEL_RATING,
        "name": "评价", "color": "#eab308",
    },
    # 评价与打赏都是"三段式"：老板 → 中间节点（正文/金额）→ 打手。
    # 中间那段用「给」，读起来才是
    #   老板 —评价了→ [这个打手真强] —给→ 打手
    #   老板 —打赏→ [打赏 ¥16.00] —给→ 打手
    "(Rating)-[ABOUT]->(Player)": {
        "start": LABEL_RATING, "rel": REL_ABOUT, "end": LABEL_PLAYER,
        "name": "给", "color": "#a3e635",
    },
    "(Rating)-[FOR_ORDER]->(Order)": {
        "start": LABEL_RATING, "rel": REL_FOR_ORDER, "end": LABEL_ORDER,
        "name": "评价订单", "color": "#facc15",
    },
    "(Boss)-[COMPLAINED]->(Player)": {
        "start": LABEL_BOSS, "rel": REL_COMPLAINED, "end": LABEL_PLAYER,
        "name": "投诉过", "color": "#ef4444",
    },
    "(Boss)-[TIPPED]->(Tip)": {
        "start": LABEL_BOSS, "rel": REL_TIPPED, "end": LABEL_TIP,
        "name": "打赏", "color": "#f43f5e",
    },
    "(Tip)-[TO]->(Player)": {
        "start": LABEL_TIP, "rel": REL_TO, "end": LABEL_PLAYER,
        "name": "给", "color": "#fb7185",
    },
    "(Player)-[WITHDREW]->(Withdrawal)": {
        "start": LABEL_PLAYER, "rel": REL_WITHDREW, "end": LABEL_WITHDRAWAL,
        "name": "提现", "color": "#06b6d4",
    },
    "(Boss)-[PUNISHED]->(Punishment)": {
        "start": LABEL_BOSS, "rel": REL_PUNISHED, "end": LABEL_PUNISHMENT,
        "name": "被处罚", "color": "#dc2626",
    },
    "(Player)-[PUNISHED]->(Punishment)": {
        "start": LABEL_PLAYER, "rel": REL_PUNISHED, "end": LABEL_PUNISHMENT,
        "name": "被处罚", "color": "#b91c1c",
    },
}

# 订单状态的中文显示（与 order_api.py 的状态流转保持一致）
ORDER_STATUS_TEXT = {
    "pending": "待派单",
    "pending_accept": "待打手确认",
    "assigned": "已接单",
    "processing": "服务中",
    "pending_settlement": "待确认结单",
    "completed": "已完成",
    "rejected": "已拒单",
    "cancelled": "已取消",
}

# 评价复查状态中文（rating_api 的 review_status）
REVIEW_STATUS_TEXT = {
    "normal": "正常展示",
    "reviewing": "复查中",
    "removed": "已删除",
}

# 提现状态中文
WITHDRAW_STATUS_TEXT = {
    "pending": "待审核",
    "approved": "已通过",
    "rejected": "已驳回",
}

# 打手标签的审核状态中文（PlayerTag.status）
TAG_STATUS_TEXT = {
    "pending": "待审核",
    "approved": "已通过",
    "rejected": "已驳回",
}

# 是否类字段的中文。
# 键统一用小写：Python 的 str(True) 是 "True"，而 JS 的 String(true) 是 "true"，
# 不下发同一套小写键的话前端查表会落空（api._enum_for 也会再兜一层小写）。
BOOL_TEXT = {"true": "是", "false": "否"}


# ——————————————————————————————————————————————
# 字段口径：枚举、单位
# ——————————————————————————————————————————————
# 这两张表是给前端看的——库内取值（pending / normal / 1620）要翻成
# 「待完成」「正常展示」「¥16.20」才能读。映射放在后端，前端只查表不写死字典，
# 这样以后改了状态名或加了等级，图谱页不会和后端脱节。

# (节点标签, 字段名) → 取值的中文映射
FIELD_ENUMS = {
    (LABEL_ORDER, "status"): ORDER_STATUS_TEXT,
    (LABEL_RATING, "review_status"): REVIEW_STATUS_TEXT,
    (LABEL_RATING, "is_complaint"): BOOL_TEXT,
    (LABEL_WITHDRAWAL, "status"): WITHDRAW_STATUS_TEXT,
    (LABEL_TAG, "status"): TAG_STATUS_TEXT,
    (LABEL_BOSS, "blacklisted"): BOOL_TEXT,
    (LABEL_PLAYER, "blacklisted"): BOOL_TEXT,
}

# 字段的数值口径：库里存原始值，展示时要换算
#   fen     分 → 元（金额字段一律按分存）
#   coin    大狗币（1 大狗币 = 1 元）
#   percent 百分数，未评价时库里存 -1，展示成 "—"
FIELD_UNITS = {
    "consume_amount": "fen",
    "total_amount": "fen",
    "backend_amount": "fen",
    "amount": "fen",
    "tip_amount": "fen",
    "balance": "coin",
    "good_rate": "percent",
}


def rel_name(rel: str) -> str:
    """关系名的中文显示。同名的多条定义（如 PUNISHED 有老板/打手两种起点）取第一处。"""
    for meta in REL_TYPES.values():
        if meta["rel"] == rel:
            return meta["name"]
    return rel


def node_meta(label: str) -> dict:
    """取某标签的定义；未登记时返回一个安全的最小结构。"""
    return NODE_TYPES.get(label, {"name": label, "key": "key", "color": "#94a3b8", "fields": {}})


def field_name(label: str, field: str) -> str:
    """字段的中文名，未登记时回退用英文字段名。"""
    return node_meta(label)["fields"].get(field, (field, False))[0]


def is_sensitive(label: str, field: str) -> bool:
    """该字段是否敏感（只有管理员可见）。

    未登记的字段一律按敏感处理——宁可多隐藏，不可漏出去。
    """
    return bool(node_meta(label)["fields"].get(field, (field, True))[1])
