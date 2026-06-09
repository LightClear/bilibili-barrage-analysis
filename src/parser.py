"""弹幕 XML 解析与字段标准化。

当前已模块已实现功能：
1. 把 B 站弹幕 XML 转换成统一的字典列表。
2. 保留可视化需要的核心字段。
3. 清理弹幕文本中的 HTML 转义和多余空白。
4. 把发送时间戳转换为北京时间文本。 --5.27
"""

from __future__ import annotations

from html import unescape
from typing import Any
from xml.etree import ElementTree

from src.time_utils import timestamp_to_beijing_text


def parse_danmaku_xml(
    xml_text: str,
    bvid: str = "",
    title: str = "",
    cid: int | None = None,
) -> list[dict[str, Any]]:
    """把 B 站弹幕 XML 转换成统一的字典列表。

    B 站旧弹幕接口中，每条弹幕的属性 `p` 是逗号分隔字段：
    出现时间、模式、字号、颜色、发送时间戳、弹幕池、用户哈希、弹幕ID。
    当前项目只保留可视化需要的核心字段。
    """

    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return []

    rows: list[dict[str, Any]] = []
    for node in root.findall("d"):
        raw_params = node.attrib.get("p", "")
        parts = raw_params.split(",")
        if len(parts) < 5:
            continue

        try:
            send_timestamp = int(float(parts[4]))
            rows.append(
                {
                    "cid": cid,
                    "title": title,
                    "time_in_video": float(parts[0]),
                    "color": int(float(parts[3])),
                    "send_timestamp": send_timestamp,
                    "send_time_text": timestamp_to_beijing_text(send_timestamp),
                    "user_hash": parts[6] if len(parts) > 6 else "",
                    "content": clean_text(node.text or ""),
                }
            )
        except ValueError:
            # 单条弹幕字段异常时跳过，避免影响整批数据。
            continue
    return rows


def parse_danmaku_seg(
    data: bytes,
    bvid: str = "",
    title: str = "",
    cid: int | None = None,
) -> list[dict[str, Any]]:
    """解析 B 站分段弹幕 protobuf 数据。

    只解析可视化需要的字段，避免为 DEMO 引入额外 protobuf 依赖。
    """

    rows: list[dict[str, Any]] = []
    for payload in _iter_length_delimited_field(data or b"", target_field=1):
        item = _parse_danmaku_elem(payload)
        content = clean_text(str(item.get("content") or ""))
        if not content:
            continue
        send_timestamp = int(item.get("send_timestamp") or 0)
        rows.append(
            {
                "cid": cid,
                "title": title,
                "time_in_video": round(float(item.get("progress_ms") or 0) / 1000, 3),
                "color": int(item.get("color") or 16777215),
                "send_timestamp": send_timestamp,
                "send_time_text": timestamp_to_beijing_text(send_timestamp) if send_timestamp else "",
                "user_hash": str(item.get("user_hash") or ""),
                "content": content,
            }
        )
    return rows


def _parse_danmaku_elem(data: bytes) -> dict[str, Any]:
    item: dict[str, Any] = {}
    pos = 0
    length = len(data)
    while pos < length:
        key, pos = _read_varint(data, pos)
        field = key >> 3
        wire_type = key & 0x07
        if wire_type == 0:
            value, pos = _read_varint(data, pos)
            if field == 2:
                item["progress_ms"] = value
            elif field == 5:
                item["color"] = value
            elif field == 8:
                item["send_timestamp"] = value
        elif wire_type == 2:
            size, pos = _read_varint(data, pos)
            raw = data[pos:pos + size]
            pos += size
            if field == 6:
                item["user_hash"] = raw.decode("utf-8", errors="replace")
            elif field == 7:
                item["content"] = raw.decode("utf-8", errors="replace")
        elif wire_type == 5:
            pos += 4
        elif wire_type == 1:
            pos += 8
        else:
            break
    return item


def _iter_length_delimited_field(data: bytes, target_field: int):
    pos = 0
    length = len(data)
    while pos < length:
        key, pos = _read_varint(data, pos)
        field = key >> 3
        wire_type = key & 0x07
        if wire_type == 2:
            size, pos = _read_varint(data, pos)
            payload = data[pos:pos + size]
            pos += size
            if field == target_field:
                yield payload
        elif wire_type == 0:
            _, pos = _read_varint(data, pos)
        elif wire_type == 5:
            pos += 4
        elif wire_type == 1:
            pos += 8
        else:
            break


def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    value = 0
    shift = 0
    length = len(data)
    while pos < length:
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, pos
        shift += 7
    return value, pos


def clean_text(text: str) -> str:
    """清理弹幕文本中的 HTML 转义和多余空白。"""

    return " ".join(unescape(text).strip().split())
