import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import ai_service
import ai_tools
import config_service
from auth import get_current_user
from database import get_db
from models import AiConversation, AiMessage, User
from schemas import AiChatRequest, AiChatResponse

router = APIRouter(prefix="/api/ai", tags=["AI 客服"])

MAX_MESSAGE_LEN = 1000  # 单条提问字数上限，防止把整个知识库挤掉
MAX_TOOL_ROUNDS = 3     # 工具调用最多几轮，防止模型反复调同一个工具烧 token


def _today_start() -> datetime:
    now = datetime.now()
    return datetime(now.year, now.month, now.day)


def _used_today(db: Session, username: str) -> int:
    """统计该用户今天已提问的条数（只数 user 角色消息）"""
    return (db.query(AiMessage)
            .join(AiConversation, AiMessage.conversation_id == AiConversation.id)
            .filter(AiConversation.username == username,
                    AiMessage.role == "user",
                    AiMessage.created_at >= _today_start())
            .count())


def _remaining(db: Session, username: str) -> int:
    """今日剩余可提问条数；-1 表示不限制"""
    limit = int(config_service.get_config("ai_daily_limit", db))
    if limit <= 0:
        return -1
    return max(0, limit - _used_today(db, username))


# 前端用它决定要不要显示聊天入口（未配置密钥/已关闭时就不显示，避免点进去报错）
@router.get("/status")
def ai_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    enabled = bool(config_service.get_config("ai_enabled", db))
    configured = ai_service.is_configured()
    return {
        "enabled": enabled,
        "configured": configured,          # 是否已配置 API Key
        "available": enabled and configured,  # 真正可用
        "model": config_service.get_config("ai_model", db),
        "remaining_today": _remaining(db, current_user.username),
        "daily_limit": int(config_service.get_config("ai_daily_limit", db)),
    }


