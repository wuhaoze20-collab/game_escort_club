import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import ContentConfig, User
from schemas import ContentConfigUpdate
from auth import get_current_user, require_roles

router = APIRouter(prefix="/api/content", tags=["内容管理"])

# 允许的配置key
VALID_CONFIG_KEYS = ["notice", "orderGuide", "price", "recharge", "member", "payment", "punishment", "matches"]

# 客服不可编辑的内容项。
# 这两项已从客服菜单移除（充值由老板自行操作、支付方式属平台配置），
# 因此接口层也要一并拦住 —— 否则会出现「界面没入口、但调 API 仍能改」的前后端权限不一致。
# 管理员不受此限制。
SERVICE_FORBIDDEN_KEYS = {"recharge", "payment"}

# 各内容模块允许的结构：notice=对象；orderGuide=字符串数组；其余=对象数组（字段均为字符串）
LIST_TEXT_FIELDS = {
    "price": ["game", "rank", "unit"],
    "recharge": ["bonus"],
    "member": ["level", "discount", "benefits"],
    "payment": ["name", "desc", "icon"],
    "punishment": ["level", "desc", "date"],
    "matches": ["game", "title", "url"],
}
# 对象数组中的数字字段
LIST_NUMBER_FIELDS = {
    "price": ["price"],
    "recharge": ["amount", "gift"],
}


def _validate_content_structure(key: str, value):
    """校验内容结构，防止写入错误类型导致前端全局渲染崩溃"""
    if key == "notice":
        if not isinstance(value, dict):
            raise HTTPException(status_code=400, detail="公告内容格式错误：应为 {title, content, updateTime} 对象")
        for field in ("title", "content"):
            if not isinstance(value.get(field), str):
                raise HTTPException(status_code=400, detail=f"公告缺少文本字段：{field}")
        return

    if key == "orderGuide":
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            raise HTTPException(status_code=400, detail="下单须知格式错误：应为字符串数组，例如 [\"须知1\", \"须知2\"]")
        return

    # price / recharge / member / payment / punishment：均为对象数组
    if not isinstance(value, list):
        raise HTTPException(status_code=400, detail="内容格式错误：应为数组")
    text_fields = LIST_TEXT_FIELDS.get(key, [])
    number_fields = LIST_NUMBER_FIELDS.get(key, [])
    for i, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail=f"第{i}条格式错误：应为对象")
        for field in text_fields:
            if not isinstance(item.get(field), str):
                raise HTTPException(status_code=400, detail=f"第{i}条缺少文本字段：{field}")
        for field in number_fields:
            v = item.get(field)
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise HTTPException(status_code=400, detail=f"第{i}条缺少数字字段：{field}")
            if v < 0:
                raise HTTPException(status_code=400, detail=f"第{i}条的 {field} 不能为负数")

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

# 更新内容配置（管理员可改全部；客服可改除 SERVICE_FORBIDDEN_KEYS 之外的内容）
@router.put("/{config_key}")
def update_content(
    config_key: str,
    request: ContentConfigUpdate,
    current_user: User = Depends(require_roles("admin", "service")),
    db: Session = Depends(get_db)
):
    if config_key not in VALID_CONFIG_KEYS:
        raise HTTPException(status_code=400, detail="无效的配置类型")

    # 客服不能改充值中心与支付方式（与前端菜单保持一致）
    if current_user.role == "service" and config_key in SERVICE_FORBIDDEN_KEYS:
        raise HTTPException(
            status_code=403,
            detail="「充值中心」与「支付方式」仅管理员可编辑，客服无此权限",
        )

    # 校验结构（防止写入错误类型把前端所有页面写崩）
    _validate_content_structure(config_key, request.value)

    value = request.value
    if isinstance(value, dict):
        value = dict(value)
        # 公告自动刷新"最后更新"时间，避免非法类型
        value["updateTime"] = datetime.now().strftime("%Y-%m-%d %H:%M")

    config = db.query(ContentConfig).filter(ContentConfig.config_key == config_key).first()
    if config:
        config.config_value = json.dumps(value, ensure_ascii=False)
    else:
        config = ContentConfig(
            config_key=config_key,
            config_value=json.dumps(value, ensure_ascii=False)
        )
        db.add(config)

    db.commit()
    return {"message": "保存成功", "data": value}
