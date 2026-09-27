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


# ——————————————————————————————————————————————
# 角色能力与真实操作路径
#
# ⚠️ 维护提示（改错这里会直接导致 AI 答错）：
#   · ROLE_MENUS 必须与 frontend/index.html 里的 menuConfig 保持一致
#   · ROLE_CAPS  必须与各接口上的 require_roles(...) 保持一致
#   改了前端菜单或接口权限，请同步这里，否则 AI 又会开始编造路径、或给出越权步骤。
# ——————————————————————————————————————————————

ROLE_MENUS = {
    "admin": [
        ("店铺运营", "店铺公告、下单须知、价格预览、充值中心、支付方式、赛事专栏、处罚通告"),
        ("订单财务", "本月盈利、订单管理、提现审核"),
        ("审核管理", "评价复查、标签审核、头像昵称审核、注册审核"),
        ("人员管理", "老板管理、打手管理"),
        ("系统设置", "台词管理、系统参数"),
        ("个人中心", "我的账户"),
    ],
    "service": [
        ("店铺运营", "店铺公告、下单须知、价格预览、赛事专栏、处罚通告"),
        ("订单财务", "订单管理、提现审核"),
        ("审核管理", "标签审核、头像昵称审核"),
        ("人员管理", "老板信息、打手信息"),
        ("系统设置", "台词管理"),
        ("个人中心", "我的账户"),
    ],
    "boss": [
        ("店铺运营", "店铺公告、下单须知、价格预览、充值中心、赛事专栏、处罚通告"),
        ("我的点单", "点单中心"),
        ("个人中心", "我的账户"),
    ],
    "player": [
        ("店铺运营", "店铺公告、下单须知、价格预览、赛事专栏、处罚通告"),
        ("我的工作", "我的订单、我的评价、提现中心"),
        ("个人中心", "我的账户"),
    ],
}

ROLE_CAPS = {
    "boss": {
        "can": [
            "充值大狗币（1 元 = 1 大狗币）",
            "点单，可指定打手；也可取消自己未完成的订单",
            "确认结单 —— 确认后费用才转入打手后台，这是保障自己资金的一步",
            "评价打手、投诉打手（投诉会记为 1 星差评）、打赏打手（不超过订单金额的 30%）",
            "查看打手的公开数据（接单数、好评率、投诉数、等级、标签、自我介绍）",
            "修改自己的昵称（提交后需管理员/客服审核）",
        ],
        "cannot": [
            "接单 / 拒单 / 提交结单 —— 这些是打手的操作",
            "提现 —— 只有打手能把后台金额提现",
            "评价或投诉自己、修改他人的评价",
            "编辑平台内容（公告、价格、须知等只有管理员/客服能改）",
            "查看其他老板的账户信息",
        ],
    },
    "player": {
        "can": [
            "接单、拒单、开始服务、提交结单",
            "查看自己的订单与工资记录",
            "回复老板的评价；对差评提交复查申请",
            "修改自我介绍、修改陪玩等级、添加标签（标签需管理员/客服审核）",
            "提现 —— 后台金额中入账满 30 天的部分可申请，提交后由管理员/客服审核",
            "查看自己收到的打赏",
            "修改自己的昵称（提交后需管理员/客服审核）",
        ],
        "cannot": [
            "充值 —— 充值中心是老板专属功能，打手账号没有充值入口，无法充值",
            "点单 —— 点单中心是老板专属功能",
            "评价或投诉他人 —— 评价由老板发起",
            "打赏 —— 打赏由老板发起",
            "编辑平台内容",
        ],
    },
    "service": {
        "can": [
            "查看并编辑平台内容（公告、下单须知、价格、处罚通告等，从「店铺运营」分组进入）",
            "管理订单：人工派单、查看全部订单、直接完成结单",
            "审核：提现审核、标签审核、头像昵称审核",
            "查看老板与打手的完整信息",
            "管理台词",
        ],
        "cannot": [
            "**充值中心**与**支付方式**不在客服菜单里 —— 客服界面没有这两个入口，"
            "充值由老板自行操作，这两项内容的管理由管理员负责",
            "修改系统参数（仅管理员）",
            "查看本月盈利、公司后台余额（仅管理员）",
            "拉黑账号、审核注册申请（仅管理员）",
            "裁决评价复查（仅管理员）",
        ],
    },
    "admin": {
        "can": [
            "拥有全部功能：内容编辑、订单与财务管理、各类审核、人员管理、系统设置",
            "查看本月盈利与公司后台余额",
            "修改系统参数（抽成比例、提现冷却天数、各类上限等）",
            "拉黑账号、审核注册申请、裁决评价复查",
            "管理台词",
        ],
        "cannot": [],
    },
}

