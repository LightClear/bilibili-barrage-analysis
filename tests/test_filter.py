from src.filter import apply_blocklist, load_block_words


def test_load_block_words_ignores_blank_lines_and_comments(tmp_path):
    path = tmp_path / "block_words.txt"
    path.write_text("\n# 注释\n剧透\n广告\n", encoding="utf-8")

    assert load_block_words(path) == ["剧透", "广告"]


def test_apply_blocklist_drops_matching_danmakus():
    rows = [
        {"content": "正常弹幕", "user_hash": "u1"},
        {"content": "这条包含剧透", "user_hash": "u2"},
    ]

    result = apply_blocklist(rows, ["剧透"], mode="drop")

    assert result.danmakus == [{"content": "正常弹幕", "user_hash": "u1"}]
    assert result.removed_count == 1
    assert result.masked_count == 0


def test_apply_blocklist_masks_matching_words():
    rows = [{"content": "这条包含剧透", "user_hash": "u1"}]

    result = apply_blocklist(rows, ["剧透"], mode="mask")

    assert result.danmakus[0]["content"] == "这条包含***"
    assert result.removed_count == 0
    assert result.masked_count == 1
