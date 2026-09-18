# -*- coding: utf-8 -*-
"""反向纵断面 DXF 导入回归测试。"""

import os
import copy
import json
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SIPHON_ROOT = ROOT / "倒虹吸水力计算系统"
if str(SIPHON_ROOT) not in sys.path:
    sys.path.insert(0, str(SIPHON_ROOT))

import app_渠系计算前端.water_profile.water_profile_dialogs as dialog_mod
from app_渠系计算前端.water_profile.water_profile_dialogs import PressurePipeConfigDialog
from dxf_parser import DxfParser
WATER_PROFILE_ROOT = ROOT / "推求水面线"
if str(WATER_PROFILE_ROOT) not in sys.path:
    sys.path.insert(0, str(WATER_PROFILE_ROOT))

from models.data_models import ChannelNode
from models.enums import InOutType, StructureType
from utils.pressure_pipe_extractor import PressurePipeDataExtractor


@pytest.mark.parametrize("use_recorded_sample", [False, True], ids=["second-station", "xujia-0918-all-114"])
def test_route_reimport_matches_clear_reimport_and_persisted_dxf(monkeypatch, local_tmp_path, use_recorded_sample):
    """真实解析、整线持久化和DXF文字应与清空后重导一致。"""
    import ezdxf
    from managers.pressure_pipe_manager import PressurePipeManager
    from app_渠系计算前端.water_profile import cad_tools

    _get_qapp()
    source = ROOT / "工程资料" / "徐家" / "原始图纸" / "徐家.dxf"
    if not source.exists():
        source = local_tmp_path / "profile.dxf"
        doc = ezdxf.new()
        doc.modelspace().add_lwpolyline([
            (0.0, 328.88), (42.45624695043082, 328.88),
            (79.0716934533557, 322.5213844958879), (100.0, 322.0),
        ])
        doc.saveas(source)

    route_key = "flow2-route1"
    stale = [
        {"chainage": 0.0, "elevation": 328.88},
        {"chainage": 59.77, "elevation": 341.94},
        {"chainage": 100.0, "elevation": 322.0},
    ]
    station_values = [0.0, 59.77]
    if use_recorded_sample:
        # 保存实际成果作为预期值；污染输入仅由错误表采样重建，不冒充历史缓存。
        fixture = json.loads((ROOT / "tests/fixtures/xujia_profile_reimport_0918.json").read_text(encoding="utf-8"))
        columns = fixture["columns"]
        assert len(columns) == 114
        assert sum(c["bad_elevation_text"] != c["good_elevation_text"] for c in columns) == 32
        source = local_tmp_path / "xujia-source.dxf"
        doc = ezdxf.new()
        doc.modelspace().add_lwpolyline(fixture["source_vertices_xyb"], format="xyb")
        doc.saveas(source)
        station_values = [c["station_m"] for c in columns]
        stale = [{"chainage": c["station_m"], "elevation": float(c["bad_elevation_text"])} for c in columns]

        # 对照旧实现：只覆盖同桩号会完整保留错误表的114列取值。
        parsed, _ = DxfParser.parse_longitudinal_profile(str(source))
        imported = PressurePipeConfigDialog._convert_imported_longitudinal_nodes(parsed)
        assert len(imported) == 144
        # 还原旧解析器只保留大于0.5°折点的行为，独立验证清空后版本也有9列偏差。
        legacy_imported = [imported[0]] + [n for n in imported[1:-1] if n["turn_type"] != "NONE"] + [imported[-1]]
        assert len(legacy_imported) == 138
        assert [f'{cad_tools.sample_xxpipe_centerline_elevation(legacy_imported, s):.2f}' for s in station_values] == [
            c["good_elevation_text"] for c in columns
        ]
        legacy_map = {round(n["chainage"], 6): n for n in stale + legacy_imported}
        legacy = sorted(legacy_map.values(), key=lambda n: n["chainage"])
        assert [f'{cad_tools.sample_xxpipe_centerline_elevation(legacy, s):.2f}' for s in station_values] == [
            c["bad_elevation_text"] for c in columns
        ]
        # 按原始折线逐段插值作为独立基准，不复用程序的节点采样器。
        vertices = fixture["source_vertices_xyb"]
        assert all(bulge == 0.0 for _, _, bulge in vertices)
        for column in columns:
            station = column["station_m"]
            start, end = next(
                (a, b) for a, b in zip(vertices, vertices[1:])
                if a[0] - 1e-9 <= station <= b[0] + 1e-9
            )
            elevation = start[1] + (end[1] - start[1]) * (station - start[0]) / (end[0] - start[0])
            assert f"{elevation:.2f}" == column["source_elevation_text"]
        assert sum(c["source_elevation_text"] != c["good_elevation_text"] for c in columns) == 9
    manager = PressurePipeManager(str(local_tmp_path / "route.qxproj"))
    manager.set_route_longitudinal_nodes(route_key, stale, "徐家分支管")
    route_nodes = [
        _set_station_point(
            _make_extractor_node("2", "徐家分支管", "有压管道", InOutType.NORMAL), s, s, 0.0,
        )
        for s in station_values
    ]
    for index, node in enumerate(route_nodes):
        node.pressure_pipe_row_identity = f"flow2-row{index + 1}"
    points = [{"x": n.station_MC, "y": 0.0, "station_mc": n.station_MC} for n in route_nodes]
    dialog = PressurePipeConfigDialog(
        pipe_groups=[], manager=manager, xxpipe_route_mode=True,
        route_import_targets={route_key: {"display_name": "徐家分支管", "nodes": route_nodes}},
    )
    dialog._route_contexts[route_key] = {"display_name": "徐家分支管", "groups": []}
    dialog._restore_manager_route_longitudinal_data(route_key)
    assert dialog._longitudinal_data[route_key] == stale
    errors = []
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *_a, **_k: (str(source), "DXF")))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *_a: errors.append(_a[2])))
    monkeypatch.setattr(dialog_mod, "fluent_info", lambda *_a, **_k: None)
    monkeypatch.setattr(dialog_mod, "fluent_question", lambda *_a, **_k: True)
    try:
        dialog._import_longitudinal_dxf(route_key, points)
        assert errors == []
        direct = copy.deepcopy(dialog._longitudinal_data[route_key])
        reloaded = PressurePipeManager(str(local_tmp_path / "route.qxproj"))
        saved = reloaded.get_route_config(route_key)
        assert saved["longitudinal_nodes"] == direct
        assert round(cad_tools.sample_xxpipe_centerline_elevation(direct, 59.77), 2) == 325.87

        dialog._clear_longitudinal(route_key)
        dialog._import_longitudinal_dxf(route_key, points)
        assert errors == []
        assert dialog._longitudinal_data[route_key] == direct
        reloaded_after_clear = PressurePipeManager(str(local_tmp_path / "route.qxproj"))
        assert reloaded_after_clear.get_route_config(route_key)["raw_profile_polyline"] == saved["raw_profile_polyline"]

        profile = cad_tools._build_xxpipe_profile_data(
            route_nodes, {node.pressure_pipe_row_identity: direct for node in route_nodes},
            station_prefix="徐分支",
        )
        doc = ezdxf.new()
        cad_tools._draw_xxpipe_profile_on_msp(
            doc.modelspace(), route_nodes,
            {"text_height": 3.5, "rotation": 90, "scale_x": 1000, "scale_y": 100,
             "xxpipe_centerline_elev_decimals": 2, "xxpipe_station_decimals": 2},
            "徐分支", xxpipe_profile_data=profile,
        )
        output = local_tmp_path / "reimport.dxf"
        doc.saveas(output)
        texts = [e.dxf.text for e in ezdxf.readfile(output).modelspace().query("TEXT")]
        assert "328.88" in texts
        assert "325.87" in texts
        assert "341.94" not in texts
        if use_recorded_sample:
            expected = [c["source_elevation_text"] for c in columns]
            assert [f'{cad_tools.sample_xxpipe_centerline_elevation(direct, s):.2f}' for s in station_values] == expected
            exported = sorted(
                (float(e.dxf.insert.x), e.dxf.text)
                for e in ezdxf.readfile(output).modelspace().query("TEXT")
                if abs(e.dxf.insert.y - 21.0) < 1e-6
            )
            assert [text for _, text in exported] == expected
    finally:
        dialog.close()
        dialog.deleteLater()


