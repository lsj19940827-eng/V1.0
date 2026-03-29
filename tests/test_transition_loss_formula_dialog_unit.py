# -*- coding: utf-8 -*-
"""渐变段水头损失弹窗完整推导单元测试。"""

import importlib.util
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QWidget


def _load_formula_dialog_module():
    module_path = next(Path(".").glob("**/water_profile/formula_dialog.py")).resolve()
    spec = importlib.util.spec_from_file_location("wp_transition_loss_formula_dialog_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _get_qapp():
    return QApplication.instance() or QApplication([])


def test_show_transition_loss_dialog_renders_complete_derivation_sections(monkeypatch):
    module = _load_formula_dialog_module()
    captured = {}

    class _FakeFormulaDialog:
        def __init__(self, parent, title, sections):
            captured["parent"] = parent
            captured["title"] = title
            captured["sections"] = sections

    monkeypatch.setattr(module, "FormulaDialog", _FakeFormulaDialog)

    module.show_transition_loss_dialog(
        None,
        "渐变段1",
        {
            "transition_type": "进口",
            "transition_form": "曲线形反弯扭曲面",
            "zeta": 0.1,
            "v1": 1.035,
            "v2": 1.313,
            "B1": 5.785,
            "B2": 5.113,
            "length": 12.075,
            "R1": 0.782,
            "R2": 0.745,
            "R_avg": 0.7635,
            "v_avg": 1.174,
            "n": 0.014,
            "hydraulic_slope_i": 0.000414,
            "h_j1": 0.0033,
            "h_f": 0.0050,
            "total": 0.0083,
            "length_details": {
                "transition_type": "进口",
                "struct_name": "隧洞-马蹄形",
                "B1": 5.785,
                "B2": 5.113,
                "coefficient": 2.5,
                "L_basic": 1.68,
                "channel_depth": 1.6,
                "L_result": 12.075,
                "constraint_applied": "隧洞-马蹄形",
                "constraint_desc": "max(5倍水深, 3倍洞径/洞宽)",
                "depth_multiplier": 5,
                "L_depth": 8.0,
                "tunnel_multiplier": 3,
                "tunnel_size": 4.025,
                "L_tunnel": 12.075,
                "prev_name": "上游明渠",
                "next_name": "隧洞1",
            },
        },
    )

    titles = [section.get("title", "") for section in captured["sections"]]
    text_blob = "\n".join(
        "\n".join(
            str(section.get(key, ""))
            for key in ("title", "values", "content", "formula")
        )
        for section in captured["sections"]
    )

    assert captured["title"] == "渐变段1 - 渐变段水头损失计算详情"
    assert len(captured["sections"]) == 9
    assert titles == [
        "1. 基本信息",
        "2. 渐变段长度计算过程",
        "3. 流速参数",
        "4. 水力半径参数",
        "5. 平均参数计算",
        "6. 局部水头损失公式与代入",
        "7. 平均水力坡降计算",
        "8. 沿程水头损失代入计算",
        "9. 总水头损失",
    ]
    assert "R_{avg}" in text_blob
    assert "v_{avg}" in text_blob
    assert "i =" in text_blob
    assert "h_f = i" in text_blob


def test_formula_dialog_builds_html_in_webview_mode(monkeypatch):
    module = _load_formula_dialog_module()
    _get_qapp()
    captured = {}

    class _FakeWebView(QWidget):
        def setHtml(self, html):
            captured["html"] = html

    monkeypatch.setattr(module, "HAS_WEBENGINE", True)
    monkeypatch.setattr(module, "HAS_SVG_RENDERER", True)
    monkeypatch.setattr(module, "create_web_view", lambda: _FakeWebView())

    dialog = module.FormulaDialog(
        None,
        "测试弹窗",
        [{"title": "1. 标题", "content": "正文"}],
        auto_exec=False,
    )
    try:
        assert "测试弹窗" == dialog.windowTitle()
        assert "1. 标题" in captured["html"]
        assert "正文" in captured["html"]
    finally:
        dialog.deleteLater()
