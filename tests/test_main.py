from src.main import build_parser


def test_build_parser_accepts_popular_mode():
    args = build_parser().parse_args(["--mode", "popular", "--limit", "10"])

    assert args.mode == "popular"
    assert args.limit == 10


def test_build_parser_accepts_bv_mode():
    args = build_parser().parse_args(["--mode", "bv", "--bvid", "BV1xx411c7mD"])

    assert args.mode == "bv"
    assert args.bvid == "BV1xx411c7mD"


def test_build_parser_accepts_filter_and_archive_options():
    args = build_parser().parse_args(
        [
            "--mode",
            "popular",
            "--archive-days",
            "14",
            "--filter-mode",
            "mask",
            "--block-words",
            "config/custom.txt",
            "--stop-words",
            "config/stop.txt",
        ]
    )

    assert args.archive_days == 14
    assert args.filter_mode == "mask"
    assert args.block_words == "config/custom.txt"
    assert args.stop_words == "config/stop.txt"
