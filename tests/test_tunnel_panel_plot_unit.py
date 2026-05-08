# -*- coding: utf-8 -*-
"""Unit tests for tunnel section-plot titles and horseshoe plotting geometry."""

import importlib
import math
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from matplotlib.figure import Figure

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "codex-mplconfig"))

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

for calc_dir in ROOT.glob("calc_*"):
    calc_path = str(calc_dir)
    if calc_path not in sys.path:
        sys.path.insert(0, calc_path)

tunnel_panel_mod = importlib.import_module("app_\u6e20\u7cfb\u8ba1\u7b97\u524d\u7aef.tunnel.panel")


class _PlotUpdateDummy:
    _section_plot_title = staticmethod(tunnel_panel_mod.TunnelPanel._section_plot_title)

    def __init__(self, all_results):
        self.section_fig = Figure()
        self.section_canvas = SimpleNamespace(draw=lambda: None)
        self._all_results = all_results
        self.titles = []

    def _draw_circular(self, _ax, _D, _h_w, _V, _Q, title):
        self.titles.append(title)

    def _draw_horseshoe(self, _ax, _B, _H_total, _theta_rad, _h_w, _V, _Q, title):
        self.titles.append(title)

    def _draw_horseshoe_std(self, _ax, _sec_type, _r, _h_w, _V, _Q, title):
        self.titles.append(title)


class _FullPlotDummy:
    _section_plot_title = staticmethod(tunnel_panel_mod.TunnelPanel._section_plot_title)
    _apply_section_plot_title = staticmethod(tunnel_panel_mod.TunnelPanel._apply_section_plot_title)
    _horseshoe_plot_geometry = staticmethod(tunnel_panel_mod.TunnelPanel._horseshoe_plot_geometry)
    _horseshoe_plot_half_width = staticmethod(tunnel_panel_mod.TunnelPanel._horseshoe_plot_half_width)
    _horseshoe_cap_polygon = staticmethod(tunnel_panel_mod.TunnelPanel._horseshoe_cap_polygon)
    _draw_circular = tunnel_panel_mod.TunnelPanel._draw_circular
    _draw_flat_bottom_circle = tunnel_panel_mod.TunnelPanel._draw_flat_bottom_circle
    _draw_horseshoe = tunnel_panel_mod.TunnelPanel._draw_horseshoe
    _draw_horseshoe_std = tunnel_panel_mod.TunnelPanel._draw_horseshoe_std

    def __init__(self, all_results):
        self.section_fig = Figure()
        self.section_canvas = SimpleNamespace(draw=lambda: None)
        self._all_results = all_results

    def _draw_increased_waterline(self, *args, **kwargs):
        return tunnel_panel_mod.TunnelPanel._draw_increased_waterline(self, *args, **kwargs)


class _SinglePlotDummy:
    _update_section_plot = tunnel_panel_mod.TunnelPanel._update_section_plot

    def __init__(self, section_type):
        self.section_fig = Figure()
        self.section_canvas = SimpleNamespace(draw=lambda: None)
        self.input_params = {"section_type": section_type, "Q": 8.0, "use_increase": False}
        if section_type == "马蹄形":
            self.input_params["sec_type_int"] = 1
        self.titles = []
        self.increase_calls = []

    def _draw_circular(self, _ax, _D, _h_w, _V, _Q, title):
        self.titles.append(title)

    def _draw_flat_bottom_circle(self, _ax, _D, _B, _h_w, _V, _Q, title):
        self.titles.append(title)

    def _draw_horseshoe(self, _ax, _B, _H_total, _theta_rad, _h_w, _V, _Q, title):
        self.titles.append(title)

    def _draw_horseshoe_std(self, _ax, _sec_type, _r, _h_w, _V, _Q, title):
        self.titles.append(title)

    def _draw_increased_waterline(self, *args, **kwargs):
        self.increase_calls.append((args, kwargs))


