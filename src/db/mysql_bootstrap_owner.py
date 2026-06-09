"""Create or update an owner account directly in MySQL.

This module is intentionally a local command-line tool.  It should not be
exposed through the browser or normal HTTP APIs.
"""

from __future__ import annotations

import argparse
from datetime import datetime

from src.account_demo import (
    hash_password,
    validate_account,
    validate_email,
    validate_password,
    validate_username,
)

from .mysql_config import load_mysql_config
from .mysql_connection import mysql_transaction


def bootstrap_owner(
    *,
    account: str,
    username: str,
    email: str,
    password: str,
    config_path: str | None = None,
    replace: bool = False,
) -> dict[str, str]:
    account = validate_account(account)
    username = validate_username(username)
    email = validate_email(email)
    password_hash = hash_password(validate_password(password))
    config = load_mysql_config(config_path)

    with mysql_transaction(config) as connection:
        cursor = connection.cursor()
        try:
            cursor.execute("SELECT id, role FROM users WHERE account=%s", (account,))
            existing = cursor.fetchone()
            if existing and not replace:
                raise ValueError("账号已存在。若确认要更新为 owner，请添加 --replace。")

            if existing:
                cursor.execute(
                    """
                    UPDATE users
                    SET username=%s, email=%s, password_hash=%s, role='owner',
                        disabled=FALSE, updated_at=CURRENT_TIMESTAMP
                    WHERE account=%s
                    """,
                    (username, email, password_hash, account),
                )
                action = "updated"
            else:
                cursor.execute(
                    """
                    INSERT INTO users (
                      account, username, password_hash, email, role, gender,
                      birthday, api_enabled, search_interval_seconds,
                      disabled, created_at
                    ) VALUES (%s, %s, %s, %s, 'owner', '未设置', NULL, FALSE, 10, FALSE, %s)
                    """,
                    (account, username, password_hash, email, datetime.now()),
                )
                action = "created"
        finally:
            cursor.close()

    return {"account": account, "role": "owner", "action": action}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="在 MySQL 中创建服务器本地 owner 账号。")
    parser.add_argument("--config", help="MySQL 配置文件路径，默认读取 config/mysql.local.json。")
    parser.add_argument("--account", required=True, help="owner 账号，6-20 位字母、数字或下划线。")
    parser.add_argument("--username", required=True, help="owner 用户名，2-16 个字符。")
    parser.add_argument("--email", required=True, help="owner 邮箱。")
    parser.add_argument("--password", required=True, help="owner 密码，8-32 位且包含字母和数字。")
    parser.add_argument("--replace", action="store_true", help="账号已存在时更新其密码、邮箱和 owner 角色。")
    args = parser.parse_args(argv)

    result = bootstrap_owner(
        account=args.account,
        username=args.username,
        email=args.email,
        password=args.password,
        config_path=args.config,
        replace=args.replace,
    )
    print(f"MySQL owner 账号{result['action']}：{result['account']}。密码不会输出。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

