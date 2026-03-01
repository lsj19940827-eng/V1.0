# -*- coding: utf-8 -*-
"""
重传 v1.0.6 Release 附件 + 更新 Gist（使用 curl 流式上传）
用于上传超时后的断点补救
"""
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
import urllib.parse
from datetime import date

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

from repo_config import GITHUB_OWNER, GITHUB_REPO, GIST_ID
from version import APP_VERSION, APP_NAME_EN

VERSION = APP_VERSION  # 1.0.6
CHANGELOG = "有压管道模块重构：计算核心升级、面板重设计、支持报告导出"

DIST_DIR = os.path.join(PROJECT_ROOT, "dist")
FULL_ZIP   = os.path.join(DIST_DIR, f"CanalHydraulicCalc-V{VERSION}.zip")
PATCH_V104 = os.path.join(DIST_DIR, f"CanalHydraulicCalc-V{VERSION}-from-V1.0.4-patch.zip")
PATCH_V105 = os.path.join(DIST_DIR, f"CanalHydraulicCalc-V{VERSION}-from-V1.0.5-patch.zip")

CURL = r"C:\Windows\System32\curl.exe"


def _load_token():
    env_path = os.path.join(PROJECT_ROOT, ".env")
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("GITHUB_TOKEN="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError("GITHUB_TOKEN not found in .env")


def _api(method, url, token, data=None):
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", APP_NAME_EN)
    if body:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _upload_curl(upload_url, file_path, token):
    """用 curl 流式上传，显示进度条，不把文件载入内存"""
    filename = os.path.basename(file_path)
    size_mb = os.path.getsize(file_path) / 1024 / 1024
    base_url = upload_url.split("{")[0]
    url = f"{base_url}?name={urllib.parse.quote(filename)}"

    print(f"\n  上传: {filename} ({size_mb:.1f} MB)")

    cmd = [
        CURL, "-#",           # 显示进度条
        "-X", "POST",
        "-H", f"Authorization: token {token}",
        "-H", "Accept: application/vnd.github+json",
        "-H", "Content-Type: application/zip",
        "--data-binary", f"@{file_path}",
        "-o", "-",            # 响应输出到 stdout
        url,
    ]

    result = subprocess.run(cmd, capture_output=False, stdout=subprocess.PIPE, text=False)
    if result.returncode != 0:
        raise RuntimeError(f"curl 上传失败，退出码 {result.returncode}")

    resp_json = json.loads(result.stdout.decode("utf-8", errors="replace"))
    if "browser_download_url" not in resp_json:
        raise RuntimeError(f"上传响应异常: {resp_json}")

    print(f"  ✓ {resp_json['browser_download_url']}")
    return resp_json["browser_download_url"]


def main():
    token = _load_token()
    print(f"Token OK, 目标版本: v{VERSION}\n")

    # 1. 获取已有 Release
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/tags/v{VERSION}"
    release = _api("GET", url, token)
    upload_url = release["upload_url"]
    print(f"Release id={release['id']}, 已有附件: {[a['name'] for a in release.get('assets', [])] or '(空)'}\n")

    # 2. 删除已存在的同名附件（防止 422 冲突）
    for asset in release.get("assets", []):
        del_url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/assets/{asset['id']}"
        req = urllib.request.Request(del_url, method="DELETE")
        req.add_header("Authorization", f"token {token}")
        req.add_header("User-Agent", APP_NAME_EN)
        urllib.request.urlopen(req, timeout=30)
        print(f"  已删除旧附件: {asset['name']}")

    # 3. 上传文件（curl 流式）
    urls = {}
    urls["download_url"] = _upload_curl(upload_url, FULL_ZIP, token)

    patch_urls = {}
    for base_ver, path in [("1.0.4", PATCH_V104), ("1.0.5", PATCH_V105)]:
        if os.path.exists(path):
            patch_urls[base_ver] = _upload_curl(upload_url, path, token)

    if patch_urls:
        urls["patches"] = patch_urls
        primary = sorted(patch_urls.keys())[-1]
        urls["patch_url"] = patch_urls[primary]
        urls["patch_base_version"] = primary

    # 4. 更新 Gist
    print("\n  更新 Gist version.json ...")
    full_size = os.path.getsize(FULL_ZIP) / 1024 / 1024
    version_data = {
        "latest_version": VERSION,
        "download_url": urls.get("download_url", ""),
        "changelog": CHANGELOG,
        "release_date": date.today().isoformat(),
        "min_version": "1.0.0",
        "file_size_mb": round(full_size, 1),
    }
    patch_map = {}
    for base_ver, patch_url in patch_urls.items():
        path = PATCH_V104 if base_ver == "1.0.4" else PATCH_V105
        size_mb = os.path.getsize(path) / 1024 / 1024 if os.path.exists(path) else 0
        patch_map[base_ver] = {"url": patch_url, "size_mb": round(size_mb, 1)}
    if patch_map:
        version_data["patches"] = patch_map
        primary = sorted(patch_map.keys())[-1]
        version_data["patch_url"] = patch_map[primary]["url"]
        version_data["patch_size_mb"] = patch_map[primary]["size_mb"]
        version_data["patch_base_version"] = primary

    gist_url = f"https://api.github.com/gists/{GIST_ID}"
    _api("PATCH", gist_url, token, data={
        "files": {"version.json": {"content": json.dumps(version_data, ensure_ascii=False, indent=4)}}
    })
    print("  Gist 更新成功!")
    print(f"\n{json.dumps(version_data, ensure_ascii=False, indent=2)}")
    print(f"\n✅  v{VERSION} 发版完成！")


if __name__ == "__main__":
    main()
