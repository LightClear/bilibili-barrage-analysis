"""Split JSON danmaku storage for module-scoped video pools."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from src.analyzer import build_frontend_video_stats
from src.storage import read_json, write_json


DANMAKU_STORE_DIR = "danmakus"
DANMAKU_INDEX_FILE = "danmaku_index.json"
VIDEO_STATS_FILE = "video_stats.json"
STORE_VERSION = "split-json-2026-06-03"


def safe_danmaku_filename(bvid: str) -> str:
    """Return a stable JSON filename for one video danmaku store."""

    value = str(bvid or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
        return f"{value}.json"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"bvid_{digest}.json"


def group_danmakus_by_bvid(
    videos: list[dict[str, Any]],
    danmakus: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group danmaku rows by BVID, filling missing BVIDs from video titles."""

    title_to_bvid = {
        str(video.get("title") or "").strip(): str(video.get("bvid") or "").strip()
        for video in videos
        if video.get("bvid") and str(video.get("title") or "").strip()
    }
    sole_bvid = str(videos[0].get("bvid") or "").strip() if len(videos) == 1 else ""
    video_titles = {
        str(video.get("bvid") or "").strip(): str(video.get("title") or "").strip()
        for video in videos
        if video.get("bvid")
    }
    grouped: dict[str, list[dict[str, Any]]] = {
        str(video.get("bvid") or "").strip(): []
        for video in videos
        if video.get("bvid")
    }
    for row in danmakus:
        if not isinstance(row, dict):
            continue
        bvid = str(row.get("bvid") or "").strip()
        title = str(row.get("title") or "").strip()
        if not bvid and title:
            bvid = title_to_bvid.get(title, "")
        if not bvid:
            bvid = sole_bvid
        if not bvid:
            continue
        normalized = dict(row)
        normalized["bvid"] = bvid
        if not normalized.get("title") and video_titles.get(bvid):
            normalized["title"] = video_titles[bvid]
        grouped.setdefault(bvid, []).append(normalized)
    return grouped


def build_video_stats_map(
    videos: list[dict[str, Any]],
    grouped: dict[str, list[dict[str, Any]]],
    *,
    stop_words: list[str] | None = None,
    filter_signature: str = "",
) -> dict[str, dict[str, Any]]:
    """Build frontend-ready stats for each video in a split danmaku store."""

    stats: dict[str, dict[str, Any]] = {}
    for video in videos:
        bvid = str(video.get("bvid") or "").strip()
        if not bvid:
            continue
        stats[bvid] = build_frontend_video_stats(
            grouped.get(bvid, []),
            duration=int(video.get("duration", 0) or 0),
            stop_words=stop_words,
            filter_signature=filter_signature,
        )
    return stats


def write_danmaku_store(
    base_dir: str | Path,
    videos: list[dict[str, Any]],
    danmakus: list[dict[str, Any]],
    *,
    module: str,
    date: str = "",
    stop_words: list[str] | None = None,
    filter_signature: str = "",
    cleanup: bool = True,
) -> dict[str, Any]:
    """Write one module-scoped split danmaku store and return its index."""

    base = Path(base_dir)
    store_dir = base / DANMAKU_STORE_DIR
    grouped = group_danmakus_by_bvid(videos, danmakus)
    stats = build_video_stats_map(
        videos,
        grouped,
        stop_words=stop_words,
        filter_signature=filter_signature,
    )
    expected_files: set[str] = set()
    index_videos: dict[str, dict[str, Any]] = {}

    for video in videos:
        bvid = str(video.get("bvid") or "").strip()
        if not bvid:
            continue
        filename = safe_danmaku_filename(bvid)
        rows = grouped.get(bvid, [])
        expected_files.add(filename)
        write_json(store_dir / filename, rows)
        index_videos[bvid] = {
            "file": f"{DANMAKU_STORE_DIR}/{filename}",
            "count": len(rows),
            "title": str(video.get("title") or bvid),
            "rank": int(video.get("rank") or 0),
            "duration": int(video.get("duration", 0) or 0),
        }

    if cleanup and store_dir.exists():
        for path in store_dir.glob("*.json"):
            if path.name not in expected_files:
                path.unlink(missing_ok=True)

    index = {
        "version": STORE_VERSION,
        "module": module,
        "date": date,
        "video_count": len(index_videos),
        "danmaku_count": sum(item["count"] for item in index_videos.values()),
        "videos": index_videos,
    }
    write_json(base / DANMAKU_INDEX_FILE, index)
    write_json(base / VIDEO_STATS_FILE, stats)
    return index


