# -*- coding: utf-8 -*-
"""
渠系建筑物断面尺寸计算程序 - 主程序入口

本程序提供多种渠道断面的水力计算功能，包括：
1. 明渠水力计算（梯形、矩形、圆形） 
2. 渡槽（U形、矩形）水力计算
3. 隧洞（圆形、圆拱直墙型、马蹄形）水力计算
4. 矩形暗涵水力计算

版本: V2.0 (结构整合版)
"""

import sys
import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinter import font as tkfont
from typing import Optional
import math
import unicodedata


def get_display_width(s: str) -> int:
    """计算字符串的显示宽度（中文等全角字符占2个宽度，其他字符占1个宽度）
    
    注意：只有Fullwidth(F)和Wide(W)类别的字符被视为宽字符，
    Ambiguous(A)类别（如希腊字母α、β）在等宽字体中通常占1个宽度。
    """
    width = 0
    for char in s:
        ea_width = unicodedata.east_asian_width(char)
        if ea_width in ('F', 'W'):
            width += 2
        else:
            width += 1
    return width


def pad_str(s: str, width: int, align: str = 'left') -> str:
    """将字符串填充到指定显示宽度
    
    Args:
        s: 原始字符串
        width: 目标显示宽度
        align: 对齐方式 'left'左对齐, 'right'右对齐, 'center'居中
    
    Returns:
        填充后的字符串
    """
    current_width = get_display_width(s)
    padding = width - current_width
    if padding <= 0:
        return s
    
    if align == 'left':
        return s + ' ' * padding
    elif align == 'right':
        return ' ' * padding + s
    else:  # center
        left_pad = padding // 2
        right_pad = padding - left_pad
        return ' ' * left_pad + s + ' ' * right_pad

# ============================================================
# 字体大小管理
# ============================================================

# 字体大小预设：中号、大号、特大号
FONT_SIZE_PRESETS = {
    "中号": {"default": 10, "small": 9, "title": 11, "result": 10},
    "大号": {"default": 12, "small": 10, "title": 13, "result": 11},
    "特大号": {"default": 14, "small": 12, "title": 15, "result": 13}
}

# 当前字体大小设置（全局变量）
CURRENT_FONT_SIZE = "中号"

def get_font_config():
    """获取当前字体配置"""
    return FONT_SIZE_PRESETS.get(CURRENT_FONT_SIZE, FONT_SIZE_PRESETS["中号"])

# 确保当前目录在路径中
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# ============================================================
# 导入计算模块
# ============================================================

# ============================================================
# 明渠水力设计统一模块 (含梯形、矩形、圆形明渠断面)
# ============================================================
try:
    from 明渠设计 import (
        quick_calculate as mingqu_calculate,  # 梯形明渠（向后兼容）
        quick_calculate_circular as circular_calculate,  # 圆形明渠
        calculate_area, calculate_wetted_perimeter, calculate_hydraulic_radius,
        get_flow_increase_percent, MAX_BETA,
        PI, MIN_FREEBOARD, MIN_FREE_AREA_PERCENT, MIN_FLOW_FACTOR
    )
    MINGQU_MODULE_LOADED = True
    CIRCULAR_MODULE_LOADED = True
except ImportError as e:
    MINGQU_MODULE_LOADED = False
    CIRCULAR_MODULE_LOADED = False
    MINGQU_IMPORT_ERROR = str(e)
    CIRCULAR_IMPORT_ERROR = str(e)

# 渡槽模块
try:
    from 渡槽设计 import (
        quick_calculate_u as ducao_u_calculate,
        quick_calculate_rect as ducao_rect_calculate
    )
    DUCAO_MODULE_LOADED = True
except ImportError as e:
    DUCAO_MODULE_LOADED = False
    DUCAO_IMPORT_ERROR = str(e)

# 隧洞模块
try:
    from 隧洞设计 import (
        quick_calculate_circular as suidong_circular_calculate,
        quick_calculate_horseshoe as suidong_horseshoe_calculate,
        quick_calculate_horseshoe_std as suidong_horseshoe_std_calculate
    )
    SUIDONG_MODULE_LOADED = True
except ImportError as e:
    SUIDONG_MODULE_LOADED = False
    SUIDONG_IMPORT_ERROR = str(e)

# 矩形暗涵模块（独立模块）
try:
    from 矩形暗涵设计 import (
        quick_calculate_rectangular_culvert as suidong_rect_calculate
    )
    RECT_CULVERT_MODULE_LOADED = True
except ImportError as e:
    RECT_CULVERT_MODULE_LOADED = False
    RECT_CULVERT_IMPORT_ERROR = str(e)

# 可视化模块
try:
    import matplotlib
    matplotlib.use('TkAgg')
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
    from matplotlib.figure import Figure
    import matplotlib.patches as patches
    import numpy as np
    from PIL import Image, ImageTk
    import io
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'SimSun', 'Arial Unicode MS']
    plt.rcParams['axes.unicode_minus'] = False
    plt.rcParams['mathtext.fontset'] = 'cm'  # 使用Computer Modern字体渲染数学公式
    VIZ_MODULE_LOADED = True
except ImportError as e:
    VIZ_MODULE_LOADED = False
    VIZ_IMPORT_ERROR = str(e)


def render_latex_formula(latex_str: str, fontsize: int = 14, dpi: int = 100, 
                         bg_color: str = '#f5f5f5') -> "ImageTk.PhotoImage":
    """使用matplotlib渲染LaTeX公式为Tkinter可用的图像（纯数学公式）
    
    Args:
        latex_str: LaTeX公式字符串（不需要包含$符号）
        fontsize: 字体大小
        dpi: 图像分辨率
        bg_color: 背景颜色
        
    Returns:
        Tkinter PhotoImage对象
    """
    fig, ax = plt.subplots(figsize=(8, 0.6), dpi=dpi)
    ax.set_axis_off()
    fig.patch.set_facecolor(bg_color)
    ax.set_facecolor(bg_color)
    
    ax.text(0.0, 0.5, f'${latex_str}$', fontsize=fontsize, 
            color='black', ha='left', va='center', transform=ax.transAxes)
    
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=dpi, facecolor=bg_color, 
                bbox_inches='tight', pad_inches=0.03)
    plt.close(fig)
    
    buf.seek(0)
    img = Image.open(buf)
    return ImageTk.PhotoImage(img)


def render_hybrid_formula(parts: list, fontsize: int = 14, dpi: int = 100,
                          bg_color: str = '#f5f5f5') -> "ImageTk.PhotoImage":
    """混合渲染公式（支持数学公式+中文下标）
    
    Args:
        parts: 列表，每个元素是 (text, mode) 元组
               mode='math' 用mathtext渲染（$包围）
               mode='text' 用普通中文字体渲染
               mode='sub'  用小号中文字体渲染（模拟下标）
        fontsize: 基准字体大小
        dpi: 分辨率
        bg_color: 背景色
        
    Returns:
        Tkinter PhotoImage对象
    """
    fig = plt.figure(figsize=(10, 0.7), dpi=dpi)
    fig.patch.set_facecolor(bg_color)
    
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_axis_off()
    ax.set_facecolor(bg_color)
    
    x_pos = 0.01
    baseline_y = 0.45
    
    for text, mode in parts:
        if mode == 'math':
            t = ax.text(x_pos, baseline_y, f'${text}$', fontsize=fontsize,
                       color='black', ha='left', va='center')
        elif mode == 'sub':
            # 下标：小字号，位置略低
            t = ax.text(x_pos, baseline_y - 0.15, text, fontsize=fontsize*0.65,
                       color='black', ha='left', va='center',
                       fontfamily=['SimHei', 'Microsoft YaHei', 'SimSun'])
        else:  # text
            t = ax.text(x_pos, baseline_y, text, fontsize=fontsize,
                       color='black', ha='left', va='center',
                       fontfamily=['SimHei', 'Microsoft YaHei', 'SimSun'])
        
        # 获取文本宽度来计算下一个位置
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        bbox = t.get_window_extent(renderer=renderer)
        inv = fig.transFigure.inverted()
        bbox_fig = inv.transform(bbox)
        width = bbox_fig[1][0] - bbox_fig[0][0]
        x_pos += width + 0.002
    
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=dpi, facecolor=bg_color,
                bbox_inches='tight', pad_inches=0.02)
    plt.close(fig)
    
    buf.seek(0)
    img = Image.open(buf)
    return ImageTk.PhotoImage(img)


# ============================================================
# 圆形明渠计算面板（已整合到明渠面板中）
# ============================================================
# 梯形与矩形明渠计算面板
# ============================================================

