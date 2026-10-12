"""知识图谱模块（Knowledge Graph）。

把项目里的三类业务实体——老板、打手、订单——以及它们之间的关系
建成一张图，存进 Neo4j，供后台可视化查看、也便于后续把图谱接进
RAG 做多跳关系检索。

=== 图长什么样 ===

    (Boss) --PLACED--> (Order) --FOR_GAME--> (Game)
                         ^
                         | SERVED
                         |
                      (Player) --HAS_TAG--> (Tag)

    (Boss) --HIRED--> (Player)      # 由订单推导

=== 三个文件的分工 ===

    store.py   最底层：怎么连 Neo4j、怎么跑 Cypher（不含业务语义）
    schema.py  图谱的"字典"：有哪些节点/关系/字段、哪些字段敏感
    sync.py    同步：从 MySQL 业务表 → 图谱（全量 + 单笔订单增量）
    api.py     对外接口：查询、搜索、可视化数据、重建

=== 设计上的一条硬规则 ===

图谱是"旁路"：它**不是**业务数据的真相源，MySQL 才是。
所有图谱写入都走 store.run_safe()，失败了只打印日志，
绝不让下单、结单这些核心操作因为图数据库抖动而失败。

使用示例：
    from kg import sync, store
    sync.sync_order(db, order)        # 新订单入图
    store.stats()                     # 图谱实况
"""

from . import store, schema, sync

__all__ = ["store", "schema", "sync"]
