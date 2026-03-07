# -*- coding: utf-8 -*-
"""
渠系水力计算综合系统 V1.0

统一入口 —— 启动 PySide6 主程序
（集成：calc_渠系计算算法内核 + 倒虹吸水力计算 + 水面线推求）
"""


def main():
    """程序主入口"""
    import sys
    import os

    # ============================================================
    # 0. 确保项目根目录在搜索路径中
    # ============================================================
    _root = os.path.dirname(os.path.abspath(__file__))
    if _root not in sys.path:
        sys.path.insert(0, _root)

    # ============================================================
    # 1. 高DPI设置（必须在任何 QApplication 创建之前，含授权弹窗）
    # ============================================================
    os.environ.setdefault('QT_ENABLE_HIGHDPI_SCALING', '1')
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    # ============================================================
    # 2. 授权校验
    # ============================================================
    from license_checker import check_license
    if not check_license():
        sys.exit(1)

    # ============================================================
    # 3. 启动 PySide6 主窗口
    # ============================================================
    from app_渠系计算前端.app import main as app_main

    try:
        app_main()
    except Exception as e:
        import traceback
        try:
            print(f"程序启动失败: {e}")
            traceback.print_exc()
        except Exception:
            pass
        if not getattr(sys, 'frozen', False):
            input("按回车键退出...")
        sys.exit(1)


if __name__ == "__main__":
    main()