def test_small_slope_change_preserves_elevation_without_adding_bend_loss():
    """小于0.5°的变坡仍须保留高程，但不新增折管计损节点。"""
    from app_渠系计算前端.water_profile.cad_tools import sample_xxpipe_centerline_elevation

    parsed = DxfParser._build_longitudinal_nodes([(0.0, 100.0), (100.0, 100.4), (200.0, 100.0)], [0.0] * 3, 0.0)
    nodes = PressurePipeConfigDialog._convert_imported_longitudinal_nodes(parsed)
    assert len(nodes) == 3
    assert all(n["turn_type"] == "NONE" and n["turn_angle"] == 0.0 for n in nodes)
    assert sample_xxpipe_centerline_elevation(nodes, 100.0) == pytest.approx(100.4)
    assert sample_xxpipe_centerline_elevation(nodes, 150.0) == pytest.approx(100.2)


def test_one_dxf_imports_pressure_parts_with_tunnel_gap_and_replaces_previous_file(monkeypatch, local_tmp_path):
    """一份DXF导入前后有压段，隧洞留空；再次导入不得残留前一份数据。"""
    import ezdxf
    from managers.pressure_pipe_manager import PressurePipeManager
    from utils.pressure_pipe_longitudinal_utils import sample_longitudinal_elevation, clip_longitudinal_nodes_to_range
    from core.pressure_pipe_calc import _calc_longitudinal_segment_length
    from app_渠系计算前端.water_profile import cad_tools

    _get_qapp()
    path = local_tmp_path / 'parts.dxf'
    doc = ezdxf.new()
    doc.layers.new('纵断')
    # 反向绘制后段且实体顺序倒置，仍应整体平移15米并保持中间空档。
    doc.modelspace().add_lwpolyline([(85, 90), (45, 95)], dxfattribs={'layer': '纵断'})
    doc.modelspace().add_lwpolyline([(5, 100), (25, 98)], dxfattribs={'layer': '纵断'})
    doc.saveas(path)
    key = 'flow2-route1'
    manager = PressurePipeManager(str(local_tmp_path / 'mixed.qxproj'))
    manager.set_route_longitudinal_nodes(key, [{'chainage': -20, 'elevation': 999}, {'chainage': 200, 'elevation': 999}], '测试整线')
    route_nodes = []
    definitions = [
        (20, '顶管', '前段', InOutType.INLET), (40, '顶管', '前段', InOutType.OUTLET),
        (40, '隧洞-圆形', '洞段', InOutType.INLET), (60, '隧洞-圆形', '洞段', InOutType.OUTLET),
        (60, '顶管', '后段', InOutType.INLET), (100, '顶管', '后段', InOutType.OUTLET),
    ]
    for index, (station, structure, name, in_out) in enumerate(definitions):
        node = _set_station_point(_make_extractor_node('2', name, structure, in_out), station, station, 0)
        node.pressure_pipe_row_identity = f'flow2-row{index + 1}'
        route_nodes.append(node)
    groups = PressurePipeDataExtractor.extract_dialog_pipe_groups(route_nodes, settings=_make_settings('干管'))
    assert {g.route_key for g in groups} == {key}
    assert all(g.route_start_row_index == 0 and g.route_end_row_index == 5 for g in groups)
    dialog = PressurePipeConfigDialog(pipe_groups=groups, manager=manager, xxpipe_route_mode=True,
        route_import_targets={key: {'display_name': '测试整线', 'nodes': route_nodes, 'import_anchor_station_mc': 20.0}})
    assert len(dialog._route_widgets) == 1
    dialog._restore_manager_route_longitudinal_data(key)
    errors = []
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', staticmethod(lambda *_a, **_k: (str(path), 'DXF')))
    monkeypatch.setattr(QMessageBox, 'critical', staticmethod(lambda *_a: errors.append(_a[2])))
    monkeypatch.setattr(dialog_mod, 'fluent_info', lambda *_a, **_k: None)
    points = [{'station_mc': n.station_MC, 'x': n.x, 'y': n.y} for n in route_nodes]
    try:
        dialog._import_longitudinal_dxf(key, points)
        assert errors == []
        imported = dialog._longitudinal_data[key]
        assert [n['chainage'] for n in imported] == [20, 40, 60, 100]
        assert imported[1]['profile_gap_after']
        assert sum(_calc_longitudinal_segment_length(a, b) for a, b in zip(imported, imported[1:])) == pytest.approx((20**2 + 2**2)**0.5 + (40**2 + 5**2)**0.5)
        assert sample_longitudinal_elevation(imported, 30) == pytest.approx(99)
        assert cad_tools.sample_xxpipe_centerline_elevation(imported, 80) == pytest.approx(92.5)
        for sample in [sample_longitudinal_elevation, cad_tools.sample_xxpipe_centerline_elevation]:
            with pytest.raises(ValueError):
                sample(imported, 50)
        with pytest.raises(ValueError, match='空档'):
            clip_longitudinal_nodes_to_range(imported, 30, 70)
        assert not dialog._collect_xxpipe_route_import_coverage_state(key, imported)['missing_targets']

        saved = PressurePipeManager(str(local_tmp_path / 'mixed.qxproj')).get_route_config(key)
        assert saved['longitudinal_nodes'] == imported
        assert len(saved['raw_profile_polyline']['parts']) == 2
        pressure_nodes = [n for n in route_nodes if '隧洞' not in n.get_structure_type_str()]
        profile = cad_tools._build_xxpipe_profile_data(pressure_nodes,
            {n.pressure_pipe_row_identity: imported for n in pressure_nodes},
            raw_profile_polylines_by_route={key: saved['raw_profile_polyline']},
            warning_context_by_identity={n.pressure_pipe_row_identity: {'route_key': key} for n in pressure_nodes})
        assert [(p['start_mc'], p['end_mc']) for p in profile['centerline_draw_segments']] == [(20, 40), (60, 100)]
        output = ezdxf.new()
        cad_tools._draw_xxpipe_profile_on_msp(output.modelspace(), pressure_nodes,
            {'text_height': 3.5, 'rotation': 90, 'scale_x': 1000, 'scale_y': 1000}, '', xxpipe_profile_data=profile)
        assert len(list(output.modelspace().query('LWPOLYLINE'))) == 2

        # 重开真实整线卡片后仍保留分段结构，预览渲染也能跳过空档。
        reopened = PressurePipeConfigDialog(pipe_groups=groups,
            manager=PressurePipeManager(str(local_tmp_path / 'mixed.qxproj')), xxpipe_route_mode=True,
            route_import_targets={key: {'display_name': '测试整线', 'nodes': route_nodes, 'import_anchor_station_mc': 20.0}})
        try:
            assert reopened._longitudinal_data[key] == imported
            assert len(reopened._raw_profile_polyline_data[key]['parts']) == 2
            canvas = reopened._route_widgets[key]['canvas']
            canvas.set_view_mode('profile')
            assert not canvas.grab().isNull()
        finally:
            reopened.close()
            reopened.deleteLater()

        # 空档若落在有压子段内部，必须报告缺失，不能仅凭两端已覆盖而通过。
        dialog._route_contexts[key]['groups'] = [SimpleNamespace(segment_start_mc=30, segment_end_mc=70, structure_type='有压管道', display_name='跨空档管段')]
        assert dialog._collect_xxpipe_route_import_coverage_state(key, imported)['missing_targets']
        dialog._route_contexts[key]['groups'] = groups

        # 改为较短单段文件后，旧后段和原线parts必须一同消失。
        short = ezdxf.new()
        short.modelspace().add_lwpolyline([(5, 80), (15, 79)])
        short.saveas(path)
        dialog._import_longitudinal_dxf(key, points)
        assert errors == []
        assert [n['chainage'] for n in dialog._longitudinal_data[key]] == [20, 30]
        current = manager.get_route_config(key)
        assert 'parts' not in current['raw_profile_polyline']
        assert len(current['longitudinal_nodes']) == 2
        assert dialog._collect_xxpipe_route_import_coverage_state(key, current['longitudinal_nodes'])['missing_targets']

        # 后续文件读取失败，不能清掉刚才有效导入的数据。
        before = copy.deepcopy(current)
        path.write_text('invalid DXF', encoding='utf-8')
        dialog._import_longitudinal_dxf(key, points)
        assert errors
        assert manager.get_route_config(key) == before
    finally:
        dialog.close()
        dialog.deleteLater()


