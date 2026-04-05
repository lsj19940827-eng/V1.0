# -*- coding: utf-8 -*-
"""插入渐变段后桩号稳定性的回归测试。"""

import importlib.util
import os
import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))

from core.calculator import WaterProfileCalculator
from core.geometry_calc import GeometryCalculator
from models.data_models import ChannelNode, OpenChannelParams, ProjectSettings
from models.enums import StructureType

ROOT = Path(__file__).resolve().parents[1]


def _make_profile_node(name, structure_type, x, station_mc, section_params, water_depth):
    node = ChannelNode()
    node.name = name
    node.structure_type = StructureType.from_string(structure_type)
    node.x = float(x)
    node.y = 0.0
    node.station_MC = float(station_mc)
    node.flow_section = "1"
    node.flow = 1.0
    node.roughness = 0.014
    node.slope_i = 1.0 / 3000.0
    node.section_params = dict(section_params)
    node.water_depth = float(water_depth)
    return node


def _assert_station_tuple(node, expected):
    station_ip, station_bc, station_mc, station_ec = expected
    assert node.station_ip == pytest.approx(station_ip)
    assert node.station_BC == pytest.approx(station_bc)
    assert node.station_MC == pytest.approx(station_mc)
    assert node.station_EC == pytest.approx(station_ec)


def _get_qapp():
    """获取测试用 Qt 应用实例。"""
    return QApplication.instance() or QApplication([])


