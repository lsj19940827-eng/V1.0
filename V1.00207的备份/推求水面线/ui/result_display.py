# -*- coding: utf-8 -*-
"""
结果展示区组件

提供计算结果的展示和摘要信息。
"""

import tkinter as tk
from tkinter import ttk
from typing import List, Dict, Any
import sys
import os

# 添加父目录到路径以支持相对导入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.data_models import ChannelNode


class ResultDisplayPanel(ttk.LabelFrame):
    """
    结果展示面板
    
    显示计算结果摘要和状态信息。
    """
    
    def __init__(self, parent: tk.Widget):
        """
        初始化结果展示面板
        
        Args:
            parent: 父容器
        """
        super().__init__(parent, text="计算结果摘要", padding=(10, 5))
        
        # 创建界面
        self._create_widgets()
    
    def _create_widgets(self):
        """创建界面组件"""
        # 摘要信息显示
        self.summary_frame = ttk.Frame(self)
        self.summary_frame.pack(fill=tk.X, pady=5)
        
        # 第一行
        row1 = ttk.Frame(self.summary_frame)
        row1.pack(fill=tk.X, pady=2)
        
        self.lbl_node_count = ttk.Label(row1, text="节点数量: -")
        self.lbl_node_count.pack(side=tk.LEFT, padx=(0, 30))
        
        self.lbl_total_length = ttk.Label(row1, text="总长度: - m")
        self.lbl_total_length.pack(side=tk.LEFT, padx=(0, 30))
        
        self.lbl_water_drop = ttk.Label(row1, text="水位落差: - m")
        self.lbl_water_drop.pack(side=tk.LEFT, padx=(0, 30))
        
        # 第二行
        row2 = ttk.Frame(self.summary_frame)
        row2.pack(fill=tk.X, pady=2)
        
        self.lbl_start_station = ttk.Label(row2, text="起点桩号: -")
        self.lbl_start_station.pack(side=tk.LEFT, padx=(0, 30))
        
        self.lbl_end_station = ttk.Label(row2, text="终点桩号: -")
        self.lbl_end_station.pack(side=tk.LEFT, padx=(0, 30))
        
        self.lbl_start_wl = ttk.Label(row2, text="起点水位: - m")
        self.lbl_start_wl.pack(side=tk.LEFT, padx=(0, 30))
        
        self.lbl_end_wl = ttk.Label(row2, text="终点水位: - m")
        self.lbl_end_wl.pack(side=tk.LEFT, padx=(0, 30))
        
        # 状态栏
        status_frame = ttk.Frame(self)
        status_frame.pack(fill=tk.X, pady=(5, 0))
        
        self.lbl_status = ttk.Label(status_frame, text="状态: 等待输入数据...", 
                                    foreground="gray")
        self.lbl_status.pack(side=tk.LEFT)
    
    def update_summary(self, summary: Dict[str, Any]) -> None:
        """
        更新摘要信息
        
        Args:
            summary: 摘要字典
        """
        if not summary:
            self.clear()
            return
        
        self.lbl_node_count.config(text=f"节点数量: {summary.get('节点数量', '-')}")
        self.lbl_total_length.config(text=f"总长度: {summary.get('总长度', '-'):.3f} m")
        self.lbl_water_drop.config(text=f"水位落差: {summary.get('水位落差', '-'):.3f} m")
        self.lbl_start_station.config(text=f"起点桩号: {summary.get('起点桩号', '-'):.3f}")
        self.lbl_end_station.config(text=f"终点桩号: {summary.get('终点桩号', '-'):.3f}")
        self.lbl_start_wl.config(text=f"起点水位: {summary.get('起点水位', '-'):.3f} m")
        self.lbl_end_wl.config(text=f"终点水位: {summary.get('终点水位', '-'):.3f} m")
    
    def set_status(self, message: str, status_type: str = "info") -> None:
        """
        设置状态信息
        
        Args:
            message: 状态消息
            status_type: 状态类型 ("info", "success", "error", "warning")
        """
        colors = {
            "info": "gray",
            "success": "green",
            "error": "red",
            "warning": "orange",
        }
        
        self.lbl_status.config(text=f"状态: {message}", 
                               foreground=colors.get(status_type, "gray"))
    
    def clear(self) -> None:
        """清空摘要信息"""
        self.lbl_node_count.config(text="节点数量: -")
        self.lbl_total_length.config(text="总长度: - m")
        self.lbl_water_drop.config(text="水位落差: - m")
        self.lbl_start_station.config(text="起点桩号: -")
        self.lbl_end_station.config(text="终点桩号: -")
        self.lbl_start_wl.config(text="起点水位: - m")
        self.lbl_end_wl.config(text="终点水位: - m")
        self.set_status("等待输入数据...")
