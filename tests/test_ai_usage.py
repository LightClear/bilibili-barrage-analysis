from src.ai_usage import AiUsageStore, build_usage_record, payload_usage_metrics


def test_usage_record_never_stores_api_key_or_raw_danmaku(tmp_path):
    payload = {
        "scope": "current",
        "analysis_mode": "economy",
        "force_refresh": True,
        "danmakus": [{"content": "这是一条敏感弹幕原文", "time_in_video": 1}],
    }
    provider = {
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "api_key": "sk-secret-key-should-not-be-saved",
    }

    record = build_usage_record(
        account="user_demo",
        payload=payload,
        provider=provider,
        cache_hit=False,
        external_call=True,
        status="provider_success",
        success=True,
        response={"text": "分析完成"},
    )
    text = str(record)

    assert record["account"] == "user_demo"
    assert record["provider"] == "deepseek"
    assert record["provider_model"] == "deepseek-v4-flash"
    assert record["danmaku_count"] == 1
    assert "sk-secret" not in text
    assert "敏感弹幕原文" not in text


def test_usage_store_summarizes_account_and_admin(tmp_path):
    store = AiUsageStore(tmp_path / "usage.json", max_events=100)
    base_payload = {"scope": "current", "analysis_mode": "economy", "metrics": {"danmaku_count": 3}}

    store.record(build_usage_record(
        account="user_demo",
        payload=base_payload,
        provider=None,
        cache_hit=True,
        external_call=False,
        status="cache_hit",
        success=True,
        response={"text": "cached"},
    ))
    store.record(build_usage_record(
        account="admin_demo",
        payload={**base_payload, "analysis_mode": "full_raw"},
        provider={"provider": "deepseek", "model": "deepseek-v4-flash"},
        cache_hit=False,
        external_call=True,
        status="provider_fallback",
        success=True,
        response={"text": "fallback", "provider_error": "timeout"},
        error="timeout",
    ))

    user_summary = store.account_summary("user_demo")
    admin_summary = store.admin_summary()

    assert user_summary["summary"]["total_requests"] == 1
    assert user_summary["summary"]["cache_hits"] == 1
    assert admin_summary["summary"]["total_requests"] == 2
    assert admin_summary["summary"]["external_calls"] == 1
    assert admin_summary["summary"]["provider_fallbacks"] == 1
    assert admin_summary["summary"]["full_raw_requests"] == 1
    assert admin_summary["providers"][0]["provider"] in {"deepseek", "local-demo"}


def test_payload_usage_metrics_counts_compare_datasets():
    metrics = payload_usage_metrics({
        "scope": "compare",
        "datasets": [
            {"danmakus": [{}, {}]},
            {"metrics": {"danmaku_count": "5"}},
        ],
    })

    assert metrics["dataset_count"] == 2
    assert metrics["danmaku_count"] == 7
    assert metrics["request_bytes"] > 0
    assert metrics["estimated_input_tokens"] > 0
