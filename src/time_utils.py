"""时间处理工具，统一使用北京时间。

当前已模块已实现功能：
1. 把 Unix 时间戳转换成北京时间字符串。
2. 返回当前北京时间。 --5.27
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


BEIJING_TZ = timezone(timedelta(hours=8))


def timestamp_to_beijing_text(timestamp: int | float) -> str:
    """把 Unix 时间戳转换成北京时间字符串。"""

    dt = datetime.fromtimestamp(float(timestamp), tz=BEIJING_TZ)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def now_beijing() -> datetime:
    """返回当前北京时间。"""

    return datetime.now(tz=BEIJING_TZ)
