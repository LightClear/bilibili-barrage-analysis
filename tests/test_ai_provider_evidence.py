from src.ai_provider import _build_prompt_payload


def test_prompt_payload_includes_evidence_and_highlight_grounding():
    payload = {
        "scope": "current",
        "video": {"title": "Evidence demo"},
        "evidence_report": {
            "claims": [{"type": "keyword", "keyword": "boom", "anchors": [{"time": 10, "text": "boom"}]}],
        },
        "highlight_timeline": [
            {"start": 0, "end": 60, "title": "Opening", "samples": [{"time": 10, "text": "boom"}]},
        ],
    }
    local = {"scope": "current", "words": [{"name": "boom", "value": 1}], "metrics": {}}

    prompt = _build_prompt_payload(payload, local)

    assert prompt["evidence_report"]["claims"][0]["keyword"] == "boom"
    assert prompt["highlight_timeline"][0]["title"] == "Opening"
    assert "evidence_report" in prompt["output_schema"]
    assert "highlight_timeline" in prompt["output_schema"]