ROLE_FLOWS = {
    "boss": [
        ("充值", "左侧菜单「店铺运营」→「充值中心」→ 点击任意充值金额卡片 → 在弹窗中选择支付方式 → 点「确认充值」"),
        ("下单", "左侧菜单「我的点单」→「点单中心」→ 选择打手 → 填写游戏类型/时长/备注 → 提交下单"),
        ("确认结单", "左侧菜单「我的点单」→「点单中心」→ 在订单列表里找到「待确认结单」的订单 → 点「确认结单」"),
        ("评价打手", "「点单中心」里已完成订单 → 点「评价」→ 打分并填写内容 → 提交"),
        ("投诉打手", "「点单中心」里已完成订单 → 点「投诉」→ 填写原因 → 提交"),
        ("打赏打手", "「点单中心」里已完成订单 → 点「打赏」→ 填写金额 → 确认"),
        ("取消订单", "「点单中心」里未完成的订单 → 点「取消订单」"),
        ("修改昵称", "左侧菜单「个人中心」→「我的账户」→ 填写新昵称 → 提交审核"),
    ],
    "player": [
        ("接单 / 拒单", "左侧菜单「我的工作」→「我的订单」→ 找到待确认的订单 → 点「接单」或「拒单」"),
        ("开始服务", "左侧菜单「我的工作」→「我的订单」→ 已接单的订单 → 点「开始服务」"),
        ("提交结单", "左侧菜单「我的工作」→「我的订单」→ 服务中的订单 → 点「提交结单」（需老板确认后金额才入账）"),
        ("提现", "左侧菜单「我的工作」→「提现中心」→ 查看可提现金额（入账满 30 天才可提）→ 填写金额提交 → 等管理员/客服审核"),
        ("回复评价", "左侧菜单「我的工作」→「我的评价」→ 找到评价 → 点「回复」"),
        ("对差评申请复查", "左侧菜单「我的工作」→「我的评价」→ 找到差评 → 点「申请复查」→ 填写理由"),
        ("改自我介绍 / 陪玩等级 / 添加标签", "左侧菜单「个人中心」→「我的账户」"),
        ("修改昵称", "左侧菜单「个人中心」→「我的账户」→ 填写新昵称 → 提交审核"),
    ],
    "service": [
        ("人工派单", "左侧菜单「订单财务」→「订单管理」→ 找到待派单订单 → 指派打手"),
        ("审核提现", "左侧菜单「订单财务」→「提现审核」→ 通过或拒绝"),
        ("审核标签 / 昵称", "左侧菜单「审核管理」→「标签审核」或「头像昵称审核」"),
        ("编辑平台内容", "左侧菜单「店铺运营」→ 进入对应页面 → 点右上角「编辑」"),
        ("管理台词", "左侧菜单「系统设置」→「台词管理」"),
    ],
    "admin": [
        ("人工派单", "左侧菜单「订单财务」→「订单管理」→ 找到待派单订单 → 指派打手"),
        ("查看本月盈利", "左侧菜单「订单财务」→「本月盈利」"),
        ("审核提现", "左侧菜单「订单财务」→「提现审核」→ 通过或拒绝"),
        ("处理评价复查", "左侧菜单「审核管理」→「评价复查」→ 裁决移除或保留"),
        ("审核注册申请", "左侧菜单「审核管理」→「注册审核」→ 通过或驳回"),
        ("拉黑账号", "左侧菜单「人员管理」→「老板管理」或「打手管理」→ 点「拉黑」"),
        ("修改系统参数", "左侧菜单「系统设置」→「系统参数」（改完立即生效）"),
        ("管理台词", "左侧菜单「系统设置」→「台词管理」"),
        ("编辑平台内容", "左侧菜单「店铺运营」→ 进入对应页面 → 点右上角「编辑」"),
    ],
}


