"""Export selected MySQL data back to file-mode shaped JSON files.

The exporter writes into a new output directory and never overwrites the
running data/accounts.txt or web/data/*.json files.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from src.danmaku_store import write_danmaku_store
from src.storage import write_json, write_text

from .mysql_config import PROJECT_ROOT, load_mysql_config
from .mysql_connection import mysql_connection


def export_mysql_to_files(
    *,
    config_path: str | None = None,
    output_dir: str | Path | None = None,
    include_danmakus: bool = True,
    danmaku_limit: int | None = None,
) -> dict[str, Any]:
    config = load_mysql_config(config_path)
    target = Path(output_dir) if output_dir else _default_output_dir()
    target.mkdir(parents=True, exist_ok=True)

    with mysql_connection(config) as connection:
        cursor = connection.cursor(dictionary=True)
        try:
            users = _fetch_all(cursor, "SELECT * FROM users ORDER BY id")
            videos = _fetch_all(cursor, "SELECT * FROM videos ORDER BY updated_at DESC, id")
            danmakus = (
                _fetch_danmakus(cursor, danmaku_limit)
                if include_danmakus
                else []
            )
            global_words = _fetch_global_words(cursor)
            user_words = _fetch_user_words(cursor)
        finally:
            cursor.close()

    _write_accounts(target / "data" / "accounts.txt", users)
    write_text(target / "config" / "block_words.txt", "\n".join(global_words) + ("\n" if global_words else ""))
    for account, words in user_words.items():
        write_text(target / "data" / "user_block_words" / f"{account}.txt", "\n".join(words) + ("\n" if words else ""))
    dashboard = _build_dashboard(videos, danmakus)
    write_json(target / "web" / "data" / "dashboard.json", dashboard)
    if include_danmakus:
        write_danmaku_store(
            target / "web" / "data",
            dashboard.get("raw_videos") or [],
            [_public_danmaku(row) for row in danmakus],
            module="popular_current",
        )

    return {
        "output_dir": str(target),
        "users": len(users),
        "videos": len(videos),
        "danmakus": len(danmakus),
        "global_block_words": len(global_words),
        "user_block_word_accounts": len(user_words),
        "note": "账号本地访问令牌和模型 API Key 不会被导出明文；api_key 字段已留空。",
    }


def _default_output_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return PROJECT_ROOT / "data" / "mysql_export" / stamp


def _fetch_all(cursor: Any, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cursor.execute(sql, params)
    return list(cursor.fetchall())


def _fetch_danmakus(cursor: Any, limit: int | None) -> list[dict[str, Any]]:
    sql = """
        SELECT d.*, v.title
        FROM danmakus d
        LEFT JOIN videos v ON v.bvid = d.bvid
        ORDER BY d.bvid, d.time_in_video, d.id
    """
    params: tuple[Any, ...] = ()
    if limit:
        sql += " LIMIT %s"
        params = (int(limit),)
    return _fetch_all(cursor, sql, params)


def _fetch_global_words(cursor: Any) -> list[str]:
    rows = _fetch_all(cursor, "SELECT word FROM global_block_words ORDER BY word")
    return [str(row["word"]) for row in rows]


def _fetch_user_words(cursor: Any) -> dict[str, list[str]]:
    rows = _fetch_all(
        cursor,
        """
        SELECT u.account, w.word
        FROM user_block_words w
        JOIN users u ON u.id = w.account_id
        ORDER BY u.account, w.word
        """,
    )
    result: dict[str, list[str]] = {}
    for row in rows:
        result.setdefault(str(row["account"]), []).append(str(row["word"]))
    return result


def _write_accounts(path: Path, users: list[dict[str, Any]]) -> None:
    payload = {
        "users": [
            {
                "account": row.get("account"),
                "username": row.get("username"),
                "password_hash": row.get("password_hash"),
                "email": row.get("email"),
                "role": row.get("role"),
                "gender": row.get("gender") or "未设置",
                "birthday": _date_text(row.get("birthday")),
                "api_enabled": bool(row.get("api_enabled")),
                "api_key": "",
                "search_interval_seconds": int(row.get("search_interval_seconds") or 10),
                "disabled": bool(row.get("disabled")),
                "created_at": _datetime_text(row.get("created_at")),
                "last_login_at": _datetime_text(row.get("last_login_at")),
            }
            for row in users
        ],
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    write_json(path, payload)


def _build_dashboard(videos: list[dict[str, Any]], danmakus: list[dict[str, Any]]) -> dict[str, Any]:
    public_videos = [_public_video(row, index) for index, row in enumerate(videos, start=1)]
    return {
        "summary": {
            "danmaku_count": len(danmakus),
            "total_view": sum(int(row.get("view_count") or 0) for row in videos),
            "total_like": sum(int(row.get("like_count") or 0) for row in videos),
        },
        "raw_videos": public_videos,
        "videos": public_videos,
        "time_distribution": [],
        "length_distribution": [],
        "keywords": [],
        "source": "mysql_export",
    }


def _public_video(row: dict[str, Any], rank: int) -> dict[str, Any]:
    return {
        "rank": rank,
        "bvid": row.get("bvid"),
        "title": row.get("title"),
        "owner": row.get("owner") or "",
        "desc": row.get("description") or "",
        "cover": row.get("cover_url") or "",
        "view": int(row.get("view_count") or 0),
        "like": int(row.get("like_count") or 0),
        "favorite": int(row.get("favorite_count") or 0),
        "coin": int(row.get("coin_count") or 0),
        "duration": int(row.get("duration_seconds") or 0),
        "danmaku_count": int(row.get("danmaku_count") or 0),
    }


def _public_danmaku(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "bvid": row.get("bvid"),
        "cid": row.get("cid"),
        "title": row.get("title") or "",
        "time_in_video": float(row.get("time_in_video") or 0),
        "send_timestamp": row.get("send_timestamp"),
        "user_hash": row.get("user_hash") or "",
        "color": row.get("color"),
        "content": row.get("content") or "",
    }


def _date_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    return str(value)[:10]


def _datetime_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat(timespec="seconds")
    return str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从 MySQL 导出文件模式数据到新目录。")
    parser.add_argument("--config", help="MySQL 配置文件路径，默认读取 config/mysql.local.json。")
    parser.add_argument("--output-dir", help="输出目录；默认 data/mysql_export/时间戳。")
    parser.add_argument("--skip-danmakus", action="store_true", help="不导出弹幕明细。")
    parser.add_argument("--danmaku-limit", type=int, help="最多导出多少条弹幕。")
    args = parser.parse_args(argv)

    report = export_mysql_to_files(
        config_path=args.config,
        output_dir=args.output_dir,
        include_danmakus=not args.skip_danmakus,
        danmaku_limit=args.danmaku_limit,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
