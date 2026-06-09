"""Migrate current file-mode data into MySQL.

Default is dry-run.  Use --apply only after checking the report.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .mysql_config import PROJECT_ROOT, load_mysql_config
from .mysql_migration import (
    DEFAULT_MAX_DANMAKUS,
    apply_file_migration,
    build_file_migration_plan,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从文件模式导入数据到 MySQL。")
    parser.add_argument("--config", help="MySQL 配置文件路径，默认读取 config/mysql.local.json。")
    parser.add_argument("--root", default=str(PROJECT_ROOT), help="项目根目录。")
    parser.add_argument("--apply", action="store_true", help="真正写入 MySQL；默认只 dry-run。")
    parser.add_argument("--include-archives", action="store_true", help="同时导入 data/archive 历史归档。")
    parser.add_argument("--skip-danmakus", action="store_true", help="只导入账号、配置、视频和榜单，不导入弹幕明细。")
    parser.add_argument("--max-danmakus", type=int, default=DEFAULT_MAX_DANMAKUS, help="导入弹幕上限，默认 2000000。")
    args = parser.parse_args(argv)

    root = Path(args.root)
    include_danmakus = not args.skip_danmakus

    if not args.apply:
        report = build_file_migration_plan(
            root,
            include_archives=args.include_archives,
            include_danmakus=include_danmakus,
            max_danmakus=args.max_danmakus,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    config = load_mysql_config(args.config)
    report = apply_file_migration(
        config,
        root,
        include_archives=args.include_archives,
        include_danmakus=include_danmakus,
        max_danmakus=args.max_danmakus,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

