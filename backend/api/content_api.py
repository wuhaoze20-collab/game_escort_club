import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import ContentConfig, User
from schemas import ContentConfigUpdate
from auth import get_current_user, require_roles

router = APIRouter(prefix="/api/content", tags=["内容管理"])

# 允许的配置key
VALID_CONFIG_KEYS = ["notice", "orderGuide", "price", "recharge", "member", "payment"]

# 获取所有内容配置（所有登录用户可查看）
@router.get("/all")
def get_all_content(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    result = {}
    for key in VALID_CONFIG_KEYS:
        config = db.query(ContentConfig).filter(ContentConfig.config_key == key).first()
        if config:
            result[key] = json.loads(config.config_value)
        else:
            result[key] = None
    return result

# 获取单个内容配置
@router.get("/{config_key}")
def get_content(config_key: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if config_key not in VALID_CONFIG_KEYS:
        raise HTTPException(status_code=400, detail="无效的配置类型")
    
    config = db.query(ContentConfig).filter(ContentConfig.config_key == config_key).first()
    if not config:
        return None
    return json.loads(config.config_value)

# 更新内容配置（仅管理员和客服可编辑）
@router.put("/{config_key}")
def update_content(
    config_key: str,
    request: ContentConfigUpdate,
    current_user: User = Depends(require_roles("admin", "service")),
    db: Session = Depends(get_db)
):
    if config_key not in VALID_CONFIG_KEYS:
        raise HTTPException(status_code=400, detail="无效的配置类型")
    
    config = db.query(ContentConfig).filter(ContentConfig.config_key == config_key).first()
    if config:
        config.config_value = json.dumps(request.value, ensure_ascii=False)
    else:
        config = ContentConfig(
            config_key=config_key,
            config_value=json.dumps(request.value, ensure_ascii=False)
        )
        db.add(config)
    
    db.commit()
    return {"message": "保存成功", "data": request.value}
