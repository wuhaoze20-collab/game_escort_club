# -*- coding: utf-8 -*-
"""
演示数据填充脚本：为大狗嚼电竞系统生成一批真实感的演示数据
- 新增 6 名打手（覆盖全部等级，含自我介绍与已审核标签）
- 为 3 位老板生成历史订单（含进行中订单）+ 工资记录 + 评价 + 打赏 + 提现记录
- 幂等：若 orders 表已有数据则跳过，避免重复填充

用法：venv\Scripts\python seed_demo_data.py
"""
import random
from datetime import datetime, timedelta

from database import SessionLocal
from models import (
    User, BossInfo, PlayerInfo, PlayerTag, Order,
    SalaryRecord, PlayerRating, TipRecord, WithdrawalRecord,
)
from auth import hash_password
import config_service

random.seed(20260910)

# 俱乐部抽成比例不再硬编码：直接读取 system_config，避免与 order_api 的取值不一致

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

GAMES = ["王者荣耀", "和平精英", "英雄联盟", "原神", "CS2"]
BOSSES = ["laoban", "laoban_02", "laoban_03"]

RATING_COMMENTS = {
    5: ["非常专业，带我上分稳稳的，必须五星！", "技术一流，配合默契，下次还找你！", "全程语音指导，体验拉满，推荐给所有老板！", "稳如老狗，一晚上连上三个段，太强了！", "服务态度超好，有耐心，点赞！"],
    4: ["整体不错，技术在线，就是开场稍慢了点。", "打得挺好，沟通再多一点就更完美了。", "质量不错，价格也合理，会回购。"],
    3: ["中规中矩吧，能赢但体验一般。", "还行，偶尔掉线，希望改进。"],
    2: ["不太满意，节奏有点慢，再练练吧。", "和预期有差距，沟通也不太顺畅。"],
}
REPLIES = ["感谢老板认可，下次继续带飞！", "老板满意就好，随时约我！", "收到，一定继续保持，感谢五星好评！", "感谢支持，你的满意是我最大的动力！"]

REMARKS = ["老板想上分，稳一点", "尽量拿MVP", "语音沟通", "别浪，稳赢", "陪练新赛季冲分", "多交流，教学局", "", "速战速决"]

TIPS = [0.05, 0.08, 0.10, 0.15, 0.20]  # 打赏占订单额比例（%）

