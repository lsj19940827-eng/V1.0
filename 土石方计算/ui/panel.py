# -*- coding: utf-8 -*-
"""
土石方工程量计算 —— 主面板（UI 骨架）
事件处理器定义在 panel_handlers.py（Mixin 方式接入）
"""
from __future__ import annotations
import os, sys, math

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QGroupBox, QTabWidget, QScrollArea,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QFileDialog, QProgressBar, QTextEdit, QComboBox,
    QDoubleSpinBox, QSizePolicy, QCheckBox, QSpinBox,
)
from PySide6.QtCore import Qt
from qfluentwidgets import PushButton, PrimaryPushButton, LineEdit as FLineEdit, InfoBar, InfoBarPosition

from 渠系断面设计.styles import P, S, W, E, BG, CARD, BD, T1, T2

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from 土石方计算.ui.panel_handlers import _EarthworkPanelHandlers, _TINBuildThread


# ── 嵌入式 Matplotlib 画布（含导航工具栏）────────────────────
class _MplCanvas(QWidget):
    def __init__(self, parent=None, w=6, h=4, dpi=96, toolbar=True):
        super().__init__(parent)
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
        from matplotlib.figure import Figure
        self.fig = Figure(figsize=(w, h), dpi=dpi, tight_layout=True)
        self.axes = self.fig.add_subplot(111)
        self._cv = FigureCanvasQTAgg(self.fig)
        lay = QVBoxLayout(self); lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)
        if toolbar:
            self._tb = NavigationToolbar2QT(self._cv, self)
            self._tb.setFixedHeight(28)
            self._tb.setStyleSheet("QToolBar{border:none;background:transparent;spacing:2px;}")
            lay.addWidget(self._tb)
        lay.addWidget(self._cv)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def redraw(self): self._cv.draw_idle()
    def clear_axes(self): self.axes.cla()


