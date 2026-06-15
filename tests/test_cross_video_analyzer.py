from src.cross_video_analyzer import build_keyword_sankey, build_theme_river


def test_build_keyword_sankey_links_keywords_to_videos_and_samples():
    snapshots = [
        {
            "date": "2026-06-01",
            "videos": [
                {"bvid": "BVAAAA00001", "title": "视频甲"},
                {"bvid": "BVBBBB00002", "title": "视频乙"},
            ],
            "danmakus": [
                {"bvid": "BVAAAA00001", "title": "视频甲", "content": "破防 破防 高能", "time_in_video": 12},
                {"bvid": "BVBBBB00002", "title": "视频乙", "content": "高能 名场面", "time_in_video": 30},
            ],
        },
        {
            "date": "2026-06-02",
            "videos": [{"bvid": "BVCCCC00003", "title": "视频丙"}],
            "danmakus": [
                {"bvid": "BVCCCC00003", "title": "视频丙", "content": "破防 名场面", "time_in_video": 8},
            ],
        },
    ]

    result = build_keyword_sankey(snapshots, top_k=2)

    keyword_nodes = {node["name"] for node in result["nodes"] if node["category"] == "keyword"}
    video_nodes = {node["name"] for node in result["nodes"] if node["category"] == "video"}
    assert keyword_nodes == {"破防", "高能"}
    assert video_nodes == {"视频甲", "视频乙", "视频丙"}
    assert {"source": "破防", "target": "视频甲", "value": 2} in result["links"]
    assert {"source": "高能", "target": "视频乙", "value": 1} in result["links"]
    assert result["samples"]["破防"][0]["content"] == "破防 破防 高能"


def test_build_theme_river_counts_keywords_by_date():
    snapshots = [
        {
            "date": "2026-06-01",
            "videos": [{"bvid": "BVAAAA00001", "title": "视频甲"}],
            "danmakus": [{"bvid": "BVAAAA00001", "title": "视频甲", "content": "破防 高能"}],
        },
        {
            "date": "2026-06-02",
            "videos": [{"bvid": "BVBBBB00002", "title": "视频乙"}],
            "danmakus": [{"bvid": "BVBBBB00002", "title": "视频乙", "content": "破防 破防"}],
        },
    ]

    river = build_theme_river(snapshots, top_k=2)

    assert ["2026-06-01", 1, "破防"] in river
    assert ["2026-06-02", 2, "破防"] in river
    assert ["2026-06-01", 1, "高能"] in river