class _DrawDummy:
    _apply_section_plot_title = staticmethod(tunnel_panel_mod.TunnelPanel._apply_section_plot_title)
    _horseshoe_plot_geometry = staticmethod(tunnel_panel_mod.TunnelPanel._horseshoe_plot_geometry)
    _horseshoe_plot_half_width = staticmethod(tunnel_panel_mod.TunnelPanel._horseshoe_plot_half_width)
    _horseshoe_cap_polygon = staticmethod(tunnel_panel_mod.TunnelPanel._horseshoe_cap_polygon)


def _increase_overlay_lines(ax):
    """返回加大水位线图元。"""
    return [
        line
        for line in ax.lines
        if line.get_color() == "tab:orange" and line.get_linestyle() == "--"
    ]


def _has_horizontal_line_at(ax, y_value):
    """判断坐标轴中是否存在指定高度的水平线。"""
    for line in ax.lines:
        y_data = list(line.get_ydata())
        if len(y_data) >= 2 and all(float(y) == pytest.approx(y_value, abs=1e-6) for y in y_data):
            return True
    return False


def _has_increased_depth_dimension(ax, expected_y):
    """判断是否存在加大水深竖向尺寸箭头。"""
    for text in ax.texts:
        if text.get_text() != "":
            continue
        arrow_patch = getattr(text, "arrow_patch", None)
        xy = getattr(text, "xy", None)
        xyann = getattr(text, "xyann", None)
        if arrow_patch is None or xy is None or xyann is None:
            continue
        if (
            float(xy[1]) == pytest.approx(expected_y)
            and float(xyann[1]) == pytest.approx(0.0)
            and float(xy[0]) == pytest.approx(float(xyann[0]))
        ):
            return True
    return False


def _multi_case_item(section_type, h_design, h_increased, use_increase=True):
    """生成多工况断面图测试数据。"""
    result = {
        "success": True,
        "h_design": h_design,
        "V_design": 1.2,
        "h_increased": h_increased,
        "V_increased": 1.35,
        "Q_increased": 9.0,
    }
    input_params = {"section_type": section_type, "Q": 8.0, "use_increase": use_increase}
    if section_type == "平底圆形":
        result.update({"D": 4.0, "B": 2.0})
    elif section_type == "圆形":
        result.update({"D": 4.0})
    elif section_type == "圆拱直墙型":
        result.update({"B": 4.0, "H_total": 5.0, "theta_deg": 180.0})
    else:
        result.update({"r": 2.0})
        input_params["sec_type_int"] = 1
    return {"input": input_params, "result": result, "case": {"section_type": section_type}}


def _single_result(section_type):
    """生成单工况断面图测试数据。"""
    result = {
        "success": True,
        "h_design": 1.0,
        "V_design": 1.2,
        "h_increased": 1.5,
        "V_increased": 1.35,
        "Q_increased": 9.0,
    }
    if section_type == "平底圆形":
        result.update({"D": 4.0, "B": 2.0})
    elif section_type == "圆形":
        result.update({"D": 4.0})
    elif section_type == "圆拱直墙型":
        result.update({"B": 4.0, "H_total": 5.0, "theta_deg": 180.0})
    else:
        result.update({"r": 2.0})
    return result


def test_update_section_plot_all_uses_original_case_numbered_titles():
    dummy = _PlotUpdateDummy(
        [
            {
                "input": {"section_type": "圆形", "Q": 10.0},
                "result": {"success": True, "h_design": 1.2, "V_design": 1.0, "D": 2.0},
                "case": {"section_type": "圆形"},
            },
            {
                "input": {"section_type": "圆形", "Q": 11.0},
                "result": {"success": False, "error_message": "缺少参数"},
                "case": {"section_type": "圆形"},
            },
            {
                "input": {"section_type": "圆拱直墙型", "Q": 12.0},
                "result": {
                    "success": True,
                    "h_design": 3.1,
                    "V_design": 1.5,
                    "B": 4.0,
                    "H_total": 5.0,
                    "theta_deg": 180.0,
                },
                "case": {"section_type": "圆拱直墙型"},
            },
        ]
    )

    tunnel_panel_mod.TunnelPanel._update_section_plot_all(dummy)

    assert dummy.titles == ["工况 1｜圆形", "工况 3｜圆拱直墙型"]
    assert all(ch not in "".join(dummy.titles) for ch in "₀₁₂₃₄₅₆₇₈₉")


