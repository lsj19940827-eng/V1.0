# -*- coding: utf-8 -*-
"""
基础设置区组件

提供项目基础参数的输入界面。
"""

import tkinter as tk
from tkinter import ttk
from typing import Optional, Callable, List, Tuple
import sys
import os

# 添加父目录到路径以支持相对导入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.data_models import ProjectSettings
from config.constants import (
    DEFAULT_ROUGHNESS, DEFAULT_TURN_RADIUS, 
    CHANNEL_LEVEL_OPTIONS, DEFAULT_CHANNEL_LEVEL,
    TRANSITION_FORM_OPTIONS
)


def get_flow_increase_percent(design_Q: float) -> float:
    """
    根据设计流量查找加大流量百分比
    
    参照《灌溉与排水工程设计标准》规定：
    - Q < 1 m³/s: 30%
    - 1 <= Q < 5 m³/s: 25%
    - 5 <= Q < 20 m³/s: 20%
    - 20 <= Q < 50 m³/s: 15%
    - 50 <= Q < 100 m³/s: 10%
    - Q >= 100 m³/s: 5%
    
    参数:
        design_Q: 设计流量 (m³/s)
    
    返回:
        加大百分比 (如30表示30%)
    """
    if design_Q <= 0:
        return 0.0
    elif design_Q < 1:
        return 30.0
    elif design_Q < 5:
        return 25.0
    elif design_Q < 20:
        return 20.0
    elif design_Q < 50:
        return 15.0
    elif design_Q < 100:
        return 10.0
    elif design_Q <= 300:
        return 5.0
    else:
        return 5.0


def calculate_max_flow(design_Q: float) -> float:
    """
    根据设计流量计算加大流量
    
    参数:
        design_Q: 设计流量 (m³/s)
    
    返回:
        加大流量 (m³/s)
    """
    if design_Q <= 0:
        return 0.0
    increase_percent = get_flow_increase_percent(design_Q)
    return round(design_Q * (1 + increase_percent / 100), 3)


