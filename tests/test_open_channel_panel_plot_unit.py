# -*- coding: utf-8 -*-
"""明渠断面图绘制回归测试。"""

import importlib
import inspect
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from matplotlib.colors import to_rgba
from matplotlib.figure import Figure


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(tempfile.gettempdir()) / "codex-mplconfig"),
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

for calc_dir in ROOT.glob("calc_*"):
    calc_path = str(calc_dir)
    if calc_path not in sys.path:
        sys.path.insert(0, calc_path)

open_channel_panel_mod = importlib.import_module("app_渠系计算前端.open_channel.panel")


class _PlotAllDummy:
    """只挂载断面图所需属性和绘图方法。"""

    _multi_case_section_plot_title = (
        open_channel_panel_mod.OpenChannelPanel._multi_case_section_plot_title
    )
    _draw_case_section_plot = open_channel_panel_mod.OpenChannelPanel._draw_case_section_plot
    _draw_trapezoid = open_channel_panel_mod.OpenChannelPanel._draw_trapezoid
    _draw_circular = open_channel_panel_mod.OpenChannelPanel._draw_circular
    _draw_compound_trapezoid = open_channel_panel_mod.OpenChannelPanel._draw_compound_trapezoid
    _draw_u_section = open_channel_panel_mod.OpenChannelPanel._draw_u_section
    _update_section_plot = open_channel_panel_mod.OpenChannelPanel._update_section_plot
    _compound_trapezoid_geometry = (
        open_channel_panel_mod.OpenChannelPanel._compound_trapezoid_geometry
    )
    _compound_trapezoid_water_points = (
        open_channel_panel_mod.OpenChannelPanel._compound_trapezoid_water_points
    )
    _compound_trapezoid_view_limits = (
        open_channel_panel_mod.OpenChannelPanel._compound_trapezoid_view_limits
    )

    def __init__(self, all_results):
        self.section_fig = Figure()
        self.section_canvas = SimpleNamespace(draw=lambda: None)
        self._all_results = all_results
        self.input_params = {}


class _DrawTrackingCanvas:
    """记录项目恢复清图时的画布绘制次数。"""

    def __init__(self):
        self.draw_calls = 0

    def draw(self):
        self.draw_calls += 1

    def update(self):
        return None

    def repaint(self):
        return None


class _Notebook:
    """记录项目恢复时页签复位行为。"""

    def __init__(self, current_index=1, count=3):
        self.index = current_index
        self._count = count
        self.set_indexes = []

    def count(self):
        return self._count

    def currentIndex(self):
        return self.index

    def setCurrentIndex(self, index):
        self.index = index
        self.set_indexes.append(index)


def _from_project_dummy():
    """构造带旧断面图残留的项目恢复替身。"""
    fig = Figure()
    axes = fig.subplots(2, 2).ravel()
    axes[-1].set_visible(False)
    return SimpleNamespace(
        section_fig=fig,
        section_canvas=_DrawTrackingCanvas(),
        _section_axis_dialogs={axes[0]: object()},
        _section_plot_layout=object(),
        _section_plot_layout_case_count=3,
        _has_rendered_results=True,
        _results_dirty=True,
        _all_results_stale=True,
        _stale_result_case_indexes={0},
        _load_case=lambda _idx: None,
        _rebuild_case_tags=lambda: None,
        _update_calc_btn_text=lambda: None,
        _display_all_results=lambda: None,
        _update_section_plot_all=lambda: None,
        _refresh_comparison_tables=lambda: None,
        _clear_comparison_tables=lambda: None,
        _show_initial_help=lambda: None,
    )


def _base_trapezoid_case(section_type, q, h):
    """构造梯形或矩形明渠断面图工况。"""
    m = 1.0 if section_type == "梯形" else 0.0
    return (
        {"section_type": section_type, "Q": q, "m": m, "use_increase": True},
        {
            "success": True,
            "b_design": 1.30,
            "h_design": h,
            "h_prime": h + 0.40,
            "V_design": 1.11,
            "Q_increased": q * 1.2,
            "h_increased": h + 0.20,
            "V_increased": 1.16,
        },
    )


