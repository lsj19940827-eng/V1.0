# -*- coding: utf-8 -*-
"""
水面线面板 CAD 工具集

移植自原版 TK 的工程辅助功能，包括：
1. 生成纵断面表格（AutoCAD pl + -text 命令）
2. 生成bzzh2命令内容（ZDM用）
3. 建筑物名称上平面图（AutoCAD -TEXT 命令）
4. IP坐标及弯道参数表导出Excel
5. 断面汇总表
"""

import os
import sys
import math

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QGroupBox, QTextEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QFileDialog, QApplication, QScrollArea, QWidget, QComboBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QShortcut, QKeySequence

from qfluentwidgets import PushButton, PrimaryPushButton, LineEdit

from 渠系断面设计.styles import (
    auto_resize_table, DIALOG_STYLE,
    fluent_info, fluent_error, fluent_question,
)

# 确保推求水面线模块可用
_pkg_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_water_profile_dir = os.path.join(_pkg_root, '推求水面线')
if _water_profile_dir not in sys.path:
    sys.path.insert(0, _water_profile_dir)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

try:
    from models.data_models import ProjectSettings
    from models.enums import StructureType, InOutType
    MODELS_AVAILABLE = True
except ImportError:
    MODELS_AVAILABLE = False


# ================================================================
# 辅助工具函数
# ================================================================

def _format_number(value):
    """格式化数值：保留完整精度，去除无意义的尾零"""
    return f"{value:.15g}"


def _get_building_display_name(node):
    """获取纵断面用的建筑物名称显示"""
    struct_str = node.get_structure_type_str() or ""
    if node.is_transition or struct_str == "渐变段":
        return ""
    if struct_str.startswith("明渠"):
        return struct_str
    if struct_str == "矩形暗涵":
        return struct_str
    if node.name:
        category = struct_str.split("-")[0]
        return f"{node.name}{category}"
    return struct_str.split("-")[0] if struct_str else ""


def _estimate_text_width(text, text_height):
    """估算 AutoCAD 中文字的总宽度（用于居中对齐）

    中文字符（CJK）宽度 ≈ text_height
    ASCII 字符（字母/数字/标点）宽度 ≈ text_height × 0.7
    """
    width = 0.0
    for ch in text:
        if ord(ch) > 127:
            width += text_height
        else:
            width += text_height * 0.7
    return width


def _format_slope_text(slope_i):
    """格式化坡降为显示文本"""
    if slope_i is not None and slope_i > 0:
        slope_inv = round(1.0 / slope_i)
        return f"1/{slope_inv}"
    return "/"


def _get_node_slope_text(node, next_node=None):
    """获取节点坡降文本（直接使用节点自身的 slope_i）。"""
    return _format_slope_text(getattr(node, 'slope_i', None))


def _struct_val(struct_type):
    """获取 StructureType 的字符串值（兼容双路径导入的 enum 实例）"""
    if struct_type is None:
        return ""
    return struct_type.value if hasattr(struct_type, 'value') else str(struct_type)


def _in_out_val(in_out):
    """获取 InOutType 的字符串值（兼容双路径导入的 enum 实例）"""
    if in_out is None:
        return ""
    return in_out.value if hasattr(in_out, 'value') else str(in_out)


def _is_special_structure_sv(struct_type):
    """判断是否为特殊建筑物（隧洞/倒虹吸/渡槽），使用字符串值比较

    注意：矩形暗涵不需要进出口标识，不属于特殊建筑物。
    避免双路径导入导致 enum 实例比较失败"""
    sv = _struct_val(struct_type)
    return any(k in sv for k in ("隧洞", "倒虹吸", "渡槽"))


def _is_gate_name(name):
    """判断建筑物显示名称是否为闸类点状建筑物（分水闸/分水口/节制闸/泄水闸等）"""
    if not name:
        return False
    return "闸" in name or "分水" in name


def _get_segment_slope_text(mc_list, mc_to_node):
    """从建筑物段的节点列表中提取坡降文本

    遍历段内所有 MC 对应的节点，取第一个有效的 slope_i 作为坡降。
    Args:
        mc_list: 该建筑物段包含的桩号列表
        mc_to_node: {station_MC: node} 查找表
    Returns:
        坡降文本（如 "1/3000"），无数据时返回 None
    """
    for mc in mc_list:
        node = mc_to_node.get(mc)
        if node:
            st = _format_slope_text(getattr(node, 'slope_i', None))
            if st != "/":
                return st
    return None


def _merge_segments_across_gates(segments, gate_mc_set=None):
    """合并被闸（点状建筑物）拆分的同名段落

    规则：如果段落 i 和段落 j 的值相同，且 i~j 之间的所有段落
    都是闸类点状建筑物，则将 j 的 MC 列表合并到 i，闸段保留不变。

    对建筑物名称段落：通过名称判断闸（_is_gate_name）。
    对坡降等段落：通过 gate_mc_set（闸节点的桩号集合）判断。

    Args:
        segments: [(value, [mc_list]), ...] 按位置排列的段落
        gate_mc_set: 闸节点桩号集合，仅在非名称场景下使用
    """
    if len(segments) <= 2:
        return segments

    def _is_gate_seg(val, mc_list):
        if gate_mc_set is not None:
            return all(mc in gate_mc_set for mc in mc_list)
        return _is_gate_name(val)

    merged = []
    i = 0
    while i < len(segments):
        val, mc_list = segments[i]

        if _is_gate_seg(val, mc_list):
            merged.append((val, list(mc_list)))
            i += 1
            continue

        # 非闸段：尝试向后合并同名段（跳过中间的闸段）
        mc_list = list(mc_list)
        j = i + 1
        while j + 1 < len(segments):
            mid_val, mid_mcs = segments[j]
            next_val, next_mcs = segments[j + 1]
            if _is_gate_seg(mid_val, mid_mcs) and next_val == val:
                merged.append((mid_val, list(mid_mcs)))  # 闸段保留
                mc_list.extend(next_mcs)
                j += 2
            else:
                break

        merged.append((val, mc_list))
        i = j if j > i + 1 else i + 1

    return merged


# ================================================================
# 纵断面表格导出设置对话框
# ================================================================

class TextExportSettingsDialog(QDialog):
    """纵断面文字导出参数配置弹窗（QFluentWidgets 风格）"""

    def __init__(self, parent=None, defaults=None):
        super().__init__(parent)
        self.setWindowTitle("纵断面文字导出设置")
        self.setMinimumWidth(420)
        self.setStyleSheet(DIALOG_STYLE)
        self.result = None

        if defaults is None:
            defaults = {}
        self._defaults = {
            'y_bottom': defaults.get('y_bottom', 1),
            'y_top': defaults.get('y_top', 31),
            'y_water': defaults.get('y_water', 16),
            'text_height': defaults.get('text_height', 3.5),
            'rotation': defaults.get('rotation', 90),
            'elev_decimals': defaults.get('elev_decimals', 3),
            'y_name': defaults.get('y_name', 115),
            'y_slope': defaults.get('y_slope', 105),
            'y_ip': defaults.get('y_ip', 77),
            'y_station': defaults.get('y_station', 47),
            'y_line_height': defaults.get('y_line_height', 120),
            'scale_x': defaults.get('scale_x', 1),
            'scale_y': defaults.get('scale_y', 1),
        }

        self._entries = {}
        self._init_ui()

    def _init_ui(self):
        lay = QVBoxLayout(self)

        # Y坐标设置
        y_grp = QGroupBox("Y 坐标设置（CAD 表格行高）")
        y_form = QGridLayout(y_grp)
        for row, (label, key) in enumerate([
            ("渠底文字 Y 坐标:", 'y_bottom'),
            ("渠顶文字 Y 坐标:", 'y_top'),
            ("水面文字 Y 坐标:", 'y_water'),
        ]):
            y_form.addWidget(QLabel(label), row, 0)
            e = LineEdit(); e.setText(str(self._defaults[key])); e.setFixedWidth(100)
            y_form.addWidget(e, row, 1)
            self._entries[key] = e
        lay.addWidget(y_grp)

        # 文字样式
        style_grp = QGroupBox("文字样式")
        style_form = QGridLayout(style_grp)
        for row, (label, key) in enumerate([
            ("字高:", 'text_height'),
            ("旋转角度:", 'rotation'),
            ("高程小数位数:", 'elev_decimals'),
        ]):
            style_form.addWidget(QLabel(label), row, 0)
            e = LineEdit(); e.setText(str(self._defaults[key])); e.setFixedWidth(100)
            style_form.addWidget(e, row, 1)
            self._entries[key] = e
        lay.addWidget(style_grp)

        # 纵断面信息列
        info_grp = QGroupBox("纵断面信息列 Y 坐标")
        info_form = QGridLayout(info_grp)
        for row, (label, key) in enumerate([
            ("建筑物名称 Y 坐标:", 'y_name'),
            ("坡降 Y 坐标:", 'y_slope'),
            ("IP点名称 Y 坐标:", 'y_ip'),
            ("里程桩号 Y 坐标:", 'y_station'),
            ("整线竖线高度:", 'y_line_height'),
        ]):
            info_form.addWidget(QLabel(label), row, 0)
            e = LineEdit(); e.setText(str(self._defaults[key])); e.setFixedWidth(100)
            info_form.addWidget(e, row, 1)
            self._entries[key] = e
        lay.addWidget(info_grp)

        # 比例设置
        scale_grp = QGroupBox("比例设置")
        scale_form = QGridLayout(scale_grp)
        scale_form.addWidget(QLabel("X 方向 (1:N)，N ="), 0, 0)
        e = LineEdit(); e.setText(str(self._defaults['scale_x'])); e.setFixedWidth(100)
        scale_form.addWidget(e, 0, 1)
        scale_form.addWidget(QLabel("如 1:1000 则输入 1000"), 0, 2)
        self._entries['scale_x'] = e
        scale_form.addWidget(QLabel("Y 方向 (1:N)，N ="), 1, 0)
        e = LineEdit(); e.setText(str(self._defaults['scale_y'])); e.setFixedWidth(100)
        scale_form.addWidget(e, 1, 1)
        scale_form.addWidget(QLabel("如 1:100 则输入 100"), 1, 2)
        self._entries['scale_y'] = e
        lay.addWidget(scale_grp)

        # 预览
        preview_grp = QGroupBox("命令格式预览")
        preview_lay = QVBoxLayout(preview_grp)
        self._preview_label = QLabel()
        self._preview_label.setStyleSheet("color: #336699;")
        self._preview_label.setFont(QFont("Consolas", 9))
        preview_lay.addWidget(self._preview_label)
        lay.addWidget(preview_grp)
        self._update_preview()
        for entry in self._entries.values():
            entry.textChanged.connect(self._update_preview)

        # 按钮
        btn_lay = QHBoxLayout()
        btn_reset = PushButton("恢复默认"); btn_reset.clicked.connect(self._reset_defaults)
        btn_lay.addWidget(btn_reset); btn_lay.addStretch()
        btn_cancel = PushButton("取消"); btn_cancel.clicked.connect(self.reject)
        btn_ok = PrimaryPushButton("确定"); btn_ok.clicked.connect(self._on_confirm)
        btn_lay.addWidget(btn_cancel); btn_lay.addWidget(btn_ok)
        lay.addLayout(btn_lay)

        # 键盘快捷键
        QShortcut(QKeySequence(Qt.Key_Escape), self, self.reject)
        QShortcut(QKeySequence(Qt.Key_Return), self, self._on_confirm)

    def _update_preview(self):
        try:
            y_b = self._entries['y_bottom'].text().strip()
            h = self._entries['text_height'].text().strip()
            r = self._entries['rotation'].text().strip()
            d = self._entries['elev_decimals'].text().strip()
            try:
                decimals = int(float(d))
                sample = f"{431.666:.{decimals}f}"
            except Exception:
                sample = "431.666"
            self._preview_label.setText(f"-text 里程MC,{y_b} {h} {r} {sample} ")
        except Exception:
            self._preview_label.setText("-text 里程MC,Y 字高 角度 高程 ")

    def _reset_defaults(self):
        original = {
            'y_bottom': 1, 'y_top': 31, 'y_water': 16,
            'text_height': 3.5, 'rotation': 90, 'elev_decimals': 3,
            'y_name': 115, 'y_slope': 105, 'y_ip': 77,
            'y_station': 47, 'y_line_height': 120,
            'scale_x': 1, 'scale_y': 1,
        }
        for key, value in original.items():
            self._entries[key].setText(str(value))
        self._update_preview()

    def _on_confirm(self):
        try:
            result = {}
            for key, entry in self._entries.items():
                val_str = entry.text().strip()
                if not val_str:
                    raise ValueError("参数不能为空")
                val = float(val_str)
                if key == 'elev_decimals':
                    if val < 0 or val != int(val):
                        raise ValueError("高程小数位数必须为非负整数")
                    val = int(val)
                if key in ('scale_x', 'scale_y'):
                    if val <= 0:
                        raise ValueError("比例尺必须大于0")
                result[key] = val
            self.result = result
            self.accept()
        except ValueError as e:
            fluent_error(self, "输入错误", f"请输入有效的数值:\n{str(e)}")


