# -*- coding: utf-8 -*-
"""Unit tests for aqueduct section-plot titles and plot routing."""

import importlib
import math
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from matplotlib.colors import to_rgba
from matplotlib.figure import Figure
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea, QTextEdit

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

aqueduct_panel_mod = importlib.import_module("app_渠系计算前端.aqueduct.panel")


def _get_qapp():
    """获取测试用 Qt 应用。"""
    return QApplication.instance() or QApplication([])


def _process_events(app, rounds=8):
    """让 Qt 完成当前窗口布局。"""
    for _ in range(rounds):
        app.processEvents()


def _axis_width_px(fig, ax):
    """返回子图在画布中的像素宽度。"""
    return ax.get_position().width * fig.get_size_inches()[0] * fig.dpi


def _u_result():
    return {
        "success": True,
        "section_type": "U形",
        "R": 1.4,
        "f": 0.6,
        "H_total": 2.0,
        "h_design": 1.2,
        "V_design": 1.1,
        "Q_increased": 6.0,
        "h_increased": 1.45,
        "V_increased": 1.2,
    }


def _rect_result(*, has_chamfer=False, custom_label=None):
    result = {
        "success": True,
        "section_type": "矩形",
        "B": 3.41,
        "H_total": 2.72,
        "h_design": 2.27,
        "V_design": 1.30,
        "Q_increased": 12.0,
        "h_increased": 2.62,
        "V_increased": 1.35,
        "has_chamfer": has_chamfer,
        "chamfer_angle": 30 if has_chamfer else 0,
        "chamfer_length": 0.2 if has_chamfer else 0,
    }
    if custom_label is not None:
        result["custom_label"] = custom_label
    return result


class _PlotAllDummy:
    _section_plot_title = staticmethod(aqueduct_panel_mod.AqueductPanel._section_plot_title)
    _update_section_plot = aqueduct_panel_mod.AqueductPanel._update_section_plot

    def __init__(self, all_results, cases):
        self.section_fig = Figure()
        self.section_canvas = SimpleNamespace(draw=lambda: None)
        self._all_results = all_results
        self._cases = cases
        self.calls = []

    def _draw_u_section(self, _ax, R, f, H_total, h_w, V, Q, title, result=None):
        self.calls.append(
            {
                "kind": "U形",
                "R": R,
                "f": f,
                "H_total": H_total,
                "h_w": h_w,
                "V": V,
                "Q": Q,
                "title": title,
                "result": result,
            }
        )

    def _draw_rect_section(self, _ax, B, H_total, h_w, V, Q, title, result=None):
        self.calls.append(
            {
                "kind": "矩形",
                "B": B,
                "H_total": H_total,
                "h_w": h_w,
                "V": V,
                "Q": Q,
                "title": title,
                "result": result,
            }
        )


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


class _SinglePlotDummy:
    def __init__(self, input_params):
        self.section_fig = Figure()
        self.section_canvas = SimpleNamespace(draw=lambda: None)
        self.input_params = input_params
        self.titles = []

    def _draw_u_section(self, *_args):
        self.titles.append(_args[-2])

    def _draw_rect_section(self, *_args, **_kwargs):
        self.titles.append(_args[6])


class _DrawDummy:
    _apply_section_plot_title = staticmethod(aqueduct_panel_mod.AqueductPanel._apply_section_plot_title)


class _RenderPlotAllDummy:
    _section_plot_title = staticmethod(aqueduct_panel_mod.AqueductPanel._section_plot_title)
    _apply_section_plot_title = staticmethod(aqueduct_panel_mod.AqueductPanel._apply_section_plot_title)
    _update_section_plot = aqueduct_panel_mod.AqueductPanel._update_section_plot
    _draw_u_section = aqueduct_panel_mod.AqueductPanel._draw_u_section
    _draw_rect_section = aqueduct_panel_mod.AqueductPanel._draw_rect_section

    def __init__(self, all_results=None, cases=None, input_params=None):
        self.section_fig = Figure()
        self.section_canvas = SimpleNamespace(draw=lambda: None)
        self._all_results = all_results or []
        self._cases = cases or []
        self.input_params = input_params or {}


class _PanelParseDummy:
    pass


