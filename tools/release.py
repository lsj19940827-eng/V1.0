# -*- coding: utf-8 -*-
"""
一键正式发版脚本

流程：bump 版本 -> 打包 -> git commit/tag -> 创建 GitHub Release -> 上传 zip -> 按需上传 Gitee 补丁镜像 -> 更新正式 Gist。
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
GITEE_RELEASE_ATTACHMENT_LIMIT_MB = 100.0
sys.path.insert(0, PROJECT_ROOT)

from version import APP_NAME_EN
from repo_config import (
    GITHUB_OWNER,
    GITHUB_REPO,
    GIST_ID,
    DOWNLOAD_PROXIES,
    GITEE_OWNER,
    GITEE_REPO,
    GITEE_API_BASE,
    GITHUB_VERSION_URL,
)
from tools import patch_policy, release_snapshot, release_acceptance


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


def _get_gitee_token() -> str:
    """读取 Gitee 私人令牌；只允许来自本地环境或 .env。"""
    token = os.environ.get("GITEE_TOKEN", "") or _load_env().get("GITEE_TOKEN", "")
    if not token:
        print("[错误] 未找到 GITEE_TOKEN")
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
        # 不把未经完整回读的代理地址写进正式清单；默认复用已核验直连地址。
        "download_url_proxy": urls.get("download_url_proxy", download_url_direct),
        "download_url_mirrors": list(urls.get("download_url_mirrors", []) or []),
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
        version_data["patch_url_proxy"] = urls.get("patch_url_proxy", patch_url_direct)
        version_data["patch_url_mirrors"] = list(urls.get("patch_url_mirrors", []) or [])
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


def _gitee_api(method: str, url: str, token: str, data=None, raw_body=None,
               content_type: str = "application/x-www-form-urlencoded") -> dict:
    """调用 Gitee OpenAPI；附件上传用 curl 走 multipart，避免把大包读入内存。"""
    if content_type == "multipart/form-data":
        if not data or not data.get("file_path"):
            raise RuntimeError("Gitee 附件上传缺少 file_path")
        curl = r"C:\Windows\System32\curl.exe"
        cmd = [
            curl, "-sS",
            "-X", method,
            "-F", f"access_token={token}",
            "-F", f"file=@{data['file_path']}",
            "-o", "-",
            url,
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"gitee curl upload failed: exit {result.returncode}")
        payload = result.stdout.decode("utf-8", errors="replace")
        return json.loads(payload) if payload else {}

    body = None
    request_url = url
    if data is not None:
        form_data = dict(data)
        form_data["access_token"] = token
        body = urllib.parse.urlencode(form_data).encode("utf-8")
    elif raw_body is not None:
        body = raw_body
    else:
        sep = "&" if "?" in request_url else "?"
        request_url = f"{request_url}{sep}access_token={urllib.parse.quote(token)}"

    req = urllib.request.Request(request_url, data=body, method=method)
    req.add_header("User-Agent", APP_NAME_EN)
    if body is not None:
        req.add_header("Content-Type", content_type)

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = resp.read().decode("utf-8")
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        print(f"  [Gitee API 错误] {exc.code}: {err_body[:500]}")
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


def _upload_gitee_release_asset(release_id: int, file_path: str, token: str) -> str:
    """上传 Gitee Release 附件并返回浏览器下载地址。"""
    filename = os.path.basename(file_path)
    size_mb = os.path.getsize(file_path) / (1024 * 1024)
    url = (
        f"{GITEE_API_BASE}/repos/{urllib.parse.quote(GITEE_OWNER, safe='')}/"
        f"{urllib.parse.quote(GITEE_REPO, safe='')}/releases/{release_id}/attach_files"
    )
    print(f"  Gitee 上传: {filename} ({size_mb:.1f} MB)")
    resp = _gitee_api(
        "POST",
        url,
        token,
        data={"file_path": file_path},
        content_type="multipart/form-data",
    )
    download_url = resp.get("browser_download_url", "")
    if not download_url:
        raise RuntimeError(f"gitee upload response missing browser_download_url: {resp}")
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
    return collect_assets(dist_dir, app_version)


def collect_assets(dist_dir: str, app_version: str) -> dict:
    """只读取候选产物，只验收模式不运行构建或版本递增。"""
    full_zip = os.path.join(dist_dir, f"{APP_NAME_EN}-V{app_version}.zip")
    release_acceptance.require(os.path.isfile(full_zip), f"找不到候选全量包: {full_zip}")

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
    for remote in ("origin", "gitee"):
        _run(["git", "push", remote, branch])
        _run(["git", "push", remote, tag_name])


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


def step_create_gitee_release_and_upload_assets(
    tag_name: str,
    release_name: str,
    changelog: str,
    assets: dict,
    token: str,
    branch: str = "master",
) -> dict:
    """创建 Gitee Release 并上传合格补丁包，返回 version.json 的镜像字段。"""
    print(f"\n{'=' * 60}")
    print(f"  [Gitee] 检查补丁镜像 {tag_name}")
    print(f"{'=' * 60}\n")

    patch_zip = assets.get("patch_zip", "")
    if not patch_zip or not os.path.exists(patch_zip):
        print("  [Gitee] 未生成补丁包，跳过 Gitee 附件上传。")
        return {}

    patch_size_mb = float(
        assets.get("patch_size_mb")
        or (os.path.getsize(patch_zip) / (1024 * 1024))
    )
    if patch_size_mb > GITEE_RELEASE_ATTACHMENT_LIMIT_MB:
        print(
            "  [Gitee] 跳过补丁包："
            f"{patch_size_mb:.2f} MB 超过 Gitee 单附件 {GITEE_RELEASE_ATTACHMENT_LIMIT_MB:.0f} MB 限制。"
        )
        return {}

    should_skip_patch, skip_reason = patch_policy.should_skip_universal_patch(
        {
            "changed_count": assets.get("patch_changed_count", 0),
            "deleted_count": assets.get("patch_deleted_count", 0),
            "size_mb": patch_size_mb,
            "source_versions": assets.get("patch_source_versions", []),
        },
        full_size_mb=assets.get("full_size_mb", 0),
    )
    if should_skip_patch:
        print(f"  [Gitee] 跳过补丁包：{skip_reason}")
        return {}

    release_url = (
        f"{GITEE_API_BASE}/repos/{urllib.parse.quote(GITEE_OWNER, safe='')}/"
        f"{urllib.parse.quote(GITEE_REPO, safe='')}/releases"
    )
    release_obj = _gitee_api(
        "POST",
        release_url,
        token,
        data={
            "tag_name": tag_name,
            "name": release_name,
            "body": changelog or f"{release_name} 版本发布",
            "prerelease": "false",
            "target_commitish": branch,
        },
    )
    release_id = release_obj.get("id")
    if not release_id:
        raise RuntimeError(f"Gitee Release 创建失败：{release_obj}")

    return {
        "patch_url_mirrors": [
            _upload_gitee_release_asset(int(release_id), patch_zip, token)
        ],
    }


def load_gist_version(token: str, gist_id: str = GIST_ID) -> dict:
    data = _github_api("GET", f"https://api.github.com/gists/{gist_id}", token)
    content = data.get("files", {}).get("version.json", {}).get("content", "")
    release_acceptance.require(content, "正式 Gist 缺少 version.json")
    return json.loads(content)


def save_gist_version(token: str, version_data: dict, gist_id: str = GIST_ID):
    _github_api("PATCH", f"https://api.github.com/gists/{gist_id}", token, data={
        "files": {"version.json": {"content": json.dumps(version_data, ensure_ascii=False, indent=4)}}})


def step_update_gist(version: str, urls: dict, assets: dict, token: str,
                     changelog: str, gist_id: str, *, acceptance=None, previous_version_data=None) -> dict:
    print(f"\n{'=' * 60}")
    print("  [步骤 6/6] 更新 GitHub Gist version.json（正式通道）")
    print(f"{'=' * 60}\n")

    version_data = _build_version_data(version, urls, assets, changelog)
    return activate_version_data(version_data, token, acceptance=acceptance,
                                 previous_version_data=previous_version_data, gist_id=gist_id)


def activate_version_data(version_data, token, *, acceptance, previous_version_data,
                          gist_id=GIST_ID, after_acceptance=None):
    """清单切换、线上验收与失败恢复共用入口，补丁回补也不能绕过。"""
    release_acceptance.require(acceptance is not None and previous_version_data is not None,
                               "缺少发布验收上下文，禁止直接切换 Gist")
    release_acceptance.require_remote_receipt(acceptance, version_data)
    previous = previous_version_data
    acceptance.record("previous_manifest", previous)
    try:
        release_acceptance.require(load_gist_version(token, gist_id) == previous,
                                   "正式清单被其它发布改变，停止切换")
        print("[步骤 6/6] 切换已通过远端验收的正式更新清单", flush=True)
        acceptance.record("switch", {"status": "attempting", "version_data": version_data})
        save_gist_version(token, version_data, gist_id)
        release_acceptance.require(load_gist_version(token, gist_id) == version_data, "Gist 回写核验失败")
        print("[验收 U09] 从正式旧版应用内完成线上下载、安装与新版启动...", flush=True)
        release_acceptance.verify_online(acceptance, version_data, GITHUB_VERSION_URL)
        if after_acceptance:
            after_acceptance()
        acceptance.record("status", "passed")
    except BaseException as exc:
        # 写入结果不明确时也核对清单；发生并发修改则停止，避免覆盖其它人的发布。
        recovery = {"status": "not_needed"}
        try:
            current = load_gist_version(token, gist_id)
            if current == version_data:
                save_gist_version(token, previous, gist_id)
                release_acceptance.require(load_gist_version(token, gist_id) == previous, "旧清单恢复核验失败")
                visible = release_acceptance.wait_for_manifest(GITHUB_VERSION_URL, previous)
                recovery = {"status": "restored_previous_manifest", "ordinary_manifest": visible}
            elif current != previous:
                recovery = {"status": "conflict", "message": "清单已由其它发布改变，未覆盖"}
        except Exception as recovery_exc:
            recovery = {"status": "failed", "error_type": type(recovery_exc).__name__}
        acceptance.record("failure", {"status": "failed", "error_type": type(exc).__name__, "recovery": recovery})
        acceptance.record("status", "failed")
        raise release_acceptance.AcceptanceError(
            f"上线验收未通过，发布停止；清单恢复结果：{recovery['status']}；记录：{acceptance.output}") from exc
    return version_data


def release(level: str, changelog: str = "", no_bump: bool = False, tag_suffix: str = "", *,
            candidate_dir: str = ""):
    token = _get_token()
    gitee_token = _get_gitee_token()

    print("验证 GitHub Token...", end=" ", flush=True)
    try:
        _github_api("GET", "https://api.github.com/user", token)
        print("OK")
    except Exception:
        print("FAIL")
        print("[错误] GitHub Token 无效或网络不可用")
        sys.exit(1)
    print()

    print("验证 Gitee Token...", end=" ", flush=True)
    try:
        _gitee_api("GET", f"{GITEE_API_BASE}/user", gitee_token)
        print("OK")
    except Exception:
        print("FAIL")
        print("[错误] Gitee Token 无效或网络不可用")
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

    if candidate_dir:
        release_acceptance.require(no_bump, "重用候选包时版本必须与已构建版本一致")
        print(f"[候选包] 重用现有产物并重新执行全部发版验收：{candidate_dir}")
        assets = collect_assets(candidate_dir, new_ver)
    else:
        assets = step_build()
    if assets.get("patch_zip"):
        release_acceptance.require(assets.get("patch_min_version") == patch_policy.DEFAULT_MIN_VERSION,
                                   "候选补丁覆盖下限与正式发版设置不一致")
    print("[验收 U01-U07] 检查候选包并运行正式 EXE 升级、回退及恢复验收...", flush=True)
    # 本地产物验收在 Git commit/tag/push 和所有发布写操作之前执行。
    previous = load_gist_version(token)
    previous_version = previous.get("latest_version")
    if previous_version == new_ver:
        previous_version = None
    acceptance = release_acceptance.prepare_local(
        new_ver, assets, root=PROJECT_ROOT, python=_project_python(), previous_version=previous_version)
    assets = acceptance.assets
    acceptance.assert_unchanged()
    step_git_commit_and_tag(tag_name, branch, commit_message)
    acceptance.assert_unchanged()
    release_obj = step_create_release(tag_name, release_name, token, changelog)
    acceptance.assert_unchanged()
    urls = step_upload_assets(release_obj, assets, token)
    acceptance.assert_unchanged()
    urls.update(
        step_create_gitee_release_and_upload_assets(
            tag_name,
            release_name,
            changelog,
            assets,
            gitee_token,
            branch=branch,
        )
    )
    version_data = _build_version_data(new_ver, urls, assets, changelog)
    print("[验收 U08] 完整回读所有正式下载地址并校验 SHA256...", flush=True)
    release_acceptance.verify_remote(acceptance, version_data)
    def snapshot_after_acceptance():
        snapshot_file = release_snapshot.write_release_snapshot(
            version=new_ver, tag_name=tag_name, full_zip_path=assets["full_zip"],
            full_download_url=urls.get("download_url", ""), version_data=version_data,
            manifest_path=assets.get("manifest_path", ""),
            patch_zip_path=assets.get("patch_zip", "") if urls.get("patch_url") else "",
            patch_download_url=urls.get("patch_url", ""))
        print(f"  - 发布快照: {snapshot_file}")
    activate_version_data(version_data, token, acceptance=acceptance, previous_version_data=previous,
                          after_acceptance=snapshot_after_acceptance)
    print(f"  - 更新验收记录: {acceptance.output / 'acceptance.json'}")

    print(f"\n{'=' * 60}")
    print(f"  {tag_name} 正式发布完成")
    print("  - GitHub: 已发布")
    print("  - Gitee: 已同步镜像")
    print("  - Gist通道: prod")
    print(f"{'=' * 60}\n")


def main(argv=None):
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
    parser.add_argument("level", nargs="?", choices=["hotfix", "patch", "minor", "major"],
                        help="版本递增级别（--no-bump 时仅作兼容占位）")
    parser.add_argument("-m", "--message", default="",
                        help="更新日志（用 \\n 分隔多条）")
    parser.add_argument("--no-bump", action="store_true",
                        help="不递增 version.py，保留当前版本号")
    parser.add_argument("--tag-suffix", default="",
                        help="tag 后缀，例如 rc.20260317.1，生成 vX.Y.Z-<suffix>")

    parser.add_argument("--verify-only", action="store_true", help="只验收现有候选产物，不发布、不修改版本或 Git")
    parser.add_argument("--assets-dir", default=os.path.join(PROJECT_ROOT, "dist"), help="只验收模式的候选产物目录")
    parser.add_argument("--version", help="只验收模式的目标版本，默认当前源码版本")
    parser.add_argument("--use-existing-candidate", action="store_true",
                        help="按当前版本重用候选包，完整重跑所有发版验收")
    args = parser.parse_args(argv)
    try:
        if args.verify_only:
            if args.use_existing_candidate:
                parser.error("只验收模式直接用 --assets-dir 指定候选产物")
            target = args.version or step_get_current_version()
            assets = collect_assets(os.path.abspath(args.assets_dir), target)
            result = release_acceptance.prepare_local(target, assets, root=PROJECT_ROOT, python=_project_python())
            print(f"本地验收通过，未执行发布：{result.output / 'acceptance.json'}")
        else:
            if args.level is None:
                parser.error("正式发布必须提供版本级别；只验收请使用 --verify-only")
            if args.version:
                parser.error("--version 仅供只验收模式使用")
            if args.use_existing_candidate and not args.no_bump:
                parser.error("--use-existing-candidate 必须与 --no-bump 一起使用")
            options = {"candidate_dir": os.path.abspath(args.assets_dir)} if args.use_existing_candidate else {}
            release(args.level, args.message, no_bump=args.no_bump, tag_suffix=args.tag_suffix, **options)
        return 0
    except (release_acceptance.AcceptanceError, subprocess.TimeoutExpired) as exc:
        print(f"[验收未通过] {exc}\n已停止后续发布步骤。", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"[发布停止] {type(exc).__name__}，请查看当前步骤的日志处理失败项。", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
