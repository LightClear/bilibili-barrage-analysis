"""MySQL connection helpers.

The main server does not import this module during normal file-mode startup.
All imports of mysql.connector are delayed so missing MySQL dependencies do not
break the stable DEMO runtime.
"""

from __future__ import annotations

from contextlib import contextmanager
import importlib
from typing import Any, Iterator

from .mysql_config import MySQLConfig


class MySQLDriverMissingError(RuntimeError):
    """Raised when mysql-connector-python is not installed."""


def load_mysql_connector() -> Any:
    try:
        return importlib.import_module("mysql.connector")
    except ImportError as exc:
        raise MySQLDriverMissingError(
            "缺少 MySQL Python 驱动，请先执行：python -m pip install mysql-connector-python"
        ) from exc


def connect_mysql(config: MySQLConfig) -> Any:
    connector = load_mysql_connector()
    return connector.connect(**config.to_connection_kwargs())


@contextmanager
def mysql_connection(config: MySQLConfig) -> Iterator[Any]:
    connection = connect_mysql(config)
    try:
        yield connection
    finally:
        connection.close()


@contextmanager
def mysql_transaction(config: MySQLConfig) -> Iterator[Any]:
    connection = connect_mysql(config)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def close_cursor(cursor: Any) -> None:
    try:
        cursor.close()
    except Exception:
        pass

