# -*- coding: utf-8 -*-
"""倒虹吸 starter 工况空白几何与默认通用构件配置回归测试。"""

from __future__ import annotations

import json
from pathlib import Path


def _starter_case_path(case_name: str) -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "siphon_cases" / case_name


def test_starter_case_is_blank_and_keeps_transition_defaults():
    data = json.loads(_starter_case_path("工况1.siphon.json").read_text(encoding="utf-8"))

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
