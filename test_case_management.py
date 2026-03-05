# -*- coding: utf-8 -*-
"""测试倒虹吸工况管理"""
import sys
from PySide6.QtWidgets import QApplication
from 渠系断面设计.siphon.panel import SiphonPanel

if __name__ == '__main__':
    app = QApplication(sys.argv)

    # 创建带工况管理的倒虹吸面板
    panel = SiphonPanel(show_case_management=True)
    panel.setWindowTitle("倒虹吸水力设计 - 工况管理测试")
    panel.resize(1400, 900)
    panel.show()

    sys.exit(app.exec())
