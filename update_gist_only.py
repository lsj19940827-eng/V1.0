# -*- coding: utf-8 -*-
"""仅更新 Gist version.json（不打包、不创建 Release）"""
import json
import urllib.request
from datetime import date
from version import APP_VERSION
from repo_config import GIST_ID, DOWNLOAD_PROXIES

def load_env():
    with open(".env", "r", encoding="utf-8") as f:
        for line in f:
            if line.strip() and "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                if k.strip() == "GITHUB_TOKEN":
                    return v.strip()
    raise ValueError("未找到 GITHUB_TOKEN")

def proxied_url(url):
    for prefix in DOWNLOAD_PROXIES:
        if prefix:
            return prefix + url
    return url

token = load_env()
download_url_direct = f"https://github.com/lsj19940827-eng/V1.0/releases/download/v{APP_VERSION}/CanalHydraulicCalc-V{APP_VERSION}.zip"
patch_url_direct = f"https://github.com/lsj19940827-eng/V1.0/releases/download/v{APP_VERSION}/CanalHydraulicCalc-V{APP_VERSION}-patch.zip"

version_data = {
    "latest_version": APP_VERSION,
    "download_url": proxied_url(download_url_direct),
    "download_url_direct": download_url_direct,
    "patch_url": proxied_url(patch_url_direct),
    "patch_url_direct": patch_url_direct,
    "changelog": f"V{APP_VERSION} 版本发布",
    "release_date": date.today().isoformat(),
    "min_version": "1.0.0",
    "file_size_mb": 302.0,
    "patch_size_mb": 35.0,
    "min_patch_version": "1.0.7",
    "patch_base_version": "1.0.7",
}

url = f"https://api.github.com/gists/{GIST_ID}"
data = {"files": {"version.json": {"content": json.dumps(version_data, ensure_ascii=False, indent=4)}}}
req = urllib.request.Request(url, data=json.dumps(data).encode(), method="PATCH")
req.add_header("Authorization", f"token {token}")
req.add_header("Content-Type", "application/json")

with urllib.request.urlopen(req) as resp:
    print(f"Gist updated to V{APP_VERSION}")
    print(json.dumps(version_data, ensure_ascii=False, indent=2))
