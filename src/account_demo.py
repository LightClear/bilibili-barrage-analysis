"""本地 DEMO 账号、验证码和 API Key 管理。

该模块服务于课程项目演示，不提供生产级安全能力。账号数据写入
``data/accounts.txt``，格式为 JSON 文本，便于查看和后续替换成数据库。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import secrets
import threading
from pathlib import Path
from typing import Any

from src.storage import write_json


BEIJING_TZ = timezone(timedelta(hours=8))
ACCOUNT_RE = re.compile(r"^[A-Za-z0-9_]{6,20}$")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
ACCOUNT_ROLES = {"normal", "admin", "owner"}
ADMIN_ACCOUNT_ROLES = {"admin", "owner"}
PRIVILEGED_ACCOUNT_ROLES = {"admin", "owner"}
GENDER_OPTIONS = {"未设置", "男", "女", "其他", "不愿透露"}
DEFAULT_SEARCH_INTERVAL_SECONDS = 10
PASSWORD_HASH_ALGORITHM = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 200_000
LEGACY_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_ACCOUNT_PASSWORDS = {
    "owner_demo": "Owner12345",
    "admin_demo": "Admin12345",
    "user_demo": "User12345",
}


def now_text() -> str:
    return datetime.now(BEIJING_TZ).isoformat(timespec="seconds")


def legacy_hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def hash_password(password: str, salt: str | None = None, iterations: int = PASSWORD_HASH_ITERATIONS) -> str:
    """Hash a password with PBKDF2-SHA256 and a per-account random salt."""

    salt_value = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_value.encode("utf-8"),
        int(iterations),
    ).hex()
    return f"{PASSWORD_HASH_ALGORITHM}${int(iterations)}${salt_value}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify PBKDF2 hashes and legacy unsalted SHA256 hashes."""

    stored = str(stored_hash or "")
    if LEGACY_SHA256_RE.fullmatch(stored):
        return secrets.compare_digest(legacy_hash_password(password), stored)
    parts = stored.split("$")
    if len(parts) != 4 or parts[0] != PASSWORD_HASH_ALGORITHM:
        return False
    _, iterations_raw, salt, expected = parts
    try:
        candidate = hash_password(password, salt=salt, iterations=int(iterations_raw)).split("$", 3)[3]
    except ValueError:
        return False
    return secrets.compare_digest(candidate, expected)


def password_hash_needs_migration(stored_hash: str) -> bool:
    return not str(stored_hash or "").startswith(f"{PASSWORD_HASH_ALGORITHM}$")


def validate_account(account: str) -> str:
    value = str(account or "").strip()
    if not ACCOUNT_RE.fullmatch(value):
        raise ValueError("账号需为 6-20 位字母、数字或下划线")
    return value


def validate_username(username: str) -> str:
    value = str(username or "").strip()
    if not 2 <= len(value) <= 16:
        raise ValueError("用户名需为 2-16 个字符")
    return value


def validate_password(password: str) -> str:
    value = str(password or "")
    if not 8 <= len(value) <= 32:
        raise ValueError("密码需为 8-32 位")
    if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
        raise ValueError("密码需同时包含字母和数字")
    return value


def validate_email(email: str) -> str:
    value = str(email or "").strip()
    if not EMAIL_RE.fullmatch(value):
        raise ValueError("邮箱格式不正确")
    return value


def mask_account(account: str) -> str:
    value = str(account or "")
    if len(value) <= 4:
        return value[0:1] + "*" * max(1, len(value) - 1)
    return f"{value[:2]}{'*' * (len(value) - 4)}{value[-2:]}"


def mask_email(email: str) -> str:
    value = str(email or "")
    if "@" not in value:
        return mask_account(value)
    name, domain = value.split("@", 1)
    masked_name = name[:2] + "*" * max(2, len(name) - 2)
    return f"{masked_name}@{domain}"


def new_api_key() -> str:
    return f"bili_demo_{secrets.token_urlsafe(24)}"


def normalize_search_interval(value: Any) -> int:
    try:
        interval = int(value)
    except (TypeError, ValueError):
        interval = DEFAULT_SEARCH_INTERVAL_SECONDS
    return max(0, min(interval, 3600))


