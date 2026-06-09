import json

from src.storage import write_json


def test_write_json_creates_parent_directory_and_utf8_file(tmp_path):
    target = tmp_path / "nested" / "data.json"
    payload = {"message": "中文弹幕"}

    write_json(target, payload)

    assert json.loads(target.read_text(encoding="utf-8")) == payload
