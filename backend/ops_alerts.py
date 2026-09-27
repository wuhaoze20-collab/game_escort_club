"""运行期异常留痕：把「被防御代码兜住的异常」记下来，供后台查看。

动机
----
项目里有不少防御性写法是**静默回退**的：
  · 系统参数读失败 → 用出厂默认值继续跑
  · 可提现额算出负值 → 归零后照常返回
  · 初始化失败 → 只打印一行就继续启动

好处是业务不会崩，坏处是**出了问题没人知道** —— 管理员会以为自己在用后台设置的参数，
实际系统正按默认值运行；账目不一致也只会看到 0 而不是一个提示。

这里把这类事件留下来（进程内、有上限、同一 key 合并计数），由 /api/config/all 带出去，
前端在「系统参数」页顶部显示告警条。**不是日志系统**，只为让静默故障变得可见。
"""

from datetime import datetime

# key -> {"at": 时间, "message": 说明, "count": 次数}
_recent: dict[str, dict] = {}

# 最多保留多少条不同的告警（避免无限增长）
MAX_KEEP = 50


def record(key: str, message: str) -> None:
    """记一条告警。同一 key 重复出现只累加次数并刷新时间，不重复占位。"""
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        item = _recent.get(key)
        if item:
            item["at"] = now
            item["message"] = message
            item["count"] += 1
        else:
            if len(_recent) >= MAX_KEEP:
                # 丢弃最早的一条，给新告警腾位置
                oldest = min(_recent.items(), key=lambda kv: kv[1]["at"])[0]
                _recent.pop(oldest, None)
            _recent[key] = {"at": now, "message": message, "count": 1}
    except Exception:
        # 留痕本身绝不能影响业务
        pass


def list_alerts() -> list[dict]:
    """按时间倒序列出告警（最新的在前）"""
    return [
        {"key": k, "at": v["at"], "message": v["message"], "count": v["count"]}
        for k, v in sorted(_recent.items(), key=lambda kv: kv[1]["at"], reverse=True)
    ]


def clear() -> None:
    _recent.clear()
