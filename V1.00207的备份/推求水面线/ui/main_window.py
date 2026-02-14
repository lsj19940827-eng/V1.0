# -*- coding: utf-8 -*-
"""
主窗口

整合所有UI组件，提供完整的用户界面。
包含：
1. 渠系建筑物断面尺寸计算（明渠、渡槽、隧洞、矩形暗涵、多流量段批量计算）
2. 推求水面线计算

版本: V2.0 (整合版)
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import Optional, List, Dict, Any
import sys
import os

# 添加父目录到路径以支持相对导入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 添加V1.0根目录到路径以支持导入计算模块
v1_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if v1_root not in sys.path:
    sys.path.insert(0, v1_root)

from config.constants import (
    APP_FULL_TITLE, WINDOW_WIDTH, WINDOW_HEIGHT,
    WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT, EXCEL_FILE_TYPES
)
from models.data_models import ChannelNode, ProjectSettings
from core.calculator import WaterProfileCalculator
from utils.excel_io import ExcelIO
from ui.basic_settings import BasicSettingsPanel
from ui.data_table import DataTablePanel
from ui.result_display import ResultDisplayPanel
from ui.open_channel_dialog import OpenChannelDialog, OpenChannelParams
from ui.shared_data_manager import get_shared_data_manager

# 导入断面计算Panel包装器
try:
    from ui.section_panels_wrapper import (
        OpenChannelPanel, AqueductPanel, TunnelPanel, 
        RectangularCulvertPanel, BatchCalculationPanel,
        MODULES_LOADED, get_loaded_modules_info, is_any_module_loaded
    )
    SECTION_PANELS_LOADED = True
except ImportError as e:
    SECTION_PANELS_LOADED = False
    SECTION_PANELS_ERROR = str(e)
    OpenChannelPanel = None
    AqueductPanel = None
    TunnelPanel = None
    RectangularCulvertPanel = None
    BatchCalculationPanel = None
    MODULES_LOADED = {}
    def get_loaded_modules_info(): return "断面计算模块加载失败"
    def is_any_module_loaded(): return False


class MainWindow:
    """
    主窗口
    
    整合所有UI组件，提供完整的渠系水力计算界面。
    包含两大功能模块：
    1. 渠系建筑物断面尺寸计算（明渠、渡槽、隧洞、矩形暗涵、多流量段批量计算）
    2. 推求水面线计算
    """
    
    def __init__(self):
        """初始化主窗口"""
        self.root = tk.Tk()
        self.root.title("渠系水力计算系统")
        # 增大窗口尺寸以容纳更多内容
        self.root.geometry("1400x900")
        self.root.minsize(1200, 800)
        
        # 计算器和工具
        self.calculator: Optional[WaterProfileCalculator] = None
        self.excel_io: Optional[ExcelIO] = None
        
        # 共享数据管理器
        self.shared_data = get_shared_data_manager()
        
        # 创建界面
        self._create_main_notebook()
        self._create_status_bar()
        
        # 初始化工具
        self._init_tools()
        
        # 加载默认数据
        self._load_default_data()
        
        # 更新状态栏
        self._update_status_bar()
    
    def _create_main_notebook(self):
        """创建主Notebook（标签页容器）"""
        self.main_notebook = ttk.Notebook(self.root)
        self.main_notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 创建断面计算标签页（如果模块加载成功）
        if SECTION_PANELS_LOADED and is_any_module_loaded():
            self._create_section_calc_tabs()
        
        # 创建推求水面线标签页
        self._create_water_profile_tab()
    
    def _create_section_calc_tabs(self):
        """创建断面计算相关的标签页"""
        # Tab 1: 明渠
        if OpenChannelPanel is not None:
            self.open_channel_tab = ttk.Frame(self.main_notebook)
            self.main_notebook.add(self.open_channel_tab, text="明渠")
            self.open_channel_panel = OpenChannelPanel(self.open_channel_tab)
            self.open_channel_panel.pack(fill=tk.BOTH, expand=True)
        
        # Tab 2: 渡槽
        if AqueductPanel is not None:
            self.aqueduct_tab = ttk.Frame(self.main_notebook)
            self.main_notebook.add(self.aqueduct_tab, text="渡槽")
            self.aqueduct_panel = AqueductPanel(self.aqueduct_tab)
            self.aqueduct_panel.pack(fill=tk.BOTH, expand=True)
        
        # Tab 3: 隧洞
        if TunnelPanel is not None:
            self.tunnel_tab = ttk.Frame(self.main_notebook)
            self.main_notebook.add(self.tunnel_tab, text="隧洞")
            self.tunnel_panel = TunnelPanel(self.tunnel_tab)
            self.tunnel_panel.pack(fill=tk.BOTH, expand=True)
        
        # Tab 4: 矩形暗涵
        if RectangularCulvertPanel is not None:
            self.culvert_tab = ttk.Frame(self.main_notebook)
            self.main_notebook.add(self.culvert_tab, text="矩形暗涵")
            self.culvert_panel = RectangularCulvertPanel(self.culvert_tab)
            self.culvert_panel.pack(fill=tk.BOTH, expand=True)
        
        # Tab 5: 多流量段批量计算
        if BatchCalculationPanel is not None:
            self.batch_tab = ttk.Frame(self.main_notebook)
            self.main_notebook.add(self.batch_tab, text="多流量段批量计算")
            self.batch_panel = BatchCalculationPanel(self.batch_tab)
            self.batch_panel.pack(fill=tk.BOTH, expand=True)
    
    def _create_water_profile_tab(self):
        """创建推求水面线标签页"""
        self.water_profile_tab = ttk.Frame(self.main_notebook)
        self.main_notebook.add(self.water_profile_tab, text="推求水面线")
        
        # 创建原有的推求水面线界面
        self._create_water_profile_area(self.water_profile_tab)
    
    def _create_water_profile_area(self, parent):
        """创建推求水面线主区域（原_create_main_area的内容）"""
        main_frame = ttk.Frame(parent)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 工具栏（只在推求水面线标签页显示）
        self._create_toolbar(main_frame)
        
        # 顶部：基础设置区
        self.settings_panel = BasicSettingsPanel(main_frame)
        self.settings_panel.pack(fill=tk.X, pady=(0, 5))
        
        # 中部：数据表格（占主要空间）
        self.data_table = DataTablePanel(main_frame)
        self.data_table.pack(fill=tk.BOTH, expand=True, pady=(0, 5))
        
        # 底部：结果展示区
        self.result_panel = ResultDisplayPanel(main_frame)
        self.result_panel.pack(fill=tk.X)
    
    def _create_status_bar(self):
        """创建状态栏"""
        status_frame = ttk.Frame(self.root)
        status_frame.pack(side=tk.BOTTOM, fill=tk.X)
        
        # 模块加载状态
        self.status_label = ttk.Label(status_frame, text="", anchor=tk.W)
        self.status_label.pack(side=tk.LEFT, padx=5, pady=2)
        
        # 共享数据状态
        self.shared_data_label = ttk.Label(status_frame, text="", anchor=tk.E)
        self.shared_data_label.pack(side=tk.RIGHT, padx=5, pady=2)
    
    def _update_status_bar(self):
        """更新状态栏信息"""
        # 模块加载状态
        if SECTION_PANELS_LOADED:
            loaded_modules = [name for name, loaded in MODULES_LOADED.items() if loaded]
            if loaded_modules:
                status_text = f"已加载模块: {', '.join(loaded_modules)}"
            else:
                status_text = "断面计算模块未加载"
        else:
            status_text = f"断面计算模块加载失败: {SECTION_PANELS_ERROR if 'SECTION_PANELS_ERROR' in dir() else '未知错误'}"
        
        self.status_label.config(text=status_text)
        
        # 共享数据状态
        result_count = self.shared_data.get_result_count()
        batch_count = self.shared_data.get_batch_count()
        if result_count > 0 or batch_count > 0:
            self.shared_data_label.config(text=f"计算结果缓存: 单项{result_count}条, 批量{batch_count}条")
        else:
            self.shared_data_label.config(text="")
        
        # 定时更新
        self.root.after(5000, self._update_status_bar)
    
    def _load_default_data(self):
        """加载默认数据"""
        try:
            # 设置默认渠道名称、级别和起始桩号
            # 起始桩号为0，与参考图片一致
            default_start_station = 0.0
            default_settings = ProjectSettings(
                channel_name="南峰寺",
                channel_level="支渠",
                start_station=default_start_station
            )
            self.settings_panel.var_channel_name.set("南峰寺")
            self.settings_panel.var_channel_level.set("支渠")
            self.settings_panel.var_start_station.set(str(default_start_station))
            
            # 设置桩号前缀（取渠道名称前两个字）
            station_prefix = default_settings.get_station_prefix()
            self.data_table.set_station_prefix(station_prefix)
            
            # 设置项目参数（用于联动计算）
            self.data_table.set_project_settings(default_settings)
            
            # 不加载默认节点数据，表格启动时为空
            self.data_table.set_nodes([])
            
            # 绑定设置变化事件来更新桩号前缀
            self.settings_panel.var_channel_name.trace_add('write', self._on_station_prefix_change)
            self.settings_panel.var_channel_level.trace_add('write', self._on_station_prefix_change)
            
            # 设置自动计算转弯半径的回调
            self.settings_panel.set_auto_calc_turn_radius_callback(self._auto_calc_turn_radius)
            
            # 设置转弯半径变化回调（同步更新表格）
            self.settings_panel.set_turn_radius_change_callback(self._on_turn_radius_change)
            
            # 设置起始桩号变化回调（同步更新表格中的桩号列）
            self.settings_panel.set_start_station_change_callback(self._on_start_station_change)
        except Exception as e:
            print(f"加载默认数据失败: {e}")
    
    def _on_turn_radius_change(self, turn_radius: float):
        """转弯半径变化时更新表格"""
        try:
            self.data_table.update_global_turn_radius(turn_radius)
        except Exception as e:
            print(f"更新转弯半径失败: {e}")
    
    def _on_start_station_change(self, start_station: float):
        """
        起始桩号变化时更新表格
        
        当用户修改起始桩号后，需要：
        1. 更新 project_settings 中的 start_station
        2. 重新计算所有桩号列（IP点桩号、弯前BC、里程MC、弯末EC）
        """
        try:
            # 更新 project_settings 中的起始桩号
            if self.data_table._project_settings:
                self.data_table._project_settings.start_station = start_station
            
            # 触发重新计算（从第0行开始，重新计算所有桩号）
            self.data_table.recalculate(0)
        except Exception as e:
            print(f"更新起始桩号失败: {e}")
    
    def _on_station_prefix_change(self, *args):
        """渠道名称或级别变化时更新桩号前缀和项目设置"""
        try:
            settings = self.settings_panel.get_settings()
            station_prefix = settings.get_station_prefix()
            self.data_table.set_station_prefix(station_prefix)
            
            # 更新项目设置（用于联动计算）
            self.data_table.set_project_settings(settings)
            
            # 重新刷新表格显示（仅更新桩号列）
            self._refresh_station_display()
        except Exception as e:
            print(f"更新桩号前缀失败: {e}")
    
    def _refresh_station_display(self):
        """刷新表格中的桩号显示"""
        nodes = self.data_table.get_nodes()
        if nodes:
            self.data_table.refresh_station_display(nodes)
    
    def _auto_calc_turn_radius(self):
        """自动计算转弯半径并更新UI"""
        try:
            nodes = self.data_table.get_nodes()
            if not nodes:
                from tkinter import messagebox
                messagebox.showwarning("提示", "表格中没有数据，无法自动计算转弯半径")
                return
            
            # 计算推荐的转弯半径
            recommended_turn_radius = self._calculate_recommended_turn_radius(nodes)
            
            # 更新UI
            self.settings_panel.set_turn_radius(recommended_turn_radius)
            
            from tkinter import messagebox
            messagebox.showinfo("完成", f"已自动计算转弯半径R = {recommended_turn_radius:.1f} m\n"
                               f"（按规范取各断面5倍特征尺寸的最大值）")
        except Exception as e:
            from tkinter import messagebox
            messagebox.showerror("错误", f"自动计算转弯半径失败: {str(e)}")
    
    def _create_toolbar(self, parent):
        """创建工具栏（仅在推求水面线标签页内显示）"""
        toolbar = ttk.Frame(parent)
        toolbar.pack(side=tk.TOP, fill=tk.X, pady=(0, 5))
        
        # 文件操作
        ttk.Button(toolbar, text="导入Excel", 
                   command=self.import_excel).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="导出Excel", 
                   command=self.export_excel).pack(side=tk.LEFT, padx=2)
        
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=5, fill=tk.Y)
        ttk.Button(toolbar, text="从计算结果导入", 
                   command=self.import_from_calc_results).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="倒虹吸水力计算", 
                   command=self.open_siphon_calculator).pack(side=tk.LEFT, padx=2)
        
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=5, fill=tk.Y)
        
        # 计算按钮（突出显示）
        calc_btn = ttk.Button(toolbar, text="执行计算", command=self.calculate)
        calc_btn.pack(side=tk.LEFT, padx=2)
        
        # 右侧：帮助和关于
        ttk.Button(toolbar, text="关于", 
                   command=self.show_about).pack(side=tk.RIGHT, padx=2)
    
    def _init_tools(self):
        """初始化工具"""
        try:
            self.excel_io = ExcelIO()
        except ImportError as e:
            messagebox.showwarning("警告", f"Excel功能不可用: {e}\n请安装 pandas 或 openpyxl")
    
    def calculate(self):
        """执行计算"""
        try:
            # 获取设置
            settings = self.settings_panel.get_settings()
            
            # 验证设置
            is_valid, error_msg = settings.validate()
            if not is_valid:
                messagebox.showerror("参数错误", error_msg)
                return
            
            # 获取节点数据
            nodes = self.data_table.get_nodes()
            
            if len(nodes) < 2:
                messagebox.showerror("数据错误", "至少需要2个节点才能进行计算")
                return
            
            # 创建计算器
            self.calculator = WaterProfileCalculator(settings)
            
            # 验证输入
            is_valid, errors = self.calculator.validate_input(nodes)
            if not is_valid:
                messagebox.showerror("输入错误", "\n".join(errors))
                return
            
            # 更新状态
            self.result_panel.set_status("正在计算...", "info")
            self.root.update()
            
            # 创建明渠段参数获取回调
            def open_channel_callback(upstream_channel, available_length, prev_struct, next_struct, flow_section, flow):
                """弹窗让用户选择明渠段参数"""
                dialog = OpenChannelDialog(
                    self.root,
                    upstream_channel=upstream_channel,
                    available_length=available_length,
                    prev_structure=prev_struct,
                    next_structure=next_struct,
                    flow_section=flow_section,
                    flow=flow
                )
                return dialog.show()
            
            # 执行计算
            calculated_nodes = self.calculator.calculate_all(nodes, open_channel_callback)
            
            # 更新表格结果
            self.data_table.update_results(calculated_nodes)
            
            # 更新摘要
            summary = self.calculator.get_calculation_summary(calculated_nodes)
            self.result_panel.update_summary(summary)
            
            # 更新状态
            self.result_panel.set_status("计算完成", "success")
            
            messagebox.showinfo("完成", "计算完成！")
            
        except Exception as e:
            self.result_panel.set_status(f"计算出错: {str(e)}", "error")
            messagebox.showerror("计算错误", f"计算过程中出错:\n{str(e)}")
    
    def export_excel(self):
        """导出Excel文件"""
        if self.excel_io is None:
            messagebox.showerror("错误", "Excel功能不可用")
            return
        
        file_path = filedialog.asksaveasfilename(
            title="保存Excel文件",
            defaultextension=".xlsx",
            filetypes=EXCEL_FILE_TYPES
        )
        
        if not file_path:
            return
        
        try:
            nodes = self.data_table.get_nodes()
            
            if not nodes:
                messagebox.showwarning("警告", "没有数据可导出")
                return
            
            # 转换为字典列表
            data = [node.to_dict() for node in nodes]
            
            self.excel_io.write_excel(file_path, data)
            
            messagebox.showinfo("完成", f"已导出到:\n{file_path}")
            
        except Exception as e:
            messagebox.showerror("导出错误", f"导出失败:\n{str(e)}")
    
    def import_excel(self):
        """
        导入Excel文件（断面参数）
        
        从【多流量段批量计算】标签页的【导出Excel报告】功能生成的Excel文件导入断面参数。
        """
        if self.excel_io is None:
            messagebox.showerror("错误", "Excel功能不可用")
            return
        
        # 引导用户：说明导入文件的来源
        guide_result = messagebox.askyesno(
            "导入Excel - 使用说明",
            "本功能用于导入【多流量段批量计算】标签页中\n"
            "【导出Excel报告】按钮生成的Excel文件。\n\n"
            "操作步骤：\n"
            "  1. 切换到【多流量段批量计算】标签页\n"
            "  2. 完成批量计算后，点击底部的【导出Excel报告】\n"
            "  3. 回到本页面，点击【导入Excel】选择该文件\n\n"
            "是否继续选择文件？"
        )
        
        if not guide_result:
            return
        
        file_path = filedialog.askopenfilename(
            title="选择【多流量段批量计算】导出的Excel文件",
            filetypes=EXCEL_FILE_TYPES
        )
        
        if not file_path:
            return
        
        try:
            # 尝试读取Excel文件
            import pandas as pd
            
            # 先尝试从第2行读取基础信息（新格式Excel）
            # 新格式第2行：A2=渠道名称(标签), B2=值, C2=渠道类型(标签), D2=值, 
            #             E2=起始水位(标签), F2=值, G2=起始桩号(标签), H2=值
            channel_name_value = None
            channel_level_value = None
            start_water_level_value = None
            start_station_value = None
            
            try:
                raw_df = pd.read_excel(file_path, sheet_name='批量计算结果', header=None, nrows=3)
                if len(raw_df) > 1 and len(raw_df.columns) >= 8:
                    # 新格式：标签和值分开存储
                    # A2=渠道名称(标签), B2=值
                    a2_label = str(raw_df.iloc[1, 0]) if raw_df.iloc[1, 0] is not None else ""
                    if "渠道名称" in a2_label:
                        b2_value = raw_df.iloc[1, 1]
                        if b2_value is not None and str(b2_value).strip():
                            channel_name_value = str(b2_value).strip()
                    
                    # C2=渠道类型(标签), D2=值
                    c2_label = str(raw_df.iloc[1, 2]) if raw_df.iloc[1, 2] is not None else ""
                    if "渠道类型" in c2_label:
                        d2_value = raw_df.iloc[1, 3]
                        if d2_value is not None and str(d2_value).strip():
                            channel_level_value = str(d2_value).strip()
                    
                    # E2=起始水位(标签), F2=值
                    e2_label = str(raw_df.iloc[1, 4]) if raw_df.iloc[1, 4] is not None else ""
                    if "起始水位" in e2_label or "水位" in e2_label:
                        f2_value = raw_df.iloc[1, 5]
                        if f2_value is not None and str(f2_value).strip():
                            start_water_level_value = str(f2_value).strip()
                    
                    # G2=起始桩号(标签), H2=值
                    g2_label = str(raw_df.iloc[1, 6]) if raw_df.iloc[1, 6] is not None else ""
                    if "起始桩号" in g2_label or "桩号" in g2_label:
                        h2_value = raw_df.iloc[1, 7]
                        if h2_value is not None and str(h2_value).strip():
                            start_station_value = str(h2_value).strip()
                
                # 兼容旧格式：A2="渠道起始水位: xxx m"
                if start_water_level_value is None and len(raw_df) > 1:
                    a2_value = str(raw_df.iloc[1, 0]) if raw_df.iloc[1, 0] is not None else ""
                    if "渠道起始水位" in a2_value and ":" in a2_value:
                        level_str = a2_value.split(":")[1].replace("m", "").strip()
                        start_water_level_value = level_str
                        
            except:
                pass  # 兼容旧格式Excel（无基础信息）
            
            # 读取Excel文件，尝试不同的表格
            # 多渠段批量计算导出的Excel：第1行标题，第2行基础信息，第3行表头，第4行开始数据
            sheet_name_used = None
            try:
                df = pd.read_excel(file_path, sheet_name='批量计算结果', header=2)
                sheet_name_used = '批量计算结果'
            except:
                try:
                    df = pd.read_excel(file_path, sheet_name=0, header=2)
                    sheet_name_used = '第一个工作表'
                except:
                    messagebox.showerror("错误", "无法读取Excel文件，请确保文件格式正确")
                    return
            
            # 打印列名以便调试
            
            if df.empty:
                messagebox.showwarning("警告", "Excel文件中没有数据")
                return
            
            # 自动填入读取到的基础信息
            if channel_name_value:
                self.settings_panel.var_channel_name.set(channel_name_value)
            
            if channel_level_value:
                # 验证是否为有效的渠道级别选项
                valid_levels = [
                    "总干渠", "总干管", "分干渠", "分干管", 
                    "干渠", "干管", "支渠", "支管", "分支渠", "分支管"
                ]
                if channel_level_value in valid_levels:
                    self.settings_panel.var_channel_level.set(channel_level_value)
            
            if start_water_level_value:
                self.settings_panel.var_start_water_level.set(start_water_level_value)
            
            if start_station_value:
                from ui.basic_settings import parse_station_input
                station_num = parse_station_input(start_station_value)
                self.settings_panel.set_start_station_value(station_num)
            
            # 尝试检测列名（兼容不同格式）
            def find_column(df, candidates):
                """在DataFrame中查找匹配的列名"""
                for col in df.columns:
                    col_str = str(col).strip()
                    for candidate in candidates:
                        if candidate in col_str:
                            return col
                return None
            
            # 定义列名候选项（按优先级排序）
            # 结果表格列：序号, 流量段, 建筑物名称, 结构形式, X, Y, Q(m³/s), 糙率n, 比降(1/), 边坡系数m,
            #            底宽B(m), 直径D(m), 半径R(m), h设计(m), V设计(m/s), A设计(m²), R水力(m), 湿周χ(m), ...
            col_flow_section = find_column(df, ["流量段"])
            col_name = find_column(df, ["建筑物名称"])
            col_structure = find_column(df, ["断面类型", "结构形式"])
            # 分别识别设计流量和加大流量列（注意：Q加大的候选项要排除，避免误匹配）
            # 先匹配加大流量列
            col_max_flow = find_column(df, ["Q加大", "加大流量"])  # 加大流量
            # 再匹配设计流量列（排除已匹配的加大流量列）
            design_flow_candidates = ["Q(m³/s)", "Q(m3/s)", "Q设计", "设计流量"]
            col_design_flow = None
            for col in df.columns:
                col_str = str(col).strip()
                # 跳过加大流量列
                if col_max_flow and col == col_max_flow:
                    continue
                for candidate in design_flow_candidates:
                    if candidate in col_str:
                        col_design_flow = col
                        break
                if col_design_flow:
                    break
            col_roughness = find_column(df, ["糙率n", "糙率"])
            col_slope = find_column(df, ["比降(1/)", "比降", "底坡"])
            col_depth = find_column(df, ["h设计(m)", "h设计", "水深"])
            col_area = find_column(df, ["A设计(m²)", "A设计", "过水断面面积", "过水面积"])
            col_perimeter = find_column(df, ["湿周χ(m)", "湿周χ", "湿周"])
            col_radius = find_column(df, ["R水力(m)", "R水力", "水力半径"])
            col_velocity = find_column(df, ["V设计(m/s)", "V设计", "流速"])
            col_bottom_width = find_column(df, ["B或D(m)", "底宽B(m)", "底宽"])
            col_diameter = find_column(df, ["直径D(m)", "直径D", "直径"])  # 单独查找直径列
            col_side_slope = find_column(df, ["边坡系数m", "边坡系数"])
            # 圆形断面的半径参数 - 需要精确匹配避免误匹配"R水力(m)"
            col_r_param = None
            for col in df.columns:
                col_str = str(col).strip()
                # 精确匹配 "R(m)" 或 "半径R(m)" 或 "半径R"，但排除 "R水力"
                if col_str == "R(m)" or col_str == "半径R(m)" or col_str == "半径R":
                    col_r_param = col
                    break
            col_x = find_column(df, ["X", "坐标X", "x"])  # X坐标
            col_y = find_column(df, ["Y", "坐标Y", "y"])  # Y坐标
            
            # 调试信息：显示找到的列和总行数
            debug_cols = []
            if col_flow_section: debug_cols.append(f"流量段:{col_flow_section}")
            if col_structure: debug_cols.append(f"结构形式:{col_structure}")
            if col_design_flow: debug_cols.append(f"设计流量:{col_design_flow}")
            
            # 创建新的节点列表（完全替换原有数据）
            new_nodes = []
            
            # 用于收集各流量段的设计流量（按流量段编号分组）
            flow_segment_map = {}  # {流量段编号: 设计流量}
            
            # 调试计数器
            skipped_rows = 0
            processed_rows = 0
            
            for idx, row in df.iterrows():
                # 跳过标题行或空行（检测是否为有效数据行）
                if col_flow_section:
                    flow_section_val = row.get(col_flow_section, "")
                    if not self._is_valid_data_value(flow_section_val):
                        skipped_rows += 1
                        continue
                
                processed_rows += 1
                
                # 创建新节点
                node = ChannelNode()
                
                # 导入X、Y坐标（如有列则导入，否则保持默认值0）
                if col_x:
                    node.x = self._parse_float(row.get(col_x, 0), 0.0)
                else:
                    node.x = 0.0
                
                if col_y:
                    node.y = self._parse_float(row.get(col_y, 0), 0.0)
                else:
                    node.y = 0.0
                
                # 导入流量段
                flow_section_num = 1
                if col_flow_section:
                    val = row.get(col_flow_section, "")
                    node.flow_section = str(val) if pd.notna(val) else ""
                    try:
                        flow_section_num = int(val)
                    except (ValueError, TypeError):
                        flow_section_num = 1
                
                # 导入建筑物名称
                if col_name:
                    val = row.get(col_name, "")
                    node.name = str(val) if pd.notna(val) else ""
                
                # 导入结构形式（直接使用多渠段批量计算中的类型，不进行转换）
                if col_structure:
                    val = row.get(col_structure, "")
                    if pd.notna(val):
                        original_type = str(val).strip()
                        try:
                            from models.enums import StructureType
                            node.structure_type = StructureType.from_string(original_type)
                        except ValueError:
                            # 如果枚举中没有该类型，保持默认值
                            pass
                
                # 导入设计流量并收集到流量段映射
                if col_design_flow:
                    val = row.get(col_design_flow, 0)
                    node.flow = self._parse_float(val, 0.0)
                    # 收集每个流量段的设计流量（取该流量段的第一个值）
                    if flow_section_num not in flow_segment_map and node.flow > 0:
                        flow_segment_map[flow_section_num] = node.flow
                
                # 导入糙率
                if col_roughness:
                    val = row.get(col_roughness, 0)
                    node.roughness = self._parse_float(val, 0.0)
                
                # 导入比降（存储为 slope_i）
                if col_slope:
                    val = row.get(col_slope, 0)
                    slope_val = self._parse_float(val, 0)
                    if slope_val > 0:
                        node.slope_i = 1.0 / slope_val  # 比降(1/i) 转换为 i
                    else:
                        node.slope_i = 0
                
                # 导入水深
                if col_depth:
                    val = row.get(col_depth, 0)
                    node.water_depth = self._parse_float(val, 0.0)
                
                # 导入过水断面面积（存储到section_params）
                if col_area:
                    val = row.get(col_area, 0)
                    node.section_params["A"] = self._parse_float(val, 0.0)
                
                # 导入湿周（存储到section_params）
                if col_perimeter:
                    val = row.get(col_perimeter, 0)
                    node.section_params["X"] = self._parse_float(val, 0.0)
                
                # 导入水力半径（存储到section_params）
                if col_radius:
                    val = row.get(col_radius, 0)
                    node.section_params["R"] = self._parse_float(val, 0.0)
                
                # 导入流速
                if col_velocity:
                    val = row.get(col_velocity, 0)
                    node.velocity = self._parse_float(val, 0.0)
                
                # 导入底宽（存储到section_params）
                if col_bottom_width:
                    val = row.get(col_bottom_width, 0)
                    node.section_params["B"] = self._parse_float(val, 0.0)
                
                # 导入直径（存储到section_params）
                if col_diameter:
                    val = row.get(col_diameter, 0)
                    node.section_params["D"] = self._parse_float(val, 0.0)
                
                # 导入边坡系数（存储到section_params）
                if col_side_slope:
                    val = row.get(col_side_slope, 0)
                    node.section_params["m"] = self._parse_float(val, 0.0)
                
                # 导入圆形断面半径R（存储到section_params）
                if col_r_param:
                    val = row.get(col_r_param, 0)
                    r_val = self._parse_float(val, 0.0)
                    if r_val > 0:
                        node.section_params["R_circle"] = r_val
                
                new_nodes.append(node)
            
            
            if not new_nodes:
                # 提供详细的诊断信息
                diag_info = f"Excel文件总行数: {len(df)}\n"
                diag_info += f"跳过的行数: {skipped_rows}\n"
                diag_info += f"识别到的列:\n"
                diag_info += f"  - 流量段列: {'是' if col_flow_section else '否'}\n"
                diag_info += f"  - 结构形式列: {'是' if col_structure else '否'}\n"
                diag_info += f"  - 设计流量列: {'是' if col_design_flow else '否'}\n"
                if len(df) > 0 and col_flow_section:
                    # 显示前几行的流量段值，帮助诊断
                    sample_vals = []
                    for i, (_, row) in enumerate(df.head(3).iterrows()):
                        val = row.get(col_flow_section, "")
                        sample_vals.append(f"'{val}'")
                    diag_info += f"  - 流量段列前3行值: {', '.join(sample_vals)}\n"
                diag_info += "\n可能原因:\n"
                diag_info += "1. Excel文件格式与预期不符\n"
                diag_info += "2. 表头行位置不在第3行\n"
                diag_info += "3. 流量段列的值无效或为空"
                messagebox.showwarning("警告", f"未找到有效的数据行\n\n{diag_info}")
                return
            
            # 计算推荐的转弯半径（按规范取大值）
            recommended_turn_radius = self._calculate_recommended_turn_radius(new_nodes)
            
            # 不设置节点的 turn_radius，使用全局转弯半径
            # 节点的 turn_radius 保持为0，表格显示时会自动使用全局值
            
            # 先更新 project_settings 的转弯半径
            if self.data_table._project_settings:
                self.data_table._project_settings.turn_radius = recommended_turn_radius
            
            # 完全替换表格内容（只显示导入的行）
            self.data_table.set_nodes(new_nodes)
            try:
                self.root.update_idletasks()
            except Exception:
                pass
            try:
                self.data_table.sheet.redraw()
            except Exception:
                try:
                    self.data_table.sheet.refresh()
                except Exception:
                    pass
            try:
                self.root.update()
            except Exception:
                pass
            
            # 更新UI界面的转弯半径输入框
            self.settings_panel.var_turn_radius.set(f"{recommended_turn_radius:.1f}")
            
            # 提取流量段的设计流量并填入基础设置区
            if flow_segment_map:
                # 按流量段编号排序，提取设计流量列表
                sorted_segments = sorted(flow_segment_map.keys())
                design_flows = [flow_segment_map[seg] for seg in sorted_segments]
                
                # 填入基础设置区的设计流量输入框
                self.settings_panel.set_design_flows(design_flows)
                
                # 自动计算并填入加大流量
                self.settings_panel._calculate_max_flows()
            
            # 构建导入完成提示信息
            flow_values = ", ".join([f"{flow_segment_map[k]:.2f}" for k in sorted(flow_segment_map.keys())]) if flow_segment_map else "无"
            # 转弯半径计算说明
            turn_radius_note = f"已自动计算转弯半径R = {recommended_turn_radius:.1f} m\n"
            messagebox.showinfo("完成", f"已成功导入 {len(new_nodes)} 行断面参数数据\n"
                               f"已自动填充 {len(flow_segment_map)} 个流量段的设计流量和加大流量\n"
                               f"设计流量: {flow_values}\n"
                               f"{turn_radius_note}"
                               f"请填写渠道起始水位后点击【执行计算】按钮")
            
        except ImportError:
            messagebox.showerror("错误", "需要安装 pandas 库\n请运行: pip install pandas")
        except Exception as e:
            messagebox.showerror("导入错误", f"导入失败:\n{str(e)}")
    
    def import_from_calc_results(self):
        """
        从计算结果导入断面参数
        
        允许用户选择在明渠、渡槽、隧洞、矩形暗涵标签页中已完成的计算结果，
        直接导入到推求水面线的表格中，无需先导出Excel再导入。
        """
        # 获取可用的计算结果
        available_sources = self.shared_data.get_available_sources()
        batch_results = self.shared_data.get_batch_results()
        
        if not available_sources and not batch_results:
            messagebox.showinfo("提示", 
                "暂无可用的计算结果\n\n"
                "请先在【明渠】【渡槽】【隧洞】【矩形暗涵】标签页中完成计算，\n"
                "或在【多流量段批量计算】标签页中完成批量计算。")
            return
        
        # 创建选择对话框
        dialog = CalcResultImportDialog(
            self.root, 
            self.shared_data,
            on_import=self._do_import_from_calc_result
        )
    
    def _do_import_from_calc_result(self, results: List[Any]):
        """
        执行从计算结果导入
        
        支持从批量计算结果导入完整数据，包括：
        - 基础信息（渠道名称、类型、起始水位、起始桩号）
        - 坐标（X、Y）
        - 流量段、建筑物名称
        - 完整的断面参数和水力参数
        
        Args:
            results: SectionResult对象列表
        """
        if not results:
            return
        
        try:
            from models.enums import StructureType
            
            new_nodes = []
            flow_segment_map = {}
            
            # 检测是否有批量计算结果（含基础信息）
            first_result = results[0]
            has_batch_info = (hasattr(first_result, 'channel_name') and first_result.channel_name) or \
                             (hasattr(first_result, 'flow_section') and first_result.flow_section)
            
            # 如果有基础信息，同步到界面
            if has_batch_info and hasattr(first_result, 'channel_name') and first_result.channel_name:
                self.settings_panel.var_channel_name.set(first_result.channel_name)
            if has_batch_info and hasattr(first_result, 'channel_level') and first_result.channel_level:
                # 验证是否为有效的渠道级别选项
                valid_levels = [
                    "总干渠", "总干管", "分干渠", "分干管", 
                    "干渠", "干管", "支渠", "支管", "分支渠", "分支管"
                ]
                if first_result.channel_level in valid_levels:
                    self.settings_panel.var_channel_level.set(first_result.channel_level)
            if has_batch_info and hasattr(first_result, 'start_water_level') and first_result.start_water_level > 0:
                self.settings_panel.var_start_water_level.set(str(first_result.start_water_level))
            if has_batch_info and hasattr(first_result, 'start_station'):
                try:
                    self.settings_panel.set_start_station_value(first_result.start_station)
                except:
                    pass
            
            for i, result in enumerate(results):
                node = ChannelNode()
                
                # 设置流量段（优先使用批量计算的flow_section）
                if hasattr(result, 'flow_section') and result.flow_section:
                    node.flow_section = str(result.flow_section)
                    try:
                        flow_section_num = int(result.flow_section)
                    except (ValueError, TypeError):
                        flow_section_num = i + 1
                else:
                    flow_section_num = i + 1
                    node.flow_section = str(flow_section_num)
                
                # 设置建筑物名称（优先使用批量计算的building_name）
                if hasattr(result, 'building_name') and result.building_name:
                    node.name = result.building_name
                else:
                    node.name = result.source
                
                # 设置坐标（从批量计算结果中获取）
                if hasattr(result, 'coord_X'):
                    node.x = result.coord_X if result.coord_X else 0.0
                if hasattr(result, 'coord_Y'):
                    node.y = result.coord_Y if result.coord_Y else 0.0
                
                # 设置结构形式
                section_type = result.section_type
                try:
                    # 首先尝试直接解析（批量计算结果的section_type与枚举值一致）
                    node.structure_type = StructureType.from_string(section_type)
                except ValueError:
                    # 如果直接解析失败，尝试模糊匹配
                    try:
                        if "明渠-梯形" in section_type or section_type == "梯形":
                            node.structure_type = StructureType.from_string("明渠-梯形")
                        elif "明渠-矩形" in section_type:
                            node.structure_type = StructureType.from_string("明渠-矩形")
                        elif "明渠-圆形" in section_type:
                            node.structure_type = StructureType.from_string("明渠-圆形")
                        elif "渡槽-U形" in section_type or "U形渡槽" in section_type:
                            node.structure_type = StructureType.from_string("渡槽-U形")
                        elif "渡槽-矩形" in section_type:
                            node.structure_type = StructureType.from_string("渡槽-矩形")
                        elif "隧洞-圆形" in section_type:
                            node.structure_type = StructureType.from_string("隧洞-圆形")
                        elif "隧洞-圆拱直墙" in section_type:
                            node.structure_type = StructureType.from_string("隧洞-圆拱直墙型")
                        elif "隧洞-马蹄形Ⅰ" in section_type:
                            node.structure_type = StructureType.from_string("隧洞-马蹄形Ⅰ型")
                        elif "隧洞-马蹄形Ⅱ" in section_type:
                            node.structure_type = StructureType.from_string("隧洞-马蹄形Ⅱ型")
                        elif "矩形暗涵" in section_type or "暗涵" in section_type:
                            node.structure_type = StructureType.from_string("矩形暗涵")
                        elif "倒虹吸" in section_type:
                            node.structure_type = StructureType.from_string("倒虹吸")
                        elif "分水闸" in section_type:
                            node.structure_type = StructureType.from_string("分水闸")
                        elif "分水口" in section_type:
                            node.structure_type = StructureType.from_string("分水口")
                        elif "分水" in section_type:
                            node.structure_type = StructureType.from_string("分水闸")
                        elif "渐变段" in section_type:
                            node.structure_type = StructureType.from_string("渐变段")
                        elif "矩形" in section_type:
                            node.structure_type = StructureType.from_string("矩形")
                        elif "隧洞" in section_type:
                            node.structure_type = StructureType.from_string("隧洞")
                        elif "渡槽" in section_type:
                            node.structure_type = StructureType.from_string("渡槽")
                    except ValueError:
                        # 如果仍然失败，打印警告
                        print(f"警告：无法识别结构形式 '{section_type}'，跳过设置")
                
                # 设置流量
                node.flow = result.Q
                if flow_section_num not in flow_segment_map and result.Q > 0:
                    flow_segment_map[flow_section_num] = result.Q
                
                # 设置糙率
                node.roughness = result.n
                
                # 设置比降
                if result.slope_inv and result.slope_inv > 0:
                    node.slope_i = 1.0 / result.slope_inv
                
                # 设置水深
                node.water_depth = result.h if result.h else 0.0
                
                # 设置流速
                node.velocity = result.V
                
                # 设置断面参数
                if result.B:
                    node.section_params["B"] = result.B
                if result.m:
                    node.section_params["m"] = result.m
                if result.D:
                    node.section_params["D"] = result.D
                if result.R:
                    node.section_params["R_circle"] = result.R
                if result.A:
                    node.section_params["A"] = result.A
                if result.X:
                    node.section_params["X"] = result.X
                if result.R_hydraulic:
                    node.section_params["R"] = result.R_hydraulic
                
                new_nodes.append(node)
            
            if not new_nodes:
                messagebox.showwarning("警告", "没有有效的数据可导入")
                return
            
            # 计算推荐的转弯半径
            recommended_turn_radius = self._calculate_recommended_turn_radius(new_nodes)
            
            # 更新表格
            self.data_table.set_nodes(new_nodes)
            
            # 更新转弯半径
            if self.data_table._project_settings:
                self.data_table._project_settings.turn_radius = recommended_turn_radius
            self.settings_panel.var_turn_radius.set(f"{recommended_turn_radius:.1f}")
            
            # 提取流量段的设计流量并填入基础设置区
            if flow_segment_map:
                sorted_segments = sorted(flow_segment_map.keys())
                design_flows = [flow_segment_map[seg] for seg in sorted_segments]
                self.settings_panel.set_design_flows(design_flows)
                self.settings_panel._calculate_max_flows()
            
            # 切换到推求水面线标签页
            if hasattr(self, 'water_profile_tab'):
                self.main_notebook.select(self.water_profile_tab)
            
            # 构建完成提示信息
            info_parts = [f"已成功导入 {len(new_nodes)} 条计算结果"]
            if has_batch_info:
                info_parts.append("已同步基础设置（渠道名称、起始水位等）")
            info_parts.append(f"已自动计算转弯半径R = {recommended_turn_radius:.1f} m")
            info_parts.append("请检查参数后点击【执行计算】按钮")
            
            messagebox.showinfo("完成", "\n".join(info_parts))
            
        except Exception as e:
            messagebox.showerror("导入错误", f"导入失败:\n{str(e)}")
    
    def _calculate_recommended_turn_radius(self, nodes: list) -> float:
        """
        根据规范计算推荐的转弯半径
        
        按照"从严不从宽、取大值"的原则确定：
        - 隧洞：弯曲半径不宜小于洞径（或洞宽）的5倍
        - 明渠：弯曲半径不应小于该段水面宽度的5倍
        - 渡槽进口转弯段：弯道半径宜不小于与其连接的明渠的渠底宽度的5倍
        
        Args:
            nodes: ChannelNode列表
            
        Returns:
            推荐的转弯半径（m）
        """
        from models.enums import StructureType
        
        max_turn_radius = 0.0
        
        for node in nodes:
            if not node.structure_type:
                continue
            
            struct_value = node.structure_type.value
            
            # 获取断面尺寸参数
            # B: 底宽或直径, R_circle: 圆形断面半径, m: 边坡系数
            b_or_d = node.section_params.get("B", 0)  # 底宽或直径
            r_circle = node.section_params.get("R_circle", 0)  # 圆形断面半径
            side_slope = node.section_params.get("m", 0)  # 边坡系数
            water_depth = node.water_depth  # 水深
            
            min_radius = 0.0
            
            # 判断结构类型并计算最小转弯半径
            if "隧洞" in struct_value:
                # 隧洞：弯曲半径不宜小于洞径（或洞宽）的5倍
                if r_circle > 0:
                    # 圆形隧洞，直径 = 2 * 半径
                    tunnel_diameter = r_circle * 2
                    min_radius = tunnel_diameter * 5
                elif b_or_d > 0:
                    # 其他类型隧洞，使用宽度参数
                    min_radius = b_or_d * 5
                    
            elif "明渠" in struct_value or struct_value in ["矩形"]:
                # 明渠：弯曲半径不应小于该段水面宽度的5倍
                # 水面宽度计算：
                # - 矩形渠道：水面宽度 = 底宽B
                # - 梯形渠道：水面宽度 = B + 2 * m * h
                if b_or_d > 0:
                    if side_slope > 0 and water_depth > 0:
                        # 梯形渠道：水面宽度 = 底宽 + 2 * 边坡系数 * 水深
                        water_surface_width = b_or_d + 2 * side_slope * water_depth
                    else:
                        # 矩形渠道或无法计算时使用底宽
                        water_surface_width = b_or_d
                    min_radius = water_surface_width * 5
                    
            elif "渡槽" in struct_value:
                # 渡槽进口转弯段：弯道半径宜不小于与其连接的明渠的渠底宽度的5倍
                # 此处使用渡槽自身的宽度作为参考
                if b_or_d > 0:
                    min_radius = b_or_d * 5
                    
            elif "暗涵" in struct_value:
                # 矩形暗涵：按隧洞标准，取宽度的5倍
                if b_or_d > 0:
                    min_radius = b_or_d * 5
            
            # 取最大值
            if min_radius > max_turn_radius:
                max_turn_radius = min_radius
        
        # 如果没有计算出有效值，返回默认值
        if max_turn_radius <= 0:
            from config.constants import DEFAULT_TURN_RADIUS
            max_turn_radius = DEFAULT_TURN_RADIUS
        
        # 向上取整到整数（工程习惯）
        import math
        return math.ceil(max_turn_radius)
    
    def _is_valid_data_value(self, val) -> bool:
        """检查值是否为有效数据（非标题行）"""
        import pandas as pd
        if pd.isna(val):
            return False
        val_str = str(val).strip()
        if not val_str:
            return False
        # 检查是否为标题行的标识
        if val_str in ["流量段", "序号"]:
            return False
        return True
    
    def _parse_float(self, val, default: float = 0.0) -> float:
        """安全解析浮点数"""
        import pandas as pd
        if pd.isna(val):
            return default
        try:
            # 处理"-"等特殊值
            val_str = str(val).strip()
            if val_str in ["-", "", "N/A", "nan"]:
                return default
            return float(val_str)
        except (ValueError, TypeError):
            return default
    
    def open_siphon_calculator(self):
        """打开倒虹吸水力计算窗口"""
        try:
            from utils.siphon_extractor import SiphonDataExtractor
            from managers.siphon_manager import SiphonManager
            from ui.multi_siphon_window import MultiSiphonWindow
            
            # 获取表格数据
            nodes = self.data_table.get_nodes()
            if not nodes:
                messagebox.showinfo("提示", "表格中没有数据\n请先导入断面参数")
                return
            
            # 识别倒虹吸
            siphon_groups = SiphonDataExtractor.extract_siphons(nodes)
            if not siphon_groups:
                messagebox.showinfo("提示", "表格中没有倒虹吸数据\n请确保有结构形式为\"倒虹吸\"的行")
                return
            
            # 获取项目路径
            project_path = getattr(self, '_current_project_path', None)
            if not project_path:
                # 使用默认路径
                project_path = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "default_project"
                )
            
            # 创建管理器
            manager = SiphonManager(project_path)
            
            # 定义导入回调函数
            def import_losses_callback(results):
                """导入倒虹吸水头损失到表格"""
                nodes = self.data_table.get_nodes()
                siphon_groups = SiphonDataExtractor.extract_siphons(nodes)
                
                imported_count = 0
                for group in siphon_groups:
                    if group.name in results and results[group.name] is not None:
                        outlet_idx = group.outlet_row_index
                        if 0 <= outlet_idx < len(nodes):
                            nodes[outlet_idx].head_loss_siphon = results[group.name]
                            imported_count += 1
                
                if imported_count > 0:
                    self.data_table.set_nodes(nodes)
                
                return imported_count
            
            # 打开多标签页窗口
            window = MultiSiphonWindow(
                self.root, 
                siphon_groups, 
                manager,
                on_import_losses=import_losses_callback
            )
            
            # 保存窗口引用（防止被垃圾回收）
            self._siphon_window = window
            
        except ImportError as e:
            messagebox.showerror("错误", f"模块导入失败: {str(e)}\n请确保倒虹吸计算系统已正确安装")
        except Exception as e:
            import traceback
            traceback.print_exc()
            messagebox.showerror("错误", f"打开倒虹吸计算窗口失败: {str(e)}")
    
    def show_about(self):
        """显示关于对话框"""
        about_text = f"""
{APP_FULL_TITLE}

