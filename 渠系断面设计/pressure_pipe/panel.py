# -*- coding: utf-8 -*-
"""
有压管道设计面板 —— QWidget 版本

功能：单次计算（推荐管径 + 候选表 + 详细过程）、批量计算（后台线程 + 进度 + CSV/PDF）
"""

import sys
import os
import html as html_mod

_pkg_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_pkg_root, "渠系建筑物断面计算"))

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox,
    QSplitter, QFrame, QTabWidget, QTextEdit, QFileDialog,
    QScrollArea, QTableWidget, QTableWidgetItem, QHeaderView,
    QProgressBar, QAbstractItemView,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWebEngineWidgets import QWebEngineView

from qfluentwidgets import (
    ComboBox, PushButton, PrimaryPushButton, LineEdit,
    CheckBox, InfoBar, InfoBarPosition
)

from 有压管道设计 import (
    PIPE_MATERIALS, DEFAULT_DIAMETER_SERIES,
    DEFAULT_Q_RANGE, DEFAULT_SLOPE_DENOMINATORS,
    PressurePipeInput, RecommendationResult,
    get_flow_increase_percent, evaluate_single_diameter,
    recommend_diameter, build_detailed_process_text,
    run_batch_scan, BatchScanConfig, BatchScanResult,
)

from 渠系断面设计.styles import (
    P, S, W, E, BG, CARD, BD, T1, T2,
    INPUT_LABEL_STYLE, INPUT_SECTION_STYLE, INPUT_HINT_STYLE
)
from 渠系断面设计.formula_renderer import (
    plain_text_to_formula_html, load_formula_page, make_plain_html,
)


def _e(s):
    return html_mod.escape(str(s))


# ============================================================
# 批量计算工作线程
# ============================================================
class _BatchWorker(QThread):
    """后台批量计算线程"""
    progress = Signal(int, int, str)   # current, total, message
    finished = Signal(object)          # BatchScanResult
    error = Signal(str)

    def __init__(self, config: BatchScanConfig, parent=None):
        super().__init__(parent)
        self._config = config
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            result = run_batch_scan(
                self._config,
                progress_cb=lambda cur, tot, msg: self.progress.emit(cur, tot, msg),
                cancel_flag=lambda: self._cancel,
            )
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


