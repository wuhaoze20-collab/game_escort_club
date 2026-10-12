"""
RAG 量化评估模块（层次1：本地实现，不依赖 LLM 打分）

评估三个核心指标：
  1. Context Precision（上下文精确率）：检索到的片段中，与标准答案相关的占比
  2. Context Recall（上下文召回率）：标准答案的关键信息，有多少被检索到了
  3. 语义相似度（端到端）：AI 生成答案 vs 标准答案的余弦相似度

评估方法：
  - 用 BGE 语义模型计算文本间的余弦相似度，判断"是否相关"
  - 不需要调大模型当评委，纯本地计算，快、稳定、可复现
  - 阈值 0.65：相似度 ≥ 0.65 判定为"相关"

使用方式：
  from rag_eval import evaluate_rag
  results = evaluate_rag(db, questions, role="boss")
  # results 包含每条问答的详细得分 + 整体平均分
"""

import os
import time
from typing import List, Dict

# 必须在导入 sentence_transformers 之前设置镜像，否则会直连 huggingface 超时
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "0")

# —— 语义相似度模型（延迟加载，首次调用时才下载/加载）——
_sim_model = None
_sim_model_name = "BAAI/bge-small-zh-v1.5"  # 轻量中文版，速度快效果够评估用


def _get_sim_model():
    """获取 BGE 语义相似度模型（单例，首次加载后缓存）。

    优先用本地 sentence-transformers 的 BGE 模型；
    如果本地没有缓存（首次需要下载，可能很慢），直接回退到千问 embedding API。
    手动下载模型后会自动启用本地模型：
        from sentence_transformers import SentenceTransformer
        SentenceTransformer("BAAI/bge-small-zh-v1.5")
    """
    global _sim_model
    if _sim_model is not None:
        return _sim_model

    # 先检查本地是否已有模型缓存（避免每次都尝试下载导致超时）
    try:
        from sentence_transformers import SentenceTransformer
        import huggingface_hub
        # 检查模型是否已在本地缓存
        try:
            local_path = huggingface_hub.snapshot_download(
                _sim_model_name, local_files_only=True)
            _sim_model = SentenceTransformer(local_path)
            print(f"[rag_eval] 已加载本地语义模型：{_sim_model_name}")
            return _sim_model
        except Exception:
            # 本地没有缓存，不尝试下载（避免长时间超时），直接回退
            print("[rag_eval] 本地无 BGE 模型缓存，使用千问 embedding API 计算相似度")
            print(f"[rag_eval] 如需启用本地模型，运行：python -c \"from sentence_transformers import SentenceTransformer; SentenceTransformer('{_sim_model_name}')\"")
            _sim_model = "_dashscope_api"
            return _sim_model
    except ImportError:
        print("[rag_eval] 未安装 sentence-transformers，使用千问 embedding API")
        _sim_model = "_dashscope_api"
        return _sim_model


def _semantic_similarity(text_a: str, text_b: str) -> float:
    """计算两段文本的语义相似度（余弦相似度，范围 0~1）。

    参数：
        text_a: 文本A
        text_b: 文本B

    返回：
        0~1 的浮点数，越接近1越相似
    """
    if not text_a or not text_b:
        return 0.0

    model = _get_sim_model()

    if model == "_dashscope_api":
        # 回退方案：用千问 embedding API 计算
        from ai_rag import embed_texts, _cosine
        vecs = embed_texts([text_a, text_b])
        return _cosine(vecs[0], vecs[1])

    # 本地 BGE 模型
    import numpy as np
    emb_a = model.encode(text_a, normalize_embeddings=True)
    emb_b = model.encode(text_b, normalize_embeddings=True)
    score = float(np.dot(emb_a, emb_b))
    return max(0.0, min(1.0, score))


def _split_into_units(text: str, min_len: int = 12) -> List[str]:
    """把文本按句子切成语义单元，过滤掉过短的碎片。

    用于 Context Recall：把标准答案切成句子，看有多少句子被检索到了。

    参数：
        text: 待切分文本
        min_len: 最短句子长度，过滤掉"好的。"这种无意义碎片

    返回：
        句子列表
    """
    import re
    if not text:
        return []
    # 按句号、问号、感叹号、分号切分（保留标点）
    sentences = re.split(r'(?<=[。！？；])', text)
    return [s.strip() for s in sentences if len(s.strip()) >= min_len]


def calc_context_precision(retrieved_chunks: List[str], ground_truth: str,
                           threshold: float = 0.65) -> tuple:
    """计算 Context Precision（上下文精确率）。

    定义：检索返回的片段中，与标准答案真实相关的内容占比。

    计算方法：
      对每个检索到的片段，计算它与标准答案的语义相似度；
      相似度 ≥ threshold 判定为"相关"，否则为"噪声"。
      precision = 相关片段数 / 检索到的片段总数

    参数：
        retrieved_chunks: 检索到的片段文本列表
        ground_truth: 标准答案
        threshold: 相似度阈值，默认 0.65

    返回：
        (precision, detail_list)
        precision: 0~1 的精确率
        detail_list: 每个片段的 [(内容前50字, 相似度, 是否相关), ...]
    """
    if not retrieved_chunks or not ground_truth:
        return 0.0, []

    details = []
    relevant_count = 0
    for chunk in retrieved_chunks:
        sim = _semantic_similarity(chunk, ground_truth)
        is_rel = sim >= threshold
        if is_rel:
            relevant_count += 1
        details.append({
            "content": chunk[:80] + ("..." if len(chunk) > 80 else ""),
            "similarity": round(sim, 4),
            "relevant": is_rel,
        })

    precision = relevant_count / len(retrieved_chunks)
    return round(precision, 4), details


