# -*- coding: utf-8 -*-
"""
仓库与更新源配置 —— 所有地址、ID集中管理

修改仓库信息只需改这一个文件，updater.py / release.py / release_gui.py 都从这里读取。
"""

# ============================================================
# GitHub（源代码仓库 + 外网更新源）
# ============================================================
GITHUB_OWNER = "lsj19940827-eng"
GITHUB_REPO = "V1.0"
GITHUB_REPO_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
GIST_ID = "5b065a668e99faddcec02415cb423d96"
GITHUB_VERSION_URL = (
    f"https://gist.githubusercontent.com/"
    f"{GITHUB_OWNER}/{GIST_ID}/raw/version.json"
)

# ============================================================
# GitHub Release 下载代理（国内加速）
# 按优先级排列，空字符串表示直连 GitHub（兜底）
# 代理 URL 变换：proxy_prefix + original_github_url
# ============================================================
DOWNLOAD_PROXIES = [
    "https://ghproxy.com/",
    "https://mirror.ghproxy.com/",
    "https://gh.ddlc.top/",
    "",  # 直连兜底
]