# 发消息（一问一答）
@router.post("/chat", response_model=AiChatResponse)
def ai_chat(
    request: AiChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not bool(config_service.get_config("ai_enabled", db)):
        raise HTTPException(status_code=403, detail="AI 客服当前已关闭")

    # 先做无副作用的校验，再检查配置与配额，最后才落库
    text = (request.message or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="请输入内容")
    if len(text) > MAX_MESSAGE_LEN:
        raise HTTPException(status_code=400, detail=f"单条提问不能超过 {MAX_MESSAGE_LEN} 个字符")

    # 未配置密钥时提前拦截 —— 避免每次尝试都写出一条会话和两条消息（垃圾数据）
    if not ai_service.is_configured():
        raise HTTPException(
            status_code=503,
            detail="AI 客服尚未配置：请在 backend/.env 里填写 DASHSCOPE_API_KEY 后重启后端",
        )

    # 每日上限（防止接口被刷导致费用失控）
    limit = int(config_service.get_config("ai_daily_limit", db))
    if limit > 0 and _used_today(db, current_user.username) >= limit:
        raise HTTPException(status_code=429,
                            detail=f"今日提问次数已用完（上限 {limit} 条），请明天再来")

    # 取或建会话 —— 必须校验归属，否则能读别人的聊天记录
    conv = None
    if request.conversation_id:
        conv = db.query(AiConversation).filter(
            AiConversation.id == request.conversation_id,
            AiConversation.username == current_user.username,   # 归属校验
        ).first()
        if not conv:
            raise HTTPException(status_code=404, detail="会话不存在")
    if conv is None:
        conv = AiConversation(username=current_user.username,
                              title=text[:30] or "新对话")
        db.add(conv)
        db.flush()  # 拿到 conv.id

    # 存用户这条
    db.add(AiMessage(conversation_id=conv.id, role="user", content=text))
    db.commit()

    # 取最近 N 轮作为上下文
    rounds = max(1, int(config_service.get_config("ai_history_rounds", db)))
    history = (db.query(AiMessage)
               .filter(AiMessage.conversation_id == conv.id)
               .order_by(AiMessage.id.desc())
               .limit(rounds * 2)
               .all())
    history.reverse()

    # 传 text 进去：FAQ 按需注入要用本轮提问做关键词匹配
    messages = [{"role": "system", "content": ai_service.build_system_prompt(db, current_user, text)}]
    for m in history:
        # 调用失败的助手消息（内容为空）不放进上下文，避免污染
        if m.role == "assistant" and not (m.content or "").strip():
            continue
        messages.append({"role": m.role, "content": m.content})

    # 按角色暴露工具（无权限的工具根本不给模型看，减少它乱猜）
    tools = ai_tools.available_tools(current_user.role)
    model = config_service.get_config("ai_model", db)
    temperature = float(config_service.get_config("ai_temperature", db))
    max_tokens = int(config_service.get_config("ai_max_tokens", db))

    # —— 工具调用循环 ——
    # 模型可能连续要求多个工具（先查余额再查订单）。最多跑 MAX_TOOL_ROUNDS 轮，
    # 避免模型陷入"反复调同一个工具"的死循环把 token 烧光。
    used_tools = []
    prompt_tokens = completion_tokens = 0
    result = {"ok": False, "reply": "", "error": "未执行", "model": model}
    for _round in range(MAX_TOOL_ROUNDS):
        result = ai_service.chat(messages, model=model, temperature=temperature,
                                 max_tokens=max_tokens, tools=tools or None)
        prompt_tokens += result.get("prompt_tokens", 0)
        completion_tokens += result.get("completion_tokens", 0)
        if not result["ok"]:
            break
        tool_calls = result.get("tool_calls") or []
        if not tool_calls:
            break

        # 把模型这一轮的"要求调工具"消息原样带上，再逐个追加工具结果
        messages.append({
            "role": "assistant",
            "content": result.get("reply") or "",
            "tool_calls": tool_calls,
        })
        for tc in tool_calls:
            fn = (tc.get("function") or {})
            name = fn.get("name") or ""
            raw_args = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                if not isinstance(args, dict):
                    args = {}
            except Exception:
                args = {}
            outcome = ai_tools.run_tool(name, args, db, current_user)
            used_tools.append(name)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id") or name,
                "content": outcome["result"],
            })
    else:
        # 跑满轮数还没收敛：补一次不带工具的调用，强制它用已有信息作答
        result = ai_service.chat(messages, model=model, temperature=temperature,
                                 max_tokens=max_tokens, tools=None)
        prompt_tokens += result.get("prompt_tokens", 0)
        completion_tokens += result.get("completion_tokens", 0)

    # 多轮累加 token（覆盖单轮的统计，否则只记了最后一轮）
    result["prompt_tokens"] = prompt_tokens
    result["completion_tokens"] = completion_tokens

    # 失败也落库，便于排查（内容为空，error 记原因）
    db.add(AiMessage(
        conversation_id=conv.id,
        role="assistant",
        content=result["reply"],
        prompt_tokens=result["prompt_tokens"],
        completion_tokens=result["completion_tokens"],
        error=result["error"][:255],
        tools_used=",".join(used_tools)[:255],
    ))
    conv.updated_at = datetime.now()
    db.commit()

    if not result["ok"]:
        # 用 502 表示「上游 AI 服务有问题」，但仍把可读原因带给前端
        raise HTTPException(status_code=502, detail=result["error"])

    return AiChatResponse(
        conversation_id=conv.id,
        reply=result["reply"],
        prompt_tokens=result["prompt_tokens"],
        completion_tokens=result["completion_tokens"],
        remaining_today=_remaining(db, current_user.username),
        model=result["model"],
    )


# 我的会话列表
@router.get("/conversations")
def list_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    convs = (db.query(AiConversation)
             .filter(AiConversation.username == current_user.username)
             .order_by(AiConversation.updated_at.desc())
             .limit(50).all())
    return [{
        "id": c.id,
        "title": c.title,
        "created_at": c.created_at,
        "updated_at": c.updated_at,
        "message_count": db.query(AiMessage).filter(AiMessage.conversation_id == c.id).count(),
    } for c in convs]


# 某会话的历史消息
@router.get("/conversations/{conversation_id}/messages")
def get_messages(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = db.query(AiConversation).filter(
        AiConversation.id == conversation_id,
        AiConversation.username == current_user.username,   # 归属校验
    ).first()
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")

    rows = (db.query(AiMessage)
            .filter(AiMessage.conversation_id == conversation_id)
            .order_by(AiMessage.id.asc()).all())
    return [{
        "id": m.id,
        "role": m.role,
        "content": m.content,
        "error": m.error or "",
        "created_at": m.created_at,
    } for m in rows]


# 删除会话（连同其消息）
@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = db.query(AiConversation).filter(
        AiConversation.id == conversation_id,
        AiConversation.username == current_user.username,   # 归属校验
    ).first()
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")

    db.query(AiMessage).filter(AiMessage.conversation_id == conversation_id).delete()
    db.delete(conv)
    db.commit()
    return {"message": "会话已删除"}