def _circular_case(q, diameter, water_depth):
    """构造圆形明渠断面图工况。"""
    return (
        {"section_type": "圆形", "Q": q, "use_increase": True},
        {
            "success": True,
            "D_design": diameter,
            "y_d": water_depth,
            "V_d": 1.05,
            "Q_inc": q * 1.2,
            "y_i": water_depth + 0.20,
            "V_i": 1.17,
        },
    )


def _u_case(q, radius, water_depth):
    """构造 U 形明渠断面图工况。"""
    return (
        {"section_type": "U形", "Q": q, "use_increase": True},
        {
            "success": True,
            "R": radius,
            "alpha_deg": 12.0,
            "theta_deg": 120.0,
            "h_design": water_depth,
            "h_prime": water_depth + 0.60,
            "V_design": 1.08,
            "Q_increased": q * 1.2,
            "h_increased": water_depth + 0.20,
            "V_increased": 1.18,
        },
    )


def _compound_case(q, water_depth):
    """构造复式梯形明渠断面图工况。"""
    return (
        {
            "section_type": "复式梯形",
            "Q": q,
            "m1": 1.0,
            "B1": 2.0,
            "m2": 1.0,
            "B2": 1.50,
            "m3": 1.0,
            "h1": 1.0,
            "use_increase": True,
        },
        {
            "success": True,
            "b_design": 1.50,
            "h_design": water_depth,
            "h_prime": water_depth + 0.50,
            "V_design": 1.12,
            "Q_increased": q * 1.2,
            "h_increased": water_depth + 0.20,
            "V_increased": 1.22,
        },
    )


def _water_line_levels(ax):
    """提取断面图中水平水位线的高度。"""
    levels = []
    for line in ax.lines:
        x_data = list(line.get_xdata())
        y_data = list(line.get_ydata())
        if len(x_data) < 2 or len(y_data) < 2:
            continue
        if not _is_blue_line_color(line.get_color()):
            continue
        if max(y_data) - min(y_data) > 1e-6:
            continue
        if y_data[0] <= 0:
            continue
        levels.append(round(float(y_data[0]), 3))
    return sorted(levels)


def _vertical_dimension_arrow_tops(ax, color):
    """提取指定颜色竖向双向尺寸箭头的顶部高度。"""
    expected_color = to_rgba(color)
    tops = []
    for text in ax.texts:
        arrow_patch = getattr(text, "arrow_patch", None)
        xy = getattr(text, "xy", None)
        xyann = getattr(text, "xyann", None)
        if arrow_patch is None or xy is None or xyann is None:
            continue
        if to_rgba(arrow_patch.get_edgecolor()) != pytest.approx(expected_color):
            continue
        if abs(float(xy[0]) - float(xyann[0])) > 1e-6:
            continue
        y0 = float(xyann[1])
        y1 = float(xy[1])
        if min(y0, y1) != pytest.approx(0.0):
            continue
        if max(y0, y1) <= 0:
            continue
        tops.append(round(max(y0, y1), 3))
    return sorted(tops)


def _is_blue_line_color(color):
    """判断 Matplotlib 线条颜色是否为水位蓝色。"""
    if color == "b":
        return True
    if isinstance(color, tuple) and len(color) >= 3:
        return color[0] == pytest.approx(0.0) and color[1] == pytest.approx(0.0) and color[2] == pytest.approx(1.0)
    return False


def _expected_increase_depth(result):
    """按普通断面和圆形断面的不同字段取加大水深。"""
    return result.get("y_i", result.get("h_increased"))


def _with_use_increase(case, use_increase):
    """复制工况并设置是否启用加大流量。"""
    params, result = case
    return ({**params, "use_increase": use_increase}, dict(result))


