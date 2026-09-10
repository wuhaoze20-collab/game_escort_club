import os
import json
import threading
import time
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from database import engine, SessionLocal, Base, DB_ENGINE
from models import User, ContentConfig, BossInfo, PlayerInfo
from auth import hash_password

# 导入路由
from api.auth_api import router as auth_router
from api.content_api import router as content_router
from api.user_info_api import router as user_info_router
from api.order_api import router as order_router
from api.rating_api import router as rating_router, auto_default_rating
from api.stats_api import router as stats_router
from api.tip_api import router as tip_router
from api.withdraw_api import router as withdraw_router

# 创建数据库表
Base.metadata.create_all(bind=engine)


# 轻量迁移：旧库自动补充新增列（避免删除数据库丢失数据）
def migrate_db():
    with engine.connect() as conn:
        if DB_ENGINE == "mysql":
            # MySQL：通过 information_schema 检查列是否存在
            for col, ddl in (
                ("failed_attempts", "ALTER TABLE users ADD COLUMN failed_attempts INTEGER DEFAULT 0"),
                ("lock_until", "ALTER TABLE users ADD COLUMN lock_until DATETIME NULL"),
            ):
                exists = conn.execute(
                    text("SELECT COUNT(*) FROM information_schema.columns "
                         "WHERE table_schema = DATABASE() AND table_name='users' AND column_name=:c"),
                    {"c": col}
                ).scalar()
                if not exists:
                    conn.execute(text(ddl))
            conn.commit()
        else:
            # SQLite：通过 PRAGMA 检查列是否存在
            cols = [r[1] for r in conn.execute(text("PRAGMA table_info(users)")).fetchall()]
            if "failed_attempts" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN failed_attempts INTEGER DEFAULT 0"))
            if "lock_until" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN lock_until DATETIME"))
            conn.commit()


migrate_db()

app = FastAPI(title="游戏护航俱乐部管理系统", version="2.7.0")

# CORS配置：默认放开跨域便于本地开发；生产环境请用环境变量 CORS_ORIGINS 指定域名列表（逗号分隔）
# 例如：set CORS_ORIGINS=https://admin.example.com,https://www.example.com
default_origins = os.getenv("CORS_ORIGINS", "*").split(",")
allow_origins = [o.strip() for o in default_origins if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=allow_origins != ["*"],  # 通配符时不能带 credentials，避免浏览器拒绝
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth_router)
app.include_router(content_router)
app.include_router(user_info_router)
app.include_router(order_router)
app.include_router(rating_router)
app.include_router(stats_router)
app.include_router(tip_router)
app.include_router(withdraw_router)

