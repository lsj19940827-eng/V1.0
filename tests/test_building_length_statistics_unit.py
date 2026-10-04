"""建筑物长度的边界、分类及明细/汇总一致性验证。"""

import copy
import math

import pytest

from 推求水面线.core.calculator import WaterProfileCalculator
from 推求水面线.models.data_models import ChannelNode, ProjectSettings
from 推求水面线.models.enums import InOutType, StructureType


def _node(name, kind, station, role='', *, automatic=False, length=0.0):
    node = ChannelNode(name=name, structure_type=StructureType.from_string(kind),
                       flow_section='1', station_MC=station)
    node.in_out = {'进': InOutType.INLET, '出': InOutType.OUTLET}.get(role, InOutType.NORMAL)
    node.is_transition = kind == '渐变段'
    node.is_auto_inserted_channel = automatic
    node.stat_length = length
    if node.is_transition:
        node.transition_length = length
        node.transition_type = '进口' if role == '进' else '出口'
    return node


def _connection_case():
    return [
        _node('上游隧洞', '隧洞-圆拱直墙型', 0, '进'),
        _node('上游隧洞', '隧洞-圆拱直墙型', 100, '出'),
        _node('-', '渐变段', 100, '出', length=5),
        _node('-', '明渠-矩形', 125, automatic=True, length=20),
        _node('-', '渐变段', 125, '进', length=5),
        _node('下游倒虹吸', '倒虹吸', 130, '进'),
        _node('下游倒虹吸', '倒虹吸', 230, '出'),
    ]


def _summary_map(items):
    return {item['structure_type']: item for item in items}


def _assert_partition(nodes, records):
    real = [n for n in nodes if not n.is_transition and not n.is_auto_inserted_channel]
    cursor = real[0].station_MC
    for record in sorted((r for r in records if r['length'] > 0), key=lambda r: r['start_station']):
        assert record['start_station'] == pytest.approx(cursor, abs=1e-8)
        assert record['length'] == pytest.approx(record['end_station'] - record['start_station'], abs=1e-8)
        cursor = record['end_station']
    assert cursor == pytest.approx(real[-1].station_MC, abs=1e-8)
    assert math.fsum(r['length'] for r in records) == pytest.approx(real[-1].station_MC - real[0].station_MC)


def test_summary_uses_transition_lengths_and_connection_boundaries():
    calc = WaterProfileCalculator(ProjectSettings())
    nodes = _connection_case()
    original = copy.deepcopy(nodes)
    records = calc.calculate_building_lengths(nodes)
    summary = _summary_map(calc.calculate_comprehensive_type_summary(nodes))
    assert summary['渐变段']['total_length'] == pytest.approx(10)
    assert summary['明渠-矩形']['total_length'] == pytest.approx(20)
    assert summary['倒虹吸']['total_length'] == pytest.approx(100)
    assert summary['隧洞-圆拱直墙型']['total_length'] == pytest.approx(100)
    assert calc.calculate_type_summary(records) == calc.calculate_comprehensive_type_summary(nodes)
    _assert_partition(nodes, records)
    assert nodes == original


def test_unnamed_culverts_keep_their_actual_type():
    calc = WaterProfileCalculator(ProjectSettings())
    nodes = [_node('', '暗涵-矩形', 0), _node('', '暗涵-矩形', 100)]
    records = calc.calculate_building_lengths(nodes)
    assert len(records) == 1
    assert records[0]['structure_type'] == '暗涵-矩形'
    assert records[0]['length'] == 100
    assert _summary_map(calc.calculate_comprehensive_type_summary(nodes))['暗涵-矩形']['total_length'] == 100


def test_adjacent_different_buildings_of_same_type_are_counted_separately():
    calc = WaterProfileCalculator(ProjectSettings())
    nodes = [
        _node('甲隧洞', '隧洞-圆形', 0, '进'), _node('甲隧洞', '隧洞-圆形', 50, '出'),
        _node('乙隧洞', '隧洞-圆形', 50, '进'), _node('乙隧洞', '隧洞-圆形', 100, '出'),
    ]
    summary = _summary_map(calc.calculate_comprehensive_type_summary(nodes))
    assert summary['隧洞-圆形']['count'] == 2
    assert summary['隧洞-圆形']['total_length'] == 100


def test_multiple_point_gates_do_not_split_one_named_building():
    calc = WaterProfileCalculator(ProjectSettings())
    nodes = [
        _node('甲隧洞', '隧洞-圆形', 0, '进'),
        _node('一号', '分水闸', 20), _node('二号', '分水闸', 30),
        _node('甲隧洞', '隧洞-圆形', 100, '出'),
    ]
    records = calc.calculate_building_lengths(nodes)
    summary = _summary_map(calc.calculate_comprehensive_type_summary(nodes))
    assert summary['隧洞-圆形']['count'] == 1
    assert summary['隧洞-圆形']['total_length'] == 100
    assert summary['分水闸']['count'] == 2
    assert summary['分水闸']['total_length'] == 0
    _assert_partition(nodes, records)


def test_submillimetre_gaps_do_not_shift_building_endpoints():
    calc = WaterProfileCalculator(ProjectSettings())
    nodes = [
        _node('甲隧洞', '隧洞-圆形', 0, '进'), _node('甲隧洞', '隧洞-圆形', 10, '出'),
        _node('乙隧洞', '隧洞-圆形', 10.0005, '进'), _node('乙隧洞', '隧洞-圆形', 20, '出'),
    ]
    records = calc.calculate_building_lengths(nodes)
    first = next(r for r in records if r['name'] == '甲隧洞')
    assert first['end_station'] == 10
    assert first['length'] == 10
    _assert_partition(nodes, records)


