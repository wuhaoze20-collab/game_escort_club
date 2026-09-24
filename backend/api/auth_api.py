from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from database import get_db
from models import User, BossInfo, PlayerInfo
from schemas import LoginRequest, LoginResponse, ResetPasswordRequest, ChangePasswordRequest, RegisterRequest, RegistrationDecisionRequest
from auth import verify_password, hash_password, create_access_token, get_current_user, require_roles
from api.notification_api import create_notification
import config_service

router = APIRouter(prefix="/api", tags=["认证"])


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

    # 登录锁定策略取自 system_config（默认：连续 5 次锁定 10 分钟）
    max_attempts = config_service.login_max_failed_attempts(db)
    lock_minutes = config_service.login_lock_minutes(db)

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
        if user.failed_attempts >= max_attempts:
            # 达到上限：按配置锁定并重置计数
            user.lock_until = now + timedelta(minutes=lock_minutes)
            user.failed_attempts = 0
            db.commit()
            raise HTTPException(
                status_code=423,
                detail=f"密码连续错误 {max_attempts} 次，账户已锁定 {lock_minutes} 分钟，请稍后再试"
            )
        db.commit()
        remaining = max_attempts - user.failed_attempts
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"账号或密码错误，还可尝试 {remaining} 次"
        )

    # 登录成功：重置失败计数与锁定状态
    if user.failed_attempts or user.lock_until:
        user.failed_attempts = 0
        user.lock_until = None
        db.commit()

    # 注册审核状态检查
    if user.account_status == "pending":
        raise HTTPException(
            status_code=403,
            detail="账号审核中，请等待管理员审核通过后登录"
        )
    if user.account_status == "rejected":
        raise HTTPException(
            status_code=403,
            detail="账号审核未通过，无法登录"
        )

    # 生成令牌（有效期取自 system_config，默认 24 小时）
    token_minutes = int(config_service.get_config("token_expire_minutes", db))
    access_token_expires = timedelta(minutes=token_minutes)
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


# ============ 注册功能 ============
# 老板注册直接生效；打手/客服注册需管理员审核通过后才能登录
ROLE_NAMES = {"boss": "老板", "player": "打手", "service": "客服"}
ROLE_AVATARS = {"boss": "avatar_boss.png", "player": "avatar_yule.jpg", "service": "avatar_service.png"}
# 技术陪等级列表已迁入 system_config（tech_levels），此处不再重复定义


@router.post("/register")
def register(request: RegisterRequest, db: Session = Depends(get_db)):
    username = request.username.strip()
    password = request.password
    role = request.role.strip().lower()
    if not username:
        raise HTTPException(status_code=400, detail="请输入账号")
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="账号长度不能少于 3 位")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="密码长度不能少于 6 位")
    if role not in ROLE_NAMES:
        raise HTTPException(status_code=400, detail="无效的注册角色")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=400, detail="该账号已被注册")

    nickname = request.nickname.strip() or username
    avatar = ROLE_AVATARS[role]
    needs_review = role in ("player", "service")

    # 打手等级校验（等级列表取自 system_config，与「我的账户」修改等级使用同一份数据）
    if role == "player":
        level_type = request.level_type.strip() or "娱乐陪"
        tech_level = request.tech_level.strip()
        if level_type == "技术陪" and tech_level not in config_service.tech_levels(db):
            raise HTTPException(
                status_code=400,
                detail=f"技术陪等级须为：{' / '.join(config_service.tech_levels(db))}"
            )

    user = User(
        username=username,
        password_hash=hash_password(password),
        role=role,
        role_name=ROLE_NAMES[role],
        nickname=nickname,
        avatar=avatar,
        account_status="pending" if needs_review else "approved",
    )
    db.add(user)
    db.flush()

    if role == "boss":
        db.add(BossInfo(username=username))
    elif role == "player":
        db.add(PlayerInfo(
            username=username,
            intro=request.intro.strip(),
            level_type=level_type,
            tech_level=tech_level if level_type == "技术陪" else "",
        ))
    db.commit()

    if needs_review:
        # 通知管理员有新的注册待审核
        for au in db.query(User).filter(User.role == "admin").all():
            create_notification(db, au.id, "新注册待审核", f"新用户 {username}（{ROLE_NAMES[role]}）提交了注册申请，请及时审核", "info", "/register")
        return {"message": "注册成功！账号已提交审核，请等待管理员审核通过后登录", "status": "pending"}
    return {"message": "注册成功！请使用新账号登录", "status": "approved"}


# 注册审核列表（仅管理员）
@router.get("/admin/registration-list")
def registration_list(
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db)
):
    users = db.query(User).filter(User.account_status == "pending").order_by(User.created_at.desc()).all()
    result = []
    for u in users:
        item = {
            "id": u.id, "username": u.username, "role": u.role, "role_name": u.role_name,
            "nickname": u.nickname, "avatar": u.avatar, "created_at": u.created_at,
        }
        if u.role == "player":
            pi = db.query(PlayerInfo).filter(PlayerInfo.username == u.username).first()
            item["intro"] = pi.intro if pi else ""
            item["level_type"] = pi.level_type if pi else "娱乐陪"
            item["tech_level"] = pi.tech_level if pi else ""
        result.append(item)
    return result


# 注册审核决策（仅管理员）：approve=通过 / reject=驳回
@router.post("/admin/registration-decision")
def registration_decision(
    request: RegistrationDecisionRequest,
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db)
):
    if request.action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="无效的操作类型")
    user = db.query(User).filter(User.id == request.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.account_status != "pending":
        raise HTTPException(status_code=400, detail="该账号不在审核中")
    if request.action == "approve":
        user.account_status = "approved"
        msg = f"已通过 {user.username} 的注册审核"
    else:
        user.account_status = "rejected"
        msg = f"已驳回 {user.username} 的注册申请"
    
    # 通知用户审核结果
    if request.action == "approve":
        create_notification(db, user.id, "注册审核通过", "恭喜！您的账号已通过审核，现在可以登录了", "success", "/")
    else:
        create_notification(db, user.id, "注册被驳回", f"您的注册申请未通过审核（{request.note or '未说明原因'}），如有疑问请联系管理员", "warning", "/")
    db.commit()
    return {"message": msg}


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
