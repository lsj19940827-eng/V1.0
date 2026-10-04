"""连接明渠自动拟定、复算、模板和单处覆盖的回归验证。"""

import copy
import json
import math
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / 'calc_渠系计算算法内核'):
    sys.path.insert(0, str(path))

from PySide6.QtWidgets import QApplication
from 推求水面线.core.calculator import WaterProfileCalculator
from 推求水面线.core.connection_channel import recalculate_open_channel, reference_to_params
from 推求水面线.models.data_models import ChannelNode, ProjectSettings
from 推求水面线.models.enums import InOutType, StructureType
from app_渠系计算前端.water_profile.water_profile_dialogs import BatchChannelConfirmDialog, OpenChannelDialog


def _case(distance=60.0):
    settings = ProjectSettings(design_flow=2.88, max_flow=3.6, design_flows=[2.88], max_flows=[3.6], roughness=0.014)
    left = ChannelNode(flow_section='1', name='参考隧洞', structure_type=StructureType.TUNNEL_ARCH,
                       x=100, y=100, station_MC=0, flow=2.88, in_out=InOutType.OUTLET,
                       roughness=0.014, slope_i=1 / 3000, water_depth=1.54, structure_height=8)
    left.section_params = {'B': 2.0, 'm': 0.0, 'H_total': 8, 'theta_deg': 180}
    right = ChannelNode(flow_section='1', name='倒虹吸', structure_type=StructureType.INVERTED_SIPHON,
                        x=100 + distance, y=100, station_MC=distance, flow=2.88, in_out=InOutType.INLET,
                        roughness=0.014, slope_i=0, water_depth=1.5)
    right.section_params = {'D': 1.5}
    return WaterProfileCalculator(settings), [left, right]


def _reference(calc, nodes):
    return calc._find_reference_segment_same_section_v2(nodes, 0, 0, 1)


def test_inferred_rectangle_balances_both_flows_and_does_not_copy_roof_height():
    calc, nodes = _case()
    before = copy.deepcopy(nodes)
    ref = _reference(calc, nodes)
    assert ref['source_kind'] == 'inferred_rectangular'
    assert ref['bottom_width'] == 2
    assert ref['roughness_source'] == '项目渠道糙率'
    assert ref['geometry_source_name'] == ref['slope_source_name'] == '参考隧洞'
    for depth_key, flow in [('water_depth', 2.88), ('water_depth_increased', 3.6)]:
        depth = ref[depth_key]
        area = 2 * depth
        radius = area / (2 + 2 * depth)
        assert area * radius ** (2 / 3) * math.sqrt(1 / 3000) / 0.014 == pytest.approx(flow, rel=2e-6)
    assert ref['water_depth'] == pytest.approx(1.54114, abs=1e-5)
    assert 1.842 < ref['water_depth_increased'] < 1.845
    assert ref['structure_height'] - ref['water_depth_increased'] == pytest.approx(0.25 * ref['water_depth_increased'] + 0.2, abs=0.001)
    assert ref['reference_froude'] < 1 and ref['froude_increased'] < 1
    assert nodes == before


def test_two_siphons_borrow_nearby_unpressurized_width_not_diameter():
    calc, nodes = _case()
    donor = nodes[0]
    donor.station_MC = -100
    left = copy.deepcopy(nodes[1])
    left.name, left.x, left.station_MC, left.in_out = '上游倒虹吸', 100, 0, InOutType.OUTLET
    left.section_params['D'] = 9
    nodes = [left, nodes[1], donor]
    ref = _reference(calc, nodes)
    assert ref['bottom_width'] == 2
    assert ref['geometry_source_name'] == donor.name


def test_no_usable_width_uses_economic_rectangle_but_no_slope_stays_manual():
    calc, nodes = _case()
    nodes[0].structure_type = StructureType.TUNNEL_CIRCULAR
    nodes[0].section_params = {'D': 6}
    ref = _reference(calc, nodes)
    assert ref['source_kind'] == 'economic_rectangular'
    assert ref['bottom_width'] == 2.47
    nodes[0].slope_i = 0
    assert _reference(calc, nodes) is None
    nodes[0].slope_i = float('nan')
    assert _reference(calc, nodes) is None


def test_cross_section_inference_recalculates_for_target_flow():
    calc, nodes = _case()
    donor = copy.deepcopy(nodes[0])
    donor.flow_section, donor.flow = '2', 20
    nodes[0].structure_type = StructureType.INVERTED_SIPHON
    nodes[0].section_params = {'D': 9}
    nodes[0].slope_i = 0
    nodes.append(donor)
    assert _reference(calc, nodes) is None
    ref = calc._find_reference_segment_cross_section_v2(nodes, 0, 0, 1)
    assert ref['reference_source_flow_section'] == '2'
    assert ref['flow'] == 2.88 and ref['max_flow'] == 3.6
    assert ref['water_depth'] == pytest.approx(1.54114, abs=1e-5)