def calc_context_recall(retrieved_chunks: List[str], ground_truth: str,
                        threshold: float = 0.65) -> tuple:
    """计算 Context Recall（上下文召回率）。

    定义：标准答案中的关键信息，有多少被成功检索到了。

    计算方法：
      把标准答案切成句子（语义单元）；
      对每个句子，看它是否被任意一个检索片段覆盖（相似度 ≥ threshold）；
      recall = 被覆盖的句子数 / 标准答案句子总数

    参数：
        retrieved_chunks: 检索到的片段文本列表
        ground_truth: 标准答案
        threshold: 相似度阈值，默认 0.65

    返回：
        (recall, detail_list)
        recall: 0~1 的召回率
        detail_list: 每个句子的 [(句子, 最高相似度, 是否被覆盖), ...]
    """
    if not retrieved_chunks or not ground_truth:
        return 0.0, []

    gold_units = _split_into_units(ground_truth)
    if not gold_units:
        return 0.0, []

    details = []
    covered_count = 0
    for unit in gold_units:
        # 找这个句子和所有检索片段的最高相似度
        max_sim = max((_semantic_similarity(unit, c) for c in retrieved_chunks), default=0.0)
        is_covered = max_sim >= threshold
        if is_covered:
            covered_count += 1
        details.append({
            "unit": unit[:60] + ("..." if len(unit) > 60 else ""),
            "max_similarity": round(max_sim, 4),
            "covered": is_covered,
        })

    recall = covered_count / len(gold_units)
    return round(recall, 4), details


def calc_answer_similarity(ai_answer: str, ground_truth: str):
    """计算端到端语义相似度（AI答案 vs 标准答案）。

    这是最直观的端到端指标：AI 生成的答案和标准答案有多像。
    用 BGE 模型把两段文本转成向量，算余弦相似度。

    参数：
        ai_answer: AI 生成的答案
        ground_truth: 人工标注的标准答案

    返回：
        0~1 的相似度分数；如果 AI 答案为空或生成失败，返回 None（不参与平均）
    """
    if not ai_answer or not ai_answer.strip() or not ground_truth:
        return None
    return round(_semantic_similarity(ai_answer, ground_truth), 4)


def calc_faithfulness(ai_answer: str, retrieved_chunks: List[str]):
    """计算忠实度（Faithfulness）：AI 答案有多少是基于检索上下文的，有没有编造。

    实现方式：把 AI 答案按句子拆分，每个句子和所有检索片段算最高语义相似度，
    超过阈值（0.6）算"有依据"。忠实度 = 有依据的句子数 / 总句子数。

    分数低说明 AI 在"幻觉"——回答了上下文里没有的内容。

    参数：
        ai_answer: AI 生成的答案
        retrieved_chunks: 检索到的上下文片段列表

    返回：
        0~1 的忠实度分数；如果 AI 答案为空或无检索上下文，返回 None
    """
    if not ai_answer or not ai_answer.strip() or not retrieved_chunks:
        return None

    # 按句号/分号/问号/感叹号拆句子
    import re
    sentences = [s.strip() for s in re.split(r"[。；！？\n]", ai_answer) if s.strip()]
    if not sentences:
        return None

    context_text = " ".join(retrieved_chunks)
    supported = 0
    for sent in sentences:
        # 每个句子和检索上下文算相似度，超过阈值算有依据
        sim = _semantic_similarity(sent, context_text)
        if sim >= 0.6:
            supported += 1

    return round(supported / len(sentences), 4)


def calc_answer_relevancy(ai_answer: str, question: str):
    """计算答案相关性（Answer Relevancy）：AI 答案是否切题，有没有答非所问。

    实现方式：直接计算 AI 答案和用户问题的语义相似度。
    分数低说明 AI 在"跑题"——回答了和问题无关的内容。

    参数：
        ai_answer: AI 生成的答案
        question: 用户的原始问题

    返回：
        0~1 的相关性分数；如果 AI 答案为空，返回 None
    """
    if not ai_answer or not ai_answer.strip() or not question:
        return None
    return round(_semantic_similarity(ai_answer, question), 4)


# —— 查询类型：对应评估数据集"覆盖性"原则的三个维度 ——
#   fact    事实型：答案在某一处就能直接找到（"抽成比例是多少"）
#   reason  推理型：需要跨段落组合条件或多步推导（"好评率是怎么计算的"）
#   compare 对比型：需要比对两处信息才能回答（"提现冷却期和打赏到账有什么不同"）
# 抽题时按这个字段分层、每类保底覆盖，避免整类被漏掉。
QUERY_TYPE_LABELS = {"fact": "事实型", "reason": "推理型", "compare": "对比型"}
QUERY_TYPES = ("fact", "reason", "compare")


