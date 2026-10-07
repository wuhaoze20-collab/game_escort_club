# -*- coding: utf-8 -*-
"""查询优化器：子查询分解、后退提示生成、查询重写、查询增强。

五种技术可以组合使用，也可以单独启用（通过 config_service 控制）。
所有优化都有降级保护：大模型调用失败时退回原问题，不会让检索失效。

技术说明：
1. 查询重写（Query Rewriting）：把用户口语化/模糊问题改写成更适合检索的标准查询
2. 子查询分解（Sub-Query Decomposition）：把复杂问题拆成多个子问题，分别检索后合并
3. 后退提示生成（Step-Back Prompting）：先问一个更抽象的问题获取背景知识，再回答原问题
4. 查询扩展（Query Expansion）：补充同义词/相关关键词，扩大召回覆盖面
5. HyDE（假设性文档嵌入）：先让 LLM 生成假设答案，用答案措辞去检索，缩小"问-答"表述鸿沟
"""

import re

import config_service


# ——————————————————————————————————————————————
# 配置开关
# ——————————————————————————————————————————————

def _rewrite_enabled(db) -> bool:
    try:
        return bool(config_service.get_config("ai_query_rewrite_enabled", db))
    except Exception:
        return False  # 默认关闭，避免额外调用


def _decompose_enabled(db) -> bool:
    try:
        return bool(config_service.get_config("ai_query_decompose_enabled", db))
    except Exception:
        return False


def _stepback_enabled(db) -> bool:
    try:
        return bool(config_service.get_config("ai_query_stepback_enabled", db))
    except Exception:
        return False


def _expand_enabled(db) -> bool:
    try:
        return bool(config_service.get_config("ai_query_expand_enabled", db))
    except Exception:
        return False


def _hyde_enabled(db) -> bool:
    try:
        return bool(config_service.get_config("ai_query_hyde_enabled", db))
    except Exception:
        return False


def _max_sub_queries(db) -> int:
    try:
        return max(1, min(5, int(config_service.get_config("ai_query_max_sub", db))))
    except Exception:
        return 3


# ——————————————————————————————————————————————
# 大模型调用（复用 ai_service.chat，保持统一鉴权）
# ——————————————————————————————————————————————

def _llm_rewrite(prompt: str, max_tokens: int = 200) -> str:
    """调用大模型，返回纯文本结果。失败返回空字符串。"""
    try:
        import ai_service
        result = ai_service.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.1,  # 低温度，保证改写稳定
            max_tokens=max_tokens,
        )
        if result.get("ok"):
            return (result.get("reply") or "").strip()
    except Exception as e:
        print(f"[query_opt] 大模型调用失败: {e}")
    return ""


# ——————————————————————————————————————————————
# 1. 查询重写（Query Rewriting）
# ——————————————————————————————————————————————

REWRITE_PROMPT = """你是一个知识库检索查询优化助手。把用户的问题改写成更适合检索的标准查询。

规则：
1. 保留核心意图，补充省略的上下文
2. 把口语化表达转为正式术语
3. 去掉语气词、客套话
4. 如果问题已经很标准，保持不变
5. 只输出改写后的查询，不要解释、不要加引号

用户问题：{question}

改写后的查询："""


def rewrite_query(db, question: str) -> str:
    """把用户口语化问题改写成更适合检索的标准查询。

    失败或未启用时返回原问题。
    """
    question = (question or "").strip()
    if not question or not _rewrite_enabled(db):
        return question

    prompt = REWRITE_PROMPT.format(question=question)
    result = _llm_rewrite(prompt, max_tokens=150)
    if result:
        # 清理可能的多余内容
        result = result.split("\n")[0].strip()
        result = re.sub(r'^["「『]|["」』]$', '', result).strip()
        if result:
            return result
    return question


# ——————————————————————————————————————————————
# 2. 子查询分解（Sub-Query Decomposition）
# ——————————————————————————————————————————————

