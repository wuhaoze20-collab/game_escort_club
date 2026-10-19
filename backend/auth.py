import os
import bcrypt
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from database import get_db
from models import User

# 配置：生产环境务必通过环境变量 SECRET_KEY 覆盖（例如：set SECRET_KEY=随机长字符串）
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
# 令牌有效期不再硬编码于此：统一由 system_config 的 token_expire_minutes 提供（默认 24 小时）

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/login")

# 密码哈希（直接使用bcrypt，避免passlib兼容问题）
def hash_password(password: str) -> str:
    # bcrypt最多支持72字节，自动截断
    password_bytes = password.encode('utf-8')[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password_bytes, salt).decode('utf-8')

# 验证密码
def verify_password(plain_password: str, hashed_password: str) -> bool:
    password_bytes = plain_password.encode('utf-8')[:72]
    return bcrypt.checkpw(password_bytes, hashed_password.encode('utf-8'))

# 生成JWT令牌
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        # 未显式指定时按 system_config 的有效期（默认 24 小时），避免此处再藏一份隐式默认值
        import config_service
        minutes = int(config_service.get_config("token_expire_minutes"))
        expire = datetime.utcnow() + timedelta(minutes=minutes)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# 获取当前登录用户
def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效的登录凭证",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception

    # 封禁状态检查：已登录用户被封禁后，任何请求都踢下线
    now = datetime.utcnow()
    # 用本地时区时间比较
    from datetime import datetime as dt
    now_local = dt.now()
    if user.ban_type == "permanent":
        raise HTTPException(status_code=403, detail="账号已被永久封禁，请重新登录")
    if user.ban_type == "pending_ban":
        if user.ban_until and user.ban_until > now_local:
            remaining = user.ban_until - now_local
            hours = int(remaining.total_seconds() // 3600)
            raise HTTPException(status_code=403,
                              detail=f"账号处于拉黑缓冲期，剩余{hours}小时后将永久封禁，请重新登录")
    if user.ban_type == "temporary":
        if user.ban_until and user.ban_until > now_local:
            remaining = user.ban_until - now_local
            days = int(remaining.total_seconds() // 86400)
            hours = int((remaining.total_seconds() % 86400) // 3600)
            raise HTTPException(status_code=403,
                              detail=f"账号被临时封禁，剩余{days}天{hours}小时，请重新登录")
        else:
            # 临时封禁到期自动解封
            user.ban_type = ""
            user.ban_until = None
            user.ban_reason = ""
            user.ban_requested_at = None
            db.commit()

    return user

# 权限校验：仅允许指定角色访问
def require_roles(*roles):
    def role_checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="无权限访问该资源"
            )
        return current_user
    return role_checker
