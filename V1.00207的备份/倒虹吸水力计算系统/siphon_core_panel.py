# -*- coding: utf-8 -*-
"""
倒虹吸水力计算核心面板
可嵌入到任何容器中使用（Notebook标签页、独立窗口等）
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import math
import os
from typing import List, Optional, Dict, Any, Callable

from siphon_models import (
    GlobalParameters, StructureSegment, CalculationResult,
    SegmentType, SegmentDirection, GradientType, TrashRackBarShape, TrashRackParams, 
    InletOutletShape, INLET_SHAPE_COEFFICIENTS,
    LongitudinalNode, PlanFeaturePoint, TurnType
)
from siphon_coefficients import CoefficientService
from dxf_parser import DxfParser
from siphon_hydraulics import HydraulicCore

# 尝试导入PIL，如果失败则禁用图片功能
try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


class SiphonCorePanel(ttk.Frame):
    """倒虹吸水力计算核心面板 - 可嵌入任何容器"""
    
    VERSION = "1.0.0"
    
    def __init__(self, parent, siphon_name: str = "", on_result_callback: Callable = None):
        """
        初始化核心面板
        
        Args:
            parent: 父容器（可以是Tk、Toplevel、Frame、Notebook等）
            siphon_name: 倒虹吸名称（用于标识和显示）
            on_result_callback: 计算完成回调函数，签名: callback(result: CalculationResult)
        """
        super().__init__(parent)
        
        self.siphon_name = siphon_name
        self.on_result_callback = on_result_callback
        
        # 查找顶级窗口用于对话框
        self._dialog_parent = self._find_toplevel_parent()
        
        # 数据存储
        self.segments: List[StructureSegment] = []
        self.plan_segments: List[StructureSegment] = []  # 平面段（从推求水面线自动提取）
        self.plan_total_length: float = 0.0               # 平面总水平长度
        self.plan_feature_points: List[PlanFeaturePoint] = []  # 平面IP特征点（三维空间合并用）
        self.longitudinal_nodes: List[LongitudinalNode] = []   # 纵断面变坡点（从DXF导入）
        self.calculation_result: Optional[CalculationResult] = None
        self.show_detailed_process = tk.BooleanVar(value=True)
        
        # 出口渐变段始端流速用户修改标志
        self._v_channel_out_user_modified = False
        
        # 创建界面
        self._create_ui()
        
        # 初始化默认结构段
        self._init_default_segments()
    
    def _find_toplevel_parent(self):
        """向上遍历找到Toplevel或Tk窗口，用于对话框的父窗口"""
        widget = self
        while widget:
            if isinstance(widget, (tk.Tk, tk.Toplevel)):
                return widget
            widget = widget.master
        return self  # 降级方案
    
    # ==================== 外部接口方法 ====================
    
    def set_params(self, Q: float = None, v_guess: float = None, 
                   H_up: float = None, H_down: float = None,
                   H_bottom: float = None, roughness_n: float = None,
                   D_custom: float = None, 
                   plan_segments: list = None, plan_total_length: float = None,
                   plan_feature_points: list = None,
                   **kwargs):
        """
        设置计算参数（外部调用接口）
        
        Args:
            Q: 设计流量 (m³/s)
            v_guess: 拟定流速 (m/s)
            H_up: 上游水位 (m)
            H_down: 下游水位 (m)
            H_bottom: 上游渠底高程 (m)
            roughness_n: 糙率 n
            D_custom: 自定义管径 (m)，留空则自动计算
            plan_segments: 平面段数据列表 (从推求水面线表格提取)
            plan_total_length: 平面总水平长度 (m)
            plan_feature_points: 平面IP特征点列表 (用于三维空间合并)
        """
        if Q is not None:
            self.entry_Q.delete(0, tk.END)
            self.entry_Q.insert(0, str(Q))
        
        if v_guess is not None:
            self.entry_v.delete(0, tk.END)
            self.entry_v.insert(0, str(v_guess))
        
        if H_up is not None:
            self.entry_H_up.delete(0, tk.END)
            self.entry_H_up.insert(0, str(H_up))
        
        if H_down is not None:
            self.entry_H_down.delete(0, tk.END)
            self.entry_H_down.insert(0, str(H_down))
        
        if H_bottom is not None:
            self.entry_H_bottom.delete(0, tk.END)
            self.entry_H_bottom.insert(0, str(H_bottom))
        
        if roughness_n is not None:
            self.entry_n.delete(0, tk.END)
            self.entry_n.insert(0, str(roughness_n))
        
        if D_custom is not None:
            self.entry_D_custom.delete(0, tk.END)
            self.entry_D_custom.insert(0, str(D_custom))
        
        # 设置平面段数据
        if plan_segments is not None:
            self._set_plan_segments(plan_segments)
        if plan_total_length is not None:
            self.plan_total_length = plan_total_length
        
        # 设置平面IP特征点（用于三维空间合并计算）
        if plan_feature_points is not None:
            self._set_plan_feature_points(plan_feature_points)
        
        # 触发更新
        self._on_water_level_changed()
    
    def _set_plan_segments(self, plan_data: list):
        """
        设置平面段数据（从推求水面线表格提取的平面段信息转换为 StructureSegment 列表）
        
        Args:
            plan_data: 平面段字典列表，每项包含 segment_type, direction, length, radius, angle 等
        """
        self.plan_segments = []
        for item in plan_data:
            seg_type_str = item.get("segment_type", "直管")
            seg_type = SegmentType.STRAIGHT
            for st in SegmentType:
                if st.value == seg_type_str:
                    seg_type = st
                    break
            
            seg = StructureSegment(
                segment_type=seg_type,
                direction=SegmentDirection.PLAN,
                length=item.get("length", 0.0),
                radius=item.get("radius", 0.0),
                angle=item.get("angle", 0.0),
                locked=True,  # 平面段锁定，不可手动编辑
                source_ip_index=item.get("source_ip_index"),
            )
            self.plan_segments.append(seg)
        
        self._refresh_tree()
    
    def _set_plan_feature_points(self, fp_data: list):
        """
        设置平面IP特征点数据（用于三维空间合并计算）
        
        Args:
            fp_data: 特征点字典列表
        """
        self.plan_feature_points = []
        for item in fp_data:
            tt = TurnType.NONE
            for t in TurnType:
                if t.value == item.get("turn_type", "无"):
                    tt = t
                    break
            fp = PlanFeaturePoint(
                chainage=item.get("chainage", 0.0),
                x=item.get("x", 0.0),
                y=item.get("y", 0.0),
                azimuth=item.get("azimuth", 0.0),
                turn_radius=item.get("turn_radius", 0.0),
                turn_angle=item.get("turn_angle", 0.0),
                turn_type=tt,
                ip_index=item.get("ip_index", 0),
            )
            self.plan_feature_points.append(fp)
    
    def get_result(self) -> Optional[CalculationResult]:
        """获取最近一次计算结果"""
        return self.calculation_result
    
    def get_total_head_loss(self) -> Optional[float]:
        """获取总水头损失（便捷方法）"""
        if self.calculation_result:
            return self.calculation_result.total_head_loss
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化当前配置为字典（用于持久化）"""
        try:
            data = {
                "siphon_name": self.siphon_name,
                "Q": float(self.entry_Q.get() or 0),
                "v_guess": float(self.entry_v.get() or 0),
                "H_up": float(self.entry_H_up.get() or 0),
                "H_down": float(self.entry_H_down.get() or 0),
                "H_bottom": float(self.entry_H_bottom.get() or 0),
                "roughness_n": float(self.entry_n.get() or 0.014),
                "D_custom": self.entry_D_custom.get().strip() or None,
                "inlet_type": self.combo_inlet_type.get(),
                "outlet_type": self.combo_outlet_type.get(),
                "xi_inlet": float(self.entry_xi_inlet.get() or 0),
                "xi_outlet": float(self.entry_xi_outlet.get() or 0),
                "v_channel_in": float(self.entry_v_channel_in.get() or 0),
                "v_pipe_in": float(self.entry_v_pipe_in.get() or 0),
                "v_channel_out": float(self.entry_v_channel_out.get() or 0),
                "v_pipe_out": float(self.entry_v_pipe_out.get() or 0),
                "show_detailed": self.show_detailed_process.get(),
                "segments": [self._segment_to_dict(seg) for seg in self.segments],
                "plan_segments": [self._segment_to_dict(seg) for seg in self.plan_segments],
                "plan_total_length": self.plan_total_length,
                "plan_feature_points": [fp.to_dict() for fp in self.plan_feature_points],
                "longitudinal_nodes": [ln.to_dict() for ln in self.longitudinal_nodes],
            }
            
            # 保存计算结果
            if self.calculation_result:
                data["total_head_loss"] = self.calculation_result.total_head_loss
                data["diameter"] = self.calculation_result.diameter
                data["velocity"] = self.calculation_result.velocity
            
            return data
        except Exception as e:
            print(f"序列化错误: {e}")
            return {}
    
    def from_dict(self, data: Dict[str, Any]):
        """从字典恢复配置"""
        if not data:
            return
        
        try:
            # 恢复基本参数
            if "Q" in data:
                self.entry_Q.delete(0, tk.END)
                self.entry_Q.insert(0, str(data["Q"]))
            
            if "v_guess" in data:
                self.entry_v.delete(0, tk.END)
                self.entry_v.insert(0, str(data["v_guess"]))
            
            if "H_up" in data:
                self.entry_H_up.delete(0, tk.END)
                self.entry_H_up.insert(0, str(data["H_up"]))
            
            if "H_down" in data:
                self.entry_H_down.delete(0, tk.END)
                self.entry_H_down.insert(0, str(data["H_down"]))
            
            if "H_bottom" in data:
                self.entry_H_bottom.delete(0, tk.END)
                self.entry_H_bottom.insert(0, str(data["H_bottom"]))
            
            if "roughness_n" in data:
                self.entry_n.delete(0, tk.END)
                self.entry_n.insert(0, str(data["roughness_n"]))
            
            if "D_custom" in data and data["D_custom"]:
                self.entry_D_custom.delete(0, tk.END)
                self.entry_D_custom.insert(0, str(data["D_custom"]))
            
            if "inlet_type" in data:
                self.combo_inlet_type.set(data["inlet_type"])
            
            if "outlet_type" in data:
                self.combo_outlet_type.set(data["outlet_type"])
            
            if "xi_inlet" in data:
                self.entry_xi_inlet.delete(0, tk.END)
                self.entry_xi_inlet.insert(0, str(data["xi_inlet"]))
            
            if "xi_outlet" in data:
                self.entry_xi_outlet.delete(0, tk.END)
                self.entry_xi_outlet.insert(0, str(data["xi_outlet"]))
            
            if "v_channel_in" in data:
                self.entry_v_channel_in.delete(0, tk.END)
                self.entry_v_channel_in.insert(0, str(data["v_channel_in"]))
            
            if "v_pipe_in" in data:
                self.entry_v_pipe_in.delete(0, tk.END)
                self.entry_v_pipe_in.insert(0, str(data["v_pipe_in"]))
            
            if "v_channel_out" in data:
                self.entry_v_channel_out.delete(0, tk.END)
                self.entry_v_channel_out.insert(0, str(data["v_channel_out"]))
            
            if "v_pipe_out" in data:
                self.entry_v_pipe_out.delete(0, tk.END)
                self.entry_v_pipe_out.insert(0, str(data["v_pipe_out"]))
            
            if "show_detailed" in data:
                self.show_detailed_process.set(data["show_detailed"])
            
            # 恢复结构段（纵断面段）
            if "segments" in data and data["segments"]:
                self.segments = [self._dict_to_segment(s) for s in data["segments"]]
            
            # 恢复平面段
            if "plan_segments" in data and data["plan_segments"]:
                self.plan_segments = [self._dict_to_segment(s) for s in data["plan_segments"]]
            if "plan_total_length" in data:
                self.plan_total_length = data["plan_total_length"]
            
            # 恢复平面IP特征点
            if "plan_feature_points" in data and data["plan_feature_points"]:
                self.plan_feature_points = [
                    PlanFeaturePoint.from_dict(fp) for fp in data["plan_feature_points"]
                ]
            
            # 恢复纵断面变坡点
            if "longitudinal_nodes" in data and data["longitudinal_nodes"]:
                self.longitudinal_nodes = [
                    LongitudinalNode.from_dict(ln) for ln in data["longitudinal_nodes"]
                ]
            
            self._refresh_tree()
            
            # 触发更新
            self._on_water_level_changed()
            
        except Exception as e:
            print(f"反序列化错误: {e}")
    
    def _segment_to_dict(self, seg: StructureSegment) -> Dict[str, Any]:
        """将结构段转换为字典"""
        d = {
            "segment_type": seg.segment_type.value,
            "direction": seg.direction.value if hasattr(seg, 'direction') else "纵断面",
            "length": seg.length,
            "radius": seg.radius,
            "angle": seg.angle,
            "xi_user": seg.xi_user,
            "xi_calc": seg.xi_calc,
            "locked": seg.locked,
            "inlet_shape": seg.inlet_shape.value if seg.inlet_shape else None,
            "outlet_shape": seg.outlet_shape.value if seg.outlet_shape else None,
            "start_elevation": seg.start_elevation,
            "end_elevation": seg.end_elevation,
            "source_ip_index": seg.source_ip_index,
        }
        return d
    
    def _dict_to_segment(self, data: Dict[str, Any]) -> StructureSegment:
        """从字典恢复结构段"""
        segment_type = SegmentType.STRAIGHT
        for st in SegmentType:
            if st.value == data.get("segment_type"):
                segment_type = st
                break
        
        # 解析方向
        direction = SegmentDirection.LONGITUDINAL
        dir_str = data.get("direction", "纵断面")
        for sd in SegmentDirection:
            if sd.value == dir_str:
                direction = sd
                break
        
        inlet_shape = None
        if data.get("inlet_shape"):
            for shape in InletOutletShape:
                if shape.value == data["inlet_shape"]:
                    inlet_shape = shape
                    break
        
        outlet_shape = None
        if data.get("outlet_shape"):
            for shape in InletOutletShape:
                if shape.value == data["outlet_shape"]:
                    outlet_shape = shape
                    break
        
        return StructureSegment(
            segment_type=segment_type,
            direction=direction,
            length=data.get("length", 0),
            radius=data.get("radius", 0),
            angle=data.get("angle", 0),
            xi_user=data.get("xi_user"),
            xi_calc=data.get("xi_calc"),
            locked=data.get("locked", False),
            inlet_shape=inlet_shape,
            outlet_shape=outlet_shape,
            start_elevation=data.get("start_elevation"),
            end_elevation=data.get("end_elevation"),
            source_ip_index=data.get("source_ip_index"),
        )
    
    # ==================== UI 创建方法 ====================
    
    def _create_ui(self):
        """创建用户界面"""
        # 主容器
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 顶部可视化区域
        self._create_visual_area(main_frame)
        
        # 中部参数设置区域
        self._create_parameter_area(main_frame)
        
        # 底部操作区域
        self._create_operation_area(main_frame)
    
    def _create_visual_area(self, parent):
        """创建顶部可视化区域"""
        visual_frame = ttk.LabelFrame(parent, text="管道剖面图", padding=5)
        visual_frame.pack(fill=tk.X, pady=(0, 5))
        
        # 顶部工具栏 - 缩放控制
        toolbar = ttk.Frame(visual_frame)
        toolbar.pack(fill=tk.X, pady=(0, 5))
        
        # 缩放控制
        zoom_frame = ttk.Frame(toolbar)
        zoom_frame.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(zoom_frame, text="缩放:").pack(side=tk.LEFT, padx=2)
        ttk.Button(zoom_frame, text="放大", command=self._zoom_in, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Button(zoom_frame, text="缩小", command=self._zoom_out, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Button(zoom_frame, text="重置", command=self._zoom_reset, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Button(zoom_frame, text="适应窗口", command=self._zoom_fit, width=8).pack(side=tk.LEFT, padx=2)
        
        self.zoom_label = ttk.Label(zoom_frame, text="100%")
        self.zoom_label.pack(side=tk.LEFT, padx=5)
        
        # Canvas画布
        canvas_container = ttk.Frame(visual_frame)
        canvas_container.pack(fill=tk.BOTH, expand=True)
        
        self.canvas = tk.Canvas(
            canvas_container,
            height=250,
            bg='black',
            highlightthickness=1,
            highlightbackground='gray'
        )
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        
        # 缩放相关变量
        self.zoom_level = 1.0
        self.pan_offset_x = 0
        self.pan_offset_y = 0
        self._drag_start = None
        
        # 绑定事件
        self.canvas.bind('<Configure>', self._on_canvas_resize)
        self.canvas.bind('<MouseWheel>', self._on_mouse_wheel)
        self.canvas.bind('<Button-4>', self._on_mouse_wheel)
        self.canvas.bind('<Button-5>', self._on_mouse_wheel)
        self.canvas.bind('<ButtonPress-1>', self._on_canvas_drag_start)
        self.canvas.bind('<B1-Motion>', self._on_canvas_drag)
        self.canvas.bind('<ButtonRelease-1>', self._on_canvas_drag_end)
    
    def _create_parameter_area(self, parent):
        """创建中部参数设置区域"""
        param_frame = ttk.Frame(parent)
        param_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # 使用Notebook创建选项卡
        self.notebook = ttk.Notebook(param_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        
        # Tab1: 基本参数
        self._create_basic_params_tab()
        
        # Tab2: 结构段信息
        self._create_segments_tab()
    
    def _create_basic_params_tab(self):
        """创建基本参数选项卡"""
        tab1 = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab1, text="基本参数")
        
        # 左右分栏
        left_frame = ttk.LabelFrame(tab1, text="全局水力参数", padding=10)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        
        right_frame = ttk.LabelFrame(tab1, text="渐变段配置", padding=10)
        right_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0))
        
        # ===== 左侧：全局水力参数 =====
        row = 0
        
        # 计算目标
        ttk.Label(left_frame, text="计算目标:").grid(row=row, column=0, sticky='e', pady=2)
        self.calc_target = ttk.Combobox(left_frame, values=["设计截面"], state='readonly', width=15)
        self.calc_target.set("设计截面")
        self.calc_target.grid(row=row, column=1, sticky='w', pady=2, padx=5)
        row += 1
        
        # 设计流量
        ttk.Label(left_frame, text="设计流量 Q (m³/s):").grid(row=row, column=0, sticky='e', pady=2)
        self.entry_Q = ttk.Entry(left_frame, width=15)
        self.entry_Q.insert(0, "10.0")
        self.entry_Q.grid(row=row, column=1, sticky='w', pady=2, padx=5)
        self.entry_Q.bind('<KeyRelease>', self._on_Qv_changed)
        row += 1
        
        # 拟定流速
        ttk.Label(left_frame, text="拟定流速 v (m/s):").grid(row=row, column=0, sticky='e', pady=2)
        self.entry_v = ttk.Entry(left_frame, width=15)
        self.entry_v.insert(0, "2.0")
        self.entry_v.grid(row=row, column=1, sticky='w', pady=2, padx=5)
        self.entry_v.bind('<KeyRelease>', self._on_Qv_changed)
        row += 1
        
        # 上游水位
        ttk.Label(left_frame, text="上游水位 (m):").grid(row=row, column=0, sticky='e', pady=2)
        self.entry_H_up = ttk.Entry(left_frame, width=15)
        self.entry_H_up.insert(0, "100.0")
        self.entry_H_up.grid(row=row, column=1, sticky='w', pady=2, padx=5)
        self.entry_H_up.bind('<KeyRelease>', self._on_water_level_changed)
        row += 1
        
        # 下游水位
        ttk.Label(left_frame, text="下游水位 (m):").grid(row=row, column=0, sticky='e', pady=2)
        self.entry_H_down = ttk.Entry(left_frame, width=15)
        self.entry_H_down.insert(0, "98.0")
        self.entry_H_down.grid(row=row, column=1, sticky='w', pady=2, padx=5)
        self.entry_H_down.bind('<KeyRelease>', self._on_water_level_changed)
        row += 1
        
        # 上游渠底高程
        ttk.Label(left_frame, text="上游渠底高程 (m):").grid(row=row, column=0, sticky='e', pady=2)
        self.entry_H_bottom = ttk.Entry(left_frame, width=15)
        self.entry_H_bottom.insert(0, "95.0")
        self.entry_H_bottom.grid(row=row, column=1, sticky='w', pady=2, padx=5)
        self.entry_H_bottom.bind('<KeyRelease>', self._on_water_level_changed)
        row += 1
        
        # 糙率
        ttk.Label(left_frame, text="糙率 n:").grid(row=row, column=0, sticky='e', pady=2)
        self.entry_n = ttk.Entry(left_frame, width=15)
        self.entry_n.insert(0, "0.014")
        self.entry_n.grid(row=row, column=1, sticky='w', pady=2, padx=5)
        row += 1
        
        # 用户自定义设计管径
        ttk.Label(left_frame, text="自定义设计管径 D (m):").grid(row=row, column=0, sticky='e', pady=2)
        self.entry_D_custom = ttk.Entry(left_frame, width=15)
        self.entry_D_custom.grid(row=row, column=1, sticky='w', pady=2, padx=5)
        self.entry_D_custom.bind('<KeyRelease>', self._on_D_custom_changed)
        ttk.Label(left_frame, text="(留空则自动计算)", font=('', 8)).grid(row=row, column=2, sticky='w')
        row += 1
        
        # ===== 右侧：渐变段配置 =====
        row = 0
        
        # 进口渐变段型式
        ttk.Label(right_frame, text="进口渐变段型式:").grid(row=row, column=0, sticky='e', pady=2)
        self.combo_inlet_type = ttk.Combobox(
            right_frame,
            values=[gt.value for gt in GradientType],
            state='readonly',
            width=15
        )
        self.combo_inlet_type.set(GradientType.NONE.value)
        self.combo_inlet_type.grid(row=row, column=1, sticky='w', pady=2, padx=5)
        self.combo_inlet_type.bind('<<ComboboxSelected>>', self._on_inlet_type_changed)
        row += 1
        
        # 进口局部水头损失系数
        ttk.Label(right_frame, text="进口局部水头损失系数 ξ₁:").grid(row=row, column=0, sticky='e', pady=2)
        self.entry_xi_inlet = ttk.Entry(right_frame, width=15)
        self.entry_xi_inlet.insert(0, "0.0")
        self.entry_xi_inlet.grid(row=row, column=1, sticky='w', pady=2, padx=5)
        row += 1
        
        # 进口渐变段始端流速v1
        ttk.Label(right_frame, text="进口渐变段始端流速v₁ (m/s):").grid(row=row, column=0, sticky='e', pady=2)
        v1_frame = tk.Frame(right_frame)
        v1_frame.grid(row=row, column=1, columnspan=2, sticky='w', pady=2, padx=5)
        self.entry_v_channel_in = ttk.Entry(v1_frame, width=15)
        self.entry_v_channel_in.insert(0, "1.0")
        self.entry_v_channel_in.pack(side=tk.LEFT)
        self.entry_v_channel_in.bind('<KeyRelease>', self._on_v_channel_in_changed)
        tk.Label(v1_frame, text="(可采用上游渠道断面平均流速)", fg='#FF6600', font=('Microsoft YaHei', 8)).pack(side=tk.LEFT, padx=(2, 0))
        row += 1
        
        # 进口渐变段末端流速v2
        ttk.Label(right_frame, text="进口渐变段末端流速v₂ (m/s):").grid(row=row, column=0, sticky='e', pady=2)
        v2_frame = tk.Frame(right_frame)
        v2_frame.grid(row=row, column=1, columnspan=2, sticky='w', pady=2, padx=5)
        self.entry_v_pipe_in = ttk.Entry(v2_frame, width=15)
        self.entry_v_pipe_in.insert(0, "1.2")
        self.entry_v_pipe_in.pack(side=tk.LEFT)
        self.entry_v_pipe_in.bind('<Double-Button-1>', self._open_inlet_section_dialog)
        self.entry_v_pipe_in.bind('<FocusOut>', self._validate_inlet_velocity)
        tk.Label(v2_frame, text="(双击设置断面参数自动计算)", fg='#0066CC', font=('Microsoft YaHei', 9)).pack(side=tk.LEFT, padx=(2, 0))
        row += 1
        
        # 添加默认规则说明
        tk.Label(
            right_frame, 
            text="默认规则：未设置进口渐变段末端断面参数时，v₂ = v₁ + 0.2", 
            fg='#666666', 
            font=('Microsoft YaHei', 9)
        ).grid(row=row, column=0, columnspan=3, sticky='w', pady=(0, 5), padx=5)
        row += 1
        
        # 内部存储断面参数
        self.inlet_section_B = None
        self.inlet_section_h = None
        self.inlet_section_m = None
        
        ttk.Separator(right_frame, orient='horizontal').grid(row=row, column=0, columnspan=3, sticky='ew', pady=10)
        row += 1
        
        # 出口渐变段型式
        ttk.Label(right_frame, text="出口渐变段型式:").grid(row=row, column=0, sticky='e', pady=2)
        self.combo_outlet_type = ttk.Combobox(
            right_frame,
            values=[gt.value for gt in GradientType],
            state='readonly',
            width=15
        )
        self.combo_outlet_type.set(GradientType.NONE.value)
        self.combo_outlet_type.grid(row=row, column=1, sticky='w', pady=2, padx=5)
        self.combo_outlet_type.bind('<<ComboboxSelected>>', self._on_outlet_type_changed)
        row += 1
        
        # 出口局部水头损失系数
        ttk.Label(right_frame, text="出口局部水头损失系数 ξ₂:").grid(row=row, column=0, sticky='e', pady=2)
        self.entry_xi_outlet = ttk.Entry(right_frame, width=15)
        self.entry_xi_outlet.insert(0, "0.0")
        self.entry_xi_outlet.grid(row=row, column=1, sticky='w', pady=2, padx=5)
        row += 1
        
        # 出口渐变段始端流速v
        ttk.Label(right_frame, text="出口渐变段始端流速v (m/s):").grid(row=row, column=0, sticky='e', pady=2)
        v_out_frame = tk.Frame(right_frame)
        v_out_frame.grid(row=row, column=1, columnspan=2, sticky='w', pady=2, padx=5)
        self.entry_v_channel_out = ttk.Entry(v_out_frame, width=15)
        default_v_out = self.entry_v.get().strip() or "2.0"
        self.entry_v_channel_out.insert(0, default_v_out)
        self.entry_v_channel_out.pack(side=tk.LEFT)
        self.entry_v_channel_out.bind('<KeyRelease>', self._on_v_channel_out_user_modified)
        tk.Label(v_out_frame, text="(可采用管道出口处流速)", fg='#FF6600', font=('Microsoft YaHei', 8)).pack(side=tk.LEFT, padx=(2, 0))
        row += 1
        
        # 出口渐变段末端流速v3
        ttk.Label(right_frame, text="出口渐变段末端流速v₃ (m/s):").grid(row=row, column=0, sticky='e', pady=2)
        v3_frame = tk.Frame(right_frame)
        v3_frame.grid(row=row, column=1, columnspan=2, sticky='w', pady=2, padx=5)
        self.entry_v_pipe_out = ttk.Entry(v3_frame, width=15)
        self.entry_v_pipe_out.insert(0, "1.8835")
        self.entry_v_pipe_out.pack(side=tk.LEFT)
        tk.Label(v3_frame, text="(可采用下游渠道断面平均流速)", fg='#FF6600', font=('Microsoft YaHei', 8)).pack(side=tk.LEFT, padx=(2, 0))
    
    def _create_segments_tab(self):
        """创建结构段信息选项卡"""
        tab2 = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab2, text="结构段信息")
        
        # 顶部工具栏
        toolbar = ttk.Frame(tab2)
        toolbar.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Button(toolbar, text="导入DXF", command=self._import_dxf).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="添加直管", command=self._add_straight_segment).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="添加弯管", command=self._add_bend_segment).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="删除", command=self._delete_segment).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="清空", command=self._clear_segments).pack(side=tk.LEFT, padx=2)
        
        ttk.Label(toolbar, text="结构段数:").pack(side=tk.LEFT, padx=(20, 2))
        self.label_segment_count = ttk.Label(toolbar, text="0")
        self.label_segment_count.pack(side=tk.LEFT)
        
        # 创建表格区域
        table_frame = ttk.Frame(tab2)
        table_frame.pack(fill=tk.BOTH, expand=True)
        
        # Treeview表格
        columns = ('序号', '方向', '类型', '长度(m)', '半径R(m)', '角度θ(°)', 
                   '起点高程', '终点高程', '空间长度', '局部系数', '锁定')
        self.tree = ttk.Treeview(table_frame, columns=columns, show='headings', height=8)
        
        for col in columns:
            self.tree.heading(col, text=col)
        
        self.tree.column('序号', width=40, anchor='center')
        self.tree.column('方向', width=55, anchor='center')
        self.tree.column('类型', width=100, anchor='center')
        self.tree.column('长度(m)', width=70, anchor='center')
        self.tree.column('半径R(m)', width=70, anchor='center')
        self.tree.column('角度θ(°)', width=70, anchor='center')
        self.tree.column('起点高程', width=70, anchor='center')
        self.tree.column('终点高程', width=70, anchor='center')
        self.tree.column('空间长度', width=70, anchor='center')
        self.tree.column('局部系数', width=70, anchor='center')
        self.tree.column('锁定', width=40, anchor='center')
        
        # 定义颜色标签用于区分平面段和纵断面段
        self.tree.tag_configure('plan', background='#E8F0FE')       # 浅蓝色背景 - 平面段
        self.tree.tag_configure('longitudinal', background='#E8F5E9')  # 浅绿色背景 - 纵断面段
        
        scrollbar = ttk.Scrollbar(table_frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 双击编辑
        self.tree.bind('<Double-1>', self._on_tree_double_click)
        
        # 拖拽排序
        self._drag_data = {'item': None, 'index': None, 'start_y': None}
        self.tree.bind('<Button-1>', self._on_drag_start)
        self.tree.bind('<B1-Motion>', self._on_drag_motion)
        self.tree.bind('<ButtonRelease-1>', self._on_drag_release)
        
        # 操作说明面板
        info_frame = ttk.LabelFrame(tab2, text="操作说明", padding=10)
        info_frame.pack(fill=tk.X, pady=(5, 0))
        
        info_text = """1. 点击"导入 DXF"可从CAD文件导入管道几何
2. 点击"添加段"手动添加结构段
3. 双击表格行可编辑该行数据
4. 拖拽表格行可调整顺序（首末行除外）
5. 第一行为进水口，最后一行为出水口
6. 类型包括：进水口、直管、弯管、折管、拦污栅、闸门槽、旁通管、其他、出水口"""
        ttk.Label(info_frame, text=info_text, justify='left').pack(anchor='w')
    
    def _create_operation_area(self, parent):
        """创建底部操作区域"""
        op_frame = ttk.Frame(parent)
        op_frame.pack(fill=tk.X, pady=(5, 0))
        
        # 左侧：公式说明
        formula_frame = ttk.LabelFrame(op_frame, text="计算公式", padding=5)
        formula_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        
        formula_text = """谢才公式: C = (1/n) × R^(1/6)
沿程损失: hf = v²L/(C²R)
局部损失: hj = Σξ × v²/(2g)
总损失: hw = hf + hj"""
        ttk.Label(formula_frame, text=formula_text, justify='left', font=('Consolas', 9)).pack()
        
        # 中间：名称和选项
        middle_frame = ttk.Frame(op_frame)
        middle_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10)
        
        ttk.Label(middle_frame, text="倒虹吸名称:").pack(side=tk.LEFT)
        self.entry_job_name = ttk.Entry(middle_frame, width=25)
        self.entry_job_name.insert(0, self.siphon_name or "倒虹吸")
        self.entry_job_name.pack(side=tk.LEFT, padx=5)
        
        ttk.Checkbutton(
            middle_frame,
            text="输出详细计算过程",
            variable=self.show_detailed_process
        ).pack(side=tk.LEFT, padx=10)
        
        # 右侧：操作按钮
        btn_frame = ttk.Frame(op_frame)
        btn_frame.pack(side=tk.RIGHT)
        
        self.btn_calculate = ttk.Button(btn_frame, text="执行计算", command=self._execute_calculation, width=10)
        self.btn_calculate.pack(side=tk.LEFT, padx=2)
        
        ttk.Button(btn_frame, text="导出结果", command=self._export_result, width=10).pack(side=tk.LEFT, padx=2)
    
    # ==================== 初始化和刷新方法 ====================
    
    def _init_default_segments(self):
        """初始化默认结构段"""
        # 进水口默认使用"进口稍微修圆"，系数取中值0.225
        inlet_shape = InletOutletShape.SLIGHTLY_ROUNDED
        inlet_xi = sum(INLET_SHAPE_COEFFICIENTS[inlet_shape]) / 2  # 取范围中值
        
        # 出水口默认使用流入明渠计算，初始系数设为0（待用户设置渠道参数后计算）
        outlet_xi = 0.0
        
        self.segments = [
            StructureSegment(segment_type=SegmentType.INLET, locked=True, 
                           inlet_shape=inlet_shape, xi_calc=inlet_xi),
            StructureSegment(segment_type=SegmentType.TRASH_RACK, length=1.0),
            StructureSegment(segment_type=SegmentType.GATE_SLOT, length=0.5),
            StructureSegment(segment_type=SegmentType.BYPASS_PIPE, xi_user=0.1),
            StructureSegment(segment_type=SegmentType.FOLD, length=5.0),
            StructureSegment(segment_type=SegmentType.STRAIGHT, length=50.0),
            StructureSegment(segment_type=SegmentType.BEND, length=10.0, radius=5.0, angle=45.0),
            StructureSegment(segment_type=SegmentType.STRAIGHT, length=100.0),
            StructureSegment(segment_type=SegmentType.BEND, length=10.0, radius=5.0, angle=45.0),
            StructureSegment(segment_type=SegmentType.STRAIGHT, length=50.0),
            StructureSegment(segment_type=SegmentType.OTHER, xi_user=0.1),
            StructureSegment(segment_type=SegmentType.OUTLET, locked=True, xi_calc=outlet_xi)
        ]
        self._refresh_tree()
    
    def _get_all_display_segments(self) -> list:
        """
        获取用于表格显示的所有段列表（平面段 + 纵断面段），
        返回 [(StructureSegment, source)] 列表，source = 'plan' 或 'longitudinal'
        """
        display = []
        # 平面段排在前面
        for seg in self.plan_segments:
            display.append((seg, 'plan'))
        # 纵断面段排在后面
        for seg in self.segments:
            display.append((seg, 'longitudinal'))
        return display
    
    def _refresh_tree(self):
        """刷新表格显示"""
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        display_segments = self._get_all_display_segments()
        
        for i, (seg, source) in enumerate(display_segments):
            xi = seg.xi_user if seg.xi_user is not None else (seg.xi_calc if seg.xi_calc is not None else '--')
            if isinstance(xi, float):
                xi = f"{xi:.4f}"
            
            type_display = seg.segment_type.value
            if seg.segment_type == SegmentType.INLET and seg.inlet_shape:
                type_display = f"进水口({seg.inlet_shape.value})"
            elif seg.segment_type == SegmentType.OUTLET:
                type_display = "出水口"
            
            direction_display = seg.direction.value if hasattr(seg, 'direction') else "纵断面"
            
            # 高程显示（仅纵断面直管段/折管段有意义）
            start_elev = f"{seg.start_elevation:.2f}" if seg.start_elevation is not None else '--'
            end_elev = f"{seg.end_elevation:.2f}" if seg.end_elevation is not None else '--'
            
            # 空间长度显示
            sp_len = seg.spatial_length
            spatial_display = f"{sp_len:.2f}" if sp_len > 0 else '--'
            
            values = (
                i + 1,
                direction_display,
                type_display,
                f"{seg.length:.2f}" if seg.length > 0 else '--',
                f"{seg.radius:.2f}" if seg.radius > 0 else '--',
                f"{seg.angle:.1f}" if seg.angle > 0 else '--',
                start_elev,
                end_elev,
                spatial_display,
                xi,
                '是' if seg.locked else '否'
            )
            tag = source  # 'plan' 或 'longitudinal'
            self.tree.insert('', 'end', values=values, tags=(tag,))
        
        total_count = len(self.plan_segments) + len(self.segments)
        plan_count = len(self.plan_segments)
        if plan_count > 0:
            self.label_segment_count.config(text=f"{total_count} (平面:{plan_count})")
        else:
            self.label_segment_count.config(text=str(total_count))
        self._draw_pipeline()
    
    # ==================== 事件处理方法 ====================
    
    def _on_inlet_type_changed(self, event=None):
        """进口渐变段型式改变"""
        type_name = self.combo_inlet_type.get()
        gradient_type = self._get_gradient_type_by_name(type_name)
        coeff = CoefficientService.get_gradient_coeff(gradient_type, True)
        self.entry_xi_inlet.delete(0, tk.END)
        self.entry_xi_inlet.insert(0, f"{coeff:.4f}")
        
        if self.segments and self.segments[0].segment_type == SegmentType.INLET:
            self.segments[0].xi_calc = coeff
            self._refresh_tree()
    
    def _on_outlet_type_changed(self, event=None):
        """出口渐变段型式改变"""
        type_name = self.combo_outlet_type.get()
        gradient_type = self._get_gradient_type_by_name(type_name)
        coeff = CoefficientService.get_gradient_coeff(gradient_type, False)
        self.entry_xi_outlet.delete(0, tk.END)
        self.entry_xi_outlet.insert(0, f"{coeff:.4f}")
        
        if self.segments and self.segments[-1].segment_type == SegmentType.OUTLET:
            self.segments[-1].xi_calc = coeff
            self._refresh_tree()
    
    def _get_gradient_type_by_name(self, name: str) -> GradientType:
        """根据名称获取渐变段类型枚举"""
        for gt in GradientType:
            if gt.value == name:
                return gt
        return GradientType.NONE
    
    def _on_water_level_changed(self, event=None):
        """水位参数改变"""
        if hasattr(self, '_redraw_pending'):
            self.after_cancel(self._redraw_pending)
        self._redraw_pending = self.after(100, self._draw_pipeline)
    
    def _on_Qv_changed(self, event=None):
        """Q或v参数改变"""
        if hasattr(self, '_update_xi_pending'):
            self.after_cancel(self._update_xi_pending)
        self._update_xi_pending = self.after(200, self._update_after_Q_changed)
    
    def _update_after_Q_changed(self):
        """Q改变后更新"""
        self._update_segment_coefficients()
        self._on_inlet_section_changed()
        self._update_v_channel_out_default()
    
    def _on_v_channel_out_user_modified(self, event=None):
        """用户手动修改出口流速"""
        self._v_channel_out_user_modified = True
    
    def _update_v_channel_out_default(self):
        """更新出口流速默认值"""
        if self._v_channel_out_user_modified:
            return
        try:
            v = self.entry_v.get().strip()
            if v:
                self.entry_v_channel_out.delete(0, tk.END)
                self.entry_v_channel_out.insert(0, v)
        except:
            pass
    
    def _on_D_custom_changed(self, event=None):
        """自定义管径改变"""
        custom_d = self.entry_D_custom.get().strip()
        if custom_d:
            self.entry_v.configure(state='disabled')
        else:
            self.entry_v.configure(state='normal')
        
        if hasattr(self, '_update_xi_pending'):
            self.after_cancel(self._update_xi_pending)
        self._update_xi_pending = self.after(200, self._update_segment_coefficients)
    
    def _update_segment_coefficients(self):
        """更新结构段系数"""
        try:
            Q = float(self.entry_Q.get())
            v = float(self.entry_v.get())
        except ValueError:
            return
        
        if Q <= 0 or v <= 0:
            return
        
        custom_d = self.entry_D_custom.get().strip()
        if custom_d:
            try:
                D = float(custom_d)
            except ValueError:
                omega = Q / v
                D = math.sqrt(4 * omega / math.pi)
        else:
            omega = Q / v
            D = math.sqrt(4 * omega / math.pi)
        
        if D <= 0:
            return
        
        updated = False
        for seg in self.segments:
            if seg.segment_type == SegmentType.BEND and seg.radius > 0 and seg.angle > 0:
                if seg.xi_user is None:
                    xi_bend = CoefficientService.calculate_bend_coeff(seg.radius, D, seg.angle, verbose=False)
                    seg.xi_calc = xi_bend
                    updated = True
        
        if updated:
            self._refresh_tree()
    
    def _on_v_channel_in_changed(self, event=None):
        """进口始端流速改变"""
        try:
            if self.inlet_section_B is not None:
                self._on_inlet_section_changed()
                return
            
            v1_str = self.entry_v_channel_in.get().strip()
            if not v1_str:
                return
            
            v1 = float(v1_str)
            if v1 <= 0:
                return
            
            v2 = v1 + 0.2
            self.entry_v_pipe_in.delete(0, tk.END)
            self.entry_v_pipe_in.insert(0, f"{v2:.4f}")
        except ValueError:
            pass
    
    def _on_inlet_section_changed(self, event=None):
        """进口断面参数改变"""
        try:
            if self.inlet_section_B is None:
                return
            Q = float(self.entry_Q.get())
            if self.inlet_section_B <= 0 or self.inlet_section_h <= 0 or Q <= 0:
                return
            v2 = self._calculate_trapezoidal_velocity(
                self.inlet_section_B, self.inlet_section_h, self.inlet_section_m, Q)
            self.entry_v_pipe_in.delete(0, tk.END)
            self.entry_v_pipe_in.insert(0, f"{v2:.4f}")
        except ValueError:
            pass
    
    def _calculate_trapezoidal_velocity(self, B, h, m, Q):
        """计算梯形断面流速"""
        area = (B + m * h) * h
        if area <= 0:
            return 0.0
        return Q / area
    
    def _validate_inlet_velocity(self, event=None):
        """验证进口流速"""
        try:
            v1 = float(self.entry_v_channel_in.get().strip() or 0)
            v2 = float(self.entry_v_pipe_in.get().strip() or 0)
            if v2 <= v1:
                messagebox.showwarning("警告", "进口末端流速应大于始端流速", parent=self._dialog_parent)
        except ValueError:
            pass
    
    def _open_inlet_section_dialog(self, event=None):
        """打开进口断面参数对话框"""
        try:
            Q = float(self.entry_Q.get())
            if Q <= 0:
                messagebox.showwarning("参数错误", "请先设置有效的设计流量Q", parent=self._dialog_parent)
                return
        except ValueError:
            messagebox.showwarning("参数错误", "请先设置有效的设计流量Q", parent=self._dialog_parent)
            return
        
        dialog = InletSectionDialog(
            self._dialog_parent, 
            Q=Q,
            B=self.inlet_section_B,
            h=self.inlet_section_h,
            m=self.inlet_section_m
        )
        self.wait_window(dialog)
        
        if hasattr(dialog, 'result_B'):
            self.inlet_section_B = dialog.result_B
            self.inlet_section_h = dialog.result_h
            self.inlet_section_m = dialog.result_m
            
            if dialog.result_velocity is not None:
                self.entry_v_pipe_in.delete(0, tk.END)
                self.entry_v_pipe_in.insert(0, f"{dialog.result_velocity:.4f}")
            elif self.inlet_section_B is None:
                self._on_v_channel_in_changed()
    
    # ==================== 结构段操作方法 ====================
    
    def _import_dxf(self):
        """
        导入DXF纵断面多段线
        
        解析流程：
        1. 读取 LWPOLYLINE，X=桩号，Y=高程
        2. bulge→竖曲线半径，直线段→坡段
        3. 生成 LongitudinalNode 变坡点节点表
        4. 同时生成传统 StructureSegment 用于表格显示
        5. 桩号自动对齐到 MC 进口桩号
        """
        file_path = filedialog.askopenfilename(
            title="选择纵断面DXF文件",
            filetypes=[("DXF文件", "*.dxf"), ("所有文件", "*.*")],
            parent=self._dialog_parent
        )
        
        if not file_path:
            return
        
        # 计算桩号偏移量：使多段线起点X对齐到进口MC桩号
        chainage_offset = 0.0
        if self.plan_feature_points:
            # 先读取DXF获取起点X
            try:
                import ezdxf
                doc = ezdxf.readfile(file_path)
                msp = doc.modelspace()
                polys = list(msp.query('LWPOLYLINE'))
                if not polys:
                    polys = list(msp.query('POLYLINE'))
                if polys:
                    first_point = list(polys[0].get_points(format='xyseb'))[0]
                    x_start = first_point[0]
                    mc_inlet = self.plan_feature_points[0].chainage
                    chainage_offset = mc_inlet - x_start
            except Exception:
                pass  # 偏移量默认为0
        
        # 解析纵断面为变坡点节点表
        long_nodes, message = DxfParser.parse_longitudinal_profile(
            file_path, chainage_offset=chainage_offset
        )
        
        if not long_nodes:
            messagebox.showerror("导入失败", message, parent=self._dialog_parent)
            return
        
        self.longitudinal_nodes = long_nodes
        
        # 同时用传统方式解析生成 StructureSegment（用于表格显示和向后兼容）
        segments, h_bottom, seg_msg = DxfParser.parse_dxf(file_path)
        if segments:
            self.segments = segments
        
        # 更新渠底高程建议值
        if h_bottom > 0:
            self.entry_H_bottom.delete(0, tk.END)
            self.entry_H_bottom.insert(0, f"{h_bottom:.2f}")
        
        self._refresh_tree()
        
        # 提示信息
        node_info = f"变坡点节点: {len(long_nodes)} 个"
        turns = sum(1 for nd in long_nodes if nd.turn_type != TurnType.NONE)
        node_info += f"（其中转弯 {turns} 个）"
        
        spatial_info = ""
        if self.plan_feature_points:
            spatial_info = "\n已检测到平面数据，将使用三维空间合并计算"
        else:
            spatial_info = "\n未检测到平面数据，将使用纵断面独立计算模式"
        
        messagebox.showinfo(
            "导入成功", 
            f"{message}\n{node_info}{spatial_info}",
            parent=self._dialog_parent
        )
    
    def _add_straight_segment(self):
        """添加直管段"""
        if self.segments and self.segments[-1].segment_type == SegmentType.OUTLET:
            self.segments.insert(-1, StructureSegment(segment_type=SegmentType.STRAIGHT, length=50.0))
        else:
            self.segments.append(StructureSegment(segment_type=SegmentType.STRAIGHT, length=50.0))
        self._refresh_tree()
    
    def _add_bend_segment(self):
        """添加弯管段"""
        if self.segments and self.segments[-1].segment_type == SegmentType.OUTLET:
            self.segments.insert(-1, StructureSegment(segment_type=SegmentType.BEND, length=10.0, radius=5.0, angle=45.0))
        else:
            self.segments.append(StructureSegment(segment_type=SegmentType.BEND, length=10.0, radius=5.0, angle=45.0))
        self._refresh_tree()
        self._update_segment_coefficients()
    
    def _delete_segment(self):
        """删除结构段"""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("提示", "请先选择要删除的行", parent=self._dialog_parent)
            return
        
        display_index = self.tree.index(selection[0])
        source, real_index, segment = self._resolve_display_index(display_index)
        
        # 平面段不允许删除
        if source == 'plan':
            messagebox.showwarning("提示", "平面段由推求水面线表格自动提取，不可手动删除", parent=self._dialog_parent)
            return
        
        if segment.segment_type in [SegmentType.INLET, SegmentType.OUTLET]:
            messagebox.showwarning("提示", "不能删除进水口或出水口", parent=self._dialog_parent)
            return
        
        if messagebox.askyesno("确认", "确定要删除选中的结构段吗？", parent=self._dialog_parent):
            del self.segments[real_index]
            self._refresh_tree()
    
    def _clear_segments(self):
        """清空结构段"""
        if messagebox.askyesno("确认", "确定要清空所有结构段吗？", parent=self._dialog_parent):
            self._init_default_segments()
    
    def _resolve_display_index(self, display_index: int):
        """
        将表格显示索引解析为 (source, real_index, segment)
        source: 'plan' 或 'longitudinal'
        real_index: 在对应列表中的真实索引
        """
        plan_count = len(self.plan_segments)
        if display_index < plan_count:
            return 'plan', display_index, self.plan_segments[display_index]
        else:
            real_idx = display_index - plan_count
            return 'longitudinal', real_idx, self.segments[real_idx]
    
    def _on_tree_double_click(self, event):
        """双击编辑"""
        selection = self.tree.selection()
        if not selection:
            return
        
        display_index = self.tree.index(selection[0])
        source, real_index, segment = self._resolve_display_index(display_index)
        
        # 平面段为只读，不允许编辑
        if source == 'plan':
            from tkinter import messagebox
            messagebox.showinfo("提示", 
                "平面段由推求水面线表格自动提取，不可手动编辑。\n"
                "如需修改请在推求水面线表格中调整坐标数据。",
                parent=self._dialog_parent)
            return
        
        # 以下为纵断面段的编辑逻辑
        index = real_index
        
        if segment.segment_type == SegmentType.INLET:
            dialog = InletShapeDialog(self._dialog_parent, segment)
            self.wait_window(dialog)
            if dialog.result:
                self.segments[index] = dialog.result
                self._refresh_tree()
            return
        
        if segment.segment_type == SegmentType.OUTLET:
            try:
                Q = float(self.entry_Q.get())
                v = float(self.entry_v.get())
            except ValueError:
                Q, v = 10.0, 2.0
            dialog = OutletShapeDialog(self._dialog_parent, segment, Q=Q, v=v)
            self.wait_window(dialog)
            if dialog.result:
                self.segments[index] = dialog.result
                self._refresh_tree()
            return
        
        if segment.locked:
            if not messagebox.askyesno("提示", "该行已锁定，确定要编辑吗？", parent=self._dialog_parent):
                return
        
        try:
            Q = float(self.entry_Q.get())
            v = float(self.entry_v.get())
        except ValueError:
            Q, v = 10.0, 2.0
        
        dialog = SegmentEditDialog(self._dialog_parent, "编辑结构段", segment, Q=Q, v=v)
        self.wait_window(dialog)
        
        if dialog.result:
            self.segments[index] = dialog.result
            self._refresh_tree()
    
    def _on_drag_start(self, event):
        """开始拖拽（仅限纵断面段）"""
        item = self.tree.identify_row(event.y)
        if not item:
            return
        
        display_index = self.tree.index(item)
        source, real_index, segment = self._resolve_display_index(display_index)
        
        # 平面段不允许拖拽
        if source == 'plan':
            self._drag_data = {'item': None, 'index': None, 'start_y': None}
            return
        
        # 纵断面段的首末行（进水口/出水口）不允许拖拽
        if real_index == 0 or real_index == len(self.segments) - 1:
            self._drag_data = {'item': None, 'index': None, 'start_y': None}
            return
        
        self._drag_data = {'item': item, 'index': display_index, 'start_y': event.y}
        self.tree.selection_set(item)
    
    def _on_drag_motion(self, event):
        """拖拽移动（仅限纵断面段内部排序）"""
        if not self._drag_data['item']:
            return
        
        target_item = self.tree.identify_row(event.y)
        if not target_item:
            return
        
        target_display_index = self.tree.index(target_item)
        current_display_index = self._drag_data['index']
        
        # 只允许在纵断面段内拖拽
        plan_count = len(self.plan_segments)
        target_source, target_real, _ = self._resolve_display_index(target_display_index)
        if target_source == 'plan':
            return
        if target_real == 0 or target_real == len(self.segments) - 1:
            return
        
        current_real = current_display_index - plan_count
        
        if target_real != current_real:
            self.segments[current_real], self.segments[target_real] = \
                self.segments[target_real], self.segments[current_real]
            self._drag_data['index'] = target_display_index
            self._refresh_tree()
            
            children = self.tree.get_children()
            if target_display_index < len(children):
                self._drag_data['item'] = children[target_display_index]
                self.tree.selection_set(children[target_display_index])
    
    def _on_drag_release(self, event):
        """拖拽释放"""
        self._drag_data = {'item': None, 'index': None, 'start_y': None}
    
    # ==================== 计算方法 ====================
    
    def _get_global_params(self) -> Optional[GlobalParameters]:
        """获取全局参数"""
        try:
            v_channel_in = float(self.entry_v_channel_in.get() or 0)
            
            v_pipe_in_str = self.entry_v_pipe_in.get().strip()
            if not v_pipe_in_str:
                if self.inlet_section_B is not None:
                    try:
                        Q = float(self.entry_Q.get())
                        v_pipe_in = self._calculate_trapezoidal_velocity(
                            self.inlet_section_B, self.inlet_section_h, self.inlet_section_m, Q)
                    except:
                        v_pipe_in = v_channel_in + 0.2
                else:
                    v_pipe_in = v_channel_in + 0.2
            else:
                v_pipe_in = float(v_pipe_in_str)
            
            params = GlobalParameters(
                Q=float(self.entry_Q.get()),
                v_guess=float(self.entry_v.get()),
                H_up=float(self.entry_H_up.get()),
                H_down=float(self.entry_H_down.get()),
                roughness_n=float(self.entry_n.get()),
                inlet_type=self._get_gradient_type_by_name(self.combo_inlet_type.get()),
                outlet_type=self._get_gradient_type_by_name(self.combo_outlet_type.get()),
                v_channel_in=v_channel_in,
                v_pipe_in=v_pipe_in,
                v_channel_out=float(self.entry_v_channel_out.get() or 0),
                v_pipe_out=float(self.entry_v_pipe_out.get() or 0),
                H_bottom_up=float(self.entry_H_bottom.get() or 0),
                xi_inlet=float(self.entry_xi_inlet.get()),
                xi_outlet=float(self.entry_xi_outlet.get())
            )
            return params
        except ValueError as e:
            messagebox.showerror("输入错误", f"参数格式错误\n{str(e)}", parent=self._dialog_parent)
            return None
    
    def _execute_calculation(self):
        """执行计算"""
        params = self._get_global_params()
        if params is None:
            return
        
        if params.Q <= 0:
            messagebox.showerror("输入错误", "设计流量必须大于0", parent=self._dialog_parent)
            return
        if params.v_guess <= 0:
            messagebox.showerror("输入错误", "拟定流速必须大于0", parent=self._dialog_parent)
            return
        
        diameter_override = None
        custom_d = self.entry_D_custom.get().strip()
        if custom_d:
            try:
                diameter_override = float(custom_d)
            except ValueError:
                messagebox.showerror("输入错误", "自定义管径格式错误", parent=self._dialog_parent)
                return
        
        try:
            result = HydraulicCore.execute_calculation(
                params,
                self.segments,
                diameter_override=diameter_override,
                verbose=self.show_detailed_process.get(),
                plan_segments=self.plan_segments,
                plan_total_length=self.plan_total_length,
                plan_feature_points=self.plan_feature_points,
                longitudinal_nodes=self.longitudinal_nodes,
            )
            self.calculation_result = result
            self._refresh_tree()
            self._show_result(result)
            
            # 触发回调
            if self.on_result_callback:
                self.on_result_callback(result)
                
        except Exception as e:
            messagebox.showerror("计算错误", f"计算过程发生错误:\n{str(e)}", parent=self._dialog_parent)
    
    def _show_result(self, result: CalculationResult):
        """显示计算结果"""
        result_window = tk.Toplevel(self._dialog_parent)
        result_window.title("计算结果")
        result_window.geometry("700x600")
        result_window.transient(self._dialog_parent)
        
        text_frame = ttk.Frame(result_window, padding=10)
        text_frame.pack(fill=tk.BOTH, expand=True)
        
        text = tk.Text(text_frame, wrap=tk.WORD, font=('Consolas', 10))
        scrollbar = ttk.Scrollbar(text_frame, orient='vertical', command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        result_text = HydraulicCore.format_result(result, show_steps=self.show_detailed_process.get())
        text.insert('1.0', result_text)
        text.config(state='disabled')
        
        ttk.Button(result_window, text="关闭", command=result_window.destroy).pack(pady=10)
    
    def _export_result(self):
        """导出结果"""
        if not self.calculation_result:
            messagebox.showwarning("提示", "请先执行计算", parent=self._dialog_parent)
            return
        
        file_path = filedialog.asksaveasfilename(
            title="保存结果",
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
            parent=self._dialog_parent
        )
        
        if not file_path:
            return
        
        try:
            result_text = HydraulicCore.format_result(
                self.calculation_result,
                show_steps=self.show_detailed_process.get()
            )
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(f"名称: {self.entry_job_name.get()}\n\n")
                f.write(result_text)
            messagebox.showinfo("导出成功", f"结果已保存到:\n{file_path}", parent=self._dialog_parent)
        except Exception as e:
            messagebox.showerror("导出失败", f"保存失败:\n{str(e)}", parent=self._dialog_parent)
    
    # ==================== 绘图方法 ====================
    
    def _on_canvas_resize(self, event):
        """画布大小改变"""
        self._draw_pipeline()
    
    def _zoom_in(self):
        """放大"""
        self.zoom_level = min(5.0, self.zoom_level * 1.2)
        self._update_zoom_label()
        self._draw_pipeline()
    
    def _zoom_out(self):
        """缩小"""
        self.zoom_level = max(0.2, self.zoom_level / 1.2)
        self._update_zoom_label()
        self._draw_pipeline()
    
    def _zoom_reset(self):
        """重置缩放"""
        self.zoom_level = 1.0
        self.pan_offset_x = 0
        self.pan_offset_y = 0
        self._update_zoom_label()
        self._draw_pipeline()
    
    def _zoom_fit(self):
        """适应窗口"""
        self.zoom_level = 1.0
        self.pan_offset_x = 0
        self.pan_offset_y = 0
        self._update_zoom_label()
        self._draw_pipeline()
    
    def _update_zoom_label(self):
        """更新缩放标签"""
        if hasattr(self, 'zoom_label'):
            self.zoom_label.config(text=f"{int(self.zoom_level * 100)}%")
    
    def _on_mouse_wheel(self, event):
        """鼠标滚轮缩放"""
        if event.num == 4 or (hasattr(event, 'delta') and event.delta > 0):
            factor = 1.15
        else:
            factor = 1 / 1.15
        
        new_zoom = self.zoom_level * factor
        if 0.2 <= new_zoom <= 5.0:
            self.zoom_level = new_zoom
            self._update_zoom_label()
            self._draw_pipeline()
    
    def _on_canvas_drag_start(self, event):
        """开始拖拽画布"""
        self._drag_start = (event.x, event.y)
    
    def _on_canvas_drag(self, event):
        """拖拽画布"""
        if self._drag_start:
            dx = event.x - self._drag_start[0]
            dy = event.y - self._drag_start[1]
            self.pan_offset_x += dx
            self.pan_offset_y += dy
            self._drag_start = (event.x, event.y)
            self._draw_pipeline()
    
    def _on_canvas_drag_end(self, event):
        """结束拖拽画布"""
        self._drag_start = None
    
    def _draw_pipeline(self):
        """绘制管道剖面图"""
        self.canvas.delete('all')
        
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        
        if width < 10 or height < 10:
            return
        
        # 收集所有坐标点
        all_coords = []
        for seg in self.segments:
            all_coords.extend(seg.coordinates)
        
        if not all_coords:
            # 如果没有坐标，根据长度生成简化图
            self._draw_simplified_pipeline(width, height)
            return
        
        # 计算边界
        xs = [c[0] for c in all_coords]
        ys = [c[1] for c in all_coords]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        
        # 获取水位信息用于扩展Y范围
        try:
            H_up = float(self.entry_H_up.get())
            H_down = float(self.entry_H_down.get())
            min_y = min(min_y, H_down - 5)
            max_y = max(max_y, H_up + 5)
        except:
            H_up = 100.0
            H_down = 98.0
        
        # 添加边距
        margin = 50
        data_width = max_x - min_x if max_x > min_x else 1
        data_height = max_y - min_y if max_y > min_y else 1
        
        # 应用缩放
        base_scale_x = (width - 2 * margin) / data_width
        base_scale_y = (height - 2 * margin) / data_height
        base_scale = min(base_scale_x, base_scale_y)
        scale = base_scale * self.zoom_level
        
        # 居中偏移 + 用户平移
        center_x = width / 2 + self.pan_offset_x
        center_y = height / 2 + self.pan_offset_y
        data_center_x = (min_x + max_x) / 2
        data_center_y = (min_y + max_y) / 2
        
        def transform(x, y):
            """坐标转换"""
            sx = center_x + (x - data_center_x) * scale
            sy = center_y - (y - data_center_y) * scale  # Y轴翻转
            return sx, sy
        
        # 绘制管道中心线
        points = []
        for coord in all_coords:
            points.append(transform(coord[0], coord[1]))
        
        if len(points) >= 2:
            # 绘制绿色管道线
            for i in range(len(points) - 1):
                self.canvas.create_line(
                    points[i][0], points[i][1],
                    points[i + 1][0], points[i + 1][1],
                    fill='#00FF00', width=3
                )
        
        # 绘制进出口形状
        if points:
            self._draw_inlet_shape(points[0][0], points[0][1], scale, is_inlet=True)
            self._draw_outlet_shape(points[-1][0], points[-1][1], scale, is_inlet=False)
        
        # 绘制增强的水位标注
        try:
            # 上游水位线和标注
            x_up, y_up = transform(min_x, H_up)
            line_length = 80 * self.zoom_level
            
            # 绘制上游水位线
            self.canvas.create_line(x_up - line_length/2, y_up, x_up + line_length/2, y_up, 
                                   fill='#00FFFF', width=2)
            # 绘制水位符号（倒三角）
            self._draw_water_symbol(x_up, y_up, "上游水位", H_up)
            
            # 下游水位线和标注
            x_down, y_down = transform(max_x, H_down)
            
            # 绘制下游水位线
            self.canvas.create_line(x_down - line_length/2, y_down, x_down + line_length/2, y_down,
                                   fill='#00FFFF', width=2)
            # 绘制水位符号（倒三角）
            self._draw_water_symbol(x_down, y_down, "下游水位", H_down)
        except:
            pass
        
        # 绘制底部信息
        total_length = sum(seg.length for seg in self.segments if seg.length > 0)
        info_text = f"总长度: {total_length:.1f}m | 结构段: {len(self.segments)} | 水位差: {H_up - H_down:.2f}m | 缩放: {int(self.zoom_level * 100)}%"
        self.canvas.create_text(width / 2, height - 10, text=info_text, fill='#AAAAAA', font=('', 9))
    
    def _draw_simplified_pipeline(self, width, height):
        """绘制简化的管道示意图 - 基于结构段动态生成倒虹吸剖面"""
        margin = 50
        
        # 计算总长度
        total_length = sum(seg.length for seg in self.segments if seg.length > 0)
        if total_length <= 0:
            total_length = 100
        
        # 获取水位信息
        try:
            H_up = float(self.entry_H_up.get())
            H_down = float(self.entry_H_down.get())
            H_bottom = float(self.entry_H_bottom.get())
        except:
            H_up = 100.0
            H_down = 98.0
            H_bottom = 95.0
        
        # 计算倒虹吸最低点高程（低于渠底，形成下凹）
        siphon_depth = max(5, (H_up - H_down) * 2)  # 下凹深度
        H_lowest = H_bottom - siphon_depth
        
        # 根据结构段生成管道路径点
        points = []
        segment_positions = []  # 记录每段的起点位置用于标注
        current_x = 0.0
        
        # 计算每段的水平位置
        seg_lengths = []
        for seg in self.segments:
            if seg.segment_type in [SegmentType.INLET, SegmentType.OUTLET]:
                seg_lengths.append(0)
            else:
                seg_lengths.append(seg.length if seg.length > 0 else 5)
        
        # 生成倒虹吸典型剖面：进口-下降段-底部-上升段-出口
        num_segs = len(self.segments)
        for i, seg in enumerate(self.segments):
            # 计算当前段在管道中的相对位置 (0~1)
            progress = current_x / total_length if total_length > 0 else 0
            
            # 使用正弦曲线生成平滑的倒虹吸剖面
            # y = H_bottom - depth * sin(pi * progress)，使中间最低
            current_y = H_bottom - siphon_depth * math.sin(math.pi * progress)
            
            segment_positions.append((current_x, current_y, seg.segment_type.value))
            points.append((current_x, current_y))
            
            # 更新x位置
            if seg.segment_type == SegmentType.INLET:
                pass  # 进水口不占长度
            elif seg.segment_type == SegmentType.OUTLET:
                pass  # 出水口不占长度
            else:
                current_x += seg.length if seg.length > 0 else 5
        
        # 添加出口终点
        if points:
            end_y = H_bottom - siphon_depth * math.sin(math.pi * 1.0)  # 应接近 H_bottom
            points.append((total_length, H_bottom - (H_up - H_down) * 0.5))
        
        # 如果点太少，补充中间点使曲线平滑
        if len(points) < 5:
            smooth_points = []
            for t in [0, 0.2, 0.4, 0.5, 0.6, 0.8, 1.0]:
                x = t * total_length
                y = H_bottom - siphon_depth * math.sin(math.pi * t)
                smooth_points.append((x, y))
            points = smooth_points
        
        # 计算坐标范围
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        
        # 扩展Y范围以包含水位线
        min_y = min(min_y, H_lowest - 2)
        max_y = max(max_y, H_up + 5)
        
        # 计算缩放比例
        data_width = max_x - min_x if max_x > min_x else 1
        data_height = max_y - min_y if max_y > min_y else 1
        
        # 应用缩放
        base_scale_x = (width - 2 * margin) / data_width
        base_scale_y = (height - 2 * margin) / data_height
        base_scale = min(base_scale_x, base_scale_y)
        scale = base_scale * self.zoom_level
        
        # 居中偏移 + 用户平移
        center_x = width / 2 + self.pan_offset_x
        center_y = height / 2 + self.pan_offset_y
        data_center_x = (min_x + max_x) / 2
        data_center_y = (min_y + max_y) / 2
        
        def transform(x, y):
            """坐标转换"""
            sx = center_x + (x - data_center_x) * scale
            sy = center_y - (y - data_center_y) * scale  # Y轴翻转
            return sx, sy
        
        # 绘制平滑的管道曲线
        canvas_points = [transform(p[0], p[1]) for p in points]
        if len(canvas_points) >= 2:
            # 使用平滑曲线绘制
            flat_points = []
            for pt in canvas_points:
                flat_points.extend([pt[0], pt[1]])
            if len(flat_points) >= 4:
                self.canvas.create_line(flat_points, fill='#00FF00', width=3, smooth=True)
        
        # 绘制结构段分界点和标注
        for i, (x, y, seg_name) in enumerate(segment_positions):
            cx, cy = transform(x, y)
            # 绘制节点
            self.canvas.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, fill='#00FF00', outline='white', width=1)
        
        # 标注进出口并绘制形状
        if canvas_points:
            start_pt = canvas_points[0]
            end_pt = canvas_points[-1]
            
            # 进水口形状和标注
            self._draw_inlet_shape(start_pt[0], start_pt[1], scale, is_inlet=True)
            self.canvas.create_text(start_pt[0], start_pt[1] - 45, text="进水口", fill='cyan', anchor='s', font=('', 9))
            
            # 出水口形状和标注
            self._draw_outlet_shape(end_pt[0], end_pt[1], scale, is_inlet=False)
            self.canvas.create_text(end_pt[0], end_pt[1] - 45, text="出水口", fill='cyan', anchor='s', font=('', 9))
        
        # 绘制增强的水位标注
        try:
            # 上游水位线和符号
            x_up, y_up = transform(min_x, H_up)
            line_length = 80 * self.zoom_level
            self.canvas.create_line(x_up - line_length/2, y_up, x_up + line_length/2, y_up, 
                                   fill='#00FFFF', width=2, dash=(5, 3))
            self._draw_water_symbol(x_up, y_up, "上游水位", H_up)
            
            # 下游水位线和符号
            x_down, y_down = transform(max_x, H_down)
            self.canvas.create_line(x_down - line_length/2, y_down, x_down + line_length/2, y_down,
                                   fill='#00FFFF', width=2, dash=(5, 3))
            self._draw_water_symbol(x_down, y_down, "下游水位", H_down)
            
            # 渠底高程参考线（虚线）
            x_b1, y_b = transform(min_x, H_bottom)
            x_b2, _ = transform(max_x, H_bottom)
            self.canvas.create_line(x_b1, y_b, x_b2, y_b, fill='#666666', width=1, dash=(3, 3))
            self.canvas.create_text(x_b1 + 5, y_b + 12, text=f"渠底 {H_bottom:.1f}m", fill='#888888', anchor='w', font=('', 8))
        except:
            pass
        
        # 绘制底部信息
        info_text = f"总长度: {total_length:.1f}m | 结构段: {len(self.segments)} | 水位差: {H_up - H_down:.2f}m | 缩放: {int(self.zoom_level * 100)}%"
        self.canvas.create_text(width / 2, height - 10, text=info_text, fill='#AAAAAA', font=('', 9))
    
    def _draw_water_triangle(self, x, y):
        """绘制倒三角水位符号"""
        size = 8
        points = [x, y - size, x - size, y + size, x + size, y + size]
        self.canvas.create_polygon(points, fill='#00FFFF', outline='#00FFFF')
    
    def _draw_water_symbol(self, x, y, label, value):
        """绘制增强的水位符号和标注"""
        # 绘制倒三角符号
        size = 10
        points = [x, y - size, x - size, y + size, x + size, y + size]
        self.canvas.create_polygon(points, fill='#00FFFF', outline='white', width=1)
        
        # 绘制水位数值标注
        self.canvas.create_text(x, y - size - 5, text=f"{label}", fill='#00FFFF', anchor='s', font=('', 9, 'bold'))
        self.canvas.create_text(x, y + size + 12, text=f"{value:.2f}m", fill='#FFFF00', anchor='n', font=('', 9))
    
    def _draw_inlet_shape(self, x, y, scale, is_inlet=True):
        """绘制进水口形状（纵剖面视图，按表L.1.4-2）"""
        # 从结构段获取进水口形状
        inlet_shape = None
        if self.segments and self.segments[0].segment_type == SegmentType.INLET:
            inlet_shape = self.segments[0].inlet_shape
        
        if inlet_shape is None:
            inlet_shape = InletOutletShape.SLIGHTLY_ROUNDED
        
        self._draw_inlet_profile(x, y, inlet_shape)
    
    def _draw_outlet_shape(self, x, y, scale, is_inlet=False):
        """绘制出水口形状（纵剖面视图，按表L.1.4-2）"""
        # 从结构段获取出水口形状
        outlet_shape = None
        if self.segments and self.segments[-1].segment_type == SegmentType.OUTLET:
            outlet_shape = self.segments[-1].outlet_shape
        
        if outlet_shape is None:
            outlet_shape = InletOutletShape.SLIGHTLY_ROUNDED
        
        self._draw_outlet_profile(x, y, outlet_shape)
    
    def _draw_inlet_profile(self, x, y, inlet_shape):
        """绘制进水口纵剖面形状
        
        根据表L.1.4-2绘制不同形状的进水口纵剖面：
        - 进口完全修圆：平滑的圆弧曲线入口（上半部分）
        - 进口稍微修圆：较小的圆弧入口（上半部分）
        - 进口没有修圆：直角入口（上半部分）
        注意：下半部分统一为平直线条
        """
        base_size = max(12, 20 * min(self.zoom_level, 2.0))
        wall_length = base_size * 2.0
        wall_thickness = 3
        
        # 管道口半高度
        pipe_half_height = base_size * 0.4
        
        if inlet_shape == InletOutletShape.FULLY_ROUNDED:
            # 进口完全修圆 - 大圆弧曲线（如图1第一行）
            curve_length = base_size * 1.2
            
            # 上部：绘制向左延伸的壁和圆弧入口
            # 外壁水平线
            self.canvas.create_line(x - wall_length, y - base_size, x - curve_length, y - base_size,
                                   fill='#00FF00', width=wall_thickness)
            # 圆弧曲线（从外壁到管口）- 使用多段线模拟平滑曲线
            points_upper = []
            for i in range(15):
                t = i / 14.0
                # 贝塞尔曲线效果
                cx = x - curve_length + curve_length * t
                cy = y - base_size + (base_size - pipe_half_height) * (t ** 0.5)
                points_upper.extend([cx, cy])
            if len(points_upper) >= 4:
                self.canvas.create_line(points_upper, fill='#00FF00', width=wall_thickness, smooth=True)
            
            # 下部：平直线条（从外壁直接延伸到管口位置）
            self.canvas.create_line(x - wall_length, y + pipe_half_height, x, y + pipe_half_height,
                                   fill='#00FF00', width=wall_thickness)
            
            # 绘制斜线填充表示墙体（仅上部）
            self._draw_hatch_lines(x - wall_length, y - base_size - 5, x - curve_length, y - base_size, is_upper=True)
            
        elif inlet_shape == InletOutletShape.SLIGHTLY_ROUNDED:
            # 进口稍微修圆 - 小圆弧（如图1第二行）
            curve_length = base_size * 0.6
            
            # 上部
            self.canvas.create_line(x - wall_length, y - base_size, x - curve_length, y - base_size,
                                   fill='#00FF00', width=wall_thickness)
            # 小圆弧
            points_upper = []
            for i in range(10):
                t = i / 9.0
                cx = x - curve_length + curve_length * t
                cy = y - base_size + (base_size - pipe_half_height) * (t ** 0.3)
                points_upper.extend([cx, cy])
            if len(points_upper) >= 4:
                self.canvas.create_line(points_upper, fill='#00FF00', width=wall_thickness, smooth=True)
            
            # 下部：平直线条（从外壁直接延伸到管口位置）
            self.canvas.create_line(x - wall_length, y + pipe_half_height, x, y + pipe_half_height,
                                   fill='#00FF00', width=wall_thickness)
            
            # 绘制斜线填充（仅上部）
            self._draw_hatch_lines(x - wall_length, y - base_size - 5, x - curve_length, y - base_size, is_upper=True)
            
        elif inlet_shape == InletOutletShape.NOT_ROUNDED:
            # 进口没有修圆 - 直角入口（如图1第三行）
            # 上部：直角
            self.canvas.create_line(x - wall_length, y - base_size, x, y - base_size,
                                   fill='#00FF00', width=wall_thickness)
            self.canvas.create_line(x, y - base_size, x, y - pipe_half_height,
                                   fill='#00FF00', width=wall_thickness)
            
            # 下部：平直线条（从外壁直接延伸到管口位置）
            self.canvas.create_line(x - wall_length, y + pipe_half_height, x, y + pipe_half_height,
                                   fill='#00FF00', width=wall_thickness)
            
            # 绘制斜线填充（仅上部）
            self._draw_hatch_lines(x - wall_length, y - base_size - 5, x, y - base_size, is_upper=True)
    
    def _draw_outlet_profile(self, x, y, outlet_shape):
        """绘制出水口纵剖面形状（向右延伸，镜像于进水口）
        
        根据表L.1.4-2绘制不同形状的出水口纵剖面：
        - 进口完全修圆：平滑的圆弧曲线出口（上半部分）
        - 进口稍微修圆：较小的圆弧出口（上半部分）
        - 进口没有修圆：直角出口（上半部分）
        注意：下半部分统一为平直线条
        """
        base_size = max(12, 20 * min(self.zoom_level, 2.0))
        wall_length = base_size * 2.0
        wall_thickness = 3
        
        # 管道口半高度
        pipe_half_height = base_size * 0.4
        
        if outlet_shape == InletOutletShape.FULLY_ROUNDED:
            # 进口完全修圆 - 大圆弧曲线（向右延伸）
            curve_length = base_size * 1.2
            
            # 上部：绘制向右延伸的壁和圆弧出口
            # 外壁水平线
            self.canvas.create_line(x + curve_length, y - base_size, x + wall_length, y - base_size,
                                   fill='#00FF00', width=wall_thickness)
            
            # 圆弧过渡（使用弧线）
            radius = base_size * 0.8
            self.canvas.create_arc(x + curve_length - radius, y - base_size, 
                                  x + curve_length + radius, y - base_size + 2*radius,
                                  start=270, extent=90, style='arc',
                                  outline='#00FF00', width=wall_thickness)
            
            # 内壁
            self.canvas.create_line(x, y - pipe_half_height, x + curve_length - radius, y - pipe_half_height,
                                   fill='#00FF00', width=wall_thickness)
            
            # 下部：平直线条（从管口直接延伸到外壁位置）
            self.canvas.create_line(x, y + pipe_half_height, x + wall_length, y + pipe_half_height,
                                   fill='#00FF00', width=wall_thickness)
            
            # 绘制斜线填充表示墙体（仅上部）
            self._draw_hatch_lines(x + curve_length, y - base_size - 5, x + wall_length, y - base_size, is_upper=True)
            
        elif outlet_shape == InletOutletShape.SLIGHTLY_ROUNDED:
            # 进口稍微修圆 - 小圆弧（向右延伸）
            curve_length = base_size * 0.6
            
            # 上部
            self.canvas.create_line(x + curve_length, y - base_size, x + wall_length, y - base_size,
                                   fill='#00FF00', width=wall_thickness)
            
            radius = base_size * 0.4
            self.canvas.create_arc(x + curve_length - radius, y - base_size,
                                  x + curve_length + radius, y - base_size + 2*radius,
                                  start=270, extent=90, style='arc',
                                  outline='#00FF00', width=wall_thickness)
            
            self.canvas.create_line(x, y - pipe_half_height, x + curve_length - radius, y - pipe_half_height,
                                   fill='#00FF00', width=wall_thickness)
            
            # 下部：平直线条（从管口直接延伸到外壁位置）
            self.canvas.create_line(x, y + pipe_half_height, x + wall_length, y + pipe_half_height,
                                   fill='#00FF00', width=wall_thickness)
            
            # 绘制斜线填充（仅上部）
            self._draw_hatch_lines(x + curve_length, y - base_size - 5, x + wall_length, y - base_size, is_upper=True)
            
        elif outlet_shape == InletOutletShape.NOT_ROUNDED:
            # 进口没有修圆 - 直角出口（向右延伸）
            # 上部：直角
            self.canvas.create_line(x, y - base_size, x + wall_length, y - base_size,
                                   fill='#00FF00', width=wall_thickness)
            self.canvas.create_line(x, y - base_size, x, y - pipe_half_height,
                                   fill='#00FF00', width=wall_thickness)
            
            # 下部：平直线条（从管口直接延伸到外壁位置）
            self.canvas.create_line(x, y + pipe_half_height, x + wall_length, y + pipe_half_height,
                                   fill='#00FF00', width=wall_thickness)
            
            # 绘制斜线填充（仅上部）
            self._draw_hatch_lines(x, y - base_size - 5, x + wall_length, y - base_size, is_upper=True)
    
    def _draw_hatch_lines(self, x1, y1, x2, y2, is_upper=True):
        """绘制斜线填充表示墙体截面"""
        # 斜线间距
        spacing = 6
        num_lines = int(abs(x2 - x1) / spacing)
        
        for i in range(num_lines + 1):
            lx = x1 + i * spacing
            if lx > x2:
                break
            # 绘制斜线
            if is_upper:
                self.canvas.create_line(lx, y2, lx + 5, y1, fill='#00FF00', width=1)
            else:
                self.canvas.create_line(lx, y1, lx + 5, y2, fill='#00FF00', width=1)


