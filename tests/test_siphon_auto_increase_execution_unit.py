# -*- coding: utf-8 -*-
"""倒虹吸自动查表加大工况执行与详细过程回归测试。"""

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "倒虹吸水力计算系统"))

from PySide6.QtWidgets import QApplication, QWidget

import app_渠系计算前端.siphon.panel as siphon_panel_mod
from siphon_hydraulics import HydraulicCore
from siphon_models import (
    CalculationResult,
    GlobalParameters,
    GradientType,
    SegmentType,
    StructureSegment,
    V2Strategy,
)


class _FakeWebEngineView(QWidget):
    """避免测试环境加载真实 QWebEngine。"""

    def setHtml(self, *_args, **_kwargs):
        return None


def _get_qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _make_two_plan_points():
    return [
        siphon_panel_mod.PlanFeaturePoint(chainage=0.0, x=0.0, y=0.0),
        siphon_panel_mod.PlanFeaturePoint(chainage=120.0, x=120.0, y=0.0),
    ]


def test_panel_auto_percent_mode_passes_lookup_percent_to_engine(monkeypatch):
    _get_qapp()
    monkeypatch.setattr(
        siphon_panel_mod,
        "create_web_view",
        lambda parent=None: _FakeWebEngineView(parent),
    )

    panel = siphon_panel_mod.SiphonPanel(
        show_case_management=False,
        disable_autosave_load=True,
    )
    panel.from_dict({"show_detail": False})
    panel._suppress_result_display = True
    panel.plan_feature_points = _make_two_plan_points()
    panel._turn_n_user_confirmed = True
    panel._v_user_confirmed = True
    panel._num_pipes_user_confirmed = True
    panel.inc_cb.setChecked(True)
    panel.inc_mode_percent_rb.setChecked(True)
    panel.edit_inc.setText("")
    panel.edit_v1_inc.setText("0.686")
    panel.edit_v3_inc.setText("0.686")

    monkeypatch.setattr(panel, "_validate_inlet_velocity", lambda: None)
    monkeypatch.setattr(
        panel,
        "_get_global_params",
        lambda: GlobalParameters(
            Q=0.51,
            v_guess=2.0,
            roughness_n=0.012,
            inlet_type=GradientType.REVERSE_BEND,
            outlet_type=GradientType.REVERSE_BEND,
            v_channel_in=0.65,
            v_pipe_in=1.8038,
            v_channel_out=1.8038,
            v_pipe_out=0.65,
            xi_inlet=0.1,
            xi_outlet=0.2,
            v2_strategy=V2Strategy.AUTO_PIPE,
        ),
    )

    captured = {}

    def _fake_execute(_params, _segments, **kwargs):
        captured.update(kwargs)
        return CalculationResult(
            diameter=0.6,
            velocity=1.8038,
            total_head_loss=1.0,
            velocity_channel_in=0.65,
            velocity_pipe_in=1.8038,
            velocity_outlet_start=1.8038,
            velocity_channel_out=0.65,
            increase_percent=kwargs.get("increase_percent") or 0.0,
            Q_increased=0.663 if kwargs.get("increase_percent") else 0.0,
            total_head_loss_inc=1.23 if kwargs.get("increase_percent") else 0.0,
        )

    monkeypatch.setattr(siphon_panel_mod.HydraulicCore, "execute_calculation", _fake_execute)

    panel._execute_calculation()

    assert captured["increase_percent"] == pytest.approx(30.0)
    assert captured["verbose"] is True
    assert panel.calculation_result is not None
    panel.deleteLater()


def test_auto_lookup_increase_case_produces_nonzero_result_and_detailed_steps():
    params = GlobalParameters(
        Q=0.51,
        v_guess=2.0,
        roughness_n=0.012,
        inlet_type=GradientType.REVERSE_BEND,
        outlet_type=GradientType.REVERSE_BEND,
        v_channel_in=0.65,
        v_pipe_in=1.8038,
        v_channel_out=1.8038,
        v_pipe_out=0.65,
        xi_inlet=0.1,
        xi_outlet=0.2,
        v2_strategy=V2Strategy.AUTO_PIPE,
    )
    segments = [
        StructureSegment(segment_type=SegmentType.INLET),
        StructureSegment(segment_type=SegmentType.STRAIGHT, length=1184.615),
        StructureSegment(segment_type=SegmentType.OUTLET),
    ]

    result = HydraulicCore.execute_calculation(
        params,
        segments,
        verbose=True,
        increase_percent=30.0,
        v1_inc=0.686,
        v3_inc=0.686,
    )
    detail_text = HydraulicCore.format_result(result, show_steps=True)

    assert result.increase_percent == pytest.approx(30.0)
    assert result.Q_increased == pytest.approx(0.663)
    assert result.total_head_loss_inc > 0
    assert "Q加大 = 0.6630 m³/s" in detail_text
    assert "ΔZ1加大" in detail_text
    assert "ΔZ2加大" in detail_text
    assert "ΔZ3加大" in detail_text
    assert "ΔZ加大" in detail_text