def is_admin_role(role: Any) -> bool:
    return str(role or "").strip().lower() in ADMIN_ACCOUNT_ROLES


def is_owner_role(role: Any) -> bool:
    return str(role or "").strip().lower() == "owner"


def is_privileged_role(role: Any) -> bool:
    return str(role or "").strip().lower() in PRIVILEGED_ACCOUNT_ROLES


def default_accounts() -> list[dict[str, Any]]:
    created = "2026-05-29T00:00:00+08:00"
    return [
        {
            "account": "owner_demo",
            "username": "项目负责人",
            "password_hash": hash_password(DEFAULT_ACCOUNT_PASSWORDS["owner_demo"]),
            "email": "owner@example.com",
            "role": "owner",
            "gender": "未设置",
            "birthday": "2000-01-01",
            "api_enabled": False,
            "api_key": "",
            "search_interval_seconds": DEFAULT_SEARCH_INTERVAL_SECONDS,
            "disabled": False,
            "created_at": created,
            "last_login_at": "",
        },
        {
            "account": "admin_demo",
            "username": "演示管理员",
            "password_hash": hash_password(DEFAULT_ACCOUNT_PASSWORDS["admin_demo"]),
            "email": "admin@example.com",
            "role": "admin",
            "gender": "未设置",
            "birthday": "2000-01-01",
            "api_enabled": False,
            "api_key": "",
            "search_interval_seconds": DEFAULT_SEARCH_INTERVAL_SECONDS,
            "disabled": False,
            "created_at": created,
            "last_login_at": "",
        },
        {
            "account": "user_demo",
            "username": "普通演示用户",
            "password_hash": hash_password(DEFAULT_ACCOUNT_PASSWORDS["user_demo"]),
            "email": "user@example.com",
            "role": "normal",
            "gender": "未设置",
            "birthday": "2001-01-01",
            "api_enabled": False,
            "api_key": "",
            "search_interval_seconds": DEFAULT_SEARCH_INTERVAL_SECONDS,
            "disabled": False,
            "created_at": created,
            "last_login_at": "",
        },
    ]


def public_user(user: dict[str, Any], reveal_api_key: bool = False) -> dict[str, Any]:
    return {
        "username": user.get("username", ""),
        "account": user.get("account", ""),
        "account_masked": mask_account(user.get("account", "")),
        "email_masked": mask_email(user.get("email", "")),
        "role": user.get("role", "normal"),
        "gender": user.get("gender", "未设置"),
        "birthday": user.get("birthday", ""),
        "api_enabled": bool(user.get("api_enabled")),
        "api_key": user.get("api_key", "") if reveal_api_key and user.get("api_enabled") else "",
        "search_interval_seconds": normalize_search_interval(user.get("search_interval_seconds")),
        "disabled": bool(user.get("disabled")),
        "created_at": user.get("created_at", ""),
        "last_login_at": user.get("last_login_at", ""),
    }


