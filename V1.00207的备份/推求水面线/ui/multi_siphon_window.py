# -*- coding: utf-8 -*-
"""
多标签页倒虹吸计算窗口

支持多个倒虹吸的并行计算，每个倒虹吸一个标签页。
"""

import tkinter as tk
from tkinter import ttk, messagebox
from typing import List, Dict, Optional
from datetime import datetime

from .siphon_tab_panel import SiphonTabPanel

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.siphon_extractor import SiphonGroup
from managers.siphon_manager import SiphonManager, SiphonConfig


class MultiSiphonWindow(tk.Toplevel):
    """
    多标签页倒虹吸计算窗口
    
    管理多个倒虹吸的计算，每个倒虹吸一个标签页。
    """
    
    def __init__(self, parent, siphon_groups: List[SiphonGroup], manager: SiphonManager,
                 on_import_losses=None):
        """
        初始化窗口
        
        Args:
            parent: 父窗口
            siphon_groups: 倒虹吸分组列表
            manager: 倒虹吸数据管理器
            on_import_losses: 导入水损回调函数，签名: callback(results: Dict[str, float]) -> int
        """
        super().__init__(parent)
        
        self.parent = parent
        self.siphon_groups = siphon_groups
        self.manager = manager
        self.on_import_losses = on_import_losses
        
        # 面板字典 {倒虹吸名称: SiphonTabPanel}
        self.panels: Dict[str, SiphonTabPanel] = {}
        
        # 配置窗口
        self._configure_window()
        
        # 创建界面
        self._create_ui()
        
        # 加载历史数据
        self._load_saved_data()
        
        # 绑定关闭事件
        self.protocol("WM_DELETE_WINDOW", self._on_close)
    
    def _configure_window(self):
        """配置窗口属性"""
        self.title("倒虹吸水力计算")
        self.geometry("1200x950")
        self.minsize(1000, 850)
        
        # 使窗口模态化（可选）
        # self.transient(self.parent)
        # self.grab_set()
        
        # 居中显示
        self.update_idletasks()
        x = (self.winfo_screenwidth() - 1200) // 2
        y = (self.winfo_screenheight() - 950) // 2
        self.geometry(f"+{x}+{y}")
    
    def _create_ui(self):
        """创建用户界面"""
        # 顶部工具栏
        self._create_toolbar()
        
        # 中部标签页容器
        self._create_notebook()
        
        # 底部状态栏
        self._create_status_bar()
    
    def _create_toolbar(self):
        """创建顶部工具栏"""
        toolbar = ttk.Frame(self)
        toolbar.pack(fill=tk.X, padx=5, pady=5)
        
        # 左侧按钮
        ttk.Button(toolbar, text="保存全部", command=self._save_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="全部计算", command=self._calculate_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="导出倒虹吸水头损失", command=self._import_losses).pack(side=tk.LEFT, padx=2)
        
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=10, fill=tk.Y)
        
        # 倒虹吸数量提示
        count = len(self.siphon_groups)
        ttk.Label(toolbar, text=f"共 {count} 个倒虹吸").pack(side=tk.LEFT, padx=5)
        
        # 右侧按钮
        ttk.Button(toolbar, text="关闭", command=self._on_close).pack(side=tk.RIGHT, padx=2)
    
    def _create_notebook(self):
        """创建标签页容器"""
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 为每个倒虹吸创建标签页
        for group in self.siphon_groups:
            self._add_siphon_tab(group)
    
    def _add_siphon_tab(self, group: SiphonGroup):
        """
        添加倒虹吸标签页
        
        Args:
            group: 倒虹吸分组数据
        """
        # 创建面板
        panel = SiphonTabPanel(
            self.notebook, 
            group.name,
            on_result_changed=self._on_result_changed
        )
        
        # 设置初始参数（从水面线系统传递，含平面段数据）
        panel.set_params(
            Q=group.design_flow,
            H_up=group.upstream_level,
            H_down=group.downstream_level,
            roughness_n=group.roughness,
            H_bottom=group.upstream_bottom_elev,
            plan_segments=group.plan_segments,
            plan_total_length=group.plan_total_length,
            plan_feature_points=group.plan_feature_points,
        )
        
        # 添加到 Notebook
        self.notebook.add(panel, text=group.name)
        
        # 保存引用
        self.panels[group.name] = panel
    
    def _create_status_bar(self):
        """创建底部状态栏"""
        status_frame = ttk.Frame(self)
        status_frame.pack(fill=tk.X, padx=5, pady=2)
        
        self.status_label = ttk.Label(status_frame, text="就绪")
        self.status_label.pack(side=tk.LEFT)
        
        self.time_label = ttk.Label(status_frame, text="")
        self.time_label.pack(side=tk.RIGHT)
        
        # 更新时间显示
        self._update_time_label()
    
    def _update_time_label(self):
        """更新最后保存时间显示"""
        last_modified = self.manager.last_modified
        if last_modified:
            self.time_label.config(text=f"上次保存: {last_modified}")
        else:
            self.time_label.config(text="")
    
    def _load_saved_data(self):
        """加载已保存的数据"""
        for name, panel in self.panels.items():
            config = self.manager.get_siphon_config(name)
            if config:
                # 转换为字典格式
                data = {
                    "Q": config.Q,
                    "v_guess": config.v_guess,
                    "H_up": config.H_up,
                    "H_down": config.H_down,
                    "H_bottom": config.H_bottom,
                    "roughness_n": config.roughness_n,
                    "D_custom": config.D_custom,
                    "inlet_type": config.inlet_type,
                    "outlet_type": config.outlet_type,
                    "xi_inlet": config.xi_inlet,
                    "xi_outlet": config.xi_outlet,
                    "v_channel_in": config.v_channel_in,
                    "v_pipe_in": config.v_pipe_in,
                    "v_channel_out": config.v_channel_out,
                    "v_pipe_out": config.v_pipe_out,
                    "segments": config.segments,
                }
                panel.from_dict(data)
        
        self._update_status(f"已加载 {len(self.panels)} 个倒虹吸的配置")
    
    def _save_all(self):
        """保存所有倒虹吸的配置"""
        try:
            for name, panel in self.panels.items():
                data = panel.to_dict()
                
                config = SiphonConfig(
                    name=name,
                    Q=data.get("Q", 0.0),
                    v_guess=data.get("v_guess", 2.0),
                    H_up=data.get("H_up", 0.0),
                    H_down=data.get("H_down", 0.0),
                    H_bottom=data.get("H_bottom", 0.0),
                    roughness_n=data.get("roughness_n", 0.014),
                    D_custom=data.get("D_custom", ""),
                    inlet_type=data.get("inlet_type", "曲线形反弯扭曲面"),
                    outlet_type=data.get("outlet_type", "曲线形反弯扭曲面"),
                    xi_inlet=data.get("xi_inlet", 0.1),
                    xi_outlet=data.get("xi_outlet", 0.2),
                    v_channel_in=data.get("v_channel_in", 0.0),
                    v_pipe_in=data.get("v_pipe_in", 0.0),
                    v_channel_out=data.get("v_channel_out", 0.0),
                    v_pipe_out=data.get("v_pipe_out", 0.0),
                    segments=data.get("segments", []),
                    plan_segments=data.get("plan_segments", []),
                    plan_total_length=data.get("plan_total_length", 0.0),
                    plan_feature_points=data.get("plan_feature_points", []),
                    longitudinal_nodes=data.get("longitudinal_nodes", []),
                    total_head_loss=data.get("total_head_loss"),
                )
                
                self.manager.set_siphon_config(config)
            
            self.manager.save_config()
            self._update_time_label()
            self._update_status("已保存所有配置")
            
        except Exception as e:
            messagebox.showerror("保存失败", f"保存配置时出错: {str(e)}")
    
    def _calculate_all(self):
        """计算所有倒虹吸"""
        success_count = 0
        fail_count = 0
        
        for name, panel in self.panels.items():
            try:
                panel._execute_calculation()
                if panel.get_result() is not None:
                    success_count += 1
                else:
                    fail_count += 1
            except Exception as e:
                fail_count += 1
                print(f"计算 {name} 失败: {e}")
        
        # 保存结果
        self._save_all()
        
        self._update_status(f"计算完成: {success_count} 成功, {fail_count} 失败")
        
        if fail_count > 0:
            messagebox.showwarning("计算完成", 
                f"共 {success_count + fail_count} 个倒虹吸\n"
                f"成功: {success_count}\n"
                f"失败: {fail_count}")
    
    def _on_result_changed(self, siphon_name: str, result):
        """
        计算结果变化回调
        
        Args:
            siphon_name: 倒虹吸名称
            result: 计算结果
        """
        if result is not None:
            # 更新管理器中的结果
            self.manager.update_siphon_result(
                siphon_name, 
                result.total_head_loss,
                result.diameter
            )
            self.manager.save_config()
            self._update_time_label()
            
            self._update_status(f"{siphon_name}: 总水头损失 = {result.total_head_loss:.4f} m")
    
    def _update_status(self, message: str):
        """更新状态栏消息"""
        self.status_label.config(text=message)
    
    def _on_close(self):
        """关闭窗口前保存"""
        # 询问是否保存
        if self.panels:
            save = messagebox.askyesnocancel("关闭", "是否保存当前配置？")
            if save is None:
                return  # 取消关闭
            if save:
                self._save_all()
        
        self.destroy()
    
    def get_all_results(self) -> Dict[str, float]:
        """
        获取所有倒虹吸的计算结果
        
        Returns:
            {倒虹吸名称: 总水头损失} 字典
        """
        results = {}
        for name, panel in self.panels.items():
            result = panel.get_result()
            if result is not None:
                results[name] = result.total_head_loss
        return results
    
    def _import_losses(self):
        """导入倒虹吸水头损失到主表格"""
        # 先保存当前数据
        self._save_all()
        
        # 获取所有计算结果
        results = self.get_all_results()
        
        if not results:
            messagebox.showinfo("提示", "没有可导入的计算结果\n请先执行计算")
            return
        
        # 调用回调函数导入到主表格
        if self.on_import_losses:
            imported_count = self.on_import_losses(results)
            if imported_count > 0:
                messagebox.showinfo("导入完成", f"已导入 {imported_count} 个倒虹吸的水头损失")
            else:
                messagebox.showinfo("提示", "未能导入任何数据")
        else:
            messagebox.showwarning("警告", "导入回调未配置")
