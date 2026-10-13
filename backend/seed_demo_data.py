# -*- coding: utf-8 -*-
"""演示数据生成器（大狗嚼电竞）

设计原则
--------
1. **账本唯一**：所有余额 / 累计消费 / 接单数 / 后台金额 / 投诉数，
   只由本文件末尾的 `_ledger_*` 系列函数改动，杜绝各写各的导致对不上。
2. **口径对齐线上**：
   - 金额与时长/数量自洽：时长业务 `金额 = 时长 ÷ 60 × 单价`；级/层业务 `金额 = 数量 × 单价`
   - `order_count` / `consume_amount` **只在结单时累加**（与 order_api.settle_order 一致，
     进行中订单不下单时计数）
   - 好评率 = 有效评价中 4 星及以上占比；无评价为 None（前端显示 "-"）
   - 投诉数 = 当前仍标记着「【老板投诉】」且未被申诉撤销的条数
3. **幂等**：`orders` 表非空则跳过；需要重建时用 `--reset`。

用法
----
    python seed_demo_data.py            # 首次填充（已有订单则跳过）
    python seed_demo_data.py --reset    # 清空业务数据后重新生成
"""
import sys
import json
import random
from datetime import datetime, timedelta
from decimal import Decimal

from database import SessionLocal
from models import (
    User, BossInfo, PlayerInfo, PlayerTag, Order, ContentConfig,
    SalaryRecord, PlayerRating, TipRecord, WithdrawalRecord, Notification,
)
from auth import hash_password
import config_service

# 固定种子，保证每次重建得到同一批数据（便于复现问题）
random.seed(20261013)

# ---------------------------------------------------------------- 配置区

# 新增打手（username, 昵称, 陪玩类型, 技术等级, 头像, 自我介绍, 已审核标签）
NEW_PLAYERS = [
    ("dashou_07", "阿泽", "技术陪", "985", "avatar_985_2.jpg",
     "985名校技术陪，王者荣耀国服前百打野，意识教学型陪玩，带你上分更带你理解游戏。",
     ["王者百星", "国服打野", "语音带飞"]),
    ("dashou_08", "老六", "技术陪", "211", "avatar_211_2.jpg",
     "211技术陪，主玩和平精英，四排带队冲分，战术清晰执行力强，稳定吃鸡。",
     ["百星王者", "吃鸡指挥", "深夜可约"]),
    ("dashou_09", "小杰", "技术陪", "大专", "avatar_dazhuan.png",
     "大专技术陪，英雄联盟峡谷之巅选手，主玩中单，价格实惠质量在线。",
     ["峡谷千分", "中单带飞"]),
    ("dashou_10", "夜煞", "技术陪", "魔王护", "avatar_mowanghu.jpg",
     "魔王护专属护航，高端局代练出身，节奏把控一流，全程语音护驾。",
     ["高端局护航", "节奏大师"]),
    ("dashou_11", "神谕", "技术陪", "明星护", "avatar_mingxing.jpg",
     "明星级护航，原神满命深渊速通、王者巅峰赛顶级对局，服务高端客户。",
     ["原神深渊", "巅峰2000", "全天可约"]),
    ("dashou_12", "软糖", "娱乐陪", "", "avatar_yule.jpg",
     "娱乐陪玩，能聊能玩会哄人，排位不掉星，输了算我的，开心最重要！",
     ["声音好听", "欢乐陪玩"]),
]

# 老板 → 计划生成订单数（拉开规模差距，演示"大客户/普通客户"）
BOSS_ORDER_PLAN = {"laoban": 26, "laoban_02": 20, "laoban_03": 14}

# 打手最少接单数：低于这个量级好评率只有 0% 或 100%，演示时看着像 bug
PLAYER_MIN_ORDERS = 3

# 老板起始余额（大狗币，与人民币 1:1）
BOSS_BALANCE = {"laoban": 9000, "laoban_02": 5000, "laoban_03": 3000}