class OpenChannelPanel(ttk.Frame):
    """明渠计算面板（支持矩形、梯形、圆形断面）"""
    
    def __init__(self, parent):
        super().__init__(parent)
        
        self.input_params = {}
        self.current_result = None
        self.show_detail_var = tk.BooleanVar(value=True)  # 默认显示详细过程
        
        self._create_ui()
    
    def _create_ui(self):
        """创建UI"""
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 左侧输入面板
        self._create_input_panel(main_frame)
        
        # 右侧输出面板
        self._create_output_panel(main_frame)
    
    def _create_input_panel(self, parent):
        """创建输入面板"""
        input_frame = ttk.LabelFrame(parent, text="输入参数", padding="10")
        input_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        
        # 断面类型选择（矩形、梯形、圆形）
        self.section_type_var = tk.StringVar(value="梯形")

        row = 0
        ttk.Label(input_frame, text="断面类型:").grid(row=row, column=0, sticky=tk.W, pady=5)
        section_combo = ttk.Combobox(input_frame, textvariable=self.section_type_var,
                                      width=12, values=["矩形", "梯形", "圆形"], state='readonly')
        section_combo.grid(row=row, column=1, padx=5, pady=5)
        section_combo.bind('<<ComboboxSelected>>', self._on_section_type_changed)
        
        # 参数变量
        self.Q_var = tk.DoubleVar(value=5.0)
        self.m_var = tk.DoubleVar(value=1.0)
        self.n_var = tk.DoubleVar(value=0.014)
        self.slope_inv_var = tk.DoubleVar(value=3000)
        self.v_min_var = tk.DoubleVar(value=0.1)
        self.v_max_var = tk.DoubleVar(value=100.0)
        
        # 可选参数
        self.manual_beta_var = tk.StringVar(value="")
        self.manual_b_var = tk.StringVar(value="")
        self.manual_D_var = tk.StringVar(value="")  # 圆形断面直径
        self.manual_increase_var = tk.StringVar(value="")
        
        # 设计流量
        row += 1
        ttk.Label(input_frame, text="设计流量 Q (m³/s):").grid(row=row, column=0, sticky=tk.W, pady=5)
        ttk.Entry(input_frame, textvariable=self.Q_var, width=15).grid(row=row, column=1, padx=5, pady=5)
        
        # 边坡系数（仅梯形）
        row += 1
        self.m_label = ttk.Label(input_frame, text="边坡系数 m:")
        self.m_label.grid(row=row, column=0, sticky=tk.W, pady=5)
        self.m_entry = ttk.Entry(input_frame, textvariable=self.m_var, width=15)
        self.m_entry.grid(row=row, column=1, padx=5, pady=5)
        
        # 糙率
        row += 1
        ttk.Label(input_frame, text="糙率 n:").grid(row=row, column=0, sticky=tk.W, pady=5)
        ttk.Entry(input_frame, textvariable=self.n_var, width=15).grid(row=row, column=1, padx=5, pady=5)
        
        # 水力坡降
        row += 1
        ttk.Label(input_frame, text="水力坡降 1/").grid(row=row, column=0, sticky=tk.W, pady=5)
        ttk.Entry(input_frame, textvariable=self.slope_inv_var, width=15).grid(row=row, column=1, padx=5, pady=5)
        
        # 流速参数栏目
        row += 1
        ttk.Label(input_frame, text="【流速参数】", font=('', 9, 'bold')).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=5)
        
        # 不淤流速
        row += 1
        ttk.Label(input_frame, text="不淤流速 (m/s):").grid(row=row, column=0, sticky=tk.W, pady=5)
        ttk.Entry(input_frame, textvariable=self.v_min_var, width=15).grid(row=row, column=1, padx=5, pady=5)
        
        # 不冲流速
        row += 1
        ttk.Label(input_frame, text="不冲流速 (m/s):").grid(row=row, column=0, sticky=tk.W, pady=5)
        ttk.Entry(input_frame, textvariable=self.v_max_var, width=15).grid(row=row, column=1, padx=5, pady=5)
        
        # 流速提示
        row += 1
        ttk.Label(input_frame, text="(一般情况下保持默认数值即可)", font=('', 8), foreground='black').grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=2)
        
        # 流量加大比例栏目
        row += 1
        ttk.Label(input_frame, text="【流量加大】", font=('', 9, 'bold')).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=5)
        
        row += 1
        ttk.Label(input_frame, text="流量加大比例 (%):").grid(row=row, column=0, sticky=tk.W, pady=3)
        ttk.Entry(input_frame, textvariable=self.manual_increase_var, width=15).grid(row=row, column=1, padx=5, pady=3)
        
        row += 1
        self.increase_hint_var = tk.StringVar(value="(留空则自动计算)")
        self.increase_hint_label = ttk.Label(input_frame, textvariable=self.increase_hint_var, font=('', 8), foreground='black')
        self.increase_hint_label.grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=2)
        
        # 分隔线
        row += 1
        ttk.Separator(input_frame, orient=tk.HORIZONTAL).grid(row=row, column=0, columnspan=2, 
                                                                sticky=tk.EW, pady=10)
        
        # 可选参数标签
        row += 1
        ttk.Label(input_frame, text="【可选参数】", font=('', 9, 'bold')).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=5)
        
        # 手动宽深比（仅矩形/梯形）
        row += 1
        self.beta_label = ttk.Label(input_frame, text="手动宽深比 β:")
        self.beta_label.grid(row=row, column=0, sticky=tk.W, pady=3)
        self.beta_entry = ttk.Entry(input_frame, textvariable=self.manual_beta_var, width=15)
        self.beta_entry.grid(row=row, column=1, padx=5, pady=3)
        
        # 手动底宽（仅矩形/梯形）
        row += 1
        self.b_label = ttk.Label(input_frame, text="手动底宽 B (m):")
        self.b_label.grid(row=row, column=0, sticky=tk.W, pady=3)
        self.b_entry = ttk.Entry(input_frame, textvariable=self.manual_b_var, width=15)
        self.b_entry.grid(row=row, column=1, padx=5, pady=3)

        # 提示（仅矩形/梯形）
        row += 1
        self.beta_b_hint = ttk.Label(input_frame, text="(二选一输入，留空则自动计算)", font=('', 8), foreground='black')
        self.beta_b_hint.grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=2)
        
        # 手动直径（仅圆形）
        row += 1
        self.D_label = ttk.Label(input_frame, text="手动直径 D (m):")
        self.D_label.grid(row=row, column=0, sticky=tk.W, pady=3)
        self.D_entry = ttk.Entry(input_frame, textvariable=self.manual_D_var, width=15)
        self.D_entry.grid(row=row, column=1, padx=5, pady=3)
        
        # 提示（仅圆形）
        row += 1
        self.D_hint = ttk.Label(input_frame, text="(留空则自动计算)", font=('', 8), foreground='black')
        self.D_hint.grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=2)
        
        # 初始化时隐藏圆形参数
        self.D_label.grid_remove()
        self.D_entry.grid_remove()
        self.D_hint.grid_remove()
        
        # 分隔线
        row += 1
        ttk.Separator(input_frame, orient=tk.HORIZONTAL).grid(row=row, column=0, columnspan=2, 
                                                                sticky=tk.EW, pady=10)
        
        # 输出选项
        row += 1
        ttk.Checkbutton(input_frame, text="输出详细计算过程", 
                       variable=self.show_detail_var).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=5)
        
        # 按钮
        row += 1
        btn_frame = ttk.Frame(input_frame)
        btn_frame.grid(row=row, column=0, columnspan=2, pady=10)
        
        ttk.Button(btn_frame, text="计算", command=self._calculate, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="清空", command=self._clear, width=10).pack(side=tk.LEFT, padx=5)
        
        # 导出按钮
        row += 1
        export_frame = ttk.Frame(input_frame)
        export_frame.grid(row=row, column=0, columnspan=2, pady=5)
        
        ttk.Button(export_frame, text="导出图表", command=self._export_charts, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Button(export_frame, text="导出报告", command=self._export_report, width=10).pack(side=tk.LEFT, padx=5)
    
    def _on_section_type_changed(self, event=None):
        """断面类型切换（矩形、梯形、圆形）"""
        section_type = self.section_type_var.get()

        # 根据断面类型调整界面
        if section_type == "矩形":
            # 矩形：隐藏边坡系数，设为0
            self.m_label.grid_remove()
            self.m_entry.grid_remove()
            self.m_var.set(0.0)
            # 修改默认值
            self.v_min_var.set(0.1)
            self.v_max_var.set(100.0)
            # 显示宽深比和底宽
            self.beta_label.grid()
            self.beta_entry.grid()
            self.b_label.grid()
            self.b_entry.grid()
            self.beta_b_hint.grid()
            # 隐藏圆形参数
            self.D_label.grid_remove()
            self.D_entry.grid_remove()
            self.D_hint.grid_remove()
        elif section_type == "梯形":
            # 梯形：显示边坡系数
            self.m_label.grid()
            self.m_entry.grid()
            self.m_var.set(1.0)
            self.v_min_var.set(0.1)
            self.v_max_var.set(100.0)
            # 显示宽深比和底宽
            self.beta_label.grid()
            self.beta_entry.grid()
            self.b_label.grid()
            self.b_entry.grid()
            self.beta_b_hint.grid()
            # 隐藏圆形参数
            self.D_label.grid_remove()
            self.D_entry.grid_remove()
            self.D_hint.grid_remove()
        elif section_type == "圆形":
            # 圆形：隐藏边坡系数、宽深比和底宽
            self.m_label.grid_remove()
            self.m_entry.grid_remove()
            self.beta_label.grid_remove()
            self.beta_entry.grid_remove()
            self.b_label.grid_remove()
            self.b_entry.grid_remove()
            self.beta_b_hint.grid_remove()
            # 显示直径参数
            self.D_label.grid()
            self.D_entry.grid()
            self.D_hint.grid()
            # 设置默认值
            self.v_min_var.set(0.1)
            self.v_max_var.set(100.0)
    
    def _create_output_panel(self, parent):
        """创建输出面板"""
        output_frame = ttk.Frame(parent)
        output_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        self.notebook = ttk.Notebook(output_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        
        # 计算结果
        self.result_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.result_tab, text="计算结果")
        self._create_result_view(self.result_tab)
        
        # 断面图
        if VIZ_MODULE_LOADED:
            self.section_tab = ttk.Frame(self.notebook)
            self.notebook.add(self.section_tab, text="断面图")
            self._create_section_view(self.section_tab)
    
    def _create_result_view(self, parent):
        """创建结果视图"""
        result_frame = ttk.LabelFrame(parent, text="计算结果详情", padding="10")
        result_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.result_text = tk.Text(result_frame, wrap=tk.WORD, font=('Consolas', 11), 
                                    bg='#f5f5f5', relief=tk.FLAT)
        self.result_text.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(self.result_text, orient=tk.VERTICAL, 
                                   command=self.result_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.result_text.configure(yscrollcommand=scrollbar.set)
        
        self._show_initial_help()
    
    def _show_initial_help(self):
        """显示初始帮助"""
        self.result_text.configure(state=tk.NORMAL)
        self.result_text.delete(1.0, tk.END)
        self.result_text.insert(tk.END, '请选择断面类型并输入参数后点击"计算"按钮开始计算...\n\n')
        self.result_text.insert(tk.END, "=" * 50 + "\n")
        self.result_text.insert(tk.END, "明渠水力计算说明\n")
        self.result_text.insert(tk.END, "=" * 50 + "\n\n")
        self.result_text.insert(tk.END, "支持断面类型：\n")
        self.result_text.insert(tk.END, "  1. 矩形断面（边坡系数 m=0）\n")
        self.result_text.insert(tk.END, "  2. 梯形断面（用户自定义边坡系数 m）\n")
        self.result_text.insert(tk.END, "  3. 圆形明渠\n\n")
        self.result_text.insert(tk.END, "本程序基于曼宁公式进行计算：\n")
        self.result_text.insert(tk.END, "  - Q = (1/n) × A × R^(2/3) × i^(1/2)\n\n")
        self.result_text.insert(tk.END, "断面几何公式：\n")
        self.result_text.insert(tk.END, "  - 过水面积: A = (B + m×h) × h\n")
        self.result_text.insert(tk.END, "  - 湿周: X = B + 2×h×√(1+m²)\n")
        self.result_text.insert(tk.END, "  - 水力半径: R = A/X\n\n")
        self.result_text.insert(tk.END, "宽深比说明：\n")
        self.result_text.insert(tk.END, "  - 定义: β = B/h (底宽/设计水深)\n")
        self.result_text.insert(tk.END, f"  - 推荐范围: 0 < β ≤ {MAX_BETA}\n")
        self.result_text.insert(tk.END, "  - 可选参数中可手动指定宽深比或底宽\n")
        self.result_text.insert(tk.END, "  - 二选一输入，留空则自动寻优计算\n\n")
        self.result_text.insert(tk.END, f"约束条件：\n")
        self.result_text.insert(tk.END, f"  - 流速范围: 不淤流速 < V < 不冲流速\n")
        self.result_text.insert(tk.END, f"  - 宽深比范围: 0 < β ≤ {MAX_BETA}\n")
        self.result_text.configure(state=tk.DISABLED)
    
    def _create_section_view(self, parent):
        """创建断面图视图"""
        self.section_fig = Figure(figsize=(8, 6), dpi=100)
        self.section_canvas = FigureCanvasTkAgg(self.section_fig, master=parent)
        self.section_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        toolbar = NavigationToolbar2Tk(self.section_canvas, parent)
        toolbar.update()
        
    def _show_error_in_result(self, title, message):
        """在计算结果区域显示错误信息"""
        self.result_text.configure(state=tk.NORMAL)
        self.result_text.delete(1.0, tk.END)
            
        output = []
        output.append("=" * 70)
        output.append(f"  {title}")
        output.append("=" * 70)
        output.append("")
        output.append(message)
        output.append("")
        output.append("-" * 70)
        output.append("请修正后重新计算。")
        output.append("=" * 70)
            
        self.result_text.insert(tk.END, "\n".join(output))
        self.result_text.configure(state=tk.DISABLED)
        
    def _calculate(self):
        """执行计算（矩形、梯形、圆形明渠）"""
        section_type = self.section_type_var.get()

        # 检查明渠模块
        if not MINGQU_MODULE_LOADED:
            self._show_error_in_result("模块加载错误", "明渠计算模块未加载。")
            return
        
        # 检查圆形明渠模块
        if section_type == "圆形" and not CIRCULAR_MODULE_LOADED:
            self._show_error_in_result("模块加载错误", "圆形明渠计算模块未加载。")
            return
            
        try:
            Q = self.Q_var.get()
            n = self.n_var.get()
            slope_inv = self.slope_inv_var.get()
            v_min = self.v_min_var.get()
            v_max = self.v_max_var.get()
                
            # 验证通用参数
            if Q <= 0:
                self._show_error_in_result("参数错误", "请输入有效的设计流量 Q（必须大于0）。")
                return
            if n <= 0:
                self._show_error_in_result("参数错误", "请输入有效的糙率 n（必须大于0）。")
                return
            if slope_inv <= 0:
                self._show_error_in_result("参数错误", "请输入有效的水力坡降倒数（必须大于0）。")
                return
            if v_min >= v_max:
                self._show_error_in_result("参数错误", "不淤流速必须小于不冲流速。")
                return
            
            # 根据断面类型获取特定参数并执行计算
            if section_type == "圆形":
                # 圆形断面计算
                manual_D = None
                manual_increase = None
                
                if self.manual_D_var.get().strip():
                    manual_D = float(self.manual_D_var.get())
                if self.manual_increase_var.get().strip():
                    manual_increase = float(self.manual_increase_var.get())
                
                # 保存参数
                self.input_params = {
                    'Q': Q, 'n': n, 'slope_inv': slope_inv,
                    'v_min': v_min, 'v_max': v_max,
                    'section_type': section_type,
                    'manual_b': manual_D,  # 圆形使用manual_b传递直径
                    'manual_increase': manual_increase
                }
                
                # 调用圆形明渠计算
                result = circular_calculate(
                    Q=Q, n=n, slope_inv=slope_inv,
                    v_min=v_min, v_max=v_max,
                    manual_D=manual_D,
                    increase_percent=manual_increase
                )
                
            else:
                # 梯形/矩形断面计算
                m = self.m_var.get()
                
                # 验证梯形参数
                if section_type == "梯形" and m < 0:
                    self._show_error_in_result("参数错误", "请输入有效的边坡系数 m（不能为负）。")
                    return
                
                # 可选参数
                manual_beta = None
                manual_b = None
                manual_increase = None
                
                if self.manual_beta_var.get().strip():
                    manual_beta = float(self.manual_beta_var.get())
                if self.manual_b_var.get().strip():
                    manual_b = float(self.manual_b_var.get())
                if self.manual_increase_var.get().strip():
                    manual_increase = float(self.manual_increase_var.get())
                
                # 保存参数
                self.input_params = {
                    'Q': Q, 'm': m, 'n': n, 'slope_inv': slope_inv,
                    'v_min': v_min, 'v_max': v_max,
                    'section_type': section_type,
                    'manual_beta': manual_beta,
                    'manual_b': manual_b,
                    'manual_increase': manual_increase
                }
                
                # 使用明渠计算（支持梯形和矩形，m=0时为矩形）
                result = mingqu_calculate(
                    Q=Q, m=m, n=n, slope_inv=slope_inv,
                    v_min=v_min, v_max=v_max,
                    manual_beta=manual_beta,
                    manual_b=manual_b,
                    manual_increase_percent=manual_increase
                )

            self.current_result = result

            # 计算完成后，更新加大比例提示标签显示实际使用的值
            if result.get('success') and 'increase_percent' in result:
                actual_increase = result['increase_percent']
                # 检查increase_percent是字符串还是数值
                if isinstance(actual_increase, str):
                    # 圆形断面返回字符串格式
                    if self.manual_increase_var.get().strip():
                        self.increase_hint_var.set(f"(手动指定: {actual_increase})")
                    else:
                        self.increase_hint_var.set(f"(自动计算: {actual_increase})")
                else:
                    # 梯形/矩形断面返回数值
                    if self.manual_increase_var.get().strip():
                        self.increase_hint_var.set(f"(手动指定: {actual_increase:.1f}%)")
                    else:
                        self.increase_hint_var.set(f"(自动计算: {actual_increase:.1f}%)")
            
            # 更新显示
            self._update_result_display(result)
            
            if VIZ_MODULE_LOADED:
                self._update_section_plot(result)
            
        except (ValueError, tk.TclError) as e:
            # 捕获参数错误（如未输入或格式错误）
            error_detail = str(e)
            if "invalid literal" in error_detail or "expected floating" in error_detail:
                if section_type == "圆形":
                    param_list = "- 设计流量 Q\n- 糙率 n\n- 水力坡降 1/x"
                elif section_type == "梯形":
                    param_list = "- 设计流量 Q\n- 边坡系数 m\n- 糙率 n\n- 水力坡降 1/x"
                else:
                    param_list = "- 设计流量 Q\n- 糙率 n\n- 水力坡降 1/x"
                self._show_error_in_result("输入错误", f"参数输入不完整或格式错误，请检查并填写所有必填参数：\n{param_list}")
            else:
                self._show_error_in_result("输入错误", f"{error_detail}")
        except Exception as e:
            self._show_error_in_result("计算错误", f"计算过程出错: {str(e)}")
    
    def _update_result_display(self, result):
        """更新结果显示"""
        self.result_text.configure(state=tk.NORMAL)
        self.result_text.delete(1.0, tk.END)
        
        if not result['success']:
            error_msg = result.get('error_message', '未知错误')
            self.result_text.insert(tk.END, f"计算失败: {error_msg}\n")
            self.result_text.configure(state=tk.DISABLED)
            return
        
        section_type = self.input_params.get('section_type', '梯形')
        show_detail = self.show_detail_var.get()
        
        # 根据断面类型和输出选项调用不同的显示方法
        if section_type == '圆形':
            if show_detail:
                self._update_circular_result_display(result)
            else:
                self._show_circular_brief_result(result)
        else:
            if show_detail:
                self._update_trapezoid_result_display(result)
            else:
                self._show_trapezoid_brief_result(result)
    
    def _show_circular_brief_result(self, result):
        """显示圆形断面简要结果"""
        Q = self.input_params['Q']
        n = self.input_params['n']
        slope_inv = self.input_params['slope_inv']
        v_min = self.input_params['v_min']
        v_max = self.input_params['v_max']
        
        D_design = result.get('D_design', 0)
        h = result.get('y_d', 0)  # 设计水深
        V = result.get('V_d', 0)  # 设计流速
        A_d = result.get('A_d', 0)  # 过水面积
        FB_d = result.get('FB_d', 0)  # 净空高度
        PA_d = result.get('PA_d', 0)  # 净空面积百分比
        
        # 加大流量工况
        increase_info = result.get('increase_percent', '')
        Q_inc = result.get('Q_inc', 0)
        h_i = result.get('y_i', 0)
        V_i = result.get('V_i', 0)
        FB_i = result.get('FB_i', 0)
        PA_i = result.get('PA_i', 0)
        
        output = []
        output.append("=" * 70)
        output.append("              明渠水力计算结果（圆形断面）")
        output.append("=" * 70)
        output.append("")
        
        output.append("【输入参数】")
        output.append(f"  设计流量 Q = {Q:.3f} m³/s")
        output.append(f"  糙率 n = {n}")
        output.append(f"  水力坡降 1/{int(slope_inv)}")
        output.append("")
        
        output.append("【断面尺寸】")
        output.append(f"  设计直径 D = {D_design:.2f} m")
        output.append("")
        
        output.append("【设计流量工况】")
        output.append(f"  设计水深 h = {h:.3f} m")
        output.append(f"  设计流速 V = {V:.3f} m/s")
        output.append(f"  过水面积 A = {A_d:.3f} m²")
        output.append(f"  净空高度 Fb = {FB_d:.3f} m")
        output.append(f"  净空比例 = {PA_d:.1f}%")
        output.append("")
        
        output.append("【加大流量工况】")
        output.append(f"  流量加大比例 = {increase_info}")
        output.append(f"  加大流量 Q加大 = {Q_inc:.3f} m³/s")
        output.append(f"  加大水深 h加大 = {h_i:.3f} m")
        output.append(f"  加大流速 V加大 = {V_i:.3f} m/s")
        output.append(f"  净空高度 Fb加大 = {FB_i:.3f} m")
        output.append(f"  净空比例 = {PA_i:.1f}%")
        output.append("")
        
        output.append("【验证结果】")
        velocity_ok = v_min <= V <= v_max
        velocity_inc_ok = v_min <= V_i <= v_max if V_i else True
        output.append(f"  1. 设计流速验证")
        output.append(f"     范围要求: {v_min} ≤ V ≤ {v_max} m/s")
        output.append(f"     计算结果: V = {V:.3f} m/s")
        output.append(f"     验证结果: {'通过 ✓' if velocity_ok else '未通过 ✗'}")
        output.append("")
        
        output.append(f"  2. 加大流速验证")
        output.append(f"     范围要求: {v_min} ≤ V ≤ {v_max} m/s")
        if V_i:
            output.append(f"     计算结果: V加大 = {V_i:.3f} m/s")
            output.append(f"     验证结果: {'通过 ✓' if velocity_inc_ok else '未通过 ✗'}")
        else:
            output.append(f"     计算结果: 无数据")
        output.append("")
        
        all_ok = velocity_ok and velocity_inc_ok
        output.append("=" * 70)
        output.append(f"  综合验证结果: {'通过 ✓' if all_ok else '未通过 ✗'}")
        output.append("=" * 70)
        
        self.result_text.insert(tk.END, "\n".join(output))
        self.result_text.configure(state=tk.DISABLED)
    
    def _show_trapezoid_brief_result(self, result):
        """显示梯形/矩形断面简要结果"""
        Q = self.input_params['Q']
        m = self.input_params['m']
        n = self.input_params['n']
        slope_inv = self.input_params['slope_inv']
        v_min = self.input_params['v_min']
        v_max = self.input_params['v_max']
        section_type = self.input_params.get('section_type', '梯形')
        
        b = result['b_design']
        h = result['h_design']
        V = result['V_design']
        A = result['A_design']
        R = result['R_design']
        β = result['Beta_design']
        
        inc_pct = result['increase_percent']
        Q_加大 = result['Q_increased']
        h_加大 = result['h_increased']
        V_加大 = result['V_increased']
        Fb = result['Fb']
        H = result['h_prime']
        
        # 判断加大比例来源
        manual_increase = self.input_params.get('manual_increase')
        inc_source = "(手动指定)" if manual_increase else "(自动计算)"
        
        output = []
        output.append("=" * 70)
        output.append(f"              明渠水力计算结果（{section_type}断面）")
        output.append("=" * 70)
        output.append("")
        
        output.append("【输入参数】")
        output.append(f"  设计流量 Q = {Q:.3f} m³/s")
        if section_type == "梯形":
            output.append(f"  边坡系数 m = {m}")
        output.append(f"  糙率 n = {n}")
        output.append(f"  水力坡降 1/{int(slope_inv)}")
        output.append("")
        
        output.append("【设计结果】")
        output.append(f"  设计方法: {result['design_method']}")
        output.append(f"  底宽 B = {b:.3f} m")
        output.append(f"  水深 h = {h:.3f} m")
        output.append(f"  宽深比 β = {β:.3f}")
        output.append(f"  过水面积 A = {A:.3f} m²")
        output.append(f"  水力半径 R = {R:.3f} m")
        output.append(f"  设计流速 V = {V:.3f} m/s")
        output.append("")
        
        # 如果有附录E备选方案，展示方案对比表
        appendix_e_schemes = result.get('appendix_e_schemes', [])
        if appendix_e_schemes:
            output.append("【附录E断面方案对比】")
            output.append("  说明: α=1.00为水力最佳断面，α越大断面越宽浅")
            output.append("")
            output.append("  α值    方案类型        底宽B(m)  水深h(m)  宽深比β   流速V(m/s)  面积+  状态")
            output.append("  " + "-" * 78)
            
            for scheme in appendix_e_schemes:
                alpha = scheme['alpha']
                stype = scheme['scheme_type']
                sb = scheme['b']
                sh = scheme['h']
                sbeta = scheme['beta']
                sV = scheme['V']
                area_inc = scheme['area_increase']
                
                # 判断是否为选中的方案
                is_selected = abs(sb - b) < 0.01 and abs(sh - h) < 0.01
                status = "★选中" if is_selected else ""
                
                # 检查流速是否满足约束
                v_ok = v_min < sV < v_max
                if not v_ok:
                    status = "流速不符"
                
                output.append(f"  {alpha:.2f}   {stype:<12}  {sb:8.3f}  {sh:8.3f}  {sbeta:8.3f}  {sV:10.3f}  +{area_inc:.0f}%   {status}")
            
            output.append("")
            output.append(f"  注: 流速约束范围 {v_min} ~ {v_max} m/s")
            output.append("")
        
        output.append("【加大流量工况】")
        output.append(f"  流量加大比例 = {inc_pct:.1f}% {inc_source}")
        output.append(f"  加大流量 Q加大 = {Q_加大:.3f} m³/s")
        if h_加大 > 0:
            output.append(f"  加大水深 h加大 = {h_加大:.3f} m")
            output.append(f"  加大流速 V加大 = {V_加大:.3f} m/s")
            output.append(f"  岸顶超高 Fb = {Fb:.3f} m")
            output.append(f"  渠道高度 H = {H:.3f} m")
        output.append("")
        
        output.append("【验证结果】")
        velocity_ok = v_min < V < v_max
        beta_ok = 0 < β <= MAX_BETA
        fb_req = 0.25 * h_加大 + 0.2
        fb_ok = Fb >= (fb_req - 0.001)
        
        output.append(f"  流速验证: {'✓ 通过' if velocity_ok else '✗ 未通过'}")
        output.append(f"  宽深比验证: {'✓ 通过' if beta_ok else '✗ 未通过'}")
        output.append(f"  超高复核: {'✓ 通过' if fb_ok else '✗ 未通过'} (Fb={Fb:.3f}m, 规范要求≥{fb_req:.3f}m)")
        output.append("")
        
        all_pass = velocity_ok and beta_ok and fb_ok
        output.append("=" * 70)
        output.append(f"  综合验证结果: {'全部通过 ✓' if all_pass else '未通过 ✗'}")
        output.append("=" * 70)
        
        self.result_text.insert(tk.END, "\n".join(output))
        self.result_text.configure(state=tk.DISABLED)
    
    def _update_circular_result_display(self, result):
        """显示圆形断面计算结果（详细过程）"""
        # 获取输入参数
        Q = self.input_params['Q']
        n = self.input_params['n']
        slope_inv = self.input_params['slope_inv']
        v_min = self.input_params['v_min']
        v_max = self.input_params['v_max']
            
        # 计算中间变量
        i = 1 / slope_inv
            
        # 获取计算结果
        D_calculated = result.get('D_calculated', 0)
        D_design = result.get('D_design', 0)
        pipe_area = PI * D_design**2 / 4
            
        # 设计流量工况
        h_d = result.get('y_d', 0)  # 设计水深
        V_d = result.get('V_d', 0)  # 设计流速
        A_d = result.get('A_d', 0)  # 过水面积
        P_d = result.get('P_d', 0)  # 湿周
        R_d = result.get('R_d', 0)  # 水力半径
        PA_d = result.get('PA_d', 0)  # 净空面积百分比
        FB_d = result.get('FB_d', 0)  # 净空高度
        Q_check_d = result.get('Q_check_d', 0)  # 校核流量
            
        # 加大流量工况
        increase_info = result.get('increase_percent', '')
        Q_inc = result.get('Q_inc', 0)
        h_i = result.get('y_i', 0)
        V_i = result.get('V_i', 0)
        A_i = result.get('A_i', 0)
        P_i = result.get('P_i', 0)
        R_i = result.get('R_i', 0)
        Q_check_i = result.get('Q_check_i', 0)
        PA_i = result.get('PA_i', 0)
        FB_i = result.get('FB_i', 0)
            
        # 解析加大比例
        try:
            increase_pct = float(increase_info.split('%')[0])
        except:
            increase_pct = 20
            
        # 最小流量工况
        Q_min = result.get('Q_min', 0)
        h_m = result.get('y_m', 0)
        V_m = result.get('V_m', 0)
            
        # 格式化输出
        output = []
        output.append("=" * 70)
        output.append("              明渠水力计算结果（圆形断面）")
        output.append("=" * 70)
        output.append("")
            
        # 输入参数
        output.append("【一、输入参数】")
        output.append(f"  断面类型 = 圆形")
        output.append(f"  设计流量 Q = {Q:.3f} m³/s")
        output.append(f"  糙率 n = {n}")
        output.append(f"  水力坡降 1/{int(slope_inv)}")
        output.append(f"  不淤流速 = {v_min} m/s")
        output.append(f"  不冲流速 = {v_max} m/s")
            
        # 显示手动输入参数
        if self.input_params.get('manual_b'):
            output.append(f"  [手动] 直径 D = {self.input_params['manual_b']} m")
        output.append("")
            
        # 直径确定
        output.append("【二、直径确定】")
        output.append("")
        if D_calculated > 0:
            output.append(f"  1. 计算直径: D计算 = {D_calculated:.3f} m")
        output.append(f"  2. 设计直径: D = {D_design:.2f} m")
        output.append("")
        output.append("  3. 管道总断面积计算:")
        output.append(f"     A总 = π × D² / 4")
        output.append(f"        = {PI:.4f} × {D_design:.2f}² / 4")
        output.append(f"        = {PI:.4f} × {D_design**2:.4f} / 4")
        output.append(f"        = {pipe_area:.3f} m²")
        output.append("")
            
        # 设计流量工况
        output.append("【三、设计流量工况计算】")
        output.append(f"  Q = {Q:.3f} m³/s")
        output.append("")
        output.append(f"  4. 设计水深:")
        output.append(f"     h = {h_d:.3f} m")
        output.append("")
            
        # 计算圆心角
        if h_d > 0 and D_design > 0 and h_d <= D_design:
            R_radius = D_design / 2
            theta = 2 * math.acos((R_radius - h_d) / R_radius)
            output.append(f"  5. 圆心角计算:")
            output.append(f"     θ = 2 × arccos((R - h) / R)")
            output.append(f"       = 2 × arccos(({R_radius:.3f} - {h_d:.3f}) / {R_radius:.3f})")
            output.append(f"       = 2 × arccos({(R_radius - h_d)/R_radius:.4f})")
            output.append(f"       = {math.degrees(theta):.2f}° ({theta:.4f} rad)")
            output.append("")
            
        output.append(f"  6. 过水面积计算:")
        output.append(f"     A = (D²/8) × (θ - sinθ)")
        output.append(f"       = {A_d:.3f} m²")
        output.append("")
        output.append(f"  7. 湿周计算:")
        output.append(f"      χ = D × θ / 2")
        output.append(f"        = {P_d:.3f} m")
        output.append("")
        output.append(f"  8. 水力半径计算:")
        output.append(f"      R = A / χ")
        output.append(f"        = {A_d:.3f} / {P_d:.3f}")
        output.append(f"        = {R_d:.3f} m")
        output.append("")
        output.append(f"  9. 设计流速计算 (曼宁公式):")
        output.append(f"      V = (1/n) × R^(2/3) × i^(1/2)")
        output.append(f"        = (1/{n}) × {R_d:.3f}^(2/3) × {i:.6f}^(1/2)")
        output.append(f"        = {1/n:.2f} × {R_d**(2/3):.4f} × {math.sqrt(i):.6f}")
        output.append(f"        = {V_d:.3f} m/s")
        output.append("")
        output.append(f"  10. 流量校核:")
        output.append(f"      Q计算 = V × A")
        output.append(f"           = {V_d:.3f} × {A_d:.3f}")
        output.append(f"           = {Q_check_d:.3f} m³/s")
        if Q_check_d > 0:
            output.append(f"      误差 = {abs(Q_check_d-Q)/Q*100:.2f}%")
        output.append("")
        output.append(f"  11. 净空高度:")
        output.append(f"      Fb = D - h = {D_design:.3f} - {h_d:.3f} = {FB_d:.3f} m")
        output.append("")
        output.append(f"  12. 净空面积:")
        output.append(f"      PA = (A总 - A) / A总 × 100%")
        output.append(f"         = ({pipe_area:.3f} - {A_d:.3f}) / {pipe_area:.3f} × 100%")
        output.append(f"         = {PA_d:.1f}%")
        output.append("")
            
        # 加大流量工况
        output.append("【四、加大流量工况计算】")
        output.append("")
        output.append(f"  13. 加大流量计算:")
        output.append(f"      流量加大比例 = {increase_info}")
        output.append(f"      Q加大 = Q × (1 + {increase_pct/100:.2f})")
        output.append(f"           = {Q:.3f} × {1+increase_pct/100:.2f}")
        output.append(f"           = {Q_inc:.3f} m³/s")
        output.append("")

        if h_i is not None and h_i > 0 and D_design > 0:
            output.append(f"  14. 加大水深:")
            output.append(f"      h加大 = {h_i:.3f} m")
            output.append("")

            R_radius_inc = D_design / 2
            theta_i = 2 * math.acos((R_radius_inc - h_i) / R_radius_inc)
            output.append(f"  15. 圆心角计算:")
            output.append(f"      θ加大 = 2 × arccos((R - h加大) / R)")
            output.append(f"           = 2 × arccos(({R_radius_inc:.3f} - {h_i:.3f}) / {R_radius_inc:.3f})")
            output.append(f"           = 2 × arccos({(R_radius_inc - h_i)/R_radius_inc:.4f})")
            output.append(f"           = {math.degrees(theta_i):.2f}° ({theta_i:.4f} rad)")
            output.append("")

            output.append(f"  16. 过水面积计算:")
            output.append(f"      A加大 = (D²/8) × (θ加大 - sinθ加大)")
            output.append(f"           = ({D_design:.3f}²/8) × ({theta_i:.4f} - sin{theta_i:.4f})")
            output.append(f"           = {A_i:.3f} m²")
            output.append("")

            output.append(f"  17. 湿周计算:")
            output.append(f"      χ加大 = D × θ加大 / 2")
            output.append(f"           = {D_design:.3f} × {theta_i:.4f} / 2")
            output.append(f"           = {P_i:.3f} m")
            output.append("")
        else:
            output.append(f"  14. 加大水深: h加大 = N/A")
            output.append("")

        output.append(f"  18. 水力半径计算:")
        output.append(f"      R加大 = A加大 / χ加大")
        output.append(f"           = {A_i:.3f} / {P_i:.3f}")
        output.append(f"           = {R_i:.3f} m")
        output.append("")

        output.append(f"  19. 加大流速计算 (曼宁公式):")
        output.append(f"      V加大 = (1/n) × R加大^(2/3) × i^(1/2)")
        output.append(f"           = (1/{n}) × {R_i:.3f}^(2/3) × {i:.6f}^(1/2)")
        output.append(f"           = {1/n:.2f} × {R_i**(2/3):.4f} × {math.sqrt(i):.6f}")
        output.append(f"           = {V_i:.3f} m/s")
        output.append("")

        output.append(f"  20. 流量校核:")
        output.append(f"      Q计算 = V加大 × A加大")
        output.append(f"           = {V_i:.3f} × {A_i:.3f}")
        output.append(f"           = {Q_check_i:.3f} m³/s")
        output.append("")

        output.append(f"  21. 净空高度计算:")
        output.append(f"      Fb加大 = D - h加大")
        output.append(f"           = {D_design:.3f} - {h_i:.3f}")
        output.append(f"           = {FB_i:.3f} m")
        output.append("")

        output.append(f"  22. 净空面积计算:")
        output.append(f"      PA加大 = (A总 - A加大) / A总 × 100%")
        output.append(f"           = ({pipe_area:.3f} - {A_i:.3f}) / {pipe_area:.3f} × 100%")
        output.append(f"           = {PA_i:.1f}%")
        output.append("")
            
        # 最小流量工况
        output.append("【五、最小流量工况计算】")
        output.append(f"  Q最小 = {Q_min:.3f} m³/s" if Q_min is not None else "  Q最小 = N/A")
        output.append(f"  水深 h最小 = {h_m:.3f} m" if h_m is not None else "  水深 h最小 = N/A")
        output.append(f"  流速 V最小 = {V_m:.3f} m/s" if V_m is not None else "  流速 V最小 = N/A")
        output.append("")
            
        # 验证结果
        output.append("【六、设计验证】")
        output.append("")
        velocity_ok = V_d is not None and v_min <= V_d <= v_max
        fb_ok = FB_i is not None and FB_i >= MIN_FREEBOARD
        pa_ok = PA_i is not None and PA_i >= MIN_FREE_AREA_PERCENT
        min_v_ok = V_m is not None and V_m >= v_min
            
        output.append(f"  23. 流速验证:")
        output.append(f"      不淤流速 ≤ V ≤ 不冲流速")
        if V_d is not None:
            output.append(f"      {v_min} ≤ {V_d:.3f} ≤ {v_max}")
            output.append(f"      结果: {'通过 ✓' if velocity_ok else '未通过 ✗'}")
        else:
            output.append(f"      计算失败")
        output.append("")
        output.append(f"  24. 净空高度验证:")
        output.append(f"      Fb加大 ≥ {MIN_FREEBOARD}")
        if FB_i is not None:
            output.append(f"      {FB_i:.3f} ≥ {MIN_FREEBOARD}")
            output.append(f"      结果: {'通过 ✓' if fb_ok else '未通过 ✗'}")
        else:
            output.append(f"      计算失败")
        output.append("")
        output.append(f"  25. 净空面积验证:")
        output.append(f"      PA加大 ≥ {MIN_FREE_AREA_PERCENT}%")
        if PA_i is not None:
            output.append(f"      {PA_i:.1f}% ≥ {MIN_FREE_AREA_PERCENT}%")
            output.append(f"      结果: {'通过 ✓' if pa_ok else '未通过 ✗'}")
        else:
            output.append(f"      计算失败")
        output.append("")
        output.append(f"  26. 最小流速验证:")
        output.append(f"      V最小 ≥ 不淤流速")
        if V_m is not None:
            output.append(f"      {V_m:.3f} ≥ {v_min}")
            output.append(f"      结果: {'通过 ✓' if min_v_ok else '未通过 ✗'}")
        else:
            output.append(f"      计算失败")
        output.append("")
            
        all_pass = velocity_ok and fb_ok and pa_ok and min_v_ok
        output.append("=" * 70)
        output.append(f"  综合验证结果: {'全部通过 ✓' if all_pass else '未通过 ✗'}")
        output.append("=" * 70)
            
        self.result_text.insert(tk.END, "\n".join(output))
        self.result_text.configure(state=tk.DISABLED)
    
    def _update_trapezoid_result_display(self, result):
        """显示梯形/矩形断面计算结果"""
        # 获取参数
        Q = self.input_params['Q']
        m = self.input_params['m']
        n = self.input_params['n']
        slope_inv = self.input_params['slope_inv']
        v_min = self.input_params['v_min']
        v_max = self.input_params['v_max']
        section_type = self.input_params.get('section_type', '梯形')
        
        i = 1 / slope_inv
        
        # 设计结果
        b = result['b_design']
        h = result['h_design']
        V = result['V_design']
        A = result['A_design']
        χ = result['X_design']  # 湿周
        R = result['R_design']
        β = result['Beta_design']
        Q_计算 = result['Q_calc']
        
        # 加大流量
        inc_pct = result['increase_percent']
        Q_加大 = result['Q_increased']
        h_加大 = result['h_increased']
        V_加大 = result['V_increased']
        Fb = result['Fb']
        H = result['h_prime']
        
        # 判断加大比例来源
        manual_increase = self.input_params.get('manual_increase')
        inc_source = "(手动指定)" if manual_increase else "(自动计算)"
        
        output = []
        output.append("=" * 70)
        output.append(f"              明渠水力计算结果（{section_type}断面）")
        output.append("=" * 70)
        output.append("")
        
        # 输入参数
        output.append("【一、输入参数】")
        output.append(f"  断面类型 = {section_type}")
        output.append(f"  设计流量 Q = {Q:.3f} m³/s")
        if section_type == "梯形":
            output.append(f"  边坡系数 m = {m}")
        output.append(f"  糙率 n = {n}")
        output.append(f"  水力坡降 1/{int(slope_inv)}")
        output.append(f"  不淤流速 = {v_min} m/s")
        output.append(f"  不冲流速 = {v_max} m/s")
        
        if self.input_params.get('manual_beta'):
            output.append(f"  [手动] 宽深比 β = {self.input_params['manual_beta']}")
        if self.input_params.get('manual_b'):
            output.append(f"  [手动] 底宽 B = {self.input_params['manual_b']} m")
        if self.input_params.get('manual_increase'):
            output.append(f"  [手动] 加大比例 = {self.input_params['manual_increase']}%")
        output.append("")
        
        # 设计方法
        output.append("【二、设计方法】")
        output.append(f"  采用方法: {result['design_method']}")
        output.append("")
        
        # 如果有附录E备选方案，展示方案对比表
        appendix_e_schemes = result.get('appendix_e_schemes', [])
        if appendix_e_schemes:
            output.append("【附录E断面方案对比表】")
            output.append("  说明: α=1.00为水力最佳断面(深窄)，α越大断面越宽浅，面积增加但流速降低")
            output.append("")
            output.append("  +-------+----------------+---------+---------+---------+---------+----------+----------+")
            output.append("  | α值   |    方案类型     | 底宽B   | 水深h    | 宽深比β | 流速V    | 面积增加 |   状态    |")
            output.append("  |       |                |   (m)   |   (m)   |         |  (m/s)  |          |          |")
            output.append("  +-------+----------------+---------+---------+---------+---------+----------+----------+")
            
            for scheme in appendix_e_schemes:
                alpha = scheme['alpha']
                stype = scheme['scheme_type']
                sb = scheme['b']
                sh = scheme['h']
                sbeta = scheme['beta']
                sV = scheme['V']
                area_inc = scheme['area_increase']
                
                # 判断是否为选中的方案
                is_selected = abs(sb - b) < 0.01 and abs(sh - h) < 0.01
                status = "★选中" if is_selected else ""
                
                # 检查流速是否满足约束
                v_ok = v_min < sV < v_max
                if not v_ok:
                    status = "流速不符"
                
                # 使用pad_str处理中文字符宽度对齐
                alpha_str = f"{alpha:.2f}"
                stype_str = pad_str(stype, 14, 'center')  # 方案类型居中，显示宽度14
                area_str = f"+{area_inc:.0f}%"
                status_str = pad_str(status, 8, 'center')  # 状态居中，显示宽度8
                output.append(f"  | {alpha_str:^5} | {stype_str} | {sb:7.3f} | {sh:7.3f} | {sbeta:7.3f} | {sV:7.3f} | {area_str:^8} | {status_str} |")
            
            output.append("  +-------+----------------+---------+---------+---------+---------+----------+----------+")
            output.append("")
            output.append(f"  注: 流速约束范围 {v_min} ~ {v_max} m/s")
            output.append("")
        
        # 设计结果
        output.append("【三、设计结果】")
        output.append("")
        output.append("  1. 设计底宽:")
        output.append(f"     B = {b:.3f} m")
        output.append("")
        output.append("  2. 设计水深:")
        output.append(f"     h = {h:.3f} m")
        output.append("")
        output.append("  3. 宽深比:")
        output.append(f"     β = B/h = {b:.3f}/{h:.3f} = {β:.3f}")
        output.append("")
        output.append("  4. 过水面积计算:")
        output.append(f"     A = (B + m×h) × h")
        output.append(f"       = ({b:.3f} + {m}×{h:.3f}) × {h:.3f}")
        output.append(f"       = {A:.3f} m²")
        output.append("")
        output.append("  5. 湿周计算:")
        sqrt_1_m2 = math.sqrt(1 + m*m)
        output.append(f"     χ = B + 2×h×√(1+m²)")
        output.append(f"       = {b:.3f} + 2×{h:.3f}×√(1+{m}²)")
        output.append(f"       = {b:.3f} + 2×{h:.3f}×{sqrt_1_m2:.4f}")
        output.append(f"       = {χ:.3f} m")
        output.append("")
        output.append("  6. 水力半径计算:")
        output.append(f"     R = A/χ = {A:.3f}/{χ:.3f} = {R:.3f} m")
        output.append("")
        output.append("  7. 设计流速计算 (曼宁公式):")
        output.append(f"     V = (1/n) × R^(2/3) × i^(1/2)")
        output.append(f"       = (1/{n}) × {R:.3f}^(2/3) × {i:.6f}^(1/2)")
        output.append(f"       = {1/n:.2f} × {R**(2/3):.4f} × {math.sqrt(i):.6f}")
        output.append(f"       = {V:.3f} m/s")
        output.append("")
        output.append("  8. 流量校核:")
        output.append(f"      Q计算 = V × A = {V:.3f} × {A:.3f} = {Q_计算:.3f} m³/s")
        output.append(f"      误差 = {abs(Q_计算-Q)/Q*100:.2f}%")
        output.append("")
        
        # 加大流量工况
        output.append("【四、加大流量工况计算】")
        output.append("")
        output.append("  9. 加大流量计算:")
        output.append(f"      流量加大比例 = {inc_pct:.1f}% {inc_source}")
        output.append(f"      Q加大 = Q × (1 + {inc_pct/100:.2f})")
        output.append(f"           = {Q:.3f} × {1+inc_pct/100:.2f}")
        output.append(f"           = {Q_加大:.3f} m³/s")
        output.append("")
        
        if h_加大 > 0:
            output.append(f"  10. 加大水深: h加大 = {h_加大:.3f} m")
            output.append("")
            output.append(f"  11. 加大流速: V加大 = {V_加大:.3f} m/s")
            output.append("")
            output.append("  12. 渠道岸顶超高计算:")
            output.append(f"      Fb = (1/4) × h加大 + 0.2")
            output.append(f"         = (1/4) × {h_加大:.3f} + 0.2")
            output.append(f"         = {Fb:.3f} m")
            output.append("")
            output.append("  13. 渠道高度计算:")
            output.append(f"      H = h加大 + Fb")
            output.append(f"        = {h_加大:.3f} + {Fb:.3f}")
            output.append(f"        = {H:.3f} m")
        else:
            output.append("  加大水深计算失败")
        output.append("")
        
        # 验证
        output.append("【五、设计验证】")
        output.append("")
        
        velocity_ok = v_min < V < v_max
        output.append(f"  14. 流速验证:")
        output.append(f"      范围要求: {v_min} < V < {v_max} m/s")
        output.append(f"      设计流速: V = {V:.3f} m/s")
        output.append(f"      结果: {'通过 ✓' if velocity_ok else '未通过 ✗'}")
        output.append("")
        
        beta_ok = 0 < β <= MAX_BETA
        output.append(f"  15. 宽深比验证:")
        output.append(f"      规范要求: 0 < β ≤ {MAX_BETA}")
        output.append(f"      计算结果: β = {β:.3f}")
        output.append(f"      结果: {'通过 ✓' if beta_ok else '未通过 ✗'}")
        output.append("")
        
        # 16. 超高复核（规范 6.4.8-2）
        fb_req = 0.25 * h_加大 + 0.2
        fb_ok = Fb >= (fb_req - 0.001)
        output.append(f"  16. 超高复核（规范 6.4.8-2）:")
        output.append(f"      规范要求: Fb ≥ (1/4)×h加大 + 0.2 = {fb_req:.3f} m")
        output.append(f"      计算结果: Fb = {Fb:.3f} m")
        output.append(f"      结果: {'通过 ✓' if fb_ok else '未通过 ✗'}")
        output.append("")
        
        all_pass = velocity_ok and beta_ok and fb_ok
        output.append("=" * 70)
        output.append(f"  综合验证结果: {'全部通过 ✓' if all_pass else '未通过 ✗'}")
        output.append("=" * 70)
        
        self.result_text.insert(tk.END, "\n".join(output))
        self.result_text.configure(state=tk.DISABLED)
    
    def _update_section_plot(self, result):
        """更新断面图"""
        self.section_fig.clear()
        
        if not result['success']:
            return
        
        section_type = self.input_params.get('section_type', '梯形')
        
        # 根据断面类型绘制不同的断面图
        if section_type == '圆形':
            # 圆形断面使用原圆形管道的绘图方法
            D = result.get('D_design', 0)
            y_d = result.get('y_d', 0)
            V_d = result.get('V_d', 0)
            Q = self.input_params['Q']
            
            ax = self.section_fig.add_subplot(111)
            self._draw_circular_section(ax, D, y_d, V_d, Q, '设计流量')
        else:
            # 矩形/梯形断面
            b = result['b_design']
            h = result['h_design']
            m = self.input_params['m']
            Q = self.input_params['Q']
            V = result['V_design']
            
            h_inc = result['h_increased']
            Q_inc = result['Q_increased']
            V_inc = result['V_increased']
            h_prime = result['h_prime']
            
            axes = self.section_fig.subplots(1, 2)
            
            # 设计流量断面
            self._draw_trapezoid_section(axes[0], b, h, m, V, Q, h, "设计流量")
            
            # 加大流量断面
            if h_inc > 0:
                self._draw_trapezoid_section(axes[1], b, h_prime, m, V_inc, Q_inc, h_inc, "加大流量")
            else:
                axes[1].set_title("加大流量\n数据不可用")
        
        self.section_fig.tight_layout()
        self.section_canvas.draw()
    
    def _draw_circular_section(self, ax, D, y, V, Q, title):
        """绘制圆形断面"""
        R = D / 2
        
        theta = np.linspace(0, 2*np.pi, 100)
        circle_x = R * np.cos(theta)
        circle_y = R + R * np.sin(theta)
        ax.plot(circle_x, circle_y, 'k-', linewidth=2)
        
        if y > 0 and y < D:
            h = y - R
            if abs(h) <= R:
                half_angle = math.acos(h / R)
                water_width = math.sqrt(R**2 - h**2)
                
                water_angles = np.linspace(np.pi/2 + half_angle, 
                                           np.pi/2 - half_angle + 2*np.pi, 50)
                water_x = R * np.cos(water_angles)
                water_y = R + R * np.sin(water_angles)
                
                mask = water_y <= y + 0.001
                water_x_f = water_x[mask]
                water_y_f = water_y[mask]
                
                if len(water_x_f) > 0:
                    poly_x = np.concatenate([[water_width], water_x_f, [-water_width]])
                    poly_y = np.concatenate([[y], water_y_f, [y]])
                    ax.fill(poly_x, poly_y, color='lightblue', alpha=0.7)
                    ax.plot([-water_width, water_width], [y, y], 'b-', linewidth=1.5)
        
        # 添加尺寸标注
        # 标注直径 D
        ax.annotate('', xy=(R, R), xytext=(-R, R),
                   arrowprops=dict(arrowstyle='<->', color='gray', lw=1.5))
        ax.text(0, R+0.15*R, f'D={D:.2f}m', ha='center', fontsize=9, color='gray')
        
        # 标注水深 y
        if y > 0:
            ax.annotate('', xy=(-R-0.12*R, y), xytext=(-R-0.12*R, 0),
                       arrowprops=dict(arrowstyle='<->', color='blue', lw=1.5))
            ax.text(-R-0.2*R, y/2, f'y={y:.2f}m', ha='right', fontsize=8, color='blue', rotation=90, va='center')
        
        ax.set_xlim(-R*1.7, R*1.7)
        ax.set_ylim(-R*0.4, D*1.2)
        ax.set_aspect('equal')
        ax.set_title(f'{title}\nQ={Q:.2f}m$^3$/s, V={V:.2f}m/s', fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.axhline(y=0, color='brown', linewidth=3)
    
    def _draw_trapezoid_section(self, ax, b, h_channel, m, V, Q, h_water, title):
        """绘制梯形断面"""
        # 渠道轮廓
        top_width = b + 2 * m * h_channel
        
        # 底部
        ax.plot([-b/2, b/2], [0, 0], 'k-', linewidth=2)
        # 左侧边坡
        ax.plot([-b/2, -top_width/2], [0, h_channel], 'k-', linewidth=2)
        # 右侧边坡
        ax.plot([b/2, top_width/2], [0, h_channel], 'k-', linewidth=2)
        # 顶部
        ax.plot([-top_width/2, top_width/2], [h_channel, h_channel], 'k--', linewidth=1)
        
        # 水流区域
        if h_water > 0:
            water_top_width = b + 2 * m * h_water
            water_x = [-b/2, -water_top_width/2, water_top_width/2, b/2]
            water_y = [0, h_water, h_water, 0]
            ax.fill(water_x, water_y, color='lightblue', alpha=0.7)
            ax.plot([-water_top_width/2, water_top_width/2], [h_water, h_water], 'b-', linewidth=1.5)
        
        # 标注尺寸
        # 底宽 B
        ax.annotate('', xy=(b/2, -0.1*h_channel), xytext=(-b/2, -0.1*h_channel),
                   arrowprops=dict(arrowstyle='<->', color='gray', lw=1.5))
        ax.text(0, -0.2*h_channel, f'B={b:.2f}m', ha='center', fontsize=9, color='gray')
        
        # 渠道高度 H
        ax.annotate('', xy=(top_width/2+0.08*top_width, h_channel), xytext=(top_width/2+0.08*top_width, 0),
                   arrowprops=dict(arrowstyle='<->', color='purple', lw=1.5))
        ax.text(top_width/2+0.12*top_width, h_channel/2, f'H={h_channel:.2f}m', fontsize=9, color='purple', rotation=90, va='center')
        
        # 水深 h
        if h_water > 0:
            ax.annotate('', xy=(-top_width/2-0.08*top_width, h_water), xytext=(-top_width/2-0.08*top_width, 0),
                       arrowprops=dict(arrowstyle='<->', color='blue', lw=1.5))
            ax.text(-top_width/2-0.12*top_width, h_water/2, f'h={h_water:.2f}m', fontsize=9, color='blue', rotation=90, va='center', ha='right')
        
        ax.set_xlim(-top_width*0.85, top_width*0.85)
        ax.set_ylim(-h_channel*0.4, h_channel*1.2)
        ax.set_aspect('equal')
        ax.set_title(f'{title}\nQ={Q:.2f}m$^3$/s, V={V:.2f}m/s', fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.axhline(y=0, color='brown', linewidth=3)
    
    def _clear(self):
        """清空"""
        self._show_initial_help()
        
        if VIZ_MODULE_LOADED:
            self.section_fig.clear()
            self.section_canvas.draw()
    
    def _export_charts(self):
        """导出图表"""
        if not hasattr(self, 'current_result') or not self.current_result or not self.current_result['success']:
            messagebox.showwarning("警告", "请先进行计算")
            return
        
        folder = filedialog.askdirectory(title="选择保存目录")
        if not folder:
            return
        
        try:
            self.section_fig.savefig(os.path.join(folder, '明渠断面图.png'), dpi=150, bbox_inches='tight')
            messagebox.showinfo("成功", f"图表已保存到: {folder}")
        except Exception as e:
            messagebox.showerror("错误", f"保存失败: {str(e)}")
    
    def _export_report(self):
        """导出报告"""
        if not hasattr(self, 'current_result') or not self.current_result or not self.current_result['success']:
            messagebox.showwarning("警告", "请先进行计算")
            return
        
        filepath = filedialog.asksaveasfilename(
            title="保存报告",
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")]
        )
        if not filepath:
            return
        
        try:
            self.result_text.configure(state=tk.NORMAL)
            content = self.result_text.get(1.0, tk.END)
            self.result_text.configure(state=tk.DISABLED)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            
            messagebox.showinfo("成功", f"报告已保存到: {filepath}")
        except Exception as e:
            messagebox.showerror("错误", f"保存失败: {str(e)}")


# ============================================================
# 渡槽计算面板
# ============================================================

class AqueductPanel(ttk.Frame):
    """渡槽计算面板（支持U形和矩形断面）"""
    
    def __init__(self, parent):
        super().__init__(parent)
        
        self.input_params = {}
        self.current_result = None
        self.show_detail_var = tk.BooleanVar(value=True)  # 默认显示详细过程
        self.formula_images = []  # 保持对LaTeX公式图像的引用，防止垃圾回收
        
        self._create_ui()
    
    def _create_ui(self):
        """创建UI"""
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        self._create_input_panel(main_frame)
        self._create_output_panel(main_frame)
    
    def _create_input_panel(self, parent):
        """创建输入面板"""
        input_frame = ttk.LabelFrame(parent, text="输入参数", padding="10")
        input_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        
        # 断面类型选择
        self.section_type_var = tk.StringVar(value="U形")
        
        row = 0
        ttk.Label(input_frame, text="断面类型:").grid(row=row, column=0, sticky=tk.W, pady=5)
        section_combo = ttk.Combobox(input_frame, textvariable=self.section_type_var, 
                                      width=12, values=["U形", "矩形"], state='readonly')
        section_combo.grid(row=row, column=1, padx=5, pady=5)
        section_combo.bind('<<ComboboxSelected>>', self._on_section_type_changed)
        
        # 基本参数
        self.Q_var = tk.DoubleVar(value=5.0)
        self.n_var = tk.DoubleVar(value=0.014)
        self.slope_inv_var = tk.DoubleVar(value=3000)
        self.v_min_var = tk.DoubleVar(value=0.1)
        self.v_max_var = tk.DoubleVar(value=100.0)
        
        row += 1
        ttk.Label(input_frame, text="设计流量 Q (m³/s):").grid(row=row, column=0, sticky=tk.W, pady=5)
        ttk.Entry(input_frame, textvariable=self.Q_var, width=15).grid(row=row, column=1, padx=5, pady=5)
        
        row += 1
        ttk.Label(input_frame, text="糙率 n:").grid(row=row, column=0, sticky=tk.W, pady=5)
        ttk.Entry(input_frame, textvariable=self.n_var, width=15).grid(row=row, column=1, padx=5, pady=5)
        
        row += 1
        ttk.Label(input_frame, text="水力坡降 1/").grid(row=row, column=0, sticky=tk.W, pady=5)
        ttk.Entry(input_frame, textvariable=self.slope_inv_var, width=15).grid(row=row, column=1, padx=5, pady=5)
        
        # 流速参数栏目
        row += 1
        ttk.Label(input_frame, text="【流速参数】", font=('', 9, 'bold')).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=5)
        
        row += 1
        ttk.Label(input_frame, text="不淤流速 (m/s):").grid(row=row, column=0, sticky=tk.W, pady=5)
        ttk.Entry(input_frame, textvariable=self.v_min_var, width=15).grid(row=row, column=1, padx=5, pady=5)
        
        row += 1
        ttk.Label(input_frame, text="不冲流速 (m/s):").grid(row=row, column=0, sticky=tk.W, pady=5)
        ttk.Entry(input_frame, textvariable=self.v_max_var, width=15).grid(row=row, column=1, padx=5, pady=5)
        
        # 流速提示
        row += 1
        ttk.Label(input_frame, text="(一般情况下保持默认数值即可)", font=('', 8), foreground='black').grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=2)
        
        # 流量加大比例栏目
        row += 1
        ttk.Label(input_frame, text="【流量加大】", font=('', 9, 'bold')).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=5)
        
        row += 1
        self.manual_increase_var = tk.StringVar(value="")
        ttk.Label(input_frame, text="流量加大比例 (%):").grid(row=row, column=0, sticky=tk.W, pady=3)
        ttk.Entry(input_frame, textvariable=self.manual_increase_var, width=15).grid(row=row, column=1, padx=5, pady=3)
        
        row += 1
        self.increase_hint_var = tk.StringVar(value="(留空则自动计算)")
        self.increase_hint_label = ttk.Label(input_frame, textvariable=self.increase_hint_var, font=('', 8), foreground='black')
        self.increase_hint_label.grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=2)
        
        # 分隔线
        row += 1
        ttk.Separator(input_frame, orient=tk.HORIZONTAL).grid(row=row, column=0, columnspan=2, 
                                                                sticky=tk.EW, pady=10)
        
        # 可选参数标签
        row += 1
        ttk.Label(input_frame, text="【可选参数】", font=('', 9, 'bold')).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=5)
        
        # U形断面参数框
        row += 1
        self.u_frame = ttk.LabelFrame(input_frame, text="U形断面参数", padding="5")
        self.u_frame.grid(row=row, column=0, columnspan=2, sticky=tk.EW, pady=5)
        
        self.manual_R_var = tk.StringVar(value="")
        ttk.Label(self.u_frame, text="手动内半径 R (m):").grid(row=0, column=0, sticky=tk.W, pady=3)
        ttk.Entry(self.u_frame, textvariable=self.manual_R_var, width=15).grid(row=0, column=1, padx=5, pady=3)
        ttk.Label(self.u_frame, text="(留空则自动计算)", font=('', 8), foreground='black').grid(row=1, column=0, columnspan=2, sticky=tk.W)
        
        # 矩形断面参数框
        row += 1
        self.rect_frame = ttk.LabelFrame(input_frame, text="矩形断面参数", padding="5")
        self.rect_frame.grid(row=row, column=0, columnspan=2, sticky=tk.EW, pady=5)
        
        self.depth_width_ratio_var = tk.StringVar(value="")  # 改为StringVar以支持留空
        self.manual_B_var = tk.StringVar(value="")  # 手动槽宽B
        self.chamfer_angle_var = tk.DoubleVar(value=0)
        self.chamfer_length_var = tk.DoubleVar(value=0)
        
        ttk.Label(self.rect_frame, text="深宽比 (H/B):").grid(row=0, column=0, sticky=tk.W, pady=3)
        ttk.Entry(self.rect_frame, textvariable=self.depth_width_ratio_var, width=15).grid(row=0, column=1, padx=5, pady=3)
        ttk.Label(self.rect_frame, text="(留空默认0.8)", font=('', 8), foreground='black').grid(row=1, column=0, columnspan=2, sticky=tk.W)
        
        ttk.Label(self.rect_frame, text="槽宽 B (m):").grid(row=2, column=0, sticky=tk.W, pady=3)
        ttk.Entry(self.rect_frame, textvariable=self.manual_B_var, width=15).grid(row=2, column=1, padx=5, pady=3)
        ttk.Label(self.rect_frame, text="(二选一，都留空按深宽比0.8计算)", font=('', 8), foreground='gray').grid(row=3, column=0, columnspan=2, sticky=tk.W)
        
        ttk.Label(self.rect_frame, text="倒角角度 (度):").grid(row=4, column=0, sticky=tk.W, pady=3)
        ttk.Entry(self.rect_frame, textvariable=self.chamfer_angle_var, width=15).grid(row=4, column=1, padx=5, pady=3)
        
        ttk.Label(self.rect_frame, text="倒角底边 (m):").grid(row=5, column=0, sticky=tk.W, pady=3)
        ttk.Entry(self.rect_frame, textvariable=self.chamfer_length_var, width=15).grid(row=5, column=1, padx=5, pady=3)
        
        self.rect_frame.grid_remove()  # 默认隐藏矩形参数
        
        # 分隔线
        row += 1
        ttk.Separator(input_frame, orient=tk.HORIZONTAL).grid(row=row, column=0, columnspan=2, 
                                                                sticky=tk.EW, pady=10)
        
        # 输出选项
        row += 1
        ttk.Checkbutton(input_frame, text="输出详细计算过程", 
                       variable=self.show_detail_var).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=5)
        
        # 按钮
        row += 1
        btn_frame = ttk.Frame(input_frame)
        btn_frame.grid(row=row, column=0, columnspan=2, pady=15)
        
        ttk.Button(btn_frame, text="计算", command=self._calculate, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="清空", command=self._clear, width=10).pack(side=tk.LEFT, padx=5)
        
        row += 1
        export_frame = ttk.Frame(input_frame)
        export_frame.grid(row=row, column=0, columnspan=2, pady=5)
        
        ttk.Button(export_frame, text="导出图表", command=self._export_charts, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Button(export_frame, text="导出报告", command=self._export_report, width=10).pack(side=tk.LEFT, padx=5)
    
    def _on_section_type_changed(self, event=None):
        """断面类型切换"""
        if self.section_type_var.get() == "U形":
            self.u_frame.grid()
            self.rect_frame.grid_remove()
        else:
            self.u_frame.grid_remove()
            self.rect_frame.grid()
    
    def _create_output_panel(self, parent):
        """创建输出面板"""
        output_frame = ttk.Frame(parent)
        output_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        self.notebook = ttk.Notebook(output_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        
        self.result_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.result_tab, text="计算结果")
        self._create_result_view(self.result_tab)
        
        if VIZ_MODULE_LOADED:
            self.section_tab = ttk.Frame(self.notebook)
            self.notebook.add(self.section_tab, text="断面图")
            self._create_section_view(self.section_tab)
    
    def _create_result_view(self, parent):
        """创建结果视图"""
        result_frame = ttk.LabelFrame(parent, text="计算结果详情", padding="10")
        result_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.result_text = tk.Text(result_frame, wrap=tk.WORD, font=('Consolas', 11), 
                                    bg='#f5f5f5', relief=tk.FLAT)
        self.result_text.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(self.result_text, orient=tk.VERTICAL, 
                                   command=self.result_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.result_text.configure(yscrollcommand=scrollbar.set)
        
        self._show_initial_help()
    
    def _show_initial_help(self):
        """显示初始帮助（含LaTeX公式渲染，支持中文下标）"""
        self.result_text.configure(state=tk.NORMAL)
        self.result_text.delete(1.0, tk.END)
        self.formula_images.clear()  # 清除旧的图像引用
        
        # 辅助函数：插入纯LaTeX公式图像
        def insert_formula(latex_str, fontsize=12):
            if VIZ_MODULE_LOADED:
                try:
                    img = render_latex_formula(latex_str, fontsize=fontsize, dpi=100)
                    self.formula_images.append(img)
                    self.result_text.image_create(tk.END, image=img)
                    self.result_text.insert(tk.END, "\n")
                    return True
                except Exception:
                    pass
            self.result_text.insert(tk.END, f"  {latex_str}\n")
            return False
        
        # 辅助函数：插入混合公式图像（支持中文下标）
        def insert_hybrid(parts, fontsize=12):
            if VIZ_MODULE_LOADED:
                try:
                    img = render_hybrid_formula(parts, fontsize=fontsize, dpi=100)
                    self.formula_images.append(img)
                    self.result_text.image_create(tk.END, image=img)
                    self.result_text.insert(tk.END, "\n")
                    return True
                except Exception:
                    pass
            # 回退到文本显示
            text = ''.join([p[0] for p in parts])
            self.result_text.insert(tk.END, f"  {text}\n")
            return False
        
        self.result_text.insert(tk.END, '请输入参数后点击"计算"按钮开始计算...\n\n')
        self.result_text.insert(tk.END, "=" * 50 + "\n")
        self.result_text.insert(tk.END, "渡槽水力计算说明\n")
        self.result_text.insert(tk.END, "=" * 50 + "\n\n")
        self.result_text.insert(tk.END, "本程序支持以下断面类型：\n\n")
        self.result_text.insert(tk.END, "1. U形断面\n")
        self.result_text.insert(tk.END, "   - 底部半圆 + 直立侧墙\n")
        self.result_text.insert(tk.END, "   - 推荐 f/R = 0.4~0.6\n")
        self.result_text.insert(tk.END, "   - 推荐 H/(2R) = 0.7~0.9\n\n")
        self.result_text.insert(tk.END, "2. 矩形断面\n")
        self.result_text.insert(tk.END, "   - 可选倒角设计\n")
        self.result_text.insert(tk.END, "   - 深宽比(H/B)定义：槽身总高度 / 槽宽\n")
        self.result_text.insert(tk.END, "   - 深宽比推荐值：0.6 ~ 0.8\n\n")
        
        # 矩形渡槽详细计算流程
        self.result_text.insert(tk.END, "【矩形渡槽计算流程】\n\n")
        self.result_text.insert(tk.END, "一、输入参数\n")
        self.result_text.insert(tk.END, "  • Q  — 设计流量 (m³/s)\n")
        self.result_text.insert(tk.END, "  • n  — 糙率\n")
        self.result_text.insert(tk.END, "  • i  — 水力坡降 (= 1/坡降倒数)\n")
        self.result_text.insert(tk.END, "  • α  — 深宽比约束 (默认0.8)\n\n")
        
        self.result_text.insert(tk.END, "二、加大流量计算\n")
        self.result_text.insert(tk.END, "  加大比例根据设计流量自动确定（规范9.4.1-1表）：\n")
        self.result_text.insert(tk.END, "    Q < 1 m³/s       → 加大 30%\n")
        self.result_text.insert(tk.END, "    1 ≤ Q < 10       → 加大 25%\n")
        self.result_text.insert(tk.END, "    10 ≤ Q < 100     → 加大 20%\n")
        self.result_text.insert(tk.END, "    Q ≥ 100          → 加大 15%\n")
        self.result_text.insert(tk.END, "  加大流量公式：")
        # 使用混合渲染：Q_加大 = Q × (1 + k)
        insert_hybrid([("Q", "math"), ("加大", "sub"), ("= Q \\times (1 + k)", "math")], fontsize=12)
        self.result_text.insert(tk.END, "  其中 k 为加大比例\n")
        
        self.result_text.insert(tk.END, "\n三、槽宽B搜索（深宽比模式）\n")
        self.result_text.insert(tk.END, "  搜索范围：B ∈ [0.50m, 20.0m]，步长 0.01m\n")
        self.result_text.insert(tk.END, "  对每个试算槽宽B，计算目标槽高：")
        # H_目标 = B × α
        insert_hybrid([("H", "math"), ("目标", "sub"), ("= B \\times \\alpha", "math")], fontsize=12)
        
        self.result_text.insert(tk.END, "\n四、水深计算（曼宁公式反算）\n")
        self.result_text.insert(tk.END, "  已知Q、B、n、i，求水深h，满足曼宁公式：\n")
        insert_formula(r"Q = \frac{1}{n} \cdot A \cdot R^{2/3} \cdot i^{1/2}", fontsize=13)
        self.result_text.insert(tk.END, "  其中：\n")
        insert_formula(r"A = B \cdot h", fontsize=11)
        self.result_text.insert(tk.END, "    （过水断面积）\n")
        insert_formula(r"\chi = B + 2h", fontsize=11)
        self.result_text.insert(tk.END, "    （湿周）\n")
        insert_formula(r"R = A / \chi", fontsize=11)
        self.result_text.insert(tk.END, "    （水力半径）\n")
        self.result_text.insert(tk.END, "  采用二分法迭代求解 ")
        # h_设计 和 h_加大
        insert_hybrid([("h", "math"), ("设计", "sub"), (" ", "text"), ("和", "text"), (" h", "math"), ("加大", "sub")], fontsize=11)
        
        self.result_text.insert(tk.END, "\n五、槽高H确定（规范9.4.1-2）\n")
        self.result_text.insert(tk.END, "  分别计算两个工况所需槽高：\n\n")
        self.result_text.insert(tk.END, "  工况1（设计流量）:\n")
        # F_{b,设计} ≥ h_设计/12 + 0.05
        insert_hybrid([("F_{b,}", "math"), ("设计", "sub"), ("\\geq", "math"), ("h", "math"), ("设计", "sub"), ("/12 + 0.05", "math")], fontsize=11)
        # H_1 = h_设计 + F_{b,设计}
        insert_hybrid([("H_1 = h", "math"), ("设计", "sub"), ("+ F_{b,}", "math"), ("设计", "sub")], fontsize=11)
        
        self.result_text.insert(tk.END, "\n  工况2（加大流量）:\n")
        # F_{b,加大} ≥ 0.10 m
        insert_hybrid([("F_{b,}", "math"), ("加大", "sub"), ("\\geq 0.10 \\text{ m}", "math")], fontsize=11)
        # H_2 = h_加大 + 0.10
        insert_hybrid([("H_2 = h", "math"), ("加大", "sub"), ("+ 0.10", "math")], fontsize=11)
        
        self.result_text.insert(tk.END, "\n  取两者最大值：")
        insert_formula(r"H = \max(H_1, H_2)", fontsize=12)
        self.result_text.insert(tk.END, "  最终H向上取整至0.01m\n\n")
        
        self.result_text.insert(tk.END, "六、约束检验\n")
        self.result_text.insert(tk.END, "  若满足以下条件，则该B为有效解：")
        # H ≤ H_目标 = B × α
        insert_hybrid([("H \\leq H", "math"), ("目标", "sub"), ("= B \\times \\alpha", "math")], fontsize=11)
        self.result_text.insert(tk.END, "  取第一个满足条件的B作为最优解\n\n")
        
        self.result_text.insert(tk.END, "七、流速校核（规范9.4.1-1）\n")
        insert_formula(r"v = \frac{Q}{A}", fontsize=12)
        self.result_text.insert(tk.END, "  推荐流速范围：1.0 ~ 2.5 m/s\n\n")
        
        self.result_text.insert(tk.END, "-" * 50 + "\n\n")
        
        self.result_text.insert(tk.END, "【U形断面自动搜索逻辑】\n")
        self.result_text.insert(tk.END, "当U形断面未指定内半径R时，系统将自动搜索最优R：\n")
        self.result_text.insert(tk.END, "  • 搜索范围：R_min = 0.2m，R_max = 15.0m\n")
        self.result_text.insert(tk.END, "  • 搜索步长：0.01m\n")
        self.result_text.insert(tk.END, "  • 优化目标：在满足所有约束条件下，最小化槽身总面积\n")
        self.result_text.insert(tk.END, "  • 约束条件：\n")
        self.result_text.insert(tk.END, "    1. f/R 在 0.4~0.6 范围内\n")
        self.result_text.insert(tk.END, "    2. H/(2R) 在 0.7~0.9 范围内\n")
        self.result_text.insert(tk.END, "    3. 设计流量超高 ≥ R/5（规范 9.4.1-2）\n")
        self.result_text.insert(tk.END, "    4. 加大流量超高 ≥ 0.10m（规范 9.4.1-2）\n\n")
        self.result_text.insert(tk.END, "-" * 50 + "\n\n")
        self.result_text.insert(tk.END, "【基础公式】\n")
        self.result_text.insert(tk.END, "曼宁公式：")
        insert_formula(r"Q = \frac{1}{n} \cdot A \cdot R^{2/3} \cdot i^{1/2}", fontsize=12)
        self.result_text.insert(tk.END, "流速公式：")
        insert_formula(r"v = \frac{1}{n} \cdot R^{2/3} \cdot i^{1/2}", fontsize=12)
        self.result_text.configure(state=tk.DISABLED)
    
    def _create_section_view(self, parent):
        """创建断面图视图"""
        self.section_fig = Figure(figsize=(8, 6), dpi=100)
        self.section_canvas = FigureCanvasTkAgg(self.section_fig, master=parent)
        self.section_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        toolbar = NavigationToolbar2Tk(self.section_canvas, parent)
        toolbar.update()
        
    def _show_error_in_result(self, title, message):
        """在计算结果区域显示错误信息"""
        self.result_text.configure(state=tk.NORMAL)
        self.result_text.delete(1.0, tk.END)
            
        output = []
        output.append("=" * 70)
        output.append(f"  {title}")
        output.append("=" * 70)
        output.append("")
        output.append(message)
        output.append("")
        output.append("-" * 70)
        output.append("请修正后重新计算。")
        output.append("=" * 70)
            
        self.result_text.insert(tk.END, "\n".join(output))
        self.result_text.configure(state=tk.DISABLED)
        
    def _calculate(self):
        """执行计算"""
        if not DUCAO_MODULE_LOADED:
            self._show_error_in_result("模块加载错误", "渡槽计算模块未加载。")
            return
            
        try:
            Q = self.Q_var.get()
            n = self.n_var.get()
            slope_inv = self.slope_inv_var.get()
            v_min = self.v_min_var.get()
            v_max = self.v_max_var.get()
                
            if Q <= 0:
                self._show_error_in_result("参数错误", "请输入有效的设计流量 Q（必须大于0）。")
                return
            if n <= 0:
                self._show_error_in_result("参数错误", "请输入有效的糊率 n（必须大于0）。")
                return
            if slope_inv <= 0:
                self._show_error_in_result("参数错误", "请输入有效的水力坡降倒数（必须大于0）。")
                return
            
            manual_increase = None
            if self.manual_increase_var.get().strip():
                manual_increase = float(self.manual_increase_var.get())
            
            section_type = self.section_type_var.get()
            
            if section_type == "U形":
                manual_R = None
                if self.manual_R_var.get().strip():
                    manual_R = float(self.manual_R_var.get())
                
                result = ducao_u_calculate(
                    Q=Q, n=n, slope_inv=slope_inv,
                    v_min=v_min, v_max=v_max,
                    manual_R=manual_R,
                    manual_increase_percent=manual_increase
                )
            else:
                # 矩形断面 - 处理深宽比和槽宽B
                depth_width_ratio_str = self.depth_width_ratio_var.get().strip()
                manual_B_str = self.manual_B_var.get().strip()
                
                depth_width_ratio = None
                manual_B = None
                
                if depth_width_ratio_str:
                    depth_width_ratio = float(depth_width_ratio_str)
                if manual_B_str:
                    manual_B = float(manual_B_str)
                
                # 若都留空，使用默认深宽比0.8（在计算函数中处理）
                
                chamfer_angle = self.chamfer_angle_var.get()
                chamfer_length = self.chamfer_length_var.get()
                
                result = ducao_rect_calculate(
                    Q=Q, n=n, slope_inv=slope_inv,
                    v_min=v_min, v_max=v_max,
                    depth_width_ratio=depth_width_ratio,
                    chamfer_angle=chamfer_angle,
                    chamfer_length=chamfer_length,
                    manual_increase_percent=manual_increase,
                    manual_B=manual_B
                )
            
            self.input_params = {
                'Q': Q, 'n': n, 'slope_inv': slope_inv,
                'v_min': v_min, 'v_max': v_max,
                'section_type': section_type,
                'manual_increase': manual_increase
            }
            self.current_result = result
            
            # 计算完成后，更新加大比例提示标签显示实际使用的值
            if result.get('success') and 'increase_percent' in result:
                actual_increase = result['increase_percent']
                if self.manual_increase_var.get().strip():
                    self.increase_hint_var.set(f"(手动指定: {actual_increase:.1f}%)")
                else:
                    self.increase_hint_var.set(f"(自动计算: {actual_increase:.1f}%)")
            
            self._update_result_display(result)
            
            if VIZ_MODULE_LOADED:
                self._update_section_plot(result)
            
        except (ValueError, tk.TclError) as e:
            # 捕获参数错误（如未输入或格式错误）
            error_detail = str(e)
            if "invalid literal" in error_detail or "expected floating" in error_detail:
                self._show_error_in_result("输入错误", "参数输入不完整或格式错误，请检查并填写所有必填参数：\n- 设计流量 Q\n- 糊率 n\n- 水力坡降 1/x")
            else:
                self._show_error_in_result("输入错误", f"{error_detail}")
        except Exception as e:
            self._show_error_in_result("计算错误", f"计算过程出错: {str(e)}")
    
    def _update_result_display(self, result):
        """更新结果显示"""
        self.result_text.configure(state=tk.NORMAL)
        self.result_text.delete(1.0, tk.END)
        
        if not result['success']:
            error_msg = result.get('error_message', '未知错误')
            self.result_text.insert(tk.END, f"计算失败: {error_msg}\n")
            self.result_text.configure(state=tk.DISABLED)
            return
        
        section_type = result.get('section_type', '')
        Q = self.input_params['Q']
        n = self.input_params['n']
        slope_inv = self.input_params['slope_inv']
        i = 1 / slope_inv
        
        output = []
        output.append("=" * 70)
        output.append(f"              渡槽水力计算结果 - {section_type}断面")
        output.append("=" * 70)
        output.append("")
        
        # 根据输出选项决定显示详细或简要结果
        if not self.show_detail_var.get():
            # 简要输出
            output.append("【输入参数】")
            output.append(f"  设计流量 Q = {Q:.3f} m³/s")
            output.append(f"  糙率 n = {n}")
            output.append(f"  水力坡降 1/{int(slope_inv)}")
            output.append("")
            
            output.append("【断面尺寸】")
            if section_type == 'U形':
                output.append(f"  内半径 R = {result.get('R', 0):.2f} m")
                output.append(f"  槽宽 B = {result.get('B', 0):.2f} m")
                output.append(f"  槽身总高 H = {result.get('H_total', 0):.2f} m")
                B_val = result.get('B', 0)
                H_val = result.get('H_total', 0)
                H_B_ratio = H_val / B_val if B_val > 0 else 0
                output.append(f"  H/B = {H_B_ratio:.3f}")
            else:
                output.append(f"  槽宽 B = {result.get('B', 0):.2f} m")
                output.append(f"  槽高 H = {result.get('H_total', 0):.2f} m")
                B_val = result.get('B', 0)
                H_val = result.get('H_total', 0)
                H_B_ratio = H_val / B_val if B_val > 0 else 0
                output.append(f"  H/B = {H_B_ratio:.3f}")
            output.append("")
            
            output.append("【设计流量工况】")
            output.append(f"  水深 h = {result.get('h_design', 0):.3f} m")
            output.append(f"  流速 V = {result.get('V_design', 0):.3f} m/s")
            output.append(f"  过水面积 A = {result.get('A_design', 0):.3f} m²")
            output.append("")
            
            output.append("【加大流量工况】")
            inc_pct = result.get('increase_percent', 0)
            manual_increase = self.input_params.get('manual_increase')
            inc_source = "(手动指定)" if manual_increase else "(自动计算)"
            output.append(f"  流量加大比例 = {inc_pct:.1f}% {inc_source}")
            output.append(f"  加大流量 Q加大 = {result.get('Q_increased', 0):.3f} m³/s")
            output.append(f"  加大水深 h加大 = {result.get('h_increased', 0):.3f} m")
            output.append(f"  超高 Fb = {result.get('Fb', 0):.3f} m")
            output.append("")
            
            output.append("【验证结果】")
            V = result.get('V_design', 0)
            v_min = self.input_params['v_min']
            v_max = self.input_params['v_max']
            velocity_ok = v_min <= V <= v_max
            output.append(f"  流速验证: {'✓ 通过' if velocity_ok else '✗ 未通过'}")
            output.append("")
            
            output.append("=" * 70)
            output.append(f"  计算完成: {'成功 ✓' if result['success'] else '失败 ✗'}")
            output.append("=" * 70)
            
            self.result_text.insert(tk.END, "\n".join(output))
            self.result_text.configure(state=tk.DISABLED)
            return
        
        # 详细输出 - 包含公式代入计算过程
        output.append("【一、输入参数】")
        output.append(f"  设计流量 Q = {Q:.3f} m³/s")
        output.append(f"  糙率 n = {n}")
        output.append(f"  水力坡降 1/{int(slope_inv)}")
        output.append("")
        
        if section_type == 'U形':
            R = result.get('R', 0)
            f = result.get('f', 0)
            B = result.get('B', 0)
            f_R = result.get('f_R', 0)
            H_total = result.get('H_total', 0)
            
            output.append("【二、断面尺寸】")
            output.append(f"  内半径 R = {R:.2f} m")
            output.append("")
            
            output.append("  1. 槽宽计算:")
            output.append(f"     B = 2 × R")
            output.append(f"       = 2 × {R:.2f}")
            output.append(f"       = {B:.2f} m")
            output.append("")
            
            output.append("  2. 直段高度:")
            output.append(f"     f = {f:.2f} m")
            output.append(f"     f/R = {f:.2f} / {R:.2f} = {f_R:.3f}")
            output.append("")
            
            output.append("  3. 槽身总高计算:")
            output.append(f"     H = R + f")
            output.append(f"       = {R:.2f} + {f:.2f}")
            output.append(f"       = {H_total:.2f} m")
            output.append("")
            
            output.append("  4. H/B比值计算:")
            H_B_ratio = H_total / B if B > 0 else 0
            output.append(f"     H/B = 槽身总高 ÷ 槽宽")
            output.append(f"         = {H_total:.2f} ÷ {B:.2f}")
            output.append(f"         = {H_B_ratio:.3f}")
            output.append("")
        else:
            B = result.get('B', 0)
            H_total = result.get('H_total', 0)
            ratio = result.get('depth_width_ratio', 0)
            h_design = result.get('h_design', 0)
            h_increased = result.get('h_increased', 0)
            Fb = result.get('Fb', 0)
            
            output.append("【二、断面尺寸】")
            output.append(f"  槽宽 B = {B:.2f} m")
            output.append(f"  深宽比 = {ratio:.3f}")
            output.append("")
            
            # 计算两个工况的超高需求
            Fb_design_min = h_design / 12 + 0.05
            H_design_required = h_design + Fb_design_min
            H_inc_required = h_increased + 0.10
            
            output.append("  1. 槽高计算（规范 9.4.1-2）:")
            output.append(f"     设计流量: H1 = h设计 + (h设计/12 + 0.05)")
            output.append(f"              = {h_design:.3f} + ({h_design:.3f}/12 + 0.05)")
            output.append(f"              = {h_design:.3f} + {Fb_design_min:.3f}")
            output.append(f"              = {H_design_required:.3f} m")
            output.append(f"     加大流量: H2 = h加大 + 0.10")
            output.append(f"              = {h_increased:.3f} + 0.10")
            output.append(f"              = {H_inc_required:.3f} m")
            output.append(f"     取最大值: H = max({H_design_required:.3f}, {H_inc_required:.3f})")
            output.append(f"              = {max(H_design_required, H_inc_required):.3f} m")
            output.append(f"     向上取整: H = {H_total:.2f} m")
            output.append("")
            
            output.append("  2. H/B比值计算:")
            H_B_ratio = H_total / B if B > 0 else 0
            output.append(f"     H/B = 槽身总高 ÷ 槽宽")
            output.append(f"         = {H_total:.2f} ÷ {B:.2f}")
            output.append(f"         = {H_B_ratio:.3f}")
            output.append("")
            
            if result.get('has_chamfer', False):
                output.append(f"  倒角角度 = {result.get('chamfer_angle', 0):.1f}°")
                output.append(f"  倒角底边 = {result.get('chamfer_length', 0):.2f} m")
                output.append("")
        
        output.append("【三、设计流量工况】")
        h_design = result.get('h_design', 0)
        A_design = result.get('A_design', 0)
        P_design = result.get('P_design', 0)
        R_hyd = result.get('R_hyd_design', 0)
        V_design = result.get('V_design', 0)
        Q_calc = result.get('Q_calc', 0)
        
        output.append(f"  设计水深 h = {h_design:.3f} m")
        output.append("")
        
        if section_type == 'U形':
            R = result.get('R', 0)
            output.append("  2. 过水面积计算 (U形断面):")
            if h_design <= R:
                # 水深在半圆内
                output.append(f"     当 h ≤ R 时:")
                theta_val = math.acos((R - h_design) / R) if R > 0 else 0
                output.append(f"     θ = arccos((R-h)/R) = arccos(({R:.2f}-{h_design:.3f})/{R:.2f})")
                output.append(f"       = {math.degrees(theta_val):.2f}° = {theta_val:.4f} rad")
                output.append(f"     A = R² × (θ - sinθ×cosθ)")
                output.append(f"       = {R:.2f}² × ({theta_val:.4f} - {math.sin(theta_val):.4f}×{math.cos(theta_val):.4f})")
                output.append(f"       = {A_design:.3f} m²")
            else:
                # 水深超过半圆
                output.append(f"     当 h > R 时:")
                output.append(f"     A = πR²/2 + 2R×(h-R)")
                output.append(f"       = π×{R:.2f}²/2 + 2×{R:.2f}×({h_design:.3f}-{R:.2f})")
                output.append(f"       = {math.pi*R**2/2:.3f} + {2*R*(h_design-R):.3f}")
                output.append(f"       = {A_design:.3f} m²")
            output.append("")
            
            output.append("  3. 湿周计算 (U形断面):")
            if h_design <= R:
                output.append(f"     当 h ≤ R 时:")
                output.append(f"     P = 2Rθ = 2×{R:.2f}×{theta_val:.4f}")
                output.append(f"       = {P_design:.3f} m")
            else:
                output.append(f"     当 h > R 时:")
                output.append(f"     P = πR + 2×(h-R)")
                output.append(f"       = π×{R:.2f} + 2×({h_design:.3f}-{R:.2f})")
                output.append(f"       = {math.pi*R:.3f} + {2*(h_design-R):.3f}")
                output.append(f"       = {P_design:.3f} m")
            output.append("")
        else:
            # 矩形断面
            B = result.get('B', 0)
            output.append("  2. 过水面积计算 (矩形断面):")
            output.append(f"     A = B × h")
            output.append(f"       = {B:.2f} × {h_design:.3f}")
            output.append(f"       = {A_design:.3f} m²")
            output.append("")
            
            output.append("  3. 湿周计算 (矩形断面):")
            output.append(f"     P = B + 2×h")
            output.append(f"       = {B:.2f} + 2×{h_design:.3f}")
            output.append(f"       = {B:.2f} + {2*h_design:.3f}")
            output.append(f"       = {P_design:.3f} m")
            output.append("")
        
        output.append("  4. 水力半径计算:")
        output.append(f"     R = A / P")
        output.append(f"       = {A_design:.3f} / {P_design:.3f}")
        output.append(f"       = {R_hyd:.3f} m")
        output.append("")
        
        output.append("  5. 设计流速计算 (曼宁公式):")
        output.append(f"     V = (1/n) × R^(2/3) × i^(1/2)")
        output.append(f"       = (1/{n}) × {R_hyd:.3f}^(2/3) × {i:.6f}^(1/2)")
        output.append(f"       = {1/n:.2f} × {R_hyd**(2/3):.4f} × {math.sqrt(i):.6f}")
        output.append(f"       = {V_design:.3f} m/s")
        output.append("")
        
        output.append("  6. 计算流量验证:")
        output.append(f"     Q计算 = A × V")
        output.append(f"          = {A_design:.3f} × {V_design:.3f}")
        output.append(f"          = {Q_calc:.3f} m³/s")
        output.append("")
        
        output.append("【四、加大流量工况】")
        inc_pct = result.get('increase_percent', 0)
        Q_加大 = result.get('Q_increased', 0)
        h_加大 = result.get('h_increased', 0)
        V_加大 = result.get('V_increased', 0)
        A_加大 = result.get('A_increased', 0)
        P_加大 = result.get('P_increased', 0)
        R_加大 = result.get('R_hyd_increased', 0)
        Fb = result.get('Fb', 0)
        Q_calc_inc = (1/n) * A_加大 * (R_加大 ** (2/3)) * (i ** 0.5) if R_加大 > 0 else 0

        manual_increase = self.input_params.get('manual_increase')
        inc_source = "(手动指定)" if manual_increase else "(自动计算)"

        output.append(f"  流量加大比例 = {inc_pct:.1f}% {inc_source}")
        output.append("")

        output.append("  7. 加大流量计算:")
        output.append(f"      Q加大 = Q × (1 + {inc_pct:.1f}%)")
        output.append(f"           = {Q:.3f} × {1 + inc_pct/100:.3f}")
        output.append(f"           = {Q_加大:.3f} m³/s")
        output.append("")

        output.append(f"  8. 加大水深计算结果:")
        output.append(f"      加大水深 h加大 = {h_加大:.3f} m")
        output.append("")

        # 根据断面类型输出水力参数计算过程
        if section_type == 'U形':
            R = result.get('R', 0)
            output.append("  9. 过水面积计算 (U形断面):")
            if h_加大 <= R:
                output.append(f"      A加大 = (R²/2) × (θ - sinθ)")
                theta_rad = 2 * math.acos((R - h_加大) / R)
                theta_deg = math.degrees(theta_rad)
                output.append(f"           = ({R:.2f}²/2) × ({theta_deg:.2f}° - sin{theta_deg:.2f}°)")
                output.append(f"           = {A_加大:.3f} m²")
            else:
                output.append(f"      A加大 = πR²/2 + 2R×(h加大-R)")
                output.append(f"           = π×{R:.2f}²/2 + 2×{R:.2f}×({h_加大:.3f}-{R:.2f})")
                output.append(f"           = {math.pi*R**2/2:.3f} + {2*R*(h_加大-R):.3f}")
                output.append(f"           = {A_加大:.3f} m²")
            output.append("")

            output.append("  10. 湿周计算 (U形断面):")
            if h_加大 <= R:
                theta_rad = 2 * math.acos((R - h_加大) / R)
                theta_deg = math.degrees(theta_rad)
                output.append(f"      P加大 = R × θ")
                output.append(f"           = {R:.2f} × {theta_deg:.2f}°×π/180")
                output.append(f"           = {P_加大:.3f} m")
            else:
                output.append(f"      P加大 = πR + 2×(h加大-R)")
                output.append(f"           = π×{R:.2f} + 2×({h_加大:.3f}-{R:.2f})")
                output.append(f"           = {math.pi*R:.3f} + {2*(h_加大-R):.3f}")
                output.append(f"           = {P_加大:.3f} m")
            output.append("")
        else:
            # 矩形断面
            B = result.get('B', 0)
            output.append("  9. 过水面积计算 (矩形断面):")
            output.append(f"      A加大 = B × h加大")
            output.append(f"           = {B:.2f} × {h_加大:.3f}")
            output.append(f"           = {A_加大:.3f} m²")
            output.append("")

            output.append("  10. 湿周计算 (矩形断面):")
            output.append(f"      P加大 = B + 2×h加大")
            output.append(f"           = {B:.2f} + 2×{h_加大:.3f}")
            output.append(f"           = {B:.2f} + {2*h_加大:.3f}")
            output.append(f"           = {P_加大:.3f} m")
            output.append("")

        output.append("  11. 水力半径计算:")
        output.append(f"      R加大 = A加大 / P加大")
        output.append(f"           = {A_加大:.3f} / {P_加大:.3f}")
        output.append(f"           = {R_加大:.3f} m")
        output.append("")

        output.append("  12. 加大流速计算 (曼宁公式):")
        output.append(f"      V加大 = (1/n) × R加大^(2/3) × i^(1/2)")
        output.append(f"           = (1/{n}) × {R_加大:.3f}^(2/3) × {i:.6f}^(1/2)")
        output.append(f"           = {1/n:.2f} × {R_加大**(2/3):.4f} × {math.sqrt(i):.6f}")
        output.append(f"           = {V_加大:.3f} m/s")
        output.append("")

        output.append("  13. 流量校核:")
        output.append(f"      Q计算 = A加大 × V加大")
        output.append(f"           = {A_加大:.3f} × {V_加大:.3f}")
        output.append(f"           = {Q_calc_inc:.3f} m³/s")
        output.append("")

        output.append("  14. 超高计算:")
        if section_type == 'U形':
            H_total = result.get('H_total', 0)
            output.append(f"      Fb = H - h加大 = {H_total:.2f} - {h_加大:.3f} = {Fb:.3f} m")
        else:
            H_total = result.get('H_total', 0)
            output.append(f"      Fb = H - h加大 = {H_total:.2f} - {h_加大:.3f} = {Fb:.3f} m")
        output.append("")
        
        output.append("【五、验证】")
        
        # 1. 流速验证（规范 9.4.1-1）
        v_recommended_min = 1.0  # m/s
        v_recommended_max = 2.5  # m/s
        V_design = result.get('V_design', 0)
        velocity_ok = v_recommended_min <= V_design <= v_recommended_max
        output.append(f"  1. 流速验证（规范 9.4.1-1）")
        output.append(f"     规范要求: 槽内设计流速宜为 1.0～2.5 m/s")
        output.append(f"     计算结果: V = {V_design:.3f} m/s")
        if velocity_ok:
            output.append(f"     验证结果: {v_recommended_min} ≤ {V_design:.3f} ≤ {v_recommended_max} → 通过 ✓")
        else:
            if V_design < v_recommended_min:
                output.append(f"     验证结果: {V_design:.3f} < {v_recommended_min} → 超出推荐范围 ⚠")
                output.append(f"     提示: 流速过小，可能造成泾积，建议调整断面尺寸")
            else:
                output.append(f"     验证结果: {V_design:.3f} > {v_recommended_max} → 超出推荐范围 ⚠")
                output.append(f"     提示: 流速过大，可能造成冲刷，建议调整断面尺寸")
        output.append("")
        
        # 2. 超高验证（规范 9.4.1-2）
        output.append(f"  2. 超高验证（规范 9.4.1-2）")
        
        if section_type == 'U形':
            # U形断面超高验证
            R_val = result.get('R', 0)
            h_design = result.get('h_design', 0)
            h_inc = result.get('h_increased', 0)
            H_total = result.get('H_total', 0)
            Fb_design = H_total - h_design  # 设计流量超高
            Fb_design_min = R_val / 5  # 设计流量时最小超高：槽身直径的1/10 = R/5
            Fb_inc = result.get('Fb', 0)  # 加大流量超高
            Fb_inc_min = 0.10  # 加大流量时最小超高
            
            output.append(f"     断面类型: U形")
            output.append(f"     规范要求:")
            output.append(f"       - 设计流量: 超高不应小于槽身直径的1/10 (即2R/10 = R/5 = {Fb_design_min:.3f} m)")
            output.append(f"       - 加大流量: 超高不应小于 0.10 m")
            output.append(f"")
            output.append(f"     计算结果:")
            output.append(f"       - 设计流量超高: Fb_设计 = H - h_设计 = {H_total:.2f} - {h_design:.3f} = {Fb_design:.3f} m")
            output.append(f"       - 加大流量超高: Fb_加大 = H - h_加大 = {H_total:.2f} - {h_inc:.3f} = {Fb_inc:.3f} m")
            output.append(f"")
            
            fb_design_ok = Fb_design >= Fb_design_min
            fb_inc_ok = Fb_inc >= Fb_inc_min
            
            output.append(f"     验证结果:")
            output.append(f"       - 设计流量: {Fb_design:.3f} {'≥' if fb_design_ok else '<'} {Fb_design_min:.3f} → {'通过 ✓' if fb_design_ok else '未通过 ✗'}")
            output.append(f"       - 加大流量: {Fb_inc:.3f} {'≥' if fb_inc_ok else '<'} {Fb_inc_min:.2f} → {'通过 ✓' if fb_inc_ok else '未通过 ✗'}")
        else:
            # 矩形断面超高验证
            h_design = result.get('h_design', 0)
            h_inc = result.get('h_increased', 0)
            H_total = result.get('H_total', 0)
            Fb_design = H_total - h_design  # 设计流量超高
            Fb_design_min = h_design / 12 + 0.05  # 设计流量时最小超高
            Fb_inc = result.get('Fb', 0)  # 加大流量超高
            Fb_inc_min = 0.10  # 加大流量时最小超高
            
            output.append(f"     断面类型: 矩形")
            output.append(f"     规范要求:")
            output.append(f"       - 设计流量: 超高不应小于 h/12 + 0.05 = {h_design:.3f}/12 + 0.05 = {Fb_design_min:.3f} m")
            output.append(f"       - 加大流量: 超高不应小于 0.10 m")
            output.append(f"")
            output.append(f"     计算结果:")
            output.append(f"       - 设计流量超高: Fb_设计 = H - h_设计 = {H_total:.2f} - {h_design:.3f} = {Fb_design:.3f} m")
            output.append(f"       - 加大流量超高: Fb_加大 = H - h_加大 = {H_total:.2f} - {h_inc:.3f} = {Fb_inc:.3f} m")
            output.append(f"")
            
            fb_design_ok = Fb_design >= Fb_design_min
            fb_inc_ok = Fb_inc >= Fb_inc_min
            
            output.append(f"     验证结果:")
            output.append(f"       - 设计流量: {Fb_design:.3f} {'≥' if fb_design_ok else '<'} {Fb_design_min:.3f} → {'通过 ✓' if fb_design_ok else '未通过 ✗'}")
            output.append(f"       - 加大流量: {Fb_inc:.3f} {'≥' if fb_inc_ok else '<'} {Fb_inc_min:.3f} → {'通过 ✓' if fb_inc_ok else '未通过 ✗'}")
        output.append("")
        
        output.append("=" * 70)
        output.append(f"  计算完成: {'成功 ✓' if result['success'] else '失败 ✗'}")
        output.append("=" * 70)
        
        self.result_text.insert(tk.END, "\n".join(output))
        self.result_text.configure(state=tk.DISABLED)
    
    def _update_section_plot(self, result):
        """更新断面图"""
        self.section_fig.clear()
        
        if not result['success']:
            return
        
        ax = self.section_fig.add_subplot(111)
        section_type = result.get('section_type', '')
        
        if section_type == 'U形':
            self._draw_u_section(ax, result)
        else:
            self._draw_rect_section(ax, result)
        
        self.section_fig.tight_layout()
        self.section_canvas.draw()
    
    def _draw_u_section(self, ax, result):
        """绘制U形断面"""
        R = result.get('R', 1)
        f = result.get('f', 0)
        h_water = result.get('h_design', 0)
        H_total = result.get('H_total', R + f)
        Q = self.input_params['Q']
        V = result.get('V_design', 0)
        
        # U形断面：底部半圆 + 两侧直墙
        # 半圆部分：圆心在(0, R)，半径R，底部为y=0
        theta = np.linspace(np.pi, 2*np.pi, 50)  # 下半圆 (180° to 360°)
        circle_x = R * np.cos(theta)
        circle_y = R + R * np.sin(theta)  # 底部y=0，顶部y=R
        
        # 绘制槽身轮廓
        ax.plot(circle_x, circle_y, 'k-', linewidth=2)  # 底部半圆
        ax.plot([-R, -R], [R, H_total], 'k-', linewidth=2)  # 左侧直墙
        ax.plot([R, R], [R, H_total], 'k-', linewidth=2)   # 右侧直墙
        ax.plot([-R, R], [H_total, H_total], 'k--', linewidth=1)  # 顶部虚线
        
        # 绘制水面
        if h_water > 0:
            if h_water <= R:
                # 水深在半圆内
                # 计算水面宽度：在高度h_water处，圆的方程 x² + (y-R)² = R²
                # 当 y = h_water 时，x = ±sqrt(R² - (h_water-R)²)
                dy = h_water - R  # dy < 0 当 h_water < R
                if R**2 - dy**2 >= 0:
                    water_half_width = math.sqrt(R**2 - dy**2)
                else:
                    water_half_width = 0
                
                # 绘制水面以下的半圆弧
                # 找到水面与圆弧的交点角度
                angle = math.acos(-dy / R) if abs(dy/R) <= 1 else (0 if dy > 0 else np.pi)
                water_theta = np.linspace(np.pi + (np.pi - angle), 2*np.pi - (np.pi - angle), 30)
                water_arc_x = R * np.cos(water_theta)
                water_arc_y = R + R * np.sin(water_theta)
                
                # 填充水域
                poly_x = np.concatenate([[water_half_width], water_arc_x, [-water_half_width]])
                poly_y = np.concatenate([[h_water], water_arc_y, [h_water]])
                ax.fill(poly_x, poly_y, color='lightblue', alpha=0.7)
                ax.plot([-water_half_width, water_half_width], [h_water, h_water], 'b-', linewidth=1.5)
            else:
                # 水深超过半圆，进入直墙部分
                # 底部半圆全部充满
                water_theta = np.linspace(np.pi, 2*np.pi, 50)
                water_arc_x = R * np.cos(water_theta)
                water_arc_y = R + R * np.sin(water_theta)
                
                # 水域多边形：左下角 -> 沿半圆 -> 右下角 -> 右上水面 -> 左上水面
                poly_x = np.concatenate([[-R], water_arc_x, [R], [R], [-R]])
                poly_y = np.concatenate([[R], water_arc_y, [R], [h_water], [h_water]])
                ax.fill(poly_x, poly_y, color='lightblue', alpha=0.7)
                ax.plot([-R, R], [h_water, h_water], 'b-', linewidth=1.5)
        
        # 添加尺寸标注
        # 标注槽宽 B = 2R
        B = 2 * R
        ax.annotate('', xy=(R, -0.15*R), xytext=(-R, -0.15*R),
                   arrowprops=dict(arrowstyle='<->', color='gray', lw=1.5))
        ax.text(0, -0.3*R, f'B={B:.2f}m', ha='center', fontsize=9, color='gray')
        
        # 标注半径 R
        ax.annotate('', xy=(0, R), xytext=(R*0.7, R*0.3),
                   arrowprops=dict(arrowstyle='->', color='green', lw=1.2))
        ax.text(R*0.75, R*0.15, f'R={R:.2f}m', ha='left', fontsize=8, color='green')
        
        # 标注总高 H
        ax.annotate('', xy=(R+0.15*R, H_total), xytext=(R+0.15*R, 0),
                   arrowprops=dict(arrowstyle='<->', color='purple', lw=1.5))
        ax.text(R+0.25*R, H_total/2, f'H={H_total:.2f}m', ha='left', fontsize=9, color='purple', rotation=90, va='center')
        
        # 标注水深 h
        if h_water > 0:
            ax.annotate('', xy=(-R-0.15*R, h_water), xytext=(-R-0.15*R, 0),
                       arrowprops=dict(arrowstyle='<->', color='blue', lw=1.5))
            ax.text(-R-0.25*R, h_water/2, f'h={h_water:.2f}m', ha='right', fontsize=9, color='blue', rotation=90, va='center')
        
        ax.set_xlim(-R*2.2, R*2.2)
        ax.set_ylim(-R*0.6, H_total*1.2)
        ax.set_aspect('equal')
        ax.set_title(f'U形渡槽断面\nQ={Q:.2f}m$^3$/s, V={V:.2f}m/s', fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.axhline(y=0, color='brown', linewidth=3)
    
    def _draw_rect_section(self, ax, result):
        """绘制矩形断面（支持倒角）"""
        B = result.get('B', 1)
        H = result.get('H_total', 1)
        h_water = result.get('h_design', 0)
        Q = self.input_params['Q']
        V = result.get('V_design', 0)
        
        # 获取倒角参数
        has_chamfer = result.get('has_chamfer', False)
        chamfer_angle = result.get('chamfer_angle', 0)
        chamfer_length = result.get('chamfer_length', 0)
        
        if has_chamfer and chamfer_angle > 0 and chamfer_length > 0:
            # 计算倒角高度
            chamfer_height = chamfer_length * math.tan(math.radians(chamfer_angle))
            
            # 绘制带倒角的槽身轮廓
            # 左侧壁：从倒角顶点到顶部
            ax.plot([-B/2, -B/2], [chamfer_height, H], 'k-', linewidth=2)
            # 右侧壁：从倒角顶点到顶部
            ax.plot([B/2, B/2], [chamfer_height, H], 'k-', linewidth=2)
            # 底部（中间段）
            ax.plot([-B/2 + chamfer_length, B/2 - chamfer_length], [0, 0], 'k-', linewidth=2)
            # 左下倒角
            ax.plot([-B/2, -B/2 + chamfer_length], [chamfer_height, 0], 'k-', linewidth=2)
            # 右下倒角
            ax.plot([B/2 - chamfer_length, B/2], [0, chamfer_height], 'k-', linewidth=2)
            # 顶部虚线
            ax.plot([-B/2, B/2], [H, H], 'k--', linewidth=1)
            
            # 绘制水面
            if h_water > 0:
                if h_water <= chamfer_height:
                    # 水深在倒角范围内
                    # 计算水面在倒角上的位置
                    # 倒角线性关系：x位置 = -B/2 + chamfer_length * (h / chamfer_height)
                    water_x_left = -B/2 + chamfer_length * (h_water / chamfer_height)
                    water_x_right = B/2 - chamfer_length * (h_water / chamfer_height)
                    water_x = [water_x_left, -B/2 + chamfer_length, B/2 - chamfer_length, water_x_right]
                    water_y = [h_water, 0, 0, h_water]
                    ax.fill(water_x, water_y, color='lightblue', alpha=0.7)
                    ax.plot([water_x_left, water_x_right], [h_water, h_water], 'b-', linewidth=1.5)
                else:
                    # 水深超过倒角
                    water_x = [-B/2, -B/2 + chamfer_length, B/2 - chamfer_length, B/2, B/2, -B/2]
                    water_y = [chamfer_height, 0, 0, chamfer_height, h_water, h_water]
                    ax.fill(water_x, water_y, color='lightblue', alpha=0.7)
                    ax.plot([-B/2, B/2], [h_water, h_water], 'b-', linewidth=1.5)
        else:
            # 无倒角，普通矩形
            ax.plot([-B/2, -B/2], [0, H], 'k-', linewidth=2)
            ax.plot([B/2, B/2], [0, H], 'k-', linewidth=2)
            ax.plot([-B/2, B/2], [0, 0], 'k-', linewidth=2)
            ax.plot([-B/2, B/2], [H, H], 'k--', linewidth=1)
            
            if h_water > 0:
                water_x = [-B/2, -B/2, B/2, B/2]
                water_y = [0, h_water, h_water, 0]
                ax.fill(water_x, water_y, color='lightblue', alpha=0.7)
                ax.plot([-B/2, B/2], [h_water, h_water], 'b-', linewidth=1.5)
        
        # 添加尺寸标注
        # 标注槽宽 B
        ax.annotate('', xy=(B/2, -0.1*H), xytext=(-B/2, -0.1*H),
                   arrowprops=dict(arrowstyle='<->', color='gray', lw=1.5))
        ax.text(0, -0.2*H, f'B={B:.2f}m', ha='center', fontsize=9, color='gray')
        
        # 标注总高 H
        ax.annotate('', xy=(B/2+0.1*B, H), xytext=(B/2+0.1*B, 0),
                   arrowprops=dict(arrowstyle='<->', color='purple', lw=1.5))
        ax.text(B/2+0.15*B, H/2, f'H={H:.2f}m', ha='left', fontsize=9, color='purple', rotation=90, va='center')
        
        # 标注水深 h
        if h_water > 0:
            ax.annotate('', xy=(-B/2-0.1*B, h_water), xytext=(-B/2-0.1*B, 0),
                       arrowprops=dict(arrowstyle='<->', color='blue', lw=1.5))
            ax.text(-B/2-0.15*B, h_water/2, f'h={h_water:.2f}m', ha='right', fontsize=9, color='blue', rotation=90, va='center')
        
        # 如果有倒角，标注倒角信息
        if has_chamfer and chamfer_angle > 0 and chamfer_length > 0:
            chamfer_height = chamfer_length * math.tan(math.radians(chamfer_angle))
            # 在左下角标注倒角
            ax.text(-B/2 + chamfer_length/2, chamfer_height/2, 
                   f'{chamfer_angle:.0f}°', ha='center', va='center', 
                   fontsize=7, color='orange', fontweight='bold')
        
        ax.set_xlim(-B*0.9, B*0.9)
        ax.set_ylim(-H*0.35, H*1.2)
        ax.set_aspect('equal')
        
        # 标题显示是否有倒角
        title_suffix = "(带倒角)" if has_chamfer and chamfer_angle > 0 else ""
        ax.set_title(f'矩形渡槽断面{title_suffix}\nQ={Q:.2f}m$^3$/s, V={V:.2f}m/s', fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.axhline(y=0, color='brown', linewidth=3)
    
    def _clear(self):
        """清空"""
        self._show_initial_help()
        if VIZ_MODULE_LOADED:
            self.section_fig.clear()
            self.section_canvas.draw()
    
    def _export_charts(self):
        """导出图表"""
        if not hasattr(self, 'current_result') or not self.current_result or not self.current_result['success']:
            messagebox.showwarning("警告", "请先进行计算")
            return
        
        folder = filedialog.askdirectory(title="选择保存目录")
        if not folder:
            return
        
        try:
            self.section_fig.savefig(os.path.join(folder, '渡槽断面图.png'), dpi=150, bbox_inches='tight')
            messagebox.showinfo("成功", f"图表已保存到: {folder}")
        except Exception as e:
            messagebox.showerror("错误", f"保存失败: {str(e)}")
    
    def _export_report(self):
        """导出报告"""
        if not hasattr(self, 'current_result') or not self.current_result or not self.current_result['success']:
            messagebox.showwarning("警告", "请先进行计算")
            return
        
        filepath = filedialog.asksaveasfilename(
            title="保存报告",
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")]
        )
        if not filepath:
            return
        
        try:
            self.result_text.configure(state=tk.NORMAL)
            content = self.result_text.get(1.0, tk.END)
            self.result_text.configure(state=tk.DISABLED)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            
            messagebox.showinfo("成功", f"报告已保存到: {filepath}")
        except Exception as e:
            messagebox.showerror("错误", f"保存失败: {str(e)}")


# ============================================================
# 隧洞计算面板
# ============================================================

class TunnelPanel(ttk.Frame):
    """隧洞计算面板（支持圆形、圆拱直墙型、马蹄形）"""
    
    def __init__(self, parent):
        super().__init__(parent)
        
        self.input_params = {}
        self.current_result = None
        self.show_detail_var = tk.BooleanVar(value=True)  # 默认显示详细过程
        
        self._create_ui()
    
    def _create_ui(self):
        """创建UI"""
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        self._create_input_panel(main_frame)
        self._create_output_panel(main_frame)
    
    def _create_input_panel(self, parent):
        """创建输入面板"""
        input_frame = ttk.LabelFrame(parent, text="输入参数", padding="10")
        input_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        
        # 断面类型选择
        self.section_type_var = tk.StringVar(value="圆形")
        
        row = 0
        ttk.Label(input_frame, text="断面类型:").grid(row=row, column=0, sticky=tk.W, pady=5)
        section_combo = ttk.Combobox(input_frame, textvariable=self.section_type_var, 
                                      width=14, values=["圆形", "圆拱直墙型", "马蹄形标准Ⅰ型", "马蹄形标准Ⅱ型"], state='readonly')
        section_combo.grid(row=row, column=1, padx=5, pady=5)
        section_combo.bind('<<ComboboxSelected>>', self._on_section_type_changed)
        
        # 基本参数
        self.Q_var = tk.DoubleVar(value=10.0)
        self.n_var = tk.DoubleVar(value=0.014)
        self.slope_inv_var = tk.DoubleVar(value=2000)
        self.v_min_var = tk.DoubleVar(value=0.1)
        self.v_max_var = tk.DoubleVar(value=100.0)
        
        row += 1
        ttk.Label(input_frame, text="设计流量 Q (m³/s):").grid(row=row, column=0, sticky=tk.W, pady=5)
        ttk.Entry(input_frame, textvariable=self.Q_var, width=15).grid(row=row, column=1, padx=5, pady=5)
        
        row += 1
        ttk.Label(input_frame, text="糙率 n:").grid(row=row, column=0, sticky=tk.W, pady=5)
        ttk.Entry(input_frame, textvariable=self.n_var, width=15).grid(row=row, column=1, padx=5, pady=5)
        
        row += 1
        ttk.Label(input_frame, text="水力坡降 1/").grid(row=row, column=0, sticky=tk.W, pady=5)
        ttk.Entry(input_frame, textvariable=self.slope_inv_var, width=15).grid(row=row, column=1, padx=5, pady=5)
        
        # 流速参数栏目
        row += 1
        ttk.Label(input_frame, text="【流速参数】", font=('', 9, 'bold')).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=5)
        
        row += 1
        ttk.Label(input_frame, text="不淤流速 (m/s):").grid(row=row, column=0, sticky=tk.W, pady=5)
        ttk.Entry(input_frame, textvariable=self.v_min_var, width=15).grid(row=row, column=1, padx=5, pady=5)
        
        row += 1
        ttk.Label(input_frame, text="不冲流速 (m/s):").grid(row=row, column=0, sticky=tk.W, pady=5)
        ttk.Entry(input_frame, textvariable=self.v_max_var, width=15).grid(row=row, column=1, padx=5, pady=5)
        
        # 流速提示
        row += 1
        ttk.Label(input_frame, text="(一般情况下保持默认数值即可)", font=('', 8), foreground='black').grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=2)
        
        # 流量加大比例栏目
        row += 1
        ttk.Label(input_frame, text="【流量加大】", font=('', 9, 'bold')).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=5)
        
        row += 1
        self.manual_increase_var = tk.StringVar(value="")
        ttk.Label(input_frame, text="流量加大比例 (%):").grid(row=row, column=0, sticky=tk.W, pady=3)
        ttk.Entry(input_frame, textvariable=self.manual_increase_var, width=15).grid(row=row, column=1, padx=5, pady=3)
        
        row += 1
        self.increase_hint_var = tk.StringVar(value="(留空则自动计算)")
        self.increase_hint_label = ttk.Label(input_frame, textvariable=self.increase_hint_var, font=('', 8), foreground='black')
        self.increase_hint_label.grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=2)
        
        # 分隔线
        row += 1
        ttk.Separator(input_frame, orient=tk.HORIZONTAL).grid(row=row, column=0, columnspan=2, 
                                                                sticky=tk.EW, pady=10)
        
        # 可选参数标签
        row += 1
        ttk.Label(input_frame, text="【可选参数】", font=('', 9, 'bold')).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=5)
        
        # 圆形断面参数框
        row += 1
        self.circ_frame = ttk.LabelFrame(input_frame, text="圆形断面参数", padding="5")
        self.circ_frame.grid(row=row, column=0, columnspan=2, sticky=tk.EW, pady=5)
        
        self.manual_D_var = tk.StringVar(value="")
        ttk.Label(self.circ_frame, text="手动直径 D (m):").grid(row=0, column=0, sticky=tk.W, pady=3)
        ttk.Entry(self.circ_frame, textvariable=self.manual_D_var, width=15).grid(row=0, column=1, padx=5, pady=3)
        ttk.Label(self.circ_frame, text="(留空则自动计算)", font=('', 8), foreground='black').grid(row=1, column=0, columnspan=2, sticky=tk.W)
        
        # 圆拱直墙型参数框
        row += 1
        self.hs_frame = ttk.LabelFrame(input_frame, text="圆拱直墙型参数", padding="5")
        self.hs_frame.grid(row=row, column=0, columnspan=2, sticky=tk.EW, pady=5)
        
        self.theta_var = tk.StringVar(value="")
        self.manual_B_hs_var = tk.StringVar(value="")
        
        ttk.Label(self.hs_frame, text="拱顶圆心角 (度):").grid(row=0, column=0, sticky=tk.W, pady=3)
        ttk.Entry(self.hs_frame, textvariable=self.theta_var, width=15).grid(row=0, column=1, padx=5, pady=3)
        ttk.Label(self.hs_frame, text="(留空则采用180°)", font=('', 8), foreground='black').grid(row=1, column=0, columnspan=2, sticky=tk.W)
        
        ttk.Label(self.hs_frame, text="手动底宽 B (m):").grid(row=2, column=0, sticky=tk.W, pady=3)
        ttk.Entry(self.hs_frame, textvariable=self.manual_B_hs_var, width=15).grid(row=2, column=1, padx=5, pady=3)
        
        ttk.Label(self.hs_frame, text="(手动底宽留空则自动计算)", font=('', 8), foreground='black').grid(row=3, column=0, columnspan=2, sticky=tk.W)
        
        self.hs_frame.grid_remove()
        
        # 马蹄形断面参数框
        row += 1
        self.horseshoe_std_frame = ttk.LabelFrame(input_frame, text="马蹄形断面参数", padding="5")
        self.horseshoe_std_frame.grid(row=row, column=0, columnspan=2, sticky=tk.EW, pady=5)
        
        self.manual_r_var = tk.StringVar(value="")
        ttk.Label(self.horseshoe_std_frame, text="手动半径 r (m):").grid(row=0, column=0, sticky=tk.W, pady=3)
        ttk.Entry(self.horseshoe_std_frame, textvariable=self.manual_r_var, width=15).grid(row=0, column=1, padx=5, pady=3)
        ttk.Label(self.horseshoe_std_frame, text="(留空则自动计算)", font=('', 8), foreground='black').grid(row=1, column=0, columnspan=2, sticky=tk.W)
        
        self.horseshoe_std_frame.grid_remove()
        
        # 分隔线
        row += 1
        ttk.Separator(input_frame, orient=tk.HORIZONTAL).grid(row=row, column=0, columnspan=2, 
                                                                sticky=tk.EW, pady=10)
        
        # 输出选项
        row += 1
        ttk.Checkbutton(input_frame, text="输出详细计算过程", 
                       variable=self.show_detail_var).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=5)
        
        # 按钮
        row += 1
        btn_frame = ttk.Frame(input_frame)
        btn_frame.grid(row=row, column=0, columnspan=2, pady=15)
        
        ttk.Button(btn_frame, text="计算", command=self._calculate, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="清空", command=self._clear, width=10).pack(side=tk.LEFT, padx=5)
        
        row += 1
        export_frame = ttk.Frame(input_frame)
        export_frame.grid(row=row, column=0, columnspan=2, pady=5)
        
        ttk.Button(export_frame, text="导出图表", command=self._export_charts, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Button(export_frame, text="导出报告", command=self._export_report, width=10).pack(side=tk.LEFT, padx=5)
    
    def _on_section_type_changed(self, event=None):
        """断面类型切换"""
        section = self.section_type_var.get()
        self.circ_frame.grid_remove()
        self.hs_frame.grid_remove()
        self.horseshoe_std_frame.grid_remove()
        
        if section == "圆形":
            self.circ_frame.grid()
        elif section == "圆拱直墙型":
            self.hs_frame.grid()
        elif section in ["马蹄形标准Ⅰ型", "马蹄形标准Ⅱ型"]:
            self.horseshoe_std_frame.grid()
    
    def _create_output_panel(self, parent):
        """创建输出面板"""
        output_frame = ttk.Frame(parent)
        output_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        self.notebook = ttk.Notebook(output_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        
        self.result_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.result_tab, text="计算结果")
        self._create_result_view(self.result_tab)
        
        if VIZ_MODULE_LOADED:
            self.section_tab = ttk.Frame(self.notebook)
            self.notebook.add(self.section_tab, text="断面图")
            self._create_section_view(self.section_tab)
    
    def _create_result_view(self, parent):
        """创建结果视图"""
        result_frame = ttk.LabelFrame(parent, text="计算结果详情", padding="10")
        result_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.result_text = tk.Text(result_frame, wrap=tk.WORD, font=('Consolas', 11), 
                                    bg='#f5f5f5', relief=tk.FLAT)
        self.result_text.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(self.result_text, orient=tk.VERTICAL, 
                                   command=self.result_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.result_text.configure(yscrollcommand=scrollbar.set)
        
        self._show_initial_help()
    
    def _show_initial_help(self):
        """显示初始帮助"""
        self.result_text.configure(state=tk.NORMAL)
        self.result_text.delete(1.0, tk.END)
        self.result_text.insert(tk.END, '请输入参数后点击"计算"按钮开始计算...\n\n')
        self.result_text.insert(tk.END, "=" * 50 + "\n")
        self.result_text.insert(tk.END, "隧洞水力计算说明\n")
        self.result_text.insert(tk.END, "=" * 50 + "\n\n")
        self.result_text.insert(tk.END, "本程序支持以下断面类型：\n\n")
        self.result_text.insert(tk.END, "1. 圆形断面\n")
        self.result_text.insert(tk.END, "   - 最小直径 2.0m\n")
        self.result_text.insert(tk.END, "   - 最小净空高度 0.4m\n\n")
        self.result_text.insert(tk.END, "2. 圆拱直墙型\n")
        self.result_text.insert(tk.END, "   - 拱顶圆心角 90~180度\n")
        self.result_text.insert(tk.END, "   - 推荐高宽比 1.0~1.5\n\n")
        self.result_text.insert(tk.END, "3. 马蹄形标准Ⅰ型\n")
        self.result_text.insert(tk.END, "   - t=3, 底拱半径为3r\n")
        self.result_text.insert(tk.END, "   - 适用于地质条件较好的隧洞\n\n")
        self.result_text.insert(tk.END, "4. 马蹄形标准Ⅱ型\n")
        self.result_text.insert(tk.END, "   - t=2, 底拱半径为2r\n")
        self.result_text.insert(tk.END, "   - 适用于地质条件一般的隧洞\n\n")
        self.result_text.insert(tk.END, "计算基于曼宁公式：\n")
        self.result_text.insert(tk.END, "  Q = (1/n) × A × R^(2/3) × i^(1/2)\n")
        self.result_text.configure(state=tk.DISABLED)
    
    def _create_section_view(self, parent):
        """创建断面图视图"""
        self.section_fig = Figure(figsize=(8, 6), dpi=100)
        self.section_canvas = FigureCanvasTkAgg(self.section_fig, master=parent)
        self.section_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        toolbar = NavigationToolbar2Tk(self.section_canvas, parent)
        toolbar.update()
        
    def _show_error_in_result(self, title, message):
        """在计算结果区域显示错误信息"""
        self.result_text.configure(state=tk.NORMAL)
        self.result_text.delete(1.0, tk.END)
            
        output = []
        output.append("=" * 70)
        output.append(f"  {title}")
        output.append("=" * 70)
        output.append("")
        output.append(message)
        output.append("")
        output.append("-" * 70)
        output.append("请修正后重新计算。")
        output.append("=" * 70)
            
        self.result_text.insert(tk.END, "\n".join(output))
        self.result_text.configure(state=tk.DISABLED)
        
    def _calculate(self):
        """执行计算"""
        if not SUIDONG_MODULE_LOADED:
            self._show_error_in_result("模块加载错误", "隧洞计算模块未加载。")
            return
            
        try:
            Q = self.Q_var.get()
            n = self.n_var.get()
            slope_inv = self.slope_inv_var.get()
            v_min = self.v_min_var.get()
            v_max = self.v_max_var.get()
                
            if Q <= 0:
                self._show_error_in_result("参数错误", "请输入有效的设计流量 Q（必须大于0）。")
                return
            if n <= 0:
                self._show_error_in_result("参数错误", "请输入有效的糊率 n（必须大于0）。")
                return
            if slope_inv <= 0:
                self._show_error_in_result("参数错误", "请输入有效的水力坡降倒数（必须大于0）。")
                return
            
            manual_increase = None
            if self.manual_increase_var.get().strip():
                manual_increase = float(self.manual_increase_var.get())
            
            section_type = self.section_type_var.get()
            
            if section_type == "圆形":
                manual_D = None
                if self.manual_D_var.get().strip():
                    manual_D = float(self.manual_D_var.get())
                
                result = suidong_circular_calculate(
                    Q=Q, n=n, slope_inv=slope_inv,
                    v_min=v_min, v_max=v_max,
                    manual_D=manual_D,
                    manual_increase_percent=manual_increase
                )
            elif section_type == "圆拱直墙型":
                # 如果圆心角留空，则默认使用180°
                theta_str = self.theta_var.get().strip()
                if theta_str:
                    theta_deg = float(theta_str)
                else:
                    theta_deg = 180.0
                    
                manual_B = None
                if self.manual_B_hs_var.get().strip():
                    manual_B = float(self.manual_B_hs_var.get())
                
                result = suidong_horseshoe_calculate(
                    Q=Q, n=n, slope_inv=slope_inv,
                    v_min=v_min, v_max=v_max,
                    theta_deg=theta_deg,
                    manual_B=manual_B,
                    manual_increase_percent=manual_increase
                )
            elif section_type in ["马蹄形1", "马蹄形2", "马蹄形标准Ⅰ型", "马蹄形标准Ⅱ型"]:
                # 马蹄形断面
                horseshoe_type = 1 if section_type in ["马蹄形1", "马蹄形标准Ⅰ型"] else 2
                manual_r = None
                if self.manual_r_var.get().strip():
                    manual_r = float(self.manual_r_var.get())
                
                result = suidong_horseshoe_std_calculate(
                    Q=Q, n=n, slope_inv=slope_inv,
                    v_min=v_min, v_max=v_max,
                    section_type=horseshoe_type,
                    manual_r=manual_r,
                    manual_increase_percent=manual_increase
                )
            
            self.input_params = {
                'Q': Q, 'n': n, 'slope_inv': slope_inv,
                'v_min': v_min, 'v_max': v_max,
                'section_type': section_type,
                'manual_increase': manual_increase
            }
            self.current_result = result
            
            # 计算完成后，更新加大比例提示标签显示实际使用的值
            if result.get('success') and 'increase_percent' in result:
                actual_increase = result['increase_percent']
                if self.manual_increase_var.get().strip():
                    self.increase_hint_var.set(f"(手动指定: {actual_increase:.1f}%)")
                else:
                    self.increase_hint_var.set(f"(自动计算: {actual_increase:.1f}%)")
            
            self._update_result_display(result)
            
            if VIZ_MODULE_LOADED:
                self._update_section_plot(result)
            
        except (ValueError, tk.TclError) as e:
            # 捕获参数错误（如未输入或格式错误）
            error_detail = str(e)
            if "invalid literal" in error_detail or "expected floating" in error_detail:
                self._show_error_in_result("输入错误", "参数输入不完整或格式错误，请检查并填写所有必填参数：\n- 设计流量 Q\n- 糊率 n\n- 水力坡降 1/x")
            else:
                self._show_error_in_result("输入错误", f"{error_detail}")
        except Exception as e:
            self._show_error_in_result("计算错误", f"计算过程出错: {str(e)}")
    
    def _update_result_display(self, result):
        """更新结果显示"""
        self.result_text.configure(state=tk.NORMAL)
        self.result_text.delete(1.0, tk.END)
        
        if not result['success']:
            error_msg = result.get('error_message', '未知错误')
            self.result_text.insert(tk.END, f"计算失败: {error_msg}\n")
            self.result_text.configure(state=tk.DISABLED)
            return
        
        section_type = result.get('section_type', '')
        Q = self.input_params['Q']
        n = self.input_params['n']
        slope_inv = self.input_params['slope_inv']
        i = 1 / slope_inv
        v_min = self.input_params['v_min']
        v_max = self.input_params['v_max']
        
        output = []
        output.append("=" * 70)
        output.append(f"              隧洞水力计算结果 - {section_type}")
        output.append("=" * 70)
        output.append("")
        
        # 根据输出选项显示不同内容
        if not self.show_detail_var.get():
            # 简要输出
            output.append("【输入参数】")
            output.append(f"  设计流量 Q = {Q:.3f} m³/s")
            output.append(f"  糙率 n = {n}")
            output.append(f"  水力坡降 1/{int(slope_inv)}")
            output.append("")
            
            output.append("【断面尺寸】")
            if section_type == '圆形':
                output.append(f"  直径 D = {result.get('D', 0):.2f} m")
            elif section_type == '圆拱直墙型':
                output.append(f"  宽度 B = {result.get('B', 0):.2f} m")
                output.append(f"  高度 H = {result.get('H_total', 0):.2f} m")
            elif section_type in ['马蹄形1', '马蹄形2', '马蹄形标准Ⅰ型', '马蹄形标准Ⅱ型']:
                output.append(f"  半径 r = {result.get('r', 0):.2f} m")
            output.append(f"  总面积 A = {result.get('A_total', 0):.3f} m²")
            output.append("")
            
            output.append("【设计流量工况】")
            output.append(f"  设计水深 h = {result.get('h_design', 0):.3f} m")
            output.append(f"  设计流速 V = {result.get('V_design', 0):.3f} m/s")
            output.append(f"  净空高度 Fb = {result.get('freeboard_hgt_design', 0):.3f} m")
            output.append(f"  净空比例 = {result.get('freeboard_pct_design', 0):.1f}%")
            output.append("")
            
            output.append("【加大流量工况】")
            inc_pct = result.get('increase_percent', 0)
            manual_increase = self.input_params.get('manual_increase')
            inc_source = "(手动指定)" if manual_increase else "(自动计算)"
            output.append(f"  流量加大比例 = {inc_pct:.1f}% {inc_source}")
            output.append(f"  加大流量 Q加大 = {result.get('Q_increased', 0):.3f} m³/s")
            output.append(f"  加大水深 h加大 = {result.get('h_increased', 0):.3f} m")
            output.append(f"  加大流速 V加大 = {result.get('V_increased', 0):.3f} m/s")
            output.append(f"  净空高度 Fb加大 = {result.get('freeboard_hgt_inc', 0):.3f} m")
            output.append(f"  净空比例 = {result.get('freeboard_pct_inc', 0):.1f}%")
            output.append("")
            
            output.append("【验证结果】")
            V = result.get('V_design', 0)
            velocity_ok = v_min <= V <= v_max
            fb_pct = result.get('freeboard_pct_inc', 0)
            fb_hgt = result.get('freeboard_hgt_inc', 0)
            fb_ok = fb_pct >= 15 and fb_hgt >= 0.4
            output.append(f"  流速验证: {'✓ 通过' if velocity_ok else '✗ 未通过'}")
            output.append(f"  净空验证: {'✓ 通过' if fb_ok else '需注意'}")
            output.append("")
        else:
            # 详细输出
            output.append("【一、输入参数】")
            output.append(f"  设计流量 Q = {Q:.3f} m³/s")
            output.append(f"  糙率 n = {n}")
            output.append(f"  水力坡降 1/{int(slope_inv)}")
            output.append(f"  不淤流速 = {v_min} m/s")
            output.append(f"  不冲流速 = {v_max} m/s")
            output.append("")
            
            A_total = result.get('A_total', 0)
            h_design = result.get('h_design', 0)
            A_design = result.get('A_design', 0)
            P_design = result.get('P_design', 0)
            R_hyd = result.get('R_hyd_design', 0)
            V_design = result.get('V_design', 0)
            Q_calc = result.get('Q_calc', 0)
            
            if section_type == '圆形':
                D = result.get('D', 0)
                output.append("【二、断面尺寸】")
                output.append("")
                output.append(f"  1. 设计直径:")
                output.append(f"     D = {D:.2f} m")
                output.append("")
                output.append(f"  2. 断面总面积计算:")
                output.append(f"     A总 = π × D² / 4")
                output.append(f"        = {PI:.4f} × {D:.2f}² / 4")
                output.append(f"        = {A_total:.3f} m²")
                output.append("")
            elif section_type == '圆拱直墙型':
                B = result.get('B', 0)
                H = result.get('H_total', 0)
                theta_deg = result.get('theta_deg', 0)
                output.append("【二、断面尺寸】")
                output.append("")
                output.append(f"  1. 设计宽度: B = {B:.2f} m")
                output.append(f"  2. 设计高度: H = {H:.2f} m")
                output.append(f"  3. 拱顶圆心角: θ = {theta_deg:.1f}°")
                output.append(f"  4. 高宽比: H/B = {H:.2f}/{B:.2f} = {result.get('HB_ratio', 0):.3f}")
                output.append(f"  5. 断面总面积: A总 = {A_total:.3f} m²")
                output.append("")
            elif section_type in ['马蹄形1', '马蹄形2', '马蹄形标准Ⅰ型', '马蹄形标准Ⅱ型']:
                r = result.get('r', 0)
                D_equiv = result.get('D_equiv', 0)
                output.append("【二、断面尺寸】")
                output.append("")
                output.append(f"  断面类型: {'标准Ⅰ型' if section_type in ['马蹄形1', '马蹄形标准Ⅰ型'] else '标准Ⅱ型'}")
                output.append(f"  1. 设计半径: r = {r:.2f} m")
                output.append(f"  2. 等效直径: 2r = {D_equiv:.2f} m")
                output.append(f"  3. 断面总面积: A总 = {A_total:.3f} m²")
                output.append("")
            else:
                B = result.get('B', 0)
                H = result.get('H', 0)
                output.append("【二、断面尺寸】")
                output.append("")
                output.append(f"  1. 设计宽度: B = {B:.2f} m")
                output.append(f"  2. 设计高度: H = {H:.2f} m")
                output.append(f"  3. 高宽比: H/B = {H:.2f}/{B:.2f} = {result.get('HB_ratio', 0):.3f}")
                output.append(f"  4. 断面总面积: A总 = {A_total:.3f} m²")
                output.append("")
            
            output.append("【三、设计流量工况计算】")
            output.append(f"  Q = {Q:.3f} m³/s")
            output.append("")
            output.append(f"  1. 设计水深:")
            output.append(f"     h = {h_design:.3f} m")
            output.append("")
            output.append(f"  2. 过水面积:")
            output.append(f"     A = {A_design:.3f} m²")
            output.append("")
            output.append(f"  3. 湿周计算:")
            output.append(f"     χ = {P_design:.3f} m")
            output.append("")
            output.append(f"  4. 水力半径计算:")
            output.append(f"      R = A / χ")
            output.append(f"        = {A_design:.3f} / {P_design:.3f}")
            output.append(f"        = {R_hyd:.3f} m")
            output.append("")
            output.append(f"  5. 设计流速计算 (曼宁公式):")
            output.append(f"      V = (1/n) × R^(2/3) × i^(1/2)")
            output.append(f"        = (1/{n}) × {R_hyd:.3f}^(2/3) × {i:.6f}^(1/2)")
            output.append(f"        = {1/n:.2f} × {R_hyd**(2/3):.4f} × {math.sqrt(i):.6f}")
            output.append(f"        = {V_design:.3f} m/s")
            output.append("")
            output.append(f"  6. 流量校核:")
            output.append(f"      Q计算 = V × A")
            output.append(f"           = {V_design:.3f} × {A_design:.3f}")
            output.append(f"           = {Q_calc:.3f} m³/s")
            output.append(f"      误差 = {abs(Q_calc-Q)/Q*100:.2f}%")
            output.append("")
            
            fb_pct_design = result.get('freeboard_pct_design', 0)
            fb_hgt_design = result.get('freeboard_hgt_design', 0)
            output.append(f"  7. 净空面积: {fb_pct_design:.1f}%")
            output.append(f"  8. 净空高度: Fb = {fb_hgt_design:.3f} m")
            output.append("")
            
            # 加大流量工况
            inc_pct = result.get('increase_percent', 0)
            Q_加大 = result.get('Q_increased', 0)
            h_加大 = result.get('h_increased', 0)
            V_加大 = result.get('V_increased', 0)
            fb_pct = result.get('freeboard_pct_inc', 0)
            fb_hgt = result.get('freeboard_hgt_inc', 0)
            
            manual_increase = self.input_params.get('manual_increase')
            inc_source = "(手动指定)" if manual_increase else "(自动计算)"
            
            output.append("【四、加大流量工况计算】")
            output.append("")
            output.append(f"  9. 加大流量计算:")
            output.append(f"      流量加大比例 = {inc_pct:.1f}% {inc_source}")
            output.append(f"      Q加大 = Q × (1 + {inc_pct/100:.2f})")
            output.append(f"           = {Q:.3f} × {1+inc_pct/100:.2f}")
            output.append(f"           = {Q_加大:.3f} m³/s")
            output.append("")
            output.append(f"  10. 加大水深: h加大 = {h_加大:.3f} m")
            output.append("")

            output.append("  11. 过水面积计算:")
            output.append(f"     A加大 = {result.get('A_increased', 0):.3f} m²")
            output.append("")

            output.append("  12. 湿周计算:")
            output.append(f"     P加大 = {result.get('P_increased', 0):.3f} m")
            output.append("")

            output.append("  13. 水力半径计算:")
            output.append(f"     R加大 = A加大 / P加大")
            output.append(f"          = {result.get('A_increased', 0):.3f} / {result.get('P_increased', 0):.3f}")
            output.append(f"          = {result.get('R_hyd_increased', 0):.3f} m")
            output.append("")

            output.append("  14. 加大流速计算 (曼宁公式):")
            output.append(f"     V加大 = (1/n) × R加大^(2/3) × i^(1/2)")
            output.append(f"          = (1/{n}) × {result.get('R_hyd_increased', 0):.3f}^(2/3) × {i:.6f}^(1/2)")
            output.append(f"          = {1/n:.2f} × {result.get('R_hyd_increased', 0)**(2/3):.4f} × {math.sqrt(i):.6f}")
            output.append(f"          = {V_加大:.3f} m/s")
            output.append("")

            output.append("  15. 流量校核:")
            output.append(f"     Q计算 = A加大 × V加大 = {result.get('A_increased', 0):.3f} × {V_加大:.3f} = {Q_加大:.3f} m³/s")
            output.append("")

            output.append(f"  16. 净空面积: {fb_pct:.1f}%")
            output.append(f"  17. 净空高度: Fb加大 = {fb_hgt:.3f} m")
            output.append("")
            
            # 验证
            output.append("【五、设计验证】")
            output.append("")
            V = V_design
            velocity_ok = v_min <= V <= v_max
            fb_ok = fb_pct >= 15 and fb_hgt >= 0.4
            
            output.append(f"  14. 流速验证:")
            output.append(f"      不淤流速 ≤ V ≤ 不冲流速")
            output.append(f"      {v_min} ≤ {V:.3f} ≤ {v_max}")
            output.append(f"      结果: {'通过 ✓' if velocity_ok else '未通过 ✗'}")
            output.append("")
            output.append(f"  15. 净空面积验证:")
            output.append(f"      净空面积 ≥ 15%")
            output.append(f"      {fb_pct:.1f}% ≥ 15%")
            output.append(f"      结果: {'通过 ✓' if fb_pct >= 15 else '需注意'}")
            output.append("")
            output.append(f"  16. 净空高度验证:")
            output.append(f"      净空高度 ≥ 0.4m")
            output.append(f"      {fb_hgt:.3f}m ≥ 0.4m")
            output.append(f"      结果: {'通过 ✓' if fb_hgt >= 0.4 else '需注意'}")
            output.append("")
        
        output.append("=" * 70)
        output.append(f"  计算完成: {'成功 ✓' if result['success'] else '失败 ✗'}")
        output.append("=" * 70)
        
        self.result_text.insert(tk.END, "\n".join(output))
        self.result_text.configure(state=tk.DISABLED)
    
    def _update_section_plot(self, result):
        """更新断面图"""
        self.section_fig.clear()
        
        if not result['success']:
            return
        
        ax = self.section_fig.add_subplot(111)
        section_type = result.get('section_type', '')
        
        if section_type == '圆形':
            self._draw_circular_section(ax, result)
        elif section_type == '圆拱直墙型':
            self._draw_horseshoe_section(ax, result)
        elif section_type in ['马蹄形1', '马蹄形2', '马蹄形标准Ⅰ型', '马蹄形标准Ⅱ型']:
            self._draw_horseshoe_std_section(ax, result)
        else:
            self._draw_rect_section(ax, result)
        
        self.section_fig.tight_layout()
        self.section_canvas.draw()
    
    def _draw_circular_section(self, ax, result):
        """绘制圆形断面"""
        D = result.get('D', 2)
        R = D / 2
        h_water = result.get('h_design', 0)
        Q = self.input_params['Q']
        V = result.get('V_design', 0)
        
        theta = np.linspace(0, 2*np.pi, 100)
        circle_x = R * np.cos(theta)
        circle_y = R + R * np.sin(theta)
        ax.plot(circle_x, circle_y, 'k-', linewidth=2)
        
        if h_water > 0 and h_water < D:
            h = h_water - R
            if abs(h) <= R:
                half_angle = math.acos(h / R)
                water_angles = np.linspace(np.pi/2 + half_angle, 
                                           np.pi/2 - half_angle + 2*np.pi, 50)
                water_x = R * np.cos(water_angles)
                water_y = R + R * np.sin(water_angles)
                
                mask = water_y <= h_water + 0.001
                water_x_f = water_x[mask]
                water_y_f = water_y[mask]
                
                if len(water_x_f) > 0:
                    water_width = math.sqrt(R**2 - h**2)
                    poly_x = np.concatenate([[water_width], water_x_f, [-water_width]])
                    poly_y = np.concatenate([[h_water], water_y_f, [h_water]])
                    ax.fill(poly_x, poly_y, color='lightblue', alpha=0.7)
                    ax.plot([-water_width, water_width], [h_water, h_water], 'b-', linewidth=1.5)
        
        # 添加尺寸标注
        # 标注直径 D
        ax.annotate('', xy=(R, R), xytext=(-R, R),
                   arrowprops=dict(arrowstyle='<->', color='gray', lw=1.5))
        ax.text(0, R+0.15*R, f'D={D:.2f}m', ha='center', fontsize=9, color='gray')
        
        # 标注水深 h
        if h_water > 0:
            ax.annotate('', xy=(-R-0.15*R, h_water), xytext=(-R-0.15*R, 0),
                       arrowprops=dict(arrowstyle='<->', color='blue', lw=1.5))
            ax.text(-R-0.25*R, h_water/2, f'h={h_water:.2f}m', ha='right', fontsize=9, color='blue', rotation=90, va='center')
        
        ax.set_xlim(-R*1.8, R*1.8)
        ax.set_ylim(-R*0.4, D*1.2)
        ax.set_aspect('equal')
        ax.set_title(f'圆形隧洞断面\nQ={Q:.2f}m$^3$/s, V={V:.2f}m/s', fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.axhline(y=0, color='brown', linewidth=3)
    
    def _draw_horseshoe_section(self, ax, result):
        """绘制圆拱直墙型断面"""
        B = result.get('B', 2)
        H = result.get('H_total', 2)
        h_water = result.get('h_design', 0)
        theta_deg = result.get('theta_deg', 120)
        Q = self.input_params['Q']
        V = result.get('V_design', 0)
        
        theta_rad = math.radians(theta_deg)
        half_theta = theta_rad / 2
        
        # 计算拱顶圆弧半径: B/2 = R * sin(θ/2) => R = (B/2) / sin(θ/2)
        if math.sin(half_theta) > 0.001:
            R_arch = (B / 2) / math.sin(half_theta)
        else:
            R_arch = B  # 角度接近0时的保护
        
        # 拱顶高度: H_arch = R * (1 - cos(θ/2))
        H_arch = R_arch * (1 - math.cos(half_theta))
        H_straight = max(0, H - H_arch)
        
        # 圆心y坐标: 拱顶最高点为H, 圆心在其下方R处
        # y_center = H - R_arch = H_straight + H_arch - R_arch = H_straight - R * cos(θ/2)
        arch_center_y = H - R_arch
        
        # 绘制轮廓线（闭合路径）
        # 从左下角开始，逆时针绘制
        outline_x = []
        outline_y = []
        
        # 1. 底边（从左到右）
        outline_x.extend([-B/2, B/2])
        outline_y.extend([0, 0])
        
        # 2. 右侧直墙（从下到上）
        outline_x.append(B/2)
        outline_y.append(H_straight)
        
        # 3. 拱顶圆弧（从右到左）
        # 角度从 π/2 - θ/2 (右端) 到 π/2 + θ/2 (左端)
        num_arc_points = 50
        arch_angles = np.linspace(np.pi/2 - half_theta, np.pi/2 + half_theta, num_arc_points)
        arch_x = R_arch * np.cos(arch_angles)
        arch_y = arch_center_y + R_arch * np.sin(arch_angles)
        outline_x.extend(arch_x.tolist())
        outline_y.extend(arch_y.tolist())
        
        # 4. 左侧直墙（从上到下）
        outline_x.append(-B/2)
        outline_y.append(H_straight)
        
        # 闭合到起点
        outline_x.append(-B/2)
        outline_y.append(0)
        
        # 绘制闭合轮廓线
        ax.plot(outline_x, outline_y, 'k-', linewidth=2)
        
        # 水体填充
        if h_water > 0:
            water_x = []
            water_y = []
            
            if h_water <= H_straight:
                # 水位在直墙段内，简单矩形
                water_x = [-B/2, B/2, B/2, -B/2, -B/2]
                water_y = [0, 0, h_water, h_water, 0]
            else:
                # 水位进入拱顶段
                # 计算水面与圆弧的交点
                # 水面高度为h_water，圆心在(0, arch_center_y)
                # 交点满足: y = h_water, (x)^2 + (y - arch_center_y)^2 = R^2
                dy = h_water - arch_center_y
                if abs(dy) < R_arch:
                    water_half_width = math.sqrt(R_arch**2 - dy**2)
                else:
                    water_half_width = 0
                
                # 水体区域：底边 + 右墙 + 右侧水面到圆弧交点 + 圆弧下部 + 左侧水面到圆弧交点 + 左墙
                water_x = [-B/2, B/2, B/2]
                water_y = [0, 0, H_straight]
                
                # 添加圆弧部分（从右到左，只取水面以下部分）
                arc_angles_full = np.linspace(np.pi/2 - half_theta, np.pi/2 + half_theta, num_arc_points)
                arc_x_full = R_arch * np.cos(arc_angles_full)
                arc_y_full = arch_center_y + R_arch * np.sin(arc_angles_full)
                
                # 过滤水面以下的圆弧点
                for i, (ax_pt, ay_pt) in enumerate(zip(arc_x_full, arc_y_full)):
                    if ay_pt <= h_water + 0.001:
                        water_x.append(ax_pt)
                        water_y.append(ay_pt)
                
                water_x.extend([-B/2, -B/2])
                water_y.extend([H_straight, 0])
                
                # 添加水面线闭合
                if water_half_width > 0:
                    # 找到水面两端点并用直线连接
                    pass  # 已经通过圆弧点连接
            
            ax.fill(water_x, water_y, color='lightblue', alpha=0.7)
            
            # 绘制水面线
            if h_water <= H_straight:
                ax.plot([-B/2, B/2], [h_water, h_water], 'b-', linewidth=1.5)
            else:
                dy = h_water - arch_center_y
                if abs(dy) < R_arch:
                    water_half_width = math.sqrt(R_arch**2 - dy**2)
                    ax.plot([-water_half_width, water_half_width], [h_water, h_water], 'b-', linewidth=1.5)
        
        # 添加尺寸标注
        # 标注宽度 B
        ax.annotate('', xy=(B/2, -0.1*H), xytext=(-B/2, -0.1*H),
                   arrowprops=dict(arrowstyle='<->', color='gray', lw=1.5))
        ax.text(0, -0.2*H, f'B={B:.2f}m', ha='center', fontsize=9, color='gray')
        
        # 标注总高 H
        ax.annotate('', xy=(B/2+0.1*B, H), xytext=(B/2+0.1*B, 0),
                   arrowprops=dict(arrowstyle='<->', color='purple', lw=1.5))
        ax.text(B/2+0.15*B, H/2, f'H={H:.2f}m', ha='left', fontsize=9, color='purple', rotation=90, va='center')
        
        # 标注水深 h
        if h_water > 0:
            ax.annotate('', xy=(-B/2-0.1*B, h_water), xytext=(-B/2-0.1*B, 0),
                       arrowprops=dict(arrowstyle='<->', color='blue', lw=1.5))
            ax.text(-B/2-0.15*B, h_water/2, f'h={h_water:.2f}m', ha='right', fontsize=9, color='blue', rotation=90, va='center')
        
        ax.set_xlim(-B*0.9, B*0.9)
        ax.set_ylim(-H*0.35, H*1.2)
        ax.set_aspect('equal')
        ax.set_title(f'圆拱直墙型隧洞断面\nQ={Q:.2f}m$^3$/s, V={V:.2f}m/s', fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.axhline(y=0, color='brown', linewidth=3)
    
    def _draw_rect_section(self, ax, result):
        """绘制矩形断面"""
        B = result.get('B', 2)
        H = result.get('H', 1)
        h_water = result.get('h_design', 0)
        Q = self.input_params['Q']
        V = result.get('V_design', 0)
        
        ax.plot([-B/2, -B/2], [0, H], 'k-', linewidth=2)
        ax.plot([B/2, B/2], [0, H], 'k-', linewidth=2)
        ax.plot([-B/2, B/2], [0, 0], 'k-', linewidth=2)
        ax.plot([-B/2, B/2], [H, H], 'k-', linewidth=2)
        
        if h_water > 0:
            water_x = [-B/2, -B/2, B/2, B/2]
            water_y = [0, h_water, h_water, 0]
            ax.fill(water_x, water_y, color='lightblue', alpha=0.7)
            ax.plot([-B/2, B/2], [h_water, h_water], 'b-', linewidth=1.5)
        
        # 添加尺寸标注
        # 标注宽度 B
        ax.annotate('', xy=(B/2, -0.1*H), xytext=(-B/2, -0.1*H),
                   arrowprops=dict(arrowstyle='<->', color='gray', lw=1.5))
        ax.text(0, -0.2*H, f'B={B:.2f}m', ha='center', fontsize=9, color='gray')
        
        # 标注高度 H
        ax.annotate('', xy=(B/2+0.1*B, H), xytext=(B/2+0.1*B, 0),
                   arrowprops=dict(arrowstyle='<->', color='purple', lw=1.5))
        ax.text(B/2+0.15*B, H/2, f'H={H:.2f}m', ha='left', fontsize=9, color='purple', rotation=90, va='center')
        
        # 标注水深 h
        if h_water > 0:
            ax.annotate('', xy=(-B/2-0.1*B, h_water), xytext=(-B/2-0.1*B, 0),
                       arrowprops=dict(arrowstyle='<->', color='blue', lw=1.5))
            ax.text(-B/2-0.15*B, h_water/2, f'h={h_water:.2f}m', ha='right', fontsize=9, color='blue', rotation=90, va='center')
        
        ax.set_xlim(-B*0.9, B*0.9)
        ax.set_ylim(-H*0.35, H*1.2)
        ax.set_aspect('equal')
        ax.set_title(f'矩形暗涵断面\nQ={Q:.2f}m$^3$/s, V={V:.2f}m/s', fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.axhline(y=0, color='brown', linewidth=3)
    
    def _draw_horseshoe_std_section(self, ax, result):
        """绘制标准马蹄形断面 - 通过水面宽度-高度关系绘制封闭轮廓"""
        r = result.get('r', 1)
        h_water = result.get('h_design', 0)
        Q = self.input_params['Q']
        V = result.get('V_design', 0)
        section_type = result.get('section_type', '马蹄形标准Ⅰ型')
        
        # 根据断面类型设置参数
        if '马蹄形标准Ⅰ型' in section_type or section_type == '马蹄形标准Ⅰ型' or section_type == '马蹄形1':
            t = 3.0
            theta = 0.294515  # 约16.87°
            type_name = '标准Ⅰ型'
        else:
            t = 2.0
            theta = 0.424031  # 约24.30°
            type_name = '标准Ⅱ型'
        
        # 马蹄形几何参数
        R_arch = t * r  # 底拱和侧拱半径
        e = R_arch * (1 - math.cos(theta))  # 底拱最高点高度
        
        # 通过计算不同h值对应的水面宽度B来绘制断面轮廓
        def get_half_width(h):
            """ 根据高度h计算半宽 """
            if h <= 0:
                return 0
            elif h <= e:  # 底拱段
                cos_val = max(-1, min(1, 1 - h / R_arch))
                beta = math.acos(cos_val)
                return R_arch * math.sin(beta)
            elif h <= r:  # 侧拱段
                sin_val = max(-1, min(1, (1 - h / r) / t))
                alpha = math.asin(sin_val)
                return r * (t * math.cos(alpha) - t + 1)
            elif h <= 2 * r:  # 顶拱段
                cos_val = max(-1, min(1, h / r - 1))
                phi_half = math.acos(cos_val)
                return r * math.sin(phi_half)
            else:
                return 0
        
        # 生成断面轮廓点 - 从底部到顶部
        num_points = 100
        heights = np.linspace(0, 2*r, num_points)
        
        # 计算左右边界点
        left_x = []
        left_y = []
        right_x = []
        right_y = []
        
        for h in heights:
            half_w = get_half_width(h)
            left_x.append(-half_w)
            left_y.append(h)
            right_x.append(half_w)
            right_y.append(h)
        
        # 绘制封闭的断面轮廓
        # 左侧轮廓（从底部到顶部）
        ax.plot(left_x, left_y, 'k-', linewidth=2)
        # 右侧轮廓（从底部到顶部）
        ax.plot(right_x, right_y, 'k-', linewidth=2)
        # 顶部连接（已经通过上面的点连接）
        
        # 绘制水面和水域填充
        if h_water > 0 and h_water < 2 * r:
            water_half_width = get_half_width(h_water)
            
            # 生成水域轮廓点
            water_heights = np.linspace(0, h_water, 50)
            water_left_x = [-get_half_width(h) for h in water_heights]
            water_left_y = list(water_heights)
            water_right_x = [get_half_width(h) for h in water_heights]
            water_right_y = list(water_heights)
            
            # 构建封闭的水域多边形
            fill_x = water_left_x + water_right_x[::-1]
            fill_y = water_left_y + water_right_y[::-1]
            ax.fill(fill_x, fill_y, color='lightblue', alpha=0.7)
            
            # 绘制水面线
            ax.plot([-water_half_width, water_half_width], [h_water, h_water], 'b-', linewidth=1.5)
        
        # 添加尺寸标注
        # 标注半径 r
        ax.annotate('', xy=(r, r), xytext=(0, r),
                   arrowprops=dict(arrowstyle='->', color='gray', lw=1.5))
        ax.text(r/2, r+0.15*r, f'r={r:.2f}m', ha='center', fontsize=9, color='gray')
        
        # 标注水深 h
        if h_water > 0:
            ax.annotate('', xy=(-r-0.2*r, h_water), xytext=(-r-0.2*r, 0),
                       arrowprops=dict(arrowstyle='<->', color='blue', lw=1.5))
            ax.text(-r-0.3*r, h_water/2, f'h={h_water:.2f}m', ha='right', fontsize=9, color='blue', rotation=90, va='center')
        
        ax.set_xlim(-r*2.2, r*2.2)
        ax.set_ylim(-r*0.3, 2.3*r)
        ax.set_aspect('equal')
        ax.set_title(f'马蹄形隧洞断面 ({type_name})\nQ={Q:.2f}m$^3$/s, V={V:.2f}m/s', fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.axhline(y=0, color='brown', linewidth=3)
    
    def _clear(self):
        """清空"""
        self._show_initial_help()
        if VIZ_MODULE_LOADED:
            self.section_fig.clear()
            self.section_canvas.draw()
    
    def _export_charts(self):
        """导出图表"""
        if not hasattr(self, 'current_result') or not self.current_result or not self.current_result['success']:
            messagebox.showwarning("警告", "请先进行计算")
            return
        
        folder = filedialog.askdirectory(title="选择保存目录")
        if not folder:
            return
        
        try:
            self.section_fig.savefig(os.path.join(folder, '隧洞断面图.png'), dpi=150, bbox_inches='tight')
            messagebox.showinfo("成功", f"图表已保存到: {folder}")
        except Exception as e:
            messagebox.showerror("错误", f"保存失败: {str(e)}")
    
    def _export_report(self):
        """导出报告"""
        if not hasattr(self, 'current_result') or not self.current_result or not self.current_result['success']:
            messagebox.showwarning("警告", "请先进行计算")
            return
        
        filepath = filedialog.asksaveasfilename(
            title="保存报告",
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")]
        )
        if not filepath:
            return
        
        try:
            self.result_text.configure(state=tk.NORMAL)
            content = self.result_text.get(1.0, tk.END)
            self.result_text.configure(state=tk.DISABLED)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            
            messagebox.showinfo("成功", f"报告已保存到: {filepath}")
        except Exception as e:
            messagebox.showerror("错误", f"保存失败: {str(e)}")


# ============================================================
# 矩形暗涵计算面板
# ============================================================

class RectangularCulvertPanel(ttk.Frame):
    """矩形暗涵计算面板"""
    
    def __init__(self, parent):
        super().__init__(parent)
        
        self.input_params = {}
        self.current_result = None
        self.show_detail_var = tk.BooleanVar(value=True)  # 默认显示详细过程
        
        self._create_ui()
    
    def _create_ui(self):
        """创建UI"""
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        self._create_input_panel(main_frame)
        self._create_output_panel(main_frame)
    
    def _create_input_panel(self, parent):
        """创建输入面板"""
        input_frame = ttk.LabelFrame(parent, text="输入参数", padding="10")
        input_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        
        # 基本参数
        self.Q_var = tk.DoubleVar(value=5.0)
        self.n_var = tk.DoubleVar(value=0.014)
        self.slope_inv_var = tk.DoubleVar(value=2000)
        self.v_min_var = tk.DoubleVar(value=0.1)
        self.v_max_var = tk.DoubleVar(value=100.0)
        
        row = 0
        ttk.Label(input_frame, text="设计流量 Q (m³/s):").grid(row=row, column=0, sticky=tk.W, pady=5)
        ttk.Entry(input_frame, textvariable=self.Q_var, width=15).grid(row=row, column=1, padx=5, pady=5)
        
        row += 1
        ttk.Label(input_frame, text="糙率 n:").grid(row=row, column=0, sticky=tk.W, pady=5)
        ttk.Entry(input_frame, textvariable=self.n_var, width=15).grid(row=row, column=1, padx=5, pady=5)
        
        row += 1
        ttk.Label(input_frame, text="水力坡降 1/").grid(row=row, column=0, sticky=tk.W, pady=5)
        ttk.Entry(input_frame, textvariable=self.slope_inv_var, width=15).grid(row=row, column=1, padx=5, pady=5)
        
        # 流速参数栏目
        row += 1
        ttk.Label(input_frame, text="【流速参数】", font=('', 9, 'bold')).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=5)
        
        row += 1
        ttk.Label(input_frame, text="不淤流速 (m/s):").grid(row=row, column=0, sticky=tk.W, pady=5)
        ttk.Entry(input_frame, textvariable=self.v_min_var, width=15).grid(row=row, column=1, padx=5, pady=5)
        
        row += 1
        ttk.Label(input_frame, text="不冲流速 (m/s):").grid(row=row, column=0, sticky=tk.W, pady=5)
        ttk.Entry(input_frame, textvariable=self.v_max_var, width=15).grid(row=row, column=1, padx=5, pady=5)
        
        # 流速提示
        row += 1
        ttk.Label(input_frame, text="(一般情况下保持默认数值即可)", font=('', 8), foreground='black').grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=2)
        
        # 流量加大比例栏目
        row += 1
        ttk.Label(input_frame, text="【流量加大】", font=('', 9, 'bold')).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=5)
        
        row += 1
        self.manual_increase_var = tk.StringVar(value="")
        ttk.Label(input_frame, text="流量加大比例 (%):").grid(row=row, column=0, sticky=tk.W, pady=3)
        ttk.Entry(input_frame, textvariable=self.manual_increase_var, width=15).grid(row=row, column=1, padx=5, pady=3)
        
        row += 1
        self.increase_hint_var = tk.StringVar(value="(留空则自动计算)")
        self.increase_hint_label = ttk.Label(input_frame, textvariable=self.increase_hint_var, font=('', 8), foreground='black')
        self.increase_hint_label.grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=2)
        
        # 分隔线
        row += 1
        ttk.Separator(input_frame, orient=tk.HORIZONTAL).grid(row=row, column=0, columnspan=2, 
                                                                sticky=tk.EW, pady=10)
        
        # 可选参数标签
        row += 1
        ttk.Label(input_frame, text="【可选参数】", font=('', 9, 'bold')).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=5)
        
        self.manual_BH_var = tk.StringVar(value="")
        self.manual_B_var = tk.StringVar(value="")
        
        row += 1
        ttk.Label(input_frame, text="手动宽深比:").grid(row=row, column=0, sticky=tk.W, pady=3)
        ttk.Entry(input_frame, textvariable=self.manual_BH_var, width=15).grid(row=row, column=1, padx=5, pady=3)
        
        row += 1
        ttk.Label(input_frame, text="手动底宽 B (m):").grid(row=row, column=0, sticky=tk.W, pady=3)
        ttk.Entry(input_frame, textvariable=self.manual_B_var, width=15).grid(row=row, column=1, padx=5, pady=3)
        
        row += 1
        ttk.Label(input_frame, text="(二选一输入，留空则自动计算)", font=('', 8), foreground='black').grid(row=row, column=0, columnspan=2, sticky=tk.W)
        
        # 高宽比提示
        row += 1
        ttk.Label(input_frame, text="高宽比限值H/B（或B/H）一般不超过1.2", font=('', 8), foreground='#0066CC').grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=2)
        
        # 水力最佳断面提示
        row += 1
        ttk.Label(input_frame, text="留空则采用水力最佳断面（β=B/h=2）", font=('', 8), foreground='#0066CC').grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=2)
        
        row += 1
        ttk.Label(input_frame, text="参考《涵洞》（熊启钧 编著）", font=('', 8), foreground='gray').grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=2)
        
        # 分隔线
        row += 1
        ttk.Separator(input_frame, orient=tk.HORIZONTAL).grid(row=row, column=0, columnspan=2, 
                                                                sticky=tk.EW, pady=10)
        
        # 输出选项
        row += 1
        ttk.Checkbutton(input_frame, text="输出详细计算过程", 
                       variable=self.show_detail_var).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=5)
        
        # 按钮
        row += 1
        btn_frame = ttk.Frame(input_frame)
        btn_frame.grid(row=row, column=0, columnspan=2, pady=15)
        
        ttk.Button(btn_frame, text="计算", command=self._calculate, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="清空", command=self._clear, width=10).pack(side=tk.LEFT, padx=5)
        
        row += 1
        export_frame = ttk.Frame(input_frame)
        export_frame.grid(row=row, column=0, columnspan=2, pady=5)
        
        ttk.Button(export_frame, text="导出图表", command=self._export_charts, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Button(export_frame, text="导出报告", command=self._export_report, width=10).pack(side=tk.LEFT, padx=5)
    
    def _create_output_panel(self, parent):
        """创建输出面板"""
        output_frame = ttk.Frame(parent)
        output_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        self.notebook = ttk.Notebook(output_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        
        self.result_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.result_tab, text="计算结果")
        self._create_result_view(self.result_tab)
        
        if VIZ_MODULE_LOADED:
            self.section_tab = ttk.Frame(self.notebook)
            self.notebook.add(self.section_tab, text="断面图")
            self._create_section_view(self.section_tab)
    
    def _create_result_view(self, parent):
        """创建结果视图"""
        result_frame = ttk.LabelFrame(parent, text="计算结果详情", padding="10")
        result_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.result_text = tk.Text(result_frame, wrap=tk.WORD, font=('Consolas', 11), 
                                    bg='#f5f5f5', relief=tk.FLAT)
        self.result_text.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(self.result_text, orient=tk.VERTICAL, 
                                   command=self.result_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.result_text.configure(yscrollcommand=scrollbar.set)
        
        self._show_initial_help()
    
    def _show_initial_help(self):
        """显示初始帮助"""
        self.result_text.configure(state=tk.NORMAL)
        self.result_text.delete(1.0, tk.END)
        self.result_text.insert(tk.END, '请输入参数后点击"计算"按钮开始计算...\n\n')
        self.result_text.insert(tk.END, "=" * 50 + "\n")
        self.result_text.insert(tk.END, "矩形暗涵水力计算说明\n")
        self.result_text.insert(tk.END, "=" * 50 + "\n\n")
        self.result_text.insert(tk.END, "矩形暗涵断面特点：\n")
        self.result_text.insert(tk.END, "  - 推荐宽深比 0.5~2.5\n")
        self.result_text.insert(tk.END, "  - 高宽比限值H/B（或B/H）一般不超过1.2\n")
        self.result_text.insert(tk.END, "  - 最小净空面积 10%，最大30%\n")
        self.result_text.insert(tk.END, "  - 最小净空高度 0.4m\n\n")
        self.result_text.insert(tk.END, "水力最佳断面说明：\n")
        self.result_text.insert(tk.END, "  - 当底宽和宽深比均留空时，自动采用水力最佳断面\n")
        self.result_text.insert(tk.END, "  - 矩形断面水力最佳宽深比 β = B/h = 2\n")
        self.result_text.insert(tk.END, "  - 即底宽等于2倍水深时，水力效率最高\n\n")
        self.result_text.insert(tk.END, "净空约束条件（参考《灌溉与排水工程设计标准》 GB 50288-2018）：\n")
        self.result_text.insert(tk.END, "  - 净空面积应为涵洞断面总面积的10%~30%\n")
        self.result_text.insert(tk.END, "  - 净空高度在任何情况下均不得小于0.4m\n")
        self.result_text.insert(tk.END, "  - 当H≤3m时，净空高度应≥H/6\n")
        self.result_text.insert(tk.END, "  - 当H>3m时，净空高度应≥0.5m\n\n")
        self.result_text.insert(tk.END, "宽深比说明：\n")
        self.result_text.insert(tk.END, "  - 宽深比 β = B/h (底宽/设计水深)\n")
        self.result_text.insert(tk.END, "  - 可手动指定宽深比或底宽\n")
        self.result_text.insert(tk.END, "  - 留空则自动按水力最佳断面计算\n\n")
        self.result_text.insert(tk.END, "计算基于曼宁公式：\n")
        self.result_text.insert(tk.END, "  Q = (1/n) × A × R^(2/3) × i^(1/2)\n")
        self.result_text.configure(state=tk.DISABLED)
    
    def _create_section_view(self, parent):
        """创建断面图视图"""
        self.section_fig = Figure(figsize=(8, 6), dpi=100)
        self.section_canvas = FigureCanvasTkAgg(self.section_fig, master=parent)
        self.section_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        toolbar = NavigationToolbar2Tk(self.section_canvas, parent)
        toolbar.update()
        
    def _show_error_in_result(self, title, message):
        """在计算结果区域显示错误信息"""
        self.result_text.configure(state=tk.NORMAL)
        self.result_text.delete(1.0, tk.END)
            
        output = []
        output.append("=" * 70)
        output.append(f"  {title}")
        output.append("=" * 70)
        output.append("")
        output.append(message)
        output.append("")
        output.append("-" * 70)
        output.append("请修正后重新计算。")
        output.append("=" * 70)
            
        self.result_text.insert(tk.END, "\n".join(output))
        self.result_text.configure(state=tk.DISABLED)
        
    def _calculate(self):
        """执行计算"""
        if not SUIDONG_MODULE_LOADED:
            self._show_error_in_result("模块加载错误", "矩形暗涵计算模块未加载。")
            return
            
        try:
            Q = self.Q_var.get()
            n = self.n_var.get()
            slope_inv = self.slope_inv_var.get()
            v_min = self.v_min_var.get()
            v_max = self.v_max_var.get()
                
            if Q <= 0:
                self._show_error_in_result("参数错误", "请输入有效的设计流量 Q（必须大于0）。")
                return
            if n <= 0:
                self._show_error_in_result("参数错误", "请输入有效的糊率 n（必须大于0）。")
                return
            if slope_inv <= 0:
                self._show_error_in_result("参数错误", "请输入有效的水力坡降倒数（必须大于0）。")
                return
            
            manual_increase = None
            if self.manual_increase_var.get().strip():
                manual_increase = float(self.manual_increase_var.get())
            
            manual_BH = None
            if self.manual_BH_var.get().strip():
                manual_BH = float(self.manual_BH_var.get())
            manual_B = None
            if self.manual_B_var.get().strip():
                manual_B = float(self.manual_B_var.get())
            
            result = suidong_rect_calculate(
                Q=Q, n=n, slope_inv=slope_inv,
                v_min=v_min, v_max=v_max,
                target_BH_ratio=manual_BH,
                manual_B=manual_B,
                manual_increase_percent=manual_increase
            )
            
            self.input_params = {
                'Q': Q, 'n': n, 'slope_inv': slope_inv,
                'v_min': v_min, 'v_max': v_max,
                'manual_increase': manual_increase
            }
            self.current_result = result
            
            # 计算完成后，更新加大比例提示标签显示实际使用的值
            if result.get('success') and 'increase_percent' in result:
                actual_increase = result['increase_percent']
                if self.manual_increase_var.get().strip():
                    self.increase_hint_var.set(f"(手动指定: {actual_increase:.1f}%)")
                else:
                    self.increase_hint_var.set(f"(自动计算: {actual_increase:.1f}%)")
            
            self._update_result_display(result)
            
            if VIZ_MODULE_LOADED:
                self._update_section_plot(result)
            
        except (ValueError, tk.TclError) as e:
            # 捕获参数错误（如未输入或格式错误）
            error_detail = str(e)
            if "invalid literal" in error_detail or "expected floating" in error_detail:
                self._show_error_in_result("输入错误", "参数输入不完整或格式错误，请检查并填写所有必填参数：\n- 设计流量 Q\n- 糊率 n\n- 水力坡降 1/x")
            else:
                self._show_error_in_result("输入错误", f"{error_detail}")
        except Exception as e:
            self._show_error_in_result("计算错误", f"计算过程出错: {str(e)}")
    
    def _update_result_display(self, result):
        """更新结果显示"""
        self.result_text.configure(state=tk.NORMAL)
        self.result_text.delete(1.0, tk.END)
        
        if not result['success']:
            error_msg = result.get('error_message', '未知错误')
            self.result_text.insert(tk.END, f"计算失败: {error_msg}\n")
            self.result_text.configure(state=tk.DISABLED)
            return
        
        Q = self.input_params['Q']
        n = self.input_params['n']
        slope_inv = self.input_params['slope_inv']
        i = 1 / slope_inv
        v_min = self.input_params['v_min']
        v_max = self.input_params['v_max']
        
        output = []
        output.append("=" * 70)
        
        # 判断是否为水力最佳断面
        is_optimal = result.get('is_optimal_section', False)
        if is_optimal:
            output.append("              矩形暗涵水力计算结果（水力最佳断面）")
        else:
            output.append("              矩形暗涵水力计算结果")
        output.append("=" * 70)
        output.append("")
        
        B = result.get('B', 0)
        H = result.get('H', 0)
        V = result.get('V_design', 0)
        velocity_ok = v_min <= V <= v_max
        fb_pct = result.get('freeboard_pct_inc', 0)
        fb_hgt = result.get('freeboard_hgt_inc', 0)
        fb_min_required = result.get('fb_min_required', 0.4)
        
        # 详细净空验证
        if H <= 3.0:
            fb_req_by_rule = max(0.4, H / 6.0)
        else:
            fb_req_by_rule = 0.5
        fb_ok = fb_pct >= 10 and fb_hgt >= fb_req_by_rule
        
        # 根据输出选项显示不同内容
        if not self.show_detail_var.get():
            # 简要输出
            output.append("【输入参数】")
            output.append(f"  设计流量 Q = {Q:.3f} m³/s")
            output.append(f"  糙率 n = {n}")
            output.append(f"  水力坡降 1/{int(slope_inv)}")
            output.append("")
            
            output.append("【断面尺寸】")
            if is_optimal:
                output.append(f"  ★ 采用水力最佳断面（β=B/h=2）")
            output.append(f"  宽度 B = {B:.2f} m")
            output.append(f"  高度 H = {H:.2f} m")
            BH_ratio = result.get('BH_ratio', 0)
            HB_ratio = result.get('HB_ratio', 0)
            output.append(f"  宽深比 β = B/h = {BH_ratio:.3f}")
            output.append(f"  高宽比 H/B = {HB_ratio:.3f}")
            output.append("")
            
            output.append("【设计流量工况】")
            output.append(f"  设计水深 h = {result.get('h_design', 0):.3f} m")
            output.append(f"  设计流速 V = {V:.3f} m/s")
            output.append(f"  净空高度 Fb = {result.get('freeboard_hgt_design', 0):.3f} m")
            output.append(f"  净空比例 = {result.get('freeboard_pct_design', 0):.1f}%")
            output.append("")
            
            output.append("【加大流量工况】")
            inc_pct = result.get('increase_percent', 0)
            manual_increase = self.input_params.get('manual_increase')
            inc_source = "(手动指定)" if manual_increase else "(自动计算)"
            output.append(f"  流量加大比例 = {inc_pct:.1f}% {inc_source}")
            output.append(f"  加大流量 Q加大 = {result.get('Q_increased', 0):.3f} m³/s")
            output.append(f"  加大水深 h加大 = {result.get('h_increased', 0):.3f} m")
            output.append(f"  加大流速 V加大 = {result.get('V_increased', 0):.3f} m/s")
            output.append(f"  净空高度 Fb加大 = {fb_hgt:.3f} m")
            output.append(f"  净空比例 = {fb_pct:.1f}%")
            output.append("")
            
            output.append("【验证结果】")
            output.append(f"  流速验证: {'✓ 通过' if velocity_ok else '✗ 未通过'}")
            output.append(f"  净空验证: {'✓ 通过' if fb_ok else '✗ 需注意'}")
            output.append("")
        else:
            # 详细输出 - 包含公式代入计算过程
            output.append("【一、输入参数】")
            output.append(f"  设计流量 Q = {Q:.3f} m³/s")
            output.append(f"  糙率 n = {n}")
            output.append(f"  水力坡降 1/{int(slope_inv)}")
            output.append("")
            
            output.append("【二、断面尺寸】")
            if is_optimal:
                output.append("  ★★★ 采用水力最佳断面 ★★★")
                output.append("  (当底宽和宽深比均留空时，自动按水力最佳断面计算)")
                output.append("  水力最佳断面宽深比 β = B/h = 2（即底宽等于2倍水深）")
                output.append("")
            output.append(f"  宽度 B = {B:.2f} m")
            output.append(f"  高度 H = {H:.2f} m")
            BH_ratio = result.get('BH_ratio', 0)
            HB_ratio = result.get('HB_ratio', 0)
            h_design = result.get('h_design', 0)
            A_total = result.get('A_total', 0)
            output.append("")
            
            output.append("  1. 宽深比计算:")
            output.append(f"     β = B / h")
            output.append(f"       = {B:.2f} / {h_design:.3f}")
            output.append(f"       = {BH_ratio:.3f}")
            if is_optimal:
                output.append(f"     (水力最佳断面目标值 β = 2.0)")
            output.append("")
            
            output.append("  2. 高宽比计算:")
            output.append(f"     H/B = {H:.2f} / {B:.2f} = {HB_ratio:.3f}")
            output.append(f"     (限值要求: H/B 或 B/H 一般不超过1.2)")
            output.append("")
            
            output.append("  3. 总断面积计算:")
            output.append(f"     A总 = B × H")
            output.append(f"        = {B:.2f} × {H:.2f}")
            output.append(f"        = {A_total:.3f} m²")
            output.append("")
            
            output.append("【三、设计流量工况】")
            A_design = result.get('A_design', 0)
            P_design = result.get('P_design', 0)
            R_hyd_design = result.get('R_hyd_design', 0)
            Q_calc = result.get('Q_calc', 0)
            fb_pct_design = result.get('freeboard_pct_design', 0)
            fb_hgt_design = result.get('freeboard_hgt_design', 0)
            output.append(f"  设计水深 h = {h_design:.3f} m")
            output.append("")
            
            output.append("  4. 过水面积计算:")
            output.append(f"     A = B × h")
            output.append(f"       = {B:.2f} × {h_design:.3f}")
            output.append(f"       = {A_design:.3f} m²")
            output.append("")
            
            output.append("  5. 湿周计算:")
            output.append(f"     χ = B + 2×h")
            output.append(f"       = {B:.2f} + 2×{h_design:.3f}")
            output.append(f"       = {B:.2f} + {2*h_design:.3f}")
            output.append(f"       = {P_design:.3f} m")
            output.append("")
            
            output.append("  6. 水力半径计算:")
            output.append(f"     R = A / χ")
            output.append(f"       = {A_design:.3f} / {P_design:.3f}")
            output.append(f"       = {R_hyd_design:.3f} m")
            output.append("")
            
            output.append("  7. 设计流速计算 (曼宁公式):")
            output.append(f"     V = (1/n) × R^(2/3) × i^(1/2)")
            output.append(f"       = (1/{n}) × {R_hyd_design:.3f}^(2/3) × {i:.6f}^(1/2)")
            output.append(f"       = {1/n:.2f} × {R_hyd_design**(2/3):.4f} × {math.sqrt(i):.6f}")
            output.append(f"       = {V:.3f} m/s")
            output.append("")
            
            output.append("  8. 计算流量验证:")
            output.append(f"     Q计算 = A × V")
            output.append(f"          = {A_design:.3f} × {V:.3f}")
            output.append(f"          = {Q_calc:.3f} m³/s")
            output.append("")
            
            output.append("  9. 净空高度计算:")
            output.append(f"      Fb = H - h")
            output.append(f"         = {H:.2f} - {h_design:.3f}")
            output.append(f"         = {fb_hgt_design:.3f} m")
            output.append("")
            
            output.append("  10. 净空面积比计算:")
            output.append(f"      PA = (H - h) / H × 100%")
            output.append(f"         = ({H:.2f} - {h_design:.3f}) / {H:.2f} × 100%")
            output.append(f"         = {fb_pct_design:.1f}%")
            output.append("")
            
            output.append("【四、加大流量工况】")
            inc_pct = result.get('increase_percent', 0)
            Q_加大 = result.get('Q_increased', 0)
            h_加大 = result.get('h_increased', 0)
            V_加大 = result.get('V_increased', 0)
            
            manual_increase = self.input_params.get('manual_increase')
            inc_source = "(手动指定)" if manual_increase else "(自动计算)"
            
            output.append(f"  流量加大比例 = {inc_pct:.1f}% {inc_source}")
            output.append("")
            
            output.append("  11. 加大流量计算:")
            output.append(f"      Q加大 = Q × (1 + {inc_pct:.1f}%)")
            output.append(f"           = {Q:.3f} × {1 + inc_pct/100:.3f}")
            output.append(f"           = {Q_加大:.3f} m³/s")
            output.append("")
            
            output.append(f"  12. 加大水深计算结果:")
            output.append(f"      加大水深 h加大 = {h_加大:.3f} m")
            output.append("")
            
            # 加大流量工况下的水力参数计算
            A_加大 = B * h_加大
            χ_加大 = B + 2 * h_加大
            R_加大 = A_加大 / χ_加大 if χ_加大 > 0 else 0
            
            output.append("  13. 加大流量工况过水面积:")
            output.append(f"      A加大 = B × h加大")
            output.append(f"           = {B:.2f} × {h_加大:.3f}")
            output.append(f"           = {A_加大:.3f} m²")
            output.append("")
            
            output.append("  14. 加大流量工况湿周:")
            output.append(f"      χ加大 = B + 2×h加大")
            output.append(f"           = {B:.2f} + 2×{h_加大:.3f}")
            output.append(f"           = {χ_加大:.3f} m")
            output.append("")
            
            output.append("  15. 加大流量工况水力半径:")
            output.append(f"      R加大 = A加大 / χ加大")
            output.append(f"           = {A_加大:.3f} / {χ_加大:.3f}")
            output.append(f"           = {R_加大:.3f} m")
            output.append("")
            
            output.append("  16. 加大流量工况流速 (曼宁公式):")
            output.append(f"      V加大 = (1/n) × R^(2/3) × i^(1/2)")
            output.append(f"           = (1/{n}) × {R_加大:.3f}^(2/3) × {i:.6f}^(1/2)")
            output.append(f"           = {1/n:.2f} × {R_加大**(2/3):.4f} × {math.sqrt(i):.6f}")
            output.append(f"           = {V_加大:.3f} m/s")
            output.append("")
            
            output.append("  17. 加大流量工况净空:")
            output.append(f"      净空高度 Fb加大 = H - h加大 = {H:.2f} - {h_加大:.3f} = {fb_hgt:.3f} m")
            output.append(f"      净空面积 PA加大 = (H - h加大) / H × 100% = {fb_pct:.1f}%")
            output.append("")
            
            # 详细净空验证过程
            output.append("【五、净空验证】")
            output.append("")
            output.append("  根据《灌溉与排水工程设计标准》 GB 50288-2018要求：")
            output.append("  1. 净空面积要求：应为涵洞断面总面积的10%~30%")
            output.append("  2. 净空高度要求：")
            output.append("     - 在任何情况下，净空高度均不得小于0.4m")
            if H <= 3.0:
                output.append(f"     - 当涵洞内侧高度H≤3m时，净空高度应≥H/6")
                output.append(f"       H = {H:.2f}m ≤ 3m")
                output.append(f"       H/6 = {H/6:.3f}m")
                output.append(f"       要求净空高度≥max(0.4, {H/6:.3f}) = {fb_req_by_rule:.3f}m")
            else:
                output.append(f"     - 当涵洞内侧高度H>3m时，净空高度应≥0.5m")
                output.append(f"       H = {H:.2f}m > 3m")
                output.append(f"       要求净空高度≥0.5m")
            output.append("")
            
            output.append("  净空验证结果（加大流量工况）：")
            # 净空面积验证
            fb_area_ok = 10.0 <= fb_pct <= 30.0
            output.append(f"  a) 净空面积验证: 10% ≤ {fb_pct:.1f}% ≤ 30%")
            output.append(f"     → {'通过 ✓' if fb_area_ok else '未通过 ✗'}")
            
            # 净空高度验证
            fb_hgt_ok = fb_hgt >= fb_req_by_rule
            output.append(f"  b) 净空高度验证: {fb_hgt:.3f}m ≥ {fb_req_by_rule:.3f}m")
            output.append(f"     → {'通过 ✓' if fb_hgt_ok else '未通过 ✗'}")
            output.append("")
            
            output.append("【六、综合验证】")
            output.append(f"  1. 流速验证: {v_min} ≤ {V:.3f} ≤ {v_max} → {'通过 ✓' if velocity_ok else '未通过 ✗'}")
            output.append(f"  2. 净空面积验证: → {'通过 ✓' if fb_area_ok else '未通过 ✗'}")
            output.append(f"  3. 净空高度验证: → {'通过 ✓' if fb_hgt_ok else '未通过 ✗'}")
            output.append("")
        
        output.append("=" * 70)
        if is_optimal:
            output.append(f"  计算完成: {'成功 ✓' if result['success'] else '失败 ✗'} (水力最佳断面)")
        else:
            output.append(f"  计算完成: {'成功 ✓' if result['success'] else '失败 ✗'}")
        output.append("=" * 70)
        
        self.result_text.insert(tk.END, "\n".join(output))
        self.result_text.configure(state=tk.DISABLED)
    
    def _update_section_plot(self, result):
        """更新断面图"""
        self.section_fig.clear()
        
        if not result['success']:
            return
        
        ax = self.section_fig.add_subplot(111)
        
        B = result.get('B', 2)
        H = result.get('H', 1)
        h_water = result.get('h_design', 0)
        Q = self.input_params['Q']
        V = result.get('V_design', 0)
        
        ax.plot([-B/2, -B/2], [0, H], 'k-', linewidth=2)
        ax.plot([B/2, B/2], [0, H], 'k-', linewidth=2)
        ax.plot([-B/2, B/2], [0, 0], 'k-', linewidth=2)
        ax.plot([-B/2, B/2], [H, H], 'k-', linewidth=2)
        
        if h_water > 0:
            water_x = [-B/2, -B/2, B/2, B/2]
            water_y = [0, h_water, h_water, 0]
            ax.fill(water_x, water_y, color='lightblue', alpha=0.7)
            ax.plot([-B/2, B/2], [h_water, h_water], 'b-', linewidth=1.5)
        
        # 添加尺寸标注
        ax.annotate('', xy=(B/2, -0.1*H), xytext=(-B/2, -0.1*H),
                   arrowprops=dict(arrowstyle='<->', color='gray', lw=1.5))
        ax.text(0, -0.2*H, f'B={B:.2f}m', ha='center', fontsize=9, color='gray')
        
        ax.annotate('', xy=(B/2+0.1*B, H), xytext=(B/2+0.1*B, 0),
                   arrowprops=dict(arrowstyle='<->', color='purple', lw=1.5))
        ax.text(B/2+0.15*B, H/2, f'H={H:.2f}m', ha='left', fontsize=9, color='purple', rotation=90, va='center')
        
        if h_water > 0:
            ax.annotate('', xy=(-B/2-0.1*B, h_water), xytext=(-B/2-0.1*B, 0),
                       arrowprops=dict(arrowstyle='<->', color='blue', lw=1.5))
            ax.text(-B/2-0.15*B, h_water/2, f'h={h_water:.2f}m', ha='right', fontsize=9, color='blue', rotation=90, va='center')
        
        ax.set_xlim(-B*0.9, B*0.9)
        ax.set_ylim(-H*0.35, H*1.2)
        ax.set_aspect('equal')
        ax.set_title(f'矩形暗涵断面\nQ={Q:.2f}m$^3$/s, V={V:.2f}m/s', fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.axhline(y=0, color='brown', linewidth=3)
        
        self.section_fig.tight_layout()
        self.section_canvas.draw()
    
    def _clear(self):
        """清空"""
        self._show_initial_help()
        if VIZ_MODULE_LOADED:
            self.section_fig.clear()
            self.section_canvas.draw()
    
    def _export_charts(self):
        """导出图表"""
        if not hasattr(self, 'current_result') or not self.current_result or not self.current_result['success']:
            messagebox.showwarning("警告", "请先进行计算")
            return
        
        folder = filedialog.askdirectory(title="选择保存目录")
        if not folder:
            return
        
        try:
            self.section_fig.savefig(os.path.join(folder, '矩形暗涵断面图.png'), dpi=150, bbox_inches='tight')
            messagebox.showinfo("成功", f"图表已保存到: {folder}")
        except Exception as e:
            messagebox.showerror("错误", f"保存失败: {str(e)}")
    
    def _export_report(self):
        """导出报告"""
        if not hasattr(self, 'current_result') or not self.current_result or not self.current_result['success']:
            messagebox.showwarning("警告", "请先进行计算")
            return
        
        filepath = filedialog.asksaveasfilename(
            title="保存报告",
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")]
        )
        if not filepath:
            return
        
        try:
            self.result_text.configure(state=tk.NORMAL)
            content = self.result_text.get(1.0, tk.END)
            self.result_text.configure(state=tk.DISABLED)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            
            messagebox.showinfo("成功", f"报告已保存到: {filepath}")
        except Exception as e:
            messagebox.showerror("错误", f"保存失败: {str(e)}")


# ============================================================
# 导入批量计算模块
# ============================================================

try:
    from 多渠段批量计算 import BatchCalculationPanel
    BATCH_MODULE_LOADED = True
except ImportError as e:
    BATCH_MODULE_LOADED = False
    BATCH_IMPORT_ERROR = str(e)


# ============================================================
# 主应用程序
# ============================================================

class MainApplication(tk.Tk):
    """渠系建筑物断面尺寸计算程序主应用"""
    
    def __init__(self):
        super().__init__()
        
        self.title("渠系建筑物断面尺寸计算程序")
        self.geometry("1300x850")
        self.minsize(1100, 750)
        
        try:
            self.iconbitmap("icon.ico")
        except:
            pass
        
        # 初始化字体管理
        self._init_fonts()
        
        # 检查依赖
        error_msgs = []
        if not MINGQU_MODULE_LOADED:
            error_msgs.append(f"明渠模块: {MINGQU_IMPORT_ERROR}")
        if not DUCAO_MODULE_LOADED:
            error_msgs.append(f"渡槽模块: {DUCAO_IMPORT_ERROR}")
        if not SUIDONG_MODULE_LOADED:
            error_msgs.append(f"隧洞模块: {SUIDONG_IMPORT_ERROR}")
        
        # 至少需要一个模块可用
        modules_ok = MINGQU_MODULE_LOADED or DUCAO_MODULE_LOADED or SUIDONG_MODULE_LOADED
        if not modules_ok:
            messagebox.showerror("错误", "所有计算模块加载失败:\n" + "\n".join(error_msgs))
            self.destroy()
            return
        
        if not VIZ_MODULE_LOADED:
            messagebox.showwarning("警告", f"可视化模块加载失败: {VIZ_IMPORT_ERROR}\n将仅提供基本计算功能")
        
        # 注意：先创建状态栏，再创建UI，确保状态栏在底部可见
        self._create_status_bar()
        self._create_ui()
    
    def _init_fonts(self):
        """初始化字体管理"""
        global CURRENT_FONT_SIZE
        
        # 创建命名字体对象
        font_config = get_font_config()
        self.default_font = tkfont.Font(family="Microsoft YaHei", size=font_config["default"])
        self.small_font = tkfont.Font(family="Microsoft YaHei", size=font_config["small"])
        self.title_font = tkfont.Font(family="Microsoft YaHei", size=font_config["title"], weight="bold")
        self.result_font = tkfont.Font(family="Consolas", size=font_config["result"])
        
        # 配置ttk样式
        self.style = ttk.Style()
        self._apply_font_style()
    
    def _apply_font_style(self):
        """应用字体样式到ttk组件"""
        font_config = get_font_config()
        
        # 更新命名字体
        self.default_font.configure(size=font_config["default"])
        self.small_font.configure(size=font_config["small"])
        self.title_font.configure(size=font_config["title"])
        self.result_font.configure(size=font_config["result"])
        
        # 配置ttk组件样式
        self.style.configure(".", font=("Microsoft YaHei", font_config["default"]))
        self.style.configure("TLabel", font=("Microsoft YaHei", font_config["default"]))
        self.style.configure("TButton", font=("Microsoft YaHei", font_config["default"]))
        self.style.configure("TEntry", font=("Microsoft YaHei", font_config["default"]))
        self.style.configure("TCombobox", font=("Microsoft YaHei", font_config["default"]))
        self.style.configure("TCheckbutton", font=("Microsoft YaHei", font_config["default"]))
        self.style.configure("TRadiobutton", font=("Microsoft YaHei", font_config["default"]))
        self.style.configure("TLabelframe.Label", font=("Microsoft YaHei", font_config["default"]))
        self.style.configure("TNotebook.Tab", font=("Microsoft YaHei", font_config["default"]), padding=[10, 5])
        self.style.configure("Treeview", font=("Microsoft YaHei", font_config["default"]), rowheight=int(font_config["default"] * 2.2))
        self.style.configure("Treeview.Heading", font=("Microsoft YaHei", font_config["default"], "bold"))
        
        # 配置小字体提示样式
        self.style.configure("Small.TLabel", font=("Microsoft YaHei", font_config["small"]), foreground="black")
    
    def _change_font_size(self, size_name):
        """切换字体大小"""
        global CURRENT_FONT_SIZE
        if size_name in FONT_SIZE_PRESETS:
            CURRENT_FONT_SIZE = size_name
            self._apply_font_style()
            # 更新所有子面板
            self._refresh_all_panels()
    
    def _create_ui(self):
        """创建UI"""
        # 主Notebook用于切换不同计算模块
        self.main_notebook = ttk.Notebook(self)
        self.main_notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 明渠模块（统一支持矩形、梯形、圆形断面）
        if MINGQU_MODULE_LOADED:
            self.mingqu_panel = OpenChannelPanel(self.main_notebook)
            self.main_notebook.add(self.mingqu_panel, text="  明渠  ")

        # 渡槽模块
        if DUCAO_MODULE_LOADED:
            self.aqueduct_panel = AqueductPanel(self.main_notebook)
            self.main_notebook.add(self.aqueduct_panel, text="  渡槽  ")
        
        # 隧洞模块
        if SUIDONG_MODULE_LOADED:
            self.tunnel_panel = TunnelPanel(self.main_notebook)
            self.main_notebook.add(self.tunnel_panel, text="  隧洞  ")
        
        # 矩形暗涵模块
        if SUIDONG_MODULE_LOADED:
            self.culvert_panel = RectangularCulvertPanel(self.main_notebook)
            self.main_notebook.add(self.culvert_panel, text="  矩形暗涵  ")
        

        # 多流量段批量计算模块
        if BATCH_MODULE_LOADED:
            self.batch_panel = BatchCalculationPanel(self.main_notebook)
            self.main_notebook.add(self.batch_panel, text="  多流量段批量计算  ")
    
    def _create_status_bar(self):
        """创建状态栏"""
        status_frame = ttk.Frame(self)
        status_frame.pack(side=tk.BOTTOM, fill=tk.X)
        
        modules_loaded = []
        if MINGQU_MODULE_LOADED:
            modules_loaded.append("明渠")
        if DUCAO_MODULE_LOADED:
            modules_loaded.append("渡槽")
        if SUIDONG_MODULE_LOADED:
            modules_loaded.append("隧洞")
            modules_loaded.append("矩形暗涵")

        
        status_text = f"已加载模块: {', '.join(modules_loaded)}" if modules_loaded else "无可用模块"
        if VIZ_MODULE_LOADED:
            status_text += " | 可视化: 已启用"
        else:
            status_text += " | 可视化: 未启用"
        
        # 左侧状态信息（先pack，但不expand）
        self.status_label = ttk.Label(status_frame, text=status_text, relief=tk.SUNKEN, 
                                      anchor=tk.W, padding=(5, 2))
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # 右侧控件区域（使用固定宽度的frame）
        right_frame = ttk.Frame(status_frame)
        right_frame.pack(side=tk.RIGHT)
        
        # 版权信息
        author_info = "四川水发设计公司   刘思杰  18380433746  版权所有"
        ttk.Label(right_frame, text=author_info, relief=tk.SUNKEN,
                  anchor=tk.E, padding=(5, 2)).pack(side=tk.LEFT, padx=2)
        
        # 版本号
        ttk.Label(right_frame, text="V2.0", relief=tk.SUNKEN,
                  anchor=tk.E, padding=(5, 2)).pack(side=tk.LEFT, padx=2)
        
        # 分隔符
        ttk.Separator(right_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)
        
        # 字体大小选择器
        ttk.Label(right_frame, text="字体:").pack(side=tk.LEFT)
        self.font_size_var = tk.StringVar(value=CURRENT_FONT_SIZE)
        font_combo = ttk.Combobox(right_frame, textvariable=self.font_size_var, 
                                  values=list(FONT_SIZE_PRESETS.keys()), 
                                  width=6, state="readonly")
        font_combo.pack(side=tk.LEFT, padx=2)
        font_combo.bind("<<ComboboxSelected>>", lambda e: self._change_font_size(self.font_size_var.get()))
    
    def _refresh_all_panels(self):
        """刷新所有面板以应用新字体"""
        # 更新结果文本框字体
        font_config = get_font_config()
        result_font = ("Consolas", font_config["result"])
        
        # 遍历所有面板更新结果文本框
        panels = []
        if hasattr(self, 'mingqu_panel'):
            panels.append(self.mingqu_panel)
        if hasattr(self, 'aqueduct_panel'):
            panels.append(self.aqueduct_panel)
        if hasattr(self, 'tunnel_panel'):
            panels.append(self.tunnel_panel)
        if hasattr(self, 'culvert_panel'):
            panels.append(self.culvert_panel)
        
        for panel in panels:
            if hasattr(panel, 'result_text'):
                panel.result_text.configure(font=result_font)


def main():
    """主函数"""
    app = MainApplication()
    app.mainloop()


if __name__ == "__main__":
    main()
