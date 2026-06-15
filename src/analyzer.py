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

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import jieba

from src.query import count_by_user_hash

DistributionBucket = tuple[str, float, float | None]
MAX_DISTRIBUTION_BUCKETS = 10
DEFAULT_SENTIMENT_WORDS = {
    "positive": ["好看", "喜欢", "燃", "燃爆", "精彩", "厉害", "舒服", "支持", "感动", "快乐"],
    "negative": ["无聊", "难看", "浪费", "尴尬", "生气", "讨厌", "离谱", "破防", "垃圾", "失望"],
    "intensity": ["太", "很", "真", "真的", "超级", "爆", "绝了"],
    "negation": ["不", "不是", "没有", "没", "别"],
    "sarcasm": ["典", "孝", "绷", "乐"],
}
SENTIMENT_WORDS_PATH = Path(__file__).resolve().parents[1] / "config" / "sentiment_words.json"
FRONTEND_LENGTH_BUCKETS: list[DistributionBucket] = [
    ("1-5", 0, 5),
    ("6-10", 6, 10),
    ("11-20", 11, 20),
    ("20+", 21, None),
]


def load_sentiment_words(path: Path = SENTIMENT_WORDS_PATH) -> dict[str, list[str]]:
    """加载轻量情绪词典，配置缺失时使用内置兜底。"""

    words = {key: list(value) for key, value in DEFAULT_SENTIMENT_WORDS.items()}
    if not path.exists():
        return words
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return words
    if not isinstance(data, dict):
        return words
    for key in words:
        values = data.get(key)
        if isinstance(values, list):
            cleaned = [str(item).strip() for item in values if str(item).strip()]
            if cleaned:
                words[key] = cleaned
    return words


def classify_sentiment(text: str, words: dict[str, list[str]] | None = None) -> dict[str, Any]:
    """用本地词典规则输出弹幕情绪标签和 [-1, 1] 强度分。"""

    content = str(text or "").strip()
    if not content:
        return {"label": "neutral", "score": 0.0}

    active_words = words or load_sentiment_words()
    positive_words = active_words.get("positive", [])
    negative_words = active_words.get("negative", [])
    intensity_words = active_words.get("intensity", [])
    negation_words = active_words.get("negation", [])

    score = 0.0
    for word in positive_words:
        if word and word in content:
            score += -1.0 if has_nearby_negation(content, word, negation_words) else 1.0
    for word in negative_words:
        if word and word in content:
            score += 1.0 if has_nearby_negation(content, word, negation_words) else -1.0

    if score:
        intensity_hits = sum(1 for word in intensity_words if word and word in content)
        score *= 1 + min(intensity_hits, 2) * 0.25

    normalized = max(-1.0, min(1.0, score))
    if normalized > 0.15:
        label = "positive"
    elif normalized < -0.15:
        label = "negative"
    else:
        label = "neutral"
        normalized = 0.0
    return {"label": label, "score": round(normalized, 3)}


def has_nearby_negation(content: str, word: str, negation_words: list[str], window: int = 3) -> bool:
    """判断情绪词前方短窗口内是否出现否定词。"""

    index = content.find(word)
    if index < 0:
        return False
    prefix = content[max(0, index - window):index]
    return any(negation in prefix for negation in negation_words)


def classify_danmaku_sentiments(danmakus: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """为弹幕列表附加本地情绪分类结果。"""

    words = load_sentiment_words()
    enriched = []
    for row in danmakus:
        result = classify_sentiment(str(row.get("content", "")), words=words)
        enriched.append({**row, "sentiment": result})
    return enriched


def build_sentiment_timeline(
    danmakus: list[dict[str, Any]],
    *,
    bucket_seconds: int = 10,
) -> list[dict[str, Any]]:
    """按视频时间桶聚合情绪均值和各类弹幕数量。"""

    if bucket_seconds <= 0:
        raise ValueError("bucket_seconds 必须大于 0")

    buckets: dict[int, dict[str, Any]] = {}
    words = load_sentiment_words()
    for row in danmakus:
        time_value = parse_float(row.get("time_in_video"))
        if time_value is None:
            continue
        bucket = int(time_value // bucket_seconds) * bucket_seconds
        item = buckets.setdefault(
            bucket,
            {"time": bucket, "count": 0, "score_total": 0.0, "positive": 0, "neutral": 0, "negative": 0},
        )
        sentiment = classify_sentiment(str(row.get("content", "")), words=words)
        label = str(sentiment["label"])
        item["count"] += 1
        item["score_total"] += float(sentiment["score"])
        item[label] += 1

    timeline = []
    for bucket in sorted(buckets):
        item = buckets[bucket]
        count = int(item["count"])
        timeline.append({
            "time": int(item["time"]),
            "count": count,
            "score": round(float(item["score_total"]) / count, 3) if count else 0.0,
            "positive": int(item["positive"]),
            "neutral": int(item["neutral"]),
            "negative": int(item["negative"]),
        })
    return timeline


def build_playback_track(
    danmakus: list[dict[str, Any]],
    *,
    lane_count: int = 12,
) -> list[dict[str, Any]]:
    """构造前端 Canvas 回放所需的有序弹幕轨道。"""

    active_lane_count = max(1, int(lane_count or 1))
    lane_available_at = [0.0 for _ in range(active_lane_count)]
    rows: list[tuple[float, int, dict[str, Any]]] = []
    for index, row in enumerate(danmakus):
        time_value = parse_float(row.get("time_in_video"))
        if time_value is None:
            continue
        rows.append((time_value, index, row))

    track = []
    for time_value, _, row in sorted(rows, key=lambda item: (item[0], item[1])):
        text = str(row.get("content", "")).strip()
        duration = playback_duration(text)
        lane = choose_playback_lane(lane_available_at, time_value)
        lane_available_at[lane] = time_value + duration
        track.append({
            "time": float(time_value),
            "text": text,
            "lane": lane,
            "color": normalize_danmaku_color(row.get("color")),
            "duration": duration,
        })
    return track


def parse_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def choose_playback_lane(lane_available_at: list[float], time_value: float) -> int:
    for lane, available_at in enumerate(lane_available_at):
        if available_at <= time_value:
            return lane
    return min(range(len(lane_available_at)), key=lambda lane: lane_available_at[lane])


def playback_duration(text: str) -> float:
    return round(max(6.0, min(12.0, 4.0 + len(text) * 0.35)), 2)


def normalize_danmaku_color(value: Any) -> str:
    if isinstance(value, int):
        return f"#{max(0, min(value, 0xFFFFFF)):06x}"
    text = str(value or "").strip()
    if text.startswith("#") and len(text) == 7:
        return text.lower()
    if text.startswith("#") and len(text) == 4:
        return "#" + "".join(ch * 2 for ch in text[1:].lower())
    return "#ffffff"


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
