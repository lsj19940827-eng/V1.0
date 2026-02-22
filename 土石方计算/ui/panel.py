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
    QDoubleSpinBox, QSizePolicy,
)
from PySide6.QtCore import Qt
from qfluentwidgets import PushButton, PrimaryPushButton, LineEdit as FLineEdit, InfoBar, InfoBarPosition

from 渠系断面设计.styles import P, S, W, E, BG, CARD, BD, T1, T2

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from 土石方计算.ui.panel_handlers import _EarthworkPanelHandlers, _TINBuildThread


# ── 嵌入式 Matplotlib 画布 ────────────────────────────────────
class _MplCanvas(QWidget):
    def __init__(self, parent=None, w=6, h=4, dpi=96):
        super().__init__(parent)
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from matplotlib.figure import Figure
        self.fig = Figure(figsize=(w, h), dpi=dpi, tight_layout=True)
        self.axes = self.fig.add_subplot(111)
        self._cv = FigureCanvasQTAgg(self.fig)
        lay = QVBoxLayout(self); lay.setContentsMargins(0,0,0,0); lay.addWidget(self._cv)
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
        btn_load = PrimaryPushButton("载入地形数据"); btn_load.clicked.connect(self._on_load_terrain)
        self._terrain_lbl = QLabel("— 未载入 —"); self._terrain_lbl.setStyleSheet(f"color:{T2};font-size:12px;")
        load_r.addWidget(btn_load); load_r.addWidget(self._terrain_lbl); load_r.addStretch()
        f.addRow("", load_r)
        lay.addWidget(g)

        # 中心线
        g2 = QGroupBox("渠道中心线"); f2 = QFormLayout(g2); f2.setSpacing(8)
        self._al_src = QComboBox(); self._al_src.addItems(["DXF 多段线", "手动输入（起止点直线）"])
        self._al_src.currentIndexChanged.connect(self._on_al_src_changed)
        f2.addRow("来源:", self._al_src)
        al_r = QHBoxLayout()
        self._al_path = FLineEdit(); self._al_path.setPlaceholderText("中心线 DXF 文件路径…")
        btn_al = PushButton("浏览"); btn_al.setFixedWidth(64); btn_al.clicked.connect(self._browse_alignment)
        al_r.addWidget(self._al_path, 1); al_r.addWidget(btn_al)
        self._al_file_w = QWidget(); self._al_file_w.setLayout(al_r)
        f2.addRow("DXF 文件:", self._al_file_w)
        self._al_manual_w = QWidget(); mf = QFormLayout(self._al_manual_w); mf.setContentsMargins(0,0,0,0)
        self._al_x0 = QDoubleSpinBox(); self._al_x0.setRange(-1e8,1e8); self._al_x0.setDecimals(3)
        self._al_y0 = QDoubleSpinBox(); self._al_y0.setRange(-1e8,1e8); self._al_y0.setDecimals(3)
        self._al_x1 = QDoubleSpinBox(); self._al_x1.setRange(-1e8,1e8); self._al_x1.setDecimals(3)
        self._al_y1 = QDoubleSpinBox(); self._al_y1.setRange(-1e8,1e8); self._al_y1.setDecimals(3)
        r0 = QHBoxLayout(); r0.addWidget(QLabel("X₀:")); r0.addWidget(self._al_x0); r0.addWidget(QLabel("Y₀:")); r0.addWidget(self._al_y0)
        r1 = QHBoxLayout(); r1.addWidget(QLabel("X₁:")); r1.addWidget(self._al_x1); r1.addWidget(QLabel("Y₁:")); r1.addWidget(self._al_y1)
        mf.addRow("起点:", r0); mf.addRow("终点:", r1)
        f2.addRow("坐标:", self._al_manual_w); self._al_manual_w.setVisible(False)
        self._al_layer = FLineEdit(); self._al_layer.setPlaceholderText("中心线图层名（默认: 中心线）")
        f2.addRow("图层名:", self._al_layer)
        lay.addWidget(g2)

        # 设计断面
        g3 = QGroupBox("渠道设计断面参数"); f3 = QFormLayout(g3); f3.setSpacing(8)
        self._ds_b  = QDoubleSpinBox(); self._ds_b.setRange(0.1,100);  self._ds_b.setValue(3.0);  self._ds_b.setSuffix(" m")
        self._ds_h  = QDoubleSpinBox(); self._ds_h.setRange(0.1,30);   self._ds_h.setValue(2.0);  self._ds_h.setSuffix(" m")
        self._ds_ml = QDoubleSpinBox(); self._ds_ml.setRange(0,5);     self._ds_ml.setValue(1.5); self._ds_ml.setSingleStep(0.25)
        self._ds_mr = QDoubleSpinBox(); self._ds_mr.setRange(0,5);     self._ds_mr.setValue(1.5); self._ds_mr.setSingleStep(0.25)
        f3.addRow("渠底宽 b:", self._ds_b); f3.addRow("渠深 h:", self._ds_h)
        f3.addRow("左内坡比 m:", self._ds_ml); f3.addRow("右内坡比 m:", self._ds_mr)
        lay.addWidget(g3)

        # 纵坡设计
        g4 = QGroupBox("纵坡设计（渠底高程）"); f4 = QFormLayout(g4); f4.setSpacing(8)
        self._dp_s0 = QDoubleSpinBox(); self._dp_s0.setRange(0,1e6); self._dp_s0.setSuffix(" m")
        self._dp_e0 = QDoubleSpinBox(); self._dp_e0.setRange(-200,5000); self._dp_e0.setDecimals(3); self._dp_e0.setValue(97.0); self._dp_e0.setSuffix(" m")
        self._dp_i  = QDoubleSpinBox(); self._dp_i.setRange(-0.1,0.1); self._dp_i.setDecimals(6); self._dp_i.setValue(-0.0003); self._dp_i.setSingleStep(0.0001)
        self._dp_s1 = QDoubleSpinBox(); self._dp_s1.setRange(0,1e6); self._dp_s1.setValue(1000.0); self._dp_s1.setSuffix(" m")
        f4.addRow("起始桩号:", self._dp_s0); f4.addRow("起始渠底高程:", self._dp_e0)
        f4.addRow("纵坡 i（负=顺坡）:", self._dp_i); f4.addRow("终止桩号:", self._dp_s1)
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
        self._cs_sample   = QDoubleSpinBox(); self._cs_sample.setRange(0.1,5);  self._cs_sample.setValue(0.5);   self._cs_sample.setSuffix(" m")
        self._extra_sta_edit = FLineEdit()
        self._extra_sta_edit.setPlaceholderText("关键桩号（逗号分隔，如 100,250.5,500）")
        f6.addRow("纵断面采样步长:", self._long_step); f6.addRow("横断面间距:", self._cs_interval)
        f6.addRow("横断面半宽:", self._cs_hw);         f6.addRow("横断面采样步长:", self._cs_sample)
        f6.addRow("关键桩号（额外）:", self._extra_sta_edit)
        lay.addWidget(g6)
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
        vl.addWidget(QLabel("状态:")); vl.addWidget(self._tin_stat)
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
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(8,8,8,8); lay.setSpacing(10)
        g = QGroupBox("输出设置"); f = QFormLayout(g); f.setSpacing(8)
        od_r = QHBoxLayout()
        self._out_dir = FLineEdit(); self._out_dir.setPlaceholderText("输出目录（默认当前目录）")
        btn_od = PushButton("浏览"); btn_od.setFixedWidth(64); btn_od.clicked.connect(self._browse_outdir)
        od_r.addWidget(self._out_dir, 1); od_r.addWidget(btn_od)
        self._proj_name = FLineEdit(); self._proj_name.setPlaceholderText("项目名称（用于文件名前缀）")
        f.addRow("输出目录:", od_r); f.addRow("项目名称:", self._proj_name)
        lay.addWidget(g)
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
        lay.addWidget(g3, 1)
        return w

    # ── 浏览按钮 ─────────────────────────────────────────────
    def _browse_terrain(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择地形文件", "", "地形文件 (*.dxf *.csv *.txt *.xlsx);;所有文件 (*)")
        if p: self._terrain_path.setText(p)

    def _browse_alignment(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择中心线 DXF", "", "DXF 文件 (*.dxf);;所有文件 (*)")
        if p: self._al_path.setText(p)

    def _browse_outdir(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if d: self._out_dir.setText(d)

    def _on_al_src_changed(self, idx: int):
        self._al_file_w.setVisible(idx == 0)
        self._al_manual_w.setVisible(idx == 1)

    # ── 日志 + InfoBar ───────────────────────────────────────
    def _log_msg(self, msg: str, level: str = "INFO"):
        prefix = {"INFO":"ℹ️","OK":"✅","WARN":"⚠️","ERR":"❌"}.get(level, "•")
        self._log.append(f"{prefix} {msg}")

    def _infobar(self, title: str, content: str, level: str = "success"):
        fn = {"success": InfoBar.success, "warning": InfoBar.warning,
              "error": InfoBar.error, "info": InfoBar.info}.get(level, InfoBar.info)
        fn(title=title, content=content, orient=Qt.Horizontal,
           isClosable=True, position=InfoBarPosition.TOP, duration=4000, parent=self)
