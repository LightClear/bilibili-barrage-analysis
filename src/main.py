"""命令行入口：采集弹幕并生成前端可视化数据。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    # 允许用户直接运行 `python src/main.py`，同时不影响 `python -m src.main`。
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.archive import ArchiveStore
from src.collector import BilibiliApiError, BilibiliCollector, build_video_url, extract_bvid
from src.filter import load_block_words
from src.pipeline import collect_popular_dataset, collect_single_video, export_project_data



def build_parser() -> argparse.ArgumentParser:
    """创建命令行参数解析器。"""

    parser = argparse.ArgumentParser(description="B站弹幕数据采集与可视化数据生成")
    parser.add_argument(
        "--mode",
        choices=["popular", "bv"],
        default="popular",
        help="popular: 抓取热门视频；bv: 抓取指定 BV 号",
    )
    parser.add_argument("--bvid", help="当 mode=bv 时需要提供的 BV 号")
    parser.add_argument("--limit", type=int, default=50, help="热门视频抓取数量，默认 50")
    parser.add_argument("--archive-days", type=int, default=14, help="兼容旧参数；当前榜单导出不再合并历史归档")
    parser.add_argument("--block-words", default="config/block_words.txt", help="屏蔽词文件路径")
    parser.add_argument("--stop-words", default="config/stop_words.txt", help="停用词文件路径，用于词频/词云分析")
    parser.add_argument("--filter-mode", choices=["drop", "mask"], default="drop", help="屏蔽模式：drop 删除整条，mask 替换命中词")
    parser.add_argument("--case-sensitive", action="store_true", default=False, help="停用词区分大小写，默认不区分")
    parser.add_argument(
        "--project-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="项目根目录，默认自动识别",
    )
    return parser


def main() -> int:
    """执行命令行流程，返回进程退出码。"""

    args = build_parser().parse_args()
    collector = BilibiliCollector()
    project_root = Path(args.project_root)
    block_words = load_block_words(project_root / args.block_words)
    stop_words = load_block_words(project_root / args.stop_words)

    try:
        if args.mode == "popular":
            today_videos, today_danmakus = collect_popular_dataset(collector, limit=args.limit)
            archive = ArchiveStore(project_root)
            archive.save_today_hot_data(today_videos, today_danmakus, stop_words=stop_words)
            videos = today_videos
            danmakus = today_danmakus
        else:
            if not args.bvid:
                raise BilibiliApiError("mode=bv 时必须提供 --bvid")
            bvid = extract_bvid(args.bvid)
            video_info = collector.fetch_video_info(bvid)
            danmakus = collect_single_video(
                collector,
                bvid,
                title=video_info.get("title", bvid),
                duration=int(video_info.get("duration", 0) or 0),
            )
            videos = [{**video_info, "danmaku": len(danmakus), "video_url": build_video_url(bvid)}]

        export_project_data(
            project_root,
            videos,
            danmakus,
            block_words=block_words,
            stop_words=stop_words,
            filter_mode=args.filter_mode,
            case_sensitive=args.case_sensitive,
        )
    except BilibiliApiError as exc:
        print(f"采集失败：{exc}")
        return 1

    print("数据生成完成：web/data/dashboard.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