# —— 内置测试集（覆盖平台核心业务场景）——
# 每条：question（问题）、ground_truth（标准答案）、role（适用角色）、
#       query_type（查询类型，见上方说明）
DEFAULT_TEST_SET = [
    {
        "question": "平台抽成比例是多少？",
        "ground_truth": "平台抽成30%，打手实得70%。订单结单后金额先进入打手后台金额，提现时扣除平台抽成。",
        "role": "boss",
        "query_type": "fact",
    },
    {
        "question": "打手提现的冷却期是几天？",
        "ground_truth": "打手获得的金额有30天冷却期，冷却期满后才能申请提现。提现需在「我的工作」→「提现中心」操作。",
        "role": "player",
        "query_type": "fact",
    },
    {
        "question": "大狗币和人民币的兑换比例是多少？",
        "ground_truth": "大狗币与人民币比例为1:1，充值1元人民币获得1大狗币。老板点单消耗大狗币，订单结单后到达打手后台自动转换为人民币。",
        "role": "boss",
        "query_type": "fact",
    },
    {
        "question": "打赏有什么限制？",
        "ground_truth": "老板结单后可以给打手打赏，打赏上限不可超过订单单价的30%，打赏金额无冷却期，直接进入打手后台金额。",
        "role": "boss",
        "query_type": "fact",
    },
    {
        "question": "打手有哪些等级？",
        "ground_truth": "打手分为娱乐陪和技术陪两大类。技术陪由低到高分为：985、211、大专、魔王护、明星护五个等级。打手可自己添加标签，由管理员或客服审核通过后对外展示。",
        "role": "boss",
        "query_type": "fact",
    },
    {
        "question": "好评率是怎么计算的？",
        "ground_truth": "好评率 = 好评订单数 / 总评价订单数。结单后三天没评价的订单默认为好评；老板投诉的订单自动记为差评，若打手申诉成功则撤销该差评，计算好评率时屏蔽申诉成功的订单。没有被评价过的打手好评率显示为\"-\"。",
        "role": "boss",
        "query_type": "reason",
    },
    {
        "question": "连续输错密码会怎样？",
        "ground_truth": "连续输错密码5次会锁定账户10分钟，10分钟后自动解锁。锁定期间无法登录。如忘记密码可点击「忘记密码」重置。",
        "role": "boss",
        "query_type": "fact",
    },
    {
        "question": "怎么充值大狗币？",
        "ground_truth": "老板在「充值中心」选择充值金额，选择后弹出支付方式，支持微信、支付宝等。充值满100送10大狗币，满300送50，满500送120，满1000送300。充值后立即到账。",
        "role": "boss",
        "query_type": "fact",
    },
    {
        "question": "订单的流程是什么？",
        "ground_truth": "老板点单 → 打手接单 → 打手开始服务 → 打手提交结单 → 老板审核确认结单 → 金额转入打手后台。老板也可以提价备注，打手可根据备注自行决定是否接单。客服可人工派单。",
        "role": "boss",
        "query_type": "fact",
    },
    {
        "question": "被拉黑了会怎么样？",
        "ground_truth": "管理员可以拉黑老板和打手账户。被拉黑后，打手的后台金额会转入公司后台，并在处罚公告里发布拉黑通知。被拉黑账户无法登录和使用平台功能。",
        "role": "player",
        "query_type": "reason",
    },
    # —— 以下为第二版扩充题（依据《用户服务协议》《打手服务规范》《退款投诉争议规则》）——
    {
        "question": "打手有哪些禁止行为？",
        "ground_truth": "打手禁止代练账号共享、使用外挂、代充与套现、引导私下交易、辱骂骚扰、恶意刷单、虚假战绩承诺等。违反者按情节给予警告、停单3天或封禁账号处理，构成严重违规的永久封禁并扣除后台金额。",
        "role": "player",
        "query_type": "fact",
    },
    {
        "question": "打手无故拒单会怎么处理？",
        "ground_truth": "打手收到派单后应在规定时间内确认或拒绝，不得无故拒单。无故拒单属于中度违规，平台处以停单3天；因打手无故拒单导致订单取消的，全额退款并对打手按中度违规处理。",
        "role": "player",
        "query_type": "fact",
    },
    {
        "question": "打手的昵称、简介和标签有什么长度限制？",
        "ground_truth": "打手昵称最长20个字符，简介最长100个字符，标签最长20个字符。昵称、简介与标签不得包含违法、低俗、侮辱、广告、联系方式及误导性内容。",
        "role": "player",
        "query_type": "fact",
    },
    {
        "question": "打手被处罚后怎么申诉？需要提供哪些材料？",
        "ground_truth": "打手对处罚有异议的，可在收到处罚通知后3日内通过客服渠道提交申诉，材料包括订单号、聊天记录、录屏、系统通知截图等。管理员审核后作出最终决定。同一事项仅可申诉一次，有新证据可在驳回后7日内申请复核。",
        "role": "player",
        "query_type": "reason",
    },
    {
        "question": "收到投诉后多久响应？处理时限是多久？",
        "ground_truth": "客服在收到投诉后1个工作日内首次响应，告知受理结果与后续流程。投诉应在订单结束后3日内发起，涉及作弊、诈骗等严重违规的不受3日期限限制。",
        "role": "service",
        "query_type": "fact",
    },
    {
        "question": "哪些情况下老板可以申请退款？",
        "ground_truth": "订单尚未派单、或在打手确认前取消的，可全额退款；打手接单后长时间未开始服务、无故拒单、使用外挂作弊、辱骂骚扰老板或引导私下交易的，老板可申请退款，平台核实后支持。已确认结单的订单除存在违规情形外，原则上不予退款。",
        "role": "service",
        "query_type": "fact",
    },
    {
        "question": "结单争议怎么处理？争议期间费用由谁保管？",
        "ground_truth": "老板对结单有异议的，应当在确认前于订单页面发起结单争议。客服核对订单信息、服务记录、双方陈述与证据材料后处理，处理时限一般为受理后3个工作日内给出处理意见。争议期间订单费用继续由平台托管，打手不得催促或威胁老板确认结单。",
        "role": "service",
        "query_type": "reason",
    },
    {
        "question": "平台对违规行为有哪几档处罚？",
        "ground_truth": "平台实行三档处罚体系：警告、停单3天、封禁账号。言语不当、消极服务等轻微违规给予警告，警告累计3次升级为停单处罚；无故拒单、态度恶劣等中度违规处以停单3天；作弊、诈骗、恶意刷单等严重违规永久封禁账号并扣除后台金额，账号被拉黑后后台金额转入公司账户。",
        "role": "admin",
        "query_type": "fact",
    },
    {
        "question": "用户对处罚决定有异议，申诉流程是怎样的？",
        "ground_truth": "用户可在收到处罚通知后3日内通过客服渠道提交申诉，并提供相应证据。管理员独立审核，结合订单记录、双方陈述与证据材料作出最终决定。申诉期间原处罚一般继续执行，管理员认定处罚确有错误的，予以撤销或调整。",
        "role": "admin",
        "query_type": "fact",
    },
    {
        "question": "恶意投诉会怎么处理？",
        "ground_truth": "恶意投诉指明知投诉事由不实、以索取不当利益或损害他人为目的、反复提交无依据投诉或伪造证据投诉等行为。对恶意投诉的老板，可视情节给予警告、限制投诉权限、限制下单或封禁账号；对恶意投诉的打手，可视情节给予警告、停单3天或封禁账号，涉及伪造证据的从重处理。",
        "role": "admin",
        "query_type": "reason",
    },
    # —— 第三版扩充题：对比型（需要比对两处信息才能回答）——
    {
        "question": "打手提现的到账规则，和老板打赏的到账规则有什么不同？",
        "ground_truth": "两者到账规则不同：打手通过订单获得的金额有30天冷却期，冷却期满后才能申请提现，提现时平台扣除30%抽成、打手实得70%；而老板结单后的打赏金额无冷却期，直接进入打手后台金额，且打赏上限不可超过订单单价的30%。",
        "role": "player",
        "query_type": "compare",
    },
    {
        "question": "轻微违规和中度违规分别会受到什么处罚？",
        "ground_truth": "平台三档处罚为警告、停单3天、封禁账号。言语不当、消极服务等轻微违规给予警告，警告累计3次升级为停单处罚；无故拒单、态度恶劣等中度违规处以停单3天；作弊、诈骗、恶意刷单等严重违规永久封禁账号并扣除后台金额。",
        "role": "service",
        "query_type": "compare",
    },
    {
        "question": "老板和打手分别会因为什么被处罚？处理方式有什么不同？",
        "ground_truth": "老板侧主要针对恶意投诉：明知投诉事由不实、以索取不当利益或损害他人为目的、反复提交无依据投诉或伪造证据的，可视情节给予警告、限制投诉权限、限制下单或封禁账号。打手侧范围更广：代练账号共享、使用外挂、引导私下交易、辱骂骚扰、恶意刷单等禁止行为按情节给予警告、停单3天或封禁账号；无故拒单属中度违规处以停单3天；涉及伪造证据的从重处理。",
        "role": "admin",
        "query_type": "compare",
    },
    {
        "question": "打手无故拒单，对老板和对打手分别有什么后果？",
        "ground_truth": "对打手：无故拒单属于中度违规，平台处以停单3天。对老板：因打手无故拒单导致订单取消的，全额退款。打手收到派单后应在规定时间内确认或拒绝，不得无故拒单。",
        "role": "player",
        "query_type": "compare",
    },
    {
        "question": "老板点单时能看到打手的哪些信息？哪些信息看不到？",
        "ground_truth": "老板点单时可以看到打手的公开数据：昵称、头像、简介、等级（娱乐陪/技术陪及技术陪子等级）、经审核通过的自定义标签、接单次数、好评率，以及其他老板留下的评价；提价备注会随订单一起展示给打手。打手的后台金额等敏感信息对老板隐藏，只有本人、客服和管理员可见。",
        "role": "boss",
        "query_type": "compare",
    },
]


