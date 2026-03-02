# -*- coding: utf-8 -*-
"""
打包前模块导入验证脚本

验证所有 hidden_imports 中的模块在运行时可正确导入。
用于在打包前检查配置完整性。

用法：
    python tools/verify_imports.py
"""

import sys
import os
import importlib
import io

# 设置输出编码为 UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 模块搜索路径（与 build.py 保持一致）
SEARCH_PATHS = [
    PROJECT_ROOT,
    os.path.join(PROJECT_ROOT, "渠系建筑物断面计算"),
    os.path.join(PROJECT_ROOT, "倒虹吸水力计算系统"),
    os.path.join(PROJECT_ROOT, "推求水面线"),
]

# 需要验证的核心模块（从 build.py hidden_imports 提取）
CORE_MODULES = {
    "授权与版本": [
        "license_checker",
        "version",
        "updater",
    ],
    "渠系建筑物断面计算": [
        "明渠设计",
        "渡槽设计",
        "隧洞设计",
        "矩形暗涵设计",
        "有压管道设计",
        "生成断面汇总表",
    ],
    "倒虹吸水力计算系统": [
        "siphon_models",
        "siphon_hydraulics",
        "siphon_coefficients",
        "dxf_parser",
        "spatial_merger",
    ],
    "推求水面线": [
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
        "utils.excel_io",
        "managers",
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
    "土石方计算依赖": [
        "shapely",
        "triangle",
        # "startinpy",  # 可选依赖，可能未安装
    ],
}


def setup_paths():
    """设置模块搜索路径"""
    for path in SEARCH_PATHS:
        if path not in sys.path:
            sys.path.insert(0, path)


def verify_module(module_name: str) -> tuple[bool, str]:
    """
    验证单个模块是否可导入
    
    Returns:
        (success, message)
    """
    try:
        importlib.import_module(module_name)
        return True, "OK"
    except ImportError as e:
        return False, str(e)
    except Exception as e:
        return False, f"异常: {e}"


def main():
    print("=" * 60)
    print("  渠系水力计算综合系统 - 模块导入验证")
    print("=" * 60)
    
    setup_paths()
    
    total = 0
    passed = 0
    failed = 0
    failed_modules = []
    
    for category, modules in CORE_MODULES.items():
        print(f"\n[{category}]")
        for mod in modules:
            total += 1
            success, msg = verify_module(mod)
            if success:
                passed += 1
                print(f"  [OK] {mod}")
            else:
                failed += 1
                failed_modules.append((mod, msg))
                print(f"  [FAIL] {mod} - {msg}")
    
    print("\n" + "=" * 60)
    print(f"  验证结果: {passed}/{total} 通过")
    
    if failed_modules:
        print(f"\n  失败模块 ({failed} 个):")
        for mod, msg in failed_modules:
            print(f"    - {mod}: {msg}")
        print("\n  建议: 请检查依赖是否已安装 (pip install <package>)")
        sys.exit(1)
    else:
        print("\n  所有模块验证通过，可以执行打包!")
        sys.exit(0)


if __name__ == "__main__":
    main()