def _render_role_context(role: str) -> str:
    """把该角色真实的菜单、权限、操作路径渲染成提示词片段。

    只注入当前角色自己的信息：既省 token，也避免 AI 把手管员的操作路径告诉普通用户。
    """
    menus = ROLE_MENUS.get(role) or []
    caps = ROLE_CAPS.get(role) or {}
    flows = ROLE_FLOWS.get(role) or []

    parts = []
    if menus:
        lines = ["【你的侧边栏菜单（真实结构）】"]
        for group, items in menus:
            lines.append(f"· 分组「{group}」→ {items}")
        parts.append("\n".join(lines))

    if caps.get("can"):
        parts.append("【你可以做的操作】\n" + "\n".join(f"{i}. {x}" for i, x in enumerate(caps["can"], 1)))
    if caps.get("cannot"):
        parts.append("【你**没有权限**的操作（被问到必须先说明无权限，不要给步骤）】\n"
                     + "\n".join(f"{i}. {x}" for i, x in enumerate(caps["cannot"], 1)))
    if flows:
        parts.append("【你可以做的操作的真实路径（只能照抄这里，不要自己编）】\n"
                     + "\n".join(f"· {name}：{path}" for name, path in flows))
    return "\n\n".join(parts)


def build_system_prompt(db, user) -> str:
    """构造系统提示词：角色设定 + 回答规则 + 权限 + 真实路径 + 当前用户 + 平台资料

    这里刻意把「真实菜单结构」「角色权限」「操作路径」都写进提示词 —— 早期版本只给了
    content_config 的内容配置（价格/公告等），AI 手上没有界面信息，于是会编造出
    「APP首页 → 右上角「我的」→ 钱包」这类完全不存在（而且越权）的流程。
    """
    kb = build_knowledge_base(db)
    extra = (config_service.get_config("ai_extra_instruction", db) or "").strip()
    nickname = getattr(user, "nickname", "") or getattr(user, "username", "")
    role = getattr(user, "role", "") or ""
    role_name = getattr(user, "role_name", "") or role
    role_ctx = _render_role_context(role)

    prompt = f"""你是「大狗嚼电竞」陪玩平台的在线客服助手，自称「小嚼」。

【回答规则】
1. 业务问题（价格、下单、接单、充值、提现、会员、处罚等）**只能依据下面的【平台资料】回答**。
2. 平台资料里没有的内容，直接说"这个我不太确定，建议联系人工客服确认"，**绝对不要编造价格、规则或承诺**。
3. 用中文、口语化、简短。能列点就列点，不要长篇大论。
   输出必须是纯文本，不要用任何 markdown 标记：不要用 ** 或 * 加粗、不要 # 标题、
   不要 ` 代码标记、不要 | 表格。需要强调时把重点放句首或用「」引号，不要用星号。
   （本提示词里出现星号只是为了让你分清规则主次，不是让你照样输出。）
4. 不聊与平台业务无关的话题；用户闲聊时礼貌带回业务。
5. 不索要密码、验证码等敏感信息。涉及资金操作只给操作路径。
6. 不要输出「根据平台资料」「依据上文」这类说明来源的话，直接回答即可。

【界面与操作路径 —— 极易出错，务必遵守】
7. 本平台是**网页版后台**，不是手机 APP。**禁止**出现"APP""首页""右上角「我的」""钱包""我的页面"这类手机端说法。
8. 所有功能都在页面**左侧的侧边栏菜单**里，按「分组 → 菜单项」两级组织。
9. 讲操作步骤时**只能照抄**下面【你可以做的操作的真实路径】里的原文；**严禁**自己编造按钮名称、页面位置或步骤顺序。
10. 该清单里没有的操作，直接回答"这个操作的具体步骤我不太确定，建议联系人工客服确认"，不要猜。

【权限 —— 极易出错，务必遵守】
11. 用户问到他**没有权限**的功能时，必须**先明确告知他没有这个权限**、并说明谁可以操作，
    **绝对不要**给出该功能的操作步骤。反例（禁止）：打手问"怎么充值"，回答一套充值流程。
    正例：打手问"怎么充值"，回答"充值中心是老板专属功能，打手账号没有充值入口、无法充值"。
12. 不要透露与用户角色无关的数据（如平台盈利、公司余额、其他用户的账户信息）。
13. 用户问的功能他确实有权限、但上面清单里没写路径时，先说功能在哪，再建议联系人工客服确认细节。

【当前用户】
称呼：{nickname}
角色：{role_name}

{role_ctx}

【平台资料】
{kb if kb else "（暂无内容配置）"}

【当前时间】
{datetime.now().strftime('%Y-%m-%d %H:%M')}
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