def init_eval_questions(db):
    """把内置测试题初始化到数据库（幂等：已存在的不重复插入）。

    在后端启动时调用一次，确保 ai_eval_questions 表有初始数据。
    后续管理员可以在前端增删改查，不再依赖硬编码。

    除了插入新题，还会给老库里的既有题目回填 query_type
    —— 该字段是 V4.7.0 新增的（对应数据集"覆盖性"原则），
    之前入库的题目这一列是空的，不回填就没有分层抽样的依据。
    """
    from models import AiEvalQuestion
    existing = {q.question.strip(): q for q in db.query(AiEvalQuestion).all()}
    added = 0
    backfilled = 0
    for item in DEFAULT_TEST_SET:
        q = item["question"].strip()
        qtype = item.get("query_type", "fact")
        row = existing.get(q)
        if row is not None:
            # 回填老库。注意不能只看"值是否合法"：加列时 MySQL 会给既有行
            # 填上默认值 'fact'，于是推理型/对比型全被压成事实型，而 'fact'
            # 本身是合法值，那种判断法查不出问题。
            # 所以拿内置标注来校准：内置集里不是 fact、库里却还是 fact 的，
            # 就是没回填过。只处理能在内置集里匹配到的题，管理员自建题不受影响。
            if qtype != "fact" and (row.query_type or "fact") == "fact":
                row.query_type = qtype
                backfilled += 1
            continue
        db.add(AiEvalQuestion(
            question=item["question"],
            ground_truth=item["ground_truth"],
            role=item.get("role", "boss"),
            # 题目自带 category 时优先使用，否则按关键词自动猜测
            category=item.get("category") or _guess_category(item["question"]),
            query_type=qtype,
            enabled=1,
        ))
        added += 1
    if added or backfilled:
        db.commit()
    if backfilled:
        print(f"[eval] 题库回填查询类型：{backfilled} 道")
    return added


