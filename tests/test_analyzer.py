import pytest

from src.analyzer import build_dashboard_payload, build_frontend_video_stats


def test_build_dashboard_payload_calculates_chart_data():
    videos = [
        {"bvid": "BV1", "title": "视频一", "view": 1000, "danmaku": 20, "like": 30},
        {"bvid": "BV2", "title": "视频二", "view": 500, "danmaku": 10, "like": 80},
    ]
    danmakus = [
        {"title": "视频一", "time_in_video": 1.2, "content": "测试 测试 弹幕", "user_hash": "u1"},
        {"title": "视频一", "time_in_video": 61.0, "content": "互动 很好", "user_hash": "u1"},
        {"title": "视频二", "time_in_video": 120.0, "content": "测试 数据", "user_hash": "u2"},
    ]

    payload = build_dashboard_payload(videos, danmakus, top_n_words=5)

    assert "video_count" not in payload["summary"]
    assert payload["summary"]["danmaku_count"] == 3
    assert "video_rank" not in payload
    assert payload["raw_videos"] == videos
    assert payload["time_distribution"] == [
        {"minute": 0, "count": 1},
        {"minute": 1, "count": 1},
        {"minute": 2, "count": 1},
    ]
    assert payload["length_distribution"][0]["range"] == "0-5"
    assert payload["word_cloud"][0] == {"name": "测试", "value": 3}
    assert payload["user_hash_rank"][0] == {"user_hash": "u1", "count": 2}


def test_build_dashboard_payload_uses_user_stop_words():
    videos = [{"bvid": "BV1", "title": "视频一", "view": 1000, "danmaku": 20, "like": 30}]
    danmakus = [
        {"title": "视频一", "time_in_video": 1.2, "content": "测试 测试 弹幕", "user_hash": "u1"},
        {"title": "视频一", "time_in_video": 2.2, "content": "测试 数据", "user_hash": "u2"},
    ]

    payload = build_dashboard_payload(videos, danmakus, top_n_words=5, stop_words=["测试"])

    assert {"name": "测试", "value": 3} not in payload["word_cloud"]
    assert payload["word_cloud"][0]["name"] == "弹幕"


def test_build_dashboard_payload_uses_custom_distribution_buckets():
    videos = [{"bvid": "BV1", "title": "视频一", "view": 1000, "danmaku": 20, "like": 30}]
    danmakus = [
        {"title": "视频一", "time_in_video": 10.0, "content": "短句", "user_hash": "u1"},
        {"title": "视频一", "time_in_video": 80.0, "content": "这是一条比较长的弹幕", "user_hash": "u2"},
        {"title": "视频一", "time_in_video": 140.0, "content": "中等长度", "user_hash": "u3"},
    ]

    payload = build_dashboard_payload(
        videos,
        danmakus,
        time_buckets=[("开头", 0, 60), ("中段", 61, 120), ("后段", 121, None)],
        length_buckets=[("短", 0, 3), ("长", 4, None)],
    )

    assert payload["time_distribution"] == [
        {"range": "开头", "count": 1},
        {"range": "中段", "count": 1},
        {"range": "后段", "count": 1},
    ]
    assert payload["length_distribution"] == [
        {"range": "短", "count": 1},
        {"range": "长", "count": 2},
    ]


def test_custom_distribution_buckets_allow_at_most_ten_groups():
    videos = [{"bvid": "BV1", "title": "视频一", "view": 1000, "danmaku": 20, "like": 30}]
    danmakus = [{"title": "视频一", "time_in_video": 10.0, "content": "短句", "user_hash": "u1"}]
    ten_buckets = [(f"第{i}组", i, i) for i in range(10)]
    eleven_buckets = [(f"第{i}组", i, i) for i in range(11)]

    payload = build_dashboard_payload(videos, danmakus, time_buckets=ten_buckets)
    assert len(payload["time_distribution"]) == 10

    with pytest.raises(ValueError, match="最多只能设置 10 组"):
        build_dashboard_payload(videos, danmakus, length_buckets=eleven_buckets)


def test_build_frontend_video_stats_matches_browser_shape():
    danmakus = [
        {"time_in_video": 1, "content": "测试弹幕甲乙", "user_hash": "u1"},
        {"time_in_video": 61, "content": "测试弹幕甲乙", "user_hash": "u1"},
        {"time_in_video": 122, "content": "很长很长很长很长很长很长", "user_hash": "u2"},
    ]

    stats = build_frontend_video_stats(danmakus, duration=180, filter_signature="abc")

    assert stats["source"] == "server"
    assert stats["filter_signature"] == "abc"
    assert stats["time_series"]["labels"] == ["0分", "1分", "2分", "3分"]
    assert stats["time_series"]["values"] == [1, 1, 1, 0]
    assert stats["length_buckets"]["1-5"] == 0
    assert stats["length_buckets"]["6-10"] == 2
    assert stats["length_buckets"]["20+"] == 0
    assert stats["word_cloud"]
    assert stats["user_rank"][0] == {"userHash": "u1", "count": 2}
