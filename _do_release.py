# -*- coding: utf-8 -*-
"""临时脚本：完成 V1.0.8.2 发布的剩余步骤（3-6）"""

import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
import urllib.parse
from datetime import date

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from version import APP_VERSION, APP_NAME_EN
from repo_config import GITHUB_OWNER, GITHUB_REPO, GIST_ID, DOWNLOAD_PROXIES

VERSION = APP_VERSION  # 1.0.8.2


def load_token():
    env_file = os.path.join(PROJECT_ROOT, ".env")
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("GITHUB_TOKEN="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError("GITHUB_TOKEN not found in .env")


def github_api(method, url, token, data=None, raw_body=None,
               content_type="application/json"):
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
        with urllib.request.urlopen(req, timeout=120) as resp:
            resp_body = resp.read().decode("utf-8")
            return json.loads(resp_body) if resp_body else {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        print(f"  [API 错误] {e.code}: {err_body[:500]}")
        raise


def proxied_url(url):
    if not url or not url.startswith("https://github.com/"):
        return url
    for prefix in DOWNLOAD_PROXIES:
        if prefix:
            return prefix + url
    return url


def main():
    token = load_token()

    # 验证 token
    print("验证 GitHub Token...", end=" ", flush=True)
    try:
        github_api("GET", "https://api.github.com/user", token)
        print("OK")
    except Exception:
        print("FAIL")
        sys.exit(1)

    # ---- 步骤 3：Git commit + tag + push ----
    print(f"\n{'='*60}")
    print(f"  [步骤 3/6] Git commit + tag v{VERSION}")
    print(f"{'='*60}\n")

    def run(cmd):
        print(f"  $ {cmd}")
        subprocess.run(cmd, cwd=PROJECT_ROOT, shell=True, check=True)

    run("git add -A")
    run(f'git commit -m "release: v{VERSION}"')
    run(f"git tag v{VERSION}")

    branch = subprocess.run(
        "git rev-parse --abbrev-ref HEAD",
        cwd=PROJECT_ROOT, shell=True, capture_output=True, text=True
    ).stdout.strip() or "master"
    run(f"git push origin {branch}")
    run(f"git push origin v{VERSION}")

    # ---- 步骤 4：创建 GitHub Release ----
    print(f"\n{'='*60}")
    print(f"  [步骤 4/6] 创建 GitHub Release v{VERSION}")
    print(f"{'='*60}\n")

    release_url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
    release_data = {
        "tag_name": f"v{VERSION}",
        "name": f"V{VERSION}",
        "body": f"V{VERSION} 版本发布",
        "draft": False,
        "prerelease": False,
    }
    release = github_api("POST", release_url, token, data=release_data)
    print(f"  Release 创建成功: {release.get('html_url', '')}")

    # ---- 步骤 5：上传附件 ----
    print(f"\n{'='*60}")
    print(f"  [步骤 5/6] 上传发布包到 GitHub...")
    print(f"{'='*60}\n")

    upload_url_template = release.get("upload_url", "")
    base_upload_url = upload_url_template.split("{")[0]
    dist_dir = os.path.join(PROJECT_ROOT, "dist")

    urls = {}

    full_zip = os.path.join(dist_dir, f"{APP_NAME_EN}-V{VERSION}.zip")
    patch_zip = os.path.join(dist_dir, f"{APP_NAME_EN}-V{VERSION}-patch.zip")

    for label, filepath in [("全量包", full_zip), ("补丁包", patch_zip)]:
        if not os.path.exists(filepath):
            print(f"  [跳过] {label} 不存在: {filepath}")
            continue

        filename = os.path.basename(filepath)
        size_mb = os.path.getsize(filepath) / (1024 * 1024)
        print(f"  上传: {filename} ({size_mb:.1f} MB)")

        url = f"{base_upload_url}?name={urllib.parse.quote(filename)}"
        curl = r"C:\Windows\System32\curl.exe"
        cmd = [
            curl, "-#",
            "-X", "POST",
            "-H", f"Authorization: token {token}",
            "-H", "Accept: application/vnd.github+json",
            "-H", "Content-Type: application/zip",
            "--data-binary", f"@{filepath}",
            "-o", "-",
            url,
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE)
        if result.returncode != 0:
            print(f"  [上传失败] curl 退出码 {result.returncode}")
            sys.exit(1)

        resp = json.loads(result.stdout.decode("utf-8", errors="replace"))
        dl_url = resp.get("browser_download_url", "")
        if not dl_url:
            print(f"  [上传失败] 响应: {str(resp)[:300]}")
            sys.exit(1)

        print(f"  ✓ {dl_url}")
        if "patch" in filename:
            urls["patch_url"] = dl_url
        else:
            urls["download_url"] = dl_url

    # ---- 步骤 6：更新 Gist ----
    print(f"\n{'='*60}")
    print(f"  [步骤 6/6] 更新 GitHub Gist version.json")
    print(f"{'='*60}\n")

    patch_info_file = os.path.join(dist_dir, "patch-info.json")
    patch_min_version = ""
    patch_size_mb = 0
    if os.path.exists(patch_info_file):
        with open(patch_info_file, "r", encoding="utf-8") as f:
            pi = json.load(f)
        patch_min_version = pi.get("min_version", "")
        patch_size_mb = pi.get("size_mb", 0)

    full_size = os.path.getsize(full_zip) / (1024 * 1024) if os.path.exists(full_zip) else 0

    version_data = {
        "latest_version": VERSION,
        "download_url": proxied_url(urls.get("download_url", "")),
        "download_url_direct": urls.get("download_url", ""),
        "changelog": f"V{VERSION} 版本发布",
        "release_date": date.today().isoformat(),
        "min_version": "1.0.0",
        "file_size_mb": round(full_size, 1),
    }

    if "patch_url" in urls:
        version_data["patch_url"] = proxied_url(urls["patch_url"])
        version_data["patch_url_direct"] = urls["patch_url"]
        version_data["patch_size_mb"] = patch_size_mb
        version_data["min_patch_version"] = patch_min_version
        version_data["patch_base_version"] = patch_min_version

    gist_url = f"https://api.github.com/gists/{GIST_ID}"
    gist_data = {
        "files": {
            "version.json": {
                "content": json.dumps(version_data, ensure_ascii=False, indent=4)
            }
        }
    }
    github_api("PATCH", gist_url, token, data=gist_data)
    print(f"  Gist 更新成功!")
    print(f"  内容:\n{json.dumps(version_data, ensure_ascii=False, indent=2)}")

    # 完成
    print(f"\n{'='*60}")
    print(f"  V{VERSION} 发版完成！用户可通过「检查更新」获取新版本。")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
