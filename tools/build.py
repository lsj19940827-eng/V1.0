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
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from contextlib import contextmanager

# ============================================================
# 配置区（版本号从 version.py 读取，发版时只需修改 version.py）
# ============================================================
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from version import APP_VERSION, APP_NAME, APP_NAME_EN

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?$")
UNIVERSAL_PATCH_MIN_VERSION = "1.1.9"
MAX_PATCH_DELETED_COUNT = 100
MAX_PATCH_TOTAL_COVERAGE = 300


def _version_key(v: str) -> tuple:
    m = _VERSION_RE.match((v or "").strip())
    if not m:
        return (0, 0, 0)
    return tuple(int(x) for x in m.groups() if x is not None)


def _select_universal_patch_manifest_files(manifest_files, current_version: str) -> list[str]:
    """Keep only manifests that are still within the supported patch upgrade floor."""
    selected = []
    current_key = _version_key(current_version)
    min_key = _version_key(UNIVERSAL_PATCH_MIN_VERSION)

    for name in manifest_files:
        if not (name.startswith("manifest-V") and name.endswith(".json")):
            continue
        version = name.replace("manifest-V", "").replace(".json", "")
        version_key = _version_key(version)
        if version_key >= current_key:
            continue
        if version_key < min_key:
            continue
        selected.append(name)

    return sorted(
        selected,
        key=lambda x: _version_key(x.replace("manifest-V", "").replace(".json", "")),
    )


def _should_skip_universal_patch(patch_result: dict) -> tuple[bool, str]:
    """判断通用补丁是否覆盖过重，避免把高风险补丁发给用户。"""
    changed_count = int((patch_result or {}).get("changed_count", 0) or 0)
    deleted_count = int((patch_result or {}).get("deleted_count", 0) or 0)

    if deleted_count > MAX_PATCH_DELETED_COUNT:
        return (
            True,
            f"覆盖范围过大：deleted_count={deleted_count}，超过 {MAX_PATCH_DELETED_COUNT}",
        )

    total_coverage = changed_count + deleted_count
    if total_coverage > MAX_PATCH_TOTAL_COVERAGE:
        return (
            True,
            f"覆盖范围过大：changed+deleted={total_coverage}，超过 {MAX_PATCH_TOTAL_COVERAGE}",
        )

    return False, ""


def bump_version(level: str) -> str:
    """
    自动递增 version.py 中的版本号。

    Args:
        level: 'patch' | 'minor' | 'major' | 'hotfix'

    Returns:
        新版本号字符串
    """
    global APP_VERSION
    parts = [int(x) for x in APP_VERSION.split(".")]
    if len(parts) == 3:
        parts.append(0)

    if level == "major":
        parts = [parts[0] + 1, 0, 0, 0]
    elif level == "minor":
        parts = [parts[0], parts[1] + 1, 0, 0]
    elif level == "patch":
        parts = [parts[0], parts[1], parts[2] + 1, 0]
    else:  # hotfix
        parts = [parts[0], parts[1], parts[2], parts[3] + 1]

    new_ver = ".".join(str(x) for x in parts) if parts[3] > 0 else ".".join(str(x) for x in parts[:3])

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

# ------------------------------------------------------------
# 显式排除当前桌面应用未使用、但容易被静态分析误收入的可选 AI/视觉栈
# 触发链：scipy.optimize -> scipy._lib._array_api -> torch ->
#         torch.testing._internal.common_distributed -> transformers ->
#         transformers.video_utils / transformers.data.metrics -> cv2 / sklearn
# 这些依赖在当前项目源码中没有直接导入，但会显著放大全量包和补丁包。
# ------------------------------------------------------------
OPTIONAL_ML_EXCLUDES = [
    "torch",
    "transformers",
    "cv2",
    "sklearn",
]

