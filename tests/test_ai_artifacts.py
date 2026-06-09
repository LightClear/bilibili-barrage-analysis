from __future__ import annotations

import os
import time

import server


def test_ai_cache_key_changes_with_prompt_version(monkeypatch):
    handler = object.__new__(server.Handler)
    handler._current_account = lambda: "user_demo"
    payload = {"scope": "current", "analysis_mode": "economy", "video": {"bvid": "BV1"}}

    key1 = handler._ai_cache_key(payload, provider=None)
    monkeypatch.setattr(server, "AI_ANALYSIS_PROMPT_VERSION", "test-version-2")
    key2 = handler._ai_cache_key(payload, provider=None)

    assert key1 != key2


def test_prune_ai_artifacts_keeps_newest_and_ignores_non_artifacts(tmp_path):
    folder = tmp_path / "ai_analysis"
    cache_dir = folder / "cache"
    cache_dir.mkdir(parents=True)
    keep_json = folder / "usage_stats.json"
    keep_json.write_text("{}", encoding="utf-8")
    (cache_dir / "cache.json").write_text("{}", encoding="utf-8")

    files = []
    for index in range(5):
        path = folder / f"current_BV{index}_report.txt"
        path.write_text(str(index), encoding="utf-8")
        timestamp = time.time() + index
        os.utime(path, (timestamp, timestamp))
        files.append(path)

    result = server.prune_ai_artifacts(folder, max_files=3)

    assert result["removed"] == 2
    assert keep_json.exists()
    assert (cache_dir / "cache.json").exists()
    existing = {path.name for path in files if path.exists()}
    assert existing == {"current_BV2_report.txt", "current_BV3_report.txt", "current_BV4_report.txt"}
