import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from database import get_db
from models import BanRequest, BossInfo, PlayerInfo, PlayerTag, User, ContentConfig
from api.notification_api import create_notification
from schemas import (
    BossInfoResponse, PlayerInfoResponse, PlayerPublicInfo,
    IntroUpdateRequest, LevelUpdateRequest, TagCreateRequest, TagResponse,
    TagDecisionRequest, RechargeRequest, ProfileUpdateRequest, ProfileReviewRequest,
    BanRequestCreate, BanDecisionRequest
)
from auth import get_current_user, require_roles
import config_service
import ops_alerts

router = APIRouter(prefix="/api", tags=["用户信息"])

# 技术陪细分等级、违规昵称等已迁入 system_config 表（后台可改），此处不再硬编码。

# 用户默认头像分配（touxiangku 图库仅供系统默认分配，任何人不可选用）
def default_avatar_for(user: User, db: Session = None) -> str:
    if user.role == "admin":
        return "avatar_admin.jpg"
    if user.role == "service":
        return "avatar_service.png"
    if user.role == "boss":
        return "avatar_boss.png"
    # 打手按等级分配
    if db:
        p = db.query(PlayerInfo).filter(PlayerInfo.username == user.username).first()
        if p:
            mapping = {
                "985": "avatar_985_1.jpg", "211": "avatar_211_1.jpg",
                "大专": "avatar_dazhuan.png", "魔王护": "avatar_mowanghu.jpg",
                "明星护": "avatar_mingxing.jpg", "娱乐陪": "avatar_yule.jpg"
            }
            key = p.tech_level or p.level_type or "娱乐陪"
            return mapping.get(key, "avatar_yule.jpg")
    return "avatar_yule.jpg"

# 获取老板列表（仅管理员和客服可查看全部）
@router.get("/boss/list", response_model=List[BossInfoResponse])
def get_boss_list(
    current_user: User = Depends(require_roles("admin", "service")),
    db: Session = Depends(get_db)
):
    bosses = db.query(BossInfo).all()
    result = []
    for b in bosses:
        u = db.query(User).filter(User.username == b.username).first()
        item = {
            "username": b.username,
            "consume_amount": b.consume_amount,
            "balance": b.balance,
            "order_count": b.order_count
        }
        if u:
            item["nickname"] = u.nickname or u.username
            item["avatar"] = u.avatar
        result.append(item)
    return result

# 获取打手列表（仅管理员和客服可查看全部，含后台金额等敏感数据）
@router.get("/player/list", response_model=List[PlayerInfoResponse])
def get_player_list(
    current_user: User = Depends(require_roles("admin", "service")),
    db: Session = Depends(get_db)
):
    players = db.query(PlayerInfo).all()
    result = []
    for p in players:
        u = db.query(User).filter(User.username == p.username).first()
        item = {
            "username": p.username,
            "order_count": p.order_count,
            "complaint_count": p.complaint_count,
            "good_rate": p.good_rate,
            "backend_amount": p.backend_amount,
            "intro": p.intro,
            "level_type": p.level_type,
            "tech_level": p.tech_level
        }
        if u:
            item["nickname"] = u.nickname or u.username
            item["avatar"] = u.avatar
        result.append(item)
    return result