def _horizontal_dashed_lines_at(ax, y_value):
    """查找指定高程处的水平虚线。"""
    matches = []
    for line in ax.lines:
        y_data = list(line.get_ydata())
        if not y_data or line.get_linestyle() != "--":
            continue
        if all(abs(float(y) - y_value) < 1e-6 for y in y_data):
            matches.append(line)
    return matches


def _assert_increased_line(ax, h_increased, expected_left, expected_right):
    """断言加大水位线按真实断面宽度绘制。"""
    matches = _horizontal_dashed_lines_at(ax, h_increased)
    assert len(matches) == 1
    x_data = list(matches[0].get_xdata())
    assert x_data[0] == pytest.approx(expected_left)
    assert x_data[-1] == pytest.approx(expected_right)

    labels = [text.get_text() for text in ax.texts]
    assert any("加大水位" in label for label in labels)


def _vertical_double_arrows_at(ax, height, color):
    """查找从0到指定水深的同色竖向双向箭头。"""
    expected_color = to_rgba(color)
    matches = []
    for text in ax.texts:
        if text.get_text() != "":
            continue
        arrow = getattr(text, "arrow_patch", None)
        if arrow is None:
            continue
        x0, y0 = text.xy
        x1, y1 = text.get_position()
        if abs(float(x0) - float(x1)) > 1e-6:
            continue
        if sorted([float(y0), float(y1)]) != pytest.approx([0.0, height]):
            continue
        if arrow.get_edgecolor() != pytest.approx(expected_color):
            continue
        matches.append(text)
    return matches


def _assert_increased_depth_dimension(ax, h_increased):
    """断言加大水深尺寸标注完整且避开既有竖向尺寸。"""
    color = "#0066cc"
    expected_label = f"h加大={h_increased:.2f}m"
    labels = [text for text in ax.texts if text.get_text() == expected_label]
    assert len(labels) == 1
    label = labels[0]
    label_x, label_y = label.get_position()
    assert label_y == pytest.approx(h_increased / 2)
    assert label.get_color() == color
    assert label.get_rotation() == pytest.approx(90)

    existing_vertical_labels = [
        text
        for text in ax.texts
        if text.get_text().startswith(("h=", "H="))
    ]
    assert existing_vertical_labels
    for existing in existing_vertical_labels:
        assert abs(label_x - existing.get_position()[0]) > 1e-6

    arrows = _vertical_double_arrows_at(ax, h_increased, color)
    assert len(arrows) == 1


