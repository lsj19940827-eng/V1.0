# -*- coding: utf-8 -*-
"""全部闸行渠底/渠顶参照推算与自动成果刷新回归。"""

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
from 推求水面线.models.data_models import ChannelNode, ProjectSettings
from 推求水面线.models.enums import StructureType
from 推求水面线.models.profile_node_codec import (
    GATE_DOWNSTREAM_WATER_LEVEL_ROLE_KEY, GATE_UPSTREAM_WATER_LEVEL_ROLE_KEY,
    GATE_ELEVATION_REFERENCE_DETAILS_ROLE_KEY, ProfileNodeCodec,
)
from 推求水面线.models.profile_state import ProfileRow, ProfileTableState


def _channel(name, x=0, *, section="1", depth=1.2, height=2.5):
    return ChannelNode(
        name=name, structure_type=StructureType.MINGQU_RECTANGULAR,
        flow_section=section, flow=2.0, x=float(x),
        section_params={"B": 2.0, "h": depth, "m": 0.0},
        water_depth=depth, structure_height=height, slope_i=0.001,
    )


def _gate(name, x=100, *, section="1", level=99.9):
    return ChannelNode(
        name=name, structure_type=StructureType.CHECK_GATE,
        flow_section=section, flow=2.0, x=float(x), is_diversion_gate=True,
        water_level=level, head_loss_gate=0.1,
        gate_upstream_water_level=level + 0.1,
        gate_downstream_water_level=level,
    )


def test_calculate_all_middle_gate_has_reference_bottom_and_top():
    nodes = [_channel("上游", 0), _gate("中间闸", 100), _channel("下游", 200)]
    result = WaterProfileCalculator(ProjectSettings(start_water_level=100.0, design_flow=2.0)).calculate_all(nodes)
    gate = result[1]

    assert gate.water_level == pytest.approx(99.8)
    assert gate.bottom_elevation == pytest.approx(98.7)
    assert gate.top_elevation == pytest.approx(101.2)
    details = gate.terminal_gate_backfill_details
    assert details["filled_fields"] == ["bottom_elevation", "top_elevation"]
    assert details["donor_name"] == "上游"
    assert details["donor_direction"] == "上游"
    assert details["reference_source"] == "同流量段上游明渠-矩形参考断面"
    assert details["donor_water_depth"] == 1.2
    assert details["donor_structure_height"] == 2.5
    assert gate.water_depth == 0.0
    assert gate.structure_height == 0.0


def test_calculate_all_repeated_after_gate_loss_change_keeps_geometric_elevations():
    calculator = WaterProfileCalculator(ProjectSettings(start_water_level=100.0, design_flow=2.0))
    result = calculator.calculate_all([_channel("上游", 0), _gate("中间闸", 100), _channel("下游", 200)])
    gate = result[1]
    gate.head_loss_gate = 0.025
    gate.section_params["gate_head_loss_user_set"] = True

    result = calculator.calculate_all(result)

    assert gate is result[1]
    assert gate.water_level == pytest.approx(99.875)
    # 闸损变动改变闸后水位，不能改变既定参考床面。
    assert gate.bottom_elevation == pytest.approx(98.7)
    assert gate.top_elevation == pytest.approx(101.2)
    assert gate.terminal_gate_backfill_details["target_water_level"] == 99.875


def test_calculate_all_first_gate_uses_downstream_donor_and_keeps_upstream_unknown():
    result = WaterProfileCalculator(ProjectSettings(start_water_level=100.0, design_flow=2.0)).calculate_all(
        [_gate("起点闸", 0), _channel("下游参考", 100)],
    )
    gate = result[0]

    assert gate.gate_upstream_water_level is None
    assert gate.gate_downstream_water_level == 100.0
    assert gate.bottom_elevation == pytest.approx(98.8)
    assert gate.top_elevation == pytest.approx(101.3)
    assert gate.terminal_gate_backfill_details["donor_direction"] == "下游"
    assert gate.terminal_gate_backfill_details["donor_row"] == 2


def test_all_gates_prefers_upstream_valid_donor_over_nearer_downstream():
    upstream = _channel("上游有效", 0, depth=1.6, height=2.4)
    upstream_empty = _channel("上游无高度", 90, depth=1.1, height=0.0)
    gate = _gate("中间闸", 100, level=99.9)
    downstream = _channel("下游更近", 110, depth=2.0, height=3.0)

    HydraulicCalculator(ProjectSettings()).apply_gate_elevation_backfill([upstream, upstream_empty, gate, downstream])

    assert gate.bottom_elevation == pytest.approx(98.4)
    assert gate.top_elevation == pytest.approx(100.8)
    assert gate.terminal_gate_backfill_details["donor_name"] == "上游有效"


