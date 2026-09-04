from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from database import get_db
from models import BossInfo, PlayerInfo, User
from schemas import BossInfoResponse, PlayerInfoResponse
from auth import get_current_user, require_roles

router = APIRouter(prefix="/api", tags=["用户信息"])

# 获取老板列表（仅管理员和客服可查看全部）
@router.get("/boss/list", response_model=List[BossInfoResponse])
def get_boss_list(
    current_user: User = Depends(require_roles("admin", "service")),
    db: Session = Depends(get_db)
):
    return db.query(BossInfo).all()

# 获取打手列表（仅管理员和客服可查看全部）
@router.get("/player/list", response_model=List[PlayerInfoResponse])
def get_player_list(
    current_user: User = Depends(require_roles("admin", "service")),
    db: Session = Depends(get_db)
):
    return db.query(PlayerInfo).all()

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
