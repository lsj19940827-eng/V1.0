# -*- coding: utf-8 -*-
"""Unit tests for siphon num-pipes confirmation behavior."""

import os
import sys
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

import app_渠系计算前端.siphon.multi_siphon_dialog as multi_siphon_dialog_mod
import app_渠系计算前端.siphon.panel as siphon_panel_mod


class _FakeWebEngineView(QWidget):
    """Avoid QWebEngineView crashes in headless test runs."""

    def setHtml(self, *_args, **_kwargs):
        return None


class _InfoBarSpy:
    """Capture InfoBar calls without showing real UI."""

    warnings = []
    errors = []

    @classmethod
    def reset(cls):
        cls.warnings = []
        cls.errors = []

    @classmethod
    def warning(cls, *args, **kwargs):
        cls.warnings.append((args, kwargs))
        return None

    @classmethod
    def error(cls, *args, **kwargs):
        cls.errors.append((args, kwargs))
        return None

    @staticmethod
    def success(*_args, **_kwargs):
        return None


def _get_qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _make_two_plan_points():
    return [
        siphon_panel_mod.PlanFeaturePoint(chainage=0.0, x=0.0, y=0.0),
        siphon_panel_mod.PlanFeaturePoint(chainage=120.0, x=120.0, y=0.0),
    ]


def _make_group(name: str):
    return SimpleNamespace(
        name=name,
        design_flow=4.0,
        roughness=0.014,
        inlet_transition_form="",
        outlet_transition_form="",
        siphon_transition_inlet_zeta=0.1,
        siphon_transition_outlet_zeta=0.2,
        upstream_velocity=1.044,
        downstream_velocity=1.088,
        upstream_velocity_increased=1.107,
        downstream_velocity_increased=1.140,
        upstream_section_B=None,
        upstream_section_h=None,
        upstream_section_m=None,
        plan_segments=[],
        plan_total_length=131.6,
        plan_feature_points=[],
        downstream_structure_type="",
        downstream_section_B=None,
        downstream_section_h=None,
        downstream_section_m=None,
        downstream_section_D=None,
        downstream_section_R=None,
        rows=[],
    )


def test_num_pipes_unconfirmed_warns_but_not_blocked_and_auto_confirms(monkeypatch):
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "QWebEngineView", _FakeWebEngineView)
    monkeypatch.setattr(siphon_panel_mod, "InfoBar", _InfoBarSpy)
    _InfoBarSpy.reset()

    panel = siphon_panel_mod.SiphonPanel(show_case_management=False, disable_autosave_load=True)
    panel._suppress_result_display = True
    panel.plan_feature_points = _make_two_plan_points()
    panel.inc_cb.setChecked(False)
    panel._turn_n_user_confirmed = True
    panel._v_user_confirmed = True
    panel._num_pipes_user_confirmed = False
    panel.spin_num_pipes.setValue(2)

    monkeypatch.setattr(panel, "_validate_inlet_velocity", lambda: None)
    monkeypatch.setattr(
        panel,
        "_get_global_params",
        lambda: siphon_panel_mod.GlobalParameters(Q=10.0, v_guess=2.0, num_pipes=2),
    )

    def _fake_execute(_params, _segments, **_kwargs):
        return siphon_panel_mod.CalculationResult(
            diameter=1.0,
            velocity=1.0,
            total_head_loss=1.0,
            velocity_channel_in=1.0,
            velocity_pipe_in=1.0,
            velocity_outlet_start=1.0,
            velocity_channel_out=1.0,
        )

    monkeypatch.setattr(siphon_panel_mod.HydraulicCore, "execute_calculation", _fake_execute)

    panel._execute_calculation()

    assert panel.calculation_result is not None, "N unconfirmed should not block calculation"
    assert panel._num_pipes_user_confirmed is True, "Successful calculation should auto-confirm N"
    assert len(_InfoBarSpy.warnings) == 1, "N unconfirmed should show one warning"

    panel.deleteLater()


