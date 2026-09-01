# -*- coding: utf-8 -*-
"""Unit tests for siphon num-pipes confirmation behavior."""

import os
import sys
import math
from types import SimpleNamespace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "倒虹吸水力计算系统"))

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

import pytest

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


def _make_excel_turn_plan_points(radius=10.0):
    return [
        {
            "chainage": 0.0,
            "x": 0.0,
            "y": 0.0,
            "turn_radius": 0.0,
            "turn_angle": 0.0,
            "turn_type": "无",
            "ip_index": 1,
            "turn_radius_is_explicit": False,
            "turn_radius_text": "",
            "turn_radius_source": "",
        },
        {
            "chainage": 80.0,
            "x": 80.0,
            "y": 0.0,
            "turn_radius": radius,
            "turn_angle": 35.0,
            "turn_type": "圆弧",
            "ip_index": 2,
            "turn_radius_is_explicit": True,
            "turn_radius_text": f"{radius:g}",
            "turn_radius_source": "water_profile",
        },
        {
            "chainage": 160.0,
            "x": 160.0,
            "y": 45.0,
            "turn_radius": 0.0,
            "turn_angle": 0.0,
            "turn_type": "无",
            "ip_index": 3,
            "turn_radius_is_explicit": False,
            "turn_radius_text": "",
            "turn_radius_source": "",
        },
    ]


def _make_multiple_excel_turn_plan_points():
    points = _make_excel_turn_plan_points(radius=10.0)
    points.insert(
        2,
        {
            "chainage": 120.0,
            "x": 120.0,
            "y": 20.0,
            "turn_radius": 11.5,
            "turn_angle": 28.0,
            "turn_type": "圆弧",
            "ip_index": 3,
            "turn_radius_is_explicit": True,
            "turn_radius_text": "11.5",
            "turn_radius_source": "water_profile",
        },
    )
    points[-1]["chainage"] = 200.0
    points[-1]["x"] = 200.0
    points[-1]["ip_index"] = 4
    return points


def _make_blank_middle_turn_plan_points():
    points = _make_excel_turn_plan_points(radius=0.0)
    points[1].update(
        {
            "turn_radius": 0.0,
            "turn_angle": 35.0,
            "turn_type": "折线",
            "turn_radius_is_explicit": False,
            "turn_radius_text": "",
            "turn_radius_source": "",
        }
    )
    return points


def _make_panel(monkeypatch):
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", lambda parent=None: _FakeWebEngineView(parent))
    panel = siphon_panel_mod.SiphonPanel(show_case_management=False, disable_autosave_load=True)
    panel._suppress_result_display = True
    return panel


def _set_excel_turn_params(panel, *, radius=10.0, n_value=3.0):
    panel.set_params(
        Q=math.pi,
        v_guess=1.0,
        roughness_n=0.014,
        siphon_name="测试倒虹吸",
        siphon_turn_radius_n=n_value,
        plan_source="water_profile",
        plan_total_length=160.0,
        plan_feature_points=_make_excel_turn_plan_points(radius=radius),
    )


def _set_plan_params(panel, plan_feature_points, *, n_value=3.0):
    panel.set_params(
        Q=math.pi,
        v_guess=1.0,
        roughness_n=0.014,
        siphon_name="测试倒虹吸",
        siphon_turn_radius_n=n_value,
        plan_source="water_profile",
        plan_total_length=200.0,
        plan_feature_points=plan_feature_points,
    )


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
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", lambda parent=None: _FakeWebEngineView(parent))
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


def test_turn_radius_n_enter_confirms_default_and_suppresses_warning(monkeypatch):
    """默认转弯半径倍数按 Enter 后应视为已确认，并停止提示。"""
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", lambda parent=None: _FakeWebEngineView(parent))
    monkeypatch.setattr(siphon_panel_mod, "InfoBar", _InfoBarSpy)
    _InfoBarSpy.reset()

    panel = siphon_panel_mod.SiphonPanel(show_case_management=False, disable_autosave_load=True)
    panel._turn_n_user_confirmed = False
    panel._update_turn_n_style()

    panel.edit_turn_n.editingFinished.emit()
    panel._warn_turn_n_if_needed()

    assert panel._turn_n_user_confirmed is True
    assert _InfoBarSpy.warnings == []

    panel.deleteLater()


