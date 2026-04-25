# -*- coding: utf-8 -*-
"""倒虹吸紧凑工况选择控件 GUI 单元测试。"""

import json
import os
import shutil
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

import pytest
from PySide6.QtWidgets import QApplication, QSplitter, QWidget
from qfluentwidgets import PushButton

import app_渠系计算前端.siphon.panel as siphon_panel_mod
from app_渠系计算前端.siphon.case_manager import CaseManager

ROOT = Path(__file__).resolve().parents[1]


class _FakeWebEngineView(QWidget):
    """测试替身：避免 QWebEngineView 在无头环境触发子进程。"""

    def setHtml(self, *_args, **_kwargs):
        return None


def _fake_web_view_factory(parent=None):
    return _FakeWebEngineView(parent)


def _get_qapp():
    return QApplication.instance() or QApplication([])


def _import_case_selector_module():
    import app_渠系计算前端.siphon.case_selector as module

    return module


class _FakeRoundMenu:
    """测试替身：收集更多菜单动作，不弹出真实菜单。"""

    last = None

    def __init__(self, *args, **kwargs):
        self.actions = []
        _FakeRoundMenu.last = self

    def addAction(self, action):
        self.actions.append(action)

    def addSeparator(self):
        return None

    def exec(self, *args, **kwargs):
        return None


def _open_more_menu(monkeypatch, module, selector):
    """打开更多菜单并返回动作列表。"""
    _FakeRoundMenu.last = None
    monkeypatch.setattr(module, "RoundMenu", _FakeRoundMenu)
    selector._show_more_menu()
    assert _FakeRoundMenu.last is not None
    return _FakeRoundMenu.last.actions


def _trigger_menu_action(actions, text):
    """按菜单文字触发动作。"""
    for action in actions:
        if action.text() == text:
            action.trigger()
            return
    raise AssertionError(f"未找到菜单项: {text}")


@pytest.fixture(autouse=True)
def _disable_runtime_side_effects(monkeypatch):
    """界面测试不写真实自动保存文件。"""
    monkeypatch.setattr(siphon_panel_mod.SiphonPanel, "_save_autosave", lambda self: None)


@pytest.fixture
def temp_workspace():
    """使用仓库内临时目录，避开系统临时目录权限问题。"""
    base = ROOT / ".pytest_tmp"
    base.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix="siphon-case-selector-", dir=str(base)))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_siphon_panel_uses_compact_case_selector_without_left_splitter(monkeypatch, temp_workspace):
    """开启工况管理时，倒虹吸页不再创建左侧工况栏。"""
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", _fake_web_view_factory)
    monkeypatch.setattr(siphon_panel_mod, "_pkg_root", str(temp_workspace))

    panel = siphon_panel_mod.SiphonPanel(
        show_case_management=True,
        disable_autosave_load=True,
    )

    assert getattr(panel, "case_selector", None) is not None
    assert getattr(panel, "case_sidebar", None) is None
    assert panel.findChildren(QSplitter) == []
    assert panel.case_selector.get_current_case().name == "工况1"

    panel.deleteLater()


def test_case_selector_creates_new_case_and_selects_it(temp_workspace):
    """点击加号后新增工况，并自动切换到新工况。"""
    _get_qapp()
    module = _import_case_selector_module()
    manager = CaseManager(str(temp_workspace))
    manager.create_case()
    selector = module.CaseSelector(manager)

    selected = []
    selector.case_selected.connect(lambda case: selected.append(case.name))

    selector.btn_new.click()

    assert selector.get_current_case().name == "工况2"
    assert [case.name for case in manager.cases] == ["工况1", "工况2"]
    assert selected[-1] == "工况2"

    selector.deleteLater()


def test_case_selector_has_no_standalone_import_button(temp_workspace):
    """工况控件不再常驻显示导入按钮，低频导入收进更多菜单。"""
    _get_qapp()
    module = _import_case_selector_module()
    manager = CaseManager(str(temp_workspace))
    manager.create_case()
    selector = module.CaseSelector(manager)

    button_texts = {button.text() for button in selector.findChildren(PushButton)}

    assert "+" in button_texts
    assert "更多" in button_texts
    assert "导入" not in button_texts
    assert not hasattr(selector, "btn_import")

    selector.deleteLater()


