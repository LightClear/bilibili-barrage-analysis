from src.ai_analysis import build_ai_analysis


def test_build_current_ai_analysis_uses_all_loaded_rows():
    payload = {
        "scope": "current",
        "video": {"title": "测试视频", "duration": 180, "view": 1000, "like": 20, "coin": 5},
        "danmakus": [
            {"content": "高能来了", "time_in_video": 62, "user_hash": "u1"},
            {"content": "真的好强", "time_in_video": 64, "user_hash": "u2"},
            {"content": "高能高能", "time_in_video": 120, "user_hash": "u1"},
        ],
        "words": [{"name": "高能", "value": 3}],
    }

    result = build_ai_analysis(payload)

    assert result["ok"] is True
    assert result["scope"] == "current"
    assert result["metrics"]["danmaku_count"] == 3
    assert result["metrics"]["unique_users"] == 2
    assert "测试视频" in result["text"]


def test_build_compare_ai_analysis_fills_missing_slot():
    payload = {
        "scope": "compare",
        "datasets": [
            {
                "label": "A",
                "video": {"title": "A 视频"},
                "danmakus": [{"content": "好看", "time_in_video": 1, "user_hash": "u1"}],
                "words": [{"name": "好看", "value": 1}],
            }
        ],
    }

    result = build_ai_analysis(payload)

    assert result["ok"] is True
    assert result["scope"] == "compare"
    assert result["metrics"]["A"]["danmaku_count"] == 1
    assert result["metrics"]["B"]["danmaku_count"] == 0
