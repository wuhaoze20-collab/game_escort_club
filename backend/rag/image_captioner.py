# -*- coding: utf-8 -*-
"""多模态 RAG · 路线 A：把图片"翻译成文字"，再交给现有文本检索管线。

为什么这样做（而不是给图片建向量）
────────────────────────────────────────────────
现有 RAG 管线（父子分块 → 向量化 → 多路召回 → RRF 融合 → 重排序 → Self-RAG）
解决的是「文本语义检索」。图片本身没法被文本向量命中，但只要先把图片变成
一段**信息密度高、可检索的中文文本**（结构化描述 + 图内文字 OCR + 关键实体），
它就能作为一个普通文档源流进那条管线 —— 检索侧零改动。

为什么让 VL 一次同时产出「描述 + OCR + 实体」，而不分开做：
    · 分三次调用 = 三倍费用、三倍失败点；
    · 千问 VL 本来就能在一次回答里把画面理解和文字识别一起给出；
    · 三者拼成一段文本后，向量检索对"描述词"和"图中数字"都能命中。

成本控制（这是本模块最要紧的设计）
────────────────────────────────────────────────
图注缓存在 `ai_image_captions` 表，缓存键 = 文件名 + **图片文件二进制的 MD5**。
· 图片没换 → 直接读缓存，一次 API 都不调；
· 图片换了内容（MD5 变）→ 只重算这一张。
所以管理员把「重建索引」点一百遍，只要图库没动，VL 花费就是 0。

与 embedding 的关系：本模块只负责"产出文本"，不负责向量化。
    图注文本交回 ai_rag.collect_sources()，由现成的 embed_texts() 统一向量化。
"""

import base64
import hashlib
import io
import os

import requests

# 知识库图片目录：项目根 / kb_images
# 与 touxiangku/（头像源库）、bizhiku/（壁纸库）同级，都是"文件放磁盘、库里只存文件名"
KB_IMAGES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "kb_images"
)

# 支持的图片格式（GIF 只取第一帧）
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")

DEFAULT_VL_MODEL = "qwen3-vl-plus"
VL_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
VL_TIMEOUT = 90

# 发给模型前把图压到长边 1280、JPEG 质量 85：
# · base64 会让体积膨胀约 33%，原图直传很容易撞上请求体上限；
# · 1280 的长边对「看清段位数字、界面文字」已经足够，再大只是白花钱。
_MAX_SIDE = 1280
_JPEG_QUALITY = 85

# 图注提示词：目标不是"好看的描述文案"，而是**能被检索命中的结构化文本**。
# 所以「图中文字」这一项要求逐条抄录 —— 段位名、KD 数字、游戏 ID 常常只出现在
# 画面里，不抄下来，用户问"有没有钻石以上的打手"就永远检索不到这张图。
CAPTION_PROMPT = """你是游戏陪玩平台的知识库整理助手。请仔细观察这张图片，输出一段**用于文本检索**的结构化描述，而不是给人看的文案。

请严格按以下四段输出：

一、一句话概括
用不超过 30 字概括这张图是什么。

二、画面内容
客观描述图中出现的界面、人物、图表、数据、道具等，只描述看得见的东西，不要评价、不要推测原因。

三、图中文字
逐条抄录图片里所有可见的文字与数字，包括：标题、按钮文字、段位名称、等级、战绩数字（KD、胜率、场次）、游戏 ID、订单号、金额、时间等。这一项是检索的关键，务必抄全，看不清的用「?」代替。

四、关键信息
列出可用于检索的标签词，例如所属游戏名、段位、数据类型（战绩截图 / 规则截图 / 界面截图）、相关业务（点单 / 充值与会员 / 投诉与处罚 / 打手资质 等）。

直接输出正文，不要寒暄、不要 Markdown 代码块。"""


# ——————————————————————————————————————————————
# 基础工具
# ——————————————————————————————————————————————

def is_image(filename: str) -> bool:
    """判断文件名是否属于支持的图片格式。"""
    return (filename or "").lower().endswith(IMAGE_EXTENSIONS)


def ensure_dir() -> str:
    """确保图片目录存在，返回目录路径。"""
    os.makedirs(KB_IMAGES_DIR, exist_ok=True)
    return KB_IMAGES_DIR


