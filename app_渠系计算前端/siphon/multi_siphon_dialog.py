# -*- coding: utf-8 -*-
"""
多标签页倒虹吸计算窗口（PySide6版）

支持多个倒虹吸的并行计算，每个倒虹吸一个标签页。
功能复刻自原版 Tkinter MultiSiphonWindow：
- 从水面线表格自动提取倒虹吸分组数据
- 每个倒虹吸独立标签页（SiphonPanel）
- 参数自动导入（流量、糙率、流速、渐变段、断面参数、平面段等）
- 全部计算并导出水头损失到主表格
- SiphonManager 持久化（保存/加载历史配置）
- 计算结果汇总对话框
"""

import os
import sys
from typing import List, Dict, Optional, Callable
from datetime import datetime

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QLabel,
    QWidget, QProgressBar, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QCheckBox,
    QSizePolicy, QFrame
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont

from qfluentwidgets import (
    PushButton, PrimaryPushButton, InfoBar, InfoBarPosition
)

from app_渠系计算前端.siphon.panel import SiphonPanel
from app_渠系计算前端.styles import P, S, T1, T2, BD, auto_resize_table, DIALOG_STYLE

# 倒虹吸系统路径
_pkg_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_siphon_dir = os.path.join(_pkg_root, '倒虹吸水力计算系统')
if _siphon_dir not in sys.path:
    sys.path.insert(0, _siphon_dir)

# SiphonManager (来自推求水面线模块)
_water_profile_dir = os.path.join(_pkg_root, '推求水面线')
if _water_profile_dir not in sys.path:
    sys.path.insert(0, _water_profile_dir)

try:
    from managers.siphon_manager import SiphonManager, SiphonConfig
    MANAGER_AVAILABLE = True
except ImportError:
    MANAGER_AVAILABLE = False

# SiphonDataExtractor
try:
    from utils.siphon_extractor import SiphonDataExtractor, SiphonGroup
    EXTRACTOR_AVAILABLE = True
except ImportError:
    EXTRACTOR_AVAILABLE = False


