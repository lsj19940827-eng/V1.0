# -*- coding: utf-8 -*-
"""泄水渠与陡坡纵断面图中文化和第二版线型测试。"""

import sys
from pathlib import Path

from matplotlib.figure import Figure

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_渠系计算前端.spillway_steep_chute.plotting import draw_longitudinal_profile


def test_longitudinal_profile_uses_chinese_labels_and_v2_lines():
    """纵断面图应使用中文标题、坐标和图例，并显示掺气水面线与侧墙顶线。"""
    fig = Figure()
    draw_longitudinal_profile(
        fig,
        {
            "profile_points": [
                {
                    "distance_m": 0.0,
                    "bed_elevation_m": 100.0,
                    "water_elevation_m": 101.0,
                    "aerated_water_elevation_m": 101.2,
                    "sidewall_top_elevation_m": 101.8,
                },
                {
                    "distance_m": 20.0,
                    "bed_elevation_m": 99.0,
                    "water_elevation_m": 99.8,
                    "aerated_water_elevation_m": 100.0,
                    "sidewall_top_elevation_m": 100.6,
                },
            ]
        },
    )

    ax = fig.axes[0]
    legend_labels = [item.get_text() for item in ax.get_legend().texts]
    line_xs = [list(line.get_xdata()) for line in ax.lines]
    assert ax.get_title() == "泄水渠与陡坡纵断面图"
    assert ax.get_xlabel() == "沿程距离（米）"
    assert ax.get_ylabel() == "高程（米）"
    assert legend_labels == ["渠底线", "水面线", "掺气水面线", "侧墙顶线"]
    assert line_xs[0] == [0.0, 20.0]
