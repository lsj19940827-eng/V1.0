# -*- coding: utf-8 -*-
"""倒虹吸加大流速参数链路映射单元测试。"""

from types import SimpleNamespace

from 推求水面线.utils.siphon_extractor import SiphonGroup
from app_渠系计算前端.siphon.multi_siphon_dialog import MultiSiphonDialog


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


def test_collect_velocity_source_warning_metadata_for_fallback_and_missing():
    groups = [
        SiphonGroup(
            name="虹吸C",
            upstream_velocity_source="adjacent",
            downstream_velocity_source="same_section_nearest_channel_fallback",
        ),
        SiphonGroup(
            name="虹吸D",
            upstream_velocity_source="missing",
            downstream_velocity_source="missing",
        ),
    ]

    metadata = MultiSiphonDialog._collect_velocity_source_warning_metadata(groups)

    assert metadata["fallback"] == ["虹吸C（下游）"]
    assert metadata["missing"] == ["虹吸D（上游/下游）"]