# ============================================================
# 面板
# ============================================================
class PressurePipePanel(QWidget):
    """有压管道设计面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_result: RecommendationResult | None = None
        self._export_plain_text = ""
        self._batch_worker: _BatchWorker | None = None
        self._init_ui()

    # ================================================================
    # UI 构建
    # ================================================================
    def _init_ui(self):
        main_lay = QHBoxLayout(self)
        main_lay.setContentsMargins(10, 8, 10, 8)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        main_lay.addWidget(splitter)

        # 左侧: 输入参数
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        inp_w = QWidget()
        self._build_input(inp_w)
        scroll.setWidget(inp_w)
        scroll.setMinimumWidth(280)
        scroll.setMaximumWidth(500)
        splitter.addWidget(scroll)

        # 右侧: 输出区
        out_w = QWidget()
        self._build_output(out_w)
        splitter.addWidget(out_w)
        splitter.setSizes([400, 900])

    # ----------------------------------------------------------------
    # 输入区
    # ----------------------------------------------------------------
    def _build_input(self, parent):
        lay = QVBoxLayout(parent)
        lay.setContentsMargins(5, 5, 5, 5)
        lay.setSpacing(6)

        # ---- 单次计算参数组 ----
        grp = QGroupBox("输入参数")
        fl = QVBoxLayout(grp)
        fl.setSpacing(5)

        # 设计流量
        self.Q_edit = self._field(fl, "设计流量 Q (m³/s):", "0.5")
        # 管材
        r = QHBoxLayout()
        lbl = QLabel("管材类型:")
        lbl.setMinimumWidth(140)
        lbl.setStyleSheet(INPUT_LABEL_STYLE)
        r.addWidget(lbl)
        self.material_combo = ComboBox()
        mat_display = [(k, v["name"]) for k, v in PIPE_MATERIALS.items()]
        self._mat_keys = [k for k, _ in mat_display]
        self.material_combo.addItems([n for _, n in mat_display])
        r.addWidget(self.material_combo, 1)
        fl.addLayout(r)

        # 管长
        fl.addWidget(self._slbl("【管道参数】"))
        self.length_edit = self._field(fl, "管长 L (m):", "1000")

        # 加大流量
        self.inc_cb = CheckBox("考虑加大流量")
        self.inc_cb.setChecked(True)
        self.inc_cb.stateChanged.connect(self._on_inc_toggle)
        fl.addWidget(self.inc_cb)
        self.inc_edit = self._field(fl, "加大比例 (%):", "")
        self.inc_hint = QLabel("(留空则自动计算)")
        self.inc_hint.setStyleSheet(INPUT_HINT_STYLE)
        fl.addWidget(self.inc_hint)

        fl.addWidget(self._sep())

        # 详细过程开关
        self.detail_cb = CheckBox("输出详细计算过程")
        self.detail_cb.setChecked(True)
        fl.addWidget(self.detail_cb)

        # 按钮
        br = QHBoxLayout()
        cb = PrimaryPushButton("计算")
        cb.setCursor(Qt.PointingHandCursor)
        cb.clicked.connect(self._calculate)
        clb = PushButton("清空")
        clb.setCursor(Qt.PointingHandCursor)
        clb.clicked.connect(self._clear)
        br.addWidget(cb)
        br.addWidget(clb)
        fl.addLayout(br)

        lay.addWidget(grp)

        # ---- 批量计算参数组 ----
        grp2 = QGroupBox("批量计算")
        fl2 = QVBoxLayout(grp2)
        fl2.setSpacing(5)

        fl2.addWidget(self._hint("按默认参数范围批量扫描计算，生成 CSV / PDF"))
        self.batch_q_edit = self._field(fl2, "Q范围(起,止,步长):", "0.1,2.0,0.1")
        self.batch_slope_edit = self._field(fl2, "坡度分母(逗号):", "500,750,1000,1500,2000,2500,3000,3500,4000")
        self.batch_n_edit = self._field(fl2, "糙率 n:", "0.014")
        self.batch_length_edit = self._field(fl2, "管长 L (m):", "1000")

        # 管材多选（默认全选）
        fl2.addWidget(self._slbl("【管材选择】"))
        self._mat_cbs = {}
        for k, v in PIPE_MATERIALS.items():
            cb_mat = CheckBox(v["name"])
            cb_mat.setChecked(True)
            fl2.addWidget(cb_mat)
            self._mat_cbs[k] = cb_mat

        fl2.addWidget(self._sep())

        # 进度条
        self.batch_progress = QProgressBar()
        self.batch_progress.setVisible(False)
        fl2.addWidget(self.batch_progress)
        self.batch_status_label = QLabel("")
        self.batch_status_label.setStyleSheet("font-size:11px;color:#666;")
        self.batch_status_label.setVisible(False)
        fl2.addWidget(self.batch_status_label)

        # 按钮
        br2 = QHBoxLayout()
        self.batch_btn = PrimaryPushButton("开始批量计算")
        self.batch_btn.setCursor(Qt.PointingHandCursor)
        self.batch_btn.clicked.connect(self._start_batch)
        self.cancel_btn = PushButton("取消")
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self._cancel_batch)
        br2.addWidget(self.batch_btn)
        br2.addWidget(self.cancel_btn)
        fl2.addLayout(br2)

        lay.addWidget(grp2)
        lay.addStretch()

    # ----------------------------------------------------------------
    # 输出区
    # ----------------------------------------------------------------
    def _build_output(self, parent):
        lay = QVBoxLayout(parent)
        lay.setContentsMargins(0, 0, 0, 0)
        self.notebook = QTabWidget()
        lay.addWidget(self.notebook)

        # Tab1: 计算结果（公式渲染）
        t1 = QWidget()
        t1l = QVBoxLayout(t1)
        t1l.setContentsMargins(5, 5, 5, 5)
        grp = QGroupBox("计算结果详情")
        gl = QVBoxLayout(grp)
        self.result_view = QWebEngineView()
        gl.addWidget(self.result_view)
        t1l.addWidget(grp)
        self.notebook.addTab(t1, "计算结果")

        # Tab2: 候选表
        t2 = QWidget()
        t2l = QVBoxLayout(t2)
        t2l.setContentsMargins(5, 5, 5, 5)
        self.candidate_table = QTableWidget()
        self.candidate_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.candidate_table.setAlternatingRowColors(True)
        self.candidate_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        t2l.addWidget(self.candidate_table)
        self.notebook.addTab(t2, "候选管径")

        # Tab3: 批量日志
        t3 = QWidget()
        t3l = QVBoxLayout(t3)
        t3l.setContentsMargins(5, 5, 5, 5)
        self.batch_log = QTextEdit()
        self.batch_log.setReadOnly(True)
        t3l.addWidget(self.batch_log)
        self.notebook.addTab(t3, "批量计算日志")

        self._show_initial_help()

    # ----------------------------------------------------------------
    # 辅助 UI
    # ----------------------------------------------------------------
    def _field(self, lay, label, default=""):
        r = QHBoxLayout()
        l = QLabel(label)
        l.setMinimumWidth(140)
        l.setStyleSheet(INPUT_LABEL_STYLE)
        r.addWidget(l)
        e = LineEdit()
        e.setText(default)
        r.addWidget(e, 1)
        lay.addLayout(r)
        return e

    def _slbl(self, t):
        l = QLabel(t)
        l.setStyleSheet(INPUT_SECTION_STYLE)
        return l

    def _hint(self, t):
        l = QLabel(t)
        l.setStyleSheet(INPUT_HINT_STYLE)
        return l

    def _sep(self):
        f = QFrame()
        f.setFrameShape(QFrame.HLine)
        f.setStyleSheet(f"color:{BD};")
        return f

    def _on_inc_toggle(self, _state):
        enabled = self.inc_cb.isChecked()
        self.inc_edit.setVisible(enabled)
        self.inc_hint.setVisible(enabled)

    def _show_initial_help(self):
        """初始帮助页"""
        html = f"""
        <div style="padding:40px;text-align:center;font-family:'Microsoft YaHei',sans-serif;">
            <h2 style="color:{P};">有压管道设计</h2>
            <p style="color:{T2};font-size:14px;">
                在左侧输入设计参数后点击"计算"，即可获得推荐管径及详细计算过程。<br><br>
                <b>支持功能：</b><br>
                ● 单次计算：自动推荐经济管径，展示前5候选<br>
                ● 批量计算：多管材/多工况扫描，生成 CSV + PDF 图表<br><br>
                <b>管材支持：</b>HDPE/玻璃钢夹砂管、球墨铸铁管、预应力钢筒混凝土管、钢管<br>
                <b>推荐规则：</b>经济优先 → 妥协兜底 → 就近流速兜底
            </p>
        </div>
        """
        self.result_view.setHtml(html)

    # ================================================================
    # 单次计算
    # ================================================================
    def _calculate(self):
        try:
            Q = float(self.Q_edit.text().strip())
            if Q <= 0:
                raise ValueError("Q 必须大于 0")
        except ValueError as ex:
            InfoBar.error(title="输入错误", content=f"设计流量无效: {ex}",
                          parent=self, position=InfoBarPosition.TOP_RIGHT, duration=4000)
            return

        try:
            length_m = float(self.length_edit.text().strip())
            if length_m <= 0:
                raise ValueError
        except ValueError:
            length_m = 1000.0

        mat_idx = self.material_combo.currentIndex()
        mat_key = self._mat_keys[mat_idx]

        manual_pct = None
        if self.inc_cb.isChecked():
            txt = self.inc_edit.text().strip()
            if txt:
                try:
                    manual_pct = float(txt)
                except ValueError:
                    pass
        else:
            manual_pct = 0.0  # 不考虑加大流量 → 加大比例为 0

        inp = PressurePipeInput(
            Q=Q, material_key=mat_key,
            length_m=length_m,
            manual_increase_percent=manual_pct,
        )

        result = recommend_diameter(inp)
        self.current_result = result
        self._export_plain_text = result.calc_steps

        # 显示结果
        self._display_result(inp, result)
        self._display_candidates(result)

    def _display_result(self, inp: PressurePipeInput, result: RecommendationResult):
        """显示推荐结果 + 详细过程"""
        rec = result.recommended
        mat_name = PIPE_MATERIALS[inp.material_key]["name"]

        # 构建摘要卡片 HTML
        if rec:
            badge_color = {"经济": S, "妥协": W, "兜底": E}.get(result.category, T2)
            card_html = f"""
            <div style="background:{CARD};border:2px solid {badge_color};border-radius:10px;
                        padding:18px 24px;margin:10px 0;font-family:'Microsoft YaHei',sans-serif;">
                <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;">
                    <span style="background:{badge_color};color:white;padding:3px 12px;
                                 border-radius:12px;font-size:12px;font-weight:bold;">
                        {_e(result.category)}区推荐
                    </span>
                    <span style="font-size:13px;color:{T2};">管材: {_e(mat_name)}</span>
                </div>
                <table style="width:100%;border-collapse:collapse;font-size:13px;">
                    <tr>
                        <td style="padding:6px 12px;color:{T2};">推荐管径</td>
                        <td style="padding:6px 12px;font-weight:bold;color:{T1};">
                            D = {rec.D} m ({rec.D*1000:.0f} mm)
                        </td>
                    </tr>
                    <tr style="background:#F8F9FA;">
                        <td style="padding:6px 12px;color:{T2};">有压流速</td>
                        <td style="padding:6px 12px;font-weight:bold;color:{T1};">
                            V = {rec.V_press:.4f} m/s
                        </td>
                    </tr>
                    <tr>
                        <td style="padding:6px 12px;color:{T2};">沿程水损</td>
                        <td style="padding:6px 12px;">{rec.hf_friction_km:.4f} m/km</td>
                    </tr>
                    <tr style="background:#F8F9FA;">
                        <td style="padding:6px 12px;color:{T2};">局部水损</td>
                        <td style="padding:6px 12px;">{rec.hf_local_km:.4f} m/km</td>
                    </tr>
                    <tr>
                        <td style="padding:6px 12px;color:{T2};">总水损</td>
                        <td style="padding:6px 12px;font-weight:bold;">
                            {rec.hf_total_km:.4f} m/km
                        </td>
                    </tr>
                    <tr style="background:#F8F9FA;">
                        <td style="padding:6px 12px;color:{T2};">按管长折算总损失</td>
                        <td style="padding:6px 12px;font-weight:bold;">
                            {rec.h_loss_total_m:.4f} m (L={inp.length_m}m)
                        </td>
                    </tr>
                </table>
            </div>
            """
        else:
            card_html = f"""
            <div style="background:#FFF3E0;border:2px solid {E};border-radius:10px;
                        padding:18px 24px;margin:10px 0;font-family:'Microsoft YaHei',sans-serif;">
                <p style="color:{E};font-weight:bold;">无可用推荐结果</p>
                <p>{_e(result.reason)}</p>
            </div>
            """

        if self.detail_cb.isChecked() and result.calc_steps:
            formula_html = plain_text_to_formula_html(result.calc_steps)
            full_html = card_html + formula_html
        else:
            full_html = card_html

        load_formula_page(self.result_view, full_html)
        self.notebook.setCurrentIndex(0)

    def _display_candidates(self, result: RecommendationResult):
        """填充候选管径表"""
        headers = ["排名", "管径 D (m)", "管径 (mm)", "流速 V (m/s)",
                    "沿程水损 (m/km)", "局部水损 (m/km)", "总水损 (m/km)",
                    "总损失 (m)", "类别", "标记"]
        self.candidate_table.setColumnCount(len(headers))
        self.candidate_table.setHorizontalHeaderLabels(headers)

        candidates = result.top_candidates
        self.candidate_table.setRowCount(len(candidates))

        for i, c in enumerate(candidates):
            items = [
                str(i + 1),
                f"{c.D:.3f}",
                f"{c.D * 1000:.0f}",
                f"{c.V_press:.4f}",
                f"{c.hf_friction_km:.4f}",
                f"{c.hf_local_km:.4f}",
                f"{c.hf_total_km:.4f}",
                f"{c.h_loss_total_m:.4f}",
                c.category,
                ", ".join(c.flags) if c.flags else "",
            ]
            for j, txt in enumerate(items):
                item = QTableWidgetItem(txt)
                item.setTextAlignment(Qt.AlignCenter)
                self.candidate_table.setItem(i, j, item)

        self.candidate_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

    def _clear(self):
        self.Q_edit.setText("")
        self.current_result = None
        self._export_plain_text = ""
        self._show_initial_help()
        self.candidate_table.setRowCount(0)

    # ================================================================
    # 批量计算
    # ================================================================
    def _start_batch(self):
        # 选择输出目录
        output_dir = QFileDialog.getExistingDirectory(self, "选择输出目录", "")
        if not output_dir:
            return

        # 解析 Q 范围
        try:
            parts = self.batch_q_edit.text().strip().split(",")
            q_start, q_end, q_step = float(parts[0]), float(parts[1]), float(parts[2])
            import numpy as np
            q_values = np.round(np.arange(q_start, q_end + q_step * 0.5, q_step), 2)
        except Exception:
            InfoBar.error(title="参数错误", content="Q范围格式无效，应为: 起始,结束,步长",
                          parent=self, position=InfoBarPosition.TOP_RIGHT, duration=4000)
            return

        # 解析坡度分母
        try:
            slope_denoms = [int(x.strip()) for x in self.batch_slope_edit.text().strip().split(",")]
        except Exception:
            InfoBar.error(title="参数错误", content="坡度分母格式无效",
                          parent=self, position=InfoBarPosition.TOP_RIGHT, duration=4000)
            return

        # 糙率
        try:
            n_unpr = float(self.batch_n_edit.text().strip())
        except ValueError:
            n_unpr = 0.014

        # 管长
        try:
            length_m = float(self.batch_length_edit.text().strip())
        except ValueError:
            length_m = 1000.0

        # 管材
        selected_mats = [k for k, cb in self._mat_cbs.items() if cb.isChecked()]
        if not selected_mats:
            InfoBar.error(title="参数错误", content="至少选择一种管材",
                          parent=self, position=InfoBarPosition.TOP_RIGHT, duration=4000)
            return

        config = BatchScanConfig(
            q_values=q_values,
            slope_denominators=slope_denoms,
            diameter_values=DEFAULT_DIAMETER_SERIES,
            materials=selected_mats,
            n_unpr=n_unpr,
            length_m=length_m,
            output_dir=output_dir,
        )

        # 切换UI
        self.batch_btn.setEnabled(False)
        self.cancel_btn.setVisible(True)
        self.batch_progress.setVisible(True)
        self.batch_progress.setValue(0)
        self.batch_status_label.setVisible(True)
        self.batch_status_label.setText("正在准备...")
        self.batch_log.clear()
        self.notebook.setCurrentIndex(2)

        # 启动线程
        self._batch_worker = _BatchWorker(config, self)
        self._batch_worker.progress.connect(self._on_batch_progress)
        self._batch_worker.finished.connect(self._on_batch_finished)
        self._batch_worker.error.connect(self._on_batch_error)
        self._batch_worker.start()

    def _cancel_batch(self):
        if self._batch_worker:
            self._batch_worker.cancel()
            self.batch_status_label.setText("正在取消...")

    def _on_batch_progress(self, current, total, msg):
        if total > 0:
            self.batch_progress.setMaximum(total)
            self.batch_progress.setValue(current)
        self.batch_status_label.setText(msg)

    def _on_batch_finished(self, result: BatchScanResult):
        self.batch_btn.setEnabled(True)
        self.cancel_btn.setVisible(False)
        self.batch_progress.setVisible(False)
        self.batch_status_label.setText("完成")

        for log in result.logs:
            self.batch_log.append(log)

        if result.csv_path:
            self.batch_log.append(f"\nCSV 路径: {result.csv_path}")
        if result.merged_pdf:
            self.batch_log.append(f"合并PDF: {result.merged_pdf}")
        self.batch_log.append(f"\n共生成 {len(result.generated_pdfs)} 个PDF, {len(result.generated_pngs)} 个PNG")

        InfoBar.success(
            title="批量计算完成",
            content=f"CSV + {len(result.generated_pdfs)} PDF 已输出",
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
            duration=5000,
        )

    def _on_batch_error(self, msg):
        self.batch_btn.setEnabled(True)
        self.cancel_btn.setVisible(False)
        self.batch_progress.setVisible(False)
        self.batch_status_label.setText("出错")
        self.batch_log.append(f"错误: {msg}")
        InfoBar.error(title="批量计算失败", content=msg,
                      parent=self, position=InfoBarPosition.TOP_RIGHT, duration=5000)
