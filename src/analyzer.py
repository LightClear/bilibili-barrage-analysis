"""弹幕统计分析与前端数据构造。

当前已模块已实现功能：
1. 生成前端 ECharts 页面所需的完整数据结构
2. 汇总视频数量、弹幕数量、播放量和点赞量
3. 按视频内分钟统计弹幕出现数量
4. 统计弹幕文本长度区间分布
5. 使用 jieba 分词生成高频词数据
6. 过滤过短、纯空白或用户配置的停用词 --5.27
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

import jieba

from src.query import count_by_user_hash

DistributionBucket = tuple[str, float, float | None]
MAX_DISTRIBUTION_BUCKETS = 10
FRONTEND_LENGTH_BUCKETS: list[DistributionBucket] = [
    ("1-5", 0, 5),
    ("6-10", 6, 10),
    ("11-20", 11, 20),
    ("20+", 21, None),
]


def build_dashboard_payload(
    videos: list[dict[str, Any]],
    danmakus: list[dict[str, Any]],
    top_n_words: int = 80,
    stop_words: list[str] | None = None,
    time_buckets: list[DistributionBucket] | None = None,
    length_buckets: list[DistributionBucket] | None = None,
    case_sensitive: bool = False,
) -> dict[str, Any]:
    """生成前端 ECharts 页面所需的完整数据结构。"""

    return {
        "summary": build_summary(videos, danmakus), #汇总视频数量、弹幕数量、播放量和点赞量
        "time_distribution": build_time_distribution(danmakus, buckets=time_buckets), #按视频内时间区间统计弹幕出现数量
        "length_distribution": build_length_distribution(danmakus, buckets=length_buckets), #统计弹幕文本长度区间分布
        "word_cloud": build_word_cloud(danmakus, top_n=top_n_words, stop_words=stop_words, case_sensitive=case_sensitive), #使用 jieba 分词生成高频词数据
        "user_hash_rank": count_by_user_hash(danmakus), #统计用户哈希出现数量
        "raw_videos": videos, #原始视频数据
    }


def build_summary(videos: list[dict[str, Any]], danmakus: list[dict[str, Any]]) -> dict[str, int]:
    """汇总视频数量、弹幕数量、播放量和点赞量。"""

    return {
        "danmaku_count": len(danmakus), #弹幕数量
        "total_view": sum(int(video.get("view", 0) or 0) for video in videos), #播放量
        "total_like": sum(int(video.get("like", 0) or 0) for video in videos), #点赞量
    }


def build_time_distribution(
    danmakus: list[dict[str, Any]],
    buckets: list[DistributionBucket] | None = None,
) -> list[dict[str, int]]:
    """按视频内时间统计弹幕出现数量。

    不传 buckets 时保持旧逻辑：按自然分钟分组。
    传入 buckets 时按用户配置的秒级区间分组。
    """

    if buckets:
        return build_bucket_distribution(
            [float(row.get("time_in_video", 0)) for row in danmakus],
            buckets,
        )

    counter: dict[int, int] = defaultdict(int)
    for row in danmakus:
        minute = int(float(row.get("time_in_video", 0)) // 60)
        counter[minute] += 1
    return [{"minute": minute, "count": counter[minute]} for minute in sorted(counter)]


def build_length_distribution(
    danmakus: list[dict[str, Any]],
    buckets: list[DistributionBucket] | None = None,
) -> list[dict[str, Any]]:
    """统计弹幕文本长度区间分布。"""

    active_buckets = buckets or [
        ("0-5", 0, 5),
        ("6-10", 6, 10),
        ("11-20", 11, 20),
        ("21-40", 21, 40),
        ("40+", 41, None),
    ]
    return build_bucket_distribution(
        [len(str(row.get("content", ""))) for row in danmakus],
        active_buckets,
    )


def build_bucket_distribution(
    values: list[float],
    buckets: list[DistributionBucket],
) -> list[dict[str, Any]]:
    """根据用户配置的区间统计数值分布。"""

    validate_distribution_buckets(buckets)
    counts = {label: 0 for label, _, _ in buckets}
    for value in values:
        for label, start, end in buckets:
            upper = float("inf") if end is None else end
            if start <= value <= upper:
                counts[label] += 1
                break
    return [{"range": label, "count": counts[label]} for label, _, _ in buckets]


def validate_distribution_buckets(buckets: list[DistributionBucket]) -> None:
    """校验用户自定义区间数量，避免前端展示和统计结果过载。"""

    if not buckets:
        raise ValueError("区间组不能为空")
    if len(buckets) > MAX_DISTRIBUTION_BUCKETS:
        raise ValueError("自定义区间最多只能设置 10 组")


def build_word_cloud(
    danmakus: list[dict[str, Any]],
    top_n: int = 80,
    stop_words: list[str] | None = None,
    case_sensitive: bool = False,
) -> list[dict[str, Any]]:
    """使用 jieba 分词生成高频词数据。"""

    counter: Counter[str] = Counter()
    stop_word_set: set[str] = set()
    for w in (stop_words or []):
        w = w.strip()
        if w:
            stop_word_set.add(w if case_sensitive else w.lower())
    for row in danmakus:
        text = str(row.get("content", ""))
        for word in jieba.cut(text):
            normalized = word.strip()
            if is_valid_word(normalized, stop_word_set, case_sensitive=case_sensitive):
                counter[normalized] += 1
    return [{"name": word, "value": count} for word, count in counter.most_common(top_n)]


def build_frontend_video_stats(
    danmakus: list[dict[str, Any]],
    *,
    duration: int = 0,
    top_n_words: int = 80,
    stop_words: list[str] | None = None,
    filter_signature: str = "",
) -> dict[str, Any]:
    """构造 BV 搜索结果可直接交给前端图表使用的单视频统计。"""

    return {
        "source": "server",
        "filter_signature": filter_signature,
        "danmaku_count": len(danmakus),
        "time_series": build_frontend_time_series(danmakus, duration=duration),
        "length_buckets": {
            item["range"]: item["count"]
            for item in build_length_distribution(danmakus, buckets=FRONTEND_LENGTH_BUCKETS)
        },
        "word_cloud": build_word_cloud(danmakus, top_n=top_n_words, stop_words=stop_words),
        "user_rank": [
            {"userHash": item["user_hash"], "count": item["count"]}
            for item in count_by_user_hash(danmakus)[:20]
        ],
    }


def build_frontend_time_series(danmakus: list[dict[str, Any]], *, duration: int = 0) -> dict[str, list[Any]]:
    """按自然分钟构造前端折线图使用的 labels/values。"""

    counter: dict[int, int] = defaultdict(int)
    max_minute = max(0, int((max(0, int(duration or 0)) + 59) // 60))
    for row in danmakus:
        minute = int(float(row.get("time_in_video", 0) or 0) // 60)
        max_minute = max(max_minute, minute)
        counter[minute] += 1
    minutes = list(range(max_minute + 1))
    return {
        "labels": [f"{minute}分" for minute in minutes],
        "values": [counter[minute] for minute in minutes],
    }


def is_valid_word(word: str, stop_words: set[str] | None = None, case_sensitive: bool = False) -> bool:
    """过滤过短、纯空白或用户配置的停用词。"""

    if not word or len(word) < 2:
        return False
    if not stop_words:
        return True
    target = word if case_sensitive else word.lower()
    return target not in stop_words
