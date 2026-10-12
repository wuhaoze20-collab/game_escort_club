"""知识图谱的构建与同步。

两条路径：

    全量同步  sync_all(db)      —— 从 MySQL 的业务表把整个图谱重建一遍，
                                   在「知识图谱」页面点「重建图谱」时触发，
                                   后端启动时如果图谱是空的也会自动跑一次。

    增量同步  sync_order(db, order) —— 每产生一笔新订单就把它写进图谱。
                                   挂在下单/派单/接单/结单等接口里。

两条路径都靠 Cypher 的 MERGE + 业务主键保证幂等——
同一笔订单同步十次，图里也只有一份，不会越跑越肿。

=== 为什么用 MERGE 而不是 CREATE ===

MERGE 的语义是「有就匹配、没有就创建」。图谱同步天然是重复执行的
（下单一次、接单再同步一次、结单还要同步一次），用 CREATE 会造出一堆
重复节点。MERGE 配合唯一约束（ensure_constraints）才是正确写法。

=== 单位口径（和业务表保持一致，不要在这里换算） ===

    boss_info.balance            大狗币（1 大狗币 = 1 元，DECIMAL）
    boss_info.consume_amount     分
    player_info.backend_amount   分
    order.total_amount           分

入库时按原样存，换算交给前端显示层——存的时候就换会导致对不上账。
"""

from datetime import datetime
import hashlib
import json
import re

from models import (User, BossInfo, PlayerInfo, PlayerTag, Order,
                    PlayerRating, TipRecord, WithdrawalRecord, ContentConfig)
from kg import store, schema

# 处罚通告正文里用「」括出被处罚账号，如「老板「laoban」被管理员拉黑封禁」
_PUNISH_TARGET_RE = re.compile(r"「([^」]+)」")


# ——————————————————————————————————————————————
# 唯一约束（MERGE 的性能与幂等都依赖它）
# ——————————————————————————————————————————————

def ensure_constraints() -> bool:
    """给每个节点标签的业务主键建唯一约束。

    有约束时 Neo4j 会为该属性自动建索引，MERGE 就是「走索引查一次」而不是
    「扫全图」，节点多了之后差别很大；同时约束还从数据库层兜住了重复节点。
    已存在时不会报错（IF NOT EXISTS）。
    """
    ok = True
    for label, meta in schema.NODE_TYPES.items():
        key = meta["key"]
        try:
            store.run(
                f"CREATE CONSTRAINT kg_{label.lower()}_key IF NOT EXISTS "
                f"FOR (n:{label}) REQUIRE n.{key} IS UNIQUE",
                mode="w",
            )
        except Exception as e:
            # 约束建不上（权限不足、旧版本语法差异）不该阻断同步，只记一笔
            print(f"[kg] 建约束 {label}.{key} 失败：{type(e).__name__}: {e}")
            ok = False
    return ok


# ——————————————————————————————————————————————
# 工具函数
# ——————————————————————————————————————————————

def _dt(v) -> str:
    """datetime → ISO 字符串。

    不用 Neo4j 原生 datetime 类型：它在转 JSON 回前端时会变成一串
    结构体，还得再解析一遍。存 ISO 字符串前端直接显示，最省事。
    """
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    return ""


def _nickname(db, username: str) -> tuple:
    """取展示用的昵称与头像（昵称优先，空则回退用户名）。"""
    u = db.query(User).filter(User.username == username).first()
    if not u:
        return "", ""
    return (u.nickname or ""), (u.avatar or "")


def _is_banned(db, username: str) -> bool:
    """账号是否已被拉黑。

    拉黑在业务上的落地方式是 user.account_status = "rejected"（见
    user_info_api._apply_ban），图谱只是把这个事实带进来用于展示。
    """
    u = db.query(User).filter(User.username == username).first()
    return bool(u and u.account_status == "rejected")


# ——————————————————————————————————————————————
# 单实体同步
# ——————————————————————————————————————————————

