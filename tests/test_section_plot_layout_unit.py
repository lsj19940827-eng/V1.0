# -*- coding: utf-8 -*-
"""多工况断面图滚动布局与双击放大交互测试。"""

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from app_渠系计算前端 import section_plot_layout as section_plot_layout_mod
from app_渠系计算前端.section_plot_layout import (
    SectionGridLayout,
    SectionGridOptions,
    apply_section_axis_alignment,
    apply_section_grid_spacing,
    choose_section_grid_layout,
    clear_section_plot_state,
    configure_section_grid_canvas,
    connect_section_tab_refresh,
    create_section_plot_scroll_area,
    finalize_section_grid_layout,
    handle_section_plot_double_click,
    register_section_axis_dialog,
    refresh_section_plot_when_visible,
    schedule_section_plot_restore_refresh,
    TUNNEL_SECTION_GRID_OPTIONS,
)


def _get_qapp():
    """获取测试用 Qt 应用实例。"""
    return QApplication.instance() or QApplication([])


class _Canvas:
    """记录画布尺寸调整，模拟 Qt FigureCanvas。"""

    def __init__(self):
        self.minimum_height = 0
        self.resized_to = None

    def setMinimumHeight(self, height):
        self.minimum_height = height

    def resize(self, width, height):
        self.resized_to = (width, height)

    def width(self):
        return 1200


class _Widget:
    """提供 width/viewport/parentWidget 的轻量控件替身。"""

    def __init__(self, width, parent=None, viewport=None, horizontal_bar=None):
        self._width = width
        self._parent = parent
        self._viewport = viewport
        self._horizontal_bar = horizontal_bar

    def width(self):
        return self._width

    def parentWidget(self):
        return self._parent

    def viewport(self):
        return self._viewport

    def horizontalScrollBar(self):
        return self._horizontal_bar


class _ScrollBar:
    """记录横向滚动位置复位行为。"""

    def __init__(self, value):
        self.value = value
        self.values = []

    def setValue(self, value):
        self.value = value
        self.values.append(value)


class _Signal:
    """模拟 Qt signal 的 connect/emit。"""

    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, value):
        for callback in list(self.callbacks):
            callback(value)


class _Notebook(_Widget):
    """带 currentChanged 信号的页签替身。"""

    def __init__(self, width):
        super().__init__(width)
        self.currentChanged = _Signal()


class _TrackingCanvas(QWidget):
    """记录滚动时同步刷新调用的轻量画布。"""

    def __init__(self):
        super().__init__()
        self.update_calls = 0
        self.repaint_calls = 0

    def update(self, *args):
        self.update_calls += 1
        return super().update(*args)

    def repaint(self, *args):
        self.repaint_calls += 1
        return super().repaint(*args)


class _DrawTrackingCanvas(_Canvas):
    """记录清理断面图时的 draw/update/repaint 调用。"""

    def __init__(self):
        super().__init__()
        self.draw_calls = 0
        self.update_calls = 0
        self.repaint_calls = 0

    def draw(self):
        self.draw_calls += 1

    def update(self):
        self.update_calls += 1

    def repaint(self):
        self.repaint_calls += 1


def test_create_section_plot_scroll_area_uses_explicit_canvas_size_and_repaints_on_scroll():
    """断面图滚动区应由布局显式控制画布尺寸，并在纵向滚动时强制刷新。"""
    _get_qapp()
    canvas = _TrackingCanvas()
    canvas.resize(900, 1800)

    scroll = create_section_plot_scroll_area(canvas)
    scroll.resize(600, 400)
    scroll.verticalScrollBar().setRange(0, 1200)

    assert scroll.widgetResizable() is False
    assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert scroll.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded
    assert scroll.widget().size().width() == 900
    assert scroll.widget().size().height() == 1800

    scroll.verticalScrollBar().setValue(240)

    assert canvas.update_calls >= 1
    assert canvas.repaint_calls >= 1