# 获取打手公开列表（所有登录用户可见，供老板点单参考，不含后台金额等敏感信息，含等级与已审核标签）
@router.get("/player/public", response_model=List[PlayerPublicInfo])
def get_player_public_list(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    players = db.query(PlayerInfo).all()
    result = []
    for p in players:
        u = db.query(User).filter(User.username == p.username).first()
        tags = db.query(PlayerTag).filter(
            PlayerTag.username == p.username,
            PlayerTag.status == "approved"
        ).order_by(PlayerTag.id.desc()).all()
        item = {
            "username": p.username,
            "order_count": p.order_count,
            "complaint_count": p.complaint_count,
            "good_rate": p.good_rate,
            "intro": p.intro,
            "level_type": p.level_type,
            "tech_level": p.tech_level,
            "tags": [{"id": t.id, "tag": t.tag} for t in tags]
        }
        if u:
            item["nickname"] = u.nickname or u.username
            item["avatar"] = u.avatar
        result.append(item)
    return result

# 获取当前老板的个人信息
@router.get("/boss/me", response_model=BossInfoResponse)
def get_my_boss_info(
    current_user: User = Depends(require_roles("boss")),
    db: Session = Depends(get_db)
):
    info = db.query(BossInfo).filter(BossInfo.username == current_user.username).first()
    if not info:
        raise HTTPException(status_code=404, detail="用户信息不存在")
    return {
        "username": info.username,
        "nickname": current_user.nickname or current_user.username,
        "avatar": current_user.avatar,
        "consume_amount": info.consume_amount,
        "balance": info.balance,
        "order_count": info.order_count
    }

# 获取当前打手的个人信息
@router.get("/player/me", response_model=PlayerInfoResponse)
def get_my_player_info(
    current_user: User = Depends(require_roles("player")),
    db: Session = Depends(get_db)
):
    info = db.query(PlayerInfo).filter(PlayerInfo.username == current_user.username).first()
    if not info:
        raise HTTPException(status_code=404, detail="用户信息不存在")
    return {
        "username": info.username,
        "nickname": current_user.nickname or current_user.username,
        "avatar": current_user.avatar,
        "order_count": info.order_count,
        "complaint_count": info.complaint_count,
        "good_rate": info.good_rate,
        "backend_amount": info.backend_amount,
        "intro": info.intro,
        "level_type": info.level_type,
        "tech_level": info.tech_level
    }

# ==================== 头像与昵称（所有账户可自定义，管理员/客服审核） ====================

# 提交昵称修改（头像由系统默认分配，任何人不可选用图库头像）
@router.put("/profile")
def update_my_profile(
    request: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # 头像不再支持自定义：touxiangku 图库仅供默认分配
    if request.avatar is not None and request.avatar.strip():
        raise HTTPException(status_code=400, detail="头像由系统默认分配，暂不支持自定义修改")
    
    if request.nickname is not None and request.nickname.strip():
        nick = request.nickname.strip()
        max_nick_len = int(config_service.get_config("nickname_max_len", db))
        if len(nick) > max_nick_len:
            raise HTTPException(status_code=400, detail=f"昵称不能超过{max_nick_len}个字符")
        if nick == config_service.get_config("violation_nickname", db):
            raise HTTPException(status_code=400, detail="该昵称不可用")
        if current_user.nickname_status == "pending":
            raise HTTPException(status_code=400, detail="昵称审核中，请等待管理员审核后再修改")
        if nick != current_user.nickname:
            current_user.pending_nickname = nick
            current_user.nickname_status = "pending"
        else:
            raise HTTPException(status_code=400, detail="新昵称与当前昵称相同")
    else:
        raise HTTPException(status_code=400, detail="没有需要修改的内容，请填写新昵称")

    # 通知管理员与客服有新的资料待审核（头像/昵称审核 admin、service 都有权限，故两者都通知）
    who = current_user.nickname or current_user.username
    for rv in db.query(User).filter(User.role.in_(["admin", "service"])).all():
        create_notification(db, rv.id, "新的头像昵称待审核",
                            f"{current_user.role_name or ''}「{who}」提交了昵称修改"
                            f"（{current_user.nickname or current_user.username} → {current_user.pending_nickname}），"
                            f"请到「头像昵称审核」处理", "warning", "profile-review")

    db.commit()
    return {
        "message": "已提交，等待管理员/客服审核",
        "nickname_status": current_user.nickname_status
    }

# 管理员/客服查看待审核的头像与昵称
@router.get("/profile/review")
def get_profile_review_list(
    current_user: User = Depends(require_roles("admin", "service")),
    db: Session = Depends(get_db)
):
    users = db.query(User).filter(
        (User.nickname_status == "pending") | (User.avatar_status == "pending")
    ).all()
    result = []
    for u in users:
        result.append({
            "username": u.username,
            "role_name": u.role_name,
            "role": u.role,
            "nickname": u.nickname or u.username,
            "avatar": u.avatar,
            "pending_nickname": u.pending_nickname,
            "pending_avatar": u.pending_avatar,
            "nickname_status": u.nickname_status,
            "avatar_status": u.avatar_status
        })
    return result

# 管理员/客服审核头像或昵称（approve=通过生效 / reject=打回；昵称打回改为违规昵称，头像打回恢复默认头像）
@router.post("/profile/review/{username}")
def decide_profile(
    username: str,
    request: ProfileReviewRequest,
    current_user: User = Depends(require_roles("admin", "service")),
    db: Session = Depends(get_db)
):
    if request.field not in ["nickname", "avatar"]:
        raise HTTPException(status_code=400, detail="审核对象必须为 nickname 或 avatar")
    if request.action not in ["approve", "reject"]:
        raise HTTPException(status_code=400, detail="操作必须为 approve 或 reject")
    
    u = db.query(User).filter(User.username == username).first()
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    if request.field == "nickname":
        if u.nickname_status != "pending" or not u.pending_nickname:
            raise HTTPException(status_code=400, detail="该用户没有待审核的昵称")
        if request.action == "approve":
            u.nickname = u.pending_nickname
            u.nickname_status = "approved"
            msg = f"昵称审核通过：{u.nickname}"
        else:
            violation = config_service.get_config("violation_nickname", db)
            u.nickname = violation
            u.nickname_status = "approved"
            u.reject_reason = request.note
            msg = f"昵称不合规，已改为：{violation}"
        u.pending_nickname = ""
    else:
        if u.avatar_status != "pending" or not u.pending_avatar:
            raise HTTPException(status_code=400, detail="该用户没有待审核的头像")
        if request.action == "approve":
            u.avatar = u.pending_avatar
            u.avatar_status = "approved"
            msg = "头像审核通过"
        else:
            u.avatar = default_avatar_for(u, db)
            u.avatar_status = "approved"
            u.reject_reason = request.note
            msg = "头像不合规，已恢复默认头像"
        u.pending_avatar = ""
    
    # 通知用户审核结果
    create_notification(db, u.id, "资料审核结果", msg, "success" if "通过" in msg else "warning", "profile")
    
    db.commit()
    return {"message": msg, "nickname": u.nickname, "avatar": u.avatar}

# 打手更新自己的自我介绍（仅打手本人）
@router.put("/player/intro")
def update_my_intro(
    request: IntroUpdateRequest,
    current_user: User = Depends(require_roles("player")),
    db: Session = Depends(get_db)
):
    info = db.query(PlayerInfo).filter(PlayerInfo.username == current_user.username).first()
    if not info:
        raise HTTPException(status_code=404, detail="用户信息不存在")
    info.intro = request.intro
    db.commit()
    return {"message": "自我介绍已更新", "intro": request.intro}

# 打手更新自己的等级（仅打手本人）
@router.put("/player/level")
def update_my_level(
    request: LevelUpdateRequest,
    current_user: User = Depends(require_roles("player")),
    db: Session = Depends(get_db)
):
    all_level_types = config_service.level_types(db)
    tech_levels = config_service.tech_levels(db)
    if request.level_type not in all_level_types:
        raise HTTPException(status_code=400, detail=f"等级大类必须为：{' / '.join(all_level_types)}")
    tech_level = ""
    if request.level_type == "技术陪":
        if request.tech_level not in tech_levels:
            raise HTTPException(status_code=400, detail=f"技术陪细分等级必须为：{'/'.join(tech_levels)}")
        tech_level = request.tech_level
    info = db.query(PlayerInfo).filter(PlayerInfo.username == current_user.username).first()
    if not info:
        raise HTTPException(status_code=404, detail="用户信息不存在")
    info.level_type = request.level_type
    info.tech_level = tech_level
    db.commit()
    return {"message": "等级已更新", "level_type": request.level_type, "tech_level": tech_level}

# 打手查看自己的标签（含审核状态）
@router.get("/player/tags", response_model=List[TagResponse])
def get_my_tags(
    current_user: User = Depends(require_roles("player")),
    db: Session = Depends(get_db)
):
    return db.query(PlayerTag).filter(
        PlayerTag.username == current_user.username
    ).order_by(PlayerTag.id.desc()).all()

# 打手添加标签（提交审核）
@router.post("/player/tags", response_model=TagResponse)
def add_my_tag(
    request: TagCreateRequest,
    current_user: User = Depends(require_roles("player")),
    db: Session = Depends(get_db)
):
    tag = request.tag.strip()
    if not tag:
        raise HTTPException(status_code=400, detail="标签内容不能为空")
    if len(tag) > 20:
        raise HTTPException(status_code=400, detail=f"标签不能超过{int(config_service.get_config('tag_max_len', db))}个字符")
    # 限制待审核标签数量，防止刷屏
    pending_count = db.query(PlayerTag).filter(
        PlayerTag.username == current_user.username,
        PlayerTag.status == "pending"
    ).count()
    if pending_count >= 5:
        raise HTTPException(status_code=400, detail="待审核标签过多，请等待管理员审核后再添加")
    # 去重（同内容已存在则拒绝）
    exists = db.query(PlayerTag).filter(
        PlayerTag.username == current_user.username,
        PlayerTag.tag == tag
    ).first()
    if exists:
        raise HTTPException(status_code=400, detail="该标签已存在")
    t = PlayerTag(username=current_user.username, tag=tag, status="pending")
    db.add(t)

    # 通知管理员与客服有新的标签待审核（标签审核 admin、service 都有权限）
    who = current_user.nickname or current_user.username
    for rv in db.query(User).filter(User.role.in_(["admin", "service"])).all():
        create_notification(db, rv.id, "新的标签待审核",
                            f"打手「{who}」提交了标签「{tag}」，请到「标签审核」处理",
                            "warning", "tag-review")

    db.commit()
    db.refresh(t)
    return t

# 打手删除自己的标签
@router.delete("/player/tags/{tag_id}")
def delete_my_tag(
    tag_id: int,
    current_user: User = Depends(require_roles("player")),
    db: Session = Depends(get_db)
):
    t = db.query(PlayerTag).filter(PlayerTag.id == tag_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="标签不存在")
    if t.username != current_user.username:
        raise HTTPException(status_code=403, detail="只能删除自己的标签")
    db.delete(t)
    db.commit()
    return {"message": "标签已删除"}

# 管理员/客服查看标签审核列表（默认待审核，可传status=all查看全部）
@router.get("/player/tags/review", response_model=List[TagResponse])
def get_tag_review_list(
    status: str = "pending",
    current_user: User = Depends(require_roles("admin", "service")),
    db: Session = Depends(get_db)
):
    query = db.query(PlayerTag)
    if status != "all":
        query = query.filter(PlayerTag.status == status)
    return query.order_by(PlayerTag.id.desc()).all()

# 管理员/客服审核标签（approve=通过展示 / reject=拒绝）
@router.post("/player/tags/{tag_id}/decision")
def decide_tag(
    tag_id: int,
    request: TagDecisionRequest,
    current_user: User = Depends(require_roles("admin", "service")),
    db: Session = Depends(get_db)
):
    if request.action not in ["approve", "reject"]:
        raise HTTPException(status_code=400, detail="操作必须为 approve 或 reject")
    t = db.query(PlayerTag).filter(PlayerTag.id == tag_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="标签不存在")
    if t.status != "pending":
        raise HTTPException(status_code=400, detail="该标签已审核过")
    t.status = "approved" if request.action == "approve" else "rejected"
    t.note = request.note
    t.processed_at = datetime.now()
    
    # 通知打手标签审核结果
    p_user = db.query(User).filter(User.username == t.username).first()
    if p_user:
        if t.status == "approved":
            create_notification(db, p_user.id, "标签审核通过", f"您的标签「{t.tag}」已通过审核，将对外展示", "success", "profile")
        else:
            create_notification(db, p_user.id, "标签被驳回", f"您的标签「{t.tag}」未通过审核（{request.note or '未说明原因'}）", "warning", "profile")
    db.commit()
    db.refresh(t)
    return {"message": "已通过" if t.status == "approved" else "已拒绝", "tag": t.tag, "status": t.status}

# 老板充值（大狗币 1:1，按充值福利档位赠送，选择支付方式）
@router.post("/boss/recharge")
def recharge_balance(
    request: RechargeRequest,
    current_user: User = Depends(require_roles("boss")),
    db: Session = Depends(get_db)
):
    if request.amount <= 0:
        raise HTTPException(status_code=400, detail="充值金额必须大于0")
    recharge_max = int(config_service.get_config("recharge_max_amount", db))
    if request.amount > recharge_max:
        raise HTTPException(status_code=400, detail=f"单次充值金额不能超过{recharge_max / 100:g}元")
    if not request.payment.strip():
        raise HTTPException(status_code=400, detail="请选择支付方式")
    
    boss = db.query(BossInfo).filter(BossInfo.username == current_user.username).first()
    if not boss:
        raise HTTPException(status_code=404, detail="老板账户不存在")
    
    # 从充值福利配置中匹配赠送（精确匹配档位金额；未匹配到档位则无赠送，这是允许的）
    gift = 0
    bonus = ""
    cfg = db.query(ContentConfig).filter(ContentConfig.config_key == "recharge").first()
    if cfg:
        try:
            recharge_list = json.loads(cfg.config_value)
            if not isinstance(recharge_list, list):
                raise ValueError("充值福利配置不是数组")
        except Exception as e:
            # 配置坏了必须**显式失败**，不能静默按 0 赠送：
            # 否则用户照常扣款却拿不到该有的赠送，而且没有任何人会发现配置坏了。
            ops_alerts.record(
                "recharge_config_broken",
                f"「充值福利」配置无法解析（{e}），已暂停充值以免少给赠送。"
                f"请到「充值福利」页检查配置格式"
            )
            print(f"[recharge] 「充值福利」配置解析失败，已拒绝本次充值：{e}")
            raise HTTPException(
                status_code=500,
                detail="充值福利配置异常，为避免让你少拿赠送已暂停充值，请联系管理员检查「充值福利」配置",
            )

        for item in recharge_list:
            if not isinstance(item, dict):
                continue
            if item.get("amount") == request.amount:
                try:
                    gift = int(item.get("gift") or 0)
                except (TypeError, ValueError):
                    # 单个档位的赠送值写坏了：这一项按 0 处理并留痕，但不阻断充值
                    ops_alerts.record(
                        f"recharge_gift_bad:{request.amount}",
                        f"「充值福利」中 {request.amount} 元档位的赠送值不是整数，本次按 0 赠送处理",
                    )
                    gift = 0
                bonus = item.get("bonus") or ""
                break
    
    total = request.amount + gift
    boss.balance += total
    
    db.commit()
    return {
        "message": f"充值成功！到账 {total} 大狗币（充值{request.amount} + 赠送{gift}）",
        "recharge_amount": request.amount,
        "gift": gift,
        "bonus": bonus,
        "total": total,
        "payment": request.payment,
        "balance": boss.balance
    }


# ——————————————————————————————————————————————
# 封禁/拉黑核心逻辑
# ——————————————————————————————————————————————

def _do_final_ban(db: Session, user: User, *, operator_display: str, reason: str) -> int:
    """最终执行永久拉黑（不可逆）：余额转公司账户、写处罚通告、账号注销。
    24小时缓冲期到了自动调用，或管理员手动立即执行时调用。
    """
    username = user.username
    amount = 0
    role_name = "老板" if user.role == "boss" else "打手"
    display = user.nickname or username

    # 余额转入公司账户
    if user.role == "player":
        player = db.query(PlayerInfo).filter(PlayerInfo.username == username).first()
        if player:
            amount = int(round(player.backend_amount or 0))
            player.backend_amount = 0
    elif user.role == "boss":
        boss = db.query(BossInfo).filter(BossInfo.username == username).first()
        if boss:
            amount = int((boss.balance or 0) * 100)
            boss.balance = 0

    if amount > 0:
        cb = db.query(ContentConfig).filter(ContentConfig.config_key == "company_balance").first()
        if not cb:
            cb = ContentConfig(config_key="company_balance", config_value=json.dumps({"balance": 0}))
            db.add(cb)
        cfg = json.loads(cb.config_value or '{"balance": 0}')
        cfg["balance"] = cfg.get("balance", 0) + amount
        cb.config_value = json.dumps(cfg, ensure_ascii=False)

        rec = db.query(ContentConfig).filter(ContentConfig.config_key == "company_records").first()
        if not rec:
            rec = ContentConfig(config_key="company_records", config_value="[]")
            db.add(rec)
        records = json.loads(rec.config_value or "[]")
        records.insert(0, {"date": datetime.now().strftime("%Y-%m-%d %H:%M"), "type": "永久拉黑",
                           "user": f"{display}（{username}）", "amount": amount})
        rec.config_value = json.dumps(records, ensure_ascii=False)

    money_desc = (f"{('后台金额' if user.role == 'player' else '账户余额')} ¥{amount / 100:.2f} 已转入公司账户"
                  if amount > 0 else "账号已永久注销")
    head = f"{role_name}「{display}」被{operator_display}永久拉黑封禁"
    if reason:
        head += f"，原因：{reason}"

    # 处罚公告
    pun = db.query(ContentConfig).filter(ContentConfig.config_key == "punishment").first()
    if pun:
        plist = json.loads(pun.config_value or "[]")
        plist.insert(0, {"level": "永久封禁", "desc": f"{head}，{money_desc}",
                         "date": datetime.now().strftime("%Y-%m-%d")})
        pun.config_value = json.dumps(plist, ensure_ascii=False)

    from api.notification_api import create_notification
    create_notification(db, user.id, "账号被永久封禁",
                        "您的账号已被永久拉黑注销，如有疑问请联系管理员", "warning", "")

    try:
        from kg import sync as kg_sync
        kg_sync.sync_punishments(db)
    except Exception as e:
        print(f"[kg] 处罚通告入图失败：{type(e).__name__}: {e}")

    user.account_status = "rejected"
    user.ban_type = "permanent"
    user.ban_until = None
    user.ban_reason = reason
    return amount


# 临时封禁
@router.post("/admin/temp-ban/{username}")
def temp_ban_user(
    username: str,
    days: int = 1,
    reason: str = "",
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db)
):
    """临时封禁账号：可选 1/3/7/30 天/永久(传0或-1)。封禁后立刻踢下线。"""
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.role not in ["boss", "player"]:
        raise HTTPException(status_code=400, detail="只能封禁老板或打手账号")

    from datetime import timedelta
    now = datetime.now()
    display = user.nickname or username
    role_name = "老板" if user.role == "boss" else "打手"

    if days <= 0:
        # 永久封禁（直接执行，不走缓冲期）
        _do_final_ban(db, user, operator_display=current_user.nickname or current_user.username, reason=reason)
        db.commit()
        return {"message": f"用户 {username} 已被永久封禁"}

    ban_until = now + timedelta(days=days)
    user.ban_type = "temporary"
    user.ban_until = ban_until
    user.ban_reason = reason
    user.ban_requested_at = now

    # 处罚公告
    pun = db.query(ContentConfig).filter(ContentConfig.config_key == "punishment").first()
    if pun:
        plist = json.loads(pun.config_value or "[]")
        plist.insert(0, {"level": f"临时封禁{days}天",
                         "desc": f"{role_name}「{display}」被{current_user.nickname or current_user.username}临时封禁{days}天"
                                 f"（至 {ban_until.strftime('%Y-%m-%d %H:%M')}），原因：{reason or '违规'}",
                         "date": datetime.now().strftime("%Y-%m-%d")})
        pun.config_value = json.dumps(plist, ensure_ascii=False)

    from api.notification_api import create_notification
    create_notification(db, user.id, f"账号被临时封禁{days}天",
                        f"您的账号因「{reason or '违规'}」被临时封禁{days}天，"
                        f"将于 {ban_until.strftime('%Y-%m-%d %H:%M')} 自动解封", "warning", "")

    try:
        from kg import sync as kg_sync
        kg_sync.sync_punishments(db)
    except Exception as e:
        print(f"[kg] 处罚通告入图失败：{type(e).__name__}: {e}")

    db.commit()
    return {"message": f"用户 {username} 已被临时封禁{days}天，至 {ban_until.strftime('%Y-%m-%d %H:%M')}",
            "ban_until": ban_until.isoformat()}


# 解除封禁/解封
@router.post("/admin/unban/{username}")
def unban_user(
    username: str,
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db)
):
    """解除临时封禁或取消拉黑缓冲期，恢复账号正常使用。"""
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if not user.ban_type:
        raise HTTPException(status_code=400, detail="该账号未被封禁，无需解封")
    if user.ban_type == "permanent":
        raise HTTPException(status_code=400, detail="永久封禁账号不可解封，请直接重新注册")

    display = user.nickname or username
    role_name = "老板" if user.role == "boss" else "打手"
    ban_desc = "临时封禁" if user.ban_type == "temporary" else "拉黑缓冲期"

    # 处罚公告记录解封
    pun = db.query(ContentConfig).filter(ContentConfig.config_key == "punishment").first()
    if pun:
        plist = json.loads(pun.config_value or "[]")
        plist.insert(0, {"level": "解除封禁",
                         "desc": f"{role_name}「{display}」的{ban_desc}已被管理员解除，账号恢复正常使用",
                         "date": datetime.now().strftime("%Y-%m-%d")})
        pun.config_value = json.dumps(plist, ensure_ascii=False)

    from api.notification_api import create_notification
    create_notification(db, user.id, "账号已解封",
                        f"您的{ban_desc}已解除，账号恢复正常使用", "success", "")

    user.ban_type = ""
    user.ban_until = None
    user.ban_reason = ""
    user.ban_requested_at = None
    if user.account_status == "rejected" and user.ban_type != "permanent":
        user.account_status = "approved"

    db.commit()
    return {"message": f"用户 {username} 已解除封禁，账号恢复正常"}


