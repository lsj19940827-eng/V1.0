# -*- coding: utf-8 -*-
"""
倒虹吸水力计算软件 - 主程序
独立运行入口，嵌入核心面板
"""

import tkinter as tk
from tkinter import ttk

from siphon_core_panel import SiphonCorePanel


class InvertedSiphonCalculator(tk.Tk):
    """倒虹吸水力计算软件主窗口（独立运行包装器）"""
    
    def __init__(self):
        super().__init__()
        
        self.title("倒虹吸水力计算系统")
        self.geometry("1200x950")
        self.minsize(1000, 850)
        
        # 嵌入核心面板
        self.core_panel = SiphonCorePanel(
            self,
            siphon_name="倒虹吸",
            on_result_callback=self._on_calculation_complete
        )
        self.core_panel.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 添加关闭按钮到底部
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(btn_frame, text="关闭", command=self.destroy, width=12).pack(side=tk.RIGHT)
    
    def _on_calculation_complete(self, result):
        """计算完成回调（可选扩展）"""
        pass


def main():
    """主函数"""
    app = InvertedSiphonCalculator()
    app.mainloop()


if __name__ == "__main__":
    main()
