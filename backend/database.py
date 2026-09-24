import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# 数据库类型：默认 mysql；设置环境变量 DB_ENGINE=sqlite 可回退到本地 SQLite
DB_ENGINE = os.getenv("DB_ENGINE", "mysql")

# SQLite 文件的落点固定为 backend/ 目录下，避免因工作目录不同而生成到别处
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))

if DB_ENGINE == "mysql":
    MYSQL_USER = os.getenv("MYSQL_USER", "game_escort")
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "123456")
    MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
    MYSQL_PORT = os.getenv("MYSQL_PORT", "3306")
    MYSQL_DB = os.getenv("MYSQL_DB", "game_escort_club")
    SQLALCHEMY_DATABASE_URL = (
        f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}?charset=utf8mb4"
    )
    engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_pre_ping=True)
else:
    _SQLITE_FILE = os.path.join(_BACKEND_DIR, "game_club.db").replace("\\", "/")
    SQLALCHEMY_DATABASE_URL = f"sqlite:///{_SQLITE_FILE}"
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# 数据库依赖
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
