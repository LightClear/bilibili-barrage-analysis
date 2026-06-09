import json

from src.collector import BilibiliApiError
from src.danmaku_store import read_video_danmakus
from src.pipeline import classify_history_error, collect_video_danmaku_result, export_project_data


def test_export_project_data_writes_processed_and_web_files(tmp_path):
    videos = [{"bvid": "BV1", "title": "视频", "view": 1, "danmaku": 1, "like": 1}]
    danmakus = [{"title": "视频", "time_in_video": 0, "content": "测试弹幕"}]

    export_project_data(tmp_path, videos, danmakus)

    processed = json.loads((tmp_path / "data" / "processed" / "danmakus.json").read_text(encoding="utf-8"))
    dashboard = json.loads((tmp_path / "web" / "data" / "dashboard.json").read_text(encoding="utf-8"))
    index = json.loads((tmp_path / "web" / "data" / "danmaku_index.json").read_text(encoding="utf-8"))
    stats = json.loads((tmp_path / "web" / "data" / "video_stats.json").read_text(encoding="utf-8"))
    web_danmakus, _ = read_video_danmakus(tmp_path / "web" / "data", "BV1")

    assert processed == danmakus
    assert web_danmakus == [{**danmakus[0], "bvid": "BV1"}]
    assert index["videos"]["BV1"]["file"] == "danmakus/BV1.json"
    assert stats["BV1"]["danmaku_count"] == 1
    assert dashboard["summary"]["danmaku_count"] == 1
    assert dashboard["word_cloud"] == []
    assert dashboard["user_hash_rank"] == []
    assert "stats" not in dashboard["raw_videos"][0]


def test_collect_video_danmaku_result_reports_xml_fallback():
    class FakeCollector:
        def fetch_danmaku_segments(self, cid, duration=0):
            raise BilibiliApiError("segment failed")

        def fetch_danmaku_xml(self, cid):
            return '<i><d p="1,1,25,16777215,1700000000,0,user1,1">测试</d></i>'

    result = collect_video_danmaku_result(FakeCollector(), 123, bvid="BV1", title="视频")

    assert result.source == "xml"
    assert result.segment_count == 0
    assert len(result.rows) == 1


def test_collect_video_danmaku_result_marks_history_auth_required():
    class FakeCollector:
        def has_history_auth(self):
            return False

        def fetch_danmaku_segments(self, cid, duration=0):
            raise BilibiliApiError("segment failed")

        def fetch_danmaku_xml(self, cid):
            return '<i><d p="1,1,25,16777215,1700000000,0,user1,1">测试</d></i>'

    result = collect_video_danmaku_result(
        FakeCollector(),
        123,
        bvid="BV1",
        title="视频",
        include_history=True,
    )

    assert result.history_enabled is True
    assert result.history_auth_required is True
    assert result.history_error_type == "auth_required"
    assert len(result.rows) == 1


def test_collect_video_danmaku_result_marks_empty_history_index():
    class FakeCollector:
        def has_history_auth(self):
            return True

        def fetch_danmaku_segments(self, cid, duration=0):
            raise BilibiliApiError("segment failed")

        def fetch_danmaku_xml(self, cid):
            return '<i><d p="1,1,25,16777215,1700000000,0,user1,1">测试</d></i>'

        def fetch_history_dates(self, cid, month):
            return []

    result = collect_video_danmaku_result(
        FakeCollector(),
        123,
        bvid="BV1",
        title="视频",
        include_history=True,
        pubdate=1700000000,
        history_max_months=1,
    )

    assert result.history_error_type == "index_empty"
    assert result.history_date_count == 0


def test_collect_video_danmaku_result_continues_after_soft_history_month_failure():
    class FakeCollector:
        def __init__(self):
            self.calls = 0

        def has_history_auth(self):
            return True

        def fetch_danmaku_segments(self, cid, duration=0):
            raise BilibiliApiError("segment failed")

        def fetch_danmaku_xml(self, cid):
            return '<i><d p="1,1,25,16777215,1700000000,0,user1,1">测试</d></i>'

        def fetch_history_dates(self, cid, month):
            self.calls += 1
            if self.calls == 1:
                raise BilibiliApiError("B 站接口返回错误：code=-400，message=请求错误")
            return ["2024-01-01"]

        def fetch_history_segment(self, cid, date):
            return b""

    result = collect_video_danmaku_result(
        FakeCollector(),
        123,
        bvid="BV1",
        title="视频",
        include_history=True,
        pubdate=1700000000,
        history_max_months=2,
    )

    assert result.history_error_type == "index_partial"
    assert result.history_date_count == 1
    assert len(result.rows) == 1


def test_collect_video_danmaku_result_reports_history_index_failed_when_all_months_fail():
    class FakeCollector:
        def has_history_auth(self):
            return True

        def fetch_danmaku_segments(self, cid, duration=0):
            raise BilibiliApiError("segment failed")

        def fetch_danmaku_xml(self, cid):
            return '<i><d p="1,1,25,16777215,1700000000,0,user1,1">测试</d></i>'

        def fetch_history_dates(self, cid, month):
            raise BilibiliApiError("B 站接口返回错误：code=-400，message=请求错误")

    result = collect_video_danmaku_result(
        FakeCollector(),
        123,
        bvid="BV1",
        title="视频",
        include_history=True,
        pubdate=1700000000,
        history_max_months=2,
    )

    assert result.history_error_type == "index_failed"
    assert "未找到可用快照" in result.history_error
    assert len(result.rows) == 1


def test_classify_history_error_detects_risk_control():
    assert classify_history_error("B 站接口返回错误：-412", stage="index") == "risk_control"
    assert classify_history_error("下载历史弹幕失败：123@2024-01-01", stage="snapshot") == "snapshot_failed"
