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
from seed_ai_content import seed_ai_prompts, seed_ai_faqs
from seed_kb_docs import seed_kb_docs
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
from api.ai_prompt_api import router as ai_prompt_router
from api.ai_rag_api import router as ai_rag_router
from api.kg_api import router as kg_router

# 创建数据库表
Base.metadata.create_all(bind=engine)


# 轻量迁移：旧库自动补充新增列 / 修正列类型（避免删库丢数据）
#
# 新增列一律加进 ADD_COLUMNS，格式 (表名, 列名, DDL)。判定走 information_schema，
# 已存在则跳过，因此每次启动都可安全执行、不会重复 ALTER、不会覆盖数据。
ADD_COLUMNS = (
    ("users", "failed_attempts",
     "ALTER TABLE users ADD COLUMN failed_attempts INTEGER DEFAULT 0"),
    ("users", "lock_until",
     "ALTER TABLE users ADD COLUMN lock_until DATETIME NULL"),
    ("users", "account_status",
     "ALTER TABLE users ADD COLUMN account_status VARCHAR(20) DEFAULT 'approved'"),
    # AI 回答用到的工具名（逗号分隔）。用于审计"AI 到底做了哪些查询"，
    # 出问题时能定位是模型编造还是工具返回了错数据。
    ("ai_messages", "tools_used",
     "ALTER TABLE ai_messages ADD COLUMN tools_used VARCHAR(255) DEFAULT ''"),
    # 评估历史的参数快照（JSON）。V4.4.0 先建了 ai_eval_history 表，
    # A/B 对比参数差异功能才补上这一列，老库升级上来会缺列，
    # 报 "Unknown column 'ai_eval_history.config_json'"，这里自动补齐。
    # 注意：MySQL 的 TEXT 列不能带 DEFAULT（errno 1101），所以不写默认值。
    ("ai_eval_history", "config_json",
     "ALTER TABLE ai_eval_history ADD COLUMN config_json TEXT"),
    # ---- V4.7.0 评估数据集规范：查询类型 / 题集版本 / 评估留痕 ----
    # 题库加"查询类型"（事实型/推理型/对比型）。数据集的覆盖性原则要求三类
    # 都覆盖，抽题时按这个字段分层保底；老库升级上来会缺列，这里自动补齐。
    ("ai_eval_questions", "query_type",
     "ALTER TABLE ai_eval_questions ADD COLUMN query_type VARCHAR(20) DEFAULT 'fact'"),
    # 固定题集从"只留最新一行"改成"每次抽题留一行"，需要版本号与分布快照
    ("ai_eval_fixed_set", "version",
     "ALTER TABLE ai_eval_fixed_set ADD COLUMN version INTEGER DEFAULT 1"),
    ("ai_eval_fixed_set", "role_dist",
     "ALTER TABLE ai_eval_fixed_set ADD COLUMN role_dist TEXT"),
    ("ai_eval_fixed_set", "query_type_dist",
     "ALTER TABLE ai_eval_fixed_set ADD COLUMN query_type_dist TEXT"),
    # 评估历史留一份"当时考了哪几道题"，否则题集重抽之后无法回溯
    ("ai_eval_history", "question_ids",
     "ALTER TABLE ai_eval_history ADD COLUMN question_ids TEXT"),
    ("ai_eval_history", "fixed_set_version",
     "ALTER TABLE ai_eval_history ADD COLUMN fixed_set_version INTEGER DEFAULT 0"),
)


def migrate_db():
    with engine.connect() as conn:
        if DB_ENGINE == "mysql":
            # MySQL：通过 information_schema 检查列是否存在
            for table, col, ddl in ADD_COLUMNS:
                exists = conn.execute(
                    text("SELECT COUNT(*) FROM information_schema.columns "
                         "WHERE table_schema = DATABASE() AND table_name=:t AND column_name=:c"),
                    {"t": table, "c": col}
                ).scalar()
                if not exists:
                    print(f"[migrate] {table}.{col} 缺失，自动补齐…")
                    conn.execute(text(ddl))
            conn.commit()

            # ---- 列类型修正：大狗币余额要支持两位小数 ----
            # 早期建表时该列是 INT，会把小数静默取整（实测写入 0.01 读回 0），
            # 而订单金额不是 100 分整数倍时（如 25.5 元）确实会产生小数。
            # 只在类型还不是 DECIMAL 时执行，因此可反复启动而不会重复 ALTER。
            data_type = conn.execute(
                text("SELECT DATA_TYPE FROM information_schema.columns "
                     "WHERE table_schema = DATABASE() AND table_name='boss_info' "
                     "AND column_name='balance'")
            ).scalar()
            if data_type and str(data_type).lower() not in ("decimal", "numeric"):
                print(f"[migrate] boss_info.balance 当前类型为 {data_type}，升级为 DECIMAL(10,2) 以支持小数…")
                # 先把可能存在的 NULL 归零，否则加 NOT NULL 会失败
                conn.execute(text("UPDATE boss_info SET balance = 0 WHERE balance IS NULL"))
                conn.execute(text(
                    "ALTER TABLE boss_info MODIFY COLUMN balance DECIMAL(10,2) NOT NULL DEFAULT 0.00"))
                conn.commit()
                print("[migrate] boss_info.balance 已升级为 DECIMAL(10,2)")
        else:
            # SQLite：通过 PRAGMA 检查列是否存在
            for table, col, _ddl in ADD_COLUMNS:
                existing = [r[1] for r in
                            conn.execute(text(f"PRAGMA table_info({table})")).fetchall()]
                if col not in existing:
                    # SQLite 的动态类型不需要精确 DDL，这里按列名给一个宽松类型即可
                    kind = "INTEGER" if col in ("failed_attempts",) else "VARCHAR(255) DEFAULT ''"
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {kind}"))
            # SQLite 是动态类型，列本身无需改类型（Numeric 由 SQLAlchemy 侧处理）
            conn.commit()


