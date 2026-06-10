"""Local AI-style danmaku analysis used as a stable API fallback.

The project can later replace this module with a real model provider.  The
returned structure is intentionally provider-like so the frontend does not need
to change when the backend starts calling an external API.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from src.ai_evidence import build_evidence_report, build_highlight_timeline


POSITIVE_WORDS = {"好", "强", "神", "爽", "笑", "爱", "牛", "稳", "燃", "高能", "厉害", "可爱"}
QUESTION_WORDS = {"?", "？", "啥", "什么", "怎么", "为何", "为什么", "哪里", "谁"}
INTENSE_WORDS = {"高能", "来了", "泪目", "爆", "草", "哈哈", "笑死", "震撼", "名场面"}


def build_ai_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    """Build a deterministic local analysis for current video or comparison."""

    scope = str(payload.get("scope") or "current")
    if scope == "compare":
        return _build_compare_analysis(payload)
    return _build_current_analysis(payload)


def _user_requirement(payload: dict[str, Any]) -> str:
    text = str(payload.get("user_requirement") or "")
    text = "".join(
        " " if ord(char) < 32 or ord(char) == 127 else char
        for char in text
    )
    return " ".join(text.split()).strip()[:300]


def _build_current_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    video = payload.get("video") if isinstance(payload.get("video"), dict) else {}
    rows = _as_rows(payload.get("danmakus"))
    words = _top_words_from_payload(payload.get("words"), rows)
    metrics = _metrics_from_payload(payload, rows, video, words)
    evidence_report = _evidence_from_payload(payload, rows, words, metrics)
    highlight_timeline = _highlights_from_payload(payload, rows, words)
    suggestions = _suggestions(metrics, words)
    title = video.get("title") or video.get("bvid") or "这个视频"
    top_words = _format_words(words)
    paragraphs = [
        f"我看了一下《{title}》这批弹幕，整体给人的感觉是：{metrics['atmosphere']}。",
        metrics["atmosphere_reason"],
        f"这次共分析了 {metrics['danmaku_count']} 条弹幕，参与的 user_hash 大约有 {metrics['unique_users']} 个，说明讨论不是只由少数账号撑起来的。弹幕平均长度是 {metrics['avg_length']} 个字，峰值集中在第 {metrics['peak_minute']} 分钟附近，这个时间点很可能对应了观众最想吐槽、许愿、刷梗或表达情绪的片段。",
        f"从词云看，比较值得注意的高频表达是：{top_words}。这些词可以理解为观众最直接的注意力入口：它们不一定都是完整观点，但能说明这批弹幕最常围绕哪些情绪和话题展开。",
        f"视频基础数据方面，当前记录到的播放为 {_format_number(_metric(video, 'view'))}，点赞 {_format_number(_metric(video, 'like'))}，硬币 {_format_number(_metric(video, 'coin'))}，收藏 {_format_number(_metric(video, 'favorite'))}，视频长度 {_format_time(_metric(video, 'duration'))}。如果这些互动数据和弹幕峰值同时偏高，通常说明观众不只是路过，而是在某些片段上形成了比较集中的反馈。",
    ]
    requirement = _user_requirement(payload)
    if requirement:
        paragraphs.append(f"你这次额外希望关注的是“{requirement}”。本地兜底会把它作为阅读方向，但不会因为这句话跳过数据依据或安全限制。")
    paragraphs.append(f"我的建议是：{'；'.join(suggestions)}。如果要继续深挖，可以优先回看峰值分钟附近的画面，再结合词云里排名靠前的表达判断观众到底是在玩梗、许愿、讨论剧情，还是单纯刷情绪。")
    text = "\n".join(paragraphs)
    return {
        "ok": True,
        "provider": "local-demo",
        "scope": "current",
        "text": text,
        "words": words[:30],
        "metrics": metrics,
        "evidence_report": evidence_report,
        "highlight_timeline": highlight_timeline,
        "suggestions": suggestions,
    }


def _build_compare_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    datasets = payload.get("datasets")
    if not isinstance(datasets, list):
        datasets = []
    normalized = []
    for index, item in enumerate(datasets[:2]):
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or ("A" if index == 0 else "B"))
        video = item.get("video") if isinstance(item.get("video"), dict) else {}
        rows = _as_rows(item.get("danmakus"))
        words = _top_words_from_payload(item.get("words"), rows)
        metrics = _metrics_from_payload(item, rows, video, words)
        normalized.append({"label": label, "video": video, "rows": rows, "words": words, "metrics": metrics})

    while len(normalized) < 2:
        label = "A" if not normalized else "B"
        normalized.append({
            "label": label,
            "video": {},
            "rows": [],
            "words": [],
            "metrics": _dataset_metrics([], {}, []),
        })

    metrics = {item["label"]: item["metrics"] for item in normalized}
    a = normalized[0]
    b = normalized[1]
    dominant = _compare_dominant(metrics.get("A", {}), metrics.get("B", {}))
    common_words = _common_words(a["words"], b["words"])
    a_title = a["video"].get("title") or a["video"].get("bvid") or "A 视频"
    b_title = b["video"].get("title") or b["video"].get("bvid") or "B 视频"
    a_words = _format_words(a["words"])
    b_words = _format_words(b["words"])
    paragraphs = [
        f"这两个视频放在一起看，A《{a_title}》和 B《{b_title}》的弹幕都不算冷清，但热闹的方式不太一样。",
        f"弹幕量上，A 有 {metrics['A']['danmaku_count']} 条，B 有 {metrics['B']['danmaku_count']} 条，{dominant}。如果只看数量，A 的观众反馈更密一些；但数量不是全部，具体还要看大家在说什么。",
        f"氛围上，A 更偏 {metrics['A']['atmosphere']}，B 更偏 {metrics['B']['atmosphere']}。A 的峰值在第 {metrics['A']['peak_minute']} 分钟附近，B 的峰值在第 {metrics['B']['peak_minute']} 分钟附近，这两个时间点很适合回看，对照画面内容判断弹幕为什么突然集中。",
        f"关键词方面，A 比较突出的表达有：{a_words}。B 比较突出的表达有：{b_words}。两边共同出现得比较明显的是：{common_words or '暂时没有特别强的共同关键词'}。",
        "简单说，如果两个视频都有同一个关键词，但语境不同，那它们可能只是共享了一个热梗；如果关键词、峰值时间和弹幕长度都接近，那就更像是观众在围绕相似情绪或相似内容点反复表达。",
    ]
    requirement = _user_requirement(payload)
    if requirement:
        paragraphs.append(f"你这次额外希望关注的是“{requirement}”。本地兜底会把它作为对比方向，但不会因为这句话跳过数据依据或安全限制。")
    paragraphs.append("建议后续可以先看两边峰值分钟，再看词云里最靠前的几个主题。这样比单纯比较播放、点赞或弹幕总数更容易看出两个视频的真正差异。")
    text = "\n".join(paragraphs)
    return {
        "ok": True,
        "provider": "local-demo",
        "scope": "compare",
        "text": text,
        "words": {
            "A": a["words"][:30],
            "B": b["words"][:30],
        },
        "metrics": metrics,
        "suggestions": [
            "对照峰值分钟查看视频内容节点",
            "结合关键词和弹幕长度判断氛围强度",
            "真实 API 接入后可在同一接口加入情绪分类和观点聚类",
        ],
    }


def _as_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _rows_from_samples(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [{"content": str(item)} for item in value if str(item or "").strip()]


def _metrics_from_payload(
    payload: dict[str, Any],
    rows: list[dict[str, Any]],
    video: dict[str, Any],
    words: list[dict[str, Any]],
) -> dict[str, Any]:
    sample_rows = _rows_from_samples(payload.get("danmaku_samples")) if not rows else []
    metrics = _dataset_metrics(rows or sample_rows, video, words)
    supplied = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}

    numeric_keys = {
        "danmaku_count",
        "unique_users",
        "avg_length",
        "max_length",
        "peak_minute",
        "duration",
        "view",
        "like",
        "coin",
        "favorite",
    }
    for key in numeric_keys:
        if key in supplied:
            metrics[key] = round(_safe_number(supplied.get(key)), 1) if key == "avg_length" else int(_safe_number(supplied.get(key)))

    if isinstance(supplied.get("top_words"), list):
        metrics["top_words"] = supplied["top_words"][:10]
    if supplied.get("atmosphere"):
        metrics["atmosphere"] = str(supplied.get("atmosphere"))
    if supplied.get("atmosphere_reason"):
        metrics["atmosphere_reason"] = str(supplied.get("atmosphere_reason"))
    elif not rows and sample_rows and metrics.get("danmaku_count"):
        atmosphere, reason = _atmosphere(
            [str(row.get("content") or "") for row in sample_rows],
            words,
            int(metrics.get("danmaku_count") or 0),
            _safe_number(metrics.get("duration")),
        )
        metrics["atmosphere"] = atmosphere
        metrics["atmosphere_reason"] = reason
    return metrics


def _dataset_metrics(rows: list[dict[str, Any]], video: dict[str, Any], words: list[dict[str, Any]]) -> dict[str, Any]:
    contents = [str(row.get("content") or "") for row in rows]
    lengths = [len(text) for text in contents]
    users = {str(row.get("user_hash") or "") for row in rows if row.get("user_hash")}
    peak_minute = _peak_minute(rows)
    atmosphere, reason = _atmosphere(contents, words, len(rows), _metric(video, "duration"))
    return {
        "danmaku_count": len(rows),
        "unique_users": len(users),
        "avg_length": round(sum(lengths) / len(lengths), 1) if lengths else 0,
        "max_length": max(lengths) if lengths else 0,
        "peak_minute": peak_minute,
        "top_words": words[:10],
        "atmosphere": atmosphere,
        "atmosphere_reason": reason,
        "duration": _metric(video, "duration"),
        "view": _metric(video, "view"),
        "like": _metric(video, "like"),
        "coin": _metric(video, "coin"),
        "favorite": _metric(video, "favorite"),
    }


def _top_words_from_payload(value: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(value, list):
        cleaned = []
        for item in value:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            count = _safe_number(item.get("value"))
            if name and count > 0:
                cleaned.append({"name": name, "value": int(count)})
        if cleaned:
            return cleaned[:80]

    counter: Counter[str] = Counter()
    for row in rows:
        for token in _simple_tokens(str(row.get("content") or "")):
            counter[token] += 1
    return [{"name": name, "value": count} for name, count in counter.most_common(80)]


def _simple_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    current = ""
    for char in text:
        if char.isascii() and char.isalnum():
            current += char.lower()
            continue
        if len(current) >= 2:
            tokens.append(current)
        current = ""
        if "\u4e00" <= char <= "\u9fff":
            tokens.append(char)
    if len(current) >= 2:
        tokens.append(current)
    return tokens


def _peak_minute(rows: list[dict[str, Any]]) -> int:
    counter: Counter[int] = Counter()
    for row in rows:
        minute = int(max(0, _safe_number(row.get("time_in_video"))) // 60)
        counter[minute] += 1
    if not counter:
        return 0
    return counter.most_common(1)[0][0]


def _atmosphere(contents: list[str], words: list[dict[str, Any]], count: int, duration: float) -> tuple[str, str]:
    joined = "\n".join(contents)
    positive_hits = sum(joined.count(word) for word in POSITIVE_WORDS)
    question_hits = sum(joined.count(word) for word in QUESTION_WORDS)
    intense_hits = sum(joined.count(word) for word in INTENSE_WORDS)
    density = count / max(1, duration / 60)
    top_word_text = "、".join(str(item.get("name")) for item in words[:5])

    if count == 0:
        return "暂无弹幕", "当前视频没有可分析弹幕，建议先获取或切换到有弹幕的视频。"
    if intense_hits >= max(3, count * 0.04) or density >= 25:
        return "高活跃", f"弹幕密度较高或高能词出现明显，前排关键词为 {top_word_text or '暂无'}。"
    if question_hits > positive_hits and question_hits >= max(2, count * 0.03):
        return "讨论型", "疑问词占比较高，观众更偏向提问、解释和互动讨论。"
    if positive_hits >= max(2, count * 0.03):
        return "正向活跃", "正向表达和认同类词汇较多，整体反馈偏积极。"
    return "平稳", "弹幕分布较均衡，未出现特别集中的情绪或争议信号。"


def _suggestions(metrics: dict[str, Any], words: list[dict[str, Any]]) -> list[str]:
    suggestions = []
    if metrics["danmaku_count"] == 0:
        return ["先获取该视频弹幕后再进行评价"]
    if metrics["peak_minute"] > 0:
        suggestions.append(f"重点查看第 {metrics['peak_minute']} 分钟附近的弹幕峰值")
    if metrics["avg_length"] >= 18:
        suggestions.append("平均弹幕较长，可进一步分析观众观点和解释型内容")
    else:
        suggestions.append("短弹幕占比较高，适合优先观察情绪和梗传播")
    if words:
        suggestions.append(f"围绕“{words[0]['name']}”检查是否存在集中话题")
    return suggestions


def _common_words(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> str:
    a_names = {str(item.get("name")) for item in a[:12]}
    common = [str(item.get("name")) for item in b[:12] if str(item.get("name")) in a_names]
    return "、".join(common[:8])


def _evidence_from_payload(
    payload: dict[str, Any],
    rows: list[dict[str, Any]],
    words: list[dict[str, Any]],
    metrics: dict[str, Any],
) -> dict[str, Any]:
    supplied = payload.get("evidence_report")
    if isinstance(supplied, dict) and isinstance(supplied.get("claims"), list):
        return supplied
    return build_evidence_report(rows, words=words, metrics=metrics)


def _highlights_from_payload(
    payload: dict[str, Any],
    rows: list[dict[str, Any]],
    words: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    supplied = payload.get("highlight_timeline")
    if isinstance(supplied, list):
        return [item for item in supplied if isinstance(item, dict)][:8]
    return build_highlight_timeline(rows, words=words)


def _compare_dominant(a: dict[str, Any], b: dict[str, Any]) -> str:
    diff = int(a.get("danmaku_count") or 0) - int(b.get("danmaku_count") or 0)
    if diff == 0:
        return "两者弹幕量持平"
    return "A 弹幕更集中" if diff > 0 else "B 弹幕更集中"


def _metric(video: dict[str, Any], key: str) -> float:
    aliases = {
        "view": ["view", "views"],
        "like": ["like", "likes"],
        "favorite": ["favorite", "favorites", "fav"],
        "danmaku": ["danmaku", "danmaku_count"],
        "coin": ["coin", "coins"],
        "duration": ["duration", "length"],
    }
    for name in aliases.get(key, [key]):
        if name in video and video[name] is not None:
            return _safe_number(video[name])
    return 0


def _safe_number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0


def _format_number(value: float) -> str:
    return f"{int(value):,}"


def _format_time(seconds: float) -> str:
    total = int(seconds or 0)
    hour = total // 3600
    minute = (total % 3600) // 60
    second = total % 60
    if hour:
        return f"{hour}:{minute:02d}:{second:02d}"
    return f"{minute}:{second:02d}"


def _format_words(words: list[dict[str, Any]]) -> str:
    if not words:
        return "暂无明显关键词"
    return "、".join(f"{item['name']}({item['value']})" for item in words[:8])
