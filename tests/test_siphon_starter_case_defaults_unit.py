# -*- coding: utf-8 -*-
"""倒虹吸 starter 工况空白几何与默认通用构件配置回归测试。"""

from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QWidget

import app_渠系计算前端.siphon.panel as siphon_panel_mod


class _ReportView(QWidget):
    """默认工况不涉及网页渲染，只替换报告显示控件。"""

    def setHtml(self, *_args, **_kwargs):
        pass


def _assert_starter_defaults(data):
    """新建工况和首次保存必须同时满足相同的默认参数与空白几何契约。"""
    assert data["inlet_type"] == "直线扭曲面"
    assert data["outlet_type"] == "直线扭曲面"
    assert data["xi_inlet"] == 0.2
    assert data["xi_outlet"] == 0.4
    assert data.get("common_defaults_initialized") is True
    assert [seg["type"] for seg in data.get("segments", [])] == [
        "进水口",
        "拦污栅",
        "闸门槽",
        "旁通管",
        "管道渐变段",
        "其他",
        "出水口",
    ]
    assert data.get("plan_segments", []) == []
    assert data.get("plan_feature_points", []) == []
    assert "longitudinal_nodes" not in data


def test_starter_case_is_blank_and_keeps_transition_defaults(monkeypatch, tmp_path):
    # 用户可修改的工况1不是出厂样本；从空目录走真实创建、保存和重开路径。
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(siphon_panel_mod, "_pkg_root", str(tmp_path))
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", lambda parent=None: _ReportView(parent))
    panel = siphon_panel_mod.SiphonPanel(show_case_management=True, disable_autosave_load=True)
    reopened = None
    try:
        assert [case.name for case in panel.case_manager.cases] == ["工况1"]
        _assert_starter_defaults(panel.to_dict())
        panel._do_autosave()
        case_file = tmp_path / "data" / "siphon_cases" / "工况1.siphon.json"
        _assert_starter_defaults(json.loads(case_file.read_text(encoding="utf-8")))

        reopened = siphon_panel_mod.SiphonPanel(show_case_management=True, disable_autosave_load=True)
        _assert_starter_defaults(reopened.to_dict())
    finally:
        for widget in (reopened, panel):
            if widget is not None:
                widget.close()
                widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        assert app is QApplication.instance()
