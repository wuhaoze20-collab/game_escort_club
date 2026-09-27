import os
import sys
import threading
import time

# 路径基准：全部基于本文件位置推导，因此从任何工作目录启动都能正确定位
# （此前用 "../frontend/..." 这类相对路径，必须先 cd 到 backend 才能启动）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))       # backend/
PROJECT_ROOT = os.path.dirname(BASE_DIR)                     # 项目根目录
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")
AVATARS_DIR = os.path.join(FRONTEND_DIR, "avatars")
BIZHIKU_DIR = os.path.join(PROJECT_ROOT, "bizhiku")
INDEX_HTML = os.path.join(FRONTEND_DIR, "index.html")

# 保证任何工作目录下都能 import 到本项目模块
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import text
from database import engine, SessionLocal, Base, DB_ENGINE
from seed_default_accounts import seed_default_accounts
from seed_quotes import seed_quotes
import config_service

# 导入路由
from api.auth_api import router as auth_router
from api.content_api import router as content_router
from api.user_info_api import router as user_info_router
from api.order_api import router as order_router
from api.rating_api import router as rating_router, auto_default_rating
from api.stats_api import router as stats_router
from api.tip_api import router as tip_router
from api.withdraw_api import router as withdraw_router
from api.notification_api import router as notification_router
from api.quote_api import router as quote_router
from api.config_api import router as config_router
from api.ai_api import router as ai_router

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
                ("account_status", "ALTER TABLE users ADD COLUMN account_status VARCHAR(20) DEFAULT 'approved'"),
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
            if "account_status" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN account_status VARCHAR(20) DEFAULT 'approved'"))
            conn.commit()


migrate_db()

app = FastAPI(title="大狗嚼电竞管理系统", version="3.5.0")

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
app.include_router(notification_router)
app.include_router(quote_router)
app.include_router(config_router)
app.include_router(ai_router)

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

# 启动时初始化默认数据（账户/老板/打手/内容配置，幂等，数据实体存 MySQL）
seed_default_accounts()


# 初始化台词表与系统参数表（幂等：二者都只在缺失时写入，不覆盖后台的增删改）
def init_quotes_and_config():
    db = SessionLocal()
    try:
        added_quotes = seed_quotes(db)
        if added_quotes:
            print(f"台词表初始化完成：导入 {added_quotes} 条默认台词")
        added_configs = config_service.ensure_defaults(db)
        if added_configs:
            print(f"系统参数表初始化完成：补齐 {added_configs} 项参数")
    except Exception as e:
        print(f"[init_quotes_and_config] 初始化异常: {e}")
    finally:
        db.close()


init_quotes_and_config()

@app.get("/")
def root():
    return FileResponse(INDEX_HTML)

# 挂载头像静态文件
app.mount("/avatars", StaticFiles(directory=AVATARS_DIR), name="avatars")

# 挂载壁纸库静态文件
app.mount("/bizhiku", StaticFiles(directory=BIZHIKU_DIR), name="bizhiku")

if __name__ == "__main__":
    import uvicorn
    # app_dir 让 reload 的子进程也能找到本模块，从而摆脱对工作目录的依赖
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, app_dir=BASE_DIR)