def test_disconnected_profile_rejects_overlapping_axes(local_tmp_path):
    """前后段必须共用桩号坐标，重叠候选不得按多段轴线混入。"""
    import ezdxf

    doc = ezdxf.new()
    doc.layers.new('纵断')
    doc.modelspace().add_lwpolyline([(0, 100), (100, 90)], dxfattribs={'layer': '纵断'})
    doc.modelspace().add_lwpolyline([(50, 90), (150, 80)], dxfattribs={'layer': '纵断'})
    path = local_tmp_path / 'overlap.dxf'
    doc.saveas(path)
    with pytest.raises(ValueError, match='重叠'):
        DxfParser.get_longitudinal_profile_parts(str(path))


@pytest.fixture
def local_tmp_path():
    """在项目目录下创建临时目录，避开系统临时目录权限问题。"""
    base_dir = ROOT / ".pytest_tmp"
    base_dir.mkdir(exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="reverse-long-", dir=base_dir))
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _get_qapp():
    """确保测试运行时存在 Qt 应用实例。"""
    return QApplication.instance() or QApplication([])


class _FakeManager:
    """提供对话框初始化所需的最小管理器桩。"""

    def get_pipe_config(self, _pipe_name):
        return None

    def get_all_pipe_names(self):
        return []


def _make_extractor_node(flow_section, name, structure, in_out, diameter=0.8, flow=0.49):
    """构造用于提取有压组的最小节点。"""
    node = ChannelNode()
    node.flow_section = flow_section
    node.name = name
    node.structure_type = StructureType.from_string(structure)
    node.in_out = in_out
    node.flow = flow
    node.turn_radius = 0.0
    node.turn_angle = 0.0
    node.section_params = {
        "D": diameter,
        "in_out_raw": in_out.value if hasattr(in_out, "value") else str(in_out),
    }
    return node


