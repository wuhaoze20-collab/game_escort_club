# -*- coding: utf-8 -*-
"""
默认账户与基础数据种子脚本
============================================
把系统的默认账户、老板/打手初始信息、内容配置全部定义在这里，
数据实体统一写入 MySQL，后端主程序不再内嵌任何账户数据。

- 12 个默认账户：管理员1 / 客服1 / 老板3 / 打手6（密码统一 123456，bcrypt 哈希存储）
- 3 个老板初始信息（大狗币余额；消费金额/点单次数由实际订单动态计算）
- 6 个打手初始信息（后台金额/简介/等级；接单数/投诉数/好评率由实际订单与评价动态计算）
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

# ========== 默认老板信息（balance 为大狗币，1大狗币=1元；消费金额/点单次数由实际订单动态计算，不硬编码） ==========
DEFAULT_BOSS = [
    {"username": "laoban", "balance": 1280},
    {"username": "laoban_02", "balance": 500},
    {"username": "laoban_03", "balance": 2300},
]

# ========== 默认打手信息（含等级划分；接单数/投诉数/好评率由实际订单与评价动态计算，不硬编码） ==========
DEFAULT_PLAYER = [
    {"username": "dashou", "backend_amount": 368000, "intro": "大家好，我是打手小达，主玩王者荣耀、和平精英，擅长上分护航，王者100星以上，服务耐心，欢迎老板点单！", "level_type": "技术陪", "tech_level": "魔王护"},
    {"username": "dashou_02", "backend_amount": 285000, "intro": "英雄联盟大师段位，主玩打野位，可以语音沟通，稳扎稳打不浪，陪你上分到天亮。", "level_type": "技术陪", "tech_level": "211"},
    {"username": "dashou_03", "backend_amount": 620000, "intro": "全能型打手，王者/联盟/原神都可接单，多年护航经验，口碑老店，品质保障。", "level_type": "娱乐陪", "tech_level": ""},
    {"username": "dashou_04", "backend_amount": 156000, "intro": "王者荣耀国服百星打野，985技术陪全程语音指导，稳上分不炸车，高端局也能带飞。", "level_type": "技术陪", "tech_level": "985"},
    {"username": "dashou_05", "backend_amount": 98000, "intro": "大专技术陪，主玩王者/和平精英，价格实惠服务到位，性价比之选，欢迎新老板体验。", "level_type": "技术陪", "tech_level": "大专"},
    {"username": "dashou_06", "backend_amount": 452000, "intro": "明星级护航，原神满命深渊、王者巅峰赛顶级对局，高端局专属陪玩，全天可约。", "level_type": "技术陪", "tech_level": "明星护"},
]

# ========== 默认内容配置（公告/须知/价格/充值/会员/支付/处罚） ==========
DEFAULT_CONTENT = {
    "notice": {
    "title": "欢迎来到大狗嚼电竞",
    "content": "「大狗嚼电竞」专注游戏陪玩、护航、上分服务，平台打手全部实名认证、分级管理（娱乐陪/技术陪），服务全程可评价可投诉。\n\n【服务时间】\n全天 24 小时在线接单，高峰期（18:00-24:00）打手充足，下单后 5 分钟内响应。\n\n【平台活动】\n· 新用户首单立减 20%；\n· 充值满 100 送 10 大狗币，满 300 送 50，满 500 送 120，满 1000 送 300；\n· 充值可叠加会员专属福利，充得越多送得越多。\n\n【温馨提示】\n· 请通过平台内下单，切勿私下转账，谨防上当受骗；\n· 大狗币充值与消费全程受平台保障；\n· 遇到任何问题请联系在线客服。\n\n愿你在每一局游戏里，都能畅快到底！",
    "updateTime": "2026-09-11 18:00"
},
    "orderGuide": [
    "下单前请先在「价格预览」查看各游戏与业务的单价",
    "进入「点单中心」选择游戏、业务类型、打手与时长，金额由系统自动计算",
    "下单时可填写备注（段位、模式、上分要求等），打手将根据备注决定接单或拒单",
    "打手接单并开始服务后，服务完成由打手提交结单，老板确认后费用才转入打手后台",
    "点单消耗大狗币（1元 = 1大狗币），金额按单价×时长/数量自动计算，不可手动修改",
    "结单后可自愿打赏打手，单次打赏上限不超过订单单价的 30%",
    "打手提现需满足 30 天冷却期，金额转入绑定的收款账户",
    "打手简介、标签、等级全部公开透明，老板可自行筛选",
    "服务结束后 3 天内未评价的订单自动默认为好评",
    "老板可对不满意的订单发起投诉，打手可申诉，由管理员最终审核",
    "打手接单后长时间未开始服务，老板可申请取消订单并退款",
    "请勿绕过平台私下交易，私下交易产生的纠纷平台不予受理",
    "请文明沟通，恶意辱骂、骚扰将被处罚，情节严重将封禁账号",
    "账号被拉黑后，后台金额将转入公司账户",
    "如有疑问请联系在线客服"
],
    "price": [
        {"game": "王者荣耀", "rank": "青铜-钻石", "price": 25, "unit": "元/小时"},
        {"game": "王者荣耀", "rank": "钻石-王者", "price": 40, "unit": "元/小时"},
        {"game": "英雄联盟", "rank": "青铜-铂金", "price": 30, "unit": "元/小时"},
        {"game": "英雄联盟", "rank": "铂金-钻石", "price": 50, "unit": "元/小时"},
        {"game": "和平精英", "rank": "青铜-王牌", "price": 35, "unit": "元/小时"},
        {"game": "原神", "rank": "深渊代打", "price": 60, "unit": "元/层"},
        {"game": "三角洲行动", "rank": "陪玩护航", "price": 35, "unit": "元/小时"},
        {"game": "三角洲行动", "rank": "跑刀摸金", "price": 28, "unit": "元/小时"},
        {"game": "三角洲行动", "rank": "战术配合", "price": 45, "unit": "元/小时"},
        {"game": "Apex英雄", "rank": "陪玩上分", "price": 35, "unit": "元/小时"},
        {"game": "Apex英雄", "rank": "排位上分", "price": 45, "unit": "元/小时"},
        {"game": "Apex英雄", "rank": "通行证代肝", "price": 1.5, "unit": "元/级"},
        {"game": "Apex英雄", "rank": "通行证满级", "price": 70, "unit": "元/满级"},
        {"game": "无畏契约", "rank": "陪玩娱乐", "price": 35, "unit": "元/小时"},
        {"game": "无畏契约", "rank": "排位上分", "price": 50, "unit": "元/小时"},
        {"game": "CS2", "rank": "陪玩娱乐", "price": 30, "unit": "元/小时"},
        {"game": "CS2", "rank": "排位上分", "price": 45, "unit": "元/小时"},
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
        {"game": "无畏契约", "title": "无畏契约官方赛事直播", "url": "https://live.bilibili.com/22908869/?live_from=86001&spm_id_from=333.1387.0.0"},
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
