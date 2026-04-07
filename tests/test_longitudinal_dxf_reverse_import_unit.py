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