def main():
    db = SessionLocal()
    try:
        if db.query(Order).count() > 0:
            print("⚠️  orders 表已有数据，已跳过演示填充（如需重置请清空业务表后再运行）")
            return

        now = datetime.now()

        # ========== 1. 新增 6 名打手 ==========
        players = list(db.query(PlayerInfo).all())  # 已有打手
        for uname, nick, ltype, tech, avatar, intro, tags in NEW_PLAYERS:
            user = User(
                username=uname, password_hash=hash_password("123456"),
                role="player", role_name="打手", nickname=nick, avatar=avatar,
                nickname_status="approved", avatar_status="approved",
            )
            db.add(user)
            pi = PlayerInfo(
                username=uname, order_count=0, complaint_count=0,
                good_rate=100.0, backend_amount=0,
                intro=intro, level_type=ltype, tech_level=tech,
            )
            db.add(pi)
            for tag in tags:
                db.add(PlayerTag(username=uname, tag=tag, status="approved",
                                 processed_at=now - timedelta(days=random.randint(1, 20))))
            players.append(pi)
            print(f"  新增打手 {uname}（{nick}/{tech or '娱乐陪'}）")

        # ========== 2. 老板充值（保证余额充足） ==========
        for bname in BOSSES:
            boss = db.query(BossInfo).filter(BossInfo.username == bname).first()
            if boss:
                boss.balance += 5000
        print("  老板各充值 +5000 大狗币")

        # ========== 3. 生成订单 ==========
        all_players = players
        order_seq = 0
        for bname in BOSSES:
            boss = db.query(BossInfo).filter(BossInfo.username == bname).first()
            n_orders = random.randint(9, 12)
            for _ in range(n_orders):
                order_seq += 1
                order_no = f"GC{now:%Y%m%d%H%M%S}{order_seq:03d}"
                player = random.choice(all_players)
                game = random.choice(GAMES)
                duration = random.choice([60, 90, 120, 150, 180, 240])
                amount = random.randint(30, 200) * 100  # 30~200元(分)
                is_completed = random.random() < 0.9
                # 时间：60% 落在本月（9月1日~今天），40% 落在8月
                days_ago = random.randint(1, 45)
                created = now - timedelta(days=days_ago)
                if random.random() < 0.4:
                    created = now - timedelta(days=random.randint(16, 45))
                remark = random.choice(REMARKS)
                if is_completed:
                    start = created + timedelta(minutes=random.randint(3, 15))
                    end = start + timedelta(minutes=duration)
                    order = Order(order_no=order_no, boss_username=bname, player_username=player.username,
                                  game_type=game, duration_min=duration, total_amount=amount,
                                  remark=remark, status="completed",
                                  created_at=created, start_time=start, end_time=end)
                    db.add(order)
                    db.flush()
                    # 结算：工资记录（抽成比例读自 system_config，与真实结单逻辑保持同一口径）
                    commission = int(amount * config_service.commission_rate(db))
                    income = amount - commission
                    db.add(SalaryRecord(order_id=order.id, player_username=player.username,
                                        order_total=amount, club_commission=commission,
                                        player_income=income, settlement_time=end,
                                        payout_status="paid"))
                    # 老板扣款 + 消费/次数
                    boss.balance -= amount // 100
                    boss.consume_amount += amount
                    boss.order_count += 1
                    # 打手：接单数 + 后台金额入账
                    player.order_count += 1
                    player.backend_amount += income
                    # 评价（70%）
                    if random.random() < 0.7:
                        score = random.choices([5, 4, 3, 2], weights=[60, 25, 10, 5])[0]
                        rating = PlayerRating(player_username=player.username, boss_username=bname,
                                              order_id=order.id, rating=score,
                                              comment=random.choice(RATING_COMMENTS[score]),
                                              created_at=end + timedelta(minutes=random.randint(5, 240)))
                        # 30% 打手回复
                        if random.random() < 0.3:
                            rating.reply = random.choice(REPLIES)
                            rating.reply_time = end + timedelta(hours=random.randint(2, 48))
                        db.add(rating)
                    # 打赏（25%）
                    if random.random() < 0.25:
                        tip_amount = int(amount * random.choice(TIPS))
                        db.add(TipRecord(order_id=order.id, boss_username=bname,
                                         player_username=player.username, amount=tip_amount,
                                         created_at=end + timedelta(minutes=random.randint(10, 120))))
                        boss.balance -= tip_amount // 100
                        player.backend_amount += tip_amount
                else:
                    # 进行中订单：已接单/服务中
                    status = random.choice(["pending_accept", "assigned", "processing"])
                    start = created + timedelta(minutes=random.randint(1, 10))
                    order = Order(order_no=order_no, boss_username=bname, player_username=player.username,
                                  game_type=game, duration_min=duration, total_amount=amount,
                                  remark=remark, status=status,
                                  created_at=created, start_time=start if status != "pending_accept" else None)
                    db.add(order)
                    # 下单即冻结余额
                    boss.balance -= amount // 100
                    boss.order_count += 1

        # ========== 4. 提现记录（部分打手） ==========
        withdraw_players = random.sample(all_players, min(6, len(all_players)))
        for p in withdraw_players:
            if p.backend_amount < 5000:
                continue
            roll = random.random()
            if roll < 0.5:
                w_amount = int(p.backend_amount * random.uniform(0.2, 0.4))
                p.backend_amount -= w_amount
                db.add(WithdrawalRecord(player_username=p.username, amount=w_amount, status="approved",
                                        note="已到账", created_at=now - timedelta(days=random.randint(2, 20)),
                                        processed_at=now - timedelta(days=random.randint(1, 18))))
            elif roll < 0.8:
                w_amount = int(p.backend_amount * random.uniform(0.1, 0.2))
                db.add(WithdrawalRecord(player_username=p.username, amount=w_amount, status="pending",
                                        created_at=now - timedelta(days=random.randint(0, 2))))
            else:
                w_amount = int(p.backend_amount * random.uniform(0.1, 0.2))
                db.add(WithdrawalRecord(player_username=p.username, amount=w_amount, status="rejected",
                                        note="收款信息有误，请核对后重新申请",
                                        created_at=now - timedelta(days=random.randint(3, 12)),
                                        processed_at=now - timedelta(days=random.randint(1, 10))))

        db.commit()
        print(f"✅ 演示数据填充完成：{order_seq} 笔订单")

        # ========== 5. 重算好评率（与评价数据保持一致） ==========
        from api.rating_api import recalc_good_rate
        for p in all_players:
            recalc_good_rate(db, p.username)
        db.commit()
        print("✅ 好评率已按评价数据重算")
    finally:
        db.close()


if __name__ == "__main__":
    main()
