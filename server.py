"""开发服务器：静态文件 + BV 号实时搜索 API。

替换 `python -m http.server`，增加 GET /api/search?bvid=BVxxx 端点。
启动：python server.py
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import secrets
import sys
import threading
import time
from collections.abc import Callable
from http.cookies import SimpleCookie
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

# 确保项目根目录在 sys.path 中，方便从项目根启动
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.account_demo import (
    AccountStore,
    is_admin_role,
    is_owner_role,
    is_privileged_role,
    normalize_search_interval,
    public_user,
    validate_email,
)
from src.ai_analysis import build_ai_analysis
from src.ai_usage import AiUsageStore, build_usage_record
from src.ai_provider import (
    AiProviderError,
    call_deepseek_analysis,
    normalize_provider_config,
    provider_status,
    test_deepseek_provider,
)
from src.analyzer import build_frontend_video_stats
from src.archive import ArchiveStore
from src.collector import BilibiliApiError, BilibiliCollector, build_video_url, extract_bvid
from src.danmaku_store import (
    DANMAKU_INDEX_FILE,
    VIDEO_STATS_FILE,
    build_lightweight_dashboard,
    ensure_danmaku_store,
    load_danmaku_index,
    load_video_stats,
    read_all_danmakus,
    read_video_danmakus,
    write_danmaku_store,
)
from src.filter import apply_blocklist, load_block_words
from src.job_manager import JobManager
from src.pipeline import collect_popular_dataset, collect_video_danmaku_result, collect_video_danmaku_rows, export_project_data
from src.secure_provider_store import SecureProviderStore
from src.secure_bili_cookie_store import SecureBiliCookieStore, bili_cookie_status
from src.session_store import MemorySessionStore
from src.storage import read_json, write_json, write_text
from src.storage_cleanup import auto_cleanup_storage, cleanup_storage, storage_usage
from src.time_utils import BEIJING_TZ, now_beijing


IDENTITY_ROLES = ["normal", "api", "admin", "owner"]
SESSION_COOKIE_NAME = "bili_demo_session"
SESSION_MAX_AGE_SECONDS = 8 * 60 * 60
DEFAULT_JSON_BODY_LIMIT = 64 * 1024
SMALL_JSON_BODY_LIMIT = 16 * 1024
BLOCK_WORDS_BODY_LIMIT = 32 * 1024
AI_ANALYZE_BODY_LIMIT = 4 * 1024 * 1024
MAX_DANMAKU_ROWS = 2_000_000
MAX_AI_FULL_RAW_ROWS = 20_000
AI_USER_REQUIREMENT_MAX_CHARS = 300
AI_ANALYSIS_PROMPT_VERSION = "2026-06-02.1"
AI_LOCAL_STATS_VERSION = "2026-06-02.1"
AI_ARTIFACT_MAX_FILES = 40
SESSIONS: dict[str, str] = {}
SESSION_IDENTITY_ROLES: dict[str, str] = {}
SESSION_CSRF_TOKENS: dict[str, str] = {}
SESSION_EXPIRES_AT: dict[str, float] = {}
SESSION_CREATED_AT: dict[str, float] = {}
SESSION_LAST_SEEN_AT: dict[str, float] = {}
ACCOUNT_STORE = AccountStore(ROOT / "data" / "accounts.txt")
AI_PROVIDER_STORE = SecureProviderStore(ROOT / "data" / "secure")
BILI_COOKIE_STORE = SecureBiliCookieStore(ROOT / "data" / "secure")
AI_USAGE_STORE = AiUsageStore(ROOT / "data" / "ai_analysis" / "usage_stats.json")
EMAIL_CODES: dict[str, dict] = {}
AI_CAPTCHAS: dict[str, dict] = {}
RATE_LIMITS: dict[str, float] = {}
RATE_WINDOWS: dict[str, list[float]] = {}
LOGIN_FAILURES: dict[str, dict[str, float | int]] = {}
STATE_LOCK = threading.RLock()
SESSION_STORE = MemorySessionStore(
    SESSIONS,
    SESSION_CSRF_TOKENS,
    SESSION_IDENTITY_ROLES,
    SESSION_EXPIRES_AT,
    created_at=SESSION_CREATED_AT,
    last_seen_at=SESSION_LAST_SEEN_AT,
    lock=STATE_LOCK,
)
JOB_MANAGER = JobManager(max_jobs=50, max_events_per_job=80)
JOB_RESULTS: dict[str, dict[str, Any]] = {}
LOGIN_FAILURE_WINDOW_SECONDS = 15 * 60
LOGIN_CAPTCHA_THRESHOLD = 3
LOGIN_LOCK_THRESHOLD = 5
LOGIN_LOCK_STEPS_SECONDS = (60, 3 * 60, 5 * 60)
ADMIN_DEFAULT_PROVIDER_ACCOUNT = "admin_demo"
ADMIN_DEFAULT_PROVIDER_KEY_ENV = "BILI_ADMIN_DEFAULT_API_KEY"
REFRESH_POPULAR_JOB_TYPE = "refresh_popular"
BVID_SEARCH_JOB_TYPE = "bvid_search"
ARCHIVE_DATE_REFRESH_JOB_TYPE = "refresh_archive_date"
MAX_FULL_JOB_RESULTS = 5
CSRF_EXEMPT_POST_PATHS = {
    "/api/account/email-code",
    "/api/account/register",
    "/api/account/login",
}


class RequestBodyTooLarge(ValueError):
    """Raised when a JSON request exceeds the endpoint-specific limit."""


class LocalThreadingHTTPServer(ThreadingHTTPServer):
    """Threaded local server that does not block shutdown on active handlers."""

    daemon_threads = True


def normalize_identity_role(role: str) -> str:
    """Return a supported test identity role or raise a user-facing error."""
    value = str(role or "").strip().lower()
    if value not in IDENTITY_ROLES:
        raise ValueError("身份必须是 normal、api、admin 或 owner")
    return value


def build_identity_payload(role: str) -> dict:
    """Build the frontend identity state used for local role switching."""
    normalized = normalize_identity_role(role)
    return {
        "ok": True,
        "role": normalized,
        "is_admin": normalized in {"admin", "owner"},
        "api_enabled": normalized == "api",
        "roles": IDENTITY_ROLES,
    }


def normalize_ai_user_requirement(value: Any) -> str:
    """Normalize user-provided AI focus text without treating it as trusted instruction."""

    text = str(value or "")
    text = "".join(
        " " if ord(char) < 32 or ord(char) == 127 else char
        for char in text
    )
    text = " ".join(text.split()).strip()
    if len(text) > AI_USER_REQUIREMENT_MAX_CHARS:
        raise ValueError(f"AI 分析要求最多 {AI_USER_REQUIREMENT_MAX_CHARS} 个字符")
    if re.search(r"(sk-[A-Za-z0-9_\-]{12,}|[A-Za-z0-9_\-]{48,})", text):
        raise ValueError("AI 分析要求中不要填写 API Key、密码或其他密钥")
    return text


def can_manage_account_role(actor_role: str, target_role: str, requested_role: str) -> bool:
    """Return whether an account role update is allowed by the DEMO hierarchy."""

    if is_owner_role(requested_role) and not is_owner_role(target_role):
        return False
    if is_owner_role(actor_role):
        return True
    return not (is_privileged_role(target_role) or is_privileged_role(requested_role))


def csrf_token_matches(expected: str, provided: str) -> bool:
    """Constant-time CSRF token comparison."""

    if not expected or not provided:
        return False
    return secrets.compare_digest(str(expected), str(provided))


def drop_session_locked(token: str) -> None:
    """Remove all in-memory state for one session token. Caller holds STATE_LOCK."""

    SESSION_STORE.drop(token)


def cleanup_expired_sessions(now: float | None = None) -> int:
    """Clear expired in-memory sessions and return the number removed."""

    return SESSION_STORE.cleanup_expired(now)


def install_admin_default_ai_provider() -> None:
    """Install an admin demo provider from env without hardcoding secrets."""

    api_key = os.environ.get(ADMIN_DEFAULT_PROVIDER_KEY_ENV, "").strip()
    if not api_key or AI_PROVIDER_STORE.has(ADMIN_DEFAULT_PROVIDER_ACCOUNT):
        return
    try:
        config = normalize_provider_config({
            "provider": "deepseek",
            "api_key": api_key,
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-v4-flash",
        })
        AI_PROVIDER_STORE.set(ADMIN_DEFAULT_PROVIDER_ACCOUNT, config)
    except ValueError as exc:
        print(f"管理员默认模型 API 未安装：{exc}", file=sys.stderr)


def store_job_full_result(job_id: str, payload: dict[str, Any]) -> None:
    """Store large job result separately so status polling stays lightweight."""

    with STATE_LOCK:
        JOB_RESULTS[job_id] = payload
        while len(JOB_RESULTS) > MAX_FULL_JOB_RESULTS:
            oldest_id = next(iter(JOB_RESULTS))
            JOB_RESULTS.pop(oldest_id, None)


def pop_job_full_result(job_id: str, consume: bool = True) -> dict[str, Any] | None:
    """Return a full job result, optionally consuming it after the frontend reads it."""

    with STATE_LOCK:
        if consume:
            return JOB_RESULTS.pop(job_id, None)
        return JOB_RESULTS.get(job_id)


def danmaku_fetch_meta(
    reported_count: int,
    fetched_count: int,
    source: str,
    segment_count: int = 0,
    history_enabled: bool = False,
    history_auth_required: bool = False,
    history_month_count: int = 0,
    history_date_count: int = 0,
    history_rows_count: int = 0,
    history_error: str = "",
    history_error_type: str = "",
) -> dict[str, Any]:
    """Build user-facing diagnostics for a danmaku fetch operation."""

    ratio = fetched_count / reported_count if reported_count > 0 else 1
    warning = ""
    if history_auth_required:
        warning = (
            "已请求历史弹幕补抓，但服务端未配置 BILI_SESSDATA 或 BILI_COOKIE。"
            "当前只返回公开分段弹幕池。"
        )
    elif history_error or history_error_type:
        warning = history_warning_message(history_error_type, history_error)
    elif reported_count > fetched_count and reported_count >= 10_000 and ratio < 0.8:
        hint = "可勾选历史补抓并在服务端配置 BILI_SESSDATA。" if not history_enabled else "历史补抓后仍未接近统计值，可能受接口权限、快照覆盖范围或上限影响。"
        warning = (
            f"B 站统计约 {reported_count} 条弹幕，本次通过"
            f"{'分段接口' if source == 'segment' else '旧 XML 接口'}获取 {fetched_count} 条。"
            "当前 DEMO 抓取的是公开视频接口可返回的弹幕池，未按历史发送日期遍历，"
            f"因此老视频或百万弹幕视频可能无法拿到历史累计全量。{hint}"
        )
    return {
        "reported_count": reported_count,
        "fetched_count": fetched_count,
        "source": source,
        "segment_count": segment_count,
        "history_enabled": history_enabled,
        "history_auth_required": history_auth_required,
        "history_month_count": history_month_count,
        "history_date_count": history_date_count,
        "history_rows_count": history_rows_count,
        "history_error": history_error,
        "history_error_type": history_error_type,
        "coverage_ratio": round(ratio, 4) if reported_count > 0 else 1,
        "warning": warning,
    }


def history_warning_message(error_type: str, history_error: str = "") -> str:
    """Build a concise diagnostic for historical danmaku fetch failures."""

    detail = f"：{history_error}" if history_error else ""
    messages = {
        "auth_required": "历史补抓需要服务端配置 BILI_SESSDATA 或 BILI_COOKIE",
        "cookie_invalid": "历史补抓可能因为 Cookie 失效或权限不足而失败",
        "risk_control": "历史补抓疑似触发 B 站风控或 412 限制",
        "index_empty": "历史弹幕日期索引为空，可能该视频无可用历史快照或接口未返回数据",
        "index_partial": "部分历史月份索引读取失败",
        "index_failed": "历史弹幕日期索引读取失败",
        "snapshot_failed": "部分历史弹幕快照下载失败",
        "parse_failed": "历史弹幕快照解析异常",
        "row_limit": "历史补抓已达到当前 DEMO 弹幕上限",
    }
    prefix = messages.get(error_type or "", "历史弹幕补抓未完成")
    return f"{prefix}{detail}。当前结果可能不是历史累计全量。"


def ai_artifact_files(folder: Path) -> list[Path]:
    """Return AI report/word artifacts, excluding cache and usage stats."""

    if not folder.exists():
        return []
    patterns = (
        "current_*_report.txt",
        "current_*_words.json",
        "compare_*_report.txt",
        "compare_*_words.json",
    )
    files: list[Path] = []
    for pattern in patterns:
        files.extend(path for path in folder.glob(pattern) if path.is_file() and path.parent == folder)
    return sorted(set(files), key=lambda path: path.stat().st_mtime, reverse=True)


def prune_ai_artifacts(folder: Path, max_files: int = AI_ARTIFACT_MAX_FILES) -> dict[str, int]:
    """Keep only the newest AI report/word artifacts in file-mode demo storage."""

    limit = max(1, int(max_files or AI_ARTIFACT_MAX_FILES))
    files = ai_artifact_files(folder)
    removed = 0
    removed_bytes = 0
    for path in files[limit:]:
        try:
            size = path.stat().st_size
            path.unlink()
            removed += 1
            removed_bytes += size
        except OSError:
            continue
    return {"removed": removed, "removed_bytes": removed_bytes, "max_files": limit}


def read_int_env(name: str, default: int, min_value: int, max_value: int) -> int:
    """Read a bounded integer environment setting."""

    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    return max(min_value, min(max_value, value))


def block_words_signature(words: list[str] | None) -> str:
    """Return the same lightweight signature used by the browser."""

    return "\n".join(
        str(word or "").strip().lower()
        for word in (words or [])
        if str(word or "").strip()
    )


def build_search_stats(rows: list[dict[str, Any]], duration: int, block_words: list[str] | None = None) -> dict[str, Any]:
    """Build filtered server-side stats for a BV search response."""

    effective_rows = apply_blocklist(rows, block_words or [], mode="drop").danmakus
    return build_frontend_video_stats(
        effective_rows,
        duration=duration,
        stop_words=load_block_words(ROOT / "config" / "stop_words.txt"),
        filter_signature=block_words_signature(block_words),
    )


def bvid_search_payload(
    bvid: str,
    cid_raw: str = "",
    include_history: bool = False,
    block_words: list[str] | None = None,
    history_cookie: str = "",
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Fetch one BV video and its selected part danmakus with progress events."""

    def emit(event: dict[str, Any]) -> None:
        if progress_callback:
            progress_callback(event)

    emit({"stage": "search_start", "progress": 4, "message": f"准备获取 {bvid}"})
    collector = BilibiliCollector(history_cookie=history_cookie)
    emit({"stage": "video_info_start", "progress": 12, "message": "正在读取视频标题、封面和统计数据"})
    video_info = collector.fetch_video_info(bvid)
    emit({
        "stage": "video_info_done",
        "progress": 24,
        "message": f"视频信息读取完成：{video_info.get('title') or bvid}",
        "video": {"bvid": bvid, "title": video_info.get("title", "")},
    })
    emit({"stage": "pages_start", "progress": 30, "message": "正在读取视频分 P 信息"})
    pages = collector.fetch_page_list(bvid)
    emit({"stage": "pages_done", "progress": 38, "message": f"已读取 {len(pages)} 个分 P", "page_count": len(pages)})
    if cid_raw:
        try:
            cid = int(cid_raw)
        except ValueError as exc:
            raise ValueError("cid 必须是数字") from exc
        if not any(p["cid"] == cid for p in pages):
            raise ValueError(f"cid {cid} 不属于该视频")
    else:
        cid = pages[0]["cid"]

    title = video_info["title"]
    emit({"stage": "danmaku_collect_start", "progress": 45, "message": "开始下载并解析弹幕分段", "cid": cid})
    collect_result = collect_video_danmaku_result(
        collector,
        cid,
        bvid=bvid,
        title=title,
        duration=int(video_info.get("duration", 0) or 0),
        include_history=include_history,
        pubdate=int(video_info.get("pubdate", 0) or 0),
        history_max_months=read_int_env("BILI_HISTORY_MAX_MONTHS", 180, 1, 240),
        history_max_dates=read_int_env("BILI_HISTORY_MAX_DATES", 180, 1, 1200),
        max_rows=MAX_DANMAKU_ROWS,
        progress_callback=progress_callback,
    )
    rows = collect_result.rows
    if len(rows) > MAX_DANMAKU_ROWS:
        raise RequestBodyTooLarge(f"该分 P 弹幕数为 {len(rows)}，超过当前 DEMO 上限 {MAX_DANMAKU_ROWS}")
    reported_count = int(video_info.get("danmaku", 0) or 0)
    video = {**video_info, "danmaku": len(rows), "reported_danmaku": reported_count}
    stats = build_search_stats(rows, int(video_info.get("duration", 0) or 0), block_words=block_words)
    fetch_meta = danmaku_fetch_meta(
        reported_count=reported_count,
        fetched_count=len(rows),
        source=collect_result.source,
        segment_count=collect_result.segment_count,
        history_enabled=collect_result.history_enabled,
        history_auth_required=collect_result.history_auth_required,
        history_month_count=collect_result.history_month_count,
        history_date_count=collect_result.history_date_count,
        history_rows_count=collect_result.history_rows_count,
        history_error=collect_result.history_error,
        history_error_type=collect_result.history_error_type,
    )
    emit({"stage": "package_done", "progress": 94, "message": f"弹幕整理完成，共 {len(rows)} 条", "rows_count": len(rows)})
    return {
        "ok": True,
        "video": video,
        "pages": pages,
        "current_cid": cid,
        "danmakus": rows,
        "stats": stats,
        "danmaku_fetch": fetch_meta,
    }


