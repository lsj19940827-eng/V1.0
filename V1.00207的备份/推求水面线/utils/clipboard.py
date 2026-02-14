# -*- coding: utf-8 -*-
"""
剪贴板处理工具

提供从Excel复制数据的解析功能，支持Ctrl+V粘贴到表格。
"""

from typing import List, Tuple, Optional
import tkinter as tk


class ClipboardHandler:
    """
    剪贴板处理器
    
    处理从Excel等外部程序复制的数据，解析为可用格式。
    """
    
    def __init__(self, root: tk.Tk):
        """
        初始化剪贴板处理器
        
        Args:
            root: Tkinter根窗口
        """
        self.root = root
    
    def get_clipboard_data(self) -> Optional[str]:
        """
        获取剪贴板中的文本数据
        
        Returns:
            剪贴板文本内容，如果为空或出错则返回None
        """
        try:
            return self.root.clipboard_get()
        except tk.TclError:
            # 剪贴板为空或格式不支持
            return None
    
    def parse_excel_data(self, clipboard_text: str) -> List[List[str]]:
        """
        解析从Excel复制的数据
        
        Excel数据格式：行以换行符分隔，列以制表符分隔
        
        Args:
            clipboard_text: 剪贴板中的文本
            
        Returns:
            二维列表，每行为一个列表
        """
        if not clipboard_text:
            return []
        
        rows = []
        # 按行分割（处理Windows和Unix换行符）
        lines = clipboard_text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
        
        for line in lines:
            # 跳过空行
            if not line.strip():
                continue
            # 按制表符分割列
            cells = line.split('\t')
            # 去除每个单元格的首尾空白
            cells = [cell.strip() for cell in cells]
            rows.append(cells)
        
        return rows
    
    def parse_coordinates(self, clipboard_text: str) -> List[Tuple[float, float]]:
        """
        解析坐标数据（X, Y两列）
        
        Args:
            clipboard_text: 剪贴板中的文本
            
        Returns:
            坐标列表 [(x1, y1), (x2, y2), ...]
        """
        rows = self.parse_excel_data(clipboard_text)
        coordinates = []
        
        for row in rows:
            if len(row) >= 2:
                try:
                    x = float(row[0])
                    y = float(row[1])
                    coordinates.append((x, y))
                except ValueError:
                    # 跳过无法转换为浮点数的行（可能是标题行）
                    continue
        
        return coordinates
    
    def get_and_parse_excel_data(self) -> List[List[str]]:
        """
        获取并解析剪贴板中的Excel数据
        
        Returns:
            解析后的二维数据列表
        """
        text = self.get_clipboard_data()
        if text:
            return self.parse_excel_data(text)
        return []
    
    def get_and_parse_coordinates(self) -> List[Tuple[float, float]]:
        """
        获取并解析剪贴板中的坐标数据
        
        Returns:
            坐标列表
        """
        text = self.get_clipboard_data()
        if text:
            return self.parse_coordinates(text)
        return []
    
    @staticmethod
    def format_for_clipboard(data: List[List[str]]) -> str:
        """
        将二维数据格式化为Excel可识别的剪贴板格式
        
        Args:
            data: 二维数据列表
            
        Returns:
            格式化后的字符串（制表符分隔列，换行符分隔行）
        """
        lines = []
        for row in data:
            lines.append('\t'.join(str(cell) for cell in row))
        return '\n'.join(lines)
    
    def copy_to_clipboard(self, data: List[List[str]]) -> None:
        """
        将数据复制到剪贴板
        
        Args:
            data: 二维数据列表
        """
        text = self.format_for_clipboard(data)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
