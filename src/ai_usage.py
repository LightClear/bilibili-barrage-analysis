"""Local usage statistics for AI analysis requests.

The project cannot reliably read provider balance or billing information from
user-owned API keys. This module only records facts observed inside this demo:
cache hits, external-call attempts, success/failure state, request size, and
rough token estimates. API keys and raw danmaku text are never stored here.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any
import json

from .storage import read_json, write_json
from .time_utils import BEIJING_TZ, now_beijing


USAGE_VERSION = 1
DEFAULT_MAX_EVENTS = 1000


def payload_usage_metrics(payload: dict[str, Any]) -> dict[str, int]:
    """Return non-sensitive size metrics for an AI analysis payload."""

    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    request_bytes = len(text.encode("utf-8"))
    rows = _payload_rows(payload)
    return {
        "request_bytes": request_bytes,
        "estimated_input_tokens": max(1, round(len(text) / 1.8)) if text else 0,
        "danmaku_count": rows,
        "dataset_count": _dataset_count(payload),
    }


def build_usage_record(
    *,
    account: str | None,
    payload: dict[str, Any],
    provider: dict[str, Any] | None,
    cache_hit: bool = False,
    external_call: bool = False,
    status: str = "success",
    success: bool = True,
    response: dict[str, Any] | None = None,
    error: str = "",
) -> dict[str, Any]:
    """Build a sanitized usage record without secrets or raw danmaku text."""

    metrics = payload_usage_metrics(payload)
    provider_name = str(provider.get("provider") or "local-demo") if provider else "local-demo"
    provider_model = str(provider.get("model") or "") if provider else ""
    result_text = str((response or {}).get("text") or "")
    return {
        "created_at": now_beijing().isoformat(timespec="seconds"),
        "account": str(account or "anonymous"),
        "scope": str(payload.get("scope") or "current"),
        "analysis_mode": str(payload.get("analysis_mode") or "economy"),
        "provider": provider_name,
        "provider_model": provider_model,
        "cache_hit": bool(cache_hit),
        "external_call": bool(external_call),
        "force_refresh": bool(payload.get("force_refresh")),
        "status": str(status or "success"),
        "success": bool(success),
        "provider_error": _short_error(error or str((response or {}).get("provider_error") or "")),
        "request_bytes": metrics["request_bytes"],
        "estimated_input_tokens": metrics["estimated_input_tokens"],
        "danmaku_count": metrics["danmaku_count"],
        "dataset_count": metrics["dataset_count"],
        "response_chars": len(result_text),
    }


class AiUsageStore:
    """Bounded JSON-backed AI usage event store."""

    def __init__(self, path: Path, max_events: int = DEFAULT_MAX_EVENTS):
        self.path = Path(path)
        self.max_events = max(100, int(max_events or DEFAULT_MAX_EVENTS))
        self._lock = RLock()

    def record(self, event: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            data = self._load()
            events = data.setdefault("events", [])
            events.append(self._sanitize_event(event))
            data["events"] = events[-self.max_events:]
            data["version"] = USAGE_VERSION
            write_json(self.path, data)
            return data["events"][-1]

    def account_summary(self, account: str, recent_limit: int = 10) -> dict[str, Any]:
        events = [
            event for event in self._events()
            if str(event.get("account") or "") == str(account or "")
        ]
        return self._summary_payload(events, recent_limit=recent_limit, scope="account", account=account)

    def admin_summary(self, recent_limit: int = 20) -> dict[str, Any]:
        return self._summary_payload(self._events(), recent_limit=recent_limit, scope="admin", account="")

    def _events(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._load().get("events", []))

    def _load(self) -> dict[str, Any]:
        try:
            data = read_json(self.path)
        except (OSError, json.JSONDecodeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        events = data.get("events")
        if not isinstance(events, list):
            events = []
        return {"version": int(data.get("version") or USAGE_VERSION), "events": [e for e in events if isinstance(e, dict)]}

    def _sanitize_event(self, event: dict[str, Any]) -> dict[str, Any]:
        allowed_text = {
            "created_at", "account", "scope", "analysis_mode", "provider", "provider_model",
            "status", "provider_error",
        }
        allowed_bool = {"cache_hit", "external_call", "force_refresh", "success"}
        allowed_int = {
            "request_bytes", "estimated_input_tokens", "danmaku_count",
            "dataset_count", "response_chars",
        }
        cleaned: dict[str, Any] = {}
        for key in allowed_text:
            value = str(event.get(key) or "")
            cleaned[key] = _short_error(value, limit=160 if key == "provider_error" else 80)
        for key in allowed_bool:
            cleaned[key] = bool(event.get(key))
        for key in allowed_int:
            cleaned[key] = max(0, int(float(event.get(key) or 0)))
        if not cleaned["created_at"]:
            cleaned["created_at"] = now_beijing().isoformat(timespec="seconds")
        if not cleaned["account"]:
            cleaned["account"] = "anonymous"
        return cleaned

    def _summary_payload(self, events: list[dict[str, Any]], recent_limit: int, scope: str, account: str) -> dict[str, Any]:
        events = sorted(events, key=lambda item: str(item.get("created_at") or ""))
        today = now_beijing().date()
        today_events = [event for event in events if _event_date(event) == today]
        return {
            "ok": True,
            "scope": scope,
            "account": account,
            "summary": _counter_summary(events),
            "today": _counter_summary(today_events),
            "providers": _provider_summary(events),
            "recent": events[-max(1, recent_limit):][::-1],
            "note": "本项目只统计本地观察到的 AI 调用记录，不读取第三方 API 余额；费用请以模型平台控制台为准。",
            "path": f"data/ai_analysis/{self.path.name}",
        }


def _payload_rows(payload: dict[str, Any]) -> int:
    if isinstance(payload.get("datasets"), list):
        total = 0
        for item in payload["datasets"]:
            if isinstance(item, dict):
                rows = item.get("danmakus")
                if isinstance(rows, list):
                    total += len(rows)
                else:
                    metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
                    total += _safe_int(metrics.get("danmaku_count"))
        return total
    rows = payload.get("danmakus")
    if isinstance(rows, list):
        return len(rows)
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    return _safe_int(metrics.get("danmaku_count"))


def _dataset_count(payload: dict[str, Any]) -> int:
    datasets = payload.get("datasets")
    if isinstance(datasets, list):
        return len([item for item in datasets if isinstance(item, dict)])
    return 1


def _counter_summary(events: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total_requests": len(events),
        "successes": sum(1 for event in events if event.get("success")),
        "failures": sum(1 for event in events if not event.get("success")),
        "cache_hits": sum(1 for event in events if event.get("cache_hit")),
        "external_calls": sum(1 for event in events if event.get("external_call")),
        "provider_fallbacks": sum(1 for event in events if event.get("status") == "provider_fallback"),
        "force_refreshes": sum(1 for event in events if event.get("force_refresh")),
        "full_raw_requests": sum(1 for event in events if event.get("analysis_mode") == "full_raw"),
        "estimated_input_tokens": sum(int(event.get("estimated_input_tokens") or 0) for event in events),
        "request_bytes": sum(int(event.get("request_bytes") or 0) for event in events),
    }


def _provider_summary(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter: Counter[tuple[str, str]] = Counter()
    for event in events:
        counter[(str(event.get("provider") or "local-demo"), str(event.get("provider_model") or ""))] += 1
    return [
        {"provider": provider, "model": model, "count": count}
        for (provider, model), count in counter.most_common(8)
    ]


def _event_date(event: dict[str, Any]):
    text = str(event.get("created_at") or "")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=BEIJING_TZ)
    return parsed.astimezone(BEIJING_TZ).date()


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(float(value or 0)))
    except (TypeError, ValueError):
        return 0


def _short_error(value: str, limit: int = 160) -> str:
    return " ".join(str(value or "").split())[:limit]
