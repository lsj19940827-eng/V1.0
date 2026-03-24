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
    )

    assert dlg.ed_angle.text() == "16.951"
    assert dlg.ed_radius.text() == "4.8"
    assert dlg.ed_xi.text() == f"{expected_xi:.4f}"
    assert f"{expected_xi:.4f}" in dlg.formula_view.html
    assert "0.1221" not in dlg.formula_view.html

    dlg.deleteLater()