# 打手接单权重：等级越"贵"接单越多；dashou 是主演示账号，给最高权重保证有内容可看
PLAYER_WEIGHT = {
    "dashou": 12,     # 主演示打手账号
    "dashou_11": 10,  # 明星护
    "dashou_10": 9,   # 魔王护
    "dashou_07": 8,   # 985
    "dashou_05": 6,
    "dashou_08": 6,   # 211
    "dashou_03": 6,
    "dashou_06": 6,
    "dashou_09": 5,   # 大专
    "dashou_02": 5,
    "dashou_04": 5,
    "dashou_12": 3,   # 娱乐陪
}
DEFAULT_WEIGHT = 2

# 评价语料
RATING_COMMENTS = {
    5: ["非常专业，带我上分稳稳的，必须五星！", "技术一流，配合默契，下次还找你！",
        "全程语音指导，体验拉满，推荐给所有老板！", "稳如老狗，一晚上连上三个段，太强了！",
        "服务态度超好，有耐心，点赞！", "节奏带得特别好，全程零失误，值这个价！"],
    4: ["整体不错，技术在线，就是开场稍慢了点。", "打得挺好，沟通再多一点就更完美了。",
        "质量不错，价格也合理，会回购。"],
    3: ["中规中矩吧，能赢但体验一般。", "还行，偶尔掉线，希望改进。"],
    2: ["不太满意，节奏有点慢，再练练吧。", "和预期有差距，沟通也不太顺畅。"],
}
REPLIES = ["感谢老板认可，下次继续带飞！", "老板满意就好，随时约我！",
           "收到，一定继续保持，感谢五星好评！", "感谢支持，你的满意是我最大的动力！"]

# 星级权重按等级走：等级越高评价越好（否则会出现"魔王护 0% 好评率"这种看着像 bug 的数据）
LEVEL_STAR_WEIGHTS = {
    "明星护": [62, 30, 6, 2],
    "魔王护": [60, 32, 6, 2],
    "985": [58, 32, 8, 2],
    "211": [50, 32, 13, 5],
    "大专": [48, 32, 14, 6],
}
DEFAULT_STAR_WEIGHTS = [55, 30, 11, 4]   # 娱乐陪等无技术等级的打手
STAR_KEYS = [5, 4, 3, 2]

REMARKS = ["老板想上分，稳一点", "尽量拿MVP", "语音沟通", "别浪，稳赢",
           "陪练新赛季冲分", "多交流，教学局", "", "速战速决"]

# 打赏占订单金额比例
TIP_RATIOS = [0.05, 0.08, 0.10, 0.15, 0.20, 0.25]

# 订单状态：88% 已完成，其余分摊到在途状态，保证各页面都有数据看
ONGOING_STATUS = ["pending_accept", "assigned", "processing", "pending_settlement"]


# ---------------------------------------------------------------- 账本（唯一改动入口）

def _ledger_freeze_boss(boss: BossInfo, amount_cent: int) -> None:
    """下单：冻结大狗币（只扣余额，不计数——计数在结单时）"""
    boss.balance = Decimal(boss.balance or 0) - Decimal(amount_cent) / Decimal(100)


def _ledger_settle(db, order: Order, boss: BossInfo, player: PlayerInfo,
                   rate: float, end_time: datetime) -> SalaryRecord:
    """结单：改写订单状态、生成工资记录、双方记账（与 order_api.settle_order 同口径）"""
    amount = int(order.total_amount or 0)
    order.status = "completed"
    order.end_time = end_time

    commission = int(amount * rate)
    income = amount - commission
    sal = SalaryRecord(order_id=order.id, player_username=player.username,
                       order_total=amount, club_commission=commission,
                       player_income=income, settlement_time=end_time,
                       payout_status="paid")
    db.add(sal)

    player.backend_amount = int(player.backend_amount or 0) + income
    player.order_count = (player.order_count or 0) + 1
    boss.consume_amount = int(boss.consume_amount or 0) + amount
    boss.order_count = (boss.order_count or 0) + 1
    return sal


def _ledger_tip(db, order: Order, boss: BossInfo, player: PlayerInfo,
                amount_cent: int, when: datetime) -> None:
    """打赏：老板扣大狗币，打手后台按 1:1 入账"""
    db.add(TipRecord(order_id=order.id, boss_username=boss.username,
                     player_username=player.username, amount=amount_cent,
                     created_at=when))
    boss.balance = Decimal(boss.balance or 0) - Decimal(amount_cent) / Decimal(100)
    player.backend_amount = int(player.backend_amount or 0) + amount_cent


