import os
import sys
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "倒虹吸水力计算系统"))

from siphon_hydraulics import HydraulicCore  # noqa: E402
from siphon_models import GlobalParameters, GradientType, V2Strategy  # noqa: E402


def test_detailed_steps_do_not_include_english_stage_titles():
    params = GlobalParameters(
        Q=4.0,
        v_guess=2.0,
        roughness_n=0.014,
        inlet_type=GradientType.QUARTER_ARC,
        outlet_type=GradientType.QUARTER_ARC,
        v_channel_in=0.0,
        v_pipe_in=0.0,
        v_channel_out=0.0,
        v_pipe_out=0.0,
        xi_inlet=0.1,
        xi_outlet=0.2,
        v2_strategy=V2Strategy.AUTO_PIPE,
    )

    result = HydraulicCore.execute_calculation(params, [], verbose=True)
    detail_text = HydraulicCore.format_result(result, show_steps=True)

    assert "步骤1：几何设计与流速计算" in detail_text
    assert "步骤2：阻力参数初始化" in detail_text
    assert "步骤3：水头损失求解" in detail_text

    assert "(Geometry & Velocity)" not in detail_text
    assert "(Resistance Setup)" not in detail_text
    assert "(Head Loss Calculation)" not in detail_text
