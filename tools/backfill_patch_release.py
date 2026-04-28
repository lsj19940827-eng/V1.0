# -*- coding: utf-8 -*-
"""基于正式发布快照回补 patch 资产。

约束：
1. 只能使用已发布快照里的 full zip、manifest 和 version.json
2. 不再依赖发布后可能漂移的本地 dist 或手工改过的 manifest
3. 若快照中的本地文件缺失，会按快照里的下载地址重新拉取并校验 SHA256
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import urllib.request
import zipfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

from repo_config import GIST_ID, GITHUB_OWNER, GITHUB_REPO
from tools import patch_builder, release, release_snapshot
from version import APP_NAME_EN, APP_VERSION

DEFAULT_BASE_VERSION = "1.3.0"


def _patch_zip_path(dist_dir: str, target_version: str) -> str:
    """返回指定版本补丁包路径。"""
    return os.path.join(dist_dir, f"{APP_NAME_EN}-V{target_version}-patch.zip")


def _extract_release_zip(full_zip_path: str, work_dir: str) -> str:
    """解压全量包并返回真正的应用根目录。"""
    extract_root = os.path.join(work_dir, "full-package")
    os.makedirs(extract_root, exist_ok=True)
    with zipfile.ZipFile(full_zip_path, "r") as zf:
        zf.extractall(extract_root)

    entries = [os.path.join(extract_root, name) for name in os.listdir(extract_root)]
    child_dirs = [path for path in entries if os.path.isdir(path)]
    if len(child_dirs) == 1:
        return child_dirs[0]
    return extract_root


def _download_snapshot_asset(entry: dict, download_dir: str) -> str:
    """按快照记录重新下载资产并校验。"""
    download_url = (entry or {}).get("download_url", "")
    if not download_url:
        raise RuntimeError(f"快照资产缺少下载地址：{entry}")
    target_path = os.path.join(download_dir, entry.get("name") or os.path.basename(download_url))
    urllib.request.urlretrieve(download_url, target_path)
    actual_sha256 = release_snapshot.sha256_file(target_path)
    expected_sha256 = (entry.get("sha256") or "").strip().lower()
    if expected_sha256 and actual_sha256.lower() != expected_sha256:
        raise RuntimeError(
            f"下载的快照资产校验失败：{target_path}，期望 {expected_sha256}，实际 {actual_sha256}"
        )
    return target_path


def _ensure_snapshot_file(entry: dict, download_dir: str) -> str:
    """优先复用快照记录的本地文件，缺失时再按快照地址下载。"""
    local_path = (entry or {}).get("path", "")
    expected_sha256 = (entry or {}).get("sha256", "").strip().lower()
    if local_path and os.path.isfile(local_path):
        actual_sha256 = release_snapshot.sha256_file(local_path).lower()
        if not expected_sha256 or actual_sha256 == expected_sha256:
            return local_path
    return _download_snapshot_asset(entry, download_dir)


def _resolve_snapshot_inputs(
    *,
    snapshot_root: str,
    target_version: str,
    base_version: str,
    download_dir: str,
) -> dict:
    """解析回补 patch 所需的快照输入。"""
    base_snapshot = release_snapshot.load_release_snapshot(base_version, snapshot_root)
    target_snapshot = release_snapshot.load_release_snapshot(target_version, snapshot_root)
    base_manifest_path = ((base_snapshot.get("manifest") or {}).get("path") or "").strip()
    target_manifest_path = ((target_snapshot.get("manifest") or {}).get("path") or "").strip()
    if not os.path.isfile(base_manifest_path):
        raise FileNotFoundError(f"未找到旧版快照 manifest：{base_manifest_path}")
    if not os.path.isfile(target_manifest_path):
        raise FileNotFoundError(f"未找到目标版本快照 manifest：{target_manifest_path}")
    full_zip_path = _ensure_snapshot_file(target_snapshot.get("full_zip") or {}, download_dir)
    return {
        "base_snapshot": base_snapshot,
        "target_snapshot": target_snapshot,
        "base_manifest_path": base_manifest_path,
        "target_manifest_path": target_manifest_path,
        "full_zip_path": full_zip_path,
    }


def _build_patch_info(patch_name: str, patch_result: dict) -> dict:
    """构造与正式发版链路兼容的 patch-info.json 内容。"""
    return {
        "type": "universal",
        "latest_version": patch_result.get("version", "") or "",
        "generated_at": patch_result.get("build_time", "") or "",
        "min_version": patch_result.get("min_version", ""),
        "patch_name": patch_name,
        "size_mb": patch_result.get("size_mb", 0),
        "changed_count": patch_result.get("changed_count", 0),
        "deleted_count": patch_result.get("deleted_count", 0),
    }


def _write_patch_info(dist_dir: str, patch_info: dict) -> str:
    """写出 patch-info.json。"""
    patch_info_path = os.path.join(dist_dir, "patch-info.json")
    with open(patch_info_path, "w", encoding="utf-8") as f:
        json.dump(patch_info, f, ensure_ascii=False, indent=2)
    return patch_info_path


def prepare_backfill_patch_artifacts(
    *,
    target_version: str = APP_VERSION,
    base_version: str = DEFAULT_BASE_VERSION,
    dist_dir: str | None = None,
    snapshot_root: str | None = None,
) -> dict:
    """根据正式快照本地生成回补 patch 包。"""
    dist_dir = dist_dir or os.path.join(PROJECT_ROOT, "dist")
    snapshot_root = snapshot_root or os.path.join(PROJECT_ROOT, release_snapshot.SNAPSHOT_ROOT)
    os.makedirs(dist_dir, exist_ok=True)
    patch_zip_path = _patch_zip_path(dist_dir, target_version)

    with tempfile.TemporaryDirectory(prefix="backfill_patch_snapshot_") as tmp_dir:
        inputs = _resolve_snapshot_inputs(
            snapshot_root=snapshot_root,
            target_version=target_version,
            base_version=base_version,
            download_dir=tmp_dir,
        )
        old_manifest = patch_builder.load_manifest(inputs["base_manifest_path"])
        new_manifest = patch_builder.load_manifest(inputs["target_manifest_path"])
        extracted_root = _extract_release_zip(inputs["full_zip_path"], tmp_dir)
        if os.path.exists(patch_zip_path):
            os.remove(patch_zip_path)
        patch_result = patch_builder.build_universal_patch(
            extracted_root,
            [(base_version, old_manifest)],
            new_manifest,
            patch_zip_path,
        )

    if not patch_result:
        raise RuntimeError("指定旧版本与目标版本之间没有差异，未生成补丁包。")
    if patch_result.get("min_version") != base_version:
        raise RuntimeError(
            f"补丁覆盖范围异常：期望 {base_version}，实际 {patch_result.get('min_version')}"
        )

    patch_result["version"] = target_version
    patch_result["build_time"] = new_manifest.get("build_time", "")
    patch_info = _build_patch_info(os.path.basename(patch_zip_path), patch_result)
    patch_info_path = _write_patch_info(dist_dir, patch_info)
    return {
        "patch_zip": patch_zip_path,
        "patch_info_path": patch_info_path,
        "patch_info": patch_info,
        "patch_result": patch_result,
        "target_snapshot": inputs["target_snapshot"],
    }


def build_backfilled_version_data(
    existing_version_data: dict,
    *,
    patch_url_direct: str,
    patch_zip_path: str,
    patch_size_mb: float,
    min_patch_version: str,
) -> dict:
    """在现有 Gist 数据上只补齐 patch 字段。"""
    merged = dict(existing_version_data)
    merged["patch_url"] = patch_url_direct
    merged["patch_url_direct"] = patch_url_direct
    merged["patch_url_proxy"] = release._proxied_url(patch_url_direct)
    merged["patch_size_mb"] = patch_size_mb
    merged["min_patch_version"] = min_patch_version
    merged["patch_base_version"] = min_patch_version
    merged["patch_sha256"] = release_snapshot.sha256_file(patch_zip_path)
    return merged


def _get_release_by_tag(tag_name: str, token: str) -> dict:
    """读取现有 GitHub Release。"""
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/tags/{tag_name}"
    return release._github_api("GET", url, token)


def _delete_asset_if_exists(release_obj: dict, asset_name: str, token: str) -> bool:
    """删除同名旧资产，避免留下旧链接。"""
    deleted = False
    for asset in release_obj.get("assets", []) or []:
        if asset.get("name") != asset_name:
            continue
        asset_id = asset.get("id")
        if not asset_id:
            continue
        url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/assets/{asset_id}"
        release._github_api("DELETE", url, token)
        deleted = True
    return deleted


def _load_gist_version_data(token: str) -> tuple[dict, dict]:
    """读取当前 Gist 的 version.json。"""
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


def backfill_patch_release(
    *,
    target_version: str = APP_VERSION,
    base_version: str = DEFAULT_BASE_VERSION,
    dist_dir: str | None = None,
    snapshot_root: str | None = None,
) -> dict:
    """执行一次基于快照的 patch 回补。"""
    token = release._get_token()
    release._github_api("GET", "https://api.github.com/user", token)

    artifacts = prepare_backfill_patch_artifacts(
        target_version=target_version,
        base_version=base_version,
        dist_dir=dist_dir,
        snapshot_root=snapshot_root,
    )
    tag_name = f"v{target_version}"
    _gist_data, current_version_data = _load_gist_version_data(token)
    if current_version_data.get("latest_version") != target_version:
        raise RuntimeError(
            f"Gist 当前 latest_version={current_version_data.get('latest_version')}，"
            f"与目标版本 {target_version} 不一致，已停止回补。"
        )

    release_obj = _get_release_by_tag(tag_name, token)
    patch_name = os.path.basename(artifacts["patch_zip"])
    deleted_old_asset = _delete_asset_if_exists(release_obj, patch_name, token)
    patch_url_direct = release._upload_release_asset(
        release_obj.get("upload_url", ""),
        artifacts["patch_zip"],
        token,
    )

    merged_version_data = build_backfilled_version_data(
        current_version_data,
        patch_url_direct=patch_url_direct,
        patch_zip_path=artifacts["patch_zip"],
        patch_size_mb=artifacts["patch_info"]["size_mb"],
        min_patch_version=base_version,
    )
    _save_gist_version_data(token, merged_version_data)
    return {
        "tag_name": tag_name,
        "release_url": release_obj.get("html_url", ""),
        "patch_zip": artifacts["patch_zip"],
        "patch_info_path": artifacts["patch_info_path"],
        "patch_info": artifacts["patch_info"],
        "patch_result": artifacts["patch_result"],
        "patch_url_direct": patch_url_direct,
        "deleted_old_asset": deleted_old_asset,
        "version_data": merged_version_data,
    }


def main():
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="基于正式发布快照回补 patch 资产")
    parser.add_argument("--version", default=APP_VERSION, help="目标正式版本，默认当前 version.py")
    parser.add_argument(
        "--base-version",
        default=DEFAULT_BASE_VERSION,
        help="补丁覆盖的旧版本下限，默认 1.3.0",
    )
    parser.add_argument(
        "--snapshot-root",
        default=os.path.join(PROJECT_ROOT, release_snapshot.SNAPSHOT_ROOT),
        help="发布快照目录",
    )
    args = parser.parse_args()

    result = backfill_patch_release(
        target_version=args.version,
        base_version=args.base_version,
        snapshot_root=args.snapshot_root,
    )
    print(f"已完成 {result['tag_name']} patch 回补")
    print(f"补丁包：{result['patch_zip']}")
    print(
        f"补丁统计：changed={result['patch_result']['changed_count']} "
        f"deleted={result['patch_result']['deleted_count']}"
    )
    print(f"补丁链接：{result['patch_url_direct']}")
    print(f"GitHub Release：{result['release_url']}")


if __name__ == "__main__":
    main()