# 初始化默认数据
def init_default_data():
    db = SessionLocal()
    try:
        # 初始化默认用户（含默认昵称与默认头像，头像来自 touxiangku 图库）
        default_users = [
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
            {"username": "dashou_06", "password": "123456", "role": "player", "role_name": "打手", "nickname": "星火", "avatar": "avatar_mingxing.jpg"}
        ]
        
        for user_data in default_users:
            existing = db.query(User).filter(User.username == user_data["username"]).first()
            if not existing:
                user = User(
                    username=user_data["username"],
                    password_hash=hash_password(user_data["password"]),
                    role=user_data["role"],
                    role_name=user_data["role_name"],
                    nickname=user_data.get("nickname", ""),
                    avatar=user_data.get("avatar", "")
                )
                db.add(user)
        
        # 初始化默认老板信息（balance 为大狗币，1大狗币=1元）
        default_boss = [
            {"username": "laoban", "consume_amount": 520000, "balance": 1280, "order_count": 36},
            {"username": "laoban_02", "consume_amount": 310000, "balance": 500, "order_count": 18},
            {"username": "laoban_03", "consume_amount": 890000, "balance": 2300, "order_count": 62}
        ]
        for boss_data in default_boss:
            existing = db.query(BossInfo).filter(BossInfo.username == boss_data["username"]).first()
            if not existing:
                db.add(BossInfo(**boss_data))
        
        # 初始化默认打手信息（含等级）
        default_player = [
            {"username": "dashou", "order_count": 128, "complaint_count": 3, "good_rate": 97.2, "backend_amount": 368000, "intro": "大家好，我是打手小达，主玩王者荣耀、和平精英，擅长上分护航，王者100星以上，服务耐心，欢迎老板点单！", "level_type": "技术陪", "tech_level": "魔王护"},
            {"username": "dashou_02", "order_count": 95, "complaint_count": 1, "good_rate": 98.5, "backend_amount": 285000, "intro": "英雄联盟大师段位，主玩打野位，可以语音沟通，稳扎稳打不浪，陪你上分到天亮。", "level_type": "技术陪", "tech_level": "211"},
            {"username": "dashou_03", "order_count": 210, "complaint_count": 7, "good_rate": 95.8, "backend_amount": 620000, "intro": "全能型打手，王者/联盟/原神都可接单，多年护航经验，口碑老店，品质保障。", "level_type": "娱乐陪", "tech_level": ""},
            {"username": "dashou_04", "order_count": 76, "complaint_count": 0, "good_rate": 99.1, "backend_amount": 156000, "intro": "王者荣耀国服百星打野，985技术陪全程语音指导，稳上分不炸车，高端局也能带飞。", "level_type": "技术陪", "tech_level": "985"},
            {"username": "dashou_05", "order_count": 54, "complaint_count": 2, "good_rate": 96.4, "backend_amount": 98000, "intro": "大专技术陪，主玩王者/和平精英，价格实惠服务到位，性价比之选，欢迎新老板体验。", "level_type": "技术陪", "tech_level": "大专"},
            {"username": "dashou_06", "order_count": 168, "complaint_count": 4, "good_rate": 96.9, "backend_amount": 452000, "intro": "明星级护航，原神满命深渊、王者巅峰赛顶级对局，高端局专属陪玩，全天可约。", "level_type": "技术陪", "tech_level": "明星护"}
        ]
        for player_data in default_player:
            existing = db.query(PlayerInfo).filter(PlayerInfo.username == player_data["username"]).first()
            if not existing:
                db.add(PlayerInfo(**player_data))
        
        # 初始化默认内容配置
        default_content = {
            "notice": {
                "title": "欢迎来到XX游戏护航俱乐部",
                "content": "我们提供专业的游戏陪玩、上分护航服务，全天24小时在线。\n近期活动：新用户首单立减20%，充值满100送20余额。\n客服微信：xxxxxx",
                "updateTime": "2024-01-15 10:00"
            },
            "orderGuide": [
                "下单前请联系客服确认打手档期，避免等待",
                "下单后请保持游戏在线，及时接受组队邀请",
                "服务过程中如遇问题，请立即联系客服处理",
                "订单完成后请确认结算，有异议可在24小时内申诉",
                "禁止要求打手进行违规操作，违者账号封禁"
            ],
            "price": [
                {"game": "王者荣耀", "rank": "青铜-钻石", "price": 25, "unit": "元/小时"},
                {"game": "王者荣耀", "rank": "钻石-王者", "price": 40, "unit": "元/小时"},
                {"game": "英雄联盟", "rank": "青铜-铂金", "price": 30, "unit": "元/小时"},
                {"game": "英雄联盟", "rank": "铂金-钻石", "price": 50, "unit": "元/小时"},
                {"game": "和平精英", "rank": "青铜-王牌", "price": 35, "unit": "元/小时"},
                {"game": "原神", "rank": "深渊代打", "price": 60, "unit": "元/层"}
            ],
            "recharge": [
                {"amount": 100, "gift": 10, "bonus": "送大狗币10枚 + 普通会员1天"},
                {"amount": 300, "gift": 50, "bonus": "送大狗币50枚 + 白银会员7天"},
                {"amount": 500, "gift": 120, "bonus": "送大狗币120枚 + 黄金会员15天"},
                {"amount": 1000, "gift": 300, "bonus": "送大狗币300枚 + 黄金会员30天 + 专属打手"}
            ],
            "member": [
                {"level": "普通会员", "discount": "无折扣", "benefits": "基础客服服务、订单优先分配"},
                {"level": "白银会员", "discount": "95折", "benefits": "专属客服、订单优先派单、生日福利"},
                {"level": "黄金会员", "discount": "88折", "benefits": "专属客服、指定打手、免费改单、生日福利"},
                {"level": "钻石会员", "discount": "8折", "benefits": "一对一专属客服、顶级打手优先、全程保段、退款优先"}
            ],
            "payment": [
                {"name": "微信支付", "desc": "支持微信扫码支付，实时到账", "icon": "💬"},
                {"name": "支付宝", "desc": "支持支付宝扫码支付，实时到账", "icon": "💰"},
                {"name": "QQ钱包", "desc": "支持QQ钱包支付，即时到账", "icon": "🐧"},
                {"name": "银行卡转账", "desc": "支持主流银行卡转账，1-2小时到账", "icon": "💳"}
            ],
            "punishment": [
                {"level": "警告", "desc": "轻微违规（言语不当、消极服务等），累计3次升级为停单处罚", "date": "2026-09-01"},
                {"level": "停单3天", "desc": "中度违规（无故拒单、态度恶劣），期间无法接单", "date": "2026-09-01"},
                {"level": "封禁账号", "desc": "严重违规（作弊、诈骗、恶意刷单等），永久封禁并扣除后台金额", "date": "2026-09-01"}
            ]
        }
        
        for key, value in default_content.items():
            existing = db.query(ContentConfig).filter(ContentConfig.config_key == key).first()
            if not existing:
                db.add(ContentConfig(
                    config_key=key,
                    config_value=json.dumps(value, ensure_ascii=False)
                ))
        
        db.commit()
        print("默认数据初始化完成")
    finally:
        db.close()

# 结单后3天未评价的订单自动默认好评（后台线程，每5分钟扫描一次）
@app.on_event("startup")
def start_auto_default_rating():
    def _loop():
        time.sleep(2)  # 等初始化完成后先跑一次
        while True:
            try:
                db = SessionLocal()
                try:
                    auto_default_rating(db)
                finally:
                    db.close()
            except Exception as e:
                print(f"[auto_default_rating] 扫描异常: {e}")
            time.sleep(300)
    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    print("自动默认好评后台任务已启动（每5分钟扫描一次）")

# 启动时初始化数据
init_default_data()

@app.get("/")
def root():
    return {"message": "游戏护航俱乐部管理系统API", "docs": "/docs"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
