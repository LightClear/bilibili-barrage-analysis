"""B站视频和弹幕采集模块。

本模块只负责和 B 站接口交互，不做复杂统计分析，方便后续维护和测试。

当前已模块已实现功能：
1. 采集 B 站热门视频列表
2. 根据 BV 号获取视频第一分 P 的 cid
3. 根据 cid 下载弹幕 XML 文本
4. 发送 GET 请求并校验 B 站 JSON 响应
5. 根据 BV 号构造 B 站视频播放页地址 --5.27
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import os
import re
from typing import Any

import requests

BVID_PATTERN = re.compile(r"BV[0-9A-Za-z]{10,}")


class BilibiliApiError(RuntimeError):
    """B 站接口返回异常或网络请求失败时抛出的错误。"""


def extract_bvid(value: str) -> str:
    """从 BV 号或 B 站视频 URL 中提取 BV 号。"""

    match = BVID_PATTERN.search(value.strip())
    if not match:
        raise ValueError(f"无法从输入中识别 BV 号：{value}")
    return match.group(0)


def normalize_media_url(value: str) -> str:
    """把 B 站返回的资源地址整理成浏览器更稳定的 HTTPS 地址。"""

    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith("//"):
        return f"https:{raw}"
    if raw.startswith("http://"):
        return f"https://{raw.removeprefix('http://')}"
    return raw


def normalize_description(data: dict[str, Any]) -> str:
    """从 B 站详情数据中提取稳定的视频简介文本。"""

    desc = str(data.get("desc", "") or "").strip()
    if desc:
        return desc
    desc_v2 = data.get("desc_v2") or []
    parts = [
        str(item.get("raw_text", "") or "").strip()
        for item in desc_v2
        if isinstance(item, dict) and item.get("raw_text")
    ]
    return "\n".join(parts)


@dataclass
class BilibiliCollector:
    """封装 B 站热门视频和弹幕 XML 的采集逻辑。"""

    session: Any = field(default_factory=requests.Session)
    timeout: int = 10
    history_cookie: str = ""

    POPULAR_URL = "https://api.bilibili.com/x/web-interface/popular"
    PAGE_LIST_URL = "https://api.bilibili.com/x/player/pagelist"
    DANMAKU_URL = "https://comment.bilibili.com/{cid}.xml"
    DANMAKU_SEGMENT_URL = "https://api.bilibili.com/x/v2/dm/web/seg.so"
    DANMAKU_HISTORY_INDEX_URL = "https://api.bilibili.com/x/v2/dm/history/index"
    DANMAKU_HISTORY_SEGMENT_URL = "https://api.bilibili.com/x/v2/dm/web/history/seg.so"
    DANMAKU_SEGMENT_SECONDS = 360
    VIDEO_INFO_URL = "https://api.bilibili.com/x/web-interface/view"

    def __post_init__(self) -> None:
        # UA 能降低接口拒绝普通脚本请求的概率。
        if hasattr(self.session, "headers"):
            self.session.headers.update(
                {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0 Safari/537.36"
                    ),
                    "Referer": "https://www.bilibili.com/",
                }
            )
            cookie = self._history_cookie_header()
            if cookie:
                self.session.headers.update({"Cookie": cookie})

    def _history_cookie_header(self) -> str:
        """Read Bilibili login cookie from account config first, then environment."""

        injected_cookie = str(self.history_cookie or "").strip()
        if injected_cookie:
            return injected_cookie
        full_cookie = os.environ.get("BILI_COOKIE", "").strip()
        if full_cookie:
            return full_cookie
        sessdata = os.environ.get("BILI_SESSDATA", "").strip()
        return f"SESSDATA={sessdata}" if sessdata else ""

    def has_history_auth(self) -> bool:
        """Whether historical danmaku endpoints can be attempted."""

        return bool(self._history_cookie_header())

    def fetch_popular_videos(self, limit: int = 50) -> list[dict[str, Any]]:
        """获取 B 站热门视频列表，并整理成稳定字段。"""

        page_size = max(1, min(limit, 50))
        payload = self._get_json(self.POPULAR_URL, params={"ps": page_size, "pn": 1})
        videos = payload.get("data", {}).get("list", [])

        results: list[dict[str, Any]] = []
        for index, item in enumerate(videos[:limit]):
            stat = item.get("stat", {})
            owner = item.get("owner", {})
            results.append(
                {
                    "rank": index + 1,
                    "bvid": item.get("bvid", ""),
                    "title": item.get("title", ""),
                    "owner": owner.get("name", ""),
                    "desc": normalize_description(item),
                    "view": int(stat.get("view", 0) or 0),
                    "danmaku": int(stat.get("danmaku", 0) or 0),
                    "like": int(stat.get("like", 0) or 0),
                    "favorite": int(stat.get("favorite", 0) or 0),
                    "coin": int(stat.get("coin", 0) or 0),
                    "duration": int(item.get("duration", 0) or 0),
                    "cover_url": normalize_media_url(item.get("pic", "")),
                    "video_url": build_video_url(item.get("bvid", "")),
                }
            )
        return [video for video in results if video["bvid"]]

    def fetch_cid(self, bvid: str) -> int:
        """根据 BV 号获取视频第一分 P 的 cid。"""

        payload = self._get_json(self.PAGE_LIST_URL, params={"bvid": bvid})
        pages = payload.get("data", [])
        if not pages:
            raise BilibiliApiError(f"未找到 BV 号对应的分 P 信息：{bvid}")
        return int(pages[0]["cid"])

    def fetch_page_list(self, bvid: str) -> list[dict[str, Any]]:
        """根据 BV 号获取所有分 P 的 cid、页码和标题。"""

        payload = self._get_json(self.PAGE_LIST_URL, params={"bvid": bvid})
        pages = payload.get("data", [])
        if not pages:
            raise BilibiliApiError(f"未找到 BV 号对应的分 P 信息：{bvid}")
        return [
            {
                "cid": int(p["cid"]),
                "page": int(p.get("page", idx + 1)),
                "part": p.get("part", f"P{idx + 1}"),
            }
            for idx, p in enumerate(pages)
        ]

    def fetch_video_info(self, bvid: str) -> dict[str, Any]:
        """根据 BV 号获取视频标题、封面等基本信息。"""

        payload = self._get_json(self.VIDEO_INFO_URL, params={"bvid": bvid})
        data = payload.get("data", {})
        stat = data.get("stat", {})
        owner = data.get("owner", {})
        return {
            "rank": 0,
            "bvid": bvid,
            "title": data.get("title", bvid),
            "owner": owner.get("name", ""),
            "desc": normalize_description(data),
            "view": int(stat.get("view", 0) or 0),
            "danmaku": int(stat.get("danmaku", 0) or 0),
            "like": int(stat.get("like", 0) or 0),
            "favorite": int(stat.get("favorite", 0) or 0),
            "coin": int(stat.get("coin", 0) or 0),
            "duration": int(data.get("duration", 0) or 0),
            "pubdate": int(data.get("pubdate", 0) or 0),
            "cover_url": normalize_media_url(data.get("pic", "")),
            "video_url": build_video_url(bvid),
        }

    def fetch_danmaku_xml(self, cid: int) -> str:
        """根据 cid 下载弹幕 XML 文本。"""

        url = self.DANMAKU_URL.format(cid=cid)
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001 - 对外统一成业务错误更友好。
            raise BilibiliApiError(f"下载弹幕失败：{cid}") from exc
        content = getattr(response, "content", None)
        if content:
            return content.decode("utf-8", errors="replace")
        return response.text

    def fetch_danmaku_segments(self, cid: int, duration: int = 0) -> list[bytes]:
        """根据 cid 下载当前分段弹幕 protobuf 数据。

        旧 XML 接口经常只返回约 3600 条弹幕；分段接口可以拿到更多当前弹幕。
        """

        max_segments = max(1, math.ceil(max(0, int(duration or 0)) / self.DANMAKU_SEGMENT_SECONDS))
        segments: list[bytes] = []
        for index in range(1, max_segments + 1):
            data = self.fetch_danmaku_segment(cid, index)
            if data:
                segments.append(data)
        return segments

    def fetch_danmaku_segment(self, cid: int, segment_index: int = 1) -> bytes:
        """下载单个分段弹幕 protobuf。"""

        try:
            response = self.session.get(
                self.DANMAKU_SEGMENT_URL,
                params={"type": 1, "oid": cid, "segment_index": segment_index},
                timeout=self.timeout,
            )
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            raise BilibiliApiError(f"下载分段弹幕失败：{cid}#{segment_index}") from exc
        return bytes(getattr(response, "content", b"") or b"")

    def fetch_history_dates(self, cid: int, month: str) -> list[str]:
        """查询某月存在历史弹幕快照的日期。

        该接口需要登录 Cookie。Cookie 只从环境变量读取，不写入项目文件。
        """

        if not self.has_history_auth():
            raise BilibiliApiError("历史弹幕接口需要 BILI_SESSDATA 或 BILI_COOKIE")
        payload = self._get_json(
            self.DANMAKU_HISTORY_INDEX_URL,
            params={"type": 1, "oid": cid, "month": month},
        )
        dates = payload.get("data") or []
        if not isinstance(dates, list):
            return []
        return [str(item) for item in dates if item]

    def fetch_history_segment(self, cid: int, date: str) -> bytes:
        """下载某个历史日期的弹幕 protobuf 快照。"""

        if not self.has_history_auth():
            raise BilibiliApiError("历史弹幕接口需要 BILI_SESSDATA 或 BILI_COOKIE")
        try:
            response = self.session.get(
                self.DANMAKU_HISTORY_SEGMENT_URL,
                params={"type": 1, "oid": cid, "date": date},
                timeout=self.timeout,
            )
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            raise BilibiliApiError(f"下载历史弹幕失败：{cid}@{date}") from exc

        content = bytes(getattr(response, "content", b"") or b"")
        if content.lstrip().startswith(b"{"):
            try:
                payload = response.json()
            except Exception as exc:  # noqa: BLE001
                raise BilibiliApiError(f"历史弹幕接口返回异常：{date}") from exc
            if payload.get("code", 0) != 0:
                raise BilibiliApiError(f"历史弹幕接口返回错误：{payload.get('message', '未知错误')}")
        return content

    def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        """发送 GET 请求并校验 B 站 JSON 响应。"""

        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # noqa: BLE001
            raise BilibiliApiError(f"请求 B 站接口失败：{url}") from exc

        if payload.get("code", 0) != 0:
            code = payload.get("code", "未知")
            message = payload.get("message", "未知错误")
            raise BilibiliApiError(f"B 站接口返回错误：code={code}，message={message}")
        return payload


def build_video_url(bvid: str) -> str:
    """根据 BV 号构造 B 站视频播放页地址。"""

    return f"https://www.bilibili.com/video/{bvid}" if bvid else ""
