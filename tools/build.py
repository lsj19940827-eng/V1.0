# -*- coding: utf-8 -*-
"""
一键打包脚本

将渠系水力计算系统打包为独立的 Windows 可执行程序。
同事不需要安装 Python，解压即可使用。

用法（在项目根目录 V1.0 下运行）：
    python tools/build.py              # 打包（生成 zip，发给同事即可）
    python tools/build.py --clean      # 清理上次的构建产物

前置条件（只需安装一次）：
    pip install pyinstaller
"""

import argparse
import os
import shutil
import subprocess
import sys
import zipfile

# ============================================================
# 配置区（每次发版时改这里的版本号）
# ============================================================
APP_NAME = "渠系水力计算综合系统"
APP_NAME_EN = "CanalHydraulicCalc"
APP_VERSION = "1.0.0"

# ============================================================
# 路径（build.py 位于 tools/ 下，项目根目录在上一级）
# ============================================================
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST_DIR = os.path.join(PROJECT_ROOT, "dist")
BUILD_DIR = os.path.join(PROJECT_ROOT, "build")
MAIN_SCRIPT = os.path.join(PROJECT_ROOT, "main.py")
ICON_FILE = os.path.join(PROJECT_ROOT, "icon.ico")


# ============================================================
# 构建流程
# ============================================================
def build():
    print(f"{'=' * 60}")
    print(f"  {APP_NAME} 打包工具")
    print(f"  版本: V{APP_VERSION}")
    print(f"{'=' * 60}")

    # 清理旧的构建
    for d in [DIST_DIR, BUILD_DIR]:
        if os.path.exists(d):
            shutil.rmtree(d, ignore_errors=True)

    # ---- 构建 PyInstaller 参数 ----
    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",                      # 不询问确认
        "--clean",                          # 清理临时文件
        "--windowed",                       # 隐藏控制台窗口
        f"--name={APP_NAME_EN}",            # 输出 exe 名称
        f"--distpath={DIST_DIR}",           # 输出目录
        f"--workpath={BUILD_DIR}",          # 工作目录
        f"--specpath={BUILD_DIR}",          # spec 文件目录
    ]

    # 图标
    if os.path.exists(ICON_FILE):
        args.append(f"--icon={ICON_FILE}")

    # ---- 需要隐式导入的包（PyInstaller 可能扫描不到的） ----
    hidden_imports = [
        "PySide6",
        "qfluentwidgets",
        "pandas",
        "openpyxl",
        "matplotlib",
        "matplotlib.backends.backend_qtagg",
        "ezdxf",
        "PIL",
    ]
    for mod in hidden_imports:
        args.append(f"--hidden-import={mod}")

    # ---- 添加数据文件 ----
    sep = ";"  # Windows 用分号分隔 src;dest

    # 项目子目录（源码 + 资源）
    data_dirs = [
        (os.path.join(PROJECT_ROOT, "渠系断面设计"), "渠系断面设计"),
        (os.path.join(PROJECT_ROOT, "推求水面线"), "推求水面线"),
        (os.path.join(PROJECT_ROOT, "渠系建筑物断面计算"), "渠系建筑物断面计算"),
        (os.path.join(PROJECT_ROOT, "倒虹吸水力计算系统"), "倒虹吸水力计算系统"),
        (os.path.join(PROJECT_ROOT, "data"), "data"),
        (os.path.join(PROJECT_ROOT, "docs"), "docs"),
    ]
    for src, dest in data_dirs:
        if os.path.exists(src):
            args.append(f"--add-data={src}{sep}{dest}")

    # 入口文件
    args.append(MAIN_SCRIPT)

    # ---- 执行 ----
    print(f"\n[1/2] 正在打包，请耐心等待（约 3~10 分钟）...\n")
    result = subprocess.run(args, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        print(f"\n[错误] 打包失败（退出码: {result.returncode}）")
        sys.exit(1)

    # ---- 打包为 zip ----
    print(f"\n[2/2] 打包完成，正在压缩为 zip...\n")
    dist_folder = os.path.join(DIST_DIR, APP_NAME_EN)
    if not os.path.exists(dist_folder):
        print("[错误] 未找到打包产物")
        sys.exit(1)

    zip_name = f"{APP_NAME_EN}-V{APP_VERSION}"
    zip_path = os.path.join(DIST_DIR, f"{zip_name}.zip")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(dist_folder):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.join(
                    zip_name,
                    os.path.relpath(file_path, dist_folder),
                )
                zf.write(file_path, arcname)

    size_mb = os.path.getsize(zip_path) / (1024 * 1024)

    # ---- 自动清理中间文件，保持文件夹整洁 ----
    shutil.rmtree(dist_folder, ignore_errors=True)   # dist 下的解压文件夹
    shutil.rmtree(BUILD_DIR, ignore_errors=True)      # build 中间文件

    print(f"{'=' * 60}")
    print(f"  打包完成!")
    print(f"  文件: {zip_path}")
    print(f"  大小: {size_mb:.1f} MB")
    print(f"")
    print(f"  把这个 zip 通过微信/QQ 发给同事，")
    print(f"  同事解压后双击 {APP_NAME_EN}.exe 即可使用。")
    print(f"{'=' * 60}")


def clean():
    """清理构建产物"""
    for d in [DIST_DIR, BUILD_DIR]:
        if os.path.exists(d):
            print(f"  清理: {d}")
            shutil.rmtree(d, ignore_errors=True)
    # 清理 Nuitka 残留
    for f in ["nuitka-crash-report.xml"]:
        p = os.path.join(PROJECT_ROOT, f)
        if os.path.exists(p):
            os.remove(p)
    print("  清理完成")


# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=f"{APP_NAME} 打包工具")
    parser.add_argument("--clean", action="store_true", help="清理构建产物")
    args = parser.parse_args()

    if args.clean:
        clean()
    else:
        build()