@dataclass
class AccountStore:
    path: Path | str
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)

    def ensure_defaults(self) -> None:
        with self._lock:
            data = self.load()
            users = data.setdefault("users", [])
            existing = {user.get("account") for user in users}
            changed = False
            for user in users:
                if "search_interval_seconds" not in user:
                    user["search_interval_seconds"] = DEFAULT_SEARCH_INTERVAL_SECONDS
                    changed = True
                if "demo_password" in user:
                    user.pop("demo_password", None)
                    changed = True
                default_password = DEFAULT_ACCOUNT_PASSWORDS.get(str(user.get("account") or ""))
                if (
                    default_password
                    and password_hash_needs_migration(user.get("password_hash", ""))
                    and verify_password(default_password, user.get("password_hash", ""))
                ):
                    user["password_hash"] = hash_password(default_password)
                    changed = True
            for user in default_accounts():
                if user["account"] not in existing:
                    users.append(user)
                    changed = True
            if changed or not self.path.exists():
                self.save(data)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"users": [], "updated_at": now_text()}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {"users": [], "updated_at": now_text()}
        data.setdefault("users", [])
        return data

    def save(self, data: dict[str, Any]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data["updated_at"] = now_text()
            write_json(self.path, data)

    def users(self) -> list[dict[str, Any]]:
        with self._lock:
            self.ensure_defaults()
            return self.load()["users"]

    def find(self, account: str) -> dict[str, Any] | None:
        with self._lock:
            value = str(account or "").strip()
            for user in self.users():
                if user.get("account") == value:
                    return user
            return None

    def authenticate(self, account: str, password: str) -> dict[str, Any]:
        with self._lock:
            raw_password = str(password or "")
            user = self.find(validate_account(account))
            if not user or not verify_password(raw_password, user.get("password_hash", "")):
                raise ValueError("账号或密码错误")
            if user.get("disabled"):
                raise ValueError("账号已被封禁，请联系管理员")
            data = self.load()
            for item in data["users"]:
                if item.get("account") == user["account"]:
                    item["last_login_at"] = now_text()
                    item.pop("demo_password", None)
                    if password_hash_needs_migration(item.get("password_hash", "")):
                        item["password_hash"] = hash_password(raw_password)
                    user = item
                    break
            self.save(data)
            return user

    def create_user(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            account = validate_account(payload.get("account", ""))
            if self.find(account):
                raise ValueError("账号已存在")
            password = validate_password(payload.get("password", ""))
            if password != str(payload.get("password_confirm", "")):
                raise ValueError("两次密码输入不一致")
            user = {
                "account": account,
                "username": validate_username(payload.get("username", "")),
                "password_hash": hash_password(password),
                "email": validate_email(payload.get("email", "")),
                "role": "normal",
                "gender": payload.get("gender", "未设置") if payload.get("gender") in GENDER_OPTIONS else "未设置",
                "birthday": str(payload.get("birthday", "") or ""),
                "api_enabled": False,
                "api_key": "",
                "search_interval_seconds": DEFAULT_SEARCH_INTERVAL_SECONDS,
                "disabled": False,
                "created_at": now_text(),
                "last_login_at": now_text(),
            }
            data = self.load()
            data.setdefault("users", []).append(user)
            self.save(data)
            return user

    def update_profile(self, account: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            data = self.load()
            for user in data["users"]:
                if user.get("account") == account:
                    if "username" in payload:
                        user["username"] = validate_username(payload["username"])
                    if payload.get("gender") in GENDER_OPTIONS:
                        user["gender"] = payload["gender"]
                    if "birthday" in payload:
                        user["birthday"] = str(payload.get("birthday") or "")
                    self.save(data)
                    return user
            raise ValueError("账号不存在")

    def set_api_enabled(self, account: str, enabled: bool) -> dict[str, Any]:
        with self._lock:
            data = self.load()
            for user in data["users"]:
                if user.get("account") == account:
                    user["api_enabled"] = bool(enabled)
                    if enabled and not user.get("api_key"):
                        user["api_key"] = new_api_key()
                    if not enabled:
                        user["api_key"] = ""
                    self.save(data)
                    return user
            raise ValueError("账号不存在")

    def reset_api_key(self, account: str) -> dict[str, Any]:
        with self._lock:
            data = self.load()
            for user in data["users"]:
                if user.get("account") == account:
                    user["api_enabled"] = True
                    user["api_key"] = new_api_key()
                    self.save(data)
                    return user
            raise ValueError("账号不存在")

    def admin_update_user(self, account: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            data = self.load()
            for user in data["users"]:
                if user.get("account") == account:
                    if payload.get("role") in ACCOUNT_ROLES:
                        if payload["role"] == "owner" and user.get("role") != "owner":
                            raise ValueError("owner 账号只能在服务器端创建，不能通过后台提升")
                        user["role"] = payload["role"]
                    if "disabled" in payload:
                        user["disabled"] = bool(payload["disabled"])
                    if "username" in payload and payload["username"]:
                        user["username"] = validate_username(payload["username"])
                    if "search_interval_seconds" in payload:
                        user["search_interval_seconds"] = normalize_search_interval(payload["search_interval_seconds"])
                    self.save(data)
                    return user
            raise ValueError("账号不存在")