# ============================================================
# 隐式导入分组
# 统一维护 PyInstaller 打包与打包前导入校验所依赖的模块清单。
# ============================================================
AUTH_AND_UPDATE_HIDDEN_IMPORTS = [
    "license_checker",
    "version",
    "updater",
]

THIRD_PARTY_HIDDEN_IMPORTS = [
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
    "matplotlib.backends.backend_pdf",
    "ezdxf",
    "PIL",
    "shapely",
    "shapely.geometry",
    "triangle",
    "startinpy",
    "scipy",
    "scipy.spatial",
    "scipy.optimize",
    "seaborn",
    "pypdf",
]

WORD_EXPORT_HIDDEN_IMPORTS = [
    "docx",
    "latex2mathml",
    "lxml",
]

PIP_INSTALL_NAME_OVERRIDES = {
    "docx": "python-docx",
}

PRESSURE_PIPE_DESIGN_HIDDEN_IMPORTS = [
    "有压管道设计",
]

CALC_CORE_HIDDEN_IMPORTS = [
    "明渠设计",
    "渡槽设计",
    "隧洞设计",
    "矩形暗涵设计",
    "生成断面汇总表",
]

SIPHON_CORE_HIDDEN_IMPORTS = [
    "siphon_models",
    "siphon_hydraulics",
    "siphon_coefficients",
    "dxf_parser",
    "spatial_merger",
]

WATER_PROFILE_UTIL_HIDDEN_IMPORTS = [
    "utils.excel_io",
    "utils.siphon_extractor",
    "utils.pressure_pipe_result_helpers",
]

WATER_PROFILE_CORE_HIDDEN_IMPORTS = [
    "models",
    "models.data_models",
    "models.enums",
    "core",
    "core.calculator",
    "core.geometry_calc",
    "core.hydraulic_calc",
    "shared",
    "shared.shared_data_manager",
    "shared.k12_images_data",
    "config",
    "config.constants",
    "config.default_data",
    "utils",
    *WATER_PROFILE_UTIL_HIDDEN_IMPORTS,
    "managers",
    "managers.siphon_manager",
]

WATER_PROFILE_NAMESPACE_HIDDEN_IMPORTS = [
    "推求水面线.utils",
    "推求水面线.utils.excel_io",
    "推求水面线.utils.siphon_extractor",
    "推求水面线.utils.pressure_pipe_common",
    "推求水面线.utils.pressure_pipe_extractor",
    "推求水面线.utils.pressure_pipe_longitudinal_utils",
    "推求水面线.utils.pressure_pipe_result_helpers",
    "推求水面线.models",
    "推求水面线.models.data_models",
    "推求水面线.models.enums",
    "推求水面线.shared",
    "推求水面线.shared.k12_images_data",
]


def get_hidden_imports() -> list[str]:
    """返回 PyInstaller 需要强制带入的隐式导入模块列表。"""
    return [
        *AUTH_AND_UPDATE_HIDDEN_IMPORTS,
        *THIRD_PARTY_HIDDEN_IMPORTS,
        *WORD_EXPORT_HIDDEN_IMPORTS,
        *PRESSURE_PIPE_DESIGN_HIDDEN_IMPORTS,
        *CALC_CORE_HIDDEN_IMPORTS,
        *SIPHON_CORE_HIDDEN_IMPORTS,
        *WATER_PROFILE_CORE_HIDDEN_IMPORTS,
        *WATER_PROFILE_NAMESPACE_HIDDEN_IMPORTS,
    ]