def sync_boss(db, username: str) -> None:
    """把一个老板写进图谱（不存在则创建，存在则更新属性）。"""
    info = db.query(BossInfo).filter(BossInfo.username == username).first()
    if not info:
        return
    nickname, avatar = _nickname(db, username)

    store.run(
        "MERGE (b:Boss {username: $username}) "
        "SET b.nickname = $nickname, b.avatar = $avatar, "
        "    b.balance = $balance, b.consume_amount = $consume, "
        "    b.order_count = $order_count, b.blacklisted = $banned, "
        "    b.updated_at = $now",
        {
            "username": username,
            "nickname": nickname,
            "avatar": avatar,
            "balance": float(info.balance or 0),
            "consume": int(info.consume_amount or 0),
            "order_count": int(info.order_count or 0),
            "banned": _is_banned(db, username),
            "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
    )


def sync_player(db, username: str) -> None:
    """把一个打手写进图谱（不存在则创建，存在则更新属性）。"""
    info = db.query(PlayerInfo).filter(PlayerInfo.username == username).first()
    if not info:
        return
    nickname, avatar = _nickname(db, username)

    # good_rate 可能是 None（没有任何评价）——Neo4j 属性不能存 None，
    # 会直接抛错，所以这里转成 -1 表示「暂无」。前端见到 -1 显示 "-"。
    good_rate = info.good_rate
    good_rate = -1.0 if good_rate is None else float(good_rate)

    store.run(
        "MERGE (p:Player {username: $username}) "
        "SET p.nickname = $nickname, p.avatar = $avatar, "
        "    p.level_type = $level_type, p.tech_level = $tech_level, "
        "    p.order_count = $order_count, p.complaint_count = $complaint, "
        "    p.good_rate = $good_rate, p.backend_amount = $backend, "
        "    p.blacklisted = $banned, p.updated_at = $now",
        {
            "username": username,
            "nickname": nickname,
            "avatar": avatar,
            "level_type": info.level_type or "",
            "tech_level": info.tech_level or "",
            "order_count": int(info.order_count or 0),
            "complaint": int(info.complaint_count or 0),
            "good_rate": good_rate,
            "backend": int(info.backend_amount or 0),
            "banned": _is_banned(db, username),
            "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
    )


def sync_player_tags(db, username: str) -> None:
    """同步某打手的全部标签（只带审核通过的对外展示）。

    先删这个打手现有的 HAS_TAG 关系再重建：标签会被审核通过/驳回、
    也可能被删除，增量对比反而容易漏，直接重建最简单也最准。
    """
    tags = db.query(PlayerTag).filter(PlayerTag.username == username).all()

    store.run_safe(
        "MATCH (p:Player {username: $username})-[r:HAS_TAG]->() DELETE r",
        {"username": username}, tag=f"clear_tags({username})",
    )
    for t in tags:
        name = (t.tag or "").strip()
        if not name:
            continue
        store.run_safe(
            "MATCH (p:Player {username: $username}) "
            "MERGE (t:Tag {tag_key: $tag_key}) "
            "SET t.name = $name, t.status = $status "
            "MERGE (p)-[:HAS_TAG]->(t)",
            {
                "username": username,
                "tag_key": f"{username}:{name}",
                "name": name,
                "status": t.status or "pending",
            },
            tag=f"sync_tag({username}/{name})",
        )


def sync_order(db, order: Order) -> None:
    """把一笔订单及其关联实体写进图谱。

    这是「后续新订单都存进图谱」的落点，也是图谱里最核心的一条链：

        (Boss)-[:PLACED]->(Order)-[:FOR_GAME]->(Game)
                             ^
                  (Player)-[:SERVED]

    调用时机：下单后调用一次即可；订单状态变化（接单、结单）时再调用一次，
    属性会被更新成最新状态。哪怕同一笔订单调用多次也只会有一份。
    """
    if order is None:
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ① 老板节点 + 下单关系
    sync_boss(db, order.boss_username)
    store.run_safe(
        "MERGE (b:Boss {username: $boss}) "
        "MERGE (o:Order {order_no: $order_no}) "
        "MERGE (b)-[:PLACED]->(o)",
        {"boss": order.boss_username, "order_no": order.order_no},
        tag=f"link_placed({order.order_no})",
    )

    # ② 订单自身的属性
    store.run_safe(
        "MERGE (o:Order {order_no: $order_no}) "
        "SET o.game_type = $game_type, "
        "    o.duration_min = $duration, "
        "    o.total_amount = $amount, "
        "    o.service_note = $note, "
        "    o.remark = $remark, "
        "    o.status = $status, "
        "    o.status_text = $status_text, "
        "    o.boss_username = $boss, "
        "    o.player_username = $player, "
        "    o.created_at = $created_at, "
        "    o.start_time = $start_time, "
        "    o.end_time = $end_time, "
        "    o.updated_at = $now",
        {
            "order_no": order.order_no,
            "game_type": order.game_type or "",
            "duration": int(order.duration_min or 0),
            "amount": int(order.total_amount or 0),
            "note": order.service_note or "",
            "remark": order.remark or "",
            "status": order.status or "",
            "status_text": schema.ORDER_STATUS_TEXT.get(order.status, order.status or ""),
            "boss": order.boss_username or "",
            "player": order.player_username or "",
            "created_at": _dt(order.created_at),
            "start_time": _dt(order.start_time),
            "end_time": _dt(order.end_time),
            "now": now,
        },
        tag=f"sync_order({order.order_no})",
    )

    # ③ 游戏节点 + 所属关系
    game = (order.game_type or "").strip()
    if game:
        store.run_safe(
            "MERGE (o:Order {order_no: $order_no}) "
            "MERGE (g:Game {name: $game}) "
            "MERGE (o)-[:FOR_GAME]->(g)",
            {"order_no": order.order_no, "game": game},
            tag=f"link_game({order.order_no})",
        )

    # ④ 打手节点 + 接单关系 + 雇佣关系
    player = (order.player_username or "").strip()
    if player:
        sync_player(db, player)
        store.run_safe(
            "MERGE (p:Player {username: $player}) "
            "MERGE (o:Order {order_no: $order_no}) "
            "MERGE (p)-[:SERVED]->(o)",
            {"player": player, "order_no": order.order_no},
            tag=f"link_served({order.order_no})",
        )
        # 老板雇佣过打手：从订单推导出来的「人—人」关系，
        # 这张边让图谱能回答「这个老板都和哪些打手合作过」。
        store.run_safe(
            "MERGE (b:Boss {username: $boss}) "
            "MERGE (p:Player {username: $player}) "
            "MERGE (b)-[h:HIRED]->(p) "
            "SET h.order_count = coalesce(h.order_count, 0) + 0, "
            "    h.last_order_no = $order_no, h.updated_at = $now",
            {
                "boss": order.boss_username, "player": player,
                "order_no": order.order_no, "now": now,
            },
            tag=f"link_hired({order.order_no})",
        )


def sync_order_by_no(db, order_no: str) -> None:
    """按订单号从 MySQL 读最新状态再同步（接单/结单等状态变更后调用）。"""
    order = db.query(Order).filter(Order.order_no == order_no).first()
    if order:
        sync_order(db, order)


# ——————————————————————————————————————————————
# 订单之后发生的事：评价 / 投诉 / 打赏 / 提现 / 处罚
#
# 订单只记录「服务发生了」，而评价、打赏、投诉、提现记录的是「结果如何」。
# 没有这几类节点，图谱就答不出「谁给谁打赏过」「这个打手被投诉几次」——
# 这类问题的答案不在文档里，也不在订单里，而在事后单据里。
# ——————————————————————————————————————————————

def _order_no_of(db, order_id) -> str:
    """按 orders.id 反查订单号；查不到返回空串（那这条记录就只连人不连单）。"""
    if not order_id:
        return ""
    row = db.query(Order.order_no).filter(Order.id == order_id).first()
    return (row[0] if row else "") or ""


def _is_complaint(comment: str) -> bool:
    """这条评价是不是投诉。

    判定口径必须与 rating_api 完全一致——投诉不会被单独建表，
    而是把评价正文改成「【老板投诉】…」并把订单记成差评。
    """
    return (comment or "").strip().startswith("【老板投诉】")


def _refresh_complained(db, boss: str, player: str) -> None:
    """重算「某老板投诉过某打手」这条派生边（含次数）。

    投诉可撤销（打手申诉成功 → review_status=removed），
    所以这条边不能只在投诉时累加，必须按当前**有效**投诉条数重算，
    否则申诉成功后图上还挂着一条不该存在的投诉。
    """
    rows = db.query(PlayerRating).filter(
        PlayerRating.boss_username == boss,
        PlayerRating.player_username == player,
    ).all()
    n = sum(1 for r in rows
            if _is_complaint(r.comment) and (r.review_status or "normal") != "removed")

    store.run_safe(
        "MATCH (b:Boss {username: $boss})-[c:COMPLAINED]->(p:Player {username: $player}) "
        "DELETE c",
        {"boss": boss, "player": player}, tag=f"clear_complained({boss}->{player})",
    )
    if n > 0:
        store.run_safe(
            "MERGE (b:Boss {username: $boss}) "
            "MERGE (p:Player {username: $player}) "
            "MERGE (b)-[c:COMPLAINED]->(p) "
            "SET c.count = $n, c.updated_at = $now",
            {"boss": boss, "player": player, "n": n,
             "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
            tag=f"link_complained({boss}->{player})",
        )


def sync_rating(db, rating: PlayerRating) -> None:
    """把一条评价写进图谱（投诉型评价也在这张表里）。

        (Boss)-[:RATED]->(Rating)-[:ABOUT]->(Player)
                                 └-[:FOR_ORDER]->(Order)

    投诉型评价额外补一条人—人派生边 (Boss)-[:COMPLAINED]->(Player)：
    「这个老板投诉过谁」不必绕道评价节点，一跳就能拿到。
    """
    if rating is None:
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rid = f"rating:{rating.id}"
    comment = (rating.comment or "").strip()
    complaint = _is_complaint(comment)
    order_no = _order_no_of(db, rating.order_id)

    sync_boss(db, rating.boss_username)
    sync_player(db, rating.player_username)

    store.run_safe(
        "MERGE (r:Rating {rating_id: $rid}) "
        "SET r.rating = $rating, r.comment = $comment, r.reply = $reply, "
        "    r.is_complaint = $complaint, r.review_status = $review_status, "
        "    r.review_status_text = $review_text, "
        "    r.boss_username = $boss, r.player_username = $player, "
        "    r.order_no = $order_no, r.created_at = $created_at, r.updated_at = $now",
        {
            "rid": rid,
            "rating": int(rating.rating or 0),
            "comment": comment,
            "reply": (rating.reply or "").strip(),
            "complaint": complaint,
            "review_status": rating.review_status or "normal",
            "review_text": schema.REVIEW_STATUS_TEXT.get(rating.review_status or "normal", ""),
            "boss": rating.boss_username or "",
            "player": rating.player_username or "",
            "order_no": order_no,
            "created_at": _dt(rating.created_at),
            "now": now,
        },
        tag=f"sync_rating({rating.id})",
    )

    # 三条结构边先清后建，避免评价被改动后留下旧边
    store.run_safe(
        "MATCH (r:Rating {rating_id: $rid})-[e:RATED|ABOUT|FOR_ORDER]->() DELETE e",
        {"rid": rid}, tag=f"clear_rating_edges({rating.id})",
    )
    store.run_safe(
        "MERGE (b:Boss {username: $boss}) "
        "MERGE (r:Rating {rating_id: $rid}) "
        "MERGE (b)-[:RATED]->(r)",
        {"boss": rating.boss_username, "rid": rid},
        tag=f"link_rated({rating.id})",
    )
    store.run_safe(
        "MERGE (p:Player {username: $player}) "
        "MERGE (r:Rating {rating_id: $rid}) "
        "MERGE (r)-[:ABOUT]->(p)",
        {"player": rating.player_username, "rid": rid},
        tag=f"link_about({rating.id})",
    )
    if order_no:
        store.run_safe(
            "MERGE (o:Order {order_no: $order_no}) "
            "MERGE (r:Rating {rating_id: $rid}) "
            "MERGE (r)-[:FOR_ORDER]->(o)",
            {"order_no": order_no, "rid": rid},
            tag=f"link_rating_order({rating.id})",
        )

    # 派生边：投诉过（按当前有效投诉数重算）
    _refresh_complained(db, rating.boss_username, rating.player_username)


def sync_tip(db, tip: TipRecord) -> None:
    """把一条打赏写进图谱。

        (Boss)-[:TIPPED]->(Tip)-[:TO]->(Player)
                                └-[:FOR_ORDER]->(Order)
    """
    if tip is None:
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tid = f"tip:{tip.id}"
    order_no = _order_no_of(db, tip.order_id)

    sync_boss(db, tip.boss_username)
    sync_player(db, tip.player_username)

    store.run_safe(
        "MERGE (t:Tip {tip_id: $tid}) "
        "SET t.amount = $amount, t.boss_username = $boss, "
        "    t.player_username = $player, t.order_no = $order_no, "
        "    t.created_at = $created_at, t.updated_at = $now",
        {
            "tid": tid,
            "amount": int(tip.amount or 0),
            "boss": tip.boss_username or "",
            "player": tip.player_username or "",
            "order_no": order_no,
            "created_at": _dt(tip.created_at),
            "now": now,
        },
        tag=f"sync_tip({tip.id})",
    )
    store.run_safe(
        "MATCH (t:Tip {tip_id: $tid})-[e:TIPPED|TO|FOR_ORDER]->() DELETE e",
        {"tid": tid}, tag=f"clear_tip_edges({tip.id})",
    )
    store.run_safe(
        "MERGE (b:Boss {username: $boss}) "
        "MERGE (t:Tip {tip_id: $tid}) "
        "MERGE (b)-[:TIPPED]->(t)",
        {"boss": tip.boss_username, "tid": tid}, tag=f"link_tipped({tip.id})",
    )
    store.run_safe(
        "MERGE (p:Player {username: $player}) "
        "MERGE (t:Tip {tip_id: $tid}) "
        "MERGE (t)-[:TO]->(p)",
        {"player": tip.player_username, "tid": tid}, tag=f"link_tip_to({tip.id})",
    )
    if order_no:
        store.run_safe(
            "MERGE (o:Order {order_no: $order_no}) "
            "MERGE (t:Tip {tip_id: $tid}) "
            "MERGE (t)-[:FOR_ORDER]->(o)",
            {"order_no": order_no, "tid": tid}, tag=f"link_tip_order({tip.id})",
        )


def sync_withdrawal(db, wd: WithdrawalRecord) -> None:
    """把一条提现申请写进图谱：(Player)-[:WITHDREW]->(Withdrawal)。

    提现没有对应订单，所以图上是一棵只挂人的单边链——
    「这个打手提过几次现、审核结果如何」靠它回答。
    """
    if wd is None:
        return

    wid = f"wd:{wd.id}"
    sync_player(db, wd.player_username)

    store.run_safe(
        "MERGE (w:Withdrawal {wd_id: $wid}) "
        "SET w.amount = $amount, w.status = $status, w.status_text = $status_text, "
        "    w.note = $note, w.player_username = $player, "
        "    w.created_at = $created_at, w.processed_at = $processed_at, "
        "    w.updated_at = $now",
        {
            "wid": wid,
            "amount": int(wd.amount or 0),
            "status": wd.status or "pending",
            "status_text": schema.WITHDRAW_STATUS_TEXT.get(wd.status or "pending", ""),
            "note": (wd.note or "").strip(),
            "player": wd.player_username or "",
            "created_at": _dt(wd.created_at),
            "processed_at": _dt(wd.processed_at),
            "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
        tag=f"sync_withdrawal({wd.id})",
    )
    store.run_safe(
        "MATCH (w:Withdrawal {wd_id: $wid})<-[e:WITHDREW]-() DELETE e",
        {"wid": wid}, tag=f"clear_wd_edges({wd.id})",
    )
    store.run_safe(
        "MERGE (p:Player {username: $player}) "
        "MERGE (w:Withdrawal {wd_id: $wid}) "
        "MERGE (p)-[:WITHDREW]->(w)",
        {"player": wd.player_username, "wid": wid},
        tag=f"link_withdrew({wd.id})",
    )


def sync_punishments(db) -> int:
    """把「处罚通告」里的条目写进图谱（通告存在 content_config.punishment）。

    通告正文是一段自由文本（如「老板「laoban」被管理员拉黑封禁，账户余额…」），
    没有外键指向具体账号，所以用「」把账号名括出来的写法里提取目标建边；
    提不到目标就只建节点——节点照样能被全文检索和统计命中，只是没有边。

    每次都按当前通告内容重建全部处罚节点（通告会被追加，条目数不多），
    以 desc 的哈希当主键，同一件事同步多次也只会有一份。
    """
    row = db.query(ContentConfig).filter(ContentConfig.config_key == "punishment").first()
    if not row:
        return 0

    try:
        items = json.loads(row.config_value or "[]")
    except Exception:
        return 0
    if not isinstance(items, list):
        return 0

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    n = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        level = (it.get("level") or "").strip()
        desc = (it.get("desc") or "").strip()
        date = (it.get("date") or "").strip()
        if not desc:
            continue
        pkey = "pn:" + hashlib.md5(f"{level}|{desc}".encode("utf-8")).hexdigest()[:16]
        target = ""
        m = _PUNISH_TARGET_RE.search(desc)
        if m:
            target = m.group(1).strip()

        store.run_safe(
            "MERGE (n:Punishment {punish_key: $key}) "
            "SET n.level = $level, n.desc = $desc, n.date = $date, "
            "    n.target = $target, n.updated_at = $now",
            {"key": pkey, "level": level, "desc": desc, "date": date,
             "target": target, "now": now},
            tag=f"sync_punishment({pkey})",
        )
        n += 1

        if not target:
            continue
        # 目标可能是老板也可能是打手；哪个存在就连哪个
        for label in (schema.LABEL_BOSS, schema.LABEL_PLAYER):
            store.run_safe(
                f"MATCH (u:{label} {{username: $u}}) "
                "MATCH (n:Punishment {punish_key: $key}) "
                "MERGE (u)-[:PUNISHED]->(n)",
                {"u": target, "key": pkey},
                tag=f"link_punished({target}/{pkey})",
            )
    return n


# ——————————————————————————————————————————————
# 全量同步
# ——————————————————————————————————————————————

def sync_all(db, force: bool = False) -> dict:
    """把 MySQL 里的老板、打手、订单全量同步进图谱。

    参数 force：为 True 时先清空图谱再重建（用于「重建图谱」按钮）。

    返回统计字典，便于接口直接回给前端显示「同步了多少条」。
    """
    started = datetime.now()
    result = {"bosses": 0, "players": 0, "tags": 0, "orders": 0, "games": 0,
              "ratings": 0, "tips": 0, "withdrawals": 0, "punishments": 0,
              "cleared": False, "errors": []}

    if not store.is_ready():
        result["errors"].append("图谱不可用（未配置密码或 Neo4j 未启动）")
        return result

    ensure_constraints()

    if force:
        clear()
        result["cleared"] = True

    # ① 老板（users 里 role=boss 的账号，且有 boss_info 记录）
    for u in db.query(User).filter(User.role == "boss").all():
        try:
            before = store.run(
                "MATCH (b:Boss {username: $u}) RETURN count(b) AS c",
                {"u": u.username}, mode="r")
            exists = bool(before and before[0]["c"])
            sync_boss(db, u.username)
            if not exists:
                result["bosses"] += 1
        except Exception as e:
            result["errors"].append(f"老板 {u.username}: {e}")

    # ② 打手
    for u in db.query(User).filter(User.role == "player").all():
        try:
            before = store.run(
                "MATCH (p:Player {username: $u}) RETURN count(p) AS c",
                {"u": u.username}, mode="r")
            exists = bool(before and before[0]["c"])
            sync_player(db, u.username)
            sync_player_tags(db, u.username)
            result["tags"] += db.query(PlayerTag).filter(
                PlayerTag.username == u.username).count()
            if not exists:
                result["players"] += 1
        except Exception as e:
            result["errors"].append(f"打手 {u.username}: {e}")

    # ③ 订单（全量；订单量可能较大，分批同步避免一次性占用太多内存）
    orders = db.query(Order).all()
    for o in orders:
        try:
            sync_order(db, o)
            result["orders"] += 1
        except Exception as e:
            result["errors"].append(f"订单 {o.order_no}: {e}")

    # ④ 评价（含投诉）——必须在订单之后：评价要靠订单号连到 Order 节点
    for r in db.query(PlayerRating).all():
        try:
            sync_rating(db, r)
            result["ratings"] += 1
        except Exception as e:
            result["errors"].append(f"评价 {r.id}: {e}")

    # ⑤ 打赏
    for t in db.query(TipRecord).all():
        try:
            sync_tip(db, t)
            result["tips"] += 1
        except Exception as e:
            result["errors"].append(f"打赏 {t.id}: {e}")

    # ⑥ 提现
    for w in db.query(WithdrawalRecord).all():
        try:
            sync_withdrawal(db, w)
            result["withdrawals"] += 1
        except Exception as e:
            result["errors"].append(f"提现 {w.id}: {e}")

    # ⑦ 处罚通告
    try:
        result["punishments"] = sync_punishments(db)
    except Exception as e:
        result["errors"].append(f"处罚通告: {e}")

    # ⑧ 游戏节点的订单数：按关系现场数出来，不另存一份计数（避免两份数据对不上）
    try:
        store.run(
            "MATCH (g:Game)<-[:FOR_GAME]-(o:Order) "
            "WITH g, count(o) AS c SET g.order_count = c",
            mode="w")
        rows = store.run("MATCH (g:Game) RETURN count(g) AS c", mode="r")
        result["games"] = int(rows[0]["c"]) if rows else 0
    except Exception as e:
        result["errors"].append(f"游戏统计: {e}")

    # ⑨ 雇佣关系上的订单数（同样现场数出来）
    try:
        store.run(
            "MATCH (b:Boss)-[h:HIRED]->(p:Player) "
            "OPTIONAL MATCH (b)-[:PLACED]->(o:Order)-[:SERVED]->(p) "
            "WITH b, p, h, count(o) AS c "
            "SET h.order_count = c",
            mode="w")
    except Exception as e:
        result["errors"].append(f"雇佣关系统计: {e}")

    # ⑩ 打手身上的收到打赏总额（现场聚合，口径与业务表一致：分）
    try:
        store.run(
            "MATCH (p:Player)<-[:TO]-(t:Tip) "
            "WITH p, sum(coalesce(t.amount, 0)) AS s SET p.tip_amount = s",
            mode="w")
    except Exception as e:
        result["errors"].append(f"打赏汇总: {e}")

    result["elapsed_ms"] = int((datetime.now() - started).total_seconds() * 1000)
    result["stats"] = store.stats()
    return result


def is_empty() -> bool:
    """图谱里一个节点都没有（用于判断启动时要不要自动同步一次）。"""
    try:
        rows = store.run("MATCH (n) RETURN count(n) AS c", mode="r")
        return (not rows) or int(rows[0]["c"]) == 0
    except Exception:
        return False


def clear() -> None:
    """清空整个图谱（只删本项目用到的标签，不碰库里别的东西）。

    用 DETACH DELETE：节点上的关系会跟着一起删。分两批删是为了
    避免一次性删除大量数据时的事务内存压力。
    """
    for label in schema.NODE_TYPES:
        store.run_safe(f"MATCH (n:{label}) DETACH DELETE n", tag=f"clear({label})")
