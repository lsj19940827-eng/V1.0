# -*- coding: utf-8 -*-
"""闸两侧水位正式递推、旧成果恢复及持久化回归。"""

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "推求水面线") not in sys.path:
    sys.path.insert(0, str(ROOT / "推求水面线"))

from 推求水面线.core.calculator import WaterProfileCalculator
from 推求水面线.core.hydraulic_calc import HydraulicCalculator
from 推求水面线.models.data_models import (
    ChannelNode, ProjectSettings, restore_gate_water_levels,
)
from 推求水面线.models.enums import StructureType
from 推求水面线.models.profile_node_codec import (
    GATE_UPSTREAM_WATER_LEVEL_ROLE_KEY, GATE_DOWNSTREAM_WATER_LEVEL_ROLE_KEY,
    ProfileNodeCodec,
)
from 推求水面线.models.profile_state import ProfileRow, ProfileTableState


def _channel(name, x):
    return ChannelNode(
        name=name, structure_type=StructureType.MINGQU_RECTANGULAR,
        flow_section="1", flow=2.0, x=float(x),
        section_params={"B": 2.0, "h": 1.2, "m": 0.0},
        water_depth=1.2, structure_height=2.5, slope_i=0.001,
    )


def _gate(name, x, loss=None):
    node = ChannelNode(
        name=name, structure_type=StructureType.CHECK_GATE,
        flow_section="1", flow=2.0, x=float(x), is_diversion_gate=True,
    )
    if loss is not None:
        node.head_loss_gate = loss
        node.section_params["gate_head_loss_user_set"] = True
    return node


def _calculate(nodes):
    return WaterProfileCalculator(
        ProjectSettings(start_water_level=100.0, design_flow=2.0),
    ).calculate_all(nodes)


def test_calculate_all_saves_both_sides_and_accounts_for_upstream_channel_interval():
    results = _calculate([_channel("上游", 0), _gate("中间闸", 100), _channel("下游", 200)])
    upstream, gate, downstream = results

    # 闸是点状，但上游100米渠道区间仍有0.1米摩阻。
    assert [n.water_level for n in results] == pytest.approx([100.0, 99.8, 99.7])
    assert gate.gate_upstream_water_level == pytest.approx(99.9)
    assert gate.gate_downstream_water_level == pytest.approx(gate.water_level)
    assert gate.head_loss_gate == pytest.approx(0.1)
    assert gate.head_loss_friction == pytest.approx(0.1)
    assert gate.head_loss_total == pytest.approx(0.2)
    assert gate.bottom_elevation == pytest.approx(98.7)
    assert gate.top_elevation == pytest.approx(101.2)
    assert gate.terminal_gate_backfill_details["donor_name"] == "上游"
    assert gate.terminal_gate_backfill_details["donor_direction"] == "上游"
    assert gate.water_depth == 0.0
    assert gate.structure_height == 0.0
    assert upstream.gate_upstream_water_level is None
    assert downstream.gate_downstream_water_level is None


def test_calculate_all_respects_manual_zero_gate_loss():
    _, gate, downstream = _calculate(
        [_channel("上游", 0), _gate("零损失闸", 100, loss=0.0), _channel("下游", 200)],
    )

    assert gate.gate_upstream_water_level == pytest.approx(99.9)
    assert gate.gate_downstream_water_level == pytest.approx(99.9)
    assert gate.water_level == pytest.approx(99.9)
    assert gate.head_loss_gate == 0.0
    assert downstream.water_level == pytest.approx(99.8)


def test_calculate_all_tracks_each_of_multiple_gates_independently():
    results = _calculate([
        _channel("上游", 0), _gate("闸一", 100),
        _gate("闸二", 150, loss=0.025), _channel("下游", 250),
    ])
    gate_one, gate_two = results[1:3]

    assert (gate_one.gate_upstream_water_level, gate_one.gate_downstream_water_level) == pytest.approx((99.9, 99.8))
    assert (gate_two.gate_upstream_water_level, gate_two.gate_downstream_water_level) == pytest.approx((99.75, 99.725))
    assert gate_two.head_loss_friction == pytest.approx(0.05)
    assert results[-1].water_level == pytest.approx(99.625)


def test_calculate_all_first_gate_has_only_known_downstream_boundary():
    first_gate, downstream = _calculate([_gate("起点闸", 0), _channel("下游", 100)])

    assert first_gate.water_level == 100.0
    assert first_gate.gate_upstream_water_level is None
    assert first_gate.gate_downstream_water_level == 100.0
    assert downstream.water_level == pytest.approx(99.9)