# 列宽迁移：把 VARCHAR(255) 的列放宽为 TEXT。
# 为什么需要：`system_config.config_value` 早期是 VARCHAR(255)，而
# `ai_extra_instruction` 要放整段提示词文本，写入时直接抛
# DataError(1406, "Data too long for column")。凡"内容可能很长"的配置列都要放宽。
def migrate_columns_to_text():
    if DB_ENGINE != "mysql":
        return  # SQLite 是动态类型，无需处理
    targets = [("system_config", "config_value"), ("content_config", "config_value")]
    with engine.connect() as conn:
        for table, column in targets:
            data_type = conn.execute(
                text("SELECT DATA_TYPE FROM information_schema.columns "
                     "WHERE table_schema = DATABASE() AND table_name=:t AND column_name=:c"),
                {"t": table, "c": column}
            ).scalar()
            if data_type and str(data_type).lower() not in ("text", "mediumtext", "longtext"):
                print(f"[migrate] {table}.{column} 当前为 {data_type}，放宽为 TEXT…")
                conn.execute(text(
                    f"ALTER TABLE {table} MODIFY COLUMN {column} TEXT NOT NULL"))
                conn.commit()
                print(f"[migrate] {table}.{column} 已放宽为 TEXT")


migrate_columns_to_text()
migrate_db()

app = FastAPI(title="大狗嚼电竞管理系统", version="3.10.0")

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
app.include_router(ai_prompt_router)
app.include_router(ai_rag_router)
app.include_router(kg_router)

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
        # AI 提示词段落与问答库（同样幂等：表内已有数据则整体跳过）
        added_prompts = seed_ai_prompts(db)
        if added_prompts:
            print(f"AI 提示词段落初始化完成：导入 {added_prompts} 段")
        added_faqs = seed_ai_faqs(db)
        if added_faqs:
            print(f"AI 问答库初始化完成：导入 {added_faqs} 条")
        # 知识库文档（用户协议/打手规范/退款规则）。只导入正文，**不在此处建索引** ——
        # 建索引要调 embedding 接口（有成本、可能因没配 Key 而失败），
        # 应由管理员在「知识库索引」页显式点「重建索引」触发。
        added_docs = seed_kb_docs(db)
        if added_docs:
            print(f"知识库文档初始化完成：导入 {added_docs} 篇"
                  f"（尚未建立向量索引，请到「系统设置 → 知识库索引」点「重建索引」）")
        # RAG 评估测试题库（幂等：已存在的题目不重复插入）
        import rag_eval
        added_questions = rag_eval.init_eval_questions(db)
        if added_questions:
            print(f"RAG 评估测试题库初始化完成：导入 {added_questions} 道测试题")
    except Exception as e:
        print(f"[init_quotes_and_config] 初始化异常: {e}")
    finally:
        db.close()


init_quotes_and_config()


# 知识图谱：启动时自检连通性；若图谱还是空的，自动从 MySQL 同步一次。
# 它只是"旁路"，任何失败都只打印一行日志，不影响后端启动与其它功能。
def init_knowledge_graph():
    try:
        from kg import store as kg_store, sync as kg_sync
        if not kg_store.available():
            print("[kg] 未安装 neo4j 驱动，知识图谱功能关闭（需要时 pip install neo4j）")
            return
        if not kg_store.configured():
            print("[kg] 未配置 NEO4J_PASSWORD，知识图谱功能关闭（见 backend/.env）")
            return
        if not kg_store.is_ready():
            print("[kg] 无法连接 Neo4j，知识图谱功能本次跳过（请确认 Neo4j 服务已启动）")
            return

        if kg_sync.is_empty():
            db = SessionLocal()
            try:
                r = kg_sync.sync_all(db)
            finally:
                db.close()
            print(f"[kg] 图谱为空，已自动同步：老板 {r['bosses']} 个、打手 {r['players']} 个、"
                  f"订单 {r['orders']} 笔、游戏 {r['games']} 个")
        else:
            st = kg_store.stats()
            print(f"[kg] 知识图谱就绪：{st['nodes']} 个节点 / {st['rels']} 条关系")
    except Exception as e:
        print(f"[kg] 知识图谱初始化异常（不影响其它功能）：{e}")


init_knowledge_graph()


@app.get("/")
def root():
    return FileResponse(INDEX_HTML)

# 挂载头像静态文件
app.mount("/avatars", StaticFiles(directory=AVATARS_DIR), name="avatars")

# 挂载壁纸库静态文件
app.mount("/bizhiku", StaticFiles(directory=BIZHIKU_DIR), name="bizhiku")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
