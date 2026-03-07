#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试Fluent Design风格的三按钮对话框"""

import sys
from PySide6.QtWidgets import QApplication, QMainWindow, QPushButton, QVBoxLayout, QWidget

# 添加项目路径
sys.path.insert(0, '.')

from app_渠系计算前端.styles import fluent_save_discard_cancel


class TestWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("测试Fluent对话框")
        self.setGeometry(100, 100, 400, 200)
        
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        btn = QPushButton("显示保存/放弃/取消对话框")
        btn.clicked.connect(self.show_dialog)
        layout.addWidget(btn)
    
    def show_dialog(self):
        result = fluent_save_discard_cancel(
            self,
            "保存项目",
            "当前项目有未保存的修改，是否保存？",
            save_text="保存",
            discard_text="放弃",
            cancel_text="取消"
        )
        print(f"用户选择: {result}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TestWindow()
    window.show()
    sys.exit(app.exec())