def test_saved_template_and_override_roundtrip_recompute_and_preserve_priority():
    calc, nodes = _case()
    ref = _reference(calc, nodes)
    calc.settings.connection_channel_templates['1'] = dict(ref, bottom_width=2.4)
    key = calc.connection_gap_key(*nodes)
    calc.settings.connection_channel_overrides[key] = dict(ref, bottom_width=3.0)
    settings = ProjectSettings.from_dict(json.loads(json.dumps(calc.settings.to_dict())))
    settings.design_flows, settings.max_flows = [4.0], [5.0]
    for node in nodes:
        node.flow = 4.0
    restored = WaterProfileCalculator(settings)
    assert restored.connection_gap_key(*nodes) == key
    current = _reference(restored, nodes)
    assert current['source_kind'] == 'user_override'
    assert current['bottom_width'] == 3
    assert current['water_depth'] != ref['water_depth']
    assert current['flow'] == 4 and current['max_flow'] == 5
    del settings.connection_channel_overrides[key]
    assert _reference(restored, nodes)['bottom_width'] == 2.4
    nodes[0].structure_type = StructureType.RECT_CULVERT
    assert _reference(restored, nodes)['section_family'] == 'culvert'


def test_invalid_saved_section_returns_editable_inputs_without_stale_depth():
    calc, nodes = _case()
    ref = _reference(calc, nodes)
    calc.settings.connection_channel_templates['1'] = dict(ref, slope_inv=0)
    invalid = _reference(calc, nodes)
    assert invalid['source_kind'] == 'user_template'
    assert invalid['water_depth'] == 0
    assert invalid['recalculation_error']
    with pytest.raises(ValueError):
        calc._build_open_channel_params_from_reference(invalid, '1', 2.88)
    repaired = recalculate_open_channel(dict(invalid, slope_inv=3000), 2.88, '1', 3.6)
    assert repaired['water_depth'] > 0
    assert 'recalculation_error' not in repaired


def test_cross_section_adjacent_culvert_keeps_source_and_uses_target_flow():
    calc, nodes = _case()
    nodes[0].structure_type = StructureType.INVERTED_SIPHON
    nodes[1].structure_type = StructureType.RECT_CULVERT
    nodes[1].flow_section, nodes[1].flow, nodes[1].structure_height = '2', 1.0, 3.0
    nodes[1].section_params = {'B': 2.0, 'H_total': 3.0}
    nodes[1].slope_i = 1 / 3000
    ref = calc._find_reference_segment_cross_section_v2(nodes, 0, 0, 1)
    assert ref['reference_source_flow_section'] == '2'
    assert ref['flow_section'] == '1' and ref['flow'] == 2.88
    assert 1.54 < ref['water_depth'] < 1.55
    nodes[1].structure_height = 0.5
    invalid = calc._find_reference_segment_cross_section_v2(nodes, 0, 0, 1)
    assert invalid['recalculation_error'] and invalid['water_depth'] == 0


@pytest.mark.parametrize('distance', [8.0, 60.0])
def test_prescan_and_actual_lengths_close_without_changing_source_nodes(distance):
    calc, nodes = _case(distance)
    gaps = calc.pre_scan_open_channels(nodes)
    inserted = calc.identify_and_insert_transitions(nodes)
    additions = [node for node in inserted if node.is_transition or node.is_auto_inserted_channel]
    assert sum(node.transition_length if node.is_transition else node.stat_length for node in additions) == pytest.approx(distance)
    channels = [node for node in additions if node.is_auto_inserted_channel]
    assert len(channels) == len(gaps)
    if channels:
        assert channels[0].stat_length == pytest.approx(gaps[0]['available_length'])
        assert channels[0].connection_source_details['gap_key'] == gaps[0]['gap_key']
    else:
        assert len(additions) == 1


def test_manual_width_change_reflows_length_and_can_merge_short_gap():
    calc, nodes = _case(30)
    gaps = calc.pre_scan_open_channels(nodes)
    assert gaps
    def choose(reference, *args):
        return reference_to_params(recalculate_open_channel(dict(reference, bottom_width=0.2), 2.88, '1', 3.6))
    inserted = calc.identify_and_insert_transitions(nodes, choose)
    assert not any(node.is_auto_inserted_channel for node in inserted)
    transitions = [node for node in inserted if node.is_transition]
    assert len(transitions) == 1 and transitions[0].transition_length == 30