# ==================== 对话框类 ====================

class SegmentEditDialog(tk.Toplevel):
    """结构段编辑对话框"""
    
    def __init__(self, parent, title: str, segment: Optional[StructureSegment] = None, Q: float = 10.0, v: float = 2.0):
        super().__init__(parent)
        self.title(title)
        self.geometry("520x520")
        self.transient(parent)
        self.grab_set()
        
        self.result: Optional[StructureSegment] = None
        self.segment = segment
        self._user_modified_xi = False  # 标记用户是否手动修改了局部系数
        self._loading_data = False  # 标记是否正在加载数据，防止触发自动计算
        
        # 保存Q和v用于计算理论管径
        self._Q = Q
        self._v = v
        self._D_theory = self._calculate_theory_diameter()
        
        self._create_ui()
        
        if segment:
            self._load_segment(segment)
        else:
            # 添加新段时，也需要初始化字段状态（默认是直管，禁用半径和角度字段）
            self._on_type_changed()
        
        # 居中显示
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")
    
    def _calculate_theory_diameter(self) -> float:
        """根据Q和v计算理论管径"""
        if self._Q > 0 and self._v > 0:
            omega = self._Q / self._v
            return math.sqrt(4 * omega / math.pi)
        return 0.0
    
    def _create_ui(self):
        """创建界面"""
        frame = ttk.Frame(self, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)
        
        row = 0
        
        # 类型
        ttk.Label(frame, text="类型:").grid(row=row, column=0, sticky='e', pady=5)
        self.combo_type = ttk.Combobox(
            frame,
            values=[st.value for st in SegmentType if st not in [SegmentType.INLET, SegmentType.OUTLET]],
            state='readonly',
            width=20
        )
        self.combo_type.set(SegmentType.STRAIGHT.value)
        self.combo_type.grid(row=row, column=1, sticky='w', pady=5, padx=10)
        self.combo_type.bind('<<ComboboxSelected>>', self._on_type_changed)
        row += 1
        
        # 长度
        ttk.Label(frame, text="长度 (m):").grid(row=row, column=0, sticky='e', pady=5)
        self.entry_length = ttk.Entry(frame, width=20)
        self.entry_length.insert(0, "0.0")
        self.entry_length.grid(row=row, column=1, sticky='w', pady=5, padx=10)
        self.entry_length.bind('<KeyRelease>', self._on_geometry_param_changed)
        row += 1
        
        # 半径（弯管）
        ttk.Label(frame, text="拐弯半径 R (m):").grid(row=row, column=0, sticky='e', pady=5)
        self.entry_radius = ttk.Entry(frame, width=20)
        self.entry_radius.insert(0, "0.0")
        self.entry_radius.grid(row=row, column=1, sticky='w', pady=5, padx=10)
        self.entry_radius.bind('<KeyRelease>', self._on_geometry_param_changed)
        row += 1
        
        # 角度
        ttk.Label(frame, text="拐角 θ (°):").grid(row=row, column=0, sticky='e', pady=5)
        self.entry_angle = ttk.Entry(frame, width=20)
        self.entry_angle.insert(0, "0.0")
        self.entry_angle.grid(row=row, column=1, sticky='w', pady=5, padx=10)
        self.entry_angle.bind('<KeyRelease>', self._on_geometry_param_changed)
        row += 1
        
        # ===== 高程信息（仅纵断面直管段/折管段有效） =====
        self.label_start_elev = ttk.Label(frame, text="起点高程 (m):")
        self.label_start_elev.grid(row=row, column=0, sticky='e', pady=5)
        self.entry_start_elev = ttk.Entry(frame, width=20)
        self.entry_start_elev.grid(row=row, column=1, sticky='w', pady=5, padx=10)
        self.entry_start_elev.bind('<KeyRelease>', self._on_elevation_changed)
        row += 1
        
        self.label_end_elev = ttk.Label(frame, text="终点高程 (m):")
        self.label_end_elev.grid(row=row, column=0, sticky='e', pady=5)
        self.entry_end_elev = ttk.Entry(frame, width=20)
        self.entry_end_elev.grid(row=row, column=1, sticky='w', pady=5, padx=10)
        self.entry_end_elev.bind('<KeyRelease>', self._on_elevation_changed)
        row += 1
        
        # 空间长度（自动计算，只读）
        self.label_spatial = ttk.Label(frame, text="空间长度 (m):")
        self.label_spatial.grid(row=row, column=0, sticky='e', pady=5)
        spatial_frame = ttk.Frame(frame)
        spatial_frame.grid(row=row, column=1, columnspan=2, sticky='w', pady=5, padx=10)
        self.label_spatial_value = ttk.Label(spatial_frame, text="--", font=('', 9, 'bold'))
        self.label_spatial_value.pack(side=tk.LEFT)
        self.label_spatial_hint = ttk.Label(spatial_frame, text="  = √(L² + ΔH²)", font=('', 8), foreground='gray')
        self.label_spatial_hint.pack(side=tk.LEFT)
        row += 1
        
        # 局部系数
        ttk.Label(frame, text="局部系数:").grid(row=row, column=0, sticky='e', pady=5)
        xi_frame = ttk.Frame(frame)
        xi_frame.grid(row=row, column=1, columnspan=2, sticky='w', pady=5, padx=10)
        self.entry_xi = ttk.Entry(xi_frame, width=15)
        self.entry_xi.pack(side=tk.LEFT)
        self.entry_xi.bind('<KeyPress>', self._on_xi_manual_input)  # 标记用户手动输入
        self.label_xi_hint = ttk.Label(xi_frame, text="(可手动修改)", font=('', 8))
        self.label_xi_hint.pack(side=tk.LEFT, padx=5)
        
        # 拦污栅详细配置按钮（初始隐藏）
        self.btn_trash_rack_config = ttk.Button(xi_frame, text="详细配置", 
                                                 command=self._open_trash_rack_config)
        # 初始不显示
        row += 1
        
        # 拦污栅参数存储
        self.trash_rack_params: Optional[TrashRackParams] = None
        
        # 按钮
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=row, column=0, columnspan=3, pady=20)
        
        ttk.Button(btn_frame, text="确定", command=self._on_ok, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="取消", command=self.destroy, width=10).pack(side=tk.LEFT, padx=5)
    
    def _on_type_changed(self, event=None):
        """类型改变事件"""
        type_name = self.combo_type.get()
        
        # 管理高程字段可见性：仅直管和折管显示高程输入
        if type_name in (SegmentType.STRAIGHT.value, SegmentType.FOLD.value):
            self.label_start_elev.grid()
            self.entry_start_elev.grid()
            self.label_end_elev.grid()
            self.entry_end_elev.grid()
            self.label_spatial.grid()
            self.label_spatial_value.master.grid()  # spatial_frame
        elif type_name == SegmentType.BEND.value:
            # 弯管不需要高程（纵断面弯管的空间长度 = R*θ）
            self.label_start_elev.grid_remove()
            self.entry_start_elev.grid_remove()
            self.label_end_elev.grid_remove()
            self.entry_end_elev.grid_remove()
            self.label_spatial.grid()
            self.label_spatial_value.master.grid()
        else:
            self.label_start_elev.grid_remove()
            self.entry_start_elev.grid_remove()
            self.label_end_elev.grid_remove()
            self.entry_end_elev.grid_remove()
            self.label_spatial.grid_remove()
            self.label_spatial_value.master.grid_remove()
        
        # 默认启用长度字段（拦污栅、闸门槽、旁通管、其他除外）
        if type_name not in [SegmentType.TRASH_RACK.value, SegmentType.GATE_SLOT.value, 
                              SegmentType.BYPASS_PIPE.value, SegmentType.OTHER.value]:
            length_text = self.entry_length.get().strip()
            if length_text == "--":
                self.entry_length.config(state='normal')
                self.entry_length.delete(0, tk.END)
                self.entry_length.insert(0, "0.0")
            else:
                self.entry_length.config(state='normal')
        
        # 根据类型启用/禁用相关字段
        if type_name == SegmentType.BEND.value:
            self.entry_radius.config(state='normal')
            self.entry_angle.config(state='normal')
            self.entry_xi.config(state='normal')
            self.label_xi_hint.config(text="(留空则计算时自动确定)")
            self.btn_trash_rack_config.pack_forget()
            # 更新UI状态
            self._auto_calculate_xi()
        elif type_name == SegmentType.FOLD.value:
            # 折管没有弯曲半径，禁用并清空半径字段
            self.entry_radius.config(state='normal')  # 先启用才能清空
            self.entry_radius.delete(0, tk.END)
            self.entry_radius.insert(0, "--")
            self.entry_radius.config(state='disabled')
            self.entry_angle.config(state='normal')
            self.entry_xi.config(state='normal')
            self.label_xi_hint.config(text="(根据拐角θ自动计算)")
            self.btn_trash_rack_config.pack_forget()
            # 更新UI状态
            self._auto_calculate_xi()
        elif type_name == SegmentType.TRASH_RACK.value:
            # 拦污栅：只需要系数，禁用长度、半径和角度
            self.entry_length.config(state='normal')
            self.entry_length.delete(0, tk.END)
            self.entry_length.insert(0, "--")
            self.entry_length.config(state='disabled')
            
            self.entry_radius.config(state='normal')
            self.entry_radius.delete(0, tk.END)
            self.entry_radius.insert(0, "--")
            self.entry_radius.config(state='disabled')
            
            self.entry_angle.config(state='normal')
            self.entry_angle.delete(0, tk.END)
            self.entry_angle.insert(0, "--")
            self.entry_angle.config(state='disabled')
            
            self.entry_xi.config(state='readonly')  # 只读
            self.label_xi_hint.config(text="")
            self.btn_trash_rack_config.pack(side=tk.LEFT, padx=5)
            # 如果没有拦污栅参数，自动初始化默认参数
            if self.trash_rack_params is None:
                self.trash_rack_params = TrashRackParams()
            # 更新系数显示
            xi = CoefficientService.calculate_trash_rack_xi(self.trash_rack_params)
            self.entry_xi.config(state='normal')
            self.entry_xi.delete(0, tk.END)
            self.entry_xi.insert(0, f"{xi:.4f}")
            self.entry_xi.config(state='readonly')
        elif type_name == SegmentType.GATE_SLOT.value:
            # 闸门槽：只需要系数，禁用长度、半径和角度
            self.entry_length.config(state='normal')
            self.entry_length.delete(0, tk.END)
            self.entry_length.insert(0, "--")
            self.entry_length.config(state='disabled')
            
            self.entry_radius.config(state='normal')
            self.entry_radius.delete(0, tk.END)
            self.entry_radius.insert(0, "--")
            self.entry_radius.config(state='disabled')
            
            self.entry_angle.config(state='normal')
            self.entry_angle.delete(0, tk.END)
            self.entry_angle.insert(0, "--")
            self.entry_angle.config(state='disabled')
            
            self.entry_xi.config(state='normal')
            # 如果系数为空或用户未手动修改，设置默认值0.1
            if not self.entry_xi.get().strip() or not self._user_modified_xi:
                self.entry_xi.delete(0, tk.END)
                self.entry_xi.insert(0, "0.1")
                self._user_modified_xi = False
            self.label_xi_hint.config(text="灌排规范2018附录L：平板门门槽ξm= 0.05～0.15")
            self.btn_trash_rack_config.pack_forget()
        elif type_name == SegmentType.BYPASS_PIPE.value:
            # 旁通管：只需要系数，禁用长度、半径和角度
            self.entry_length.config(state='normal')
            self.entry_length.delete(0, tk.END)
            self.entry_length.insert(0, "--")
            self.entry_length.config(state='disabled')
            
            self.entry_radius.config(state='normal')
            self.entry_radius.delete(0, tk.END)
            self.entry_radius.insert(0, "--")
            self.entry_radius.config(state='disabled')
            
            self.entry_angle.config(state='normal')
            self.entry_angle.delete(0, tk.END)
            self.entry_angle.insert(0, "--")
            self.entry_angle.config(state='disabled')
            
            self.entry_xi.config(state='normal')
            # 如果系数为空或用户未手动修改，设置默认值0.1
            if not self.entry_xi.get().strip() or not self._user_modified_xi:
                self.entry_xi.delete(0, tk.END)
                self.entry_xi.insert(0, "0.1")
                self._user_modified_xi = False
            self.label_xi_hint.config(text="旁通管水头损失系数ξp\n冲沙、放空、进人孔等，一般采0.10")
            self.btn_trash_rack_config.pack_forget()
        elif type_name == SegmentType.STRAIGHT.value:
            # 直管：启用长度，禁用半径和角度，系数留空（沿程损失）
            self.entry_radius.config(state='normal')
            self.entry_radius.delete(0, tk.END)
            self.entry_radius.insert(0, "--")
            self.entry_radius.config(state='disabled')
            
            self.entry_angle.config(state='normal')
            self.entry_angle.delete(0, tk.END)
            self.entry_angle.insert(0, "--")
            self.entry_angle.config(state='disabled')
            
            self.entry_xi.config(state='normal')
            self.entry_xi.delete(0, tk.END)
            self.label_xi_hint.config(text="(直管无局部损失)")
            self.btn_trash_rack_config.pack_forget()
        else:
            # 其他类型：只需要系数，禁用长度、半径和角度
            self.entry_length.config(state='normal')
            self.entry_length.delete(0, tk.END)
            self.entry_length.insert(0, "--")
            self.entry_length.config(state='disabled')
            
            self.entry_radius.config(state='normal')
            self.entry_radius.delete(0, tk.END)
            self.entry_radius.insert(0, "--")
            self.entry_radius.config(state='disabled')
            
            self.entry_angle.config(state='normal')
            self.entry_angle.delete(0, tk.END)
            self.entry_angle.insert(0, "--")
            self.entry_angle.config(state='disabled')
            
            self.entry_xi.config(state='normal')
            # 如果系数为空或用户未手动修改，设置默认值0.1
            if not self.entry_xi.get().strip() or not self._user_modified_xi:
                self.entry_xi.delete(0, tk.END)
                self.entry_xi.insert(0, "0.1")
                self._user_modified_xi = False
            self.label_xi_hint.config(text="(默认值0.1，可手动修改)")
            self.btn_trash_rack_config.pack_forget()
    
    def _on_geometry_param_changed(self, event=None):
        """几何参数改变事件（长度、半径、角度）- 自动计算局部系数"""
        self._auto_calculate_xi()
        self._update_spatial_length()
    
    def _on_elevation_changed(self, event=None):
        """高程参数改变事件 - 重新计算空间长度"""
        self._update_spatial_length()
    
    def _update_spatial_length(self):
        """根据当前输入更新空间长度显示"""
        type_name = self.combo_type.get()
        try:
            length = float(self.entry_length.get() or 0)
        except ValueError:
            length = 0.0
        
        if type_name in (SegmentType.STRAIGHT.value, SegmentType.FOLD.value):
            try:
                start_e = float(self.entry_start_elev.get()) if self.entry_start_elev.get().strip() else None
                end_e = float(self.entry_end_elev.get()) if self.entry_end_elev.get().strip() else None
            except ValueError:
                start_e, end_e = None, None
            
            if start_e is not None and end_e is not None and length > 0:
                import math as _m
                dh = end_e - start_e
                sp = _m.sqrt(length ** 2 + dh ** 2)
                self.label_spatial_value.config(text=f"{sp:.3f}")
                self.label_spatial_hint.config(text=f"  = √({length:.2f}² + {dh:.2f}²)")
            elif length > 0:
                self.label_spatial_value.config(text=f"{length:.3f}")
                self.label_spatial_hint.config(text="  (无高程,取水平长度)")
            else:
                self.label_spatial_value.config(text="--")
                self.label_spatial_hint.config(text="  = √(L² + ΔH²)")
        elif type_name == SegmentType.BEND.value:
            try:
                radius = float(self.entry_radius.get() or 0)
                angle = float(self.entry_angle.get() or 0)
            except ValueError:
                radius, angle = 0, 0
            if radius > 0 and angle > 0:
                import math as _m
                arc = radius * _m.radians(angle)
                self.label_spatial_value.config(text=f"{arc:.3f}")
                self.label_spatial_hint.config(text=f"  = R×θ = {radius:.2f}×{angle:.1f}°")
            else:
                self.label_spatial_value.config(text="--")
                self.label_spatial_hint.config(text="  = R × θ(rad)")
        else:
            self.label_spatial_value.config(text="--")
            self.label_spatial_hint.config(text="")
    
    def _auto_calculate_xi(self):
        """根据当前输入的几何参数自动计算局部系数"""
        # 如果正在加载数据，不要重新计算，保留已加载的值
        if hasattr(self, '_loading_data') and self._loading_data:
            return
        
        type_name = self.combo_type.get()
        
        # 如果用户已经手动输入了系数，不要覆盖
        current_xi = self.entry_xi.get().strip()
        if current_xi and hasattr(self, '_user_modified_xi') and self._user_modified_xi:
            return
        
        if type_name == SegmentType.BEND.value:
            # 弯管：使用理论管径实时计算系数
            try:
                radius = float(self.entry_radius.get() or 0)
                angle = float(self.entry_angle.get() or 0)
                
                if radius > 0 and angle > 0 and self._D_theory > 0:
                    # 使用理论管径计算弯管系数
                    xi_bend = CoefficientService.calculate_bend_coeff(radius, self._D_theory, angle, verbose=False)
                    self.entry_xi.delete(0, tk.END)
                    self.entry_xi.insert(0, f"{xi_bend:.4f}")
                    self._user_modified_xi = False
                elif radius > 0 and angle > 0:
                    # 理论管径为0，无法计算，留空
                    self.entry_xi.delete(0, tk.END)
                    self._user_modified_xi = False
                else:
                    # 参数不完整，清空系数
                    self.entry_xi.delete(0, tk.END)
                    self._user_modified_xi = False
            except ValueError:
                pass
        
        elif type_name == SegmentType.FOLD.value:
            # 折管：根据公式 ζ = 0.9457 * sin²(θ/2) + 2.047 * sin⁴(θ/2) 计算
            try:
                angle = float(self.entry_angle.get() or 0)
                if angle > 0:
                    # 调用折管系数计算
                    xi_fold = CoefficientService.calculate_fold_coeff(angle, verbose=False)
                    self.entry_xi.delete(0, tk.END)
                    self.entry_xi.insert(0, f"{xi_fold:.4f}")
                    self._user_modified_xi = False
                else:
                    # 角度为0，清空系数
                    self.entry_xi.delete(0, tk.END)
                    self._user_modified_xi = False
            except ValueError:
                pass
    
    def _open_trash_rack_config(self):
        """打开拦污栅详细配置对话框"""
        dialog = TrashRackConfigDialog(self, self.trash_rack_params)
        self.wait_window(dialog)
        
        if dialog.result:
            self.trash_rack_params = dialog.result
            # 计算系数并更新显示
            xi = CoefficientService.calculate_trash_rack_xi(self.trash_rack_params)
            self.entry_xi.config(state='normal')
            self.entry_xi.delete(0, tk.END)
            self.entry_xi.insert(0, f"{xi:.4f}")
            self.entry_xi.config(state='readonly')
    
    def _on_xi_manual_input(self, event=None):
        """用户手动输入局部系数事件"""
        self._user_modified_xi = True  # 标记为用户手动修改
    
    def _load_segment(self, segment: StructureSegment):
        """加载现有结构段数据"""
        self._loading_data = True  # 开始加载数据，禁止自动计算
        
        # 如果是进出口，也允许编辑
        if segment.segment_type in [SegmentType.INLET, SegmentType.OUTLET]:
            self.combo_type.config(values=[st.value for st in SegmentType])
        
        self.combo_type.set(segment.segment_type.value)
        
        self.entry_length.delete(0, tk.END)
        self.entry_length.insert(0, f"{segment.length:.2f}")
        
        self.entry_radius.delete(0, tk.END)
        self.entry_radius.insert(0, f"{segment.radius:.2f}")
        
        self.entry_angle.delete(0, tk.END)
        self.entry_angle.insert(0, f"{segment.angle:.1f}")
        
        # 加载高程数据
        self.entry_start_elev.delete(0, tk.END)
        if segment.start_elevation is not None:
            self.entry_start_elev.insert(0, f"{segment.start_elevation:.2f}")
        
        self.entry_end_elev.delete(0, tk.END)
        if segment.end_elevation is not None:
            self.entry_end_elev.insert(0, f"{segment.end_elevation:.2f}")
        
        # 加载拦污栅参数
        if segment.trash_rack_params:
            self.trash_rack_params = segment.trash_rack_params
        
        if segment.xi_user is not None:
            self.entry_xi.delete(0, tk.END)
            self.entry_xi.insert(0, f"{segment.xi_user:.4f}")
            self._user_modified_xi = True  # 标记为用户输入
        elif segment.xi_calc is not None:
            self.entry_xi.delete(0, tk.END)
            self.entry_xi.insert(0, f"{segment.xi_calc:.4f}")
            self._user_modified_xi = False  # 标记为自动计算
        
        self._on_type_changed()
        self._update_spatial_length()  # 更新空间长度显示
        
        self._loading_data = False  # 加载完成，允许自动计算
    
    def _on_ok(self):
        """确定按钮"""
        try:
            type_name = self.combo_type.get()
            segment_type = None
            for st in SegmentType:
                if st.value == type_name:
                    segment_type = st
                    break
            
            if segment_type is None:
                messagebox.showerror("错误", "请选择类型")
                return
            
            # 长度可能显示为 "--"，需要特殊处理
            length_text = self.entry_length.get().strip()
            length = 0.0 if length_text == "--" or not length_text else float(length_text)
            
            # 半径和角度可能显示为 "--"，需要特殊处理
            radius_text = self.entry_radius.get().strip()
            radius = 0.0 if radius_text == "--" or not radius_text else float(radius_text)
            
            angle_text = self.entry_angle.get().strip()
            angle = 0.0 if angle_text == "--" or not angle_text else float(angle_text)
            
            xi_user = None
            xi_calc_new = None
            xi_text = self.entry_xi.get().strip()
            if xi_text:
                xi_value = float(xi_text)
                # 区分用户手动输入和自动计算
                if self._user_modified_xi:
                    # 用户手动输入的系数，保存为 xi_user
                    xi_user = xi_value
                else:
                    # 自动计算的系数，保存为 xi_calc，让 xi_user 保持为 None
                    # 这样点击计算后可以用设计管径重新计算并更新
                    xi_calc_new = xi_value
            
            # 弯管类型校验：必须输入半径和拐角
            if segment_type == SegmentType.BEND:
                if radius <= 0:
                    messagebox.showerror("输入错误", "弯管必须输入拐弯半径 R")
                    return
                if angle <= 0:
                    messagebox.showerror("输入错误", "弯管必须输入拐角 θ")
                    return
            
            # 拦污栅类型校验
            if segment_type == SegmentType.TRASH_RACK:
                if self.trash_rack_params is None:
                    messagebox.showwarning("提示", "请先点击\"详细配置\"按钮配置拦污栅参数")
                    return
            
            # 保留原有坐标和锁定状态
            coords = self.segment.coordinates if self.segment else []
            locked = self.segment.locked if self.segment else False
            # 如果有新计算的系数，使用新值；否则保留原有值
            xi_calc = xi_calc_new if xi_calc_new is not None else (self.segment.xi_calc if self.segment else None)
            
            # 解析高程数据
            start_elevation = None
            end_elevation = None
            start_elev_text = self.entry_start_elev.get().strip()
            end_elev_text = self.entry_end_elev.get().strip()
            if start_elev_text:
                try:
                    start_elevation = float(start_elev_text)
                except ValueError:
                    pass
            if end_elev_text:
                try:
                    end_elevation = float(end_elev_text)
                except ValueError:
                    pass
            
            # 保留原有方向属性
            direction = self.segment.direction if self.segment else SegmentDirection.LONGITUDINAL
            source_ip = self.segment.source_ip_index if self.segment else None
            
            self.result = StructureSegment(
                segment_type=segment_type,
                direction=direction,
                length=length,
                radius=radius,
                angle=angle,
                xi_user=xi_user,
                xi_calc=xi_calc,
                coordinates=coords,
                locked=locked,
                trash_rack_params=self.trash_rack_params if segment_type == SegmentType.TRASH_RACK else None,
                start_elevation=start_elevation,
                end_elevation=end_elevation,
                source_ip_index=source_ip,
            )
            
            self.destroy()
            
        except ValueError as e:
            messagebox.showerror("输入错误", f"请检查数值格式:\n{str(e)}")


