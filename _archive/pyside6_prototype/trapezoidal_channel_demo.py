# -*- coding: utf-8 -*-
"""
PySide6 原型试水 —— 梯形明渠水力设计

功能：
1. 参数输入面板（设计流量、糙率、坡度等）
2. 一键计算（复用现有 明渠设计.py 的计算逻辑）
3. 结果展示（设计工况 + 加大工况 + 附录E方案表格）

独立运行，不影响原有任何文件。
"""

import sys
import os
import math

# 将父目录加入路径，以便导入现有计算模块
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_root, "渠系建筑物断面计算"))

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QLineEdit, QPushButton, QGroupBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QSplitter,
    QMessageBox, QFrame, QSizePolicy, QStatusBar, QTabWidget
)
from PySide6.QtCore import Qt, QLocale
from PySide6.QtGui import QFont, QColor, QPalette, QDoubleValidator, QIcon

# 导入现有计算逻辑
from 明渠设计 import (
    quick_calculate_trapezoidal,
    calculate_all_appendix_e_schemes,
)


# ============================================================
# 样式常量
# ============================================================
PRIMARY_COLOR = "#1976D2"
SUCCESS_COLOR = "#2E7D32"
WARNING_COLOR = "#F57C00"
ERROR_COLOR = "#D32F2F"
BG_COLOR = "#F5F7FA"
CARD_BG = "#FFFFFF"
BORDER_COLOR = "#E0E0E0"
TEXT_PRIMARY = "#212121"
TEXT_SECONDARY = "#757575"

GLOBAL_STYLE = f"""
QMainWindow {{
    background-color: {BG_COLOR};
}}
QGroupBox {{
    font-size: 13px;
    font-weight: bold;
    color: {PRIMARY_COLOR};
    border: 1px solid {BORDER_COLOR};
    border-radius: 6px;
    margin-top: 12px;
    padding: 14px 10px 10px 10px;
    background-color: {CARD_BG};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    background-color: {CARD_BG};
}}
QLabel {{
    color: {TEXT_PRIMARY};
    font-size: 12px;
}}
QLineEdit {{
    border: 1px solid {BORDER_COLOR};
    border-radius: 4px;
    padding: 5px 8px;
    font-size: 12px;
    background-color: white;
    min-height: 24px;
}}
QLineEdit:focus {{
    border: 2px solid {PRIMARY_COLOR};
}}
QLineEdit:disabled {{
    background-color: #F0F0F0;
    color: #999;
}}
QPushButton {{
    font-size: 12px;
    font-weight: bold;
    border: none;
    border-radius: 5px;
    padding: 8px 20px;
    min-height: 28px;
}}
QPushButton#calcBtn {{
    background-color: {PRIMARY_COLOR};
    color: white;
    font-size: 14px;
    padding: 10px 32px;
}}
QPushButton#calcBtn:hover {{
    background-color: #1565C0;
}}
QPushButton#calcBtn:pressed {{
    background-color: #0D47A1;
}}
QPushButton#clearBtn {{
    background-color: #E0E0E0;
    color: {TEXT_PRIMARY};
}}
QPushButton#clearBtn:hover {{
    background-color: #BDBDBD;
}}
QTableWidget {{
    border: 1px solid {BORDER_COLOR};
    border-radius: 4px;
    gridline-color: #EEEEEE;
    font-size: 12px;
    background-color: white;
    alternate-background-color: #FAFAFA;
}}
QTableWidget::item {{
    padding: 4px 8px;
}}
QHeaderView::section {{
    background-color: {PRIMARY_COLOR};
    color: white;
    padding: 6px 8px;
    border: none;
    font-size: 11px;
    font-weight: bold;
}}
QTabWidget::pane {{
    border: 1px solid {BORDER_COLOR};
    border-radius: 4px;
    background-color: {CARD_BG};
}}
QTabBar::tab {{
    background-color: #E8EAF6;
    color: {TEXT_PRIMARY};
    padding: 8px 18px;
    margin-right: 2px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    font-size: 12px;
}}
QTabBar::tab:selected {{
    background-color: {PRIMARY_COLOR};
    color: white;
    font-weight: bold;
}}
QTabBar::tab:hover:!selected {{
    background-color: #C5CAE9;
}}
QStatusBar {{
    background-color: {CARD_BG};
    border-top: 1px solid {BORDER_COLOR};
    font-size: 11px;
    color: {TEXT_SECONDARY};
}}
"""


