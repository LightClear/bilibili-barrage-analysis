from src.parser import parse_danmaku_seg, parse_danmaku_xml


def test_parse_danmaku_xml_extracts_required_query_fields():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<i>
  <d p="12.5,1,25,16777215,1716000000,0,abc,123">你好，B站！</d>
  <d p="30,1,25,16777215,1716000100,0,def,456">第二条弹幕</d>
</i>
"""

    rows = parse_danmaku_xml(xml, title="测试视频", cid=987)

    assert rows == [
        {
            "cid": 987,
            "title": "测试视频",
            "time_in_video": 12.5,
            "color": 16777215,
            "send_timestamp": 1716000000,
            "send_time_text": "2024-05-18 10:40:00",
            "user_hash": "abc",
            "content": "你好，B站！",
        },
        {
            "cid": 987,
            "title": "测试视频",
            "time_in_video": 30.0,
            "color": 16777215,
            "send_timestamp": 1716000100,
            "send_time_text": "2024-05-18 10:41:40",
            "user_hash": "def",
            "content": "第二条弹幕",
        },
    ]


def test_parse_danmaku_xml_skips_invalid_rows():
    xml = """<i>
  <d p="bad">字段不足</d>
  <d p="5,1,25,16777215,1716000000,0,abc,123">有效弹幕</d>
</i>"""

    rows = parse_danmaku_xml(xml, title="标题")

    assert len(rows) == 1
    assert rows[0]["content"] == "有效弹幕"


def _varint(value: int) -> bytes:
    data = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            data.append(byte | 0x80)
        else:
            data.append(byte)
            return bytes(data)


def _field_varint(field: int, value: int) -> bytes:
    return _varint((field << 3) | 0) + _varint(value)


def _field_bytes(field: int, value: str) -> bytes:
    raw = value.encode("utf-8")
    return _varint((field << 3) | 2) + _varint(len(raw)) + raw


def test_parse_danmaku_seg_extracts_current_danmaku_fields():
    elem = b"".join(
        [
            _field_varint(2, 12500),
            _field_varint(5, 16777215),
            _field_bytes(6, "hash123"),
            _field_bytes(7, "分段弹幕"),
            _field_varint(8, 1716000000),
        ]
    )
    payload = _varint((1 << 3) | 2) + _varint(len(elem)) + elem

    rows = parse_danmaku_seg(payload, bvid="BV1", title="测试视频", cid=123)

    assert rows == [
        {
            "cid": 123,
            "title": "测试视频",
            "time_in_video": 12.5,
            "color": 16777215,
            "send_timestamp": 1716000000,
            "send_time_text": "2024-05-18 10:40:00",
            "user_hash": "hash123",
            "content": "分段弹幕",
        }
    ]