def _guess_category(question: str) -> str:
    """根据问题关键词自动猜测分类。

    判断顺序有讲究：先判断更具体的类别（退款争议、处罚申诉），
    再判断宽泛的（投诉、打手），避免"打手被处罚"被误归到"打手管理"。
    """
    q = question or ""
    if any(k in q for k in ["退款", "争议"]):
        return "退款争议"
    if any(k in q for k in ["充值", "大狗币", "支付", "金额", "费用"]):
        return "充值计费"
    if any(k in q for k in ["处罚", "申诉", "拉黑", "封禁"]):
        return "处罚规则"
    if any(k in q for k in ["订单", "点单", "接单", "结单", "拒单", "派单", "流程"]):
        return "订单流程"
    if any(k in q for k in ["提现", "后台金额", "抽成", "结算", "打赏"]):
        return "提现结算"
    if any(k in q for k in ["密码", "登录", "锁定", "账户", "注册"]):
        return "账号安全"
    if any(k in q for k in ["好评", "评价", "投诉"]):
        return "评价投诉"
    if any(k in q for k in ["等级", "标签", "打手", "昵称", "简介"]):
        return "打手管理"
    return "通用"


def get_test_questions(db, role: str = None, only_enabled: bool = True) -> List[Dict]:
    """从数据库读取测试题（替代硬编码的 DEFAULT_TEST_SET）。

    参数：
        role: 只返回指定角色的题目，None 表示返回全部
        only_enabled: 只返回启用的题目（默认 True）
    返回：
        [{"id": 题目ID, "question": 问题, "ground_truth": 标准答案,
          "role": 角色, "category": 分类, "query_type": 查询类型}, ...]
        id 用于「固定题集」记录本次抽中了哪几道题；
        query_type 用于分层抽样（保证事实型/推理型/对比型都被覆盖）。
    """
    from models import AiEvalQuestion
    query = db.query(AiEvalQuestion)
    if only_enabled:
        query = query.filter(AiEvalQuestion.enabled == 1)
    if role:
        query = query.filter(AiEvalQuestion.role == role)
    rows = query.order_by(AiEvalQuestion.id.asc()).all()
    return [
        {"id": r.id, "question": r.question, "ground_truth": r.ground_truth,
         "role": r.role, "category": r.category or "通用",
         "query_type": r.query_type or "fact"}
        for r in rows
    ]


