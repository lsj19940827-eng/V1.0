# -*- coding: utf-8 -*-
"""
一键正式发版脚本

流程：bump 版本 -> 打包 -> git commit/tag -> 创建 GitHub Release -> 上传 zip -> 更新正式 Gist。
仅支持 master 分支正式发布；不再提供预发布/测试 Gist 通道。
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date


def _configure_stdio():
    """Avoid crashing on consoles that cannot encode some Unicode symbols."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None or not hasattr(stream, "reconfigure"):
            continue
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass


_configure_stdio()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
PROJECT_VENV_PYTHON = os.path.join(PROJECT_ROOT, ".venv", "Scripts", "python.exe")
sys.path.insert(0, PROJECT_ROOT)

from version import APP_NAME_EN
from repo_config import GITHUB_OWNER, GITHUB_REPO, GIST_ID, DOWNLOAD_PROXIES
from tools import patch_policy, release_snapshot


def _proxied_url(url: str) -> str:
    if not url or not url.startswith("https://github.com/"):
        return url
    for prefix in DOWNLOAD_PROXIES:
        if prefix:
            return prefix + url
    return url


def _load_env() -> dict:
    env_file = os.path.join(PROJECT_ROOT, ".env")
    env = {}
    if os.path.exists(env_file):
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    env[key.strip()] = value.strip()
    return env


def _get_token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "") or _load_env().get("GITHUB_TOKEN", "")
    if not token:
        print("[错误] 未找到 GITHUB_TOKEN")
        sys.exit(1)
    return token


def _current_branch() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    branch = (result.stdout or "").strip()
    return branch or "master"


def _project_python() -> str:
    if os.path.exists(PROJECT_VENV_PYTHON):
        return PROJECT_VENV_PYTHON
    return sys.executable


def _has_staged_changes() -> bool:
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=PROJECT_ROOT,
        check=False,
    )
    return result.returncode != 0


def _load_universal_patch(dist_dir: str, version: str) -> dict:
    patch_info_file = os.path.join(dist_dir, "patch-info.json")
    if os.path.exists(patch_info_file):
        try:
            with open(patch_info_file, "r", encoding="utf-8") as f:
                patch_info = json.load(f)
            patch_name = patch_info.get("patch_name", "")
            min_version = patch_info.get("min_version", "")
            if patch_name:
                path = os.path.join(dist_dir, patch_name)
                if os.path.exists(path):
                    return {
                        "file_path": path,
                        "min_version": min_version,
                        "size_mb": round(os.path.getsize(path) / (1024 * 1024), 2),
                        "changed_count": patch_info.get("changed_count", 0),
                        "deleted_count": patch_info.get("deleted_count", 0),
                        "source_versions": patch_info.get("source_versions", []),
                    }
        except Exception as exc:
            print(f"  [patch] 解析 patch-info.json 失败: {exc}")

    fallback = os.path.join(dist_dir, f"{APP_NAME_EN}-V{version}-patch.zip")
    if os.path.exists(fallback):
        return {
            "file_path": fallback,
            "min_version": "",
            "size_mb": round(os.path.getsize(fallback) / (1024 * 1024), 2),
        }
    return {}


