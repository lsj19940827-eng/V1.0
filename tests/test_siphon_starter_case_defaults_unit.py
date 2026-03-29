# -*- coding: utf-8 -*-
"""倒虹吸 starter 工况默认渐变段配置回归测试。"""

from __future__ import annotations

import json
from pathlib import Path


def _starter_case_path(case_name: str) -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "siphon_cases" / case_name


def test_starter_cases_default_to_linear_twist_transition():
    for case_name in ("工况1.siphon.json", "工况2.siphon.json"):
        data = json.loads(_starter_case_path(case_name).read_text(encoding="utf-8"))

        assert data["inlet_type"] == "直线扭曲面"
        assert data["outlet_type"] == "直线扭曲面"
        assert data["xi_inlet"] == 0.2
        assert data["xi_outlet"] == 0.4
