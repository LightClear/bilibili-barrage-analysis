"""Local file-mode storage usage and cleanup helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import shutil
import time
from pathlib import Path
from typing import Any

from src.danmaku_store import DANMAKU_INDEX_FILE, DANMAKU_STORE_DIR
from src.storage import read_json
from src.time_utils import now_beijing


def path_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            total += item.stat().st_size
    return total


def file_count(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return 1
    return sum(1 for item in path.rglob("*") if item.is_file())


def storage_usage(root: str | Path) -> dict[str, Any]:
    base = Path(root)
    web_data = base / "web" / "data"
    archive_root = base / "data" / "archive"
    ai_root = base / "data" / "ai_analysis"
    ai_cache = ai_root / "cache"

    current_split_dir = web_data / DANMAKU_STORE_DIR
    legacy_frontend = web_data / "danmakus.json"
    raw_danmakus = base / "data" / "raw" / "danmakus.json"
    processed_danmakus = base / "data" / "processed" / "danmakus.json"
    categories = {
        "current_dashboard": _usage_item(web_data / "dashboard.json"),
        "current_danmaku_index": _usage_item(web_data / DANMAKU_INDEX_FILE),
        "current_video_stats": _usage_item(web_data / "video_stats.json"),
        "current_split_danmakus": _usage_item(current_split_dir),
        "legacy_frontend_danmakus": _usage_item(legacy_frontend),
        "runtime_raw_danmakus": _usage_item(raw_danmakus),
        "runtime_processed_danmakus": _usage_item(processed_danmakus),
        "archives": _usage_item(archive_root),
        "ai_cache": _usage_item(ai_cache),
        "ai_artifacts": _usage_item(ai_root, exclude_dirs={"cache"}),
    }
    return {
        "ok": True,
        "categories": categories,
        "total_bytes": sum(item["bytes"] for item in categories.values()),
        "total_files": sum(item["files"] for item in categories.values()),
        "archive_dates": _archive_date_summaries(archive_root),
        "redundant": {
            "archive_legacy_danmakus": _archive_legacy_summary(archive_root),
        },
    }


def cleanup_storage(root: str | Path, options: dict[str, Any]) -> dict[str, Any]:
    base = Path(root)
    dry_run = bool(options.get("dry_run", True))
    cleanup_legacy = bool(options.get("legacy_frontend_danmakus", True))
    cleanup_current_orphans = bool(options.get("current_orphan_danmakus", True))
    cleanup_archive_orphans = bool(options.get("archive_orphan_danmakus", True))
    cleanup_runtime_flat = bool(options.get("runtime_flat_danmakus", True))
    cleanup_archive_legacy = bool(options.get("archive_legacy_danmakus", True))
    cleanup_ai_cache = bool(options.get("ai_cache_expired", True))
    ai_cache_max_age_days = _bounded_int(options.get("ai_cache_max_age_days", 7), 0, 3650)
    archive_retention_days = _bounded_int(options.get("archive_retention_days", 0), 0, 3650)
    confirm_archive_cleanup = bool(options.get("confirm_archive_cleanup", False))

    candidates: list[dict[str, Any]] = []
    web_data = base / "web" / "data"

    if cleanup_legacy:
        candidates.extend(_file_candidate(base, web_data / "danmakus.json", "legacy_frontend_danmakus"))

    if cleanup_runtime_flat and _split_store_ready(web_data):
        candidates.extend(_file_candidate(base, base / "data" / "raw" / "danmakus.json", "runtime_raw_danmakus"))
        candidates.extend(_file_candidate(base, base / "data" / "processed" / "danmakus.json", "runtime_processed_danmakus"))

    if cleanup_current_orphans:
        candidates.extend(_orphan_split_candidates(base, web_data, "current_orphan_danmakus"))

    archive_root = base / "data" / "archive"
    if cleanup_archive_orphans and archive_root.exists():
        for folder in _archive_dirs(archive_root):
            candidates.extend(_orphan_split_candidates(base, folder, "archive_orphan_danmakus"))

    if cleanup_archive_legacy and archive_root.exists():
        for folder in _archive_dirs(archive_root):
            if _split_store_ready(folder):
                candidates.extend(_file_candidate(base, folder / "today_danmakus.json", "archive_legacy_danmakus"))

    if cleanup_ai_cache:
        candidates.extend(_expired_file_candidates(
            base,
            base / "data" / "ai_analysis" / "cache",
            "ai_cache_expired",
            ai_cache_max_age_days,
        ))

    if archive_retention_days > 0:
        if not confirm_archive_cleanup:
            raise ValueError("清理历史归档需要 confirm_archive_cleanup=true")
        candidates.extend(_old_archive_candidates(base, archive_root, archive_retention_days))

    removed = 0
    removed_bytes = 0
    if not dry_run:
        for item in candidates:
            target = _safe_target(base, item["path"])
            if not target.exists():
                continue
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            removed += 1
            removed_bytes += int(item.get("bytes") or 0)

    return {
        "ok": True,
        "dry_run": dry_run,
        "candidates": candidates,
        "candidate_count": len(candidates),
        "candidate_bytes": sum(int(item.get("bytes") or 0) for item in candidates),
        "removed": removed,
        "removed_bytes": removed_bytes,
        "usage": storage_usage(base),
    }


def auto_cleanup_storage(root: str | Path, *, ai_cache_max_age_days: int = 7) -> dict[str, Any]:
    """Run conservative startup cleanup for local file-mode storage."""

    base = Path(root)
    current_split_ready = _has_current_split_store(base)
    return cleanup_storage(base, {
        "dry_run": False,
        "legacy_frontend_danmakus": current_split_ready,
        "runtime_flat_danmakus": current_split_ready,
        "current_orphan_danmakus": True,
        "archive_orphan_danmakus": True,
        "archive_legacy_danmakus": True,
        "ai_cache_expired": True,
        "ai_cache_max_age_days": ai_cache_max_age_days,
        "archive_retention_days": 0,
        "confirm_archive_cleanup": False,
    })


def _usage_item(path: Path, *, exclude_dirs: set[str] | None = None) -> dict[str, Any]:
    exclude_dirs = exclude_dirs or set()
    if not path.exists():
        return {"exists": False, "bytes": 0, "files": 0}
    if not exclude_dirs:
        return {"exists": True, "bytes": path_size(path), "files": file_count(path)}
    total_bytes = 0
    total_files = 0
    for item in path.rglob("*"):
        if any(part in exclude_dirs for part in item.parts):
            continue
        if item.is_file():
            total_files += 1
            total_bytes += item.stat().st_size
    return {"exists": True, "bytes": total_bytes, "files": total_files}


def _archive_date_summaries(archive_root: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for folder in _archive_dirs(archive_root):
        result.append({
            "date": folder.name,
            "bytes": path_size(folder),
            "files": file_count(folder),
        })
    return result


def _archive_legacy_summary(archive_root: Path) -> dict[str, Any]:
    bytes_total = 0
    files_total = 0
    dates: list[dict[str, Any]] = []
    for folder in _archive_dirs(archive_root):
        path = folder / "today_danmakus.json"
        if not path.exists() or not path.is_file():
            continue
        size = path.stat().st_size
        files_total += 1
        bytes_total += size
        dates.append({"date": folder.name, "bytes": size, "files": 1})
    return {
        "exists": files_total > 0,
        "bytes": bytes_total,
        "files": files_total,
        "dates": dates,
    }


def _archive_dirs(archive_root: Path) -> list[Path]:
    if not archive_root.exists():
        return []
    folders: list[Path] = []
    for path in archive_root.iterdir():
        if not path.is_dir():
            continue
        if _archive_dir_date(path) is None:
            continue
        folders.append(path)
    return sorted(folders, key=lambda item: item.name, reverse=True)


def _file_candidate(root: Path, path: Path, reason: str) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    return [{
        "reason": reason,
        "path": _relative(root, path),
        "bytes": path.stat().st_size,
        "files": 1,
    }]


def _orphan_split_candidates(root: Path, base_dir: Path, reason: str) -> list[dict[str, Any]]:
    store_dir = base_dir / DANMAKU_STORE_DIR
    if not store_dir.exists():
        return []
    referenced = _referenced_split_files(base_dir)
    if referenced is None:
        return []
    result: list[dict[str, Any]] = []
    for path in store_dir.glob("*.json"):
        rel_store = f"{DANMAKU_STORE_DIR}/{path.name}"
        if rel_store in referenced:
            continue
        result.append({
            "reason": reason,
            "path": _relative(root, path),
            "bytes": path.stat().st_size,
            "files": 1,
        })
    return result


def _referenced_split_files(base_dir: Path) -> set[str] | None:
    index_path = base_dir / DANMAKU_INDEX_FILE
    if not index_path.exists():
        return None
    try:
        data = read_json(index_path)
    except (OSError, json.JSONDecodeError):
        return None
    videos = data.get("videos") if isinstance(data, dict) else {}
    if not isinstance(videos, dict):
        return None
    result: set[str] = set()
    for meta in videos.values():
        if not isinstance(meta, dict):
            continue
        file_value = str(meta.get("file") or "").replace("\\", "/")
        if file_value.startswith(f"{DANMAKU_STORE_DIR}/") and ".." not in file_value.split("/"):
            result.add(file_value)
    return result


def _expired_file_candidates(root: Path, folder: Path, reason: str, max_age_days: int) -> list[dict[str, Any]]:
    if not folder.exists():
        return []
    cutoff = time.time() - max_age_days * 86400
    result: list[dict[str, Any]] = []
    for path in folder.glob("*.json"):
        if max_age_days > 0 and path.stat().st_mtime >= cutoff:
            continue
        result.append({
            "reason": reason,
            "path": _relative(root, path),
            "bytes": path.stat().st_size,
            "files": 1,
        })
    return result


def _old_archive_candidates(root: Path, archive_root: Path, retention_days: int) -> list[dict[str, Any]]:
    cutoff_date = now_beijing().date() - timedelta(days=retention_days)
    result: list[dict[str, Any]] = []
    for folder in _archive_dirs(archive_root):
        archive_date = _archive_dir_date(folder)
        if archive_date is None or archive_date >= cutoff_date:
            continue
        result.append({
            "reason": "old_archive",
            "path": _relative(root, folder),
            "bytes": path_size(folder),
            "files": file_count(folder),
        })
    return result


def _archive_dir_date(folder: Path):
    try:
        return datetime.strptime(folder.name, "%Y-%m-%d").date()
    except ValueError:
        return None


def _has_current_split_store(root: Path) -> bool:
    return _split_store_ready(root / "web" / "data")


def _split_store_ready(base_dir: Path) -> bool:
    if not (base_dir / DANMAKU_INDEX_FILE).exists() or not (base_dir / "video_stats.json").exists():
        return False
    referenced = _referenced_split_files(base_dir)
    if referenced is None:
        return False
    return all((base_dir / rel).exists() for rel in referenced)


def _safe_target(root: Path, relative_path: str) -> Path:
    base = root.resolve()
    target = (base / relative_path).resolve()
    target.relative_to(base)
    return target


def _relative(root: Path, path: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")


def _bounded_int(value: Any, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = minimum
    return max(minimum, min(maximum, number))
