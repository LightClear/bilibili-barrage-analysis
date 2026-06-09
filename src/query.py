"""弹幕查询与排序模块。

当前已模块已实现功能：
1. 按内容或 user_hash 查询弹幕，并按指定字段排序。
2. 统计相同 user_hash 发送的弹幕量，并按数量降序排列。 --5.27
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Literal


SortField = Literal["time_in_video", "user_hash"]


def query_danmakus(
    danmakus: list[dict[str, Any]],
    content: str | None = None,
    user_hash: str | None = None,
    sort_by: SortField = "time_in_video",
) -> list[dict[str, Any]]:
    """按内容或 user_hash 查询弹幕，并按指定字段排序。"""

    if sort_by not in {"time_in_video", "user_hash"}:
        raise ValueError("sort_by 只能是 time_in_video 或 user_hash")

    rows = []
    content_keyword = content.lower() if content else None
    for row in danmakus:
        row_content = str(row.get("content", ""))
        row_user_hash = str(row.get("user_hash", ""))

        if content_keyword and content_keyword not in row_content.lower():
            continue
        if user_hash and user_hash != row_user_hash:
            continue
        rows.append(dict(row))

    if sort_by == "time_in_video":
        return sorted(rows, key=lambda row: float(row.get("time_in_video", 0)))
    return sorted(rows, key=lambda row: (str(row.get("user_hash", "")), float(row.get("time_in_video", 0))))


def count_by_user_hash(danmakus: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """统计相同 user_hash 发送的弹幕量，并按数量降序排列。"""

    counter = Counter(str(row.get("user_hash", "")) for row in danmakus if row.get("user_hash"))
    return [{"user_hash": user_hash, "count": count} for user_hash, count in counter.most_common()]