def _ledger_withdraw(db, player: PlayerInfo, amount_cent: int, status: str,
                     created: datetime, processed=None, note="") -> None:
    """提现：只有已通过才真正扣后台金额（待审/驳回不减账）"""
    db.add(WithdrawalRecord(player_username=player.username, amount=amount_cent,
                            status=status, note=note, created_at=created,
                            processed_at=processed))
    if status == "approved":
        player.backend_amount = int(player.backend_amount or 0) - amount_cent


# ---------------------------------------------------------------- 计价

def _pick_service(price_list):
    """随机挑一条价目 → (game_type, duration_min, amount_cent, service_note)

    金额严格按线上前端口径推导：
      元/小时 → 时长分钟 ÷ 60 × 单价
      元/级   → 数量 × 单价（满 60 级自动按满级一口价）
      元/层   → 数量 × 单价
      元/满级 → 一口价
    """
    item = random.choice(price_list)
    game, rank = item["game"], item["rank"]
    price = float(item["price"])
    unit = item.get("unit", "元/小时")
    game_type = f"{game}-{rank}"

    if "小时" in unit:
        duration = random.choice([60, 90, 120, 150, 180, 240])
        yuan = duration / 60.0 * price
        return game_type, duration, int(round(yuan * 100)), ""

    if "满级" in unit:
        return game_type, 1, int(round(price * 100)), rank

    if "级" in unit:
        qty = random.randint(5, 60)
        if qty >= 60:  # Apex 通行证满 60 级按满级价
            full = next((p for p in price_list
                         if p["game"] == game and p["rank"] == "通行证满级"), None)
            yuan = float(full["price"]) if full else 70.0
        else:
            yuan = qty * price
        return game_type, 1, int(round(yuan * 100)), f"{qty}级"

    if "层" in unit:
        qty = random.randint(6, 12)
        return game_type, 1, int(round(qty * price * 100)), f"{qty}层"

    duration = random.choice([60, 120])
    return game_type, duration, int(round(duration / 60.0 * price * 100)), ""


# ---------------------------------------------------------------- 主流程

def reset_business_data(db) -> None:
    """清空业务数据并复位账户累计字段（保留账户、昵称、头像、标签、系统配置、AI 数据）"""
    print("  · 清空业务表：订单 / 工资 / 评价 / 打赏 / 提现 / 通知")
    db.query(SalaryRecord).delete(synchronize_session=False)
    db.query(PlayerRating).delete(synchronize_session=False)
    db.query(TipRecord).delete(synchronize_session=False)
    db.query(WithdrawalRecord).delete(synchronize_session=False)
    db.query(Notification).delete(synchronize_session=False)
    db.query(Order).delete(synchronize_session=False)

    print("  · 复位账户累计字段")
    for b in db.query(BossInfo).all():
        b.order_count = 0
        b.consume_amount = 0
        b.balance = Decimal(str(BOSS_BALANCE.get(b.username, 2000)))
    for p in db.query(PlayerInfo).all():
        p.order_count = 0
        p.complaint_count = 0
        p.good_rate = None
        p.backend_amount = 0
    db.commit()


def ensure_players(db, now) -> None:
    """确保 6 名演示打手存在（幂等）"""
    created = 0
    for uname, nick, ltype, tech, avatar, intro, tags in NEW_PLAYERS:
        if db.query(User).filter(User.username == uname).first():
            continue
        db.add(User(username=uname, password_hash=hash_password("123456"),
                    role="player", role_name="打手", nickname=nick, avatar=avatar,
                    nickname_status="approved", avatar_status="approved"))
        db.add(PlayerInfo(username=uname, order_count=0, complaint_count=0,
                          good_rate=None, backend_amount=0,
                          intro=intro, level_type=ltype, tech_level=tech))
        for tag in tags:
            db.add(PlayerTag(username=uname, tag=tag, status="approved",
                             processed_at=now - timedelta(days=random.randint(1, 20))))
        created += 1
    if created:
        db.commit()
        print(f"  · 新增演示打手 {created} 名")