def test_v_confirmation_still_blocks_calculation(monkeypatch):
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "QWebEngineView", _FakeWebEngineView)
    monkeypatch.setattr(siphon_panel_mod, "InfoBar", _InfoBarSpy)
    _InfoBarSpy.reset()

    panel = siphon_panel_mod.SiphonPanel(show_case_management=False, disable_autosave_load=True)
    panel.plan_feature_points = _make_two_plan_points()
    panel._v_user_confirmed = False
    panel._num_pipes_user_confirmed = True
    monkeypatch.setattr(panel, "_flash_v_field", lambda: None)

    called = {"core": 0}

    def _should_not_run(*_args, **_kwargs):
        called["core"] += 1
        return siphon_panel_mod.CalculationResult()

    monkeypatch.setattr(siphon_panel_mod.HydraulicCore, "execute_calculation", _should_not_run)

    panel._execute_calculation()

    assert called["core"] == 0, "Unconfirmed velocity should still block calculation"
    assert len(_InfoBarSpy.errors) >= 1, "Unconfirmed velocity should show an error"

    panel.deleteLater()


class _DummyThreshold:
    def __init__(self, text=""):
        self._text = text

    def text(self):
        return self._text

    def setText(self, value):
        self._text = value


class _FakeBatchPanel:
    def __init__(self, num_pipes_confirmed: bool):
        self._v_user_confirmed = True
        self._num_pipes_user_confirmed = num_pipes_confirmed
        self._suppress_result_display = False
        self._suppress_num_pipes_warning = False
        self._saved_threshold = None
        self.edit_threshold = _DummyThreshold("2.0")
        self._result = object()
        self.executed = 0

    def _execute_calculation(self):
        assert self._suppress_num_pipes_warning is True
        self.executed += 1

    def get_result(self):
        return self._result


class _FakeProgressBar:
    def __init__(self):
        self.maximum = 0
        self.value = 0
        self.visible = False

    def setMaximum(self, value):
        self.maximum = value

    def setValue(self, value):
        self.value = value

    def setVisible(self, value):
        self.visible = bool(value)


class _FakeNotebook:
    def count(self):
        return 0

    def tabText(self, _index):
        return ""

    def setCurrentIndex(self, _index):
        return None


class _FakeBatchDialog:
    def __init__(self, panels):
        self.panels = panels
        self.notebook = _FakeNotebook()
        self.progress_bar = _FakeProgressBar()
        self.on_import_losses = None
        self.status_updates = []
        self.saved = False
        self.summary_called = False

    def _update_status(self, text):
        self.status_updates.append(text)

    def _save_all(self):
        self.saved = True

    def _get_all_results(self):
        return {}

    def _show_summary_dialog(self, _successful_panels, _fail_count=0, _imported_count=0):
        self.summary_called = True


def test_batch_num_pipes_warning_is_once_and_does_not_block(monkeypatch):
    _get_qapp()
    monkeypatch.setattr(multi_siphon_dialog_mod, "InfoBar", _InfoBarSpy)
    _InfoBarSpy.reset()

    panels = {
        "SiphonA": _FakeBatchPanel(num_pipes_confirmed=False),
        "SiphonB": _FakeBatchPanel(num_pipes_confirmed=True),
        "SiphonC": _FakeBatchPanel(num_pipes_confirmed=False),
    }
    dialog = _FakeBatchDialog(panels=panels)

    multi_siphon_dialog_mod.MultiSiphonDialog._calculate_all(dialog)

    assert len(_InfoBarSpy.warnings) == 1, "Batch mode should summarize the N warning once"
    warning_args = _InfoBarSpy.warnings[0][0]
    warning_text = f"{warning_args[0]} {warning_args[1]}"
    assert "SiphonA" in warning_text and "SiphonC" in warning_text
    assert all(panel.executed == 1 for panel in panels.values()), "N warning should not block batch calculation"
    assert all(panel._suppress_num_pipes_warning is False for panel in panels.values())
    assert dialog.saved is True
    assert dialog.summary_called is True


def test_first_tab_enter_on_velocity_does_not_confirm_num_pipes(monkeypatch):
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "QWebEngineView", _FakeWebEngineView)

    dialog = multi_siphon_dialog_mod.MultiSiphonDialog(
        None,
        [_make_group("A"), _make_group("B"), _make_group("C")],
        manager=None,
        siphon_turn_radius_n=3.0,
    )
    dialog.show()

    panel = dialog.panels["A"]
    assert panel._v_user_confirmed is False
    assert panel._num_pipes_user_confirmed is False

    panel.edit_v.setFocus()
    panel.edit_v.selectAll()
    QTest.keyClicks(panel.edit_v, "2.0")
    QTest.keyClick(panel.edit_v, Qt.Key_Return)

    assert panel._v_user_confirmed is True
    assert panel._num_pipes_user_confirmed is False, "Pressing Enter in v must not confirm N on the first tab"

    dialog.close()
