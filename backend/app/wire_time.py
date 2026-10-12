"""接口里的时间只从这里出：带时区的 ISO 字符串。

SQLite 读回来的 datetime 没有时区（存的是 UTC），直接 isoformat() 出去没有偏移，
浏览器和 Dart 都会把它当本地时间 → 东八区差 8 小时、日期分隔/“今天 08:00”全错。
所以凡是发给客户端的 datetime 都走 iso()：无时区按 UTC 补上；date 原样（只是日期，不涉时区）。"""
from datetime import date, datetime, timezone
from typing import Any


def iso(v: datetime | None) -> str | None:
    if v is None:
        return None
    return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()


def wire(v: Any) -> Any:
    """通用序列化：datetime → iso()，date → YYYY-MM-DD，别的原样。"""
    if isinstance(v, datetime):
        return iso(v)
    if isinstance(v, date):
        return v.isoformat()
    return v