def get_verify_import_groups() -> dict[str, list[str]]:
    """返回打包前导入校验使用的模块分组。"""
    return {
        "授权与版本": list(AUTH_AND_UPDATE_HIDDEN_IMPORTS),
        "calc_渠系计算算法内核": [
            *CALC_CORE_HIDDEN_IMPORTS,
            *PRESSURE_PIPE_DESIGN_HIDDEN_IMPORTS,
        ],
        "倒虹吸水力计算系统": list(SIPHON_CORE_HIDDEN_IMPORTS),
        "推求水面线": [
            *WATER_PROFILE_CORE_HIDDEN_IMPORTS,
            *WATER_PROFILE_NAMESPACE_HIDDEN_IMPORTS,
        ],
        "第三方库": [
            "PySide6",
            "qfluentwidgets",
            "pandas",
            "openpyxl",
            "matplotlib",
            "ezdxf",
            "PIL",
            "scipy",
            "scipy.optimize",
        ],
        "Word导出依赖": list(WORD_EXPORT_HIDDEN_IMPORTS),
        "土石方计算依赖": [
            "shapely",
            # triangle 缺失时土石方模块会回退到 scipy.Delaunay，这里不阻断打包前校验。
        ],
    }


def get_collect_data_packages() -> list[str]:
    """返回需要随安装包一起收集数据文件的第三方包列表。"""
    return [
        "ezdxf",
        "matplotlib",
        "seaborn",
        "latex2mathml",
    ]


def _find_missing_imports(import_groups: dict[str, list[str]], importer=None) -> dict[str, list[str]]:
    """返回每个分组里当前环境无法导入的模块列表。"""
    if importer is None:
        importer = importlib.import_module

    missing: dict[str, list[str]] = {}
    for group_name, modules in import_groups.items():
        group_missing: list[str] = []
        for module_name in modules:
            try:
                importer(module_name)
            except Exception:
                group_missing.append(module_name)
        if group_missing:
            missing[group_name] = group_missing
    return missing


def _build_install_command(modules: list[str]) -> str:
    """把模块名转换成用户可直接执行的 pip 安装命令。"""
    package_names: list[str] = []
    seen: set[str] = set()
    for module_name in modules:
        package_name = PIP_INSTALL_NAME_OVERRIDES.get(module_name, module_name)
        if package_name in seen:
            continue
        seen.add(package_name)
        package_names.append(package_name)
    return f"pip install {' '.join(package_names)}"


def _build_install_command_for_group(group_name: str, modules: list[str]) -> str:
    """按分组返回更适合直接执行的安装命令。"""
    if group_name == "Word导出依赖":
        return _build_install_command(list(WORD_EXPORT_HIDDEN_IMPORTS))
    return _build_install_command(modules)


def ensure_required_imports_available(import_groups: dict[str, list[str]] | None = None, importer=None):
    """在打包前校验关键依赖是否可导入，缺失时直接终止。"""
    if import_groups is None:
        import_groups = get_verify_import_groups()

    missing_imports = _find_missing_imports(import_groups, importer=importer)
    if not missing_imports:
        return

    print("\n[错误] 打包前依赖校验失败，以下模块当前环境无法导入：")
    for group_name, modules in missing_imports.items():
        print(f"  - {group_name}: {', '.join(modules)}")
        print(f"    安装命令: {_build_install_command_for_group(group_name, modules)}")
    print("  请先补齐依赖后再重新执行打包。")
    raise SystemExit(1)

# ============================================================
# 路径（build.py 位于 tools/ 下，项目根目录在上一级）
# ============================================================
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST_DIR = os.path.join(PROJECT_ROOT, "dist")
BUILD_DIR = os.path.join(PROJECT_ROOT, "build")
MANIFEST_STORE_DIR = os.path.join(PROJECT_ROOT, ".release-manifests")
MAIN_SCRIPT = os.path.join(PROJECT_ROOT, "main.py")
UPDATE_HELPER_SCRIPT = os.path.join(PROJECT_ROOT, "update_helper.py")
ICON_FILE = os.path.join(PROJECT_ROOT, "icon.ico")
SHARED_UPDATE_HELPER_ICON_FILE = os.path.join(
    PROJECT_ROOT, "app_渠系计算前端", "resources", "license_shield.ico"
)
UPDATE_HELPER_ICON_FILE = os.path.join(
    PROJECT_ROOT, "app_渠系计算前端", "resources", "update_helper.ico"
)
LICENSE_MANAGER_ICON_FILE = os.path.join(PROJECT_ROOT, "tools", "license_icon.ico")
PROJECT_VENV_PYTHON = os.path.join(PROJECT_ROOT, ".venv", "Scripts", "python.exe")
UPDATE_HELPER_NAME = f"{APP_NAME_EN}Updater"