def test_clear_section_plot_state_removes_axes_dialogs_and_layout_state():
    """加载无结果项目时，应清空旧断面图画布和交互状态。"""
    fig = Figure()
    axes = fig.subplots(2, 2).ravel()
    axes[-1].set_visible(False)
    canvas = _DrawTrackingCanvas()
    horizontal_bar = _ScrollBar(240)
    panel = SimpleNamespace(
        section_fig=fig,
        section_canvas=canvas,
        _section_plot_scroll=_Widget(
            1200,
            viewport=_Widget(1200),
            horizontal_bar=horizontal_bar,
        ),
        _section_axis_dialogs={axes[0]: object()},
        _section_plot_layout=choose_section_grid_layout(3, 1200),
        _section_plot_layout_case_count=3,
    )

    clear_section_plot_state(panel)

    assert panel.section_fig.axes == []
    assert panel._section_axis_dialogs == {}
    assert getattr(panel, "_section_plot_layout") is None
    assert getattr(panel, "_section_plot_layout_case_count") is None
    assert horizontal_bar.value == 0
    assert canvas.minimum_height == 600
    assert canvas.resized_to == (1200, 600)
    assert canvas.draw_calls == 1
    assert canvas.update_calls >= 1
    assert canvas.repaint_calls >= 1


def test_clear_section_plot_state_tolerates_missing_canvas_and_scroll():
    """清理函数在测试替身或异常缺省控件上也不应报错。"""
    fig = Figure()
    fig.subplots()
    panel = SimpleNamespace(section_fig=fig)

    clear_section_plot_state(panel)

    assert panel.section_fig.axes == []
    assert panel._section_axis_dialogs == {}


def test_section_grid_layout_uses_two_columns_for_five_wide_cases():
    """5 个工况且宽度足够时，也应固定 2 列避免横向裁切。"""
    layout = choose_section_grid_layout(5, available_width_px=1280)

    assert layout.columns == 2
    assert layout.rows == 3
    assert layout.canvas_height_px == 1080


def test_section_grid_layout_uses_two_columns_for_two_wide_cases():
    """2 个工况且宽度足够时，应并排显示为 2 列。"""
    layout = choose_section_grid_layout(2, available_width_px=1280)

    assert layout.columns == 2
    assert layout.rows == 1


def test_section_grid_layout_uses_two_columns_for_many_cases():
    """10 个工况应切到 2 列，避免小图过窄过矮。"""
    layout = choose_section_grid_layout(10, available_width_px=1280)

    assert layout.columns == 2
    assert layout.rows == 5
    assert layout.canvas_height_px == 1800


def test_section_grid_layout_accepts_custom_row_height_for_tall_sections():
    """高瘦断面可指定更高行高，避免等比例子图被压窄。"""
    layout = choose_section_grid_layout(9, available_width_px=1200, row_height_px=520)

    assert layout.columns == 2
    assert layout.rows == 5
    assert layout.canvas_width_px == 1200
    assert layout.canvas_height_px == 2600


def test_section_grid_layout_falls_back_to_one_column_when_narrow():
    """右侧区域明显不足时，应退到 1 列避免横向挤压。"""
    layout = choose_section_grid_layout(5, available_width_px=620)

    assert layout.columns == 1
    assert layout.rows == 5


def test_configure_section_grid_canvas_expands_figure_height_for_thirty_cases():
    """30 个工况时，画布高度应随行数增长，交给滚动区域承载。"""
    panel = SimpleNamespace(section_fig=Figure(dpi=100), section_canvas=_Canvas())

    layout = configure_section_grid_canvas(panel, 30, available_width_px=1280)

    assert layout.columns == 2
    assert layout.rows == 15
    assert layout.canvas_height_px == 5400
    assert panel.section_canvas.minimum_height == 5400
    assert panel.section_fig.get_size_inches()[1] == 54


