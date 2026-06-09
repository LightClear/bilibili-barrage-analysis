"""Session storage helpers.

Current runtime still uses an in-memory store so the demo can start without
MySQL. The interface is intentionally close to the planned `sessions` table:
token, account, csrf token, identity role, created_at, last_seen_at, expires_at.
"""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Any


class MemorySessionStore:
    """Thread-safe in-memory session store with a MySQL-ready shape."""

    def __init__(
        self,
        accounts: dict[str, str] | None = None,
        csrf_tokens: dict[str, str] | None = None,
        identity_roles: dict[str, str] | None = None,
        expires_at: dict[str, float] | None = None,
        *,
        created_at: dict[str, float] | None = None,
        last_seen_at: dict[str, float] | None = None,
        lock: threading.RLock | None = None,
    ):
        self.accounts = accounts if accounts is not None else {}
        self.csrf_tokens = csrf_tokens if csrf_tokens is not None else {}
        self.identity_roles = identity_roles if identity_roles is not None else {}
        self.expires_at = expires_at if expires_at is not None else {}
        self.created_at = created_at if created_at is not None else {}
        self.last_seen_at = last_seen_at if last_seen_at is not None else {}
        self.lock = lock or threading.RLock()

    def create(self, token: str, account: str, csrf_token: str, expires_at: float, now: float | None = None) -> None:
        current = time.time() if now is None else float(now)
        with self.lock:
            self.accounts[token] = str(account)
            self.csrf_tokens[token] = str(csrf_token)
            self.expires_at[token] = float(expires_at)
            self.created_at[token] = current
            self.last_seen_at[token] = current
            self.identity_roles.pop(token, None)

    def get(self, token: str, now: float | None = None, touch: bool = True) -> dict[str, Any] | None:
        if not token:
            return None
        current = time.time() if now is None else float(now)
        with self.lock:
            expires_at = float(self.expires_at.get(token) or 0)
            if expires_at and expires_at <= current:
                self.drop(token)
                return None
            account = self.accounts.get(token)
            if not account:
                return None
            if touch:
                self.last_seen_at[token] = current
            return {
                "token": token,
                "account": account,
                "csrf_token": self.csrf_tokens.get(token, ""),
                "identity_role": self.identity_roles.get(token, ""),
                "created_at": float(self.created_at.get(token) or current),
                "last_seen_at": float(self.last_seen_at.get(token) or current),
                "expires_at": expires_at,
            }

    def get_account(self, token: str, now: float | None = None) -> str | None:
        record = self.get(token, now=now)
        return str(record["account"]) if record else None

    def get_csrf_token(self, token: str, now: float | None = None) -> str:
        record = self.get(token, now=now, touch=False)
        return str(record.get("csrf_token") or "") if record else ""

    def get_identity_role(self, token: str, now: float | None = None) -> str:
        record = self.get(token, now=now, touch=False)
        return str(record.get("identity_role") or "") if record else ""

    def set_identity_role(self, token: str, role: str) -> bool:
        with self.lock:
            if token not in self.accounts:
                return False
            self.identity_roles[token] = str(role)
            self.last_seen_at[token] = time.time()
            return True

    def clear_identity_role(self, token: str) -> None:
        with self.lock:
            self.identity_roles.pop(token, None)

    def drop(self, token: str) -> None:
        with self.lock:
            self.accounts.pop(token, None)
            self.csrf_tokens.pop(token, None)
            self.identity_roles.pop(token, None)
            self.expires_at.pop(token, None)
            self.created_at.pop(token, None)
            self.last_seen_at.pop(token, None)

    def cleanup_expired(self, now: float | None = None) -> int:
        current = time.time() if now is None else float(now)
        with self.lock:
            expired = [
                token
                for token, expires_at in self.expires_at.items()
                if float(expires_at or 0) <= current
            ]
            for token in expired:
                self.drop(token)
            return len(expired)

    def mysql_projection(self, token: str) -> dict[str, Any] | None:
        """Return a non-secret row-shaped payload for a future MySQL adapter."""

        record = self.get(token, touch=False)
        if not record:
            return None
        return {
            "session_token_hash": hash_secret(token),
            "account": record["account"],
            "csrf_token_hash": hash_secret(record["csrf_token"]),
            "identity_role": record["identity_role"] or None,
            "created_at": record["created_at"],
            "last_seen_at": record["last_seen_at"],
            "expires_at": record["expires_at"],
        }


def hash_secret(value: str) -> str:
    """Hash a session or CSRF token before storing it outside process memory."""

    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()
