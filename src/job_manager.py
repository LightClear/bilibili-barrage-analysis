"""轻量内存任务管理器。

当前用于文件模式下的热门榜单更新进度可视化。后续接入 MySQL 后，
这里的任务结构可以迁移到 `jobs` 和 `job_events` 表。
"""

from __future__ import annotations

import threading
import uuid
from copy import deepcopy
from typing import Any

from src.time_utils import now_beijing


TERMINAL_STATUSES = {"success", "failed", "cancelled"}


class JobManager:
    """保存最近一批后台任务和任务事件。"""

    def __init__(self, max_jobs: int = 50, max_events_per_job: int = 80) -> None:
        self.max_jobs = max(1, int(max_jobs))
        self.max_events_per_job = max(1, int(max_events_per_job))
        self._jobs: dict[str, dict[str, Any]] = {}
        self._order: list[str] = []
        self._lock = threading.RLock()

    def create(self, job_type: str, account: str | None = None, message: str = "") -> dict[str, Any]:
        job_id = str(uuid.uuid4())
        created = _now_text()
        job = {
            "job_id": job_id,
            "type": str(job_type or "unknown"),
            "account": account or "",
            "status": "pending",
            "progress": 0,
            "message": message or "任务已创建",
            "created_at": created,
            "started_at": "",
            "finished_at": "",
            "result": {},
            "error": "",
            "events": [],
        }
        with self._lock:
            self._jobs[job_id] = job
            self._order.insert(0, job_id)
            self._prune_locked()
        self.add_event(job_id, message or "任务已创建", progress=0, step_name="created")
        return self.get(job_id) or job

    def start(self, job_id: str, message: str = "任务开始执行") -> dict[str, Any] | None:
        return self.update(job_id, status="running", progress=1, message=message, started_at=_now_text())

    def update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        progress: int | None = None,
        message: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            if status is not None:
                job["status"] = status
            if progress is not None:
                job["progress"] = _clamp_progress(progress)
            if message is not None:
                job["message"] = str(message)
            if result is not None:
                job["result"] = result
            if error is not None:
                job["error"] = str(error)
            if started_at is not None:
                job["started_at"] = started_at
            if finished_at is not None:
                job["finished_at"] = finished_at
            return deepcopy(job)

    def add_event(
        self,
        job_id: str,
        message: str,
        *,
        level: str = "info",
        step_name: str = "",
        progress: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        event = {
            "level": level if level in {"info", "warning", "error"} else "info",
            "step_name": str(step_name or ""),
            "progress": _clamp_progress(progress) if progress is not None else None,
            "message": str(message or ""),
            "detail": detail or {},
            "created_at": _now_text(),
        }
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            job["events"].append(event)
            if len(job["events"]) > self.max_events_per_job:
                job["events"] = job["events"][-self.max_events_per_job:]
            return deepcopy(event)

    def succeed(self, job_id: str, message: str, result: dict[str, Any] | None = None) -> dict[str, Any] | None:
        self.add_event(job_id, message, progress=100, step_name="success")
        return self.update(
            job_id,
            status="success",
            progress=100,
            message=message,
            result=result or {},
            error="",
            finished_at=_now_text(),
        )

    def fail(self, job_id: str, message: str, error: str | None = None) -> dict[str, Any] | None:
        self.add_event(job_id, message, level="error", step_name="failed")
        return self.update(
            job_id,
            status="failed",
            message=message,
            error=error or message,
            finished_at=_now_text(),
        )

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return deepcopy(job) if job else None

    def recent(self, limit: int = 10, job_type: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            jobs = []
            for job_id in self._order:
                job = self._jobs[job_id]
                if job_type and job.get("type") != job_type:
                    continue
                jobs.append(deepcopy(job))
                if len(jobs) >= limit:
                    break
            return jobs

    def latest_running(self, job_type: str) -> dict[str, Any] | None:
        with self._lock:
            for job_id in self._order:
                job = self._jobs[job_id]
                if job.get("type") == job_type and job.get("status") not in TERMINAL_STATUSES:
                    return deepcopy(job)
            return None

    def _prune_locked(self) -> None:
        while len(self._order) > self.max_jobs:
            old_id = self._order.pop()
            self._jobs.pop(old_id, None)


def _now_text() -> str:
    return now_beijing().isoformat(timespec="seconds")


def _clamp_progress(value: int | float | None) -> int:
    try:
        number = int(value if value is not None else 0)
    except (TypeError, ValueError):
        number = 0
    return max(0, min(100, number))