def _set_station_point(node, station_mc, x, y):
    """补齐桩号和平面坐标。"""
    node.station_MC = float(station_mc)
    node.x = float(x)
    node.y = float(y)
    return node


def _make_settings(channel_level):
    """构造最小设置对象。"""
    return SimpleNamespace(channel_level=channel_level)


def _build_route_nodes():
    """构造 xx管 整线校验需要的最小节点集。"""
    return [
        SimpleNamespace(
            ip_number=1,
            name="穿路段",
            flow_section="2",
            station_MC=0.0,
            x=0.0,
            y=0.0,
            structure_type=SimpleNamespace(value="有压管道"),
            is_transition=False,
            is_auto_inserted_channel=False,
        ),
        SimpleNamespace(
            ip_number=2,
            name="穿路段",
            flow_section="2",
            station_MC=10.0,
            x=10.0,
            y=0.0,
            structure_type=SimpleNamespace(value="有压管道"),
            is_transition=False,
            is_auto_inserted_channel=False,
        ),
        SimpleNamespace(
            ip_number=3,
            name="穿路段",
            flow_section="2",
            station_MC=30.0,
            x=30.0,
            y=0.0,
            structure_type=SimpleNamespace(value="有压管道"),
            is_transition=False,
            is_auto_inserted_channel=False,
        ),
    ]


