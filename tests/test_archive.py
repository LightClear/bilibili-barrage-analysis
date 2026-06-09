from datetime import datetime, timedelta, timezone

from src.archive import ArchiveStore, HotVideoCache, should_update_now
from src.danmaku_store import read_video_danmakus


BEIJING = timezone(timedelta(hours=8))


def test_should_update_now_uses_five_minute_boundary_without_first_update():
    boundary = datetime(2026, 5, 26, 14, 30, tzinfo=BEIJING)

    assert not should_update_now(datetime(2026, 5, 26, 14, 31, tzinfo=BEIJING), last_update_at=None)
    assert should_update_now(boundary, last_update_at=None)
    assert not should_update_now(boundary, last_update_at=boundary)
    assert should_update_now(datetime(2026, 5, 26, 14, 35, tzinfo=BEIJING), last_update_at=boundary)


def test_should_update_now_allows_admin_force_update():
    now = datetime(2026, 5, 26, 14, 31, tzinfo=BEIJING)

    assert should_update_now(now, last_update_at=now, admin_force=True)


def test_should_update_now_skips_end_of_day_archive_update():
    end_of_day = datetime(2026, 5, 26, 0, 0, tzinfo=BEIJING)

    assert not should_update_now(end_of_day, last_update_at=None)
    assert not should_update_now(end_of_day, last_update_at=None, admin_force=True)


def test_archive_store_reads_missing_history_as_empty(tmp_path):
    store = ArchiveStore(tmp_path)

    history = store.load_recent_hot_data(today=datetime(2026, 5, 26, tzinfo=BEIJING), days=14)

    assert history == {"videos": [], "danmakus": []}


def test_archive_store_writes_split_danmaku_store(tmp_path):
    store = ArchiveStore(tmp_path)
    day = datetime(2026, 5, 26, 14, 30, tzinfo=BEIJING)
    videos = [{"bvid": "BV1234567890", "title": "视频", "duration": 60}]
    rows = [{"bvid": "BV1234567890", "title": "视频", "content": "弹幕", "time_in_video": 1}]

    store.save_today_hot_data(videos, rows, current_time=day)
    folder = tmp_path / "data" / "archive" / "2026-05-26"
    stored_rows, _ = read_video_danmakus(folder, "BV1234567890")

    assert stored_rows == rows
    assert (folder / "danmaku_index.json").exists()
    assert (folder / "video_stats.json").exists()


def test_hot_video_cache_releases_removed_videos():
    cache = HotVideoCache()
    cache.danmakus_by_bvid = {"BV1": [{"content": "旧"}], "BV2": [{"content": "保留"}]}

    removed = cache.refresh_active_videos([{"bvid": "BV2"}, {"bvid": "BV3"}])

    assert removed == ["BV1"]
    assert "BV1" not in cache.danmakus_by_bvid
    assert cache.active_bvids == {"BV2", "BV3"}