class InputField(QWidget):
    """带标签的输入字段组件"""

    def __init__(self, label: str, default: str = "", unit: str = "",
                 tooltip: str = "", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(6)

        # 标签
        lbl = QLabel(label)
        lbl.setFixedWidth(110)
        lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(lbl)

        # 输入框
        self.edit = QLineEdit(default)
        self.edit.setValidator(QDoubleValidator(0, 999999, 6))
        if tooltip:
            self.edit.setToolTip(tooltip)
        layout.addWidget(self.edit, 1)

        # 单位
        if unit:
            unit_lbl = QLabel(unit)
            unit_lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
            unit_lbl.setFixedWidth(40)
            layout.addWidget(unit_lbl)

    def value(self) -> float:
        """获取输入值，无效则返回 0.0"""
        try:
            return float(self.edit.text())
        except (ValueError, TypeError):
            return 0.0

    def set_value(self, val):
        self.edit.setText(str(val))

    def clear(self):
        self.edit.clear()


class ResultCard(QFrame):
    """单个结果卡片"""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(f"""
            ResultCard {{
                background-color: {CARD_BG};
                border: 1px solid {BORDER_COLOR};
                border-radius: 6px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"font-size: 11px; color: {TEXT_SECONDARY};")
        layout.addWidget(title_lbl)

        self.value_lbl = QLabel("—")
        self.value_lbl.setStyleSheet(f"""
            font-size: 18px;
            font-weight: bold;
            color: {TEXT_PRIMARY};
        """)
        layout.addWidget(self.value_lbl)

    def set_value(self, text: str, color: str = TEXT_PRIMARY):
        self.value_lbl.setText(text)
        self.value_lbl.setStyleSheet(f"""
            font-size: 18px;
            font-weight: bold;
            color: {color};
        """)

    def reset(self):
        self.value_lbl.setText("—")
        self.value_lbl.setStyleSheet(f"""
            font-size: 18px;
            font-weight: bold;
            color: {TEXT_PRIMARY};
        """)


class TrapezoidalChannelApp(QMainWindow):
    """梯形明渠水力设计 —— PySide6 原型"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("梯形明渠水力设计 —— PySide6 原型")
        self.setMinimumSize(900, 700)
        self.resize(1060, 780)

        self._init_ui()
        self.statusBar().showMessage("就绪 | PySide6 原型演示")

    # ------------------------------------------------------------------ UI
    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(16, 10, 16, 10)
        main_layout.setSpacing(10)

        # ── 顶部标题 ──
        title_lbl = QLabel("梯形明渠水力设计计算")
        title_lbl.setStyleSheet(f"""
            font-size: 20px;
            font-weight: bold;
            color: {PRIMARY_COLOR};
            padding: 4px 0;
        """)
        main_layout.addWidget(title_lbl)

        subtitle = QLabel("依据《灌溉与排水工程设计标准》(GB 50288-2018) 附录E")
        subtitle.setStyleSheet(f"font-size: 11px; color: {TEXT_SECONDARY};")
        main_layout.addWidget(subtitle)

        # ── 上部：输入 + 结果卡片 ──
        top_splitter = QSplitter(Qt.Horizontal)
        top_splitter.setChildrenCollapsible(False)
        main_layout.addWidget(top_splitter, 0)

        # 左侧 - 输入面板
        input_group = QGroupBox("参数输入")
        input_layout = QVBoxLayout(input_group)
        input_layout.setSpacing(4)

        self.f_Q = InputField("设计流量 Q", "5.0", "m³/s", "渠道设计流量")
        self.f_m = InputField("边坡系数 m", "1.5", "", "梯形渠道边坡系数")
        self.f_n = InputField("糙率 n", "0.025", "", "曼宁糙率系数")
        self.f_slope = InputField("坡度倒数 1/i", "5000", "", "底坡倒数，如5000表示坡度1/5000")
        self.f_vmin = InputField("不淤流速", "0.3", "m/s", "最小允许流速")
        self.f_vmax = InputField("不冲流速", "1.5", "m/s", "最大允许流速")

        for f in [self.f_Q, self.f_m, self.f_n, self.f_slope, self.f_vmin, self.f_vmax]:
            input_layout.addWidget(f)

        # 可选参数
        opt_group = QGroupBox("可选参数")
        opt_layout = QVBoxLayout(opt_group)
        opt_layout.setSpacing(4)
        opt_group.setStyleSheet(opt_group.styleSheet() + f"""
            QGroupBox {{
                color: {WARNING_COLOR};
                border: 1px dashed {BORDER_COLOR};
            }}
        """)

        self.f_beta = InputField("指定宽深比 β", "", "", "留空则自动计算")
        self.f_b = InputField("指定底宽 b", "", "m", "留空则自动计算")
        self.f_inc = InputField("加大比例", "", "%", "留空则按规范自动取值")

        for f in [self.f_beta, self.f_b, self.f_inc]:
            opt_layout.addWidget(f)

        input_layout.addWidget(opt_group)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        calc_btn = QPushButton("计 算")
        calc_btn.setObjectName("calcBtn")
        calc_btn.setCursor(Qt.PointingHandCursor)
        calc_btn.clicked.connect(self._on_calculate)

        clear_btn = QPushButton("清 空")
        clear_btn.setObjectName("clearBtn")
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.clicked.connect(self._on_clear)

        btn_layout.addWidget(calc_btn, 2)
        btn_layout.addWidget(clear_btn, 1)
        input_layout.addLayout(btn_layout)
        input_layout.addStretch()

        top_splitter.addWidget(input_group)

        # 右侧 - 结果概览卡片
        result_overview = QGroupBox("计算结果概览")
        ro_layout = QGridLayout(result_overview)
        ro_layout.setSpacing(8)

        self.card_b = ResultCard("底宽 b (m)")
        self.card_h = ResultCard("水深 h (m)")
        self.card_v = ResultCard("流速 V (m/s)")
        self.card_beta = ResultCard("宽深比 β")
        self.card_A = ResultCard("过水面积 A (m²)")
        self.card_R = ResultCard("水力半径 R (m)")
        self.card_Fb = ResultCard("超高 Fb (m)")
        self.card_H = ResultCard("渠道高度 H (m)")
        self.card_method = ResultCard("设计方法")

        cards = [
            self.card_b, self.card_h, self.card_v,
            self.card_beta, self.card_A, self.card_R,
            self.card_Fb, self.card_H, self.card_method,
        ]
        for i, card in enumerate(cards):
            ro_layout.addWidget(card, i // 3, i % 3)

        top_splitter.addWidget(result_overview)
        top_splitter.setSizes([380, 620])

        # ── 下部：详细结果表格（Tab 页）──
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget, 1)

        # Tab 1：设计工况 & 加大工况
        self.detail_table = self._create_detail_table()
        self.tab_widget.addTab(self.detail_table, "设计 && 加大工况")

        # Tab 2：附录E方案对比
        self.scheme_table = self._create_scheme_table()
        self.tab_widget.addTab(self.scheme_table, "附录E方案对比")

    def _create_detail_table(self) -> QTableWidget:
        table = QTableWidget(2, 8)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.verticalHeader().setVisible(False)

        headers = ["工况", "流量 Q\n(m³/s)", "底宽 b\n(m)", "水深 h\n(m)",
                    "流速 V\n(m/s)", "面积 A\n(m²)", "湿周 X\n(m)", "水力半径 R\n(m)"]
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setRowHeight(0, 36)
        table.setRowHeight(1, 36)

        # 初始化行标签
        for r, label in enumerate(["设计工况", "加大工况"]):
            item = QTableWidgetItem(label)
            item.setTextAlignment(Qt.AlignCenter)
            item.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
            table.setItem(r, 0, item)

        return table

    def _create_scheme_table(self) -> QTableWidget:
        table = QTableWidget(0, 10)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.verticalHeader().setVisible(False)

        headers = ["α", "方案类型", "η (h/h₀)", "水深 h\n(m)", "底宽 b\n(m)",
                    "宽深比 β", "面积 A\n(m²)", "湿周 X\n(m)", "水力半径 R\n(m)", "流速 V\n(m/s)"]
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        return table

    # ------------------------------------------------------------------ 计算
    def _on_calculate(self):
        Q = self.f_Q.value()
        m = self.f_m.value()
        n = self.f_n.value()
        slope_inv = self.f_slope.value()
        v_min = self.f_vmin.value()
        v_max = self.f_vmax.value()

        # 验证
        errors = []
        if Q <= 0:
            errors.append("设计流量 Q 必须大于 0")
        if n <= 0:
            errors.append("糙率 n 必须大于 0")
        if slope_inv <= 0:
            errors.append("坡度倒数 1/i 必须大于 0")
        if v_min >= v_max:
            errors.append("不淤流速必须小于不冲流速")

        if errors:
            QMessageBox.warning(self, "输入错误", "\n".join(errors))
            return

        # 可选参数
        beta_text = self.f_beta.edit.text().strip()
        b_text = self.f_b.edit.text().strip()
        inc_text = self.f_inc.edit.text().strip()

        manual_beta = float(beta_text) if beta_text else None
        manual_b = float(b_text) if b_text else None
        manual_inc = float(inc_text) if inc_text else None

        # 调用现有计算
        result = quick_calculate_trapezoidal(
            Q, m, n, slope_inv, v_min, v_max,
            manual_beta=manual_beta,
            manual_b=manual_b,
            manual_increase_percent=manual_inc
        )

        if result['success']:
            self._display_results(result, Q)
            self.statusBar().showMessage(
                f"计算完成 | 方法: {result['design_method']}", 10000)
        else:
            QMessageBox.critical(self, "计算失败",
                                 result.get('error_message', '未知错误'))
            self.statusBar().showMessage("计算失败", 5000)

        # 附录E方案（无论成功与否都尝试展示）
        i = 1.0 / slope_inv
        schemes = calculate_all_appendix_e_schemes(Q, n, i, m)
        self._display_schemes(schemes, v_min, v_max)

    def _display_results(self, r: dict, Q: float):
        """更新结果卡片和详情表"""
        # 卡片
        self.card_b.set_value(f"{r['b_design']:.3f}")
        self.card_h.set_value(f"{r['h_design']:.3f}")

        v = r['V_design']
        v_color = SUCCESS_COLOR
        self.card_v.set_value(f"{v:.3f}", v_color)

        self.card_beta.set_value(f"{r['Beta_design']:.3f}")
        self.card_A.set_value(f"{r['A_design']:.3f}")
        self.card_R.set_value(f"{r['R_design']:.3f}")

        if r.get('Fb', -1) > 0:
            self.card_Fb.set_value(f"{r['Fb']:.3f}")
        else:
            self.card_Fb.set_value("—")

        if r.get('h_prime', -1) > 0:
            self.card_H.set_value(f"{r['h_prime']:.3f}")
        else:
            self.card_H.set_value("—")

        method = r.get('design_method', '—')
        if len(method) > 16:
            method = method[:16] + "…"
        self.card_method.set_value(method, PRIMARY_COLOR)

        # 详情表 - 设计工况
        design_data = [
            "设计工况",
            f"{Q:.3f}",
            f"{r['b_design']:.3f}",
            f"{r['h_design']:.3f}",
            f"{r['V_design']:.3f}",
            f"{r['A_design']:.3f}",
            f"{r['X_design']:.3f}",
            f"{r['R_design']:.3f}",
        ]
        for c, val in enumerate(design_data):
            item = QTableWidgetItem(val)
            item.setTextAlignment(Qt.AlignCenter)
            if c == 0:
                item.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
            self.detail_table.setItem(0, c, item)

        # 详情表 - 加大工况
        if r.get('h_increased', -1) > 0:
            inc_data = [
                f"加大工况 (+{r['increase_percent']:.0f}%)",
                f"{r['Q_increased']:.3f}",
                f"{r['b_design']:.3f}",
                f"{r['h_increased']:.3f}",
                f"{r.get('V_increased', 0):.3f}",
                f"{r.get('A_increased', 0):.3f}",
                f"{r.get('X_increased', 0):.3f}",
                f"{r.get('R_increased', 0):.3f}",
            ]
            for c, val in enumerate(inc_data):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignCenter)
                if c == 0:
                    item.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
                self.detail_table.setItem(1, c, item)

    def _display_schemes(self, schemes: list, v_min: float, v_max: float):
        """填充附录E方案对比表"""
        self.scheme_table.setRowCount(len(schemes))
        for r, s in enumerate(schemes):
            V = s['V']
            # 判断流速是否满足
            v_ok = v_min < V < v_max

            data = [
                f"{s['alpha']:.2f}",
                s['scheme_type'],
                f"{s['eta']:.4f}",
                f"{s['h']:.4f}",
                f"{s['b']:.4f}",
                f"{s['beta']:.4f}",
                f"{s['A']:.4f}",
                f"{s['X']:.4f}",
                f"{s['R']:.4f}",
                f"{V:.4f}",
            ]
            for c, val in enumerate(data):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignCenter)
                if not v_ok:
                    item.setForeground(QColor(ERROR_COLOR))
                elif s['alpha'] == 1.00:
                    item.setForeground(QColor(PRIMARY_COLOR))
                    item.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
                self.scheme_table.setItem(r, c, item)

            self.scheme_table.setRowHeight(r, 34)

    # ------------------------------------------------------------------ 清空
    def _on_clear(self):
        # 恢复默认值
        self.f_Q.set_value("5.0")
        self.f_m.set_value("1.5")
        self.f_n.set_value("0.025")
        self.f_slope.set_value("5000")
        self.f_vmin.set_value("0.3")
        self.f_vmax.set_value("1.5")
        self.f_beta.clear()
        self.f_b.clear()
        self.f_inc.clear()

        # 清空结果
        for card in [self.card_b, self.card_h, self.card_v, self.card_beta,
                     self.card_A, self.card_R, self.card_Fb, self.card_H,
                     self.card_method]:
            card.reset()

        for r in range(self.detail_table.rowCount()):
            for c in range(1, self.detail_table.columnCount()):
                self.detail_table.setItem(r, c, QTableWidgetItem(""))

        self.scheme_table.setRowCount(0)
        self.statusBar().showMessage("已清空", 3000)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei", 10))
    app.setStyleSheet(GLOBAL_STYLE)

    window = TrapezoidalChannelApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
