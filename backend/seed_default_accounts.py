# -*- coding: utf-8 -*-
"""
默认账户与基础数据种子脚本
============================================
把系统的默认账户、老板/打手初始信息、内容配置全部定义在这里，
数据实体统一写入 MySQL，后端主程序不再内嵌任何账户数据。

- 12 个默认账户：管理员1 / 客服1 / 老板3 / 打手6（密码统一 123456，bcrypt 哈希存储）
- 3 个老板初始信息（消费金额/大狗币余额/点单次数）
- 6 个打手初始信息（接单数/投诉数/好评率/后台金额/简介/等级）
- 内容配置（公告/下单须知/价格/充值福利/会员福利/支付方式/处罚通告）

幂等：已存在则跳过，可重复执行；不会覆盖已修改的数据。
用法：
    venv\Scripts\python seed_default_accounts.py          # 手动执行
    （main.py 启动时也会自动调用，保证新库首次启动有默认数据）
"""
import json

from database import SessionLocal
from models import User, BossInfo, PlayerInfo, ContentConfig
from auth import hash_password

# ========== 默认账户（密码统一 123456，存储为 bcrypt 哈希） ==========
DEFAULT_USERS = [
    {"username": "guanliyuan", "password": "123456", "role": "admin", "role_name": "管理员", "nickname": "店长", "avatar": "avatar_admin.jpg"},
    {"username": "kefu", "password": "123456", "role": "service", "role_name": "客服", "nickname": "客服小蜜", "avatar": "avatar_service.png"},
    {"username": "laoban", "password": "123456", "role": "boss", "role_name": "老板", "nickname": "老板阿昊", "avatar": "avatar_boss.png"},
    {"username": "laoban_02", "password": "123456", "role": "boss", "role_name": "老板", "nickname": "老板二狗", "avatar": "avatar_boss.png"},
    {"username": "laoban_03", "password": "123456", "role": "boss", "role_name": "老板", "nickname": "老板三少", "avatar": "avatar_boss.png"},
    {"username": "dashou", "password": "123456", "role": "player", "role_name": "打手", "nickname": "小达", "avatar": "avatar_mowanghu.jpg"},
    {"username": "dashou_02", "password": "123456", "role": "player", "role_name": "打手", "nickname": "阿岚", "avatar": "avatar_211_2.jpg"},
    {"username": "dashou_03", "password": "123456", "role": "player", "role_name": "打手", "nickname": "老猫", "avatar": "avatar_yule.jpg"},
    {"username": "dashou_04", "password": "123456", "role": "player", "role_name": "打手", "nickname": "北冥", "avatar": "avatar_985_2.jpg"},
    {"username": "dashou_05", "password": "123456", "role": "player", "role_name": "打手", "nickname": "阿澈", "avatar": "avatar_dazhuan.png"},
    {"username": "dashou_06", "password": "123456", "role": "player", "role_name": "打手", "nickname": "星火", "avatar": "avatar_mingxing.jpg"},
]

# ========== 默认老板信息（balance 为大狗币，1大狗币=1元） ==========
DEFAULT_BOSS = [
    {"username": "laoban", "consume_amount": 520000, "balance": 1280, "order_count": 36},
    {"username": "laoban_02", "consume_amount": 310000, "balance": 500, "order_count": 18},
    {"username": "laoban_03", "consume_amount": 890000, "balance": 2300, "order_count": 62},
]

# ========== 默认打手信息（含等级划分） ==========
DEFAULT_PLAYER = [
    {"username": "dashou", "order_count": 128, "complaint_count": 3, "good_rate": 97.2, "backend_amount": 368000, "intro": "大家好，我是打手小达，主玩王者荣耀、和平精英，擅长上分护航，王者100星以上，服务耐心，欢迎老板点单！", "level_type": "技术陪", "tech_level": "魔王护"},
    {"username": "dashou_02", "order_count": 95, "complaint_count": 1, "good_rate": 98.5, "backend_amount": 285000, "intro": "英雄联盟大师段位，主玩打野位，可以语音沟通，稳扎稳打不浪，陪你上分到天亮。", "level_type": "技术陪", "tech_level": "211"},
    {"username": "dashou_03", "order_count": 210, "complaint_count": 7, "good_rate": 95.8, "backend_amount": 620000, "intro": "全能型打手，王者/联盟/原神都可接单，多年护航经验，口碑老店，品质保障。", "level_type": "娱乐陪", "tech_level": ""},
    {"username": "dashou_04", "order_count": 76, "complaint_count": 0, "good_rate": 99.1, "backend_amount": 156000, "intro": "王者荣耀国服百星打野，985技术陪全程语音指导，稳上分不炸车，高端局也能带飞。", "level_type": "技术陪", "tech_level": "985"},
    {"username": "dashou_05", "order_count": 54, "complaint_count": 2, "good_rate": 96.4, "backend_amount": 98000, "intro": "大专技术陪，主玩王者/和平精英，价格实惠服务到位，性价比之选，欢迎新老板体验。", "level_type": "技术陪", "tech_level": "大专"},
    {"username": "dashou_06", "order_count": 168, "complaint_count": 4, "good_rate": 96.9, "backend_amount": 452000, "intro": "明星级护航，原神满命深渊、王者巅峰赛顶级对局，高端局专属陪玩，全天可约。", "level_type": "技术陪", "tech_level": "明星护"},
]

