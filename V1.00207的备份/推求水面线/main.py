# -*- coding: utf-8 -*-
"""
推求水面线计算程序

主程序入口

功能说明：
- 渠道平面几何计算（方位角、转角、桩号等）
- 水面线推求（水位、流速、水头损失等）
- 支持Excel数据导入导出
- 支持从Excel直接粘贴数据

版本: V1.0
"""

import sys
import os

# 确保可以导入本地模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui.main_window import MainWindow


def main():
    """程序主入口"""
    try:
        # 创建并运行主窗口
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
