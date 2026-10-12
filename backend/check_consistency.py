# -*- coding: utf-8 -*-
"""一致性自检：前端菜单 / 后端权限 / AI 角色上下文 三者是否同步。

为什么需要这个脚本
------------------
`ai_service.py` 里的 ROLE_MENUS / ROLE_CAPS / ROLE_FLOWS 是**手工抄写**的：
· ROLE_MENUS 必须与 frontend/index.html 的 menuConfig 一致
· ROLE_CAPS  必须与各接口上的 require_roles(...) 一致

历史上正是因为漏同步，AI 才会编造出不存在的菜单项与越权操作路径（见 CHANGELOG V3.3.x）。
靠人记是记不住的，所以做成脚本，改动菜单/权限后跑一次即可。

检查项
------
A. ROLE_MENUS 与 menuConfig 的分组名、菜单项名是否逐字一致
B. menuConfig 里每个 key 是否都有对应的 <section id="page-KEY">（否则点了会空白）
C. 是否存在"没人能到达"的页面（section 存在但不在任何角色菜单里）
D. 前端 apiRequest 调用的 URL 是否都真实存在于后端路由表（防前端调不存在的接口）
E. ROLE_FLOWS / ROLE_CAPS 里写的「分组 → 菜单项」路径是否真实存在于该角色菜单
   —— 这条最关键：它正是"AI 编造操作路径"的自动拦截

用法
----
    venv\\Scripts\\python check_consistency.py          # 打印报告
    venv\\Scripts\\python check_consistency.py --strict # 有 ERROR 时以非 0 退出（供提交前检查）
"""

import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE_DIR)
INDEX_HTML = os.path.join(ROOT, "frontend", "index.html")
API_DIR = os.path.join(BASE_DIR, "api")
# 除 api/ 之外，还可能有独立的业务包自带路由。
# 例如知识图谱的端点写在 kg/api.py（api/kg_api.py 只做一行转发），
# 不扫这里就会把 /api/kg/* 误判成"前端调了不存在的接口"。
EXTRA_ROUTE_DIRS = [os.path.join(BASE_DIR, "kg")]

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

ERRORS = []
WARNINGS = []
OKS = []


def err(msg):
    ERRORS.append(msg)


def warn(msg):
    WARNINGS.append(msg)


def ok(msg):
    OKS.append(msg)


# ——————————————————————————————————————————————
# 1) 解析前端 menuConfig / 页面 / 接口调用
# ——————————————————————————————————————————————

def parse_frontend():
    src = open(INDEX_HTML, encoding="utf-8").read()

    m = re.search(r"const menuConfig = \{(.*?)\n        \};", src, re.S)
    if not m:
        err("无法从 index.html 解析出 menuConfig")
        return {}, set(), set()
    body = m.group(1)

    menus = {}
    for role in ("admin", "service", "boss", "player"):
        # 最后一个角色后面没有逗号，所以逗号必须可选
        rm = re.search(role + r": \[(.*?)\n            \],?", body, re.S)
        if not rm:
            err(f"menuConfig 里找不到角色 {role}")
            continue
        block = rm.group(1)
        groups = []
        # 每个 { group: 'X', items: [ ... ] }
        for gm in re.finditer(r"\{\s*group:\s*'([^']+)'\s*,\s*items:\s*\[(.*?)\]\s*\}", block, re.S):
            gname = gm.group(1)
            items = [(k, l) for k, l in
                     re.findall(r"key:\s*'([^']+)'\s*,\s*label:\s*'([^']+)'", gm.group(2))]
            groups.append((gname, items))
        menus[role] = groups

    # <section id="page-xxx">
    pages = set(re.findall(r'<section\s+id="page-([a-z0-9\-]+)"', src))
    # apiRequest('...') / apiRequest(`...`)
    # 关键：模板字符串里的 ${expr} 必须先换成 {}，否则 `/api/config/${key}` 会被
    # 截成 "/api/config/" 而误报"接口不存在"（本脚本最初就踩了这个坑）。
    call_src = re.sub(r"\$\{[^}]*\}", "{}", src)
    calls = set()
    for c in re.findall(r"apiRequest\(\s*[`'\"]([^`'\"]+)[`'\"]", call_src):
        if c.startswith("/api"):
            calls.add(c.split("?")[0])
    return menus, pages, calls


# ——————————————————————————————————————————————
# 2) 解析后端路由表
# ——————————————————————————————————————————————

