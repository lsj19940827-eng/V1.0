# -*- coding: utf-8 -*-
"""多倒虹吸窗口从水面线进入时清理历史纵断面的回归测试。"""

import copy
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

from PySide6.QtWidgets import QApplication, QWidget

import app_渠系计算前端.siphon.panel as siphon_panel_mod
from app_渠系计算前端.siphon.multi_siphon_dialog import MultiSiphonDialog
from 推求水面线.managers.siphon_manager import SiphonManager


class _FakeWebEngineView(QWidget):
    """测试替身：避免无头环境加载真实网页视图。"""

    def setHtml(self, *_args, **_kwargs):
        return None


def _fake_web_view_factory(parent=None):
    """返回假的网页视图。"""
    return _FakeWebEngineView(parent)


def _get_qapp():
    """获取或创建 QApplication。"""
    return QApplication.instance() or QApplication([])


def _make_plan_points(name_suffix=0):
    """构造水面线提取出的平面 IP 点。"""
    offset = float(name_suffix) * 10.0
    return [
        {
            "chainage": 0.0,
            "x": offset,
            "y": 0.0,
            "azimuth": 0.0,
            "turn_radius": 0.0,
            "turn_angle": 0.0,
            "turn_type": "无",
            "ip_index": 1,
        },
        {
            "chainage": 50.0,
            "x": offset + 50.0,
            "y": 0.0,
            "azimuth": 35.0,
            "turn_radius": 0.0,
            "turn_angle": 22.0,
            "turn_type": "折线",
            "ip_index": 2,
        },
        {
            "chainage": 110.0,
            "x": offset + 110.0,
            "y": 30.0,
            "azimuth": 35.0,
            "turn_radius": 0.0,
            "turn_angle": 0.0,
            "turn_type": "无",
            "ip_index": 3,
        },
    ]


def _make_group(name, index=0):
    """构造从水面线模块传入的倒虹吸分组。"""
    return SimpleNamespace(
        name=name,
        design_flow=1.0,
        roughness=0.014,
        inlet_transition_form="",
        outlet_transition_form="",
        siphon_transition_inlet_zeta=0.0,
        siphon_transition_outlet_zeta=0.0,
        upstream_velocity=0.0,
        downstream_velocity=0.0,
        upstream_velocity_increased=0.0,
        downstream_velocity_increased=0.0,
        upstream_section_B=None,
        upstream_section_h=None,
        upstream_section_m=None,
        plan_segments=[],
        plan_total_length=110.0,
        plan_feature_points=_make_plan_points(index),
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


def _make_panel(monkeypatch):
    """创建关闭自动加载的单倒虹吸面板。"""
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", _fake_web_view_factory)
    return siphon_panel_mod.SiphonPanel(
        show_case_management=False,
        disable_autosave_load=True,
    )


def _legacy_profile_payload(monkeypatch):
    """生成一份旧配置里的纵断面资料，并让它不再完全匹配内置示例。"""
    panel = _make_panel(monkeypatch)
    try:
        panel._add_example_longitudinal()
        panel._longitudinal_is_example = False
        payload = panel.to_dict()
    finally:
        panel.deleteLater()

    payload["longitudinal_nodes"][3]["elevation"] += 1.0
    payload["longitudinal_is_example"] = False
    return payload


def _make_manager_with_legacy_profiles(monkeypatch, old_names):
    """构造只保存在内存里的历史倒虹吸配置。"""
    payload = _legacy_profile_payload(monkeypatch)
    siphons = {}
    for old_name in old_names:
        siphons[old_name] = {
            "Q": 1.0,
            "v_guess": 2.0,
            "roughness_n": 0.014,
            "inlet_type": "",
            "outlet_type": "",
            "xi_inlet": 0.0,
            "xi_outlet": 0.0,
            "segments": copy.deepcopy(payload["segments"]),
            "common_defaults_initialized": True,
            "plan_segments": [],
            "plan_total_length": 0.0,
            "plan_feature_points": [],
            "longitudinal_nodes": copy.deepcopy(payload["longitudinal_nodes"]),
            "longitudinal_is_example": payload["longitudinal_is_example"],
            "num_pipes": 1,
        }

    manager = SiphonManager()
    manager._config = {"version": "1.0", "last_modified": "", "siphons": siphons}
    manager.save_config = lambda: None
    return manager


def _make_dialog(monkeypatch, groups, manager=None):
    """创建多倒虹吸窗口。"""
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", _fake_web_view_factory)
    return MultiSiphonDialog(None, groups, manager=manager, show_case_management=False)


def test_water_profile_entry_does_not_restore_renamed_historical_longitudinal(monkeypatch):
    """从水面线进入时，自动重命名迁移来的历史纵断面不能静默恢复。"""
    old_names = ["旧倒虹吸1", "旧倒虹吸2"]
    new_names = ["大营山", "庙梁子"]
    manager = _make_manager_with_legacy_profiles(monkeypatch, old_names)
    groups = [_make_group(name, index) for index, name in enumerate(new_names)]

    dialog = _make_dialog(monkeypatch, groups, manager=manager)
    try:
        for name in new_names:
            panel = dialog.panels[name]
            assert panel.longitudinal_nodes == []
            assert panel._has_real_longitudinal_data() is False
            assert "仅平面（独立计算）" in panel.lbl_data_status.text()
    finally:
        dialog.close()
        dialog.deleteLater()


def test_water_profile_save_does_not_mark_blank_profile_as_example(monkeypatch):
    """空白纵断面保存时，不能再写入示例纵断面标记。"""
    manager = SiphonManager()
    manager._config = {"version": "1.0", "last_modified": "", "siphons": {}}
    manager.save_config = lambda: None
    dialog = _make_dialog(monkeypatch, [_make_group("庙梁子")], manager=manager)

    try:
        dialog._save_all()
        saved = manager._config["siphons"]["庙梁子"]

        assert saved["longitudinal_nodes"] == []
        assert saved.get("longitudinal_is_example") is False
    finally:
        dialog.close()
        dialog.deleteLater()