def bvid_search_job_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a compact BV search result for frequent status polling."""

    video = payload.get("video") if isinstance(payload.get("video"), dict) else {}
    meta = payload.get("danmaku_fetch") if isinstance(payload.get("danmaku_fetch"), dict) else {}
    return {
        "has_result": True,
        "bvid": video.get("bvid", ""),
        "title": video.get("title", ""),
        "danmaku_count": len(payload.get("danmakus") or []),
        "reported_count": meta.get("reported_count", 0),
        "page_count": len(payload.get("pages") or []),
        "current_cid": payload.get("current_cid", 0),
        "history_enabled": meta.get("history_enabled", False),
        "history_date_count": meta.get("history_date_count", 0),
        "history_rows_count": meta.get("history_rows_count", 0),
        "history_error_type": meta.get("history_error_type", ""),
        "warning": meta.get("warning", ""),
    }


def bvid_search_progress_callback(job_id: str) -> Callable[[dict[str, Any]], None]:
    """Build a progress callback for one BV search job."""

    def callback(event: dict[str, Any]) -> None:
        stage = str(event.get("stage") or "progress")
        progress = int(event.get("progress") or 0)
        message = str(event.get("message") or "")
        level = "info"
        detail: dict[str, Any] = dict(event)

        if stage == "danmaku_segment_done":
            segment_index = int(event.get("segment_index") or 0)
            segment_count = max(1, int(event.get("segment_count") or 1))
            rows_count = int(event.get("rows_count") or 0)
            progress = 45 + int((segment_index / segment_count) * 42)
            message = f"正在处理弹幕分段 {segment_index}/{segment_count}，已解析 {rows_count} 条"
        elif stage == "danmaku_segment_failed":
            progress = 48
            level = "warning"
            message = "分段弹幕接口失败，正在尝试旧 XML 接口"
        elif stage == "danmaku_xml_start":
            progress = 52
            level = "warning"
            message = "正在使用旧 XML 接口回退获取弹幕"
        elif stage == "danmaku_xml_done":
            progress = 86
            message = f"旧 XML 弹幕读取完成，共 {event.get('rows_count', 0)} 条"
        elif stage == "history_auth_required":
            progress = 88
            level = "warning"
            message = "历史补抓需要服务端配置 BILI_SESSDATA 或 BILI_COOKIE"
        elif stage == "history_index_start":
            progress = 88
            message = f"正在查询历史弹幕月份索引，共 {event.get('month_count', 0)} 个月"
        elif stage == "history_month_done":
            done = int(event.get("done") or 0)
            total = max(1, int(event.get("total") or 1))
            progress = 88 + int((done / total) * 4)
            message = f"历史月份索引 {done}/{total}，已找到 {event.get('date_count', 0)} 个快照日期"
        elif stage == "history_month_failed":
            done = int(event.get("done") or 0)
            total = max(1, int(event.get("total") or 1))
            progress = 88 + int((done / total) * 4)
            level = "warning"
            message = (
                f"历史月份索引 {done}/{total} 读取失败：{event.get('month', '')}，"
                "已继续尝试其他月份"
            )
        elif stage == "history_fetch_start":
            progress = 92
            message = f"开始补抓历史弹幕快照，共 {event.get('date_count', 0)} 个日期"
        elif stage == "history_date_done":
            done = int(event.get("done") or 0)
            total = max(1, int(event.get("total") or 1))
            progress = 92 + int((done / total) * 6)
            message = (
                f"历史快照 {done}/{total}：{event.get('date', '')}，"
                f"新增 {event.get('added', 0)} 条，累计 {event.get('total_rows_count', 0)} 条"
            )
        elif stage == "history_date_failed":
            level = "warning"
            message = f"历史快照 {event.get('date', '')} 读取失败：{event.get('message', '')}"
        elif stage == "history_index_failed":
            level = "warning"
            message = f"历史月份索引读取失败：{event.get('message', '')}"
        elif stage == "history_row_limit":
            progress = 98
            level = "warning"
            message = f"已达到 DEMO 弹幕上限 {event.get('row_limit', MAX_DANMAKU_ROWS)} 条，停止历史补抓"

        if not message:
            message = "任务状态更新中"
        JOB_MANAGER.update(job_id, progress=progress, message=message)
        JOB_MANAGER.add_event(job_id, message, level=level, step_name=stage, progress=progress, detail=detail)

    return callback


def run_bvid_search_job(
    job_id: str,
    bvid: str,
    cid_raw: str = "",
    include_history: bool = False,
    block_words: list[str] | None = None,
    history_cookie: str = "",
) -> None:
    """Run BV search in a background thread and keep the large payload out of status."""

    JOB_MANAGER.start(job_id, "BV 搜索任务已开始")
    try:
        payload = bvid_search_payload(
            bvid,
            cid_raw=cid_raw,
            include_history=include_history,
            block_words=block_words,
            history_cookie=history_cookie,
            progress_callback=bvid_search_progress_callback(job_id),
        )
        store_job_full_result(job_id, payload)
        summary = bvid_search_job_summary(payload)
        message = f"BV 搜索完成：{summary['title'] or summary['bvid']}，{summary['danmaku_count']} 条弹幕"
        JOB_MANAGER.succeed(job_id, message, summary)
    except Exception as exc:  # noqa: BLE001 - 后台任务需要把异常转为可见状态。
        JOB_MANAGER.fail(job_id, f"BV 搜索失败：{exc}", error=str(exc))
        print(f"BV 搜索任务失败：{exc}", file=sys.stderr)


def refresh_popular_payload(
    limit: int,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Refresh popular data and return the same payload shape used by the sync API."""

    def emit(event: dict[str, Any]) -> None:
        if progress_callback:
            progress_callback(event)

    emit({"stage": "start", "progress": 3, "message": "准备更新热门榜单"})
    collector = BilibiliCollector()
    today_videos, today_danmakus = collect_popular_dataset(
        collector,
        limit=limit,
        progress_callback=progress_callback,
    )
    stop_words = load_block_words(ROOT / "config" / "stop_words.txt")
    emit({"stage": "archive_save_start", "progress": 80, "message": "正在写入当天热门榜单归档"})
    archive = ArchiveStore(ROOT)
    archive.save_today_hot_data(today_videos, today_danmakus, stop_words=stop_words)
    emit({"stage": "archive_save_done", "progress": 86, "message": "当天归档已写入"})
    emit({"stage": "export_start", "progress": 94, "message": "正在导出今日热门榜单数据"})
    export_project_data(
        ROOT,
        today_videos,
        today_danmakus,
        block_words=load_block_words(ROOT / "config" / "block_words.txt"),
        stop_words=stop_words,
    )
    emit({"stage": "export_done", "progress": 98, "message": "前端数据已导出"})
    failed_videos = [
        {
            "bvid": video.get("bvid", ""),
            "title": video.get("title", ""),
            "error": video.get("danmaku_fetch_error", ""),
        }
        for video in today_videos
        if video.get("danmaku_fetch_error")
    ]
    return {
        "ok": True,
        "videos": today_videos,
        "danmaku_count": len(today_danmakus),
        "exported_video_count": len(today_videos),
        "exported_danmaku_count": len(today_danmakus),
        "failed_video_count": len(failed_videos),
        "failed_videos": failed_videos,
        "date": now_beijing().strftime("%Y-%m-%d"),
    }


