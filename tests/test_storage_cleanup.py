from __future__ import annotations

from datetime import datetime
import os
import time

import pytest

from src.storage import write_json
import src.storage_cleanup as storage_cleanup
from src.storage_cleanup import auto_cleanup_storage, cleanup_storage, storage_usage
from src.time_utils import BEIJING_TZ


def candidate_paths(payload: dict) -> set[str]:
    return {str(item.get("path") or "") for item in payload.get("candidates", [])}


def test_storage_cleanup_previews_and_removes_legacy_and_orphan_files(tmp_path):
    web_data = tmp_path / "web" / "data"
    write_json(web_data / "danmaku_index.json", {
        "videos": {
            "BVKEEP001": {"file": "danmakus/BVKEEP001.json", "count": 1},
        },
    })
    write_json(web_data / "danmakus" / "BVKEEP001.json", [{"content": "保留"}])
    write_json(web_data / "danmakus" / "BVORPHAN1.json", [{"content": "孤儿"}])
    write_json(web_data / "danmakus.json", [{"content": "旧全量"}])

    usage = storage_usage(tmp_path)
    assert usage["categories"]["legacy_frontend_danmakus"]["exists"] is True

    preview = cleanup_storage(tmp_path, {"dry_run": True, "ai_cache_expired": False})

    paths = candidate_paths(preview)
    assert "web/data/danmakus.json" in paths
    assert "web/data/danmakus/BVORPHAN1.json" in paths
    assert "web/data/danmakus/BVKEEP001.json" not in paths
    assert (web_data / "danmakus.json").exists()
    assert (web_data / "danmakus" / "BVORPHAN1.json").exists()

    result = cleanup_storage(tmp_path, {"dry_run": False, "ai_cache_expired": False})

    assert result["removed"] == 2
    assert not (web_data / "danmakus.json").exists()
    assert not (web_data / "danmakus" / "BVORPHAN1.json").exists()
    assert (web_data / "danmakus" / "BVKEEP001.json").exists()


def test_storage_cleanup_does_not_treat_missing_index_directory_as_orphans(tmp_path):
    web_data = tmp_path / "web" / "data"
    write_json(web_data / "danmakus" / "BVSAVED001.json", [{"content": "无索引时保留"}])

    preview = cleanup_storage(tmp_path, {
        "dry_run": True,
        "legacy_frontend_danmakus": False,
        "ai_cache_expired": False,
    })

    assert "web/data/danmakus/BVSAVED001.json" not in candidate_paths(preview)


def test_auto_cleanup_keeps_legacy_file_until_split_store_is_ready(tmp_path):
    web_data = tmp_path / "web" / "data"
    write_json(web_data / "danmakus.json", [{"content": "旧全量"}])
    write_json(tmp_path / "data" / "raw" / "danmakus.json", [{"content": "原始副本"}])
    write_json(tmp_path / "data" / "processed" / "danmakus.json", [{"content": "处理副本"}])

    result = auto_cleanup_storage(tmp_path)

    assert result["removed"] == 0
    assert (web_data / "danmakus.json").exists()
    assert (tmp_path / "data" / "raw" / "danmakus.json").exists()
    assert (tmp_path / "data" / "processed" / "danmakus.json").exists()

    write_json(web_data / "danmaku_index.json", {
        "videos": {
            "BVKEEP001": {"file": "danmakus/BVKEEP001.json", "count": 1},
        },
    })
    write_json(web_data / "video_stats.json", {"BVKEEP001": {"danmaku_count": 1}})
    write_json(web_data / "danmakus" / "BVKEEP001.json", [{"content": "保留"}])
    write_json(web_data / "danmakus" / "BVORPHAN1.json", [{"content": "孤儿"}])

    cleaned = auto_cleanup_storage(tmp_path)

    assert cleaned["removed"] == 4
    assert not (web_data / "danmakus.json").exists()
    assert not (tmp_path / "data" / "raw" / "danmakus.json").exists()
    assert not (tmp_path / "data" / "processed" / "danmakus.json").exists()
    assert not (web_data / "danmakus" / "BVORPHAN1.json").exists()
    assert (web_data / "danmakus" / "BVKEEP001.json").exists()


