"""采集、清洗、分析和导出数据的流水线。

当前已模块已实现功能：
1. 采集热门视频及其第一分 P 弹幕。
2. 采集单个 BV 号视频的弹幕并完成解析。
3. 把原始、处理后和前端可视化数据写入项目目录。
4. 应用屏蔽词过滤弹幕。
5. 构建前端 ECharts 页面所需的数据结构。
6. 记录屏蔽词过滤结果和分析选项。 --5.27
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
import math
from pathlib import Path
from typing import Any

from src.analyzer import DistributionBucket
from src.collector import BilibiliApiError, BilibiliCollector
from src.danmaku_store import build_lightweight_dashboard, load_video_stats, write_danmaku_store
from src.filter import FilterMode, apply_blocklist
from src.parser import parse_danmaku_seg, parse_danmaku_xml
from src.storage import write_json


@dataclass
class DanmakuCollectResult:
    rows: list[dict[str, Any]]
    source: str
    segment_count: int = 0
    history_enabled: bool = False
    history_auth_required: bool = False
    history_month_count: int = 0
    history_date_count: int = 0
    history_rows_count: int = 0
    history_error: str = ""
    history_error_type: str = ""


def collect_popular_dataset(
    collector: BilibiliCollector,
    limit: int = 50,
    max_workers: int = 4,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """采集热门视频及其第一分 P 弹幕。

    热门列表本身仍串行获取；每个视频的弹幕下载使用有限并发，避免 50 个视频
    串行请求时等待过久。单个视频失败会记录错误并继续处理其他视频。
    """

    def emit(event: dict[str, Any]) -> None:
        if progress_callback:
            progress_callback(event)

    emit({"stage": "fetch_popular_start", "limit": limit})
    videos = collector.fetch_popular_videos(limit=limit)
    emit({"stage": "fetch_popular_done", "limit": limit, "total": len(videos)})
    if not videos:
        return videos, []

    workers = max(1, min(int(max_workers or 1), 8, len(videos)))
    results: list[list[dict[str, Any]]] = [[] for _ in videos]

    def collect_one(index: int, video: dict[str, Any]) -> tuple[int, list[dict[str, Any]], str]:
        worker_collector = BilibiliCollector(timeout=collector.timeout)
        try:
            rows = collect_single_video(
                worker_collector,
                video["bvid"],
                video.get("title", ""),
                duration=int(video.get("duration", 0) or 0),
            )
            return index, rows, ""
        except BilibiliApiError as exc:
            return index, [], str(exc)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(collect_one, index, video)
            for index, video in enumerate(videos)
        ]
        done = 0
        for future in as_completed(futures):
            index, rows, error = future.result()
            done += 1
            results[index] = rows
            if error:
                videos[index] = {**videos[index], "danmaku_fetch_error": error}
            emit({
                "stage": "video_done",
                "done": done,
                "total": len(videos),
                "video": videos[index],
                "rows_count": len(rows),
                "error": error,
            })

    danmakus: list[dict[str, Any]] = []
    for rows in results:
        danmakus.extend(rows)
    emit({"stage": "collect_done", "total": len(videos), "danmaku_count": len(danmakus)})
    return videos, danmakus


def collect_single_video(
    collector: BilibiliCollector,
    bvid: str,
    title: str = "",
    duration: int = 0,
) -> list[dict[str, Any]]:
    """采集单个 BV 号视频的弹幕并完成解析。"""

    cid = collector.fetch_cid(bvid)
    return collect_video_danmaku_rows(collector, cid, bvid=bvid, title=title or bvid, duration=duration)


def collect_video_danmaku_rows(
    collector: BilibiliCollector,
    cid: int,
    bvid: str = "",
    title: str = "",
    duration: int = 0,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """优先使用分段接口采集弹幕，失败时回退旧 XML 接口。"""

    return collect_video_danmaku_result(
        collector,
        cid,
        bvid=bvid,
        title=title,
        duration=duration,
        progress_callback=progress_callback,
    ).rows


def collect_video_danmaku_result(
    collector: BilibiliCollector,
    cid: int,
    bvid: str = "",
    title: str = "",
    duration: int = 0,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    include_history: bool = False,
    pubdate: int = 0,
    history_max_months: int = 180,
    history_max_dates: int = 180,
    max_rows: int = 0,
) -> DanmakuCollectResult:
    """Collect danmaku rows and report which Bilibili endpoint was used."""

    def emit(event: dict[str, Any]) -> None:
        if progress_callback:
            progress_callback(event)

    source = "segment"
    segment_count = 0
    rows: list[dict[str, Any]] = []
    try:
        if hasattr(collector, "fetch_danmaku_segment"):
            segment_seconds = int(getattr(collector, "DANMAKU_SEGMENT_SECONDS", 360) or 360)
            max_segments = max(1, math.ceil(max(0, int(duration or 0)) / segment_seconds))
            for segment_index in range(1, max_segments + 1):
                segment = collector.fetch_danmaku_segment(cid, segment_index)
                rows.extend(parse_danmaku_seg(segment, bvid=bvid, title=title, cid=cid))
                emit({
                    "stage": "danmaku_segment_done",
                    "segment_index": segment_index,
                    "segment_count": max_segments,
                    "rows_count": len(rows),
                })
            segment_count = max_segments
        else:
            segments = collector.fetch_danmaku_segments(cid, duration=duration)
            segment_count = len(segments)
            for segment_index, segment in enumerate(segments, start=1):
                rows.extend(parse_danmaku_seg(segment, bvid=bvid, title=title, cid=cid))
                emit({
                    "stage": "danmaku_segment_done",
                    "segment_index": segment_index,
                    "segment_count": segment_count,
                    "rows_count": len(rows),
                })
    except BilibiliApiError:
        emit({"stage": "danmaku_segment_failed", "cid": cid})
        rows = []
        source = "xml"

    if not rows:
        emit({"stage": "danmaku_xml_start", "cid": cid})
        xml_text = collector.fetch_danmaku_xml(cid)
        rows = parse_danmaku_xml(xml_text, bvid=bvid, title=title, cid=cid)
        source = "xml"
        segment_count = 0
        emit({"stage": "danmaku_xml_done", "cid": cid, "rows_count": len(rows)})

    history_result = _collect_history_danmaku_rows(
        collector,
        cid=cid,
        bvid=bvid,
        title=title,
        pubdate=pubdate,
        enabled=include_history,
        current_rows=rows,
        max_months=history_max_months,
        max_dates=history_max_dates,
        max_rows=max_rows,
        progress_callback=progress_callback,
    )
    if history_result["rows"]:
        rows = _unique_danmaku_rows(rows + history_result["rows"])
        source = "history"
    return DanmakuCollectResult(
        rows=rows,
        source=source,
        segment_count=segment_count,
        history_enabled=include_history,
        history_auth_required=history_result["auth_required"],
        history_month_count=history_result["month_count"],
        history_date_count=history_result["date_count"],
        history_rows_count=history_result["row_count"],
        history_error=history_result["error"],
        history_error_type=history_result["error_type"],
    )


def _collect_history_danmaku_rows(
    collector: BilibiliCollector,
    *,
    cid: int,
    bvid: str,
    title: str,
    pubdate: int,
    enabled: bool,
    current_rows: list[dict[str, Any]],
    max_months: int,
    max_dates: int,
    max_rows: int,
    progress_callback: Callable[[dict[str, Any]], None] | None,
) -> dict[str, Any]:
    """Optionally collect historical danmaku snapshots using Bilibili login cookie."""

    def emit(event: dict[str, Any]) -> None:
        if progress_callback:
            progress_callback(event)

    result = {
        "rows": [],
        "auth_required": False,
        "month_count": 0,
        "date_count": 0,
        "row_count": 0,
        "error": "",
        "error_type": "",
    }
    if not enabled:
        return result
    if not hasattr(collector, "has_history_auth") or not collector.has_history_auth():
        result["auth_required"] = True
        result["error_type"] = "auth_required"
        emit({"stage": "history_auth_required", "message": "历史弹幕补抓需要配置 BILI_SESSDATA 或 BILI_COOKIE"})
        return result

    months = _history_months(pubdate, max_months=max_months)
    dates: list[str] = []
    failed_months: list[dict[str, str]] = []
    emit({"stage": "history_index_start", "month_count": len(months)})
    for index, month in enumerate(months, start=1):
        try:
            month_dates = collector.fetch_history_dates(cid, month)
        except BilibiliApiError as exc:
            error_type = classify_history_error(str(exc), stage="index")
            failed_months.append({"month": month, "message": str(exc), "error_type": error_type})
            result["month_count"] = index
            emit({
                "stage": "history_month_failed",
                "month": month,
                "done": index,
                "total": len(months),
                "message": str(exc),
                "error_type": error_type,
                "date_count": len(dates),
            })
            if error_type in {"auth_required", "cookie_invalid", "risk_control"}:
                result["error"] = str(exc)
                result["error_type"] = error_type
                emit({"stage": "history_index_failed", "message": str(exc), "error_type": error_type})
                return result
            continue

        result["month_count"] = index
        if month_dates:
            dates.extend(month_dates)
        emit({
            "stage": "history_month_done",
            "month": month,
            "done": index,
            "total": len(months),
            "date_count": len(dates),
        })
        if max_dates > 0 and len(dates) >= max_dates:
            dates = dates[:max_dates]
            break

    rows: list[dict[str, Any]] = []
    seen = {_danmaku_key(row) for row in current_rows}
    result["date_count"] = len(dates)
    if not dates:
        if failed_months:
            last_error = failed_months[-1]["message"]
            result["error_type"] = "index_failed"
            result["error"] = (
                f"已尝试 {result['month_count']} 个历史月份，"
                f"{len(failed_months)} 个失败，未找到可用快照；最后错误：{last_error}"
            )
        else:
            result["error_type"] = "index_empty"
    elif failed_months:
        result["error_type"] = "index_partial"
        result["error"] = f"{len(failed_months)} 个历史月份索引读取失败，已继续处理可用快照"
    emit({"stage": "history_fetch_start", "date_count": len(dates)})
    for index, date in enumerate(dates, start=1):
        try:
            data = collector.fetch_history_segment(cid, date)
            parsed = parse_danmaku_seg(data, bvid=bvid, title=title, cid=cid)
        except BilibiliApiError as exc:
            result["error"] = str(exc)
            result["error_type"] = classify_history_error(str(exc), stage="snapshot")
            emit({"stage": "history_date_failed", "date": date, "message": str(exc), "error_type": result["error_type"]})
            continue
        added = 0
        for row in parsed:
            key = _danmaku_key(row)
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
            added += 1
            if max_rows > 0 and len(seen) >= max_rows:
                break
        result["row_count"] = len(rows)
        emit({
            "stage": "history_date_done",
            "date": date,
            "done": index,
            "total": len(dates),
            "added": added,
            "history_rows_count": len(rows),
            "total_rows_count": len(seen),
        })
        if max_rows > 0 and len(seen) >= max_rows:
            result["error_type"] = "row_limit"
            emit({"stage": "history_row_limit", "row_limit": max_rows, "error_type": "row_limit"})
            break
    result["rows"] = rows
    return result


def classify_history_error(message: str, stage: str = "") -> str:
    """Return a stable, user-facing category for historical danmaku failures."""

    text = str(message or "").lower()
    if "bili_sessdata" in text or "bili_cookie" in text:
        return "auth_required"
    if "412" in text or "-412" in text or "风控" in text or "precondition" in text:
        return "risk_control"
    if "cookie" in text or "sessdata" in text or "登录" in text or "鉴权" in text or "权限" in text:
        return "cookie_invalid"
    if "返回异常" in text or "解析" in text or "protobuf" in text:
        return "parse_failed"
    if stage == "index":
        return "index_failed"
    if stage == "snapshot":
        return "snapshot_failed"
    return "unknown"


def _history_months(pubdate: int, max_months: int) -> list[str]:
    """Return months from publish month to current month, capped for DEMO safety."""

    now = datetime.now()
    if pubdate:
        start = datetime.fromtimestamp(int(pubdate))
    else:
        start = datetime(now.year, now.month, 1)
    year, month = start.year, start.month
    months: list[str] = []
    while (year, month) <= (now.year, now.month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            year += 1
            month = 1
    if max_months > 0 and len(months) > max_months:
        return months[-max_months:]
    return months


def _danmaku_key(row: dict[str, Any]) -> tuple:
    return (
        row.get("cid"),
        round(float(row.get("time_in_video") or 0), 3),
        int(float(row.get("send_timestamp") or 0)),
        str(row.get("user_hash") or ""),
        str(row.get("content") or ""),
    )


def _unique_danmaku_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        key = _danmaku_key(row)
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def export_project_data(
    project_root: str | Path,
    videos: list[dict[str, Any]],
    danmakus: list[dict[str, Any]],
    block_words: list[str] | None = None,
    stop_words: list[str] | None = None,
    time_buckets: list[DistributionBucket] | None = None,
    length_buckets: list[DistributionBucket] | None = None,
    filter_mode: FilterMode = "drop",
    case_sensitive: bool = False,
) -> None:
    """把原始、处理后和前端可视化数据写入项目目录。"""

    root = Path(project_root)
    filter_result = apply_blocklist(danmakus, block_words or [], mode=filter_mode)
    filter_info = {
        "enabled": bool(block_words),
        "mode": filter_mode,
        "block_words": block_words or [],
        "removed_count": filter_result.removed_count,
        "masked_count": filter_result.masked_count,
    }
    analysis_options = {
        "stop_words": stop_words or [],
        "time_buckets": time_buckets or [],
        "length_buckets": length_buckets or [],
    }

    write_json(root / "data" / "raw" / "videos.json", videos)
    write_json(root / "data" / "raw" / "danmakus.json", danmakus)
    write_json(root / "data" / "processed" / "block_filter.json", filter_info)
    write_json(root / "data" / "processed" / "danmakus.json", filter_result.danmakus)
    index = write_danmaku_store(
        root / "web" / "data",
        videos,
        filter_result.danmakus,
        module="popular_current",
        date="",
        stop_words=stop_words,
    )
    stats = load_video_stats(root / "web" / "data")
    dashboard = build_lightweight_dashboard(
        videos,
        stats,
        filter_info=filter_info,
        analysis_options=analysis_options,
        archive_source={
            "video_file": "web/data/dashboard.json",
            "danmaku_index_file": "web/data/danmaku_index.json",
            "video_stats_file": "web/data/video_stats.json",
            "danmaku_store_dir": "web/data/danmakus",
            "read_only": False,
        },
    )
    write_json(root / "web" / "data" / "dashboard.json", dashboard)