def evaluate_rag(db, test_set: List[Dict] = None, role: str = "boss",
                 generate_answer: bool = True, ai_model: str = None,
                 fixed_set_version: int = 0) -> Dict:
    """运行 RAG 量化评估，返回每条问答的详细得分和整体平均分。

    执行流程：
      1. 对每个测试问题，调用 ModularRAG 检索相关片段
      2.（可选）调用千问大模型生成 AI 答案
      3. 计算 Context Precision、Context Recall、语义相似度
      4. 汇总整体平均分

    参数：
        db: 数据库会话
        test_set: 测试问答对列表，默认用内置 DEFAULT_TEST_SET
        role: 以哪个角色身份检索（影响 FAQ 角色过滤），默认 boss
        generate_answer: 是否调用大模型生成答案并计算端到端相似度，默认 True
        ai_model: 生成答案用的模型，默认用系统参数配置

    返回：
        {
            "total": 测试题数,
            "avg_precision": 平均上下文精确率,
            "avg_recall": 平均上下文召回率,
            "avg_similarity": 平均端到端语义相似度（未生成答案时为 None）,
            "items": [
                {
                    "question": 问题,
                    "ground_truth": 标准答案,
                    "retrieved_chunks": [检索到的片段...],
                    "context_precision": 精确率,
                    "precision_detail": [...],
                    "context_recall": 召回率,
                    "recall_detail": [...],
                    "ai_answer": AI答案（可选）,
                    "answer_similarity": 端到端相似度（可选）,
                },
                ...
            ],
            "elapsed_seconds": 耗时,
        }
    """
    from rag.pipeline import ModularRAG
    from models import User

    # 优先用传入的 test_set；否则从数据库读取启用的测试题；数据库为空时回退到内置默认集
    # 角色过滤：role 为具体角色时只评估该角色的题目（分角色题库）；
    # role 为空/None/"all" 时评估全部启用的题目。每道题仍用自己记录的 role 去检索。
    if test_set is None:
        role_filter = None if (not role or role == "all") else role
        test_set = get_test_questions(db, role=role_filter)
        if not test_set:
            test_set = DEFAULT_TEST_SET
    # 记录本次实际考了哪几道题。题集表会不断新增版本，
    # 不在这里留一份，事后就没法还原当时的评估依据。
    question_ids = [it.get("id") for it in test_set if it.get("id")]

    rag = ModularRAG(db)
    results = []
    start = time.time()

    # 图谱通道需要知道「当前是谁在问」——老板/打手只能看到自己那个节点。
    # 评估场景没有登录用户，这里按题目角色取该角色的第一个真实账户。
    # 不补这一步，username 为空，图谱通道对 boss/player 题目会全程空转，
    # 「图谱开关开/关」对比就永远测不出差异。
    username_by_role = {}
    for role_key in ("boss", "player"):
        row = db.query(User).filter(User.role == role_key).order_by(User.id).first()
        if row:
            username_by_role[role_key] = row.username

    for i, item in enumerate(test_set):
        question = item["question"]
        ground_truth = item["ground_truth"]
        q_role = item.get("role") or role or "boss"

        print(f"[rag_eval] 评估第 {i+1}/{len(test_set)} 题：{question[:30]}...")

        # ① 检索：用 debug 模式拿到检索到的原始片段
        debug = {}
        context = rag.query(question, q_role, debug=debug,
                            username=username_by_role.get(q_role))

        # 从 debug 信息中提取检索到的片段文本
        retrieved_chunks = _extract_chunks_from_debug(debug, db)
        if not retrieved_chunks and context:
            # 兜底：如果 debug 里没拿到，就用整个 context（粗略）
            retrieved_chunks = [context]

        # ② 计算检索质量指标
        precision, prec_detail = calc_context_precision(retrieved_chunks, ground_truth)
        recall, recall_detail = calc_context_recall(retrieved_chunks, ground_truth)

        row = {
            "question": question,
            "ground_truth": ground_truth,
            "role": q_role,
            "retrieved_count": len(retrieved_chunks),
            "retrieved_chunks": retrieved_chunks[:3],  # 只存前3条，避免结果太大
            "context_precision": precision,
            "precision_detail": prec_detail,
            "context_recall": recall,
            "recall_detail": recall_detail,
        }

        # ③（可选）生成 AI 答案并计算端到端相似度
        if generate_answer:
            try:
                import ai_service
                # 把检索到的上下文拼进 system prompt，让 AI 基于上下文回答
                # 优先用 rag.query() 返回的最终上下文——它就是线上真正喂给
                # 大模型的那份文本（已过 top_k / max_chars / 相关性过滤）。
                # 早前是从 debug 重拼并取前 3 段，而图谱事实排在向量、关键词
                # 之后，永远进不了前 3 段，等于"图谱开了但生成阶段看不到"，
                # 端到端指标自然体现不出图谱的作用。
                context_text = (context or "").strip()
                if not context_text:
                    context_text = ("\n\n".join(retrieved_chunks[:3])
                                    if retrieved_chunks else "（无检索上下文）")
                system_prompt = (
                    "你是「大狗嚼电竞」的AI客服布鲁斯。请根据下面的参考资料回答用户问题。"
                    "如果资料中没有相关信息，请如实说明，不要编造。\n\n"
                    "【参考资料】\n" + context_text
                )
                resp = ai_service.chat(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": question},
                    ],
                    model=ai_model,
                    temperature=0.0,   # 评估用低温度，结果稳定可复现
                    max_tokens=500,
                )
                # chat() 返回 dict：{ok, reply, error, ...}
                if not resp.get("ok"):
                    raise RuntimeError(resp.get("error") or "AI 返回失败")
                ai_answer = (resp.get("reply") or "").strip()
                if not ai_answer:
                    raise RuntimeError("AI 返回了空答案")
                sim = calc_answer_similarity(ai_answer, ground_truth)
                faith = calc_faithfulness(ai_answer, retrieved_chunks)
                relev = calc_answer_relevancy(ai_answer, question)
                row["ai_answer"] = ai_answer[:500]  # 截断，避免结果太大
                row["answer_similarity"] = sim
                row["faithfulness"] = faith
                row["answer_relevancy"] = relev
            except Exception as e:
                print(f"[rag_eval] AI 答案生成失败：{e}")
                row["ai_answer"] = ""
                row["answer_similarity"] = None  # 生成失败不参与平均，不记0分
                row["faithfulness"] = None
                row["answer_relevancy"] = None
                row["answer_error"] = str(e)

        results.append(row)

    elapsed = round(time.time() - start, 2)

    # ④ 汇总平均分
    avg_precision = round(sum(r["context_precision"] for r in results) / len(results), 4) if results else 0
    avg_recall = round(sum(r["context_recall"] for r in results) / len(results), 4) if results else 0
    sim_scores = [r["answer_similarity"] for r in results
                  if r.get("answer_similarity") is not None]
    avg_similarity = round(sum(sim_scores) / len(sim_scores), 4) if sim_scores else None
    faith_scores = [r["faithfulness"] for r in results
                    if r.get("faithfulness") is not None]
    avg_faithfulness = round(sum(faith_scores) / len(faith_scores), 4) if faith_scores else None
    relev_scores = [r["answer_relevancy"] for r in results
                    if r.get("answer_relevancy") is not None]
    avg_relevancy = round(sum(relev_scores) / len(relev_scores), 4) if relev_scores else None

    # 读取当前重排序模式，记录到评估结果中
    import config_service
    rerank_enabled = bool(config_service.get_config("rag_module_rerank", db, True))
    rerank_mode = str(config_service.get_config("rag_rerank_mode", db, "rule")).strip().lower() if rerank_enabled else "off"

    # 收集 RAG 参数快照（用于 A/B 对比时展示参数差异）
    # 自动从 CONFIG_META 收集 RAG 相关分组的所有参数，避免硬编码参数名遗漏
    rag_params = {}
    RAG_PARAM_GROUPS = {"AI 知识库", "RAG 模块开关", "查询优化", "Self-RAG"}
    try:
        for key, meta in config_service.CONFIG_META.items():
            if meta.get("group") in RAG_PARAM_GROUPS:
                val = config_service.get_config(key, db, None)
                if val is not None:
                    rag_params[key] = val
    except Exception as e:
        print(f"[rag_eval] 收集RAG参数快照失败：{e}")

    result = {
        "total": len(results),
        "avg_precision": avg_precision,
        "avg_recall": avg_recall,
        "avg_similarity": avg_similarity,
        "avg_faithfulness": avg_faithfulness,
        "avg_answer_relevancy": avg_relevancy,
        "items": results,
        "elapsed_seconds": elapsed,
        "threshold": 0.65,
        "model": _sim_model_name if _sim_model != "_dashscope_api" else "千问 embedding API",
        "rerank_mode": rerank_mode,
        "config_snapshot": rag_params,
        "question_ids": question_ids,
        "fixed_set_version": fixed_set_version,
    }

    # 自动保存评估历史到数据库
    try:
        result["history_id"] = save_eval_history(db, result, role=role, generate_answer=generate_answer)
    except Exception as e:
        print(f"[rag_eval] 保存评估历史失败（不影响评估结果）：{e}")

    return result


