# -*- coding: utf-8 -*-
"""反向纵断面 DXF 导入回归测试。"""

import os
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
