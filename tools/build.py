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
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile

# ============================================================
# 配置区（版本号从 version.py 读取，发版时只需修改 version.py）
# ============================================================
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from version import APP_VERSION, APP_NAME, APP_NAME_EN

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _version_key(v: str) -> tuple:
    m = _VERSION_RE.match((v or "").strip())
    if not m:
        return (0, 0, 0)
    return tuple(int(x) for x in m.groups())


def bump_version(level: str) -> str:
    """
    自动递增 version.py 中的版本号。

    Args:
        level: 'patch' | 'minor' | 'major'

    Returns:
        新版本号字符串
    """
    global APP_VERSION
    parts = list(int(x) for x in APP_VERSION.split("."))
    if level == "major":
        parts = [parts[0] + 1, 0, 0]
    elif level == "minor":
        parts = [parts[0], parts[1] + 1, 0]
    else:  # patch
        parts = [parts[0], parts[1], parts[2] + 1]
    new_ver = ".".join(str(x) for x in parts)

    ver_file = os.path.join(PROJECT_ROOT, "version.py")
    with open(ver_file, "r", encoding="utf-8") as f:
        content = f.read()
    content = content.replace(
        f'APP_VERSION = "{APP_VERSION}"',
        f'APP_VERSION = "{new_ver}"',
    )
    with open(ver_file, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"  [版本] {APP_VERSION} → {new_ver}")
    APP_VERSION = new_ver
    return new_ver

# ============================================================
# 不需要的 Qt 模块（删除可显著减小包体积）
# 保留：QtCore/Gui/Widgets/WebEngine/Network/Svg/PrintSupport/OpenGL/Qml/Quick（WebEngine依赖）
# ============================================================
QT_UNUSED_PREFIXES = [
    "Qt63DAnim", "Qt63DCore", "Qt63DExtras",
    "Qt63DInput", "Qt63DLogic", "Qt63DRender",
    "Qt6Bluetooth",
    "Qt6Charts",
    "Qt6DataVisualization",
    "Qt6Location",
    "Qt6Nfc",
    "Qt6RemoteObjects",
    "Qt6Sensors",
    "Qt6SerialBus", "Qt6SerialPort",
    "Qt6Test",
    "Qt6VirtualKeyboard",
    "Qt6Designer",
    "Qt6Help",
    "Qt6SpatialAudio",
    "Qt6TextToSpeech",
    "Qt6Quick3D",
    "Qt6LabsAnimation",
    "Qt6LabsFolderListModel",
    "Qt6LabsQmlModels",
    "Qt6LabsSettings",
    "Qt6LabsSharedImage",
    "Qt6LabsWavefrontMesh",
]

PYSIDE6_UNUSED_MODULES = [
    "PySide6.Qt3DAnimation", "PySide6.Qt3DCore", "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DRender",
    "PySide6.QtBluetooth", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtLocation", "PySide6.QtNfc", "PySide6.QtRemoteObjects",
    "PySide6.QtSensors", "PySide6.QtSerialBus", "PySide6.QtSerialPort",
    "PySide6.QtTest", "PySide6.QtVirtualKeyboard", "PySide6.QtDesigner",
    "PySide6.QtHelp", "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech",
    "PySide6.QtQuick3D",
]

# ============================================================
# 路径（build.py 位于 tools/ 下，项目根目录在上一级）
# ============================================================
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST_DIR = os.path.join(PROJECT_ROOT, "dist")
BUILD_DIR = os.path.join(PROJECT_ROOT, "build")
MANIFEST_STORE_DIR = os.path.join(PROJECT_ROOT, ".release-manifests")
MAIN_SCRIPT = os.path.join(PROJECT_ROOT, "main.py")
ICON_FILE = os.path.join(PROJECT_ROOT, "icon.ico")