# ================================================================
# 平面图参数设置对话框
# ================================================================

class PlanTextSettingsDialog(QDialog):
    """建筑物名称上平面图参数设置对话框"""

    def __init__(self, parent=None, defaults=None):
        super().__init__(parent)
        self.setWindowTitle("建筑物名称上平面图 - 参数设置")
        self.setMinimumWidth(380)
        self.setStyleSheet(DIALOG_STYLE)
        self.result = None
        if defaults is None:
            defaults = {}
        self._init_ui(defaults)

    def _init_ui(self, defaults):
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            "生成 AutoCAD -TEXT 命令，将建筑物名称平行于轴线放置。\n"
            "文字位于建筑物最中间两个IP点连线段的中点处。"
        ))

        form = QGridLayout()
        form.addWidget(QLabel("垂直偏移距离 (V):"), 0, 0)
        self.offset_edit = LineEdit(); self.offset_edit.setText(str(defaults.get('offset', 10)))
        self.offset_edit.setFixedWidth(100)
        form.addWidget(self.offset_edit, 0, 1)
        form.addWidget(QLabel("文字中心到轴线的距离"), 0, 2)

        form.addWidget(QLabel("文字高度:"), 1, 0)
        self.height_edit = LineEdit(); self.height_edit.setText(str(defaults.get('text_height', 10)))
        self.height_edit.setFixedWidth(100)
        form.addWidget(self.height_edit, 1, 1)
        form.addWidget(QLabel("AutoCAD -TEXT 字高"), 1, 2)
        lay.addLayout(form)

        # 预览
        preview_grp = QGroupBox("命令格式预览")
        preview_lay = QVBoxLayout(preview_grp)
        self._preview_label = QLabel()
        self._preview_label.setStyleSheet("color: gray;")
        preview_lay.addWidget(self._preview_label)
        lay.addWidget(preview_grp)
        self._update_preview()
        self.offset_edit.textChanged.connect(self._update_preview)
        self.height_edit.textChanged.connect(self._update_preview)

        btn_lay = QHBoxLayout()
        btn_lay.addStretch()
        btn_cancel = PushButton("取消"); btn_cancel.clicked.connect(self.reject)
        btn_ok = PrimaryPushButton("确定"); btn_ok.clicked.connect(self._on_confirm)
        btn_lay.addWidget(btn_cancel); btn_lay.addWidget(btn_ok)
        lay.addLayout(btn_lay)

        # 键盘快捷键
        QShortcut(QKeySequence(Qt.Key_Escape), self, self.reject)
        QShortcut(QKeySequence(Qt.Key_Return), self, self._on_confirm)

    def _update_preview(self):
        try:
            o = self.offset_edit.text().strip()
            h = self.height_edit.text().strip()
            self._preview_label.setText(
                f"-TEXT J MC x,y {h} 角度 建筑物名称\n"
                f"（文字中心偏移轴线 {o} 个单位）")
        except Exception:
            pass

    def _on_confirm(self):
        try:
            o = float(self.offset_edit.text().strip())
            h = float(self.height_edit.text().strip())
            if h <= 0:
                raise ValueError("文字高度必须大于0")
            self.result = {'offset': o, 'text_height': h}
            self.accept()
        except ValueError as e:
            fluent_error(self, "输入错误", f"请输入有效的数值:\n{e}")


# ================================================================
# 1. 生成纵断面表格 TXT
# ================================================================

def export_longitudinal_profile_txt(panel):
    """一键生成上纵断面表格 TXT（AutoCAD pl + -text 命令格式）

    输出格式为逐行 AutoCAD 命令（可直接全选复制粘贴到 AutoCAD 命令行自动执行）。
    *** 所有 pl 命令在前，-text 命令在后（避免命令交错导致解析异常） ***
    """
    if not MODELS_AVAILABLE:
        fluent_info(panel.window(), "不可用", "核心模型未加载")
        return

    nodes = panel.calculated_nodes
    if not nodes:
        fluent_info(panel.window(), "警告", "没有数据可导出")
        return

    valid_nodes = [n for n in nodes if n.bottom_elevation or n.top_elevation or n.water_level]
    if not valid_nodes:
        fluent_info(panel.window(), "警告", "没有可用的高程数据，请先执行计算。")
        return

    # 弹出参数配置对话框
    dlg = TextExportSettingsDialog(panel.window(), panel._text_export_settings)
    if dlg.exec() != QDialog.Accepted or dlg.result is None:
        return

    panel._text_export_settings.update(dlg.result)
    settings = dlg.result

    y_bottom = settings['y_bottom']
    y_top = settings['y_top']
    y_water = settings['y_water']
    text_height = settings['text_height']
    rotation = settings['rotation']
    elev_decimals = int(settings.get('elev_decimals', 3))
    y_name = settings.get('y_name', 112)
    y_slope = settings.get('y_slope', 102)
    y_ip = settings.get('y_ip', 77)
    y_station = settings.get('y_station', 47)
    y_line_height = settings.get('y_line_height', 120)

    # 自动文件名
    try:
        ch_name = panel.channel_name_edit.text().strip()
        ch_level = panel.channel_level_combo.currentText()
        auto_name = f"{ch_name}{ch_level}_上纵断面表格.txt"
    except Exception:
        auto_name = "上纵断面表格.txt"

    file_path, _ = QFileDialog.getSaveFileName(
        panel, "保存上纵断面表格", auto_name,
        "文本文件 (*.txt);;所有文件 (*.*)")
    if not file_path:
        return

    try:
        fmt = _format_number
        s_y_bottom = fmt(y_bottom)
        s_y_top = fmt(y_top)
        s_y_water = fmt(y_water)
        s_height = fmt(text_height)
        s_rotation = fmt(rotation)
        s_y_name = fmt(y_name)
        s_y_slope = fmt(y_slope)
        s_y_ip = fmt(y_ip)
        s_y_station = fmt(y_station)
        s_y_line_height = fmt(y_line_height)

        # 第一个节点的文字偏移（避免与左侧竖线重叠）
        first_col_x_offset = text_height + 1.3

        try:
            proj_settings = panel._build_settings()
            station_prefix = proj_settings.get_station_prefix()
        except Exception:
            station_prefix = ""

        def fmt_elev(value):
            if value is None:
                return f"{0:.{elev_decimals}f}"
            return f"{value:.{elev_decimals}f}"

        lines = []

        # ======== 所有 pl 命令 ========

        # 第一部分：表头区域线框
        h_line_y_values = [0, 15, 30, 45, 75, 100, 110, 120]
        for hy in h_line_y_values:
            lines.append(f"pl 0,{hy} -40,{hy} ")
        lines.append(f"pl -40,0 -40,{s_y_line_height} ")
        lines.append("")

        # 第二部分：整线竖线
        tall_line_mcs = []
        for idx, node in enumerate(nodes):
            mc = fmt(node.station_MC)
            is_special = False
            if idx == 0 or idx == len(nodes) - 1:
                is_special = True
            elif (_is_special_structure_sv(node.structure_type) and
                  _in_out_val(node.in_out) in ("进", "出")):
                is_special = True
            if is_special:
                tall_line_mcs.append(node.station_MC)
            height = s_y_line_height if is_special else "100"
            lines.append(f"pl {mc},0 {mc},{height} ")
        lines.append("")

        # 第三部分：水平线
        last_mc = fmt(nodes[-1].station_MC)
        for hy in h_line_y_values:
            lines.append(f"pl 0,{hy} {last_mc},{hy} ")
        lines.append("")

        # 第四部分：渠底/渠顶/水面 pl
        for node in valid_nodes:
            if node.bottom_elevation:
                lines.append(f"pl {fmt(node.station_MC)},{fmt(node.bottom_elevation)}")
        lines.append("")
        for node in valid_nodes:
            if node.top_elevation:
                lines.append(f"pl {fmt(node.station_MC)},{fmt(node.top_elevation)}")
        lines.append("")
        for node in valid_nodes:
            if node.water_level:
                lines.append(f"pl {fmt(node.station_MC)},{fmt(node.water_level)}")
        lines.append("")

        # ======== 所有 -text 命令 ========

        # 第五部分：渠底/渠顶/水面文字
        for idx, node in enumerate(nodes):
            mc = fmt(node.station_MC)
            text_x = fmt(node.station_MC + first_col_x_offset) if idx == 0 else mc
            lines.append(
                f"-text {text_x},{s_y_bottom} {s_height} {s_rotation} {fmt_elev(node.bottom_elevation)} ")
        lines.append("")
        for idx, node in enumerate(nodes):
            mc = fmt(node.station_MC)
            text_x = fmt(node.station_MC + first_col_x_offset) if idx == 0 else mc
            lines.append(
                f"-text {text_x},{s_y_top} {s_height} {s_rotation} {fmt_elev(node.top_elevation)} ")
        lines.append("")
        for idx, node in enumerate(nodes):
            mc = fmt(node.station_MC)
            text_x = fmt(node.station_MC + first_col_x_offset) if idx == 0 else mc
            lines.append(
                f"-text {text_x},{s_y_water} {s_height} {s_rotation} {fmt_elev(node.water_level)} ")
        lines.append("")

        # 第六部分：里程桩号
        for idx, node in enumerate(nodes):
            mc = fmt(node.station_MC)
            text_x = fmt(node.station_MC + first_col_x_offset) if idx == 0 else mc
            station_text = ProjectSettings.format_station(node.station_MC, station_prefix)
            lines.append(
                f"-text {text_x},{s_y_station} {s_height} {s_rotation} {station_text} ")
        lines.append("")

        # 第七部分：表头文字
        header_col_width = 40
        header_single = [
            ("建筑物名称", 110, 120),
            ("坡 降", 100, 110),
            ("IP点名称", 75, 100),
            ("渠顶高程(m)", 30, 45),
            ("设计水位(m)", 15, 30),
            ("渠底高程(m)", 0, 15),
        ]
        header_cx = fmt(-40 + header_col_width / 2)
        for label, row_bot, row_top in header_single:
            cy = (row_bot + row_top) / 2
            lines.append(f"-text j mc {header_cx},{fmt(cy)} {s_height} 0 {label} ")
        line_spacing = text_height * 2.5
        block_h = line_spacing + text_height
        y_line_bottom_val = 45 + (30 - block_h) / 2 + text_height / 2
        y_line_top_val = y_line_bottom_val + line_spacing
        for label, y_pos in [("里程桩号", y_line_top_val), ("（千米+米）", y_line_bottom_val)]:
            lines.append(f"-text j mc {header_cx},{fmt(y_pos)} {s_height} 0 {label} ")
        lines.append("")

        # 第八部分：建筑物名称
        name_mc_pairs = []
        for node in nodes:
            building_name = _get_building_display_name(node)
            if building_name:
                name_mc_pairs.append((building_name, node.station_MC))
        building_segments = []
        for bname, bmc in name_mc_pairs:
            if building_segments and building_segments[-1][0] == bname:
                building_segments[-1][1].append(bmc)
            else:
                building_segments.append((bname, [bmc]))
        building_segments = _merge_segments_across_gates(building_segments)
        for bname, mc_list in building_segments:
            if _is_gate_name(bname):
                # 闸类点状建筑物：直接使用桩号 MC 定位
                mid_mc = mc_list[0]
            else:
                seg_start = mc_list[0]
                seg_end = mc_list[-1]
                left_bound = max((m for m in tall_line_mcs if m <= seg_start), default=seg_start)
                right_bound = min((m for m in tall_line_mcs if m >= seg_end), default=seg_end)
                mid_mc = (left_bound + right_bound) / 2.0
            lines.append(f"-text j mc {fmt(mid_mc)},115 {s_height} 0 {bname} ")
        lines.append("")

        # 第九部分：坡降（从建筑物名称分段派生，与名称行一一对齐）
        mc_to_node = {node.station_MC: node for node in nodes}
        for bname, mc_list in building_segments:
            # 闸/分水口：不显示坡降
            if _is_gate_name(bname):
                continue
            # 倒虹吸为有压流，不显示坡降
            if "倒虹吸" in bname:
                continue
            slope_text = _get_segment_slope_text(mc_list, mc_to_node)
            if not slope_text:
                continue
            # 居中位置与上方建筑物名称完全对齐
            seg_start = mc_list[0]
            seg_end = mc_list[-1]
            left_bound = max((m for m in tall_line_mcs if m <= seg_start), default=seg_start)
            right_bound = min((m for m in tall_line_mcs if m >= seg_end), default=seg_end)
            mid_mc = (left_bound + right_bound) / 2.0
            lines.append(f"-text j mc {fmt(mid_mc)},105 {s_height} 0 {slope_text} ")
        lines.append("")

        # 第十部分：IP点名称
        for idx, node in enumerate(nodes):
            struct_str = node.get_structure_type_str() or ""
            if node.is_transition or struct_str == "渐变段":
                continue
            if _is_special_structure_sv(node.structure_type):
                if _in_out_val(node.in_out) in ("进", "出"):
                    struct_abbr = ""
                    st_val = _struct_val(node.structure_type)
                    if "隧洞" in st_val:
                        struct_abbr = "隧"
                    elif "倒虹吸" in st_val:
                        struct_abbr = "倒"
                    elif "渡槽" in st_val:
                        struct_abbr = "渡"
                    in_out_str = "进" if _in_out_val(node.in_out) == "进" else "出"
                    ip_name = f"{node.name}{struct_abbr}{in_out_str}"
                else:
                    continue
            else:
                ip_name = f"{station_prefix}IP{getattr(node, 'ip_number', 0)}"
            mc = fmt(node.station_MC)
            text_x = fmt(node.station_MC + first_col_x_offset) if node.station_MC == nodes[0].station_MC else mc
            lines.append(
                f"-text {text_x},77 {s_height} {s_rotation} {ip_name} ")
        lines.append("")

        # 写入文件
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        if fluent_question(panel.window(), "完成",
                f"上纵断面表格已生成（{len(nodes)} 个节点）:\n{file_path}\n\n是否立即打开该文件？"):
            os.startfile(file_path)

    except PermissionError:
        fluent_error(panel.window(), "文件被占用",
                     f"无法写入文件，该文件可能已被其他程序打开：\n\n{file_path}\n\n"
                     f"请先关闭该文件（如记事本、Word等），然后重新操作。")
    except Exception as e:
        import traceback; traceback.print_exc()
        fluent_error(panel.window(), "导出错误", f"生成上纵断面表格失败:\n{str(e)}")


