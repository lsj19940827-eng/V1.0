# -*- coding: utf-8 -*-
"""多倒虹吸窗口关键输入区紧凑布局回归测试。"""

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

from PySide6.QtWidgets import QApplication, QWidget

import app_渠系计算前端.siphon.panel as siphon_panel_mod
from app_渠系计算前端.siphon.multi_siphon_dialog import MultiSiphonDialog


class _FakeWebEngineView(QWidget):
    """测试替身：避免 QWebEngineView 在无头环境触发子进程崩溃。"""

    def setHtml(self, *_args, **_kwargs):
        return None


def _fake_web_view_factory(parent=None):
    return _FakeWebEngineView(parent)


def _get_qapp():
    return QApplication.instance() or QApplication([])


def _flush_events(rounds: int = 6):
    app = _get_qapp()
    for _ in range(max(1, rounds)):
        app.processEvents()


def _make_group():
    return SimpleNamespace(
        name="测试倒虹吸",
        design_flow=0.51,
        roughness=0.012,
        inlet_transition_form="",
        outlet_transition_form="",
        siphon_transition_inlet_zeta=0.0,
        siphon_transition_outlet_zeta=0.0,
        upstream_velocity=0.686,
        downstream_velocity=0.686,
        upstream_velocity_increased=0.0,
        downstream_velocity_increased=0.0,
        upstream_section_B=None,
        upstream_section_h=None,
        upstream_section_m=None,
        plan_segments=[],
        plan_total_length=1616.1,
        plan_feature_points=[],
        downstream_structure_type="",
        downstream_section_B=None,
        downstream_section_h=None,
        downstream_section_m=None,
        downstream_section_D=None,
        downstream_section_R=None,
        upstream_velocity_source="missing",
        downstream_velocity_source="missing",
        upstream_velocity_provenance={},
        downstream_velocity_provenance={},
    )


def _make_dialog(monkeypatch):
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", _fake_web_view_factory)
    dialog = MultiSiphonDialog(None, [_make_group()])
    dialog.resize(1365, 768)
    dialog.show()
    _flush_events()
    return dialog


def _row_metrics(panel):
    return {
        "v_row": panel.edit_v.parentWidget(),
        "np_row": panel.spin_num_pipes.parentWidget(),
        "turn_row": panel.edit_turn_n.parentWidget(),
    }


def test_key_input_rows_keep_full_height_in_multi_siphon_dialog(monkeypatch):
    dialog = _make_dialog(monkeypatch)
    panel = dialog._get_current_panel()
    rows = _row_metrics(panel)

    assert rows["v_row"].height() >= panel.edit_v.sizeHint().height()
    assert rows["np_row"].height() >= panel.spin_num_pipes.sizeHint().height()
    assert rows["turn_row"].height() >= panel.edit_turn_n.sizeHint().height()

    panel.lbl_canvas_hint.setText("当前平面图轴线较细长，建议点“展开”或双击预览查看大图。")
    panel.lbl_canvas_hint.setVisible(True)
    _flush_events()

    assert rows["v_row"].height() >= panel.edit_v.sizeHint().height()
    assert rows["np_row"].height() >= panel.spin_num_pipes.sizeHint().height()
    assert rows["turn_row"].height() >= panel.edit_turn_n.sizeHint().height()

    dialog.close()
    dialog.deleteLater()


def test_canvas_hint_does_not_shrink_params_area_and_stays_single_line(monkeypatch):
    dialog = _make_dialog(monkeypatch)
    panel = dialog._get_current_panel()

    params_height_before = panel.params_notebook.height()

    panel.lbl_canvas_hint.setText("当前平面图轴线较细长，建议点“展开”或双击预览查看大图。")
    panel.lbl_canvas_hint.setToolTip("当前平面图轴线较细长，建议点“展开”或双击预览查看大图。")
    panel.lbl_canvas_hint.setVisible(True)
    _flush_events()

    assert panel.params_notebook.height() == params_height_before
    assert panel.lbl_canvas_hint.wordWrap() is False
    assert panel.lbl_canvas_hint.toolTip()

    dialog.close()
    dialog.deleteLater()