def test_turn_radius_n_text_change_requires_reconfirm(monkeypatch):
    """修改转弯半径倍数后，应先回到待确认状态。"""
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", lambda parent=None: _FakeWebEngineView(parent))

    panel = siphon_panel_mod.SiphonPanel(show_case_management=False, disable_autosave_load=True)
    panel._turn_n_user_confirmed = True
    panel._update_turn_n_style()

    panel.edit_turn_n.setText("4.0")

    assert panel._turn_n_user_confirmed is False

    panel.edit_turn_n.editingFinished.emit()

    assert panel._turn_n_user_confirmed is True

    panel.deleteLater()


def test_turn_radius_r_override_keeps_n_confirmed(monkeypatch):
    """直接输入 R 反推 n 后，应立即保持倍数已确认。"""
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", lambda parent=None: _FakeWebEngineView(parent))

    panel = siphon_panel_mod.SiphonPanel(show_case_management=False, disable_autosave_load=True)
    panel._turn_n_user_confirmed = False
    panel.edit_turn_R.setText("5.00")

    assert panel._turn_n_user_confirmed is True
    assert panel.edit_turn_n.text() == "1.923"

    panel.deleteLater()


def test_turn_radius_r_keyboard_entry_formats_only_after_confirmation(monkeypatch):
    """多轮键盘输入 R 均不得被延迟刷新打断，Enter 后再统一格式化。"""
    panel = _make_panel(monkeypatch)

    for _attempt in range(3):
        panel.edit_turn_R.selectAll()
        # 模拟用户刚改过 Q/v 后留下的 200ms 防抖刷新。
        panel._on_Qv_changed()
        QTest.keyClicks(panel.edit_turn_R, "3")
        QTest.qWait(250)
        assert panel.edit_turn_R.text() == "3"

        QTest.keyClicks(panel.edit_turn_R, "0")
        assert panel.edit_turn_R.text() == "30"

        QTest.keyClick(panel.edit_turn_R, Qt.Key_Return)
        assert panel.edit_turn_R.text() == "30.00"

    panel.deleteLater()


def test_excel_explicit_turn_radius_survives_initial_n_sync(monkeypatch):
    """Excel 已填的中间 IP 半径，打开窗口时不应被默认 n×D 覆盖。"""
    panel = _make_panel(monkeypatch)

    _set_excel_turn_params(panel, radius=10.0, n_value=3.0)

    assert panel.plan_feature_points[1].turn_radius == 10.0

    panel.deleteLater()


def test_excel_explicit_turn_radius_kept_when_n_change_cancelled(monkeypatch):
    """修改 n 后选择保留 Excel 半径，计算点仍使用 Excel 原值。"""
    prompts = []

    def _fake_question(_parent, title, message, yes_text=None, no_text=None):
        prompts.append((title, message, yes_text, no_text))
        return False

    panel = _make_panel(monkeypatch)
    monkeypatch.setattr(siphon_panel_mod, "fluent_question", _fake_question)
    _set_excel_turn_params(panel, radius=10.0, n_value=3.0)

    panel.edit_turn_n.setText("5.0")
    panel.edit_turn_n.editingFinished.emit()

    assert panel.plan_feature_points[1].turn_radius == 10.0
    assert prompts
    prompt_text = prompts[0][1]
    assert "测试倒虹吸" in prompt_text
    assert "IP2" in prompt_text
    assert "10" in prompt_text
    assert "n=5" in prompt_text
    assert "D=" in prompt_text
    assert "R=n×D" in prompt_text
    assert prompts[0][2] == "覆盖为 n×D"
    assert prompts[0][3] == "保留 Excel 半径"

    panel.deleteLater()


def test_multiple_excel_explicit_turn_radii_are_listed_in_prompt(monkeypatch):
    """多个中间 IP 都有 Excel 半径时，提示应逐个列出。"""
    prompts = []

    def _fake_question(_parent, title, message, yes_text=None, no_text=None):
        prompts.append(message)
        return False

    panel = _make_panel(monkeypatch)
    monkeypatch.setattr(siphon_panel_mod, "fluent_question", _fake_question)
    _set_plan_params(panel, _make_multiple_excel_turn_plan_points(), n_value=3.0)

    panel.edit_turn_n.setText("4.0")
    panel.edit_turn_n.editingFinished.emit()

    assert prompts
    assert "IP2" in prompts[0] and "10" in prompts[0]
    assert "IP3" in prompts[0] and "11.5" in prompts[0]

    panel.deleteLater()


