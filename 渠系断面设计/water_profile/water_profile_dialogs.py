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