# ========== 默认内容配置（公告/须知/价格/充值/会员/支付/处罚） ==========
DEFAULT_CONTENT = {
    "notice": {
        "title": "欢迎来到大狗嚼电竞",
        "content": "我们提供专业的游戏陪玩、上分护航服务，全天24小时在线。\n近期活动：新用户首单立减20%，充值满100送20余额。\n客服微信：xxxxxx",
        "updateTime": "2024-01-15 10:00",
    },
    "orderGuide": [
        "下单前请联系客服确认打手档期，避免等待",
        "下单后请保持游戏在线，及时接受组队邀请",
        "服务过程中如遇问题，请立即联系客服处理",
        "订单完成后请确认结算，有异议可在24小时内申诉",
        "禁止要求打手进行违规操作，违者账号封禁",
    ],
    "price": [
        {"game": "王者荣耀", "rank": "青铜-钻石", "price": 25, "unit": "元/小时"},
        {"game": "王者荣耀", "rank": "钻石-王者", "price": 40, "unit": "元/小时"},
        {"game": "英雄联盟", "rank": "青铜-铂金", "price": 30, "unit": "元/小时"},
        {"game": "英雄联盟", "rank": "铂金-钻石", "price": 50, "unit": "元/小时"},
        {"game": "和平精英", "rank": "青铜-王牌", "price": 35, "unit": "元/小时"},
        {"game": "原神", "rank": "深渊代打", "price": 60, "unit": "元/层"},
    ],
    "recharge": [
        {"amount": 100, "gift": 10, "bonus": "送大狗币10枚 + 普通会员1天"},
        {"amount": 300, "gift": 50, "bonus": "送大狗币50枚 + 白银会员7天"},
        {"amount": 500, "gift": 120, "bonus": "送大狗币120枚 + 黄金会员15天"},
        {"amount": 1000, "gift": 300, "bonus": "送大狗币300枚 + 黄金会员30天 + 专属打手"},
    ],
    "member": [
        {"level": "普通会员", "discount": "无折扣", "benefits": "基础客服服务、订单优先分配"},
        {"level": "白银会员", "discount": "95折", "benefits": "专属客服、订单优先派单、生日福利"},
        {"level": "黄金会员", "discount": "88折", "benefits": "专属客服、指定打手、免费改单、生日福利"},
        {"level": "钻石会员", "discount": "8折", "benefits": "一对一专属客服、顶级打手优先、全程保段、退款优先"},
    ],
    "payment": [
        {"name": "微信支付", "desc": "支持微信扫码支付，实时到账", "icon": "💬"},
        {"name": "支付宝", "desc": "支持支付宝扫码支付，实时到账", "icon": "💰"},
        {"name": "QQ钱包", "desc": "支持QQ钱包支付，即时到账", "icon": "🐧"},
        {"name": "银行卡转账", "desc": "支持主流银行卡转账，1-2小时到账", "icon": "💳"},
    ],
    "punishment": [
        {"level": "警告", "desc": "轻微违规（言语不当、消极服务等），累计3次升级为停单处罚", "date": "2026-09-01"},
        {"level": "停单3天", "desc": "中度违规（无故拒单、态度恶劣），期间无法接单", "date": "2026-09-01"},
        {"level": "封禁账号", "desc": "严重违规（作弊、诈骗、恶意刷单等），永久封禁并扣除后台金额", "date": "2026-09-01"},
    ],
    "matches": [
        {"game": "三角洲行动", "title": "三角洲行动官方赛事直播", "url": "https://live.bilibili.com/1921272912"},
        {"game": "Apex英雄", "title": "Apex英雄官方赛事直播", "url": "https://space.bilibili.com/1676940341"},
        {"game": "CS2", "title": "CS2官方赛事直播", "url": "https://space.bilibili.com/474595627"},
        {"game": "英雄联盟", "title": "英雄联盟官方赛事直播", "url": "https://live.bilibili.com/6"},
        {"game": "无畏契约", "title": "无畏契约官方赛事直播", "url": "https://space.bilibili.com/2071691173"},
        {"game": "刀塔2", "title": "刀塔2官方赛事直播", "url": "https://space.bilibili.com/17561885"},
        {"game": "王者荣耀", "title": "王者荣耀官方赛事直播", "url": "https://live.bilibili.com/55"},
    ],
}


def seed_default_accounts():
    """幂等写入默认数据：已存在则跳过，可重复执行"""
    db = SessionLocal()
    try:
        # 1. 默认账户（含默认昵称与默认头像，头像来自 touxiangku 图库）
        for user_data in DEFAULT_USERS:
            existing = db.query(User).filter(User.username == user_data["username"]).first()
            if not existing:
                db.add(User(
                    username=user_data["username"],
                    password_hash=hash_password(user_data["password"]),
                    role=user_data["role"],
                    role_name=user_data["role_name"],
                    nickname=user_data.get("nickname", ""),
                    avatar=user_data.get("avatar", ""),
                    nickname_status="approved",
                    avatar_status="approved",
                ))

        # 2. 默认老板信息
        for boss_data in DEFAULT_BOSS:
            existing = db.query(BossInfo).filter(BossInfo.username == boss_data["username"]).first()
            if not existing:
                db.add(BossInfo(**boss_data))

        # 3. 默认打手信息
        for player_data in DEFAULT_PLAYER:
            existing = db.query(PlayerInfo).filter(PlayerInfo.username == player_data["username"]).first()
            if not existing:
                db.add(PlayerInfo(**player_data))

        # 4. 内容配置
        for key, value in DEFAULT_CONTENT.items():
            existing = db.query(ContentConfig).filter(ContentConfig.config_key == key).first()
            if not existing:
                db.add(ContentConfig(
                    config_key=key,
                    config_value=json.dumps(value, ensure_ascii=False),
                ))

        db.commit()
        print("默认账户与基础数据初始化完成（幂等：已存在的记录未重复插入）")
    finally:
        db.close()


if __name__ == "__main__":
    seed_default_accounts()
