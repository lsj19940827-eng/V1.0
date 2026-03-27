# -*- coding: utf-8 -*-
"""渐变段长度详情弹窗兼容展示单元测试。"""

import importlib.util
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_formula_dialog_module():
    module_path = next(Path(".").glob("**/water_profile/formula_dialog.py")).resolve()
    spec = importlib.util.spec_from_file_location("wp_transition_length_formula_dialog_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_show_transition_length_dialog_marks_existing_length_as_authoritative(monkeypatch):
    module = _load_formula_dialog_module()
    captured = {}

    class _FakeFormulaDialog:
        def __init__(self, parent, title, sections):
            captured["parent"] = parent
            captured["title"] = title
            captured["sections"] = sections

    monkeypatch.setattr(module, "FormulaDialog", _FakeFormulaDialog)

    module.show_transition_length_dialog(
        None,
        "行2",
        {
            "transition_type": "进口",
            "struct_name": "隧洞-圆形",
            "B1": 5.2,
            "B2": 1.8,
            "coefficient": 2.5,
            "L_basic": 8.5,
            "channel_depth": 1.6,
            "L_result": 9.0,
            "actual_length": 9.0,
            "formula_length": 12.0,
            "uses_existing_length": True,
            "constraint_applied": "隧洞-圆形",
            "constraint_desc": "max(5倍水深, 3倍洞径/洞宽)",
            "depth_multiplier": 5,
            "L_depth": 8.0,
            "tunnel_multiplier": 3,
            "tunnel_size": 4.0,
            "L_tunnel": 12.0,
            "prev_name": "上游明渠",
            "next_name": "隧洞1",
        },
    )

    text_blob = "\n".join(
        "\n".join(
            str(section.get(key, ""))
            for key in ("title", "values", "content", "formula")
        )
        for section in captured["sections"]
    )

    assert captured["title"] == "行2 - 渐变段长度计算详情"
    assert "当前采用长度" in text_blob
    assert "公式/规范计算值" in text_blob
    assert "9.000" in text_blob
    assert "12.000" in text_blob
