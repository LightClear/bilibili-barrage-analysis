from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def script_sources(html: str) -> list[str]:
    return [source.split("?", 1)[0] for source in re.findall(r'<script[^>]+src="([^"]+)"', html)]


def test_dashboard_script_order_matches_global_dependencies():
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    sources = script_sources(index)

    expected_order = [
        "https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js",
        "./js/app-core.js",
        "./js/app-video-store.js",
        "./js/app-charts.js",
        "./js/app-ai.js",
        "./js/app-import-export.js",
        "./js/app.js",
    ]
    positions = [sources.index(item) for item in expected_order]

    assert positions == sorted(positions)
    for source in expected_order[1:]:
        assert (ROOT / "web" / source.removeprefix("./")).exists()


def test_login_page_references_existing_local_assets():
    login = (ROOT / "web" / "login.html").read_text(encoding="utf-8")

    assert "./css/login.css" in login
    assert "./js/login.js" in login
    assert (ROOT / "web" / "css" / "login.css").exists()
    assert (ROOT / "web" / "js" / "login.js").exists()