# ================================================================
# 1b. 生成纵断面表格 DXF（直接生成 CAD 可打开的 DXF 文件）
# ================================================================

def export_longitudinal_profile_dxf(panel):
    """一键生成上纵断面表格 DXF

    直接生成 DXF 文件，包含表格线框、渠底/渠顶/水面折线、
    高程文字、里程桩号、建筑物名称、坡降、IP点名称等全部内容。
    双击即可在 AutoCAD / 浩辰CAD / 中望CAD 中打开。
    """
    import ezdxf

    if not MODELS_AVAILABLE:
        fluent_info(panel.window(), "不可用", "核心模型未加载")
        return

    nodes = panel.calculated_nodes
    if not nodes:
        fluent_info(panel.window(), "警告", "没有数据可导出")
        return

    valid_nodes = [n for n in nodes if n.bottom_elevation or n.top_elevation or n.water_level]
    if not valid_nodes:
        fluent_info(panel.window(), "警告", "没有可用的高程数据，请先执行计算。")
        return

    # 弹出参数配置对话框（复用 TXT 版设置）
    dlg = TextExportSettingsDialog(panel.window(), panel._text_export_settings)
    if dlg.exec() != QDialog.Accepted or dlg.result is None:
        return

    panel._text_export_settings.update(dlg.result)
    settings = dlg.result

    y_bottom = settings['y_bottom']
    y_top = settings['y_top']
    y_water = settings['y_water']
    text_height = settings['text_height']
    rotation = settings['rotation']
    elev_decimals = int(settings.get('elev_decimals', 3))
    y_name = settings.get('y_name', 115)
    y_slope = settings.get('y_slope', 105)
    y_ip = settings.get('y_ip', 77)
    y_station = settings.get('y_station', 47)
    y_line_height = settings.get('y_line_height', 120)
    scale_x = settings.get('scale_x', 1)
    scale_y = settings.get('scale_y', 1)

    # 缩放辅助：station_MC → 图面 X 坐标，elevation → 图面 Y 坐标
    def sx(mc):
        """将里程(m)缩放到图面 X 坐标"""
        return mc / scale_x

    def sy(elev):
        """将高程(m)缩放到图面 Y 坐标"""
        return elev / scale_y

    # 自动文件名
    try:
        ch_name = panel.channel_name_edit.text().strip()
        ch_level = panel.channel_level_combo.currentText()
        auto_name = f"{ch_name}{ch_level}_上纵断面表格.dxf"
    except Exception:
        auto_name = "上纵断面表格.dxf"

    file_path, _ = QFileDialog.getSaveFileName(
        panel, "保存上纵断面表格", auto_name,
        "DXF 文件 (*.dxf);;文本文件 (*.txt);;所有文件 (*.*)")
    if not file_path:
        return

    # 如果用户选择了 .txt，走原有 TXT 导出逻辑
    if file_path.lower().endswith('.txt'):
        _export_longitudinal_txt_to_path(panel, nodes, valid_nodes, settings, file_path)
        return

    try:
        first_col_x_offset = text_height + 1.3

        try:
            proj_settings = panel._build_settings()
            station_prefix = proj_settings.get_station_prefix()
        except Exception:
            station_prefix = ""

        def fmt_elev(value):
            if value is None:
                return f"{0:.{elev_decimals}f}"
            return f"{value:.{elev_decimals}f}"

        # ---- 创建 DXF 文档 ----
        doc = ezdxf.new("R2010")
        msp = doc.modelspace()

        # 中文字体：TrueType 仿宋（Unicode版），宽度因子0.7
        if "Standard" in doc.styles:
            _sty = doc.styles.get("Standard")
        else:
            _sty = doc.styles.add("Standard")
        _sty.dxf.font = ""            # 清除 SHX 引用
        _sty.dxf.width = 0.7
        try:
            if "ACAD" not in doc.appids:
                doc.appids.new("ACAD")
        except Exception:
            pass
        _sty.set_xdata("ACAD", [(1000, "仿宋"), (1071, 0)])

        # 图层
        doc.layers.new("表格线框", dxfattribs={"color": 7})
        doc.layers.new("渠底高程线", dxfattribs={"color": 3})
        doc.layers.new("渠顶高程线", dxfattribs={"color": 1})
        doc.layers.new("设计水位线", dxfattribs={"color": 5})
        doc.layers.new("文字标注", dxfattribs={"color": 7})

        last_mc = nodes[-1].station_MC
        layer_grid = "表格线框"
        layer_text = "文字标注"

        # ======== 1. 表头区域线框 ========
        h_line_y_values = [0, 15, 30, 45, 75, 100, 110, 120]
        for hy in h_line_y_values:
            msp.add_line((-40, hy), (sx(0), hy), dxfattribs={"layer": layer_grid})
        msp.add_line((-40, 0), (-40, y_line_height), dxfattribs={"layer": layer_grid})

        # ======== 2. 节点竖线 ========
        tall_line_mcs = []
        for idx, node in enumerate(nodes):
            mc = node.station_MC
            is_special = (idx == 0 or idx == len(nodes) - 1)
            if not is_special and (_is_special_structure_sv(node.structure_type) and
                                   _in_out_val(node.in_out) in ("进", "出")):
                is_special = True
            if is_special:
                tall_line_mcs.append(mc)
            height = y_line_height if is_special else 100
            msp.add_line((sx(mc), 0), (sx(mc), height), dxfattribs={"layer": layer_grid})

        # ======== 3. 全宽水平线 ========
        for hy in h_line_y_values:
            msp.add_line((sx(0), hy), (sx(last_mc), hy), dxfattribs={"layer": layer_grid})

        # ======== 4. 渠底/渠顶/水面折线 ========
        bottom_pts = [(sx(n.station_MC), sy(n.bottom_elevation))
                      for n in valid_nodes if n.bottom_elevation]
        top_pts = [(sx(n.station_MC), sy(n.top_elevation))
                   for n in valid_nodes if n.top_elevation]
        water_pts = [(sx(n.station_MC), sy(n.water_level))
                     for n in valid_nodes if n.water_level]

        if len(bottom_pts) >= 2:
            msp.add_lwpolyline(bottom_pts, dxfattribs={"layer": "渠底高程线"})
        if len(top_pts) >= 2:
            msp.add_lwpolyline(top_pts, dxfattribs={"layer": "渠顶高程线"})
        if len(water_pts) >= 2:
            msp.add_lwpolyline(water_pts, dxfattribs={"layer": "设计水位线"})

        # ======== 5. 渠底/渠顶/水面高程文字 ========
        for idx, node in enumerate(nodes):
            text_x = sx(node.station_MC) + first_col_x_offset if idx == 0 else sx(node.station_MC) - 1
            for elev_val, y_pos in [
                (node.bottom_elevation, y_bottom),
                (node.top_elevation, y_top),
                (node.water_level, y_water),
            ]:
                msp.add_text(
                    fmt_elev(elev_val),
                    dxfattribs={"layer": layer_text, "height": text_height,
                                "rotation": rotation, "width": 0.7, "style": "Standard"}
                ).set_placement((text_x, y_pos))

        # ======== 6. 里程桩号 ========
        for idx, node in enumerate(nodes):
            text_x = sx(node.station_MC) + first_col_x_offset if idx == 0 else sx(node.station_MC) - 1
            station_text = ProjectSettings.format_station(node.station_MC, station_prefix)
            msp.add_text(
                station_text,
                dxfattribs={"layer": layer_text, "height": text_height,
                            "rotation": rotation, "width": 0.7, "style": "Standard"}
            ).set_placement((text_x, y_station))

        # ======== 7. 表头文字 ========
        header_col_width = 40
        header_single = [
            ("建筑物名称", 110, 120),
            ("坡 降", 100, 110),
            ("IP点名称", 75, 100),
            ("渠顶高程(m)", 30, 45),
            ("设计水位(m)", 15, 30),
            ("渠底高程(m)", 0, 15),
        ]
        header_cx = -40 + header_col_width / 2
        for label, row_bot, row_top in header_single:
            cy = (row_bot + row_top) / 2
            msp.add_text(
                label,
                dxfattribs={"layer": layer_text, "height": text_height,
                            "width": 0.7, "style": "Standard"}
            ).set_placement((header_cx, cy),
                            align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)

        line_spacing = text_height * 2.5
        block_h = line_spacing + text_height
        y_line_bottom_val = 45 + (30 - block_h) / 2 + text_height / 2
        y_line_top_val = y_line_bottom_val + line_spacing
        for label, y_pos in [("里程桩号", y_line_top_val), ("（千米+米）", y_line_bottom_val)]:
            msp.add_text(
                label,
                dxfattribs={"layer": layer_text, "height": text_height,
                            "width": 0.7, "style": "Standard"}
            ).set_placement((header_cx, y_pos),
                            align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)

        # ======== 8. 建筑物名称 ========
        name_mc_pairs = []
        for node in nodes:
            building_name = _get_building_display_name(node)
            if building_name:
                name_mc_pairs.append((building_name, node.station_MC))
        building_segments = []
        for bname, bmc in name_mc_pairs:
            if building_segments and building_segments[-1][0] == bname:
                building_segments[-1][1].append(bmc)
            else:
                building_segments.append((bname, [bmc]))
        building_segments = _merge_segments_across_gates(building_segments)
        for bname, mc_list in building_segments:
            if _is_gate_name(bname):
                mid_mc = mc_list[0]
            else:
                seg_start = mc_list[0]
                seg_end = mc_list[-1]
                left_bound = max((m for m in tall_line_mcs if m <= seg_start), default=seg_start)
                right_bound = min((m for m in tall_line_mcs if m >= seg_end), default=seg_end)
                mid_mc = (left_bound + right_bound) / 2.0
            msp.add_text(
                bname,
                dxfattribs={"layer": layer_text, "height": text_height,
                            "width": 0.7, "style": "Standard"}
            ).set_placement((sx(mid_mc), (110 + 120) / 2),
                            align=ezdxf.enums.TextEntityAlignment.MIDDLE)

        # ======== 9. 坡降（从建筑物名称分段派生，与名称行一一对齐） ========
        mc_to_node = {node.station_MC: node for node in nodes}
        for bname, mc_list in building_segments:
            # 闸/分水口：不显示坡降
            if _is_gate_name(bname):
                continue
            # 倒虹吸为有压流，不显示坡降
            if "倒虹吸" in bname:
                continue
            slope_text = _get_segment_slope_text(mc_list, mc_to_node)
            if not slope_text:
                continue
            # 居中位置与上方建筑物名称完全对齐
            seg_start = mc_list[0]
            seg_end = mc_list[-1]
            left_bound = max((m for m in tall_line_mcs if m <= seg_start), default=seg_start)
            right_bound = min((m for m in tall_line_mcs if m >= seg_end), default=seg_end)
            mid_mc = (left_bound + right_bound) / 2.0
            msp.add_text(
                slope_text,
                dxfattribs={"layer": layer_text, "height": text_height,
                            "width": 0.7, "style": "Standard"}
            ).set_placement((sx(mid_mc), (100 + 110) / 2),
                            align=ezdxf.enums.TextEntityAlignment.MIDDLE)

        # ======== 10. IP点名称 ========
        for idx, node in enumerate(nodes):
            struct_str = node.get_structure_type_str() or ""
            if node.is_transition or struct_str == "渐变段":
                continue
            if _is_special_structure_sv(node.structure_type):
                if _in_out_val(node.in_out) in ("进", "出"):
                    struct_abbr = ""
                    st_val = _struct_val(node.structure_type)
                    if "隧洞" in st_val:
                        struct_abbr = "隧"
                    elif "倒虹吸" in st_val:
                        struct_abbr = "倒"
                    elif "渡槽" in st_val:
                        struct_abbr = "渡"
                    in_out_str = "进" if _in_out_val(node.in_out) == "进" else "出"
                    ip_name = f"{node.name}{struct_abbr}{in_out_str}"
                else:
                    continue
            else:
                ip_name = f"{station_prefix}IP{getattr(node, 'ip_number', 0)}"
            text_x = (sx(node.station_MC) + first_col_x_offset
                      if node.station_MC == nodes[0].station_MC else sx(node.station_MC) - 1)
            msp.add_text(
                ip_name,
                dxfattribs={"layer": layer_text, "height": text_height,
                            "rotation": rotation, "width": 0.7, "style": "Standard"}
            ).set_placement((text_x, y_ip))

        # ---- 保存 ----
        doc.saveas(file_path)

        if fluent_question(panel.window(), "完成",
                f"上纵断面表格 DXF 已生成（{len(nodes)} 个节点）:\n{file_path}\n\n是否立即打开该文件？"):
            os.startfile(file_path)

    except PermissionError:
        fluent_error(panel.window(), "文件被占用",
                     f"无法写入文件，该文件可能已被其他程序打开：\n\n{file_path}\n\n"
                     f"请先关闭该文件（如CAD等），然后重新操作。")
    except Exception as e:
        import traceback; traceback.print_exc()
        fluent_error(panel.window(), "导出错误", f"生成上纵断面表格 DXF 失败:\n{str(e)}")


