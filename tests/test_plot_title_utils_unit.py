# -*- coding: utf-8 -*-
"""Tests for shared Matplotlib plot-title helpers."""

import os
import sys
import tempfile
from pathlib import Path

from matplotlib.figure import Figure

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "codex-mplconfig"))

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_渠系计算前端.plot_title_utils import (  # noqa: E402
    apply_flow_velocity_title,
    format_flow_velocity_metrics,
)


def test_format_flow_velocity_metrics_uses_mathregular_units():
    text = format_flow_velocity_metrics(10.0, 1.49)

    assert text == r"Q=10.00 $\mathregular{m^{3}/s}$, V=1.49 $\mathregular{m/s}$"


def test_apply_flow_velocity_title_sets_two_line_title():
    fig = Figure()
    ax = fig.subplots()

    apply_flow_velocity_title(ax, "工况 1｜圆拱直墙型", 10.0, 1.49, fontsize=10)

    title = ax.get_title()
    assert title.startswith("工况 1｜圆拱直墙型\nQ=10.00 ")
    assert r"\mathregular{m^{3}/s}" in title
    assert r"\mathregular{m/s}" in title
