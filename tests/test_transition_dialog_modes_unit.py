"""补段对话框状态与字段切换回归测试。"""

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "calc_渠系计算算法内核"))

from app_渠系计算前端.water_profile.water_profile_dialogs import (
    BatchChannelConfirmDialog,
    OpenChannelDialog,
    describe_transition_gap_source,
)


def _get_qapp():
    return QApplication.instance() or QApplication([])


def test_describe_transition_gap_source_distinguishes_scope_and_family():
    same_section_culvert = {
        "flow_section": "1",
        "reference_segment": {
            "structure_type": "矩形暗涵",
            "flow_section": "1",
        },
    }
    cross_section_open_channel = {
        "flow_section": "1",
        "reference_segment": {
            "structure_type": "明渠-梯形",
            "flow_section": "2",
        },
    }
    missing_gap = {"flow_section": "1", "reference_segment": None}

    assert describe_transition_gap_source(same_section_culvert) == "自动推荐-同段暗渠"
    assert describe_transition_gap_source(cross_section_open_channel) == "自动推荐-跨段明渠"
    assert describe_transition_gap_source(missing_gap) == "需手动填写"


def test_batch_dialog_adds_status_source_column():
    _get_qapp()
    gaps = [
        {
            "prev_name": "上游",
            "prev_struct": "矩形暗涵",
            "next_name": "下游",
            "next_struct": "倒虹吸",
            "available_length": 18.0,
            "flow": 2.88,
            "flow_section": "1",
            "reference_segment": {
                "structure_type": "矩形暗涵",
                "flow_section": "1",
                "bottom_width": 2.2,
                "structure_height": 2.0,
                "water_depth": 1.4,
                "roughness": 0.014,
                "slope_inv": 3000,
                "side_slope": 0.0,
            },
            "upstream_channel": None,
            "has_reference": True,
            "has_upstream": True,
        },
        {
            "prev_name": "上游2",
            "prev_struct": "倒虹吸",
            "next_name": "下游2",
            "next_struct": "隧洞-圆形",
            "available_length": 0.0,
            "flow": 2.88,
            "flow_section": "1",
            "reference_segment": None,
            "upstream_channel": None,
            "has_reference": False,
            "has_upstream": False,
        },
    ]

    dialog = BatchChannelConfirmDialog(None, len(gaps), gaps)

    assert dialog.param_table.columnCount() == 12
    assert dialog.param_table.horizontalHeaderItem(11).text() == "状态/来源"
    assert dialog.param_table.item(0, 11).text() == "自动推荐-同段暗渠"
    assert dialog.param_table.item(1, 11).text() == "需手动填写"
    assert dialog.minimumWidth() == 1040
    assert dialog.width() == 1280

    status_item = dialog.param_table.item(0, 11)
    assert status_item.toolTip() == "自动推荐-同段暗渠"
    assert dialog.param_table.item(0, 1).toolTip() == "上游(矩形暗涵)"
    assert dialog.param_table.item(0, 2).toolTip() == "下游(倒虹吸)"

    expected_status_width = max(
        145,
        dialog.param_table.fontMetrics().horizontalAdvance(status_item.text()) + 26,
    )
    assert dialog.param_table.columnWidth(11) >= expected_status_width


def test_open_channel_dialog_switches_between_h_and_m_fields():
    app = _get_qapp()
    dialog = OpenChannelDialog(
        None,
        upstream_channel={
            "structure_type": "矩形暗涵",
            "bottom_width": 2.4,
            "structure_height": 2.1,
            "water_depth": 1.5,
            "roughness": 0.014,
            "slope_inv": 3000,
            "side_slope": 0.0,
            "flow_section": "1",
            "flow": 2.88,
        },
        available_length=20.0,
        prev_structure="矩形暗涵",
        next_structure="倒虹吸",
        flow_section="1",
        flow=2.88,
    )
    dialog.show()
    app.processEvents()

    assert dialog.secondary_label.text() == "高度 H(m):"
    assert dialog.secondary_input_stack.currentWidget() is dialog.edit_H
    assert dialog.secondary_input_stack.height() >= dialog.edit_H.minimumHeight()
    assert dialog.edit_H.geometry().height() >= dialog.edit_H.minimumHeight()

    dialog.rb_manual.setChecked(True)
    dialog._on_source_change()
    app.processEvents()
    assert dialog.edit_H.isEnabled() is True
    assert dialog.edit_m.isEnabled() is False

    dialog.type_combo.setCurrentText("明渠-梯形")
    dialog._update_type_mode()
    app.processEvents()

    assert dialog.secondary_label.text() == "边坡 m:"
    assert dialog.secondary_input_stack.currentWidget() is dialog.edit_m
    assert dialog.edit_m.isEnabled() is True
    assert dialog.edit_H.text() == ""
    assert dialog.secondary_input_stack.height() >= dialog.edit_m.minimumHeight()
    assert dialog.edit_m.geometry().height() >= dialog.edit_m.minimumHeight()