def refresh_job_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a compact refresh result safe for frequent polling."""

    return {
        "video_count": len(payload.get("videos") or []),
        "danmaku_count": payload.get("danmaku_count", 0),
        "exported_video_count": payload.get("exported_video_count", 0),
        "exported_danmaku_count": payload.get("exported_danmaku_count", 0),
        "failed_video_count": payload.get("failed_video_count", 0),
        "failed_videos": payload.get("failed_videos", [])[:20],
        "date": payload.get("date", ""),
    }


def refresh_job_progress_callback(job_id: str) -> Callable[[dict[str, Any]], None]:
    """Build a progress callback that maps collection events to a visible job."""

    def callback(event: dict[str, Any]) -> None:
        stage = str(event.get("stage") or "progress")
        level = "info"
        progress = int(event.get("progress") or 0)
        message = str(event.get("message") or "")
        detail: dict[str, Any] = {}

        if stage == "fetch_popular_start":
            progress = 8
            message = "正在获取 B 站热门视频列表"
            detail = {"limit": event.get("limit", 0)}
        elif stage == "fetch_popular_done":
            progress = 15
            message = f"热门视频列表获取完成，共 {event.get('total', 0)} 个视频"
            detail = {"total": event.get("total", 0)}
        elif stage == "video_done":
            done = int(event.get("done") or 0)
            total = max(1, int(event.get("total") or 1))
            video = event.get("video") or {}
            title = video.get("title") or video.get("bvid") or "未知视频"
            progress = 15 + int((done / total) * 60)
            if event.get("error"):
                level = "warning"
                message = f"第 {done}/{total} 个视频弹幕采集失败：{title}"
            else:
                message = f"已采集第 {done}/{total} 个视频：{title}"
            detail = {
                "done": done,
                "total": total,
                "bvid": video.get("bvid", ""),
                "title": title,
                "rows_count": event.get("rows_count", 0),
                "error": event.get("error", ""),
            }
        elif stage == "collect_done":
            progress = 76
            message = f"弹幕采集完成，共 {event.get('danmaku_count', 0)} 条"
            detail = {"danmaku_count": event.get("danmaku_count", 0)}
        elif not message:
            message = "任务进度已更新"

        JOB_MANAGER.update(job_id, status="running", progress=progress, message=message)
        JOB_MANAGER.add_event(job_id, message, level=level, step_name=stage, progress=progress, detail=detail)

    return callback


def run_refresh_popular_job(job_id: str, limit: int) -> None:
    """Run the popular refresh in a background thread."""

    JOB_MANAGER.start(job_id, "热门榜单更新任务已开始")
    try:
        payload = refresh_popular_payload(limit, progress_callback=refresh_job_progress_callback(job_id))
        result = refresh_job_result(payload)
        failed = int(result.get("failed_video_count") or 0)
        if failed:
            message = f"更新完成：{result['video_count']} 个视频，{result['danmaku_count']} 条弹幕，{failed} 个视频有采集警告"
        else:
            message = f"更新完成：{result['video_count']} 个视频，{result['danmaku_count']} 条弹幕"
        JOB_MANAGER.succeed(job_id, message, result)
    except Exception as exc:  # noqa: BLE001 - 后台任务需要把异常转为可见状态。
        JOB_MANAGER.fail(job_id, f"热门榜单更新失败：{exc}", error=str(exc))
        print(f"热门榜单更新任务失败：{exc}", file=sys.stderr)


def archive_date_refresh_payload(
    selected_date: str,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """刷新某个已有热门归档日期的视频元数据和弹幕。

    历史日期代表当日榜单快照，因此这里保留原有视频成员和 rank 顺序，
    只把视频信息与弹幕重新从 B 站获取后写回同一归档目录。
    """

    def emit(event: dict[str, Any]) -> None:
        if progress_callback:
            progress_callback(event)

    datetime.strptime(selected_date, "%Y-%m-%d")
    folder = ROOT / "data" / "archive" / selected_date
    video_file = folder / "today_hot_videos.json"
    danmaku_file = folder / "today_danmakus.json"
    if not video_file.exists():
        raise FileNotFoundError(f"未找到 {selected_date} 的热门榜单视频归档")

    archived_videos = read_json(video_file)
    if not isinstance(archived_videos, list):
        raise ValueError(f"{selected_date} 的热门榜单视频归档格式不正确")
    archived_danmakus = read_all_danmakus(folder, danmaku_file)
    old_rows_by_bvid: dict[str, list[dict[str, Any]]] = {}
    if isinstance(archived_danmakus, list):
        for row in archived_danmakus:
            if not isinstance(row, dict):
                continue
            row_bvid = str(row.get("bvid") or "").strip()
            if row_bvid:
                old_rows_by_bvid.setdefault(row_bvid, []).append(row)

    emit({
        "stage": "archive_refresh_start",
        "date": selected_date,
        "total": len(archived_videos),
        "message": f"准备刷新 {selected_date} 的归档视频数据",
    })

    collector = BilibiliCollector()
    updated_videos: list[dict[str, Any]] = []
    updated_danmakus: list[dict[str, Any]] = []
    failed_videos: list[dict[str, Any]] = []

    for index, original in enumerate(archived_videos, start=1):
        if not isinstance(original, dict):
            updated_videos.append({
                "rank": index,
                "bvid": "",
                "title": f"第 {index} 个视频",
                "danmaku_fetch_error": "视频归档项格式不正确",
            })
            failed_videos.append({
                "rank": index,
                "bvid": "",
                "title": "",
                "error": "视频归档项格式不正确",
            })
            emit({
                "stage": "archive_video_done",
                "date": selected_date,
                "done": index,
                "total": len(archived_videos),
                "video": {"rank": index, "title": "格式错误"},
                "rows_count": 0,
                "error": "视频归档项格式不正确",
            })
            continue

        bvid = str(original.get("bvid") or "").strip()
        rank = int(original.get("rank") or index)
        title = str(original.get("title") or bvid or f"第 {rank} 个视频")
        if not bvid:
            failed_videos.append({
                "rank": rank,
                "bvid": "",
                "title": title,
                "error": "缺少 bvid",
            })
            updated_videos.append({**original, "rank": rank, "danmaku_fetch_error": "缺少 bvid"})
            emit({
                "stage": "archive_video_done",
                "date": selected_date,
                "done": index,
                "total": len(archived_videos),
                "video": {"rank": rank, "title": title},
                "rows_count": 0,
                "error": "缺少 bvid",
            })
            continue

        try:
            info = collector.fetch_video_info(bvid)
            pages = collector.fetch_page_list(bvid)
            cid = int(pages[0]["cid"])
            collect_result = collect_video_danmaku_result(
                collector,
                cid,
                bvid=bvid,
                title=str(info.get("title") or title),
                duration=int(info.get("duration", 0) or original.get("duration", 0) or 0),
                max_rows=MAX_DANMAKU_ROWS,
            )
            rows = collect_result.rows
            if len(rows) > MAX_DANMAKU_ROWS:
                raise ValueError(f"弹幕数 {len(rows)} 超过当前 DEMO 上限 {MAX_DANMAKU_ROWS}")

            reported_count = int(info.get("danmaku", 0) or 0)
            fetch_meta = danmaku_fetch_meta(
                reported_count=reported_count,
                fetched_count=len(rows),
                source=collect_result.source,
                segment_count=collect_result.segment_count,
                history_enabled=collect_result.history_enabled,
                history_auth_required=collect_result.history_auth_required,
                history_month_count=collect_result.history_month_count,
                history_date_count=collect_result.history_date_count,
                history_rows_count=collect_result.history_rows_count,
                history_error=collect_result.history_error,
                history_error_type=collect_result.history_error_type,
            )
            updated_video = {
                **original,
                **info,
                "rank": rank,
                "danmaku": len(rows),
                "reported_danmaku": reported_count,
                "page_count": len(pages),
                "danmaku_fetch": fetch_meta,
            }
            updated_videos.append(updated_video)
            updated_danmakus.extend(rows)
            emit({
                "stage": "archive_video_done",
                "date": selected_date,
                "done": index,
                "total": len(archived_videos),
                "video": updated_video,
                "rows_count": len(rows),
                "error": "",
            })
        except Exception as exc:  # noqa: BLE001 - 单个视频失败时保留原归档项并继续。
            error = str(exc)
            fallback = {
                **original,
                "rank": rank,
                "danmaku_fetch_error": error,
            }
            updated_videos.append(fallback)
            updated_danmakus.extend(old_rows_by_bvid.get(bvid, []))
            failed_videos.append({
                "rank": rank,
                "bvid": bvid,
                "title": title,
                "error": error,
            })
            emit({
                "stage": "archive_video_done",
                "date": selected_date,
                "done": index,
                "total": len(archived_videos),
                "video": fallback,
                "rows_count": 0,
                "error": error,
            })

    emit({
        "stage": "archive_write_start",
        "date": selected_date,
        "video_count": len(updated_videos),
        "danmaku_count": len(updated_danmakus),
        "message": f"正在写回 {selected_date} 的归档文件",
    })
    write_json(video_file, updated_videos)
    write_danmaku_store(
        folder,
        updated_videos,
        updated_danmakus,
        module="popular_archive",
        date=selected_date,
        stop_words=load_block_words(ROOT / "config" / "stop_words.txt"),
    )
    emit({
        "stage": "archive_write_done",
        "date": selected_date,
        "video_count": len(updated_videos),
        "danmaku_count": len(updated_danmakus),
        "failed_video_count": len(failed_videos),
        "message": f"{selected_date} 归档数据已写回",
    })

    return {
        "ok": True,
        "archive_date": selected_date,
        "updated_video_count": len(updated_videos),
        "updated_danmaku_count": len(updated_danmakus),
        "failed_video_count": len(failed_videos),
        "failed_videos": failed_videos[:20],
    }


def archive_date_refresh_progress_callback(job_id: str) -> Callable[[dict[str, Any]], None]:
    """把归档日期刷新事件转换为前端可展示的任务进度。"""

    def callback(event: dict[str, Any]) -> None:
        stage = str(event.get("stage") or "progress")
        level = "info"
        progress = int(event.get("progress") or 0)
        message = str(event.get("message") or "")
        detail = dict(event)

        if stage == "archive_refresh_start":
            progress = 5
            message = message or f"准备刷新 {event.get('date', '')} 的归档数据"
        elif stage == "archive_video_done":
            done = int(event.get("done") or 0)
            total = max(1, int(event.get("total") or 1))
            video = event.get("video") or {}
            title = video.get("title") or video.get("bvid") or "未知视频"
            progress = 8 + int((done / total) * 82)
            if event.get("error"):
                level = "warning"
                message = f"第 {done}/{total} 个视频刷新失败：{title}"
            else:
                message = f"已刷新第 {done}/{total} 个视频：{title}，{event.get('rows_count', 0)} 条弹幕"
            detail = {
                "date": event.get("date", ""),
                "done": done,
                "total": total,
                "bvid": video.get("bvid", ""),
                "title": title,
                "rows_count": event.get("rows_count", 0),
                "error": event.get("error", ""),
            }
        elif stage == "archive_write_start":
            progress = 94
            message = message or "正在写回归档文件"
        elif stage == "archive_write_done":
            progress = 98
            failed = int(event.get("failed_video_count") or 0)
            message = message or f"归档写入完成，{failed} 个视频有采集警告"
            detail = {
                "date": event.get("date", ""),
                "video_count": event.get("video_count", 0),
                "danmaku_count": event.get("danmaku_count", 0),
                "failed_video_count": failed,
            }
        elif not message:
            message = "归档刷新进度已更新"

        JOB_MANAGER.update(job_id, status="running", progress=progress, message=message)
        JOB_MANAGER.add_event(job_id, message, level=level, step_name=stage, progress=progress, detail=detail)

    return callback


def run_archive_date_refresh_job(job_id: str, selected_date: str) -> None:
    """在后台线程中执行历史热门归档数据刷新。"""

    JOB_MANAGER.start(job_id, f"{selected_date} 归档数据刷新任务已开始")
    try:
        result = archive_date_refresh_payload(
            selected_date,
            progress_callback=archive_date_refresh_progress_callback(job_id),
        )
        failed = int(result.get("failed_video_count") or 0)
        if failed:
            message = (
                f"{selected_date} 归档更新完成：{result['updated_video_count']} 个视频，"
                f"{result['updated_danmaku_count']} 条弹幕，{failed} 个视频有采集警告"
            )
        else:
            message = (
                f"{selected_date} 归档更新完成：{result['updated_video_count']} 个视频，"
                f"{result['updated_danmaku_count']} 条弹幕"
            )
        JOB_MANAGER.succeed(job_id, message, result)
    except Exception as exc:  # noqa: BLE001 - 后台任务需要把异常转为可见状态。
        JOB_MANAGER.fail(job_id, f"{selected_date} 归档数据刷新失败：{exc}", error=str(exc))
        print(f"归档数据刷新任务失败：{exc}", file=sys.stderr)


class Handler(SimpleHTTPRequestHandler):
    """自定义请求处理器：/api/search 走实时采集，其余走静态文件。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / "web"), **kwargs)

    def end_headers(self):
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' https: data:; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none'",
        )
        super().end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/search":
            self._handle_api_search(parsed)
        elif parsed.path == "/api/video-info":
            self._handle_video_info(parsed)
        elif parsed.path == "/api/video-danmakus":
            self._handle_video_danmakus(parsed)
        elif parsed.path == "/api/background-image":
            self._handle_background_image()
        elif parsed.path == "/api/compare":
            self._handle_compare_placeholder()
        elif parsed.path == "/api/refresh-popular":
            self._handle_deprecated_refresh_popular()
        elif parsed.path == "/api/identity":
            self._handle_get_identity()
        elif parsed.path == "/api/account/session":
            self._handle_account_session()
        elif parsed.path == "/api/account/ai-captcha":
            self._handle_ai_captcha()
        elif parsed.path == "/api/account/block-words":
            self._handle_get_block_words()
        elif parsed.path == "/api/account/ai-provider":
            self._handle_get_ai_provider()
        elif parsed.path == "/api/account/bili-cookie":
            self._handle_get_bili_cookie()
        elif parsed.path == "/api/account/ai-usage":
            self._handle_account_ai_usage()
        elif parsed.path == "/api/admin/status":
            self._handle_admin_status()
        elif parsed.path == "/api/admin/users":
            self._handle_admin_users()
        elif parsed.path == "/api/admin/block-words":
            self._handle_admin_get_block_words()
        elif parsed.path == "/api/admin/ai-cache":
            self._handle_admin_ai_cache()
        elif parsed.path == "/api/admin/storage-usage":
            self._handle_admin_storage_usage()
        elif parsed.path == "/api/admin/ai-usage":
            self._handle_admin_ai_usage()
        elif parsed.path == "/api/jobs/status":
            self._handle_job_status(parsed)
        elif parsed.path == "/api/jobs/result":
            self._handle_job_result(parsed)
        elif parsed.path == "/api/jobs/recent":
            self._handle_recent_jobs(parsed)
        elif parsed.path == "/api/popular-dates":
            self._handle_popular_dates()
        elif parsed.path == "/api/popular-date":
            self._handle_popular_date(parsed)
        else:
            if parsed.path.startswith("/api/"):
                self._send_json(404, {"ok": False, "error": "未知接口", "path": parsed.path})
                return
            super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if not self._validate_same_origin_post():
            return
        if not self._validate_csrf_post(parsed.path):
            return
        if parsed.path == "/api/identity":
            self._handle_set_identity()
        elif parsed.path == "/api/account/email-code":
            self._handle_email_code()
        elif parsed.path == "/api/account/register":
            self._handle_register()
        elif parsed.path == "/api/account/login":
            self._handle_login()
        elif parsed.path == "/api/account/logout":
            self._handle_logout()
        elif parsed.path == "/api/account/profile":
            self._handle_profile_update()
        elif parsed.path == "/api/account/api-toggle":
            self._handle_api_toggle()
        elif parsed.path == "/api/account/api-reset":
            self._handle_api_reset()
        elif parsed.path == "/api/account/block-words":
            self._handle_save_block_words()
        elif parsed.path == "/api/account/ai-provider":
            self._handle_save_ai_provider()
        elif parsed.path == "/api/account/ai-provider/test":
            self._handle_test_ai_provider()
        elif parsed.path == "/api/account/bili-cookie":
            self._handle_save_bili_cookie()
        elif parsed.path == "/api/ai/analyze":
            self._handle_ai_analyze()
        elif parsed.path == "/api/admin/users/update":
            self._handle_admin_user_update()
        elif parsed.path == "/api/admin/block-words":
            self._handle_admin_save_block_words()
        elif parsed.path == "/api/admin/ai-cache/clear":
            self._handle_admin_clear_ai_cache()
        elif parsed.path == "/api/admin/storage-cleanup":
            self._handle_admin_storage_cleanup()
        elif parsed.path == "/api/jobs/refresh-popular":
            self._handle_create_refresh_popular_job()
        elif parsed.path == "/api/jobs/refresh-archive-date":
            self._handle_create_archive_date_refresh_job()
        elif parsed.path == "/api/jobs/search":
            self._handle_create_bvid_search_job()
        elif parsed.path == "/api/refresh-popular":
            self._handle_deprecated_refresh_popular()
        else:
            self._send_json(404, {"ok": False, "error": "未知接口", "path": parsed.path})

    def _read_json_body(self, max_bytes: int = DEFAULT_JSON_BODY_LIMIT) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError as exc:
            raise ValueError("Content-Length 不合法") from exc
        if length > max_bytes:
            raise RequestBodyTooLarge(f"请求体过大，最大允许 {max_bytes // 1024} KB")
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        return json.loads(raw or "{}")

    def _validate_same_origin_post(self) -> bool:
        origin = self.headers.get("Origin", "").strip()
        referer = self.headers.get("Referer", "").strip()
        source = origin or referer
        if not source:
            return True
        host = self.headers.get("Host", "").strip()
        parsed = urlparse(source)
        if parsed.scheme in {"http", "https"} and parsed.netloc == host:
            return True
        self._send_json(403, {"ok": False, "error": "请求来源不合法"})
        return False

    def _validate_csrf_post(self, path: str) -> bool:
        if path in CSRF_EXEMPT_POST_PATHS:
            return True
        session_token = self._session_token()
        if not session_token:
            return True
        if not self._current_account():
            return True
        provided = self.headers.get("X-CSRF-Token", "").strip()
        expected = SESSION_STORE.get_csrf_token(session_token)
        if csrf_token_matches(expected, provided):
            return True
        self._send_json(403, {"ok": False, "error": "CSRF Token 无效，请刷新页面后重试"})
        return False

    def _client_key(self) -> str:
        host = self.client_address[0] if self.client_address else "local"
        return str(host or "local")

    def _rate_owner(self) -> str:
        return self._current_account() or self._client_key()

    def _check_interval_limit(self, key: str, interval_seconds: int, label: str) -> bool:
        if interval_seconds <= 0:
            return True
        with STATE_LOCK:
            now = time.time()
            last = RATE_LIMITS.get(key)
            if last is None or now - last >= interval_seconds:
                RATE_LIMITS[key] = now
                return True
            wait = max(1, int(interval_seconds - (now - last)))
        self._send_json(429, {"ok": False, "error": f"{label}过于频繁，请等待 {wait} 秒"})
        return False

    def _check_window_limit(self, key: str, max_count: int, window_seconds: int, label: str) -> bool:
        with STATE_LOCK:
            now = time.time()
            start = now - window_seconds
            hits = [item for item in RATE_WINDOWS.get(key, []) if item >= start]
            if len(hits) < max_count:
                hits.append(now)
                RATE_WINDOWS[key] = hits
                return True
            RATE_WINDOWS[key] = hits
            wait = max(1, int(window_seconds - (now - hits[0])))
        self._send_json(429, {"ok": False, "error": f"{label}过于频繁，请等待 {wait} 秒"})
        return False

    def _session_token(self) -> str:
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookie.get(SESSION_COOKIE_NAME)
        return morsel.value if morsel else ""

    def _current_account(self) -> str | None:
        token = self._session_token()
        if not token:
            return None
        return SESSION_STORE.get_account(token)

    def _current_user(self) -> dict | None:
        account = self._current_account()
        if not account:
            return None
        return ACCOUNT_STORE.find(account)

    def _start_session(self, account: str) -> tuple[str, str]:
        cleanup_expired_sessions()
        token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        SESSION_STORE.create(token, account, csrf_token, time.time() + SESSION_MAX_AGE_SECONDS)
        cookie = (
            f"{SESSION_COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Lax; "
            f"Max-Age={SESSION_MAX_AGE_SECONDS}"
        )
        return cookie, csrf_token

    def _clear_session_header(self) -> str:
        token = self._session_token()
        if token:
            SESSION_STORE.drop(token)
        return f"{SESSION_COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"

    def _current_csrf_token(self) -> str:
        token = self._session_token()
        if not token:
            return ""
        if not self._current_account():
            return ""
        return SESSION_STORE.get_csrf_token(token)

    def _require_login(self) -> dict | None:
        user = self._current_user()
        if not user:
            self._send_json(401, {"ok": False, "error": "请先登入"})
            return None
        return user

    def _require_admin(self) -> dict | None:
        user = self._require_login()
        if not user:
            return None
        if not is_admin_role(user.get("role")):
            self._send_json(403, {"ok": False, "error": "需要管理员或 owner 账号"})
            return None
        return user

    def _require_owner(self) -> dict | None:
        user = self._require_login()
        if not user:
            return None
        if not is_owner_role(user.get("role")):
            self._send_json(403, {"ok": False, "error": "需要 owner 账号"})
            return None
        return user

    def _block_words_path(self) -> Path:
        return ROOT / "config" / "block_words.txt"

    def _user_block_words_dir(self) -> Path:
        return ROOT / "data" / "user_block_words"

    def _user_block_words_path(self, account: str) -> Path:
        safe_account = "".join(
            char for char in str(account or "") if char.isalnum() or char == "_"
        )
        if not safe_account:
            safe_account = "unknown"
        return self._user_block_words_dir() / f"{safe_account}.txt"

    def _merge_block_words(self, *word_groups: list[str]) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for words in word_groups:
            for word in words:
                value = str(word or "").strip()
                key = value.lower()
                if not value or key in seen:
                    continue
                merged.append(value)
                seen.add(key)
        return merged

    def _normalize_block_words(self, raw_words) -> list[str]:
        if isinstance(raw_words, str):
            candidates = raw_words.replace(",", "\n").splitlines()
        elif isinstance(raw_words, list):
            candidates = [str(item) for item in raw_words]
        else:
            raise ValueError("屏蔽词必须是数组或文本")
        words: list[str] = []
        seen: set[str] = set()
        for item in candidates:
            word = item.strip()
            key = word.lower()
            if not word or word.startswith("#") or key in seen:
                continue
            if len(word) > 30:
                raise ValueError("单个屏蔽词不能超过 30 个字符")
            words.append(word)
            seen.add(key)
        if len(words) > 200:
            raise ValueError("屏蔽词最多 200 个")
        return words

    def _account_block_word_payload(self, account: str, words: list[str]) -> dict:
        global_words = load_block_words(self._block_words_path())
        effective_words = self._merge_block_words(global_words, words)
        path = self._user_block_words_path(account)
        return {
            "ok": True,
            "words": words,
            "global_words": global_words,
            "effective_words": effective_words,
            "count": len(words),
            "global_count": len(global_words),
            "effective_count": len(effective_words),
            "path": str(path.relative_to(ROOT)).replace("\\", "/"),
            "global_path": "config/block_words.txt",
            "mode": "drop",
        }

    def _current_effective_block_words(self) -> list[str]:
        user = self._current_user()
        if not user:
            return []
        account = str(user.get("account") or "")
        return self._merge_block_words(
            load_block_words(self._block_words_path()),
            load_block_words(self._user_block_words_path(account)),
        )

    def _global_block_word_payload(self, words: list[str]) -> dict:
        return {
            "ok": True,
            "words": words,
            "count": len(words),
            "path": "config/block_words.txt",
            "mode": "drop",
        }

    def _current_ai_provider(self) -> dict | None:
        user = self._current_user()
        if not user:
            return None
        return AI_PROVIDER_STORE.get(str(user.get("account") or ""))

    def _current_bili_cookie_config(self) -> dict | None:
        user = self._current_user()
        if not user:
            return None
        return BILI_COOKIE_STORE.get(str(user.get("account") or ""))

    def _current_bili_cookie_header(self) -> str:
        config = self._current_bili_cookie_config()
        return str(config.get("cookie_header") or "") if config else ""

    def _has_ai_provider(self, user: dict | None) -> bool:
        if not user:
            return False
        return AI_PROVIDER_STORE.has(str(user.get("account") or ""))

    def _api_ready_for_user(self, user: dict | None) -> bool:
        return bool(user and user.get("api_enabled") and self._has_ai_provider(user))

    def _can_use_ai_analysis(self) -> bool:
        user = self._current_user()
        return self._api_ready_for_user(user)

    def _effective_identity_role(self, user: dict | None = None) -> str:
        current = user if user is not None else self._current_user()
        token = self._session_token()
        demo_role = SESSION_STORE.get_identity_role(token) if token else ""
        if current and is_admin_role(current.get("role")):
            return demo_role or "admin"
        if self._api_ready_for_user(current):
            return "api"
        return "normal"

    def _identity_payload(self, role: str, user: dict | None = None) -> dict:
        current = self._current_user() if user is None else user
        payload = build_identity_payload(role)
        payload["api_switch_enabled"] = bool(current and current.get("api_enabled"))
        payload["api_configured"] = self._has_ai_provider(current)
        payload["ai_available"] = self._api_ready_for_user(current)
        return payload

    def _handle_get_identity(self):
        self._send_json(200, self._identity_payload(self._effective_identity_role()))

    def _handle_set_identity(self):
        actor = self._require_admin()
        if not actor:
            return
        try:
            data = self._read_json_body(SMALL_JSON_BODY_LIMIT)
            role = normalize_identity_role(data.get("role", "normal"))
            if role == "owner" and not is_owner_role(actor.get("role")):
                self._send_json(403, {"ok": False, "error": "只有 owner 可以切换到 owner 演示身份"})
                return
            token = self._session_token()
            if not token:
                raise ValueError("缺少登入会话")
            if not SESSION_STORE.set_identity_role(token, role):
                raise ValueError("缺少登入会话")
        except RequestBodyTooLarge as exc:
            self._send_json(413, {"ok": False, "error": str(exc)})
            return
        except (json.JSONDecodeError, ValueError) as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        self._send_json(200, self._identity_payload(role, actor))

    def _session_payload(self, user: dict | None = None, csrf_token: str = "") -> dict:
        current = user if user is not None else self._current_user()
        return {
            "ok": True,
            "logged_in": bool(current),
            "user": public_user(current, reveal_api_key=True) if current else None,
            "identity": self._identity_payload(self._effective_identity_role(current), current),
            "csrf_token": csrf_token or (self._current_csrf_token() if current else ""),
        }

    def _handle_account_session(self):
        ACCOUNT_STORE.ensure_defaults()
        self._send_json(200, self._session_payload())

    def _handle_ai_captcha(self):
        if not self._check_interval_limit(f"captcha:{self._client_key()}", 2, "验证码"):
            return
        left = secrets.randbelow(8) + 2
        right = secrets.randbelow(8) + 2
        token = secrets.token_urlsafe(12)
        with STATE_LOCK:
            AI_CAPTCHAS[token] = {"answer": str(left + right), "expires_at": time.time() + 300}
        self._send_json(200, {"ok": True, "token": token, "question": f"{left} + {right} = ?"})

    def _handle_email_code(self):
        try:
            data = self._read_json_body(SMALL_JSON_BODY_LIMIT)
            email = validate_email(data.get("email", ""))
        except RequestBodyTooLarge as exc:
            self._send_json(413, {"ok": False, "error": str(exc)})
            return
        except (json.JSONDecodeError, ValueError) as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        if not self._check_interval_limit(f"email:{email}:{self._client_key()}", 60, "邮箱验证码"):
            return
        code = f"{secrets.randbelow(900000) + 100000}"
        with STATE_LOCK:
            EMAIL_CODES[email] = {"code": code, "expires_at": time.time() + 300}
        self._send_json(200, {
            "ok": True,
            "message": "DEMO 验证码已生成，真实项目中应发送到邮箱。",
            "demo_code": code,
            "expires_in": 300,
        })

    def _check_register_codes(self, data: dict):
        email = validate_email(data.get("email", ""))
        email_code = str(data.get("email_code", "")).strip()
        now = time.time()
        with STATE_LOCK:
            email_record = EMAIL_CODES.get(email)
        if not email_record or email_record["expires_at"] < now or email_record["code"] != email_code:
            raise ValueError("邮箱验证码错误或已过期")

        token = str(data.get("ai_token", "")).strip()
        answer = str(data.get("ai_answer", "")).strip()
        self._verify_ai_captcha(token, answer)
        return email

    def _verify_ai_captcha(self, token: str, answer: str) -> None:
        now = time.time()
        with STATE_LOCK:
            ai_record = AI_CAPTCHAS.get(token)
        if not ai_record or ai_record["expires_at"] < now or ai_record["answer"] != answer:
            raise ValueError("AI 验证码错误或已过期")
        with STATE_LOCK:
            AI_CAPTCHAS.pop(token, None)

    def _login_failure_key(self, account_key: str) -> str:
        return f"{self._client_key()}:{account_key}"

    def _login_failure_state(self, account_key: str) -> dict[str, float | int]:
        key = self._login_failure_key(account_key)
        now = time.time()
        with STATE_LOCK:
            state = LOGIN_FAILURES.get(key)
            if not state:
                return {"count": 0, "locked_until": 0}
            locked_until = float(state.get("locked_until") or 0)
            last_at = float(state.get("last_at") or 0)
            if locked_until <= now and now - last_at > LOGIN_FAILURE_WINDOW_SECONDS:
                LOGIN_FAILURES.pop(key, None)
                return {"count": 0, "locked_until": 0}
            return dict(state)

    def _record_login_failure(self, account_key: str) -> dict[str, float | int]:
        key = self._login_failure_key(account_key)
        now = time.time()
        with STATE_LOCK:
            state = LOGIN_FAILURES.get(key)
            if not state or now - float(state.get("last_at") or 0) > LOGIN_FAILURE_WINDOW_SECONDS:
                state = {"count": 0, "locked_until": 0, "lock_count": 0}
            count = int(state.get("count") or 0) + 1
            state["count"] = count
            state["last_at"] = now
            if count >= LOGIN_LOCK_THRESHOLD:
                lock_count = int(state.get("lock_count") or 0) + 1
                state["lock_count"] = lock_count
                duration = LOGIN_LOCK_STEPS_SECONDS[min(lock_count - 1, len(LOGIN_LOCK_STEPS_SECONDS) - 1)]
                state["locked_until"] = now + duration
                state["lock_duration"] = duration
            LOGIN_FAILURES[key] = state
            return dict(state)

    def _clear_login_failures(self, account_key: str) -> None:
        with STATE_LOCK:
            LOGIN_FAILURES.pop(self._login_failure_key(account_key), None)

    def _send_login_failure(self, state: dict[str, float | int], status: int = 401) -> None:
        now = time.time()
        locked_until = float(state.get("locked_until") or 0)
        requires_captcha = int(state.get("count") or 0) >= LOGIN_CAPTCHA_THRESHOLD
        payload = {
            "ok": False,
            "error": "账号或密码错误",
            "requires_captcha": requires_captcha,
        }
        if locked_until > now:
            wait = max(1, int(locked_until - now))
            payload.update({
                "error": f"登录失败次数过多，请等待 {wait} 秒后再试",
                "locked": True,
                "retry_after": wait,
                "requires_captcha": True,
            })
            status = 429
        self._send_json(status, payload)

    def _handle_register(self):
        try:
            data = self._read_json_body(DEFAULT_JSON_BODY_LIMIT)
            self._check_register_codes(data)
            user = ACCOUNT_STORE.create_user(data)
        except RequestBodyTooLarge as exc:
            self._send_json(413, {"ok": False, "error": str(exc)})
            return
        except (json.JSONDecodeError, ValueError) as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        cookie, csrf_token = self._start_session(user["account"])
        self._send_json(200, self._session_payload(user, csrf_token), {
            "Set-Cookie": cookie,
        })

    def _handle_login(self):
        try:
            data = self._read_json_body(SMALL_JSON_BODY_LIMIT)
            account_key = str(data.get("account", "")).strip().lower() or "empty"
            if not self._check_window_limit(f"login-ip:{self._client_key()}", 20, 300, "登入"):
                return
            if not self._check_window_limit(f"login:{account_key}:{self._client_key()}", 8, 300, "登入"):
                return
            failure_state = self._login_failure_state(account_key)
            if float(failure_state.get("locked_until") or 0) > time.time():
                self._send_login_failure(failure_state)
                return
            if int(failure_state.get("count") or 0) >= LOGIN_CAPTCHA_THRESHOLD:
                token = str(data.get("ai_token", "")).strip()
                answer = str(data.get("ai_answer", "")).strip()
                if not token or not answer:
                    self._send_json(403, {
                        "ok": False,
                        "error": "登录失败次数较多，请先完成 AI 验证码",
                        "requires_captcha": True,
                    })
                    return
                try:
                    self._verify_ai_captcha(token, answer)
                except ValueError as exc:
                    self._send_json(403, {
                        "ok": False,
                        "error": str(exc),
                        "requires_captcha": True,
                    })
                    return
            user = ACCOUNT_STORE.authenticate(data.get("account", ""), data.get("password", ""))
            self._clear_login_failures(account_key)
        except RequestBodyTooLarge as exc:
            self._send_json(413, {"ok": False, "error": str(exc)})
            return
        except json.JSONDecodeError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        except ValueError as exc:
            message = str(exc)
            if "封禁" in message or "禁用" in message:
                self._clear_login_failures(str(data.get("account", "")).strip().lower() or "empty")
                self._send_json(403, {
                    "ok": False,
                    "error": message,
                    "disabled": True,
                    "requires_captcha": False,
                })
                return
            failure_state = self._record_login_failure(str(data.get("account", "")).strip().lower() or "empty")
            self._send_login_failure(failure_state)
            return
        cookie, csrf_token = self._start_session(user["account"])
        self._send_json(200, self._session_payload(user, csrf_token), {
            "Set-Cookie": cookie,
        })

    def _handle_logout(self):
        clear_cookie = self._clear_session_header()
        self._send_json(200, self._session_payload(None), {
            "Set-Cookie": clear_cookie,
        })

    def _handle_profile_update(self):
        user = self._require_login()
        if not user:
            return
        try:
            data = self._read_json_body(DEFAULT_JSON_BODY_LIMIT)
            updated = ACCOUNT_STORE.update_profile(user["account"], data)
        except RequestBodyTooLarge as exc:
            self._send_json(413, {"ok": False, "error": str(exc)})
            return
        except (json.JSONDecodeError, ValueError) as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        self._send_json(200, self._session_payload(updated))

    def _handle_api_toggle(self):
        user = self._require_login()
        if not user:
            return
        try:
            data = self._read_json_body(SMALL_JSON_BODY_LIMIT)
            enabled = bool(data.get("enabled"))
            updated = ACCOUNT_STORE.set_api_enabled(user["account"], enabled)
        except RequestBodyTooLarge as exc:
            self._send_json(413, {"ok": False, "error": str(exc)})
            return
        except (json.JSONDecodeError, ValueError) as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        self._send_json(200, self._session_payload(updated))

    def _handle_api_reset(self):
        user = self._require_login()
        if not user:
            return
        try:
            updated = ACCOUNT_STORE.reset_api_key(user["account"])
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        self._send_json(200, self._session_payload(updated))

    def _handle_get_block_words(self):
        user = self._require_login()
        if not user:
            return
        account = str(user.get("account") or "")
        words = load_block_words(self._user_block_words_path(account))
        self._send_json(200, self._account_block_word_payload(account, words))

    def _handle_save_block_words(self):
        user = self._require_login()
        if not user:
            return
        try:
            data = self._read_json_body(BLOCK_WORDS_BODY_LIMIT)
            account = str(user.get("account") or "")
            words = self._normalize_block_words(data.get("words", []))
            content = "\n".join(words)
            write_text(self._user_block_words_path(account), (content + "\n") if content else "")
        except RequestBodyTooLarge as exc:
            self._send_json(413, {"ok": False, "error": str(exc)})
            return
        except (json.JSONDecodeError, ValueError) as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        payload = self._account_block_word_payload(account, words)
        payload["message"] = "个人屏蔽词已保存，将只影响当前账号的数据查看和 AI 分析。"
        self._send_json(200, payload)

    def _handle_admin_get_block_words(self):
        if not self._require_admin():
            return
        words = load_block_words(self._block_words_path())
        self._send_json(200, self._global_block_word_payload(words))

    def _handle_admin_save_block_words(self):
        if not self._require_admin():
            return
        try:
            data = self._read_json_body(BLOCK_WORDS_BODY_LIMIT)
            words = self._normalize_block_words(data.get("words", []))
            content = "\n".join(words)
            write_text(self._block_words_path(), (content + "\n") if content else "")
        except RequestBodyTooLarge as exc:
            self._send_json(413, {"ok": False, "error": str(exc)})
            return
        except (json.JSONDecodeError, ValueError) as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        payload = self._global_block_word_payload(words)
        payload["message"] = "全局屏蔽词已保存，会与每个账号的个人屏蔽词共同生效。"
        self._send_json(200, payload)

    def _handle_get_ai_provider(self):
        if not self._require_login():
            return
        self._send_json(200, provider_status(self._current_ai_provider()))

    def _handle_save_ai_provider(self):
        user = self._require_login()
        if not user:
            return
        account = str(user.get("account") or "")
        try:
            data = self._read_json_body(SMALL_JSON_BODY_LIMIT)
            if data.get("clear"):
                AI_PROVIDER_STORE.clear(account)
                self._send_json(200, {
                    **provider_status(None),
                    "message": "自带模型 API 已清除。",
                })
                return
            existing_provider = AI_PROVIDER_STORE.get(account)
            if not str(data.get("api_key") or "").strip() and existing_provider:
                requested_provider = str(data.get("provider") or existing_provider.get("provider") or "").strip().lower()
                if requested_provider != str(existing_provider.get("provider") or "").strip().lower():
                    raise ValueError("切换模型服务商时需要重新输入 API Key")
                data["api_key"] = existing_provider["api_key"]
            config = normalize_provider_config(data)
            AI_PROVIDER_STORE.set(account, config)
        except RequestBodyTooLarge as exc:
            self._send_json(413, {"ok": False, "error": str(exc)})
            return
        except (json.JSONDecodeError, ValueError) as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        self._send_json(200, {
            **provider_status(config),
            "message": "自带模型 API 已保存到本机加密存储。",
        })

    def _handle_test_ai_provider(self):
        user = self._require_login()
        if not user:
            return
        if not self._check_interval_limit(f"ai-provider-test:{self._rate_owner()}", 15, "AI 连接测试"):
            return
        try:
            data = self._read_json_body(SMALL_JSON_BODY_LIMIT)
            config = normalize_provider_config(data) if data.get("api_key") else self._current_ai_provider()
            if not config:
                raise ValueError("请先填写并保存模型 API Key")
            result = test_deepseek_provider(config)
        except RequestBodyTooLarge as exc:
            self._send_json(413, {"ok": False, "error": str(exc)})
            return
        except (json.JSONDecodeError, ValueError, AiProviderError) as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        self._send_json(200, {
            **provider_status(config),
            "message": f"连接测试成功：{result.get('message', 'ready')}",
        })

    def _handle_get_bili_cookie(self):
        if not self._require_login():
            return
        self._send_json(200, bili_cookie_status(self._current_bili_cookie_config()))

    def _handle_save_bili_cookie(self):
        user = self._require_login()
        if not user:
            return
        account = str(user.get("account") or "")
        try:
            data = self._read_json_body(SMALL_JSON_BODY_LIMIT)
            if data.get("clear"):
                BILI_COOKIE_STORE.clear(account)
                self._send_json(200, {
                    **bili_cookie_status(None),
                    "message": "B 站历史补抓 Cookie 已清除。",
                })
                return
            BILI_COOKIE_STORE.set(
                account,
                str(data.get("credential_type") or "sessdata"),
                str(data.get("value") or ""),
            )
            config = BILI_COOKIE_STORE.get(account)
        except RequestBodyTooLarge as exc:
            self._send_json(413, {"ok": False, "error": str(exc)})
            return
        except (json.JSONDecodeError, ValueError) as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        self._send_json(200, {
            **bili_cookie_status(config),
            "message": "B 站历史补抓 Cookie 已保存到本机加密存储。",
        })

    def _handle_ai_analyze(self):
        if not self._can_use_ai_analysis():
            self._send_json(403, {"ok": False, "error": "请先在个人页面开启 API，并保存当前账号自己的模型 API 配置"})
            return
        try:
            data = self._read_json_body(AI_ANALYZE_BODY_LIMIT)
            if not isinstance(data, dict):
                raise ValueError("请求体必须是 JSON 对象")
            data["analysis_mode"] = self._normalize_ai_analysis_mode(data.get("analysis_mode"))
            data["user_requirement"] = normalize_ai_user_requirement(data.get("user_requirement"))
            self._validate_ai_payload_size(data)
            provider = self._current_ai_provider()
            cache_key = self._ai_cache_key(data, provider)
            if not data.get("force_refresh"):
                cached = self._load_ai_cache(cache_key)
                if cached:
                    cached["cached"] = True
                    cached["cache_key"] = cache_key
                    self._record_ai_usage(
                        data,
                        provider,
                        cache_hit=True,
                        external_call=False,
                        status="cache_hit",
                        success=True,
                        response=cached,
                    )
                    self._send_json(200, cached)
                    return
            if not self._check_interval_limit(f"ai-analyze:{self._rate_owner()}", 20, "AI 分析"):
                return
            result = build_ai_analysis(data)
            result["analysis_mode"] = data["analysis_mode"]
            result["analysis_prompt_version"] = AI_ANALYSIS_PROMPT_VERSION
            result["local_stats_version"] = AI_LOCAL_STATS_VERSION
            external_call = False
            usage_status = "local_success"
            if provider:
                external_call = True
                try:
                    # 当前 DEMO 由本地 server.py 代理用户自己的模型 Key。
                    # 后续若开通公益 API，可在这里接入平台统一 Key；不建议让浏览器直连暴露用户 Key。
                    result = call_deepseek_analysis(provider, data, result)
                    usage_status = "provider_success"
                except AiProviderError as exc:
                    result["provider_error"] = str(exc)
                    result["provider"] = "local-demo"
                    usage_status = "provider_fallback"
            result["cached"] = False
            result["cache_key"] = cache_key
            self._save_ai_artifacts(data, result)
            if not result.get("provider_error"):
                self._store_ai_cache(cache_key, result)
            self._record_ai_usage(
                data,
                provider,
                cache_hit=False,
                external_call=external_call,
                status=usage_status,
                success=bool(result.get("ok", True)),
                response=result,
                error=str(result.get("provider_error") or ""),
            )
        except RequestBodyTooLarge as exc:
            self._send_json(413, {"ok": False, "error": str(exc)})
            return
        except (json.JSONDecodeError, ValueError) as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        self._send_json(200, result)

    def _record_ai_usage(
        self,
        data: dict[str, Any],
        provider: dict[str, Any] | None,
        *,
        cache_hit: bool,
        external_call: bool,
        status: str,
        success: bool,
        response: dict[str, Any] | None = None,
        error: str = "",
    ) -> None:
        try:
            AI_USAGE_STORE.record(build_usage_record(
                account=self._current_account(),
                payload=data,
                provider=provider,
                cache_hit=cache_hit,
                external_call=external_call,
                status=status,
                success=success,
                response=response,
                error=error,
            ))
        except Exception:
            # 使用统计不能影响 AI 分析主流程。
            return

    def _normalize_ai_analysis_mode(self, value: Any) -> str:
        mode = str(value or "economy").strip().lower().replace("-", "_")
        aliases = {
            "summary": "economy",
            "summary_samples": "economy",
            "cheap": "economy",
            "deep_summary": "deep",
            "full": "full_raw",
            "full_raw": "full_raw",
            "raw": "full_raw",
        }
        mode = aliases.get(mode, mode)
        if mode not in {"economy", "deep", "full_raw"}:
            raise ValueError("AI 分析模式必须是 economy、deep 或 full_raw")
        return mode

    def _validate_ai_payload_size(self, data: dict):
        mode = self._normalize_ai_analysis_mode(data.get("analysis_mode"))
        datasets = data.get("datasets") if isinstance(data.get("datasets"), list) else [data]
        for item in datasets:
            if not isinstance(item, dict):
                continue
            rows = item.get("danmakus")
            if isinstance(rows, list) and len(rows) > MAX_DANMAKU_ROWS:
                raise ValueError(f"AI 接口最多接受 {MAX_DANMAKU_ROWS} 条弹幕；大数据请使用摘要和抽样模式")
            if mode == "full_raw":
                if not isinstance(rows, list):
                    raise ValueError("全量原文模式需要提交弹幕原文，请重新选择视频后再试")
                if len(rows) > MAX_AI_FULL_RAW_ROWS:
                    raise ValueError(
                        f"全量原文模式最多提交 {MAX_AI_FULL_RAW_ROWS} 条弹幕；"
                        "更大数据请使用深度摘要模式"
                    )
            metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
            count = int(float(metrics.get("danmaku_count") or 0))
            if count > MAX_DANMAKU_ROWS:
                raise ValueError(f"弹幕数量超过 {MAX_DANMAKU_ROWS} 条，当前 DEMO 不继续处理")

    def _ai_cache_dir(self) -> Path:
        return ROOT / "data" / "ai_analysis" / "cache"

    def _ai_cache_path(self, cache_key: str) -> Path:
        return self._ai_cache_dir() / f"{cache_key}.json"

    def _ai_cache_key(self, data: dict, provider: dict | None) -> str:
        payload = {key: value for key, value in data.items() if key != "force_refresh"}
        provider_fingerprint = {
            "provider": provider.get("provider") if provider else "local-demo",
            "base_url": provider.get("base_url") if provider else "",
            "model": provider.get("model") if provider else "",
        }
        basis = {
            "analysis_prompt_version": AI_ANALYSIS_PROMPT_VERSION,
            "local_stats_version": AI_LOCAL_STATS_VERSION,
            "account": self._current_account() or "anonymous",
            "provider": provider_fingerprint,
            "payload": payload,
        }
        text = json.dumps(basis, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _load_ai_cache(self, cache_key: str) -> dict | None:
        path = self._ai_cache_path(cache_key)
        if not path.exists():
            return None
        try:
            cached = read_json(path)
        except (OSError, json.JSONDecodeError):
            return None
        return cached if isinstance(cached, dict) and cached.get("ok") else None

    def _store_ai_cache(self, cache_key: str, result: dict) -> None:
        payload = dict(result)
        payload["cached"] = False
        payload["cache_key"] = cache_key
        payload["cached_at"] = now_beijing().isoformat(timespec="seconds")
        payload["analysis_prompt_version"] = payload.get("analysis_prompt_version") or AI_ANALYSIS_PROMPT_VERSION
        payload["local_stats_version"] = payload.get("local_stats_version") or AI_LOCAL_STATS_VERSION
        write_json(self._ai_cache_path(cache_key), payload)

    def _ai_cache_files(self) -> list[Path]:
        folder = self._ai_cache_dir()
        if not folder.exists():
            return []
        return [
            path
            for path in folder.glob("*.json")
            if path.is_file() and path.parent == folder
        ]

    def _ai_cache_stats(self) -> dict[str, Any]:
        files = self._ai_cache_files()
        total_bytes = sum(path.stat().st_size for path in files)
        mtimes = [path.stat().st_mtime for path in files]
        newest = max(mtimes) if mtimes else 0
        oldest = min(mtimes) if mtimes else 0
        return {
            "ok": True,
            "count": len(files),
            "total_bytes": total_bytes,
            "oldest_at": datetime.fromtimestamp(oldest, BEIJING_TZ).isoformat(timespec="seconds") if oldest else "",
            "newest_at": datetime.fromtimestamp(newest, BEIJING_TZ).isoformat(timespec="seconds") if newest else "",
            "path": str(self._ai_cache_dir().relative_to(ROOT)).replace("\\", "/"),
        }

    def _clear_ai_cache(self, mode: str = "expired", max_age_days: int = 7) -> dict[str, Any]:
        now = time.time()
        cutoff = now - max(1, int(max_age_days or 7)) * 86400
        removed = 0
        removed_bytes = 0
        for path in self._ai_cache_files():
            if mode != "all" and path.stat().st_mtime >= cutoff:
                continue
            try:
                size = path.stat().st_size
                path.unlink()
                removed += 1
                removed_bytes += size
            except OSError:
                continue
        stats = self._ai_cache_stats()
        stats.update({
            "removed": removed,
            "removed_bytes": removed_bytes,
            "mode": mode,
            "max_age_days": max_age_days,
        })
        return stats

    def _save_ai_artifacts(self, request_payload: dict, result: dict):
        folder = ROOT / "data" / "ai_analysis"
        folder.mkdir(parents=True, exist_ok=True)
        scope = str(result.get("scope") or request_payload.get("scope") or "current")
        if scope == "compare":
            base = "compare_latest"
        else:
            video = request_payload.get("video") if isinstance(request_payload.get("video"), dict) else {}
            base = f"current_{self._safe_filename(str(video.get('bvid') or 'selected'))}"
        report_path = folder / f"{base}_report.txt"
        report_path.write_text(str(result.get("text") or ""), encoding="utf-8")
        artifacts = {
            "report": str(report_path.relative_to(ROOT)).replace("\\", "/"),
            "analysis_prompt_version": AI_ANALYSIS_PROMPT_VERSION,
            "local_stats_version": AI_LOCAL_STATS_VERSION,
        }
        words = result.get("words")
        if isinstance(words, list):
            words_path = folder / f"{base}_words.json"
            write_json(words_path, words)
            artifacts["words"] = str(words_path.relative_to(ROOT)).replace("\\", "/")
        artifacts["retention"] = prune_ai_artifacts(folder, max_files=AI_ARTIFACT_MAX_FILES)
        result["artifacts"] = artifacts

    def _safe_filename(self, value: str) -> str:
        kept = [char if char.isalnum() or char in {"_", "-"} else "_" for char in value]
        text = "".join(kept).strip("_")
        return text[:80] or "selected"

    def _handle_admin_users(self):
        if not self._require_admin():
            return
        users = [public_user(user, reveal_api_key=False) for user in ACCOUNT_STORE.users()]
        self._send_json(200, {"ok": True, "users": users})

    def _handle_admin_user_update(self):
        actor = self._require_admin()
        if not actor:
            return
        try:
            data = self._read_json_body(DEFAULT_JSON_BODY_LIMIT)
            target_account = str(data.get("account", ""))
            target = ACCOUNT_STORE.find(target_account)
            if not target:
                raise ValueError("账号不存在")
            if "api_enabled" in data:
                raise ValueError("API 开关只能由账号本人在个人页面修改")
            requested_role = str(data.get("role") or target.get("role") or "normal")
            if is_owner_role(requested_role) and not is_owner_role(target.get("role")):
                raise ValueError("owner 账号只能在服务器端创建，不能通过后台提升")
            if not can_manage_account_role(actor.get("role", "normal"), target.get("role", "normal"), requested_role):
                raise ValueError("只有 owner 可以管理管理员或 owner 权限")
            if is_owner_role(actor.get("role")) and target.get("account") == actor.get("account"):
                if requested_role != "owner":
                    raise ValueError("不能撤销自己的 owner 权限")
                if data.get("disabled") is True:
                    raise ValueError("不能禁用自己的 owner 账号")
            updated = ACCOUNT_STORE.admin_update_user(target_account, data)
            if updated.get("account") == self._current_account() and not is_admin_role(updated.get("role")):
                token = self._session_token()
                SESSION_STORE.clear_identity_role(token)
        except RequestBodyTooLarge as exc:
            self._send_json(413, {"ok": False, "error": str(exc)})
            return
        except (json.JSONDecodeError, ValueError) as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        self._send_json(200, {"ok": True, "user": public_user(updated, reveal_api_key=False)})

    def _handle_admin_status(self):
        if not self._require_admin():
            return
        files = {
            "dashboard": ROOT / "web" / "data" / "dashboard.json",
            "danmaku_index": ROOT / "web" / "data" / "danmaku_index.json",
            "video_stats": ROOT / "web" / "data" / "video_stats.json",
            "accounts": ACCOUNT_STORE.path,
        }
        self._send_json(200, {
            "ok": True,
            "server_time": now_beijing().isoformat(timespec="seconds"),
            "current_identity": build_identity_payload(self._effective_identity_role()),
            "current_account": self._current_account(),
            "account_count": len(ACCOUNT_STORE.users()),
            "archive_dates": self._archive_dates(),
            "files": {
                name: {"exists": path.exists(), "size": path.stat().st_size if path.exists() else 0}
                for name, path in files.items()
            },
        })

    def _handle_admin_ai_cache(self):
        if not self._require_admin():
            return
        self._send_json(200, self._ai_cache_stats())

    def _handle_admin_storage_usage(self):
        if not self._require_admin():
            return
        self._send_json(200, storage_usage(ROOT))

    def _handle_account_ai_usage(self):
        user = self._require_login()
        if not user:
            return
        self._send_json(200, AI_USAGE_STORE.account_summary(str(user.get("account") or "")))

    def _handle_admin_ai_usage(self):
        if not self._require_owner():
            return
        self._send_json(200, AI_USAGE_STORE.admin_summary())

    def _handle_admin_clear_ai_cache(self):
        if not self._require_admin():
            return
        try:
            data = self._read_json_body(SMALL_JSON_BODY_LIMIT)
            mode = str(data.get("mode") or "expired").strip().lower()
            if mode not in {"expired", "all"}:
                raise ValueError("清理模式必须是 expired 或 all")
            if mode == "all" and data.get("confirm") is not True:
                raise ValueError("清空全部缓存需要 confirm=true")
            max_age_days = int(data.get("max_age_days") or 7)
            result = self._clear_ai_cache(mode=mode, max_age_days=max_age_days)
        except RequestBodyTooLarge as exc:
            self._send_json(413, {"ok": False, "error": str(exc)})
            return
        except (json.JSONDecodeError, ValueError) as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        self._send_json(200, result)

    def _handle_admin_storage_cleanup(self):
        if not self._require_admin():
            return
        try:
            data = self._read_json_body(SMALL_JSON_BODY_LIMIT)
            result = cleanup_storage(ROOT, data)
        except RequestBodyTooLarge as exc:
            self._send_json(413, {"ok": False, "error": str(exc)})
            return
        except (json.JSONDecodeError, ValueError) as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        self._send_json(200, result)

    def _handle_create_refresh_popular_job(self):
        if not self._require_admin():
            return
        existing = JOB_MANAGER.latest_running(REFRESH_POPULAR_JOB_TYPE)
        if existing:
            self._send_json(200, {"ok": True, "existing": True, "job": existing})
            return
        if not self._check_interval_limit(f"refresh-popular:{self._rate_owner()}", 60, "热门榜单更新"):
            return
        job = JOB_MANAGER.create(
            REFRESH_POPULAR_JOB_TYPE,
            account=self._current_account(),
            message="热门榜单更新任务已创建",
        )
        thread = threading.Thread(
            target=run_refresh_popular_job,
            args=(job["job_id"], 50),
            name=f"refresh-popular-{job['job_id'][:8]}",
            daemon=True,
        )
        thread.start()
        self._send_json(202, {"ok": True, "existing": False, "job": JOB_MANAGER.get(job["job_id"]) or job})

    def _handle_create_archive_date_refresh_job(self):
        self._send_json(410, {
            "ok": False,
            "error": "已归档榜单数据保持只读，不再支持整日归档写回。请使用当前视频数据更新，它只会刷新页面缓存，不会修改归档文件。",
        })

    def _handle_create_bvid_search_job(self):
        try:
            data = self._read_json_body(SMALL_JSON_BODY_LIMIT)
            bvid_raw = str(data.get("bvid") or "").strip()
            if not bvid_raw:
                raise ValueError("缺少 bvid 参数")
            bvid = extract_bvid(bvid_raw)
            cid_raw = str(data.get("cid") or "").strip()
            include_history_value = data.get("include_history")
            include_history = include_history_value is True or str(include_history_value).strip().lower() in {"1", "true", "yes", "on"}
        except RequestBodyTooLarge as exc:
            self._send_json(413, {"ok": False, "error": str(exc)})
            return
        except (json.JSONDecodeError, ValueError) as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        if not self._check_interval_limit(
            f"bvid-search:{self._rate_owner()}",
            self._search_interval_seconds(),
            "BV 搜索",
        ):
            return
        job = JOB_MANAGER.create(
            BVID_SEARCH_JOB_TYPE,
            account=self._rate_owner(),
            message=f"BV 搜索任务已创建：{bvid}{'（含历史补抓）' if include_history else ''}",
        )
        thread = threading.Thread(
            target=run_bvid_search_job,
            args=(
                job["job_id"],
                bvid,
                cid_raw,
                include_history,
                self._current_effective_block_words(),
                self._current_bili_cookie_header(),
            ),
            name=f"bvid-search-{job['job_id'][:8]}",
            daemon=True,
        )
        thread.start()
        active_job = JOB_MANAGER.get(job["job_id"]) or job
        self._send_json(202, {"ok": True, "job": self._job_payload_for_current_user(active_job)})

    def _can_access_job(self, job: dict[str, Any]) -> bool:
        user = self._current_user()
        if user and is_admin_role(user.get("role")):
            return True
        owner = str(job.get("account") or "")
        return bool(owner and owner == self._rate_owner())

    def _can_view_job_debug(self) -> bool:
        user = self._current_user()
        return bool(user and is_admin_role(user.get("role")))

    def _job_payload_for_current_user(self, job: dict[str, Any]) -> dict[str, Any]:
        if self._can_view_job_debug():
            return job
        return {
            "job_id": job.get("job_id", ""),
            "type": job.get("type", ""),
            "account": "",
            "status": job.get("status", "pending"),
            "progress": 100 if job.get("status") in {"success", "failed", "cancelled"} else 0,
            "message": job.get("message", "任务状态更新中"),
            "created_at": job.get("created_at", ""),
            "started_at": job.get("started_at", ""),
            "finished_at": job.get("finished_at", ""),
            "result": {},
            "error": job.get("error", ""),
            "events": [],
        }

    def _redact_danmaku_fetch_debug(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._can_view_job_debug():
            return payload
        redacted = dict(payload)
        redacted.pop("danmaku_fetch", None)
        video = redacted.get("video")
        if isinstance(video, dict):
            redacted_video = dict(video)
            redacted_video.pop("danmaku_fetch", None)
            redacted["video"] = redacted_video
        return redacted

    def _handle_job_status(self, parsed):
        params = parse_qs(parsed.query)
        job_id = str(params.get("job_id", [""])[0]).strip()
        if not job_id:
            self._send_json(400, {"ok": False, "error": "缺少 job_id 参数"})
            return
        job = JOB_MANAGER.get(job_id)
        if not job:
            self._send_json(404, {"ok": False, "error": "任务不存在或已被清理"})
            return
        if not self._can_access_job(job):
            self._send_json(403, {"ok": False, "error": "无权查看该任务"})
            return
        self._send_json(200, {"ok": True, "job": self._job_payload_for_current_user(job)})

    def _handle_job_result(self, parsed):
        params = parse_qs(parsed.query)
        job_id = str(params.get("job_id", [""])[0]).strip()
        consume = str(params.get("consume", ["1"])[0]).strip() != "0"
        if not job_id:
            self._send_json(400, {"ok": False, "error": "缺少 job_id 参数"})
            return
        job = JOB_MANAGER.get(job_id)
        if not job:
            self._send_json(404, {"ok": False, "error": "任务不存在或已被清理"})
            return
        if not self._can_access_job(job):
            self._send_json(403, {"ok": False, "error": "无权读取该任务结果"})
            return
        if job.get("status") != "success":
            self._send_json(409, {"ok": False, "error": "任务尚未完成"})
            return
        result = pop_job_full_result(job_id, consume=consume)
        if not result:
            self._send_json(404, {"ok": False, "error": "任务结果已读取或已被清理，请重新发起任务"})
            return
        self._send_json(200, self._redact_danmaku_fetch_debug(result))

    def _handle_recent_jobs(self, parsed):
        if not self._require_admin():
            return
        params = parse_qs(parsed.query)
        try:
            limit = min(max(1, int(params.get("limit", ["8"])[0])), 20)
        except ValueError:
            limit = 8
        job_type = str(params.get("type", [REFRESH_POPULAR_JOB_TYPE])[0] or "").strip() or None
        self._send_json(200, {"ok": True, "jobs": JOB_MANAGER.recent(limit=limit, job_type=job_type)})

    def _extract_bvid_param(self, parsed):
        params = parse_qs(parsed.query)
        bvid_raw = (params.get("bvid", [""])[0]).strip()
        if not bvid_raw:
            raise ValueError("缺少 bvid 参数")
        return extract_bvid(bvid_raw)

    def _handle_video_info(self, parsed):
        try:
            bvid = self._extract_bvid_param(parsed)
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return

        collector = BilibiliCollector(history_cookie=self._current_bili_cookie_header())
        try:
            video = collector.fetch_video_info(bvid)
            self._send_json(200, {"ok": True, "video": video})
        except BilibiliApiError as exc:
            self._send_json(502, {"ok": False, "error": str(exc)})

    def _handle_background_image(self):
        self._send_json(200, {
            "ok": True,
            "image_url": "/images/dashboard_background_01.png",
            "required_path": "web/images/dashboard_background_01.png",
        })

    def _handle_compare_placeholder(self):
        self._send_json(501, {
            "ok": False,
            "error": "视频对比后端分析接口已预留，当前由前端实时计算图表。",
        })

    def _handle_api_search(self, parsed):
        params = parse_qs(parsed.query)
        try:
            bvid = self._extract_bvid_param(parsed)
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        if not self._check_interval_limit(
            f"bvid-search:{self._rate_owner()}",
            self._search_interval_seconds(),
            "BV 搜索",
        ):
            return

        collector = BilibiliCollector()
        try:
            video_info = collector.fetch_video_info(bvid)
            pages = collector.fetch_page_list(bvid)
            cid_raw = (params.get("cid", [""])[0]).strip()
            if cid_raw:
                cid = int(cid_raw)
                if not any(p["cid"] == cid for p in pages):
                    self._send_json(400, {"ok": False, "error": f"cid {cid} 不属于该视频"})
                    return
            else:
                cid = pages[0]["cid"]
            title = video_info["title"]
            collect_result = collect_video_danmaku_result(
                collector,
                cid,
                bvid=bvid,
                title=title,
                duration=int(video_info.get("duration", 0) or 0),
            )
            rows = collect_result.rows
            if len(rows) > MAX_DANMAKU_ROWS:
                self._send_json(413, {
                    "ok": False,
                    "error": f"该分 P 弹幕数为 {len(rows)}，超过当前 DEMO 上限 {MAX_DANMAKU_ROWS}",
                })
                return
            reported_count = int(video_info.get("danmaku", 0) or 0)
            video = {**video_info, "danmaku": len(rows), "reported_danmaku": reported_count}
            stats = build_search_stats(
                rows,
                int(video_info.get("duration", 0) or 0),
                block_words=self._current_effective_block_words(),
            )
            fetch_meta = self._danmaku_fetch_meta(
                reported_count=reported_count,
                fetched_count=len(rows),
                source=collect_result.source,
                segment_count=collect_result.segment_count,
            )
            payload = {
                "ok": True,
                "video": video,
                "pages": pages,
                "current_cid": cid,
                "danmakus": rows,
                "stats": stats,
                "danmaku_fetch": fetch_meta,
            }
            self._send_json(200, self._redact_danmaku_fetch_debug(payload))
        except BilibiliApiError as exc:
            self._send_json(502, {"ok": False, "error": str(exc)})

    def _search_interval_seconds(self) -> int:
        user = self._current_user()
        if user and is_admin_role(user.get("role")):
            return 0
        if user:
            return normalize_search_interval(user.get("search_interval_seconds"))
        return 10

    def _danmaku_fetch_meta(
        self,
        reported_count: int,
        fetched_count: int,
        source: str,
        segment_count: int = 0,
    ) -> dict[str, Any]:
        return danmaku_fetch_meta(
            reported_count=reported_count,
            fetched_count=fetched_count,
            source=source,
            segment_count=segment_count,
        )

    def _handle_video_danmakus(self, parsed):
        params = parse_qs(parsed.query)
        selected = str(params.get("date", ["current"])[0] or "current").strip() or "current"
        bvid_raw = str(params.get("bvid", [""])[0] or "").strip()
        if not bvid_raw:
            self._send_json(400, {"ok": False, "error": "缺少 bvid 参数"})
            return
        try:
            bvid = extract_bvid(bvid_raw)
            if selected == "current":
                dashboard, _, stats = self._load_current_popular_dashboard()
                base = ROOT / "web" / "data"
                source = "current"
            else:
                base, dashboard, _, stats = self._load_archive_popular_dashboard(selected)
                source = "archive"
            videos = dashboard.get("raw_videos") if isinstance(dashboard.get("raw_videos"), list) else []
            video = next((item for item in videos if str(item.get("bvid") or "") == bvid), None)
            if not video:
                self._send_json(404, {"ok": False, "error": f"{selected} 榜单中未找到 {bvid}"})
                return
            rows, store_meta = read_video_danmakus(base, bvid)
        except FileNotFoundError as exc:
            self._send_json(404, {"ok": False, "error": str(exc)})
            return
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        self._send_json(200, {
            "ok": True,
            "date": selected,
            "source": source,
            "video": video,
            "danmakus": rows,
            "stats": stats.get(bvid),
            "store": store_meta,
        })

    def _archive_dates(self) -> list[str]:
        archive_root = ROOT / "data" / "archive"
        if not archive_root.exists():
            return []
        dates: list[str] = []
        for path in archive_root.iterdir():
            if not path.is_dir():
                continue
            try:
                datetime.strptime(path.name, "%Y-%m-%d")
            except ValueError:
                continue
            has_videos = (path / "today_hot_videos.json").exists()
            has_split_store = (path / DANMAKU_INDEX_FILE).exists() or (path / VIDEO_STATS_FILE).exists()
            has_legacy_store = (path / "today_danmakus.json").exists()
            if has_videos and (has_split_store or has_legacy_store):
                dates.append(path.name)
        return sorted(dates, reverse=True)[:14]

    def _load_current_popular_dashboard(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
        base = ROOT / "web" / "data"
        dashboard = read_json(base / "dashboard.json")
        if not isinstance(dashboard, dict):
            raise ValueError("当前榜单 dashboard.json 格式不正确")
        videos = (
            dashboard.get("raw_videos")
            or dashboard.get("videos")
            or dashboard.get("hot_videos")
            or []
        )
        if not isinstance(videos, list):
            videos = []
        ensure_danmaku_store(
            base,
            videos,
            base / "danmakus.json",
            module="popular_current",
            date=str(dashboard.get("date") or ""),
            stop_words=load_block_words(ROOT / "config" / "stop_words.txt"),
        )
        index = load_danmaku_index(base)
        stats = load_video_stats(base)
        filter_info = dashboard.get("filter") if isinstance(dashboard.get("filter"), dict) else None
        analysis_options = (
            dashboard.get("analysis_options")
            if isinstance(dashboard.get("analysis_options"), dict)
            else None
        )
        payload = build_lightweight_dashboard(
            videos,
            stats,
            filter_info=filter_info,
            analysis_options=analysis_options,
            archive_source={
                "date": str(dashboard.get("date") or ""),
                "video_file": "web/data/dashboard.json",
                "danmaku_index_file": "web/data/danmaku_index.json",
                "video_stats_file": "web/data/video_stats.json",
                "danmaku_store_dir": "web/data/danmakus",
                "legacy_danmaku_file": "web/data/danmakus.json" if (base / "danmakus.json").exists() else "",
                "read_only": False,
            },
        )
        payload["danmaku_store"] = {
            "mode": "split-json",
            "index_file": "web/data/danmaku_index.json",
            "stats_file": "web/data/video_stats.json",
            "read_only": False,
        }
        return payload, index, stats

    def _load_archive_popular_dashboard(self, selected: str) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
        datetime.strptime(selected, "%Y-%m-%d")
        folder = ROOT / "data" / "archive" / selected
        video_file = folder / "today_hot_videos.json"
        danmaku_file = folder / "today_danmakus.json"
        if not video_file.exists():
            raise FileNotFoundError(f"未找到 {selected} 的热门视频归档")
        videos = read_json(video_file)
        if not isinstance(videos, list):
            raise ValueError(f"{selected} 的热门榜单视频归档格式不正确")
        index = ensure_danmaku_store(
            folder,
            videos,
            danmaku_file,
            module="popular_archive",
            date=selected,
            stop_words=load_block_words(ROOT / "config" / "stop_words.txt"),
        )
        stats = load_video_stats(folder)
        dashboard = build_lightweight_dashboard(
            videos,
            stats,
            archive_source={
                "date": selected,
                "video_file": f"data/archive/{selected}/today_hot_videos.json",
                "danmaku_index_file": f"data/archive/{selected}/danmaku_index.json",
                "video_stats_file": f"data/archive/{selected}/video_stats.json",
                "danmaku_store_dir": f"data/archive/{selected}/danmakus",
                "legacy_danmaku_file": f"data/archive/{selected}/today_danmakus.json" if danmaku_file.exists() else "",
                "read_only": True,
            },
        )
        return folder, dashboard, index, stats

    def _handle_popular_dates(self):
        current_dates = {now_beijing().strftime("%Y-%m-%d")}
        try:
            dashboard = read_json(ROOT / "web" / "data" / "dashboard.json")
            current_date = str(dashboard.get("date") or "").strip()
            if current_date:
                current_dates.add(current_date)
        except Exception:
            pass
        dates = [{"value": "current", "label": "今日榜单"}]
        dates.extend({"value": day, "label": day} for day in self._archive_dates() if day not in current_dates)
        self._send_json(200, {"ok": True, "dates": dates})

    def _handle_popular_date(self, parsed):
        params = parse_qs(parsed.query)
        selected = params.get("date", ["current"])[0]
        try:
            if selected == "current":
                dashboard, index, stats = self._load_current_popular_dashboard()
                source = "current"
            else:
                _, dashboard, index, stats = self._load_archive_popular_dashboard(selected)
                source = "archive"
        except FileNotFoundError as exc:
            self._send_json(404, {"ok": False, "error": str(exc)})
            return
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        self._send_json(200, {
            "ok": True,
            "date": selected,
            "source": source,
            "dashboard": dashboard,
            "danmaku_index": index,
            "video_stats": stats,
            "danmakus": [],
        })

    def _handle_deprecated_refresh_popular(self):
        self._send_json(410, {
            "ok": False,
            "error": "该同步刷新接口已停用，请使用 POST /api/jobs/refresh-popular 创建可视化更新任务",
        })

    def _send_json(self, status: int, payload: dict, extra_headers: dict[str, str] | None = None):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if extra_headers:
            for name, value in extra_headers.items():
                self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        # 本地调试时静默请求日志，避免终端编码或重定向问题影响开发服务器。
        return


if __name__ == "__main__":
    ACCOUNT_STORE.ensure_defaults()
    install_admin_default_ai_provider()
    if os.environ.get("STORAGE_AUTO_CLEANUP", "1").strip().lower() not in {"0", "false", "no", "off"}:
        try:
            cleanup_result = auto_cleanup_storage(ROOT)
            if cleanup_result.get("removed"):
                print(
                    f"本地储存自动清理：移除 {cleanup_result['removed']} 项，"
                    f"释放 {cleanup_result['removed_bytes']} 字节"
                )
        except Exception as exc:
            print(f"本地储存自动清理跳过：{exc}")
    PORT = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", "8000"))
    server = LocalThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"服务已启动：http://127.0.0.1:{PORT}/start.html")
    print(f"旧版入口：http://127.0.0.1:{PORT}/index.html")
    print("按 Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
        server.server_close()
