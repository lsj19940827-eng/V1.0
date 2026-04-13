# -*- coding: utf-8 -*-
"""平底圆形隧洞在断面汇总链路中的独立支持测试。"""

import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")


def _load_summary_module():
    """加载断面汇总表模块。"""
    root = Path(__file__).resolve().parents[1]
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    matches = [p for p in root.glob("*/*.py") if p.name == "生成断面汇总表.py"]
    assert matches, "未找到 生成断面汇总表.py"
    spec = importlib.util.spec_from_file_location("summary_flat_bottom_test_mod", matches[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


summary_mod = _load_summary_module()


def _load_cad_tools_module():
    """加载 cad_tools 模块。"""
    root = Path(__file__).resolve().parents[1]
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    matches = list(root.glob("*/water_profile/cad_tools.py"))
    assert matches, "未找到 cad_tools.py"
    spec = importlib.util.spec_from_file_location("flat_bottom_summary_cad_tools_test_mod", matches[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cad_tools = _load_cad_tools_module()


def _get_qapp():
    """获取测试用 Qt 应用。"""
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


def _make_flat_bottom_tunnel_node():
    """构造平底圆形隧洞测试节点。"""
    return SimpleNamespace(
        is_transition=False,
        is_auto_inserted_channel=False,
        is_inverted_siphon=False,
        is_pressure_pipe=False,
        structure_type=SimpleNamespace(value="隧洞-平底圆形"),
        name="平底试验洞",
        flow_section="1",
        flow=5.0,
        roughness=0.014,
        slope_i=1.0 / 2000.0,
        section_params={"D": 4.0, "B": 2.0, "H_total": 3.732},
        water_depth=1.58,
        velocity=2.31,
        structure_height=3.732,
        head_loss_siphon=0.0,
    )


def test_flat_bottom_tunnel_is_classified_and_extracted_as_independent_summary_group():
    """平底圆形隧洞应进入独立的断面汇总分组，而不是混入圆形隧洞。"""
    node = _make_flat_bottom_tunnel_node()

    assert summary_mod._classify_structure(node) == "tunnel_flat_bottom_circular"

    defaults, flow_qs = summary_mod._extract_segment_defaults_from_nodes([node])

    assert flow_qs[1] == pytest.approx(5.0)
    assert 1 in defaults["tunnel_flat_bottom_circular"]
    segment = defaults["tunnel_flat_bottom_circular"][1]
    assert segment["D"] == pytest.approx(4.0)
    assert segment["B"] == pytest.approx(2.0)
    assert segment["H"] == pytest.approx(3.74)


def test_flat_bottom_tunnel_summary_builder_exposes_bottom_width_and_total_height():
    """平底圆形隧洞汇总表应有独立标题，并显式输出 D、B、H_total。"""
    compute = getattr(summary_mod, "compute_tunnel_flat_bottom_circular", None)
    assert callable(compute), "缺少 compute_tunnel_flat_bottom_circular"

    builder = getattr(summary_mod, "_dxf_build_tunnel_flat_bottom_circular", None)
    assert callable(builder), "缺少 _dxf_build_tunnel_flat_bottom_circular"

    rows, info = compute(
        [
            {
                "name": "第一流量段",
                "Q": 5.0,
                "n": 0.014,
                "slope_inv": 2000,
                "D": 4.0,
                "B": 2.0,
            }
        ],
        rock_lining=None,
        unified=False,
    )

    assert info["D"] == pytest.approx(4.0)
    assert info["B"] == pytest.approx(2.0)
    assert info["H_total"] == pytest.approx(3.732050807568877, rel=1e-6)

    title, headers, _widths, table_rows, merge = builder(rows)

    assert title == "平底圆形隧洞断面尺寸及水力要素表"
    assert ("直径D", "m") in headers
    assert ("平底宽B", "m") in headers
    assert ("总高H", "m") in headers
    assert table_rows[0][6] == pytest.approx(4.0)
    assert table_rows[0][7] == pytest.approx(2.0)
    assert table_rows[0][8] == pytest.approx(3.73, rel=1e-2)
    assert merge == [([0, 1, 2], 3)]


def test_cad_section_summary_chain_draws_flat_bottom_tunnel_as_independent_table(monkeypatch):
    """cad_tools 断面汇总导出应把平底圆形作为独立表输出。"""
    actual_summary = importlib.import_module("calc_渠系计算算法内核.生成断面汇总表")
    captured_titles = []

    def _fake_draw_table(msp, x0, y0, title, headers, col_widths, rows, merge_groups=None, layer="0"):
        _ = (msp, x0, y0, headers, col_widths, rows, merge_groups, layer)
        captured_titles.append(title)
        return 100.0

    monkeypatch.setattr(actual_summary, "_dxf_draw_table", _fake_draw_table)

    node = _make_flat_bottom_tunnel_node()
    panel = SimpleNamespace(
        _custom_struct_thickness=None,
        _custom_rock_lining=None,
        _custom_tunnel_unified={},
    )

    cad_tools._draw_section_summary_on_msp(
        panel=panel,
        msp=object(),
        nodes=[node],
        proj_settings=None,
        pressurized_params={"siphon": [], "pressure_pipe": []},
        below_y=0.0,
        summary_layer="SUMMARY",
    )

    assert "平底圆形隧洞断面尺寸及水力要素表" in captured_titles


def test_section_summary_dialog_exposes_flat_bottom_tunnel_mode_group():
    """断面汇总配置对话框应单独暴露平底圆形隧洞模式。"""
    _get_qapp()

    dialog = cad_tools.SectionSummaryDialog(None, [], None, config_only=True)

    assert "tunnel_flat_bottom_circular" in dialog._tunnel_mode_groups
