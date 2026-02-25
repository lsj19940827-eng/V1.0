# -*- coding: utf-8 -*-
"""
渠系水力计算综合系统 V1.0

统一入口 —— 启动 PySide6 主程序
（集成：渠系建筑物断面计算 + 倒虹吸水力计算 + 水面线推求）
"""


def main():
    """程序主入口"""
    import sys
    import os

    # ============================================================
    # 0. 授权校验（必须在所有 UI 初始化之前）
    # ============================================================
    from license_checker import check_license
    if not check_license():
        sys.exit(1)

    # ============================================================
    # 1. 高DPI环境变量（必须在 QApplication 之前设置）
    # ============================================================
    os.environ.setdefault('QT_ENABLE_HIGHDPI_SCALING', '1')

    # ============================================================
    # 2. 确保项目根目录在搜索路径中
    # ============================================================
    _root = os.path.dirname(os.path.abspath(__file__))
    if _root not in sys.path:
        sys.path.insert(0, _root)

    # ============================================================
    # 3. 启动 PySide6 主窗口
    # ============================================================
    from 渠系断面设计.app import main as app_main

    try:
        app_main()
    except Exception as e:
        import traceback
        print(f"程序启动失败: {e}")
        traceback.print_exc()
        input("按回车键退出...")
        sys.exit(1)


if __name__ == "__main__":
    main()
