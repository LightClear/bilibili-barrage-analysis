import pytest

from server import (
    SESSIONS,
    SESSION_CSRF_TOKENS,
    SESSION_EXPIRES_AT,
    SESSION_IDENTITY_ROLES,
    STATE_LOCK,
    build_identity_payload,
    can_manage_account_role,
    cleanup_expired_sessions,
    csrf_token_matches,
    normalize_ai_user_requirement,
    normalize_identity_role,
)


def test_build_identity_payload_marks_normal_role():
    payload = build_identity_payload("normal")

    assert payload == {
        "ok": True,
        "role": "normal",
        "is_admin": False,
        "api_enabled": False,
        "roles": ["normal", "api", "admin", "owner"],
    }


def test_build_identity_payload_marks_api_role():
    payload = build_identity_payload("api")

    assert payload["role"] == "api"
    assert payload["is_admin"] is False
    assert payload["api_enabled"] is True


def test_build_identity_payload_marks_admin_role():
    payload = build_identity_payload("admin")

    assert payload["role"] == "admin"
    assert payload["is_admin"] is True
    assert payload["api_enabled"] is False


def test_build_identity_payload_marks_owner_role_as_admin_capable():
    payload = build_identity_payload("owner")

    assert payload["role"] == "owner"
    assert payload["is_admin"] is True
    assert payload["api_enabled"] is False


def test_normalize_identity_role_rejects_unknown_role():
    with pytest.raises(ValueError, match="身份必须是 normal、api、admin 或 owner"):
        normalize_identity_role("guest")


def test_owner_can_manage_privileged_account_roles():
    assert can_manage_account_role("owner", "admin", "normal")
    assert can_manage_account_role("owner", "normal", "admin")
    assert can_manage_account_role("owner", "owner", "admin")
    assert can_manage_account_role("owner", "owner", "owner")
    assert not can_manage_account_role("owner", "normal", "owner")
    assert not can_manage_account_role("owner", "admin", "owner")


def test_admin_cannot_manage_privileged_account_roles():
    assert can_manage_account_role("admin", "normal", "normal")
    assert not can_manage_account_role("admin", "admin", "normal")
    assert not can_manage_account_role("admin", "normal", "admin")
    assert not can_manage_account_role("admin", "owner", "owner")


def test_normalize_ai_user_requirement_cleans_and_limits_text():
    assert normalize_ai_user_requirement("  重点看许愿\n氛围  ") == "重点看许愿 氛围"
    with pytest.raises(ValueError, match="最多 300"):
        normalize_ai_user_requirement("很长" * 200)
    with pytest.raises(ValueError, match="密钥"):
        normalize_ai_user_requirement("sk-" + "a" * 20)


def test_csrf_token_matches_requires_exact_value():
    assert csrf_token_matches("token-value", "token-value")
    assert not csrf_token_matches("token-value", "other-token")
    assert not csrf_token_matches("", "token-value")
    assert not csrf_token_matches("token-value", "")


def test_cleanup_expired_sessions_removes_related_state():
    token = "expired-test-token"
    with STATE_LOCK:
        SESSIONS[token] = "demo"
        SESSION_CSRF_TOKENS[token] = "csrf"
        SESSION_IDENTITY_ROLES[token] = "api"
        SESSION_EXPIRES_AT[token] = 10.0

    assert cleanup_expired_sessions(now=11.0) == 1

    with STATE_LOCK:
        assert token not in SESSIONS
        assert token not in SESSION_CSRF_TOKENS
        assert token not in SESSION_IDENTITY_ROLES
        assert token not in SESSION_EXPIRES_AT
