"""读取和校验本地 MySQL 配置。

这个模块只负责配置解析，不会主动连接数据库。真实密码只能放在
config/mysql.local.json 或环境变量指向的文件中，不要写进代码。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "mysql.local.json"
EXAMPLE_CONFIG_PATH = PROJECT_ROOT / "config" / "mysql.example.json"
CONFIG_ENV_NAMES = ("DANMAKU_MYSQL_CONFIG", "BILI_MYSQL_CONFIG")


class MySQLConfigError(ValueError):
    """Raised when the MySQL config file exists but is not usable."""


@dataclass(frozen=True)
class MySQLConfig:
    host: str
    port: int
    database: str
    user: str
    password: str
    charset: str = "utf8mb4"
    connect_timeout: int = 10

    def to_connection_kwargs(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "user": self.user,
            "password": self.password,
            "charset": self.charset,
            "connection_timeout": self.connect_timeout,
        }

    def public_dict(self) -> dict[str, Any]:
        """Return a log-safe config view without leaking the password."""
        return {
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "user": self.user,
            "password_set": bool(self.password),
            "charset": self.charset,
            "connect_timeout": self.connect_timeout,
        }


def resolve_mysql_config_path(
    path: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Path:
    if path:
        return Path(path)

    source = os.environ if env is None else env
    for name in CONFIG_ENV_NAMES:
        value = str(source.get(name) or "").strip()
        if value:
            return Path(value)

    return DEFAULT_CONFIG_PATH


def load_mysql_config(
    path: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> MySQLConfig:
    config_path = resolve_mysql_config_path(path, env)
    if not config_path.exists():
        raise FileNotFoundError(
            f"未找到 MySQL 配置文件：{config_path}。请复制 "
            f"{EXAMPLE_CONFIG_PATH} 为 config/mysql.local.json 后填写本地密码。"
        )

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MySQLConfigError(f"MySQL 配置不是合法 JSON：{exc}") from exc

    if not isinstance(data, dict):
        raise MySQLConfigError("MySQL 配置根节点必须是 JSON 对象。")

    return MySQLConfig(
        host=_required_text(data, "host"),
        port=_coerce_int(data.get("port", 3306), "port", minimum=1, maximum=65535),
        database=_required_text(data, "database"),
        user=_required_text(data, "user"),
        password=_required_text(data, "password"),
        charset=_optional_text(data, "charset", "utf8mb4"),
        connect_timeout=_coerce_int(
            data.get("connect_timeout", 10),
            "connect_timeout",
            minimum=1,
            maximum=120,
        ),
    )


def _required_text(data: Mapping[str, Any], key: str) -> str:
    value = str(data.get(key) or "").strip()
    if not value:
        raise MySQLConfigError(f"MySQL 配置缺少必填字段：{key}")
    return value


def _optional_text(data: Mapping[str, Any], key: str, default: str) -> str:
    value = str(data.get(key) or "").strip()
    return value or default


def _coerce_int(
    value: Any,
    key: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise MySQLConfigError(f"MySQL 配置字段 {key} 必须是整数。") from exc
    if number < minimum or number > maximum:
        raise MySQLConfigError(f"MySQL 配置字段 {key} 必须在 {minimum}-{maximum} 之间。")
    return number