def parse_routes():
    """返回 (route_set, path_set)。

    route_set 元素是 (方法, 完整路径)，用于统计"多少条路由"；
    path_set 只有归一化后的路径，用于检查"前端调的路径存不存在" ——
    后者必须去重，否则 GET/POST 同一个路径（如 /api/player/tags）会被当成两条。

    注意：除 `backend/api/*.py` 的 router 外，还要收 `main.py` 里直接挂在 app 上的
    应用级路由（当前只有 `GET /` 返回首页），否则总数会与 /openapi.json 对不上。
    """
    route_set = set()
    path_set = set()

    for fn in sorted(os.listdir(API_DIR)) if os.path.isdir(API_DIR) else []:
        if not fn.endswith(".py"):
            continue
        src = open(os.path.join(API_DIR, fn), encoding="utf-8").read()
        pm = re.search(r'APIRouter\(\s*prefix\s*=\s*["\']([^"\']*)["\']', src)
        prefix = pm.group(1) if pm else ""
        for m in re.finditer(r'@router\.(get|post|put|delete|patch)\(\s*["\']([^"\']+)["\']', src):
            route_set.add((m.group(1).upper(), prefix + m.group(2)))
            path_set.add(norm_path(prefix + m.group(2)))

    for d in EXTRA_ROUTE_DIRS:
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".py"):
                continue
            src = open(os.path.join(d, fn), encoding="utf-8").read()
            pm = re.search(r'APIRouter\(\s*prefix\s*=\s*["\']([^"\']*)["\']', src)
            if not pm:
                continue
            prefix = pm.group(1)
            for m in re.finditer(r'@router\.(get|post|put|delete|patch)\(\s*["\']([^"\']+)["\']', src):
                route_set.add((m.group(1).upper(), prefix + m.group(2)))
                path_set.add(norm_path(prefix + m.group(2)))

    # 应用级路由（@app.get(...) 等），如 main.py 的首页 "/"
    main_py = os.path.join(BASE_DIR, "main.py")
    if os.path.isfile(main_py):
        src = open(main_py, encoding="utf-8").read()
        for m in re.finditer(r'@app\.(get|post|put|delete|patch)\(\s*["\']([^"\']+)["\']', src):
            route_set.add((m.group(1).upper(), m.group(2)))
            path_set.add(norm_path(m.group(2)))

    if not route_set:
        err("没有解析到任何路由（backend/api 目录或 main.py 有问题？）")
    return route_set, path_set


def norm_path(p):
    """把路径参数统一成 {}，便于与前端实际调用比较"""
    p = p.split("?")[0].rstrip("/")
    return re.sub(r"\{[^}]+\}", "{}", p)


# ——————————————————————————————————————————————
# 3) 各项检查
# ——————————————————————————————————————————————

def check_a(menus, ai):
    """A. ROLE_MENUS 与 menuConfig 一致"""
    for role, groups in menus.items():
        ai_groups = ai.ROLE_MENUS.get(role) or []
        fe_group = [g for g, _ in groups]
        ai_group = [g for g, _ in ai_groups]

        if fe_group != ai_group:
            err(f"[A] {role} 分组不一致\n"
                f"      前端: {fe_group}\n"
                f"      ai_service.ROLE_MENUS: {ai_group}")
        else:
            ok(f"[A] {role} 分组名一致（{len(fe_group)} 组）")

        ai_map = dict(ai_groups)
        for g, items in groups:
            fe_labels = [l for _, l in items]
            ai_text = ai_map.get(g, "")
            ai_labels = [x.strip() for x in re.split(r"[、,，]", ai_text) if x.strip()]
            if fe_labels != ai_labels:
                err(f"[A] {role} / 分组「{g}」菜单项不一致\n"
                    f"      前端: {fe_labels}\n"
                    f"      ai_service.ROLE_MENUS: {ai_labels}")
            else:
                ok(f"[A] {role} / 「{g}」菜单项一致（{len(fe_labels)} 项）")


def check_bc(menus, pages):
    """B. key 有对应 section；C. 没有不可达页面"""
    used = set()
    for role, groups in menus.items():
        for _, items in groups:
            for k, label in items:
                used.add(k)
                if k not in pages:
                    err(f"[B] 角色 {role} 的菜单项「{label}」(key={k}) 没有对应的 "
                        f"<section id=\"page-{k}\">，点击后会空白")
    if not ERRORS:
        ok(f"[B] {len(used)} 个菜单 key 都有对应页面")

    orphan = sorted(pages - used)
    if orphan:
        warn(f"[C] 以下页面存在但不在任何角色菜单里（不可达）: {orphan}")
    else:
        ok(f"[C] 无不可达页面（共 {len(pages)} 个页面全部可从菜单到达）")


def _segs(p):
    p = p.split("?")[0].rstrip("/")
    return p.split("/") if p else []


def path_is_known(call, route_seg_list):
    """判断前端调用能否匹配到某条真实路由。

    要处理三种前端写法，否则会误报"接口不存在"：
    1. 模板字符串 `` `/api/config/${key}` ``  → 预处理成 `/api/config/{}`，段数一致、{} 通配
    2. 字符串拼接 `'/api/quote/' + id`       → 只能拿到前缀 `/api/quote/`，按"前缀匹配"判定
    3. 动态动作 `` `/api/withdraw/${id}/${action}` `` → 前端不确定动作，{} 通配到任意一段
    """
    csegs = _segs(call)
    raw = call.split("?")[0]
    is_prefix = raw.endswith("/")   # 形态 2：拼接导致 URL 被截断

    for rsegs in route_seg_list:
        if is_prefix:
            # 前缀匹配：路由比调用多若干段即认为存在（如 /api/config/ → /api/config/{k}/reset）
            if len(rsegs) > len(csegs) and rsegs[:len(csegs)] == csegs:
                return True
            continue
        if len(rsegs) != len(csegs):
            continue
        if all(cs == "{}" or rs == "{}" or cs == rs for cs, rs in zip(csegs, rsegs)):
            return True
    return False