def _clean_unused_qt_dlls(dist_folder):
    """删除 _internal/PySide6/ 中不需要的 Qt DLL，显著减小包体积。"""
    pyside6_dir = os.path.join(dist_folder, "_internal", "PySide6")
    if not os.path.isdir(pyside6_dir):
        # PyInstaller 5.x 以下没有 _internal
        pyside6_dir = os.path.join(dist_folder, "PySide6")
    if not os.path.isdir(pyside6_dir):
        return

    removed_count = 0
    removed_bytes = 0
    for fname in os.listdir(pyside6_dir):
        if not fname.endswith(".dll"):
            continue
        for prefix in QT_UNUSED_PREFIXES:
            if fname.startswith(prefix):
                fpath = os.path.join(pyside6_dir, fname)
                removed_bytes += os.path.getsize(fpath)
                os.remove(fpath)
                removed_count += 1
                break
    if removed_count:
        print(f"  [瘦身] 已删除 {removed_count} 个无用 Qt DLL，"
              f"释放 {removed_bytes / 1024 / 1024:.1f} MB")


def _clean_py_sources(dist_folder):
    """删除 dist 目录中项目相关的 .py 源码文件（双保险防止源码泄露）"""
    project_dirs = [
        "渠系断面设计", "渠系建筑物断面计算", "推求水面线",
        "倒虹吸水力计算系统", "土石方计算",
    ]
    removed = 0
    for pdir in project_dirs:
        # PyInstaller 6.x 将依赖放在 _internal/ 下
        for base in [dist_folder, os.path.join(dist_folder, "_internal")]:
            target = os.path.join(base, pdir)
            if not os.path.isdir(target):
                continue
            for root, _dirs, files in os.walk(target):
                for f in files:
                    if f.endswith('.py'):
                        os.remove(os.path.join(root, f))
                        removed += 1
    if removed:
        print(f"  [安全] 已清理 {removed} 个残留 .py 源码文件")


# ============================================================
# 构建流程
# ============================================================
def _clean_excel_temp_files(directory):
    """删除目录中 Excel 临时锁文件（~$开头），避免打包时 PermissionError。"""
    if not os.path.isdir(directory):
        return
    removed = 0
    for fname in os.listdir(directory):
        if fname.startswith("~$"):
            fpath = os.path.join(directory, fname)
            try:
                os.remove(fpath)
                removed += 1
            except OSError:
                pass
    if removed:
        print(f"  [清理] 已删除 {directory} 中 {removed} 个 Excel 临时文件")