def _with_invalid_increase_depth(case):
    """复制工况并把加大水深置为无效。"""
    params, result = case
    result = dict(result)
    if params.get("section_type") == "圆形":
        result["y_i"] = None
    else:
        result["h_increased"] = -1
    return (dict(params), result)


def _increase_depth_label_text(depth):
    """生成加大水深尺寸标注文字。"""
    return f"h加大={depth:.2f}m"


def test_from_project_dict_clears_stale_section_plot_when_open_channel_has_no_results():
    """明渠加载无计算结果项目时，不应保留上一项目的断面子图。"""
    dummy = _from_project_dummy()

    open_channel_panel_mod.OpenChannelPanel.from_project_dict(
        dummy,
        {
            "cases": [open_channel_panel_mod.OpenChannelPanel._default_case()],
            "current_case_idx": 0,
            "all_results": [],
            "current_result": None,
            "input_params": {},
            "result_state": None,
        },
    )

    assert dummy._all_results == []
    assert dummy.current_result is None
    assert dummy.section_fig.axes == []
    assert dummy._section_axis_dialogs == {}
    assert dummy._section_plot_layout is None
    assert dummy._section_plot_layout_case_count is None
    assert dummy._has_rendered_results is False
    assert dummy._results_dirty is False
    assert dummy._all_results_stale is False
    assert dummy._stale_result_case_indexes == set()


def test_from_project_dict_keeps_open_channel_results_when_section_plot_restore_fails():
    """明渠项目恢复时，断面图失败不应清空已加载的计算结果。"""
    dummy = _from_project_dummy()
    params, result = _base_trapezoid_case("梯形", 5.0, 1.30)
    all_results = [(0, params, result)]
    rendered = []
    compared = []
    dummy._display_all_results = lambda: rendered.append("display")
    dummy._refresh_comparison_tables = lambda: compared.append("comparison")

    def fail_plot():
        raise RuntimeError("plot failed")

    dummy._update_section_plot_all = fail_plot

    open_channel_panel_mod.OpenChannelPanel.from_project_dict(
        dummy,
        {
            "cases": [open_channel_panel_mod.OpenChannelPanel._default_case()],
            "current_case_idx": 0,
            "all_results": all_results,
            "current_result": result,
            "input_params": params,
            "result_state": None,
        },
    )

    assert dummy._all_results == all_results
    assert dummy.current_result == result
    assert rendered == ["display"]
    assert compared == ["comparison"]
    assert dummy.section_fig.axes == []
    assert dummy._section_axis_dialogs == {}
    assert dummy._section_plot_layout is None


def test_from_project_dict_schedules_open_channel_section_plot_refresh_after_restoring_tab(monkeypatch):
    """明渠项目恢复到断面图页后，应安排一次最终宽度重排。"""
    dummy = _from_project_dummy()
    dummy.notebook = _Notebook(current_index=1)
    params, result = _base_trapezoid_case("梯形", 5.0, 1.30)
    all_results = [(0, params, result)]
    scheduled = []
    monkeypatch.setattr(
        open_channel_panel_mod,
        "schedule_section_plot_restore_refresh",
        lambda panel: scheduled.append(panel),
        raising=False,
    )

    open_channel_panel_mod.OpenChannelPanel.from_project_dict(
        dummy,
        {
            "cases": [open_channel_panel_mod.OpenChannelPanel._default_case()],
            "current_case_idx": 0,
            "all_results": all_results,
            "current_result": result,
            "input_params": params,
            "result_state": None,
            "notebook_idx": 1,
        },
    )

    assert dummy.notebook.set_indexes == [1]
    assert scheduled == [dummy]