def check_d(calls, routes):
    """D. 前端调用的 URL 都在后端路由表里"""
    route_seg_list = [_segs(r) for r in routes]
    missing = sorted({c for c in calls if not path_is_known(c, route_seg_list)})
    if missing:
        for c in missing:
            err(f"[D] 前端调用了不存在的后端接口: {c}")
    else:
        ok(f"[D] 前端 {len(calls)} 个接口调用全部命中后端路由表")


def check_e(menus, ai):
    """E. ROLE_FLOWS / ROLE_CAPS 里写的菜单路径是否真实存在"""
    def valid_path(role, text):
        """校验形如 左侧菜单「分组」→「菜单项」 的路径"""
        gm = re.search(r"「([^」]+)」\s*→\s*(?:进入)?「([^」]+)」", text)
        if not gm:
            return None  # 不是标准路径写法，跳过
        group, item = gm.group(1), gm.group(2)
        if group == "左侧菜单":
            gm2 = re.search(r"「左侧菜单」\s*→\s*「([^」]+)」\s*→\s*「([^」]+)」", text)
            if not gm2:
                return None
            group, item = gm2.group(1), gm2.group(2)
        groups = dict((g, [l for _, l in items]) for g, items in menus.get(role, []))
        if group not in groups:
            return f"分组「{group}」不存在"
        if item not in groups[group]:
            return f"分组「{group}」里没有「{item}」"
        return None

    bad = 0
    for role, flows in (ai.ROLE_FLOWS or {}).items():
        for name, path in flows:
            why = valid_path(role, path)
            if why:
                err(f"[E] {role} 的操作路径「{name}」有误：{why}\n      原文: {path}")
                bad += 1
    for role, caps in (ai.ROLE_CAPS or {}).items():
        for key in ("can", "cannot"):
            for text in caps.get(key) or []:
                why = valid_path(role, text)
                if why:
                    err(f"[E] {role} 的能力描述({key})路径有误：{why}\n      原文: {text[:80]}")
                    bad += 1
    if not bad:
        ok("[E] ROLE_FLOWS / ROLE_CAPS 里的菜单路径全部真实存在")


def main():
    strict = "--strict" in sys.argv
    # Windows 控制台默认 GBK，直接打印 ✓/✗ 会 UnicodeEncodeError；统一降级为可编码字符
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    import ai_service

    menus, pages, calls = parse_frontend()
    route_set, path_set = parse_routes()
    total_routes = len(route_set)
    total_paths = len(path_set)
    route_paths = {p for _, p in route_set}

    print("=" * 66)
    print("一致性自检：前端菜单 / 后端路由 / AI 角色上下文")
    print("=" * 66)
    print(f"前端角色 {len(menus)} 个 · 页面 {len(pages)} 个 · 接口调用 {len(calls)} 个")
    print(f"后端路由 {total_routes} 条（含 main.py 的应用级路由；与 /openapi.json 的 paths 数应当一致）")
    print()

    check_a(menus, ai_service)
    check_bc(menus, pages)
    check_d(calls, route_paths)
    check_e(menus, ai_service)

    lines = []
    lines.append("-" * 66)
    for m in OKS:
        lines.append("  [OK]   " + m)
    for m in WARNINGS:
        lines.append("  [WARN] " + m)
    for m in ERRORS:
        lines.append("  [ERR]  " + m)
    lines.append("-" * 66)
    lines.append(f"通过 {len(OKS)} · 警告 {len(WARNINGS)} · 错误 {len(ERRORS)}")
    if ERRORS:
        lines.append("")
        lines.append("存在不一致，请修正后再提交。")
    else:
        lines.append("")
        lines.append("三者完全一致。")

    for ln in lines:
        print(ln)

    # --out FILE：把完整报告以 UTF-8 写文件。
    # 为什么需要：Windows 控制台是 GBK，用 `>` 重定向会把中文写成 GBK 字节，
    # 再被当成二进制读不出来。脚本自己写 UTF-8 最稳。
    if "--out" in sys.argv:
        i = sys.argv.index("--out")
        if i + 1 < len(sys.argv):
            head = [
                "=" * 66,
                "一致性自检：前端菜单 / 后端路由 / AI 角色上下文",
                "=" * 66,
                f"前端角色 {len(menus)} 个 · 页面 {len(pages)} 个 · 接口调用 {len(calls)} 个",
                f"后端路由 {total_routes} 条 · 归一化路径 {total_paths} 个"
                f"（差额来自同一路径的不同方法，如 GET/POST /api/player/tags）",
                "",
            ]
            with open(sys.argv[i + 1], "w", encoding="utf-8") as f:
                f.write("\n".join(head + lines) + "\n")

    if ERRORS:
        return 1 if strict else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