def test_all_gates_falls_back_to_downstream_when_upstream_has_no_valid_donor():
    gate = _gate("中间闸", 100)
    upstream = _channel("上游无高度", 0, height=0.0)
    downstream = _channel("下游参考", 200)

    HydraulicCalculator(ProjectSettings()).apply_gate_elevation_backfill([upstream, gate, downstream])

    assert gate.bottom_elevation == pytest.approx(98.7)
    assert gate.top_elevation == pytest.approx(101.2)
    assert gate.terminal_gate_backfill_details["donor_name"] == "下游参考"


def test_all_gates_does_not_borrow_across_flow_section():
    gate = _gate("独立流量段闸", 100, section="2")
    reference = _channel("其他流量段", 0, section="1")

    details = HydraulicCalculator(ProjectSettings()).apply_gate_elevation_backfill([reference, gate])

    assert gate.bottom_elevation == 0.0
    assert gate.top_elevation == 0.0
    assert details[0]["status"] == "failed"
    assert "同流量段" in details[0]["failure_reason"]


def test_all_gates_no_reference_keeps_missing_and_does_not_invent_parameters():
    gate = _gate("只有闸", 0)

    HydraulicCalculator(ProjectSettings()).apply_gate_elevation_backfill([gate])

    assert gate.bottom_elevation == 0.0
    assert gate.top_elevation == 0.0
    assert gate.water_depth == 0.0
    assert gate.structure_height == 0.0
    assert gate.terminal_gate_backfill_details["status"] == "failed"


def test_no_reference_clears_nonfinite_elevations_and_preserves_finite_precision():
    first = _gate("非有限一", 0)
    first.bottom_elevation = float("nan")
    first.top_elevation = float("inf")
    second = _gate("非有限二", 100)
    second.bottom_elevation = float("-inf")
    second.top_elevation = float("nan")
    valid = _gate("已有有效高程", 200)
    valid.bottom_elevation = 98.123456789
    valid.top_elevation = 101.987654321

    HydraulicCalculator(ProjectSettings()).apply_gate_elevation_backfill([first, second, valid])

    for node in (first, second):
        assert node.bottom_elevation == 0.0
        assert node.top_elevation == 0.0
        assert node.terminal_gate_backfill_details["status"] == "failed"
        assert node.terminal_gate_backfill_details["filled_fields"] == []
    assert valid.bottom_elevation == 98.123456789
    assert valid.top_elevation == 101.987654321


@pytest.mark.parametrize("manual_field,manual_value,expected_bottom,expected_top", [
    ("bottom_elevation", 97.0, 97.0, 99.5),
    ("top_elevation", 104.0, 98.7, 104.0),
])
def test_auto_refresh_preserves_field_changed_manually(manual_field, manual_value, expected_bottom, expected_top):
    hyd = HydraulicCalculator(ProjectSettings())
    gate = _gate("参照闸", 100)
    nodes = [_channel("上游参考", 0), gate]
    hyd.apply_gate_elevation_backfill(nodes)
    setattr(gate, manual_field, manual_value)
    gate.water_level = 99.8
    gate.gate_upstream_water_level = 99.9
    gate.gate_downstream_water_level = 99.8

    hyd.apply_gate_elevation_backfill(nodes)

    assert gate.bottom_elevation == pytest.approx(expected_bottom)
    assert gate.top_elevation == pytest.approx(expected_top)
    assert manual_field not in gate.terminal_gate_backfill_details["filled_fields"]


def test_all_gates_preserves_existing_valid_bottom_and_top_without_backfill():
    gate = _gate("已有高程", 100)
    gate.bottom_elevation = 97.0
    gate.top_elevation = 104.0

    results = HydraulicCalculator(ProjectSettings()).apply_gate_elevation_backfill([_channel("参考", 0), gate])

    assert results == []
    assert gate.bottom_elevation == 97.0
    assert gate.top_elevation == 104.0


def test_saved_auto_details_still_refresh_after_project_round_trip():
    hyd = HydraulicCalculator(ProjectSettings())
    nodes = [_channel("参考", 0), _gate("保存后闸", 100)]
    hyd.apply_gate_elevation_backfill(nodes)
    restored = [ChannelNode.from_project_dict(node.to_project_dict()) for node in nodes]
    restored[1].water_level = 99.7
    restored[1].gate_upstream_water_level = 99.8
    restored[1].gate_downstream_water_level = 99.7

    hyd.apply_gate_elevation_backfill(restored)

    assert restored[1].bottom_elevation == pytest.approx(98.6)
    assert restored[1].top_elevation == pytest.approx(101.1)