def ensure_danmaku_store(
    base_dir: str | Path,
    videos: list[dict[str, Any]],
    legacy_danmakus_path: str | Path,
    *,
    module: str,
    date: str = "",
    stop_words: list[str] | None = None,
) -> dict[str, Any]:
    """Ensure a split store exists, lazily migrating a legacy flat JSON file."""

    base = Path(base_dir)
    index_path = base / DANMAKU_INDEX_FILE
    stats_path = base / VIDEO_STATS_FILE
    if index_path.exists() and stats_path.exists():
        index = read_json(index_path)
        return index if isinstance(index, dict) else {}

    legacy = Path(legacy_danmakus_path)
    danmakus = read_all_danmakus(base, legacy)
    if not isinstance(danmakus, list):
        danmakus = []
    return write_danmaku_store(
        base,
        videos,
        danmakus,
        module=module,
        date=date,
        stop_words=stop_words,
    )


def load_danmaku_index(base_dir: str | Path) -> dict[str, Any]:
    path = Path(base_dir) / DANMAKU_INDEX_FILE
    if not path.exists():
        return {}
    data = read_json(path)
    return data if isinstance(data, dict) else {}


def load_video_stats(base_dir: str | Path) -> dict[str, dict[str, Any]]:
    path = Path(base_dir) / VIDEO_STATS_FILE
    if not path.exists():
        return {}
    data = read_json(path)
    return data if isinstance(data, dict) else {}


def attach_video_stats(
    videos: list[dict[str, Any]],
    stats: dict[str, dict[str, Any]],
    index: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return video copies with stats and split-store metadata attached."""

    index_videos = (index or {}).get("videos") if isinstance(index, dict) else {}
    if not isinstance(index_videos, dict):
        index_videos = {}
    result: list[dict[str, Any]] = []
    for video in videos:
        item = dict(video)
        bvid = str(item.get("bvid") or "").strip()
        if bvid and isinstance(stats.get(bvid), dict):
            item["stats"] = stats[bvid]
        meta = index_videos.get(bvid) if bvid else None
        if isinstance(meta, dict):
            item["danmaku_store"] = {
                "file": meta.get("file", ""),
                "count": int(meta.get("count") or 0),
            }
        result.append(item)
    return result


def read_video_danmakus(base_dir: str | Path, bvid: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read one video's danmakus from a split store."""

    base = Path(base_dir)
    normalized = str(bvid or "").strip()
    index = load_danmaku_index(base)
    index_videos = index.get("videos") if isinstance(index.get("videos"), dict) else {}
    meta = index_videos.get(normalized) if isinstance(index_videos, dict) else None
    file_value = str(meta.get("file") or "") if isinstance(meta, dict) else ""
    target = _safe_store_file(base, file_value) if file_value else base / DANMAKU_STORE_DIR / safe_danmaku_filename(normalized)
    if not target.exists():
        raise FileNotFoundError(f"未找到 {normalized} 的弹幕分库文件")
    rows = read_json(target)
    if not isinstance(rows, list):
        rows = []
    return rows, meta if isinstance(meta, dict) else {}


def read_all_danmakus(base_dir: str | Path, legacy_danmakus_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Read all rows from a split store, falling back to a legacy flat file."""

    base = Path(base_dir)
    index = load_danmaku_index(base)
    videos = index.get("videos") if isinstance(index.get("videos"), dict) else {}
    rows: list[dict[str, Any]] = []
    if isinstance(videos, dict) and videos:
        for meta in videos.values():
            file_value = str(meta.get("file") or "") if isinstance(meta, dict) else ""
            if not file_value:
                continue
            target = _safe_store_file(base, file_value)
            if target.exists():
                data = read_json(target)
                if isinstance(data, list):
                    rows.extend(row for row in data if isinstance(row, dict))
        return rows

    if legacy_danmakus_path:
        legacy = Path(legacy_danmakus_path)
        if legacy.exists():
            data = read_json(legacy)
            if isinstance(data, list):
                return [row for row in data if isinstance(row, dict)]
    return []


def build_lightweight_dashboard(
    videos: list[dict[str, Any]],
    stats: dict[str, dict[str, Any]] | None = None,
    *,
    filter_info: dict[str, Any] | None = None,
    analysis_options: dict[str, Any] | None = None,
    archive_source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a dashboard payload without scanning all danmaku rows."""

    stats = stats or {}
    payload: dict[str, Any] = {
        "summary": {
            "danmaku_count": sum(
                int((stats.get(str(video.get("bvid") or "")) or {}).get("danmaku_count") or video.get("danmaku") or 0)
                for video in videos
            ),
            "total_view": sum(int(video.get("view", 0) or 0) for video in videos),
            "total_like": sum(int(video.get("like", 0) or 0) for video in videos),
        },
        "time_distribution": [],
        "length_distribution": [],
        "word_cloud": [],
        "user_hash_rank": [],
        "raw_videos": videos,
        "filter": filter_info or {"enabled": False, "mode": "drop", "block_words": [], "removed_count": 0, "masked_count": 0},
        "analysis_options": analysis_options or {"stop_words": [], "time_buckets": [], "length_buckets": []},
    }
    if archive_source:
        payload["archive_source"] = archive_source
    return payload


def _safe_store_file(base: Path, file_value: str) -> Path:
    rel = Path(file_value)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("弹幕分库索引包含非法路径")
    target = (base / rel).resolve()
    target.relative_to(base.resolve())
    return target