def _get_build_search_paths() -> list[str]:
    """返回构建和打包前校验共用的模块搜索路径。"""
    return [
        PROJECT_ROOT,
        os.path.join(PROJECT_ROOT, "calc_渠系计算算法内核"),
        os.path.join(PROJECT_ROOT, "倒虹吸水力计算系统"),
        os.path.join(PROJECT_ROOT, "推求水面线"),
    ]


@contextmanager
def _temporary_sys_path(search_paths: list[str]):
    """临时把项目搜索路径插到 sys.path 前面，供导入校验复用。"""
    inserted_paths: list[str] = []
    for path in reversed(search_paths):
        if path in sys.path:
            continue
        sys.path.insert(0, path)
        inserted_paths.append(path)
    try:
        yield
    finally:
        for path in inserted_paths:
            while path in sys.path:
                sys.path.remove(path)


def _project_python() -> str:
    """Prefer the project's venv interpreter for reproducible builds."""
    if os.path.exists(PROJECT_VENV_PYTHON):
        return PROJECT_VENV_PYTHON
    return sys.executable


def _resolve_update_helper_icon_file() -> str:
    for path in (
        SHARED_UPDATE_HELPER_ICON_FILE,
        LICENSE_MANAGER_ICON_FILE,
        UPDATE_HELPER_ICON_FILE,
    ):
        if os.path.exists(path):
            return path
    return ICON_FILE



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
        "app_渠系计算前端", "calc_渠系计算算法内核", "推求水面线",
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