def test_configure_section_grid_canvas_applies_custom_row_height():
    """配置画布时应把自定义行高同步到 Figure 和 Qt 画布。"""
    panel = SimpleNamespace(section_fig=Figure(dpi=100), section_canvas=_Canvas())

    layout = configure_section_grid_canvas(
        panel,
        9,
        available_width_px=1200,
        row_height_px=520,
    )

    assert layout.columns == 2
    assert layout.rows == 5
    assert layout.canvas_height_px == 2600
    assert panel.section_canvas.minimum_height == 2600
    assert panel.section_canvas.resized_to == (1200, 2600)
    assert panel.section_fig.get_size_inches()[1] == 26


def test_section_grid_options_can_top_align_equal_aspect_axes():
    """多工况等比例断面图应能把坐标轴顶对齐，减少首屏上方空白。"""
    panel = SimpleNamespace(section_fig=Figure(dpi=100), section_canvas=_Canvas())

    layout = configure_section_grid_canvas(
        panel,
        4,
        available_width_px=1200,
        layout_options=SectionGridOptions(axis_anchor="N"),
    )
    axes = panel.section_fig.subplots(2, 2).ravel()
    for ax in axes:
        ax.set_aspect("equal")

    apply_section_axis_alignment(panel, layout)

    assert layout.axis_anchor == "N"
    assert [ax.get_anchor() for ax in axes] == ["N"] * 4


def test_finalize_section_grid_layout_applies_spacing_alignment_and_readability():
    """统一收口函数应同时完成边距、锚点和等比例可读高度校正。"""
    fig = Figure(figsize=(12, 7.2), dpi=100)
    axes = fig.subplots(2, 2, squeeze=False)
    for ax in axes.ravel():
        ax.set_xlim(-5, 5)
        ax.set_ylim(-0.5, 1.2)
        ax.set_aspect("equal")
    panel = SimpleNamespace(section_fig=fig, section_canvas=_Canvas())
    layout = SectionGridLayout(
        2,
        2,
        1200,
        720,
        axis_anchor="C",
        ensure_axis_readability=True,
        min_axis_width_px=420,
    )

    finalized = finalize_section_grid_layout(panel, layout, multi=True)

    assert finalized.canvas_height_px >= layout.canvas_height_px
    assert [ax.get_anchor() for ax in axes.ravel()] == ["C"] * 4
    assert panel._section_plot_layout == finalized


def test_tunnel_section_grid_options_keep_special_height_without_readability_growth():
    """隧洞通过共享配置保留高行高、顶对齐和 9 工况 2600px 画布。"""
    panel = SimpleNamespace(section_fig=Figure(dpi=100), section_canvas=_Canvas())
    layout = configure_section_grid_canvas(
        panel,
        9,
        available_width_px=1200,
        layout_options=TUNNEL_SECTION_GRID_OPTIONS,
    )
    axes = panel.section_fig.subplots(5, 2, squeeze=False)
    for ax in axes.ravel():
        ax.set_xlim(-4, 4)
        ax.set_ylim(-0.5, 6.0)
        ax.set_aspect("equal")

    finalized = finalize_section_grid_layout(panel, layout, multi=True)

    assert finalized.canvas_width_px == 1200
    assert finalized.canvas_height_px == 2600
    assert finalized.axis_anchor == "N"
    assert [ax.get_anchor() for ax in axes.ravel()] == ["N"] * 10


def test_section_grid_spacing_does_not_change_axis_anchor():
    """标题安全边距只调整网格边距，不应隐式改变子图锚点。"""
    fig = Figure(figsize=(12, 8), dpi=100)
    axes = fig.subplots(2, 2).ravel()
    for ax in axes:
        ax.set_aspect("equal")

    panel = SimpleNamespace(section_fig=fig)
    apply_section_grid_spacing(panel, multi=True)

    assert [ax.get_anchor() for ax in axes] == ["C"] * 4