class MultiSiphonDialog(QDialog):
    """
    多标签页倒虹吸计算窗口（PySide6版）

    管理多个倒虹吸的计算，每个倒虹吸一个标签页。
    """

    def __init__(self, parent, siphon_groups: List,
                 manager=None,
                 on_import_losses: Callable = None,
                 siphon_turn_radius_n: float = 0.0,
                 show_case_management: bool = False):
        """
        初始化窗口

        Args:
            parent: 父窗口
            siphon_groups: 倒虹吸分组列表 (SiphonGroup)
            manager: SiphonManager 实例（持久化用）
            on_import_losses: 导入水损回调函数，签名: callback(results: Dict) -> int
            siphon_turn_radius_n: 倒虹吸转弯半径倍数n（R = n × D）
            show_case_management: 是否显示单面板中的“工况管理”区
        """
        super().__init__(parent)
        print(f"[DEBUG MultiSiphonDialog] __init__ 开始, siphon_groups数量: {len(siphon_groups)}")
        self.siphon_groups = siphon_groups
        self.manager = manager
        self.on_import_losses = on_import_losses
        self._siphon_turn_radius_n = siphon_turn_radius_n
        self._show_case_management = bool(show_case_management)

        # 面板字典 {倒虹吸名称: SiphonPanel}
        self.panels: Dict[str, SiphonPanel] = {}

        print("[DEBUG MultiSiphonDialog] 调用 _configure_window()")
        self._configure_window()
        print("[DEBUG MultiSiphonDialog] 调用 _create_ui()")
        self._create_ui()
        print("[DEBUG MultiSiphonDialog] 调用 _load_saved_data()")
        self._load_saved_data()
        print("[DEBUG MultiSiphonDialog] __init__ 完成")

        # 标记第一次显示，用于 showEvent 中的置顶操作
        self._first_show = True

    def showEvent(self, event):
        """窗口显示事件，确保首次显示时置顶"""
        super().showEvent(event)
        if self._first_show:
            self._first_show = False
            # 延迟置顶，确保窗口已完全显示
            QTimer.singleShot(50, self._ensure_visible)

    def _configure_window(self):
        """配置窗口属性"""
        count = len(self.siphon_groups)
        self.setWindowTitle(f"倒虹吸水力计算 - 共 {count} 个倒虹吸")
        self.setMinimumSize(1100, 700)
        self.resize(1400, 900)
        # 非模态，允许用户同时操作主窗口
        self.setWindowFlags(self.windowFlags() | Qt.Window)
        # 居中显示，确保窗口不超出屏幕
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        if screen:
            screen_geo = screen.availableGeometry()
            w = min(self.width(), screen_geo.width())
            h = min(self.height(), screen_geo.height())
            self.resize(w, h)
            x = screen_geo.x() + (screen_geo.width() - w) // 2
            y = screen_geo.y() + (screen_geo.height() - h) // 2
            self.move(x, y)
        # 确保窗口置顶显示并激活
        self.raise_()
        self.activateWindow()

    def _ensure_visible(self):
        """确保窗口可见并置顶"""
        # 强制置顶并激活窗口
        self.raise_()
        self.activateWindow()
        # Windows 下需要额外的置顶操作
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)
        print("[DEBUG MultiSiphonDialog] _ensure_visible() 已执行，窗口应当可见")

    def keyPressEvent(self, event):
        """
        覆盖键盘事件处理，阻止 ESC 键关闭窗口

        ESC 键容易误触，不作为关闭快捷键。
        用户必须点击"关闭"按钮来关闭窗口。
        """
        if event.key() == Qt.Key_Escape:
            # 忽略 ESC 键，不执行任何操作
            event.accept()
            return
        super().keyPressEvent(event)

    def _create_ui(self):
        """创建用户界面"""
        main_lay = QVBoxLayout(self)
        main_lay.setContentsMargins(6, 6, 6, 6)
        main_lay.setSpacing(4)

        # 标签页容器
        self.notebook = QTabWidget()
        self.notebook.setTabsClosable(False)
        self.notebook.setMovable(False)
        main_lay.addWidget(self.notebook, 1)

        # 为每个倒虹吸创建标签页
        for group in self.siphon_groups:
            self._add_siphon_tab(group)

        # 底部操作栏
        self._create_action_bar(main_lay)

        # 底部状态栏
        self._create_status_bar(main_lay)

    def _add_siphon_tab(self, group):
        """
        添加倒虹吸标签页

        Args:
            group: 倒虹吸分组数据 (SiphonGroup)
        """
        panel = SiphonPanel(
            show_case_management=self._show_case_management,
            disable_autosave_load=True,
            siphon_manager=self.manager,
            siphon_name=group.name
        )
        panel.on_result_callback = self._make_result_callback(group.name)
        panel.edit_name.setText(group.name)

        # 设置初始参数（从水面线表格传递）
        params = self._build_params_from_group(group)
        panel.set_params(**params)

        # 添加到 TabWidget
        self.notebook.addTab(panel, group.name)
        self.panels[group.name] = panel

    def _build_params_from_group(self, group) -> dict:
        """从 SiphonGroup 构建 set_params 所需的参数字典"""
        params = {
            'Q': group.design_flow,
            'roughness_n': group.roughness,
            'siphon_name': group.name,
        }

        # 渐变段型式
        if group.inlet_transition_form:
            params['inlet_type'] = group.inlet_transition_form
        if group.outlet_transition_form:
            params['outlet_type'] = group.outlet_transition_form

        # 渐变段系数
        if group.siphon_transition_inlet_zeta > 0:
            params['xi_inlet'] = group.siphon_transition_inlet_zeta
        if group.siphon_transition_outlet_zeta > 0:
            params['xi_outlet'] = group.siphon_transition_outlet_zeta

        # 进口渐变段始端流速 v₁（上游渠道断面平均流速）
        if group.upstream_velocity > 0:
            params['v_channel_in'] = group.upstream_velocity

        # 出口渐变段末端流速 v₃（下游渠道断面平均流速）
        if group.downstream_velocity > 0:
            params['v_pipe_out'] = group.downstream_velocity

        # 加大流量工况流速 v₁加大 / v₃加大（从批量计算结果透传）
        _uv_inc = getattr(group, 'upstream_velocity_increased', 0.0)
        if _uv_inc and _uv_inc > 0:
            params['v_channel_in_inc'] = _uv_inc
        _dv_inc = getattr(group, 'downstream_velocity_increased', 0.0)
        if _dv_inc and _dv_inc > 0:
            params['v_pipe_out_inc'] = _dv_inc

        # 进口上游渠道断面参数（用于自动计算 v₂）
        # 安全判断：先检查 is not None 再比较大小，避免 None > 0 的 TypeError
        _usB = getattr(group, 'upstream_section_B', None)
        _usH = getattr(group, 'upstream_section_h', None)
        _usM = getattr(group, 'upstream_section_m', None)
        if _usB is not None and _usB > 0:
            params['inlet_section_B'] = _usB
        if _usH is not None and _usH > 0:
            params['inlet_section_h'] = _usH
        if _usM is not None:
            params['inlet_section_m'] = _usM

        # 平面段数据
        if group.plan_segments:
            params['plan_segments'] = group.plan_segments
        if group.plan_total_length > 0:
            params['plan_total_length'] = group.plan_total_length
        if group.plan_feature_points:
            params['plan_feature_points'] = group.plan_feature_points

        # 弯管半径倍数 n
        if self._siphon_turn_radius_n > 0:
            params['siphon_turn_radius_n'] = self._siphon_turn_radius_n

        # 出水口下游断面参数（安全判断 is not None）
        if group.downstream_structure_type:
            params['outlet_downstream_type'] = group.downstream_structure_type
        _dsB = getattr(group, 'downstream_section_B', None)
        _dsH = getattr(group, 'downstream_section_h', None)
        _dsM = getattr(group, 'downstream_section_m', None)
        _dsD = getattr(group, 'downstream_section_D', None)
        _dsR = getattr(group, 'downstream_section_R', None)
        if _dsB is not None and _dsB > 0:
            params['outlet_downstream_B'] = _dsB
        if _dsH is not None and _dsH > 0:
            params['outlet_downstream_h'] = _dsH
        if _dsM is not None:
            params['outlet_downstream_m'] = _dsM
        if _dsD is not None and _dsD > 0:
            params['outlet_downstream_D'] = _dsD
        if _dsR is not None and _dsR > 0:
            params['outlet_downstream_R'] = _dsR

        return params

    def _make_result_callback(self, siphon_name: str):
        """为指定倒虹吸创建计算结果回调"""
        def callback(result):
            if result is not None and self.manager and MANAGER_AVAILABLE:
                self.manager.update_siphon_result(
                    siphon_name,
                    result.total_head_loss,
                    result.diameter
                )
                self.manager.save_config()
                self._update_time_label()
                self._update_status(
                    f"{siphon_name}: 总水头损失 = {result.total_head_loss:.4f} m")
        return callback

    def _create_action_bar(self, parent_lay):
        """
        创建底部操作按钮栏

        3个功能按钮：
        - "执行计算"：计算当前标签页
        - "全部计算并导出水头损失"：计算所有 → 保存 → 导出
        - "导出结果"：导出当前标签页计算结果为txt
        """
        bar = QHBoxLayout()
        bar.setSpacing(6)

        count = len(self.siphon_groups)
        lbl = QLabel(f"共 {count} 个倒虹吸")
        lbl.setStyleSheet(f"color:{T1};font-size:12px;font-weight:bold;")
        bar.addWidget(lbl)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.VLine)
        sep1.setStyleSheet(f"color:{BD};")
        bar.addWidget(sep1)

        btn_calc = PushButton("执行计算")
        btn_calc.setToolTip("计算当前标签页的倒虹吸\n仅对当前查看的倒虹吸执行水力计算")
        btn_calc.clicked.connect(self._calculate_current)
        bar.addWidget(btn_calc)

        btn_calc_all = PrimaryPushButton("全部计算并导出水头损失")
        btn_calc_all.setToolTip(
            "一键完成全部操作：\n① 依次计算所有倒虹吸\n② 自动保存全部配置\n③ 自动将水头损失导回主表格")
        btn_calc_all.clicked.connect(self._calculate_all)
        bar.addWidget(btn_calc_all)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.VLine)
        sep2.setStyleSheet(f"color:{BD};")
        bar.addWidget(sep2)

        btn_export = PushButton("导出Word")
        btn_export.setToolTip("导出当前标签页的Word计算书")
        btn_export.clicked.connect(self._export_current_word)
        bar.addWidget(btn_export)

        bar.addStretch()

        btn_close = PushButton("关闭")
        btn_close.setToolTip("关闭窗口（自动保存配置）")
        btn_close.clicked.connect(self._on_close)
        bar.addWidget(btn_close)

        parent_lay.addLayout(bar)

    def _create_status_bar(self, parent_lay):
        """创建底部状态栏"""
        status_lay = QHBoxLayout()
        status_lay.setSpacing(6)

        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet(f"color:{T2};font-size:11px;")
        status_lay.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(16)
        self.progress_bar.setFixedWidth(200)
        self.progress_bar.setVisible(False)
        status_lay.addWidget(self.progress_bar)

        status_lay.addStretch()

        self.time_label = QLabel("")
        self.time_label.setStyleSheet(f"color:{T2};font-size:10px;")
        status_lay.addWidget(self.time_label)

        parent_lay.addLayout(status_lay)
        self._update_time_label()

    # ================================================================
    # 数据持久化
    # ================================================================
    def _load_saved_data(self):
        """加载已保存的数据，然后用最新表格数据覆盖关键参数"""
        print(f"[DEBUG _load_saved_data] 开始, manager={self.manager is not None}, MANAGER_AVAILABLE={MANAGER_AVAILABLE}")
        if not self.manager or not MANAGER_AVAILABLE:
            self._update_status(f"已加载 {len(self.panels)} 个倒虹吸")
            print("[DEBUG _load_saved_data] manager不可用，返回")
            return

        self._detect_and_migrate_renames()

        for name, panel in self.panels.items():
            config = self.manager.get_siphon_config(name)
            if config:
                # 转换为 panel 可用的字典格式
                data = self._config_to_panel_dict(config)
                panel.from_dict(data)

        # 重新应用来自表格的最新数据（表格数据优先于历史保存）
        print("[DEBUG _load_saved_data] 调用 _reapply_table_data()")
        self._reapply_table_data()
        print("[DEBUG _load_saved_data] _reapply_table_data() 完成")
        self._update_status(f"已加载 {len(self.panels)} 个倒虹吸的配置")
        print("[DEBUG _load_saved_data] 完成")

    def _detect_and_migrate_renames(self):
        """检测倒虹吸名称变更并自动迁移配置和确认态。

        当用户在水面线表格中修改了建筑物名称后，SiphonManager 中保存的
        旧名称数据会变成"孤儿"。此方法通过对比当前分组名称和已保存名称，
        将无法匹配的条目按出现顺序一一配对，自动执行 rename_siphon。
        """
        if not self.manager or not MANAGER_AVAILABLE:
            return
        if not hasattr(self.manager, 'rename_siphon'):
            return

        current_names = [g.name for g in self.siphon_groups]
        saved_names = self.manager.get_siphon_names()

        current_set = set(current_names)
        saved_set = set(saved_names)

        unmatched_current = [n for n in current_names if n not in saved_set]
        unmatched_saved = [n for n in saved_names if n not in current_set]

        if not unmatched_current or not unmatched_saved:
            return

        pairs = min(len(unmatched_current), len(unmatched_saved))
        for i in range(pairs):
            old_name = unmatched_saved[i]
            new_name = unmatched_current[i]
            print(f"[倒虹吸重命名迁移] '{old_name}' → '{new_name}'")
            self.manager.rename_siphon(old_name, new_name)
        self.manager.save_config()

    @staticmethod
    def _normalize_segments(raw_segs: list) -> list:
        """统一结构段字典的键名格式（兼容Tkinter版 segment_type 与 PySide6版 type）"""
        if not raw_segs:
            return []
        result = []
        for s in raw_segs:
            if not isinstance(s, dict):
                result.append(s)
                continue
            sd = dict(s)
            # Tkinter版用 'segment_type'，PySide6版用 'type'
            if 'segment_type' in sd and 'type' not in sd:
                sd['type'] = sd.pop('segment_type')
            if 'direction' not in sd:
                sd['direction'] = '通用'
            result.append(sd)
        return result

    def _config_to_panel_dict(self, config: 'SiphonConfig') -> dict:
        """
        将 SiphonConfig 转换为 SiphonPanel.from_dict() 可用的格式

        PySide6版 SiphonPanel.from_dict() 使用的键名：
          Q, v_guess, n, turn_n, threshold, D_override,
          inlet_type, outlet_type, xi_inlet, xi_outlet,
          v1, v2, v3, v2_strategy, name, show_detail,
          segments（键'type'）, plan_segments, plan_total_length,
          plan_feature_points, longitudinal_nodes, longitudinal_is_example
        """
        d = {
            'Q': config.Q,
            'v_guess': config.v_guess,
            'n': config.roughness_n,
            'inlet_type': config.inlet_type,
            'outlet_type': config.outlet_type,
            'xi_inlet': config.xi_inlet,
            'xi_outlet': config.xi_outlet,
            'name': config.name,
        }
        # 流速：SiphonConfig用v_channel_in/v_pipe_in/v_pipe_out，
        #        SiphonPanel.from_dict()用v1/v2/v3
        if config.v_channel_in > 0:
            d['v1'] = str(config.v_channel_in)
        if config.v_pipe_out > 0:
            d['v3'] = str(config.v_pipe_out)
        if config.v_pipe_in > 0:
            d['v2'] = str(config.v_pipe_in)
        # 出口渐变段始端流速（v_channel_out → SiphonPanel 目前无对应恢复键，
        # 该值由计算引擎自动回填，无需持久化恢复）

        # 结构段（统一键名）
        if config.segments:
            d['segments'] = self._normalize_segments(config.segments)

        # 平面段（统一键名）
        if config.plan_segments:
            d['plan_segments'] = self._normalize_segments(config.plan_segments)
        d['plan_total_length'] = config.plan_total_length
        if config.plan_feature_points:
            d['plan_feature_points'] = config.plan_feature_points

        # 纵断面节点
        if config.longitudinal_nodes:
            d['longitudinal_nodes'] = config.longitudinal_nodes

        # 管道根数
        if config.num_pipes:
            d['num_pipes'] = config.num_pipes
        # 自动确认仅依据“进程内”确认态，避免重启后仍自动确认
        if (self.manager and MANAGER_AVAILABLE
                and hasattr(self.manager, 'is_runtime_confirmed')
                and self.manager.is_runtime_confirmed(config.name)):
            d['calculated_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 从配置字典中读取 PySide6 专有扩展字段（不在 SiphonConfig 数据类中）
        if self.manager and MANAGER_AVAILABLE:
            siphons = self.manager._config.get('siphons', {})
            raw = siphons.get(config.name, {})
            if 'turn_n' in raw:
                d['turn_n'] = raw['turn_n']
            if 'threshold' in raw:
                d['threshold'] = raw['threshold']
            if 'D_override' in raw:
                d['D_override'] = raw['D_override']
            if 'v2_strategy' in raw:
                d['v2_strategy'] = raw['v2_strategy']
            if 'show_detail' in raw:
                d['show_detail'] = raw['show_detail']
            if 'longitudinal_is_example' in raw:
                d['longitudinal_is_example'] = raw['longitudinal_is_example']

        return d

    def _reapply_table_data(self):
        """
        重新应用来自推求水面线表格的最新数据

        加载历史配置后，表格中的关键参数（流量、流速、渐变段型式、
        平面段数据等）应以当前表格数据为准，覆盖历史保存的旧值。
        保留的历史值（不被覆盖）：v_guess、segments（用户自定义的纵断面管段布置）
        """
        print(f"[DEBUG _reapply_table_data] 开始, groups数量: {len(self.siphon_groups)}")
        for group in self.siphon_groups:
            if group.name not in self.panels:
                continue
            panel = self.panels[group.name]
            params = self._build_params_from_group(group)
            print(f"[DEBUG _reapply_table_data] 调用 panel.set_params() for {group.name}")
            # skip_confirm=True: 窗口初始化期间跳过确认对话框
            panel.set_params(skip_confirm=True, **params)
        print("[DEBUG _reapply_table_data] 完成")

    def _save_all(self):
        """
        保存所有倒虹吸的配置

        PySide6版 SiphonPanel.to_dict() 的键名与 SiphonConfig 字段名不同，
        需要做映射：
          to_dict键          SiphonConfig字段
          'n'               roughness_n
          'v1'              v_channel_in
          'v2'              v_pipe_in
          'v3'              v_pipe_out
          'type'(段内)       segment_type(段内)
        """
        if not self.manager or not MANAGER_AVAILABLE:
            return
        try:
            for name, panel in self.panels.items():
                data = panel.to_dict()

                # 结构段键名：PySide6用'type'，SiphonConfig/Tkinter用'segment_type'
                raw_segs = data.get('segments', [])
                saved_segs = []
                for s in raw_segs:
                    if isinstance(s, dict):
                        sd = dict(s)
                        if 'type' in sd and 'segment_type' not in sd:
                            sd['segment_type'] = sd.pop('type')
                        saved_segs.append(sd)
                    else:
                        saved_segs.append(s)

                raw_plan = data.get('plan_segments', [])
                saved_plan = []
                for s in raw_plan:
                    if isinstance(s, dict):
                        sd = dict(s)
                        if 'type' in sd and 'segment_type' not in sd:
                            sd['segment_type'] = sd.pop('type')
                        saved_plan.append(sd)
                    else:
                        saved_plan.append(s)

                config = SiphonConfig(
                    name=name,
                    Q=data.get('Q', 0.0),
                    v_guess=data.get('v_guess', 2.0),
                    roughness_n=self._safe_float(data.get('n', 0.014)),
                    inlet_type=data.get('inlet_type', ''),
                    outlet_type=data.get('outlet_type', ''),
                    xi_inlet=self._safe_float(data.get('xi_inlet', 0.1)),
                    xi_outlet=self._safe_float(data.get('xi_outlet', 0.2)),
                    v_channel_in=self._safe_float(data.get('v1', '0')),
                    v_pipe_in=self._safe_float(data.get('v2', '0')),
                    v_channel_out=0.0,
                    v_pipe_out=self._safe_float(data.get('v3', '0')),
                    segments=saved_segs,
                    plan_segments=saved_plan,
                    plan_total_length=data.get('plan_total_length', 0.0),
                    plan_feature_points=data.get('plan_feature_points', []),
                    longitudinal_nodes=data.get('longitudinal_nodes', []),
                    total_head_loss=data.get('total_head_loss'),
                    diameter=data.get('diameter'),
                    calculated_at='',  # 不保存时间戳，每次打开程序都需要重新确认
                    num_pipes=data.get('num_pipes', 1),
                )
                self.manager.set_siphon_config(config)
                # 追加 PySide6 专有扩展字段到配置字典（SiphonConfig 未定义这些字段）
                siphon_dict = self.manager._config.get('siphons', {}).get(name, {})
                siphon_dict['turn_n'] = data.get('turn_n', 5)
                siphon_dict['threshold'] = data.get('threshold', '')
                siphon_dict['D_override'] = data.get('D_override', '')
                siphon_dict['v2_strategy'] = data.get('v2_strategy', '')
                siphon_dict['show_detail'] = data.get('show_detail', True)
                siphon_dict['longitudinal_is_example'] = data.get('longitudinal_is_example', True)
            self.manager.save_config()
            self._update_time_label()
            self._update_status("已保存所有配置")
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"保存倒虹吸配置失败: {e}")

    @staticmethod
    def _safe_float(val, default=0.0):
        if val is None:
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    # ================================================================
    # 计算操作
    # ================================================================
    def _get_current_panel(self) -> Optional[SiphonPanel]:
        """获取当前选中标签页的面板"""
        idx = self.notebook.currentIndex()
        if idx < 0:
            return None
        widget = self.notebook.widget(idx)
        if isinstance(widget, SiphonPanel):
            return widget
        return None

    def _calculate_current(self):
        """计算当前标签页的倒虹吸"""
        panel = self._get_current_panel()
        if panel:
            panel._execute_calculation()

    def _export_current_word(self):
        """导出当前标签页的Word计算书"""
        panel = self._get_current_panel()
        if panel:
            panel._export_word()

    def _calculate_all(self):
        """计算所有倒虹吸并自动导出水头损失到主表格"""
        # 方案D预检查：批量计算前确认所有面板流速已输入
        unconfirmed = []
        for name, panel in self.panels.items():
            if not panel._v_user_confirmed:
                unconfirmed.append(name)
        if unconfirmed:
            # 切换到第一个未确认流速的面板
            first_name = unconfirmed[0]
            for i in range(self.notebook.count()):
                if self.notebook.tabText(i) == first_name:
                    self.notebook.setCurrentIndex(i)
                    break
            first_panel = self.panels[first_name]
            first_panel.params_notebook.setCurrentIndex(0)
            first_panel.edit_v.setFocus()
            first_panel.edit_v.selectAll()
            first_panel._flash_v_field()
            names_str = "、".join(unconfirmed)
            from qfluentwidgets import InfoBar, InfoBarPosition
            InfoBar.error(
                "请先输入拟定流速",
                f'以下倒虹吸的"拟定流速 v"尚未确认: {names_str}\n请逐个输入流速值后再执行批量计算。',
                parent=self, duration=8000,
                position=InfoBarPosition.TOP
            )
            return

        total = len(self.panels)
        success_count = 0
        fail_count = 0
        successful_panels = []

        # 1. 显示进度条
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self._update_status(f"正在计算 0/{total}...")

        # 2. 抑制所有面板的结果窗口自动弹出 + 水损阈值警告
        for panel in self.panels.values():
            panel._suppress_result_display = True
            # 保存原始阈值并临时清空，避免批量模式下弹出水损超限提示
            panel._saved_threshold = panel.edit_threshold.text()
            panel.edit_threshold.setText('')

        try:
            # 3. 依次执行所有计算
            for i, (name, panel) in enumerate(self.panels.items()):
                self._update_status(f"正在计算 {i + 1}/{total}: {name}")
                self.progress_bar.setValue(i)
                # 强制刷新UI
                from PySide6.QtWidgets import QApplication
                QApplication.processEvents()

                try:
                    panel._execute_calculation()
                    if panel.get_result() is not None:
                        success_count += 1
                        successful_panels.append((name, panel))
                    else:
                        fail_count += 1
                except Exception as e:
                    fail_count += 1
                    print(f"计算 {name} 失败: {e}")

            self.progress_bar.setValue(total)
        finally:
            # 4. 恢复标志 & 阈值 & 隐藏进度条
            for panel in self.panels.values():
                panel._suppress_result_display = False
                if hasattr(panel, '_saved_threshold'):
                    panel.edit_threshold.setText(panel._saved_threshold)
                    del panel._saved_threshold
            self.progress_bar.setVisible(False)

        # 5. 保存结果
        self._save_all()

        # 6. 自动导出水头损失到主表格
        imported_count = 0
        if success_count > 0 and self.on_import_losses:
            results = self._get_all_results()
            if results:
                try:
                    imported_count = self.on_import_losses(results)
                except Exception as e:
                    print(f"导出水头损失失败: {e}")

        # 7. 更新状态栏
        status_parts = [f"计算完成: {success_count} 成功"]
        if fail_count > 0:
            status_parts.append(f"{fail_count} 失败")
        if imported_count > 0:
            status_parts.append(f"已导出 {imported_count} 个水头损失")
        self._update_status(", ".join(status_parts))

        # 8. 弹出汇总对话框
        self._show_summary_dialog(successful_panels, fail_count, imported_count)

    def _get_all_results(self) -> Dict[str, dict]:
        """获取所有倒虹吸的计算结果"""
        results = {}
        for name, panel in self.panels.items():
            result = panel.get_result()
            if result is not None:
                # 优先使用加大流量工况水损，若无则使用设计工况
                head_loss = result.total_head_loss_inc if result.total_head_loss_inc is not None else result.total_head_loss
                results[name] = {
                    "head_loss": head_loss,
                    "diameter": result.diameter,
                    "turn_radius": panel.get_plan_bend_radius(),
                }
        return results

    # ================================================================
    # 汇总对话框
    # ================================================================
    def _show_summary_dialog(self, successful_panels, fail_count=0, imported_count=0):
        """
        显示计算结果汇总对话框

        以表格形式展示所有计算成功的倒虹吸结果（名称、管径、总水头损失），
        用户勾选后可统一查看详细计算过程。
        """
        dlg = QDialog(self)
        dlg.setWindowTitle("计算结果汇总")
        dlg.setMinimumWidth(600)
        dlg.resize(700, 450)
        dlg.setStyleSheet(DIALOG_STYLE)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(20, 15, 20, 15)
        lay.setSpacing(10)

        total = len(successful_panels) + fail_count

        # 顶部汇总信息
        if fail_count > 0:
            summary = f"共 {total} 个倒虹吸：{len(successful_panels)} 个成功，{fail_count} 个失败"
        else:
            summary = f"全部 {total} 个倒虹吸计算成功"
        if imported_count > 0:
            summary += f"\n已导出 {imported_count} 个水头损失到主表格"

        lbl_summary = QLabel(summary)
        lbl_summary.setStyleSheet(f"font-size:13px;font-weight:bold;color:{T1};")
        lbl_summary.setWordWrap(True)
        lay.addWidget(lbl_summary)

        # 表格区域
        check_vars = []
        if successful_panels:
            lbl_hint = QLabel("勾选需要查看详细计算过程的倒虹吸：")
            lbl_hint.setStyleSheet("font-size:11px;")
            lay.addWidget(lbl_hint)

            table = QTableWidget(len(successful_panels), 4)
            table.setHorizontalHeaderLabels(["查看", "名称", "管径 (m)", "总水头损失 (m)"])
            table.horizontalHeader().setStretchLastSection(True)
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
            table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
            table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
            table.setColumnWidth(0, 50)
            table.setSelectionBehavior(QAbstractItemView.SelectRows)
            table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            table.verticalHeader().setVisible(False)
            table.setFont(QFont("Microsoft YaHei", 10))

            for i, (name, panel) in enumerate(successful_panels):
                result = panel.calculation_result
                # 复选框
                cb = QCheckBox()
                cb.setChecked(True)
                check_vars.append(cb)
                cb_widget = QWidget()
                cb_lay = QHBoxLayout(cb_widget)
                cb_lay.setAlignment(Qt.AlignCenter)
                cb_lay.setContentsMargins(0, 0, 0, 0)
                cb_lay.addWidget(cb)
                table.setCellWidget(i, 0, cb_widget)

                # 名称
                item_name = QTableWidgetItem(name)
                item_name.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                table.setItem(i, 1, item_name)

                # 管径
                item_d = QTableWidgetItem(f"{result.diameter:.4f}")
                item_d.setTextAlignment(Qt.AlignCenter)
                table.setItem(i, 2, item_d)

                # 水头损失（优先显示加大流量工况，与导出到水面线表格保持一致）
                head_loss = result.total_head_loss_inc if result.total_head_loss_inc is not None else result.total_head_loss
                item_loss = QTableWidgetItem(f"{head_loss:.4f}")
                item_loss.setTextAlignment(Qt.AlignCenter)
                table.setItem(i, 3, item_loss)

            lay.addWidget(table, 1)

        # 底部按钮
        btn_lay = QHBoxLayout()
        btn_lay.setSpacing(8)

        if successful_panels and check_vars:
            btn_all = PushButton("全选")
            btn_all.clicked.connect(lambda: [cb.setChecked(True) for cb in check_vars])
            btn_lay.addWidget(btn_all)

            btn_none = PushButton("全不选")
            btn_none.clicked.connect(lambda: [cb.setChecked(False) for cb in check_vars])
            btn_lay.addWidget(btn_none)

            btn_view = PushButton("查看选中")

            def _view_selected():
                selected = [
                    (name, panel)
                    for i_idx, (name, panel) in enumerate(successful_panels)
                    if check_vars[i_idx].isChecked()
                ]
                dlg.accept()
                # 逐个显示选中面板的计算结果（与原版行为一致）
                for sel_name, sel_panel in selected:
                    # 切换到对应标签页
                    for tab_idx in range(self.notebook.count()):
                        if self.notebook.tabText(tab_idx) == sel_name:
                            self.notebook.setCurrentIndex(tab_idx)
                            break
                    # 显示结果（调用面板的结果显示逻辑）
                    if sel_panel.calculation_result:
                        sel_panel._suppress_result_display = False
                        # 填充结果到面板的结果区域
                        try:
                            from siphon_hydraulics import HydraulicCore
                            summary = HydraulicCore.format_result(
                                sel_panel.calculation_result, show_steps=False)
                            sel_panel.summary_text.setPlainText(summary)
                            if sel_panel.calculation_result.calculation_steps:
                                sel_panel.detail_text.setPlainText(
                                    sel_panel.calculation_result.calculation_steps)
                            if hasattr(sel_panel, 'result_notebook'):
                                sel_panel.result_notebook.setCurrentIndex(1)
                        except Exception:
                            pass

            btn_view.clicked.connect(_view_selected)
            btn_lay.addWidget(btn_view)

        btn_lay.addStretch()

        btn_close = PushButton("关闭")
        btn_close.clicked.connect(dlg.accept)
        btn_lay.addWidget(btn_close)

        btn_close_return = PrimaryPushButton("关闭并返回推求水面线计算面板")
        btn_close_return.setToolTip("关闭汇总对话框和倒虹吸计算窗口，返回推求水面线面板")
        def _close_and_return():
            dlg.accept()
            self._on_close()
        btn_close_return.clicked.connect(_close_and_return)
        btn_lay.addWidget(btn_close_return)

        lay.addLayout(btn_lay)
        dlg.exec()

    # ================================================================
    # 状态更新
    # ================================================================
    def _update_status(self, message: str):
        self.status_label.setText(message)

    def _update_time_label(self):
        if self.manager and MANAGER_AVAILABLE:
            last_modified = self.manager.last_modified
            if last_modified:
                self.time_label.setText(f"上次保存: {last_modified}")
                return
        self.time_label.setText("")

    # ================================================================
    # 关闭
    # ================================================================
    def _on_close(self):
        """关闭窗口前自动保存"""
        if self.panels:
            self._save_all()
        self.accept()
        # 关闭后将父窗口（推求水面线主面板）置前显示
        self._lift_parent()

    def closeEvent(self, event):
        """窗口关闭事件"""
        if self.panels:
            self._save_all()
        super().closeEvent(event)
        self._lift_parent()

    def _lift_parent(self):
        """将父窗口置前显示"""
        try:
            p = self.parent()
            if p:
                p.raise_()
                p.activateWindow()
        except Exception:
            pass