def test_storage_cleanup_removes_migrated_archive_legacy_files_only(tmp_path):
    migrated = tmp_path / "data" / "archive" / "2026-06-01"
    legacy_only = tmp_path / "data" / "archive" / "2026-06-02"
    write_json(migrated / "today_hot_videos.json", [{"bvid": "BVARCH001", "title": "已迁移"}])
    write_json(migrated / "danmaku_index.json", {
        "videos": {
            "BVARCH001": {"file": "danmakus/BVARCH001.json", "count": 1},
        },
    })
    write_json(migrated / "video_stats.json", {"BVARCH001": {"danmaku_count": 1}})
    write_json(migrated / "danmakus" / "BVARCH001.json", [{"content": "保留"}])
    write_json(migrated / "today_danmakus.json", [{"content": "旧全量"}])
    write_json(legacy_only / "today_hot_videos.json", [{"bvid": "BVOLD001", "title": "未迁移"}])
    write_json(legacy_only / "today_danmakus.json", [{"content": "还需要 fallback"}])

    usage = storage_usage(tmp_path)
    assert usage["redundant"]["archive_legacy_danmakus"]["files"] == 2

    preview = cleanup_storage(tmp_path, {
        "dry_run": True,
        "legacy_frontend_danmakus": False,
        "runtime_flat_danmakus": False,
        "current_orphan_danmakus": False,
        "archive_orphan_danmakus": False,
        "archive_legacy_danmakus": True,
        "ai_cache_expired": False,
    })
    assert candidate_paths(preview) == {"data/archive/2026-06-01/today_danmakus.json"}

    result = cleanup_storage(tmp_path, {
        "dry_run": False,
        "legacy_frontend_danmakus": False,
        "runtime_flat_danmakus": False,
        "current_orphan_danmakus": False,
        "archive_orphan_danmakus": False,
        "archive_legacy_danmakus": True,
        "ai_cache_expired": False,
    })
    assert result["removed"] == 1
    assert not (migrated / "today_danmakus.json").exists()
    assert (legacy_only / "today_danmakus.json").exists()


def test_storage_cleanup_removes_expired_ai_cache_files(tmp_path):
    cache_dir = tmp_path / "data" / "ai_analysis" / "cache"
    write_json(cache_dir / "old.json", {"cached": True})
    write_json(cache_dir / "fresh.json", {"cached": True})
    old_time = time.time() - 10 * 86400
    os.utime(cache_dir / "old.json", (old_time, old_time))

    result = cleanup_storage(tmp_path, {
        "dry_run": False,
        "legacy_frontend_danmakus": False,
        "current_orphan_danmakus": False,
        "archive_orphan_danmakus": False,
        "ai_cache_expired": True,
        "ai_cache_max_age_days": 7,
    })

    assert result["removed"] == 1
    assert not (cache_dir / "old.json").exists()
    assert (cache_dir / "fresh.json").exists()


def test_storage_cleanup_archive_retention_requires_confirmation(tmp_path, monkeypatch):
    monkeypatch.setattr(
        storage_cleanup,
        "now_beijing",
        lambda: datetime(2026, 6, 4, tzinfo=BEIJING_TZ),
    )
    old_archive = tmp_path / "data" / "archive" / "2026-05-01"
    recent_archive = tmp_path / "data" / "archive" / "2026-06-03"
    write_json(old_archive / "today_hot_videos.json", [])
    write_json(recent_archive / "today_hot_videos.json", [])

    options = {
        "dry_run": True,
        "legacy_frontend_danmakus": False,
        "current_orphan_danmakus": False,
        "archive_orphan_danmakus": False,
        "ai_cache_expired": False,
        "archive_retention_days": 7,
    }
    with pytest.raises(ValueError, match="confirm_archive_cleanup"):
        cleanup_storage(tmp_path, options)

    preview = cleanup_storage(tmp_path, {**options, "confirm_archive_cleanup": True})
    assert candidate_paths(preview) == {"data/archive/2026-05-01"}

    result = cleanup_storage(tmp_path, {**options, "dry_run": False, "confirm_archive_cleanup": True})
    assert result["removed"] == 1
    assert not old_archive.exists()
    assert recent_archive.exists()
