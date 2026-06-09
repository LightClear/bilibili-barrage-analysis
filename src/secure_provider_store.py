"""Encrypted local storage for user model provider credentials.

This is a local DEMO store: it keeps API keys out of ``accounts.txt``, ``web/``
and documentation, and stores only encrypted key material under ``data/secure``.
For a real multi-user deployment, replace this with an OS keyring, KMS, or a
database encryption layer with managed secrets.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .storage import read_json, write_json, write_text


MASTER_KEY_ENV = "BILI_DEMO_SECRET_KEY"
SECRET_FILENAME = "server_secret.key"
STORE_FILENAME = "api_providers.json"


class SecureProviderStore:
    """Store per-account AI provider configs with encrypted API keys."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self.path = self.directory / STORE_FILENAME
        self.secret_path = self.directory / SECRET_FILENAME
        self._lock = threading.RLock()
        self._master_key: bytes | None = None

    def has(self, account: str) -> bool:
        account = _normalize_account(account)
        if not account:
            return False
        with self._lock:
            return account in self._load().get("providers", {})

    def get(self, account: str) -> dict[str, Any] | None:
        account = _normalize_account(account)
        if not account:
            return None
        with self._lock:
            record = self._load().get("providers", {}).get(account)
            if not isinstance(record, dict):
                return None
            encrypted_key = record.get("api_key")
            if not isinstance(encrypted_key, dict):
                return None
            api_key = self._decrypt(encrypted_key)
            return {
                "provider": str(record.get("provider") or "deepseek"),
                "api_key": api_key,
                "base_url": str(record.get("base_url") or ""),
                "model": str(record.get("model") or ""),
                "timeout": int(record.get("timeout") or 45),
            }

    def set(self, account: str, config: dict[str, Any]) -> None:
        account = _normalize_account(account)
        if not account:
            raise ValueError("缺少账号")
        api_key = str(config.get("api_key") or "").strip()
        if not api_key:
            raise ValueError("缺少 API Key")
        with self._lock:
            data = self._load()
            providers = data.setdefault("providers", {})
            providers[account] = {
                "provider": str(config.get("provider") or "deepseek"),
                "base_url": str(config.get("base_url") or ""),
                "model": str(config.get("model") or ""),
                "timeout": int(config.get("timeout") or 45),
                "api_key": self._encrypt(api_key),
                "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
            self._save(data)

    def clear(self, account: str) -> None:
        account = _normalize_account(account)
        if not account:
            return
        with self._lock:
            data = self._load()
            data.setdefault("providers", {}).pop(account, None)
            self._save(data)

    def ensure(self, account: str, config: dict[str, Any], overwrite: bool = False) -> bool:
        account = _normalize_account(account)
        if not account:
            raise ValueError("缺少账号")
        with self._lock:
            if not overwrite and self.has(account):
                return False
            self.set(account, config)
            return True

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "providers": {}}
        data = read_json(self.path)
        if not isinstance(data, dict):
            return {"version": 1, "providers": {}}
        if not isinstance(data.get("providers"), dict):
            data["providers"] = {}
        data["version"] = 1
        return data

    def _save(self, data: dict[str, Any]) -> None:
        data["version"] = 1
        data.setdefault("providers", {})
        write_json(self.path, data)
        _chmod_private(self.path)

    def _encrypt(self, value: str) -> dict[str, str | int]:
        plaintext = value.encode("utf-8")
        nonce = secrets.token_bytes(16)
        cipher = _xor_bytes(plaintext, _keystream(self._key(), nonce, len(plaintext)))
        tag = hmac.new(self._key(), b"tag:" + nonce + cipher, hashlib.sha256).digest()
        return {
            "v": 1,
            "nonce": _b64(nonce),
            "ciphertext": _b64(cipher),
            "tag": _b64(tag),
        }

    def _decrypt(self, payload: dict[str, Any]) -> str:
        if int(payload.get("v") or 0) != 1:
            raise ValueError("不支持的 API Key 存储版本")
        nonce = _b64decode(str(payload.get("nonce") or ""))
        cipher = _b64decode(str(payload.get("ciphertext") or ""))
        tag = _b64decode(str(payload.get("tag") or ""))
        expected = hmac.new(self._key(), b"tag:" + nonce + cipher, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise ValueError("API Key 存储校验失败")
        plaintext = _xor_bytes(cipher, _keystream(self._key(), nonce, len(cipher)))
        return plaintext.decode("utf-8")

    def _key(self) -> bytes:
        if self._master_key is not None:
            return self._master_key
        env_value = os.environ.get(MASTER_KEY_ENV, "").strip()
        if env_value:
            self._master_key = hashlib.sha256(env_value.encode("utf-8")).digest()
            return self._master_key
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.secret_path.exists():
            raw = self.secret_path.read_text(encoding="utf-8").strip()
            self._master_key = _b64decode(raw)
            return self._master_key
        self._master_key = secrets.token_bytes(32)
        write_text(self.secret_path, _b64(self._master_key))
        _chmod_private(self.secret_path)
        return self._master_key


def _normalize_account(account: str) -> str:
    return str(account or "").strip()


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    blocks: list[bytes] = []
    counter = 0
    while sum(len(block) for block in blocks) < length:
        blocks.append(
            hmac.new(key, b"stream:" + nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        )
        counter += 1
    return b"".join(blocks)[:length]


def _xor_bytes(left: bytes, right: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(left, right))


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _chmod_private(path: Path) -> None:
    try:
        path.chmod(0o600)
    except OSError:
        pass
