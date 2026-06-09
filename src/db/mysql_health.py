"""MySQL 连接健康检查。

运行方式：
    python -m src.db.mysql_health

该检查只执行 SELECT 1，不创建、不修改任何业务数据。
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from .mysql_config import MySQLConfig, load_mysql_config
from .mysql_connection import MySQLDriverMissingError, connect_mysql


def check_mysql_connection(config: MySQLConfig) -> dict[str, Any]:
    try:
        connection = connect_mysql(config)
    except MySQLDriverMissingError:
        return {
            "ok": False,
            "status": "driver_missing",
            "message": "缺少 MySQL Python 驱动，请先安装 mysql-connector-python。",
            "config": config.public_dict(),
        }

    cursor = None
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT 1")
        row = cursor.fetchone()
        return {
            "ok": bool(row and row[0] == 1),
            "status": "ok",
            "message": "MySQL 连接正常。",
            "config": config.public_dict(),
        }
    except Exception as exc:  # pragma: no cover - depends on local MySQL state.
        return {
            "ok": False,
            "status": "connection_failed",
            "message": f"MySQL 连接失败：{exc}",
            "config": config.public_dict(),
        }
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查本地 MySQL 配置和连接。")
    parser.add_argument("--config", help="指定 MySQL 配置文件路径，默认读取 config/mysql.local.json。")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出检查结果。")
    args = parser.parse_args(argv)

    try:
        config = load_mysql_config(args.config)
        result = check_mysql_connection(config)
    except Exception as exc:
        result = {
            "ok": False,
            "status": "config_error",
            "message": str(exc),
        }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["message"])
        if "config" in result:
            print("配置摘要：" + json.dumps(result["config"], ensure_ascii=False))
        if result.get("status") == "driver_missing":
            print("安装命令：python -m pip install mysql-connector-python")

    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
