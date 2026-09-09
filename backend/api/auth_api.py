from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from database import get_db
from models import User
from schemas import LoginRequest, LoginResponse, ResetPasswordRequest, ChangePasswordRequest
from auth import verify_password, hash_password, create_access_token, get_current_user, ACCESS_TOKEN_EXPIRE_MINUTES

router = APIRouter(prefix="/api", tags=["认证"])

# 登录锁定配置：连续输错 5 次锁定 10 分钟
MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 10


@router.post("/login", response_model=LoginResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    # 查找用户
    user = db.query(User).filter(User.username == request.username.strip()).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="账号或密码错误"
        )

    now = datetime.now()

    # 锁定检查：若账户处于锁定期，直接拒绝
    if user.lock_until and user.lock_until > now:
        remaining_min = int((user.lock_until - now).total_seconds() // 60) + 1
        raise HTTPException(
            status_code=423,
            detail=f"密码错误次数过多，账户已锁定，请 {remaining_min} 分钟后重试"
        )

    # 验证密码
    if not verify_password(request.password, user.password_hash):
        user.failed_attempts = (user.failed_attempts or 0) + 1
        if user.failed_attempts >= MAX_FAILED_ATTEMPTS:
            # 达到上限：锁定 10 分钟并重置计数
            user.lock_until = now + timedelta(minutes=LOCK_MINUTES)
            user.failed_attempts = 0
            db.commit()
            raise HTTPException(
                status_code=423,
                detail=f"密码连续错误 {MAX_FAILED_ATTEMPTS} 次，账户已锁定 {LOCK_MINUTES} 分钟，请稍后再试"
            )
        db.commit()
        remaining = MAX_FAILED_ATTEMPTS - user.failed_attempts
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"账号或密码错误，还可尝试 {remaining} 次"
        )

    # 登录成功：重置失败计数与锁定状态
    if user.failed_attempts or user.lock_until:
        user.failed_attempts = 0
        user.lock_until = None
        db.commit()

    # 生成令牌
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username, "role": user.role},
        expires_delta=access_token_expires
    )

    return LoginResponse(
        access_token=access_token,
        user={
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "role_name": user.role_name,
            "nickname": user.nickname or user.username,
            "avatar": user.avatar
        }
    )


# 忘记密码：通过账号直接重置密码（演示环境做法；生产环境应接入短信/邮箱验证码）
@router.post("/reset-password")
def reset_password(request: ResetPasswordRequest, db: Session = Depends(get_db)):
    username = request.username.strip()
    new_password = request.new_password.strip()
    if not username:
        raise HTTPException(status_code=400, detail="请输入账号")
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码长度不能少于 6 位")

    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="账号不存在")

    user.password_hash = hash_password(new_password)
    user.failed_attempts = 0
    user.lock_until = None
    db.commit()
    return {"message": "密码重置成功，请使用新密码登录"}


# 修改密码：需登录，校验原密码
@router.post("/change-password")
def change_password(
    request: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    old_password = request.old_password
    new_password = request.new_password.strip()
    if not old_password:
        raise HTTPException(status_code=400, detail="请输入原密码")
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码长度不能少于 6 位")
    if new_password == old_password:
        raise HTTPException(status_code=400, detail="新密码不能与原密码相同")
    if not verify_password(old_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="原密码错误")

    current_user.password_hash = hash_password(new_password)
    db.commit()
    return {"message": "密码修改成功，下次登录请使用新密码"}
