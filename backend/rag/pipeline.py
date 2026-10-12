"""
主类：ModularRAG（模块化检索增强生成编排器）。

组装 6 个模块，执行完整查询流程：
    用户问题 → QueryRewriter（查询改写）
             → VectorRetriever + KeywordRetriever（多路召回）
             → FusionModule（加权 RRF 融合）
             → Reranker（检索后重排序）
             → ContextBuilder（上下文构建）
             → 返回格式化上下文文本（喂给大模型生成答案）

这是 RAG 推理问答阶段的总入口，对应传统 RAG 的"检索 + 增强"两步。
生成（Generate）在 ai_service.py 的 chat() 中完成。
"""

from .query_rewriter import QueryRewriter
from .vector_retriever import VectorRetriever
from .keyword_retriever import KeywordRetriever
from .graph_retriever import GraphRetriever
from .fusion import FusionModule
from .reranker import Reranker
from .cross_encoder_reranker import CrossEncoderReranker
from .context_builder import ContextBuilder


class ModularRAG:
    """模块化 RAG 编排器。

    系统架构：
        ┌─────────────────────────────────────────────┐
        │              用户输入查询                     │
        └──────────────────┬──────────────────────────┘
                           ▼
        ┌─────────────────────────────────────────────┐
        │  Module 1: QueryRewriter（查询改写）          │
        │  - 同义词扩展 / HyDE / 多查询生成             │
        └──────────────────┬──────────────────────────┘
                           ▼
        ┌─────────────────────────────────────────────┐
        │  Module 2: Multi-Retriever（多路检索）        │
        │  - 向量检索（千问 embedding + 余弦相似度）     │
        │  - 关键词检索（FAQ BM25 匹配）                │
        └──────────────────┬──────────────────────────┘
                           ▼
        ┌─────────────────────────────────────────────┐
        │  Module 3: Fusion（结果融合）                 │
        │  - 加权 RRF（FAQ权重1.2 / 文档权重1.0）       │
        └──────────────────┬──────────────────────────┘
                           ▼
        ┌─────────────────────────────────────────────┐
        │  Module 4: Reranker（检索后重排序）           │
        │  - 综合向量分/关键词分/来源类型/标题匹配      │
        │  - 多维度加权打分，二次排序                   │
        └──────────────────┬──────────────────────────┘
                           ▼
        ┌─────────────────────────────────────────────┐
        │  Module 5: ContextBuilder（上下文构建）       │
        │  - 格式化为引用块，top_k + max_chars 限制     │
        └──────────────────┬──────────────────────────┘
                           ▼
        ┌─────────────────────────────────────────────┐
        │              格式化上下文文本                  │
        │         （喂给千问大模型生成答案）              │
        └─────────────────────────────────────────────┘

    使用示例：
        rag = ModularRAG(db)
        context = rag.query("怎么退款", role="boss")
        # context 就是格式化好的引用块，直接拼进 Prompt
    """

    def __init__(self, db):
        """初始化模块化 RAG 系统，组装所有模块。

        参数：
            db: 数据库会话
        """
        self.db = db
        # 延迟导入配置读取函数，避免循环导入
        from ai_rag import _rrf_k, _channel_weights

        self.rewriter = QueryRewriter(db)
        self.vector_retriever = VectorRetriever(db)
        self.keyword_retriever = KeywordRetriever(db)
        # 第三路召回：知识图谱。只在问题里出现具体实体（账户名/订单号/游戏名/
        # 标签）时才产出，平时是空列表，不会稀释另外两路的结果。
        self.graph_retriever = GraphRetriever(db)
        # RRF 平滑常数与多路通道权重都从系统参数读：ModularRAG 每次查询都会
        # 重新实例化，所以管理员改完参数下一次提问即生效，不用重启服务
        self.fusion = FusionModule(rrf_k=_rrf_k(db), channel_weights=_channel_weights(db))
        self.reranker = Reranker(db)
        self.cross_encoder = CrossEncoderReranker(db)
        self.context_builder = ContextBuilder(db)

    def query(self, question: str, role: str, top_k: int = None,
              min_score: float = None, debug: dict = None,
              username: str = None) -> str:
        """执行完整 RAG 查询流程，返回格式化后的上下文文本。

        执行流程：
            ① 查询改写：query_optimizer 生成多个查询变体
            ② 多路召回：每个变体分别做关键词检索（FAQ）+ 向量检索（文档/FAQ），
                       另外对原始问题单独做一路知识图谱检索
            ③ 加权 RRF 融合：三路结果合并排序
            ④ 重排序（Re-rank）：综合向量分数、关键词分数、来源类型、标题匹配，二次排序
            ⑤ 上下文构建：渲染为引用块，受 top_k 和 max_chars 限制

        参数：
            question: 用户提问文本
            role: 当前用户角色（admin/service/boss/player）
            top_k: 返回最相关的前 K 条（None 时用系统参数 rag_top_k，默认 4）
            min_score: 最低相似度阈值（None 时用系统参数 rag_min_score，默认 0.35）
            debug: 调试信息字典，用于前端展示检索过程（查询变体、各通道命中、RRF 分数等）
            username: 当前用户的账户名。图谱这一路要靠它把老板/打手的可见范围
                      收敛到本人（不传也不会报错，只是老板/打手视角会少一路召回）

        返回：
            str，格式化后的检索上下文文本，可直接拼进系统提示词的"参考资料"部分。
            无相关内容时返回空字符串。
        """
        import ai_service
        from ai_rag import (_top_k, _min_score, _max_chars, _keyword_limit,
                            module_query_rewrite_enabled,
                            module_vector_retrieval_enabled,
                            module_keyword_retrieval_enabled,
                            module_graph_retrieval_enabled,
                            module_fusion_enabled,
                            module_rerank_enabled,
                            module_automerge_enabled)

        question = (question or "").strip()
        if not question:
            return ""

        # 读取模块开关（每个环节可独立关闭）
        use_rewrite = module_query_rewrite_enabled(self.db)
        use_vector = module_vector_retrieval_enabled(self.db)
        use_keyword = module_keyword_retrieval_enabled(self.db)
        use_graph = module_graph_retrieval_enabled(self.db)
        use_fusion = module_fusion_enabled(self.db)
        use_rerank = module_rerank_enabled(self.db)
        use_automerge = module_automerge_enabled(self.db)

        # ① 查询改写（关闭则直接用原始问题）
        if use_rewrite:
            queries = self.rewriter.rewrite(question, debug)
        else:
            queries = [{"query": question, "type": "original",
                        "channels": ["keyword", "vector"]}]

        # ② 多路召回
        all_kw_hits = []    # FAQ 关键词命中：[(score, faq_row, query_index, rank)]
        all_vec_hits = []   # 向量命中：[{"score", "chunk", "channel", "query_index", "rank_in_query", ...}]
        all_graph_hits = []  # 图谱命中：[Document(source_type="graph"), ...]
        vector_errors = []
        tk = _top_k(self.db) if top_k is None else max(1, int(top_k))
        ms = _min_score(self.db) if min_score is None else float(min_score)

        # 对每个查询变体，分别执行关键词检索和向量检索
        for qi, qinfo in enumerate(queries):
            q = qinfo["query"]
            use_ch = qinfo.get("channels", ["keyword", "vector"])

            # FAQ 通道 —— 关键词 BM25（精确匹配），模块关闭时跳过
            if use_keyword and "keyword" in use_ch:
                for rank, doc in enumerate(self.keyword_retriever.retrieve(
                        q, role, limit=_keyword_limit(self.db))):
                    all_kw_hits.append((doc.score, doc.chunk, qi, rank))

            # 向量通道 —— 文档通道与 FAQ 通道各自独立召回，模块关闭时跳过
            if use_vector and "vector" in use_ch:
                for channel, stypes in (("document", ["document"]), ("faq", ["faq"])):
                    try:
                        for rank, doc in enumerate(self.vector_retriever.retrieve(
                                q, role, top_k=tk, min_score=ms,
                                source_types=stypes, automerge=use_automerge)):
                            all_vec_hits.append({
                                "score": doc.score, "chunk": doc.chunk, "channel": channel,
                                "query_index": qi, "rank_in_query": rank,
                                "merged": doc.metadata.get("merged", False),
                                "hit_ratio": doc.metadata.get("hit_ratio", 0),
                            })
                    except Exception as e:
                        vector_errors.append(f"[{qinfo.get('type','?')}/{channel}] {e}")
                        print(f"[rag] 向量检索失败（{channel}，查询{qi}: {q[:30]}）：{e}")

        # 图谱通道 —— 只用**原始问题**做一次，不跟着查询变体分裂。
        # 原因：实体链接靠的是问题里出现的账户名/订单号/游戏名这些字面标识，
        # 而查询改写（同义扩展、HyDE、子查询）产出的变体里往往已经不含这些标识了，
        # 拿变体去匹配只会白跑几趟 Neo4j。
        if use_graph:
            try:
                all_graph_hits = self.graph_retriever.retrieve(
                    question, role, username=username)
            except Exception as e:
                print(f"[rag] 图谱检索失败，跳过该通道：{type(e).__name__}: {e}")
                all_graph_hits = []

        if not all_kw_hits and not all_vec_hits and not all_graph_hits:
            return ""

        # ③ 结果融合
        if use_fusion:
            # 加权 RRF 融合（只用排名信息，FAQ权重1.2 / 文档权重1.0 / 图谱权重1.3）
            ordered, pool = self.fusion.fuse(all_kw_hits, all_vec_hits, all_graph_hits)
        else:
            # 关闭融合：简单合并（向量结果在前，关键词结果在后），不做 RRF 排序
            ordered, pool = self._simple_merge(all_kw_hits, all_vec_hits, all_graph_hits)

        # ④ 重排序（Re-rank）：综合多维度分数二次排序
        #    两种模式：
        #      - rule（规则式）：RRF分 + 向量分 + 关键词分 + 来源加成，零成本
        #      - semantic（语义级/Cross-Encoder）：调用大模型判断每段与问题的相关性，更精准但多1次API调用
        if use_rerank:
            import config_service
            rerank_mode = str(config_service.get_config("rag_rerank_mode", self.db, "rule")).strip().lower()
            rerank_candidates = int(config_service.get_config("rag_rerank_candidate_limit", self.db, 10))
            if rerank_mode == "semantic":
                final_ordered = self.cross_encoder.rerank(
                    ordered, pool, question,
                    top_k=tk, candidate_limit=rerank_candidates,
                )
                rerank_type = "semantic"
            else:
                final_ordered = self.reranker.rerank(
                    ordered, pool, all_vec_hits, all_kw_hits, question,
                )
                rerank_type = "rule"
        else:
            final_ordered = ordered   # 关闭重排序：直接用融合结果
            rerank_type = "off"

        # ④.5 Self-RAG 相关性过滤（ISREL）：让大模型对每个片段打1-5分，过滤掉≤2分的
        #    重排序是规则式打分，Self-RAG 是大模型语义打分，更精准但多一次大模型调用
        import config_service
        use_self_rag = bool(config_service.get_config("ai_self_rag_enabled", self.db))
        use_relevance_filter = use_self_rag and bool(
            config_service.get_config("ai_self_rag_relevance_filter", self.db))
        if use_relevance_filter and final_ordered:
            try:
                # 提取候选片段的纯文本内容（取前 top_k*2 个供大模型筛选）
                # 三路来源的文本载体不同，都要认出来，否则该路候选会被当成
                # "空文本"跳过打分，随后被过滤后的集合排除掉——图谱事实就
                # 是这样被无声丢掉的（它只存了 graph 文档，没有 chunk/faq）。
                candidate_texts = []
                candidate_keys = []
                for key, _score in final_ordered[:tk * 2]:
                    item = pool.get(key) or {}
                    chunk = item.get("chunk")
                    faq_row = item.get("faq")
                    graph_doc = item.get("graph")
                    if faq_row is not None:
                        text = f"问：{faq_row.question} 答：{faq_row.answer}"
                    elif chunk is not None:
                        text = chunk.content or ""
                    elif graph_doc is not None:
                        text = getattr(graph_doc, "content", "") or ""
                    else:
                        continue
                    if text.strip():
                        candidate_texts.append(text[:300])
                        candidate_keys.append(key)

                if len(candidate_texts) > 1:
                    # 从系统参数读取相关性过滤阈值（默认3，即过滤≤2分）
                    rel_threshold = int(config_service.get_config(
                        "ai_self_rag_relevance_threshold", self.db, 3) or 3)
                    # 调用大模型打分过滤
                    filtered = ai_service.self_rag_filter_relevance(
                        question, candidate_texts, model=None,
                        threshold=rel_threshold)
                    # 用过滤后的结果重新排序
                    if filtered:
                        score_map = {candidate_keys[i]: f["score"]
                                     for i, f in enumerate(filtered)
                                     if i < len(candidate_keys)}
                        # 只保留过滤后的 key，按大模型打分降序
                        filtered_keys = {candidate_keys[i] for i, f in enumerate(filtered)
                                         if i < len(candidate_keys)}
                        final_ordered = [(k, float(score_map.get(k, 0)))
                                         for k in filtered_keys
                                         if k in score_map]
                        final_ordered.sort(key=lambda x: -x[1])
                        if debug is not None:
                            debug["self_rag_relevance_filtered"] = len(filtered)
            except Exception as e:
                print(f"[rag] Self-RAG 相关性过滤失败，使用原排序：{e}")

        # ⑤ 调试信息
        if debug is not None:
            self._fill_debug(debug, queries, all_kw_hits, all_vec_hits,
                             ordered, final_ordered, vector_errors, all_graph_hits)
            debug["module_switches"] = {
                "query_rewrite": use_rewrite,
                "vector_retrieval": use_vector,
                "keyword_retrieval": use_keyword,
                "graph_retrieval": use_graph,
                "fusion": use_fusion,
                "rerank": use_rerank,
                "rerank_mode": rerank_type if use_rerank else "off",
                "automerge": use_automerge,
            }
            # 语义重排序时，记录每个候选的语义分数
            if use_rerank and rerank_type == "semantic":
                sem_scores = self.cross_encoder.get_last_scores()
                if sem_scores:
                    debug["semantic_rerank_scores"] = [
                        {"source_type": k[0], "source_key": k[1],
                         "chunk_index": k[2], "semantic_score": round(s, 4)}
                        for k, s in sem_scores
                    ]

        # ⑥ 上下文构建（用最终排序后的结果）
        limit = _max_chars(self.db)
        context, picked_faqs = self.context_builder.build(
            final_ordered, pool, tk, limit, debug)

        # 更新 FAQ 命中次数（用于统计知识库覆盖率）
        for r in picked_faqs:
            try:
                r.hit_count = int(r.hit_count or 0) + 1
            except Exception:
                pass

        if vector_errors:
            print(f"[rag] 本轮部分查询向量检索不可用：{'; '.join(vector_errors)}")

        return context

    @staticmethod
    def _simple_merge(all_kw_hits: list, all_vec_hits: list,
                      all_graph_hits: list = None):
        """融合模块关闭时的简单合并：图谱 → 向量 → 关键词。

        不做 RRF 加权融合，直接把三路结果拼在一起，用于对比测试。
        图谱排最前，是因为它只在问题里出现具体实体时才产出，
        一旦命中就说明是"问某个具体人/单"的关系型问题，含金量最高。

        返回：
            (ordered, pool) 与 FusionModule.fuse() 相同格式
        """
        pool = {}
        ordered = []

        # 图谱事实在前（按实体匹配可信度降序）
        for doc in sorted(all_graph_hits or [],
                          key=lambda d: -(getattr(d, "score", 0) or 0)):
            meta = getattr(doc, "metadata", None) or {}
            key = ("graph", str(meta.get("node_id") or ""), 0)
            pool.setdefault(key, {})["graph"] = doc
            ordered.append((key, float(getattr(doc, "score", 0) or 0)))

        # 向量结果次之（按相似度降序）
        vec_sorted = sorted(all_vec_hits, key=lambda h: -h.get("score", 0))
        for h in vec_sorted:
            c = h.get("chunk")
            if c is None:
                continue
            key = (c.source_type, c.source_key, int(c.chunk_index or 0))
            pool.setdefault(key, {})["chunk"] = c
            ordered.append((key, float(h.get("score", 0))))

        # 关键词结果最后（按 BM25 分数降序）
        kw_sorted = sorted(all_kw_hits, key=lambda x: -float(x[0]))
        for _s, r, _qi, _rank in kw_sorted:
            key = ("faq", str(r.id), 0)
            if key in pool:
                continue   # 已在向量结果中，不重复
            pool.setdefault(key, {})["faq"] = r
            ordered.append((key, float(_s) * 0.01))  # 关键词分数缩放到0~1范围

        return ordered, pool

    def _fill_debug(self, debug: dict, queries: list, all_kw_hits: list,
                    all_vec_hits: list, ordered: list, reranked: list,
                    vector_errors: list, all_graph_hits: list = None):
        """填充调试信息（查询变体、各通道命中、RRF 分数、重排序结果等），供前端展示检索过程。

        参数：
            debug: 调试信息字典（会被原地更新）
            queries: 查询变体列表
            all_kw_hits: 关键词命中列表
            all_vec_hits: 向量命中列表
            ordered: RRF 融合后的排序列表
            reranked: 重排序后的排序列表
            vector_errors: 向量检索错误列表
            all_graph_hits: 图谱命中列表（Document 对象）
        """
        import ai_service

        per_query = []
        for qi, qinfo in enumerate(queries):
            q_kw = [(s, r) for s, r, qidx, _ in all_kw_hits if qidx == qi]
            q_vec = [h for h in all_vec_hits if h["query_index"] == qi]
            per_query.append({
                "query": qinfo["query"], "type": qinfo.get("type", "?"),
                "keyword_hits": [{"id": r.id,
                                  "question": ai_service.render_placeholders(r.question, self.db),
                                  "score": int(s)} for s, r in q_kw[:5]],
                "vector_hits": [{
                    "title": h["chunk"].title or "", "score": h["score"],
                    "merged": h.get("merged", False), "hit_ratio": h.get("hit_ratio", 0),
                    "content": ai_service.render_placeholders(h["chunk"].content or "", self.db)[:100],
                } for h in q_vec[:5]],
            })

        # 图谱这一路不对应任何查询变体（它只吃原始问题），单独列一段
        graph_items = []
        for doc in (all_graph_hits or []):
            meta = getattr(doc, "metadata", None) or {}
            graph_items.append({
                "label": meta.get("label", ""),
                "key": meta.get("key", ""),
                "node_name": meta.get("node_name", ""),
                "match_field": meta.get("match_field", ""),
                "score": round(float(getattr(doc, "score", 0) or 0), 4),
                # 截断放宽到 600：评估模块要把这段文本当成"检索到的上下文"
                # 去算 Faithfulness/Recall，而图谱的关键数字（好评率、消费额、
                # 接单数）都在事实正文的后半段，原先的 200 字符会把它们切掉，
                # 导致 AI 明明照着实答，却被判成"上下文里没有、属于编造"。
                "content": (getattr(doc, "content", "") or "")[:600],
            })

        debug.update({
            "vector_error": "; ".join(vector_errors) if vector_errors else "",
            "all_queries": [{"query": q["query"], "type": q.get("type", "?")} for q in queries],
            "per_query_results": per_query,
            "graph_hits": graph_items,
            "fused_keys": [{"source_type": k[0], "source_key": k[1], "chunk_index": k[2],
                            "rrf": round(v, 6)} for k, v in ordered[:20]],
            "reranked_keys": [{"source_type": k[0], "source_key": k[1], "chunk_index": k[2],
                               "combined_score": round(v, 6)} for k, v in reranked[:20]],
            "injected_items": 0, "injected_chars": 0,
        })