def main(reset: bool = False) -> None:
    db = SessionLocal()
    try:
        if db.query(Order).count() > 0 and not reset:
            print("⚠️  orders 表已有数据，已跳过（需要重建请加 --reset）")
            return
        if reset:
            reset_business_data(db)

        now = datetime.now()
        ensure_players(db, now)

        # 价目表（金额推导的唯一来源，避免出现"和价目表对不上"的订单）
        cc = db.query(ContentConfig).filter(ContentConfig.config_key == "price").first()
        price_list = json.loads(cc.config_value) if cc else []
        if not price_list:
            print("✗ 价目表为空，无法推导订单金额")
            return

        rate = config_service.commission_rate(db)
        print(f"  · 抽成比例 {rate:.0%}，价目 {len(price_list)} 条")

        players = db.query(PlayerInfo).all()
        weights = [PLAYER_WEIGHT.get(p.username, DEFAULT_WEIGHT) for p in players]

        total_plan = sum(BOSS_ORDER_PLAN.values())
        # 打手接单计划：先给每人保底 PLAYER_MIN_ORDERS 单，剩余名额按权重补，
        # 再打乱顺序——避免"高权重打手总是最早接到单"造成时间分布不自然。
        slots = []
        for p in players:
            slots.extend([p] * PLAYER_MIN_ORDERS)
        remain = total_plan - len(slots)
        if remain > 0:
            slots.extend(random.choices(players, weights=weights, k=remain))
        slots = slots[:total_plan]
        random.shuffle(slots)
        slot_i = 0

        total_orders = 0
        for bname, n_orders in BOSS_ORDER_PLAN.items():
            boss = db.query(BossInfo).filter(BossInfo.username == bname).first()
            if not boss:
                continue

            # 该老板的订单时间：跨度 90 天，本月占比更高，让"本月总盈利"有内容
            for i in range(n_orders):
                total_orders += 1
                game_type, duration, amount_cent, service_note = _pick_service(price_list)
                player = slots[slot_i % len(slots)]
                slot_i += 1

                if random.random() < 0.55:
                    created = now - timedelta(days=random.randint(0, 9),
                                              hours=random.randint(0, 20),
                                              minutes=random.randint(0, 59))
                else:
                    created = now - timedelta(days=random.randint(10, 88),
                                              hours=random.randint(0, 20),
                                              minutes=random.randint(0, 59))
                remark = random.choice(REMARKS)

                is_done = random.random() < 0.88
                order = Order(
                    order_no="ORD" + (created + timedelta(seconds=total_orders)).strftime("%Y%m%d%H%M%S")
                            + f"{total_orders:03d}",
                    boss_username=bname, player_username=player.username,
                    game_type=game_type, duration_min=duration,
                    total_amount=amount_cent, service_note=service_note,
                    remark=remark, created_at=created,
                )

                if is_done:
                    start = created + timedelta(minutes=random.randint(3, 15))
                    end = start + timedelta(minutes=max(duration, random.randint(30, 240)))
                    order.status = "processing"
                    order.start_time = start
                    db.add(order)
                    db.flush()
                    _ledger_freeze_boss(boss, amount_cent)          # 下单冻结
                    _ledger_settle(db, order, boss, player, rate, end)  # 结单入账

                    # 评价：90% 有评价，星级按打手等级加权（等级越高评价越好）
                    if random.random() < 0.90:
                        w = LEVEL_STAR_WEIGHTS.get(player.tech_level or "", DEFAULT_STAR_WEIGHTS)
                        score = random.choices(STAR_KEYS, weights=w)[0]
                        r = PlayerRating(
                            player_username=player.username, boss_username=bname,
                            order_id=order.id, rating=score,
                            comment=random.choice(RATING_COMMENTS[score]),
                            review_status="normal",
                            created_at=end + timedelta(minutes=random.randint(5, 240)))
                        if random.random() < 0.35:
                            r.reply = random.choice(REPLIES)
                            r.reply_time = end + timedelta(hours=random.randint(2, 48))
                        db.add(r)

                    # 打赏：30%，上限为订单金额的 30%（与线上校验一致）
                    if random.random() < 0.30:
                        ratio = min(random.choice(TIP_RATIOS), 0.30)
                        tip = int(amount_cent * ratio)
                        if tip > 0:
                            _ledger_tip(db, order, boss, player, tip,
                                        end + timedelta(minutes=random.randint(10, 120)))
                else:
                    # 在途订单：状态前移，时间更近
                    created = now - timedelta(hours=random.randint(1, 72))
                    order.created_at = created
                    order.status = random.choice(ONGOING_STATUS)
                    if order.status != "pending_accept":
                        order.start_time = created + timedelta(minutes=random.randint(3, 20))
                    db.add(order)
                    db.flush()
                    _ledger_freeze_boss(boss, amount_cent)   # 只冻结，不计数

        db.commit()
        print(f"  · 生成订单 {total_orders} 笔")

        # ---------- 提现记录（与后台金额自洽） ----------
        n_wd = 0
        for p in players:
            if int(p.backend_amount or 0) < 8000:
                continue
            roll = random.random()
            if roll < 0.45:
                amt = int(p.backend_amount * random.uniform(0.20, 0.40))
                _ledger_withdraw(db, p, amt, "approved",
                                 now - timedelta(days=random.randint(2, 20)),
                                 now - timedelta(days=random.randint(1, 18)), "已到账")
                n_wd += 1
            elif roll < 0.70:
                amt = int(p.backend_amount * random.uniform(0.10, 0.20))
                _ledger_withdraw(db, p, amt, "pending",
                                 now - timedelta(days=random.randint(0, 2)))
                n_wd += 1
            elif roll < 0.85:
                amt = int(p.backend_amount * random.uniform(0.10, 0.20))
                _ledger_withdraw(db, p, amt, "rejected",
                                 now - timedelta(days=random.randint(3, 12)),
                                 now - timedelta(days=random.randint(1, 10)),
                                 "收款信息有误，请核对后重新申请")
                n_wd += 1
        db.commit()
        print(f"  · 生成提现记录 {n_wd} 笔")

        # ---------- 投诉（差评 + 【老板投诉】标记，同步 complaint_count） ----------
        # 只挑"评价数≥3"的打手，避免把唯一一条评价改成 1 星后好评率掉到 0%，
        # 那样演示时看着像 bug 而不是数据。
        n_cp = 0
        for p in players:
            rated_cnt = db.query(PlayerRating).filter(
                PlayerRating.player_username == p.username).count()
            if rated_cnt < 3 or random.random() >= 0.30:
                continue
            cand = db.query(Order).filter(Order.player_username == p.username,
                                          Order.status == "completed").all()
            random.shuffle(cand)
            target = None
            for o in cand:   # 优先挑"已有 3~5 星评价"的单，投诉后正好变成差评
                r0 = db.query(PlayerRating).filter(PlayerRating.order_id == o.id).first()
                if r0 and (r0.rating or 0) >= 3 and r0.review_status == "normal":
                    target = (o, r0)
                    break
            if not target:
                continue
            o, r = target
            reason = random.choice(["服务中途掉线多次，体验很差", "全程几乎不沟通，态度敷衍",
                                    "技术水平和标价不符"])
            r.rating = 1
            r.comment = f"【老板投诉】{reason}（原评价：{r.comment or '无'}）"
            r.review_status = "normal"
            p.complaint_count = (p.complaint_count or 0) + 1
            n_cp += 1
        db.commit()
        print(f"  · 生成投诉 {n_cp} 条")

        # ---------- 重算好评率（与评价数据严格一致） ----------
        from api.rating_api import recalc_good_rate
        for p in players:
            recalc_good_rate(db, p.username)
        db.commit()
        print("  · 好评率已重算")

        # ---------- 站内通知 ----------
        def notify(username, title, content, link="/order"):
            u = db.query(User).filter(User.username == username).first()
            if u:
                db.add(Notification(user_id=u.id, title=title, content=content,
                                    type="info", link=link,
                                    created_at=now - timedelta(hours=random.randint(1, 72))))

        recent = db.query(Order).order_by(Order.created_at.desc()).limit(6).all()
        for o in recent:
            notify(o.boss_username, "订单进度",
                   f"您的订单 {o.order_no} 当前状态：{o.status}", "/order")
            if o.player_username:
                notify(o.player_username, "订单进度",
                       f"订单 {o.order_no} 当前状态：{o.status}", "/my-orders")
        db.commit()
        notify("kefu", "待派单提醒", "当前有订单等待人工派单，请及时处理", "/order")
        notify("guanliyuan", "系统提示", "演示数据已重新生成，可在数据统计页查看", "/stats")
        db.commit()
        print("  · 站内通知已生成")

        # ---------- 自检 ----------
        check(db)
        print("✅ 演示数据重建完成")
    finally:
        db.close()


