"""Encrypted local storage for per-account Bilibili login cookies.

The value stored here is sensitive because it can represent a logged-in Bilibili
session. Keep it out of accounts.txt, web assets and documentation.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .secure_provider_store import _chmod_private, _normalize_account, SecureProviderStore
from .storage import read_json, write_json


STORE_FILENAME = "bili_cookies.json"
SUPPORTED_TYPES = {"sessdata", "cookie"}


class SecureBiliCookieStore(SecureProviderStore):
    """Store Bilibili SESSDATA or full Cookie per account with local encryption."""

    def __init__(self, directory: str | Path):
        super().__init__(directory)
        self.path = self.directory / STORE_FILENAME

    def has(self, account: str) -> bool:
        account = _normalize_account(account)
        if not account:
            return False
        with self._lock:
            return account in self._load().get("cookies", {})

    def get(self, account: str) -> dict[str, Any] | None:
        account = _normalize_account(account)
        if not account:
            return None
        with self._lock:
            record = self._load().get("cookies", {}).get(account)
            if not isinstance(record, dict):
                return None
            encrypted_value = record.get("value")
            if not isinstance(encrypted_value, dict):
                return None
            value = self._decrypt(encrypted_value)
            credential_type = str(record.get("credential_type") or "sessdata").strip().lower()
            if credential_type not in SUPPORTED_TYPES:
                credential_type = "sessdata"
            return {
                "credential_type": credential_type,
                "value": value,
                "cookie_header": cookie_header_from_value(credential_type, value),
                "updated_at": str(record.get("updated_at") or ""),
            }

    def set(self, account: str, credential_type: str, value: str) -> None:
        account = _normalize_account(account)
        if not account:
            raise ValueError("缺少账号")
        normalized_type, normalized_value = normalize_bili_cookie_value(credential_type, value)
        with self._lock:
            data = self._load()
            cookies = data.setdefault("cookies", {})
            cookies[account] = {
                "credential_type": normalized_type,
                "value": self._encrypt(normalized_value),
                "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
            self._save(data)

    def clear(self, account: str) -> None:
        account = _normalize_account(account)
        if not account:
            return
        with self._lock:
            data = self._load()
            data.setdefault("cookies", {}).pop(account, None)
            self._save(data)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "cookies": {}}
        data = read_json(self.path)
        if not isinstance(data, dict):
            return {"version": 1, "cookies": {}}
        if not isinstance(data.get("cookies"), dict):
            data["cookies"] = {}
        data["version"] = 1
        return data

    def _save(self, data: dict[str, Any]) -> None:
        data["version"] = 1
        data.setdefault("cookies", {})
        write_json(self.path, data)
        _chmod_private(self.path)


def normalize_bili_cookie_value(credential_type: str, value: str) -> tuple[str, str]:
    """Validate and normalize user-entered Bilibili credential text."""

    text = str(value or "").strip()
    if not text:
        raise ValueError("请输入 BILI_SESSDATA 或 BILI_COOKIE")
    if "\n" in text or "\r" in text:
        raise ValueError("B 站 Cookie 不能包含换行")
    if len(text) > 8192:
        raise ValueError("B 站 Cookie 过长，请只保留必要的登录 Cookie")

    credential = str(credential_type or "sessdata").strip().lower()
    if credential not in SUPPORTED_TYPES:
        raise ValueError("凭证类型必须是 sessdata 或 cookie")

    if credential == "sessdata":
        lowered = text.lower()
        if lowered.startswith("sessdata="):
            text = text.split("=", 1)[1].strip()
        if ";" in text:
            raise ValueError("SESSDATA 输入框只填写 SESSDATA 的值；完整 Cookie 请切换为 BILI_COOKIE")
        if len(text) < 8:
            raise ValueError("SESSDATA 看起来过短")
    else:
        if "sessdata=" not in text.lower():
            raise ValueError("完整 Cookie 至少需要包含 SESSDATA=...")

    return credential, text


def cookie_header_from_value(credential_type: str, value: str) -> str:
    credential = str(credential_type or "sessdata").strip().lower()
    text = str(value or "").strip()
    if not text:
        return ""
    if credential == "cookie":
        return text
    return f"SESSDATA={text}"


def bili_cookie_status(config: dict[str, Any] | None) -> dict[str, Any]:
    """Return a public status payload without exposing the secret value."""

    if not config:
        return {
            "ok": True,
            "configured": False,
            "credential_type": "",
            "masked_value": "",
            "updated_at": "",
            "storage": "local-encrypted",
        }
    credential_type = str(config.get("credential_type") or "sessdata")
    value = str(config.get("value") or "")
    return {
        "ok": True,
        "configured": True,
        "credential_type": credential_type,
        "masked_value": mask_bili_cookie(credential_type, value),
        "updated_at": str(config.get("updated_at") or ""),
        "storage": "local-encrypted",
    }


def mask_bili_cookie(credential_type: str, value: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    if str(credential_type or "").lower() == "cookie":
        names = []
        for part in text.split(";"):
            name = part.strip().split("=", 1)[0].strip()
            if name and name not in names:
                names.append(name)
        shown = ", ".join(names[:4])
        suffix = "..." if len(names) > 4 else ""
        return f"Cookie字段：{shown}{suffix}" if shown else "完整 Cookie 已保存"
    if len(text) <= 12:
        return "SESSDATA=***"
    return f"SESSDATA={text[:6]}...{text[-4:]}"