def test_update_section_plot_all_prefers_custom_label_for_titles():
    dummy = _PlotUpdateDummy(
        [
            {
                "input": {"section_type": "圆拱直墙型", "Q": 10.0},
                "result": {
                    "success": True,
                    "h_design": 2.8,
                    "V_design": 1.4,
                    "B": 3.8,
                    "H_total": 4.6,
                    "theta_deg": 180.0,
                },
                "case": {"section_type": "圆拱直墙型", "custom_label": "北干洞试算"},
            }
        ]
    )

    tunnel_panel_mod.TunnelPanel._update_section_plot_all(dummy)

    assert dummy.titles == ["北干洞试算"]


def test_update_section_plot_all_overlays_increased_waterline_for_supported_sections():
    """多工况断面图应在同一张小图叠加加大水位线。"""
    h_increased_values = [1.6, 1.7, 3.2, 1.4]
    dummy = _FullPlotDummy(
        [
            _multi_case_item("圆形", 1.0, h_increased_values[0]),
            _multi_case_item("平底圆形", 1.1, h_increased_values[1]),
            _multi_case_item("圆拱直墙型", 2.2, h_increased_values[2]),
            _multi_case_item("马蹄形", 0.9, h_increased_values[3]),
        ]
    )

    tunnel_panel_mod.TunnelPanel._update_section_plot_all(dummy)

    visible_axes = [ax for ax in dummy.section_fig.axes if ax.axison]
    assert len(visible_axes) == 4
    for ax, h_increased in zip(visible_axes, h_increased_values):
        assert len(_increase_overlay_lines(ax)) == 1
        assert _has_horizontal_line_at(ax, h_increased)
        labels = [text.get_text() for text in ax.texts]
        assert any("加大水位" in label for label in labels)
        assert f"h加大={h_increased:.2f}m" in labels
        assert _has_increased_depth_dimension(ax, h_increased)


def test_update_section_plot_all_skips_increased_waterline_when_disabled_or_invalid():
    """未启用加大流量或加大水深无效时，不应叠加加大水位线。"""
    dummy = _FullPlotDummy(
        [
            _multi_case_item("圆形", 1.0, 1.6, use_increase=False),
            _multi_case_item("平底圆形", 1.1, 0.0, use_increase=True),
        ]
    )

    tunnel_panel_mod.TunnelPanel._update_section_plot_all(dummy)

    visible_axes = [ax for ax in dummy.section_fig.axes if ax.axison]
    assert len(visible_axes) == 2
    assert all(not _increase_overlay_lines(ax) for ax in visible_axes)
    assert all(not any("h加大" in text.get_text() for text in ax.texts) for ax in visible_axes)


@pytest.mark.parametrize("section_type", ["圆形", "平底圆形", "圆拱直墙型", "马蹄形"])
def test_update_section_plot_hides_increased_plot_when_increase_disabled(section_type):
    """单工况未勾选加大流量时，只显示设计流量断面图。"""
    dummy = _SinglePlotDummy(section_type)

    tunnel_panel_mod.TunnelPanel._update_section_plot(dummy, _single_result(section_type))

    assert dummy.titles == ["设计流量"]
    assert len(dummy.section_fig.axes) == 1
    assert dummy.increase_calls == []


@pytest.mark.parametrize("section_type", ["圆形", "平底圆形", "圆拱直墙型", "马蹄形"])
def test_update_section_plot_overlays_increased_waterline_when_enabled(section_type):
    """单工况启用加大流量时，只显示一张叠加图。"""
    dummy = _SinglePlotDummy(section_type)
    dummy.input_params["use_increase"] = True

    tunnel_panel_mod.TunnelPanel._update_section_plot(dummy, _single_result(section_type))

    assert dummy.titles == ["设计流量"]
    assert len(dummy.section_fig.axes) == 1
    assert len(dummy.increase_calls) == 1


