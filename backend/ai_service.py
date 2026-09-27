"""AI 客服服务层（通义千问）。

职责分工（与项目既有风格一致）：
- `api/ai_api.py` 只管 HTTP 出入口、鉴权、会话读写
- 本模块负责：读密钥、拼知识库提示词、调用千问、错误分类、用量统计

关键设计约束：
1. **密钥只从 backend/.env 读**，绝不硬编码、绝不入库、绝不发给前端。
2. 项目内所有接口都是同步 `def`（FastAPI 会自动放进线程池），所以这里用同步
   `requests`。**不要在 async def 里调用本模块**，那会阻塞事件循环。
3. 必须设 `timeout`，否则一个卡住的请求会长期占用线程池线程，拖慢整个后端。
4. 未配置密钥时**不抛异常**，而是返回可读提示，保证 AI 功能缺失不影响其它功能。
"""

import json
import os
from datetime import datetime

import requests

import config_service

# OpenAI 兼容接口（北京地域）。各地域 Key 不通用，换地域需同步改这里与 Key
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
DEFAULT_MODEL = "qwen-plus"
DEFAULT_TIMEOUT = 60

# content_config 的 key → 中文标题（用于拼知识库时的小标题）
CONTENT_LABELS = {
    "notice": "店铺公告",
    "orderGuide": "下单须知",
    "price": "价格预览",
    "recharge": "充值福利",
    "member": "会员福利",
    "payment": "支付方式",
    "punishment": "处罚通告",
    "matches": "赛事专栏",
}

_env_loaded = False


def _load_env():
    """加载 backend/.env（只做一次）。失败不致命，静默降级。"""
    global _env_loaded
    if _env_loaded:
        return
    _env_loaded = True
    try:
        from dotenv import load_dotenv
        base_dir = os.path.dirname(os.path.abspath(__file__))
        load_dotenv(os.path.join(base_dir, ".env"))
    except Exception as e:
        print(f"[ai] 读取 .env 失败（不影响其它功能）：{e}")


def get_api_key() -> str:
    """取千问 API Key；未配置返回空串"""
    _load_env()
    return (os.getenv("DASHSCOPE_API_KEY") or "").strip()


def is_configured() -> bool:
    """是否已配置密钥（未配置时前端只提示、不显示报错）"""
    return bool(get_api_key())


def _base_url() -> str:
    _load_env()
    return (os.getenv("QWEN_BASE_URL") or "").strip() or DEFAULT_BASE_URL


def _timeout() -> int:
    _load_env()
    try:
        return int(os.getenv("QWEN_TIMEOUT") or DEFAULT_TIMEOUT)
    except ValueError:
        return DEFAULT_TIMEOUT


# ——————————————————————————————————————————————
# 知识库：把 content_config 的 8 个内容模块转成可读文本
# ——————————————————————————————————————————————

def _render_value(val) -> str:
    """把内容配置渲染成易读文本。用通用渲染而非逐字段硬编码，
    这样以后往内容模块里加字段，知识库会自动带上，不需要改这里。"""
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        # notice 这类：{title, content, updateTime}
        lines = []
        if val.get("title"):
            lines.append(str(val["title"]))
        if val.get("content"):
            lines.append(str(val["content"]))
        for k, v in val.items():
            if k in ("title", "content", "updateTime"):
                continue
            if v not in (None, "", []):
                lines.append(f"{k}：{v}")
        return "\n".join(lines)
    if isinstance(val, list):
        out = []
        for i, item in enumerate(val, 1):
            if isinstance(item, dict):
                kv = "；".join(f"{k}：{v}" for k, v in item.items() if v not in (None, "", []))
                out.append(f"{i}. {kv}")
            else:
                out.append(f"{i}. {item}")
        return "\n".join(out)
    return str(val)


def build_knowledge_base(db) -> str:
    """拼装平台知识库（内容来自数据库，后台改内容后 AI 的回答会自动跟着变）"""
    from models import ContentConfig
    from api.content_api import VALID_CONFIG_KEYS  # 复用白名单，避免两处维护

    blocks = []
    for key in VALID_CONFIG_KEYS:
        row = db.query(ContentConfig).filter(ContentConfig.config_key == key).first()
        if not row or not row.config_value:
            continue
        try:
            val = json.loads(row.config_value)
        except Exception:
            continue
        text = _render_value(val).strip()
        if text:
            blocks.append(f"【{CONTENT_LABELS.get(key, key)}】\n{text}")
    return "\n\n".join(blocks)


