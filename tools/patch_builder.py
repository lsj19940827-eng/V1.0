# -*- coding: utf-8 -*-
"""
增量补丁包构建工具

功能：
1. 扫描打包产物目录，生成 manifest.json（文件路径 → SHA256）
2. 对比新旧 manifest，找出 新增/修改/删除 的文件
3. 构建通用补丁包：合并所有旧版本的差异，生成一个 zip 覆盖所有旧版本

通用补丁包原理（方案B）：
  - 取所有旧版 manifest 与新版的差异的并集
  - 一个补丁包即可将任意 >= min_version 的旧版本升级到最新
  - 补丁包内嵌完整的目标文件哈希表（target_files），客户端可校验

用法：
    # 1) 生成当前版本的 manifest（打包后自动调用）
    python tools/patch_builder.py manifest <dist_folder>

    # 2) 对比两个 manifest，生成补丁包
    python tools/patch_builder.py patch <old_manifest> <new_dist_folder> [--output patch.zip]

manifest.json 格式：
{
    "version": "1.0.3",
    "build_time": "2026-03-01T10:00:00",
    "files": {
        "CanalHydraulicCalc.exe": "sha256:abcdef...",
        "_internal/PySide6/QtCore.dll": "sha256:123456...",
        ...
    }
}
"""

import argparse
import hashlib
import json
import os
import re
import sys
import zipfile
from datetime import datetime

# 确保能导入 version.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _version_key(v: str) -> tuple:
    m = _VERSION_RE.match((v or "").strip())
    if not m:
        return (0, 0, 0)
    return tuple(int(x) for x in m.groups())


# ============================================================
# manifest 生成
# ============================================================
def _sha256(filepath: str) -> str:
    """计算文件的 SHA256 哈希"""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(128 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def generate_manifest(dist_folder: str, version: str = "") -> dict:
    """
    扫描 dist_folder，为每个文件计算 SHA256，返回 manifest 字典。

    Args:
        dist_folder: 打包产物根目录（如 dist/CanalHydraulicCalc/）
        version: 版本号

    Returns:
        manifest dict
    """
    if not version:
        from version import APP_VERSION
        version = APP_VERSION

    files = {}
    for root, dirs, filenames in os.walk(dist_folder):
        # 跳过备份目录
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "_backup")]
        for fname in filenames:
            fpath = os.path.join(root, fname)
            rel_path = os.path.relpath(fpath, dist_folder).replace("\\", "/")
            files[rel_path] = _sha256(fpath)

    manifest = {
        "version": version,
        "build_time": datetime.now().isoformat(timespec="seconds"),
        "file_count": len(files),
        "files": files,
    }
    return manifest


def save_manifest(manifest: dict, output_path: str):
    """将 manifest 写入 JSON 文件"""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"  [manifest] 已生成: {output_path} ({manifest['file_count']} 个文件)")


