"""热门视频两周归档、更新判断和内存缓存管理。

当前已模块已实现功能：
1. 判断当前北京时间是否需要更新热门数据
2. 管理员可强制立即更新
3. 每日结束归档时跳过那一次更新
4. 同一分钟内已经更新过则不重复更新 --5.27
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.danmaku_store import read_all_danmakus, write_danmaku_store
from src.storage import read_json, write_json
from src.time_utils import BEIJING_TZ, now_beijing


def should_update_now(
    current_time: datetime | None,
    last_update_at: datetime | None,
    admin_force: bool = False,
) -> bool:
    """判断当前北京时间是否需要更新热门数据。

    规则：
    - 默认只在分钟数能被 5 整除时更新。
    - 管理员可强制立即更新。
    - 每日结束归档时跳过那一次更新。
    - 同一分钟内已经更新过则不重复更新。
    """

    current = current_time or now_beijing()
    if current.tzinfo is None:
        current = current.replace(tzinfo=BEIJING_TZ)

    if current.hour == 0 and current.minute == 0:
        return False
    if admin_force:
        return True
    if current.minute % 5 != 0:
        return False
    if last_update_at is None:
        return True
    return current.strftime("%Y-%m-%d %H:%M") != last_update_at.astimezone(BEIJING_TZ).strftime("%Y-%m-%d %H:%M")


@dataclass
class ArchiveStore:
    """管理最近两周热门视频归档数据。"""

    root: Path | str

    def __post_init__(self) -> None:
        self.root = Path(self.root)

    def day_dir(self, day: datetime) -> Path:
        """返回某一天的归档目录。"""

        return self.root / "data" / "archive" / day.strftime("%Y-%m-%d")

    def save_today_hot_data(
        self,
        videos: list[dict[str, Any]],
        danmakus: list[dict[str, Any]],
        current_time: datetime | None = None,
        stop_words: list[str] | None = None,
    ) -> None:
        """保存当天热门视频和弹幕数据。"""

        now = current_time or now_beijing()
        day = now.astimezone(BEIJING_TZ)
        folder = self.day_dir(day)
        write_json(folder / "today_hot_videos.json", videos)
        write_danmaku_store(
            folder,
            videos,
            danmakus,
            module="popular_archive",
            date=day.strftime("%Y-%m-%d"),
            stop_words=stop_words,
        )

    def load_recent_hot_data(
        self,
        today: datetime | None = None,
        days: int = 14,
        start_offset: int = 0,
    ) -> dict[str, list[dict[str, Any]]]:
        """读取最近若干天归档；缺失日期按空数据处理。"""

        base_day = (today or now_beijing()).astimezone(BEIJING_TZ)
        videos: list[dict[str, Any]] = []
        danmakus: list[dict[str, Any]] = []

        for offset in range(start_offset, days):
            day = base_day - timedelta(days=offset)
            folder = self.day_dir(day)
            video_file = folder / "today_hot_videos.json"
            danmaku_file = folder / "today_danmakus.json"

            if video_file.exists():
                videos.extend(read_json(video_file))
            danmakus.extend(read_all_danmakus(folder, danmaku_file))

        return {"videos": videos, "danmakus": danmakus}


@dataclass
class HotVideoCache:
    """保存当前热门榜对应的弹幕缓存，并释放已下榜视频。"""

    active_bvids: set[str] = field(default_factory=set)
    danmakus_by_bvid: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def refresh_active_videos(self, videos: list[dict[str, Any]]) -> list[str]:
        """根据新榜单更新活跃 BV 集合，并删除不再上榜的视频弹幕缓存。"""

        next_bvids = {str(video.get("bvid", "")) for video in videos if video.get("bvid")}
        removed = sorted(self.active_bvids.union(self.danmakus_by_bvid) - next_bvids)
        for bvid in removed:
            self.danmakus_by_bvid.pop(bvid, None)
        self.active_bvids = next_bvids
        return removed
