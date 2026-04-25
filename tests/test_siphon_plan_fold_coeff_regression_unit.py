# -*- coding: utf-8 -*-
"""倒虹吸平面折管局部系数回归测试。"""

import math
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_TEST_DIR)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from PySide6.QtWidgets import QApplication, QWidget

import app_渠系计算前端.siphon.dialogs as siphon_dialogs_mod
import app_渠系计算前端.siphon.panel as siphon_panel_mod


class _FakeWebView(QWidget):
    """轻量替身：避免无头环境下真实 WebEngine 初始化。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.html = ""

    def setHtml(self, html, *_args, **_kwargs):
        self.html = html


def _get_qapp():
    return QApplication.instance() or QApplication([])


def _fake_web_view_factory(parent=None):
    return _FakeWebView(parent)


def _patch_dialog_formula_rendering(monkeypatch):
    monkeypatch.setattr(
        siphon_dialogs_mod,
        "render_latex_svg",
        lambda latex, fontsize=14: f'<svg height="12pt">{latex}</svg>',
    )
    monkeypatch.setattr(
        siphon_dialogs_mod,
        "wrap_with_katex",
        lambda body, extra_css=None: body,
    )
    monkeypatch.setattr(
        siphon_dialogs_mod,
        "get_svg_height_px",
        lambda svg, padding=8: 40,
    )


def test_panel_plan_fold_segments_auto_fill_local_loss_coeff(monkeypatch):
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", _fake_web_view_factory)

    panel = siphon_panel_mod.SiphonPanel(
        show_case_management=False,
        disable_autosave_load=True,
    )
    panel.edit_Q.setText("10")
    panel.edit_v.setText("2")

    angle = 42.7828
    plan_fold = siphon_panel_mod.StructureSegment(
        segment_type=siphon_panel_mod.SegmentType.FOLD,
        direction=siphon_panel_mod.SegmentDirection.PLAN,
        length=109.651,
        angle=angle,
        locked=True,
    )
    panel.plan_segments = [plan_fold]

    panel._update_segment_coefficients()
    panel._refresh_seg_table()

    expected_xi = siphon_panel_mod.CoefficientService.calculate_fold_coeff(
        angle, verbose=False
    )
    assert math.isclose(plan_fold.xi_calc, expected_xi, rel_tol=0.0, abs_tol=1e-9)

    matching_row = None
    for row in range(panel.seg_table.rowCount()):
        category_item = panel.seg_table.item(row, 1)
        type_item = panel.seg_table.item(row, 2)
        if category_item and type_item:
            if category_item.text() == "平面" and type_item.text() == "折管":
                matching_row = row
                break

    assert matching_row is not None, "应在结构段表格中找到平面折管行"
    xi_item = panel.seg_table.item(matching_row, 10)
    assert xi_item is not None
    assert xi_item.text() == f"{expected_xi:.4f}"

    panel.deleteLater()


def test_segment_edit_dialog_loads_auto_xi_for_fold_when_missing(monkeypatch):
    _get_qapp()
    monkeypatch.setattr(siphon_dialogs_mod, "create_web_view", _fake_web_view_factory)
    _patch_dialog_formula_rendering(monkeypatch)

    angle = 42.7828
    seg = siphon_dialogs_mod.StructureSegment(
        segment_type=siphon_dialogs_mod.SegmentType.FOLD,
        direction=siphon_dialogs_mod.SegmentDirection.PLAN,
        length=109.651,
        angle=angle,
        locked=True,
        xi_user=None,
        xi_calc=None,
    )

    dlg = siphon_dialogs_mod.SegmentEditDialog(
        None,
        segment=seg,
        Q=10.0,
        v=2.0,
        direction=siphon_dialogs_mod.SegmentDirection.PLAN,
    )

    expected_xi = siphon_dialogs_mod.CoefficientService.calculate_fold_coeff(
        float(dlg.ed_angle.text()), verbose=False
    )
    assert dlg.ed_xi.text() == f"{expected_xi:.4f}"
    assert f"{expected_xi:.4f}" in dlg.formula_view.html

    dlg.deleteLater()


def test_segment_edit_dialog_uses_design_diameter_for_bend_formula(monkeypatch):
    """弯管弹窗应使用设计管径计算 R/D0，而不是理论管径。"""
    _get_qapp()
    monkeypatch.setattr(siphon_dialogs_mod, "create_web_view", _fake_web_view_factory)
    _patch_dialog_formula_rendering(monkeypatch)

    diameter_theory = 0.96
    diameter_design = siphon_dialogs_mod.HydraulicCore.round_diameter(diameter_theory)
    velocity = 2.0
    flow = math.pi * velocity * diameter_theory ** 2 / 4.0
    radius = 1.0
    angle = 90.0
    stale_xi = siphon_dialogs_mod.CoefficientService.calculate_bend_coeff(
        radius, diameter_theory, angle, verbose=False
    )
    seg = siphon_dialogs_mod.StructureSegment(
        segment_type=siphon_dialogs_mod.SegmentType.BEND,
        direction=siphon_dialogs_mod.SegmentDirection.PLAN,
        radius=radius,
        angle=angle,
        length=radius * math.radians(angle),
        locked=True,
        xi_user=None,
        xi_calc=stale_xi,
    )

    dlg = siphon_dialogs_mod.SegmentEditDialog(
        None,
        segment=seg,
        Q=flow,
        v=velocity,
        direction=siphon_dialogs_mod.SegmentDirection.PLAN,
    )

    expected_xi = siphon_dialogs_mod.CoefficientService.calculate_bend_coeff(
        radius, diameter_design, angle, verbose=False
    )
    assert dlg.ed_xi.text() == f"{expected_xi:.4f}"
    assert "D设计" in dlg.formula_view.html
    assert "0.96" not in dlg.formula_view.html

    dlg.deleteLater()


def test_segment_edit_dialog_preserves_bend_precision_and_formula_matches_loaded_xi(monkeypatch):
    _get_qapp()
    monkeypatch.setattr(siphon_dialogs_mod, "create_web_view", _fake_web_view_factory)
    _patch_dialog_formula_rendering(monkeypatch)

    radius = 4.8
    angle = 16.951
    diameter = 1.514
    q = math.pi * 2.0 * diameter ** 2 / 4.0
    expected_xi = siphon_dialogs_mod.CoefficientService.calculate_bend_coeff(
        radius, diameter, angle, verbose=False
    )
    seg = siphon_dialogs_mod.StructureSegment(
        segment_type=siphon_dialogs_mod.SegmentType.BEND,
        direction=siphon_dialogs_mod.SegmentDirection.PLAN,
        radius=radius,
        angle=angle,
        length=radius * math.radians(angle),
        locked=True,
        xi_user=None,
        xi_calc=expected_xi,
    )

    dlg = siphon_dialogs_mod.SegmentEditDialog(
        None,
        segment=seg,
        Q=q,
        v=2.0,
        direction=siphon_dialogs_mod.SegmentDirection.PLAN,
        diameter=diameter,
        diameter_label="D设计",
    )

    assert dlg.ed_angle.text() == "16.951"
    assert dlg.ed_radius.text() == "4.8"
    assert dlg.ed_xi.text() == f"{expected_xi:.4f}"
    assert f"{expected_xi:.4f}" in dlg.formula_view.html
    assert "0.1221" not in dlg.formula_view.html

    dlg.deleteLater()


def test_panel_opens_segment_dialog_with_multi_pipe_design_diameter(monkeypatch):
    """多管并联编辑弯管时，弹窗应接收每管流量对应的设计管径。"""
    panel = None
    captured = {}

    class _CaptureDialog:
        result = None

        def __init__(self, parent, segment=None, Q=10.0, v=2.0, direction=None, **kwargs):
            captured.update({
                "Q": Q,
                "v": v,
                "direction": direction,
                "diameter": kwargs.get("diameter"),
                "diameter_label": kwargs.get("diameter_label"),
            })

        def exec(self):
            return 0

    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", _fake_web_view_factory)
    monkeypatch.setattr(siphon_panel_mod, "SegmentEditDialog", _CaptureDialog)
    panel = siphon_panel_mod.SiphonPanel(
        show_case_management=False,
        disable_autosave_load=True,
    )
    panel.edit_Q.setText("10")
    panel.edit_v.setText("2")
    panel.spin_num_pipes.setValue(2)
    radius = 4.8
    angle = 16.951
    plan_bend = siphon_panel_mod.StructureSegment(
        segment_type=siphon_panel_mod.SegmentType.BEND,
        direction=siphon_panel_mod.SegmentDirection.PLAN,
        radius=radius,
        angle=angle,
        length=radius * math.radians(angle),
        locked=True,
    )
    panel.plan_segments = [plan_bend]
    panel._refresh_seg_table()

    target_index = None
    for row in range(panel.seg_table.rowCount()):
        category_item = panel.seg_table.item(row, 1)
        type_item = panel.seg_table.item(row, 2)
        if category_item and type_item and category_item.text() == "平面" and type_item.text() == "弯管":
            target_index = panel.seg_table.model().index(row, 0)
            break
    assert target_index is not None

    panel._on_seg_double_click(target_index)

    expected_ctx = panel._get_adopted_diameter_context()
    assert captured["Q"] == expected_ctx["Q_single"]
    assert captured["diameter"] == expected_ctx["diameter"]
    assert captured["diameter_label"] == "D设计"

    panel.deleteLater()


def test_panel_opens_segment_dialog_with_override_diameter(monkeypatch):
    """指定管径生效后，弯管弹窗应接收采用D。"""
    captured = {}

    class _CaptureDialog:
        result = None

        def __init__(self, parent, segment=None, Q=10.0, v=2.0, direction=None, **kwargs):
            captured.update({
                "Q": Q,
                "v": v,
                "direction": direction,
                "diameter": kwargs.get("diameter"),
                "diameter_label": kwargs.get("diameter_label"),
            })

        def exec(self):
            return 0

    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", _fake_web_view_factory)
    monkeypatch.setattr(siphon_panel_mod, "SegmentEditDialog", _CaptureDialog)
    panel = siphon_panel_mod.SiphonPanel(
        show_case_management=False,
        disable_autosave_load=True,
    )
    panel.edit_Q.setText("10")
    panel.edit_v.setText("2")
    panel.cb_D_override.setChecked(True)
    panel.edit_D_override.setText("1.2")
    plan_bend = siphon_panel_mod.StructureSegment(
        segment_type=siphon_panel_mod.SegmentType.BEND,
        direction=siphon_panel_mod.SegmentDirection.PLAN,
        radius=4.8,
        angle=16.951,
        length=4.8 * math.radians(16.951),
        locked=True,
    )
    panel.plan_segments = [plan_bend]
    panel._refresh_seg_table()

    target_index = None
    for row in range(panel.seg_table.rowCount()):
        category_item = panel.seg_table.item(row, 1)
        type_item = panel.seg_table.item(row, 2)
        if category_item and type_item and category_item.text() == "平面" and type_item.text() == "弯管":
            target_index = panel.seg_table.model().index(row, 0)
            break
    assert target_index is not None

    panel._on_seg_double_click(target_index)

    assert captured["diameter"] == 1.2
    assert captured["diameter_label"] == "采用D"

    panel.deleteLater()