def _build_version_data(version: str, urls: dict, assets: dict, changelog: str) -> dict:
    """统一构造正式通道 version.json 内容。"""
    full_size = float(
        assets.get("full_size_mb")
        or (os.path.getsize(assets["full_zip"]) / (1024 * 1024))
    )
    download_url_direct = urls.get("download_url", "")
    version_data = {
        "latest_version": version,
        "download_url": download_url_direct,
        "download_url_direct": download_url_direct,
        "download_url_proxy": _proxied_url(download_url_direct),
        "download_sha256": release_snapshot.sha256_file(assets["full_zip"]),
        "changelog": changelog or f"V{version} 版本发布",
        "release_date": date.today().isoformat(),
        "min_version": "1.0.0",
        "file_size_mb": round(full_size, 1),
        "channel": "stable",
    }
    patch_zip = assets.get("patch_zip", "")
    if "patch_url" in urls and patch_zip and os.path.exists(patch_zip):
        should_skip_patch, skip_reason = patch_policy.should_skip_universal_patch(
            {
                "changed_count": assets.get("patch_changed_count", 0),
                "deleted_count": assets.get("patch_deleted_count", 0),
                "size_mb": assets.get("patch_size_mb", 0),
                "source_versions": assets.get("patch_source_versions", []),
            },
            full_size_mb=full_size,
        )
        if should_skip_patch:
            print(f"  [patch] 不写入 version.json：{skip_reason}")
            return version_data
        patch_url_direct = urls["patch_url"]
        version_data["patch_url"] = patch_url_direct
        version_data["patch_url_direct"] = patch_url_direct
        version_data["patch_url_proxy"] = _proxied_url(patch_url_direct)
        version_data["patch_size_mb"] = assets.get("patch_size_mb", 0)
        version_data["min_patch_version"] = assets.get("patch_min_version", "")
        version_data["patch_base_version"] = assets.get("patch_min_version", "")
        version_data["patch_sha256"] = release_snapshot.sha256_file(patch_zip)
    return version_data


def _github_api(method: str, url: str, token: str, data=None, raw_body=None,
                content_type: str = "application/json") -> dict:
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
    elif raw_body is not None:
        body = raw_body

    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", APP_NAME_EN)
    if body is not None:
        req.add_header("Content-Type", content_type)

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = resp.read().decode("utf-8")
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        print(f"  [API 错误] {exc.code}: {err_body[:500]}")
        raise


def _upload_release_asset(upload_url: str, file_path: str, token: str) -> str:
    filename = os.path.basename(file_path)
    size_mb = os.path.getsize(file_path) / (1024 * 1024)
    base_url = upload_url.split("{")[0]
    url = f"{base_url}?name={urllib.parse.quote(filename)}"

    print(f"  上传: {filename} ({size_mb:.1f} MB)")

    curl = r"C:\Windows\System32\curl.exe"
    cmd = [
        curl, "-#",
        "-X", "POST",
        "-H", f"Authorization: token {token}",
        "-H", "Accept: application/vnd.github+json",
        "-H", "Content-Type: application/zip",
        "--data-binary", f"@{file_path}",
        "-o", "-",
        url,
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"curl upload failed: exit {result.returncode}")

    resp = json.loads(result.stdout.decode("utf-8", errors="replace"))
    download_url = resp.get("browser_download_url", "")
    if not download_url:
        raise RuntimeError(f"upload response missing browser_download_url: {resp}")

    print("  [OK]")
    return download_url


def step_bump_version(level: str) -> str:
    from build import bump_version
    return bump_version(level)


def step_get_current_version() -> str:
    import importlib
    import version as version_module

    importlib.reload(version_module)
    return version_module.APP_VERSION


def step_build() -> dict:
    print(f"\n{'=' * 60}")
    print("  [步骤 2/6] 打包...")
    print(f"{'=' * 60}\n")

    python_exe = _project_python()
    print(f"  [环境] 使用解释器: {python_exe}")

    result = subprocess.run(
        [python_exe, os.path.join(SCRIPT_DIR, "build.py")],
        cwd=PROJECT_ROOT,
        check=False,
    )
    if result.returncode != 0:
        print("[错误] 打包失败")
        sys.exit(1)

    import importlib
    import version as version_module

    importlib.reload(version_module)
    app_version = version_module.APP_VERSION
    dist_dir = os.path.join(PROJECT_ROOT, "dist")
    full_zip = os.path.join(dist_dir, f"{APP_NAME_EN}-V{app_version}.zip")
    if not os.path.exists(full_zip):
        print(f"[错误] 找不到全量包: {full_zip}")
        sys.exit(1)

    assets = {
        "full_zip": full_zip,
        "full_size_mb": os.path.getsize(full_zip) / (1024 * 1024),
        "manifest_path": os.path.join(dist_dir, f"manifest-V{app_version}.json"),
    }
    patch_info = _load_universal_patch(dist_dir, app_version)
    if patch_info.get("file_path"):
        assets["patch_zip"] = patch_info["file_path"]
        assets["patch_min_version"] = patch_info.get("min_version", "")
        assets["patch_size_mb"] = patch_info.get("size_mb", 0)
        assets["patch_changed_count"] = patch_info.get("changed_count", 0)
        assets["patch_deleted_count"] = patch_info.get("deleted_count", 0)
        assets["patch_source_versions"] = patch_info.get("source_versions", [])
        min_ver = patch_info.get("min_version") or "?"
        print(f"  [patch] 通用补丁包: {os.path.basename(patch_info['file_path'])}")
        print(f"  [patch] 覆盖范围: V{min_ver}+ -> V{app_version} ({patch_info['size_mb']:.2f} MB)")
    return assets


