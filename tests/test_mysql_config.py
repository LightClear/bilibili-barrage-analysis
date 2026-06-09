import json

import pytest

from src.db.mysql_config import (
    DEFAULT_CONFIG_PATH,
    MySQLConfigError,
    load_mysql_config,
    resolve_mysql_config_path,
)


def write_config(path, **overrides):
    data = {
        "host": "127.0.0.1",
        "port": 3306,
        "database": "danmaku_dashboard",
        "user": "danmaku_app",
        "password": "local-password",
        "charset": "utf8mb4",
        "connect_timeout": 10,
    }
    data.update(overrides)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_load_mysql_config_from_file(tmp_path):
    config_path = tmp_path / "mysql.local.json"
    write_config(config_path, port="3307", connect_timeout="15")

    config = load_mysql_config(config_path)

    assert config.host == "127.0.0.1"
    assert config.port == 3307
    assert config.database == "danmaku_dashboard"
    assert config.to_connection_kwargs()["connection_timeout"] == 15


def test_public_mysql_config_hides_password(tmp_path):
    config_path = tmp_path / "mysql.local.json"
    write_config(config_path, password="secret-value")

    public = load_mysql_config(config_path).public_dict()

    assert public["password_set"] is True
    assert "secret-value" not in json.dumps(public, ensure_ascii=False)


def test_resolve_mysql_config_path_prefers_env(tmp_path):
    config_path = tmp_path / "custom.json"

    resolved = resolve_mysql_config_path(env={"DANMAKU_MYSQL_CONFIG": str(config_path)})

    assert resolved == config_path


def test_resolve_mysql_config_path_defaults_to_local_file():
    assert resolve_mysql_config_path(env={}) == DEFAULT_CONFIG_PATH


def test_load_mysql_config_rejects_missing_required_field(tmp_path):
    config_path = tmp_path / "mysql.local.json"
    write_config(config_path, password="")

    with pytest.raises(MySQLConfigError):
        load_mysql_config(config_path)


def test_load_mysql_config_rejects_invalid_port(tmp_path):
    config_path = tmp_path / "mysql.local.json"
    write_config(config_path, port=70000)

    with pytest.raises(MySQLConfigError):
        load_mysql_config(config_path)