# 管理员发起拉黑（进入24小时缓冲期，期间可解除，也可立即执行）
@router.post("/admin/ban/{username}")
def ban_user(
    username: str,
    reason: str = "",
    immediate: bool = False,
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db)
):
    """发起拉黑：默认进入24小时缓冲期；immediate=True 立即执行永久拉黑。"""
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.role not in ["boss", "player"]:
        raise HTTPException(status_code=400, detail="只能拉黑老板或打手账号")

    if immediate:
        amount = _do_final_ban(db, user, operator_display=current_user.nickname or current_user.username, reason=reason)
        db.commit()
        return {"message": f"用户 {username} 已被永久拉黑，¥{amount / 100:.2f} 已转入公司账户"}

    # 进入24小时缓冲期
    from datetime import timedelta
    now = datetime.now()
    deadline = now + timedelta(hours=24)
    user.ban_type = "pending_ban"
    user.ban_until = deadline
    user.ban_reason = reason
    user.ban_requested_at = now

    display = user.nickname or username
    role_name = "老板" if user.role == "boss" else "打手"

    pun = db.query(ContentConfig).filter(ContentConfig.config_key == "punishment").first()
    if pun:
        plist = json.loads(pun.config_value or "[]")
        plist.insert(0, {"level": "拉黑缓冲期",
                         "desc": f"{role_name}「{display}」被{current_user.nickname or current_user.username}发起拉黑，"
                                 f"24小时缓冲期内（至 {deadline.strftime('%Y-%m-%d %H:%M')}）可解除或立即执行",
                         "date": datetime.now().strftime("%Y-%m-%d")})
        pun.config_value = json.dumps(plist, ensure_ascii=False)

    from api.notification_api import create_notification
    create_notification(db, user.id, "账号进入拉黑缓冲期",
                        f"您的账号因「{reason or '违规'}」被发起拉黑，24小时内可申诉解除，"
                        f"逾期未解除将永久封禁", "warning", "")

    db.commit()
    return {"message": f"已发起拉黑，进入24小时缓冲期（至 {deadline.strftime('%Y-%m-%d %H:%M')}），期间可解除或立即执行",
            "ban_until": deadline.isoformat()}