def test_multiple_excel_turn_radii_use_compact_panel_summary(monkeypatch):
    """主界面只显示 Excel 半径摘要，完整 IP 清单交给明细弹窗。"""
    panel = _make_panel(monkeypatch)
    _set_plan_params(panel, _make_multiple_excel_turn_plan_points(), n_value=3.0)

    summary_text = panel.lbl_turn_R.text()

    assert "Excel半径优先：2 个 IP 使用原值" in summary_text
    assert "n×D=" in summary_text
    assert "IP2=10" not in summary_text
    assert "IP3=11.5" not in summary_text
    assert hasattr(panel, "btn_turn_R_details")
    assert not panel.btn_turn_R_details.isHidden()

    panel.deleteLater()


def test_excel_turn_radius_detail_rows_keep_full_ip_list(monkeypatch):
    """半径明细数据应完整保留每个 IP 的 Excel 半径和当前状态。"""
    panel = _make_panel(monkeypatch)
    _set_plan_params(panel, _make_multiple_excel_turn_plan_points(), n_value=3.0)
    diameter = panel._get_adopted_diameter_context()["diameter"]
    proposed_R = round(3.0 * diameter, 2)

    rows = panel._build_excel_turn_radius_detail_rows(proposed_R)

    assert rows == [
        {
            "ip": "IP2",
            "excel_radius": "10 m",
            "proposed_radius": f"{panel._format_turn_radius_value(proposed_R)} m",
            "status": "保留 Excel 半径",
        },
        {
            "ip": "IP3",
            "excel_radius": "11.5 m",
            "proposed_radius": f"{panel._format_turn_radius_value(proposed_R)} m",
            "status": "保留 Excel 半径",
        },
    ]

    panel._excel_turn_radius_override_confirmed = True
    rows_after_override = panel._build_excel_turn_radius_detail_rows(proposed_R)
    assert {row["status"] for row in rows_after_override} == {"已覆盖"}

    panel.deleteLater()


def test_excel_explicit_turn_radius_overridden_after_n_confirm(monkeypatch):
    """修改 n 后选择覆盖，Excel 半径才改为当前 n×D。"""
    panel = _make_panel(monkeypatch)
    monkeypatch.setattr(siphon_panel_mod, "fluent_question", lambda *_args, **_kwargs: True)
    _set_excel_turn_params(panel, radius=10.0, n_value=3.0)

    panel.edit_turn_n.setText("5.0")
    panel.edit_turn_n.editingFinished.emit()

    diameter = panel._get_adopted_diameter_context()["diameter"]
    assert panel.plan_feature_points[1].turn_radius == pytest.approx(round(5.0 * diameter, 2))
    assert panel.has_excel_turn_radius_override() is True

    panel.deleteLater()


def test_blank_middle_turn_radius_still_auto_uses_n_times_d(monkeypatch):
    """未显式填写 Excel 半径的中间转弯点仍按 n×D 自动补算。"""
    panel = _make_panel(monkeypatch)
    _set_plan_params(panel, _make_blank_middle_turn_plan_points(), n_value=3.0)

    diameter = panel._get_adopted_diameter_context()["diameter"]
    assert panel.plan_feature_points[1].turn_radius == pytest.approx(round(3.0 * diameter, 2))

    panel.deleteLater()


def test_direct_r_change_requires_confirm_before_overriding_excel_radius(monkeypatch):
    """直接修改 R 时，Excel 显式半径也不能被绕过覆盖。"""
    prompts = []

    def _fake_question(_parent, title, message, yes_text=None, no_text=None):
        prompts.append((title, message, yes_text, no_text))
        return False

    panel = _make_panel(monkeypatch)
    monkeypatch.setattr(siphon_panel_mod, "fluent_question", _fake_question)
    _set_excel_turn_params(panel, radius=10.0, n_value=3.0)

    panel.edit_turn_R.setText("12.00")
    panel.edit_turn_R.editingFinished.emit()

    assert panel.plan_feature_points[1].turn_radius == 10.0
    assert prompts
    assert "R=12" in prompts[0][1]

    panel.deleteLater()


def test_direct_r_change_can_override_excel_radius_after_confirm(monkeypatch):
    """直接修改 R 并确认覆盖后，中间 IP 半径应改为用户输入的 R。"""
    panel = _make_panel(monkeypatch)
    monkeypatch.setattr(siphon_panel_mod, "fluent_question", lambda *_args, **_kwargs: True)
    _set_excel_turn_params(panel, radius=10.0, n_value=3.0)

    panel.edit_turn_R.setText("12.00")
    panel.edit_turn_R.editingFinished.emit()

    diameter = panel._get_adopted_diameter_context()["diameter"]
    assert panel.plan_feature_points[1].turn_radius == pytest.approx(12.0)
    assert float(panel.edit_turn_n.text()) == pytest.approx(round(12.0 / diameter, 3))
    assert panel.has_excel_turn_radius_override() is True

    panel.deleteLater()