def list_image_files() -> list:
    """列出图片目录下的所有图片文件名（排序稳定，便于复现）。"""
    if not os.path.isdir(KB_IMAGES_DIR):
        return []
    return sorted(f for f in os.listdir(KB_IMAGES_DIR)
                  if is_image(f) and not f.startswith("~$"))


def file_md5(path: str) -> str:
    """算文件的 MD5。这是缓存键的核心 —— 内容变没变，看它就够。"""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _safe_name(name: str) -> str:
    """清洗文件名，防止路径穿越（../）与非法字符。

    只保留字母、数字、下划线、短横线、点、以及中日韩字符；
    其余一律替换成下划线。这样既允许中文文件名，又挡掉 `../`。
    """
    base = os.path.basename(name or "").strip()
    if not base:
        return ""
    keep = []
    for ch in base:
        if ch.isalnum() or ch in ("_", "-", ".", "(", ")", "（", "）", " "):
            keep.append(ch)
        elif "\u4e00" <= ch <= "\u9fff":
            keep.append(ch)
        else:
            keep.append("_")
    cleaned = "".join(keep).strip(". ")
    return cleaned


# ——————————————————————————————————————————————
# 图片预处理：压缩 + 转 base64
# ——————————————————————————————————————————————

def _prepare_data_uri(path: str) -> str:
    """把本地图片压成长边 1280 的 JPEG，再编码成 data URI 供 VL 接口使用。

    为什么要重编码而不是直接读原文件：
        · 原图可能是 5MB 的 PNG，base64 后 6.7MB，容易被接口或网关拒绝；
        · 统一转 RGB 后可以兼容 RGBA / 灰度 / 调色板等各种模式；
        · JPEG 质量 85 对文字识别几乎无损失，体积却小一个量级。
    """
    try:
        from PIL import Image
    except ImportError:
        # 没装 Pillow 时退化为直传原文件（不压缩），保证功能可用
        with open(path, "rb") as f:
            raw = f.read()
        ext = os.path.splitext(path)[1].lower().lstrip(".") or "png"
        mime = "jpeg" if ext in ("jpg", "jpeg") else ext
        return "data:image/%s;base64,%s" % (mime, base64.b64encode(raw).decode("ascii"))

    with Image.open(path) as im:
        # GIF 取第一帧；带透明通道的先铺白底，否则转 JPEG 后透明区会变黑
        try:
            im.seek(0)
        except Exception:
            pass
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            canvas = Image.new("RGB", im.size, (255, 255, 255))
            canvas.paste(im, mask=im.split()[-1])
            im = canvas
        else:
            im = im.convert("RGB")

        w, h = im.size
        if max(w, h) > _MAX_SIDE:
            scale = _MAX_SIDE / float(max(w, h))
            im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                           Image.LANCZOS)

        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=_JPEG_QUALITY, optimize=True)

    return "data:image/jpeg;base64,%s" % base64.b64encode(buf.getvalue()).decode("ascii")


# ——————————————————————————————————————————————
# 调用千问 VL 生成图注
# ——————————————————————————————————————————————

def vl_model(db=None) -> str:
    """读系统参数里的 VL 模型名，缺省回退 qwen-vl-plus。

    注意 config_service.get_config 的签名是 (key, db, default)，
    db 是第二个参数，别传反了 —— 传反不会报错，只会静默回退到默认值。
    """
    try:
        import config_service
        if db is not None:
            return (config_service.get_config("ai_vl_model", db) or DEFAULT_VL_MODEL).strip() \
                or DEFAULT_VL_MODEL
    except Exception:
        pass
    return DEFAULT_VL_MODEL