def _load_panel_module():
    """按文件路径加载水面线面板模块。"""
    panel_path = (ROOT / "app_渠系计算前端" / "water_profile" / "panel.py").resolve()
    spec = importlib.util.spec_from_file_location("wp_geometry_station_panel", panel_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_panel(module):
    """创建测试用面板并屏蔽提示弹窗。"""
    _get_qapp()
    for attr in ("success", "warning", "error", "info"):
        setattr(module.InfoBar, attr, staticmethod(lambda *args, **kwargs: None))
    panel = module.WaterProfilePanel()
    panel._choose_roughness_value = lambda values, _label: values[0] if values else None
    return panel


def test_calculate_stations_keeps_real_nodes_stable_with_transition_and_auto_channel():
    geo_calc = GeometryCalculator(ProjectSettings())

    baseline_start = ChannelNode()
    baseline_end = ChannelNode()
    baseline_end.straight_distance = 100.0

    geo_calc.calculate_stations([baseline_start, baseline_end], 0.0)
    baseline = (
        baseline_end.station_ip,
        baseline_end.station_BC,
        baseline_end.station_MC,
        baseline_end.station_EC,
    )

    start = ChannelNode()

    transition_out = ChannelNode()
    transition_out.is_transition = True

    auto_channel = ChannelNode()
    auto_channel.is_auto_inserted_channel = True
    auto_channel.straight_distance = 50.0

    transition_in = ChannelNode()
    transition_in.is_transition = True

    end = ChannelNode()
    end.straight_distance = 100.0

    geo_calc.calculate_stations(
        [start, transition_out, auto_channel, transition_in, end],
        0.0,
    )

    assert auto_channel.station_MC == pytest.approx(50.0)
    assert auto_channel.station_BC == pytest.approx(50.0)
    assert auto_channel.station_EC == pytest.approx(50.0)
    _assert_station_tuple(end, baseline)


def test_prepare_transitions_and_recalculate_geometry_preserve_real_node_stations():
    calculator = WaterProfileCalculator(ProjectSettings())

    pipe_inlet = _make_profile_node(
        "管道A",
        "有压管道",
        0.0,
        0.0,
        {"D": 1.5},
        2.0,
    )
    pipe_outlet = _make_profile_node(
        "管道A",
        "有压管道",
        50.0,
        50.0,
        {"D": 1.5},
        2.0,
    )
    tunnel_inlet = _make_profile_node(
        "隧洞B",
        "隧洞-圆形",
        150.0,
        150.0,
        {"D": 2.0},
        2.0,
    )
    tunnel_outlet = _make_profile_node(
        "隧洞B",
        "隧洞-圆形",
        200.0,
        200.0,
        {"D": 2.0},
        2.0,
    )
    original_nodes = [pipe_inlet, pipe_outlet, tunnel_inlet, tunnel_outlet]

    calculator.preprocess_nodes(original_nodes)
    calculator.calculate_geometry(original_nodes)
    baseline_by_id = {
        id(node): (node.station_ip, node.station_BC, node.station_MC, node.station_EC)
        for node in original_nodes
    }

    def open_channel_callback(_upstream, _available_length, _prev_struct, _next_struct, flow_section, flow):
        return OpenChannelParams(
            name="-",
            structure_type="明渠-矩形",
            bottom_width=2.0,
            water_depth=1.5,
            side_slope=0.0,
            roughness=0.014,
            slope_inv=3000.0,
            flow=flow,
            flow_section=flow_section,
            structure_height=2.0,
        )

    prepared_nodes = calculator.prepare_transitions(original_nodes, open_channel_callback)

    auto_channels = [node for node in prepared_nodes if node.is_auto_inserted_channel]
    transition_rows = [node for node in prepared_nodes if node.is_transition]
    assert len(auto_channels) == 1
    assert len(transition_rows) == 2
    assert auto_channels[0].station_MC == pytest.approx(100.0)

    for node in original_nodes:
        _assert_station_tuple(node, baseline_by_id[id(node)])

    calculator.calculate_geometry(prepared_nodes)

    assert auto_channels[0].station_MC == pytest.approx(100.0)
    for node in original_nodes:
        _assert_station_tuple(node, baseline_by_id[id(node)])


def test_prepare_transitions_prefers_project_start_station_over_stale_first_row_station():
    settings = ProjectSettings()
    settings.start_station = 10097.309
    calculator = WaterProfileCalculator(settings)

    pipe_inlet = _make_profile_node(
        "管道A",
        "有压管道",
        0.0,
        0.0,
        {"D": 1.5},
        2.0,
    )
    pipe_outlet = _make_profile_node(
        "管道A",
        "有压管道",
        50.0,
        0.0,
        {"D": 1.5},
        2.0,
    )
    tunnel_inlet = _make_profile_node(
        "隧洞B",
        "隧洞-圆形",
        150.0,
        0.0,
        {"D": 2.0},
        2.0,
    )
    tunnel_outlet = _make_profile_node(
        "隧洞B",
        "隧洞-圆形",
        200.0,
        0.0,
        {"D": 2.0},
        2.0,
    )
    original_nodes = [pipe_inlet, pipe_outlet, tunnel_inlet, tunnel_outlet]

    calculator.preprocess_nodes(original_nodes)
    calculator.calculate_geometry(original_nodes)
    baseline_by_id = {
        id(node): (node.station_ip, node.station_BC, node.station_MC, node.station_EC)
        for node in original_nodes
    }

    # 模拟项目加载旧快照后，表3首行桩号文本仍停留在 0 起点。
    original_nodes[0].station_ip = 0.0
    original_nodes[0].station_BC = 0.0
    original_nodes[0].station_MC = 0.0
    original_nodes[0].station_EC = 0.0

    def open_channel_callback(_upstream, _available_length, _prev_struct, _next_struct, flow_section, flow):
        return OpenChannelParams(
            name="-",
            structure_type="明渠-矩形",
            bottom_width=2.0,
            water_depth=1.5,
            side_slope=0.0,
            roughness=0.014,
            slope_inv=3000.0,
            flow=flow,
            flow_section=flow_section,
            structure_height=2.0,
        )

    prepared_nodes = calculator.prepare_transitions(original_nodes, open_channel_callback)

    auto_channels = [node for node in prepared_nodes if node.is_auto_inserted_channel]
    assert len(auto_channels) == 1
    assert prepared_nodes[0].station_MC == pytest.approx(settings.start_station)
    assert auto_channels[0].station_MC == pytest.approx(settings.start_station + 100.0)

    for node in original_nodes:
        _assert_station_tuple(node, baseline_by_id[id(node)])


def test_sample5_jinhuazhai_station_stays_stable_after_table_roundtrip_and_calculation():
    """示例五里金花寨进口桩号在插段后往返表格再计算时应保持稳定。"""
    module = _load_panel_module()
    panel = _build_panel(module)
    try:
        app = _get_qapp()
        panel._load_section_sample_5()
        app.processEvents()
        panel._run_section_batch_calculate()
        for _ in range(20):
            app.processEvents()

        settings = panel._build_settings()
        calculator = WaterProfileCalculator(settings)
        original_nodes = panel._build_nodes_from_table()
        calculator.preprocess_nodes(original_nodes)

        def open_channel_callback(reference, _available_length, _prev_struct, _next_struct, flow_section, flow):
            if not reference:
                return None
            return calculator._build_open_channel_params_from_reference(reference, flow_section, flow)

        prepared_nodes = calculator.prepare_transitions(original_nodes, open_channel_callback)
        jinhuazhai_index = next(
            idx for idx, node in enumerate(prepared_nodes)
            if str(node.name or "").strip() == "金花寨" and node.get_in_out_str() == "进"
        )
        baseline_station = prepared_nodes[jinhuazhai_index].station_MC
        assert baseline_station == pytest.approx(26242.3995, abs=1e-3)

        panel._update_table_from_nodes_full(prepared_nodes, settings.get_station_prefix())
        rebuilt_nodes = panel._build_nodes_from_table()
        rebuilt_auto_channel = next(node for node in rebuilt_nodes if getattr(node, "is_auto_inserted_channel", False))
        assert rebuilt_auto_channel.structure_type == StructureType.RECT_CULVERT

        recalculated = WaterProfileCalculator(settings).calculate_all(rebuilt_nodes)
        recalculated_station = recalculated[jinhuazhai_index].station_MC

        assert recalculated_station == pytest.approx(baseline_station, abs=1e-3)
    finally:
        panel.deleteLater()


def test_rect_culvert_to_tunnel_skips_zero_length_outlet_transition():
    """矩形暗涵接隧洞时，若出口侧长度为 0，不应再插空的渐变段。"""
    calculator = WaterProfileCalculator(ProjectSettings())

    culvert_inlet = _make_profile_node(
        "暗涵A",
        "矩形暗涵",
        0.0,
        0.0,
        {"B": 2.0},
        1.0,
    )
    culvert_outlet = _make_profile_node(
        "暗涵A",
        "矩形暗涵",
        60.0,
        60.0,
        {"B": 2.0},
        1.0,
    )
    tunnel_inlet = _make_profile_node(
        "金花寨",
        "隧洞-圆形",
        80.0,
        80.0,
        {"D": 2.0},
        1.0,
    )
    tunnel_outlet = _make_profile_node(
        "金花寨",
        "隧洞-圆形",
        140.0,
        140.0,
        {"D": 2.0},
        1.0,
    )
    original_nodes = [culvert_inlet, culvert_outlet, tunnel_inlet, tunnel_outlet]

    calculator.preprocess_nodes(original_nodes)

    def open_channel_callback(reference, _available_length, _prev_struct, _next_struct, flow_section, flow):
        if not reference:
            return None
        return calculator._build_open_channel_params_from_reference(reference, flow_section, flow)

    prepared_nodes = calculator.prepare_transitions(original_nodes, open_channel_callback)

    transition_rows = [node for node in prepared_nodes if getattr(node, "is_transition", False)]
    auto_channel_rows = [node for node in prepared_nodes if getattr(node, "is_auto_inserted_channel", False)]

    assert len(auto_channel_rows) == 1
    assert len(transition_rows) == 1
    assert transition_rows[0].transition_type == "进口"
    assert transition_rows[0].transition_length == pytest.approx(6.0)


def test_sample5_legacy_auto_channel_payload_still_keeps_jinhuazhai_station_stable():
    """旧项目缺少新辅助字段时，茶亭支渠这段桩号仍应保持稳定。"""
    module = _load_panel_module()
    panel = _build_panel(module)
    try:
        app = _get_qapp()
        panel._load_section_sample_5()
        app.processEvents()
        panel._run_section_batch_calculate()
        for _ in range(20):
            app.processEvents()

        settings = panel._build_settings()
        calculator = WaterProfileCalculator(settings)
        original_nodes = panel._build_nodes_from_table()
        calculator.preprocess_nodes(original_nodes)

        def open_channel_callback(reference, _available_length, _prev_struct, _next_struct, flow_section, flow):
            if not reference:
                return None
            return calculator._build_open_channel_params_from_reference(reference, flow_section, flow)

        prepared_nodes = calculator.prepare_transitions(original_nodes, open_channel_callback)
        jinhuazhai_index = next(
            idx for idx, node in enumerate(prepared_nodes)
            if str(node.name or "").strip() == "金花寨" and node.get_in_out_str() == "进"
        )
        baseline_station = prepared_nodes[jinhuazhai_index].station_MC

        panel._update_table_from_nodes_full(prepared_nodes, settings.get_station_prefix())
        for row in range(panel.node_table.rowCount()):
            item = panel.node_table.item(row, 0)
            payload = item.data(module.Qt.UserRole) if item else None
            if not isinstance(payload, dict) or not payload.get("_auto_channel"):
                continue
            payload.pop("_auto_channel_structure_type", None)
            payload.pop("_aux_coords", None)
            item.setData(module.Qt.UserRole, payload)

        rebuilt_nodes = panel._build_nodes_from_table()
        rebuilt_auto_channel = next(node for node in rebuilt_nodes if getattr(node, "is_auto_inserted_channel", False))
        assert rebuilt_auto_channel.structure_type == StructureType.RECT_CULVERT

        recalculated = WaterProfileCalculator(settings).calculate_all(rebuilt_nodes)
        recalculated_station = recalculated[jinhuazhai_index].station_MC

        assert recalculated_station == pytest.approx(baseline_station, abs=1e-3)
    finally:
        panel.deleteLater()