DECOMPOSE_PROMPT = """你是一个知识库检索查询优化助手。把用户的复杂问题拆分成多个独立的子问题。

规则：
1. 每个子问题都应该是可以独立检索的完整问题
2. 子问题之间不重叠、不包含
3. 数量控制在2-4个
4. 每个子问题占一行，不要编号、不要解释
5. 如果原问题已经很简单（只有一个意图），只输出原问题本身

用户问题：{question}

子问题（每行一个）："""


def decompose_query(db, question: str) -> list:
    """把复杂问题拆成多个子问题。

    返回子问题列表。失败或未启用时返回 [原问题]。
    """
    question = (question or "").strip()
    if not question or not _decompose_enabled(db):
        return [question] if question else []

    max_sub = _max_sub_queries(db)
    prompt = DECOMPOSE_PROMPT.format(question=question)
    result = _llm_rewrite(prompt, max_tokens=300)
    if not result:
        return [question]

    # 解析每行一个子问题
    subs = []
    for line in result.split("\n"):
        line = line.strip()
        # 去掉可能的编号（1. 2. 3. 或 - 或 *）
        line = re.sub(r'^[\d\.\-\*\、\s]+', '', line).strip()
        line = re.sub(r'^["「『]|["」』]$', '', line).strip()
        if line and len(line) > 3:
            subs.append(line)
        if len(subs) >= max_sub:
            break

    if not subs:
        return [question]
    # 确保原问题也在列表中（如果子问题没有覆盖原问题）
    if question not in subs:
        subs.insert(0, question)
    return subs


# ——————————————————————————————————————————————
# 3. 后退提示生成（Step-Back Prompting）
# ——————————————————————————————————————————————

STEPBACK_PROMPT = """你是一个知识库检索查询优化助手。针对用户的具体问题，生成一个更高层次、更抽象的"后退问题"，用于获取相关背景知识和通用规则。

规则：
1. 后退问题应该比原问题更宽泛、更通用
2. 后退问题应该能检索到原问题所依赖的背景规则/概念
3. 例如：原问题"打手提现30天冷却期怎么算？" → 后退问题"平台的提现规则和冷却期是什么？"
4. 只输出后退问题，不要解释、不要加引号

用户问题：{question}

后退问题："""


def step_back_query(db, question: str) -> str:
    """生成一个更抽象的后退问题，用于获取背景知识。

    失败或未启用时返回空字符串。
    """
    question = (question or "").strip()
    if not question or not _stepback_enabled(db):
        return ""

    prompt = STEPBACK_PROMPT.format(question=question)
    result = _llm_rewrite(prompt, max_tokens=150)
    if result:
        result = result.split("\n")[0].strip()
        result = re.sub(r'^["「『]|["」』]$', '', result).strip()
        return result
    return ""


# ——————————————————————————————————————————————
# 4. 查询扩展（Query Expansion）
# ——————————————————————————————————————————————

EXPAND_PROMPT = """你是知识库检索查询优化助手。针对用户问题，补充可能出现在相关文档里的同义词、近义词和相关关键词，用于扩大检索召回。

规则：
1. 输出 5-8 个和问题相关的关键词或同义说法，用空格分隔
2. 包含核心概念的不同表述（口语说法、正式术语、简称全称）
3. 不要输出句子、不要编号、不要解释
4. 例如问题"怎么退款" → "退款 退钱 申请退款 售后 原路退回 退款流程 退款规则"

用户问题：{question}

关键词："""


def expand_query(db, question: str) -> str:
    """生成补充关键词，拼接到原问题形成增强查询。

    返回增强后的查询字符串。失败或未启用时返回空字符串。
    """
    question = (question or "").strip()
    if not question or not _expand_enabled(db):
        return ""

    prompt = EXPAND_PROMPT.format(question=question)
    result = _llm_rewrite(prompt, max_tokens=120)
    if result:
        result = result.split("\n")[0].strip()
        result = re.sub(r'^["「『]|["」』]$', '', result).strip()
        if result:
            # 原问题 + 补充关键词，既保留完整意图又扩大关键词命中面
            return question + " " + result
    return ""