def build(bump: str = None):
    if bump:
        bump_version(bump)

    print(f"{'=' * 60}")
    print(f"  {APP_NAME} 打包工具")
    print(f"  版本: V{APP_VERSION}")
    print(f"{'=' * 60}")

    # 清理 data 目录中的 Excel 临时锁文件
    _clean_excel_temp_files(os.path.join(PROJECT_ROOT, "data"))

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

    # ---- 模块搜索路径 ----
    # 项目根目录：让 PyInstaller 发现 渠系断面设计、土石方计算 等正式包
    # 子目录：渠系建筑物断面计算、倒虹吸水力计算系统、推求水面线 没有 __init__.py，
    #         代码通过 sys.path.insert() 后以顶层模块名导入（如 from 明渠设计 import ...）
    search_paths = [
        PROJECT_ROOT,
        os.path.join(PROJECT_ROOT, "渠系建筑物断面计算"),
        os.path.join(PROJECT_ROOT, "倒虹吸水力计算系统"),
        os.path.join(PROJECT_ROOT, "推求水面线"),
    ]
    for p in search_paths:
        args.append(f"--paths={p}")

    # ---- 需要隐式导入的包（PyInstaller 静态分析可能扫描不到的） ----
    hidden_imports = [
        # 授权校验与更新
        "license_checker",
        "version",
        "updater",
        # 第三方库
        "PySide6",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineCore",
        "PySide6.QtSvg",
        "qfluentwidgets",
        "pandas",
        "openpyxl",
        "matplotlib",
        "matplotlib.backends.backend_qtagg",
        "matplotlib.backends.backend_svg",
        "matplotlib.backends.backend_qt5agg",
        "ezdxf",
        "PIL",
        "shapely", "shapely.geometry",
        "triangle",
        "startinpy",
        "scipy", "scipy.spatial",
        "docx", "latex2mathml", "lxml",
        # ---- 渠系建筑物断面计算（无 __init__.py，sys.path hack 导入） ----
        "明渠设计",
        "渡槽设计",
        "隧洞设计",
        "矩形暗涵设计",
        "生成断面汇总表",
        # ---- 倒虹吸水力计算系统（无 __init__.py，sys.path hack 导入） ----
        "siphon_models",
        "siphon_hydraulics",
        "siphon_coefficients",
        "dxf_parser",
        "spatial_merger",
        # ---- 推求水面线子包（无根 __init__.py，sys.path hack 导入） ----
        "models", "models.data_models", "models.enums",
        "core", "core.calculator", "core.geometry_calc", "core.hydraulic_calc",
        "shared", "shared.shared_data_manager", "shared.k12_images_data",
        "config", "config.constants", "config.default_data",
        "utils", "utils.excel_io", "utils.siphon_extractor",
        "managers", "managers.siphon_manager",
        # ---- 推求水面线命名空间包式导入（部分代码用 from 推求水面线.xxx import） ----
        "推求水面线.models", "推求水面线.models.data_models", "推求水面线.models.enums",
        "推求水面线.shared", "推求水面线.shared.k12_images_data",
    ]
    for mod in hidden_imports:
        args.append(f"--hidden-import={mod}")

    # ---- 排除明确不需要的 PySide6 子模块（减少分析范围） ----
    for mod in PYSIDE6_UNUSED_MODULES:
        args.append(f"--exclude-module={mod}")

    # ---- 收集正式 Python 包的子模块（有 __init__.py，编译为字节码） ----
    collect_submodules = [
        "渠系断面设计",
        "土石方计算",
    ]
    for mod in collect_submodules:
        args.append(f"--collect-submodules={mod}")

    # ---- 收集第三方包的数据文件（字体/图标/模板等） ----
    # ezdxf 内置字体和 DXF 模板； qfluentwidgets 内置图标和 QSS 样式表
    args.append("--collect-data=ezdxf")
    args.append("--collect-data=matplotlib")
    args.append("--collect-all=qfluentwidgets")

    # ---- 添加资源文件（仅图片/图标/JSON/Excel 等，不包含 .py 源码） ----
    sep = ";"  # Windows 用分号分隔 src;dest

    data_entries = [
        # 项目数据文件（模板等）
        (os.path.join(PROJECT_ROOT, "data"), "data"),
        # UI 图标与 Logo
        (os.path.join(PROJECT_ROOT, "渠系断面设计", "resources"),
         os.path.join("渠系断面设计", "resources")),
        (os.path.join(PROJECT_ROOT, "倒虹吸水力计算系统", "resources"),
         os.path.join("倒虹吸水力计算系统", "resources")),
        (os.path.join(PROJECT_ROOT, "推求水面线", "resources"),
         os.path.join("推求水面线", "resources")),
        # JSON 配置文件
        (os.path.join(PROJECT_ROOT, "渠系断面设计", "default_project.siphon.json"),
         "渠系断面设计"),
    ]
    for src, dest in data_entries:
        if os.path.exists(src):
            args.append(f"--add-data={src}{sep}{dest}")

    # 入口文件
    args.append(MAIN_SCRIPT)

    # ---- 执行 ----
    print(f"\n[1/3] 正在打包，请耐心等待（约 3~10 分钟）...\n")
    result = subprocess.run(args, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        print(f"\n[错误] 打包失败（退出码: {result.returncode}）")
        sys.exit(1)

    # ---- 清理残留的 .py 源码文件（双保险） ----
    _clean_py_sources(os.path.join(DIST_DIR, APP_NAME_EN))

    # ---- 删除用不到的 Qt 模块 DLL ----
    _clean_unused_qt_dlls(os.path.join(DIST_DIR, APP_NAME_EN))

    # ---- 生成文件清单 manifest.json（供增量补丁对比） ----
    print(f"\n[2/3] 生成文件清单 manifest.json...\n")
    dist_folder = os.path.join(DIST_DIR, APP_NAME_EN)
    if not os.path.exists(dist_folder):
        print("[错误] 未找到打包产物")
        sys.exit(1)

    from patch_builder import generate_manifest, save_manifest, load_manifest
    from patch_builder import diff_manifests, build_patch_zip

    new_manifest = generate_manifest(dist_folder)
    manifest_name = f"manifest-V{APP_VERSION}.json"
    manifest_path = os.path.join(DIST_DIR, manifest_name)
    save_manifest(new_manifest, manifest_path)
    os.makedirs(MANIFEST_STORE_DIR, exist_ok=True)
    store_manifest_path = os.path.join(MANIFEST_STORE_DIR, manifest_name)
    save_manifest(new_manifest, store_manifest_path)

    # ---- 自动检测旧版 manifest，生成多基线增量补丁包 ----
    patch_path = None
    patch_assets = []
    old_manifests = sorted(
        [
            f for f in os.listdir(MANIFEST_STORE_DIR)
            if f.startswith("manifest-V") and f.endswith(".json")
            and f != f"manifest-V{APP_VERSION}.json"
        ],
        key=lambda x: _version_key(x.replace("manifest-V", "").replace(".json", "")),
    )

    patch_info_path = os.path.join(DIST_DIR, "patch-info.json")
    if os.path.exists(patch_info_path):
        os.remove(patch_info_path)

    if old_manifests:
        for manifest_name in old_manifests:
            old_manifest_file = os.path.join(MANIFEST_STORE_DIR, manifest_name)
            base_ver = manifest_name.replace("manifest-V", "").replace(".json", "")
            print(f"  [patch] 旧版清单: {manifest_name}")
            old_manifest = load_manifest(old_manifest_file)
            diff = diff_manifests(old_manifest, new_manifest)
            if not diff.has_changes:
                print(f"  [patch] V{base_ver} -> V{APP_VERSION} 无变化，跳过")
                continue

            print(diff.summary())
            patch_name = f"{APP_NAME_EN}-V{APP_VERSION}-from-V{base_ver}-patch.zip"
            patch_out = os.path.join(DIST_DIR, patch_name)
            build_patch_zip(dist_folder, diff, patch_out, new_manifest)
            patch_assets.append(
                {
                    "base_version": base_ver,
                    "file_name": patch_name,
                    "file_path": patch_out,
                    "size_mb": round(os.path.getsize(patch_out) / (1024 * 1024), 2),
                }
            )

        if patch_assets:
            patch_assets.sort(key=lambda x: _version_key(x["base_version"]))
            primary = patch_assets[-1]

            # 兼容旧流程：继续产出单补丁文件名
            legacy_patch_name = f"{APP_NAME_EN}-V{APP_VERSION}-patch.zip"
            legacy_patch_path = os.path.join(DIST_DIR, legacy_patch_name)
            if os.path.abspath(primary["file_path"]) != os.path.abspath(legacy_patch_path):
                shutil.copy2(primary["file_path"], legacy_patch_path)
            patch_path = legacy_patch_path

            patch_info = {
                "latest_version": APP_VERSION,
                "generated_at": new_manifest.get("build_time", ""),
                "base_version": primary["base_version"],
                "patch_name": legacy_patch_name,
                "primary_base_version": primary["base_version"],
                "primary_file_name": primary["file_name"],
                "patches": patch_assets,
            }
            with open(patch_info_path, "w", encoding="utf-8") as f:
                json.dump(patch_info, f, ensure_ascii=False, indent=2)
            print(f"  [patch] 已生成 {len(patch_assets)} 个增量补丁")
        else:
            print("  [patch] 所有旧版本对比均无变化，跳过补丁包生成。")
    else:
        print("  [patch] 未找到旧版 manifest，跳过补丁包（首次打包）。")

    # ---- 打包为全量 zip ----
    print(f"\n[3/3] 压缩为全量 zip...\n")

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
    print(f"  全量包: {zip_path} ({size_mb:.1f} MB)")
    if patch_path and os.path.exists(patch_path):
        patch_mb = os.path.getsize(patch_path) / (1024 * 1024)
        print(f"  补丁包: {patch_path} ({patch_mb:.2f} MB)")
    print(f"  清  单: {manifest_path}")
    print(f"  基线清单仓库: {MANIFEST_STORE_DIR}")
    print(f"")
    print(f"  发版步骤:")
    print(f"  1. 上传全量 zip + 补丁 zip 到 GitHub Releases")
    print(f"  2. 更新 Gist 中的 version.json（含 patch_url）")
    print(f"  3. 保留 {os.path.basename(manifest_path)} 供下次增量对比")
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
    parser.add_argument("--bump", choices=["patch", "minor", "major"],
                        help="打包前自动递增版本号 (patch/minor/major)")
    args = parser.parse_args()

    if args.clean:
        clean()
    else:
        build(bump=args.bump)