def test_plan_feature_point_roundtrips_excel_turn_radius_metadata():
    """平面特征点保存/恢复时应保留 Excel 半径来源信息。"""
    point = siphon_panel_mod.PlanFeaturePoint(
        chainage=80.0,
        x=80.0,
        y=0.0,
        turn_radius=10.0,
        turn_angle=35.0,
        turn_type=siphon_panel_mod.TurnType.ARC,
        ip_index=2,
        turn_radius_is_explicit=True,
        turn_radius_text="10",
        turn_radius_source="water_profile",
    )

    data = point.to_dict()
    restored = siphon_panel_mod.PlanFeaturePoint.from_dict(data)

    assert data["turn_radius_is_explicit"] is True
    assert data["turn_radius_text"] == "10"
    assert data["turn_radius_source"] == "water_profile"
    assert restored.turn_radius_is_explicit is True
    assert restored.turn_radius_text == "10"
    assert restored.turn_radius_source == "water_profile"


def test_v_confirmation_still_blocks_calculation(monkeypatch):
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", lambda parent=None: _FakeWebEngineView(parent))
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


class _DummyParamNotebook:
    def __init__(self):
        self.index = None

    def setCurrentIndex(self, value):
        self.index = value


class _DummyVelocityEdit:
    def __init__(self):
        self.focused = False
        self.selected = False

    def setFocus(self):
        self.focused = True

    def selectAll(self):
        self.selected = True


class _FakeBatchPanel:
    def __init__(
        self,
        num_pipes_confirmed: bool,
        velocity_confirmed: bool = True,
        effective_velocity_input: bool | None = None,
    ):
        self._v_user_confirmed = velocity_confirmed
        self._effective_velocity_input = effective_velocity_input
        self._num_pipes_user_confirmed = num_pipes_confirmed
        self._suppress_result_display = False
        self._suppress_num_pipes_warning = False
        self._saved_threshold = None
        self.edit_threshold = _DummyThreshold("2.0")
        self.params_notebook = _DummyParamNotebook()
        self.edit_v = _DummyVelocityEdit()
        self._result = object()
        self.executed = 0
        self.flash_count = 0

    def _execute_calculation(self):
        assert self._suppress_num_pipes_warning is True
        self.executed += 1

    def _flash_v_field(self):
        self.flash_count += 1

    def _has_effective_velocity_input(self):
        """测试替身：模拟面板是否已有可计算流速来源。"""
        if self._effective_velocity_input is None:
            return self._v_user_confirmed
        return self._effective_velocity_input

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
    QApplication.processEvents()
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


def test_batch_calculation_accepts_effective_d_override_without_velocity_confirmation(monkeypatch):
    """有效指定管径已能反算实际流速时，批量计算不应再要求确认拟定流速。"""
    _get_qapp()
    monkeypatch.setattr(multi_siphon_dialog_mod, "InfoBar", _InfoBarSpy)
    _InfoBarSpy.reset()

    panels = {
        "ExcelD": _FakeBatchPanel(
            num_pipes_confirmed=True,
            velocity_confirmed=False,
            effective_velocity_input=True,
        )
    }
    dialog = _FakeBatchDialog(panels=panels)

    multi_siphon_dialog_mod.MultiSiphonDialog._calculate_all(dialog)

    assert _InfoBarSpy.errors == []
    assert panels["ExcelD"].executed == 1
    assert dialog.saved is True
    assert dialog.summary_called is True


def test_batch_calculation_blocks_when_velocity_and_d_override_are_both_invalid(monkeypatch):
    """取消指定管径且拟定流速未确认时，批量计算仍应拦截。"""
    _get_qapp()
    monkeypatch.setattr(multi_siphon_dialog_mod, "InfoBar", _InfoBarSpy)
    _InfoBarSpy.reset()

    panels = {
        "NoVelocity": _FakeBatchPanel(
            num_pipes_confirmed=True,
            velocity_confirmed=False,
            effective_velocity_input=False,
        )
    }
    dialog = _FakeBatchDialog(panels=panels)

    multi_siphon_dialog_mod.MultiSiphonDialog._calculate_all(dialog)

    assert panels["NoVelocity"].executed == 0
    assert len(_InfoBarSpy.errors) == 1
    error_text = " ".join(str(part) for part in _InfoBarSpy.errors[0][0])
    assert "请确认拟定流速或指定有效管径" in error_text


def test_first_tab_enter_on_velocity_does_not_confirm_num_pipes(monkeypatch):
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", lambda parent=None: _FakeWebEngineView(parent))

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