class TrashRackConfigDialog(tk.Toplevel):
    """拦污栅详细参数配置对话框"""
    
    # 获取当前脚本所在目录
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    
    def __init__(self, parent, params: Optional[TrashRackParams] = None):
        super().__init__(parent)
        self.title("拦污栅详细参数配置")
        self.geometry("900x750")
        self.transient(parent)
        self.grab_set()
        
        self.result: Optional[TrashRackParams] = None
        self.params = params if params else TrashRackParams()
        
        # 形状系数映射（用于显示和高亮）
        self.shape_list = list(TrashRackBarShape)
        
        # 图片引用（防止被垃圾回收）
        self.img_figure = None
        self.img_table = None
        
        self._create_ui()
        self._load_params()
        self._update_result_preview()
        
        # 居中显示
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")
    
    def _create_ui(self):
        """创建界面 - 左参右图布局"""
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 使用PanedWindow创建可调整的左右分栏
        paned = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)
        
        # ===== 左侧：参数录入区 =====
        left_frame = ttk.Frame(paned, padding=5)
        paned.add(left_frame, weight=1)
        
        self._create_input_panel(left_frame)
        
        # ===== 右侧：规范参考区 =====
        right_frame = ttk.Frame(paned, padding=5)
        paned.add(right_frame, weight=1)
        
        self._create_reference_panel(right_frame)
    
    def _create_input_panel(self, parent):
        """创建左侧参数录入区"""
        # ===== 分组一：基础参数 =====
        group1 = ttk.LabelFrame(parent, text="基础参数", padding=10)
        group1.pack(fill=tk.X, pady=(0, 10))
        
        row = 0
        # 栅面倾角
        ttk.Label(group1, text="栅面倾角 (度):").grid(row=row, column=0, sticky='e', pady=3)
        self.entry_alpha = ttk.Entry(group1, width=15)
        self.entry_alpha.grid(row=row, column=1, sticky='w', pady=3, padx=5)
        self.entry_alpha.bind('<KeyRelease>', self._on_param_changed)
        ttk.Label(group1, text="0~180度，默认90", font=('', 8), foreground='#666666').grid(row=row, column=2, sticky='w')
        row += 1
        
        # 计算模式
        ttk.Label(group1, text="计算模式:").grid(row=row, column=0, sticky='e', pady=3)
        self.var_has_support = tk.BooleanVar(value=False)
        mode_frame = ttk.Frame(group1)
        mode_frame.grid(row=row, column=1, columnspan=2, sticky='w', pady=3)
        ttk.Radiobutton(mode_frame, text="无独立支墩 (公式L.1.4-2)", 
                       variable=self.var_has_support, value=False,
                       command=self._on_mode_changed).pack(anchor='w')
        ttk.Radiobutton(mode_frame, text="有独立支墩 (公式L.1.4-3)", 
                       variable=self.var_has_support, value=True,
                       command=self._on_mode_changed).pack(anchor='w')
        
        # ===== 分组二：栅条参数 =====
        group2 = ttk.LabelFrame(parent, text="栅条参数", padding=10)
        group2.pack(fill=tk.X, pady=(0, 10))
        
        row = 0
        # 栅条形状
        ttk.Label(group2, text="栅条形状:").grid(row=row, column=0, sticky='e', pady=3)
        shape_values = [f"{s.value} (beta={CoefficientService.get_trash_rack_bar_beta(s):.2f})" 
                       for s in self.shape_list]
        self.combo_bar_shape = ttk.Combobox(group2, values=shape_values, state='readonly', width=25)
        self.combo_bar_shape.grid(row=row, column=1, columnspan=2, sticky='w', pady=3, padx=5)
        self.combo_bar_shape.bind('<<ComboboxSelected>>', self._on_bar_shape_changed)
        row += 1
        
        # 栅条厚度
        ttk.Label(group2, text="栅条厚度 s1 (mm):").grid(row=row, column=0, sticky='e', pady=3)
        self.entry_s1 = ttk.Entry(group2, width=15)
        self.entry_s1.grid(row=row, column=1, sticky='w', pady=3, padx=5)
        self.entry_s1.bind('<KeyRelease>', self._on_param_changed)
        row += 1
        
        # 栅条间距
        ttk.Label(group2, text="栅条间距 b1 (mm):").grid(row=row, column=0, sticky='e', pady=3)
        self.entry_b1 = ttk.Entry(group2, width=15)
        self.entry_b1.grid(row=row, column=1, sticky='w', pady=3, padx=5)
        self.entry_b1.bind('<KeyRelease>', self._on_param_changed)
        row += 1
        
        # 阻塞比显示（仅显示数学表达式）
        ttk.Label(group2, text="s1/b1:").grid(row=row, column=0, sticky='e', pady=3)
        self.label_ratio1 = ttk.Label(group2, text="--", width=15, anchor='w')
        self.label_ratio1.grid(row=row, column=1, sticky='w', pady=3, padx=5)
        
        # ===== 分组三：支墩参数 =====
        self.group3 = ttk.LabelFrame(parent, text="支墩参数 (仅当有独立支墩时)", padding=10)
        self.group3.pack(fill=tk.X, pady=(0, 10))
        
        row = 0
        # 支墩形状
        ttk.Label(self.group3, text="支墩形状:").grid(row=row, column=0, sticky='e', pady=3)
        self.combo_support_shape = ttk.Combobox(self.group3, values=shape_values, state='readonly', width=25)
        self.combo_support_shape.grid(row=row, column=1, columnspan=2, sticky='w', pady=3, padx=5)
        self.combo_support_shape.bind('<<ComboboxSelected>>', self._on_support_shape_changed)
        row += 1
        
        # 支墩厚度
        ttk.Label(self.group3, text="支墩厚度 s2 (mm):").grid(row=row, column=0, sticky='e', pady=3)
        self.entry_s2 = ttk.Entry(self.group3, width=15)
        self.entry_s2.grid(row=row, column=1, sticky='w', pady=3, padx=5)
        self.entry_s2.bind('<KeyRelease>', self._on_param_changed)
        row += 1
        
        # 支墩净距
        ttk.Label(self.group3, text="支墩净距 b2 (mm):").grid(row=row, column=0, sticky='e', pady=3)
        self.entry_b2 = ttk.Entry(self.group3, width=15)
        self.entry_b2.grid(row=row, column=1, sticky='w', pady=3, padx=5)
        self.entry_b2.bind('<KeyRelease>', self._on_param_changed)
        row += 1
        
        # 阻塞比显示（仅显示数学表达式）
        ttk.Label(self.group3, text="s2/b2:").grid(row=row, column=0, sticky='e', pady=3)
        self.label_ratio2 = ttk.Label(self.group3, text="--", width=15, anchor='w')
        self.label_ratio2.grid(row=row, column=1, sticky='w', pady=3, padx=5)
        
        # ===== 底部：结果预览和手动模式 =====
        result_frame = ttk.LabelFrame(parent, text="计算结果", padding=(10, 10, 10, 15))
        result_frame.pack(fill=tk.X, pady=(0, 10))
        
        # 手动模式复选框
        self.var_manual = tk.BooleanVar(value=False)
        ttk.Checkbutton(result_frame, text="强制手动输入", 
                       variable=self.var_manual,
                       command=self._on_manual_mode_changed).pack(anchor='w')
        
        # 手动输入框
        manual_frame = ttk.Frame(result_frame)
        manual_frame.pack(fill=tk.X, pady=5)
        ttk.Label(manual_frame, text="手动输入 ξs:").pack(side=tk.LEFT)
        self.entry_manual_xi = ttk.Entry(manual_frame, width=15, state='disabled')
        self.entry_manual_xi.pack(side=tk.LEFT, padx=5)
        self.entry_manual_xi.bind('<KeyRelease>', self._on_param_changed)
        
        # 结果显示（增加底部padding确保文字完整显示）
        result_label_frame = ttk.Frame(result_frame)
        result_label_frame.pack(fill=tk.X, pady=(10, 5))
        ttk.Label(result_label_frame, text="计算结果 ξs:").pack(side=tk.LEFT)
        self.label_result = ttk.Label(result_label_frame, text="--", font=('Arial', 14, 'bold'),
                                      foreground='blue')
        self.label_result.pack(side=tk.LEFT, padx=10, pady=(0, 5))
        
        # ===== 按钮区（放在计算结果区域内，更容易看到）=====
        btn_frame = ttk.Frame(result_frame)
        btn_frame.pack(fill=tk.X, pady=(10, 5))
        
        ttk.Button(btn_frame, text="确定", command=self._on_ok, width=12).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="取消", command=self.destroy, width=12).pack(side=tk.LEFT, padx=5)
        
        # 初始化支墩区域状态
        self._on_mode_changed()
    
    def _create_reference_panel(self, parent):
        """创建右侧规范参考区"""
        # ===== 上部：栅条形状示意图 =====
        fig_frame = ttk.LabelFrame(parent, text="栅条形状示意图 (图 L.1.4-1)", padding=5)
        fig_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))
        
        # 图片显示
        fig_canvas = tk.Canvas(fig_frame, bg='white', height=200)
        fig_canvas.pack(fill=tk.BOTH, expand=True)
        self.fig_canvas = fig_canvas
        
        # 绑定双击事件查看大图
        fig_canvas.bind('<Double-Button-1>', self._show_large_image)
        
        # 添加双击提示文字
        hint_label = ttk.Label(fig_frame, text="(双击图片可放大查看)", 
                               font=('', 8), foreground='gray')
        hint_label.pack(anchor='center', pady=(2, 0))
        
        # 加载图片（延迟加载以获取正确的画布尺寸）
        fig_canvas.bind('<Configure>', self._on_canvas_resize)
        
        # ===== 下部：形状系数表 =====
        table_frame = ttk.LabelFrame(parent, text="形状系数表 (表 L.1.4-1)", padding=5)
        table_frame.pack(fill=tk.BOTH, expand=True)
        
        # 创建表格
        columns = ('形状名称', '系数 beta')
        self.ref_tree = ttk.Treeview(table_frame, columns=columns, show='headings', height=8)
        
        self.ref_tree.heading('形状名称', text='形状名称')
        self.ref_tree.heading('系数 beta', text='系数 beta')
        
        self.ref_tree.column('形状名称', width=150, anchor='center')
        self.ref_tree.column('系数 beta', width=100, anchor='center')
        
        scrollbar = ttk.Scrollbar(table_frame, orient='vertical', command=self.ref_tree.yview)
        self.ref_tree.configure(yscrollcommand=scrollbar.set)
        
        self.ref_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 填充表格数据
        for shape in self.shape_list:
            beta = CoefficientService.get_trash_rack_bar_beta(shape)
            self.ref_tree.insert('', 'end', values=(shape.value, f"{beta:.2f}"))
        
        # 绑定点击事件（可选高级功能：点击表格行同步下拉框）
        self.ref_tree.bind('<<TreeviewSelect>>', self._on_table_select)
    
    def _on_canvas_resize(self, event=None):
        """画布大小改变时重新加载图片"""
        # 防止重复调用
        if hasattr(self, '_resize_pending'):
            self.after_cancel(self._resize_pending)
        self._resize_pending = self.after(100, self._load_figure_image)
    
    def _load_figure_image(self):
        """加载栅条形状示意图 - 自适应填充画布"""
        if not PIL_AVAILABLE:
            self.fig_canvas.delete('all')
            self.fig_canvas.create_text(
                200, 100, text="PIL库未安装，无法显示图片",
                fill='gray', justify='center'
            )
            return
        
        try:
            # 清除画布
            self.fig_canvas.delete('all')
            
            img_path = os.path.join(self.SCRIPT_DIR, "图L.1.4-1.png")
            if os.path.exists(img_path):
                img = Image.open(img_path)
                
                # 获取画布实际尺寸
                canvas_width = self.fig_canvas.winfo_width()
                canvas_height = self.fig_canvas.winfo_height()
                
                # 如果画布尺寸还未确定，使用默认值
                if canvas_width <= 1:
                    canvas_width = 400
                if canvas_height <= 1:
                    canvas_height = 200
                
                # 计算缩放比例，保持纵横比并尽量填充画布（留10px边距）
                img_width, img_height = img.size
                padding = 10
                available_width = canvas_width - padding * 2
                available_height = canvas_height - padding * 2
                
                ratio = min(available_width / img_width, available_height / img_height)
                new_width = int(img_width * ratio)
                new_height = int(img_height * ratio)
                
                # 缩放图片
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                self.img_figure = ImageTk.PhotoImage(img)
                
                # 居中显示
                self.fig_canvas.create_image(
                    canvas_width // 2, canvas_height // 2,
                    image=self.img_figure, anchor='center'
                )
            else:
                self.fig_canvas.create_text(
                    200, 100, text="图片未找到\n请确保 图L.1.4-1.png 在程序目录下",
                    fill='gray', justify='center'
                )
        except Exception as e:
            self.fig_canvas.create_text(
                200, 100, text=f"加载图片失败: {str(e)}",
                fill='red', justify='center'
            )
    
    def _show_large_image(self, event=None):
        """双击显示大图"""
        if not PIL_AVAILABLE:
            messagebox.showwarning("提示", "PIL库未安装，无法显示图片")
            return
        
        try:
            img_path = os.path.join(self.SCRIPT_DIR, "图L.1.4-1.png")
            if not os.path.exists(img_path):
                messagebox.showwarning("提示", "图片文件未找到")
                return
            
            # 创建大图窗口
            large_win = tk.Toplevel(self)
            large_win.title("栅条形状示意图 (图 L.1.4-1)")
            large_win.transient(self)
            large_win.grab_set()
            
            # 加载原始图片
            img = Image.open(img_path)
            
            # 获取屏幕尺寸，限制最大显示尺寸
            screen_width = self.winfo_screenwidth()
            screen_height = self.winfo_screenheight()
            max_width = int(screen_width * 0.8)
            max_height = int(screen_height * 0.8)
            
            # 如果图片太大，按比例缩放
            img_width, img_height = img.size
            if img_width > max_width or img_height > max_height:
                ratio = min(max_width / img_width, max_height / img_height)
                new_width = int(img_width * ratio)
                new_height = int(img_height * ratio)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # 显示图片
            self.large_img = ImageTk.PhotoImage(img)
            canvas = tk.Canvas(large_win, width=img.width, height=img.height, bg='white')
            canvas.pack(padx=10, pady=10)
            canvas.create_image(img.width // 2, img.height // 2, image=self.large_img, anchor='center')
            
            # 添加关闭按钮
            ttk.Button(large_win, text="关闭", command=large_win.destroy, width=15).pack(pady=10)
            
            # 居中显示
            large_win.update_idletasks()
            x = (screen_width - large_win.winfo_width()) // 2
            y = (screen_height - large_win.winfo_height()) // 2
            large_win.geometry(f"+{x}+{y}")
            
        except Exception as e:
            messagebox.showerror("错误", f"无法显示大图: {str(e)}")
    
    def _load_params(self):
        """加载现有参数"""
        # 基础参数
        self.entry_alpha.insert(0, f"{self.params.alpha:.1f}")
        self.var_has_support.set(self.params.has_support)
        
        # 栅条参数
        bar_idx = self.shape_list.index(self.params.bar_shape)
        self.combo_bar_shape.current(bar_idx)
        self.entry_s1.insert(0, f"{self.params.s1:.1f}")
        self.entry_b1.insert(0, f"{self.params.b1:.1f}")
        
        # 支墩参数
        support_idx = self.shape_list.index(self.params.support_shape)
        self.combo_support_shape.current(support_idx)
        self.entry_s2.insert(0, f"{self.params.s2:.1f}")
        self.entry_b2.insert(0, f"{self.params.b2:.1f}")
        
        # 手动模式
        self.var_manual.set(self.params.manual_mode)
        if self.params.manual_mode:
            self.entry_manual_xi.config(state='normal')
            self.entry_manual_xi.insert(0, f"{self.params.manual_xi:.4f}")
        
        # 更新UI状态
        self._on_mode_changed()
    
    def _on_mode_changed(self):
        """计算模式改变"""
        has_support = self.var_has_support.get()
        # 启用/禁用支墩参数区域 - 直接设置各控件状态
        entry_state = 'normal' if has_support else 'disabled'
        combo_state = 'readonly' if has_support else 'disabled'
        
        self.combo_support_shape.config(state=combo_state)
        self.entry_s2.config(state=entry_state)
        self.entry_b2.config(state=entry_state)
        
        self._update_result_preview()
    
    def _on_bar_shape_changed(self, event=None):
        """栅条形状改变"""
        self._update_result_preview()
    
    def _on_support_shape_changed(self, event=None):
        """支墩形状改变 - 独立工作，不影响栅条形状"""
        self._update_result_preview()
    
    def _on_param_changed(self, event=None):
        """参数改变时更新预览"""
        self._update_ratio_display()
        self._update_result_preview()
    
    def _on_manual_mode_changed(self):
        """手动模式改变"""
        manual = self.var_manual.get()
        self.entry_manual_xi.config(state='normal' if manual else 'disabled')
        self._update_result_preview()
    
    def _on_table_select(self, event=None):
        """表格选择事件 - 同步下拉框"""
        selection = self.ref_tree.selection()
        if selection:
            item = selection[0]
            idx = self.ref_tree.index(item)
            self.combo_bar_shape.current(idx)
            self._update_result_preview()
    
    def _update_ratio_display(self):
        """更新阻塞比显示"""
        try:
            s1 = float(self.entry_s1.get() or 0)
            b1 = float(self.entry_b1.get() or 1)
            if b1 > 0:
                self.label_ratio1.config(text=f"{s1/b1:.4f}")
            else:
                self.label_ratio1.config(text="错误: b1=0")
        except:
            self.label_ratio1.config(text="--")
        
        try:
            s2 = float(self.entry_s2.get() or 0)
            b2 = float(self.entry_b2.get() or 1)
            if b2 > 0:
                self.label_ratio2.config(text=f"{s2/b2:.4f}")
            else:
                self.label_ratio2.config(text="错误: b2=0")
        except:
            self.label_ratio2.config(text="--")
    
    def _update_result_preview(self):
        """更新计算结果预览"""
        try:
            params = self._collect_params()
            if params is None:
                self.label_result.config(text="参数错误", foreground='red')
                return
            
            xi = CoefficientService.calculate_trash_rack_xi(params)
            if xi < 0:
                # 计算出负数，不合理
                self.label_result.config(text="负数(不合理)", foreground='red')
            elif xi == 0.0 and not params.manual_mode:
                # 可能是错误
                self.label_result.config(text="Error", foreground='red')
            else:
                self.label_result.config(text=f"{xi:.4f}", foreground='blue')
        except Exception as e:
            self.label_result.config(text=f"错误: {str(e)}", foreground='red')
    
    def _collect_params(self) -> Optional[TrashRackParams]:
        """收集界面参数"""
        try:
            alpha = float(self.entry_alpha.get() or 90)
            # 验证角度范围
            if alpha < 0 or alpha > 180:
                return None
            has_support = self.var_has_support.get()
            
            bar_idx = self.combo_bar_shape.current()
            bar_shape = self.shape_list[bar_idx] if bar_idx >= 0 else TrashRackBarShape.RECTANGULAR
            beta1 = CoefficientService.get_trash_rack_bar_beta(bar_shape)
            s1 = float(self.entry_s1.get() or 0)
            b1 = float(self.entry_b1.get() or 0)
            
            support_idx = self.combo_support_shape.current()
            support_shape = self.shape_list[support_idx] if support_idx >= 0 else TrashRackBarShape.RECTANGULAR
            beta2 = CoefficientService.get_trash_rack_bar_beta(support_shape)
            s2 = float(self.entry_s2.get() or 0)
            b2 = float(self.entry_b2.get() or 0)
            
            manual_mode = self.var_manual.get()
            manual_xi = float(self.entry_manual_xi.get() or 0) if manual_mode else 0.0
            
            return TrashRackParams(
                alpha=alpha,
                has_support=has_support,
                bar_shape=bar_shape,
                beta1=beta1,
                s1=s1,
                b1=b1,
                support_shape=support_shape,
                beta2=beta2,
                s2=s2,
                b2=b2,
                manual_mode=manual_mode,
                manual_xi=manual_xi
            )
        except ValueError:
            return None
    
    def _on_ok(self):
        """确定按钮"""
        params = self._collect_params()
        if params is None:
            messagebox.showerror("输入错误", "请检查数值格式\n栅面倾角必须在0~180度范围内")
            return
        
        # 参数校验：角度范围
        if params.alpha < 0 or params.alpha > 180:
            messagebox.showerror("输入错误", "栅面倾角必须在0~180度范围内")
            return
        
        # 参数校验：栅条间距
        if params.b1 <= 0:
            messagebox.showerror("输入错误", "栅条间距 b1 必须大于0")
            return
        
        # 参数校验：支墩净距
        if params.has_support and params.b2 <= 0:
            messagebox.showerror("输入错误", "支墩净距 b2 必须大于0")
            return
        
        # 计算系数检验：不得为负数
        xi = CoefficientService.calculate_trash_rack_xi(params)
        if xi < 0:
            messagebox.showerror("计算错误", f"计算出的系数为负数({xi:.4f})，不符合工程实际\n请检查参数设置，特别是栅面倾角")
            return
        
        self.result = params
        self.destroy()


class InletSectionDialog(tk.Toplevel):
    """进口渐变段断面参数设置对话框"""
    
    def __init__(self, parent, Q: float, B: float = None, h: float = None, m: float = None):
        super().__init__(parent)
        self.title("进口渐变段末端断面参数设置")
        self.geometry("480x420")  # 增加高度以完整显示所有内容和按钮
        self.transient(parent)
        self.grab_set()
        
        self.Q = Q
        self.result_B = B
        self.result_h = h
        self.result_m = m
        self.result_velocity = None
        
        self._create_ui()
        
        # 如果有现有值，加载它们
        if B is not None:
            self.entry_B.insert(0, str(B))
        if h is not None:
            self.entry_h.insert(0, str(h))
        if m is not None:
            self.entry_m.insert(0, str(m))
        
        # 如果有完整参数，计算并显示流速
        if B is not None and h is not None and m is not None:
            self._calculate_velocity()
        
        # 居中显示
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")
    
    def _create_ui(self):
        """创建界面"""
        frame = ttk.Frame(self, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题说明
        ttk.Label(
            frame, 
            text="设置渐变段末端断面参数，自动计算该断面流速", 
            font=('Microsoft YaHei', 10, 'bold')
        ).pack(anchor='w', pady=(0, 15))
        
        # 参数输入区
        input_frame = ttk.Frame(frame)
        input_frame.pack(fill=tk.X, pady=10)
        
        row = 0
        # 底宽B
        ttk.Label(input_frame, text="渐变段末端底宽B (m):").grid(row=row, column=0, sticky='e', pady=8, padx=5)
        self.entry_B = ttk.Entry(input_frame, width=20)
        self.entry_B.grid(row=row, column=1, sticky='w', pady=8, padx=5)
        self.entry_B.bind('<KeyRelease>', lambda e: self._calculate_velocity())
        row += 1
        
        # 水深h
        ttk.Label(input_frame, text="渐变段末端水深h (m):").grid(row=row, column=0, sticky='e', pady=8, padx=5)
        self.entry_h = ttk.Entry(input_frame, width=20)
        self.entry_h.grid(row=row, column=1, sticky='w', pady=8, padx=5)
        self.entry_h.bind('<KeyRelease>', lambda e: self._calculate_velocity())
        row += 1
        
        # 边坡比m
        ttk.Label(input_frame, text="渐变段边坡比m:").grid(row=row, column=0, sticky='e', pady=8, padx=5)
        self.entry_m = ttk.Entry(input_frame, width=20)
        self.entry_m.grid(row=row, column=1, sticky='w', pady=8, padx=5)
        self.entry_m.bind('<KeyRelease>', lambda e: self._calculate_velocity())
        tk.Label(input_frame, text="(1:m，如1.5表示1:1.5)", fg='#666666', font=('Microsoft YaHei', 8)).grid(row=row, column=2, sticky='w', pady=8)
        row += 1
        
        # 计算结果显示
        result_frame = ttk.LabelFrame(frame, text="计算结果", padding=10)
        result_frame.pack(fill=tk.X, pady=15)
        
        ttk.Label(result_frame, text="断面面积 A = (B + m×h) × h").pack(anchor='w', pady=2)
        ttk.Label(result_frame, text="流速 v₂ = Q / A").pack(anchor='w', pady=2)
        
        self.label_result = ttk.Label(result_frame, text="请输入完整参数", font=('Microsoft YaHei', 10, 'bold'), foreground='#0066CC')
        self.label_result.pack(anchor='w', pady=(5, 0))
        
        # 按钮区
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=(15, 0))
        
        ttk.Button(btn_frame, text="确定", command=self._on_ok, width=12).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="清除", command=self._on_clear, width=12).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="取消", command=self._on_cancel, width=12).pack(side=tk.LEFT, padx=5)
    
    def _calculate_velocity(self):
        """计算流速"""
        try:
            B_str = self.entry_B.get().strip()
            h_str = self.entry_h.get().strip()
            m_str = self.entry_m.get().strip()
            
            if not B_str or not h_str or not m_str:
                self.label_result.config(text="请输入完整参数", foreground='#666666')
                self.result_velocity = None
                return
            
            B = float(B_str)
            h = float(h_str)
            m = float(m_str)
            
            if B <= 0 or h <= 0 or m < 0:
                self.label_result.config(text="参数值必须大于0", foreground='#FF0000')
                self.result_velocity = None
                return
            
            # 计算断面面积
            area = (B + m * h) * h
            if area <= 0:
                self.label_result.config(text="断面面积必须大于0", foreground='#FF0000')
                self.result_velocity = None
                return
            
            # 计算流速
            velocity = self.Q / area
            self.result_velocity = velocity
            
            self.label_result.config(
                text=f"计算结果：v₂ = {velocity:.4f} m/s (A = {area:.4f} m²)",
                foreground='#00AA00'
            )
            
        except ValueError:
            self.label_result.config(text="参数格式错误，请输入有效数字", foreground='#FF0000')
            self.result_velocity = None
    
    def _on_ok(self):
        """确定按钮"""
        try:
            B_str = self.entry_B.get().strip()
            h_str = self.entry_h.get().strip()
            m_str = self.entry_m.get().strip()
            
            # 允许空值（清除断面参数）
            if not B_str and not h_str and not m_str:
                self.result_B = None
                self.result_h = None
                self.result_m = None
                self.result_velocity = None
                self.destroy()
                return
            
            # 如果填了任何一个，必须全部填写
            if not B_str or not h_str or not m_str:
                messagebox.showwarning("输入不完整", "请输入完整的断面参数（B、h、m），\n或点击'清除'按钮移除所有参数")
                return
            
            B = float(B_str)
            h = float(h_str)
            m = float(m_str)
            
            if B <= 0 or h <= 0 or m < 0:
                messagebox.showerror("参数错误", "B、h必须大于0，m不能为负数")
                return
            
            # 保存结果
            self.result_B = B
            self.result_h = h
            self.result_m = m
            
            # 计算流速
            area = (B + m * h) * h
            self.result_velocity = self.Q / area
            
            self.destroy()
            
        except ValueError:
            messagebox.showerror("输入错误", "请输入有效的数字")
    
    def _on_clear(self):
        """清除按钮 - 清空所有输入"""
        self.entry_B.delete(0, tk.END)
        self.entry_h.delete(0, tk.END)
        self.entry_m.delete(0, tk.END)
        self.label_result.config(text="已清除参数", foreground='#666666')
        self.result_velocity = None
    
    def _on_cancel(self):
        """取消按钮"""
        self.result_B = None
        self.result_h = None
        self.result_m = None
        self.result_velocity = None
        self.destroy()