# ——————————————————————————————————————————————
# 5. HyDE（Hypothetical Document Embeddings，假设性文档嵌入）
# ——————————————————————————————————————————————

HYDE_PROMPT = """请简短回答下面的问题（2-3句话），即使不确定也请根据常识给出一个可能的答案。你的回答将用于文档检索，不需要完美准确。

问题：{question}

回答："""


def hyde_document(db, question: str) -> str:
    """生成假设性答案文档，用答案的措辞去做向量检索。

    原理：用户的"提问"和知识库里的"陈述"措辞往往不同（问题 vs 答案），
    直接用问题检索可能匹配不准。先让 LLM 写一段"假答案"，假答案和真实文档
    同样是陈述句、措辞更接近，用它去检索更容易命中真正相关的文档。

    返回假设文档字符串。失败或未启用时返回空字符串。
    """
    question = (question or "").strip()
    if not question or not _hyde_enabled(db):
        return ""

    prompt = HYDE_PROMPT.format(question=question)
    result = _llm_rewrite(prompt, max_tokens=200)
    if result:
        result = result.strip()
        result = re.sub(r'^["「『]|["」』]$', '', result).strip()
    return result


# ——————————————————————————————————————————————
# 组合优化：生成所有需要检索的查询
# ——————————————————————————————————————————————

def generate_queries(db, question: str, debug: dict = None) -> list:
    """根据启用的优化技术，生成所有需要检索的查询列表。

    返回 [{"query": str, "type": str, "channels": [str]}]，type 可选：
    - "original"：原问题
    - "rewritten"：查询重写
    - "subquery"：子查询分解
    - "stepback"：后退提示
    - "expanded"：查询扩展（原问题+补充关键词）
    - "hyde"：假设性文档（仅用于向量检索）

    channels 标记该查询适用于哪些检索通道（"keyword"/"vector"）。
    HyDE 是陈述句不是问题，关键词匹配无意义，故只走向量通道。

    所有查询去重后返回。
    """
    question = (question or "").strip()
    if not question:
        return []

    queries = []
    seen = set()
    ALL = ["keyword", "vector"]

    def _add(q, qtype, channels=None):
        q = (q or "").strip()
        if q and q not in seen:
            seen.add(q)
            queries.append({"query": q, "type": qtype,
                            "channels": channels or ALL})

    # 原问题始终保留
    _add(question, "original")

    # 1. 查询重写
    rewritten = rewrite_query(db, question)
    if rewritten and rewritten != question:
        _add(rewritten, "rewritten")

    # 2. 子查询分解（基于原问题或改写后的问题）
    base_for_decompose = rewritten if rewritten else question
    subs = decompose_query(db, base_for_decompose)
    for sub in subs:
        if sub != base_for_decompose and sub != question:
            _add(sub, "subquery")

    # 3. 后退提示
    stepback = step_back_query(db, question)
    if stepback:
        _add(stepback, "stepback")

    # 4. 查询扩展（原问题 + 补充关键词，关键词与向量通道都用）
    expanded = expand_query(db, question)
    if expanded:
        _add(expanded, "expanded")

    # 5. HyDE 假设文档（仅向量通道）
    hyde = hyde_document(db, question)
    if hyde:
        _add(hyde, "hyde", channels=["vector"])

    if debug is not None:
        debug["query_optimization"] = {
            "rewrite_enabled": _rewrite_enabled(db),
            "decompose_enabled": _decompose_enabled(db),
            "stepback_enabled": _stepback_enabled(db),
            "expand_enabled": _expand_enabled(db),
            "hyde_enabled": _hyde_enabled(db),
            "generated_queries": queries,
        }

    return queries
