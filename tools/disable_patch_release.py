# -*- coding: utf-8 -*-
"""临时关闭线上高风险 patch 字段。

这个脚本只改 Gist version.json 中的 patch 字段：
1. 保留全量包下载信息不动
2. 删除 patch_url / patch_sha256 / min_patch_version 等字段
3. 用于补丁基线还没彻底收口前，先停掉线上误伤
"""

from __future__ import annotations

import argparse
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

from repo_config import GIST_ID
from tools import release
from tools import release_snapshot
from version import APP_VERSION


def _load_gist_version_data(token: str) -> tuple[dict, dict]:
    """读取当前 Gist version.json。"""
    gist_url = f"https://api.github.com/gists/{GIST_ID}"
    gist_data = release._github_api("GET", gist_url, token)
    version_file = (gist_data.get("files") or {}).get("version.json") or {}
    content = version_file.get("content", "")
    if not content:
        raise RuntimeError("Gist 中未找到 version.json 内容。")
    return gist_data, json.loads(content)


def _save_gist_version_data(token: str, version_data: dict) -> dict:
    """回写 Gist version.json。"""
    gist_url = f"https://api.github.com/gists/{GIST_ID}"
    payload = {
        "files": {
            "version.json": {
                "content": json.dumps(version_data, ensure_ascii=False, indent=4),
            }
        }
    }
    return release._github_api("PATCH", gist_url, token, data=payload)


def disable_patch_release(version: str, force: bool = False) -> dict:
    """从线上版本清单中移除 patch 字段。"""
    token = release._get_token()
    _gist_data, current_version_data = _load_gist_version_data(token)
    latest_version = current_version_data.get("latest_version", "")
    if version and latest_version != version and not force:
        raise RuntimeError(
            f"Gist 当前 latest_version={latest_version}，与目标版本 {version} 不一致。"
            "如确认仍要移除 patch 字段，请加 --force。"
        )

    stripped = release_snapshot.strip_patch_fields(current_version_data)
    _save_gist_version_data(token, stripped)
    return {
        "latest_version": stripped.get("latest_version", ""),
        "version_data": stripped,
    }


def main():
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="移除线上 version.json 的 patch 字段")
    parser.add_argument("--version", default=APP_VERSION, help="目标版本，默认当前 version.py")
    parser.add_argument("--force", action="store_true", help="忽略 latest_version 不一致检查")
    args = parser.parse_args()

    result = disable_patch_release(args.version, force=args.force)
    print(f"已移除 V{result['latest_version']} 的 patch 字段")
    print(json.dumps(result["version_data"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
