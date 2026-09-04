import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from database import get_db
from models import BossInfo, PlayerInfo, PlayerTag, User, ContentConfig
from schemas import (
    BossInfoResponse, PlayerInfoResponse, PlayerPublicInfo,
    IntroUpdateRequest, LevelUpdateRequest, TagCreateRequest, TagResponse,
    TagDecisionRequest, RechargeRequest
)
from auth import get_current_user, require_roles

router = APIRouter(prefix="/api", tags=["用户信息"])

# 技术陪细分等级（由低到高）
TECH_LEVELS = ["985", "211", "大专", "魔王护", "明星护"]

# 获取老板列表（仅管理员和客服可查看全部）
@router.get("/boss/list", response_model=List[BossInfoResponse])
def get_boss_list(
    current_user: User = Depends(require_roles("admin", "service")),
    db: Session = Depends(get_db)
):
    return db.query(BossInfo).all()

# 获取打手列表（仅管理员和客服可查看全部，含后台金额等敏感数据）
@router.get("/player/list", response_model=List[PlayerInfoResponse])
def get_player_list(
    current_user: User = Depends(require_roles("admin", "service")),
    db: Session = Depends(get_db)
):
    return db.query(PlayerInfo).all()

# 获取打手公开列表（所有登录用户可见，供老板点单参考，不含后台金额等敏感信息，含等级与已审核标签）
@router.get("/player/public", response_model=List[PlayerPublicInfo])
def get_player_public_list(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    players = db.query(PlayerInfo).all()
    result = []
    for p in players:
        tags = db.query(PlayerTag).filter(
            PlayerTag.username == p.username,
            PlayerTag.status == "approved"
        ).order_by(PlayerTag.id.desc()).all()
        result.append({
            "username": p.username,
            "order_count": p.order_count,
            "complaint_count": p.complaint_count,
            "good_rate": p.good_rate,
            "intro": p.intro,
            "level_type": p.level_type,
            "tech_level": p.tech_level,
            "tags": [{"id": t.id, "tag": t.tag} for t in tags]
        })
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
    return info

# 获取当前打手的个人信息
@router.get("/player/me", response_model=PlayerInfoResponse)
def get_my_player_info(
    current_user: User = Depends(require_roles("player")),
    db: Session = Depends(get_db)
):
    info = db.query(PlayerInfo).filter(PlayerInfo.username == current_user.username).first()
    if not info:
        raise HTTPException(status_code=404, detail="用户信息不存在")
    return info

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
    if request.level_type not in ["娱乐陪", "技术陪"]:
        raise HTTPException(status_code=400, detail="等级大类必须为：娱乐陪 或 技术陪")
    tech_level = ""
    if request.level_type == "技术陪":
        if request.tech_level not in TECH_LEVELS:
            raise HTTPException(status_code=400, detail=f"技术陪细分等级必须为：{'/'.join(TECH_LEVELS)}")
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
        raise HTTPException(status_code=400, detail="标签不能超过20个字符")
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
    if request.amount > 100000:
        raise HTTPException(status_code=400, detail="单次充值金额不能超过10万元")
    if not request.payment.strip():
        raise HTTPException(status_code=400, detail="请选择支付方式")
    
    boss = db.query(BossInfo).filter(BossInfo.username == current_user.username).first()
    if not boss:
        raise HTTPException(status_code=404, detail="老板账户不存在")
    
    # 从充值福利配置中匹配赠送（精确匹配档位金额，未匹配则无赠送）
    gift = 0
    bonus = ""
    cfg = db.query(ContentConfig).filter(ContentConfig.config_key == "recharge").first()
    if cfg:
        try:
            recharge_list = json.loads(cfg.config_value)
            for item in recharge_list:
                if item.get("amount") == request.amount:
                    gift = int(item.get("gift", 0))
                    bonus = item.get("bonus", "")
                    break
        except Exception:
            pass
    
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
