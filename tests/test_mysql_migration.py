import json

from src.danmaku_store import write_danmaku_store
from src.db.mysql_apply_schema import split_sql_statements
from src.db.mysql_migration import build_file_migration_plan


def test_split_sql_statements_skips_comments():
    sql = """
    -- comment
    CREATE DATABASE demo;

    -- another comment
    USE demo;
    CREATE TABLE users (id INT);
    """

    statements = split_sql_statements(sql)

    assert statements == [
        "CREATE DATABASE demo;",
        "USE demo;",
        "CREATE TABLE users (id INT);",
    ]


def test_build_file_migration_plan_redacts_api_keys(tmp_path):
    root = tmp_path
    (root / "data" / "secure").mkdir(parents=True)
    (root / "data" / "user_block_words").mkdir(parents=True)
    (root / "config").mkdir()
    (root / "web" / "data").mkdir(parents=True)

    (root / "data" / "accounts.txt").write_text(
        json.dumps(
            {
                "users": [
                    {
                        "account": "user_demo",
                        "username": "普通用户",
                        "password_hash": "pbkdf2_sha256$1$salt$digest",
                        "email": "user@example.com",
                        "role": "normal",
                        "api_enabled": True,
                        "api_key": "bili_demo_sensitive_token",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (root / "data" / "secure" / "api_providers.json").write_text(
        json.dumps({"providers": {"user_demo": {"api_key": {"ciphertext": "secret"}}}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "config" / "block_words.txt").write_text("屏蔽词\n", encoding="utf-8")
    (root / "data" / "user_block_words" / "user_demo.txt").write_text("个人词\n", encoding="utf-8")
    (root / "web" / "data" / "dashboard.json").write_text(
        json.dumps({"videos": [{"bvid": "BV1234567890", "title": "测试视频"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "web" / "data" / "danmakus.json").write_text(
        json.dumps([{"title": "测试视频", "cid": 1, "content": "测试弹幕"}], ensure_ascii=False),
        encoding="utf-8",
    )

    plan = build_file_migration_plan(root)
    rendered = json.dumps(plan, ensure_ascii=False)

    assert plan["accounts"]["count"] == 1
    assert plan["accounts"]["api_enabled"] == 1
    assert plan["ai_provider_configs"]["count"] == 1
    assert plan["totals"]["video_rows"] == 1
    assert plan["totals"]["danmaku_rows"] == 1
    assert "bili_demo_sensitive_token" not in rendered
    assert "secret" not in rendered


def test_build_file_migration_plan_warns_when_danmakus_exceed_limit(tmp_path):
    root = tmp_path
    (root / "data").mkdir()
    (root / "config").mkdir()
    (root / "web" / "data").mkdir(parents=True)
    (root / "data" / "accounts.txt").write_text('{"users":[]}', encoding="utf-8")
    (root / "web" / "data" / "dashboard.json").write_text(
        json.dumps({"videos": [{"bvid": "BV1234567890", "title": "测试视频"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "web" / "data" / "danmakus.json").write_text(
        json.dumps(
            [
                {"title": "测试视频", "cid": 1, "content": "A"},
                {"title": "测试视频", "cid": 1, "content": "B"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    plan = build_file_migration_plan(root, max_danmakus=1)

    assert plan["warnings"]
    assert "超过当前上限" in plan["warnings"][0]


def test_build_file_migration_plan_reads_split_danmaku_store(tmp_path):
    root = tmp_path
    (root / "data").mkdir()
    (root / "config").mkdir()
    (root / "web" / "data").mkdir(parents=True)
    (root / "data" / "accounts.txt").write_text('{"users":[]}', encoding="utf-8")
    videos = [{"bvid": "BV1234567890", "title": "测试视频"}]
    (root / "web" / "data" / "dashboard.json").write_text(
        json.dumps({"raw_videos": videos}, ensure_ascii=False),
        encoding="utf-8",
    )
    write_danmaku_store(
        root / "web" / "data",
        videos,
        [{"bvid": "BV1234567890", "title": "测试视频", "cid": 1, "content": "A"}],
        module="popular_current",
    )

    plan = build_file_migration_plan(root)

    assert plan["totals"]["danmaku_rows"] == 1