def test_final_recurrence_refreshes_gate_after_actual_transition_losses():
    upstream = _channel("起点", 0)
    upstream.gate_upstream_water_level = 123.0
    transition = ChannelNode(is_transition=True, head_loss_transition=0.25)
    middle = _channel("渐变段下游", 100)
    middle.head_loss_friction = 0.05
    gate = _gate("下游闸", 150, loss=0.1)
    gate.head_loss_friction = 0.025
    gate.gate_upstream_water_level = 888.0
    gate.gate_downstream_water_level = 777.0

    HydraulicCalculator(ProjectSettings(start_water_level=100.0)).recalculate_water_levels_with_transition_losses(
        [upstream, transition, middle, gate],
    )

    assert gate.gate_upstream_water_level == pytest.approx(99.675)
    assert gate.gate_downstream_water_level == pytest.approx(99.575)
    assert gate.water_level == pytest.approx(99.575)
    assert upstream.gate_upstream_water_level is None
    assert middle.gate_downstream_water_level is None
    assert transition.gate_upstream_water_level is None


def test_saved_project_round_trip_preserves_gate_sides_and_manual_zero_loss():
    results = _calculate([_channel("上游", 0), _gate("零损失闸", 100, loss=0.0)])
    saved = json.loads(json.dumps([node.to_project_dict() for node in results], ensure_ascii=False))
    restored = [ChannelNode.from_project_dict(item) for item in saved]

    assert restored[1].gate_upstream_water_level == pytest.approx(99.9)
    assert restored[1].gate_downstream_water_level == pytest.approx(99.9)
    assert restored[1].head_loss_gate == 0.0
    assert restored[1].section_params["gate_head_loss_user_set"] is True
    assert restored[1].to_dict()["闸前水位"] == pytest.approx(99.9)
    assert restored[1].to_dict()["闸后水位"] == pytest.approx(99.9)


def test_restore_legacy_gate_results_does_not_recalculate_water_level_or_loss():
    first = _channel("上游", 0)
    first.water_level = 100.1234
    transition = ChannelNode(is_transition=True, water_level=987.0)
    gate = _gate("旧项目闸", 100, loss=0.025)
    gate.water_level = 99.9876
    before = (gate.water_level, gate.head_loss_gate, gate.head_loss_total)

    restore_gate_water_levels([first, transition, gate])

    # 历史上一节点到闸前可能还有区间水损；补显示应采用本闸已存闸后+闸损。
    assert gate.gate_upstream_water_level == pytest.approx(100.0126)
    assert gate.gate_downstream_water_level == 99.9876
    assert (gate.water_level, gate.head_loss_gate, gate.head_loss_total) == before
    assert transition.gate_upstream_water_level is None


def test_restore_uncomputed_legacy_gate_does_not_invent_zero_results():
    upstream = _channel("已有上游", 0)
    upstream.water_level = 100.0
    uncomputed = _gate("尚未计算", 100)

    restore_gate_water_levels([upstream, uncomputed])

    assert uncomputed.gate_upstream_water_level is None
    assert uncomputed.gate_downstream_water_level is None


def test_restore_keeps_explicit_zero_but_discards_nonfinite_and_nongate_fields():
    upstream = _channel("上游", 0)
    upstream.water_level = 100.0
    upstream.gate_upstream_water_level = 999.0
    gate = _gate("显式零高程", 100)
    gate.gate_upstream_water_level = 0.0
    gate.gate_downstream_water_level = 0.0
    invalid = _gate("非有限值", 200)
    invalid.water_level = float("nan")
    invalid.gate_upstream_water_level = float("inf")
    invalid.gate_downstream_water_level = float("nan")

    restore_gate_water_levels([upstream, gate, invalid])

    assert upstream.gate_upstream_water_level is None
    assert gate.gate_upstream_water_level == 0.0
    assert gate.gate_downstream_water_level == 0.0
    assert invalid.gate_upstream_water_level is None
    assert invalid.gate_downstream_water_level is None


def test_project_loading_discards_gate_sides_on_changed_structure():
    node = ChannelNode.from_project_dict({
        "structure_type": "明渠-矩形", "is_diversion_gate": True,
        "gate_upstream_water_level": 123.0, "gate_downstream_water_level": 122.9,
    })

    assert node.gate_upstream_water_level is None
    assert node.gate_downstream_water_level is None


