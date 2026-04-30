# -*- coding: utf-8 -*-
"""测试圆拱直墙型按净空反推尺寸弹窗本体。"""

import importlib
import math
import os
import sys
import tempfile
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QWidget


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(tempfile.gettempdir()) / "codex-mplconfig"),
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _get_qapp():
    """获取测试用 Qt 应用。"""
    return QApplication.instance() or QApplication([])


def _local_prefs_path(name):
    """生成项目内测试偏好路径，避开系统临时目录权限差异。"""
    base = ROOT / ".pytest_tmp" / "clearance_sizing_dialog"
    base.mkdir(parents=True, exist_ok=True)
    return base / name


class _DummyCanvas(QWidget):
    """替代 matplotlib Qt 画布，避免离屏测试依赖真实渲染。"""

    def __init__(self, _figure):
        super().__init__()

    def draw_idle(self):
        """忽略预览刷新。"""
        return None


def _new_dialog(monkeypatch, *, prefs_path=None, context_overrides=None):
    """创建测试弹窗。"""
    dialog_mod = importlib.import_module("app_渠系计算前端.tunnel.clearance_sizing_dialog")
    monkeypatch.setattr(dialog_mod, "FigureCanvas", _DummyCanvas)
    if prefs_path is None:
        prefs_path = _local_prefs_path("default.json")
        if prefs_path.exists():
            prefs_path.unlink()
    monkeypatch.setattr(
        dialog_mod,
        "_get_clearance_sizing_prefs_path",
        lambda: str(prefs_path),
        raising=False,
    )
    _get_qapp()
    context = {
        "Q_design": 10.0,
        "Q_increased": 12.0,
        "Q_increased_source": "auto_percent",
        "n": 0.014,
        "slope_inv": 3000.0,
        "v_min": 0.1,
        "v_max": 3.0,
        "theta_deg": 120.0,
    }
    context.update(context_overrides or {})
    return dialog_mod.HorseshoeClearanceSizingDialog(None, context)


def test_clearance_sizing_dialog_uses_15_percent_default(monkeypatch):
    """无历史偏好时，目标净空比例默认应为15%。"""
    dialog = _new_dialog(monkeypatch, prefs_path=_local_prefs_path("missing.json"))

    assert dialog.freeboard_edit.text() == "15.000"
    dialog.close()


def test_clearance_sizing_dialog_remembers_last_inputs(monkeypatch):
    """计算成功后，弹窗应跨实例恢复用户上次输入。"""
    prefs_path = _local_prefs_path("clearance_sizing_prefs.json")
    if prefs_path.exists():
        prefs_path.unlink()
    dialog = _new_dialog(monkeypatch, prefs_path=prefs_path)
    dialog.q_inc_edit.setText("12.8")
    dialog.freeboard_edit.setText("15")
    dialog.hb_edit.setText("1.1")
    dialog.theta_edit.setText("120")

    dialog._calculate()
    dialog.close()

    restored = _new_dialog(monkeypatch, prefs_path=prefs_path)
    assert restored.q_inc_edit.text() == "12.8"
    assert restored.freeboard_edit.text() == "15"
    assert restored.hb_edit.text() == "1.1"
    assert restored.theta_edit.text() == "120"
    restored.close()


def test_clearance_sizing_dialog_uses_main_flow_when_design_flow_changes(monkeypatch):
    """主流程设计流量变化后，Q加大应跟随新工况，不沿用旧弹窗输入。"""
    prefs_path = _local_prefs_path("q_change_prefs.json")
    if prefs_path.exists():
        prefs_path.unlink()
    dialog = _new_dialog(monkeypatch, prefs_path=prefs_path)
    dialog.q_inc_edit.setText("12.8")
    dialog.freeboard_edit.setText("15")
    dialog.hb_edit.setText("1.1")
    dialog.theta_edit.setText("120")
    dialog._calculate()
    dialog.close()

    restored = _new_dialog(
        monkeypatch,
        prefs_path=prefs_path,
        context_overrides={
            "Q_design": 38.0,
            "Q_increased": 43.7,
            "Q_increased_source": "auto_percent",
        },
    )

    assert restored.q_inc_edit.text() == "43.700"
    assert restored.freeboard_edit.text() == "15"
    assert restored.hb_edit.text() == "1.1"
    assert restored.theta_edit.text() == "120"
    restored.close()


