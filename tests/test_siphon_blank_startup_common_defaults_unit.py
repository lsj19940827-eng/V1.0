# -*- coding: utf-8 -*-
"""倒虹吸空白几何启动、默认通用构件和节点入口收口回归测试。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

from PySide6.QtWidgets import QApplication, QWidget

import app_渠系计算前端.siphon.panel as siphon_panel_mod


class _FakeWebEngineView(QWidget):
    """测试替身：避免无头环境加载 WebEngine。"""

    def setHtml(self, *_args, **_kwargs):
        return None


def _fake_web_view_factory(parent=None):
    return _FakeWebEngineView(parent)


def _get_qapp():
    return QApplication.instance() or QApplication([])


def _make_panel(monkeypatch):
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", _fake_web_view_factory)
    return siphon_panel_mod.SiphonPanel(
        show_case_management=False,
        disable_autosave_load=True,
    )


def _common_segments(panel):
    return [
        seg for seg in panel.segments
        if seg.direction == siphon_panel_mod.SegmentDirection.COMMON
    ]


def _default_common_types():
    """返回 7 类默认通用构件的标准顺序。"""
    return [
        siphon_panel_mod.SegmentType.INLET,
        siphon_panel_mod.SegmentType.TRASH_RACK,
        siphon_panel_mod.SegmentType.GATE_SLOT,
        siphon_panel_mod.SegmentType.BYPASS_PIPE,
        siphon_panel_mod.SegmentType.PIPE_TRANSITION,
        siphon_panel_mod.SegmentType.OTHER,
        siphon_panel_mod.SegmentType.OUTLET,
    ]


class _InfoBarSpy:
    """记录计算前提示，避免测试依赖真实弹窗。"""

    errors = []

    @classmethod
    def reset(cls):
        cls.errors = []

    @staticmethod
    def error(*args, **kwargs):
        _InfoBarSpy.errors.append((args, kwargs))


def test_new_panel_starts_with_default_common_segments_and_blank_geometry(monkeypatch):
    """新建面板应为空白几何，并直接显示 7 类通用构件。"""
    panel = _make_panel(monkeypatch)

    assert panel.longitudinal_nodes == []
    assert [seg.segment_type for seg in _common_segments(panel)] == _default_common_types()
    assert panel.plan_segments == []
    assert panel.plan_feature_points == []
    assert panel._longitudinal_is_example is False
    assert "无平面/纵断面数据" in panel.lbl_data_status.text()
    assert panel.to_dict()["common_defaults_initialized"] is True

    panel.deleteLater()


def test_builtin_example_loaded_from_old_data_is_cleared_to_blank(monkeypatch):
    """旧版误保存的内置示例纵断面应清空节点，同时保留默认通用构件。"""
    source = _make_panel(monkeypatch)
    source._add_example_longitudinal()
    source._longitudinal_is_example = False
    old_data = source.to_dict()

    target = _make_panel(monkeypatch)
    target.from_dict(old_data)

    assert target.longitudinal_nodes == []
    assert [seg.segment_type for seg in _common_segments(target)] == _default_common_types()
    assert target._longitudinal_is_example is False
    assert "无平面/纵断面数据" in target.lbl_data_status.text()

    source.deleteLater()
    target.deleteLater()


def test_non_builtin_profile_with_same_endpoints_is_not_cleared(monkeypatch):
    """首尾接近示例但中间不同的真实纵断面不能被误清空。"""
    source = _make_panel(monkeypatch)
    source._add_example_longitudinal()
    source._longitudinal_is_example = False
    profile_data = source.to_dict()
    profile_data["longitudinal_nodes"][6]["elevation"] = 50.123

    target = _make_panel(monkeypatch)
    target.from_dict(profile_data)

    assert len(target.longitudinal_nodes) == 13
    assert target._has_real_longitudinal_data() is True

    source.deleteLater()
    target.deleteLater()


def test_default_common_segments_are_completed_once_and_preserve_edits(monkeypatch):
    """补齐默认通用构件时不重复插入，也不覆盖用户已改值。"""
    panel = _make_panel(monkeypatch)

    panel._ensure_default_common_segments()
    first_common = _common_segments(panel)
    assert [seg.segment_type for seg in first_common] == _default_common_types()

    gate = next(seg for seg in first_common if seg.segment_type == siphon_panel_mod.SegmentType.GATE_SLOT)
    pipe_transition = next(
        seg for seg in first_common
        if seg.segment_type == siphon_panel_mod.SegmentType.PIPE_TRANSITION
    )
    gate.xi_user = 0.23
    pipe_transition.custom_label = "扩散"
    pipe_transition.xi_user = siphon_panel_mod.CoefficientService.PIPE_TRANSITION_EXPAND

    panel._ensure_default_common_segments()
    second_common = _common_segments(panel)
    assert len(second_common) == 7
    assert sum(1 for seg in second_common if seg.segment_type == siphon_panel_mod.SegmentType.GATE_SLOT) == 1
    assert next(seg for seg in second_common if seg.segment_type == siphon_panel_mod.SegmentType.GATE_SLOT).xi_user == 0.23
    saved_transition = next(
        seg for seg in second_common
        if seg.segment_type == siphon_panel_mod.SegmentType.PIPE_TRANSITION
    )
    assert saved_transition.custom_label == "扩散"
    assert saved_transition.xi_user == siphon_panel_mod.CoefficientService.PIPE_TRANSITION_EXPAND

    panel.deleteLater()


def test_old_case_without_common_init_marker_is_completed_once(monkeypatch):
    """旧工况缺少初始化标记时，应迁移补齐缺失的默认通用构件。"""
    source = _make_panel(monkeypatch)
    data = source.to_dict()
    data.pop("common_defaults_initialized", None)
    data["segments"] = [
        seg
        for seg in data["segments"]
        if seg.get("type") != siphon_panel_mod.SegmentType.BYPASS_PIPE.value
    ]

    target = _make_panel(monkeypatch)
    target.from_dict(data)

    assert [seg.segment_type for seg in _common_segments(target)] == _default_common_types()
    assert target.to_dict()["common_defaults_initialized"] is True

    source.deleteLater()
    target.deleteLater()


def test_initialized_case_preserves_deleted_default_common_segment(monkeypatch):
    """已初始化工况重新加载时，应尊重用户删除的默认通用构件。"""
    source = _make_panel(monkeypatch)
    data = source.to_dict()
    data["common_defaults_initialized"] = True
    data["segments"] = [
        seg
        for seg in data["segments"]
        if seg.get("type") != siphon_panel_mod.SegmentType.BYPASS_PIPE.value
    ]

    target = _make_panel(monkeypatch)
    target.from_dict(data)

    assert siphon_panel_mod.SegmentType.BYPASS_PIPE not in [
        seg.segment_type for seg in _common_segments(target)
    ]
    assert len(_common_segments(target)) == 6

    source.deleteLater()
    target.deleteLater()


def test_default_common_segments_without_geometry_do_not_execute_calculation(monkeypatch):
    """只有默认通用构件但没有几何时，执行计算应先提示导入或手动添加管身段。"""
    panel = _make_panel(monkeypatch)
    monkeypatch.setattr(siphon_panel_mod, "InfoBar", _InfoBarSpy)
    _InfoBarSpy.reset()
    called = {"execute": False}

    def _fake_execute(*_args, **_kwargs):
        called["execute"] = True
        return None

    monkeypatch.setattr(panel, "_validate_v_before_calc", lambda: True)
    monkeypatch.setattr(panel, "_validate_num_pipes_before_calc", lambda: True)
    monkeypatch.setattr(panel, "_warn_turn_n_if_needed", lambda: None)
    monkeypatch.setattr(siphon_panel_mod.HydraulicCore, "execute_calculation", _fake_execute)

    panel._execute_calculation()

    assert called["execute"] is False
    assert _InfoBarSpy.errors
    assert "请先导入平面 DXF、纵断面 DXF，或手动添加管身段" in _InfoBarSpy.errors[-1][0][1]

    panel.deleteLater()


def test_longitudinal_node_tab_removed_but_structure_tab_keeps_editor_entry(monkeypatch):
    """节点页不再作为顶层选项卡，但结构段页保留编辑入口。"""
    panel = _make_panel(monkeypatch)

    tab_names = [
        panel.params_notebook.tabText(i)
        for i in range(panel.params_notebook.count())
    ]
    assert "纵断面节点" not in tab_names
    assert "结构段信息" in tab_names

    buttons = panel.findChildren(siphon_panel_mod.PushButton)
    assert any(btn.text() == "编辑纵断面节点" for btn in buttons)

    panel.deleteLater()