def test_table_snapshot_decode_and_recalculate_keeps_auto_reference_tracking():
    settings = ProjectSettings(start_water_level=100.0, design_flow=2.0)
    original = WaterProfileCalculator(settings).calculate_all([
        _channel("上游", 0), _gate("中间闸", 100), _channel("下游", 200),
    ])
    rows = []
    for index, node in enumerate(original):
        cells = [""] * 44
        cells[0:3] = [node.flow_section, node.name, node.structure_type.value]
        cells[5:8] = [str(node.x), str(node.y), str(node.turn_radius)]
        cells[20:27] = ["2", "", "", "0", "0.014", "1000", "2"]
        cells[27] = "1.2" if index != 1 else "-"
        cells[37] = str(node.head_loss_gate) if index == 1 else "-"
        cells[41:44] = [str(node.water_level), str(node.bottom_elevation), str(node.top_elevation)]
        payload = {}
        if index == 1:
            cells[41] = "闸前 99.900\n闸后 99.800"
            payload = {
                GATE_UPSTREAM_WATER_LEVEL_ROLE_KEY: node.gate_upstream_water_level,
                GATE_DOWNSTREAM_WATER_LEVEL_ROLE_KEY: node.gate_downstream_water_level,
                GATE_ELEVATION_REFERENCE_DETAILS_ROLE_KEY: node.terminal_gate_backfill_details,
                "_numeric_display_values": {"41": {"text": cells[41], "value": node.water_level}},
            }
            payload[GATE_ELEVATION_REFERENCE_DETAILS_ROLE_KEY]["reference_source"] = "同流量段上游明渠"
        parameters = {"structure_heights": node.structure_height} if index != 1 else {}
        rows.append(ProfileRow(str(index), cells, {0: payload}, parameters))

    state = ProfileTableState.from_dict(ProfileTableState(rows=rows, column_count=44).to_dict())
    decoded = ProfileNodeCodec(state).decode()
    gate = decoded[1]
    assert gate.terminal_gate_backfill_details["reference_source"] == "同流量段上游明渠"
    assert gate.terminal_gate_backfill_details["filled_fields"] == ["bottom_elevation", "top_elevation"]
    # 解码取得独立副本，后续回推更新不修改保存快照。
    assert gate.terminal_gate_backfill_details is not state.rows[1].cell_data[0][GATE_ELEVATION_REFERENCE_DETAILS_ROLE_KEY]
    gate.head_loss_gate = 0.025
    gate.section_params["gate_head_loss_user_set"] = True
    settings.start_water_level = 101.0

    WaterProfileCalculator(settings).calculate_all(decoded)

    assert gate.water_level == pytest.approx(100.875)
    assert gate.bottom_elevation == pytest.approx(99.7)
    assert gate.top_elevation == pytest.approx(102.2)
    assert gate.terminal_gate_backfill_details["reference_source"] == "同流量段上游明渠-矩形参考断面"
    assert state.rows[1].cell_data[0][GATE_ELEVATION_REFERENCE_DETAILS_ROLE_KEY]["top"]["result"] == 101.2


def test_invalidated_reference_removes_previous_auto_results_instead_of_leaving_stale_elevations():
    hyd = HydraulicCalculator(ProjectSettings())
    reference = _channel("参考", 0)
    gate = _gate("失去参考闸", 100)
    hyd.apply_gate_elevation_backfill([reference, gate])
    reference.structure_height = 0.0

    hyd.apply_gate_elevation_backfill([reference, gate])

    assert gate.bottom_elevation == 0.0
    assert gate.top_elevation == 0.0
    assert gate.terminal_gate_backfill_details["status"] == "failed"


def test_multiple_gates_and_terminal_gate_are_all_filled():
    hyd = HydraulicCalculator(ProjectSettings())
    first = _gate("中间一", 100, level=99.9)
    second = _gate("中间二", 150, level=99.8)
    terminal = _gate("末尾", 200, level=99.7)

    results = hyd.apply_gate_elevation_backfill([_channel("参考", 0), first, second, terminal])

    assert len(results) == 3
    # 这里没有已定床面，按各闸明确的闸前边界与参考设计水深回退。
    assert [n.bottom_elevation for n in (first, second, terminal)] == pytest.approx([98.8, 98.7, 98.6])
    assert [n.top_elevation for n in (first, second, terminal)] == pytest.approx([101.3, 101.2, 101.1])