def test_clearance_sizing_dialog_restores_q_only_for_same_main_flow_context(monkeypatch):
    """主流程上下文未变化时，弹窗手改 Q加大 才应恢复。"""
    prefs_path = _local_prefs_path("same_context_prefs.json")
    if prefs_path.exists():
        prefs_path.unlink()
    dialog = _new_dialog(monkeypatch, prefs_path=prefs_path)
    dialog.q_inc_edit.setText("12.8")
    dialog._calculate()
    dialog.close()

    restored = _new_dialog(monkeypatch, prefs_path=prefs_path)

    assert restored.q_inc_edit.text() == "12.8"
    restored.close()


def test_clearance_sizing_dialog_discards_q_when_main_flow_source_changes(monkeypatch):
    """主流程加大来源变化后，弹窗应使用主流程 Q加大。"""
    prefs_path = _local_prefs_path("source_change_prefs.json")
    if prefs_path.exists():
        prefs_path.unlink()
    dialog = _new_dialog(monkeypatch, prefs_path=prefs_path)
    dialog.q_inc_edit.setText("12.8")
    dialog._calculate()
    dialog.close()

    restored = _new_dialog(
        monkeypatch,
        prefs_path=prefs_path,
        context_overrides={
            "Q_design": 10.0,
            "Q_increased": 12.5,
            "Q_increased_source": "manual_percent",
        },
    )

    assert restored.q_inc_edit.text() == "12.500"
    restored.close()


def test_clearance_sizing_dialog_ignores_broken_preferences(monkeypatch):
    """偏好文件损坏时，弹窗应安全回到默认值。"""
    prefs_path = _local_prefs_path("broken.json")
    prefs_path.write_text("{bad json", encoding="utf-8")

    dialog = _new_dialog(monkeypatch, prefs_path=prefs_path)

    assert dialog.freeboard_edit.text() == "15.000"
    assert dialog.hb_edit.text() == "1.200"
    dialog.close()


def test_clearance_sizing_dialog_enables_apply_after_valid_calculation(monkeypatch):
    """弹窗算出有效结果后才允许采用。"""
    dialog = _new_dialog(monkeypatch)

    assert dialog.apply_btn.isEnabled() is False
    dialog._calculate()

    assert dialog.apply_btn.isEnabled() is True
    assert dialog.result_payload["success"] is True
    assert "3." in dialog.result_labels["B"].text()
    dialog.close()


def test_clearance_sizing_dialog_keeps_apply_disabled_on_invalid_input(monkeypatch):
    """弹窗输入无效时应禁用采用并显示原因。"""
    dialog = _new_dialog(monkeypatch)
    dialog.hb_edit.setText("1.8")

    dialog._calculate()

    assert dialog.apply_btn.isEnabled() is False
    assert dialog.result_payload is None
    assert "高宽比" in dialog.status_label.text()
    dialog.close()


def test_clearance_sizing_dialog_preview_fill_follows_arch_wall_outline(monkeypatch):
    """断面预览水域进入拱部时，填充区域仍应贴到直墙边界。"""
    dialog = _new_dialog(monkeypatch)
    result = {
        "B": 2.988,
        "H_total": 3.585,
        "h_increased": 2.623,
        "theta_deg": 180.0,
    }

    dialog._draw_preview(result)

    ax = dialog.figure.axes[0]
    if ax.patches:
        fill_vertices = ax.patches[0].get_xy()
    else:
        fill_vertices = ax.collections[0].get_paths()[0].vertices
    fill_max_half_width = max(abs(point[0]) for point in fill_vertices)
    blue_lines = [line for line in ax.lines if line.get_color() == "#0284C7"]
    waterline_half_width = max(abs(x) for x in blue_lines[0].get_xdata())
    half_bottom_width = result["B"] / 2.0
    radius = half_bottom_width / math.sin(math.radians(result["theta_deg"]) / 2.0)
    h_arch = radius * (1.0 - math.cos(math.radians(result["theta_deg"]) / 2.0))
    h_straight = result["H_total"] - h_arch

    assert result["h_increased"] > h_straight
    assert waterline_half_width < half_bottom_width
    assert fill_max_half_width == pytest.approx(half_bottom_width, abs=1e-6)
    dialog.close()