def test_from_project_dict_clears_stale_section_plot_when_aqueduct_has_no_results():
    """渡槽加载无计算结果项目时，不应保留上一项目的断面子图。"""
    dummy = _from_project_dummy()

    aqueduct_panel_mod.AqueductPanel.from_project_dict(
        dummy,
        {
            "cases": [aqueduct_panel_mod.AqueductPanel._default_case()],
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


def test_from_project_dict_keeps_aqueduct_results_when_section_plot_restore_fails():
    """渡槽项目恢复时，断面图失败不应清空已加载的计算结果。"""
    dummy = _from_project_dummy()
    params = {"section_type": "U形", "Q": 5.0}
    result = _u_result()
    all_results = [(0, params, result)]
    rendered = []
    compared = []
    dummy._display_all_results = lambda: rendered.append("display")
    dummy._refresh_comparison_tables = lambda: compared.append("comparison")

    def fail_plot():
        raise RuntimeError("plot failed")

    dummy._update_section_plot_all = fail_plot

    aqueduct_panel_mod.AqueductPanel.from_project_dict(
        dummy,
        {
            "cases": [aqueduct_panel_mod.AqueductPanel._default_case()],
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


def test_from_project_dict_schedules_aqueduct_section_plot_refresh_after_restoring_tab(monkeypatch):
    """渡槽项目恢复到断面图页后，应安排一次最终宽度重排。"""
    dummy = _from_project_dummy()
    dummy.notebook = _Notebook(current_index=1)
    params = {"section_type": "U形", "Q": 5.0}
    result = _u_result()
    all_results = [(0, params, result)]
    scheduled = []
    monkeypatch.setattr(
        aqueduct_panel_mod,
        "schedule_section_plot_restore_refresh",
        lambda panel: scheduled.append(panel),
        raising=False,
    )

    aqueduct_panel_mod.AqueductPanel.from_project_dict(
        dummy,
        {
            "cases": [aqueduct_panel_mod.AqueductPanel._default_case()],
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


def test_update_section_plot_all_uses_original_case_numbered_titles_and_h_total():
    rect_result = _rect_result()
    dummy = _PlotAllDummy(
        [
            (0, {"section_type": "U形", "Q": 5.0}, _u_result()),
            (1, {"section_type": "矩形", "Q": 8.0}, {"success": False, "error_message": "缺少参数"}),
            (2, {"section_type": "矩形", "Q": 10.0}, rect_result),
        ],
        [
            {"section_type": "U形"},
            {"section_type": "矩形"},
            {"section_type": "矩形"},
        ],
    )

    aqueduct_panel_mod.AqueductPanel._update_section_plot_all(dummy)

    assert [call["title"] for call in dummy.calls] == ["工况 1｜U形", "工况 3｜矩形"]
    assert dummy.calls[0]["kind"] == "U形"
    assert dummy.calls[1]["kind"] == "矩形"
    assert dummy.calls[1]["H_total"] == pytest.approx(rect_result["H_total"])


def test_update_section_plot_all_prefers_custom_label_and_passes_rect_result_through():
    rect_result = _rect_result(has_chamfer=True)
    dummy = _PlotAllDummy(
        [
            (0, {"section_type": "U形", "Q": 5.0}, _u_result()),
            (1, {"section_type": "矩形", "Q": 10.0}, rect_result),
        ],
        [
            {"section_type": "U形"},
            {"section_type": "矩形", "custom_label": "北干槽试算"},
        ],
    )

    aqueduct_panel_mod.AqueductPanel._update_section_plot_all(dummy)

    assert [call["title"] for call in dummy.calls] == ["工况 1｜U形", "北干槽试算"]
    assert dummy.calls[1]["result"] is rect_result
    assert dummy.calls[1]["result"]["has_chamfer"] is True


def test_update_section_plot_all_uses_two_columns_for_many_aqueduct_cases():
    """渡槽 10 个成功工况应切到 2 列，并登记双击放大信息。"""
    all_results = [
        (idx, {"section_type": "矩形", "Q": 8.0 + idx}, _rect_result())
        for idx in range(10)
    ]
    dummy = _PlotAllDummy(all_results, [{"section_type": "矩形"} for _ in range(10)])

    aqueduct_panel_mod.AqueductPanel._update_section_plot_all(dummy)

    assert dummy._section_plot_layout.columns == 2
    assert dummy._section_plot_layout.rows == 5
    assert dummy.section_fig.get_size_inches()[1] >= 18
    assert len(dummy._section_axis_dialogs) == 10


def test_update_section_plot_all_uses_two_columns_for_five_aqueduct_cases():
    """渡槽 5 个成功工况也应固定 2 列。"""
    all_results = [
        (idx, {"section_type": "矩形", "Q": 8.0 + idx}, _rect_result())
        for idx in range(5)
    ]
    dummy = _PlotAllDummy(all_results, [{"section_type": "矩形"} for _ in range(5)])

    aqueduct_panel_mod.AqueductPanel._update_section_plot_all(dummy)

    assert dummy._section_plot_layout.columns == 2
    assert dummy._section_plot_layout.rows == 3
    assert len(dummy._section_axis_dialogs) == 5


def test_single_success_multi_case_aqueduct_registers_double_click_dialog():
    """渡槽多工况只剩 1 个成功结果时，也应保留双击放大入口。"""
    params = {"section_type": "U形", "Q": 5.0}
    result = _u_result()
    dummy = _PlotAllDummy(
        [
            (0, params, result),
            (1, {"section_type": "矩形", "Q": 8.0}, {"success": False, "error_message": "缺少参数"}),
        ],
        [{"section_type": "U形"}, {"section_type": "矩形"}],
    )

    aqueduct_panel_mod.AqueductPanel._update_section_plot_all(dummy)

    assert len(dummy.section_fig.axes) == 1
    assert len(dummy._section_axis_dialogs) == 1


@pytest.mark.parametrize("section_type", ["U形", "矩形", "带倒角矩形"])
def test_update_section_plot_all_overlays_increased_water_level_when_enabled(section_type):
    if section_type == "U形":
        result = _u_result()
        result["h_increased"] = 0.7
        expected_half_width = result["R"] * math.sqrt(1 - (1 - result["h_increased"] / result["R"]) ** 2)
        expected_left, expected_right = -expected_half_width, expected_half_width
        params = {"section_type": "U形", "Q": 5.0, "use_increase": True}
        case = {"section_type": "U形"}
    elif section_type == "带倒角矩形":
        result = _rect_result(has_chamfer=True)
        result["h_increased"] = 0.05
        chamfer_height = result["chamfer_length"] * math.tan(math.radians(result["chamfer_angle"]))
        offset = result["chamfer_length"] * (result["h_increased"] / chamfer_height)
        expected_left, expected_right = -result["B"] / 2 + offset, result["B"] / 2 - offset
        params = {"section_type": "矩形", "Q": 8.0, "use_increase": True}
        case = {"section_type": "矩形"}
    else:
        result = _rect_result()
        expected_left, expected_right = -result["B"] / 2, result["B"] / 2
        params = {"section_type": "矩形", "Q": 8.0, "use_increase": True}
        case = {"section_type": "矩形"}

    dummy = _RenderPlotAllDummy(
        [
            (0, params, result),
            (1, {"section_type": "矩形", "Q": 9.0, "use_increase": False}, _rect_result()),
        ],
        [case, {"section_type": "矩形"}],
    )

    aqueduct_panel_mod.AqueductPanel._update_section_plot_all(dummy)

    _assert_increased_line(dummy.section_fig.axes[0], result["h_increased"], expected_left, expected_right)
    _assert_increased_depth_dimension(dummy.section_fig.axes[0], result["h_increased"])


@pytest.mark.parametrize(
    ("use_increase", "h_increased"),
    [(False, 1.45), (True, 0.0), (True, None), (True, "bad")],
)
def test_update_section_plot_all_skips_increased_water_level_when_disabled_or_invalid(use_increase, h_increased):
    result = _u_result()
    result["h_increased"] = h_increased
    dummy = _RenderPlotAllDummy(
        [
            (0, {"section_type": "U形", "Q": 5.0, "use_increase": use_increase}, result),
            (1, {"section_type": "矩形", "Q": 9.0, "use_increase": False}, _rect_result()),
        ],
        [{"section_type": "U形"}, {"section_type": "矩形"}],
    )

    aqueduct_panel_mod.AqueductPanel._update_section_plot_all(dummy)

    assert _horizontal_dashed_lines_at(dummy.section_fig.axes[0], 1.45) == []
    labels = [text.get_text() for text in dummy.section_fig.axes[0].texts]
    assert not any(label.startswith("h加大=") for label in labels)


@pytest.mark.parametrize(
    ("section_type", "result_factory"),
    [("U形", _u_result), ("矩形", _rect_result)],
)
def test_update_section_plot_uses_single_subplot_when_increase_disabled(section_type, result_factory):
    dummy = _SinglePlotDummy({"Q": 5.0, "use_increase": False, "section_type": section_type})

    aqueduct_panel_mod.AqueductPanel._update_section_plot(dummy, result_factory())

    assert len(dummy.section_fig.axes) == 1
    assert dummy.titles == ["设计流量"]


@pytest.mark.parametrize(
    ("section_type", "result_factory"),
    [("U形", _u_result), ("矩形", _rect_result)],
)
def test_update_section_plot_uses_single_subplot_when_increase_enabled(section_type, result_factory):
    dummy = _SinglePlotDummy({"Q": 5.0, "use_increase": True, "section_type": section_type})

    aqueduct_panel_mod.AqueductPanel._update_section_plot(dummy, result_factory())

    assert len(dummy.section_fig.axes) == 1
    assert dummy.titles == ["设计流量"]


@pytest.mark.parametrize(
    ("section_type", "result_factory", "expected_span"),
    [
        (
            "U形",
            _u_result,
            lambda result: (
                -result["R"]
                if result["h_increased"] > result["R"]
                else -result["R"] * math.sqrt(1 - (1 - result["h_increased"] / result["R"]) ** 2),
                result["R"]
                if result["h_increased"] > result["R"]
                else result["R"] * math.sqrt(1 - (1 - result["h_increased"] / result["R"]) ** 2),
            ),
        ),
        ("矩形", _rect_result, lambda result: (-result["B"] / 2, result["B"] / 2)),
    ],
)
def test_single_section_plot_overlays_increased_waterline_when_enabled(
    section_type,
    result_factory,
    expected_span,
):
    """渡槽单工况启用加大流量时，应同图叠加加大水位。"""
    result = result_factory()
    dummy = _RenderPlotAllDummy(input_params={"Q": 5.0, "use_increase": True, "section_type": section_type})

    aqueduct_panel_mod.AqueductPanel._update_section_plot(dummy, result)

    assert len(dummy.section_fig.axes) == 1
    ax = dummy.section_fig.axes[0]
    expected_left, expected_right = expected_span(result)
    _assert_increased_line(ax, result["h_increased"], expected_left, expected_right)
    _assert_increased_depth_dimension(ax, result["h_increased"])


def test_draw_u_section_spans_negative_and_positive_x_coordinates():
    dummy = _DrawDummy()
    fig = Figure()
    ax = fig.subplots()

    aqueduct_panel_mod.AqueductPanel._draw_u_section(
        dummy,
        ax,
        R=1.4,
        f=0.6,
        H_total=2.0,
        h_w=1.2,
        V=1.1,
        Q=5.0,
        title="工况 1｜U形",
    )

    all_x = []
    for line in ax.lines:
        all_x.extend(list(line.get_xdata()))

    assert min(all_x) < -1.35
    assert max(all_x) > 1.35

    title = ax.get_title()
    assert "工况 1｜U形" in title
    assert r"\mathregular{m^{3}/s}" in title
    assert r"\mathregular{m/s}" in title


def test_aqueduct_input_sidebar_width_and_hints_are_readable(monkeypatch):
    """渡槽左侧输入栏应有足够默认宽度，长说明文字应自动换行。"""
    app = _get_qapp()
    monkeypatch.setattr(aqueduct_panel_mod, "create_web_view", QTextEdit)
    panel = aqueduct_panel_mod.AqueductPanel()
    panel.resize(1400, 900)
    panel.show()
    _process_events(app)

    scroll_areas = panel.findChildren(QScrollArea)
    assert scroll_areas
    input_scroll = next(
        scroll for scroll in scroll_areas
        if scroll.minimumWidth() >= 340
    )
    assert input_scroll.minimumWidth() >= 340
    assert input_scroll.maximumWidth() == 420
    assert input_scroll.width() <= 420

    hint_labels = [
        label
        for label in panel.findChildren(QLabel)
        if "拉杆自身尺寸高度" in label.text()
    ]
    assert hint_labels
    assert hint_labels[0].wordWrap() is True

    panel.deleteLater()


def test_aqueduct_first_section_plot_uses_readable_width_without_dragging(monkeypatch):
    """宽窗口首次打开渡槽断面图时，不应依赖拖动分隔栏才能变大。"""
    app = _get_qapp()
    monkeypatch.setattr(aqueduct_panel_mod, "create_web_view", QTextEdit)
    panel = aqueduct_panel_mod.AqueductPanel()
    panel.resize(1800, 1200)
    panel.show()
    panel.notebook.setCurrentIndex(1)
    _process_events(app)

    first = _u_result()
    second = _u_result()
    second["h_design"] = 1.15
    second["h_increased"] = 1.40
    panel._cases = [{"section_type": "U形"}, {"section_type": "U形"}]
    panel._all_results = [
        (0, {"section_type": "U形", "Q": 9.9, "use_increase": True}, first),
        (1, {"section_type": "U形", "Q": 9.5, "use_increase": True}, second),
    ]

    aqueduct_panel_mod.AqueductPanel._update_section_plot_all(panel)
    _process_events(app)

    input_scroll = next(
        scroll for scroll in panel.findChildren(QScrollArea)
        if scroll.minimumWidth() >= 340
    )
    visible_axes = [ax for ax in panel.section_fig.axes if ax.axison]
    assert input_scroll.width() <= 420
    assert panel._section_plot_layout.columns == 2
    assert _axis_width_px(panel.section_fig, visible_axes[0]) >= 520

    panel.deleteLater()


def test_parse_case_passes_tie_rod_height_to_u_kernel():
    params, result = aqueduct_panel_mod.AqueductPanel._parse_and_calc_case(
        _PanelParseDummy(),
        {
            "section_type": "U形",
            "Q": "5.0",
            "n": "0.014",
            "slope_inv": "3000",
            "v_min": "0.1",
            "v_max": "100.0",
            "inc_checked": True,
            "inc_pct": "10",
            "inc_mode": aqueduct_panel_mod.INCREASE_MODE_PERCENT,
            "inc_q_text": "",
            "detail_checked": True,
            "R": "2.4",
            "tie_rod_height": "0.35",
        },
        1,
    )

    assert params["tie_rod_height"] == pytest.approx(0.35)
    assert result["success"] is True
    assert result["tie_rod_height"] == pytest.approx(0.35)
    assert result["H_total"] == pytest.approx(result["tie_bottom_height"] + 0.35)


def test_parse_case_rejects_invalid_tie_rod_height():
    with pytest.raises(ValueError, match="拉杆高度输入无效"):
        aqueduct_panel_mod.AqueductPanel._parse_and_calc_case(
            _PanelParseDummy(),
            {
                "section_type": "U形",
                "Q": "5.0",
                "n": "0.014",
                "slope_inv": "3000",
                "v_min": "0.1",
                "v_max": "100.0",
                "inc_checked": True,
                "inc_pct": "10",
                "inc_mode": aqueduct_panel_mod.INCREASE_MODE_PERCENT,
                "inc_q_text": "",
                "detail_checked": True,
                "R": "2.4",
                "tie_rod_height": "abc",
            },
            1,
        )


def test_parse_case_rejects_negative_tie_rod_height_for_rect():
    with pytest.raises(ValueError, match="拉杆高度不能为负数"):
        aqueduct_panel_mod.AqueductPanel._parse_and_calc_case(
            _PanelParseDummy(),
            {
                "section_type": "矩形",
                "Q": "5.0",
                "n": "0.014",
                "slope_inv": "3000",
                "v_min": "0.1",
                "v_max": "100.0",
                "inc_checked": False,
                "inc_pct": "",
                "inc_mode": aqueduct_panel_mod.INCREASE_MODE_PERCENT,
                "inc_q_text": "",
                "detail_checked": True,
                "ratio": "0.8",
                "B": "",
                "chamfer_angle": "",
                "chamfer_len": "",
                "tie_rod_height": "-0.01",
            },
            1,
        )


def test_default_case_and_copy_keys_include_tie_rod_height():
    case = aqueduct_panel_mod.AqueductPanel._default_case()

    assert case["tie_rod_height"] == ""


def test_draw_u_section_marks_tie_rod_band_and_control_line():
    dummy = _DrawDummy()
    fig = Figure()
    ax = fig.subplots()

    aqueduct_panel_mod.AqueductPanel._draw_u_section(
        dummy,
        ax,
        R=1.4,
        f=0.95,
        H_total=2.35,
        h_w=1.7,
        V=1.1,
        Q=5.0,
        title="加大流量",
        result={
            "tie_rod_height": 0.35,
            "tie_bottom_height": 2.0,
            "top_clearance": 0.65,
            "Fb": 0.30,
        },
    )

    labels = [text.get_text() for text in ax.texts]
    assert any("拉杆高度" in label for label in labels)
    assert any("拉杆底" in label for label in labels)


def test_draw_u_design_section_marks_tie_bottom_clearance():
    dummy = _DrawDummy()
    fig = Figure()
    ax = fig.subplots()

    aqueduct_panel_mod.AqueductPanel._draw_u_section(
        dummy,
        ax,
        R=1.4,
        f=0.95,
        H_total=2.35,
        h_w=1.65,
        V=1.1,
        Q=5.0,
        title="设计流量",
        result={
            "tie_rod_height": 0.35,
            "tie_bottom_height": 2.0,
            "design_tie_bottom_clearance": 0.35,
        },
    )

    labels = [text.get_text() for text in ax.texts]
    assert any("设计净距" in label for label in labels)
