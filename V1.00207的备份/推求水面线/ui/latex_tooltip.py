# -*- coding: utf-8 -*-
"""
LaTeX公式提示框组件

为表格表头提供鼠标悬停显示LaTeX公式的功能。
使用matplotlib渲染LaTeX公式为图片。
"""

import tkinter as tk
from tkinter import ttk
from typing import Optional, Dict
import io

try:
    import matplotlib
    matplotlib.use('Agg')  # 使用非交互式后端
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


# 列ID到公式说明的映射
COLUMN_FORMULAS: Dict[str, Dict[str, str]] = {
    "turn_angle": {
        "title": "转角计算",
        "description": "使用余弦定理计算三点形成的偏角",
        "latex": r"$\alpha = 180° - \arccos\left(\frac{a^2 + c^2 - b^2}{2ac}\right)$",
        "note": "其中: a=当前点到下一点距离, b=前一点到下一点距离, c=前一点到当前点距离"
    },
    "tangent_length": {
        "title": "切线长计算",
        "description": "根据转角和转弯半径计算切线长度",
        "latex": r"$T = R \times \tan\left(\frac{\alpha}{2}\right)$",
        "note": "其中: R=转弯半径, α=转角(弧度)"
    },
    "arc_length": {
        "title": "弧长计算",
        "description": "根据转角和转弯半径计算弧长",
        "latex": r"$L = R \times \alpha$",
        "note": "其中: R=转弯半径, α=转角(弧度)"
    },
    "curve_length": {
        "title": "弯道长度",
        "description": "弯道长度等于弧长",
        "latex": r"$L_{curve} = S_{EC} - S_{BC} = L_{arc}$",
        "note": "即EC桩号与BC桩号之差"
    },
    "straight_distance": {
        "title": "IP直线间距",
        "description": "相邻两个IP点之间的直线距离",
        "latex": r"$D = \sqrt{(X_i - X_{i-1})^2 + (Y_i - Y_{i-1})^2}$",
        "note": "使用两点间距离公式计算"
    },
    "station_ip": {
        "title": "IP点桩号",
        "description": "IP点的累计桩号",
        "latex": r"$S_{IP}(i) = S_0 + \sum_{j=1}^{i} D_j$",
        "note": "其中: S₀=起始桩号, Dⱼ=第j段的IP直线间距"
    },
    "station_BC": {
        "title": "弯前BC桩号",
        "description": "弯道起点(曲线起点)的桩号",
        "latex": r"$S_{BC} = S_{MC} - \frac{L}{2}$",
        "note": "其中: S_MC=里程MC, L=弧长"
    },
    "station_MC": {
        "title": "里程MC桩号",
        "description": "弯道中点的桩号，使用递推公式计算",
        "latex": r"$S_{MC}(i) = S_{MC}(i-1) + D_i - T_{i-1} - T_i + \frac{L_{i-1}}{2} + \frac{L_i}{2}$",
        "note": "其中: D=IP间距, T=切线长, L=弧长"
    },
    "station_EC": {
        "title": "弯末EC桩号",
        "description": "弯道终点(曲线终点)的桩号",
        "latex": r"$S_{EC} = S_{BC} + L$",
        "note": "其中: S_BC=弯前BC桩号, L=弧长"
    },
    "turn_radius": {
        "title": "转弯半径",
        "description": "弯道的圆曲线半径",
        "latex": r"$R$",
        "note": "用户输入值，影响切线长和弧长的计算"
    },
    "check_pre_curve": {
        "title": "复核弯前长度",
        "description": "检查当前弯道的起弯点(BC)是否超过了上一个IP点",
        "latex": r"$L_{pre} = L_i - T_i$",
        "note": "其中: Lᵢ=当前IP直线间距, Tᵢ=当前切线长。若为负数说明起弯点跑到了上一IP点前面，设计不合理"
    },
    "check_post_curve": {
        "title": "复核弯后长度",
        "description": "检查当前弯道的出弯点(EC)是否超过了下一个IP点",
        "latex": r"$L_{post} = L_{i+1} - T_i$",
        "note": "其中: Lᵢ₊₁=下一段IP直线间距, Tᵢ=当前切线长。若为负数说明出弯点跑到了下一IP点后面，设计不合理"
    },
    "check_total_length": {
        "title": "复核总长度（夹直线长度）",
        "description": "检查两个弯道之间是否有足够的直线缓冲段",
        "latex": r"$L_{total} = L_i - T_{i-1} - T_i$",
        "note": "其中: Lᵢ=当前IP直线间距, Tᵢ₋₁=上一切线长, Tᵢ=当前切线长。若为负数说明两弯道曲线重叠，无法施工"
    },
    "head_loss_bend": {
        "title": "弯道水头损失计算",
        "description": "弯道处水流产生二次流（螺旋流），导致动能损耗增加",
        "latex": r"$h_w = \frac{n^2 \cdot L \cdot v^2}{R^{4/3}} \cdot \frac{3}{4}\sqrt{\frac{B}{R_c}}$",
        "note": "其中: n=糙率, L=弯道长度, v=流速, R=水力半径, B=水面宽度(B=b+2mh), Rᶜ=转弯半径, 3/4=经验常数系数"
    },
    "head_loss_transition": {
        "title": "渐变段水头损失计算",
        "description": "渐变段水头损失包括局部损失和沿程损失（平均值法）",
        "latex": r"$h_{tr} = h_{j1} + h_f = \xi_1 \frac{|v_2^2 - v_1^2|}{2g} + i \cdot L$",
        "note": "其中: ξ₁=局部损失系数(表K.1.2), v₁=起始流速, v₂=末端流速, i=平均水力坡降, L=渐变段长度。双击单元格可查看详细计算过程。"
    },
    "head_loss_friction": {
        "title": "沿程水头损失计算",
        "description": "使用底坡和有效长度计算沿程水头损失",
        "latex": r"$h_f = i \times L_{eff}$",
        "note": "有效长度 = (里程MC差) - 渐变段长度 - 上一行弧长/2 - 本行弧长/2。其中 i=底坡(如1/3000)。"
    },
    "head_loss_local": {
        "title": "局部水头损失计算",
        "description": "建筑物进出口处的局部水头损失",
        "latex": r"$h_j = \zeta \frac{v^2}{2g}$",
        "note": "其中: ζ=局部损失系数(根据建筑物类型和进出口位置查表), v=流速, g=重力加速度"
    },
    "head_loss_total": {
        "title": "总水头损失",
        "description": "该节点的总水头损失（包含弯道、渐变段、沿程及其他损失）",
        "latex": r"$h_{\Sigma} = h_w + h_{tr} + h_f + h_{res} + h_{gate} + h_{sip}$",
        "note": "其中: h_w=弯道损失, h_tr=渐变段损失, h_f=沿程损失, h_res=预留水头损失, h_gate=过闸损失, h_sip=倒虹吸损失。双击单元格可查看详细计算过程。"
    },
}