class InletShapeDialog(tk.Toplevel):
    """进水口形状选择对话框"""
    
    def __init__(self, parent, segment: StructureSegment):
        super().__init__(parent)
        self.title("进水口形状设置")
        self.geometry("450x380")
        self.transient(parent)
        self.grab_set()
        
        self.result: Optional[StructureSegment] = None
        self.segment = segment
        
        self._create_ui()
        
        # 居中显示
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")
    
    def _create_ui(self):
        """创建界面"""
        frame = ttk.Frame(self, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题说明
        ttk.Label(frame, text="根据表L.1.4-2选择进水口形状", font=('', 10, 'bold')).pack(anchor='w', pady=(0, 10))
        
        # 形状选择
        shape_frame = ttk.LabelFrame(frame, text="进水口形状", padding=10)
        shape_frame.pack(fill=tk.X, pady=5)
        
        self.shape_var = tk.StringVar()
        current_shape = self.segment.inlet_shape if self.segment.inlet_shape else InletOutletShape.SLIGHTLY_ROUNDED
        self.shape_var.set(current_shape.value)
        
        # 三种形状选项，显示对应系数范围
        shapes_info = [
            (InletOutletShape.FULLY_ROUNDED, "ξ = 0.05 ~ 0.10"),
            (InletOutletShape.SLIGHTLY_ROUNDED, "ξ = 0.20 ~ 0.25"),
            (InletOutletShape.NOT_ROUNDED, "ξ = 0.50"),
        ]
        
        for shape, coeff_text in shapes_info:
            rb_frame = ttk.Frame(shape_frame)
            rb_frame.pack(fill=tk.X, pady=3)
            
            rb = ttk.Radiobutton(rb_frame, text=shape.value, variable=self.shape_var, 
                                value=shape.value, command=self._on_shape_changed)
            rb.pack(side=tk.LEFT)
            
            ttk.Label(rb_frame, text=coeff_text, foreground='#666666').pack(side=tk.LEFT, padx=(20, 0))
        
        # 系数输入
        coeff_frame = ttk.LabelFrame(frame, text="局部阻力系数 ξ", padding=10)
        coeff_frame.pack(fill=tk.X, pady=10)
        
        coeff_row = ttk.Frame(coeff_frame)
        coeff_row.pack(fill=tk.X)
        
        ttk.Label(coeff_row, text="系数值:").pack(side=tk.LEFT)
        self.entry_xi = ttk.Entry(coeff_row, width=15)
        self.entry_xi.pack(side=tk.LEFT, padx=10)
        
        # 显示当前系数
        current_xi = self.segment.xi_user if self.segment.xi_user is not None else self.segment.xi_calc
        if current_xi is not None:
            self.entry_xi.insert(0, f"{current_xi:.4f}")
        else:
            self._update_default_xi()
        
        self.label_range = ttk.Label(coeff_frame, text="", foreground='#888888')
        self.label_range.pack(anchor='w', pady=(5, 0))
        self._update_range_hint()
        
        # 按钮
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=(20, 0))
        
        ttk.Button(btn_frame, text="确定", command=self._on_ok, width=10).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="取消", command=self.destroy, width=10).pack(side=tk.RIGHT, padx=5)
    
    def _on_shape_changed(self):
        """形状改变事件"""
        self._update_default_xi()
        self._update_range_hint()
    
    def _update_default_xi(self):
        """更新默认系数值"""
        shape = self._get_selected_shape()
        if shape:
            coeff_range = INLET_SHAPE_COEFFICIENTS[shape]
            default_xi = sum(coeff_range) / 2  # 取中值
            self.entry_xi.delete(0, tk.END)
            self.entry_xi.insert(0, f"{default_xi:.4f}")
    
    def _update_range_hint(self):
        """更新系数范围提示"""
        shape = self._get_selected_shape()
        if shape:
            coeff_range = INLET_SHAPE_COEFFICIENTS[shape]
            if coeff_range[0] == coeff_range[1]:
                hint = f"建议值: {coeff_range[0]:.2f}"
            else:
                hint = f"建议范围: {coeff_range[0]:.2f} ~ {coeff_range[1]:.2f}"
            self.label_range.config(text=hint)
    
    def _get_selected_shape(self) -> Optional[InletOutletShape]:
        """获取选中的形状"""
        shape_value = self.shape_var.get()
        for shape in InletOutletShape:
            if shape.value == shape_value:
                return shape
        return None
    
    def _on_ok(self):
        """确定按钮"""
        shape = self._get_selected_shape()
        if not shape:
            messagebox.showerror("错误", "请选择进水口形状")
            return
        
        try:
            xi = float(self.entry_xi.get())
        except ValueError:
            messagebox.showerror("输入错误", "系数格式错误")
            return
        
        # 创建新的结构段
        self.result = StructureSegment(
            segment_type=SegmentType.INLET,
            locked=self.segment.locked,
            coordinates=self.segment.coordinates,
            inlet_shape=shape,
            xi_user=xi  # 使用用户输入的值
        )
        self.destroy()


