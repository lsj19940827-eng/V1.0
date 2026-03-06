# -*- coding: utf-8 -*-
"""上传文件到 GitHub Release"""
import json
import os
import subprocess
import urllib.request
from version import APP_VERSION
from repo_config import GITHUB_OWNER, GITHUB_REPO, DOWNLOAD_PROXIES

def load_env():
    with open(".env", "r", encoding="utf-8") as f:
        for line in f:
            if line.strip() and "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                if k.strip() == "GITHUB_TOKEN":
                    return v.strip()
    raise ValueError("GITHUB_TOKEN not found")

token = load_env()

# 获取 Release 信息
url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/tags/v{APP_VERSION}"
req = urllib.request.Request(url)
req.add_header("Authorization", f"token {token}")
with urllib.request.urlopen(req) as resp:
    release = json.loads(resp.read().decode())

upload_url = release["upload_url"].split("{")[0]

# 上传全量包
full_zip = f"dist/CanalHydraulicCalc-V{APP_VERSION}.zip"
filename = os.path.basename(full_zip)
size_mb = os.path.getsize(full_zip) / (1024 * 1024)
print(f"Uploading {filename} ({size_mb:.1f} MB)...")

curl = r"C:\Windows\System32\curl.exe"
cmd = [
    curl, "-#", "-X", "POST",
    "-H", f"Authorization: token {token}",
    "-H", "Content-Type: application/zip",
    "--data-binary", f"@{full_zip}",
    f"{upload_url}?name={filename}",
]
result = subprocess.run(cmd, capture_output=True)
resp = json.loads(result.stdout.decode())
download_url = resp["browser_download_url"]
print(f"Full package uploaded: {download_url}")

# 上传补丁包
patch_zip = f"dist/CanalHydraulicCalc-V{APP_VERSION}-patch.zip"
if os.path.exists(patch_zip):
    filename = os.path.basename(patch_zip)
    size_mb = os.path.getsize(patch_zip) / (1024 * 1024)
    print(f"Uploading {filename} ({size_mb:.1f} MB)...")
    cmd[-1] = f"{upload_url}?name={filename}"
    cmd[-2] = f"@{patch_zip}"
    result = subprocess.run(cmd, capture_output=True)
    resp = json.loads(result.stdout.decode())
    patch_url = resp["browser_download_url"]
    print(f"Patch uploaded: {patch_url}")
else:
    patch_url = None

print("\nDone!")
print(f"download_url: {download_url}")
if patch_url:
    print(f"patch_url: {patch_url}")
