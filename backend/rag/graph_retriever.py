"""图谱召回通道（Graph RAG）—— 多路召回里的第三路。

在 RAG 流程中的位置：和 VectorRetriever（向量）、KeywordRetriever（关键词）
并列的一路召回。前两路回答的是"哪段文字和问题像"，这一路回答的是
"问题里提到的那些人/单/游戏，在图谱里分别连着谁"。

为什么需要单独一路：
    向量检索擅长语义相似，但对"这个老板找过哪几个打手"这类
    **关系型问题**很吃力——答案不在任何一段文字里，而在实体之间的边上。
    关键词检索更不行，BM25 只看词频，算不出多跳关系。

工作方式（三步）：
    ① 实体链接：从问题里找出图谱中真实存在的实体
       （账户名 / 昵称 / 订单号 / 游戏名 / 标签名）
    ② 取一跳邻域：把这些实体的邻居和关系一次性捞出来
    ③ 渲染事实：变成"老板 laoban —下单→ 订单 ORD2026..."这样的人话

兜底策略：
    老板和打手问"我的订单"时，问题里不会出现自己的账户名，
    实体链接会一无所获。所以当角色是 boss/player 且没匹配到任何实体时，
    直接把"本人节点"作为默认命中——这样"我的订单"也能走图谱。

权限：
    与 kg/api.py 保持一致——管理员和客服看全量；
    老板只能看自己，打手只能看自己。
    敏感字段（余额、后台金额、订单金额）对非管理员一律抹掉。

失败降级：
    图谱没配、连不上、Cypher 报错，一律返回空列表，绝不抛异常。
    RAG 少了这一路照样能答，只是回答不了关系型问题。
"""

import re

# 与 kg/schema.py 保持一致（这里不直接 import，避免 rag 包对 kg 包产生硬依赖：
# 图谱没装驱动时，rag 仍然要能正常 import）
_SENSITIVE_FIELDS = {"balance", "consume_amount", "backend_amount", "total_amount",
                     "amount", "tip_amount"}
# 字段中文名（复用 kg.schema 的登记表；取不到时回退英文字段名）
_FIELD_CN = {
    "username": "账户名", "nickname": "昵称", "order_count": "点单次数",
    "consume_amount": "累计消费", "balance": "大狗币余额",
    "complaint_count": "投诉次数", "good_rate": "好评率",
    "backend_amount": "后台金额", "level_type": "等级类型", "tech_level": "技术等级",
    "order_no": "订单号", "game_type": "游戏", "duration_min": "服务时长(分钟)",
    "total_amount": "订单金额", "status": "状态",
    # created_at 在各表里含义不同（下单时间/评价时间/打赏时间/提现时间），
    # 用中性的"时间"才不会把打赏时间渲染成"下单时间"
    "created_at": "时间",
    "name": "游戏名", "tag_key": "标签",
    # V4.11.0：订单之后发生的事（评价/打赏/提现/处罚）
    "rating": "星级", "comment": "评价内容", "reply": "打手回复",
    "is_complaint": "是否投诉", "review_status": "复查状态",
    "amount": "金额", "tip_amount": "累计收赏",
    "note": "审核备注", "processed_at": "审核时间", "status_text": "状态",
    "level": "处罚等级", "desc": "处罚说明", "date": "公示日期",
    "target": "涉及账号", "count": "次数",
    # 单据上的对手方：打赏/评价是老板→打手，提现只有打手。
    # 展示成"打手 dashou_09"才看得出这条打赏是给谁的——否则
    # 「laoban 给谁打赏过」只能答出金额，答不出对象。
    "player_username": "打手", "boss_username": "老板",
}

# 每个标签用来当"名字"的字段。渲染时这个名字已经出现在标题/边上了，
# 属性列表里就要跳过它，否则会出现"订单 ORD123（订单号 ORD123）"这种重复。
_NAME_FIELD = {
    "Boss": "nickname", "Player": "nickname", "Order": "order_no",
    "Game": "name", "Tag": "tag_key",
    # 评价/打赏/提现/处罚没有"名字"字段：标题里会用业务含义代替
    #（如「老板 小达 的一条 5 星评价」），所以这里留空。
    "Rating": "", "Tip": "", "Withdrawal": "", "Punishment": "",
}

