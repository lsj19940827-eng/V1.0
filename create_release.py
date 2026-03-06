# -*- coding: utf-8 -*-
"""创建 GitHub Release（不上传文件）"""
import json
import urllib.request
from version import APP_VERSION
from repo_config import GITHUB_OWNER, GITHUB_REPO

def load_env():
    with open(".env", "r", encoding="utf-8") as f:
        for line in f:
            if line.strip() and "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                if k.strip() == "GITHUB_TOKEN":
                    return v.strip()
    raise ValueError("GITHUB_TOKEN not found")

token = load_env()
url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
data = {
    "tag_name": f"v{APP_VERSION}",
    "name": f"V{APP_VERSION}",
    "body": f"V{APP_VERSION} release",
    "draft": False,
    "prerelease": False,
}

req = urllib.request.Request(url, data=json.dumps(data).encode(), method="POST")
req.add_header("Authorization", f"token {token}")
req.add_header("Content-Type", "application/json")
req.add_header("Accept", "application/vnd.github+json")

try:
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read().decode())
        print(f"Release created: {result['html_url']}")
except urllib.error.HTTPError as e:
    print(f"Error: {e.code}")
    print(e.read().decode())