@pytest.mark.parametrize(
    ("case_factory", "expected_labels"),
    [
        (
            lambda: [
                _base_trapezoid_case("梯形", 5.0, 1.57),
                _base_trapezoid_case("梯形", 8.0, 1.70),
            ],
            ("B=", "H=", "h="),
        ),
        (
            lambda: [
                _base_trapezoid_case("矩形", 5.0, 1.40),
                _base_trapezoid_case("矩形", 8.0, 1.60),
            ],
            ("B=", "H=", "h="),
        ),
        (
            lambda: [
                _circular_case(5.0, 2.40, 1.30),
                _circular_case(8.0, 2.80, 1.50),
            ],
            ("D=", "y="),
        ),
        (
            lambda: [
                _u_case(5.0, 1.20, 1.10),
                _u_case(8.0, 1.40, 1.25),
            ],
            ("R=", "h="),
        ),
        (
            lambda: [
                _compound_case(5.0, 1.30),
                _compound_case(8.0, 1.45),
            ],
            ("B2=", "B1=", "H=", "h="),
        ),
    ],
)
def test_multi_case_section_plot_keeps_dimension_labels_for_all_open_channel_types(
    case_factory,
    expected_labels,
):
    """明渠多工况断面图应继续显示各类尺寸标注。"""
    all_results = [
        (case_idx, params, result)
        for case_idx, (params, result) in enumerate(case_factory())
    ]
    dummy = _PlotAllDummy(all_results)

    open_channel_panel_mod.OpenChannelPanel._update_section_plot_all(dummy)

    assert len(dummy.section_fig.axes) == 2
    for ax in dummy.section_fig.axes:
        labels_text = "\n".join(text.get_text() for text in ax.texts)
        for expected_label in expected_labels:
            assert expected_label in labels_text
        assert "工况" in ax.get_title()
        assert "Q=" in ax.get_title()


def test_multi_case_section_plot_has_no_simplified_fallback_branch():
    """多工况断面图不应再保留只画简图的旧分支。"""
    source = inspect.getsource(open_channel_panel_mod.OpenChannelPanel._update_section_plot_all)

    assert "多工况简单网格" not in source
    assert "ax.text(0.5, 0.5, stype" not in source
    assert "_draw_case_section_plot" in source


def test_multi_case_section_plot_uses_two_columns_for_many_open_channel_cases():
    """明渠 10 个成功工况应切到 2 列，并拉高画布交给滚动区。"""
    all_results = [
        (idx, params | {"Q": 5.0 + idx}, result)
        for idx, (params, result) in enumerate(
            [_base_trapezoid_case("梯形", 5.0 + i, 1.30 + i * 0.01) for i in range(10)]
        )
    ]
    dummy = _PlotAllDummy(all_results)

    open_channel_panel_mod.OpenChannelPanel._update_section_plot_all(dummy)

    assert dummy._section_plot_layout.columns == 2
    assert dummy._section_plot_layout.rows == 5
    assert dummy.section_fig.get_size_inches()[1] >= 18
    assert len(dummy._section_axis_dialogs) == 10


def test_multi_case_section_plot_keeps_open_channel_axes_centered():
    """明渠宽扁断面不应被顶对齐压到每个网格上沿。"""
    all_results = [
        (idx, params | {"Q": 5.0 + idx}, result)
        for idx, (params, result) in enumerate(
            [_base_trapezoid_case("梯形", 5.0 + i, 1.30 + i * 0.01) for i in range(6)]
        )
    ]
    dummy = _PlotAllDummy(all_results)

    open_channel_panel_mod.OpenChannelPanel._update_section_plot_all(dummy)

    assert dummy._section_plot_layout.axis_anchor == "C"
    assert [ax.get_anchor() for ax in dummy.section_fig.axes] == ["C"] * 6


