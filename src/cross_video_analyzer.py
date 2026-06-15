"""跨视频关键词传播数据构造。"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

import jieba

from src.analyzer import is_valid_word


def build_keyword_sankey(
    snapshots: list[dict[str, Any]],
    *,
    top_k: int = 30,
    stop_words: list[str] | None = None,
    sample_limit: int = 10,
) -> dict[str, Any]:
    """从多日归档快照构造关键词-视频桑基图数据。"""

    stop_word_set = normalize_stop_words(stop_words)
    global_counter: Counter[str] = Counter()
    link_counter: Counter[tuple[str, str]] = Counter()
    video_labels: dict[str, str] = {}
    samples: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for snapshot in snapshots:
        date = str(snapshot.get("date") or "")
        for video in snapshot.get("videos") or []:
            bvid = str(video.get("bvid") or "").strip()
            if bvid:
                video_labels[bvid] = str(video.get("title") or bvid)
        for row in snapshot.get("danmakus") or []:
            bvid = str(row.get("bvid") or "").strip()
            if not bvid:
                continue
            title = str(row.get("title") or video_labels.get(bvid) or bvid)
            video_labels.setdefault(bvid, title)
            words = tokenize_keywords(str(row.get("content", "")), stop_word_set)
            if not words:
                continue
            row_counter = Counter(words)
            global_counter.update(row_counter)
            for word, count in row_counter.items():
                link_counter[(word, bvid)] += count
                if len(samples[word]) < sample_limit:
                    samples[word].append({
                        "date": date,
                        "bvid": bvid,
                        "title": title,
                        "time_in_video": row.get("time_in_video"),
                        "content": str(row.get("content", "")),
                    })

    top_words = [word for word, _ in global_counter.most_common(max(1, top_k))]
    used_bvids = {bvid for word, bvid in link_counter if word in top_words}
    nodes = [{"name": word, "category": "keyword"} for word in top_words]
    nodes.extend(
        {"name": video_labels.get(bvid, bvid), "category": "video", "bvid": bvid}
        for bvid in sorted(used_bvids, key=lambda item: video_labels.get(item, item))
    )
    links = [
        {"source": word, "target": video_labels.get(bvid, bvid), "value": count}
        for (word, bvid), count in sorted(link_counter.items(), key=lambda item: (item[0][0], video_labels.get(item[0][1], item[0][1])))
        if word in top_words
    ]
    return {
        "nodes": nodes,
        "links": links,
        "samples": {word: samples.get(word, []) for word in top_words},
    }


def build_theme_river(
    snapshots: list[dict[str, Any]],
    *,
    top_k: int = 12,
    stop_words: list[str] | None = None,
) -> list[list[Any]]:
    """构造 ECharts themeRiver 使用的 [date, value, keyword] 数据。"""

    stop_word_set = normalize_stop_words(stop_words)
    global_counter: Counter[str] = Counter()
    daily_counter: dict[str, Counter[str]] = defaultdict(Counter)

    for snapshot in snapshots:
        date = str(snapshot.get("date") or "")
        if not date:
            continue
        for row in snapshot.get("danmakus") or []:
            words = tokenize_keywords(str(row.get("content", "")), stop_word_set)
            global_counter.update(words)
            daily_counter[date].update(words)

    top_words = [word for word, _ in global_counter.most_common(max(1, top_k))]
    rows: list[list[Any]] = []
    for date in sorted(daily_counter):
        for word in top_words:
            count = daily_counter[date].get(word, 0)
            if count:
                rows.append([date, count, word])
    return rows


def tokenize_keywords(text: str, stop_words: set[str] | None = None) -> list[str]:
    words = []
    for word in jieba.cut(text):
        normalized = word.strip()
        if is_valid_word(normalized, stop_words):
            words.append(normalized)
    return words


def normalize_stop_words(stop_words: list[str] | None = None) -> set[str]:
    return {str(word).strip().lower() for word in (stop_words or []) if str(word).strip()}