def _extract_chunks_from_debug(debug: dict, db) -> List[str]:
    """从 RAG 检索的 debug 信息中提取检索到的片段文本。

    debug 里的 reranked_keys 是最终排序后的结果，
    但它只有 key（source_type, source_key, chunk_index），需要去数据库查内容。
    简化处理：从 per_query_results 的 vector_hits 和 keyword_hits 里提取内容。
    """
    chunks = []
    seen = set()

    # 从向量检索结果提取
    for pq in (debug.get("per_query_results") or []):
        for vh in (pq.get("vector_hits") or []):
            content = vh.get("content", "")
            if content and content not in seen:
                chunks.append(content)
                seen.add(content)

    # 从关键词检索结果提取（FAQ 的问答对）
    for pq in (debug.get("per_query_results") or []):
        for kh in (pq.get("keyword_hits") or []):
            q = kh.get("question", "")
            if q and q not in seen:
                chunks.append(f"问：{q}")
                seen.add(q)

    # 从图谱检索结果提取（实体关系事实）。
    # 图谱是第三路召回，漏掉它，指标就只反映了向量+关键词两路的水平，
    # 「图谱开关开/关」的对比也就失去了依据。
    for gh in (debug.get("graph_hits") or []):
        content = gh.get("content", "")
        if content and content not in seen:
            chunks.append(content)
            seen.add(content)

    return chunks


def print_eval_report(result: Dict):
    """把评估结果打印成可读的表格（命令行用）。

    参数：
        result: evaluate_rag() 的返回值
    """
    print("\n" + "=" * 70)
    print("  RAG 量化评估报告")
    print("=" * 70)
    print(f"  测试题数：{result['total']}")
    print(f"  语义模型：{result['model']}（相关阈值 {result['threshold']}）")
    print(f"  总耗时：{result['elapsed_seconds']} 秒")
    print("-" * 70)
    print(f"  {'指标':<20} {'得分':<10} {'参考阈值':<15} {'评价'}")
    print("-" * 70)

    def verdict(score, good, ok):
        if score >= good:
            return "优秀"
        elif score >= ok:
            return "合格"
        else:
            return "待优化"

    print(f"  {'Context Precision':<20} {result['avg_precision']:<10.4f} {'≥0.85优秀/≥0.7合格':<15} {verdict(result['avg_precision'], 0.85, 0.7)}")
    print(f"  {'Context Recall':<20} {result['avg_recall']:<10.4f} {'≥0.8合格':<15} {verdict(result['avg_recall'], 0.8, 0.6)}")
    if result['avg_similarity'] is not None:
        print(f"  {'端到端语义相似度':<20} {result['avg_similarity']:<10.4f} {'≥0.85优秀/≥0.7合格':<15} {verdict(result['avg_similarity'], 0.85, 0.7)}")
    print("-" * 70)

    print("\n  逐题详情：")
    for i, item in enumerate(result["items"], 1):
        print(f"\n  [{i}] {item['question']}")
        print(f"      检索到 {item['retrieved_count']} 段 | Precision={item['context_precision']} | Recall={item['context_recall']}")
        if "answer_similarity" in item:
            print(f"      AI答案相似度={item['answer_similarity']}")
            if item.get("ai_answer"):
                print(f"      AI答案：{item['ai_answer'][:80]}...")

    print("\n" + "=" * 70)