def _write_reverse_longitudinal_dxf(tmp_path: Path) -> Path:
    """生成一个 X 从大到小的反向纵断面 DXF。"""
    ezdxf = pytest.importorskip("ezdxf")
    file_path = tmp_path / "reverse_longitudinal.dxf"
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_lwpolyline(
        [
            (30.0, 95.0),
            (10.0, 98.0),
            (0.0, 100.0),
        ]
    )
    doc.saveas(file_path)
    return file_path


def _write_competing_longitudinal_dxf(tmp_path: Path) -> Path:
    """生成包含错误首条线与正确纵断面候选的 DXF。"""
    ezdxf = pytest.importorskip("ezdxf")
    file_path = tmp_path / "competing_longitudinal.dxf"
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    # 第一条多段线模拟工程坐标下的错误候选，长度约 31.1m。
    msp.add_lwpolyline(
        [
            (3469672.8, 3469606.5),
            (3469680.0, 3469635.4),
            (3469703.9, 3469610.2),
        ]
    )
    # 第二条多段线模拟真正的纵断面，局部坐标且图层命中 JQX。
    msp.add_lwpolyline(
        [
            (308.0, 397.0),
            (900.0, 380.0),
            (2049.0966, 329.0),
        ],
        dxfattribs={"layer": "JQX"},
    )
    doc.saveas(file_path)
    return file_path


