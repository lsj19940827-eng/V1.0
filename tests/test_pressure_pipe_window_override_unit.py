# -*- coding: utf-8 -*-
"""匿名普通有压管道窗口覆盖结果回归测试。"""

import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))

from core.hydraulic_calc import HydraulicCalculator
from models.data_models import ChannelNode, ProjectSettings
from models.enums import StructureType, InOutType


def _make_open_channel(station_mc: float, velocity: float, name: str = "明渠") -> ChannelNode:
    node = ChannelNode()
    node.name = name
    node.flow_section = "2"
    node.structure_type = StructureType.from_string("明渠-梯形")
    node.station_MC = station_mc
    node.velocity = velocity
    node.water_depth = 1.3
    node.roughness = 0.025
    node.section_params = {"B": 2.4, "m": 1.5, "h": 1.3}
    return node


def test_unnamed_pressure_pipe_window_override_drives_losses_and_details():
    upstream = _make_open_channel(0.0, 0.85, name="上游明渠")

    pressure_pipe = ChannelNode()
    pressure_pipe.flow_section = "2"
    pressure_pipe.structure_type = StructureType.from_string("有压管道")
    pressure_pipe.in_out = InOutType.NORMAL
    pressure_pipe.station_MC = 47.0
    pressure_pipe.flow = 1.55
    pressure_pipe.velocity = 0.0
    pressure_pipe.water_depth = 1.4
    pressure_pipe.turn_radius = 35.0
    pressure_pipe.turn_angle = 18.0
    pressure_pipe.section_params = {
        "D": 1.4,
        "pipe_material": "球墨铸铁管",
        "pressure_pipe_window_override": {
            "enabled": True,
            "identity": "flow2-row2",
            "friction_loss": 0.0435,
            "total_bend_loss": 0.0068,
            "local_loss": 0.0112,
            "inlet_transition_loss": 0.0042,
            "outlet_transition_loss": 0.0070,
            "total_head_loss": 0.0615,
            "friction_details": {
                "method": "pressure_pipe_fmb",
                "length_source": "spatial",
                "hf": 0.0435,
            },
            "bend_details": {
                "method": "pressure_pipe_bend",
                "hw": 0.0068,
            },
            "local_details": {
                "method": "pressure_pipe_window_transition",
                "inlet": {"loss": 0.0042},
                "outlet": {"loss": 0.0070},
            },
        },
    }

    downstream = _make_open_channel(80.0, 0.92, name="下游明渠")

    settings = ProjectSettings()
    settings.channel_level = "干管"
    settings.start_water_level = 100.0

    calc = HydraulicCalculator(settings)
    for node in (upstream, pressure_pipe, downstream):
        calc.fill_section_params(node)

    calc.calculate_water_profile([upstream, pressure_pipe, downstream], method="forward")

    assert abs(pressure_pipe.head_loss_friction - 0.0435) < 1e-9
    assert abs(pressure_pipe.head_loss_bend - 0.0068) < 1e-9
    assert abs(pressure_pipe.head_loss_local - 0.0112) < 1e-9
    assert abs(pressure_pipe.head_loss_total - 0.0615) < 1e-9
    assert pressure_pipe.head_loss_siphon == 0.0
    assert pressure_pipe.external_head_loss is None

    assert pressure_pipe.friction_calc_details["source"] == "window_override"
    assert pressure_pipe.friction_calc_details["hf"] == 0.0435
    assert pressure_pipe.bend_calc_details["source"] == "window_override"
    assert pressure_pipe.bend_calc_details["hw"] == 0.0068
    assert pressure_pipe.transition_calc_details["method"] == "pressure_pipe_window_transition"