def step_git_commit_and_tag(tag_name: str, branch: str, commit_message: str):
    print(f"\n{'=' * 60}")
    print(f"  [步骤 3/6] Git commit + tag {tag_name}")
    print(f"{'=' * 60}\n")

    def _run(cmd):
        print(f"  $ {' '.join(cmd)}")
        subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)

    _run(["git", "add", "-A"])
    if _has_staged_changes():
        _run(["git", "commit", "-m", commit_message])
    else:
        print("  [提示] 当前无可提交变更，跳过 commit。")

    tag_exists = subprocess.run(
        ["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag_name}"],
        cwd=PROJECT_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0
    if tag_exists:
        print(f"[错误] 标签已存在: {tag_name}")
        sys.exit(1)

    _run(["git", "tag", tag_name])
    _run(["git", "push", "origin", branch])
    _run(["git", "push", "origin", tag_name])


def step_create_release(tag_name: str, release_name: str, token: str, changelog: str) -> dict:
    print(f"\n{'=' * 60}")
    print(f"  [步骤 4/6] 创建 GitHub 正式 Release {tag_name}")
    print(f"{'=' * 60}\n")

    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
    data = {
        "tag_name": tag_name,
        "name": release_name,
        "body": changelog or f"{release_name} 版本发布",
        "draft": False,
        "prerelease": False,
    }
    release = _github_api("POST", url, token, data=data)
    print(f"  Release 创建成功: {release.get('html_url', '')}")
    return release


def step_upload_assets(release: dict, assets: dict, token: str) -> dict:
    print(f"\n{'=' * 60}")
    print("  [步骤 5/6] 上传发布包到 GitHub...")
    print(f"{'=' * 60}\n")

    upload_url = release.get("upload_url", "")
    urls = {"download_url": _upload_release_asset(upload_url, assets["full_zip"], token)}
    if "patch_zip" in assets and os.path.exists(assets["patch_zip"]):
        should_skip_patch, skip_reason = patch_policy.should_skip_universal_patch(
            {
                "changed_count": assets.get("patch_changed_count", 0),
                "deleted_count": assets.get("patch_deleted_count", 0),
                "size_mb": assets.get("patch_size_mb", 0),
                "source_versions": assets.get("patch_source_versions", []),
            },
            full_size_mb=assets.get("full_size_mb", 0),
        )
        if should_skip_patch:
            print(f"  [patch] 跳过上传通用补丁包：{skip_reason}")
        else:
            urls["patch_url"] = _upload_release_asset(upload_url, assets["patch_zip"], token)
    return urls


def step_update_gist(version: str, urls: dict, assets: dict, token: str,
                     changelog: str, gist_id: str) -> dict:
    print(f"\n{'=' * 60}")
    print("  [步骤 6/6] 更新 GitHub Gist version.json（正式通道）")
    print(f"{'=' * 60}\n")

    version_data = _build_version_data(version, urls, assets, changelog)

    gist_url = f"https://api.github.com/gists/{gist_id}"
    data = {"files": {"version.json": {"content": json.dumps(version_data, ensure_ascii=False, indent=4)}}}
    _github_api("PATCH", gist_url, token, data=data)
    print(f"  Gist 更新成功! (gist={gist_id})")
    print(f"  内容: {json.dumps(version_data, ensure_ascii=False, indent=2)}")
    return version_data


def release(level: str, changelog: str = "", no_bump: bool = False, tag_suffix: str = ""):
    token = _get_token()

    print("验证 GitHub Token...", end=" ", flush=True)
    try:
        _github_api("GET", "https://api.github.com/user", token)
        print("OK")
    except Exception:
        print("FAIL")
        print("[错误] GitHub Token 无效或网络不可用")
        sys.exit(1)
    print()

    branch = _current_branch()
    if branch != "master":
        print(f"[错误] 当前分支为 {branch}，只有 master 允许执行正式发版。")
        print("       请切换到 master 后再执行 release。")
        sys.exit(1)

    print(f"{'=' * 60}")
    print("  发布上下文")
    print(f"{'=' * 60}")
    print(f"  branch      : {branch}")
    print(f"  no_bump     : {no_bump}")
    print(f"{'=' * 60}\n")

    print(f"{'=' * 60}")
    if no_bump:
        print("  [步骤 1/6] 跳过版本递增（--no-bump）")
        print(f"{'=' * 60}\n")
        new_ver = step_get_current_version()
        print(f"  当前版本: {new_ver}\n")
    else:
        print(f"  [步骤 1/6] 递增版本号 ({level})")
        print(f"{'=' * 60}\n")
        new_ver = step_bump_version(level)

    suffix = (tag_suffix or "").strip()
    tag_name = f"v{new_ver}" + (f"-{suffix}" if suffix else "")
    release_name = f"V{new_ver}" + (f" ({suffix})" if suffix else "")
    commit_message = f"release: {tag_name}"

    assets = step_build()
    step_git_commit_and_tag(tag_name, branch, commit_message)
    release_obj = step_create_release(tag_name, release_name, token, changelog)
    urls = step_upload_assets(release_obj, assets, token)
    version_data = step_update_gist(new_ver, urls, assets, token, changelog, gist_id=GIST_ID)
    snapshot_file = release_snapshot.write_release_snapshot(
        version=new_ver,
        tag_name=tag_name,
        full_zip_path=assets["full_zip"],
        full_download_url=urls.get("download_url", ""),
        version_data=version_data,
        manifest_path=assets.get("manifest_path", ""),
        patch_zip_path=assets.get("patch_zip", "") if urls.get("patch_url") else "",
        patch_download_url=urls.get("patch_url", ""),
    )
    print(f"  - 发布快照: {snapshot_file}")

    print(f"\n{'=' * 60}")
    print(f"  {tag_name} 正式发布完成")
    print("  - GitHub: 已发布")
    print("  - Gist通道: prod")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="一键发版：bump -> build -> git -> release -> gist",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  python tools/release.py patch
  python tools/release.py hotfix
  python tools/release.py minor
  python tools/release.py patch -m "- 修复水面线问题"
  python tools/release.py patch --no-bump --tag-suffix rc.20260317.1
""",
    )
    parser.add_argument("level", choices=["hotfix", "patch", "minor", "major"],
                        help="版本递增级别（--no-bump 时仅作兼容占位）")
    parser.add_argument("-m", "--message", default="",
                        help="更新日志（用 \\n 分隔多条）")
    parser.add_argument("--no-bump", action="store_true",
                        help="不递增 version.py，保留当前版本号")
    parser.add_argument("--tag-suffix", default="",
                        help="tag 后缀，例如 rc.20260317.1，生成 vX.Y.Z-<suffix>")

    args = parser.parse_args()
    release(args.level, args.message, no_bump=args.no_bump, tag_suffix=args.tag_suffix)
