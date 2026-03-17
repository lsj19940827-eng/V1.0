# -*- coding: utf-8 -*-
"""退水闸结构形式回归单元测试。"""

import importlib
import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "推求水面线"))

from core.calculator import WaterProfileCalculator
from models.data_models import ChannelNode, ProjectSettings
from models.enums import InOutType, StructureType
from shared.shared_data_manager import normalize_section_type_name


def _get_panel_class():
    app_name = next(path.name for path in ROOT.iterdir() if path.is_dir() and path.name.startswith("app_"))
    module = importlib.import_module(f"{app_name}.water_profile.panel")
    return module.WaterProfilePanel


def _get_qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def test_normalize_section_type_name_keeps_return_water_gate():
    assert normalize_section_type_name("退水闸") == "退水闸"


def test_build_nodes_from_table_keeps_return_water_gate_structure_type():
    _get_qt_app()
    panel_cls = _get_panel_class()
    panel = panel_cls()
    try:
        panel._add_node_row(
            ["1", "朱家垭", "退水闸", "", "IP305", "664539.4281", "3443198.5791", ""],
            _skip_undo=True,
            _defer_controls_refresh=True,
        )

        nodes = panel._build_nodes_from_table()

        assert len(nodes) == 1
        assert nodes[0].structure_type == StructureType.RETURN_WATER_GATE
        assert nodes[0].is_diversion_gate is True
    finally:
        panel.deleteLater()


def test_return_water_gate_uses_existing_gate_transition_rules():
    pressure_pipe_outlet = ChannelNode()
    pressure_pipe_outlet.structure_type = StructureType.PRESSURE_PIPE
    pressure_pipe_outlet.name = "有压管道1"
    pressure_pipe_outlet.in_out = InOutType.OUTLET
    pressure_pipe_outlet.section_params = {"D": 1.5}
    pressure_pipe_outlet.station_MC = 100.0

    return_water_gate = ChannelNode()
    return_water_gate.structure_type = StructureType.RETURN_WATER_GATE
    return_water_gate.name = "朱家垭"
    return_water_gate.station_MC = 120.0

    calculator = WaterProfileCalculator(ProjectSettings())
    result = calculator._check_gap_exit_to_gate(pressure_pipe_outlet, return_water_gate)

    assert result["need_transition_1"] is True
    assert result["skip_loss_transition_1"] is True
    assert result["distance"] == 20.0