# ——————————————————————————————————————————————
# 拉黑申请：客服发起、管理员审核
# ——————————————————————————————————————————————

# 客服提交拉黑申请（不会立即生效，等管理员审核）
@router.post("/ban/request")
def create_ban_request(
    request: BanRequestCreate,
    current_user: User = Depends(require_roles("service")),
    db: Session = Depends(get_db)
):
    username = (request.username or "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="请指定要拉黑的账号")

    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.role not in ["boss", "player"]:
        raise HTTPException(status_code=400, detail="只能拉黑老板或打手账号")

    # 同一账号不允许多条待审申请，避免刷单
    dup = db.query(BanRequest).filter(BanRequest.target_username == username,
                                      BanRequest.status == "pending").first()
    if dup:
        raise HTTPException(status_code=400,
                            detail=f"该账号已有待审核的拉黑申请（申请人：{dup.requested_by}），请等待管理员处理")

    br = BanRequest(
        target_username=username,
        target_role=user.role,
        requested_by=current_user.username,
        reason=(request.reason or "").strip()[:500],
    )
    db.add(br)

    # 通知管理员有新申请
    from api.notification_api import create_notification
    for admin in db.query(User).filter(User.role == "admin").all():
        create_notification(db, admin.id, "新的拉黑申请",
                            f"客服 {current_user.username} 申请拉黑"
                            f"{'老板' if user.role == 'boss' else '打手'}「{user.nickname or username}」，"
                            f"请到「拉黑审核」处理", "warning", "ban-review")

    db.commit()
    db.refresh(br)
    return {"message": "已提交拉黑申请，等待管理员审核", "id": br.id}


# 拉黑申请列表（管理员/客服都可看；客服用于跟踪自己申请的状态）
@router.get("/ban/requests")
def list_ban_requests(
    current_user: User = Depends(require_roles("admin", "service")),
    db: Session = Depends(get_db)
):
    rows = db.query(BanRequest).order_by(BanRequest.id.desc()).limit(100).all()
    result = []
    for r in rows:
        target = db.query(User).filter(User.username == r.target_username).first()
        result.append({
            "id": r.id,
            "target_username": r.target_username,
            "target_role": "老板" if r.target_role == "boss" else "打手",
            "target_nickname": (target.nickname or r.target_username) if target else r.target_username,
            "requested_by": r.requested_by,
            "reason": r.reason,
            "status": r.status,
            "note": r.note,
            "processed_by": r.processed_by,
            "created_at": r.created_at,
            "processed_at": r.processed_at,
        })
    return result


# 管理员审核：通过则执行拉黑（不可逆），驳回则仅记录
@router.post("/ban/requests/{request_id}/decision")
def decide_ban_request(
    request_id: int,
    request: BanDecisionRequest,
    action: str = "approve",  # approve / reject
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db)
):
    br = db.query(BanRequest).filter(BanRequest.id == request_id).first()
    if not br:
        raise HTTPException(status_code=404, detail="申请不存在")
    if br.status != "pending":
        raise HTTPException(status_code=400, detail="该申请已处理")

    if action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="无效的操作")

    from api.notification_api import create_notification

    if action == "reject":
        br.status = "rejected"
        br.note = request.note or ""
        br.processed_by = current_user.username
        br.processed_at = datetime.now()
        # 通知申请人
        requester = db.query(User).filter(User.username == br.requested_by).first()
        if requester:
            create_notification(db, requester.id, "拉黑申请被驳回",
                                f"你申请的拉黑「{br.target_username}」已被驳回"
                                f"{('：' + request.note) if request.note else ''}", "info", "ban-review")
        db.commit()
        return {"message": "已驳回该拉黑申请（未执行拉黑）"}

    # 通过：进入24小时缓冲期
    target = db.query(User).filter(User.username == br.target_username).first()
    if not target:
        raise HTTPException(status_code=404, detail="被申请拉黑的账号已不存在")

    from datetime import timedelta
    now = datetime.now()
    deadline = now + timedelta(hours=24)
    target.ban_type = "pending_ban"
    target.ban_until = deadline
    target.ban_reason = br.reason
    target.ban_requested_at = now

    display = target.nickname or br.target_username
    role_name = "老板" if target.role == "boss" else "打手"
    pun = db.query(ContentConfig).filter(ContentConfig.config_key == "punishment").first()
    if pun:
        plist = json.loads(pun.config_value or "[]")
        plist.insert(0, {"level": "拉黑缓冲期",
                         "desc": f"{role_name}「{display}」经客服申请、管理员审核通过进入拉黑缓冲期，"
                                 f"24小时内（至 {deadline.strftime('%Y-%m-%d %H:%M')}）可解除或立即执行",
                         "date": datetime.now().strftime("%Y-%m-%d")})
        pun.config_value = json.dumps(plist, ensure_ascii=False)

    from api.notification_api import create_notification
    create_notification(db, target.id, "账号进入拉黑缓冲期",
                        f"您的账号因「{br.reason}」被客服申请拉黑、管理员审核通过，"
                        f"24小时缓冲期内可申诉解除，逾期将永久封禁", "warning", "")

    br.status = "approved"
    br.note = request.note or ""
    br.processed_by = current_user.username
    br.processed_at = datetime.now()

    requester = db.query(User).filter(User.username == br.requested_by).first()
    if requester:
        create_notification(db, requester.id, "拉黑申请已通过",
                            f"你申请的拉黑「{br.target_username}」已由管理员审核通过，进入24小时缓冲期", "success", "ban-review")
    db.commit()
    return {"message": f"已通过审核，进入24小时拉黑缓冲期（至 {deadline.strftime('%Y-%m-%d %H:%M')}），期间可解除或立即执行"}


# 公司后台余额与资金流水（仅管理员）
@router.get("/admin/company-balance")
def get_company_balance(
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db)
):
    cb = db.query(ContentConfig).filter(ContentConfig.config_key == "company_balance").first()
    rec = db.query(ContentConfig).filter(ContentConfig.config_key == "company_records").first()
    balance = json.loads(cb.config_value).get("balance", 0) if cb else 0
    records = json.loads(rec.config_value) if rec else []
    return {"balance": balance, "records": records}