def _assert_first_row_titles_inside_canvas(fig, axes):
    """断言第一行子图标题完整位于画布范围内。"""
    canvas = FigureCanvasAgg(fig)
    canvas.draw()
    renderer = canvas.get_renderer()
    canvas_height = fig.bbox.height
    for ax in axes[0]:
        title_bounds = ax.title.get_window_extent(renderer=renderer)
        assert title_bounds.y0 >= 0
        assert title_bounds.y1 <= canvas_height


def test_section_grid_spacing_keeps_first_row_titles_visible_without_top_alignment():
    """非隧洞多工况居中对齐时，第一行工况标记不应被画布顶部裁切。"""
    fig = Figure(figsize=(12, 10.8), dpi=100)
    axes = fig.subplots(3, 2, squeeze=False)
    for idx, ax in enumerate(axes.ravel()):
        ax.set_xlim(-6, 6)
        ax.set_ylim(-0.5, 3.0)
        ax.set_aspect("equal")
        ax.set_title(f"工况{idx + 1} 梯形\nQ={5 + idx:.2f} m3/s, V=1.20 m/s", fontsize=10)
    panel = SimpleNamespace(section_fig=fig)
    layout = SectionGridLayout(2, 3, 1200, 1080, axis_anchor="C")

    apply_section_grid_spacing(panel, multi=True)
    apply_section_axis_alignment(panel, layout)

    assert [ax.get_anchor() for ax in axes.ravel()] == ["C"] * 6
    _assert_first_row_titles_inside_canvas(fig, axes)


def test_section_grid_spacing_keeps_tunnel_first_row_titles_visible():
    """隧洞高行高多工况顶对齐后，第一行工况标记也不应被裁切。"""
    fig = Figure(figsize=(12, 26), dpi=100)
    axes = fig.subplots(5, 2, squeeze=False)
    for idx, ax in enumerate(axes.ravel()):
        ax.set_xlim(-4, 4)
        ax.set_ylim(-0.5, 6.0)
        ax.set_aspect("equal")
        ax.set_title(
            f"工况 {idx + 1}｜圆拱直墙型\nQ={5 + idx:.2f} m3/s, V=1.20 m/s",
            fontsize=10,
        )
    panel = SimpleNamespace(section_fig=fig)
    layout = SectionGridLayout(2, 5, 1200, 2600, axis_anchor="N")

    apply_section_grid_spacing(panel, multi=True)
    apply_section_axis_alignment(panel, layout)

    _assert_first_row_titles_inside_canvas(fig, axes)


def test_configure_section_grid_canvas_ignores_temporary_narrow_viewport_when_notebook_is_wide():
    """页签未完成布局时，临时窄 viewport 不应让宽屏多工况误退为单列。"""
    canvas = _Canvas()
    canvas.width = lambda: 640
    panel = SimpleNamespace(
        section_fig=Figure(dpi=100),
        section_canvas=canvas,
        notebook=_Widget(1280),
    )
    panel._section_plot_scroll = _Widget(
        640,
        parent=_Widget(1280),
        viewport=_Widget(640),
    )

    layout = configure_section_grid_canvas(panel, 10)

    assert layout.columns == 2
    assert layout.rows == 5
    assert layout.canvas_width_px == 1280


def test_hidden_section_grid_canvas_prefers_parent_width_over_temporary_wide_viewport():
    """断面图页隐藏时，即使 viewport 临时超过阈值，也应按父容器宽度预渲染。"""
    canvas = _Canvas()
    canvas.width = lambda: 640
    notebook = _Notebook(1188)
    notebook.current_index = 0
    notebook.currentIndex = lambda: notebook.current_index
    panel = SimpleNamespace(
        section_fig=Figure(dpi=100),
        section_canvas=canvas,
        notebook=notebook,
    )
    panel._section_plot_scroll = _Widget(
        914,
        parent=notebook,
        viewport=_Widget(900),
    )
    panel._section_plot_tab_index = 1

    layout = configure_section_grid_canvas(
        panel,
        9,
        layout_options=SectionGridOptions(row_height_px=520, axis_anchor="N"),
    )

    assert layout.columns == 2
    assert layout.rows == 5
    assert layout.canvas_width_px == 1188
    assert layout.canvas_height_px == 2600
    assert canvas.resized_to == (1188, 2600)


