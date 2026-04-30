# -*- coding: utf-8 -*-
"""测试圆拱直墙型按净空反推尺寸弹窗本体。"""

import importlib
import os
import sys
import tempfile
from pathlib import Path

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


class _DummyCanvas(QWidget):
    """替代 matplotlib Qt 画布，避免离屏测试依赖真实渲染。"""

    def __init__(self, _figure):
        super().__init__()

    def draw_idle(self):
        """忽略预览刷新。"""
        return None


def _new_dialog(monkeypatch):
    """创建测试弹窗。"""
    dialog_mod = importlib.import_module("app_渠系计算前端.tunnel.clearance_sizing_dialog")
    monkeypatch.setattr(dialog_mod, "FigureCanvas", _DummyCanvas)
    _get_qapp()
    return dialog_mod.HorseshoeClearanceSizingDialog(
        None,
        {
            "Q_design": 10.0,
            "Q_increased": 12.0,
            "n": 0.014,
            "slope_inv": 3000.0,
            "v_min": 0.1,
            "v_max": 3.0,
            "theta_deg": 120.0,
        },
    )


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