def test_multi_case_section_plot_uses_two_columns_for_five_open_channel_cases():
    """明渠 5 个成功工况也应固定 2 列，避免 3 列横向裁切。"""
    all_results = [
        (idx, params | {"Q": 5.0 + idx}, result)
        for idx, (params, result) in enumerate(
            [_base_trapezoid_case("矩形", 5.0 + i, 1.30 + i * 0.01) for i in range(5)]
        )
    ]
    dummy = _PlotAllDummy(all_results)

    open_channel_panel_mod.OpenChannelPanel._update_section_plot_all(dummy)

    assert dummy._section_plot_layout.columns == 2
    assert dummy._section_plot_layout.rows == 3
    assert len(dummy._section_axis_dialogs) == 5


def test_single_success_multi_case_open_channel_registers_double_click_dialog():
    """明渠多工况只剩 1 个成功结果时，也应保留双击放大入口。"""
    params, result = _base_trapezoid_case("梯形", 5.0, 1.30)
    dummy = _PlotAllDummy(
        [
            (0, params, result),
            (1, params | {"Q": 6.0}, {"success": False, "error_message": "缺少参数"}),
        ]
    )

    open_channel_panel_mod.OpenChannelPanel._update_section_plot_all(dummy)

    assert len(dummy.section_fig.axes) == 1
    assert len(dummy._section_axis_dialogs) == 1


@pytest.mark.parametrize(
    "case_factory",
    [
        lambda: _base_trapezoid_case("梯形", 5.0, 1.57),
        lambda: _base_trapezoid_case("矩形", 6.0, 1.40),
        lambda: _compound_case(7.0, 1.30),
        lambda: _u_case(8.0, 1.10, 1.05),
        lambda: _circular_case(9.0, 2.60, 1.20),
    ],
)
def test_multi_case_section_plot_overlays_increase_water_level(case_factory):
    """多工况断面图应在同一子图叠加设计水位和加大水位。"""
    first_case = case_factory()
    second_case = case_factory()
    all_results = [
        (0, first_case[0], first_case[1]),
        (1, second_case[0], second_case[1]),
    ]
    dummy = _PlotAllDummy(all_results)

    open_channel_panel_mod.OpenChannelPanel._update_section_plot_all(dummy)

    assert len(dummy.section_fig.axes) == 2
    design_depth = first_case[1].get("y_d", first_case[1].get("h_design"))
    increase_depth = _expected_increase_depth(first_case[1])
    for ax in dummy.section_fig.axes:
        levels = _water_line_levels(ax)
        assert round(design_depth, 3) in levels
        assert round(increase_depth, 3) in levels
        labels = [text.get_text() for text in ax.texts]
        assert any("加大水位" in label for label in labels)


@pytest.mark.parametrize(
    "case_factory",
    [
        lambda: _base_trapezoid_case("梯形", 5.0, 1.57),
        lambda: _base_trapezoid_case("矩形", 6.0, 1.40),
        lambda: _compound_case(7.0, 1.30),
        lambda: _u_case(8.0, 1.10, 1.05),
        lambda: _circular_case(9.0, 2.60, 1.20),
    ],
)
def test_multi_case_section_plot_draws_increase_depth_dimension(case_factory):
    """多工况断面图应为加大水深绘制竖向双向尺寸箭头。"""
    first_case = case_factory()
    second_case = case_factory()
    all_results = [
        (0, first_case[0], first_case[1]),
        (1, second_case[0], second_case[1]),
    ]
    dummy = _PlotAllDummy(all_results)

    open_channel_panel_mod.OpenChannelPanel._update_section_plot_all(dummy)

    increase_depth = _expected_increase_depth(first_case[1])
    expected_label = _increase_depth_label_text(increase_depth)
    for ax in dummy.section_fig.axes:
        labels = [text for text in ax.texts if text.get_text() == expected_label]
        assert len(labels) == 1
        assert to_rgba(labels[0].get_color()) == pytest.approx(to_rgba("blue"))
        assert round(increase_depth, 3) in _vertical_dimension_arrow_tops(ax, "blue")

        existing_dimension_x = [
            text.get_position()[0]
            for text in ax.texts
            if text.get_text().startswith(("h=", "y=", "H=", "R=", "B=", "B1=", "B2="))
        ]
        assert all(
            labels[0].get_position()[0] != pytest.approx(existing_x)
            for existing_x in existing_dimension_x
        )