def test_configure_section_grid_canvas_does_not_use_outer_window_as_fallback_width():
    """隐藏页签回退父宽度时，不应取比断面图区更外层的主窗口宽度。"""
    canvas = _Canvas()
    canvas.width = lambda: 640
    outer_window = _Widget(1600)
    notebook = _Widget(1280, parent=outer_window)
    panel = SimpleNamespace(
        section_fig=Figure(dpi=100),
        section_canvas=canvas,
        notebook=notebook,
    )
    panel._section_plot_scroll = _Widget(
        640,
        parent=notebook,
        viewport=_Widget(640),
    )

    layout = configure_section_grid_canvas(panel, 10)

    assert layout.columns == 2
    assert layout.rows == 5
    assert layout.canvas_width_px == 1280


def test_configure_section_grid_canvas_keeps_one_column_when_all_section_widths_are_narrow():
    """断面图区域确实很窄时，仍应退到单列。"""
    canvas = _Canvas()
    canvas.width = lambda: 620
    panel = SimpleNamespace(
        section_fig=Figure(dpi=100),
        section_canvas=canvas,
        notebook=_Widget(620),
    )
    panel._section_plot_scroll = _Widget(
        620,
        parent=_Widget(620),
        viewport=_Widget(620),
    )

    layout = configure_section_grid_canvas(panel, 5)

    assert layout.columns == 1
    assert layout.rows == 5


def test_configure_section_grid_canvas_prefers_viewport_over_wider_parent():
    """外层窗口更宽时，画布仍应使用断面图可视宽度并复位横向偏移。"""
    canvas = _Canvas()
    canvas.width = lambda: 1600
    horizontal_bar = _ScrollBar(360)
    outer = _Widget(1600)
    notebook = _Widget(1280, parent=outer)
    panel = SimpleNamespace(
        section_fig=Figure(dpi=100),
        section_canvas=canvas,
        notebook=notebook,
    )
    panel._section_plot_scroll = _Widget(
        920,
        parent=notebook,
        viewport=_Widget(900),
        horizontal_bar=horizontal_bar,
    )

    layout = configure_section_grid_canvas(panel, 7)

    assert layout.columns == 2
    assert layout.rows == 4
    assert layout.canvas_width_px == 900
    assert canvas.resized_to == (900, 1440)
    assert horizontal_bar.value == 0
    assert horizontal_bar.values == [0]


def test_connect_section_tab_refresh_redraws_when_section_tab_is_opened():
    """切到断面图页时，应按当前真实宽度重新布局已有多工况图。"""
    signal = _Signal()
    calls = []
    panel = SimpleNamespace(
        notebook=SimpleNamespace(currentChanged=signal),
        _all_results=[object(), object()],
        _update_section_plot_all=lambda: calls.append("redraw"),
    )

    connect_section_tab_refresh(panel, section_tab_index=1)

    signal.emit(0)
    assert calls == []

    signal.emit(1)
    assert calls == ["redraw"]


def test_section_tab_refresh_remeasures_width_and_restores_two_columns():
    """首次隐藏绘图误判单列后，切到断面图页应按真实宽度重排为 2 列。"""
    canvas = _Canvas()
    canvas.width = lambda: 640
    notebook = _Notebook(640)
    viewport = _Widget(640)
    scroll = _Widget(640, parent=notebook, viewport=viewport)
    panel = SimpleNamespace(
        section_fig=Figure(dpi=100),
        section_canvas=canvas,
        notebook=notebook,
        _section_plot_scroll=scroll,
        _all_results=[object()] * 10,
    )

    def redraw():
        configure_section_grid_canvas(panel, 10)

    panel._update_section_plot_all = redraw
    configure_section_grid_canvas(panel, 10)
    assert panel._section_plot_layout.columns == 1

    notebook._width = 1280
    scroll._width = 1280
    viewport._width = 1280
    connect_section_tab_refresh(panel, section_tab_index=1)

    notebook.currentChanged.emit(1)

    assert panel._section_plot_layout.columns == 2
    assert panel._section_plot_layout.rows == 5


def test_hidden_result_page_plot_retries_until_visible_width_stabilizes(monkeypatch):
    """结果页计算后首次打开断面图，若第一次仍读到旧宽度，应继续延迟重排。"""
    canvas = _Canvas()
    canvas.width = lambda: 640
    notebook = _Notebook(900)
    notebook.current_index = 0
    notebook.currentIndex = lambda: notebook.current_index
    viewport = _Widget(900)
    scroll = _Widget(914, parent=notebook, viewport=viewport)
    panel = SimpleNamespace(
        section_fig=Figure(dpi=100),
        section_canvas=canvas,
        notebook=notebook,
        _section_plot_scroll=scroll,
        _all_results=[object()] * 9,
    )
    scheduled = []

    def run_later(delay_ms, callback):
        scheduled.append((delay_ms, callback))

    monkeypatch.setattr(section_plot_layout_mod, "_run_section_plot_refresh_later", run_later)
    connect_section_tab_refresh(panel, section_tab_index=1)

    configure_section_grid_canvas(
        panel,
        9,
        layout_options=SectionGridOptions(row_height_px=520, axis_anchor="N"),
    )
    assert panel._section_plot_layout.canvas_width_px == 900

    calls = []

    def redraw():
        calls.append(viewport.width())
        configure_section_grid_canvas(
            panel,
            9,
            layout_options=SectionGridOptions(row_height_px=520, axis_anchor="N"),
        )

    panel._update_section_plot_all = redraw
    notebook.current_index = 1
    notebook._width = 1188
    notebook.currentChanged.emit(1)

    assert calls == []
    assert scheduled and scheduled[-1][0] == 0

    scheduled[-1][1]()

    assert calls == [900]
    assert panel._section_plot_layout.canvas_width_px == 900
    assert getattr(panel, "_section_plot_needs_visible_refresh") is True
    assert len(scheduled) == 2

    scroll._width = 1202
    viewport._width = 1188
    scheduled[-1][1]()

    assert calls == [900, 1188]
    assert panel._section_plot_layout.columns == 2
    assert panel._section_plot_layout.rows == 5
    assert panel._section_plot_layout.canvas_width_px == 1188
    assert panel._section_plot_layout.canvas_height_px == 2600
    assert getattr(panel, "_section_plot_needs_visible_refresh") is False


def test_hidden_result_page_plot_clears_visible_refresh_when_first_width_is_stable(monkeypatch):
    """隐藏阶段已按真实宽度预渲染时，首次切页不应再完整重画。"""
    canvas = _Canvas()
    canvas.width = lambda: 640
    notebook = _Notebook(1188)
    notebook.current_index = 0
    notebook.currentIndex = lambda: notebook.current_index
    viewport = _Widget(900)
    scroll = _Widget(914, parent=notebook, viewport=viewport)
    panel = SimpleNamespace(
        section_fig=Figure(dpi=100),
        section_canvas=canvas,
        notebook=notebook,
        _section_plot_scroll=scroll,
        _all_results=[object()] * 6,
    )
    scheduled = []

    def run_later(delay_ms, callback):
        scheduled.append((delay_ms, callback))

    monkeypatch.setattr(section_plot_layout_mod, "_run_section_plot_refresh_later", run_later)
    connect_section_tab_refresh(panel, section_tab_index=1)

    configure_section_grid_canvas(
        panel,
        6,
        layout_options=SectionGridOptions(row_height_px=520, axis_anchor="N"),
    )
    assert panel._section_plot_layout.canvas_width_px == 1188
    assert getattr(panel, "_section_plot_needs_visible_refresh") is True

    calls = []

    def redraw():
        calls.append(viewport.width())
        configure_section_grid_canvas(
            panel,
            6,
            layout_options=SectionGridOptions(row_height_px=520, axis_anchor="N"),
        )

    panel._update_section_plot_all = redraw
    notebook.current_index = 1
    scroll._width = 1202
    viewport._width = 1188
    notebook.currentChanged.emit(1)

    assert scheduled == []
    assert calls == []
    assert panel._section_plot_layout.columns == 2
    assert panel._section_plot_layout.rows == 3
    assert panel._section_plot_layout.canvas_width_px == 1188
    assert panel._section_plot_layout.canvas_height_px == 1560
    assert getattr(panel, "_section_plot_needs_visible_refresh") is False


def test_section_tab_refresh_from_comparison_uses_visible_viewport_width():
    """从工况对比切回断面图时，不应取外层窗口宽度导致横向裁切。"""
    canvas = _Canvas()
    canvas.width = lambda: 1600
    horizontal_bar = _ScrollBar(240)
    outer = _Widget(1600)
    notebook = _Notebook(1280)
    notebook._parent = outer
    viewport = _Widget(900)
    scroll = _Widget(920, parent=notebook, viewport=viewport, horizontal_bar=horizontal_bar)
    calls = []
    panel = SimpleNamespace(
        section_fig=Figure(dpi=100),
        section_canvas=canvas,
        notebook=notebook,
        _section_plot_scroll=scroll,
        _all_results=[object()] * 7,
    )

    def redraw():
        calls.append("redraw")
        configure_section_grid_canvas(panel, 7)

    panel._update_section_plot_all = redraw
    connect_section_tab_refresh(panel, section_tab_index=1)

    notebook.currentChanged.emit(2)
    assert calls == []

    notebook.currentChanged.emit(1)

    assert calls == ["redraw"]
    assert panel._section_plot_layout.columns == 2
    assert panel._section_plot_layout.canvas_width_px == 900
    assert canvas.resized_to == (900, 1440)
    assert horizontal_bar.value == 0


def test_visible_section_viewport_resize_forces_relayout_without_horizontal_overflow():
    """停留在断面图页缩窄窗口时，应重新按 viewport 宽度绘制而不是裁切右侧。"""
    app = _get_qapp()
    canvas = QWidget()
    scroll = create_section_plot_scroll_area(canvas)
    host = QWidget()
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(scroll)
    notebook = SimpleNamespace(currentChanged=_Signal(), currentIndex=lambda: 1)
    calls = []
    panel = SimpleNamespace(
        section_fig=Figure(dpi=100),
        section_canvas=canvas,
        notebook=notebook,
        _section_plot_scroll=scroll,
        _all_results=[object()] * 10,
    )

    def redraw():
        calls.append(scroll.viewport().width())
        configure_section_grid_canvas(panel, 10)

    panel._update_section_plot_all = redraw
    host.resize(1280, 720)
    host.show()
    app.processEvents()
    configure_section_grid_canvas(panel, 10, available_width_px=1280)
    assert canvas.width() == 1280

    connect_section_tab_refresh(panel, section_tab_index=1)
    host.resize(650, 720)
    for _ in range(4):
        app.processEvents()

    assert calls
    assert canvas.width() <= scroll.viewport().width()
    assert scroll.horizontalScrollBar().maximum() == 0

    host.close()
    host.deleteLater()
    canvas.deleteLater()


def test_section_tab_refresh_keeps_existing_layout_when_viewport_width_jitters():
    """断面图已正确显示后，切页回来不应因临时较小宽度重画变小。"""
    canvas = _Canvas()
    horizontal_bar = _ScrollBar(0)
    notebook = _Notebook(1280)
    viewport = _Widget(1280)
    scroll = _Widget(1280, parent=notebook, viewport=viewport, horizontal_bar=horizontal_bar)
    calls = []
    panel = SimpleNamespace(
        section_fig=Figure(dpi=100),
        section_canvas=canvas,
        notebook=notebook,
        _section_plot_scroll=scroll,
        _all_results=[object()] * 10,
    )

    configure_section_grid_canvas(panel, 10)
    assert panel._section_plot_layout.canvas_width_px == 1280
    assert canvas.resized_to == (1280, 1800)

    viewport._width = 900
    scroll._width = 920
    horizontal_bar.value = 240
    horizontal_bar.values.clear()

    def redraw():
        calls.append("redraw")
        configure_section_grid_canvas(panel, 10)

    panel._update_section_plot_all = redraw
    connect_section_tab_refresh(panel, section_tab_index=1)

    notebook.currentChanged.emit(2)
    notebook.currentChanged.emit(1)

    assert calls == []
    assert panel._section_plot_layout.canvas_width_px == 1280
    assert canvas.resized_to == (1280, 1800)
    assert horizontal_bar.value == 0
    assert horizontal_bar.values == [0]


def test_section_tab_refresh_counts_only_successful_dict_results():
    """隧洞字典型结果里失败工况不应触发稳定布局重画。"""
    canvas = _Canvas()
    horizontal_bar = _ScrollBar(180)
    notebook = _Notebook(1280)
    viewport = _Widget(1280)
    scroll = _Widget(1280, parent=notebook, viewport=viewport, horizontal_bar=horizontal_bar)
    calls = []
    panel = SimpleNamespace(
        section_fig=Figure(dpi=100),
        section_canvas=canvas,
        notebook=notebook,
        _section_plot_scroll=scroll,
        _section_plot_tab_index=1,
        _all_results=[
            {"result": {"success": True}},
            {"result": {"success": False}},
            {"result": {"success": True}},
        ],
        _update_section_plot_all=lambda: calls.append("redraw"),
    )

    configure_section_grid_canvas(panel, 2)

    handled = refresh_section_plot_when_visible(panel, 1)

    assert handled is True
    assert calls == []
    assert horizontal_bar.value == 0


def test_schedule_section_plot_restore_refresh_defers_for_current_section_tab(monkeypatch):
    """项目恢复完成后，应延迟按当前断面图页强制刷新一次。"""
    scheduled_delays = []
    redraws = []

    def run_later(delay_ms, callback):
        scheduled_delays.append(delay_ms)
        callback()

    monkeypatch.setattr(section_plot_layout_mod, "_run_section_plot_refresh_later", run_later)
    panel = SimpleNamespace(
        _all_results=[object()] * 10,
        _section_plot_tab_index=1,
        _update_section_plot_all=lambda: redraws.append("redraw"),
    )

    handled = schedule_section_plot_restore_refresh(panel)

    assert handled is True
    assert scheduled_delays == [0]
    assert redraws == ["redraw"]


def test_section_tab_refresh_uses_explicit_tab_index():
    """刷新钩子应使用 addTab 返回的真实断面图页索引。"""
    signal = _Signal()
    calls = []
    panel = SimpleNamespace(
        notebook=SimpleNamespace(currentChanged=signal),
        _all_results=[object()],
        _update_section_plot_all=lambda: calls.append("redraw"),
    )

    connect_section_tab_refresh(panel, section_tab_index=2)

    signal.emit(1)
    assert calls == []

    signal.emit(2)
    assert calls == ["redraw"]


def test_double_click_uses_registered_axis_payload(monkeypatch):
    """双击子图时，应按坐标轴找到对应工况并打开大图。"""
    fig = Figure()
    ax = fig.subplots()
    opened = []
    panel = SimpleNamespace()

    def draw(_ax):
        return None

    register_section_axis_dialog(panel, ax, "工况 3｜圆拱直墙型", draw)

    def fake_show(parent, title, draw_func):
        opened.append((parent, title, draw_func))

    monkeypatch.setattr(
        "app_渠系计算前端.section_plot_layout.show_section_plot_dialog",
        fake_show,
    )

    handled = handle_section_plot_double_click(
        panel,
        SimpleNamespace(dblclick=True, inaxes=ax),
    )

    assert handled is True
    assert opened == [(panel, "工况 3｜圆拱直墙型", draw)]