class LaTeXTooltip:
    """
    LaTeX公式提示框
    
    鼠标悬停在表头时显示该列的计算公式说明。
    """
    
    def __init__(self, widget: tk.Widget):
        """
        初始化LaTeX提示框
        
        Args:
            widget: 需要绑定提示框的组件（通常是Treeview）
        """
        self.widget = widget
        self.tooltip_window: Optional[tk.Toplevel] = None
        self.current_column: Optional[str] = None
        self._after_id: Optional[str] = None
        self._show_delay = 10  # 显示延迟（毫秒）
        
        # 缓存渲染好的公式图片
        self._formula_cache: Dict[str, any] = {}
    
    def show(self, col_id: str, x: int, y: int):
        """
        显示提示框
        
        Args:
            col_id: 列ID
            x, y: 屏幕坐标
        """
        if col_id not in COLUMN_FORMULAS:
            return
        
        self.hide()
        self.current_column = col_id
        
        formula_info = COLUMN_FORMULAS[col_id]
        
        # 创建提示窗口
        self.tooltip_window = tk.Toplevel(self.widget)
        self.tooltip_window.wm_overrideredirect(True)
        self.tooltip_window.wm_attributes("-topmost", True)
        
        # 设置窗口样式
        frame = ttk.Frame(self.tooltip_window, relief="solid", borderwidth=1)
        frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        title_label = ttk.Label(frame, text=formula_info["title"], 
                                font=("Microsoft YaHei", 11, "bold"))
        title_label.pack(anchor="w", padx=10, pady=(10, 5))
        
        # 描述
        desc_label = ttk.Label(frame, text=formula_info["description"],
                               font=("Microsoft YaHei", 9))
        desc_label.pack(anchor="w", padx=10, pady=(0, 5))
        
        # 公式（使用matplotlib渲染或纯文本）
        if HAS_MATPLOTLIB and HAS_PIL:
            self._add_latex_formula(frame, formula_info["latex"])
        else:
            # 回退到纯文本显示
            latex_text = formula_info["latex"].replace("$", "")
            formula_label = ttk.Label(frame, text=latex_text,
                                     font=("Consolas", 10))
            formula_label.pack(anchor="w", padx=10, pady=5)
        
        # 备注
        note_label = ttk.Label(frame, text=formula_info["note"],
                              font=("Microsoft YaHei", 8), foreground="gray")
        note_label.pack(anchor="w", padx=10, pady=(5, 10))
        
        # 设置位置（稍微偏移避免遮挡）
        self.tooltip_window.update_idletasks()
        width = self.tooltip_window.winfo_width()
        height = self.tooltip_window.winfo_height()
        
        # 确保不超出屏幕边界
        screen_width = self.widget.winfo_screenwidth()
        screen_height = self.widget.winfo_screenheight()
        
        if x + width > screen_width:
            x = screen_width - width - 10
        if y + height > screen_height:
            y = y - height - 30
        
        self.tooltip_window.wm_geometry(f"+{x}+{y + 25}")
    
    def _add_latex_formula(self, parent: ttk.Frame, latex: str):
        """
        使用matplotlib渲染LaTeX公式并添加到父容器
        
        Args:
            parent: 父容器
            latex: LaTeX公式字符串
        """
        # 检查缓存
        if latex in self._formula_cache:
            img = self._formula_cache[latex]
        else:
            try:
                # 创建matplotlib图形
                fig = plt.figure(figsize=(4, 0.6), dpi=100)
                fig.patch.set_facecolor('white')
                
                # 渲染LaTeX
                fig.text(0.5, 0.5, latex, fontsize=12, ha='center', va='center',
                        transform=fig.transFigure)
                
                # 保存为图片
                buf = io.BytesIO()
                fig.savefig(buf, format='png', bbox_inches='tight', 
                           pad_inches=0.1, facecolor='white', edgecolor='none')
                buf.seek(0)
                plt.close(fig)
                
                # 转换为PhotoImage
                pil_img = Image.open(buf)
                img = ImageTk.PhotoImage(pil_img)
                
                # 缓存
                self._formula_cache[latex] = img
            except Exception as e:
                # 渲染失败，使用纯文本
                latex_text = latex.replace("$", "")
                formula_label = ttk.Label(parent, text=latex_text,
                                         font=("Consolas", 10))
                formula_label.pack(anchor="w", padx=10, pady=5)
                return
        
        # 显示图片
        label = tk.Label(parent, image=img, bg="white")
        label.image = img  # 保持引用防止被垃圾回收
        label.pack(anchor="w", padx=10, pady=5)
    
    def hide(self):
        """隐藏提示框"""
        if self._after_id:
            self.widget.after_cancel(self._after_id)
            self._after_id = None
        
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None
        
        self.current_column = None
    
    def schedule_show(self, col_id: str, x: int, y: int):
        """
        延迟显示提示框
        
        Args:
            col_id: 列ID
            x, y: 屏幕坐标
        """
        # 取消之前的延迟显示
        if self._after_id:
            self.widget.after_cancel(self._after_id)
        
        # 如果当前已显示相同列的提示，不需要重新显示
        if self.current_column == col_id and self.tooltip_window:
            return
        
        # 设置延迟显示
        self._after_id = self.widget.after(
            self._show_delay, 
            lambda: self.show(col_id, x, y)
        )