def format_station_display(value: float) -> str:
    """
    将桩号数值格式化为标准显示格式（如 12+111.222）
    
    参数:
        value: 桩号数值（米），如 12111.222
    
    返回:
        格式化后的桩号字符串，如 "12+111.222"
    """
    if value < 0:
        value = abs(value)
    
    # 分离公里数和米数
    km = int(value // 1000)
    meters = value % 1000
    
    # 格式化为 km+xxx.xxx 格式，米数部分保持3位整数+3位小数
    return f"{km}+{meters:07.3f}"


def parse_station_input(input_str: str) -> float:
    """
    解析桩号输入字符串为数值
    
    支持两种输入格式：
    1. 纯数字：12111.222 -> 12111.222
    2. 带加号格式：12+111.222 -> 12111.222
    
    参数:
        input_str: 输入字符串
    
    返回:
        桩号数值（米）
    """
    input_str = input_str.strip()
    if not input_str:
        return 0.0
    
    # 检查是否包含加号
    if '+' in input_str:
        parts = input_str.split('+')
        if len(parts) == 2:
            try:
                km = int(parts[0])
                meters = float(parts[1])
                return km * 1000 + meters
            except ValueError:
                pass
    
    # 尝试直接解析为数字
    try:
        return float(input_str)
    except ValueError:
        return 0.0


class BasicSettingsPanel(ttk.LabelFrame):
    """
    基础设置面板
    
    包含渠道名称、流量、水位、转弯半径、糙率等参数的输入。
    """
    
    def __init__(self, parent: tk.Widget, on_change: Optional[Callable] = None):
        """
        初始化基础设置面板
        
        Args:
            parent: 父容器
            on_change: 参数变化时的回调函数
        """
        super().__init__(parent, text="基础设置", padding=(10, 5))
        
        self.on_change = on_change
        
        # 创建变量
        self._create_variables()
        
        # 创建界面
        self._create_widgets()
        
        # 延迟格式化初始值
        self.after(100, self._format_start_station_display)
    
    def _create_variables(self):
        """创建Tkinter变量"""
        self.var_channel_name = tk.StringVar(value="")
        self.var_channel_level = tk.StringVar(value=DEFAULT_CHANNEL_LEVEL)
        self.var_start_station = tk.StringVar(value="0")
        # 多流量段支持：设计流量和加大流量均支持逗号分隔的多值输入
        self.var_design_flow = tk.StringVar(value="")
        self.var_max_flow = tk.StringVar(value="")
        self.var_start_water_level = tk.StringVar(value="")
        self.var_turn_radius = tk.StringVar(value="")
        
        # 渐变段形式
        self.var_transition_inlet_form = tk.StringVar(value="曲线形反弯扭曲面")
        self.var_transition_outlet_form = tk.StringVar(value="曲线形反弯扭曲面")
        self.var_open_channel_transition_form = tk.StringVar(value="曲线形反弯扭曲面")  # 明渠渐变段形式
        
        # 绑定设计流量变化时自动计算加大流量
        self.var_design_flow.trace_add('write', self._on_design_flow_change)
        
        # 绑定转弯半径变化时同步更新表格
        self.var_turn_radius.trace_add('write', self._on_turn_radius_change)
        
        # 绑定起始桩号变化时同步更新表格
        self.var_start_station.trace_add('write', self._on_start_station_change)
        
        # 转弯半径变化回调（由外部设置）
        self._turn_radius_change_callback = None
        
        # 起始桩号变化回调（由外部设置）
        self._start_station_change_callback = None
    
    def _create_widgets(self):
        """创建界面组件"""
        # 第一行：渠道名称、渠道级别、起始桩号
        row1 = ttk.Frame(self)
        row1.pack(fill=tk.X, pady=2)
        
        # 渠道名称
        ttk.Label(row1, text="渠道名称:").pack(side=tk.LEFT, padx=(0, 5))
        entry_name = ttk.Entry(row1, textvariable=self.var_channel_name, width=12)
        entry_name.pack(side=tk.LEFT, padx=(0, 10))
        
        # 渠道级别
        ttk.Label(row1, text="渠道级别:").pack(side=tk.LEFT, padx=(0, 5))
        combo_level = ttk.Combobox(row1, textvariable=self.var_channel_level, 
                                   values=CHANNEL_LEVEL_OPTIONS, width=8, state="readonly")
        combo_level.pack(side=tk.LEFT, padx=(0, 10))
        
        # 起始桩号
        ttk.Label(row1, text="起始桩号 (m):").pack(side=tk.LEFT, padx=(0, 5))
        self._entry_start_station = ttk.Entry(row1, textvariable=self.var_start_station, width=15)
        self._entry_start_station.pack(side=tk.LEFT, padx=(0, 3))
        
        # 起始桩号输入提示（蓝色高对比度）
        ttk.Label(row1, text="(如12+111.222,输入12111.222)", 
                  foreground='#0066CC', font=('', 8)).pack(side=tk.LEFT, padx=(0, 10))
        
        # 绑定焦点事件：失去焦点时自动格式化显示
        self._entry_start_station.bind('<FocusOut>', self._on_start_station_focus_out)
        self._entry_start_station.bind('<FocusIn>', self._on_start_station_focus_in)
        # 绑定Enter键：按Enter键也触发格式化
        self._entry_start_station.bind('<Return>', self._on_start_station_enter)
        self._entry_start_station.bind('<KP_Enter>', self._on_start_station_enter)
        
        # 第二行：多流量段设计流量和加大流量
        row2 = ttk.Frame(self)
        row2.pack(fill=tk.X, pady=2)
        
        # 设计流量（支持多流量段）
        ttk.Label(row2, text="设计流量Q (m³/s):").pack(side=tk.LEFT, padx=(0, 5))
        entry_q = ttk.Entry(row2, textvariable=self.var_design_flow, width=25)
        entry_q.pack(side=tk.LEFT, padx=(0, 10))
        
        # 加大流量（支持多流量段）
        ttk.Label(row2, text="加大流量Qmax (m³/s):").pack(side=tk.LEFT, padx=(0, 5))
        entry_qmax = ttk.Entry(row2, textvariable=self.var_max_flow, width=25)
        entry_qmax.pack(side=tk.LEFT, padx=(0, 5))
        
        # 提示标签
        ttk.Label(row2, text="(多流量段用逗号分隔)", 
                  foreground='gray').pack(side=tk.LEFT, padx=(5, 0))
        
        # 第三行：起始水位、转弯半径、糙率
        row3 = ttk.Frame(self)
        row3.pack(fill=tk.X, pady=2)
        
        # 渠道起始水位
        ttk.Label(row3, text="渠道起始水位 (m):").pack(side=tk.LEFT, padx=(0, 5))
        entry_wl = ttk.Entry(row3, textvariable=self.var_start_water_level, width=12)
        entry_wl.pack(side=tk.LEFT, padx=(0, 20))
        
        # 转弯半径
        ttk.Label(row3, text="转弯半径R (m):").pack(side=tk.LEFT, padx=(0, 5))
        entry_r = ttk.Entry(row3, textvariable=self.var_turn_radius, width=12)
        entry_r.pack(side=tk.LEFT, padx=(0, 3))
        
        # 转弯半径提示图标（带tooltip）
        self._turn_radius_tip_label = ttk.Label(row3, text="?", foreground="gray", 
                                                 cursor="question_arrow", font=("", 8))
        self._turn_radius_tip_label.pack(side=tk.LEFT, padx=(0, 3))
        self._create_turn_radius_tooltip()
        
        # 自动计算转弯半径按钮
        self._auto_calc_turn_radius_btn = ttk.Button(row3, text="自动", width=4,
                                                      command=self._on_auto_calc_turn_radius)
        self._auto_calc_turn_radius_btn.pack(side=tk.LEFT, padx=(0, 15))
        
        # 自动计算回调函数（由外部设置）
        self._auto_calc_turn_radius_callback = None
        
        # 第四行：渐变段形式设置
        row4 = ttk.Frame(self)
        row4.pack(fill=tk.X, pady=2)
        
        # 进口渐变段形式
        ttk.Label(row4, text="进口渐变段形式:").pack(side=tk.LEFT, padx=(0, 5))
        combo_inlet_form = ttk.Combobox(row4, textvariable=self.var_transition_inlet_form,
                                        values=TRANSITION_FORM_OPTIONS, width=18, state="readonly")
        combo_inlet_form.pack(side=tk.LEFT, padx=(0, 15))
        
        # 出口渐变段形式
        ttk.Label(row4, text="出口渐变段形式:").pack(side=tk.LEFT, padx=(0, 5))
        combo_outlet_form = ttk.Combobox(row4, textvariable=self.var_transition_outlet_form,
                                         values=TRANSITION_FORM_OPTIONS, width=18, state="readonly")
        combo_outlet_form.pack(side=tk.LEFT, padx=(0, 15))
        
        # 明渠渐变段形式（例如：梯形-矩形）
        ttk.Label(row4, text="明渠渐变段形式:").pack(side=tk.LEFT, padx=(0, 5))
        combo_open_channel_form = ttk.Combobox(row4, textvariable=self.var_open_channel_transition_form,
                                               values=TRANSITION_FORM_OPTIONS, width=18, state="readonly")
        combo_open_channel_form.pack(side=tk.LEFT, padx=(0, 10))
        
        # 渐变段提示
        ttk.Label(row4, text="(表K.1.2)", foreground='gray').pack(side=tk.LEFT, padx=(5, 0))
        
        # 绑定变化事件
        for var in [self.var_channel_name, self.var_channel_level, self.var_start_station,
                    self.var_design_flow, self.var_max_flow, self.var_start_water_level, 
                    self.var_turn_radius]:
            var.trace_add('write', self._on_value_change)
    
    def _create_turn_radius_tooltip(self):
        """为转弯半径创建提示tooltip"""
        tooltip_text = (
            "转弯半径取值规范（取大值原则）：\n"
            "• 隧洞：弯曲半径≥洞径(或洞宽)×5\n"
            "• 明渠：弯曲半径≥水面宽度×5\n"
            "• 渡槽：弯道半径≥连接明渠渠底宽度×5"
        )
        
        # 创建隐藏的tooltip窗口
        self._tooltip = None
        
        def show_tooltip(event):
            if self._tooltip is not None:
                return
            # 获取鼠标位置
            x = self._turn_radius_tip_label.winfo_rootx() + 20
            y = self._turn_radius_tip_label.winfo_rooty() + 20
            
            # 创建tooltip窗口
            self._tooltip = tk.Toplevel(self)
            self._tooltip.wm_overrideredirect(True)  # 无边框
            self._tooltip.wm_geometry(f"+{x}+{y}")
            
            # 创建tooltip内容
            frame = ttk.Frame(self._tooltip, relief="solid", borderwidth=1)
            frame.pack(fill=tk.BOTH, expand=True)
            label = ttk.Label(frame, text=tooltip_text, justify=tk.LEFT,
                            background="#FFFFE0", padding=(6, 4))
            label.pack()
        
        def hide_tooltip(event):
            if self._tooltip is not None:
                self._tooltip.destroy()
                self._tooltip = None
        
        # 绑定鼠标事件
        self._turn_radius_tip_label.bind("<Enter>", show_tooltip)
        self._turn_radius_tip_label.bind("<Leave>", hide_tooltip)
    
    def set_turn_radius(self, value: float) -> None:
        """设置转弯半径值"""
        if value > 0:
            self.var_turn_radius.set(f"{value:.1f}")
    
    def set_auto_calc_turn_radius_callback(self, callback: Callable) -> None:
        """设置自动计算转弯半径的回调函数"""
        self._auto_calc_turn_radius_callback = callback
    
    def _on_auto_calc_turn_radius(self):
        """点击自动计算按钮时的处理"""
        if self._auto_calc_turn_radius_callback:
            self._auto_calc_turn_radius_callback()
    
    def set_turn_radius_change_callback(self, callback: Callable) -> None:
        """设置转弯半径变化的回调函数"""
        self._turn_radius_change_callback = callback
    
    def set_start_station_change_callback(self, callback: Callable) -> None:
        """设置起始桩号变化的回调函数"""
        self._start_station_change_callback = callback
    
    def _on_turn_radius_change(self, *args):
        """转弯半径变化时的处理"""
        if self._turn_radius_change_callback:
            try:
                turn_radius = float(self.var_turn_radius.get())
                if turn_radius > 0:
                    self._turn_radius_change_callback(turn_radius)
            except (ValueError, TypeError):
                pass
    
    def _on_start_station_change(self, *args):
        """起始桩号变化时的处理"""
        if self._start_station_change_callback:
            try:
                start_station = parse_station_input(self.var_start_station.get())
                self._start_station_change_callback(start_station)
            except (ValueError, TypeError):
                pass
    
    def _on_value_change(self, *args):
        """值变化回调"""
        if self.on_change:
            self.on_change()
    
    def _on_design_flow_change(self, *args):
        """设计流量变化时自动计算加大流量"""
        # 自动计算加大流量
        self._calculate_max_flows()
    
    def _calculate_max_flows(self):
        """根据设计流量自动计算加大流量"""
        design_flows = self.parse_flow_values(self.var_design_flow.get())
        if not design_flows:
            return
        
        # 计算每个设计流量对应的加大流量
        max_flows = [calculate_max_flow(q) for q in design_flows]
        
        # 格式化输出（保留3位小数，去除尾部的0）
        max_flow_strs = []
        for q in max_flows:
            formatted = f"{q:.3f}".rstrip('0').rstrip('.')
            max_flow_strs.append(formatted)
        
        # 更新加大流量输入框
        self.var_max_flow.set(", ".join(max_flow_strs))
    
    def parse_flow_values(self, flow_str: str) -> List[float]:
        """
        解析流量字符串为浮点数列表
        
        支持逗号分隔的多流量段输入
        
        参数:
            flow_str: 流量字符串，如 "5.0, 8.0, 10.0"
        
        返回:
            流量值列表
        """
        if not flow_str or not flow_str.strip():
            return []
        
        # 支持中英文逗号
        flow_str = flow_str.replace('，', ',')
        
        flow_values = []
        for q_str in flow_str.split(','):
            q_str = q_str.strip()
            if q_str:
                try:
                    flow_values.append(float(q_str))
                except ValueError:
                    continue
        
        return flow_values
    
    def get_design_flows(self) -> List[float]:
        """获取设计流量列表"""
        return self.parse_flow_values(self.var_design_flow.get())
    
    def get_max_flows(self) -> List[float]:
        """获取加大流量列表"""
        return self.parse_flow_values(self.var_max_flow.get())
    
    def set_design_flows(self, flows: List[float]) -> None:
        """
        设置设计流量值
        
        参数:
            flows: 流量值列表
        """
        if not flows:
            self.var_design_flow.set("")
            return
        
        # 格式化输出（保留3位小数，去除尾部的0）
        flow_strs = []
        for q in flows:
            formatted = f"{q:.3f}".rstrip('0').rstrip('.')
            flow_strs.append(formatted)
        
        self.var_design_flow.set(", ".join(flow_strs))
    
    def set_max_flows(self, flows: List[float]) -> None:
        """
        设置加大流量值
        
        参数:
            flows: 流量值列表
        """
        if not flows:
            self.var_max_flow.set("")
            return
        
        # 格式化输出（保留3位小数，去除尾部的0）
        flow_strs = []
        for q in flows:
            formatted = f"{q:.3f}".rstrip('0').rstrip('.')
            flow_strs.append(formatted)
        
        self.var_max_flow.set(", ".join(flow_strs))
    
    def get_flow_for_segment(self, segment: int) -> Tuple[float, float]:
        """
        获取指定流量段的设计流量和加大流量
        
        参数:
            segment: 流量段编号（从1开始）
        
        返回:
            (设计流量, 加大流量) 元组
        """
        design_flows = self.get_design_flows()
        max_flows = self.get_max_flows()
        
        # 获取设计流量
        if 1 <= segment <= len(design_flows):
            design_q = design_flows[segment - 1]
        elif design_flows:
            design_q = design_flows[-1]  # 使用最后一个值
        else:
            design_q = 0.0
        
        # 获取加大流量
        if 1 <= segment <= len(max_flows):
            max_q = max_flows[segment - 1]
        elif max_flows:
            max_q = max_flows[-1]  # 使用最后一个值
        else:
            # 如果没有加大流量，则自动计算
            max_q = calculate_max_flow(design_q)
        
        return (design_q, max_q)
    
    def get_settings(self) -> ProjectSettings:
        """
        获取当前设置
        
        支持多流量段：design_flows 和 max_flows 为流量列表。
        同时保持向后兼容：design_flow 和 max_flow 取列表第一个值。
        
        Returns:
            ProjectSettings对象
        """
        def safe_float(value: str, default: float = 0.0) -> float:
            """安全转换为浮点数"""
            try:
                return float(value) if value.strip() else default
            except ValueError:
                return default
        
        # 解析多流量段
        design_flows = self.get_design_flows()
        max_flows = self.get_max_flows()
        
        # 向后兼容：取第一个值作为单值
        design_flow = design_flows[0] if design_flows else 0.0
        max_flow = max_flows[0] if max_flows else 0.0
        
        return ProjectSettings(
            channel_name=self.var_channel_name.get().strip(),
            channel_level=self.var_channel_level.get().strip() or DEFAULT_CHANNEL_LEVEL,
            start_station=parse_station_input(self.var_start_station.get()),
            design_flow=design_flow,
            max_flow=max_flow,
            design_flows=design_flows,
            max_flows=max_flows,
            start_water_level=safe_float(self.var_start_water_level.get()),
            turn_radius=safe_float(self.var_turn_radius.get(), DEFAULT_TURN_RADIUS),
            roughness=DEFAULT_ROUGHNESS,  # 糙率使用默认值，实际值从断面参数导入
            transition_inlet_form=self.var_transition_inlet_form.get(),
            transition_outlet_form=self.var_transition_outlet_form.get(),
            open_channel_transition_form=self.var_open_channel_transition_form.get(),
        )
    
    def set_settings(self, settings: ProjectSettings) -> None:
        """
        设置参数值
        
        支持多流量段：优先使用 design_flows 和 max_flows 列表。
        
        Args:
            settings: ProjectSettings对象
        """
        self.var_channel_name.set(settings.channel_name)
        self.var_channel_level.set(settings.channel_level or DEFAULT_CHANNEL_LEVEL)
        # 使用格式化函数设置起始桩号
        if settings.start_station:
            self.set_start_station_value(settings.start_station)
        else:
            self.var_start_station.set("0+000.000")
        
        # 设置多流量段（优先使用列表）
        if settings.design_flows:
            self.set_design_flows(settings.design_flows)
        elif settings.design_flow:
            self.var_design_flow.set(str(settings.design_flow))
        else:
            self.var_design_flow.set("")
        
        if settings.max_flows:
            self.set_max_flows(settings.max_flows)
        elif settings.max_flow:
            self.var_max_flow.set(str(settings.max_flow))
        else:
            self.var_max_flow.set("")
        
        self.var_start_water_level.set(str(settings.start_water_level) if settings.start_water_level else "")
        self.var_turn_radius.set(str(settings.turn_radius))
        
        # 设置渐变段形式
        if hasattr(settings, 'transition_inlet_form') and settings.transition_inlet_form:
            self.var_transition_inlet_form.set(settings.transition_inlet_form)
        if hasattr(settings, 'transition_outlet_form') and settings.transition_outlet_form:
            self.var_transition_outlet_form.set(settings.transition_outlet_form)
        if hasattr(settings, 'open_channel_transition_form') and settings.open_channel_transition_form:
            self.var_open_channel_transition_form.set(settings.open_channel_transition_form)
    
    def validate(self) -> tuple:
        """
        验证输入
        
        Returns:
            (is_valid, error_message)
        """
        settings = self.get_settings()
        return settings.validate()
    
    def clear(self) -> None:
        """清空所有输入"""
        self.var_channel_name.set("")
        self.var_channel_level.set(DEFAULT_CHANNEL_LEVEL)
        self.var_start_station.set("0+000.000")
        self.var_design_flow.set("")
        self.var_max_flow.set("")
        self.var_start_water_level.set("")
        self.var_turn_radius.set(str(DEFAULT_TURN_RADIUS))
    
    def _on_start_station_focus_out(self, event=None):
        """起始桩号输入框失去焦点时格式化显示"""
        self._format_start_station_display()
    
    def _on_start_station_focus_in(self, event=None):
        """起始桩号输入框获得焦点时转换为纯数字便于编辑"""
        current = self.var_start_station.get()
        value = parse_station_input(current)
        # 显示纯数字格式便于编辑
        self.var_start_station.set(str(value))
    
    def _on_start_station_enter(self, event=None):
        """起始桩号输入框按Enter键时格式化显示"""
        self._format_start_station_display()
        return "break"  # 阻止Enter键的默认行为
    
    def _format_start_station_display(self):
        """格式化起始桩号显示"""
        current = self.var_start_station.get()
        value = parse_station_input(current)
        formatted = format_station_display(value)
        self.var_start_station.set(formatted)
    
    def get_start_station_value(self) -> float:
        """获取起始桩号的数值（米）"""
        return parse_station_input(self.var_start_station.get())
    
    def set_start_station_value(self, value: float) -> None:
        """
        设置起始桩号值
        
        参数:
            value: 桩号数值（米）
        """
        formatted = format_station_display(value)
        self.var_start_station.set(formatted)
