from server import block_words_signature, build_search_stats


def test_block_words_signature_is_stable_and_case_insensitive():
    assert block_words_signature(["  Foo ", "bar"]) == "foo\nbar"


def test_build_search_stats_applies_block_words_before_counting():
    rows = [
        {"time_in_video": 0, "content": "保留弹幕", "user_hash": "u1"},
        {"time_in_video": 60, "content": "屏蔽弹幕", "user_hash": "u2"},
    ]

    stats = build_search_stats(rows, duration=120, block_words=["屏蔽"])

    assert stats["filter_signature"] == "屏蔽"
    assert stats["danmaku_count"] == 1
    assert stats["time_series"]["values"] == [1, 0, 0]
    assert stats["user_rank"] == [{"userHash": "u1", "count": 1}]