def _export_longitudinal_txt_to_path(panel, nodes, valid_nodes, settings, file_path):
    """内部方法：将纵断面表格以 TXT（AutoCAD 命令）格式写入指定路径"""
    fmt = _format_number

    y_bottom = settings['y_bottom']
    y_top = settings['y_top']
    y_water = settings['y_water']
    text_height = settings['text_height']
    rotation = settings['rotation']
    elev_decimals = int(settings.get('elev_decimals', 3))
    y_name = settings.get('y_name', 115)
    y_slope = settings.get('y_slope', 105)
    y_ip = settings.get('y_ip', 77)
    y_station = settings.get('y_station', 47)
    y_line_height = settings.get('y_line_height', 120)
    scale_x = settings.get('scale_x', 1)
    scale_y = settings.get('scale_y', 1)

    def sx(mc):
        return mc / scale_x

    def sy(elev):
        return elev / scale_y

    s_y_bottom = fmt(y_bottom)
    s_y_top = fmt(y_top)
    s_y_water = fmt(y_water)
    s_height = fmt(text_height)
    s_rotation = fmt(rotation)
    s_y_name = fmt(y_name)
    s_y_slope = fmt(y_slope)
    s_y_ip = fmt(y_ip)
    s_y_station = fmt(y_station)
    s_y_line_height = fmt(y_line_height)

    first_col_x_offset = text_height + 1.3

    try:
        proj_settings = panel._build_settings()
        station_prefix = proj_settings.get_station_prefix()
    except Exception:
        station_prefix = ""

    def fmt_elev(value):
        if value is None:
            return f"{0:.{elev_decimals}f}"
        return f"{value:.{elev_decimals}f}"

    lines = []

    # pl 命令
    h_line_y_values = [0, 15, 30, 45, 75, 100, 110, 120]
    for hy in h_line_y_values:
        lines.append(f"pl {fmt(sx(0))},{hy} -40,{hy} ")
    lines.append(f"pl -40,0 -40,{s_y_line_height} ")
    lines.append("")

    tall_line_mcs = []
    for idx, node in enumerate(nodes):
        mc_scaled = fmt(sx(node.station_MC))
        is_special = (idx == 0 or idx == len(nodes) - 1)
        if not is_special and (_is_special_structure_sv(node.structure_type) and
                               _in_out_val(node.in_out) in ("进", "出")):
            is_special = True
        if is_special:
            tall_line_mcs.append(node.station_MC)
        height = s_y_line_height if is_special else "100"
        lines.append(f"pl {mc_scaled},0 {mc_scaled},{height} ")
    lines.append("")

    last_mc_scaled = fmt(sx(nodes[-1].station_MC))
    for hy in h_line_y_values:
        lines.append(f"pl {fmt(sx(0))},{hy} {last_mc_scaled},{hy} ")
    lines.append("")

    for node in valid_nodes:
        if node.bottom_elevation:
            lines.append(f"pl {fmt(sx(node.station_MC))},{fmt(sy(node.bottom_elevation))}")
    lines.append("")
    for node in valid_nodes:
        if node.top_elevation:
            lines.append(f"pl {fmt(sx(node.station_MC))},{fmt(sy(node.top_elevation))}")
    lines.append("")
    for node in valid_nodes:
        if node.water_level:
            lines.append(f"pl {fmt(sx(node.station_MC))},{fmt(sy(node.water_level))}")
    lines.append("")

    # -text 命令
    for idx, node in enumerate(nodes):
        mc = fmt(sx(node.station_MC))
        text_x = fmt(sx(node.station_MC) + first_col_x_offset) if idx == 0 else mc
        lines.append(
            f"-text {text_x},{s_y_bottom} {s_height} {s_rotation} {fmt_elev(node.bottom_elevation)} ")
    lines.append("")
    for idx, node in enumerate(nodes):
        mc = fmt(sx(node.station_MC))
        text_x = fmt(sx(node.station_MC) + first_col_x_offset) if idx == 0 else mc
        lines.append(
            f"-text {text_x},{s_y_top} {s_height} {s_rotation} {fmt_elev(node.top_elevation)} ")
    lines.append("")
    for idx, node in enumerate(nodes):
        mc = fmt(sx(node.station_MC))
        text_x = fmt(sx(node.station_MC) + first_col_x_offset) if idx == 0 else mc
        lines.append(
            f"-text {text_x},{s_y_water} {s_height} {s_rotation} {fmt_elev(node.water_level)} ")
    lines.append("")

    for idx, node in enumerate(nodes):
        mc = fmt(sx(node.station_MC))
        text_x = fmt(sx(node.station_MC) + first_col_x_offset) if idx == 0 else mc
        station_text = ProjectSettings.format_station(node.station_MC, station_prefix)
        lines.append(
            f"-text {text_x},{s_y_station} {s_height} {s_rotation} {station_text} ")
    lines.append("")

    header_col_width = 40
    header_single = [
        ("建筑物名称", 110, 120),
        ("坡 降", 100, 110),
        ("IP点名称", 75, 100),
        ("渠顶高程(m)", 30, 45),
        ("设计水位(m)", 15, 30),
        ("渠底高程(m)", 0, 15),
    ]
    header_cx = fmt(-40 + header_col_width / 2)
    for label, row_bot, row_top in header_single:
        cy = (row_bot + row_top) / 2
        lines.append(f"-text j mc {header_cx},{fmt(cy)} {s_height} 0 {label} ")
    line_spacing = text_height * 2.5
    block_h = line_spacing + text_height
    y_line_bottom_val = 45 + (30 - block_h) / 2 + text_height / 2
    y_line_top_val = y_line_bottom_val + line_spacing
    for label, y_pos in [("里程桩号", y_line_top_val), ("（千米+米）", y_line_bottom_val)]:
        lines.append(f"-text j mc {header_cx},{fmt(y_pos)} {s_height} 0 {label} ")
    lines.append("")

    name_mc_pairs = []
    for node in nodes:
        building_name = _get_building_display_name(node)
        if building_name:
            name_mc_pairs.append((building_name, node.station_MC))
    building_segments = []
    for bname, bmc in name_mc_pairs:
        if building_segments and building_segments[-1][0] == bname:
            building_segments[-1][1].append(bmc)
        else:
            building_segments.append((bname, [bmc]))
    building_segments = _merge_segments_across_gates(building_segments)
    for bname, mc_list in building_segments:
        if _is_gate_name(bname):
            mid_mc = mc_list[0]
        else:
            seg_start = mc_list[0]
            seg_end = mc_list[-1]
            left_bound = max((m for m in tall_line_mcs if m <= seg_start), default=seg_start)
            right_bound = min((m for m in tall_line_mcs if m >= seg_end), default=seg_end)
            mid_mc = (left_bound + right_bound) / 2.0
        lines.append(f"-text j mc {fmt(sx(mid_mc))},115 {s_height} 0 {bname} ")
    lines.append("")

    # 坡降（从建筑物名称分段派生，与名称行一一对齐）
    mc_to_node = {node.station_MC: node for node in nodes}
    for bname, mc_list in building_segments:
        # 闸/分水口：不显示坡降
        if _is_gate_name(bname):
            continue
        # 倒虹吸为有压流，不显示坡降
        if "倒虹吸" in bname:
            continue
        slope_text = _get_segment_slope_text(mc_list, mc_to_node)
        if not slope_text:
            continue
        # 居中位置与上方建筑物名称完全对齐
        seg_start = mc_list[0]
        seg_end = mc_list[-1]
        left_bound = max((m for m in tall_line_mcs if m <= seg_start), default=seg_start)
        right_bound = min((m for m in tall_line_mcs if m >= seg_end), default=seg_end)
        mid_mc = (left_bound + right_bound) / 2.0
        lines.append(f"-text j mc {fmt(sx(mid_mc))},105 {s_height} 0 {slope_text} ")
    lines.append("")

    for idx, node in enumerate(nodes):
        struct_str = node.get_structure_type_str() or ""
        if node.is_transition or struct_str == "渐变段":
            continue
        if _is_special_structure_sv(node.structure_type):
            if _in_out_val(node.in_out) in ("进", "出"):
                struct_abbr = ""
                st_val = _struct_val(node.structure_type)
                if "隧洞" in st_val:
                    struct_abbr = "隧"
                elif "倒虹吸" in st_val:
                    struct_abbr = "倒"
                elif "渡槽" in st_val:
                    struct_abbr = "渡"
                in_out_str = "进" if _in_out_val(node.in_out) == "进" else "出"
                ip_name = f"{node.name}{struct_abbr}{in_out_str}"
            else:
                continue
        else:
            ip_name = f"{station_prefix}IP{getattr(node, 'ip_number', 0)}"
        mc = fmt(sx(node.station_MC))
        text_x = fmt(sx(node.station_MC) + first_col_x_offset) if node.station_MC == nodes[0].station_MC else mc
        lines.append(
            f"-text {text_x},77 {s_height} {s_rotation} {ip_name} ")
    lines.append("")

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        if fluent_question(panel.window(), "完成",
                f"上纵断面表格已生成（{len(nodes)} 个节点）:\n{file_path}\n\n是否立即打开该文件？"):
            os.startfile(file_path)
    except PermissionError:
        fluent_error(panel.window(), "文件被占用",
                     f"无法写入文件，该文件可能已被其他程序打开：\n\n{file_path}\n\n"
                     f"请先关闭该文件（如记事本、Word等），然后重新操作。")
    except Exception as e:
        import traceback; traceback.print_exc()
        fluent_error(panel.window(), "导出错误", f"生成上纵断面表格失败:\n{str(e)}")


# ================================================================
# 2. 生成bzzh2命令内容
# ================================================================