def save_eval_history(db, result: Dict, role: str = "boss", generate_answer: bool = True):
    """把评估结果存入 ai_eval_history 表，用于历史趋势对比。

    参数：
        db: 数据库会话
        result: evaluate_rag() 的返回值
        role: 以哪个角色身份评估
        generate_answer: 是否生成了AI答案
    """
    import json
    from models import AiEvalHistory

    # 逐题详情精简后存 JSON（去掉 retrieved_chunks 等大字段，避免数据过大）
    items_slim = []
    for item in result.get("items", []):
        items_slim.append({
            "question": item.get("question", ""),
            "ground_truth": item.get("ground_truth", "")[:200],
            "retrieved_count": item.get("retrieved_count", 0),
            "context_precision": item.get("context_precision", 0),
            "context_recall": item.get("context_recall", 0),
            "answer_similarity": item.get("answer_similarity"),
            "faithfulness": item.get("faithfulness"),
            "answer_relevancy": item.get("answer_relevancy"),
            "ai_answer": (item.get("ai_answer") or "")[:300],
            "answer_error": item.get("answer_error", ""),
        })

    record = AiEvalHistory(
        role=role,
        generate_answer=1 if generate_answer else 0,
        total=result.get("total", 0),
        avg_precision=result.get("avg_precision", 0),
        avg_recall=result.get("avg_recall", 0),
        avg_similarity=result.get("avg_similarity"),
        avg_faithfulness=result.get("avg_faithfulness"),
        avg_answer_relevancy=result.get("avg_answer_relevancy"),
        elapsed_seconds=result.get("elapsed_seconds", 0),
        model=result.get("model", ""),
        rerank_mode=result.get("rerank_mode", "rule"),
        config_json=json.dumps(result.get("config_snapshot", {}), ensure_ascii=False),
        items_json=json.dumps(items_slim, ensure_ascii=False),
        question_ids=json.dumps(result.get("question_ids", []), ensure_ascii=False),
        fixed_set_version=result.get("fixed_set_version", 0),
    )
    db.add(record)
    db.commit()
    print(f"[rag_eval] 评估结果已存入历史记录（ID: {record.id}）")
    return record.id


def get_eval_history(db, limit: int = 20) -> List[Dict]:
    """获取最近的评估历史记录（不包含逐题详情，用于列表展示）。"""
    from models import AiEvalHistory
    import json as _json
    records = db.query(AiEvalHistory).order_by(AiEvalHistory.id.desc()).limit(limit).all()
    result = []
    for r in records:
        try:
            cfg = _json.loads(r.config_json or "{}")
        except Exception:
            cfg = {}
        result.append({
            "id": r.id,
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else "",
            "role": r.role,
            "generate_answer": r.generate_answer,
            "total": r.total,
            "avg_precision": r.avg_precision,
            "avg_recall": r.avg_recall,
            "avg_similarity": r.avg_similarity,
            "avg_faithfulness": r.avg_faithfulness,
            "avg_answer_relevancy": r.avg_answer_relevancy,
            "elapsed_seconds": r.elapsed_seconds,
            "model": r.model,
            "rerank_mode": r.rerank_mode or "rule",
            "config_snapshot": cfg,
        })
    return result


def get_eval_detail(db, eval_id: int):
    """获取单次评估的完整详情（含逐题详情）。"""
    from models import AiEvalHistory
    import json
    record = db.query(AiEvalHistory).filter(AiEvalHistory.id == eval_id).first()
    if not record:
        return None
    items = []
    try:
        items = json.loads(record.items_json or "[]")
    except Exception:
        items = []
    try:
        cfg = json.loads(record.config_json or "{}")
    except Exception:
        cfg = {}
    return {
        "id": record.id,
        "created_at": record.created_at.strftime("%Y-%m-%d %H:%M:%S") if record.created_at else "",
        "role": record.role,
        "generate_answer": record.generate_answer,
        "total": record.total,
        "avg_precision": record.avg_precision,
        "avg_recall": record.avg_recall,
        "avg_similarity": record.avg_similarity,
        "avg_faithfulness": record.avg_faithfulness,
        "avg_answer_relevancy": record.avg_answer_relevancy,
        "elapsed_seconds": record.elapsed_seconds,
        "model": record.model,
        "rerank_mode": record.rerank_mode or "rule",
        "threshold": 0.65,
        "config_snapshot": cfg,
        "items": items,
    }


if __name__ == "__main__":
    # 命令行直接运行：评估当前 RAG 系统
    from database import SessionLocal
    db = SessionLocal()
    try:
        result = evaluate_rag(db, generate_answer=True)
        print_eval_report(result)
    finally:
        db.close()