def test_pressure_pipe_window_override_preserves_chain_prefix_metadata_after_calculation():
    upstream = _make_open_channel(0.0, 0.85, name="上游明渠")

    pressure_pipe = ChannelNode()
    pressure_pipe.flow_section = "1"
    pressure_pipe.name = "大石包"
    pressure_pipe.structure_type = StructureType.from_string("定向钻")
    pressure_pipe.in_out = InOutType.INLET
    pressure_pipe.station_MC = 21.6
    pressure_pipe.flow = 0.32
    pressure_pipe.velocity = 0.0
    pressure_pipe.water_depth = 1.1
    pressure_pipe.turn_radius = 0.0
    pressure_pipe.turn_angle = 0.0
    pressure_pipe.section_params = {
        "D": 1.0,
        "pipe_material": "球墨铸铁管",
        "pressure_pipe_window_override": {
            "enabled": True,
            "identity": "1::苟家湾::rows83",
            "storage_key": "1::苟家湾::rows83",
            "display_name": "苟家湾（前缀段）",
            "group_mode": "chain_prefix_member",
            "data_mode": "链前缀段",
            "applied_at": "2026-04-08 21:13:14",
            "calc_steps": "prefix-step",
            "target_row_index": 1,
            "upstream_row_index": 0,
            "Q": 0.32,
            "D": 1.0,
            "total_length": 21.6,
            "pipe_velocity": 0.41,
            "friction_loss": 0.3188,
            "total_bend_loss": 0.0,
            "local_loss": 0.0,
            "inlet_transition_loss": 0.0,
            "outlet_transition_loss": 0.0,
            "total_head_loss": 0.3188,
            "friction_details": {"method": "gb50288", "hf": 0.3188},
            "bend_details": {},
            "local_details": {"method": "chain_prefix_member", "hj": 0.0},
        },
    }

    downstream = _make_open_channel(60.0, 0.92, name="下游明渠")

    settings = ProjectSettings()
    settings.channel_level = "支渠"
    settings.start_water_level = 100.0

    calc = HydraulicCalculator(settings)
    for node in (upstream, pressure_pipe, downstream):
        calc.fill_section_params(node)

    calc.calculate_water_profile([upstream, pressure_pipe, downstream], method="forward")

    override = pressure_pipe.pressure_pipe_window_override
    assert override["identity"] == "1::苟家湾::rows83"
    assert override["storage_key"] == "1::苟家湾::rows83"
    assert override["display_name"] == "苟家湾（前缀段）"
    assert override["group_mode"] == "chain_prefix_member"
    assert override["data_mode"] == "链前缀段"
    assert override["applied_at"] == "2026-04-08 21:13:14"
    assert override["calc_steps"] == "prefix-step"
    assert override["target_row_index"] == 1
    assert override["upstream_row_index"] == 0


def test_pressure_pipe_window_override_manual_total_head_loss_takes_priority_after_calculation():
    upstream = _make_open_channel(0.0, 0.85, name="上游明渠")

    pressure_pipe = ChannelNode()
    pressure_pipe.flow_section = "2"
    pressure_pipe.structure_type = StructureType.from_string("有压管道")
    pressure_pipe.in_out = InOutType.NORMAL
    pressure_pipe.station_MC = 47.0
    pressure_pipe.flow = 1.55
    pressure_pipe.velocity = 0.0
    pressure_pipe.water_depth = 1.4
    pressure_pipe.turn_radius = 35.0
    pressure_pipe.turn_angle = 18.0
    pressure_pipe.section_params = {
        "D": 1.4,
        "pipe_material": "球墨铸铁管",
        "pressure_pipe_window_override": {
            "enabled": True,
            "identity": "flow2-row2",
            "group_mode": "chain_row_member",
            "friction_loss": 0.0435,
            "total_bend_loss": 0.0068,
            "local_loss": 0.0112,
            "total_head_loss": 0.0615,
            "manual_total_head_loss": 0.0835,
            "manual_override_source": "pressure_pipe_loss_dialog",
            "manual_override_updated_at": "2026-04-13 18:50:00",
        },
    }

    downstream = _make_open_channel(80.0, 0.92, name="下游明渠")

    settings = ProjectSettings()
    settings.channel_level = "干管"
    settings.start_water_level = 100.0

    calc = HydraulicCalculator(settings)
    for node in (upstream, pressure_pipe, downstream):
        calc.fill_section_params(node)

    calc.calculate_water_profile([upstream, pressure_pipe, downstream], method="forward")

    assert abs(getattr(pressure_pipe, "_pressure_pipe_display_loss", 0.0) - 0.0835) < 1e-9
    assert abs(pressure_pipe.head_loss_total - 0.0835) < 1e-9
    assert abs(pressure_pipe.water_level - 99.9165) < 1e-9
    assert pressure_pipe.pressure_pipe_window_override["manual_total_head_loss"] == 0.0835
