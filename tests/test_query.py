from src.query import count_by_user_hash, query_danmakus


ROWS = [
    {"content": "高能来了", "time_in_video": 20.0, "user_hash": "u2"},
    {"content": "普通弹幕", "time_in_video": 10.0, "user_hash": "u1"},
    {"content": "高能预警", "time_in_video": 5.0, "user_hash": "u1"},
]


def test_query_danmakus_by_content_and_sort_by_time():
    result = query_danmakus(ROWS, content="高能", sort_by="time_in_video")

    assert [row["time_in_video"] for row in result] == [5.0, 20.0]


def test_query_danmakus_by_user_hash_and_sort_by_user_hash():
    result = query_danmakus(ROWS, user_hash="u1", sort_by="user_hash")

    assert [row["content"] for row in result] == ["高能预警", "普通弹幕"]


def test_count_by_user_hash_returns_ranked_counts():
    result = count_by_user_hash(ROWS)

    assert result[0] == {"user_hash": "u1", "count": 2}
