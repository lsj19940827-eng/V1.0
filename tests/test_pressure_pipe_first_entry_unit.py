"""有压管道首次进入的依赖加载和延迟帮助页回归。"""

import os
from pathlib import Path
import subprocess
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTextBrowser

from app_渠系计算前端.pressure_pipe import panel as panel_module


ROOT = Path(__file__).resolve().parents[1]


def test_first_entry_and_single_calculation_do_not_load_batch_libraries():
    """独立进程检查首次创建及普通选径，避免已导入模块掩盖加载回归。"""
    script = """
import sys
from app_渠系计算前端.bootstrap import initialize_runtime_environment
from app_渠系计算前端.qfluentwidgets_compat import ensure_qfluentwidgets_compat
initialize_runtime_environment()
ensure_qfluentwidgets_compat()
from PySide6.QtWidgets import QApplication
from app_渠系计算前端.pressure_pipe.panel import PressurePipePanel
from 有压管道设计 import PressurePipeInput, recommend_diameter
app = QApplication([])
panel = PressurePipePanel()
result = recommend_diameter(PressurePipeInput(Q=0.5, material_key='HDPE管'))
assert result.recommended is not None
assert 'pandas' not in sys.modules
assert 'scipy.optimize' not in sys.modules
panel.close()
"""
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", CODEX_FORCE_QTEXTBROWSER="1")
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, env=env,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture
def panel(monkeypatch):
    """使用真实控件和事件循环，文本视图只替代网页进程。"""
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(panel_module, "_create_result_view", QTextBrowser)
    widget = panel_module.PressurePipePanel()
    yield widget, app
    widget.close()
    widget.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("restore_errors", [False, True])
def test_first_show_preserves_restored_result_or_error_page(panel, restore_errors):
    """项目先恢复、页面后显示时，成果与错误详情均不能被帮助页替换。"""
    widget, app = panel
    if restore_errors:
        payload = {"cases": [widget._default_case()], "last_errors": ["测试工况输入错误"]}
    else:
        widget.Q_edit.setText("0.5")
        widget._calculate()
        payload = widget.to_project_dict()
        assert payload["all_results"]
    widget.from_project_dict(payload)
    expected = widget.result_view.toPlainText()
    assert expected
    if restore_errors:
        assert "测试工况输入错误" in expected
    widget.resize(1200, 800)
    widget.show()
    for _ in range(4):
        app.processEvents()
    assert widget.result_view.toPlainText() == expected


def test_quickly_leaving_page_defers_help_until_visible(panel, monkeypatch):
    """显示后立即离开时不做隐藏页渲染，重新进入只执行一次。"""
    widget, app = panel
    calls = []

    def render_help():
        """记录真正完成的帮助页渲染。"""
        widget._initial_help_rendered = True
        calls.append(True)

    monkeypatch.setattr(widget, "_show_initial_help", render_help)
    widget.show()
    widget.hide()
    app.processEvents()
    assert calls == []
    widget.show()
    for _ in range(3):
        app.processEvents()
    widget.hide()
    widget.show()
    app.processEvents()
    assert calls == [True]
