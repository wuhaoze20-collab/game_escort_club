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
}

# ——————————————————————————————————————————————
# 关系类型
# ——————————————————————————————————————————————

REL_PLACED = "PLACED"
REL_SERVED = "SERVED"
REL_FOR_GAME = "FOR_GAME"
REL_HAS_TAG = "HAS_TAG"
REL_HIRED = "HIRED"

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
