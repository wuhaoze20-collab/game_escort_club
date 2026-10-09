# -*- coding: utf-8 -*-
"""结构自检：SQLAlchemy 模型定义 与 实际数据库表结构 是否一致。

为什么需要这个脚本
------------------
项目用 `Base.metadata.create_all()` 建表，但它有两个盲区：
· **已存在的表不会补新列** —— 后续给老表加字段（如 ai_eval_history.config_json），
  自己的库手动 ALTER 过了没事，别人克隆后复用旧库就会报
  `Unknown column 'xxx' in 'field list'`。
· 新表能自动建，所以"加表"安全，"给老表加列"才是坑。

这正是"为什么别人拉取的和我这里不一样"的常见根因。
改动 models.py 后跑一次，能立刻发现漏掉的列。

检查项
------
A. 模型里定义的表是否都在数据库中
B. 每个表：模型有、数据库没有的列（← 会导致运行时 Unknown column）
C. 数据库有、模型没定义的列（多余列，一般无害，仅提示）
D. 缺失的列是否已被 main.py 的 ADD_COLUMNS 自动迁移覆盖

用法
----
    python check_schema.py            # 打印报告
    python check_schema.py --strict   # 有 ERROR 时以非 0 退出（提交前检查）
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import inspect  # noqa: E402

import models  # 导入即把所有模型注册到 Base.metadata，下面才能比对表结构
from database import engine, Base  # noqa: E402
from main import ADD_COLUMNS  # noqa: E402


def main() -> int:
    # 显式引用一次 models：它只为"注册所有模型"而导入，
    # 不加这句，静态检查（pyflakes）会把它误判为多余的导入。
    _ = models.__name__
    insp = inspect(engine)
    db_tables = set(insp.get_table_names())
    model_tables = set(Base.metadata.tables.keys())

    errors = []
    warns = []

    print("=" * 74)
    print("结构自检：模型定义 vs 数据库实际表结构")
    print("=" * 74)

    # A. 表
    missing_tables = sorted(model_tables - db_tables)
    if missing_tables:
        for t in missing_tables:
            errors.append(f"数据库缺少表 {t}")
        print(f"\n[ERR] 数据库缺失 {len(missing_tables)} 张表：")
        for t in missing_tables:
            print(f"      ✗ {t}")
    else:
        print(f"\n[OK] 表：{len(model_tables)} 张全部存在")

    # B / C. 列
    missing_cols = []
    extra_cols = []
    for tname in sorted(model_tables & db_tables):
        try:
            db_cols = {c["name"] for c in insp.get_columns(tname)}
        except Exception as e:  # pragma: no cover
            warns.append(f"{tname} 读取失败：{e}")
            continue
        model_cols = {c.name for c in Base.metadata.tables[tname].columns}
        miss = model_cols - db_cols
        ex = db_cols - model_cols
        if miss:
            missing_cols.append((tname, sorted(miss)))
        if ex:
            extra_cols.append((tname, sorted(ex)))

    if missing_cols:
        print("\n[ERR] 模型有、数据库没有的列（运行时会报 Unknown column）：")
        for t, cols in missing_cols:
            print(f"      ✗ {t}: {', '.join(cols)}")
            errors.append(f"{t} 缺列 {', '.join(cols)}")
    else:
        print("[OK] 列：模型与数据库完全一致")

    if extra_cols:
        print("\n[WARN] 数据库有、模型未定义的列（多余列，一般无害）：")
        for t, cols in extra_cols:
            print(f"      · {t}: {', '.join(cols)}")

    # D. 自动迁移覆盖
    covered = {(t, c) for t, c, _ in ADD_COLUMNS}
    uncovered = [(t, c) for t, cols in missing_cols for c in cols if (t, c) not in covered]
    print("\n[自动迁移] main.py 的 ADD_COLUMNS 已覆盖 %d 个列" % len(covered))
    if uncovered:
        print("[ERR] 以下缺列未被自动迁移覆盖，别人拉取后会报错：")
        for t, c in uncovered:
            print(f"      ✗ {t}.{c}")
            errors.append(f"{t}.{c} 未纳入 ADD_COLUMNS")
    elif missing_cols:
        print("[OK]  所有缺列都已在 ADD_COLUMNS 中，启动时会自动补齐")

    print("\n" + "-" * 74)
    print(f"通过 {len(errors) == 0 and '✓' or ''} · 错误 {len(errors)} · 警告 {len(warns)}")
    if errors:
        print("存在不一致，请修正后再提交。")
        return 1
    print("模型与数据库结构一致。")
    return 0


if __name__ == "__main__":
    code = main()
    sys.exit(code if "--strict" in sys.argv else 0)