@pytest.mark.parametrize('structure', ['明渠-矩形', '明渠-U形'])
def test_existing_automatic_channel_only_becomes_override_after_input_edit(structure):
    calc, nodes = _case()
    if structure == '明渠-U形':
        calc.settings.connection_channel_templates['1'] = dict(
            _reference(calc, nodes), structure_type=structure, bottom_width=0, arc_radius=1.7,
            side_slope=0.5, theta_deg=152,
        )
    inserted = calc.identify_and_insert_transitions(nodes)
    channel = next(node for node in inserted if node.is_auto_inserted_channel)
    calc.remember_connection_edits(inserted)
    assert not calc.settings.connection_channel_overrides
    channel.section_params['R_circle' if structure == '明渠-U形' else 'B'] = 2.7
    calc.remember_connection_edits(inserted)
    ref = _reference(calc, nodes)
    assert ref['arc_radius' if structure == '明渠-U形' else 'bottom_width'] == 2.7
    assert ref['source_kind'] == 'user_override'


def test_both_dialogs_prefill_without_marking_recommendation_as_manual():
    app = QApplication.instance() or QApplication([])
    calc, nodes = _case()
    gap = calc.pre_scan_open_channels(nodes)[0]
    batch = BatchChannelConfirmDialog(None, 1, [copy.deepcopy(gap)])
    single = OpenChannelDialog(None, upstream_channel=gap['reference_segment'], flow=2.88, flow_section='1')
    try:
        batch._on_ok()
        single._on_ok()
        for params in [batch.get_result()['params'][0], single.get_result()]:
            assert params.structure_type == '明渠-矩形'
            assert params.bottom_width == 2
            assert params.structure_height == pytest.approx(2.504)
            assert not params.reference_details.get('user_modified')
        assert '底宽取' in batch.param_table.item(0, 11).toolTip()
        single.rb_manual.setChecked(True)
        single.edit_B.setText('2.345')
        single.save_template_cb.setChecked(True)
        single._on_apply_all()
        assert single.get_result().bottom_width == 2.345
        assert single.get_result().reference_details['user_modified']
    finally:
        batch.deleteLater()
        single.deleteLater()
        app.processEvents()


def test_dialog_flow_display_rounding_preserves_calculation_and_manual_edits():
    """两种补段窗口预填两位流量，确认、推荐回填和人工编辑均不误截断。"""
    app = QApplication.instance() or QApplication([])
    calc, nodes = _case()
    raw_flow = 2.87654321
    for node in nodes:
        node.flow = raw_flow
    calc.settings.design_flow = raw_flow
    calc.settings.design_flows = [raw_flow]
    gap = calc.pre_scan_open_channels(nodes)[0]
    batch = BatchChannelConfirmDialog(None, 1, [copy.deepcopy(gap)])
    single = OpenChannelDialog(None, upstream_channel=gap['reference_segment'], flow=raw_flow, flow_section='1')
    try:
        assert batch.param_table.item(0, 10).text() == '2.88'
        assert single.edit_Q.text() == '2.88'
        batch._on_ok()
        single._on_ok()
        assert batch.get_result()['params'][0].flow == raw_flow
        assert single.get_result().flow == raw_flow
        assert not batch.get_result()['params'][0].reference_details.get('user_modified')
        batch.param_table.item(0, 10).setText('3.0123')
        single.rb_manual.setChecked(True)
        single.edit_Q.setText('3.0123')
        batch._on_ok()
        single._on_ok()
        assert batch.get_result()['params'][0].flow == 3.0123
        assert single.get_result().flow == 3.0123
        batch._fill_recommended(0)
        assert batch.param_table.item(0, 10).text() == '2.88'
        assert batch._get_cell_val(0, 10) == raw_flow
    finally:
        batch.deleteLater()
        single.deleteLater()
        app.processEvents()


def test_template_apply_keeps_single_edits_culverts_other_sections_and_undo():
    app = QApplication.instance() or QApplication([])
    calc, nodes = _case()
    base = calc.pre_scan_open_channels(nodes)[0]
    gaps = [copy.deepcopy(base) for _ in range(5)]
    for idx, gap in enumerate(gaps):
        gap['gap_key'] = str(idx)
    gaps[3]['reference_segment'].update(structure_type='暗涵-矩形', structure_height=3)
    gaps[4]['flow_section'] = '2'
    dialog = BatchChannelConfirmDialog(None, 5, gaps)
    try:
        dialog._set_cell(2, 5, '2.7')
        dialog.param_table.setCurrentCell(0, 5)
        dialog._set_cell(0, 5, '2.345')
        before = dialog._snapshot_param_table()
        dialog._apply_section_template()
        assert [float(dialog.param_table.item(i, 5).text()) for i in range(5)] == [2.345, 2.345, 2.7, 2, 2]
        assert dialog._template_updates['1']['bottom_width'] == 2.345
        assert gaps[1]['reference_segment']['source_kind'] == 'user_template'
        dialog._undo_param_table()
        assert dialog._snapshot_param_table() == before
        dialog._redo_param_table()
        dialog._on_ok()
        result = dialog.get_result()
        assert result['templates']['1']['bottom_width'] == 2.345
        assert result['params'][1].bottom_width == 2.345
        assert result['params'][2].reference_details['user_modified']
        assert not result['params'][1].reference_details.get('user_modified')
    finally:
        dialog.deleteLater()
        app.processEvents()
