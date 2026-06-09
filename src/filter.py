"""弹幕内容屏蔽模块。

本模块只负责和 B 站接口交互，不做复杂统计分析，方便后续维护和测试。

当前已模块已实现功能：
1. 读取屏蔽词配置，自动忽略空行和以 # 开头的注释。
2. 按屏蔽词处理弹幕。
3. 把内容中的屏蔽词替换为星号。
4. 判断弹幕内容是否包含任一屏蔽词。 --5.27
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


FilterMode = Literal["drop", "mask"]


@dataclass
class FilterResult:
    """屏蔽处理结果。"""

    danmakus: list[dict[str, Any]]
    removed_count: int = 0
    masked_count: int = 0


def load_block_words(path: str | Path) -> list[str]:
    """读取屏蔽词配置，自动忽略空行和以 # 开头的注释。"""

    target = Path(path)
    if not target.exists():
        return []

    words: list[str] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        word = line.strip()
        if word and not word.startswith("#"):
            words.append(word)
    return words


def apply_blocklist(
    danmakus: list[dict[str, Any]],
    block_words: list[str],
    mode: FilterMode = "drop",
) -> FilterResult:
    """按屏蔽词处理弹幕。

    `drop` 会删除命中弹幕；`mask` 会把命中的字段替换成 `***`。
    """

    if not block_words:
        return FilterResult(danmakus=list(danmakus))
    if mode not in {"drop", "mask"}:
        raise ValueError("mode 只能是 drop 或 mask")

    kept: list[dict[str, Any]] = []
    removed_count = 0
    masked_count = 0

    for row in danmakus:
        content = str(row.get("content", ""))
        if not _contains_block_word(content, block_words):
            kept.append(dict(row))
            continue

        if mode == "drop":
            removed_count += 1
            continue

        masked_row = dict(row)
        masked_row["content"] = mask_content(content, block_words)
        kept.append(masked_row)
        masked_count += 1

    return FilterResult(kept, removed_count=removed_count, masked_count=masked_count)


def mask_content(content: str, block_words: list[str]) -> str:
    """把内容中的屏蔽词替换为星号。"""

    masked = content
    for word in block_words:
        if word:
            masked = masked.replace(word, "***")
    return masked


def _contains_block_word(content: str, block_words: list[str]) -> bool:
    """判断弹幕内容是否包含任一屏蔽词。"""

    lowered = content.lower()
    return any(word.lower() in lowered for word in block_words if word)