def _build_update_helper(app_dist_dir: str):
    """构建独立更新助手，输出到主程序目录。"""
    if not os.path.exists(UPDATE_HELPER_SCRIPT):
        raise FileNotFoundError(f"未找到更新助手入口：{UPDATE_HELPER_SCRIPT}")

    helper_workdir = os.path.join(BUILD_DIR, "update_helper")
    os.makedirs(helper_workdir, exist_ok=True)
    args = [
        _project_python(), "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        f"--name={UPDATE_HELPER_NAME}",
        f"--distpath={app_dist_dir}",
        f"--workpath={helper_workdir}",
        f"--specpath={helper_workdir}",
        f"--paths={PROJECT_ROOT}",
        "--hidden-import=PySide6",
        "--hidden-import=PySide6.QtCore",
        "--hidden-import=PySide6.QtGui",
        "--hidden-import=PySide6.QtWidgets",
        "--hidden-import=updater",
        "--hidden-import=version",
    ]
    update_helper_icon = _resolve_update_helper_icon_file()
    if os.path.exists(update_helper_icon):
        args.append(f"--icon={update_helper_icon}")
    args.append(UPDATE_HELPER_SCRIPT)

    print("\n[helper] 正在构建独立更新助手...\n")
    result = subprocess.run(args, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        raise RuntimeError(f"更新助手构建失败，退出码：{result.returncode}")


def build(bump: str = None):
    if bump:
        bump_version(bump)

    print(f"{'=' * 60}")
    print(f"  {APP_NAME} 打包工具")
    print(f"  版本: V{APP_VERSION}")
    print(f"  Python: {_project_python()}")
    print(f"{'=' * 60}")

    with _temporary_sys_path(_get_build_search_paths()):
        ensure_required_imports_available()

    # 清理 data 目录中的 Excel 临时锁文件
    _clean_excel_temp_files(os.path.join(PROJECT_ROOT, "data"))

    # 清理旧的构建
    for d in [DIST_DIR, BUILD_DIR]:
        if os.path.exists(d):
            shutil.rmtree(d, ignore_errors=True)

    # ---- 构建 PyInstaller 参数 ----
    args = [
        _project_python(), "-m", "PyInstaller",
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
    # 项目根目录：让 PyInstaller 发现 app_渠系计算前端、土石方计算 等正式包
    # 子目录：calc_渠系计算算法内核、倒虹吸水力计算系统、推求水面线 没有 __init__.py，
    #         代码通过 sys.path.insert() 后以顶层模块名导入（如 from 明渠设计 import ...）
    search_paths = _get_build_search_paths()
    for p in search_paths:
        args.append(f"--paths={p}")

    # ---- 需要隐式导入的包（PyInstaller 静态分析可能扫描不到的） ----
    hidden_imports = get_hidden_imports()
    for mod in hidden_imports:
        args.append(f"--hidden-import={mod}")

    # ---- 排除明确不需要的 PySide6 子模块（减少分析范围） ----
    for mod in PYSIDE6_UNUSED_MODULES:
        args.append(f"--exclude-module={mod}")

    # ---- 排除被 scipy / 第三方 hook 误带入的可选 ML 依赖 ----
    for mod in OPTIONAL_ML_EXCLUDES:
        args.append(f"--exclude-module={mod}")

    # ---- 收集正式 Python 包的子模块（有 __init__.py，编译为字节码） ----
    collect_submodules = [
        "app_渠系计算前端",
        "土石方计算",
    ]
    for mod in collect_submodules:
        args.append(f"--collect-submodules={mod}")

    # ---- 收集第三方包的数据文件（字体/图标/模板等） ----
    # ezdxf 内置字体和 DXF 模板； qfluentwidgets 内置图标和 QSS 样式表
    for package_name in get_collect_data_packages():
        args.append(f"--collect-data={package_name}")
    args.append("--collect-all=qfluentwidgets")

    # ---- 添加资源文件（仅图片/图标/JSON/Excel 等，不包含 .py 源码） ----
    sep = ";"  # Windows 用分号分隔 src;dest

    # 从 data/ 目录逐个添加文件，排除 autosave 子目录和 .qxproj 等运行时产物
    _data_src = os.path.join(PROJECT_ROOT, "data")
    _data_exclude_exts = {".qxproj", ".log"}
    _data_exclude_dirs = {"autosave"}
    if os.path.isdir(_data_src):
        for _fname in os.listdir(_data_src):
            _fpath = os.path.join(_data_src, _fname)
            if os.path.isdir(_fpath):
                if _fname not in _data_exclude_dirs:
                    args.append(f"--add-data={_fpath}{sep}{os.path.join('data', _fname)}")
                continue
            if _fname.startswith("~$"):
                continue
            if os.path.splitext(_fname)[1] in _data_exclude_exts:
                continue
            args.append(f"--add-data={_fpath}{sep}data")

    data_entries = [
        # UI 图标、Logo 与本地化网页静态资源（含 Tabulator）
        (os.path.join(PROJECT_ROOT, "app_渠系计算前端", "resources"),
         os.path.join("app_渠系计算前端", "resources")),
        (os.path.join(PROJECT_ROOT, "倒虹吸水力计算系统", "resources"),
         os.path.join("倒虹吸水力计算系统", "resources")),
        (os.path.join(PROJECT_ROOT, "推求水面线", "resources"),
         os.path.join("推求水面线", "resources")),
        # JSON 配置文件
        (os.path.join(PROJECT_ROOT, "app_渠系计算前端", "default_project.siphon.json"),
         "app_渠系计算前端"),
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

    app_dist_dir = os.path.join(DIST_DIR, APP_NAME_EN)
    _build_update_helper(app_dist_dir)

    # ---- 清理残留的 .py 源码文件（双保险） ----
    _clean_py_sources(app_dist_dir)

    # ---- 删除用不到的 Qt 模块 DLL ----
    _clean_unused_qt_dlls(app_dist_dir)

    # ---- 生成文件清单 manifest.json（供增量补丁对比） ----
    print(f"\n[2/3] 生成文件清单 manifest.json...\n")
    dist_folder = app_dist_dir
    if not os.path.exists(dist_folder):
        print("[错误] 未找到打包产物")
        sys.exit(1)

    from patch_builder import (
        generate_manifest, save_manifest, load_manifest,
        build_universal_patch,
    )

    new_manifest = generate_manifest(dist_folder)
    manifest_name = f"manifest-V{APP_VERSION}.json"
    manifest_path = os.path.join(DIST_DIR, manifest_name)
    save_manifest(new_manifest, manifest_path)
    os.makedirs(MANIFEST_STORE_DIR, exist_ok=True)
    store_manifest_path = os.path.join(MANIFEST_STORE_DIR, manifest_name)
    save_manifest(new_manifest, store_manifest_path)

    # ---- 生成通用增量补丁包（一个包覆盖所有旧版本） ----
    patch_path = None
    patch_result = None
    manifest_files = os.listdir(MANIFEST_STORE_DIR)
    old_manifest_files = _select_universal_patch_manifest_files(manifest_files, APP_VERSION)
    skipped_manifest_count = len(
        [
            f for f in manifest_files
            if f.startswith("manifest-V") and f.endswith(".json")
            and f != f"manifest-V{APP_VERSION}.json"
            and _version_key(f.replace("manifest-V", "").replace(".json", ""))
            < _version_key(UNIVERSAL_PATCH_MIN_VERSION)
        ]
    )

    patch_info_path = os.path.join(DIST_DIR, "patch-info.json")
    if os.path.exists(patch_info_path):
        os.remove(patch_info_path)

    if skipped_manifest_count:
        print(
            f"  [patch] 已忽略 {skipped_manifest_count} 个 "
            f"V{UNIVERSAL_PATCH_MIN_VERSION} 之前的旧版 manifest"
        )

    if old_manifest_files:
        # 加载所有旧版 manifest
        old_manifests = []
        for mf_name in old_manifest_files:
            mf_path = os.path.join(MANIFEST_STORE_DIR, mf_name)
            base_ver = mf_name.replace("manifest-V", "").replace(".json", "")
            old_manifests.append((base_ver, load_manifest(mf_path)))

        patch_name = f"{APP_NAME_EN}-V{APP_VERSION}-patch.zip"
        patch_out = os.path.join(DIST_DIR, patch_name)
        patch_result = build_universal_patch(
            dist_folder, old_manifests, new_manifest, patch_out,
        )

        if patch_result:
            should_skip_patch, skip_reason = _should_skip_universal_patch(patch_result)
            if should_skip_patch:
                if os.path.exists(patch_out):
                    os.remove(patch_out)
                patch_result = None
                print(f"  [patch] 已跳过补丁，原因是覆盖范围过大：{skip_reason}")
            else:
                patch_path = patch_out
                patch_info = {
                    "type": "universal",
                    "latest_version": APP_VERSION,
                    "generated_at": new_manifest.get("build_time", ""),
                    "min_version": patch_result["min_version"],
                    "patch_name": patch_name,
                    "size_mb": patch_result["size_mb"],
                    "changed_count": patch_result["changed_count"],
                    "deleted_count": patch_result["deleted_count"],
                }
                with open(patch_info_path, "w", encoding="utf-8") as f:
                    json.dump(patch_info, f, ensure_ascii=False, indent=2)
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
        min_ver = patch_result["min_version"] if patch_result else "?"
        print(f"  补丁包: {patch_path} ({patch_mb:.2f} MB)")
        print(f"  补丁覆盖: V{min_ver}+ → V{APP_VERSION}（通用补丁）")
    print(f"  清  单: {manifest_path}")
    print(f"  基线清单仓库: {MANIFEST_STORE_DIR}")
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
