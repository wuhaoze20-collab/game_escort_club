from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import config_service
import ops_alerts
from database import get_db
from models import User
from auth import require_roles
from schemas import SystemConfigUpdate

router = APIRouter(prefix="/api/config", tags=["系统参数"])

MANAGE_ROLES = ("admin", "service")


# 读取全部系统参数（含默认值、类型、说明，供后台设置页渲染表单）
# 同时带回运行期异常留痕：让「被防御代码兜住的静默故障」能被管理员看见
@router.get("/all")
def list_configs(
    current_user: User = Depends(require_roles(*MANAGE_ROLES)),
    db: Session = Depends(get_db),
):
    items = config_service.get_all_configs(db)
    return {"total": len(items), "items": items, "alerts": ops_alerts.list_alerts()}


# 清空异常留痕（管理员确认处理完之后）
@router.post("/alerts/clear")
def clear_alerts(
    current_user: User = Depends(require_roles("admin")),
):
    ops_alerts.clear()
    return {"message": "已清空异常提示"}


# 修改单个参数
@router.put("/{config_key}")
def update_config(
    config_key: str,
    request: SystemConfigUpdate,
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    try:
        stored = config_service.set_config(db, config_key, request.value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"message": "参数已更新（立即生效）", "config_key": config_key, "config_value": stored}


# 恢复单个参数为默认值
@router.post("/{config_key}/reset")
def reset_config(
    config_key: str,
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    meta = config_service.CONFIG_META.get(config_key)
    if meta is None:
        raise HTTPException(status_code=404, detail="未知参数")
    default_text = config_service._dump(meta["default"], meta["type"])
    config_service.set_config(db, config_key, default_text)
    return {"message": f"已恢复默认值 {default_text}", "config_key": config_key,
            "config_value": default_text}
