"""
明渠段参数选择对话框

当建筑物之间需要插入明渠段时，弹出此对话框让用户选择参数来源：
1. 复制上游最近明渠的参数（推荐）
2. 手动输入参数
"""

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional, Dict, Any
from dataclasses import dataclass
import math


@dataclass
class OpenChannelParams:
    """明渠段参数"""
    name: str = "-"  # 明渠段名称固定为"-"
    structure_type: str = "明渠-梯形"
    bottom_width: float = 0.0  # 底宽 B
    water_depth: float = 0.0  # 水深 h（自动计算）
    side_slope: float = 0.0  # 边坡系数 m
    roughness: float = 0.014  # 糙率 n
    slope_inv: float = 3000.0  # 底坡 1/i
    flow: float = 0.0  # 流量 Q
    flow_section: str = ""  # 流量段


class OpenChannelDialog(tk.Toplevel):
    """
    明渠段参数选择对话框
    
    用于在建筑物之间插入明渠段时，让用户选择参数来源
    """
    
    # 明渠结构类型选项
    STRUCTURE_TYPES = [
        "明渠-梯形",
        "明渠-矩形",
        "明渠-圆形"
    ]
    
    def __init__(self, parent, 
                 upstream_channel: Optional[Dict] = None,
                 available_length: float = 0.0,
                 prev_structure: str = "",
                 next_structure: str = "",
                 flow_section: str = "",
                 flow: float = 0.0):
        """
        初始化对话框
        
        Args:
            parent: 父窗口
            upstream_channel: 上游找到的明渠节点参数（可能为None）
            available_length: 可用长度
            prev_structure: 前一建筑物结构形式
            next_structure: 后一建筑物结构形式
            flow_section: 当前流量段名称
            flow: 当前流量段的设计流量
        """
        super().__init__(parent)
        
        self.upstream_channel = upstream_channel
        self.available_length = available_length
        self.prev_structure = prev_structure
        self.next_structure = next_structure
        self.flow_section = flow_section
        self.flow = flow
        
        self._result: Optional[OpenChannelParams] = None
        self._cancelled = False
        
        self._setup_window()
        self._create_widgets()
        self._bind_events()
        
        # 默认选择：如果有上游明渠则选择复制，否则选择手动输入
        if self.upstream_channel:
            self.source_var.set("copy")
            self._on_source_change()
        else:
            self.source_var.set("manual")
            self._on_source_change()
    
    def _setup_window(self):
        """设置窗口属性"""
        self.title("插入明渠段")
        self.geometry("480x710")
        self.resizable(False, False)
        
        # 模态对话框
        self.transient(self.master)
        self.grab_set()
        
        # 居中显示
        self.update_idletasks()
        x = (self.winfo_screenwidth() - 480) // 2
        y = (self.winfo_screenheight() - 710) // 2
        self.geometry(f"+{x}+{y}")
    
    def _create_widgets(self):
        """创建控件"""
        # 主框架
        main_frame = ttk.Frame(self, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题说明
        title_text = f"在 [{self.prev_structure}] 和 [{self.next_structure}] 之间插入明渠段"
        ttk.Label(main_frame, text=title_text, font=("", 10, "bold")).pack(anchor="w")
        
        length_text = f"可用长度: {self.available_length:.2f} m"
        ttk.Label(main_frame, text=length_text, foreground="gray").pack(anchor="w")
        
        # 显示流量段信息
        flow_info = f"当前流量段: {self.flow_section}，流量 Q = {self.flow:.3f} m³/s"
        ttk.Label(main_frame, text=flow_info, foreground="blue", font=("", 9, "bold")).pack(anchor="w", pady=(5, 5))
        
        # ===== 提示信息区域 =====
        tip_frame = ttk.LabelFrame(main_frame, text="💡 说明", padding=(10, 5))
        tip_frame.pack(fill="x", pady=(5, 10))
        
        tip_text = (
            "系统检测到上述两个建筑物之间存在空余渠段（无建筑物覆盖），\n"
            "需要补充一段明渠来连接它们，以保证水面线计算的连续性。\n"
            "\n"
            "您可以选择【复制上游明渠参数】（推荐，快速沿用已有断面），\n"
            "或【手动输入参数】自行指定断面尺寸。"
        )
        tip_label = ttk.Label(tip_frame, text=tip_text, foreground="#555555",
                              wraplength=420, justify="left", font=("", 9))
        tip_label.pack(anchor="w")
        
        ttk.Separator(main_frame, orient="horizontal").pack(fill="x", pady=5)
        
        # 参数来源选择
        self.source_var = tk.StringVar(value="copy" if self.upstream_channel else "manual")
        
        # 选项1：复制上游明渠参数
        copy_frame = ttk.Frame(main_frame)
        copy_frame.pack(fill="x", pady=5)
        
        self.copy_radio = ttk.Radiobutton(
            copy_frame, text="复制上游明渠参数（推荐）", 
            variable=self.source_var, value="copy",
            command=self._on_source_change
        )
        self.copy_radio.pack(anchor="w")
        
        # 上游明渠信息显示
        self.upstream_info_frame = ttk.Frame(main_frame)
        self.upstream_info_frame.pack(fill="x", padx=(20, 0), pady=(0, 5))
        
        if self.upstream_channel:
            upstream_name = self.upstream_channel.get("name", "-")
            upstream_type = self.upstream_channel.get("structure_type", "")
            upstream_flow_section = self.upstream_channel.get("flow_section", "")
            upstream_flow = self.upstream_channel.get("flow", 0)
            
            ttk.Label(self.upstream_info_frame, 
                     text=f"找到的明渠: ({upstream_type})",
                     foreground="blue").pack(anchor="w")
            
            # 流量段信息
            flow_section_text = f"流量段: {upstream_flow_section}，Q = {upstream_flow:.3f} m³/s"
            ttk.Label(self.upstream_info_frame, text=flow_section_text, foreground="green").pack(anchor="w")
            
            # 参数预览
            B = self.upstream_channel.get("bottom_width", 0)
            h = self.upstream_channel.get("water_depth", 0)
            m = self.upstream_channel.get("side_slope", 0)
            n = self.upstream_channel.get("roughness", 0.014)
            slope = self.upstream_channel.get("slope_inv", 0)
            
            preview_text = f"参数: B={B:.2f}m, h={h:.2f}m, m={m}, n={n}, 底坡1/{slope:.0f}"
            ttk.Label(self.upstream_info_frame, text=preview_text, foreground="gray").pack(anchor="w")
        else:
            ttk.Label(self.upstream_info_frame, 
                     text="未找到上游明渠段",
                     foreground="red").pack(anchor="w")
            self.copy_radio.configure(state="disabled")
        
        ttk.Separator(main_frame, orient="horizontal").pack(fill="x", pady=5)
        
        # 选项2：手动输入参数
        manual_frame = ttk.Frame(main_frame)
        manual_frame.pack(fill="x", pady=5)
        
        self.manual_radio = ttk.Radiobutton(
            manual_frame, text="手动输入参数", 
            variable=self.source_var, value="manual",
            command=self._on_source_change
        )
        self.manual_radio.pack(anchor="w")
        
        # 手动输入表单
        self.form_frame = ttk.Frame(main_frame)
        self.form_frame.pack(fill="x", padx=(20, 0), pady=5)
        
        # 结构形式（只读下拉框）
        row = 0
        ttk.Label(self.form_frame, text="结构形式:").grid(row=row, column=0, sticky="e", pady=3)
        self.type_combo = ttk.Combobox(self.form_frame, values=self.STRUCTURE_TYPES, 
                                       state="readonly", width=22)
        self.type_combo.set(self.STRUCTURE_TYPES[0])
        self.type_combo.grid(row=row, column=1, sticky="w", padx=5, pady=3)
        self.type_combo.bind("<<ComboboxSelected>>", self._on_type_change)
        
        # 流量 Q（显示当前流量段的流量，用户可修改）
        row += 1
        ttk.Label(self.form_frame, text="流量 Q:").grid(row=row, column=0, sticky="e", pady=3)
        self.flow_entry = ttk.Entry(self.form_frame, width=15)
        self.flow_entry.insert(0, f"{self.flow:.3f}" if self.flow > 0 else "")
        self.flow_entry.grid(row=row, column=1, sticky="w", padx=5, pady=3)
        ttk.Label(self.form_frame, text="m³/s").grid(row=row, column=2, sticky="w")
        
        # 底宽 B
        row += 1
        ttk.Label(self.form_frame, text="底宽 B:").grid(row=row, column=0, sticky="e", pady=3)
        self.bottom_width_entry = ttk.Entry(self.form_frame, width=15)
        self.bottom_width_entry.grid(row=row, column=1, sticky="w", padx=5, pady=3)
        ttk.Label(self.form_frame, text="m").grid(row=row, column=2, sticky="w")
        
        # 边坡系数 m（梯形用）
        row += 1
        self.side_slope_label = ttk.Label(self.form_frame, text="边坡 m:")
        self.side_slope_label.grid(row=row, column=0, sticky="e", pady=3)
        self.side_slope_entry = ttk.Entry(self.form_frame, width=15)
        self.side_slope_entry.grid(row=row, column=1, sticky="w", padx=5, pady=3)
        
        # 糙率 n
        row += 1
        ttk.Label(self.form_frame, text="糙率 n:").grid(row=row, column=0, sticky="e", pady=3)
        self.roughness_entry = ttk.Entry(self.form_frame, width=15)
        self.roughness_entry.insert(0, "0.014")
        self.roughness_entry.grid(row=row, column=1, sticky="w", padx=5, pady=3)
        
        # 底坡 1/i
        row += 1
        ttk.Label(self.form_frame, text="底坡 1/i:").grid(row=row, column=0, sticky="e", pady=3)
        self.slope_entry = ttk.Entry(self.form_frame, width=15)
        self.slope_entry.insert(0, "3000")
        self.slope_entry.grid(row=row, column=1, sticky="w", padx=5, pady=3)
        
        # 计算结果显示区域
        row += 1
        ttk.Separator(self.form_frame, orient="horizontal").grid(row=row, column=0, columnspan=3, sticky="ew", pady=10)
        
        row += 1
        self.calc_result_label = ttk.Label(self.form_frame, text="", foreground="green")
        self.calc_result_label.grid(row=row, column=0, columnspan=3, sticky="w", pady=3)
        
        # 取消提示
        cancel_hint = ttk.Label(
            main_frame,
            text="⚠ 若取消，此处将不插入明渠段，两建筑物之间的水面线计算可能不连续。",
            foreground="#CC6600", font=("", 8), wraplength=440, justify="left"
        )
        cancel_hint.pack(fill="x", pady=(10, 0))
        
        # 按钮区域
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill="x", pady=(5, 0))
        
        ttk.Button(btn_frame, text="确定", command=self._on_ok, width=10).pack(side="right", padx=5)
        ttk.Button(btn_frame, text="取消", command=self._on_cancel, width=10).pack(side="right")
    
    def _bind_events(self):
        """绑定事件"""
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Return>", lambda e: self._on_ok())
        self.bind("<Escape>", lambda e: self._on_cancel())
    
    def _on_source_change(self):
        """参数来源切换"""
        if self.source_var.get() == "copy":
            # 禁用手动输入表单
            for child in self.form_frame.winfo_children():
                if isinstance(child, ttk.Entry):
                    child.configure(state="disabled")
                elif isinstance(child, ttk.Combobox):
                    child.configure(state="disabled")
            self.calc_result_label.configure(text="")
        else:
            # 启用手动输入表单
            for child in self.form_frame.winfo_children():
                if isinstance(child, ttk.Entry):
                    child.configure(state="normal")
            self.type_combo.configure(state="readonly")
            self._on_type_change()
    
    def _on_type_change(self, event=None):
        """结构类型切换"""
        struct_type = self.type_combo.get()
        
        # 根据类型显示/隐藏边坡字段
        if struct_type == "明渠-梯形":
            self.side_slope_label.grid()
            self.side_slope_entry.grid()
            self.side_slope_entry.configure(state="normal")
        else:
            self.side_slope_entry.delete(0, tk.END)
            self.side_slope_entry.insert(0, "0")
            self.side_slope_entry.configure(state="disabled")
    
    def _calculate_normal_depth(self, Q: float, B: float, m: float, n: float, i: float) -> float:
        """
        计算明渠正常水深（曼宁公式迭代求解）
        
        Q = A * v = A * (1/n) * R^(2/3) * i^(1/2)
        
        梯形断面：
        A = (B + m*h) * h
        P = B + 2*h*sqrt(1+m^2)
        R = A / P
        
        Args:
            Q: 流量 (m³/s)
            B: 底宽 (m)
            m: 边坡系数
            n: 糙率
            i: 底坡
            
        Returns:
            正常水深 h (m)
        """
        if Q <= 0 or B <= 0 or n <= 0 or i <= 0:
            return 0.0
        
        # 牛顿迭代法求解
        h = 1.0  # 初始猜测
        max_iter = 100
        tol = 1e-6
        
        for _ in range(max_iter):
            # 计算过水断面面积
            A = (B + m * h) * h
            # 计算湿周
            P = B + 2 * h * math.sqrt(1 + m * m)
            # 计算水力半径
            R = A / P if P > 0 else 0
            
            if R <= 0:
                h = h * 1.5
                continue
            
            # 计算流量
            Q_calc = A * (1 / n) * (R ** (2.0 / 3.0)) * math.sqrt(i)
            
            # 计算误差
            f = Q_calc - Q
            
            if abs(f) < tol:
                return h
            
            # 计算导数 dQ/dh
            dA_dh = B + 2 * m * h
            dP_dh = 2 * math.sqrt(1 + m * m)
            dR_dh = (dA_dh * P - A * dP_dh) / (P * P) if P > 0 else 0
            
            dQ_dh = (dA_dh * (R ** (2.0 / 3.0)) + A * (2.0 / 3.0) * (R ** (-1.0 / 3.0)) * dR_dh) * (1 / n) * math.sqrt(i)
            
            if abs(dQ_dh) < 1e-10:
                h = h * 1.1
                continue
            
            # 牛顿迭代
            h_new = h - f / dQ_dh
            
            if h_new <= 0:
                h = h / 2
            else:
                h = h_new
        
        return h
    
    def _calculate_hydraulic_params(self, h: float, B: float, m: float) -> Dict[str, float]:
        """
        计算水力学参数
        
        Args:
            h: 水深 (m)
            B: 底宽 (m)
            m: 边坡系数
            
        Returns:
            水力学参数字典
        """
        # 过水断面面积
        A = (B + m * h) * h
        # 湿周
        P = B + 2 * h * math.sqrt(1 + m * m)
        # 水力半径
        R = A / P if P > 0 else 0
        # 水面宽度
        T = B + 2 * m * h
        
        return {
            "A": round(A, 3),
            "P": round(P, 3),
            "R": round(R, 4),
            "T": round(T, 3)
        }
    
    def _validate_inputs(self) -> bool:
        """验证输入"""
        if self.source_var.get() == "copy":
            return True
        
        try:
            flow = float(self.flow_entry.get() or 0)
            bottom_width = float(self.bottom_width_entry.get() or 0)
            roughness = float(self.roughness_entry.get() or 0.014)
            slope_inv = float(self.slope_entry.get() or 3000)
            
            struct_type = self.type_combo.get()
            if struct_type == "明渠-梯形":
                side_slope = float(self.side_slope_entry.get() or 0)
            
            if flow <= 0:
                messagebox.showwarning("输入错误", "流量Q必须大于0")
                return False
            
            if bottom_width <= 0 and struct_type != "明渠-圆形":
                messagebox.showwarning("输入错误", "底宽B必须大于0")
                return False
            
            if roughness <= 0:
                messagebox.showwarning("输入错误", "糙率n必须大于0")
                return False
            
            if slope_inv <= 0:
                messagebox.showwarning("输入错误", "底坡1/i必须大于0")
                return False
            
            return True
            
        except ValueError:
            messagebox.showwarning("输入错误", "请输入有效的数值")
            return False
    
    def _on_ok(self):
        """确定按钮"""
        if not self._validate_inputs():
            return
        
        if self.source_var.get() == "copy" and self.upstream_channel:
            # 复制上游参数
            self._result = OpenChannelParams(
                name="-",  # 名称固定为"-"
                structure_type=self.upstream_channel.get("structure_type", "明渠-梯形"),
                bottom_width=self.upstream_channel.get("bottom_width", 0),
                water_depth=self.upstream_channel.get("water_depth", 0),
                side_slope=self.upstream_channel.get("side_slope", 0),
                roughness=self.upstream_channel.get("roughness", 0.014),
                slope_inv=self.upstream_channel.get("slope_inv", 3000),
                flow=self.upstream_channel.get("flow", self.flow),
                flow_section=self.upstream_channel.get("flow_section", self.flow_section)
            )
        else:
            # 使用手动输入，自动计算水深
            struct_type = self.type_combo.get()
            flow = float(self.flow_entry.get() or 0)
            bottom_width = float(self.bottom_width_entry.get() or 0)
            roughness = float(self.roughness_entry.get() or 0.014)
            slope_inv = float(self.slope_entry.get() or 3000)
            slope_i = 1.0 / slope_inv if slope_inv > 0 else 0
            
            side_slope = 0
            if struct_type == "明渠-梯形":
                side_slope = float(self.side_slope_entry.get() or 0)
            
            # 计算正常水深
            water_depth = self._calculate_normal_depth(flow, bottom_width, side_slope, roughness, slope_i)
            
            if water_depth <= 0:
                messagebox.showwarning("计算错误", "无法计算出有效的水深，请检查输入参数")
                return
            
            # 计算水力学参数
            hydraulic_params = self._calculate_hydraulic_params(water_depth, bottom_width, side_slope)
            
            # 显示计算结果
            result_text = f"计算结果: h={water_depth:.3f}m, A={hydraulic_params['A']:.3f}m², R={hydraulic_params['R']:.4f}m"
            self.calc_result_label.configure(text=result_text)
            
            self._result = OpenChannelParams(
                name="-",  # 名称固定为"-"
                structure_type=struct_type,
                bottom_width=bottom_width,
                water_depth=water_depth,
                side_slope=side_slope,
                roughness=roughness,
                slope_inv=slope_inv,
                flow=flow,
                flow_section=self.flow_section
            )
        
        self.destroy()
    
    def _on_cancel(self):
        """取消按钮 —— 弹出确认框提醒用户后果"""
        confirm = messagebox.askyesno(
            "确认取消",
            "取消后，此处将不会插入明渠段，\n"
            "两个建筑物之间的水面线计算可能出现断档。\n\n"
            "确定要跳过吗？",
            icon="warning",
            parent=self
        )
        if confirm:
            self._cancelled = True
            self._result = None
            self.destroy()
    
    def show(self) -> Optional[OpenChannelParams]:
        """
        显示对话框并返回结果
        
        Returns:
            OpenChannelParams 或 None（用户取消）
        """
        self.wait_window()
        return self._result
