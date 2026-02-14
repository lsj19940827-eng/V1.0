# -*- coding: utf-8 -*-
"""
渠系水力计算综合系统 V1.0

统一入口 —— 启动「推求水面线」主程序
（集成：渠系建筑物断面计算 + 倒虹吸水力计算 + 水面线推求）
"""

import sys
import os

# 将推求水面线目录加入模块搜索路径
_app_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "推求水面线")
sys.path.insert(0, _app_dir)

from ui.main_window import MainWindow


def main():
    """程序主入口"""
    try:
        app = MainWindow()
        app.run()
    except Exception as e:
        import traceback
        print(f"程序启动失败: {e}")
        traceback.print_exc()
        input("按回车键退出...")
        sys.exit(1)


if __name__ == "__main__":
    main()
