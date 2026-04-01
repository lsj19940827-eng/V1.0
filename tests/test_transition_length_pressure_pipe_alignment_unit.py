# -*- coding: utf-8 -*-
"""普通有压管道渐变段长度口径统一回归测试。"""

import importlib.util
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
CORE_ROOT = ROOT / "推求水面线"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from core.calculator import WaterProfileCalculator
from core.hydraulic_calc import HydraulicCalculator
from models.data_models import ChannelNode, ProjectSettings
from models.enums import StructureType


def _load_formula_dialog_module():
    """加载渐变段长度详情弹窗模块。"""
    module_path = next(Path(".").glob("**/water_profile/formula_dialog.py")).resolve()
    spec = importlib.util.spec_from_file_location(
        "wp_transition_length_pressure_pipe_alignment_test",
        module_path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_pressure_pipe_transition_case():
    """构造普通有压管道进口渐变段测试场景。"""
    prev_node = ChannelNode()
    prev_node.structure_type = StructureType.from_string("明渠-矩形")
    prev_node.name = "上游明渠"
    prev_node.section_params = {
        "B": 1.0,
        "m": 0.0,
        "h": 2.0,
        "水深": 2.0,
        "A": 2.0,
        "X": 5.0,
        "R": 0.4,
    }
    prev_node.water_depth = 2.0
    prev_node.roughness = 0.014
    prev_node.flow_section = "1"

    next_node = ChannelNode()
    next_node.structure_type = StructureType.from_string("有压管道")
    next_node.name = "有压管道1"
    next_node.section_params = {"D": 1.0}
    next_node.water_depth = 2.0
    next_node.roughness = 0.014
    next_node.flow_section = "1"

    transition = ChannelNode()
    transition.is_transition = True
    transition.structure_type = StructureType.TRANSITION
    transition.transition_type = "进口"
    transition.flow_section = "1"
    transition.roughness = 0.014

    return prev_node, transition, next_node


def test_pressure_pipe_transition_formula_matches_topology_estimate():
    """普通有压管道详情里的公式值应与插入阶段口径一致。"""
    settings = ProjectSettings()
    topology_calc = WaterProfileCalculator(settings)
    hydraulic_calc = HydraulicCalculator(settings)
    prev_node, transition, next_node = _make_pressure_pipe_transition_case()

    estimate = topology_calc._estimate_transition_length(
        next_node,
        "进口",
        [prev_node, next_node],
        0,
        upstream_node=prev_node,
        downstream_node=next_node,
    )

    details = hydraulic_calc.ensure_transition_length_details(
        transition,
        prev_node,
        next_node,
        [prev_node, transition, next_node],
        actual_length=estimate,
        preserve_existing_length=True,
    )

    assert estimate == 10.0
    assert details["formula_length"] == 10.0
    assert details["requested_length"] == 10.0
    assert details["actual_length"] == 10.0
    assert transition.transition_length_calc_details["constraint_applied"] == "有压管道"
    assert transition.transition_length_calc_details["constraint_desc"] == "5倍渠道设计水深"


def test_pressure_pipe_transition_dialog_shows_aligned_formula_length(monkeypatch):
    """普通有压管道弹窗不应再显示基础公式 2.5m 这类错位值。"""
    module = _load_formula_dialog_module()
    captured = {}

    class _FakeFormulaDialog:
        def __init__(self, parent, title, sections):
            captured["parent"] = parent
            captured["title"] = title
            captured["sections"] = sections

    monkeypatch.setattr(module, "FormulaDialog", _FakeFormulaDialog)

    settings = ProjectSettings()
    topology_calc = WaterProfileCalculator(settings)
    hydraulic_calc = HydraulicCalculator(settings)
    prev_node, transition, next_node = _make_pressure_pipe_transition_case()

    adopted_length = topology_calc._estimate_transition_length(
        next_node,
        "进口",
        [prev_node, next_node],
        0,
        upstream_node=prev_node,
        downstream_node=next_node,
    )
    details = hydraulic_calc.ensure_transition_length_details(
        transition,
        prev_node,
        next_node,
        [prev_node, transition, next_node],
        actual_length=adopted_length,
        preserve_existing_length=True,
    )

    module.show_transition_length_dialog(None, "行2", details)

    text_blob = "\n".join(
        "\n".join(str(section.get(key, "")) for key in ("title", "values", "content", "formula"))
        for section in captured["sections"]
    )

    assert captured["title"] == "行2 - 渐变段长度计算详情"
    assert "公式/规范计算值  $L_{formula} = 10.000$ m" in text_blob
    assert "规则目标长度  $L_{target} = 10.000$ m" in text_blob
    assert "当前采用长度（最终采用长度）  $L_{actual} = 10.000$ m" in text_blob
    assert "2.500" not in text_blob