def _call_vl(db, data_uri: str, model: str) -> str:
    """调一次千问 VL，返回图注正文。失败抛 RuntimeError（由上层决定是否降级）。"""
    import ai_service
    api_key = ai_service.get_api_key()
    if not api_key:
        raise RuntimeError("未配置 DASHSCOPE_API_KEY")

    payload = {
        "model": model,
        # 图片放在文字**前面**：千问 VL 的图文消息里图片在前时，
        # 模型对"描述这张图"的指令跟随更稳（放在后面偶发答非所问）。
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": data_uri}},
                {"type": "text", "text": CAPTION_PROMPT},
            ],
        }],
        # 图注要求客观、稳定，随机度压低；长度给足，否则「图中文字」会被截断
        "temperature": 0.1,
        "max_tokens": 1200,
    }
    try:
        resp = requests.post(
            VL_URL,
            headers={"Authorization": "Bearer %s" % api_key,
                     "Content-Type": "application/json"},
            json=payload,
            timeout=VL_TIMEOUT,
        )
    except requests.exceptions.Timeout:
        raise RuntimeError("图片理解服务响应超时")
    except requests.exceptions.RequestException as e:
        raise RuntimeError("无法连接图片理解服务（%s）" % type(e).__name__)

    if resp.status_code != 200:
        detail = ""
        try:
            body = resp.json()
            detail = ((body.get("error") or {}).get("message") or body.get("message") or "")
        except Exception:
            detail = (resp.text or "")[:160]
        raise RuntimeError("图片理解接口 HTTP %s%s"
                           % (resp.status_code, ("：" + detail) if detail else ""))

    try:
        data = resp.json()
        choices = data.get("choices") or []
        text = ((choices[0].get("message") or {}).get("content") or "").strip()
    except Exception as e:
        raise RuntimeError("图片理解接口返回无法解析：%s" % e)

    if not text:
        raise RuntimeError("图片理解接口返回了空内容")
    return text


# ——————————————————————————————————————————————
# 带缓存的图注获取（本模块对外的主入口）
# ——————————————————————————————————————————————

def get_caption(db, filename: str, force: bool = False) -> dict:
    """获取一张图片的图注，命中缓存则零 API 花费。

    返回 dict：
        {"ok": bool, "caption": str, "from_cache": bool, "model": str, "error": str}

    调用时机：ai_rag.collect_sources() 在规划阶段逐张调用。
    失败不抛异常 —— 单张图挂了不能让整次重建索引中断，只记录错误并跳过该图。
    """
    from models import AiImageCaption

    path = os.path.join(KB_IMAGES_DIR, filename)
    if not os.path.isfile(path):
        return {"ok": False, "caption": "", "from_cache": False,
                "model": "", "error": "文件不存在"}

    try:
        cur_hash = file_md5(path)
    except Exception as e:
        return {"ok": False, "caption": "", "from_cache": False,
                "model": "", "error": "读取文件失败：%s" % e}

    row = db.query(AiImageCaption).filter(
        AiImageCaption.file_name == filename).first()

    # 缓存命中：文件内容没变（且不是强制重算），直接用旧图注，不花一分钱
    if row is not None and not force and (row.file_hash or "") == cur_hash \
            and (row.caption or "").strip():
        return {"ok": True, "caption": row.caption, "from_cache": True,
                "model": row.model or "", "error": ""}

    model = vl_model(db)
    try:
        data_uri = _prepare_data_uri(path)
        caption = _call_vl(db, data_uri, model)
    except Exception as e:
        # 生成失败：保留旧缓存（若有），否则本次跳过这张图
        if row is not None and (row.caption or "").strip():
            return {"ok": True, "caption": row.caption, "from_cache": True,
                    "model": row.model or "", "error": str(e)}
        return {"ok": False, "caption": "", "from_cache": False,
                "model": model, "error": str(e)}

    # 写回缓存（upsert）
    if row is None:
        row = AiImageCaption(file_name=filename)
        db.add(row)
    row.file_hash = cur_hash
    row.caption = caption
    row.model = model
    try:
        db.commit()
    except Exception:
        db.rollback()

    return {"ok": True, "caption": caption, "from_cache": False,
            "model": model, "error": ""}


def drop_caption(db, filename: str) -> int:
    """删除某张图片的图注缓存。返回删除条数。

    删除图片时必须调用 —— 否则同名文件重新上传后，会因为 MD5 恰好相同
    （同一张图重传）而拿到已删除图片的缓存，虽然内容一致，但会让
    「图片列表」与「缓存表」出现不一致的残留行。
    """
    from models import AiImageCaption
    n = db.query(AiImageCaption).filter(
        AiImageCaption.file_name == filename).delete(synchronize_session=False)
    db.commit()
    return n
