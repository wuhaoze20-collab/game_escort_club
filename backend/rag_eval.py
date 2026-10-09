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
from typing import List, Dict, Optional

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
            print(f"[rag_eval] 本地无 BGE 模型缓存，使用千问 embedding API 计算相似度")
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


# —— 内置测试集（覆盖平台核心业务场景）——
# 每条：question（问题）、ground_truth（标准答案）、role（适用角色）
DEFAULT_TEST_SET = [
    {
        "question": "平台抽成比例是多少？",
        "ground_truth": "平台抽成30%，打手实得70%。订单结单后金额先进入打手后台金额，提现时扣除平台抽成。",
        "role": "boss",
    },
    {
        "question": "打手提现的冷却期是几天？",
        "ground_truth": "打手获得的金额有30天冷却期，冷却期满后才能申请提现。提现需在「我的工作」→「提现中心」操作。",
        "role": "player",
    },
    {
        "question": "大狗币和人民币的兑换比例是多少？",
        "ground_truth": "大狗币与人民币比例为1:1，充值1元人民币获得1大狗币。老板点单消耗大狗币，订单结单后到达打手后台自动转换为人民币。",
        "role": "boss",
    },
    {
        "question": "打赏有什么限制？",
        "ground_truth": "老板结单后可以给打手打赏，打赏上限不可超过订单单价的30%，打赏金额无冷却期，直接进入打手后台金额。",
        "role": "boss",
    },
    {
        "question": "打手有哪些等级？",
        "ground_truth": "打手分为娱乐陪和技术陪两大类。技术陪由低到高分为：985、211、大专、魔王护、明星护五个等级。打手可自己添加标签，由管理员或客服审核通过后对外展示。",
        "role": "boss",
    },
    {
        "question": "好评率是怎么计算的？",
        "ground_truth": "好评率 = 好评订单数 / 总评价订单数。结单后三天没评价的订单默认为好评；老板投诉的订单自动记为差评，若打手申诉成功则撤销该差评，计算好评率时屏蔽申诉成功的订单。没有被评价过的打手好评率显示为\"-\"。",
        "role": "boss",
    },
    {
        "question": "连续输错密码会怎样？",
        "ground_truth": "连续输错密码5次会锁定账户10分钟，10分钟后自动解锁。锁定期间无法登录。如忘记密码可点击「忘记密码」重置。",
        "role": "boss",
    },
    {
        "question": "怎么充值大狗币？",
        "ground_truth": "老板在「充值中心」选择充值金额，选择后弹出支付方式，支持微信、支付宝等。充值满100送10大狗币，满300送50，满500送120，满1000送300。充值后立即到账。",
        "role": "boss",
    },
    {
        "question": "订单的流程是什么？",
        "ground_truth": "老板点单 → 打手接单 → 打手开始服务 → 打手提交结单 → 老板审核确认结单 → 金额转入打手后台。老板也可以提价备注，打手可根据备注自行决定是否接单。客服可人工派单。",
        "role": "boss",
    },
    {
        "question": "被拉黑了会怎么样？",
        "ground_truth": "管理员可以拉黑老板和打手账户。被拉黑后，打手的后台金额会转入公司后台，并在处罚公告里发布拉黑通知。被拉黑账户无法登录和使用平台功能。",
        "role": "player",
    },
]


def init_eval_questions(db):
    """把内置测试题初始化到数据库（幂等：已存在的不重复插入）。

    在后端启动时调用一次，确保 ai_eval_questions 表有初始数据。
    后续管理员可以在前端增删改查，不再依赖硬编码。
    """
    from models import AiEvalQuestion
    existing = {q.question.strip(): q for q in db.query(AiEvalQuestion).all()}
    added = 0
    for item in DEFAULT_TEST_SET:
        q = item["question"].strip()
        if q in existing:
            continue
        db.add(AiEvalQuestion(
            question=item["question"],
            ground_truth=item["ground_truth"],
            role=item.get("role", "boss"),
            category=_guess_category(item["question"]),
            enabled=1,
        ))
        added += 1
    if added:
        db.commit()
    return added


def _guess_category(question: str) -> str:
    """根据问题关键词自动猜测分类。"""
    q = question or ""
    if any(k in q for k in ["充值", "大狗币", "支付", "金额", "费用"]):
        return "充值计费"
    if any(k in q for k in ["订单", "点单", "接单", "结单", "流程"]):
        return "订单流程"
    if any(k in q for k in ["提现", "后台金额", "抽成"]):
        return "提现结算"
    if any(k in q for k in ["密码", "登录", "锁定", "账户", "注册"]):
        return "账号安全"
    if any(k in q for k in ["好评", "评价", "投诉", "申诉"]):
        return "评价投诉"
    if any(k in q for k in ["等级", "标签", "打手"]):
        return "打手管理"
    if any(k in q for k in ["拉黑", "处罚", "封禁"]):
        return "处罚规则"
    return "通用"


def get_test_questions(db, role: str = None, only_enabled: bool = True) -> List[Dict]:
    """从数据库读取测试题（替代硬编码的 DEFAULT_TEST_SET）。

    参数：
        role: 只返回指定角色的题目，None 表示返回全部
        only_enabled: 只返回启用的题目（默认 True）
    返回：
        [{"question": ..., "ground_truth": ..., "role": ...}, ...]
    """
    from models import AiEvalQuestion
    query = db.query(AiEvalQuestion)
    if only_enabled:
        query = query.filter(AiEvalQuestion.enabled == 1)
    if role:
        query = query.filter(AiEvalQuestion.role == role)
    rows = query.order_by(AiEvalQuestion.id.asc()).all()
    return [
        {"question": r.question, "ground_truth": r.ground_truth, "role": r.role}
        for r in rows
    ]


def evaluate_rag(db, test_set: List[Dict] = None, role: str = "boss",
                 generate_answer: bool = True, ai_model: str = None) -> Dict:
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

    # 优先用传入的 test_set；否则从数据库读取启用的测试题；数据库为空时回退到内置默认集
    if test_set is None:
        test_set = get_test_questions(db, role=role)
        if not test_set:
            test_set = DEFAULT_TEST_SET
    rag = ModularRAG(db)
    results = []
    start = time.time()

    for i, item in enumerate(test_set):
        question = item["question"]
        ground_truth = item["ground_truth"]
        q_role = item.get("role", role)

        print(f"[rag_eval] 评估第 {i+1}/{len(test_set)} 题：{question[:30]}...")

        # ① 检索：用 debug 模式拿到检索到的原始片段
        debug = {}
        context = rag.query(question, q_role, debug=debug)

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
                context_text = "\n\n".join(retrieved_chunks[:3]) if retrieved_chunks else "（无检索上下文）"
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
    import ai_service
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
        items_json=json.dumps(items_slim, ensure_ascii=False),
    )
    db.add(record)
    db.commit()
    print(f"[rag_eval] 评估结果已存入历史记录（ID: {record.id}）")
    return record.id


def get_eval_history(db, limit: int = 20) -> List[Dict]:
    """获取最近的评估历史记录（不包含逐题详情，用于列表展示）。"""
    from models import AiEvalHistory
    records = db.query(AiEvalHistory).order_by(AiEvalHistory.id.desc()).limit(limit).all()
    return [{
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
    } for r in records]


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
