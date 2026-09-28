# -*- coding: utf-8 -*-
"""AI 工具的安全性自检（权限边界 + 身份绑定）。

为什么单独做一个脚本
--------------------
`ai_tools.py` 是**安全边界**：提示词里那句"你没有权限"只是话术，真正拦住越权的是
这里的 `TOOL_ROLES` 校验与"工具函数签名里没有 username 参数"这一设计。
这类保障一旦被后续改动破坏（例如有人为了"方便"给工具加上 username 参数），
表面上功能照常工作，但 AI 就能查别人的余额了 —— 不会报错、不会被发现。

所以把它做成可重复执行的检查：每次改动 ai_tools.py 或相关权限后跑一次。

用法
----
    venv\\Scripts\\python check_ai_tools.py            # 打印报告
    venv\\Scripts\\python check_ai_tools.py --strict   # 有失败项时以非 0 退出
    venv\\Scripts\\python check_ai_tools.py --out FILE # 写 UTF-8 报告
"""

import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

ERRORS = []
OKS = []


def check(name, cond, extra=""):
    if cond:
        OKS.append(name + (("  " + extra) if extra else ""))
    else:
        ERRORS.append(name + (("  " + extra) if extra else ""))


def main():
    strict = "--strict" in sys.argv
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass

    from database import SessionLocal
    from models import User
    import ai_tools

    db = SessionLocal()
    try:
        by_role = {}
        for u in db.query(User).all():
            by_role.setdefault(u.role, u)

        names_by_role = {r: {t["function"]["name"] for t in ai_tools.available_tools(r)}
                         for r in ("admin", "service", "boss", "player")}

        # ── 1) 敏感工具不得暴露给无权角色 ──
        check("管理员可用 query_monthly_profit",
              "query_monthly_profit" in names_by_role["admin"])
        check("打手不可用 query_monthly_profit",
              "query_monthly_profit" not in names_by_role["player"])
        check("客服不可用 query_monthly_profit",
              "query_monthly_profit" not in names_by_role["service"])
        check("客服不可用 query_my_orders（订单只给买卖双方）",
              "query_my_orders" not in names_by_role["service"])
        check("老板不可用 query_my_withdrawals（提现是打手专属）",
              "query_my_withdrawals" not in names_by_role["boss"])

        # ── 2) 每个工具都必须在 TOOL_ROLES 里登记（防止漏配导致权限判定失效）──
        declared = {t["function"]["name"] for t in ai_tools.TOOLS}
        check("TOOLS 与 TOOL_ROLES 的键完全一致",
              declared == set(ai_tools.TOOL_ROLES), str(declared ^ set(ai_tools.TOOL_ROLES)))

        # ── 3) 铁律：工具函数签名里绝不能有 username 之类的身份参数 ──
        src = open(os.path.join(BASE_DIR, "ai_tools.py"), encoding="utf-8").read()
        impl_src = src.split("_IMPL = {")[0].split("def _tool_")[1:]
        bad_sig = []
        for chunk in impl_src:
            sig = chunk.split("):")[0]
            if re.search(r"\b(username|user_name|account)\b", sig):
                bad_sig.append(chunk.split("\n")[0])
        check("所有工具实现函数签名里都没有身份参数（身份只能来自令牌）",
              not bad_sig, "; ".join(bad_sig))

        # ── 4) 运行时校验：越权调用必须被拒 ──
        if "player" in by_role:
            r = ai_tools.run_tool("query_monthly_profit", {}, db, by_role["player"])
            check("打手运行时调用盈利工具被拒", r["ok"] is False)
            check("拒绝时给出可读原因", "没有权限" in r["result"])

            # 试图通过参数越权查别人 —— 必须失败（签名里根本没这个参数）
            r = ai_tools.run_tool("query_my_balance", {"username": "someone_else"},
                                  db, by_role["player"])
            check("传 username 试图查他人被拒", r["ok"] is False, r["result"][:60])

            # 结果里不能出现其他打手的账号
            r = ai_tools.run_tool("query_my_orders", {}, db, by_role["player"])
            others = [u.username for u in db.query(User).filter(User.role == "player").all()
                      if u.username != by_role["player"].username]
            leaked = [o for o in others if o in r["result"]]
            check("订单结果不泄露其他打手账号", not leaked, str(leaked))

        # ── 5) 编造的工具名 / 非法参数要被挡住 ──
        r = ai_tools.run_tool("query_all_passwords", {}, db, by_role.get("admin"))
        check("不存在的工具名被拒", r["ok"] is False)
        if "player" in by_role:
            r = ai_tools.run_tool("query_my_orders", {"status": "hacked"}, db, by_role["player"])
            check("非法状态值被拒并提示有效取值",
                  r["ok"] is False and "有效取值" in r["result"])
            r = ai_tools.run_tool("query_my_orders", {"limit": 999999}, db, by_role["player"])
            check("limit 被夹到上限（不会拉全表）",
                  r["ok"] and r["result"].count("· 订单号") <= 10)

        # ── 6) 全部工具都必须是只读（不能出现写操作的关键词）──
        write_words = ("create", "update", "delete", "ban", "settle", "approve", "reject")
        offenders = [n for n in declared if any(w in n for w in write_words)]
        check("所有工具都是只读（名字里无写操作动作）", not offenders, str(offenders))

        lines = ["-" * 62,
                 f"通过 {len(OKS)} · 失败 {len(ERRORS)}",
                 ""]
        lines += ["  [OK]   " + m for m in OKS]
        lines += ["  [FAIL] " + m for m in ERRORS]
        lines.append("")
        lines.append("工具层安全边界完好。" if not ERRORS else "存在安全问题，请修正。")
        for ln in lines:
            print(ln)

        if "--out" in sys.argv:
            i = sys.argv.index("--out")
            if i + 1 < len(sys.argv):
                with open(sys.argv[i + 1], "w", encoding="utf-8") as f:
                    f.write("AI 工具安全性自检\n" + "\n".join(lines) + "\n")
    finally:
        db.close()

    return 1 if (ERRORS and strict) else 0


if __name__ == "__main__":
    sys.exit(main())
