"""Apply database/mysql/001_schema.sql to a configured MySQL database."""

from __future__ import annotations

import argparse
from pathlib import Path

from .mysql_config import PROJECT_ROOT, load_mysql_config
from .mysql_connection import load_mysql_connector


DEFAULT_SCHEMA_PATH = PROJECT_ROOT / "database" / "mysql" / "001_schema.sql"


def split_sql_statements(sql_text: str) -> list[str]:
    statements: list[str] = []
    buffer: list[str] = []
    for line in sql_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buffer.append(line)
        if stripped.endswith(";"):
            statement = "\n".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer = []
    tail = "\n".join(buffer).strip()
    if tail:
        statements.append(tail)
    return statements


def apply_schema(config_path: str | None = None, schema_path: str | Path = DEFAULT_SCHEMA_PATH) -> int:
    config = load_mysql_config(config_path)
    statements = split_sql_statements(Path(schema_path).read_text(encoding="utf-8"))
    connector = load_mysql_connector()
    kwargs = config.to_connection_kwargs()
    kwargs.pop("database", None)
    connection = connector.connect(**kwargs)
    try:
        cursor = connection.cursor()
        try:
            for statement in statements:
                cursor.execute(statement)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
    finally:
        connection.close()
    return len(statements)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="执行 MySQL 建库建表脚本。")
    parser.add_argument("--config", help="MySQL 配置文件路径，默认读取 config/mysql.local.json。")
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA_PATH), help="SQL schema 文件路径。")
    args = parser.parse_args(argv)

    count = apply_schema(args.config, args.schema)
    print(f"MySQL schema 执行完成，共执行 {count} 条 SQL 语句。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