功能说明：
- 渠系建筑物断面尺寸计算（明渠、渡槽、隧洞、矩形暗涵）
- 多流量段批量计算
- 渠道平面几何计算（方位角、转角、桩号等）
- 水面线推求（水位、流速、水头损失等）
- 支持Excel数据导入导出
- 支持从计算结果直接导入断面参数

版本: V2.0 (整合版)
        """
        messagebox.showinfo("关于", about_text.strip())
    
    def run(self):
        """运行主窗口"""
        self.root.mainloop()


class CalcResultImportDialog(tk.Toplevel):
    """
    计算结果导入对话框
    
    用于选择要导入到推求水面线表格的计算结果。
    """
    
    def __init__(self, parent, shared_data, on_import=None):
        """
        初始化对话框
        
        Args:
            parent: 父窗口
            shared_data: SharedDataManager实例
            on_import: 导入回调函数，接收选中的SectionResult列表
        """
        super().__init__(parent)
        
        self.shared_data = shared_data
        self.on_import = on_import
        self.selected_results = []
        
        self.title("从计算结果导入断面参数")
        self.geometry("650x620")
        self.resizable(True, True)
        
        # 模态对话框
        self.transient(parent)
        self.grab_set()
        
        self._create_ui()
        self._load_results()
        
        # 居中显示
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
    
    def _create_ui(self):
        """创建UI"""
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 说明文字
        ttk.Label(main_frame, text="选择要导入的计算结果：", 
                  font=('', 10, 'bold')).pack(anchor=tk.W, pady=(0, 10))
        
        # 单项计算结果区域
        single_frame = ttk.LabelFrame(main_frame, text="单项计算结果", padding=5)
        single_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # 创建Treeview（带复选框效果）
        columns = ("来源", "断面类型", "流量Q", "尺寸参数", "流速V")
        self.single_tree = ttk.Treeview(single_frame, columns=columns, show='headings', 
                                         selectmode='extended', height=8)
        
        self.single_tree.heading("来源", text="来源")
        self.single_tree.heading("断面类型", text="断面类型")
        self.single_tree.heading("流量Q", text="流量Q(m³/s)")
        self.single_tree.heading("尺寸参数", text="尺寸参数")
        self.single_tree.heading("流速V", text="流速V(m/s)")
        
        self.single_tree.column("来源", width=100)
        self.single_tree.column("断面类型", width=80)
        self.single_tree.column("流量Q", width=100)
        self.single_tree.column("尺寸参数", width=200)
        self.single_tree.column("流速V", width=100)
        
        scrollbar = ttk.Scrollbar(single_frame, orient=tk.VERTICAL, 
                                   command=self.single_tree.yview)
        self.single_tree.configure(yscrollcommand=scrollbar.set)
        
        self.single_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 批量计算结果区域
        batch_frame = ttk.LabelFrame(main_frame, text="批量计算结果", padding=5)
        batch_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        self.batch_tree = ttk.Treeview(batch_frame, columns=columns, show='headings',
                                        selectmode='extended', height=6)
        
        for col in columns:
            self.batch_tree.heading(col, text=col if col != "流量Q" else "流量Q(m³/s)")
            if col == "尺寸参数":
                self.batch_tree.column(col, width=200)
            else:
                self.batch_tree.column(col, width=100)
        
        batch_scrollbar = ttk.Scrollbar(batch_frame, orient=tk.VERTICAL,
                                         command=self.batch_tree.yview)
        self.batch_tree.configure(yscrollcommand=batch_scrollbar.set)
        
        self.batch_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        batch_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 选择提示
        self.selection_label = ttk.Label(main_frame, text="提示：按住Ctrl可多选，按住Shift可连选")
        self.selection_label.pack(anchor=tk.W, pady=5)
        
        # 按钮区域
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(10, 0))
        
        ttk.Button(btn_frame, text="全选单项", 
                   command=self._select_all_single).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="全选批量", 
                   command=self._select_all_batch).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="取消选择", 
                   command=self._clear_selection).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(btn_frame, text="导入选中项", 
                   command=self._do_import).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="取消", 
                   command=self.destroy).pack(side=tk.RIGHT, padx=5)
    
    def _load_results(self):
        """加载计算结果到列表"""
        # 加载单项计算结果
        for source, result in self.shared_data.get_all_results().items():
            values = (
                source,
                result.section_type,
                f"{result.Q:.3f}" if result.Q else "-",
                result.get_display_info(),
                f"{result.V:.3f}" if result.V else "-"
            )
            self.single_tree.insert("", tk.END, values=values, tags=(source,))
        
        # 加载批量计算结果
        for i, result in enumerate(self.shared_data.get_batch_results()):
            values = (
                f"批量-{i+1}",
                result.section_type,
                f"{result.Q:.3f}" if result.Q else "-",
                result.get_display_info(),
                f"{result.V:.3f}" if result.V else "-"
            )
            self.batch_tree.insert("", tk.END, values=values, tags=(f"batch_{i}",))
    
    def _select_all_single(self):
        """全选单项结果"""
        for item in self.single_tree.get_children():
            self.single_tree.selection_add(item)
    
    def _select_all_batch(self):
        """全选批量结果"""
        for item in self.batch_tree.get_children():
            self.batch_tree.selection_add(item)
    
    def _clear_selection(self):
        """取消所有选择"""
        for item in self.single_tree.selection():
            self.single_tree.selection_remove(item)
        for item in self.batch_tree.selection():
            self.batch_tree.selection_remove(item)
    
    def _do_import(self):
        """执行导入"""
        results = []
        
        # 获取选中的单项结果
        for item in self.single_tree.selection():
            tags = self.single_tree.item(item, 'tags')
            if tags:
                source = tags[0]
                result = self.shared_data.get_result(source)
                if result:
                    results.append(result)
        
        # 获取选中的批量结果
        batch_results = self.shared_data.get_batch_results()
        for item in self.batch_tree.selection():
            tags = self.batch_tree.item(item, 'tags')
            if tags:
                tag = tags[0]
                if tag.startswith("batch_"):
                    idx = int(tag.split("_")[1])
                    if 0 <= idx < len(batch_results):
                        results.append(batch_results[idx])
        
        if not results:
            messagebox.showwarning("提示", "请至少选择一项计算结果")
            return
        
        # 调用回调函数
        if self.on_import:
            self.on_import(results)
        
        self.destroy()
