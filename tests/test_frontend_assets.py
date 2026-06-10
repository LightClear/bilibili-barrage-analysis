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
        "./js/app-playback.js",
        "./js/app-ai.js",
        "./js/app-import-export.js",
        "./js/app.js",
    ]
    positions = [sources.index(item) for item in expected_order]

    assert positions == sorted(positions)
    for source in expected_order[1:]:
        assert (ROOT / "web" / source.removeprefix("./")).exists()


def test_dashboard_contains_playback_panel_assets():
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    core = (ROOT / "web" / "js" / "app-core.js").read_text(encoding="utf-8")

    assert 'id="playbackPanel"' in index
    assert 'id="playbackCanvas"' in index
    assert 'id="playbackSentimentChart"' in index
    assert 'id="playbackToggleBtn"' in index
    assert "playbackTrack" in core


def test_dashboard_contains_cross_video_panel_assets():
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    core = (ROOT / "web" / "js" / "app-core.js").read_text(encoding="utf-8")

    assert 'id="crossVideoPanel"' in index
    assert 'id="keywordSankeyChart"' in index
    assert 'id="themeRiverChart"' in index
    assert 'id="keywordSamples"' in index
    assert "crossVideoKeywords" in core


def test_dashboard_contains_ai_evidence_and_highlight_assets():
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    ai = (ROOT / "web" / "js" / "app-ai.js").read_text(encoding="utf-8")

    assert 'id="aiEvidenceReport"' in index
    assert 'id="aiHighlightTimeline"' in index
    assert "buildEvidenceReportForAi" in ai
    assert "buildHighlightTimelineForAi" in ai
    assert "renderAiEvidenceReport" in ai
    assert "renderAiHighlightTimeline" in ai


def test_dashboard_ai_insight_console_design_assets():
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "web" / "css" / "dashboard.css").read_text(encoding="utf-8")
    ai = (ROOT / "web" / "js" / "app-ai.js").read_text(encoding="utf-8")

    assert 'class="panel ai-text-panel ai-insight-console ai-only"' in index
    assert 'class="ai-console-head"' in index
    assert 'class="ai-mode-pill"' in index
    assert 'class="ai-command-bar"' in index
    assert 'class="ai-report-body"' in index
    assert 'class="ai-insight-section ai-evidence-report"' in index
    assert 'class="ai-insight-section ai-highlight-timeline"' in index
    assert ".ai-insight-console" in css
    assert ".ai-console-head" in css
    assert ".ai-command-bar" in css
    assert ".ai-report-body" in css
    assert ".ai-highlight-item::before" in css
    assert "ai-evidence-kicker" in ai
    assert "ai-highlight-meta" in ai


def test_login_page_references_existing_local_assets():
    login = (ROOT / "web" / "login.html").read_text(encoding="utf-8")

    assert "./css/login.css" in login
    assert "./js/login.js" in login
    assert (ROOT / "web" / "css" / "login.css").exists()
    assert (ROOT / "web" / "js" / "login.js").exists()
