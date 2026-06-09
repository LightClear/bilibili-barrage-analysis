"""File-mode to MySQL migration helpers.

The default path is conservative: build a dry-run plan first, then write only
when the CLI is called with --apply.  API keys are never printed in reports.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from src.danmaku_store import read_all_danmakus
from src.storage import read_json

from .mysql_config import MySQLConfig
from .mysql_connection import mysql_transaction


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MAX_DANMAKUS = 2_000_000
BATCH_SIZE = 1000


@dataclass(frozen=True)
class Dataset:
    label: str
    snapshot_date: date
    videos_path: Path
    danmakus_path: Path
    videos: list[dict[str, Any]]
    danmakus: list[dict[str, Any]]


def build_file_migration_plan(
    root: str | Path = PROJECT_ROOT,
    *,
    include_archives: bool = False,
    include_danmakus: bool = True,
    max_danmakus: int = DEFAULT_MAX_DANMAKUS,
) -> dict[str, Any]:
    root_path = Path(root)
    accounts = _load_accounts(root_path)
    datasets = _load_datasets(root_path, include_archives=include_archives)
    total_videos = sum(len(dataset.videos) for dataset in datasets)
    total_danmakus = sum(len(dataset.danmakus) for dataset in datasets) if include_danmakus else 0
    provider_count = _provider_count(root_path)
    user_block_word_files = list((root_path / "data" / "user_block_words").glob("*.txt"))
    global_block_words = _load_word_file(root_path / "config" / "block_words.txt")

    warnings: list[str] = []
    if include_danmakus and total_danmakus > max_danmakus:
        warnings.append(
            f"弹幕数量 {total_danmakus} 超过当前上限 {max_danmakus}，正式导入会被拒绝；"
            "可调高 --max-danmakus 或先分批导入。"
        )
    if not (root_path / "config" / "mysql.local.json").exists():
        warnings.append("未检测到 config/mysql.local.json；dry-run 不受影响，正式导入前需要先配置 MySQL。")

    return {
        "mode": "dry-run",
        "root": str(root_path),
        "accounts": {
            "count": len(accounts),
            "roles": dict(Counter(str(user.get("role") or "normal") for user in accounts)),
            "api_enabled": sum(1 for user in accounts if bool(user.get("api_enabled"))),
        },
        "block_words": {
            "global_count": len(global_block_words),
            "user_file_count": len(user_block_word_files),
        },
        "ai_provider_configs": {
            "count": provider_count,
            "note": "只统计账号级配置数量，不输出或解密 API Key。",
        },
        "datasets": [
            {
                "label": dataset.label,
                "snapshot_date": dataset.snapshot_date.isoformat(),
                "video_count": len(dataset.videos),
                "danmaku_count": len(dataset.danmakus) if include_danmakus else 0,
                "videos_path": str(dataset.videos_path),
                "danmakus_path": str(dataset.danmakus_path),
            }
            for dataset in datasets
        ],
        "totals": {
            "video_rows": total_videos,
            "danmaku_rows": total_danmakus,
            "include_archives": include_archives,
            "include_danmakus": include_danmakus,
            "max_danmakus": max_danmakus,
        },
        "warnings": warnings,
    }


def apply_file_migration(
    config: MySQLConfig,
    root: str | Path = PROJECT_ROOT,
    *,
    include_archives: bool = False,
    include_danmakus: bool = True,
    max_danmakus: int = DEFAULT_MAX_DANMAKUS,
) -> dict[str, Any]:
    root_path = Path(root)
    plan = build_file_migration_plan(
        root_path,
        include_archives=include_archives,
        include_danmakus=include_danmakus,
        max_danmakus=max_danmakus,
    )
    if include_danmakus and plan["totals"]["danmaku_rows"] > max_danmakus:
        raise ValueError("弹幕数量超过导入上限，请先 dry-run 检查并调整 --max-danmakus。")

    datasets = _load_datasets(root_path, include_archives=include_archives)
    counters: Counter[str] = Counter()
    warnings: list[str] = list(plan["warnings"])

    with mysql_transaction(config) as connection:
        cursor = connection.cursor()
        try:
            account_ids = _upsert_accounts(cursor, _load_accounts(root_path), counters)
            _upsert_block_words(cursor, root_path, account_ids, counters)
            _upsert_ai_providers(cursor, root_path, account_ids, counters)
            for dataset in datasets:
                video_map = _upsert_dataset_videos(cursor, dataset, counters)
                if include_danmakus:
                    skipped = _upsert_dataset_danmakus(cursor, dataset, video_map, counters)
                    if skipped:
                        warnings.append(f"{dataset.label} 有 {skipped} 条弹幕无法匹配 BVID，已跳过。")
        finally:
            cursor.close()

    return {
        "mode": "apply",
        "root": str(root_path),
        "counters": dict(counters),
        "warnings": warnings,
    }


def _load_accounts(root: Path) -> list[dict[str, Any]]:
    path = root / "data" / "accounts.txt"
    if not path.exists():
        return []
    data = read_json(path)
    users = data.get("users") if isinstance(data, dict) else []
    return [user for user in users if isinstance(user, dict)]


def _provider_count(root: Path) -> int:
    path = root / "data" / "secure" / "api_providers.json"
    if not path.exists():
        return 0
    data = read_json(path)
    providers = data.get("providers") if isinstance(data, dict) else {}
    return len(providers) if isinstance(providers, dict) else 0


def _load_datasets(root: Path, *, include_archives: bool) -> list[Dataset]:
    datasets: list[Dataset] = []
    current_dashboard = root / "web" / "data" / "dashboard.json"
    current_danmakus = root / "web" / "data" / "danmakus.json"
    if current_dashboard.exists():
        datasets.append(
            _load_dataset(
                "current",
                date.today(),
                current_dashboard,
                current_danmakus,
            )
        )

    if include_archives:
        archive_root = root / "data" / "archive"
        if archive_root.exists():
            for folder in sorted(path for path in archive_root.iterdir() if path.is_dir()):
                try:
                    snapshot_date = date.fromisoformat(folder.name)
                except ValueError:
                    continue
                videos_path = folder / "today_hot_videos.json"
                danmakus_path = folder / "today_danmakus.json"
                if videos_path.exists():
                    datasets.append(
                        _load_dataset(
                            f"archive:{folder.name}",
                            snapshot_date,
                            videos_path,
                            danmakus_path,
                        )
                    )
    return datasets


def _load_dataset(label: str, snapshot_date: date, videos_path: Path, danmakus_path: Path) -> Dataset:
    raw_videos = read_json(videos_path)
    if isinstance(raw_videos, dict):
        videos = (
            raw_videos.get("videos")
            or raw_videos.get("hot_videos")
            or raw_videos.get("raw_videos")
            or []
        )
    elif isinstance(raw_videos, list):
        videos = raw_videos
    else:
        videos = []

    raw_danmakus = read_all_danmakus(danmakus_path.parent, danmakus_path)
    if not isinstance(raw_danmakus, list):
        raw_danmakus = []

    return Dataset(
        label=label,
        snapshot_date=snapshot_date,
        videos_path=videos_path,
        danmakus_path=danmakus_path,
        videos=[row for row in videos if isinstance(row, dict)],
        danmakus=[row for row in raw_danmakus if isinstance(row, dict)],
    )


def _upsert_accounts(cursor: Any, users: list[dict[str, Any]], counters: Counter[str]) -> dict[str, int]:
    for user in users:
        account = _text(user.get("account"), 32)
        if not account:
            continue
        api_key = str(user.get("api_key") or "")
        cursor.execute(
            """
            INSERT INTO users (
              account, username, password_hash, email, role, gender, birthday,
              api_enabled, app_api_key_hash, app_api_key_last4,
              search_interval_seconds, disabled, created_at, last_login_at
            ) VALUES (
              %s, %s, %s, %s, %s, %s, %s,
              %s, %s, %s,
              %s, %s, %s, %s
            )
            ON DUPLICATE KEY UPDATE
              username=VALUES(username),
              password_hash=VALUES(password_hash),
              email=VALUES(email),
              role=VALUES(role),
              gender=VALUES(gender),
              birthday=VALUES(birthday),
              api_enabled=VALUES(api_enabled),
              app_api_key_hash=VALUES(app_api_key_hash),
              app_api_key_last4=VALUES(app_api_key_last4),
              search_interval_seconds=VALUES(search_interval_seconds),
              disabled=VALUES(disabled),
              last_login_at=VALUES(last_login_at)
            """,
            (
                account,
                _text(user.get("username"), 64) or account,
                str(user.get("password_hash") or ""),
                _text(user.get("email"), 255) or f"{account}@example.invalid",
                _normalize_role(user.get("role")),
                _text(user.get("gender"), 16) or "未设置",
                _parse_date(user.get("birthday")),
                bool(user.get("api_enabled")),
                _sha256_or_none(api_key),
                api_key[-8:] if api_key else None,
                _int(user.get("search_interval_seconds"), default=10),
                bool(user.get("disabled")),
                _parse_datetime(user.get("created_at")) or datetime.now(),
                _parse_datetime(user.get("last_login_at")),
            ),
        )
        counters["users"] += 1

    if not users:
        return {}

    accounts = [_text(user.get("account"), 32) for user in users if _text(user.get("account"), 32)]
    placeholders = ",".join(["%s"] * len(accounts))
    cursor.execute(f"SELECT id, account FROM users WHERE account IN ({placeholders})", accounts)
    return {str(account): int(user_id) for user_id, account in cursor.fetchall()}


def _upsert_block_words(
    cursor: Any,
    root: Path,
    account_ids: dict[str, int],
    counters: Counter[str],
) -> None:
    global_words = _load_word_file(root / "config" / "block_words.txt")
    for word in global_words:
        cursor.execute(
            "INSERT IGNORE INTO global_block_words (word, created_by) VALUES (%s, NULL)",
            (_text(word, 128),),
        )
        counters["global_block_words"] += 1

    user_dir = root / "data" / "user_block_words"
    if not user_dir.exists():
        return
    for path in sorted(user_dir.glob("*.txt")):
        account = path.stem
        account_id = account_ids.get(account)
        if not account_id:
            counters["user_block_word_files_skipped"] += 1
            continue
        for word in _load_word_file(path):
            cursor.execute(
                "INSERT IGNORE INTO user_block_words (account_id, word) VALUES (%s, %s)",
                (account_id, _text(word, 128)),
            )
            counters["user_block_words"] += 1


def _upsert_ai_providers(
    cursor: Any,
    root: Path,
    account_ids: dict[str, int],
    counters: Counter[str],
) -> None:
    path = root / "data" / "secure" / "api_providers.json"
    if not path.exists():
        return
    data = read_json(path)
    providers = data.get("providers") if isinstance(data, dict) else {}
    if not isinstance(providers, dict):
        return
    for account, record in providers.items():
        if not isinstance(record, dict):
            continue
        account_id = account_ids.get(str(account))
        if not account_id:
            counters["ai_provider_configs_skipped"] += 1
            continue
        encrypted_key = record.get("api_key")
        if not isinstance(encrypted_key, dict):
            counters["ai_provider_configs_skipped"] += 1
            continue
        cipher_json = json.dumps(encrypted_key, ensure_ascii=False, sort_keys=True)
        cursor.execute(
            """
            INSERT INTO ai_provider_configs (
              account_id, provider, base_url, model, api_key_cipher_json,
              api_key_fingerprint, enabled
            ) VALUES (%s, %s, %s, %s, %s, %s, TRUE)
            ON DUPLICATE KEY UPDATE
              provider=VALUES(provider),
              base_url=VALUES(base_url),
              model=VALUES(model),
              api_key_cipher_json=VALUES(api_key_cipher_json),
              api_key_fingerprint=VALUES(api_key_fingerprint),
              enabled=TRUE
            """,
            (
                account_id,
                _text(record.get("provider"), 32) or "custom",
                _text(record.get("base_url"), 512),
                _text(record.get("model"), 128),
                cipher_json,
                _sha256_or_none(cipher_json),
            ),
        )
        counters["ai_provider_configs"] += 1


def _upsert_dataset_videos(
    cursor: Any,
    dataset: Dataset,
    counters: Counter[str],
) -> dict[str, str]:
    title_to_bvid: dict[str, str] = {}
    cid_to_bvid: dict[str, str] = {}
    cursor.execute("DELETE FROM popular_snapshots WHERE snapshot_date=%s", (dataset.snapshot_date,))
    for index, row in enumerate(dataset.videos, start=1):
        video = _normalize_video(row)
        if not video["bvid"]:
            counters["videos_skipped"] += 1
            continue
        cursor.execute(
            """
            INSERT INTO videos (
              bvid, aid, title, owner, cover_url, description,
              view_count, like_count, favorite_count, coin_count,
              danmaku_count, duration_seconds, pubdate
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
              aid=VALUES(aid),
              title=VALUES(title),
              owner=VALUES(owner),
              cover_url=VALUES(cover_url),
              description=VALUES(description),
              view_count=VALUES(view_count),
              like_count=VALUES(like_count),
              favorite_count=VALUES(favorite_count),
              coin_count=VALUES(coin_count),
              danmaku_count=GREATEST(danmaku_count, VALUES(danmaku_count)),
              duration_seconds=VALUES(duration_seconds),
              pubdate=VALUES(pubdate)
            """,
            (
                video["bvid"],
                video["aid"],
                video["title"],
                video["owner"],
                video["cover_url"],
                video["description"],
                video["view_count"],
                video["like_count"],
                video["favorite_count"],
                video["coin_count"],
                video["danmaku_count"],
                video["duration_seconds"],
                video["pubdate"],
            ),
        )
        cursor.execute(
            """
            INSERT INTO popular_snapshots (snapshot_date, rank_position, bvid, score)
            VALUES (%s, %s, %s, %s)
            """,
            (
                dataset.snapshot_date,
                _int(row.get("rank") or row.get("rank_position"), default=index),
                video["bvid"],
                video["view_count"],
            ),
        )
        title_to_bvid[video["title"]] = video["bvid"]
        for page in row.get("pages") or []:
            if isinstance(page, dict):
                cid = _int(page.get("cid"))
                if cid:
                    cid_to_bvid[str(cid)] = video["bvid"]
                    _upsert_video_page(cursor, video["bvid"], page, video["title"])
        counters["videos"] += 1
        counters["popular_snapshots"] += 1
    return {**title_to_bvid, **{f"cid:{cid}": bvid for cid, bvid in cid_to_bvid.items()}}


def _upsert_dataset_danmakus(
    cursor: Any,
    dataset: Dataset,
    video_map: dict[str, str],
    counters: Counter[str],
) -> int:
    skipped = 0
    batch: list[tuple[Any, ...]] = []
    page_seen: set[tuple[str, int]] = set()
    for row in dataset.danmakus:
        bvid = _resolve_danmaku_bvid(row, video_map)
        if not bvid:
            skipped += 1
            continue
        cid = _int(row.get("cid"))
        if cid and (bvid, cid) not in page_seen:
            _upsert_video_page(
                cursor,
                bvid,
                {"cid": cid, "page": 1, "part": row.get("title") or ""},
                str(row.get("title") or ""),
            )
            page_seen.add((bvid, cid))
        danmaku = _normalize_danmaku(row, bvid)
        if not danmaku:
            skipped += 1
            continue
        batch.append(danmaku)
        if len(batch) >= BATCH_SIZE:
            _insert_danmaku_batch(cursor, batch)
            counters["danmakus"] += len(batch)
            batch.clear()
    if batch:
        _insert_danmaku_batch(cursor, batch)
        counters["danmakus"] += len(batch)
    return skipped


def _insert_danmaku_batch(cursor: Any, batch: list[tuple[Any, ...]]) -> None:
    cursor.executemany(
        """
        INSERT IGNORE INTO danmakus (
          bvid, cid, time_in_video, send_timestamp, user_hash,
          content, content_hash, color
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        batch,
    )


def _upsert_video_page(cursor: Any, bvid: str, page: dict[str, Any], fallback_title: str) -> None:
    cid = _int(page.get("cid"))
    if not cid:
        return
    cursor.execute(
        """
        INSERT INTO video_pages (bvid, cid, page_index, part_title, duration_seconds)
        VALUES (%s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
          page_index=VALUES(page_index),
          part_title=VALUES(part_title),
          duration_seconds=GREATEST(duration_seconds, VALUES(duration_seconds))
        """,
        (
            bvid,
            cid,
            _int(page.get("page") or page.get("page_index"), default=1),
            _text(page.get("part") or page.get("part_title") or fallback_title, 512),
            _int(page.get("duration") or page.get("duration_seconds")),
        ),
    )


def _normalize_video(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "bvid": _text(row.get("bvid") or row.get("bv"), 32),
        "aid": _int(row.get("aid")),
        "title": _text(row.get("title"), 512) or "未命名视频",
        "owner": _text(row.get("owner") or row.get("author") or row.get("up"), 128),
        "cover_url": _text(row.get("cover_url") or row.get("cover") or row.get("pic"), 1024),
        "description": _text(row.get("description") or row.get("desc"), 20000),
        "view_count": _int(row.get("view_count") or row.get("view") or row.get("play")),
        "like_count": _int(row.get("like_count") or row.get("like")),
        "favorite_count": _int(row.get("favorite_count") or row.get("favorite")),
        "coin_count": _int(row.get("coin_count") or row.get("coin")),
        "danmaku_count": _int(row.get("danmaku_count") or row.get("danmaku")),
        "duration_seconds": _int(row.get("duration_seconds") or row.get("duration")),
        "pubdate": _parse_datetime(row.get("pubdate")),
    }


def _normalize_danmaku(row: dict[str, Any], bvid: str) -> tuple[Any, ...] | None:
    content = _text(row.get("content") or row.get("text"), 1000)
    if not content:
        return None
    return (
        bvid,
        _int(row.get("cid")),
        float(row.get("time_in_video") or row.get("time") or row.get("progress") or 0),
        _int_or_none(row.get("send_timestamp") or row.get("timestamp") or row.get("date")),
        _text(row.get("user_hash"), 128),
        content,
        hashlib.sha256(content.encode("utf-8")).hexdigest(),
        _int_or_none(row.get("color")),
    )


def _resolve_danmaku_bvid(row: dict[str, Any], video_map: dict[str, str]) -> str:
    direct = _text(row.get("bvid"), 32)
    if direct:
        return direct
    cid = _int(row.get("cid"))
    if cid:
        found = video_map.get(f"cid:{cid}")
        if found:
            return found
    title = str(row.get("title") or "")
    return video_map.get(title, "")


def _load_word_file(path: Path) -> list[str]:
    if not path.exists():
        return []
    words: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        word = line.strip()
        if word and not word.startswith("#"):
            words.append(word)
    return words


def _text(value: Any, max_length: int) -> str:
    text = str(value or "").strip()
    return text[:max_length]


def _int(value: Any, default: int = 0) -> int:
    number = _int_or_none(value)
    return default if number is None else number


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _normalize_role(value: Any) -> str:
    role = str(value or "normal").strip().lower()
    return role if role in {"normal", "admin", "owner"} else "normal"


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value)
        except (OSError, ValueError):
            return None
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=None)


def _sha256_or_none(value: str) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def chunked(items: Iterable[Any], size: int) -> Iterable[list[Any]]:
    batch: list[Any] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch
