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
    _draw_u_section = aqueduct_panel_mod.AqueductPanel._draw_u_section
    _draw_rect_section = aqueduct_panel_mod.AqueductPanel._draw_rect_section

    def __init__(self, all_results, cases):
        self.section_fig = Figure()
        self.section_canvas = SimpleNamespace(draw=lambda: None)
        self._all_results = all_results
        self._cases = cases


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
def test_update_section_plot_uses_two_subplots_when_increase_enabled(section_type, result_factory):
    dummy = _SinglePlotDummy({"Q": 5.0, "use_increase": True, "section_type": section_type})

    aqueduct_panel_mod.AqueductPanel._update_section_plot(dummy, result_factory())

    assert len(dummy.section_fig.axes) == 2
    assert dummy.titles == ["设计流量", "加大流量"]


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
    _get_qapp()
    monkeypatch.setattr(aqueduct_panel_mod, "create_web_view", QTextEdit)
    panel = aqueduct_panel_mod.AqueductPanel()
    panel.resize(1400, 900)
    panel.show()

    scroll_areas = panel.findChildren(QScrollArea)
    assert scroll_areas
    input_scroll = scroll_areas[0]
    assert input_scroll.minimumWidth() >= 340
    assert input_scroll.maximumWidth() > 10000

    hint_labels = [
        label
        for label in panel.findChildren(QLabel)
        if "拉杆自身尺寸高度" in label.text()
    ]
    assert hint_labels
    assert hint_labels[0].wordWrap() is True

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
