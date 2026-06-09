from src.secure_provider_store import SecureProviderStore
from src.secure_bili_cookie_store import SecureBiliCookieStore, normalize_bili_cookie_value


def test_secure_provider_store_round_trips_without_plaintext(tmp_path):
    store = SecureProviderStore(tmp_path / "secure")
    config = {
        "provider": "deepseek",
        "api_key": "sk-test-secret-value",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
        "timeout": 45,
    }

    store.set("admin_demo", config)
    loaded = store.get("admin_demo")

    assert loaded == config
    assert store.has("admin_demo")
    assert "sk-test-secret-value" not in store.path.read_text(encoding="utf-8")


def test_secure_provider_store_clear_removes_account(tmp_path):
    store = SecureProviderStore(tmp_path / "secure")
    store.set("user_demo", {
        "provider": "openai",
        "api_key": "sk-user-secret-value",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4.1-mini",
        "timeout": 30,
    })

    store.clear("user_demo")

    assert store.get("user_demo") is None
    assert not store.has("user_demo")


def test_secure_bili_cookie_store_round_trips_without_plaintext(tmp_path):
    store = SecureBiliCookieStore(tmp_path / "secure")

    store.set("user_demo", "sessdata", "abcdef1234567890")
    loaded = store.get("user_demo")

    assert loaded["credential_type"] == "sessdata"
    assert loaded["value"] == "abcdef1234567890"
    assert loaded["cookie_header"] == "SESSDATA=abcdef1234567890"
    assert store.has("user_demo")
    assert "abcdef1234567890" not in store.path.read_text(encoding="utf-8")


def test_secure_bili_cookie_store_accepts_full_cookie(tmp_path):
    store = SecureBiliCookieStore(tmp_path / "secure")
    cookie = "SESSDATA=abcdef1234567890; bili_jct=csrf-token"

    store.set("user_demo", "cookie", cookie)
    loaded = store.get("user_demo")

    assert loaded["credential_type"] == "cookie"
    assert loaded["cookie_header"] == cookie
    assert "abcdef1234567890" not in store.path.read_text(encoding="utf-8")


def test_bili_sessdata_field_rejects_full_cookie():
    try:
        normalize_bili_cookie_value("sessdata", "SESSDATA=abc; bili_jct=csrf")
    except ValueError as exc:
        assert "完整 Cookie" in str(exc)
    else:
        raise AssertionError("expected ValueError")