@pytest.mark.parametrize("saved_gate_loss,expected_upstream", [(0.1, 0.0), (0.0, -0.1)])
def test_restore_uses_saved_gate_loss_instead_of_previous_zero_gate_boundary(saved_gate_loss, expected_upstream):
    first = _gate("零高程起点闸", 0)
    first.gate_downstream_water_level = 0.0
    second = _gate("下一闸", 100, loss=saved_gate_loss)
    second.water_level = -0.1

    restore_gate_water_levels([first, second])

    assert first.gate_upstream_water_level is None
    # 已保存0.1米闸损可确认闸前为零；显式零闸损则两侧都为-0.1。
    assert second.gate_upstream_water_level == pytest.approx(expected_upstream)
    assert second.gate_downstream_water_level == -0.1


def _profile_state(*, gate_water="99.900", gate_upstream=None, gate_downstream=None, exact=None, roles=False):
    rows = []
    for index, structure in enumerate(("明渠-矩形", "节制闸")):
        cells = [""] * 44
        cells[0:3] = ["1", f"节点{index}", structure]
        cells[5:8] = [str(index * 100), "0", "0"]
        cells[20:27] = ["2", "", "", "0", "0.014", "1000", "2"]
        cells[37] = "0.1" if index else ""
        cells[41] = "100.000" if index == 0 else gate_water
        cell_data = {}
        if roles and index == 1:
            cell_data[0] = {
                GATE_UPSTREAM_WATER_LEVEL_ROLE_KEY: gate_upstream,
                GATE_DOWNSTREAM_WATER_LEVEL_ROLE_KEY: gate_downstream,
            }
            if exact is not None:
                cell_data[0]["_numeric_display_values"] = {
                    "41": {"text": cells[41], "value": exact},
                }
        rows.append(ProfileRow(str(index), cells, cell_data))
    return ProfileTableState(rows=rows, column_count=44)


def test_codec_decodes_old_44_column_results_with_legacy_sides():
    nodes = ProfileNodeCodec(_profile_state()).decode()

    assert nodes[1].gate_upstream_water_level == 100.0
    assert nodes[1].gate_downstream_water_level == 99.9
    assert nodes[1].water_level == 99.9


def test_codec_retains_gate_hidden_precision_and_composite_cell_through_snapshot_save():
    state = _profile_state(
        gate_water="闸前 100.123\n闸后 100.098",
        gate_upstream=100.123456, gate_downstream=100.098456,
        exact=100.098456, roles=True,
    )
    saved = json.loads(json.dumps(state.to_dict(), ensure_ascii=False))
    restored = ProfileTableState.from_dict(saved)
    nodes = ProfileNodeCodec(restored).decode()

    assert restored.column_count == 44
    assert all(len(row.cells) == 44 for row in restored.rows)
    assert nodes[1].gate_upstream_water_level == 100.123456
    assert nodes[1].gate_downstream_water_level == 100.098456
    assert nodes[1].water_level == 100.098456
    assert nodes[0].gate_upstream_water_level is None


def test_codec_does_not_fill_uncomputed_gate_or_reuse_invalid_roles():
    nodes = ProfileNodeCodec(_profile_state(
        gate_water="-", gate_upstream="nan", gate_downstream="-", roles=True,
    )).decode()

    assert nodes[1].gate_upstream_water_level is None
    assert nodes[1].gate_downstream_water_level is None


def test_codec_first_gate_preserves_unknown_upstream_through_snapshot_save():
    state = _profile_state(
        gate_water="闸前 —\n闸后 100.000", gate_upstream=None,
        gate_downstream=100.0, exact=100.0, roles=True,
    )
    state.rows = [state.rows[1]]
    saved = json.loads(json.dumps(state.to_dict(), ensure_ascii=False))
    nodes = ProfileNodeCodec(ProfileTableState.from_dict(saved)).decode()

    assert nodes[0].gate_upstream_water_level is None
    assert nodes[0].gate_downstream_water_level == 100.0
    assert nodes[0].water_level == 100.0


def test_codec_ignores_gate_hidden_roles_on_nongate_row():
    state = _profile_state()
    state.rows[0].cell_data[0] = {
        GATE_UPSTREAM_WATER_LEVEL_ROLE_KEY: 123.0,
        GATE_DOWNSTREAM_WATER_LEVEL_ROLE_KEY: 122.9,
    }

    nodes = ProfileNodeCodec(state).decode()

    assert nodes[0].gate_upstream_water_level is None
    assert nodes[0].gate_downstream_water_level is None


def test_codec_explicit_zero_gate_sides_remain_valid():
    nodes = ProfileNodeCodec(_profile_state(
        gate_water="闸前 0.000\n闸后 0.000", gate_upstream=0.0,
        gate_downstream=0.0, exact=0.0, roles=True,
    )).decode()

    assert nodes[1].gate_upstream_water_level == 0.0
    assert nodes[1].gate_downstream_water_level == 0.0
    assert nodes[1].water_level == 0.0