def _write_close_ranked_longitudinal_dxf(tmp_path: Path) -> Path:
    """生成两条非常接近的纵断面候选，验证需要确认标记。"""
    ezdxf = pytest.importorskip("ezdxf")
    file_path = tmp_path / "close_ranked_longitudinal.dxf"
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    msp.add_lwpolyline(
        [
            (0.0, 100.0),
            (52.0, 96.4),
            (100.0, 92.0),
        ],
        dxfattribs={"layer": "JQX"},
    )
    msp.add_lwpolyline(
        [
            (0.0, 110.0),
            (51.0, 106.8),
            (98.2, 103.5),
        ],
        dxfattribs={"layer": "纵断"},
    )
    doc.saveas(file_path)
    return file_path


def test_dxf_parser_uses_normalized_profile_start_for_reverse_polyline(local_tmp_path):
    """反向纵断面应自动按较小桩号端作为导入起点。"""
    dxf_path = _write_reverse_longitudinal_dxf(local_tmp_path)

    start_x = DxfParser.get_longitudinal_profile_start_x(str(dxf_path))
    nodes, _message = DxfParser.parse_longitudinal_profile(
        str(dxf_path),
        chainage_offset=-start_x,
    )

    assert start_x == pytest.approx(0.0)
    assert [float(node.chainage) for node in nodes] == pytest.approx([0.0, 10.0, 30.0])


def test_dxf_parser_prefers_ranked_longitudinal_candidate_over_first_polyline(local_tmp_path):
    """导入纵断面时应优先选择真正的纵断面候选，而不是盲取首条多段线。"""
    dxf_path = _write_competing_longitudinal_dxf(local_tmp_path)

    selection, error = DxfParser.inspect_longitudinal_profile_candidates(str(dxf_path))
    assert error == ""
    assert selection["selected_rank_index"] == 0
    assert selection["candidates"][0]["layer"] == "JQX"
    assert selection["candidates"][0]["x_span"] == pytest.approx(1741.0966)

    start_x = DxfParser.get_longitudinal_profile_start_x(str(dxf_path))
    nodes, _message = DxfParser.parse_longitudinal_profile(
        str(dxf_path),
        chainage_offset=-start_x,
    )

    assert start_x == pytest.approx(308.0)
    assert float(nodes[0].chainage) == pytest.approx(0.0)
    assert float(nodes[-1].chainage) == pytest.approx(1741.0966)


def test_dxf_parser_marks_confirmation_when_top_ranked_candidates_are_close(local_tmp_path):
    """当前两名候选非常接近时，应给出需要确认标记。"""
    dxf_path = _write_close_ranked_longitudinal_dxf(local_tmp_path)

    selection, error = DxfParser.inspect_longitudinal_profile_candidates(str(dxf_path))

    assert error == ""
    assert selection["selected_rank_index"] == 0
    assert selection["needs_confirmation"] is True
    assert selection["confirmation_rank_indices"] == [0, 1]
    assert selection["candidates"][0]["layer"] == "JQX"
    assert selection["candidates"][1]["layer"] == "纵断"


