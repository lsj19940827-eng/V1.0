# -*- coding: utf-8 -*-
"""
水面线面板辅助对话框

包含：
- BuildingLengthDialog: 建筑物长度统计对话框
- BatchChannelConfirmDialog: 批量明渠段插入确认对话框
- OpenChannelDialog: 明渠段参数选择对话框（逐一弹窗模式）
"""

import math
from typing import List, Dict, Any, Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QGroupBox, QGridLayout, QComboBox, QLineEdit,
    QRadioButton, QButtonGroup, QSplitter, QApplication,
    QSizePolicy, QTabWidget
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor

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
# 建筑物长度统计对话框
# ============================================================
class BuildingLengthDialog(QDialog):
    """
    建筑物长度统计对话框（PySide6版）

    以表格形式展示各建筑物的长度详情和按结构类型汇总，
    支持复制到剪贴板和复制排版格式。
    """

    # 统一样式常量
    _TABLE_FONT = "Microsoft YaHei"
    _TABLE_FONT_SIZE = 10
    _ROW_HEIGHT = 32
    _HEADER_STYLE = (
        "QHeaderView::section {"
        "  background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #F0F4FA, stop:1 #E2E8F0);"
        "  color: #1A2942;"
        "  font-weight: bold;"
        "  font-size: 10pt;"
        "  padding: 6px 10px;"
        "  border: none;"
        "  border-bottom: 2px solid #CBD5E1;"
        "  border-right: 1px solid #E2E8F0;"
        "}"
    )
    _TABLE_STYLE = (
        "QTableWidget {"
        "  gridline-color: #E8ECF1;"
        "  border: 1px solid #D1D9E6;"
        "  border-radius: 6px;"
        "  selection-background-color: #DBEAFE;"
        "  selection-color: #1E3A5F;"
        "}"
        "QTableWidget::item {"
        "  padding: 4px 8px;"
        "}"
        "QTableWidget::item:alternate {"
        "  background: #F8FAFC;"
        "}"
    )

    def __init__(self, parent, building_lengths: List[Dict[str, Any]],
                 channel_total_length: float = 0.0,
                 type_summary: List[Dict[str, Any]] = None,
                 station_prefix: str = ""):
        super().__init__(parent)
        self.building_lengths = building_lengths or []
        self.channel_total_length = channel_total_length
        self._type_summary = type_summary
        self._station_prefix = station_prefix

        self.setWindowTitle("建筑物长度统计")
        self.setMinimumSize(500, 350)
        self._create_ui()
        self._load_data()
        self._auto_resize_dialog()

    def _setup_table(self, table: QTableWidget):
        """统一设置表格样式"""
        table.setFont(QFont(self._TABLE_FONT, self._TABLE_FONT_SIZE))
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(self._ROW_HEIGHT)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setShowGrid(True)
        table.setStyleSheet(self._TABLE_STYLE)
        table.horizontalHeader().setStyleSheet(self._HEADER_STYLE)
        table.horizontalHeader().setMinimumHeight(36)
        table.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        table.horizontalHeader().setStretchLastSection(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)

    def _create_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        # ---- QTabWidget：明细 / 汇总 两个Tab页 ----
        self.tab_widget = QTabWidget()
        self.tab_widget.setFont(QFont(self._TABLE_FONT, 10))
        self.tab_widget.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #D1D9E6; border-radius: 6px; "
            "  background: white; padding: 6px; }"
            "QTabBar::tab { padding: 8px 20px; font-size: 10pt; font-weight: bold; "
            "  border: 1px solid #D1D9E6; border-bottom: none; border-radius: 6px 6px 0 0; "
            "  margin-right: 2px; background: #F0F4FA; color: #4A5568; }"
            "QTabBar::tab:selected { background: white; color: #1A56DB; "
            "  border-bottom: 2px solid #1A56DB; }"
            "QTabBar::tab:hover:!selected { background: #E8ECF1; }"
        )

        # ---- Tab1：建筑物长度明细 ----
        tab_detail = QWidget()
        detail_lay = QVBoxLayout(tab_detail)
        detail_lay.setContentsMargins(6, 8, 6, 6)
        detail_lay.setSpacing(6)
        self.detail_table = QTableWidget()
        detail_headers = ["序号", "建筑物名称", "结构形式", "长度(m)", "起始桩号(m)", "终止桩号(m)", "备注"]
        self.detail_table.setColumnCount(len(detail_headers))
        self.detail_table.setHorizontalHeaderLabels(detail_headers)
        self._setup_table(self.detail_table)
        detail_lay.addWidget(self.detail_table, stretch=1)

        self.lbl_total = QLabel()
        self.lbl_total.setStyleSheet(
            "font-size: 10pt; color: #1E3A5F; font-weight: bold; padding: 4px 2px;"
        )
        detail_lay.addWidget(self.lbl_total)
        lbl_basis = QLabel("统计口径：按桩号差统计；渐变段单列；自动插入明渠计入对应类型")
        lbl_basis.setStyleSheet("color: #4A5568; font-size: 9pt; padding-left: 2px;")
        detail_lay.addWidget(lbl_basis)
        self.tab_widget.addTab(tab_detail, "建筑物长度明细")

        # ---- Tab2：按结构类型汇总 ----
        tab_summary = QWidget()
        summary_lay = QVBoxLayout(tab_summary)
        summary_lay.setContentsMargins(6, 8, 6, 6)
        summary_lay.setSpacing(6)
        self.summary_table = QTableWidget()
        summary_headers = ["序号", "结构类型", "数量", "累计长度(m)"]
        self.summary_table.setColumnCount(len(summary_headers))
        self.summary_table.setHorizontalHeaderLabels(summary_headers)
        self._setup_table(self.summary_table)
        summary_lay.addWidget(self.summary_table, stretch=1)
        self.tab_widget.addTab(tab_summary, "按结构类型汇总")

        lay.addWidget(self.tab_widget, stretch=1)

        # 按钮区
        btn_lay = QHBoxLayout()
        btn_lay.setContentsMargins(0, 4, 0, 0)
        btn_copy = PushButton("复制到剪贴板")
        btn_copy.clicked.connect(self._copy_to_clipboard)
        btn_format = PushButton("排版表预览(Excel)")
        btn_format.setToolTip(
            "将建筑物明细重新排版为左右对照表格（左侧为各建筑物进出口桩号及长度，\n"
            "右侧为各结构类型汇总长度），可直接复制粘贴到 Excel 中，\n"
            "用于填写渠道特性统计表和分段土石方汇总表。"
        )
        btn_format.clicked.connect(self._copy_formatted)
        btn_close = PushButton("关闭")
        btn_close.clicked.connect(self.accept)
        btn_lay.addWidget(btn_copy)
        btn_lay.addWidget(btn_format)
        btn_lay.addStretch()
        btn_lay.addWidget(btn_close)
        lay.addLayout(btn_lay)

    @staticmethod
    def _is_building_type(structure_type: str) -> bool:
        """判断结构类型是否为建筑物（渡槽/隧洞/倒虹吸）"""
        return any(kw in structure_type for kw in ('渡槽', '隧洞', '倒虹吸'))

    def _load_data(self):
        """加载明细和汇总数据到表格"""
        total_length = 0.0

        # 明细表
        self.detail_table.setRowCount(len(self.building_lengths))
        for i, item in enumerate(self.building_lengths):
            length = item.get('length', 0.0)
            total_length += length
            # 非建筑物类型（渡槽/隧洞/倒虹吸以外）名称显示为"-"
            name = item.get('name', '')
            st = item.get('structure_type', '')
            display_name = name if self._is_building_type(st) else '-'
            vals = [
                str(i + 1),
                display_name,
                st,
                f"{length:.3f}",
                f"{item.get('start_station', 0.0):.3f}",
                f"{item.get('end_station', 0.0):.3f}",
                item.get('note', ''),
            ]
            for c, v in enumerate(vals):
                cell = QTableWidgetItem(v)
                cell.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
                self.detail_table.setItem(i, c, cell)

        # 合计 + 校验
        count = len(self.building_lengths)
        diff = abs(total_length - self.channel_total_length)
        if self.channel_total_length > 0 and diff < 0.001:
            verify = f"  (桩号总长: {self.channel_total_length:.3f} m, 校验通过)"
        elif self.channel_total_length > 0:
            verify = f"  (桩号总长: {self.channel_total_length:.3f} m, 差值: {diff:.3f} m)"
        else:
            verify = ""
        self.lbl_total.setText(f"合计: {count} 个段落,  总长度: {total_length:.3f} m{verify}")

        # 汇总表
        if self._type_summary is None:
            self._type_summary = self._calc_type_summary()

        n = len(self._type_summary)
        self.summary_table.setRowCount(n + 1)  # 多一行合计
        total_count = 0
        total_len_sum = 0.0
        for i, item in enumerate(self._type_summary):
            cnt = item['count']
            tl = item['total_length']
            total_count += cnt
            total_len_sum += tl
            vals = [
                str(i + 1),
                item['structure_type'],
                str(cnt),
                f"{tl:.3f}",
            ]
            for c, v in enumerate(vals):
                cell = QTableWidgetItem(v)
                cell.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
                self.summary_table.setItem(i, c, cell)

        # 合计行
        sum_vals = ["", "合计", str(total_count), f"{total_len_sum:.3f}"]
        bold_font = QFont(self._TABLE_FONT, self._TABLE_FONT_SIZE)
        bold_font.setBold(True)
        for c, v in enumerate(sum_vals):
            cell = QTableWidgetItem(v)
            cell.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            cell.setFont(bold_font)
            self.summary_table.setItem(n, c, cell)

    def _auto_resize_dialog(self):
        """根据两个表格内容自动调整窗口大小"""
        # 先让表格根据内容调整列宽
        self.detail_table.resizeColumnsToContents()
        self.summary_table.resizeColumnsToContents()

        # 为每列增加适当内边距（左右各12px）
        for table in (self.detail_table, self.summary_table):
            header = table.horizontalHeader()
            for c in range(header.count()):
                cur_w = header.sectionSize(c)
                table.setColumnWidth(c, cur_w + 24)

        # 计算明细表所需宽度（含对话框边距24 + Tab内边距12 + 面板padding12 + 竖滚动条17 + 余量）
        extra = 80
        detail_w = sum(
            self.detail_table.columnWidth(c)
            for c in range(self.detail_table.columnCount())
        ) + extra

        # 计算汇总表所需宽度
        summary_w = sum(
            self.summary_table.columnWidth(c)
            for c in range(self.summary_table.columnCount())
        ) + extra

        # 取两个表格宽度的最大值作为窗口宽度
        content_w = max(detail_w, summary_w)

        # 计算明细表所需高度
        detail_rows = self.detail_table.rowCount()
        summary_rows = self.summary_table.rowCount()
        max_rows = max(detail_rows, summary_rows)
        table_h = 36 + max_rows * self._ROW_HEIGHT + 4  # 表头 + 数据行
        fixed_h = 130  # Tab栏 + 合计标签 + 按钮 + 边距
        content_h = table_h + fixed_h

        # 限制最大尺寸为屏幕的 85%/70%
        screen = self.screen()
        if screen:
            sg = screen.availableGeometry()
            max_w = int(sg.width() * 0.85)
            max_h = int(sg.height() * 0.70)
        else:
            max_w, max_h = 1400, 750

        win_w = min(max(content_w, 500), max_w)
        win_h = min(max(content_h, 350), max_h)
        self.resize(win_w, win_h)

        # 窗口大小确定后，启用最后一列拉伸填充多余空间
        self.detail_table.horizontalHeader().setStretchLastSection(True)
        self.summary_table.horizontalHeader().setStretchLastSection(True)

    def _calc_type_summary(self):
        """按结构类型汇总累计长度（用唯一名称计数，被分水闸拆分的同名隧洞只算1个）"""
        type_map = {}
        for item in self.building_lengths:
            st = item.get('structure_type', '')
            name = item.get('name', '')
            if not st or '连接' in name:
                continue
            length = item.get('length', 0.0)
            if st not in type_map:
                type_map[st] = {'names': set(), 'total_length': 0.0}
            type_map[st]['names'].add(name)
            type_map[st]['total_length'] += length
        return [
            {'structure_type': k, 'count': len(v['names']), 'total_length': v['total_length']}
            for k, v in sorted(type_map.items())
        ]

    def _copy_to_clipboard(self):
        """复制到剪贴板（制表符分隔，含明细和汇总）"""
        lines = ["【建筑物长度明细】"]
        lines.append("序号\t建筑物名称\t结构形式\t长度(m)\t起始桩号(m)\t终止桩号(m)\t备注")
        for i in range(self.detail_table.rowCount()):
            row = []
            for c in range(self.detail_table.columnCount()):
                item = self.detail_table.item(i, c)
                row.append(item.text() if item else "")
            lines.append("\t".join(row))
        total_length = sum(item.get('length', 0.0) for item in self.building_lengths)
        lines.append(f"合计\t{len(self.building_lengths)} 个段落\t\t{total_length:.3f}\t\t\t")
        lines.append("")
        lines.append("【按结构类型汇总】")
        lines.append("序号\t结构类型\t数量\t累计长度(m)")
        for i in range(self.summary_table.rowCount()):
            row = []
            for c in range(self.summary_table.columnCount()):
                item = self.summary_table.item(i, c)
                row.append(item.text() if item else "")
            lines.append("\t".join(row))

        clipboard = QApplication.clipboard()
        clipboard.setText("\n".join(lines))
        fluent_info(self, "提示", "已复制到剪贴板（含明细和汇总）")

    def _copy_formatted(self):
        """打开排版格式预览对话框"""
        type_summary = self._type_summary if self._type_summary is not None else self._calc_type_summary()
        try:
            dlg = FormattedLayoutDialog(
                self, self.building_lengths, type_summary,
                station_prefix=self._station_prefix
            )
            dlg.exec()
        except Exception as e:
            import traceback
            tb_str = traceback.format_exc()
            traceback.print_exc()
            fluent_error(self, "错误", f"打开排版格式预览失败：\n{tb_str}")

    @staticmethod
    def _format_station(value, prefix=""):
        """格式化桩号显示"""
        km = int(value // 1000)
        remainder = value - km * 1000
        s = f"{km}+{remainder:07.3f}"
        return f"{prefix}{s}" if prefix else s


# ============================================================
# 排版格式预览对话框
# ============================================================
class FormattedLayoutDialog(QDialog):
    """
    排版格式预览对话框（PySide6版）

    以表格形式展示可直接复制粘贴到 Excel 的工程排版格式，
    左侧为建筑物明细（名称、进出口桩号、长度），
    右侧为各结构类型汇总长度。
    """

    def __init__(self, parent, building_lengths: List[Dict[str, Any]],
                 type_summary: List[Dict[str, Any]],
                 station_prefix: str = ""):
        super().__init__(parent)
        self._building_lengths = building_lengths or []
        self._type_summary = type_summary or []
        self._station_prefix = station_prefix

        self.setWindowTitle("排版格式预览")
        self.setMinimumSize(700, 400)

        # 预先生成数据（供 UI 和复制共用）
        self._headers, self._table_data = self._build_table_data()

        self._create_ui()
        self._auto_resize()

    def _build_table_data(self):
        """
        构建表格数据（表头 + 二维数据）

        布局：左侧4列为建筑物明细，右侧2列为结构类型汇总。
        分水闸/分水口不参与统计，从明细和汇总中均排除。
        """
        prefix = self._station_prefix

        # 过滤明细数据：排除分水闸/分水口和渐变段
        detail_items = [
            item for item in self._building_lengths
            if '分水' not in item.get('structure_type', '')
            and item.get('structure_type', '') != '渐变段'
        ]

        # 构建右侧汇总行：排除分水闸/分水口，含末行"总长度"
        summary_rows = []
        for item in self._type_summary:
            if '分水' in item.get('structure_type', ''):
                continue
            summary_rows.append({
                'label': item['structure_type'],
                'length': item['total_length'],
            })
        # 添加"总长度"汇总行
        total_all = sum(item.get('total_length', 0.0) for item in self._type_summary)
        summary_rows.append({
            'label': '总长度',
            'length': total_all,
        })

        headers = ["建筑物名称", "进口桩号", "出口桩号", "长度", "各建筑物总长度", "长度（m）"]

        # 确定总行数（左右取最大值）
        detail_count = len(detail_items)
        summary_count = len(summary_rows)
        max_rows = max(detail_count, summary_count)

        data = []
        for i in range(max_rows):
            # 左侧：建筑物明细
            if i < detail_count:
                item = detail_items[i]
                raw_name = item.get('name', '')
                struct_type = item.get('structure_type', '')
                if '连接' in raw_name:
                    name = struct_type or raw_name
                else:
                    name = f"{raw_name}{struct_type}" if struct_type else raw_name
                start_station = self._format_station(
                    item.get('start_station', 0.0), prefix)
                end_station = self._format_station(
                    item.get('end_station', 0.0), prefix)
                length = f"{item.get('length', 0.0):.3f}"
            else:
                name = ""
                start_station = ""
                end_station = ""
                length = ""

            # 右侧：结构类型汇总
            if i < summary_count:
                s = summary_rows[i]
                s_label = s['label']
                s_length = f"{s['length']:.3f}"
            else:
                s_label = ""
                s_length = ""

            data.append([name, start_station, end_station, length, s_label, s_length])

        return headers, data

    def _create_ui(self):
        """创建预览界面"""
        lay = QVBoxLayout(self)
        lay.setSpacing(6)

        # 说明标签
        hint_label = QLabel(
            "以下内容为制表符分隔格式，可直接复制粘贴到 Excel 中使用。\n"
            "用于渠道特性统计表和分段土石方汇总表。"
        )
        hint_label.setWordWrap(True)
        hint_label.setStyleSheet("color: black; font-size: 13px;")
        lay.addWidget(hint_label)

        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(len(self._headers))
        self.table.setHorizontalHeaderLabels(self._headers)
        self.table.setRowCount(len(self._table_data))
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.setSelectionMode(QAbstractItemView.ContiguousSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setFont(QFont("Microsoft YaHei", 10))
        self.table.verticalHeader().setDefaultSectionSize(28)

        # 右侧汇总列浅蓝底色
        summary_bg = QColor("#EDF4FC")
        total_bg = QColor("#D6E8F7")

        # 计算"总长度"行索引
        summary_count = len([
            item for item in self._type_summary
            if '分水' not in item.get('structure_type', '')
        ]) + 1  # +1 for "总长度" row
        total_row_idx = summary_count - 1

        for r, row_data in enumerate(self._table_data):
            for c, val in enumerate(row_data):
                cell = QTableWidgetItem(str(val))
                # 数值列居中
                if c in (2, 3, 5):
                    cell.setTextAlignment(Qt.AlignCenter)
                elif c == 1:
                    cell.setTextAlignment(Qt.AlignCenter)
                else:
                    cell.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)

                # 右侧汇总列设置背景色
                if c >= 4:
                    if r == total_row_idx:
                        cell.setBackground(total_bg)
                    else:
                        cell.setBackground(summary_bg)

                self.table.setItem(r, c, cell)

        lay.addWidget(self.table, stretch=1)

        # 按钮区
        btn_lay = QHBoxLayout()
        btn_copy = PushButton("复制到剪贴板")
        btn_copy.clicked.connect(self._copy_to_clipboard)
        btn_close = PushButton("关闭")
        btn_close.clicked.connect(self.accept)
        btn_lay.addWidget(btn_copy)
        btn_lay.addStretch()
        btn_lay.addWidget(btn_close)
        lay.addLayout(btn_lay)

    def _auto_resize(self):
        """根据内容自动调整列宽和窗口大小"""
        auto_resize_table(self.table)

        # 计算所需宽度
        total_w = 0
        for c in range(self.table.columnCount()):
            total_w += self.table.columnWidth(c)
        # 加上行号列、滚动条和边距
        total_w += self.table.verticalHeader().width() + 50

        # 计算所需高度
        row_count = self.table.rowCount()
        row_h = self.table.verticalHeader().defaultSectionSize()
        header_h = self.table.horizontalHeader().height()
        table_h = header_h + row_count * row_h + 4
        fixed_h = 120  # 说明标签 + 按钮 + 边距
        total_h = table_h + fixed_h

        # 限制最大尺寸为屏幕的 85%
        screen = self.screen()
        if screen:
            sg = screen.availableGeometry()
            max_w = int(sg.width() * 0.85)
            max_h = int(sg.height() * 0.65)
        else:
            max_w, max_h = 1400, 700

        win_w = min(max(total_w, 700), max_w)
        win_h = min(max(total_h, 400), max_h)
        self.resize(win_w, win_h)

    def _generate_tsv_text(self) -> str:
        """从表头和数据生成制表符分隔文本"""
        lines = ["\t".join(self._headers)]
        for row in self._table_data:
            lines.append("\t".join(str(cell) for cell in row))
        return "\n".join(lines)

    def _copy_to_clipboard(self):
        """将排版文本复制到剪贴板（制表符分隔格式）"""
        text = self._generate_tsv_text()
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        fluent_info(self, "提示", "排版格式已复制到剪贴板，可直接粘贴到 Excel")

    @staticmethod
    def _format_station(value, prefix=""):
        """格式化桩号显示"""
        km = int(value // 1000)
        remainder = value - km * 1000
        s = f"{km}+{remainder:07.3f}"
        return f"{prefix}{s}" if prefix else s


# ============================================================
# 批量明渠段插入确认对话框
# ============================================================
class BatchChannelConfirmDialog(QDialog):
    """
    批量明渠段插入确认对话框（PySide6版）

    展示所有需要插入明渠段的位置，提供表格编辑和逐一确认两种模式。
    """

    RESULT_TABLE_EDIT = "table_edit"
    RESULT_MANUAL_EACH = "manual_each"
    RESULT_CANCELLED = "cancelled"

    STRUCTURE_TYPES = ["明渠-梯形", "明渠-矩形", "明渠-圆形"]

    def __init__(self, parent, total_count: int, gaps_info: list):
        super().__init__(parent)
        self.total_count = total_count
        self.gaps_info = gaps_info
        self.result = {'mode': self.RESULT_MANUAL_EACH, 'params': {}}
        self._row_widgets = []

        self.setWindowTitle("批量插入明渠段")
        self.resize(1100, 580)
        self.setMinimumSize(900, 400)
        self._create_ui()
        self._fill_all_recommended()

    def _create_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(6)

        # 标题 & 统计
        has_upstream = sum(1 for g in self.gaps_info if g.get('has_upstream'))
        no_upstream = self.total_count - has_upstream

        lbl_title = QLabel(f"系统检测到 <b>{self.total_count}</b> 处需要插入明渠段")
        lay.addWidget(lbl_title)

        if has_upstream == self.total_count:
            lbl_sub = QLabel(f"全部 {self.total_count} 处均可复制上游明渠参数")
            lbl_sub.setStyleSheet("color: green;")
        else:
            lbl_sub = QLabel(f"其中 {has_upstream} 处可复制上游参数，{no_upstream} 处需手动输入")
            lbl_sub.setStyleSheet("color: #CC6600;")
        lay.addWidget(lbl_sub)

        # 原理说明
        tip_grp = QGroupBox("为什么需要插入明渠段？")
        tip_lay = QVBoxLayout(tip_grp)
        tip_text = (
            "渠系中各建筑物之间往往存在无建筑物覆盖的空余渠段。"
            "系统通过比较相邻建筑物间的里程差与渐变段长度之和，自动检测出这些空隙位置。\n"
            "为保证水面线推算的连续性，需要在空隙处补充明渠段。"
            "推荐直接复制上游已有明渠的断面参数，也可手动修改。"
        )
        lbl_tip = QLabel(tip_text)
        lbl_tip.setWordWrap(True)
        lbl_tip.setStyleSheet("color: #0055AA;")
        tip_lay.addWidget(lbl_tip)
        lay.addWidget(tip_grp)

        # 模式选择
        mode_lay = QHBoxLayout()
        self.mode_group = QButtonGroup(self)
        self.rb_table = QRadioButton("在下方表格中统一编辑（推荐）")
        self.rb_manual = QRadioButton("逐一弹窗确认")
        self.rb_table.setChecked(True)
        self.mode_group.addButton(self.rb_table)
        self.mode_group.addButton(self.rb_manual)
        self.rb_table.toggled.connect(self._on_mode_change)
        mode_lay.addWidget(self.rb_table)
        mode_lay.addWidget(self.rb_manual)
        mode_lay.addStretch()
        lay.addLayout(mode_lay)

        # 工具栏
        tb = QHBoxLayout()
        self._fill_btn = PushButton("全部填充推荐参数")
        self._fill_btn.clicked.connect(self._fill_all_recommended)
        self._clear_btn = PushButton("全部清空")
        self._clear_btn.clicked.connect(self._clear_all)
        tb.addWidget(self._fill_btn)
        tb.addWidget(self._clear_btn)
        tb.addStretch()
        lay.addLayout(tb)

        # 参数表格
        self.param_table = QTableWidget(self.total_count, 10)
        headers = ["#", "上游", "下游", "可用长度(m)", "结构形式", "B(m)", "m", "n", "底坡1/i", "Q(m³/s)"]
        self.param_table.setHorizontalHeaderLabels(headers)
        self.param_table.horizontalHeader().setStretchLastSection(False)
        self.param_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.param_table.setFont(QFont("Microsoft YaHei", 10))
        self.param_table.verticalHeader().setVisible(False)
        self.param_table.setAlternatingRowColors(True)

        self._row_widgets = []
        for idx, gap in enumerate(self.gaps_info):
            # # 列
            item_idx = QTableWidgetItem(str(idx + 1))
            item_idx.setFlags(item_idx.flags() & ~Qt.ItemIsEditable)
            item_idx.setTextAlignment(Qt.AlignCenter)
            self.param_table.setItem(idx, 0, item_idx)

            # 上游列：名称(结构形式)
            prev_name = gap.get('prev_name', '')
            prev_struct = gap.get('prev_struct', '')
            prev_text = f"{prev_name}({prev_struct})" if prev_name else prev_struct
            item_prev = QTableWidgetItem(prev_text)
            item_prev.setFlags(item_prev.flags() & ~Qt.ItemIsEditable)
            item_prev.setToolTip(prev_text)
            self.param_table.setItem(idx, 1, item_prev)

            # 下游列：名称(结构形式)
            next_name = gap.get('next_name', '')
            next_struct = gap.get('next_struct', '')
            next_text = f"{next_name}({next_struct})" if next_name else next_struct
            item_next = QTableWidgetItem(next_text)
            item_next.setFlags(item_next.flags() & ~Qt.ItemIsEditable)
            item_next.setToolTip(next_text)
            self.param_table.setItem(idx, 2, item_next)

            # 可用长度列
            item_len = QTableWidgetItem(f"{gap['available_length']:.1f}")
            item_len.setFlags(item_len.flags() & ~Qt.ItemIsEditable)
            item_len.setTextAlignment(Qt.AlignCenter)
            self.param_table.setItem(idx, 3, item_len)

            # 结构形式 ComboBox
            type_cb = QComboBox()
            type_cb.addItems(self.STRUCTURE_TYPES)
            type_cb.setCurrentIndex(0)
            self.param_table.setCellWidget(idx, 4, type_cb)

            # B, m, n, 底坡, Q 输入框
            row_widgets = {'gap': gap, 'type_combo': type_cb, 'entries': {}}
            for c, key in [(5, 'B'), (6, 'm'), (7, 'n'), (8, 'slope'), (9, 'Q')]:
                default_val = ""
                if key == 'n':
                    default_val = "0.014"
                elif key == 'slope':
                    default_val = "3000"
                elif key == 'Q':
                    default_val = f"{gap['flow']:.3f}"
                item = QTableWidgetItem(default_val)
                item.setTextAlignment(Qt.AlignCenter)
                self.param_table.setItem(idx, c, item)
                row_widgets['entries'][key] = (idx, c)

            self._row_widgets.append(row_widgets)

        lay.addWidget(self.param_table, stretch=1)

        # 底部按钮
        btn_lay = QHBoxLayout()
        btn_lay.addStretch()
        btn_ok = PrimaryPushButton("确定")
        btn_ok.clicked.connect(self._on_ok)
        btn_ok.setFixedWidth(100)
        btn_ok.setDefault(True)
        btn_ok.setFocus()
        btn_lay.addWidget(btn_ok)
        lay.addLayout(btn_lay)

    def _set_cell(self, row, col, val):
        """设置表格单元格值"""
        item = self.param_table.item(row, col)
        if item is None:
            item = QTableWidgetItem(str(val))
            item.setTextAlignment(Qt.AlignCenter)
            self.param_table.setItem(row, col, item)
        else:
            item.setText(str(val))

    def _fill_recommended(self, row_idx):
        """用上游参数填充一行"""
        row = self._row_widgets[row_idx]
        up = row['gap'].get('upstream_channel')
        if not up:
            return
        st = up.get('structure_type', '明渠-梯形')
        idx_in_combo = self.STRUCTURE_TYPES.index(st) if st in self.STRUCTURE_TYPES else 0
        row['type_combo'].setCurrentIndex(idx_in_combo)

        entries = row['entries']
        self._set_cell(entries['B'][0], entries['B'][1], f"{up.get('bottom_width', 0):.2f}")
        self._set_cell(entries['m'][0], entries['m'][1], f"{up.get('side_slope', 0)}")
        self._set_cell(entries['n'][0], entries['n'][1], f"{up.get('roughness', 0.014)}")
        self._set_cell(entries['slope'][0], entries['slope'][1], f"{up.get('slope_inv', 3000):.0f}")
        self._set_cell(entries['Q'][0], entries['Q'][1], f"{row['gap']['flow']:.3f}")

    def _fill_all_recommended(self):
        for i, row in enumerate(self._row_widgets):
            if row['gap'].get('has_upstream'):
                self._fill_recommended(i)

    def _clear_all(self):
        for row in self._row_widgets:
            row['type_combo'].setCurrentIndex(0)
            entries = row['entries']
            self._set_cell(entries['B'][0], entries['B'][1], "")
            self._set_cell(entries['m'][0], entries['m'][1], "")
            self._set_cell(entries['n'][0], entries['n'][1], "0.014")
            self._set_cell(entries['slope'][0], entries['slope'][1], "3000")
            self._set_cell(entries['Q'][0], entries['Q'][1], f"{row['gap']['flow']:.3f}")

    def _on_mode_change(self):
        enabled = self.rb_table.isChecked()
        self._fill_btn.setEnabled(enabled)
        self._clear_btn.setEnabled(enabled)
        # 禁用/启用表格编辑
        for r in range(self.param_table.rowCount()):
            for c in range(5, 10):
                item = self.param_table.item(r, c)
                if item:
                    if enabled:
                        item.setFlags(item.flags() | Qt.ItemIsEditable)
                    else:
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)

    def _get_cell_val(self, row, col, default=0.0):
        item = self.param_table.item(row, col)
        if item is None:
            return default
        text = item.text().strip()
        if not text:
            return default
        try:
            return float(text)
        except ValueError:
            return default

    def _validate_and_collect(self):
        """验证表格并收集参数"""
        params = {}
        for idx, row in enumerate(self._row_widgets):
            entries = row['entries']
            try:
                st = row['type_combo'].currentText()
                B = self._get_cell_val(entries['B'][0], entries['B'][1])
                m = self._get_cell_val(entries['m'][0], entries['m'][1]) if st == "明渠-梯形" else 0
                n = self._get_cell_val(entries['n'][0], entries['n'][1], 0.014)
                si = self._get_cell_val(entries['slope'][0], entries['slope'][1], 3000)
                Q = self._get_cell_val(entries['Q'][0], entries['Q'][1])
                slope_i = 1.0 / si if si > 0 else 0

                if Q <= 0:
                    fluent_info(self, "输入错误", f"第 {idx+1} 处: 流量 Q 必须大于 0")
                    return None
                if B <= 0 and st != "明渠-圆形":
                    fluent_info(self, "输入错误", f"第 {idx+1} 处: 底宽 B 必须大于 0")
                    return None
                if n <= 0:
                    fluent_info(self, "输入错误", f"第 {idx+1} 处: 糙率 n 必须大于 0")
                    return None

                D_param = B if st == "明渠-圆形" else 0.0
                B_param = 0.0 if st == "明渠-圆形" else B
                h = calculate_normal_depth(Q, B_param, m, n, slope_i, D=D_param)
                if h <= 0:
                    up = row['gap'].get('upstream_channel')
                    if up and up.get('water_depth', 0) > 0:
                        h = up['water_depth']
                    else:
                        fluent_info(self, "计算错误",
                                    f"第 {idx+1} 处: 无法计算有效水深，请检查参数")
                        return None

                # 从上游渠道继承结构高度（用于计算渠顶高程）
                up = row['gap'].get('upstream_channel') or {}
                sh = up.get('structure_height', 0.0)
                params[idx] = OpenChannelParams(
                    name="-", structure_type=st,
                    bottom_width=B, water_depth=h, side_slope=m,
                    roughness=n, slope_inv=si, flow=Q,
                    flow_section=row['gap'].get('flow_section', ''),
                    structure_height=sh,
                )
            except ValueError:
                fluent_info(self, "输入错误", f"第 {idx+1} 处: 请输入有效数值")
                return None
        return params

    def _on_ok(self):
        if self.rb_table.isChecked():
            params = self._validate_and_collect()
            if params is None:
                return
            self.result = {'mode': self.RESULT_TABLE_EDIT, 'params': params}
        else:
            self.result = {'mode': self.RESULT_MANUAL_EACH, 'params': {}}
        self.accept()

    def closeEvent(self, event):
        if fluent_question(self, "确认取消",
                "关闭后将跳过明渠段插入，渠段之间可能出现空隙。\n确定要取消吗？"):
            self.result = {'mode': self.RESULT_CANCELLED, 'params': {}}
            event.accept()
        else:
            event.ignore()

    def get_result(self):
        return self.result


# ============================================================
# 明渠段参数选择对话框（逐一弹窗模式）
# ============================================================
class OpenChannelDialog(QDialog):
    """
    明渠段参数选择对话框（PySide6版）

    用于在建筑物之间插入明渠段时，让用户选择参数来源。
    """

    STRUCTURE_TYPES = ["明渠-梯形", "明渠-矩形", "明渠-圆形"]

    def __init__(self, parent,
                 upstream_channel: Optional[Dict] = None,
                 available_length: float = 0.0,
                 prev_structure: str = "",
                 next_structure: str = "",
                 flow_section: str = "",
                 flow: float = 0.0,
                 current_index: int = 1,
                 total_count: int = 1):
        super().__init__(parent)
        self.upstream_channel = upstream_channel
        self.available_length = available_length
        self.prev_structure = prev_structure
        self.next_structure = next_structure
        self.flow_section = flow_section
        self.flow = flow
        self.current_index = current_index
        self.total_count = total_count

        self._result: Optional[OpenChannelParams] = None
        self.apply_all_remaining = False

        if total_count > 1:
            self.setWindowTitle(f"插入明渠段 ({current_index}/{total_count})")
        else:
            self.setWindowTitle("插入明渠段")
        self.resize(520, 560)
        self.setMinimumSize(420, 440)
        self._create_ui()

    def _create_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        # 位置信息
        loc_grp = QGroupBox("插入位置")
        loc_lay = QVBoxLayout(loc_grp)
        loc_lay.addWidget(QLabel(f"前方建筑物: {self.prev_structure}"))
        loc_lay.addWidget(QLabel(f"后方建筑物: {self.next_structure}"))
        loc_lay.addWidget(QLabel(f"可用长度: {self.available_length:.1f} m    流量段: {self.flow_section}    流量: {self.flow:.3f} m³/s"))
        lay.addWidget(loc_grp)

        # 参数来源
        src_grp = QGroupBox("参数来源")
        src_lay = QVBoxLayout(src_grp)
        self.src_group = QButtonGroup(self)
        self.rb_copy = QRadioButton("复制上游明渠参数（推荐）")
        self.rb_manual = QRadioButton("手动输入参数")
        self.src_group.addButton(self.rb_copy)
        self.src_group.addButton(self.rb_manual)
        src_lay.addWidget(self.rb_copy)

        if self.upstream_channel:
            self.rb_copy.setChecked(True)
            up = self.upstream_channel
            info = f"  → {up.get('structure_type', '')}  B={up.get('bottom_width', 0):.2f}m  m={up.get('side_slope', 0)}  n={up.get('roughness', 0.014)}  底坡1/{up.get('slope_inv', 3000):.0f}"
            lbl_info = QLabel(info)
            lbl_info.setStyleSheet("color: green; margin-left: 20px;")
            src_lay.addWidget(lbl_info)
        else:
            self.rb_copy.setEnabled(False)
            self.rb_manual.setChecked(True)

        src_lay.addWidget(self.rb_manual)
        lay.addWidget(src_grp)

        # 参数编辑区
        param_grp = QGroupBox("明渠段参数")
        pg = QGridLayout(param_grp)
        pg.setVerticalSpacing(10)
        pg.setHorizontalSpacing(12)
        pg.setContentsMargins(12, 16, 12, 12)

        _row_h = 32
        pg.addWidget(QLabel("结构形式:"), 0, 0)
        self.type_combo = QComboBox()
        self.type_combo.setMinimumHeight(_row_h)
        self.type_combo.addItems(self.STRUCTURE_TYPES)
        pg.addWidget(self.type_combo, 0, 1)

        pg.addWidget(QLabel("底宽 B(m):"), 1, 0)
        self.edit_B = QLineEdit()
        self.edit_B.setMinimumHeight(_row_h)
        pg.addWidget(self.edit_B, 1, 1)

        pg.addWidget(QLabel("边坡 m:"), 2, 0)
        self.edit_m = QLineEdit()
        self.edit_m.setMinimumHeight(_row_h)
        pg.addWidget(self.edit_m, 2, 1)

        pg.addWidget(QLabel("糙率 n:"), 3, 0)
        self.edit_n = QLineEdit()
        self.edit_n.setMinimumHeight(_row_h)
        self.edit_n.setText("0.014")
        pg.addWidget(self.edit_n, 3, 1)

        pg.addWidget(QLabel("底坡 1/i:"), 4, 0)
        self.edit_slope = QLineEdit()
        self.edit_slope.setMinimumHeight(_row_h)
        self.edit_slope.setText("3000")
        pg.addWidget(self.edit_slope, 4, 1)

        pg.addWidget(QLabel("流量 Q(m³/s):"), 5, 0)
        self.edit_Q = QLineEdit()
        self.edit_Q.setMinimumHeight(_row_h)
        self.edit_Q.setText(f"{self.flow:.3f}")
        pg.addWidget(self.edit_Q, 5, 1)

        lay.addWidget(param_grp)

        # 按钮区
        btn_lay = QHBoxLayout()
        if self.total_count > 1 and self.current_index < self.total_count:
            btn_all = PushButton("剩余全部用推荐")
            btn_all.clicked.connect(self._on_apply_all)
            btn_lay.addWidget(btn_all)
        btn_lay.addStretch()
        btn_skip = PushButton("跳过")
        btn_skip.clicked.connect(self.reject)
        btn_ok = PrimaryPushButton("确定")
        btn_ok.clicked.connect(self._on_ok)
        btn_lay.addWidget(btn_skip)
        btn_lay.addWidget(btn_ok)
        lay.addLayout(btn_lay)

        # 收集可编辑控件，用于禁用/启用切换
        self._param_widgets = [self.type_combo, self.edit_B, self.edit_m,
                               self.edit_n, self.edit_slope, self.edit_Q]

        # 如果有上游参数，默认填充
        if self.upstream_channel:
            self._fill_from_upstream()
        self._on_source_change()  # 初始化启用/禁用状态
        self.rb_copy.toggled.connect(self._on_source_change)

    def _fill_from_upstream(self):
        """用上游参数填充"""
        up = self.upstream_channel
        if not up:
            return
        st = up.get('structure_type', '明渠-梯形')
        idx = self.STRUCTURE_TYPES.index(st) if st in self.STRUCTURE_TYPES else 0
        self.type_combo.setCurrentIndex(idx)
        self.edit_B.setText(f"{up.get('bottom_width', 0):.2f}")
        self.edit_m.setText(f"{up.get('side_slope', 0)}")
        self.edit_n.setText(f"{up.get('roughness', 0.014)}")
        self.edit_slope.setText(f"{up.get('slope_inv', 3000):.0f}")

    def _on_source_change(self, checked=None):
        is_manual = self.rb_manual.isChecked()
        for w in self._param_widgets:
            w.setEnabled(is_manual)
        if not is_manual and self.upstream_channel:
            self._fill_from_upstream()

    def _on_apply_all(self):
        """剩余全部用推荐"""
        self.apply_all_remaining = True
        if self.upstream_channel:
            self._fill_from_upstream()
        self._on_ok()

    def _on_ok(self):
        try:
            st = self.type_combo.currentText()
            B = float(self.edit_B.text() or 0)
            m = float(self.edit_m.text() or 0) if st == "明渠-梯形" else 0
            n = float(self.edit_n.text() or 0.014)
            si = float(self.edit_slope.text() or 3000)
            Q = float(self.edit_Q.text() or 0)
            slope_i = 1.0 / si if si > 0 else 0

            if Q <= 0:
                fluent_info(self, "输入错误", "流量 Q 必须大于 0")
                return
            if B <= 0 and st != "明渠-圆形":
                fluent_info(self, "输入错误", "底宽 B 必须大于 0")
                return

            D_param = B if st == "明渠-圆形" else 0.0
            B_param = 0.0 if st == "明渠-圆形" else B
            h = calculate_normal_depth(Q, B_param, m, n, slope_i, D=D_param)
            if h <= 0 and self.upstream_channel:
                h = self.upstream_channel.get('water_depth', 0)
            if h <= 0:
                fluent_info(self, "计算错误", "无法计算有效水深，请检查参数")
                return

            # 从上游渠道继承结构高度（用于计算渠顶高程）
            sh = self.upstream_channel.get('structure_height', 0.0) if self.upstream_channel else 0.0
            self._result = OpenChannelParams(
                name="-", structure_type=st,
                bottom_width=B, water_depth=h, side_slope=m,
                roughness=n, slope_inv=si, flow=Q,
                flow_section=self.flow_section,
                structure_height=sh,
            )
            self.accept()
        except ValueError:
            fluent_info(self, "输入错误", "请输入有效数值")

    def get_result(self):
        return self._result


# ============================================================
# 转弯半径自动计算详情对话框
# ============================================================
class TurnRadiusCalcDialog(QDialog):
    """展示转弯半径自动计算的详细过程：表格 + 规范依据 + 结论"""

    def __init__(self, parent=None, rec_r=0.0, max_r=0.0,
                 details=None, controlling_name=""):
        """
        Parameters
        ----------
        rec_r : float  - 推荐值（向上取整后）
        max_r : float  - 计算最大值（未取整）
        details : list  - [(name, stype, dim_str, basis, r_val), ...]
        controlling_name : str - 控制节点名称
        """
        super().__init__(parent)
        self.setWindowTitle("转弯半径自动计算")
        self.setMinimumWidth(620)
        self.setMinimumHeight(380)
        self.setStyleSheet("QDialog { background: #FAFBFC; }")

        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(20, 16, 20, 16)

        # ---- 顶部结论区 ----
        top = QHBoxLayout()
        top.setSpacing(12)

        icon_lbl = QLabel("📐")
        icon_lbl.setStyleSheet("font-size: 32px;")
        icon_lbl.setFixedSize(48, 48)
        icon_lbl.setAlignment(Qt.AlignCenter)
        top.addWidget(icon_lbl)

        result_box = QVBoxLayout()
        result_box.setSpacing(2)
        val_lbl = QLabel(f"{rec_r:.1f} m")
        val_lbl.setStyleSheet(
            "font-size: 28px; font-weight: bold; color: #1976D2;"
        )
        result_box.addWidget(val_lbl)
        sub_lbl = QLabel("推荐转弯半径（向上取整）")
        sub_lbl.setStyleSheet("font-size: 12px; color: #424242;")
        result_box.addWidget(sub_lbl)
        top.addLayout(result_box)
        top.addStretch()

        if controlling_name and details:
            ctrl_lbl = QLabel(f"控制节点：{controlling_name}")
            ctrl_lbl.setStyleSheet(
                "font-size: 12px; color: #E65100; font-weight: bold;"
                "background: #FFF3E0; border-radius: 4px; padding: 4px 10px;"
            )
            top.addWidget(ctrl_lbl)

        lay.addLayout(top)

        # ---- 分隔线 ----
        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #E0E0E0;")
        lay.addWidget(sep)

        # ---- 中间表格区 ----
        if details:
            tbl_label = QLabel(f"逐节点计算明细（共 {len(details)} 个有效节点）")
            tbl_label.setStyleSheet(
                "font-size: 13px; font-weight: bold; color: #424242;"
            )
            lay.addWidget(tbl_label)

            headers = ["序号", "节点名称", "结构类型", "关键尺寸", "规范公式", "Rmin (m)"]
            tbl = QTableWidget(len(details), len(headers))
            tbl.setHorizontalHeaderLabels(headers)
            tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
            tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
            tbl.setAlternatingRowColors(True)
            tbl.verticalHeader().setVisible(False)
            tbl.setStyleSheet("""
                QTableWidget {
                    border: 1px solid #E0E0E0; border-radius: 4px;
                    background: white; alternate-background-color: #F5F7FA;
                    font-size: 12px; gridline-color: #EEEEEE;
                }
                QTableWidget::item { padding: 4px 6px; }
                QTableWidget::item:selected { background: #E3F2FD; color: #1565C0; }
                QHeaderView::section {
                    background: #ECEFF1; color: #37474F; font-weight: bold;
                    font-size: 12px; padding: 6px 4px;
                    border: none; border-bottom: 2px solid #B0BEC5;
                }
            """)

            HIGHLIGHT_BG = QColor("#FFF8E1")
            HIGHLIGHT_FG = QColor("#E65100")
            STAR = " ★"

            for row, (name, stype, dim, basis_str, r_val) in enumerate(details):
                is_ctrl = (name == controlling_name)
                items_data = [
                    str(row + 1),
                    (name + STAR) if is_ctrl else name,
                    stype,
                    dim,
                    basis_str,
                    f"{r_val:.1f}",
                ]
                for col, text in enumerate(items_data):
                    item = QTableWidgetItem(text)
                    item.setTextAlignment(Qt.AlignCenter if col in (0, 5) else Qt.AlignLeft | Qt.AlignVCenter)
                    if is_ctrl:
                        item.setBackground(HIGHLIGHT_BG)
                        item.setForeground(HIGHLIGHT_FG)
                        f = item.font()
                        f.setBold(True)
                        item.setFont(f)
                    tbl.setItem(row, col, item)

            h_header = tbl.horizontalHeader()
            h_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
            h_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
            h_header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
            h_header.setSectionResizeMode(3, QHeaderView.Stretch)
            h_header.setSectionResizeMode(4, QHeaderView.Stretch)
            h_header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
            tbl.setMaximumHeight(min(36 * len(details) + 36, 260))
            lay.addWidget(tbl, 1)
        else:
            no_data = QLabel("未找到有效建筑物节点，使用默认转弯半径。")
            no_data.setStyleSheet("font-size: 13px; color: #424242; padding: 20px;")
            no_data.setAlignment(Qt.AlignCenter)
            lay.addWidget(no_data)

        # ---- 底部规范依据 ----
        ref_grp = QGroupBox("规范依据")
        ref_grp.setStyleSheet("""
            QGroupBox {
                font-size: 12px; font-weight: bold; color: #1976D2;
                border: 1px solid #E0E0E0; border-radius: 6px;
                margin-top: 10px; padding: 12px 10px 8px 10px;
                background: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 12px;
                padding: 0 6px; background: white;
            }
        """)
        ref_lay = QVBoxLayout(ref_grp)
        ref_lay.setSpacing(4)
        ref_items = [
            ("隧洞", "弯曲半径 ≥ 洞径(或洞宽) × 5"),
            ("明渠", "弯曲半径 ≥ 水面宽度 × 5"),
            ("渡槽", "弯道半径 ≥ 连接明渠渠底宽度 × 5"),
            ("暗涵", "弯曲半径 ≥ 涵宽 × 5"),
        ]
        for cat, rule in ref_items:
            rl = QLabel(f"  •  {cat}：{rule}")
            rl.setStyleSheet("font-size: 13px; color: #616161; font-weight: normal;")
            ref_lay.addWidget(rl)
        note = QLabel("取所有建筑物中的最大值，向上取整，作为统一转弯半径。")
        note.setStyleSheet(
            "font-size: 13px; color: #1976D2; font-weight: normal; margin-top: 4px;"
        )
        ref_lay.addWidget(note)
        src = QLabel("——《灌溉与排水工程设计标准》(GB 50288)")
        src.setStyleSheet("font-size: 11px; color: #555555; font-weight: normal;")
        src.setAlignment(Qt.AlignRight)
        ref_lay.addWidget(src)
        lay.addWidget(ref_grp)

        # ---- 底部按钮 ----
        btn_lay = QHBoxLayout()
        btn_lay.addStretch()
        btn_ok = PrimaryPushButton("确定")
        btn_ok.setFixedWidth(90)
        btn_ok.clicked.connect(self.accept)
        btn_lay.addWidget(btn_ok)
        lay.addLayout(btn_lay)