@pytest.mark.parametrize(
    "case_factory",
    [
        lambda: _base_trapezoid_case("梯形", 5.0, 1.57),
        lambda: _circular_case(9.0, 2.60, 1.20),
    ],
)
@pytest.mark.parametrize("case_mutator", [_with_use_increase, _with_invalid_increase_depth])
def test_multi_case_section_plot_skips_increase_water_level_when_disabled_or_invalid(
    case_factory,
    case_mutator,
):
    """未启用加大流量或加大水深无效时，多工况断面图不画加大水位线。"""
    if case_mutator is _with_use_increase:
        first_case = case_mutator(case_factory(), False)
        second_case = case_mutator(case_factory(), False)
    else:
        first_case = case_mutator(case_factory())
        second_case = case_mutator(case_factory())
    all_results = [
        (0, first_case[0], first_case[1]),
        (1, second_case[0], second_case[1]),
    ]
    dummy = _PlotAllDummy(all_results)

    open_channel_panel_mod.OpenChannelPanel._update_section_plot_all(dummy)

    assert len(dummy.section_fig.axes) == 2
    design_depth = first_case[1].get("y_d", first_case[1].get("h_design"))
    original_increase_depth = _expected_increase_depth(case_factory()[1])
    for ax in dummy.section_fig.axes:
        levels = _water_line_levels(ax)
        assert levels == [round(design_depth, 3)]
        assert round(original_increase_depth, 3) not in levels
        assert all("h加大=" not in text.get_text() for text in ax.texts)


def test_single_circular_section_plot_uses_increase_depth_fields():
    """圆形明渠单工况应在同一张图叠加 y_i 加大水位。"""
    params, result = _circular_case(9.0, 2.60, 1.20)
    dummy = _PlotAllDummy([])
    dummy.input_params = params

    open_channel_panel_mod.OpenChannelPanel._update_section_plot(dummy, result)

    assert len(dummy.section_fig.axes) == 1
    ax = dummy.section_fig.axes[0]
    levels = _water_line_levels(ax)
    assert round(result["y_d"], 3) in levels
    assert round(result["y_i"], 3) in levels
    labels = [text.get_text() for text in ax.texts]
    assert any("加大水位" in label for label in labels)
    assert _increase_depth_label_text(result["y_i"]) in labels


@pytest.mark.parametrize(
    "case_factory",
    [
        lambda: _base_trapezoid_case("梯形", 5.0, 1.57),
        lambda: _base_trapezoid_case("矩形", 6.0, 1.40),
        lambda: _compound_case(7.0, 1.30),
        lambda: _u_case(8.0, 1.10, 1.05),
        lambda: _circular_case(9.0, 2.60, 1.20),
    ],
)
def test_single_section_plot_overlays_increase_water_level_when_enabled(case_factory):
    """明渠单工况启用加大流量时，应只有一张图并同图叠加加大水位。"""
    params, result = case_factory()
    dummy = _PlotAllDummy([])
    dummy.input_params = params

    open_channel_panel_mod.OpenChannelPanel._update_section_plot(dummy, result)

    assert len(dummy.section_fig.axes) == 1
    ax = dummy.section_fig.axes[0]
    design_depth = result.get("y_d", result.get("h_design"))
    increase_depth = _expected_increase_depth(result)
    levels = _water_line_levels(ax)
    assert round(design_depth, 3) in levels
    assert round(increase_depth, 3) in levels
    labels = [text.get_text() for text in ax.texts]
    assert any("加大水位" in label for label in labels)
    assert _increase_depth_label_text(increase_depth) in labels