def test_pressure_pipe_config_dialog_imports_reverse_longitudinal_dxf(monkeypatch, local_tmp_path):
    """xx管 整线导入时应接受反向纵断面 DXF。"""
    _get_qapp()
    dxf_path = _write_reverse_longitudinal_dxf(local_tmp_path)
    route_key = "flow2-route1"
    route_nodes = _build_route_nodes()
    route_points = [
        {"x": 0.0, "y": 0.0, "turn_angle": 0.0, "station_mc": 0.0},
        {"x": 10.0, "y": 0.0, "turn_angle": 0.0, "station_mc": 10.0},
        {"x": 30.0, "y": 0.0, "turn_angle": 0.0, "station_mc": 30.0},
    ]

    dialog = PressurePipeConfigDialog(
        pipe_groups=[],
        manager=_FakeManager(),
        xxpipe_route_mode=True,
        route_import_targets={
            route_key: {
                "display_name": "流量段2 整线1",
                "station_prefix": "",
                "nodes": route_nodes,
            }
        },
    )

    errors = []
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *_args, **_kwargs: (str(dxf_path), "DXF文件 (*.dxf)")),
    )
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        staticmethod(lambda *_args: errors.append(_args[2])),
    )
    monkeypatch.setattr(dialog_mod, "fluent_info", lambda *_args, **_kwargs: None)

    dialog._import_longitudinal_dxf(route_key, route_points)

    assert errors == []
    imported = dialog.get_longitudinal_nodes_dict()[route_key]
    assert imported[0]["chainage"] == pytest.approx(0.0)
    assert imported[-1]["chainage"] == pytest.approx(30.0)

    dialog.close()
    dialog.deleteLater()