def test_case_selector_more_menu_uses_specific_case_file_labels(monkeypatch, temp_workspace):
    """更多菜单应明确区分单个工况文件和项目文件。"""
    _get_qapp()
    module = _import_case_selector_module()
    manager = CaseManager(str(temp_workspace))
    manager.create_case()
    selector = module.CaseSelector(manager)

    actions = _open_more_menu(monkeypatch, module, selector)
    labels = [action.text() for action in actions]

    assert labels == [
        "重命名",
        "复制",
        "从文件添加工况...",
        "导出当前工况...",
        "删除",
    ]

    selector.deleteLater()


def test_case_selector_imports_wrapped_parameter_json_from_more_menu_and_selects_it(monkeypatch, temp_workspace):
    """更多菜单中的添加工况继续兼容旧参数 JSON，并自动选中导入工况。"""
    _get_qapp()
    module = _import_case_selector_module()
    manager = CaseManager(str(temp_workspace / "cases"))
    manager.create_case()
    selector = module.CaseSelector(manager)

    source_path = temp_workspace / "倒虹吸参数_老方案_20260425.json"
    source_path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "saved_at": "2026-04-25 10:00:00",
                "data": {"name": "老方案", "Q": 3.21, "v_guess": 2.4},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        module.QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(source_path), "JSON文件 (*.json)"),
    )

    actions = _open_more_menu(monkeypatch, module, selector)
    _trigger_menu_action(actions, "从文件添加工况...")

    assert selector.get_current_case().name == "老方案"
    assert manager.load_case_data(selector.get_current_case())["Q"] == 3.21

    selector.deleteLater()


def test_case_selector_exports_current_case_from_more_menu(monkeypatch, temp_workspace):
    """更多菜单中的导出当前工况只复制当前工况文件。"""
    _get_qapp()
    module = _import_case_selector_module()
    manager = CaseManager(str(temp_workspace / "cases"))
    case = manager.create_case("方案A")
    selector = module.CaseSelector(manager)
    target_path = temp_workspace / "方案A_导出.siphon.json"
    copied = []

    monkeypatch.setattr(
        module.QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: (str(target_path), "倒虹吸工况 (*.siphon.json)"),
    )
    monkeypatch.setattr(module.shutil, "copy", lambda src, dst: copied.append((src, dst)))

    actions = _open_more_menu(monkeypatch, module, selector)
    _trigger_menu_action(actions, "导出当前工况...")

    assert copied == [(case.file_path, str(target_path))]

    selector.deleteLater()


def test_siphon_panel_switches_case_from_selector_and_saves_current(monkeypatch, temp_workspace):
    """下拉切换工况时，应先保存当前工况，再加载目标工况。"""
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", _fake_web_view_factory)
    monkeypatch.setattr(siphon_panel_mod, "_pkg_root", str(temp_workspace))

    cases_dir = temp_workspace / "data" / "siphon_cases"
    manager = CaseManager(str(cases_dir))
    case1 = manager.create_case("方案A")
    case2 = manager.create_case("方案B")
    manager.save_case_data(case1, {"name": "方案A", "Q": 1.0, "v_guess": 2.0})
    manager.save_case_data(case2, {"name": "方案B", "Q": 2.0, "v_guess": 2.5})

    panel = siphon_panel_mod.SiphonPanel(
        show_case_management=True,
        disable_autosave_load=True,
    )
    panel.edit_Q.setText("9.9")
    panel._data_dirty = True

    panel.case_selector.combo_cases.setCurrentIndex(1)
    _get_qapp().processEvents()

    saved_case1 = CaseManager(str(cases_dir)).load_case_data(case1)
    assert saved_case1["Q"] == 9.9
    assert panel.edit_Q.text() == "2.0"
    assert panel.case_selector.get_current_case().name == "方案B"

    panel.deleteLater()