def build_system_prompt(db, user) -> str:
    """构造系统提示词：角色设定 + 回答规则 + 当前用户上下文 + 平台资料"""
    kb = build_knowledge_base(db)
    extra = (config_service.get_config("ai_extra_instruction", db) or "").strip()
    nickname = getattr(user, "nickname", "") or getattr(user, "username", "")
    role_name = getattr(user, "role_name", "") or getattr(user, "role", "")

    prompt = f"""你是「大狗嚼电竞」陪玩平台的在线客服助手，自称「小嚼」。

【回答规则】
1. 业务问题（价格、下单、接单、充值、提现、会员、处罚等）**只能依据下面的【平台资料】回答**。
2. 平台资料里没有的内容，直接说"这个我不太确定，建议联系人工客服确认"，**绝对不要编造价格、规则或承诺**。
3. 用中文、口语化、简短。能列点就列点，不要长篇大论。
4. 不聊与平台业务无关的话题；用户闲聊时礼貌带回业务。
5. 不索要密码、验证码等敏感信息。涉及资金操作只给操作路径（在哪个页面怎么点）。
6. 不要输出「根据平台资料」「依据上文」这类说明来源的话，直接回答即可。

【当前用户】
称呼：{nickname}
角色：{role_name}
当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}

【平台资料】
{kb if kb else "（暂无内容配置）"}
"""
    if extra:
        prompt += f"\n【补充指示】\n{extra}\n"
    return prompt


# ——————————————————————————————————————————————
# 调用千问
# ——————————————————————————————————————————————

def chat(messages: list, model: str = None, temperature: float = 0.3,
         max_tokens: int = 800) -> dict:
    """调用千问。**不抛异常**，一律返回结构化结果。

    返回：{
        "ok": bool,
        "reply": str,            # 成功时的回答
        "error": str,            # 失败原因（可直接展示给用户）
        "prompt_tokens": int,
        "completion_tokens": int,
        "model": str,
    }
    """
    fail = lambda msg: {"ok": False, "reply": "", "error": msg,
                        "prompt_tokens": 0, "completion_tokens": 0, "model": model or ""}

    api_key = get_api_key()
    if not api_key:
        return fail("AI 客服尚未配置：请在 backend/.env 里填写 DASHSCOPE_API_KEY 后重启后端。"
                    "（可联系管理员处理）")

    model = (model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # —— 网络层 ——
    try:
        resp = requests.post(_base_url(), headers=headers, json=payload, timeout=_timeout())
    except requests.exceptions.Timeout:
        return fail("AI 服务响应超时，请稍后再试一次。")
    except requests.exceptions.RequestException as e:
        return fail(f"无法连接 AI 服务，请检查网络后重试。（{type(e).__name__}）")

    # —— 状态码分类，给可读提示（避免把原始 JSON 直接甩给用户）——
    if resp.status_code == 401:
        return fail("AI 服务鉴权失败：API Key 无效，或 Key 与接口地域不匹配"
                    "（例如用别的地域创建的 Key 调北京接口）。请联系管理员核对。")
    if resp.status_code == 429:
        return fail("AI 服务请求过于频繁或额度已用尽，请稍后再试。")
    if resp.status_code >= 500:
        return fail("AI 服务暂时不可用，请稍后再试。")
    if resp.status_code != 200:
        detail = ""
        try:
            body = resp.json()
            detail = (body.get("error") or {}).get("message") or body.get("message") or ""
        except Exception:
            detail = (resp.text or "")[:120]
        return fail(f"AI 服务返回异常（HTTP {resp.status_code}）{('：' + detail) if detail else ''}")

    # —— 解析响应 ——
    try:
        data = resp.json()
        reply = (data["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:
        return fail(f"AI 返回内容无法解析，请稍后再试。（{type(e).__name__}）")

    if not reply:
        return fail("AI 没有返回内容，请换个说法再问一次。")

    usage = data.get("usage") or {}
    return {
        "ok": True,
        "reply": reply,
        "error": "",
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "model": data.get("model") or model,
    }