class OutletShapeDialog(tk.Toplevel):
    """出水口局部阻力系数对话框（流入明渠计算）"""
    
    def __init__(self, parent, segment: StructureSegment, Q: float = 10.0, v: float = 2.0):
        super().__init__(parent)
        self.title("出水口局部阻力系数")
        self.geometry("480x480")
        self.transient(parent)
        self.grab_set()
        
        self.result: Optional[StructureSegment] = None
        self.segment = segment
        self.Q = Q  # 设计流量
        self.v = v  # 拟定流速
        
        # 计算管道断面积 ωg
        self.omega_g = Q / v if v > 0 else 0.0
        
        self._create_ui()
        
        # 居中显示
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")
    
    def _create_ui(self):
        """创建界面"""
        frame = ttk.Frame(self, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题说明
        title_frame = ttk.Frame(frame)
        title_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(title_frame, text="流入明渠  ", font=('', 11, 'bold')).pack(side=tk.LEFT)
        ttk.Label(title_frame, text="ξc = (1 - ωg/ωq)²", font=('', 11), foreground='#0066CC').pack(side=tk.LEFT)
        
        # === 下游明渠参数区域 ===
        channel_frame = ttk.LabelFrame(frame, text="下游明渠参数", padding=10)
        channel_frame.pack(fill=tk.X, pady=5)
        
        # 显示管道断面积
        info_row = ttk.Frame(channel_frame)
        info_row.pack(fill=tk.X, pady=2)
        ttk.Label(info_row, text=f"管道断面积 ωg = Q/v = {self.Q:.2f}/{self.v:.2f} = {self.omega_g:.4f} m²", 
                 foreground='#0066CC').pack(anchor='w')
        
        # 下游渠道底宽 B
        row1 = ttk.Frame(channel_frame)
        row1.pack(fill=tk.X, pady=3)
        ttk.Label(row1, text="下游渠道底宽 B (m):", width=20).pack(side=tk.LEFT)
        self.entry_B = ttk.Entry(row1, width=12)
        self.entry_B.insert(0, "3.0")
        self.entry_B.pack(side=tk.LEFT, padx=5)
        self.entry_B.bind('<KeyRelease>', self._on_channel_param_changed)
        
        # 下游渠道水深 h
        row2 = ttk.Frame(channel_frame)
        row2.pack(fill=tk.X, pady=3)
        ttk.Label(row2, text="下游渠道水深 h (m):", width=20).pack(side=tk.LEFT)
        self.entry_h = ttk.Entry(row2, width=12)
        self.entry_h.insert(0, "2.0")
        self.entry_h.pack(side=tk.LEFT, padx=5)
        self.entry_h.bind('<KeyRelease>', self._on_channel_param_changed)
        
        # 坡比 m
        row3 = ttk.Frame(channel_frame)
        row3.pack(fill=tk.X, pady=3)
        ttk.Label(row3, text="坡比 m:", width=20).pack(side=tk.LEFT)
        self.entry_m = ttk.Entry(row3, width=12)
        self.entry_m.insert(0, "0")
        self.entry_m.pack(side=tk.LEFT, padx=5)
        ttk.Label(row3, text="(矩形渠道为0)", foreground='#888888').pack(side=tk.LEFT)
        self.entry_m.bind('<KeyRelease>', self._on_channel_param_changed)
        
        # 计算结果显示
        calc_frame = ttk.LabelFrame(frame, text="计算结果", padding=10)
        calc_frame.pack(fill=tk.X, pady=10)
        
        self.label_omega_q = ttk.Label(calc_frame, text="下游明渠断面积 ωq = (B + m×h)×h = --", foreground='#666666')
        self.label_omega_q.pack(anchor='w')
        self.label_calc_xi = ttk.Label(calc_frame, text="ξc = (1 - ωg/ωq)² = --", foreground='#006600', font=('', 10, 'bold'))
        self.label_calc_xi.pack(anchor='w', pady=(5, 0))
        
        # 系数输入
        coeff_frame = ttk.LabelFrame(frame, text="局部阻力系数 ξc", padding=10)
        coeff_frame.pack(fill=tk.X, pady=5)
        
        coeff_row = ttk.Frame(coeff_frame)
        coeff_row.pack(fill=tk.X)
        
        ttk.Label(coeff_row, text="系数值:").pack(side=tk.LEFT)
        self.entry_xi = ttk.Entry(coeff_row, width=15)
        self.entry_xi.pack(side=tk.LEFT, padx=10)
        ttk.Label(coeff_row, text="(可手动修改)", foreground='#888888').pack(side=tk.LEFT)
        
        # 显示当前系数或初始计算
        current_xi = self.segment.xi_user if self.segment.xi_user is not None else self.segment.xi_calc
        if current_xi is not None:
            self.entry_xi.insert(0, f"{current_xi:.4f}")
        
        # 按钮
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=(20, 0))
        
        ttk.Button(btn_frame, text="确定", command=self._on_ok, width=10).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="取消", command=self.destroy, width=10).pack(side=tk.RIGHT, padx=5)
        
        # 初始化计算
        self._on_channel_param_changed()
    
    def _on_channel_param_changed(self, event=None):
        """渠道参数改变事件，重新计算系数"""
        try:
            B = float(self.entry_B.get())
            h = float(self.entry_h.get())
            m = float(self.entry_m.get())
            
            if B <= 0 or h <= 0:
                self.label_omega_q.config(text="下游明渠断面积 ωq = (B + m×h)×h = 请输入有效参数")
                self.label_calc_xi.config(text="ξc = (1 - ωg/ωq)² = --")
                return
            
            # 计算下游明渠断面积 ωq = (B + m*h) * h
            omega_q = (B + m * h) * h
            self.label_omega_q.config(text=f"下游明渠断面积 ωq = ({B:.2f} + {m:.2f}×{h:.2f})×{h:.2f} = {omega_q:.4f} m²")
            
            if omega_q <= 0:
                self.label_calc_xi.config(text="ξc = (1 - ωg/ωq)² = --")
                return
            
            # 计算出口水头损失系数 ξc = (1 - ωg/ωq)²
            ratio = self.omega_g / omega_q
            xi_c = (1 - ratio) ** 2
            self.label_calc_xi.config(text=f"ξc = (1 - {self.omega_g:.4f}/{omega_q:.4f})² = (1 - {ratio:.4f})² = {xi_c:.4f}")
            
            # 更新系数输入框
            self.entry_xi.delete(0, tk.END)
            self.entry_xi.insert(0, f"{xi_c:.4f}")
            
        except ValueError:
            self.label_omega_q.config(text="下游明渠断面积 ωq = (B + m×h)×h = 请输入有效数值")
            self.label_calc_xi.config(text="ξc = (1 - ωg/ωq)² = --")
    
    def _on_ok(self):
        """确定按钮"""
        try:
            xi = float(self.entry_xi.get())
        except ValueError:
            messagebox.showerror("输入错误", "系数格式错误")
            return
        
        # 创建新的结构段（流入明渠模式）
        self.result = StructureSegment(
            segment_type=SegmentType.OUTLET,
            locked=self.segment.locked,
            coordinates=self.segment.coordinates,
            outlet_shape=None,  # 流入明渠模式不使用形状
            xi_user=xi
        )
        self.destroy()
