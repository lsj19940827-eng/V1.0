# -*- coding: utf-8 -*-
"""Shared helpers for multi-case DXF export workflows."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable, Literal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app_渠系计算前端.dxf_common import (
    DEFAULT_SCALE_OPTIONS,
    TrackedSectionMsp,
    compute_auto_grid,
    create_measurement_msp,
    ensure_section_dxf_layers,
    setup_section_dxf_document,
)


ScopeLiteral = Literal["current", "checked", "all"]


@dataclass(frozen=True)
class DxfExportCaseEntry:
    case_idx: int
    label: str
    input_params: dict
    result: dict | None
    is_valid: bool
    invalid_reason: str | None = None


@dataclass(frozen=True)
class DxfExportDialogResult:
    scope: ScopeLiteral
    checked_case_indexes: list[int]
    scale_denom: int


def choose_scale_denom(parent=None, initial_index: int = 2):
    from app_渠系计算前端.styles import fluent_select

    scale_str, ok = fluent_select(
        parent,
        "选择比例尺",
        "输出比例尺 (图纸单位: mm):",
        list(DEFAULT_SCALE_OPTIONS),
        initial_index,
    )
    if not ok:
        return None
    return int(str(scale_str).split(":")[1])


class MultiCaseDxfExportDialog(QDialog):
    def __init__(
        self,
        module_title: str,
        case_entries: list[DxfExportCaseEntry],
        current_case_idx: int,
        parent=None,
    ):
        super().__init__(parent)
        self._entries = list(case_entries)
        self._current_case_idx = int(current_case_idx)
        self._checkboxes: dict[int, QCheckBox] = {}
        self._manual_checked_case_indexes = {self._current_case_idx}
        self._last_scope: ScopeLiteral | None = None

        self.setWindowTitle(f"导出 DXF - {module_title}")
        self.setMinimumSize(720, 460)
        self._build_ui(module_title)
        self._apply_scope_state()

    def _build_ui(self, module_title: str):
        root = QVBoxLayout(self)
        root.setSpacing(10)

        tip = QLabel(
            f"即将导出 <b>{module_title}</b> 的 DXF，请确认导出范围、比例尺和工况列表。"
        )
        tip.setWordWrap(True)
        root.addWidget(tip)

        scope_group = QGroupBox("导出范围")
        scope_layout = QVBoxLayout(scope_group)
        self._scope_current = QRadioButton("当前工况")
        self._scope_checked = QRadioButton("勾选多个工况")
        self._scope_all = QRadioButton("全部工况")
        self._scope_current.setChecked(True)
        self._scope_buttons = QButtonGroup(self)
        self._scope_buttons.addButton(self._scope_current)
        self._scope_buttons.addButton(self._scope_checked)
        self._scope_buttons.addButton(self._scope_all)
        for button in (self._scope_current, self._scope_checked, self._scope_all):
            scope_layout.addWidget(button)
            button.toggled.connect(self._apply_scope_state)
        root.addWidget(scope_group)

        scale_group = QGroupBox("比例尺")
        scale_layout = QHBoxLayout(scale_group)
        scale_layout.addWidget(QLabel("输出比例尺："))
        self._scale_combo = QComboBox()
        self._scale_combo.addItems(list(DEFAULT_SCALE_OPTIONS))
        self._scale_combo.setCurrentIndex(2)
        scale_layout.addWidget(self._scale_combo, 1)
        root.addWidget(scale_group)

        list_group = QGroupBox("工况列表")
        list_layout = QVBoxLayout(list_group)
        self._table = QTableWidget(len(self._entries), 4, self)
        self._table.setHorizontalHeaderLabels(("选择", "工况", "状态", "原因"))
        self._table.setSelectionMode(QAbstractItemView.NoSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        for row, entry in enumerate(self._entries):
            checkbox = QCheckBox()
            checkbox.setChecked(entry.case_idx == self._current_case_idx)
            checkbox.toggled.connect(self._on_checkbox_toggled)
            self._checkboxes[entry.case_idx] = checkbox
            self._table.setCellWidget(row, 0, checkbox)

            case_item = QTableWidgetItem(
                f"工况 {entry.case_idx + 1}｜{entry.label}"
            )
            state_item = QTableWidgetItem("可导出" if entry.is_valid else "将跳过")
            reason_item = QTableWidgetItem("" if entry.is_valid else (entry.invalid_reason or ""))
            for column, item in enumerate((case_item, state_item, reason_item), start=1):
                item.setFlags(Qt.ItemIsEnabled)
                self._table.setItem(row, column, item)
        self._table.resizeColumnsToContents()
        list_layout.addWidget(self._table)
        root.addWidget(list_group, 1)

        self._hint_label = QLabel("")
        self._hint_label.setWordWrap(True)
        root.addWidget(self._hint_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._ok_button = buttons.button(QDialogButtonBox.Ok)
        self._ok_button.setText("确认导出")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _selected_scope(self) -> ScopeLiteral:
        if self._scope_checked.isChecked():
            return "checked"
        if self._scope_all.isChecked():
            return "all"
        return "current"

    def _set_checked_case_indexes(self, case_indexes):
        target = set(int(idx) for idx in case_indexes)
        for case_idx, checkbox in self._checkboxes.items():
            checkbox.blockSignals(True)
            checkbox.setChecked(case_idx in target)
            checkbox.blockSignals(False)

    def _apply_scope_state(self):
        scope = self._selected_scope()
        if scope == "current":
            self._set_checked_case_indexes([self._current_case_idx])
        elif scope == "all":
            self._set_checked_case_indexes(self._checkboxes.keys())
        elif self._last_scope != "checked":
            if not self._manual_checked_case_indexes:
                self._manual_checked_case_indexes = {self._current_case_idx}
            self._set_checked_case_indexes(self._manual_checked_case_indexes)

        allow_manual = scope == "checked"
        for checkbox in self._checkboxes.values():
            checkbox.setEnabled(allow_manual)

        checked_count = len(self.checked_case_indexes())
        self._ok_button.setEnabled(scope != "checked" or checked_count > 0)
        if scope == "checked" and checked_count == 0:
            self._hint_label.setText("请至少勾选一个工况。")
        elif scope == "current":
            self._hint_label.setText("将导出左侧当前激活工况对应的 DXF。")
        elif scope == "all":
            self._hint_label.setText("将尝试导出全部工况，无效工况会在导出时自动跳过。")
        else:
            self._hint_label.setText("将导出勾选的工况，无效工况会在导出时自动跳过。")
        self._last_scope = scope

    def _on_checkbox_toggled(self):
        if self._selected_scope() == "checked":
            self._manual_checked_case_indexes = set(self.checked_case_indexes())
        self._apply_scope_state()

    def checked_case_indexes(self):
        return [
            case_idx
            for case_idx, checkbox in self._checkboxes.items()
            if checkbox.isChecked()
        ]

    def get_result(self):
        return DxfExportDialogResult(
            scope=self._selected_scope(),
            checked_case_indexes=self.checked_case_indexes(),
            scale_denom=int(self._scale_combo.currentText().split(":")[1]),
        )


def show_multi_case_dxf_dialog(
    parent,
    module_title: str,
    case_entries: list[DxfExportCaseEntry],
    current_case_idx: int,
):
    dialog = MultiCaseDxfExportDialog(
        module_title=module_title,
        case_entries=case_entries,
        current_case_idx=current_case_idx,
        parent=parent,
    )
    if dialog.exec() != QDialog.Accepted:
        return None
    return dialog.get_result()


def select_case_entries(
    case_entries: list[DxfExportCaseEntry],
    scope: ScopeLiteral,
    current_case_idx: int,
    checked_case_indexes=None,
):
    if scope == "current":
        return [entry for entry in case_entries if entry.case_idx == current_case_idx]
    if scope == "checked":
        selected = set(int(idx) for idx in (checked_case_indexes or []))
        return [entry for entry in case_entries if entry.case_idx in selected]
    return list(case_entries)


def partition_valid_case_entries(case_entries: list[DxfExportCaseEntry]):
    valid_entries = [entry for entry in case_entries if entry.is_valid]
    invalid_entries = [entry for entry in case_entries if not entry.is_valid]
    return valid_entries, invalid_entries


def format_invalid_case_summary(case_entries: list[DxfExportCaseEntry]):
    if not case_entries:
        return ""
    return "；".join(
        f"工况 {entry.case_idx + 1}（{entry.invalid_reason or '不可导出'}）"
        for entry in case_entries
    )


def format_export_result_message(valid_count: int, invalid_entries: list[DxfExportCaseEntry]):
    if not invalid_entries:
        return f"已导出 {valid_count} 个工况到 1 个 DXF。"
    skipped_count = len(invalid_entries)
    skipped_text = format_invalid_case_summary(invalid_entries)
    return (
        f"已导出 {valid_count} 个工况，跳过 {skipped_count} 个无效工况。"
        f"\n跳过项：{skipped_text}"
    )


def format_empty_export_warning(invalid_entries: list[DxfExportCaseEntry]):
    detail = format_invalid_case_summary(invalid_entries)
    if detail:
        return f"当前选中范围内没有可导出的工况。\n{detail}"
    return "当前选中范围内没有可导出的工况。"


def export_combined_case_dxf(
    filepath: str,
    case_entries: list[DxfExportCaseEntry],
    scale_denom: int,
    draw_case: Callable,
    draw_summary_table: Callable | None = None,
):
    try:
        import ezdxf
    except ImportError:
        raise ImportError("需要安装 ezdxf 库: pip install ezdxf")

    normalized_path = filepath if str(filepath).lower().endswith(".dxf") else f"{filepath}.dxf"
    doc = ezdxf.new("R2010")
    setup_section_dxf_document(doc, scale_denom=scale_denom)
    msp = doc.modelspace()

    measurements = []
    for entry in case_entries:
        measurement_msp = create_measurement_msp(layer_prefix=f"工况{entry.case_idx + 1}_")
        width, height = draw_case(
            measurement_msp,
            entry.result or {},
            entry.input_params or {},
            scale_denom=scale_denom,
            title=f"工况 {entry.case_idx + 1}｜{entry.label}",
        )
        min_x, min_y, max_x, max_y = measurement_msp.local_bounds()
        measurements.append(
            {
                "entry": entry,
                "bounds": (min_x, min_y, max_x, max_y),
                "width": max(width, max_x - min_x),
                "height": max(height, max_y - min_y),
            }
        )

    cell_padding_x = 40.0
    cell_padding_y = 40.0
    max_width = max(item["width"] for item in measurements)
    max_height = max(item["height"] for item in measurements)
    cell_width = max_width + cell_padding_x * 2.0
    cell_height = max_height + cell_padding_y * 2.0
    ncols, _nrows = compute_auto_grid(len(measurements))

    for draw_index, item in enumerate(measurements):
        entry = item["entry"]
        min_x, min_y, _max_x, _max_y = item["bounds"]
        row, col = divmod(draw_index, ncols)
        layer_prefix = f"工况{entry.case_idx + 1}_"
        ensure_section_dxf_layers(doc, layer_prefix=layer_prefix)
        tracked_msp = TrackedSectionMsp(
            msp,
            ox=col * cell_width + cell_padding_x - min_x,
            oy=-(row * cell_height) + cell_padding_y - min_y,
            layer_prefix=layer_prefix,
        )
        draw_case(
            tracked_msp,
            entry.result or {},
            entry.input_params or {},
            scale_denom=scale_denom,
            title=f"工况 {entry.case_idx + 1}｜{entry.label}",
        )

    if draw_summary_table is not None:
        nrows = int(math.ceil(len(measurements) / ncols))
        summary_origin_x = 0.0
        summary_origin_y = -(nrows * cell_height) - 20.0
        draw_summary_table(doc, msp, case_entries, summary_origin_x, summary_origin_y)

    doc.saveas(normalized_path)
    return normalized_path
