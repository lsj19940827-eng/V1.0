# -*- coding: utf-8 -*-
"""从正式快照生成排除用户运行数据的校正补丁，仅生成本地待发布成果。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import backfill_patch_release, patch_builder, release_snapshot
from update_artifact_rules import is_runtime_artifact


def prepare_snapshot_runtime_patch_repair(
    version: str, output_dir: str, snapshot_root: str | None = None,
) -> dict:
    """只移除已有正式补丁中的运行数据，保持程序字节和版本覆盖范围一致。"""
    snapshot_root = snapshot_root or str(ROOT / release_snapshot.SNAPSHOT_ROOT)
    snapshot = release_snapshot.load_release_snapshot(version, snapshot_root)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="runtime-patch-snapshot-") as download_dir:
        source_zip = backfill_patch_release._ensure_snapshot_file(snapshot.get("patch_zip") or {}, download_dir)
        # 校正补丁仍以原正式全量包为目标，不能带入当前开发工作区的程序。
        backfill_patch_release._ensure_snapshot_file(snapshot.get("full_zip") or {}, download_dir)
        manifest_path = snapshot["manifest"]["path"]
        manifest = patch_builder.load_manifest(manifest_path)
        target_files = patch_builder._program_manifest_files(manifest)
        target_zip = output / Path(source_zip).name
        if target_zip.resolve() == Path(source_zip).resolve():
            raise ValueError("校正补丁必须输出到独立目录，不能覆盖原发布快照资产。")
        temporary_zip = target_zip.with_suffix(".zip.tmp")
        with zipfile.ZipFile(source_zip) as source:
            meta = json.loads(source.read("patch_manifest.json"))
            if meta.get("type") != "universal_patch" or meta.get("version") != version:
                raise ValueError("正式补丁类型或目标版本与快照不一致。")
            original_target = meta.get("target_files") or {}
            if patch_builder._program_manifest_files({"files": original_target}) != target_files:
                raise ValueError("正式补丁的程序目标哈希表与正式全量包清单不一致。")
            removed_paths = sorted({
                path
                for field in ("included_files", "deleted", "target_files", "allowed_source_hashes")
                for path in (meta.get(field) or [])
                if is_runtime_artifact(path)
            })
            meta["included_files"] = [p for p in meta["included_files"] if not is_runtime_artifact(p)]
            meta["deleted"] = [p for p in meta.get("deleted", []) if not is_runtime_artifact(p)]
            meta["target_files"] = target_files
            meta["allowed_source_hashes"] = {
                p: values for p, values in meta["allowed_source_hashes"].items()
                if not is_runtime_artifact(p)
            }
            if not removed_paths:
                raise ValueError("正式补丁没有需要排除的运行数据，无需生成校正包。")
            try:
                with zipfile.ZipFile(temporary_zip, "w", zipfile.ZIP_DEFLATED) as repaired:
                    repaired.writestr("patch_manifest.json", json.dumps(meta, ensure_ascii=False, indent=2))
                    for path in meta["included_files"]:
                        digest = hashlib.sha256()
                        with source.open(path) as reader, repaired.open(source.getinfo(path), "w") as writer:
                            while chunk := reader.read(1024 * 1024):
                                digest.update(chunk)
                                writer.write(chunk)
                        if digest.hexdigest() != target_files.get(path):
                            raise ValueError(f"正式补丁文件与目标哈希不一致：{path}")
                os.replace(temporary_zip, target_zip)
            finally:
                temporary_zip.unlink(missing_ok=True)
    result = {
        "version": version,
        "patch_zip": str(target_zip.resolve()),
        "source_patch_sha256": snapshot["patch_zip"]["sha256"],
        "patch_sha256": release_snapshot.sha256_file(str(target_zip)),
        "full_package_sha256": snapshot["full_zip"]["sha256"],
        "min_version": meta["min_version"],
        "source_versions": meta["source_versions"],
        "removed_runtime_paths": removed_paths,
        "included_count": len(meta["included_files"]),
        "deleted_count": len(meta["deleted"]),
        "size_mb": round(target_zip.stat().st_size / (1024 * 1024), 2),
        "program_payload_verified": True,
        "published": False,
    }
    (output / "repair-audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    print(json.dumps(prepare_snapshot_runtime_patch_repair(args.version, args.output_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
