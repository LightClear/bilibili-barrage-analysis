import pytest

from src.account_demo import (
    AccountStore,
    is_admin_role,
    is_owner_role,
    legacy_hash_password,
    public_user,
    validate_account,
    validate_password,
    verify_password,
)


def test_validate_account_allows_numeric_account():
    assert validate_account("123456") == "123456"


def test_validate_password_requires_letters_and_digits():
    assert validate_password("User12345") == "User12345"
    with pytest.raises(ValueError, match="同时包含字母和数字"):
        validate_password("12345678")


def test_account_store_authenticates_default_users(tmp_path):
    store = AccountStore(tmp_path / "accounts.txt")

    user = store.authenticate("admin_demo", "Admin12345")

    assert user["role"] == "admin"
    assert user["password_hash"].startswith("pbkdf2_sha256$")
    assert verify_password("Admin12345", user["password_hash"])

    owner = store.authenticate("owner_demo", "Owner12345")
    assert owner["role"] == "owner"
    assert is_admin_role(owner["role"])
    assert is_owner_role(owner["role"])


def test_account_store_migrates_legacy_sha256_hash(tmp_path):
    store = AccountStore(tmp_path / "accounts.txt")
    legacy_hash = legacy_hash_password("User12345")
    store.save({
        "users": [
            {
                "account": "123456",
                "username": "旧账号",
                "password_hash": legacy_hash,
                "demo_password": "User12345",
                "email": "old@example.com",
                "role": "normal",
            }
        ]
    })

    user = store.authenticate("123456", "User12345")

    assert user["password_hash"] != legacy_hash
    assert user["password_hash"].startswith("pbkdf2_sha256$")
    assert "demo_password" not in user
    assert verify_password("User12345", user["password_hash"])


def test_public_user_masks_private_fields():
    user = {
        "account": "123456789",
        "username": "测试用户",
        "email": "demo@example.com",
        "role": "normal",
        "api_enabled": True,
        "api_key": "secret",
    }

    payload = public_user(user)

    assert payload["account_masked"] == "12*****89"
    assert payload["email_masked"] == "de**@example.com"
    assert payload["api_key"] == ""
    assert payload["search_interval_seconds"] == 10


def test_admin_update_user_can_change_search_interval(tmp_path):
    store = AccountStore(tmp_path / "accounts.txt")
    store.ensure_defaults()

    updated = store.admin_update_user("user_demo", {"search_interval_seconds": 25})

    assert updated["search_interval_seconds"] == 25


def test_disabled_account_gets_clear_login_error(tmp_path):
    store = AccountStore(tmp_path / "accounts.txt")
    store.ensure_defaults()
    store.admin_update_user("user_demo", {"disabled": True})

    with pytest.raises(ValueError, match="封禁"):
        store.authenticate("user_demo", "User12345")


def test_admin_update_user_ignores_api_switch(tmp_path):
    store = AccountStore(tmp_path / "accounts.txt")
    store.ensure_defaults()

    updated = store.admin_update_user("user_demo", {"api_enabled": True})

    assert updated["api_enabled"] is False
    assert updated["api_key"] == ""


def test_admin_update_user_rejects_owner_promotion(tmp_path):
    store = AccountStore(tmp_path / "accounts.txt")
    store.ensure_defaults()

    with pytest.raises(ValueError, match="owner 账号只能在服务器端创建"):
        store.admin_update_user("user_demo", {"role": "owner"})

    assert store.find("user_demo")["role"] == "normal"


def test_admin_update_user_keeps_existing_owner_role(tmp_path):
    store = AccountStore(tmp_path / "accounts.txt")
    store.ensure_defaults()

    updated = store.admin_update_user("owner_demo", {"role": "owner", "search_interval_seconds": 0})

    assert updated["role"] == "owner"
    assert updated["search_interval_seconds"] == 0
