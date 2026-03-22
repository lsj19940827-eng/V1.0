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


class _DrawDummy:
    _apply_section_plot_title = staticmethod(tunnel_panel_mod.TunnelPanel._apply_section_plot_title)
    _horseshoe_plot_geometry = staticmethod(tunnel_panel_mod.TunnelPanel._horseshoe_plot_geometry)
    _horseshoe_plot_half_width = staticmethod(tunnel_panel_mod.TunnelPanel._horseshoe_plot_half_width)
    _horseshoe_cap_polygon = staticmethod(tunnel_panel_mod.TunnelPanel._horseshoe_cap_polygon)


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
