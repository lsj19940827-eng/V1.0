# -*- coding: utf-8 -*-
"""倒虹吸加大流速参数链路映射单元测试。"""

from types import SimpleNamespace

from 推求水面线.utils.siphon_extractor import SiphonGroup
from 渠系断面设计.siphon.multi_siphon_dialog import MultiSiphonDialog


def _fake_dialog(turn_n: float = 0.0):
    return SimpleNamespace(_siphon_turn_radius_n=turn_n)


def test_group_increased_velocity_maps_to_panel_param_keys():
    group = SiphonGroup(
        name="虹吸A",
        design_flow=2.0,
        roughness=0.014,
        upstream_velocity_increased=1.234,
        downstream_velocity_increased=2.345,
    )

    params = MultiSiphonDialog._build_params_from_group(_fake_dialog(), group)

    assert params["v_channel_in_inc"] == 1.234
    assert params["v_pipe_out_inc"] == 2.345


def test_zero_increased_velocity_not_injected_into_params():
    group = SiphonGroup(
        name="虹吸B",
        design_flow=1.0,
        roughness=0.014,
        upstream_velocity_increased=0.0,
        downstream_velocity_increased=0.0,
    )

    params = MultiSiphonDialog._build_params_from_group(_fake_dialog(), group)

    assert "v_channel_in_inc" not in params
    assert "v_pipe_out_inc" not in params