def test_pressure_pipe_config_dialog_non_route_import_uses_station_mc_from_extracted_group_points(monkeypatch):
    """普通命名有压组导入时，也应优先按项目桩号对齐。"""
    _get_qapp()
    inlet = _set_station_point(
        _make_extractor_node("8", "三清庙", "有压管道", InOutType.INLET),
        12722.465,
        3469698.1,
        100.0,
    )
    outlet = _set_station_point(
        _make_extractor_node("8", "三清庙", "有压管道", InOutType.OUTLET),
        12762.465,
        3469738.1,
        100.0,
    )
    groups = PressurePipeDataExtractor.extract_dialog_pipe_groups(
        [inlet, outlet],
        settings=_make_settings("支渠"),
    )
    assert len(groups) == 1
    group = groups[0]

    class _FakeParser:
        @staticmethod
        def get_longitudinal_profile_start_x(_filepath):
            return 3469698.1

        @staticmethod
        def parse_longitudinal_profile(_filepath, chainage_offset=0.0):
            turn_type = SimpleNamespace(name="NONE")
            base_x_values = [3469698.1, 3469738.1]
            nodes = [
                SimpleNamespace(
                    chainage=base_x + chainage_offset,
                    elevation=394.5 - index,
                    vertical_curve_radius=0.0,
                    turn_type=turn_type,
                    turn_angle=0.0,
                    slope_before=0.0,
                    slope_after=0.0,
                    arc_center_s=None,
                    arc_center_z=None,
                    arc_end_chainage=None,
                    arc_theta_rad=None,
                )
                for index, base_x in enumerate(base_x_values)
            ]
            return nodes, "测试导入"

    dialog = PressurePipeConfigDialog(
        pipe_groups=[],
        manager=_FakeManager(),
        xxpipe_route_mode=False,
    )

    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *_args, **_kwargs: ("D:/fake/normal-group-import.dxf", "DXF文件 (*.dxf)")),
    )
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *_args, **_kwargs: None))
    monkeypatch.setattr(dialog_mod, "fluent_info", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(dialog_mod, "fluent_question", lambda *_args, **_kwargs: True)
    monkeypatch.setitem(sys.modules, "dxf_parser", SimpleNamespace(DxfParser=_FakeParser))

    dialog._import_longitudinal_dxf(group.storage_key, group.ip_points)

    imported = dialog.get_longitudinal_nodes_dict()[group.storage_key]
    assert imported[0]["chainage"] == pytest.approx(12722.465)
    assert imported[-1]["chainage"] == pytest.approx(12762.465)

    dialog.close()
    dialog.deleteLater()


def test_pressure_pipe_config_dialog_rejects_non_route_import_when_chainage_stays_in_raw_coordinate_space(monkeypatch):
    """导入结果若仍停留在原始坐标空间，应直接报错并中止保存。"""
    _get_qapp()

    class _FakeParser:
        @staticmethod
        def get_longitudinal_profile_start_x(_filepath):
            return 3469698.1

        @staticmethod
        def parse_longitudinal_profile(_filepath, chainage_offset=0.0):
            _ = chainage_offset
            turn_type = SimpleNamespace(name="NONE")
            nodes = [
                SimpleNamespace(
                    chainage=3469698.1,
                    elevation=394.5,
                    vertical_curve_radius=0.0,
                    turn_type=turn_type,
                    turn_angle=0.0,
                    slope_before=0.0,
                    slope_after=0.0,
                    arc_center_s=None,
                    arc_center_z=None,
                    arc_end_chainage=None,
                    arc_theta_rad=None,
                ),
                SimpleNamespace(
                    chainage=3469738.1,
                    elevation=393.5,
                    vertical_curve_radius=0.0,
                    turn_type=turn_type,
                    turn_angle=0.0,
                    slope_before=0.0,
                    slope_after=0.0,
                    arc_center_s=None,
                    arc_center_z=None,
                    arc_end_chainage=None,
                    arc_theta_rad=None,
                ),
            ]
            return nodes, "测试导入"

    dialog = PressurePipeConfigDialog(
        pipe_groups=[],
        manager=_FakeManager(),
        xxpipe_route_mode=False,
    )
    errors = []
    ip_points = [
        {"x": 3469698.1, "y": 100.0, "turn_angle": 0.0, "station_mc": 12722.465},
        {"x": 3469738.1, "y": 100.0, "turn_angle": 0.0, "station_mc": 12762.465},
    ]

    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *_args, **_kwargs: ("D:/fake/raw-coordinate-import.dxf", "DXF文件 (*.dxf)")),
    )
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        staticmethod(lambda *_args: errors.append(_args[2])),
    )
    monkeypatch.setattr(dialog_mod, "fluent_info", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(dialog_mod, "fluent_question", lambda *_args, **_kwargs: True)
    monkeypatch.setitem(sys.modules, "dxf_parser", SimpleNamespace(DxfParser=_FakeParser))

    dialog._import_longitudinal_dxf("三清庙", ip_points)

    assert errors
    assert "原始坐标" in errors[0]
    assert "三清庙" not in dialog.get_longitudinal_nodes_dict()

    dialog.close()
    dialog.deleteLater()


def test_pressure_pipe_config_dialog_stops_import_when_candidate_confirmation_is_cancelled(monkeypatch):
    """候选过于接近且用户取消时，不应继续导入。"""
    _get_qapp()
    route_key = "flow2-route1"
    route_nodes = _build_route_nodes()
    route_points = [
        {"x": 0.0, "y": 0.0, "turn_angle": 0.0, "station_mc": 0.0},
        {"x": 10.0, "y": 0.0, "turn_angle": 0.0, "station_mc": 10.0},
        {"x": 30.0, "y": 0.0, "turn_angle": 0.0, "station_mc": 30.0},
    ]

    class _FakeParser:
        @staticmethod
        def inspect_longitudinal_profile_candidates(_filepath):
            return ({
                "needs_confirmation": True,
                "candidates": [
                    {"layer": "JQX", "x_span": 100.0, "path_length": 101.0},
                    {"layer": "纵断", "x_span": 98.5, "path_length": 99.0},
                ],
            }, "")

        @staticmethod
        def get_longitudinal_profile_start_x(_filepath):
            raise AssertionError("取消后不应继续读取起点 X")

        @staticmethod
        def parse_longitudinal_profile(_filepath, chainage_offset=0.0):
            raise AssertionError("取消后不应继续解析纵断面")

    dialog = PressurePipeConfigDialog(
        pipe_groups=[],
        manager=_FakeManager(),
        xxpipe_route_mode=True,
        route_import_targets={
            route_key: {
                "display_name": "流量段2 整线1",
                "station_prefix": "",
                "nodes": route_nodes,
            }
        },
    )

    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *_args, **_kwargs: ("D:/fake/close-candidates.dxf", "DXF文件 (*.dxf)")),
    )
    monkeypatch.setattr(dialog_mod, "fluent_question", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *_args, **_kwargs: None))
    monkeypatch.setitem(sys.modules, "dxf_parser", SimpleNamespace(DxfParser=_FakeParser))

    dialog._import_longitudinal_dxf(route_key, route_points)

    assert dialog.get_longitudinal_nodes_dict() == {}

    dialog.close()
    dialog.deleteLater()
