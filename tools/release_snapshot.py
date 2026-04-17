# -*- coding: utf-8 -*-
"""正式发版快照工具。

快照用于固定一次正式发布对应的全量包、补丁包、manifest 和 Gist version.json，
后续回补 patch 只能基于这份不可变快照，不再依赖会漂移的本地 dist 或 manifest。
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime

SNAPSHOT_ROOT = ".release-snapshots"
PATCH_FIELDS = {
    "patch_url",
    "patch_url_direct",
    "patch_url_proxy",
    "patch_size_mb",
    "min_patch_version",
    "patch_base_version",
    "patch_sha256",
}


def sha256_file(path: str) -> str:
    """计算文件 SHA256。"""
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(128 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def strip_patch_fields(version_data: dict) -> dict:
    """移除高风险 patch 字段，便于临时只保留全量更新。"""
    return {
        key: value
        for key, value in (version_data or {}).items()
        if key not in PATCH_FIELDS
    }


def snapshot_dir_for_version(version: str, snapshot_root: str) -> str:
    """返回指定版本的快照目录。"""
    safe_version = (version or "").strip() or "unknown"
    return os.path.join(snapshot_root, f"v{safe_version}")


def load_release_snapshot(version: str, snapshot_root: str) -> dict:
    """读取指定版本快照。"""
    snapshot_file = os.path.join(
        snapshot_dir_for_version(version, snapshot_root),
        "snapshot.json",
    )
    with open(snapshot_file, "r", encoding="utf-8") as f:
        return json.load(f)


def write_release_snapshot(
    *,
    version: str,
    tag_name: str,
    full_zip_path: str,
    full_download_url: str,
    version_data: dict,
    manifest_path: str = "",
    patch_zip_path: str = "",
    patch_download_url: str = "",
    snapshot_root: str = SNAPSHOT_ROOT,
) -> str:
    """写入正式发布快照并返回 snapshot.json 路径。"""
    version_dir = snapshot_dir_for_version(version, snapshot_root)
    os.makedirs(version_dir, exist_ok=True)

    snapshot: dict = {
        "version": version,
        "tag_name": tag_name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "version_data": dict(version_data or {}),
        "full_zip": {
            "path": os.path.abspath(full_zip_path),
            "name": os.path.basename(full_zip_path),
            "size_bytes": os.path.getsize(full_zip_path),
            "sha256": sha256_file(full_zip_path),
            "download_url": full_download_url,
        },
    }

    if manifest_path and os.path.isfile(manifest_path):
        manifest_copy_path = os.path.join(version_dir, "manifest.json")
        shutil.copy2(manifest_path, manifest_copy_path)
        snapshot["manifest"] = {
            "path": os.path.abspath(manifest_copy_path),
            "source_path": os.path.abspath(manifest_path),
            "name": os.path.basename(manifest_copy_path),
        }

    if patch_zip_path and os.path.isfile(patch_zip_path):
        snapshot["patch_zip"] = {
            "path": os.path.abspath(patch_zip_path),
            "name": os.path.basename(patch_zip_path),
            "size_bytes": os.path.getsize(patch_zip_path),
            "sha256": sha256_file(patch_zip_path),
            "download_url": patch_download_url,
        }

    snapshot_file = os.path.join(version_dir, "snapshot.json")
    with open(snapshot_file, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    return snapshot_file
