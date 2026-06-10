from src.ai_evidence import build_evidence_report, build_highlight_timeline


def test_build_evidence_report_links_claims_to_sample_danmakus():
    rows = [
        {"content": "boom scene", "time_in_video": 10, "user_hash": "u1"},
        {"content": "boom again", "time_in_video": 12, "user_hash": "u2"},
        {"content": "quiet part", "time_in_video": 70, "user_hash": "u3"},
    ]
    words = [{"name": "boom", "value": 2}]
    metrics = {"danmaku_count": 3, "peak_minute": 0, "peak_count": 2}

    report = build_evidence_report(rows, words=words, metrics=metrics)

    assert report["summary"]["sample_count"] == 3
    assert report["summary"]["unique_users"] == 3
    assert report["claims"][0]["type"] == "keyword"
    assert report["claims"][0]["keyword"] == "boom"
    assert report["claims"][0]["evidence_count"] == 2
    assert report["claims"][0]["anchors"][0] == {"time": 10.0, "text": "boom scene"}
    assert any(claim["type"] == "peak" for claim in report["claims"])


def test_build_highlight_timeline_ranks_dense_keyword_segments():
    rows = [
        {"content": "open", "time_in_video": 2, "user_hash": "u1"},
        {"content": "boom scene", "time_in_video": 61, "user_hash": "u2"},
        {"content": "boom again", "time_in_video": 75, "user_hash": "u3"},
        {"content": "boom final", "time_in_video": 89, "user_hash": "u4"},
        {"content": "ending", "time_in_video": 180, "user_hash": "u5"},
    ]
    words = [{"name": "boom", "value": 3}]

    timeline = build_highlight_timeline(rows, words=words, segment_seconds=60, max_segments=3)

    assert timeline[0]["start"] == 60
    assert timeline[0]["end"] == 120
    assert timeline[0]["score"] > timeline[1]["score"]
    assert timeline[0]["danmaku_count"] == 3
    assert timeline[0]["keywords"] == ["boom"]
    assert [item["text"] for item in timeline[0]["samples"]] == ["boom scene", "boom again", "boom final"]