# 每个标签只展示这几个字段。其余（blacklisted / updated_at / avatar /
# pending_* / boss_username 之类）是图谱同步带进来的内部字段或冗余信息——
# 全铺出来不但把上下文预算吃光，还会让大模型抓错重点。
_KEY_FIELDS = {
    "Boss": ["username", "order_count", "consume_amount", "balance"],
    "Player": ["username", "level_type", "tech_level", "good_rate",
               "order_count", "complaint_count"],
    "Order": ["game_type", "status", "duration_min"],
    "Game": ["order_count"],
    "Tag": [],
    # 评价要带上正文和回复——"这个打手被投诉了什么"的答案就在 comment 里；
    # 打赏/提现要带金额（敏感字段，只有管理员或本人可见）；
    # 处罚要带上说明与等级。
    # Rating / Tip 还要带上对手方（player_username），否则站在老板视角
    # 只答得出"打赏了 16 元"，答不出"打赏给了谁"。
    "Rating": ["rating", "is_complaint", "comment", "reply",
               "review_status", "player_username", "created_at"],
    "Tip": ["amount", "player_username", "created_at"],
    "Withdrawal": ["amount", "status_text", "note", "created_at"],
    # 等级和日期已经拼在处罚节点的显示名里（"封禁账号（2026-09-01）"），
    # 这里只留说明正文，避免同一句话出现两遍
    "Punishment": ["desc"],
}

# 一类关系最多列几条边。像"某个老手下过 20 单"，20 条订单号铺出来
# 对回答毫无帮助，反而把别的通道挤没；列前 4 条 + 一句"共 N 条"更有用。
_MAX_EDGES_PER_REL = 4

# 整条事实的硬上限（标题 + 所有边）。超过就截断，保证一条事实不会独占上下文预算。
_MAX_LINES = 14

# 「本人兜底」的触发条件：问题里得有自称词。
# 少了这一条，任何一道 boss/player 的题（"大狗币兑换比例是多少"）都会被兜底命中，
# 把本人的订单列表塞进完全不相关的上下文里。
_SELF_REF_RE = re.compile(r"我|自己|本人|咱|自家")

# 标签关键词兜底：实体链接一个种子都匹配不到时，按问题里的词直接取该类节点。
#
# 为什么需要：处罚通告这类节点**没有任何账号名可匹配**——"平台上有哪些处罚通告"
# 里不含 username / order_no / 游戏名 / 标签，实体链接必然空手而归，
# 图谱这一路就算库里躺着一堆通告也召回不了。
# 顺序有讲究：越具体的标签排前面，避免"投诉"被更宽泛的词抢走。
_LABEL_KEYWORD_HINTS = (
    (r"处罚|通告|封禁|违规|拉黑", "Punishment"),
    (r"打赏|赏金", "Tip"),
    (r"提现|提款", "Withdrawal"),
    (r"评价|好评|差评|投诉|星级", "Rating"),
)

# 节点标签 → 中文名
_LABEL_CN = {
    "Boss": "老板", "Player": "打手", "Order": "订单", "Game": "游戏", "Tag": "标签",
    "Rating": "评价", "Tip": "打赏记录", "Withdrawal": "提现记录",
    "Punishment": "处罚通告",
}

# 关系类型 → 中文名
_REL_CN = {
    "PLACED": "下单", "SERVED": "接单", "FOR_GAME": "所属游戏",
    "HAS_TAG": "持有标签", "HIRED": "雇佣过",
    # V4.11.0
    "RATED": "评价了", "ABOUT": "评价对象", "FOR_ORDER": "对应订单",
    "COMPLAINED": "投诉过", "TIPPED": "打赏了", "TO": "打赏给",
    "WITHDREW": "提现", "PUNISHED": "被处罚",
}

# 渲染时的关系展示优先级（数字越小越先渲染）。
#
# 为什么需要：每条事实有 _MAX_LINES 行预算，而一个老打手名下有几十条订单，
# 「接单」一列就吃掉 4 行。实测把提现、打赏这些"信息密度高但条数少"的关系
# 排在订单类关系后面时，它们会被行数预算整段截掉——图谱召回了却看不见，
# 问「这个打手提过几次现」永远答不出。
# 所以把事后单据类关系提到前面，订单类排到最后（订单量大、单条信息量低）。
_REL_PRIORITY = {
    "COMPLAINED": 0, "PUNISHED": 1, "RATED": 2, "TIPPED": 3,
    "WITHDREW": 4, "ABOUT": 5, "TO": 6, "HIRED": 7,
    "HAS_TAG": 8, "PLACED": 9, "SERVED": 9, "FOR_GAME": 9, "FOR_ORDER": 9,
}

