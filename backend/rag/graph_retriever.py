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

# 与 kg/schema.py 保持一致（这里不直接 import，避免 rag 包对 kg 包产生硬依赖：
# 图谱没装驱动时，rag 仍然要能正常 import）
_SENSITIVE_FIELDS = {"balance", "consume_amount", "backend_amount", "total_amount"}

# 字段中文名（复用 kg.schema 的登记表；取不到时回退英文字段名）
_FIELD_CN = {
    "username": "账户名", "nickname": "昵称", "order_count": "点单次数",
    "consume_amount": "累计消费", "balance": "大狗币余额",
    "complaint_count": "投诉次数", "good_rate": "好评率",
    "backend_amount": "后台金额", "level_type": "等级类型", "tech_level": "技术等级",
    "order_no": "订单号", "game_type": "游戏", "duration_min": "服务时长(分钟)",
    "total_amount": "订单金额", "status": "状态", "created_at": "下单时间",
    "name": "游戏名", "tag_key": "标签",
}

# 每个标签用来当"名字"的字段。渲染时这个名字已经出现在标题/边上了，
# 属性列表里就要跳过它，否则会出现"订单 ORD123（订单号 ORD123）"这种重复。
_NAME_FIELD = {
    "Boss": "nickname", "Player": "nickname", "Order": "order_no",
    "Game": "name", "Tag": "tag_key",
}

# 每个标签只展示这几个字段。其余（blacklisted / updated_at / avatar /
# pending_* / boss_username 之类）是图谱同步带进来的内部字段或冗余信息——
# 全铺出来不但把上下文预算吃光，还会让大模型抓错重点。
_KEY_FIELDS = {
    "Boss": ["username", "order_count", "balance"],
    "Player": ["username", "level_type", "tech_level", "good_rate", "order_count"],
    "Order": ["game_type", "status", "duration_min"],
    "Game": ["order_count"],
    "Tag": [],
}

# 一类关系最多列几条边。像"某个老手下过 20 单"，20 条订单号铺出来
# 对回答毫无帮助，反而把别的通道挤没；列前 4 条 + 一句"共 N 条"更有用。
_MAX_EDGES_PER_REL = 4

# 整条事实的硬上限（标题 + 所有边）。超过就截断，保证一条事实不会独占上下文预算。
_MAX_LINES = 14

# 节点标签 → 中文名
_LABEL_CN = {
    "Boss": "老板", "Player": "打手", "Order": "订单", "Game": "游戏", "Tag": "标签",
}

# 关系类型 → 中文名
_REL_CN = {
    "PLACED": "下单", "SERVED": "接单", "FOR_GAME": "所属游戏",
    "HAS_TAG": "持有标签", "HIRED": "雇佣过",
}

# 订单状态 → 中文（与 kg/schema.py 的 ORDER_STATUS_TEXT 一致）
_ORDER_STATUS_CN = {
    "pending": "待派单", "pending_accept": "待打手确认", "assigned": "已接单",
    "processing": "服务中", "pending_settlement": "待确认结单",
    "completed": "已完成", "rejected": "已拒单", "cancelled": "已取消",
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
        # 但如果问题里**明明提到了别的实体**（账户名、订单号……），只是当前角色
        # 没权限看，就绝不能兜底——否则打手问"laoban 的余额是多少"会被悄悄换成
        # "你自己的记录"，答非所问还容易让人以为看到了别人的数据。
        if not seeds and not blocked and role in ("boss", "player") and username:
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
            if not edges:
                continue
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
        """
        is_admin = role in ("admin", "service")
        label = fact["label"]
        lines = []

        head = f"· 【图谱事实】{_LABEL_CN.get(label, label)} {fact['node_name']}"
        own = self._render_props(label, fact.get("props") or {}, is_admin, limit=3)
        if own:
            head += "（" + "，".join(own) + "）"
        lines.append(head)

        # 按关系类型分组，组内限量
        groups = {}
        for e in fact["edges"]:
            groups.setdefault(e["rel"], []).append(e)

        for rel, edges in groups.items():
            rel_cn = _REL_CN.get(rel, rel)
            shown = edges[:_MAX_EDGES_PER_REL]
            for e in shown:
                arrow = "—" + rel_cn + "→" if e["out"] else "←" + rel_cn + "—"
                peer = f"{_LABEL_CN.get(e['peer_label'], e['peer_label'])} {e['peer_name']}"
                # 打手/老板这类"人"的邻居，好评率和等级比账户名更值得看，
                # 所以多给一个字段位（limit=3）
                detail = self._render_props(e["peer_label"], e["peer_props"],
                                            is_admin, limit=3)
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

        # 只有表头、没有任何一条边，这条事实没有信息量，丢掉
        if len(lines) <= 1:
            return []
        return lines

    def _render_props(self, label: str, props: dict, is_admin: bool,
                      limit: int = 3) -> list:
        """把节点属性渲染成"中文名 值"的短串列表。

        只取 _KEY_FIELDS 里登记的字段，按登记顺序输出——顺序稳定，
        大模型每次看到的字段排列一致，更容易学会怎么读。
        节点自己的"名字"字段（如订单号）已经出现在标题或边上，这里跳过不重复。

        敏感字段（余额、后台金额、订单金额）对非管理员直接跳过——
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
            if field in _SENSITIVE_FIELDS and not is_admin:
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
        if field in ("consume_amount", "backend_amount", "total_amount"):
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
        text = str(val)
        # 游戏名这类可能很长（"王者荣耀-钻石-王者"），截一下避免边行过长
        return text if len(text) <= 24 else text[:23] + "…"

    @staticmethod
    def _display(label: str, props: dict) -> str:
        """节点的显示名：有昵称优先用昵称，否则用主键。"""
        nickname = str(props.get("nickname") or "").strip()
        if nickname:
            return nickname
        for k in ("username", "order_no", "name", "tag_key"):
            v = props.get(k)
            if v:
                return str(v)
        return "（未命名）"

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
