import pytest

from src.analyzer import (
    build_dashboard_payload,
    build_frontend_video_stats,
    build_playback_track,
    build_sentiment_timeline,
    classify_sentiment,
)


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


def test_classify_sentiment_uses_local_dictionary_rules():
    assert classify_sentiment("太喜欢了真的好看") == {"label": "positive", "score": 1.0}
    assert classify_sentiment("无聊难看浪费时间") == {"label": "negative", "score": -1.0}
    assert classify_sentiment("来了来了") == {"label": "neutral", "score": 0.0}


def test_classify_sentiment_handles_negation_and_intensity():
    assert classify_sentiment("不是很好看")["label"] == "negative"
    intense = classify_sentiment("太燃了太喜欢了")
    assert intense["label"] == "positive"
    assert intense["score"] == 1.0


def test_build_sentiment_timeline_groups_scores_by_video_time():
    danmakus = [
        {"time_in_video": 1, "content": "好看"},
        {"time_in_video": 9, "content": "燃爆"},
        {"time_in_video": 11, "content": "无聊"},
        {"time_in_video": 25, "content": "来了"},
        {"time_in_video": "bad", "content": "好看"},
    ]

    timeline = build_sentiment_timeline(danmakus, bucket_seconds=10)

    assert timeline == [
        {"time": 0, "count": 2, "score": 1.0, "positive": 2, "neutral": 0, "negative": 0},
        {"time": 10, "count": 1, "score": -1.0, "positive": 0, "neutral": 0, "negative": 1},
        {"time": 20, "count": 1, "score": 0.0, "positive": 0, "neutral": 1, "negative": 0},
    ]


def test_build_playback_track_sorts_rows_and_assigns_stable_lanes():
    danmakus = [
        {"time_in_video": 12, "content": "第三条", "color": "#fff"},
        {"time_in_video": 1, "content": "第一条", "color": 16777215},
        {"time_in_video": 3, "content": "第二条"},
        {"time_in_video": "bad", "content": "忽略"},
    ]

    track = build_playback_track(danmakus, lane_count=2)

    assert [item["text"] for item in track] == ["第一条", "第二条", "第三条"]
    assert [item["time"] for item in track] == [1.0, 3.0, 12.0]
    assert [item["lane"] for item in track] == [0, 1, 0]
    assert track[0]["color"] == "#ffffff"
    assert track[2]["duration"] >= 6.0