class SheetHeaderTooltip:
    """
    tksheet表头提示框管理器
    
    监听鼠标在表头上的移动，显示对应列的公式提示。
    """
    
    def __init__(self, sheet, columns: list):
        """
        初始化表头提示框管理器
        
        Args:
            sheet: tksheet.Sheet组件
            columns: 列定义列表 [{"id": ..., "text": ...}, ...]
        """
        self.sheet = sheet
        self.columns = columns
        self.tooltip = LaTeXTooltip(sheet)
        
        # 绑定事件到 ColumnHeaders 画布
        # tksheet.CH 是 ColumnHeaders 画布组件
        if hasattr(self.sheet, 'CH'):
            self.sheet.CH.bind("<Motion>", self._on_motion, add="+")
            self.sheet.CH.bind("<Leave>", self._on_leave, add="+")
    
    def _on_motion(self, event):
        """鼠标移动事件处理"""
        # 使用 identify_column 获取列索引
        # 注意：tksheet 的 identify_column 需要传入 event
        col_idx = self.sheet.identify_column(event)
        
        if col_idx is not None and 0 <= col_idx < len(self.columns):
            col_id = self.columns[col_idx]["id"]
            
            # 获取屏幕坐标
            x = event.x_root
            y = event.y_root
            
            # 延迟显示提示框
            self.tooltip.schedule_show(col_id, x, y)
        else:
            self.tooltip.hide()
    
    def _on_leave(self, event):
        """鼠标离开事件处理"""
        self.tooltip.hide()
