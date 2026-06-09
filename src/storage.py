"""项目数据读写工具。

当前已模块已实现功能：
1. 以 UTF-8 JSON 格式写入数据，并自动创建父目录。
2. 读取 UTF-8 JSON 文件。 --5.27
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any


def write_json(path: str | Path, payload: Any) -> None:
    """以 UTF-8 JSON 格式原子写入数据，并自动创建父目录。"""

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    write_text(path, text)


def write_text(path: str | Path, text: str) -> None:
    """以 UTF-8 文本格式原子写入数据，并自动创建父目录。"""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=target.parent,
            delete=False,
            prefix=f".{target.name}.",
            suffix=".tmp",
        ) as file:
            file.write(text)
            temp_path = Path(file.name)
        temp_path.replace(target)
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)


def read_json(path: str | Path) -> Any:
    """读取 UTF-8 JSON 文件。"""

    return json.loads(Path(path).read_text(encoding="utf-8"))
