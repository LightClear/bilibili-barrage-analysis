"""Evidence and highlight builders for grounded AI danmaku reports."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def build_evidence_report(
    rows: list[dict[str, Any]],
    *,
    words: list[dict[str, Any]] | None = None,
    metrics: dict[str, Any] | None = None,
    max_claims: int = 6,
    max_anchors: int = 5,
) -> dict[str, Any]:
    cleaned = _clean_rows(rows)
    active_words = _clean_words(words or [])
    active_metrics = metrics or {}
    claims: list[dict[str, Any]] = []

    for word in active_words[:4]:
        keyword = str(word.get("name") or "").strip()
        if not keyword:
            continue
        anchors = _keyword_anchors(cleaned, keyword, max_anchors=max_anchors)
        if not anchors:
            continue
        claims.append({
            "type": "keyword",
            "title": f"Keyword focus: {keyword}",
            "keyword": keyword,
            "evidence_count": len(anchors),
            "confidence": _confidence(len(anchors), len(cleaned)),
            "anchors": anchors,
        })
        if len(claims) >= max_claims:
            break

    peak_claim = _peak_claim(cleaned, active_metrics, max_anchors=max_anchors)
    if peak_claim:
        claims.append(peak_claim)

    if not claims and cleaned:
        claims.append({
            "type": "sample",
            "title": "Representative danmaku samples",
            "evidence_count": min(len(cleaned), max_anchors),
            "confidence": 0.4,
            "anchors": [_anchor(row) for row in cleaned[:max_anchors]],
        })

    return {
        "summary": {
            "sample_count": len(cleaned),
            "unique_users": len({row["user_hash"] for row in cleaned if row.get("user_hash")}),
            "keyword_count": len(active_words),
        },
        "claims": claims[:max_claims],
    }


def build_highlight_timeline(
    rows: list[dict[str, Any]],
    *,
    words: list[dict[str, Any]] | None = None,
    segment_seconds: int = 60,
    max_segments: int = 5,
    max_samples: int = 4,
) -> list[dict[str, Any]]:
    cleaned = _clean_rows(rows)
    if not cleaned:
        return []
    active_words = [str(item.get("name") or "").strip() for item in (words or []) if str(item.get("name") or "").strip()]
    bucket_size = max(10, int(segment_seconds or 60))
    buckets: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in cleaned:
        start = int(row["time"] // bucket_size) * bucket_size
        buckets[start].append(row)

    segments = []
    for start, bucket_rows in buckets.items():
        keyword_hits = _segment_keyword_hits(bucket_rows, active_words)
        unique_users = len({row["user_hash"] for row in bucket_rows if row.get("user_hash")})
        score = len(bucket_rows) * 10 + sum(keyword_hits.values()) * 6 + unique_users * 2
        top_keywords = [name for name, _ in keyword_hits.most_common(3)]
        samples = [_anchor(row) for row in bucket_rows[:max_samples]]
        segments.append({
            "start": int(start),
            "end": int(start + bucket_size),
            "title": _segment_title(start, top_keywords),
            "score": int(score),
            "danmaku_count": len(bucket_rows),
            "unique_users": unique_users,
            "keywords": top_keywords,
            "reason": _segment_reason(len(bucket_rows), top_keywords),
            "samples": samples,
        })

    segments.sort(key=lambda item: (-item["score"], item["start"]))
    return segments[:max(1, int(max_segments or 1))]


def _clean_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        text = str(row.get("content") or "").strip()
        if not text:
            continue
        time_value = _safe_float(row.get("time_in_video"))
        if time_value is None:
            continue
        cleaned.append({
            "time": round(time_value, 3),
            "text": text[:160],
            "user_hash": str(row.get("user_hash") or ""),
        })
    cleaned.sort(key=lambda item: item["time"])
    return cleaned


def _clean_words(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned = []
    for item in words:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        cleaned.append({"name": name, "value": _safe_int(item.get("value"))})
    cleaned.sort(key=lambda item: -item["value"])
    return cleaned


def _keyword_anchors(rows: list[dict[str, Any]], keyword: str, *, max_anchors: int) -> list[dict[str, Any]]:
    lower_keyword = keyword.lower()
    anchors = []
    for row in rows:
        if lower_keyword in row["text"].lower():
            anchors.append(_anchor(row))
        if len(anchors) >= max_anchors:
            break
    return anchors


def _peak_claim(rows: list[dict[str, Any]], metrics: dict[str, Any], *, max_anchors: int) -> dict[str, Any] | None:
    if not rows:
        return None
    minute = _safe_int(metrics.get("peak_minute"))
    start = minute * 60
    end = start + 60
    anchors = [_anchor(row) for row in rows if start <= row["time"] < end][:max_anchors]
    if not anchors:
        counter: Counter[int] = Counter(int(row["time"] // 60) for row in rows)
        if not counter:
            return None
        minute = counter.most_common(1)[0][0]
        start = minute * 60
        end = start + 60
        anchors = [_anchor(row) for row in rows if start <= row["time"] < end][:max_anchors]
    if not anchors:
        return None
    return {
        "type": "peak",
        "title": f"Peak activity around {minute}:00",
        "start": int(start),
        "end": int(end),
        "evidence_count": len(anchors),
        "confidence": _confidence(len(anchors), len(rows)),
        "anchors": anchors,
    }


def _segment_keyword_hits(rows: list[dict[str, Any]], keywords: list[str]) -> Counter[str]:
    hits: Counter[str] = Counter()
    for row in rows:
        text = row["text"].lower()
        for keyword in keywords:
            if keyword.lower() in text:
                hits[keyword] += 1
    return hits


def _segment_title(start: int, keywords: list[str]) -> str:
    minute = start // 60
    if keywords:
        return f"{minute}:00 keyword burst: {keywords[0]}"
    return f"{minute}:00 danmaku burst"


def _segment_reason(count: int, keywords: list[str]) -> str:
    if keywords:
        return f"{count} danmakus concentrated here, led by {', '.join(keywords[:2])}."
    return f"{count} danmakus concentrated in this time window."


def _anchor(row: dict[str, Any]) -> dict[str, Any]:
    return {"time": float(row["time"]), "text": row["text"]}


def _confidence(hit_count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(min(0.95, 0.35 + hit_count / max(total, 1)), 2)


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0