def test_length_override_reallocates_remaining_connection_length():
    calc = WaterProfileCalculator(ProjectSettings())
    nodes = _connection_case()
    # 后置修改渐变段后，连接段历史 stat_length 不能掩盖当前的实际剩余长度。
    nodes[2].transition_length = 8
    nodes[2].transition_length_override_m = 8
    records = calc.calculate_building_lengths(nodes)
    summary = _summary_map(calc.calculate_comprehensive_type_summary(nodes))
    assert summary['渐变段']['total_length'] == 13
    assert summary['明渠-矩形']['total_length'] == 17
    _assert_partition(nodes, records)


def test_reversed_real_stations_are_reported_instead_of_taking_absolute_length():
    calc = WaterProfileCalculator(ProjectSettings())
    nodes = [_node('甲隧洞', '隧洞-圆形', 100, '进'), _node('甲隧洞', '隧洞-圆形', 90, '出')]
    with pytest.raises(ValueError, match='桩号'):
        calc.calculate_building_lengths(nodes)


def test_same_name_different_type_on_either_side_of_gate_is_not_merged():
    calc = WaterProfileCalculator(ProjectSettings())
    nodes = [
        _node('甲', '隧洞-圆形', 0, '进'), _node('甲', '隧洞-圆形', 50, '出'),
        _node('闸', '分水闸', 55),
        _node('甲', '渡槽-矩形', 60, '进'), _node('甲', '渡槽-矩形', 100, '出'),
    ]
    records = calc.calculate_building_lengths(nodes)
    summary = _summary_map(calc.calculate_type_summary(records))
    assert summary['隧洞-圆形']['total_length'] == 50
    assert summary['渡槽-矩形']['total_length'] == 40
    assert summary['未划分连接段']['total_length'] == 10
    _assert_partition(nodes, records)


def test_inlet_transition_is_anchored_at_the_downstream_boundary():
    calc = WaterProfileCalculator(ProjectSettings())
    nodes = [_node('', '明渠-矩形', 0), _node('-', '渐变段', 0, '进', length=5),
             _node('甲', '隧洞-圆形', 100, '进'), _node('甲', '隧洞-圆形', 200, '出')]
    records = calc.calculate_building_lengths(nodes)
    transition = next(r for r in records if r['structure_type'] == '渐变段')
    assert (transition['start_station'], transition['end_station']) == (95, 100)
    _assert_partition(nodes, records)


def test_all_point_nodes_count_individually_without_inventing_gate_length():
    calc = WaterProfileCalculator(ProjectSettings())
    nodes = [_node('甲闸', '分水闸', 0), _node('乙闸', '分水闸', 10)]
    records = calc.calculate_building_lengths(nodes)
    summary = _summary_map(calc.calculate_type_summary(records))
    assert summary['分水闸']['count'] == 2
    assert summary['分水闸']['total_length'] == 0
    assert summary['未划分连接段']['total_length'] == 10
    _assert_partition(nodes, records)


def test_invalid_transition_length_is_not_scaled_to_hide_the_conflict():
    calc = WaterProfileCalculator(ProjectSettings())
    nodes = _connection_case()
    nodes[2].transition_length = 50
    with pytest.raises(ValueError, match='超过实际桩号间距'):
        calc.calculate_building_lengths(nodes)


def test_validation_rejects_wrong_type_allocation_even_when_total_matches():
    calc = WaterProfileCalculator(ProjectSettings())
    nodes = _connection_case()
    summary = calc.calculate_comprehensive_type_summary(nodes)
    for item in summary:
        if item['structure_type'] == '渐变段':
            item['total_length'] = 30
        elif item['structure_type'] == '明渠-矩形':
            item['total_length'] = 0
    result = calc.validate_type_summary_total(nodes, summary)
    assert result['diff'] == 0
    assert not result['ok']
    assert result['errors']


def test_unnamed_building_with_explicit_boundaries_does_not_absorb_the_gap():
    calc = WaterProfileCalculator(ProjectSettings())
    nodes = [_node('', '暗涵-矩形', 0, '进'), _node('', '暗涵-矩形', 50, '出'),
             _node('', '暗涵-矩形', 60, '进'), _node('', '暗涵-矩形', 100, '出')]
    summary = _summary_map(calc.calculate_comprehensive_type_summary(nodes))
    assert summary['暗涵-矩形']['count'] == 2
    assert summary['暗涵-矩形']['total_length'] == 90
    assert summary['未划分连接段']['total_length'] == 10


def test_single_transition_is_capped_before_statistics_and_stays_capped_after_loss_calculation():
    calc = WaterProfileCalculator(ProjectSettings())
    left = _node('杨家沟', '倒虹吸', 100, '出')
    right = _node('', '暗涵-矩形', 104.437473137348)
    left.section_params = {'D': 1.5}
    right.section_params = {'B': 2.0, 'H': 2.3}
    left.water_depth = right.water_depth = 1.5
    nodes = calc.identify_and_insert_transitions([left, right])
    transition = next(n for n in nodes if n.is_transition)
    assert transition.transition_length <= right.station_MC - left.station_MC
    assert transition.transition_length_calc_details['distance_clamped']
    calc.calculate_transition_losses(nodes)
    assert transition.transition_length <= right.station_MC - left.station_MC
    _assert_partition(nodes, calc.calculate_building_lengths(nodes))