# ── 主面板 ────────────────────────────────────────────────────
class EarthworkPanel(_EarthworkPanelHandlers, QWidget):
    """土石方工程量计算主面板（PySide6 + qfluentwidgets）"""

    def __init__(self, parent=None):
        QWidget.__init__(self, parent)
        # 运行时状态（由 panel_handlers.py 中的方法读写）
        self._terrain_pts     = None
        self._terrain_tp_list  = []
        self._terrain_edges    = []
        self._terrain_src_files = []
        self._project_dir      = ""
        self._tin = None
        self._interp = None
        self._alignment = None
        self._long_data = None
        self._sections = []
        self._volume_result = None
        self._sec_idx = 0
        self._build_thread = None
        self._geology_depth_data: dict = {}  # {layer_name: [(station, thickness), ...]}
        self._build_ui()

    # ── 顶层骨架 ─────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self); root.setContentsMargins(8,8,8,8); root.setSpacing(6)
        title_row = QHBoxLayout()
        title = QLabel("土石方工程量计算")
        title.setStyleSheet(f"font-size:18px;font-weight:bold;color:{P};padding:4px 0;")
        title_row.addWidget(title, 1)
        btn_open = PushButton("📁 打开项目"); btn_open.clicked.connect(self._on_open_project)
        btn_save = PushButton("💾 保存项目"); btn_save.clicked.connect(self._on_save_project)
        title_row.addWidget(btn_open); title_row.addWidget(btn_save)
        root.addLayout(title_row)
        self._tabs = QTabWidget(); self._tabs.setDocumentMode(True)
        root.addWidget(self._tabs, 1)
        self._tabs.addTab(self._tab_import(),   "①  数据导入")
        self._tabs.addTab(self._tab_tin(),      "②  TIN建模")
        self._tabs.addTab(self._tab_sections(), "③  断面切割")
        self._tabs.addTab(self._tab_volume(),   "④  工程量计算")
        self._tabs.addTab(self._tab_export(),   "⑤  成果导出")

    # ── Tab 1  数据导入 ──────────────────────────────────────
    def _tab_import(self) -> QWidget:
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{border:none;}")
        inner = QWidget(); scroll.setWidget(inner)
        lay = QVBoxLayout(inner); lay.setContentsMargins(12,12,12,12); lay.setSpacing(10)

        # 地形数据
        g = QGroupBox("地形数据来源"); f = QFormLayout(g); f.setSpacing(8)
        self._fmt = QComboBox()
        self._fmt.addItems(["DXF 等高线", "DXF 高程点", "CSV/TXT (X,Y,Z)", "Excel"])
        f.addRow("数据格式:", self._fmt)
        row = QHBoxLayout()
        self._terrain_path = FLineEdit(); self._terrain_path.setPlaceholderText("地形文件路径…")
        btn = PushButton("浏览"); btn.setFixedWidth(64); btn.clicked.connect(self._browse_terrain)
        row.addWidget(self._terrain_path, 1); row.addWidget(btn)
        f.addRow("文件路径:", row)
        self._layer_name = FLineEdit(); self._layer_name.setPlaceholderText("等高线图层名（默认: 等高线）")
        f.addRow("等高线图层:", self._layer_name)
        self._contour_step = QDoubleSpinBox(); self._contour_step.setRange(0.1,100); self._contour_step.setValue(1.0); self._contour_step.setSuffix(" m")
        f.addRow("等高线离散间距:", self._contour_step)
        ox_r = QHBoxLayout()
        self._ox = QDoubleSpinBox(); self._ox.setRange(-1e7,1e7); self._ox.setDecimals(3); self._ox.setPrefix("ΔX = ")
        self._oy = QDoubleSpinBox(); self._oy.setRange(-1e7,1e7); self._oy.setDecimals(3); self._oy.setPrefix("ΔY = ")
        ox_r.addWidget(self._ox); ox_r.addWidget(self._oy)
        f.addRow("坐标偏移（减去）:", ox_r)
        load_r = QHBoxLayout()
        btn_load = PrimaryPushButton("载入地形数据")
        btn_load.clicked.connect(self._on_load_terrain)
        btn_append = PushButton("➕ 追加到现有")
        btn_append.setToolTip("将此文件的地形点追加到已载入的点集（多源合并）")
        btn_append.clicked.connect(self._on_append_terrain)
        btn_clear = PushButton("❌ 清空")
        btn_clear.setToolTip("清空全部地形点")
        btn_clear.clicked.connect(self._on_clear_terrain)
        self._terrain_lbl = QLabel("— 未载入 —"); self._terrain_lbl.setStyleSheet(f"color:{T2};font-size:12px;")
        load_r.addWidget(btn_load); load_r.addWidget(btn_append)
        load_r.addWidget(btn_clear); load_r.addWidget(self._terrain_lbl); load_r.addStretch()
        f.addRow("", load_r)
        lay.addWidget(g)

        # 中心线
        g2 = QGroupBox("渠道中心线"); f2 = QFormLayout(g2); f2.setSpacing(8)
        self._al_src = QComboBox()
        self._al_src.addItems(["DXF 多段线", "桩号坐标表 (Excel/CSV)", "手动输入（起止点直线）"])
        self._al_src.currentIndexChanged.connect(self._on_al_src_changed)
        f2.addRow("来源:", self._al_src)
        # --- DXF 选项 ---
        al_r = QHBoxLayout()
        self._al_path = FLineEdit(); self._al_path.setPlaceholderText("中心线 DXF 文件路径…")
        btn_al = PushButton("浏览"); btn_al.setFixedWidth(64); btn_al.clicked.connect(self._browse_alignment)
        al_r.addWidget(self._al_path, 1); al_r.addWidget(btn_al)
        self._al_file_w = QWidget(); self._al_file_w.setLayout(al_r)
        f2.addRow("DXF 文件:", self._al_file_w)
        self._al_layer = FLineEdit(); self._al_layer.setPlaceholderText("中心线图层名（默认: 中心线）")
        self._al_layer_row_lbl = QLabel("图层名:")
        f2.addRow(self._al_layer_row_lbl, self._al_layer)
        # --- 桩号坐标表选项 ---
        self._al_table_w = QWidget(); tf = QFormLayout(self._al_table_w); tf.setContentsMargins(0,0,0,0)
        sta_r = QHBoxLayout()
        self._al_sta_path = FLineEdit(); self._al_sta_path.setPlaceholderText("中心线 Excel/CSV 文件路径…")
        btn_sta = PushButton("浏览"); btn_sta.setFixedWidth(64); btn_sta.clicked.connect(self._browse_alignment_table)
        sta_r.addWidget(self._al_sta_path, 1); sta_r.addWidget(btn_sta)
        tf.addRow("坐标表文件:", sta_r)
        self._al_sheet = FLineEdit(); self._al_sheet.setPlaceholderText("Sheet1（Excel时填写）")
        self._al_col_sta = FLineEdit(); self._al_col_sta.setPlaceholderText("桩号")
        self._al_col_x2 = FLineEdit(); self._al_col_x2.setPlaceholderText("X")
        self._al_col_y2 = FLineEdit(); self._al_col_y2.setPlaceholderText("Y")
        col_r = QHBoxLayout(); col_r.addWidget(QLabel("桩号列:")); col_r.addWidget(self._al_col_sta)
        col_r.addWidget(QLabel(" X列:")); col_r.addWidget(self._al_col_x2)
        col_r.addWidget(QLabel(" Y列:")); col_r.addWidget(self._al_col_y2)
        tf.addRow("工作表:", self._al_sheet)
        tf.addRow("列映射:", col_r)
        f2.addRow(self._al_table_w); self._al_table_w.setVisible(False)
        # --- 手动直线选项 ---
        self._al_manual_w = QWidget(); mf = QFormLayout(self._al_manual_w); mf.setContentsMargins(0,0,0,0)
        self._al_x0 = QDoubleSpinBox(); self._al_x0.setRange(-1e8,1e8); self._al_x0.setDecimals(3)
        self._al_y0 = QDoubleSpinBox(); self._al_y0.setRange(-1e8,1e8); self._al_y0.setDecimals(3)
        self._al_x1 = QDoubleSpinBox(); self._al_x1.setRange(-1e8,1e8); self._al_x1.setDecimals(3)
        self._al_y1 = QDoubleSpinBox(); self._al_y1.setRange(-1e8,1e8); self._al_y1.setDecimals(3)
        r0 = QHBoxLayout(); r0.addWidget(QLabel("X₀:")); r0.addWidget(self._al_x0); r0.addWidget(QLabel("Y₀:")); r0.addWidget(self._al_y0)
        r1 = QHBoxLayout(); r1.addWidget(QLabel("X₁:")); r1.addWidget(self._al_x1); r1.addWidget(QLabel("Y₁:")); r1.addWidget(self._al_y1)
        mf.addRow("起点:", r0); mf.addRow("终点:", r1)
        f2.addRow("坐标:", self._al_manual_w); self._al_manual_w.setVisible(False)
        lay.addWidget(g2)

        # 设计断面
        g3 = QGroupBox("渠道设计断面参数"); f3 = QFormLayout(g3); f3.setSpacing(8)
        self._ds_b  = QDoubleSpinBox(); self._ds_b.setRange(0.1,100);  self._ds_b.setValue(3.0);  self._ds_b.setSuffix(" m")
        self._ds_h  = QDoubleSpinBox(); self._ds_h.setRange(0.1,30);   self._ds_h.setValue(2.0);  self._ds_h.setSuffix(" m")
        self._ds_ml = QDoubleSpinBox(); self._ds_ml.setRange(0,5);     self._ds_ml.setValue(1.5); self._ds_ml.setSingleStep(0.25)
        self._ds_mr = QDoubleSpinBox(); self._ds_mr.setRange(0,5);     self._ds_mr.setValue(1.5); self._ds_mr.setSingleStep(0.25)
        f3.addRow("渠底宽 b:", self._ds_b); f3.addRow("渠深 h:", self._ds_h)
        f3.addRow("左内坡比 m:", self._ds_ml); f3.addRow("右内坡比 m:", self._ds_mr)
        btn_import_ds = PushButton("↑ 从明渠设计模块读取当前参数")
        btn_import_ds.setToolTip("读取「明渠设计」标签页中当前输入的断面参数（渠底宽/渠深/内坡比）")
        btn_import_ds.clicked.connect(self._on_import_from_channel_design)
        f3.addRow("", btn_import_ds)
        lay.addWidget(g3)

        # 纵坡设计（多段支持）
        g4 = QGroupBox("纵坡设计（渠底高程，支持多段）"); sl4 = QVBoxLayout(g4); sl4.setSpacing(6)
        sl4.addWidget(QLabel("每行定义一段纵坡（起始桩号/起始渠底高程/纵坡i/终止桩号）："))
        self._dp_table = QTableWidget(1, 4)
        self._dp_table.setHorizontalHeaderLabels(["起始桩号(m)", "起始底高程(m)", "纵坡 i", "终止桩号(m)"])
        self._dp_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._dp_table.verticalHeader().setVisible(False)
        self._dp_table.setMaximumHeight(110)
        for c_, v_ in enumerate(["0", "97.000", "-0.000300", "1000"]):
            self._dp_table.setItem(0, c_, QTableWidgetItem(v_))
        dp_btn_r = QHBoxLayout()
        btn_dp_add = PushButton("＋ 添加段"); btn_dp_del = PushButton("－ 删除最后")
        btn_dp_xl  = PushButton("📂 从Excel导入")
        btn_dp_xl.setToolTip("从Excel文件读取纵断面设计底高程（桩号,设计底高程 两列）")
        btn_dp_wpl = PushButton("↑ 从水面线模块读取")
        btn_dp_wpl.setToolTip("读取推求水面线模块中已计算的纵断面设计底高程")
        def _dp_add():
            r = self._dp_table.rowCount(); self._dp_table.insertRow(r)
            for c_, v_ in enumerate(["0", "97.000", "-0.000300", "1000"]):
                self._dp_table.setItem(r, c_, QTableWidgetItem(v_))
        def _dp_del():
            if self._dp_table.rowCount() > 1: self._dp_table.removeRow(self._dp_table.rowCount()-1)
        btn_dp_add.clicked.connect(_dp_add); btn_dp_del.clicked.connect(_dp_del)
        btn_dp_xl.clicked.connect(self._on_import_design_profile_excel)
        btn_dp_wpl.clicked.connect(self._on_import_from_water_profile)
        dp_btn_r.addWidget(btn_dp_add); dp_btn_r.addWidget(btn_dp_del)
        dp_btn_r.addWidget(btn_dp_xl); dp_btn_r.addWidget(btn_dp_wpl); dp_btn_r.addStretch()
        sl4.addWidget(self._dp_table); sl4.addLayout(dp_btn_r)
        # 向下兼容：保留单段属性（供已有代码访问）
        self._dp_s0 = QDoubleSpinBox(); self._dp_s0.setVisible(False)
        self._dp_e0 = QDoubleSpinBox(); self._dp_e0.setVisible(False); self._dp_e0.setValue(97.0)
        self._dp_i  = QDoubleSpinBox(); self._dp_i.setVisible(False);  self._dp_i.setValue(-0.0003)
        self._dp_s1 = QDoubleSpinBox(); self._dp_s1.setVisible(False); self._dp_s1.setValue(1000.0)
        lay.addWidget(g4)

        # 开挖边坡（多级）
        g5 = QGroupBox("开挖边坡（支持多级放坡+马道）"); sl5 = QVBoxLayout(g5); sl5.setSpacing(6)
        self._slope_table = QTableWidget(1, 3)
        self._slope_table.setHorizontalHeaderLabels(["坡比 m", "高度 h(m)\n空=延伸到地面", "马道宽(m)"])
        self._slope_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._slope_table.verticalHeader().setVisible(False)
        self._slope_table.setMaximumHeight(120)
        for c_, v_ in enumerate(["1.0", "∞", "0.0"]):
            self._slope_table.setItem(0, c_, QTableWidgetItem(v_))
        btn_add = PushButton("＋ 添加一级"); btn_del = PushButton("－ 删除最后")
        def _add():
            r = self._slope_table.rowCount(); self._slope_table.insertRow(r)
            for c_, v_ in enumerate(["1.0", "∞", "0.0"]): self._slope_table.setItem(r, c_, QTableWidgetItem(v_))
        def _del():
            if self._slope_table.rowCount() > 1: self._slope_table.removeRow(self._slope_table.rowCount()-1)
        btn_add.clicked.connect(_add); btn_del.clicked.connect(_del)
        btn_r = QHBoxLayout(); btn_r.addWidget(btn_add); btn_r.addWidget(btn_del); btn_r.addStretch()
        sl5.addWidget(QLabel("从下到上依次填写各级边坡（最后一级高度留空=延伸到地面）："))
        sl5.addWidget(self._slope_table); sl5.addLayout(btn_r)
        lay.addWidget(g5)

        # 切割参数
        g6 = QGroupBox("断面切割参数"); f6 = QFormLayout(g6); f6.setSpacing(8)
        self._long_step   = QDoubleSpinBox(); self._long_step.setRange(0.5,50);  self._long_step.setValue(2.0);  self._long_step.setSuffix(" m")
        self._cs_interval = QDoubleSpinBox(); self._cs_interval.setRange(5,500); self._cs_interval.setValue(20.0); self._cs_interval.setSuffix(" m")
        self._cs_hw       = QDoubleSpinBox(); self._cs_hw.setRange(5,300);      self._cs_hw.setValue(30.0);      self._cs_hw.setSuffix(" m")
        btn_auto_hw = PushButton("自动估算")
        btn_auto_hw.setToolTip("根据设计断面口宽×2@边坡延伸自动估算横断面半宽")
        btn_auto_hw.clicked.connect(self._on_auto_estimate_width)
        self._cs_sample   = QDoubleSpinBox(); self._cs_sample.setRange(0.1,5);  self._cs_sample.setValue(0.5);   self._cs_sample.setSuffix(" m")
        self._extra_sta_edit = FLineEdit()
        self._extra_sta_edit.setPlaceholderText("关键桩号（逗号分隔，如 100,250.5,500）")
        # 非对称宽度
        self._cs_asym_chk = QCheckBox("左右非对称宽度")
        self._cs_asym_chk.toggled.connect(self._on_asym_width_toggled)
        self._cs_lw_w = QWidget(); lw_f = QHBoxLayout(self._cs_lw_w); lw_f.setContentsMargins(0,0,0,0)
        self._cs_lw = QDoubleSpinBox(); self._cs_lw.setRange(5,300); self._cs_lw.setValue(30.0); self._cs_lw.setSuffix(" m")
        self._cs_rw = QDoubleSpinBox(); self._cs_rw.setRange(5,300); self._cs_rw.setValue(30.0); self._cs_rw.setSuffix(" m")
        lw_f.addWidget(QLabel("左宽:")); lw_f.addWidget(self._cs_lw)
        lw_f.addWidget(QLabel(" 右宽:")); lw_f.addWidget(self._cs_rw)
        self._cs_lw_w.setVisible(False)
        hw_row = QWidget(); hw_lay = QHBoxLayout(hw_row); hw_lay.setContentsMargins(0,0,0,0)
        hw_lay.addWidget(self._cs_hw); hw_lay.addWidget(btn_auto_hw)
        f6.addRow("纵断面采样步长:", self._long_step); f6.addRow("横断面间距:", self._cs_interval)
        f6.addRow("横断面半宽:", hw_row);              f6.addRow("横断面采样步长:", self._cs_sample)
        f6.addRow("", self._cs_asym_chk);               f6.addRow("非对称宽度:", self._cs_lw_w)
        f6.addRow("关键桩号（额外）:", self._extra_sta_edit)
        lay.addWidget(g6)

        # 地质分层管理
        g7 = QGroupBox("地质分层（可选）"); sl7 = QVBoxLayout(g7); sl7.setSpacing(6)
        sl7.addWidget(QLabel("从上到下依次添加地质层（留空则不使用地质分层）："))
        self._geo_table = QTableWidget(0, 4)
        self._geo_table.setHorizontalHeaderLabels(["层名称", "填充图案", "ACI颜色", "统一深度(m)\n空=从文件导入"])
        self._geo_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._geo_table.verticalHeader().setVisible(False)
        self._geo_table.setMaximumHeight(130)
        geo_btn_r = QHBoxLayout()
        btn_geo_add = PushButton("＋ 添加层")
        btn_geo_del = PushButton("－ 删除最后")
        btn_geo_xl  = PushButton("📂 从Excel导入深度表")
        btn_geo_dxf = PushButton("🗺 从DXF导入分层线")
        def _geo_add():
            r = self._geo_table.rowCount(); self._geo_table.insertRow(r)
            defaults = [f"地质层{r+1}", "ANSI31", "8", ""]
            for c_, v_ in enumerate(defaults):
                self._geo_table.setItem(r, c_, QTableWidgetItem(v_))
        def _geo_del():
            if self._geo_table.rowCount() > 0:
                self._geo_table.removeRow(self._geo_table.rowCount()-1)
        btn_geo_add.clicked.connect(_geo_add)
        btn_geo_del.clicked.connect(_geo_del)
        btn_geo_xl.clicked.connect(self._on_import_geology_excel)
        btn_geo_dxf.clicked.connect(self._on_import_geology_dxf)
        geo_btn_r.addWidget(btn_geo_add); geo_btn_r.addWidget(btn_geo_del)
        geo_btn_r.addWidget(btn_geo_xl); geo_btn_r.addWidget(btn_geo_dxf); geo_btn_r.addStretch()
        # 深度表状态标签
        self._geo_depth_lbl = QLabel("未导入深度表（若无地质分层数据可跳过）")
        self._geo_depth_lbl.setStyleSheet(f"color:{T2};font-size:12px;")
        sl7.addWidget(self._geo_table); sl7.addLayout(geo_btn_r)
        sl7.addWidget(self._geo_depth_lbl)
        lay.addWidget(g7)

        lay.addStretch()
        return scroll

    # ── Tab 2  TIN 建模 ──────────────────────────────────────
    def _tab_tin(self) -> QWidget:
        w = QWidget(); lay = QHBoxLayout(w); lay.setContentsMargins(8,8,8,8)
        ctrl = QWidget(); ctrl.setFixedWidth(260); cl = QVBoxLayout(ctrl); cl.setContentsMargins(0,0,8,0)
        g = QGroupBox("TIN 构建"); vl = QVBoxLayout(g)
        self._tin_stat = QLabel("尚未构建"); self._tin_stat.setStyleSheet(f"color:{T2};")
        self._tin_prog = QProgressBar(); self._tin_prog.setRange(0,0); self._tin_prog.setVisible(False)
        self._tin_prog_lbl = QLabel(""); self._tin_prog_lbl.setStyleSheet(f"font-size:12px;color:{T2};")
        self._btn_tin = PrimaryPushButton("构建 TIN 地形模型")
        self._btn_tin.setEnabled(False); self._btn_tin.clicked.connect(self._on_build_tin)
        self._tin_info = QLabel(""); self._tin_info.setWordWrap(True)
        self._tin_info.setStyleSheet(f"font-size:12px;color:{T1};line-height:1.6;")
        self._tin_filter_chk = QCheckBox("构建前过滤异常高程点（IQR法）")
        self._tin_filter_chk.setToolTip("适用于地形数据中存在Z=0或极端异常高程的情况")
        vl.addWidget(QLabel("状态:")); vl.addWidget(self._tin_stat)
        vl.addWidget(self._tin_filter_chk)
        vl.addWidget(self._btn_tin); vl.addWidget(self._tin_prog)
        vl.addWidget(self._tin_prog_lbl); vl.addWidget(self._tin_info); vl.addStretch()
        cl.addWidget(g); cl.addStretch()
        lay.addWidget(ctrl)
        gp = QGroupBox("TIN 地形预览（俯视图）"); pl = QVBoxLayout(gp)
        self._tin_canvas = _MplCanvas(h=5)
        self._tin_canvas.axes.set_aspect("equal"); self._tin_canvas.axes.set_title("等待构建…")
        pl.addWidget(self._tin_canvas)
        lay.addWidget(gp, 1)
        return w

    # ── Tab 3  断面切割 ──────────────────────────────────────
    def _tab_sections(self) -> QWidget:
        w = QWidget(); lay = QHBoxLayout(w); lay.setContentsMargins(8,8,8,8)
        ctrl = QWidget(); ctrl.setFixedWidth(210); cl = QVBoxLayout(ctrl); cl.setContentsMargins(0,0,8,0)
        g_l = QGroupBox("纵断面"); vl_l = QVBoxLayout(g_l)
        self._btn_long = PrimaryPushButton("生成纵断面")
        self._btn_long.setEnabled(False); self._btn_long.clicked.connect(self._on_cut_long)
        self._long_stat = QLabel("未生成"); self._long_stat.setStyleSheet(f"color:{T2};font-size:12px;")
        vl_l.addWidget(self._btn_long); vl_l.addWidget(self._long_stat)
        g_c = QGroupBox("横断面"); vl_c = QVBoxLayout(g_c)
        self._btn_cs = PrimaryPushButton("切割横断面")
        self._btn_cs.setEnabled(False); self._btn_cs.clicked.connect(self._on_cut_sections)
        self._cs_stat = QLabel("未切割"); self._cs_stat.setStyleSheet(f"color:{T2};font-size:12px;")
        vl_c.addWidget(self._btn_cs); vl_c.addWidget(self._cs_stat)
        cl.addWidget(g_l); cl.addWidget(g_c); cl.addStretch()
        lay.addWidget(ctrl)

        self._sec_tabs = QTabWidget(); self._sec_tabs.setDocumentMode(True)
        # 纵断面 tab
        lw = QWidget(); ll = QVBoxLayout(lw); ll.setContentsMargins(4,4,4,4)
        self._long_canvas = _MplCanvas(h=4)
        self._long_canvas.axes.set_title("纵断面（等待生成）")
        self._long_canvas.axes.set_xlabel("桩号 (m)"); self._long_canvas.axes.set_ylabel("高程 (m)")
        ll.addWidget(self._long_canvas)
        # 横断面 tab
        cw = QWidget(); cv = QVBoxLayout(cw); cv.setContentsMargins(4,4,4,4)
        nav = QHBoxLayout()
        self._btn_prev = PushButton("◀ 上一"); self._btn_prev.clicked.connect(self._sec_prev)
        self._btn_next = PushButton("下一 ▶"); self._btn_next.clicked.connect(self._sec_next)
        self._sec_lbl  = QLabel("—"); self._sec_lbl.setAlignment(Qt.AlignCenter)
        nav.addWidget(self._btn_prev); nav.addWidget(self._sec_lbl, 1); nav.addWidget(self._btn_next)
        self._cs_canvas = _MplCanvas(h=4)
        self._cs_canvas.axes.set_title("横断面（等待切割）")
        cv.addLayout(nav); cv.addWidget(self._cs_canvas)

        self._sec_tabs.addTab(lw, "纵断面图"); self._sec_tabs.addTab(cw, "横断面浏览")
        lay.addWidget(self._sec_tabs, 1)
        return w

    # ── Tab 4  工程量计算 ────────────────────────────────────
    def _tab_volume(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(8,8,8,8); lay.setSpacing(8)
        top = QHBoxLayout()
        self._btn_vol = PrimaryPushButton("计算工程量")
        self._btn_vol.setEnabled(False); self._btn_vol.clicked.connect(self._on_compute_volume)
        self._vol_stat = QLabel("未计算"); self._vol_stat.setStyleSheet(f"color:{T2};")
        top.addWidget(self._btn_vol); top.addWidget(self._vol_stat); top.addStretch()
        lay.addLayout(top)
        self._vol_summary = QLabel("")
        self._vol_summary.setStyleSheet(f"font-size:13px;color:{T1};padding:6px;background:{CARD};border:1px solid {BD};border-radius:4px;")
        self._vol_summary.setWordWrap(True)
        lay.addWidget(self._vol_summary)
        self._vol_table = QTableWidget(0, 7)
        self._vol_table.setHorizontalHeaderLabels([
            "起始桩号","终止桩号","段长(m)",
            "平均断面法挖(m³)","棱台法挖(m³)",
            "平均断面法填(m³)","棱台法填(m³)"])
        self._vol_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._vol_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._vol_table.verticalHeader().setVisible(False)
        lay.addWidget(self._vol_table, 1)
        return w

    # ── Tab 5  成果导出 ──────────────────────────────────────
    def _tab_export(self) -> QWidget:
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{border:none;}")
        w = QWidget(); scroll.setWidget(w)
        lay = QVBoxLayout(w); lay.setContentsMargins(8,8,8,8); lay.setSpacing(10)

        g = QGroupBox("输出设置"); f = QFormLayout(g); f.setSpacing(8)
        od_r = QHBoxLayout()
        self._out_dir = FLineEdit(); self._out_dir.setPlaceholderText("输出目录（默认当前目录）")
        btn_od = PushButton("浏览"); btn_od.setFixedWidth(64); btn_od.clicked.connect(self._browse_outdir)
        od_r.addWidget(self._out_dir, 1); od_r.addWidget(btn_od)
        self._proj_name = FLineEdit(); self._proj_name.setPlaceholderText("项目名称（用于文件名前缀）")
        f.addRow("输出目录:", od_r); f.addRow("项目名称:", self._proj_name)
        lay.addWidget(g)

        # 横断面DXF排版配置
        g_dxf = QGroupBox("横断面 DXF 排版配置（PRD: 全部可配置）")
        f_dxf = QFormLayout(g_dxf); f_dxf.setSpacing(8)
        self._dxf_spp  = QSpinBox(); self._dxf_spp.setRange(1, 12); self._dxf_spp.setValue(4)
        self._dxf_pw   = QDoubleSpinBox(); self._dxf_pw.setRange(200, 2000); self._dxf_pw.setValue(594.0); self._dxf_pw.setSuffix(" mm")
        self._dxf_ph   = QDoubleSpinBox(); self._dxf_ph.setRange(200, 2000); self._dxf_ph.setValue(420.0); self._dxf_ph.setSuffix(" mm")
        self._dxf_sh   = QDoubleSpinBox(); self._dxf_sh.setRange(50, 5000); self._dxf_sh.setValue(200.0); self._dxf_sh.setPrefix("1:"); self._dxf_sh.setSuffix(" 水平")
        self._dxf_sv   = QDoubleSpinBox(); self._dxf_sv.setRange(50, 5000); self._dxf_sv.setValue(200.0); self._dxf_sv.setPrefix("1:"); self._dxf_sv.setSuffix(" 竖向")
        f_dxf.addRow("每页断面数:", self._dxf_spp)
        f_dxf.addRow("图幅宽×高:", self._make_hw_row(self._dxf_pw, self._dxf_ph))
        f_dxf.addRow("水平/竖向比例尺:", self._make_hw_row(self._dxf_sh, self._dxf_sv))
        lay.addWidget(g_dxf)

        # 纵断面DXF配置
        g_ldxf = QGroupBox("纵断面 DXF 排版配置")
        f_ldxf = QFormLayout(g_ldxf); f_ldxf.setSpacing(8)
        self._ldxf_sh = QDoubleSpinBox(); self._ldxf_sh.setRange(100, 50000); self._ldxf_sh.setValue(2000.0); self._ldxf_sh.setPrefix("1:")
        self._ldxf_sv = QDoubleSpinBox(); self._ldxf_sv.setRange(20, 1000);  self._ldxf_sv.setValue(200.0);  self._ldxf_sv.setPrefix("1:")
        f_ldxf.addRow("水平比例尺:", self._ldxf_sh)
        f_ldxf.addRow("竖向比例尺:", self._ldxf_sv)
        lay.addWidget(g_ldxf)

        g2 = QGroupBox("导出成果"); bl = QHBoxLayout(g2)
        self._btn_xlsx    = PrimaryPushButton("导出 Excel 汇总表")
        self._btn_long_dxf = PushButton("导出纵断面 DXF")
        self._btn_cs_dxf   = PushButton("导出横断面 DXF（批量）")
        for btn in (self._btn_xlsx, self._btn_long_dxf, self._btn_cs_dxf):
            btn.setEnabled(False)
        self._btn_xlsx.clicked.connect(self._on_export_excel)
        self._btn_long_dxf.clicked.connect(self._on_export_long_dxf)
        self._btn_cs_dxf.clicked.connect(self._on_export_cs_dxf)
        bl.addWidget(self._btn_xlsx); bl.addWidget(self._btn_long_dxf); bl.addWidget(self._btn_cs_dxf); bl.addStretch()
        lay.addWidget(g2)
        g3 = QGroupBox("操作日志"); ll = QVBoxLayout(g3)
        self._log = QTextEdit(); self._log.setReadOnly(True); self._log.setMaximumHeight(200)
        self._log.setStyleSheet("font-size:12px;font-family:Consolas,'Courier New';")
        ll.addWidget(self._log)
        lay.addWidget(g3)
        lay.addStretch()
        return scroll

    @staticmethod
    def _make_hw_row(w1, w2):
        """创建两个控件并排的 QWidget"""
        row = QWidget(); lay = QHBoxLayout(row); lay.setContentsMargins(0,0,0,0)
        lay.addWidget(w1); lay.addWidget(w2)
        return row

    # ── 浏览按钮 ─────────────────────────────────────────────
    def _browse_terrain(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择地形文件", "", "地形文件 (*.dxf *.csv *.txt *.xlsx *.xls);;所有文件 (*)")
        if p: self._terrain_path.setText(p)

    def _browse_alignment(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择中心线 DXF", "", "DXF 文件 (*.dxf);;所有文件 (*)")
        if p: self._al_path.setText(p)

    def _browse_alignment_table(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择中心线坐标表", "",
            "坐标文件 (*.xlsx *.xls *.csv *.txt);;所有文件 (*)")
        if p: self._al_sta_path.setText(p)

    def _browse_outdir(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if d: self._out_dir.setText(d)

    def _on_asym_width_toggled(self, checked: bool):
        self._cs_hw.setVisible(not checked)
        self._cs_lw_w.setVisible(checked)

    def _on_al_src_changed(self, idx: int):
        self._al_file_w.setVisible(idx == 0)
        self._al_layer_row_lbl.setVisible(idx == 0)
        self._al_layer.setVisible(idx == 0)
        self._al_table_w.setVisible(idx == 1)
        self._al_manual_w.setVisible(idx == 2)

    # ── 日志 + InfoBar ───────────────────────────────────────
    def _log_msg(self, msg: str, level: str = "INFO"):
        prefix = {"INFO":"ℹ️","OK":"✅","WARN":"⚠️","ERR":"❌"}.get(level, "•")
        self._log.append(f"{prefix} {msg}")

    def _infobar(self, title: str, content: str, level: str = "success"):
        fn = {"success": InfoBar.success, "warning": InfoBar.warning,
              "error": InfoBar.error, "info": InfoBar.info}.get(level, InfoBar.info)
        fn(title=title, content=content, orient=Qt.Horizontal,
           isClosable=True, position=InfoBarPosition.TOP, duration=4000, parent=self)
