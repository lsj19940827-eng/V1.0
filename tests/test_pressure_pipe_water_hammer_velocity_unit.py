# -*- coding: utf-8 -*-
"""水锤验算流速工况解析单元测试。"""

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "推求水面线") not in sys.path:
    sys.path.insert(0, str(ROOT / "推求水面线"))

from 推求水面线.core.pressure_pipe_calc import (  # noqa: E402
    calc_pipe_velocity,
    resolve_water_hammer_velocity,
)


def test_resolve_water_hammer_velocity_uses_increased_flow_when_enabled():
    """勾选加大流量且Q加大有效时，水锤流速应取Q加大/A。"""
    result = resolve_water_hammer_velocity(
        design_flow_m3s=1.0,
        increased_flow_m3s=1.25,
        use_increase=True,
        diameter_m=1.0,
    )

    assert result["velocity_mps"] == pytest.approx(calc_pipe_velocity(1.25, 1.0))
    assert result["flow_m3s"] == pytest.approx(1.25)
    assert result["source"] == "加大流量"
    assert result["use_increase"] is True
    assert result["warning"] == ""


def test_resolve_water_hammer_velocity_uses_design_flow_when_increase_disabled():
    """未勾选加大流量时，水锤流速应固定取设计流量。"""
    result = resolve_water_hammer_velocity(
        design_flow_m3s=1.0,
        increased_flow_m3s=1.25,
        use_increase=False,
        diameter_m=1.0,
    )

    assert result["velocity_mps"] == pytest.approx(calc_pipe_velocity(1.0, 1.0))
    assert result["flow_m3s"] == pytest.approx(1.0)
    assert result["source"] == "设计流量"
    assert result["use_increase"] is False
    assert result["warning"] == ""


def test_resolve_water_hammer_velocity_falls_back_to_design_flow_when_increased_missing():
    """勾选加大流量但Q加大缺失时，应按设计流量并返回提示。"""
    result = resolve_water_hammer_velocity(
        design_flow_m3s=1.0,
        increased_flow_m3s=0.0,
        use_increase=True,
        diameter_m=1.0,
    )

    assert result["velocity_mps"] == pytest.approx(calc_pipe_velocity(1.0, 1.0))
    assert result["flow_m3s"] == pytest.approx(1.0)
    assert result["source"] == "设计流量"
    assert "缺少有效Q加大" in result["warning"]


def test_resolve_water_hammer_velocity_uses_history_when_diameter_invalid():
    """管径无效且无法自动算流速时，才允许历史流速兜底。"""
    result = resolve_water_hammer_velocity(
        design_flow_m3s=1.0,
        increased_flow_m3s=1.2,
        use_increase=True,
        diameter_m=0.0,
        fallback_velocity_mps=0.88,
    )

    assert result["velocity_mps"] == pytest.approx(0.88)
    assert result["flow_m3s"] == pytest.approx(1.2)
    assert result["source"] == "历史流速兜底"
    assert "历史流速兜底" in result["warning"]


def test_resolve_water_hammer_velocity_returns_zero_when_all_inputs_invalid():
    """管径、流量和历史流速都无效时，让现有缺v0提示继续生效。"""
    result = resolve_water_hammer_velocity(
        design_flow_m3s=0.0,
        increased_flow_m3s=0.0,
        use_increase=True,
        diameter_m=math.nan,
        fallback_velocity_mps=0.0,
    )

    assert result["velocity_mps"] == pytest.approx(0.0)
    assert result["flow_m3s"] == pytest.approx(0.0)
    assert result["source"] == "加大流量"
    assert result["warning"]
