# -*- coding: utf-8 -*-
"""
水面线面板辅助对话框

包含：
- BuildingLengthDialog: 建筑物长度统计对话框
- BatchChannelConfirmDialog: 批量明渠段插入确认对话框
- OpenChannelDialog: 明渠段参数选择对话框（逐一弹窗模式）
- PressurePipeConfigDialog: 有压管道计算配置对话框
"""

import math
from typing import List, Dict, Any, Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QGroupBox, QGridLayout, QComboBox, QLineEdit,
    QRadioButton, QButtonGroup, QSplitter, QApplication,
    QSizePolicy, QTabWidget, QCheckBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor, QShortcut, QKeySequence

from 渠系断面设计.styles import auto_resize_table, fluent_info, fluent_error, fluent_question

try:
    from qfluentwidgets import PushButton, PrimaryPushButton, LineEdit, ComboBox
except ImportError:
    PushButton = QPushButton
    PrimaryPushButton = QPushButton
    LineEdit = QLineEdit
    ComboBox = QComboBox


# ============================================================
# 正常水深计算（曼宁公式）
# ============================================================
def calculate_normal_depth(Q, B, m, n, i, D=0.0):
    """计算明渠正常水深（曼宁公式），支持梯形/矩形/圆形断面"""
    if Q <= 0 or n <= 0 or i <= 0:
        return 0.0
    # 圆形断面
    if D > 0 and B <= 0:
        h_low, h_high = 0.001, D * 0.95
        r = D / 2
        for _ in range(200):
            h = (h_low + h_high) / 2
            cos_arg = max(-1.0, min(1.0, (r - h) / r))
            theta = 2 * math.acos(cos_arg)
            A = r * r * (theta - math.sin(theta)) / 2
            P = r * theta
            if P <= 1e-10:
                h_low = h
                continue
            R_hyd = A / P
            if R_hyd <= 1e-10:
                h_low = h
                continue
            Q_calc = (1.0 / n) * A * (R_hyd ** (2.0 / 3.0)) * math.sqrt(i)
            if abs(Q_calc - Q) / max(Q, 1e-10) < 1e-6:
                return h
            if Q_calc < Q:
                h_low = h
            else:
                h_high = h
        return (h_low + h_high) / 2
    # 梯形/矩形断面
    if B <= 0:
        return 0.0
    h = 1.0
    for _ in range(100):
        A = (B + m * h) * h
        P = B + 2 * h * math.sqrt(1 + m * m)
        R = A / P if P > 0 else 0
        if R <= 0:
            h *= 1.5
            continue
        Q_calc = A * (1 / n) * (R ** (2.0 / 3.0)) * math.sqrt(i)
        f = Q_calc - Q
        if abs(f) < 1e-6:
            return h
        dA = B + 2 * m * h
        dP = 2 * math.sqrt(1 + m * m)
        dR = (dA * P - A * dP) / (P * P) if P > 0 else 0
        dQ = (dA * (R ** (2.0 / 3.0)) + A * (2.0 / 3.0) * (R ** (-1.0 / 3.0)) * dR) * (1 / n) * math.sqrt(i)
        if abs(dQ) < 1e-10:
            h *= 1.1
            continue
        h_new = h - f / dQ
        h = h_new if h_new > 0 else h / 2
    return h


# OpenChannelParams 已移至核心数据模型层，从此处重新导出以保持兼容
from 推求水面线.models.data_models import OpenChannelParams


# ============================================================
# 有压管道计算配置对话框
# ============================================================
class PressurePipeConfigDialog(QDialog):
    """有压管道计算配置对话框（在计算前配置参数）"""

    def __init__(self, parent=None, default_sensitivity_enabled=True):
        super().__init__(parent)
        self.setWindowTitle("有压管道水力计算配置")
        self.setMinimumWidth(520)
        self.setModal(True)

        self._sensitivity_enabled = default_sensitivity_enabled

        self._init_ui()

    def _init_ui(self):
        """初始化UI"""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(14)

        # 标题说明
        title = QLabel("有压管道水力计算")
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #1976D2;")
        lay.addWidget(title)

        desc = QLabel(
            "系统将根据表格中的有压管道数据，计算沿程损失、弯头损失、渐变段损失等，\n"
            "并将总水头损失回写到"倒虹吸/有压管道水头损失"列。"
        )
        desc.setStyleSheet("font-size: 12px; color: #616161;")
        desc.setWordWrap(True)
        lay.addWidget(desc)

        # 分隔线
        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet("background-color: #E0E0E0;")
        lay.addWidget(line)

        # 配置选项组
        config_grp = QGroupBox("计算选项")
        config_grp.setStyleSheet("""
            QGroupBox {
                font-size: 13px; font-weight: bold; color: #424242;
                border: 1px solid #E0E0E0; border-radius: 6px;
                margin-top: 10px; padding: 14px 12px 10px 12px;
                background: #FAFAFA;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 12px;
                padding: 0 6px; background: #FAFAFA;
            }
        """)
        config_lay = QVBoxLayout(config_grp)
        config_lay.setSpacing(10)

        # 球墨铸铁管上下限对比勾选框
        try:
            from qfluentwidgets import CheckBox
            self.chk_sensitivity = CheckBox("球墨铸铁管 f 上下限对比")
        except ImportError:
            self.chk_sensitivity = QCheckBox("球墨铸铁管 f 上下限对比")

        self.chk_sensitivity.setChecked(self._sensitivity_enabled)
        self.chk_sensitivity.setStyleSheet("font-size: 13px; color: #424242;")
        config_lay.addWidget(self.chk_sensitivity)

        # 说明文本
        sensitivity_desc = QLabel(
            "球墨铸铁管按规范给定 f 上下限（非单一值）：\n"
            "  • 主值 f = 223200（用于计算主结果并回写）\n"
            "  • 下限 f = 189900（仅用于对比分析，不影响回写）\n"
            "勾选后，结果对话框将显示上下限对比列，便于评估设计裕度。"
        )
        sensitivity_desc.setStyleSheet(
            "font-size: 12px; color: #757575; padding-left: 24px; font-weight: normal;"
        )
        sensitivity_desc.setWordWrap(True)
        config_lay.addWidget(sensitivity_desc)

        lay.addWidget(config_grp)

        lay.addStretch()

        # 底部按钮
        btn_lay = QHBoxLayout()
        btn_lay.addStretch()

        try:
            from qfluentwidgets import PushButton as FluentPushButton
            from qfluentwidgets import PrimaryPushButton as FluentPrimaryPushButton
            btn_cancel = FluentPushButton("取消")
            btn_start = FluentPrimaryPushButton("开始计算")
        except ImportError:
            btn_cancel = QPushButton("取消")
            btn_start = QPushButton("开始计算")

        btn_cancel.setFixedWidth(90)
        btn_start.setFixedWidth(110)

        btn_cancel.clicked.connect(self.reject)
        btn_start.clicked.connect(self.accept)

        btn_lay.addWidget(btn_cancel)
        btn_lay.addSpacing(10)
        btn_lay.addWidget(btn_start)

        lay.addLayout(btn_lay)

    def get_sensitivity_enabled(self) -> bool:
        """获取是否启用球墨铸铁管上下限对比"""
        return self.chk_sensitivity.isChecked()
