# -*- coding: utf-8 -*-
"""接口冒烟测试：4 种角色登录，遍历全部无参 GET 接口，报告 500 与非预期状态码。

用途
----
改动后端代码（尤其接口层、鉴权、序列化）后跑一遍，确认没有把接口改坏。
它只做"读"操作，不写数据，可安全重复运行。

前提：后端已在 127.0.0.1:8000 运行。

用法
----
    python check_api.py
"""

import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"

# 四种角色的测试账号（密码统一 123456，来自项目的默认账户初始化）
ACCOUNTS = [
    ("guanliyuan", "admin"),
    ("kefu", "service"),
    ("laoban", "boss"),
    ("dashou", "player"),
]
PASSWORD = "123456"

# 这些状态码在遍历中属正常（403=该角色无权限、404=该角色无此数据、400/422=参数校验）
NORMAL_CODES = {200, 201, 204, 400, 403, 404, 422}


def call(method, path, token=None, data=None):
    """发一个请求，返回 (状态码, 响应体)。连接失败返回 0。"""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return 0, str(e).encode()


def main() -> int:
    # 从 OpenAPI 拿全部路由，只保留不带路径参数的 GET（带参数的需要具体 id）
    try:
        with urllib.request.urlopen(BASE + "/openapi.json", timeout=30) as resp:
            spec = json.load(resp)
    except Exception as e:
        print(f"无法读取 /openapi.json：{e}")
        print("请确认后端已启动（python main.py）。")
        return 1

    paths = sorted(
        p for p, ops in (spec.get("paths") or {}).items()
        if "get" in ops and "{" not in p
    )
    print(f"后端 GET 接口共 {len(paths)} 个\n")

    tokens = {}
    for user, role in ACCOUNTS:
        code, body = call("POST", "/api/login",
                          data={"username": user, "password": PASSWORD})
        if code == 200:
            tokens[user] = json.loads(body)["access_token"]
            print(f"  ✓ {user:<12} ({role}) 登录成功")
        else:
            print(f"  ✗ {user:<12} ({role}) 登录失败 HTTP {code}")

    if not tokens:
        print("\n所有账号登录失败，请检查后端与数据库。")
        return 1

    errors_500 = []
    unexpected = []
    total = 0
    for user, token in tokens.items():
        for p in paths:
            total += 1
            code, _ = call("GET", p, token=token)
            if code == 0:
                unexpected.append((user, p, "连接失败"))
            elif code >= 500:
                errors_500.append((user, p, code))
            elif code not in NORMAL_CODES:
                unexpected.append((user, p, code))

    print("\n" + "=" * 72)
    print(f"共发起 {total} 次请求")
    print("=" * 72)

    print("\n【严重】500 服务器错误：")
    if errors_500:
        for u, p, c in errors_500:
            print(f"  ✗ [{u}] {p} → {c}")
    else:
        print("  无")

    print("\n【其他】非预期状态码：")
    if unexpected:
        for u, p, c in unexpected:
            print(f"  · [{u}] {p} → {c}")
    else:
        print("  无")

    return 1 if (errors_500 or unexpected) else 0


if __name__ == "__main__":
    raise SystemExit(main())