def extract_bzzh2_data(panel):
    """bzzh2命令提取工具

    从计算结果中提取所有有进出口标识（进/出）的建筑物节点，
    按桩号排序，整理为制表符分隔的TXT文件，供ZDM的bzzh2命令使用。
    """
    if not MODELS_AVAILABLE:
        fluent_info(panel.window(), "不可用", "核心模型未加载")
        return

    nodes = panel.calculated_nodes
    if not nodes:
        fluent_info(panel.window(), "警告", "表格中没有数据，请先导入或输入数据。")
        return

    try:
        proj_settings = panel._build_settings()
        station_prefix = proj_settings.get_station_prefix()
    except Exception:
        station_prefix = ""

    bzzh2_rows = []
    for node in nodes:
        try:
            in_out = getattr(node, 'in_out', None)
            if _in_out_val(in_out) not in ("进", "出"):
                continue
            if getattr(node, 'is_transition', False):
                continue

            station_mc = getattr(node, 'station_MC', 0.0)
            if not isinstance(station_mc, (int, float)):
                station_mc = 0.0
            station_str = ProjectSettings.format_station(station_mc, station_prefix)

            struct_name = ""
            struct_str = _struct_val(node.structure_type)
            if struct_str:
                if "隧洞" in struct_str:
                    struct_name = "隧洞"
                elif "倒虹吸" in struct_str:
                    struct_name = "倒虹吸"
                elif "渡槽" in struct_str:
                    struct_name = "渡槽"
                elif "暗涵" in struct_str:
                    struct_name = "暗涵"
                else:
                    struct_name = struct_str

            in_out_str = "进" if _in_out_val(in_out) == "进" else "出"
            name = getattr(node, 'name', '') or ''
            desc = f"{name}{struct_name}{in_out_str}"
            bzzh2_rows.append((station_str, desc))
        except Exception as node_err:
            import traceback; traceback.print_exc()
            print(f"[bzzh2] 跳过节点（处理异常）: {node_err}")
            continue

    if not bzzh2_rows:
        fluent_info(
            panel.window(), "无可提取数据",
            "未找到有进出口标识的建筑物节点。\n\n"
            "bzzh2命令需要隧洞、倒虹吸、渡槽等建筑物的进/出口数据。\n"
            "请确保表格中已有相关数据并完成计算。")
        return

    # 预览对话框
    preview_dlg = QDialog(panel.window())
    preview_dlg.setWindowTitle("预览 — bzzh2命令数据（ZDM用）")
    preview_dlg.setMinimumSize(600, 400)
    preview_dlg.setStyleSheet(DIALOG_STYLE)
    dlg_lay = QVBoxLayout(preview_dlg)

    dlg_lay.addWidget(QLabel(
        f"共 {len(bzzh2_rows)} 条建筑物进出口数据，请确认内容后点击「确认导出」保存为TXT文件。"))

    table = QTableWidget(len(bzzh2_rows), 2)
    table.setHorizontalHeaderLabels(["桩号", "说明"])
    table.horizontalHeader().setStretchLastSection(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setAlternatingRowColors(True)
    for i, (s, d) in enumerate(bzzh2_rows):
        table.setItem(i, 0, QTableWidgetItem(s))
        table.setItem(i, 1, QTableWidgetItem(d))
    auto_resize_table(table)
    dlg_lay.addWidget(table)

    btn_lay = QHBoxLayout()
    btn_lay.addStretch()
    btn_cancel = PushButton("取消"); btn_cancel.clicked.connect(preview_dlg.reject)
    btn_ok = PrimaryPushButton("确认导出"); btn_ok.clicked.connect(preview_dlg.accept)
    btn_lay.addWidget(btn_cancel); btn_lay.addWidget(btn_ok)
    dlg_lay.addLayout(btn_lay)

    # 绑定 ESC 关闭 / Enter 确认
    QShortcut(QKeySequence(Qt.Key_Escape), preview_dlg, preview_dlg.reject)
    QShortcut(QKeySequence(Qt.Key_Return), preview_dlg, preview_dlg.accept)

    if preview_dlg.exec() != QDialog.Accepted:
        return

    # 保存文件
    try:
        ch_name = panel.channel_name_edit.text().strip()
        ch_level = panel.channel_level_combo.currentText()
        auto_name = f"{ch_name}{ch_level}_ZDM的bzzh2命令.txt"
    except Exception:
        auto_name = "ZDM的bzzh2命令.txt"

    file_path, _ = QFileDialog.getSaveFileName(
        panel, "保存bzzh2命令数据", auto_name,
        "文本文件 (*.txt);;所有文件 (*.*)")
    if not file_path:
        return

    try:
        with open(file_path, 'w', encoding='gbk', errors='replace') as f:
            for station_str, desc in bzzh2_rows:
                f.write(f"{station_str}\t{desc}\t\n")

        if fluent_question(panel.window(), "提取完成",
                f"bzzh2命令数据提取成功！\n\n"
                f"文件保存路径:\n{file_path}\n\n"
                f"导出数据行数: {len(bzzh2_rows)}\n\n"
                f"请使用ZDM的bzzh2命令完成建筑物进出口上平面图。\n\n"
                f"是否要立即打开该txt文件？"):
            try:
                os.startfile(file_path)
            except AttributeError:
                import subprocess
                subprocess.Popen(['xdg-open', file_path])
            except Exception:
                fluent_info(panel.window(), "打开文件",
                            f"无法自动打开文件，请手动打开:\n\n{file_path}")
    except PermissionError:
        fluent_error(panel.window(), "文件被占用",
                     f"无法写入文件，该文件可能已被其他程序打开：\n\n{file_path}\n\n"
                     f"请先关闭该文件（如记事本、Word等），然后重新操作。")
    except Exception as e:
        import traceback; traceback.print_exc()
        fluent_error(panel.window(), "提取失败",
                     f"bzzh2命令数据提取过程中发生错误:\n\n{str(e)}")


# ================================================================
# 3. 建筑物名称上平面图
# ================================================================

def export_building_name_plan(panel):
    """生成「平行于轴线的建筑物名称上平面图」AutoCAD -TEXT 命令

    对于进出口之间有多个IP点的建筑物，文字放置在最中间两个相邻
    IP点连线段的中点处（垂直偏移），方向角取该中间线段的方向。
    """
    if not MODELS_AVAILABLE:
        fluent_info(panel.window(), "不可用", "核心模型未加载")
        return

    nodes = panel.calculated_nodes
    if not nodes:
        fluent_info(panel.window(), "警告", "表格中没有数据，请先导入或输入数据。")
        return

    try:
        # 按建筑物分组收集所有节点
        building_groups = {}
        building_order = []
        for node in nodes:
            if node.is_transition or getattr(node, 'is_auto_inserted_channel', False):
                continue
            if not node.name:
                continue
            key = (node.name, _struct_val(node.structure_type))
            if key not in building_groups:
                building_groups[key] = []
                building_order.append(key)
            building_groups[key].append(node)

        # 筛选有完整进出口且坐标有效的建筑物
        valid_buildings = []
        for key in building_order:
            group = building_groups[key]
            has_inlet = any(_in_out_val(n.in_out) == "进" for n in group)
            has_outlet = any(_in_out_val(n.in_out) == "出" for n in group)
            if not (has_inlet and has_outlet):
                continue
            coord_nodes = [n for n in group
                           if n.x is not None and n.y is not None and
                           (n.x != 0 or n.y != 0)]
            if len(coord_nodes) >= 2:
                valid_buildings.append((key, group, coord_nodes))

        if not valid_buildings:
            fluent_info(
                panel.window(), "无可提取数据",
                "未找到有效的建筑物进出口数据。\n\n"
                "需要隧洞、倒虹吸、渡槽等建筑物同时存在进口和出口，\n"
                "且节点具有有效的X、Y坐标。")
            return

        # 参数设置对话框
        dlg = PlanTextSettingsDialog(panel.window(), panel._plan_text_settings)
        if dlg.exec() != QDialog.Accepted or dlg.result is None:
            return

        panel._plan_text_settings.update(dlg.result)
        offset = dlg.result['offset']
        text_height = dlg.result['text_height']

        # 生成 -TEXT 命令
        text_commands = []
        for key, all_nodes, coord_nodes in valid_buildings:
            N = len(coord_nodes)
            mid_right = N // 2
            mid_left = mid_right - 1

            node_a = coord_nodes[mid_left]
            node_b = coord_nodes[mid_right]
            x1, y1 = node_a.x, node_a.y
            x2, y2 = node_b.x, node_b.y

            dx = x2 - x1
            dy = y2 - y1
            if abs(dx) < 1e-10 and abs(dy) < 1e-10:
                continue

            mx = (x1 + x2) / 2
            my = (y1 + y2) / 2
            angle_rad = math.atan2(dy, dx)
            angle_deg = math.degrees(angle_rad)

            text_x = mx - offset * math.sin(angle_rad)
            text_y = my + offset * math.cos(angle_rad)

            inlet_node = next(
                (n for n in all_nodes if _in_out_val(n.in_out) == "进"),
                all_nodes[0])
            struct_name = ""
            struct_str = _struct_val(inlet_node.structure_type)
            if struct_str:
                if "隧洞" in struct_str:
                    struct_name = "隧洞"
                elif "倒虹吸" in struct_str:
                    struct_name = "倒虹吸"
                elif "渡槽" in struct_str:
                    struct_name = "渡槽"
                elif "暗涵" in struct_str:
                    struct_name = "暗涵"
                else:
                    struct_name = struct_str

            building_name = f"{inlet_node.name or ''}{struct_name}"
            cmd = (f"-TEXT J MC {text_x},{text_y} "
                   f"{text_height} {angle_deg} {building_name}")
            text_commands.append((building_name, N, cmd))

        if not text_commands:
            fluent_info(panel.window(), "无有效数据",
                        "没有生成任何 -TEXT 命令，请检查建筑物坐标。")
            return

        # 显示预览
        all_cmds_text = "\n".join(cmd for _, _, cmd in text_commands)

        preview = QDialog(panel.window())
        preview.setWindowTitle(f"建筑物名称上平面图 — {len(text_commands)} 条命令")
        preview.setMinimumSize(700, 400)
        preview.setStyleSheet(DIALOG_STYLE)
        p_lay = QVBoxLayout(preview)

        p_lay.addWidget(QLabel(
            f"共 {len(text_commands)} 个建筑物  |  "
            f"偏移距离: {offset}  |  文字高度: {text_height}"))

        text_widget = QTextEdit()
        text_widget.setReadOnly(True)
        text_widget.setFont(QFont("Consolas", 10))
        html_parts = []
        for i, (name, node_count, cmd) in enumerate(text_commands):
            comment = f"' [{i+1}] {name}（{node_count}个IP点）"
            html_parts.append(f'<span style="color:gray">{comment}</span><br>')
            html_parts.append(f'{cmd}<br><br>')
        text_widget.setHtml('<pre style="font-family:Consolas;font-size:10pt">' +
                            ''.join(html_parts) + '</pre>')
        p_lay.addWidget(text_widget)

        btn_lay = QHBoxLayout()
        status_label = QLabel("")
        status_label.setStyleSheet("color: green;")
        btn_lay.addWidget(status_label)
        btn_lay.addStretch()

        def copy_commands_only():
            QApplication.clipboard().setText(all_cmds_text)
            status_label.setText("✓ 已复制纯命令到剪贴板，可直接粘贴到 AutoCAD")

        def copy_all_content():
            QApplication.clipboard().setText(text_widget.toPlainText())
            status_label.setText("✓ 已复制全部内容到剪贴板（含注释）")

        btn_copy_all = PushButton("复制全部内容")
        btn_copy_all.clicked.connect(copy_all_content)
        btn_copy_cmd = PrimaryPushButton("复制纯命令")
        btn_copy_cmd.clicked.connect(copy_commands_only)
        btn_close = PushButton("关闭")
        btn_close.clicked.connect(preview.close)
        btn_lay.addWidget(btn_copy_all)
        btn_lay.addWidget(btn_copy_cmd)
        btn_lay.addWidget(btn_close)
        p_lay.addLayout(btn_lay)

        preview.exec()

    except Exception as e:
        import traceback; traceback.print_exc()
        fluent_error(panel.window(), "生成失败",
                     f"建筑物名称上平面图生成过程中发生错误:\n\n{str(e)}")


# ================================================================
# 4. IP坐标及弯道参数表
# ================================================================

def _write_ip_table_dxf(file_path, preview_data, title="IP坐标及弯道参数表"):
    """将IP坐标及弯道参数表写入DXF文件（紧凑排版、自适应列宽、无底色）"""
    import ezdxf

    # 样式常量（单位: mm）
    ROW_H = 6.0
    HDR_ROW_H = 6.0
    TITLE_ROW_H = 7.0
    TEXT_H = 2.2
    HDR_TEXT_H = 2.5
    TITLE_TEXT_H = 3.0
    COL_PAD = 2.0

    # 11列的第二行表头
    sub_headers = [
        "IP点", "E（m）", "N（m）",
        "弯前(千米+米)", "弯中(千米+米)", "弯末(千米+米)",
        "转角", "半径", "切线长", "弧长", "底高程(m)",
    ]
    # 第一行分组表头 (start_col, end_col, text)
    group_headers = [
        (0, 0, "IP点"),
        (1, 2, "坐标值"),
        (3, 5, "桩号"),
        (6, 9, "弯道参数"),
        (10, 10, "底高程(m)"),
    ]
    v_merged = {0, 10}  # 垂直合并（上下两行合并）的列
    ncols = 11
    nrows = len(preview_data)

    # 估算文字宽度（已计入宽度因子0.7）
    _wf = 0.7
    def _tw(text, h):
        if text is None:
            return 0.0
        return sum(h * _wf if ord(c) > 0x7F else h * 0.6 * _wf for c in str(text))

    # 自适应列宽
    col_w = [0.0] * ncols
    for ci, hdr in enumerate(sub_headers):
        col_w[ci] = _tw(hdr, HDR_TEXT_H)
    # 分组表头也参与宽度计算（按平均分配到子列）
    for sc, ec, gtxt in group_headers:
        span = ec - sc + 1
        gw_each = _tw(gtxt, HDR_TEXT_H) / span
        for ci in range(sc, ec + 1):
            col_w[ci] = max(col_w[ci], gw_each)
    for row in preview_data:
        for ci, val in enumerate(row):
            if ci < ncols:
                col_w[ci] = max(col_w[ci], _tw(val, TEXT_H))
    col_w = [w + COL_PAD for w in col_w]

    # 坐标轴
    ox, oy = 0.0, 0.0
    col_x = [ox]
    for w in col_w:
        col_x.append(col_x[-1] + w)
    total_w = col_x[-1] - col_x[0]
    x_left, x_right = col_x[0], col_x[-1]

    # Y坐标（向下为负）
    y_title_top = oy
    y_title_bot = y_title_top - TITLE_ROW_H
    y_hdr1_bot = y_title_bot - HDR_ROW_H
    y_hdr2_bot = y_hdr1_bot - HDR_ROW_H
    y_data_top = y_hdr2_bot
    row_y = [y_data_top]
    for _ in range(nrows):
        row_y.append(row_y[-1] - ROW_H)

    # 创建 DXF
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    if "Standard" in doc.styles:
        _sty = doc.styles.get("Standard")
    else:
        _sty = doc.styles.add("Standard")
    _sty.dxf.font = ""            # 清除 SHX 引用
    _sty.dxf.width = 0.7
    try:
        if "ACAD" not in doc.appids:
            doc.appids.new("ACAD")
    except Exception:
        pass
    _sty.set_xdata("ACAD", [(1000, "仿宋"), (1071, 0)])
    layer = "IP_TABLE"
    dxa = {"layer": layer}

    # === 标题行 ===
    msp.add_line((x_left, y_title_top), (x_right, y_title_top), dxfattribs=dxa)
    msp.add_line((x_left, y_title_bot), (x_right, y_title_bot), dxfattribs=dxa)
    msp.add_line((x_left, y_title_top), (x_left, y_title_bot), dxfattribs=dxa)
    msp.add_line((x_right, y_title_top), (x_right, y_title_bot), dxfattribs=dxa)
    msp.add_text(
        title,
        dxfattribs={"layer": layer, "height": TITLE_TEXT_H,
                    "width": 0.7, "style": "Standard"}
    ).set_placement(
        (x_left + total_w / 2, (y_title_top + y_title_bot) / 2),
        align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER,
    )

    # === 表头区边框 ===
    msp.add_line((x_left, y_hdr2_bot), (x_right, y_hdr2_bot), dxfattribs=dxa)
    msp.add_line((x_left, y_title_bot), (x_left, y_hdr2_bot), dxfattribs=dxa)
    msp.add_line((x_right, y_title_bot), (x_right, y_hdr2_bot), dxfattribs=dxa)

    # 表头中间水平线（仅非垂直合并列）
    for ci in range(ncols):
        if ci not in v_merged:
            msp.add_line((col_x[ci], y_hdr1_bot), (col_x[ci + 1], y_hdr1_bot),
                         dxfattribs=dxa)

    # 表头竖线
    drawn_x = set()
    for sc, ec, _ in group_headers:
        for bx in (col_x[sc], col_x[ec + 1]):
            if bx not in drawn_x:
                msp.add_line((bx, y_title_bot), (bx, y_hdr2_bot), dxfattribs=dxa)
                drawn_x.add(bx)
        if sc != ec:
            for ci in range(sc + 1, ec + 1):
                msp.add_line((col_x[ci], y_hdr1_bot), (col_x[ci], y_hdr2_bot),
                             dxfattribs=dxa)

    # 第一行分组表头文字
    for sc, ec, text in group_headers:
        cx = (col_x[sc] + col_x[ec + 1]) / 2
        cy = ((y_title_bot + y_hdr2_bot) / 2 if sc in v_merged
              else (y_title_bot + y_hdr1_bot) / 2)
        msp.add_text(
            text,
            dxfattribs={"layer": layer, "height": HDR_TEXT_H,
                        "width": 0.7, "style": "Standard"}
        ).set_placement((cx, cy), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)

    # 第二行子表头文字
    for ci, hdr in enumerate(sub_headers):
        if ci in v_merged:
            continue
        cx = (col_x[ci] + col_x[ci + 1]) / 2
        cy = (y_hdr1_bot + y_hdr2_bot) / 2
        msp.add_text(
            hdr,
            dxfattribs={"layer": layer, "height": HDR_TEXT_H,
                        "width": 0.7, "style": "Standard"}
        ).set_placement((cx, cy), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)

    # === 数据区 ===
    msp.add_line((x_left, y_data_top), (x_right, y_data_top), dxfattribs=dxa)
    if nrows > 0:
        msp.add_line((x_left, row_y[-1]), (x_right, row_y[-1]), dxfattribs=dxa)
    for ri in range(1, nrows):
        msp.add_line((x_left, row_y[ri]), (x_right, row_y[ri]), dxfattribs=dxa)

    y_bottom = row_y[-1] if nrows > 0 else y_data_top
    for x in col_x:
        msp.add_line((x, y_data_top), (x, y_bottom), dxfattribs=dxa)

    # 数据文字
    for ri, row_vals in enumerate(preview_data):
        for ci, val in enumerate(row_vals):
            if val is None or val == "":
                continue
            cx = (col_x[ci] + col_x[ci + 1]) / 2
            cy = (row_y[ri] + row_y[ri + 1]) / 2
            msp.add_text(
                str(val),
                dxfattribs={"layer": layer, "height": TEXT_H,
                            "width": 0.7, "style": "Standard"}
            ).set_placement((cx, cy), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)

    doc.saveas(file_path)


def export_ip_plan_table(panel):
    """导出IP坐标及弯道参数表DXF/Excel文件（含合并表头、桩号格式化）"""
    if not MODELS_AVAILABLE:
        fluent_info(panel.window(), "不可用", "核心模型未加载")
        return

    nodes = panel.calculated_nodes
    if not nodes:
        fluent_info(panel.window(), "警告", "没有数据可导出，请先执行计算")
        return

    try:
        import openpyxl
        from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
    except ImportError:
        fluent_info(panel.window(), "缺少依赖",
                    "需要安装 openpyxl: pip install openpyxl")
        return

    try:
        try:
            proj_settings = panel._build_settings()
            station_prefix = proj_settings.get_station_prefix()
        except Exception:
            station_prefix = ""

        def _safe_float(val, default=0.0):
            if val is None:
                return default
            try:
                return float(val)
            except (TypeError, ValueError):
                return default

        def _format_ip_name(node):
            try:
                if _in_out_val(node.in_out) in ("进", "出"):
                    struct_abbr = ""
                    struct_str = _struct_val(node.structure_type)
                    if struct_str:
                        if "隧洞" in struct_str: struct_abbr = "隧"
                        elif "倒虹吸" in struct_str: struct_abbr = "倒"
                        elif "渡槽" in struct_str: struct_abbr = "渡"
                        elif "暗涵" in struct_str: struct_abbr = "暗"
                    in_out_str = "进" if _in_out_val(node.in_out) == "进" else "出"
                    return f"{node.name}{struct_abbr}{in_out_str}"
            except Exception:
                pass
            return f"{station_prefix}IP{getattr(node, 'ip_number', 0)}"

        def _format_station(value):
            return ProjectSettings.format_station(_safe_float(value), station_prefix)

        # 过滤节点
        real_nodes = [
            n for n in nodes
            if not getattr(n, 'is_transition', False)
            and not getattr(n, 'is_auto_inserted_channel', False)
        ]

        if not real_nodes:
            fluent_info(panel.window(), "警告", "没有有效的IP点数据可导出")
            return

        # 构建预览数据
        preview_headers = [
            "IP点", "E（m）", "N（m）",
            "弯前(千米+米)", "弯中(千米+米)", "弯末(千米+米)",
            "转角", "半径", "切线长", "弧长", "底高程\nm"
        ]
        preview_data = []
        for idx, node in enumerate(real_nodes):
            try:
                row = [
                    _format_ip_name(node),
                    f"{_safe_float(node.x):.6f}",
                    f"{_safe_float(node.y):.6f}",
                    _format_station(node.station_BC),
                    _format_station(node.station_MC),
                    _format_station(node.station_EC),
                    f"{_safe_float(node.turn_angle):.3f}",
                    f"{_safe_float(node.turn_radius):.3f}",
                    f"{_safe_float(node.tangent_length):.3f}",
                    f"{_safe_float(node.arc_length):.3f}",
                    f"{_safe_float(node.bottom_elevation):.3f}",
                ]
                preview_data.append(row)
            except Exception as row_err:
                print(f"[警告] 第{idx}行数据格式化失败: {row_err}")
                import traceback; traceback.print_exc()
                preview_data.append([
                    f"IP{getattr(node, 'ip_number', '?')}",
                    "0.000000", "0.000000",
                    "0+000.000", "0+000.000", "0+000.000",
                    "0.000", "0.000", "0.000", "0.000", "0.000",
                ])

        # 预览对话框
        preview_dlg = QDialog(panel.window())
        preview_dlg.setWindowTitle("预览 — IP坐标及弯道参数表")
        preview_dlg.setMinimumSize(950, 450)
        preview_dlg.setStyleSheet(DIALOG_STYLE)
        dlg_lay = QVBoxLayout(preview_dlg)

        dlg_lay.addWidget(QLabel(
            f"共 {len(preview_data)} 条IP点数据，请确认内容后点击「确认导出」保存为DXF或Excel文件。"))

        table = QTableWidget(len(preview_data), len(preview_headers))
        table.setHorizontalHeaderLabels(preview_headers)
        table.horizontalHeader().setStretchLastSection(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        for r, row_data in enumerate(preview_data):
            for c, val in enumerate(row_data):
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(Qt.AlignCenter)
                table.setItem(r, c, item)
        auto_resize_table(table)
        dlg_lay.addWidget(table)

        btn_lay = QHBoxLayout()
        btn_lay.addStretch()
        btn_cancel = PushButton("取消"); btn_cancel.clicked.connect(preview_dlg.reject)
        btn_ok = PrimaryPushButton("确认导出"); btn_ok.clicked.connect(preview_dlg.accept)
        btn_lay.addWidget(btn_cancel); btn_lay.addWidget(btn_ok)
        dlg_lay.addLayout(btn_lay)

        # 绑定 ESC 关闭 / Enter 确认
        QShortcut(QKeySequence(Qt.Key_Escape), preview_dlg, preview_dlg.reject)
        QShortcut(QKeySequence(Qt.Key_Return), preview_dlg, preview_dlg.accept)

        if preview_dlg.exec() != QDialog.Accepted:
            return

        # 保存
        try:
            ch_name = panel.channel_name_edit.text().strip()
            ch_level = panel.channel_level_combo.currentText()
            auto_name = f"{ch_name}{ch_level}_IP坐标及弯道参数表.dxf"
        except Exception:
            auto_name = "IP坐标及弯道参数表.dxf"

        file_path, _ = QFileDialog.getSaveFileName(
            panel, "保存IP坐标及弯道参数表", auto_name,
            "DXF文件 (*.dxf);;Excel文件 (*.xlsx);;所有文件 (*.*)")
        if not file_path:
            return

        # DXF 导出（紧凑排版、自适应列宽、无底色）
        if file_path.lower().endswith('.dxf'):
            _write_ip_table_dxf(file_path, preview_data)
            if fluent_question(panel.window(), "导出完成",
                    f"IP坐标及弯道参数表DXF导出成功！\n\n"
                    f"文件保存路径:\n{file_path}\n\n"
                    f"导出IP点数量: {len(real_nodes)}\n\n"
                    f"是否要立即打开该文件？"):
                try:
                    os.startfile(file_path)
                except Exception:
                    pass
            return

        # openpyxl 写入
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "IP点上平面图"

        thin_border = Border(
            left=Side(style='thin'), right=Side(style='thin'),
            top=Side(style='thin'), bottom=Side(style='thin'))
        header_font = Font(name='Microsoft YaHei', size=10, bold=True)
        data_font = Font(name='Microsoft YaHei', size=10)
        center_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
        left_align = Alignment(horizontal='left', vertical='center')
        header_fill = PatternFill(start_color='D9E1F2', end_color='D9E1F2', fill_type='solid')

        ws.cell(row=1, column=1, value="IP点")
        ws.cell(row=1, column=2, value="坐标值")
        ws.cell(row=1, column=4, value="桩号")
        ws.cell(row=1, column=7, value="弯道参数")
        ws.cell(row=1, column=11, value="底高程\nm")
        ws.cell(row=2, column=2, value="E（m）")
        ws.cell(row=2, column=3, value="N（m）")
        ws.cell(row=2, column=4, value="弯前(千米+米)")
        ws.cell(row=2, column=5, value="弯中(千米+米)")
        ws.cell(row=2, column=6, value="弯末(千米+米)")
        ws.cell(row=2, column=7, value="转角")
        ws.cell(row=2, column=8, value="半径")
        ws.cell(row=2, column=9, value="切线长")
        ws.cell(row=2, column=10, value="弧长")

        ws.merge_cells('A1:A2')
        ws.merge_cells('B1:C1')
        ws.merge_cells('D1:F1')
        ws.merge_cells('G1:J1')
        ws.merge_cells('K1:K2')

        for row in range(1, 3):
            for col in range(1, 12):
                cell = ws.cell(row=row, column=col)
                cell.font = header_font
                cell.alignment = center_align
                cell.border = thin_border
                cell.fill = header_fill

        for row_idx, node in enumerate(real_nodes, start=3):
            ws.cell(row=row_idx, column=1, value=_format_ip_name(node))
            cell_b = ws.cell(row=row_idx, column=2, value=_safe_float(node.x))
            cell_b.number_format = '0.000000'
            cell_c = ws.cell(row=row_idx, column=3, value=_safe_float(node.y))
            cell_c.number_format = '0.000000'
            ws.cell(row=row_idx, column=4, value=_format_station(node.station_BC))
            ws.cell(row=row_idx, column=5, value=_format_station(node.station_MC))
            ws.cell(row=row_idx, column=6, value=_format_station(node.station_EC))
            cell_g = ws.cell(row=row_idx, column=7,
                             value=round(_safe_float(node.turn_angle), 3))
            cell_g.number_format = '0.000'
            cell_h = ws.cell(row=row_idx, column=8,
                             value=round(_safe_float(node.turn_radius), 3))
            cell_h.number_format = '0.000'
            cell_i = ws.cell(row=row_idx, column=9,
                             value=round(_safe_float(node.tangent_length), 3))
            cell_i.number_format = '0.000'
            cell_j = ws.cell(row=row_idx, column=10,
                             value=round(_safe_float(node.arc_length), 3))
            cell_j.number_format = '0.000'
            cell_k = ws.cell(row=row_idx, column=11,
                             value=round(_safe_float(node.bottom_elevation), 3))
            cell_k.number_format = '0.000'

            for col in range(1, 12):
                cell = ws.cell(row=row_idx, column=col)
                cell.font = data_font
                cell.border = thin_border
                if col == 1:
                    cell.alignment = left_align
                else:
                    cell.alignment = Alignment(horizontal='center', vertical='center')

        # 自适应列宽（根据实际内容计算，避免出现 ###）
        for col_idx in range(1, 12):
            col_letter = chr(64 + col_idx)  # A=1, B=2, ...
            max_len = 0
            for row_idx2 in range(1, ws.max_row + 1):
                cell_val = ws.cell(row=row_idx2, column=col_idx).value
                if cell_val is not None:
                    s = str(cell_val)
                    # CJK字符算2个宽度单位
                    char_w = sum(2 if ord(c) > 0x7F else 1 for c in s)
                    max_len = max(max_len, char_w)
            ws.column_dimensions[col_letter].width = max(max_len + 3, 8)

        wb.save(file_path)
        wb.close()

        if fluent_question(panel.window(), "导出完成",
                f"IP坐标及弯道参数表导出成功！\n\n"
                f"文件保存路径:\n{file_path}\n\n"
                f"导出IP点数量: {len(real_nodes)}\n\n"
                f"是否要立即打开该文件？"):
            try:
                os.startfile(file_path)
            except Exception:
                pass

    except PermissionError:
        fluent_error(panel.window(), "文件被占用",
                     f"无法写入文件，该文件可能已被其他程序打开：\n\n{file_path}\n\n"
                     f"请先关闭该文件（如Excel等），然后重新操作。")
    except Exception as e:
        import traceback
        traceback.print_exc()
        fluent_error(panel.window(), "导出失败",
                     f"IP坐标及弯道参数表导出失败，请检查以下可能的原因：\n\n"
                     f"1. 目标文件是否被其他程序占用（如AutoCAD、Excel等）\n"
                     f"2. 文件保存路径是否有写入权限\n"
                     f"3. 数据是否完整（坐标、桩号等）\n\n"
                     f"错误信息：{str(e)}\n\n"
                     f"如仍无法解决，请将以上信息反馈给技术支持。")


# ================================================================
# 5. 断面汇总表
# ================================================================

class SectionSummaryDialog(QDialog):
    """断面尺寸及水力要素汇总表生成对话框（纯 PySide6 版）"""

    def __init__(self, parent, nodes, proj_settings, auto_name=""):
        super().__init__(parent)
        self.setWindowTitle("断面尺寸及水力要素汇总表 — 生成器")
        self.setMinimumSize(520, 560)
        self.resize(620, 650)
        self.setStyleSheet(DIALOG_STYLE)

        self._nodes = nodes
        self._proj_settings = proj_settings
        self._auto_name = auto_name

        # 导入计算模块
        from 渠系建筑物断面计算.生成断面汇总表 import (
            _extract_segment_defaults_from_nodes,
            _segment_name,
            SIPHON_MATERIALS,
            generate_excel,
            generate_dxf,
            _default_segments_rect_channel,
            _default_segments_trap_channel,
            _default_segments_tunnel_arch,
            _default_segments_tunnel_circular,
            _default_segments_tunnel_horseshoe,
            _default_segments_aqueduct_u,
            _default_segments_aqueduct_rect,
            _default_segments_rect_culvert,
            _default_segments_circular_pipe,
        )
        self._generate_excel = generate_excel
        self._generate_dxf = generate_dxf
        self._segment_name = _segment_name
        self._SIPHON_MATERIALS = SIPHON_MATERIALS
        self._default_fns = {
            'rect_channel': _default_segments_rect_channel,
            'trap_channel': _default_segments_trap_channel,
            'tunnel_arch': _default_segments_tunnel_arch,
            'tunnel_circular': _default_segments_tunnel_circular,
            'tunnel_horseshoe': _default_segments_tunnel_horseshoe,
            'aqueduct_u': _default_segments_aqueduct_u,
            'aqueduct_rect': _default_segments_aqueduct_rect,
            'rect_culvert': _default_segments_rect_culvert,
            'circular_pipe': _default_segments_circular_pipe,
        }

        node_defaults, flow_qs = _extract_segment_defaults_from_nodes(nodes)
        self._node_defaults = node_defaults
        self._flow_qs = flow_qs

        # 提取倒虹吸分组（按名称，支持不同材质和管径）
        self._siphon_groups = self._extract_siphon_groups()

        # 确定流量段数
        self._segment_count = self._get_segment_count()
        default_qs = self._build_default_qs()

        self._build_ui(default_qs)

    # ---- 流量段数计算 ----
    def _get_segment_count(self):
        counts = []
        ps = self._proj_settings
        if ps is not None and getattr(ps, "design_flows", None):
            flows = [q for q in ps.design_flows if isinstance(q, (int, float)) and q > 0]
            if flows:
                counts.append(len(flows))
        if self._flow_qs:
            counts.append(max(self._flow_qs.keys()))
        if self._node_defaults:
            for data in self._node_defaults.values():
                if data:
                    counts.append(max(data.keys()))
        return max(1, max(counts)) if counts else 7

    def _build_default_qs(self):
        fallback = [2.0, 1.3, 0.8, 0.5, 0.4, 0.2, 0.5]
        sc = self._segment_count
        ps = self._proj_settings
        if ps is not None and getattr(ps, "design_flows", None):
            flows = [q for q in ps.design_flows if isinstance(q, (int, float)) and q > 0]
            if flows:
                return [flows[i] if i < len(flows) else flows[-1] for i in range(sc)]
        if self._flow_qs:
            out = []
            for i in range(1, sc + 1):
                q = self._flow_qs.get(i, 0.0)
                out.append(q if q > 0 else (fallback[i - 1] if i - 1 < len(fallback) else fallback[-1]))
            return out
        if sc <= len(fallback):
            return list(fallback[:sc])
        return list(fallback) + [fallback[-1]] * (sc - len(fallback))

    def _extract_siphon_groups(self):
        """从节点中提取不同名称的倒虹吸及其默认DN

        返回: OrderedDict-like list of tuples [(siphon_display_name, dn_mm), ...]
        """
        groups = {}  # {display_name: dn_mm}
        order = []   # 保持顺序
        if not self._nodes:
            return order

        for node in self._nodes:
            if getattr(node, 'is_transition', False) or getattr(node, 'is_auto_inserted_channel', False):
                continue

            # 判断是否为倒虹吸
            is_siphon = getattr(node, 'is_inverted_siphon', False)
            if not is_siphon:
                st_str = _struct_val(getattr(node, 'structure_type', None))
                if '倒虹吸' not in st_str:
                    continue

            # 建筑物名称
            raw_name = getattr(node, 'name', '') or ''
            display_name = raw_name.strip() if raw_name.strip() else '倒虹吸'

            if display_name not in groups:
                groups[display_name] = 0
                order.append(display_name)

            # 提取 DN（优先 section_params.D，其次 structure_height）
            params = getattr(node, 'section_params', {}) or {}
            d_val = 0.0
            for key in ('D', 'd'):
                try:
                    v = float(params.get(key, 0) or 0)
                except (TypeError, ValueError):
                    v = 0.0
                if v > 0:
                    d_val = v
                    break
            if d_val <= 0:
                try:
                    d_val = float(getattr(node, 'structure_height', 0) or 0)
                except (TypeError, ValueError):
                    d_val = 0.0

            if d_val > 0:
                dn_mm = d_val * 1000 if d_val < 20 else d_val
                groups[display_name] = max(groups[display_name], dn_mm)

        return [(name, groups[name]) for name in order]

    # ---- UI 构建 ----
    def _build_ui(self, default_qs):
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        # 提示文字
        desc = QLabel("本功能将自动计算并生成多种建筑物断面水力要素汇总表（Excel），\n"
                      "可直接用于 AutoCAD 制表。")
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size:13px; color:#333;")
        lay.addWidget(desc)

        # ---- 流量段参数 ----
        q_group = QGroupBox("流量段设计流量 Q (m³/s)")
        q_group.setStyleSheet("QGroupBox{font-weight:bold;font-size:12px;}")
        q_lay = QVBoxLayout(q_group)

        q_grid = QGridLayout()
        q_grid.setSpacing(4)

        self._q_edits = []
        for i in range(self._segment_count):
            lbl = QLabel(self._segment_name(i + 1))
            lbl.setStyleSheet("font-size:12px;")
            edit = LineEdit()
            edit.setFixedWidth(100)
            edit.setText(str(default_qs[i] if i < len(default_qs) else default_qs[-1]))
            q_grid.addWidget(lbl, i, 0)
            q_grid.addWidget(edit, i, 1)
            self._q_edits.append(edit)

        q_grid.setColumnStretch(2, 1)
        q_lay.addLayout(q_grid)
        lay.addWidget(q_group)

        # ---- 倒虹吸管道参数（按名称分组） ----
        siphon_group = QGroupBox("倒虹吸管道参数")
        siphon_group.setStyleSheet("QGroupBox{font-weight:bold;font-size:12px;}")
        siphon_lay = QVBoxLayout(siphon_group)

        # 构建倒虹吸分组列表；无数据时提供一个默认行
        siphon_items = self._siphon_groups if self._siphon_groups else [('倒虹吸', 0)]

        # 表头
        hdr_grid = QGridLayout()
        hdr_grid.setSpacing(6)
        for ci, txt in enumerate(['倒虹吸名称', '管道材质', 'DN (mm)']):
            lbl = QLabel(txt)
            lbl.setStyleSheet("font-size:11px; color:#555; font-weight:bold;")
            hdr_grid.addWidget(lbl, 0, ci)
        hdr_grid.setColumnStretch(0, 2)
        hdr_grid.setColumnStretch(1, 3)
        hdr_grid.setColumnStretch(2, 2)
        siphon_lay.addLayout(hdr_grid)

        self._siphon_rows = []  # [(name, mat_combo, dn_edit), ...]
        sp_grid = QGridLayout()
        sp_grid.setSpacing(4)
        for ri, (sp_name, sp_dn) in enumerate(siphon_items):
            # 名称标签
            name_lbl = QLabel(sp_name)
            name_lbl.setStyleSheet("font-size:12px;")
            sp_grid.addWidget(name_lbl, ri, 0)

            # 材质下拉
            mat_combo = QComboBox()
            mat_combo.addItems(list(self._SIPHON_MATERIALS.keys()))
            mat_combo.setCurrentText("球墨铸铁管")
            mat_combo.setFixedWidth(160)
            sp_grid.addWidget(mat_combo, ri, 1)

            # DN 输入框
            dn_edit = LineEdit()
            dn_edit.setFixedWidth(100)
            dn_val = int(round(sp_dn)) if sp_dn > 0 else 1500
            dn_edit.setText(str(dn_val))
            sp_grid.addWidget(dn_edit, ri, 2)

            self._siphon_rows.append((sp_name, mat_combo, dn_edit))

        sp_grid.setColumnStretch(0, 2)
        sp_grid.setColumnStretch(1, 3)
        sp_grid.setColumnStretch(2, 2)
        siphon_lay.addLayout(sp_grid)

        dn_note = QLabel("（DN 从倒虹吸计算结果自动导入，也可手动修改）")
        dn_note.setStyleSheet("font-size:11px; color:#666;")
        siphon_lay.addWidget(dn_note)
        lay.addWidget(siphon_group)

        # ---- 说明 ----
        note_group = QGroupBox("其他参数说明")
        note_group.setStyleSheet("QGroupBox{font-weight:bold;font-size:12px;}")
        note_lay = QVBoxLayout(note_group)
        note_lbl = QLabel(
            "• 底坡、糙率等参数使用内置默认值（可在生成后调整）\n"
            "• 隧洞表按最大流量段设计统一断面，各流量段分别求水深\n"
            "• 隧洞含 III/IV/V 类围岩衬砌厚度\n"
            "• 圆管涵默认材质为钢筋混凝土")
        note_lbl.setWordWrap(True)
        note_lbl.setStyleSheet("font-size:11px; color:#555;")
        note_lay.addWidget(note_lbl)
        lay.addWidget(note_group)

        # ---- 导出格式选择 ----
        from PySide6.QtWidgets import QRadioButton, QButtonGroup
        fmt_group = QGroupBox("导出格式")
        fmt_group.setStyleSheet("QGroupBox{font-weight:bold;font-size:12px;}")
        fmt_lay = QHBoxLayout(fmt_group)
        self._radio_excel = QRadioButton("Excel (.xlsx)  — 多Sheet + 汇总Sheet")
        self._radio_dxf = QRadioButton("DXF (.dxf)  — 可直接导入AutoCAD")
        self._radio_excel.setStyleSheet("font-size:11px;")
        self._radio_dxf.setStyleSheet("font-size:11px;")
        self._radio_excel.setChecked(True)
        self._fmt_btn_group = QButtonGroup(self)
        self._fmt_btn_group.addButton(self._radio_excel, 0)
        self._fmt_btn_group.addButton(self._radio_dxf, 1)
        fmt_lay.addWidget(self._radio_excel)
        fmt_lay.addWidget(self._radio_dxf)
        fmt_lay.addStretch()
        lay.addWidget(fmt_group)

        # ---- 按钮栏 ----
        btn_lay = QHBoxLayout()
        btn_lay.addStretch()
        btn_cancel = PushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_generate = PrimaryPushButton("生成汇总表")
        btn_generate.clicked.connect(self._on_generate)
        btn_lay.addWidget(btn_cancel)
        btn_lay.addWidget(btn_generate)
        lay.addLayout(btn_lay)

    # ---- 生成 ----
    def _on_generate(self):
        from 渠系建筑物断面计算.生成断面汇总表 import (
            _default_segments_rect_channel,
            _default_segments_trap_channel,
            _default_segments_tunnel_arch,
            _default_segments_tunnel_circular,
            _default_segments_tunnel_horseshoe,
            _default_segments_aqueduct_u,
            _default_segments_aqueduct_rect,
            _default_segments_rect_culvert,
            _default_segments_circular_pipe,
            _segment_name,
        )

        # 读取 Q 值
        try:
            qs = [float(e.text()) for e in self._q_edits]
        except ValueError:
            fluent_error(self, "输入错误", "流量值必须为数字")
            return

        # 读取每个倒虹吸的材质和DN
        siphon_params = []  # [(name, material, dn), ...]
        for sp_name, mat_combo, dn_edit in self._siphon_rows:
            try:
                dn = int(dn_edit.text())
            except ValueError:
                fluent_error(self, "输入错误", f"{sp_name} 的 DN 必须为整数")
                return
            siphon_params.append((sp_name, mat_combo.currentText(), dn))

        segment_count = self._segment_count
        node_defaults = self._node_defaults

        # 判断导出格式
        export_dxf = self._radio_dxf.isChecked()
        if export_dxf:
            ext = ".dxf"
            filter_str = "DXF 文件 (*.dxf);;所有文件 (*.*)"
            auto_name = self._auto_name.replace('.xlsx', '.dxf') if self._auto_name else ""
        else:
            ext = ".xlsx"
            filter_str = "Excel 文件 (*.xlsx);;所有文件 (*.*)"
            auto_name = self._auto_name

        # 选择保存路径
        fp, _ = QFileDialog.getSaveFileName(
            self, "保存断面汇总表", auto_name, filter_str)
        if not fp:
            return
        if not fp.lower().endswith(ext):
            fp += ext

        # 构建各表参数
        has_source_data = bool(self._nodes) and any(node_defaults.values())

        def _make_segs(default_fn, overrides_by_idx=None):
            # 有源数据时，只生成有实际节点数据的流量段
            if has_source_data and overrides_by_idx is not None:
                if not overrides_by_idx:
                    return []
                defaults_pool = default_fn()
                segs = []
                for idx in sorted(overrides_by_idx.keys()):
                    # 用默认段作为基础模板
                    base = dict(defaults_pool[0]) if defaults_pool else {}
                    base["name"] = _segment_name(idx)
                    base.update(overrides_by_idx[idx])
                    if 0 < idx <= len(qs):
                        base["Q"] = qs[idx - 1]
                    segs.append(base)
                return segs
            # 无源数据时（独立运行），用默认值生成所有段
            segs = default_fn()
            if len(segs) < segment_count:
                last = segs[-1] if segs else {}
                for idx in range(len(segs) + 1, segment_count + 1):
                    new_seg = dict(last)
                    new_seg["name"] = _segment_name(idx)
                    segs.append(new_seg)
            segs = segs[:segment_count]
            for i, seg in enumerate(segs):
                if overrides_by_idx and (i + 1) in overrides_by_idx:
                    seg.update(overrides_by_idx[i + 1])
                if i < len(qs):
                    seg["Q"] = qs[i]
            return segs

        rc_segs = _make_segs(_default_segments_rect_channel, node_defaults.get("rect_channel"))
        tr_segs = _make_segs(_default_segments_trap_channel, node_defaults.get("trap_channel"))
        tn_arch_segs = _make_segs(_default_segments_tunnel_arch, node_defaults.get("tunnel_arch"))
        tn_circ_segs = _make_segs(_default_segments_tunnel_circular, node_defaults.get("tunnel_circular"))
        tn_horse_segs = _make_segs(_default_segments_tunnel_horseshoe, node_defaults.get("tunnel_horseshoe"))
        aq_u_segs = _make_segs(_default_segments_aqueduct_u, node_defaults.get("aqueduct_u"))
        aq_rect_segs = _make_segs(_default_segments_aqueduct_rect, node_defaults.get("aqueduct_rect"))
        rv_segs = _make_segs(_default_segments_rect_culvert, node_defaults.get("rect_culvert"))
        cp_segs = _make_segs(_default_segments_circular_pipe, node_defaults.get("circular_channel"))

        if not has_source_data:
            for segs_list in [rc_segs, tr_segs, tn_arch_segs, tn_circ_segs, tn_horse_segs,
                              aq_u_segs, aq_rect_segs, rv_segs, cp_segs]:
                for i, seg in enumerate(segs_list):
                    seg["name"] = _segment_name(i + 1)

        sp_overrides = node_defaults.get("siphon", {})
        sp_segs = []
        multi_siphon = len(siphon_params) > 1
        # 有源数据时只生成有实际数据的流量段
        sp_indices = sorted(sp_overrides.keys()) if (has_source_data and sp_overrides) else list(range(1, len(qs) + 1))
        for sp_name, sp_material, sp_dn in siphon_params:
            for idx in sp_indices:
                seg_name = (f"{sp_name}-{_segment_name(idx)}"
                            if multi_siphon else _segment_name(idx))
                seg = {"name": seg_name}
                if idx in sp_overrides:
                    seg.update(sp_overrides[idx])
                seg["DN_mm"] = sp_dn
                if 0 < idx <= len(qs):
                    seg["Q"] = qs[idx - 1]
                seg["pipe_material"] = sp_material
                sp_segs.append(seg)

        # 按结果决定表格类型
        _table_order = None
        if has_source_data:
            _table_order = []
            if node_defaults.get("rect_channel"):
                _table_order.append("rect_channel")
            if node_defaults.get("trap_channel"):
                _table_order.append("trap_channel")
            if node_defaults.get("tunnel_arch"):
                _table_order.append("tunnel_arch")
            if node_defaults.get("tunnel_circular"):
                _table_order.append("tunnel_circular")
            if node_defaults.get("tunnel_horseshoe"):
                _table_order.append("tunnel_horseshoe")
            if node_defaults.get("aqueduct_u"):
                _table_order.append("aqueduct_u")
            if node_defaults.get("aqueduct_rect"):
                _table_order.append("aqueduct_rect")
            if node_defaults.get("rect_culvert"):
                _table_order.append("rect_culvert")
            if node_defaults.get("circular_channel"):
                _table_order.append("circular_channel")
            if node_defaults.get("siphon"):
                _table_order.append("siphon")
            if not _table_order:
                _table_order = None

        gen_kwargs = dict(
            filepath=fp,
            rect_channel_segs=rc_segs,
            trap_channel_segs=tr_segs,
            tunnel_arch_segs=tn_arch_segs,
            tunnel_circular_segs=tn_circ_segs,
            tunnel_horseshoe_segs=tn_horse_segs,
            aqueduct_u_segs=aq_u_segs,
            aqueduct_rect_segs=aq_rect_segs,
            rect_culvert_segs=rv_segs,
            circular_pipe_segs=cp_segs,
            siphon_segs=sp_segs,
            siphon_material=siphon_params[0][1] if siphon_params else "球墨铸铁管",
            table_order=_table_order,
        )

        try:
            self.setCursor(Qt.WaitCursor)
            QApplication.processEvents()
            if export_dxf:
                self._generate_dxf(**gen_kwargs)
            else:
                self._generate_excel(**gen_kwargs)
            self.unsetCursor()
            mat_summary = '、'.join(f"{n}({m})" for n, m, _ in siphon_params)
            fmt_name = "DXF" if export_dxf else "Excel"
            extra = "" if export_dxf else "\n表格数量以计算结果为准，另含 1 个汇总 Sheet。"
            if fluent_question(self, "完成",
                        f"断面汇总表已生成（{fmt_name}）：\n{fp}\n{extra}\n"
                        f"倒虹吸管道材质: {mat_summary}\n\n"
                        f"是否立即打开该文件？",
                        yes_text="打开", no_text="关闭"):
                try:
                    os.startfile(fp)
                except Exception:
                    pass
            self.accept()
        except PermissionError:
            self.unsetCursor()
            fluent_error(self, "文件被占用",
                         f"无法写入文件，该文件可能已被其他程序打开：\n\n{fp}\n\n"
                         f"请先关闭该文件，然后重新操作。")
        except Exception as e:
            self.unsetCursor()
            import traceback; traceback.print_exc()
            fluent_error(self, "生成失败", f"错误: {e}")


def open_section_summary_table(panel):
    """打开断面汇总表生成器（纯 PySide6 对话框）"""
    nodes = panel.calculated_nodes
    if not nodes:
        fluent_info(panel.window(), "警告", "没有数据可用，请先执行计算。")
        return

    try:
        proj_settings = panel._build_settings()
    except Exception:
        proj_settings = panel._settings

    try:
        try:
            ch_name = panel.channel_name_edit.text().strip()
            ch_level = panel.channel_level_combo.currentText()
            auto_name = f"{ch_name}{ch_level}_断面汇总表.xlsx"
        except Exception:
            auto_name = "断面汇总表.xlsx"

        dlg = SectionSummaryDialog(panel.window(), nodes, proj_settings, auto_name)
        dlg.exec()
    except ImportError as e:
        fluent_error(
            panel.window(), "功能不可用",
            f"断面汇总表模块加载失败：\n{str(e)}")
    except Exception as e:
        import traceback; traceback.print_exc()
        fluent_error(panel.window(), "打开失败",
                     f"断面汇总表生成器打开失败：\n{str(e)}")
