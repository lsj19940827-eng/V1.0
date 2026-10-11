# -*- coding: utf-8 -*-
"""供工程、旁文件和独立工况共用的原子 JSON 写入。"""

import json
import os
import tempfile
from typing import Any


def atomic_write_json(path: str, payload: Any) -> None:
    """同目录完整写入后替换；异常向调用方传播，原文件保持完整。"""
    path = os.fspath(path)
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=directory,
            prefix=f".{os.path.basename(path)}.", suffix=".tmp", delete=False,
        ) as handle:
            temp_path = handle.name
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
