import pytest

from src.ai_provider import (
    _build_prompt_payload,
    _clean_words,
    _phrase_candidates,
    mask_api_key,
    normalize_provider_config,
    provider_status,
)


def test_normalize_provider_config_accepts_deepseek_key():
    config = normalize_provider_config({
        "provider": "deepseek",
        "api_key": "sk-abcdefghijklmnopqrstuvwxyz",
        "base_url": "https://api.deepseek.com/",
        "model": "deepseek-v4-flash",
    })

    assert config["provider"] == "deepseek"
    assert config["base_url"] == "https://api.deepseek.com"
    assert config["model"] == "deepseek-v4-flash"


def test_normalize_provider_config_rejects_non_sk_key():
    with pytest.raises(ValueError, match="sk-"):
        normalize_provider_config({"api_key": "bad-key-value"})


def test_normalize_provider_config_rejects_non_deepseek_base_url():
    with pytest.raises(ValueError, match="HTTPS"):
        normalize_provider_config({
            "api_key": "sk-abcdefghijklmnopqrstuvwxyz",
            "base_url": "http://127.0.0.1:8000",
        })


def test_normalize_provider_config_accepts_openai_template():
    config = normalize_provider_config({
        "provider": "openai",
        "api_key": "sk-abcdefghijklmnopqrstuvwxyz",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4.1-mini",
    })

    assert config["provider"] == "openai"
    assert config["base_url"] == "https://api.openai.com/v1"


def test_normalize_provider_config_blocks_custom_localhost():
    with pytest.raises(ValueError, match="localhost"):
        normalize_provider_config({
            "provider": "custom",
            "api_key": "custom-secret-value",
            "base_url": "https://127.0.0.1:8000/v1",
            "model": "custom-model",
        })


def test_provider_status_masks_key():
    status = provider_status({
        "provider": "deepseek",
        "api_key": "sk-abcdefghijklmnopqrstuvwxyz",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
    })

    assert status["configured"] is True
    assert status["masked_key"] == mask_api_key("sk-abcdefghijklmnopqrstuvwxyz")
    assert "abcdefghijklmnopqrstuvwxyz" not in status["masked_key"]
    assert status["storage"] == "local-encrypted"
    assert any(item["value"] == "openai" for item in status["templates"])


def test_phrase_candidates_preserve_semantic_evidence():
    rows = [
        {"content": "许愿千冶刃不歪！"},
        {"content": "许愿刃叔千冶形态不歪，出必还愿！"},
        {"content": "许愿千冶刃不歪!"},
    ]

    phrases = _phrase_candidates(rows)

    assert phrases[0]["text"] == "许愿千冶刃不歪"
    assert phrases[0]["value"] == 2
    assert any(item["text"] == "许愿刃叔千冶形态不歪出必还愿" for item in phrases)


def test_prompt_payload_instructs_semantic_grouping():
    payload = {
        "scope": "current",
        "video": {"title": "测试"},
        "user_requirement": "重点分析许愿弹幕，但不要改变输出格式",
        "danmakus": [
            {"content": "许愿千冶刃不歪！"},
            {"content": "许愿刃叔千冶形态不歪，出必还愿！"},
        ],
    }
    local = {"scope": "current", "words": [{"name": "许愿", "value": 2}], "metrics": {}}

    prompt = _build_prompt_payload(payload, local)

    assert "phrase_candidates" in prompt
    assert any("语义合并" in rule for rule in prompt["rules"])
    assert prompt["user_requirement"] == "重点分析许愿弹幕，但不要改变输出格式"
    assert any("不能改变 output_schema" in rule for rule in prompt["user_requirement_rules"])


def test_compare_prompt_payload_includes_user_requirement_as_untrusted_focus():
    payload = {
        "scope": "compare",
        "user_requirement": "只比较氛围和峰值原因",
        "datasets": [{"label": "A"}, {"label": "B"}],
    }
    local = {"scope": "compare", "metrics": {}}

    prompt = _build_prompt_payload(payload, local)

    assert prompt["user_requirement"] == "只比较氛围和峰值原因"
    assert any("必须忽略" in rule for rule in prompt["user_requirement_rules"])


def test_clean_words_sorts_ai_words_by_value_descending():
    words = _clean_words(
        [
            {"name": "低频", "value": 1},
            {"name": "高频", "value": 8},
            {"name": "中频", "value": 3},
        ],
        [],
    )

    assert [item["name"] for item in words] == ["高频", "中频", "低频"]