def check(db) -> None:
    """重建后立即对账，任何一项对不上都直接打出来"""
    print("\n  —— 对账自检 ——")
    bad = 0

    for b in db.query(BossInfo).all():
        done = db.query(Order).filter(Order.boss_username == b.username,
                                      Order.status == "completed").count()
        spend = sum(int(o.total_amount or 0) for o in db.query(Order).filter(
            Order.boss_username == b.username, Order.status == "completed").all())
        ok1 = (b.order_count == done)
        ok2 = (int(b.consume_amount or 0) == spend)
        if not (ok1 and ok2):
            bad += 1
        print(f"    老板 {b.username}: 点单次数 存{b.order_count}/应{done} "
              f"{'✓' if ok1 else '✗'} | 累计消费 存{int(b.consume_amount or 0)}/应{spend} "
              f"{'✓' if ok2 else '✗'} | 余额 {float(b.balance):.2f}")

    from sqlalchemy import func
    for p in db.query(PlayerInfo).all():
        done = db.query(Order).filter(Order.player_username == p.username,
                                      Order.status == "completed").count()
        sal = int(db.query(func.coalesce(func.sum(SalaryRecord.player_income), 0))
                  .filter(SalaryRecord.player_username == p.username).scalar() or 0)
        tip = int(db.query(func.coalesce(func.sum(TipRecord.amount), 0))
                  .filter(TipRecord.player_username == p.username).scalar() or 0)
        wd = int(db.query(func.coalesce(func.sum(WithdrawalRecord.amount), 0))
                 .filter(WithdrawalRecord.player_username == p.username,
                         WithdrawalRecord.status == "approved").scalar() or 0)
        want = sal + tip - wd
        cp = db.query(PlayerRating).filter(
            PlayerRating.player_username == p.username,
            PlayerRating.comment.like("【老板投诉】%")).count()
        ok1 = (p.order_count == done)
        ok2 = (int(p.backend_amount or 0) == want)
        ok3 = (p.complaint_count == cp)
        if not (ok1 and ok2 and ok3):
            bad += 1
        print(f"    打手 {p.username}: 接单 存{p.order_count}/应{done} {'✓' if ok1 else '✗'}"
              f" | 后台 存{int(p.backend_amount or 0)}/应{want} {'✓' if ok2 else '✗'}"
              f" | 投诉 存{p.complaint_count}/应{cp} {'✓' if ok3 else '✗'}"
              f" | 好评率 {p.good_rate}")

    # 订单无孤儿引用
    orphan = 0
    for o in db.query(Order).all():
        if not db.query(BossInfo).filter(BossInfo.username == o.boss_username).first():
            orphan += 1
        if o.player_username and not db.query(PlayerInfo).filter(
                PlayerInfo.username == o.player_username).first():
            orphan += 1
    neg = db.query(BossInfo).filter(BossInfo.balance < 0).count()
    negp = db.query(PlayerInfo).filter(PlayerInfo.backend_amount < 0).count()
    rated = db.query(PlayerRating).count()
    tips = db.query(TipRecord).count()
    print(f"    孤儿引用 {orphan}（应 0） | 负余额老板 {neg}（应 0） | "
          f"负后台打手 {negp}（应 0） | 评价 {rated} 条 | 打赏 {tips} 笔")
    if orphan or neg or negp:
        bad += 1
    print(f"  —— 自检结果：{'全部一致 ✓' if bad == 0 else str(bad) + ' 项不一致 ✗'} ——")


if __name__ == "__main__":
    main(reset="--reset" in sys.argv)