# 订单状态 → 中文（与 kg/schema.py 的 ORDER_STATUS_TEXT 一致）
_ORDER_STATUS_CN = {
    "pending": "待派单", "pending_accept": "待打手确认", "assigned": "已接单",
    "processing": "服务中", "pending_settlement": "待确认结单",
    "completed": "已完成", "rejected": "已拒单", "cancelled": "已取消",
}

# 评价复查状态 → 中文（与 kg/schema.py 的 REVIEW_STATUS_TEXT 一致）
_REVIEW_STATUS_CN = {
    "normal": "正常展示", "reviewing": "复查中", "removed": "已删除",
}


class GraphRetriever:
    """知识图谱召回器。

    使用示例：
        gr = GraphRetriever(db)
        docs = gr.retrieve("laoban 最近下了哪些单", role="admin", username="guanliyuan")
        # docs 是 [Document]，source_type="graph"
    """

    CHANNEL = "graph"

    # 各类实体的匹配可信度，作为这一路的原始分数
    # （账户名/订单号是精确标识，不改写；游戏名、标签可能只是顺带提到，给低一点）
    _MATCH_SCORE = {
        "username": 1.0, "order_no": 1.0,
        "nickname": 0.9, "name": 0.8, "tag_key": 0.7,
    }

    def __init__(self, db):
        """初始化。

        参数：
            db: 数据库会话（本模块只用来读系统参数，不直接查表）
        """
        self.db = db
        self._last_hits = []   # 供调试读取

    # ------------------------------------------------------------------ #
    # 对外主入口
    # ------------------------------------------------------------------ #
    def retrieve(self, question: str, role: str, username: str = None,
                 limit: int = None) -> list:
        """按问题召回图谱事实。

        参数：
            question: 用户原始问题
            role:     当前角色（admin / service / boss / player）
            username: 当前用户的账户名（用于把老板/打手的可见范围收敛到本人）
            limit:    最多返回几条事实（None 时读系统参数 rag_graph_limit，默认 3）

        返回：
            [Document]，每条是一段已经渲染成人话的图谱事实。
            没命中任何实体、或图谱不可用时返回空列表。
        """
        from .document import Document

        question = (question or "").strip()
        if not question:
            return []

        # 图谱这条路要能用，得先过三关：驱动在、密码配了、连得上
        try:
            from kg import store
            if not store.is_ready():
                return []
        except Exception:
            return []

        lim = limit if limit is not None else self._limit()
        try:
            seeds = self._link_entities(question, role, username)
        except Exception as e:
            print(f"[rag] 图谱实体链接失败，跳过图谱通道：{type(e).__name__}: {e}")
            return []

        if not seeds:
            return []

        try:
            facts = self._collect_facts(seeds, limit=lim)
        except Exception as e:
            print(f"[rag] 图谱邻域查询失败，跳过图谱通道：{type(e).__name__}: {e}")
            return []

        if not facts:
            return []

        docs = []
        for f in facts:
            text_lines = self._render(f, role)
            if not text_lines:
                continue
            docs.append(Document(
                content="\n".join(text_lines),
                metadata={
                    "node_id": f["node_id"],
                    "label": f["label"],
                    "key": f["key"],
                    "node_name": f["node_name"],
                    "match_score": f["match_score"],
                    "match_field": f["match_field"],
                },
                score=float(f["match_score"]),
                source_type=self.CHANNEL,
                chunk=None,
            ))
        self._last_hits = docs
        return docs

    def get_last_hits(self) -> list:
        """取最近一次召回的原始 Document 列表（调试面板用）。"""
        return list(self._last_hits)

    # ------------------------------------------------------------------ #
    # ① 实体链接
    # ------------------------------------------------------------------ #
    def _link_entities(self, question: str, role: str, username: str) -> list:
        """从问题里找出图谱中真实存在的实体。

        做法是让 Neo4j 去判断"问题文本里是否包含某个节点的标识"，
        而不是先把全图拉回 Python 再逐个比对——图谱里节点可能上万，
        拉回来做字符串匹配是 O(N)，交给数据库做带索引的扫描才合理。

        返回：
            [{"node_id", "label", "key", "node_name", "match_score", "match_field"}]
        """
        from kg import store

        rows = store.run(
            """
            MATCH (n)
            WHERE ($q CONTAINS n.username AND n.username IS NOT NULL)
               OR ($q CONTAINS n.order_no  AND n.order_no  IS NOT NULL)
               OR (size(coalesce(n.nickname, '')) >= 2 AND $q CONTAINS n.nickname)
               OR (size(coalesce(n.name,     '')) >= 2 AND $q CONTAINS n.name)
               OR (size(coalesce(n.tag_key,  '')) >= 2 AND $q CONTAINS n.tag_key)
            RETURN elementId(n) AS eid, labels(n) AS labels, properties(n) AS props
            LIMIT 20
            """,
            {"q": question},
            mode="r",
        ) or []

        seeds = []
        seen = set()
        blocked = False   # 问题里提到了别的实体，只是当前角色看不到
        for r in rows:
            labels = r.get("labels") or []
            props = r.get("props") or {}
            if not labels:
                continue
            label = labels[0]
            field, score = self._best_match(question, props)
            if not field:
                continue
            # 权限：老板/打手只允许命中自己
            if not self._visible(role, label, props, username):
                blocked = True
                continue
            key = str(props.get("username") or props.get("order_no")
                      or props.get("name") or props.get("tag_key") or "")
            eid = r.get("eid")
            if not eid or eid in seen:
                continue
            seen.add(eid)
            seeds.append({
                "node_id": eid, "label": label, "key": key,
                "node_name": self._display(label, props),
                "match_score": score, "match_field": field,
            })

        # 兜底：老板/打手问题里没写自己名字时，默认拿本人节点去查
        # （"我的订单""我这个月赚了多少"都不会出现账户名）
        #
        # 但必须满足两个条件，否则不能兜底：
        #   ① 问题里**没有**提到别的实体。若提到了只是没权限看，
        #      兜底会把"看看 laoban 的余额"悄悄换成"你自己的记录"，答非所问，
        #      还容易让人以为看到了别人的数据。
        #   ② 问题里出现了**自称词**（我 / 自己 / 本人 / 咱…）。这是判断
        #      "问的是不是自己"的唯一可靠线索。少了这一条，任何一道
        #      boss/player 的题都会被兜底命中，把本人的订单列表硬塞进
        #      "大狗币兑换比例是多少"这种完全不相关的上下文里。
        if (not seeds and not blocked and role in ("boss", "player") and username
                and _SELF_REF_RE.search(question or "")):
            want = "Boss" if role == "boss" else "Player"
            try:
                own = store.run(
                    "MATCH (n:" + want + " {username: $u}) "
                    "RETURN elementId(n) AS eid, properties(n) AS props LIMIT 1",
                    {"u": username}, mode="r",
                ) or []
            except Exception:
                own = []
            for r in own:
                seeds.append({
                    "node_id": r.get("eid"), "label": want, "key": username,
                    "node_name": self._display(want, r.get("props") or {}),
                    "match_score": 0.6, "match_field": "self",
                })

        # 标签关键词兜底：问题里没有具体账号/订单号可匹配，但确实在问
        # 某类单据时（"平台上有哪些处罚通告""最近有哪些打赏"），
        # 实体链接一个种子都找不到，图谱这一路就白开了。
        # 这里按标签关键词取最近的几条该类节点当种子。
        if not seeds and not blocked:
            want = None
            for pat, lb in _LABEL_KEYWORD_HINTS:
                if re.search(pat, question or ""):
                    want = lb
                    break
            if want:
                try:
                    rows = store.run(
                        "MATCH (n:" + want + ") "
                        "RETURN elementId(n) AS eid, properties(n) AS props "
                        "ORDER BY coalesce(n.updated_at, '') DESC LIMIT 3",
                        {}, mode="r",
                    ) or []
                except Exception:
                    rows = []
                for r in rows:
                    props = r.get("props") or {}
                    if not self._visible(role, want, props, username):
                        continue
                    seeds.append({
                        "node_id": r.get("eid"), "label": want, "key": "",
                        "node_name": self._display(want, props),
                        "match_score": 0.5, "match_field": "label_hint",
                    })

        seeds.sort(key=lambda s: -s["match_score"])
        return seeds[:5]

    def _best_match(self, question: str, props: dict):
        """判断这个节点是被哪个字段命中的，返回 (字段名, 可信度)。"""
        # 顺序有讲究：账户名和订单号是精确标识，优先
        for field in ("username", "order_no", "nickname", "name", "tag_key"):
            val = props.get(field)
            if not val:
                continue
            val = str(val)
            # 昵称/游戏名/标签要求至少 2 个字，否则"的""了"这类单字会满图乱撞
            if field in ("nickname", "name", "tag_key") and len(val) < 2:
                continue
            if val in question:
                return field, self._MATCH_SCORE.get(field, 0.6)
        return None, 0.0

    @staticmethod
    def _visible(role: str, label: str, props: dict, username: str) -> bool:
        """这个节点对当前角色是否可见（与 kg/api.py 的口径一致）。

        管理员 / 客服：全量可见
        老板：只看得到自己那个 Boss 节点
        打手：只看得到自己那个 Player 节点
        """
        if role in ("admin", "service"):
            return True
        if not username:
            return False
        if role == "boss":
            return label == "Boss" and str(props.get("username") or "") == username
        if role == "player":
            return label == "Player" and str(props.get("username") or "") == username
        return False

    # ------------------------------------------------------------------ #
    # ② 取一跳邻域
    # ------------------------------------------------------------------ #
    def _collect_facts(self, seeds: list, limit: int) -> list:
        """把命中实体的一跳邻居和关系捞出来，拼成待渲染的事实。

        返回：
            [{"node_id", "label", "key", "node_name", "match_score",
              "match_field", "props", "edges": [{"rel","out",
              "peer_label","peer_name","peer_props"}]}]
        """
        from kg import store

        ids = [s["node_id"] for s in seeds if s.get("node_id")]
        if not ids:
            return []

        rows = store.run(
            """
            MATCH (n)-[r]-(m)
            WHERE elementId(n) IN $ids
            RETURN elementId(n) AS nid,
                   type(r)      AS rel,
                   startNode(r) = n AS out,
                   labels(m)    AS peer_labels,
                   properties(m) AS peer_props,
                   elementId(m) AS peer_id
            """,
            {"ids": ids}, mode="r",
        ) or []

        # 按种子节点分组
        by_id = {}
        for r in rows:
            by_id.setdefault(r.get("nid"), []).append(r)

        facts = []
        for s in seeds:
            edges = []
            for r in by_id.get(s["node_id"], []):
                peer_labels = r.get("peer_labels") or []
                if not peer_labels:
                    continue
                peer_label = peer_labels[0]
                edges.append({
                    "rel": r.get("rel") or "",
                    "out": bool(r.get("out")),
                    "peer_label": peer_label,
                    "peer_id": r.get("peer_id"),
                    "peer_name": self._display(peer_label, r.get("peer_props") or {}),
                    "peer_props": r.get("peer_props") or {},
                })
            # 没有边的节点以前直接跳过，但处罚通告就是这么一种节点：
            # 它是"一条平台规则/一次处罚"本身，正文就在属性里，没有邻居。
            # 跳过它等于「问有哪些处罚通告」永远召回不到东西——
            # 所以改成保留，由 _render 判断"没边但属性非空"时照样输出。
            facts.append({
                "node_id": s["node_id"], "label": s["label"], "key": s["key"],
                "node_name": s["node_name"], "match_score": s["match_score"],
                "match_field": s["match_field"], "props": {},
                "edges": edges,
            })
            if len(facts) >= limit:
                break

        # 补上种子节点自己的属性（要在渲染时遮蔽敏感字段，所以这里现取）
        if facts:
            props_rows = store.run(
                "MATCH (n) WHERE elementId(n) IN $ids "
                "RETURN elementId(n) AS eid, properties(n) AS props, labels(n) AS labels",
                {"ids": [f["node_id"] for f in facts]}, mode="r",
            ) or []
            pmap = {r.get("eid"): (r.get("props") or {}, r.get("labels") or [])
                    for r in props_rows}
            for f in facts:
                p, _lb = pmap.get(f["node_id"], ({}, []))
                f["props"] = p

        return facts

    # ------------------------------------------------------------------ #
    # ③ 渲染成人话
    # ------------------------------------------------------------------ #
    def _render(self, fact: dict, role: str) -> list:
        """把一条图谱事实渲染成给大模型看的文字。

        渲染成"主谓宾"的句子而不是 JSON，是因为大模型读自然语言更稳；
        但也保留实体名，方便它在回答里指名道姓。

        三条节制规则（都是实测踩出来的）：
            ① 只展示 _KEY_FIELDS 里登记的关键字段，内部字段（updated_at、
               blacklisted、avatar、boss_username…）一律不出现；
            ② 同一类关系最多列 _MAX_EDGES_PER_REL 条，其余折成"共 N 条"——
               一个老手下过 20 单，20 个订单号铺出来对回答毫无帮助；
            ③ 整体不超过 _MAX_LINES 行，防止一条事实独占上下文预算
               把向量/关键词两路的结果全挤掉。

        参数 role 决定敏感字段是否遮蔽——老板的余额、打手的后台金额
        对非管理员一律不出现，避免 AI 把不该说的数字说出去。
        但「本人看自己」是例外：老板问"我一共消费了多少"时，
        消费金额就是他自己的账，遮掉等于答不出题（评估里这道题长期 0 分）。
        所以兜底命中的那条事实（match_field == "self"）按本人放行。
        """
        is_admin = role in ("admin", "service")
        is_self = (fact.get("match_field") == "self")
        label = fact["label"]
        lines = []

        head = f"· 【图谱事实】{_LABEL_CN.get(label, label)} {fact['node_name']}"
        own = self._render_props(label, fact.get("props") or {}, is_admin,
                                 limit=6, is_self=is_self)
        if own:
            head += "（" + "，".join(own) + "）"
        lines.append(head)

        # 按关系类型分组，组内限量。
        # 组间顺序不是随机的——按 _REL_PRIORITY 排，保证提现/打赏/投诉这些
        # 条数少、信息密度高的关系先占住行数预算，订单类排到最后被截。
        groups = {}
        for e in fact["edges"]:
            groups.setdefault(e["rel"], []).append(e)
        ordered_rels = sorted(groups.keys(),
                              key=lambda r: (_REL_PRIORITY.get(r, 99), r))

        for rel in ordered_rels:
            edges = groups[rel]
            rel_cn = _REL_CN.get(rel, rel)
            shown = edges[:_MAX_EDGES_PER_REL]
            for e in shown:
                arrow = "—" + rel_cn + "→" if e["out"] else "←" + rel_cn + "—"
                peer = f"{_LABEL_CN.get(e['peer_label'], e['peer_label'])} {e['peer_name']}"
                # 打手/老板这类"人"的邻居，好评率和等级比账户名更值得看，
                # 所以多给几个字段位（limit=4）
                detail = self._render_props(e["peer_label"], e["peer_props"],
                                            is_admin, limit=4)
                if detail:
                    peer += "（" + "，".join(detail) + "）"
                lines.append(f"  {arrow} {peer}")
                if len(lines) >= _MAX_LINES:
                    break
            # 被截掉的边折成一句，让大模型知道这里还有内容、不要瞎猜
            if len(edges) > len(shown) and len(lines) < _MAX_LINES:
                lines.append(f"  （{rel_cn}共 {len(edges)} 条，此处仅列前 {len(shown)} 条）")
            if len(lines) >= _MAX_LINES:
                break

        # 只有表头、没有任何一条边，这条事实没有信息量，丢掉。
        # 例外：种子节点自身属性非空时，表头本身就是答案——
        # 一条处罚通告（「处罚通告 封禁账号（2026-09-01）」+ 处罚说明）
        # 通常没有边可走，但它的说明正文正是要回答的内容，不能丢。
        if len(lines) <= 1:
            return lines if own else []
        return lines

    def _render_props(self, label: str, props: dict, is_admin: bool,
                      limit: int = 6, is_self: bool = False) -> list:
        """把节点属性渲染成"中文名 值"的短串列表。

        只取 _KEY_FIELDS 里登记的字段，按登记顺序输出——顺序稳定，
        大模型每次看到的字段排列一致，更容易学会怎么读。
        节点自己的"名字"字段（如订单号）已经出现在标题或边上，这里跳过不重复。

        关于 limit：原先给的是 3，但 Player 登记的字段有 5~6 个，
        前 3 个恰好是账户名/等级类型/技术等级，把「好评率」「接单次数」
        挤掉了——而这两个正是"这个打手好评率多少"的答案所在。
        评估里表现为：图谱明明召回了节点，回答却答不出数字，白白浪费一次召回。
        现在放宽到 6，让登记过的字段基本都能露出来。

        敏感字段（余额、累计消费、后台金额、订单金额）对非管理员直接跳过——
        不是显示成 0，而是根本不出现，避免被误读成"余额是 0"。
        """
        out = []
        name_field = _NAME_FIELD.get(label)
        for field in _KEY_FIELDS.get(label, []):
            if field == name_field:
                continue          # 名字已经展示过了，不重复
            val = props.get(field)
            if val is None or val == "":
                continue
            if field in _SENSITIVE_FIELDS and not (is_admin or is_self):
                continue
            out.append(f"{_FIELD_CN.get(field, field)} {self._fmt(field, val)}")
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _fmt(field: str, val) -> str:
        """按字段做单位换算与显示格式化。

        金额类字段库里存的是「分」，直接给大模型看 642000 会被当成 64 万，
        必须先换成元。
        好评率的哨兵值 -1 表示"还没有评价"（不是 0% 好评），显示成 —；
        其余情况库里存的**已经是百分数**（100 表示 100%、66.7 表示 66.7%），
        不要再乘 100，否则会渲染成 10000% 这种离谱数字。
        """
        if field in ("consume_amount", "backend_amount", "total_amount",
                     "amount", "tip_amount"):
            try:
                return f"{float(val) / 100:.2f} 元"
            except Exception:
                return str(val)
        if field == "balance":
            return f"{val} 大狗币"
        if field == "good_rate":
            try:
                f = float(val)
                # 负数是哨兵值：还没被评价过，不是 0% 好评
                return "—" if f < 0 else f"{f:.1f}%"
            except Exception:
                return str(val)
        if field == "status":
            return _ORDER_STATUS_CN.get(str(val), str(val))
        if field == "review_status":
            return _REVIEW_STATUS_CN.get(str(val), str(val))
        if field == "is_complaint":
            return "是" if val else "否"
        text = str(val)
        # 游戏名这类可能很长（"王者荣耀-钻石-王者"），截一下避免边行过长
        return text if len(text) <= 24 else text[:23] + "…"

    @staticmethod
    def _display(label: str, props: dict) -> str:
        """节点的显示名：有昵称优先用昵称，否则用主键。

        评价 / 打赏 / 提现 / 处罚这四类单据没有"名字"字段，主键
        （rating:3、tip:7 这种内部 id）对回答毫无意义，所以按业务含义
        拼一个展示名——大模型看到「¥16.00」比看到「tip:7」有用得多。

        注意这里**不要**再重复标签中文名：标签名已经由调用处拼在边上或
        表头里（如「—打赏了→ 打赏记录 ¥16.00」），这里只给核心事实本身。
        """
        nickname = str(props.get("nickname") or "").strip()
        if nickname:
            return nickname

        if label == "Rating":
            star = int(props.get("rating") or 0)
            tag = "（投诉）" if props.get("is_complaint") else ""
            return f"{star} 星{tag}" if star else f"评价{tag}"
        if label == "Tip":
            return GraphRetriever._yuan(props.get("amount"))
        if label == "Withdrawal":
            st = str(props.get("status_text") or "").strip()
            amt = GraphRetriever._yuan(props.get("amount"))
            return f"{amt}（{st}）" if st else amt
        if label == "Punishment":
            lv = str(props.get("level") or "").strip()
            dt = str(props.get("date") or "").strip()
            return (lv or "处罚") + (f"（{dt}）" if dt else "")

        for k in ("username", "order_no", "name", "tag_key"):
            v = props.get(k)
            if v:
                return str(v)
        return "（未命名）"

    @staticmethod
    def _yuan(val) -> str:
        """分 → 元的显示串（金额字段库里存的是分，与业务表口径一致）。"""
        try:
            return f"¥{int(val or 0) / 100:.2f}"
        except (TypeError, ValueError):
            return "¥0.00"

    # ------------------------------------------------------------------ #
    # 配置
    # ------------------------------------------------------------------ #
    def _limit(self) -> int:
        """这一路最多注入几条图谱事实（系统参数 rag_graph_limit）。"""
        try:
            import config_service
            return max(1, int(config_service.get_config("rag_graph_limit", self.db)))
        except Exception:
            return 3