def load_manifest(path: str) -> dict:
    """从 JSON 文件加载 manifest"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# 差分对比
# ============================================================
class DiffResult:
    """两个版本之间的文件差异"""

    def __init__(self):
        self.added: list[str] = []      # 新增文件
        self.modified: list[str] = []   # 修改文件
        self.deleted: list[str] = []    # 删除文件

    @property
    def changed_files(self) -> list[str]:
        """需要包含在补丁包中的文件（新增 + 修改）"""
        return self.added + self.modified

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.modified or self.deleted)

    def summary(self) -> str:
        lines = [
            f"  新增: {len(self.added)} 个文件",
            f"  修改: {len(self.modified)} 个文件",
            f"  删除: {len(self.deleted)} 个文件",
        ]
        return "\n".join(lines)


def diff_manifests(old_manifest: dict, new_manifest: dict) -> DiffResult:
    """
    对比两个 manifest，找出差异。

    Args:
        old_manifest: 旧版本 manifest
        new_manifest: 新版本 manifest

    Returns:
        DiffResult
    """
    old_files = old_manifest.get("files", {})
    new_files = new_manifest.get("files", {})

    result = DiffResult()

    for path, new_hash in new_files.items():
        if path not in old_files:
            result.added.append(path)
        elif old_files[path] != new_hash:
            result.modified.append(path)

    for path in old_files:
        if path not in new_files:
            result.deleted.append(path)

    return result


# ============================================================
# 补丁包构建
# ============================================================
def build_patch_zip(
    dist_folder: str,
    diff: DiffResult,
    output_path: str,
    new_manifest: dict,
) -> str:
    """
    将变化文件打成补丁 zip。

    zip 内容：
    - patch_manifest.json  （补丁元数据：版本号、变化文件列表、删除列表）
    - 所有新增/修改的文件（保持相对路径）

    Args:
        dist_folder: 新版本打包产物目录
        diff: 差异对比结果
        output_path: 输出 zip 路径
        new_manifest: 新版本 manifest（嵌入补丁包）

    Returns:
        输出文件路径
    """
    patch_meta = {
        "type": "patch",
        "version": new_manifest.get("version", ""),
        "build_time": new_manifest.get("build_time", ""),
        "added": diff.added,
        "modified": diff.modified,
        "deleted": diff.deleted,
    }

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # 写入补丁元数据
        zf.writestr(
            "patch_manifest.json",
            json.dumps(patch_meta, ensure_ascii=False, indent=2),
        )

        # 写入变化文件
        for rel_path in diff.changed_files:
            abs_path = os.path.join(dist_folder, rel_path.replace("/", os.sep))
            if os.path.exists(abs_path):
                zf.write(abs_path, rel_path)

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"  [patch] 补丁包: {output_path} ({size_mb:.2f} MB)")
    return output_path


# ============================================================
# 通用补丁包构建（方案B：一个包覆盖所有旧版本）
# ============================================================
def build_universal_patch(
    dist_folder: str,
    old_manifests: list,
    new_manifest: dict,
    output_path: str,
) -> dict:
    """
    构建通用补丁包，覆盖所有旧版本。

    取所有旧版 manifest 与新版的差异并集，打成一个 zip。
    zip 内含完整目标哈希表（target_files），客户端可用于校验。

    Args:
        dist_folder: 新版本打包产物目录
        old_manifests: [(version_str, manifest_dict), ...] 所有旧版 manifest
        new_manifest: 新版本 manifest
        output_path: 输出 zip 路径

    Returns:
        dict with min_version, file_path, size_mb, changed_count, deleted_count
        如果没有任何变化则返回 None
    """
    new_files = new_manifest.get("files", {})
    all_changed = set()
    all_deleted = set()
    min_version = None

    for old_ver, old_manifest in old_manifests:
        diff = diff_manifests(old_manifest, new_manifest)
        if not diff.has_changes:
            print(f"  [patch] V{old_ver} -> V{new_manifest.get('version', '?')} 无变化，跳过")
            continue
        print(f"  [patch] V{old_ver} 差异: +{len(diff.added)} ~{len(diff.modified)} -{len(diff.deleted)}")
        all_changed.update(diff.changed_files)
        all_deleted.update(diff.deleted)
        if min_version is None or _version_key(old_ver) < _version_key(min_version):
            min_version = old_ver

    if not all_changed and not all_deleted:
        return None

    # 被某些旧版标记为 deleted，但在新版中存在的文件不应删除
    all_deleted -= set(new_files.keys())

    target_version = new_manifest.get("version", "")
    patch_meta = {
        "type": "universal_patch",
        "version": target_version,
        "min_version": min_version or "",
        "build_time": new_manifest.get("build_time", ""),
        "target_files": new_files,
        "deleted": sorted(all_deleted),
        "included_files": sorted(all_changed),
    }

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "patch_manifest.json",
            json.dumps(patch_meta, ensure_ascii=False, indent=2),
        )
        for rel_path in sorted(all_changed):
            abs_path = os.path.join(dist_folder, rel_path.replace("/", os.sep))
            if os.path.exists(abs_path):
                zf.write(abs_path, rel_path)

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"  [patch] 通用补丁包: {os.path.basename(output_path)} ({size_mb:.2f} MB)")
    print(f"  [patch] 覆盖范围: V{min_version}+ -> V{target_version}")
    print(f"  [patch] 包含: {len(all_changed)} 个文件, 删除: {len(all_deleted)} 个文件")

    return {
        "min_version": min_version,
        "file_path": output_path,
        "size_mb": round(size_mb, 2),
        "changed_count": len(all_changed),
        "deleted_count": len(all_deleted),
    }


# ============================================================
# CLI 入口
# ============================================================
def cmd_manifest(args):
    """子命令：生成 manifest"""
    dist_folder = args.dist_folder
    if not os.path.isdir(dist_folder):
        print(f"[错误] 目录不存在: {dist_folder}")
        sys.exit(1)

    manifest = generate_manifest(dist_folder)
    output = args.output or os.path.join(
        os.path.dirname(dist_folder), f"manifest-V{manifest['version']}.json"
    )
    save_manifest(manifest, output)


def cmd_patch(args):
    """子命令：对比 + 生成补丁包"""
    old_manifest_path = args.old_manifest
    new_dist_folder = args.new_dist_folder

    if not os.path.isfile(old_manifest_path):
        print(f"[错误] 旧版 manifest 不存在: {old_manifest_path}")
        sys.exit(1)
    if not os.path.isdir(new_dist_folder):
        print(f"[错误] 新版目录不存在: {new_dist_folder}")
        sys.exit(1)

    # 加载旧 manifest
    old_manifest = load_manifest(old_manifest_path)
    print(f"  旧版本: V{old_manifest.get('version', '?')}")

    # 生成新 manifest
    new_manifest = generate_manifest(new_dist_folder)
    print(f"  新版本: V{new_manifest.get('version', '?')}")

    # 对比
    diff = diff_manifests(old_manifest, new_manifest)
    if not diff.has_changes:
        print("  [跳过] 没有文件变化，无需生成补丁包。")
        return

    print(f"\n  差异统计:")
    print(diff.summary())

    # 生成补丁包
    from version import APP_NAME_EN, APP_VERSION
    output = args.output or os.path.join(
        os.path.dirname(new_dist_folder),
        f"{APP_NAME_EN}-V{APP_VERSION}-patch.zip",
    )
    build_patch_zip(new_dist_folder, diff, output, new_manifest)

    # 同时保存新版 manifest（供下次对比）
    new_manifest_path = os.path.join(
        os.path.dirname(new_dist_folder),
        f"manifest-V{new_manifest['version']}.json",
    )
    save_manifest(new_manifest, new_manifest_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="增量补丁包构建工具")
    sub = parser.add_subparsers(dest="command")

    # manifest 子命令
    p_manifest = sub.add_parser("manifest", help="生成文件清单")
    p_manifest.add_argument("dist_folder", help="打包产物目录")
    p_manifest.add_argument("--output", "-o", help="输出 manifest 路径")

    # patch 子命令
    p_patch = sub.add_parser("patch", help="对比并生成补丁包")
    p_patch.add_argument("old_manifest", help="旧版 manifest.json 路径")
    p_patch.add_argument("new_dist_folder", help="新版打包产物目录")
    p_patch.add_argument("--output", "-o", help="输出补丁包路径")

    args = parser.parse_args()
    if args.command == "manifest":
        cmd_manifest(args)
    elif args.command == "patch":
        cmd_patch(args)
    else:
        parser.print_help()