def test_draw_horseshoe_waterline_clamps_to_arch_intersections():
    dummy = _DrawDummy()
    fig = Figure()
    ax = fig.subplots()
    B = 4.0
    H_total = 5.0
    theta_rad = math.pi
    h_w = 4.2

    tunnel_panel_mod.TunnelPanel._draw_horseshoe(
        dummy,
        ax,
        B=B,
        H_total=H_total,
        theta_rad=theta_rad,
        h_w=h_w,
        V=1.49,
        Q=10.0,
        title=tunnel_panel_mod.TunnelPanel._section_plot_title(0, "圆拱直墙型"),
    )

    geom = tunnel_panel_mod.TunnelPanel._horseshoe_plot_geometry(B, H_total, theta_rad)
    expected_half_width = tunnel_panel_mod.TunnelPanel._horseshoe_plot_half_width(geom, h_w)
    blue_lines = [line for line in ax.lines if line.get_color() == "b"]

    assert len(blue_lines) == 1
    waterline = blue_lines[0]
    assert waterline.get_xdata()[0] == pytest.approx(-expected_half_width, abs=1e-6)
    assert waterline.get_xdata()[1] == pytest.approx(expected_half_width, abs=1e-6)
    assert expected_half_width < B / 2

    title = ax.get_title()
    assert "工况 1｜圆拱直墙型" in title
    assert r"\mathregular{m^{3}/s}" in title
    assert r"\mathregular{m/s}" in title


def test_draw_horseshoe_marks_water_depth_label():
    """圆拱直墙型断面图应标注水深。"""
    dummy = _DrawDummy()
    fig = Figure()
    ax = fig.subplots()

    tunnel_panel_mod.TunnelPanel._draw_horseshoe(
        dummy,
        ax,
        B=3.2,
        H_total=3.6,
        theta_rad=math.pi,
        h_w=1.2,
        V=1.20,
        Q=5.0,
        title="工况 1｜圆拱直墙型",
    )

    labels = [text.get_text() for text in ax.texts]
    assert "h=1.20m" in labels


def test_draw_flat_bottom_circle_marks_water_depth_label():
    """平底圆形断面图应标注水深。"""
    dummy = _DrawDummy()
    fig = Figure()
    ax = fig.subplots()

    tunnel_panel_mod.TunnelPanel._draw_flat_bottom_circle(
        dummy,
        ax,
        D=3.2,
        B=2.0,
        h_w=1.2,
        V=1.20,
        Q=5.0,
        title="工况 1｜平底圆形",
    )

    labels = [text.get_text() for text in ax.texts]
    assert "h=1.20m" in labels


def test_draw_horseshoe_uses_kernel_consistent_non_180_degree_geometry():
    dummy = _DrawDummy()
    fig = Figure()
    ax = fig.subplots()
    B = 4.0
    H_total = 4.0
    theta_rad = math.radians(120.0)

    tunnel_panel_mod.TunnelPanel._draw_horseshoe(
        dummy,
        ax,
        B=B,
        H_total=H_total,
        theta_rad=theta_rad,
        h_w=0.0,
        V=1.20,
        Q=8.0,
        title="工况 1｜圆拱直墙型",
    )

    geom = tunnel_panel_mod.TunnelPanel._horseshoe_plot_geometry(B, H_total, theta_rad)
    arch_line = ax.lines[3]
    x_data = arch_line.get_xdata()
    y_data = arch_line.get_ydata()

    assert x_data[0] == pytest.approx(B / 2, abs=1e-6)
    assert y_data[0] == pytest.approx(geom["H_straight"], abs=1e-6)
    assert x_data[-1] == pytest.approx(-B / 2, abs=1e-6)
    assert y_data[-1] == pytest.approx(geom["H_straight"], abs=1e-6)
    assert max(y_data) == pytest.approx(H_total, abs=1e-6)
