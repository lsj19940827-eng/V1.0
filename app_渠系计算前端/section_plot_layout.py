# -*- coding: utf-8 -*-
"""多工况断面图滚动布局、画布尺寸和双击放大工具。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


_DEFAULT_WIDTH_PX = 1200
_FIG_DPI = 100
_ROW_HEIGHT_PX = 360
_MIN_HEIGHT_PX = 600
_ONE_COLUMN_MAX_WIDTH_PX = 700
_VISIBLE_REFRESH_RETRY_DELAY_MS = 40
_VISIBLE_REFRESH_MAX_RETRIES = 5
_VISIBLE_REFRESH_WIDTH_TOLERANCE_PX = 8
_VISIBLE_REFRESH_PARENT_GAP_PX = 32


@dataclass(frozen=True)
class SectionGridOptions:
    """记录多工况断面图的可选展示策略。"""

    row_height_px: int | None = None
    axis_anchor: str = "C"


@dataclass(frozen=True)
class SectionGridLayout:
    """记录多工况断面图网格布局和画布尺寸。"""

    columns: int
    rows: int
    canvas_width_px: int
    canvas_height_px: int
    axis_anchor: str = "C"


@dataclass(frozen=True)
class SectionAxisDialogPayload:
    """记录子图双击放大所需的重绘信息。"""

    title: str
    draw_func: Callable


def choose_section_grid_layout(
    case_count: int,
    available_width_px: int | None = None,
    *,
    row_height_px: int | None = None,
    layout_options: SectionGridOptions | None = None,
) -> SectionGridLayout:
    """按工况数和可用宽度决定断面图列数、行数和画布高度。"""
    options = layout_options or SectionGridOptions(row_height_px=row_height_px)
    effective_row_height = row_height_px if row_height_px is not None else options.row_height_px
    count = max(int(case_count or 0), 1)
    width = int(available_width_px or 0)
    if width <= 0:
        width = _DEFAULT_WIDTH_PX
    row_height = max(int(effective_row_height or _ROW_HEIGHT_PX), _ROW_HEIGHT_PX)
    axis_anchor = str(options.axis_anchor or "C").strip().upper() or "C"

    if count == 1 or width < _ONE_COLUMN_MAX_WIDTH_PX:
        columns = 1
    else:
        columns = min(count, 2)

    rows = (count + columns - 1) // columns
    height = max(_MIN_HEIGHT_PX, rows * row_height)
    return SectionGridLayout(columns, rows, width, height, axis_anchor=axis_anchor)


def _read_widget_width(widget) -> int | None:
    """安全读取控件宽度。"""
    if widget is None:
        return None
    width_getter = getattr(widget, "width", None)
    if callable(width_getter):
        try:
            width = int(width_getter())
            if width > 0:
                return width
        except Exception:
            return None
    return None


def _widget_viewport(widget):
    """安全读取滚动控件的 viewport。"""
    viewport_getter = getattr(widget, "viewport", None)
    if callable(viewport_getter):
        try:
            return viewport_getter()
        except Exception:
            return None
    return None


def _parent_widget(widget):
    """安全读取父控件。"""
    parent_getter = getattr(widget, "parentWidget", None)
    if callable(parent_getter):
        try:
            return parent_getter()
        except Exception:
            return None
    return None


def _widget_visible(widget) -> bool | None:
    """安全读取控件是否可见，无法判断时返回 None。"""
    visible_getter = getattr(widget, "isVisible", None)
    if callable(visible_getter):
        try:
            return bool(visible_getter())
        except Exception:
            return None
    return None


def _append_widget_widths(widths: list[int], widget) -> None:
    """把控件和 viewport 宽度加入候选列表。"""
    width = _read_widget_width(widget)
    if width is not None:
        widths.append(width)
    viewport_width = _read_widget_width(_widget_viewport(widget))
    if viewport_width is not None:
        widths.append(viewport_width)


def _append_parent_widths(widths: list[int], widget, *, limit: int = 6) -> None:
    """沿父控件链收集容器宽度，避免隐藏页签只读到临时小画布。"""
    seen: set[int] = set()
    current = _parent_widget(widget)
    depth = 0
    while current is not None and depth < limit:
        ident = id(current)
        if ident in seen:
            break
        seen.add(ident)
        _append_widget_widths(widths, current)
        current = _parent_widget(current)
        depth += 1


def _best_width(widths: list[int]) -> int | None:
    """按采集优先级选出可信宽度，避免误取更外层主窗口宽度。"""
    valid = [width for width in widths if width > 0]
    if not valid:
        return None
    for width in valid:
        if width >= _ONE_COLUMN_MAX_WIDTH_PX:
            return width
    return max(valid)


def _fallback_section_container_width(panel) -> int | None:
    """读取断面图所在输出区的父级宽度，用于识别切页瞬间的 viewport 抖动。"""
    container_widths: list[int] = []
    scroll = getattr(panel, "_section_plot_scroll", None)
    _append_parent_widths(container_widths, scroll)

    notebook = getattr(panel, "notebook", None)
    _append_widget_widths(container_widths, notebook)
    current_widget_getter = getattr(notebook, "currentWidget", None)
    if callable(current_widget_getter):
        try:
            _append_widget_widths(container_widths, current_widget_getter())
        except Exception:
            pass

    canvas = getattr(panel, "section_canvas", None)
    _append_parent_widths(container_widths, canvas)
    return _best_width(container_widths)


def _available_section_width(panel) -> int:
    """读取断面图区域宽度，未显示时回退到稳定默认值。"""
    scroll = getattr(panel, "_section_plot_scroll", None)
    viewport_width = _read_widget_width(_widget_viewport(scroll))
    scroll_width = _read_widget_width(scroll)
    scroll_visible = _widget_visible(scroll)
    section_tab_index = getattr(panel, "_section_plot_tab_index", 1)
    section_visible = _section_tab_is_visible(panel, section_tab_index)
    best_container_width = _fallback_section_container_width(panel)

    if not section_visible:
        if best_container_width is not None:
            return best_container_width
        if scroll_width is not None:
            return scroll_width
        if viewport_width is not None:
            return viewport_width

    # 已经显示的断面图页以 viewport 为准；隐藏页签读到的临时小宽度才允许回退父容器。
    if viewport_width is not None and (
        viewport_width >= _ONE_COLUMN_MAX_WIDTH_PX or scroll_visible is True
    ):
        return viewport_width
    if scroll_width is not None and (
        scroll_width >= _ONE_COLUMN_MAX_WIDTH_PX or scroll_visible is True
    ):
        return scroll_width

    canvas = getattr(panel, "section_canvas", None)
    if best_container_width is not None:
        return best_container_width

    if viewport_width is not None:
        return viewport_width
    if scroll_width is not None:
        return scroll_width

    canvas_width = _read_widget_width(canvas)
    if canvas_width is not None:
        return canvas_width

    panel_width = _read_widget_width(panel)
    if panel_width is not None:
        return panel_width
    return _DEFAULT_WIDTH_PX


def _section_success_case_count(panel) -> int:
    """统计当前断面图应显示的成功工况数量。"""
    all_results = getattr(panel, "_all_results", None) or []
    count = 0
    for item in all_results:
        result = None
        if isinstance(item, dict):
            result = item.get("result")
        if isinstance(item, tuple) and len(item) >= 3:
            result = item[2]
        if isinstance(result, dict):
            if result.get("success"):
                count += 1
        else:
            count += 1
    return max(count, 1)


def _reset_section_horizontal_scroll(panel) -> None:
    """复位断面图横向滚动，避免切页后保留旧偏移。"""
    scroll = getattr(panel, "_section_plot_scroll", None)
    horizontal_bar_getter = getattr(scroll, "horizontalScrollBar", None)
    if callable(horizontal_bar_getter):
        try:
            horizontal_bar = horizontal_bar_getter()
            setter = getattr(horizontal_bar, "setValue", None)
            if callable(setter):
                setter(0)
        except Exception:
            pass


def _force_section_scroll_repaint(scroll, canvas=None) -> None:
    """滚动断面图时同步刷新画布和视口，避免旧像素残留。"""
    widgets = []
    if canvas is not None:
        widgets.append(canvas)
    viewport = _widget_viewport(scroll)
    if viewport is not None:
        widgets.append(viewport)

    for widget in widgets:
        for method_name in ("update", "repaint"):
            method = getattr(widget, method_name, None)
            if callable(method):
                try:
                    method()
                except Exception:
                    pass


def _apply_section_canvas_size(panel, layout: SectionGridLayout) -> None:
    """把断面图布局尺寸应用到 Figure 和 Qt 画布。"""
    fig = getattr(panel, "section_fig", None)
    canvas = getattr(panel, "section_canvas", None)

    if fig is not None:
        dpi = getattr(fig, "dpi", _FIG_DPI) or _FIG_DPI
        fig.set_size_inches(layout.canvas_width_px / dpi, layout.canvas_height_px / dpi, forward=True)
    if canvas is None:
        return
    if hasattr(canvas, "setMinimumHeight"):
        canvas.setMinimumHeight(layout.canvas_height_px)
    if hasattr(canvas, "resize"):
        try:
            canvas.resize(layout.canvas_width_px, layout.canvas_height_px)
        except TypeError:
            pass


def apply_section_axis_alignment(
    panel,
    layout: SectionGridLayout | None = None,
    *,
    axis_anchor: str | None = None,
) -> None:
    """按布局配置调整所有子图在网格单元内的停靠位置。"""
    anchor = axis_anchor
    if anchor is None and layout is not None:
        anchor = layout.axis_anchor
    if anchor is None:
        anchor = getattr(panel, "_section_plot_axis_anchor", "C")
    anchor = str(anchor or "C").strip().upper() or "C"

    fig = getattr(panel, "section_fig", None)
    axes = getattr(fig, "axes", []) if fig is not None else []
    for ax in axes:
        setter = getattr(ax, "set_anchor", None)
        if callable(setter):
            try:
                setter(anchor)
            except Exception:
                pass


def apply_section_grid_spacing(
    panel,
    *,
    multi: bool = True,
    hspace: float | None = None,
    wspace: float | None = None,
) -> None:
    """为断面图子图标题预留稳定边距，避免顶对齐后标题被裁切。"""
    fig = getattr(panel, "section_fig", None)
    adjust = getattr(fig, "subplots_adjust", None)
    if not callable(adjust):
        return
    try:
        if multi:
            effective_hspace = 0.42 if hspace is None else float(hspace)
            effective_wspace = 0.24 if wspace is None else float(wspace)
            adjust(
                left=0.07,
                right=0.94,
                top=0.92,
                bottom=0.07,
                hspace=effective_hspace,
                wspace=effective_wspace,
            )
        else:
            adjust(
                left=0.08,
                right=0.92,
                top=0.90,
                bottom=0.10,
            )
    except Exception:
        pass


def _connect_section_scroll_repaint(scroll, canvas) -> None:
    """连接纵向滚动刷新，降低 Qt 滚动缓存导致的残影风险。"""
    if scroll is None or canvas is None:
        return
    if getattr(scroll, "_section_plot_repaint_connected", False):
        return
    vertical_bar_getter = getattr(scroll, "verticalScrollBar", None)
    if not callable(vertical_bar_getter):
        return
    try:
        vertical_bar = vertical_bar_getter()
    except Exception:
        return

    def _refresh(_value=None):
        _force_section_scroll_repaint(scroll, canvas)

    for signal_name in ("valueChanged", "sliderMoved", "actionTriggered"):
        signal = getattr(vertical_bar, signal_name, None)
        connector = getattr(signal, "connect", None)
        if callable(connector):
            try:
                connector(_refresh)
            except Exception:
                pass
    setattr(scroll, "_section_plot_repaint_connected", True)


def _can_keep_existing_section_layout(panel, case_count: int) -> bool:
    """切页回来时，已有稳定布局且列数不变则保持原图，避免临时宽度导致缩放。"""
    layout = getattr(panel, "_section_plot_layout", None)
    if not isinstance(layout, SectionGridLayout):
        return False

    normalized_count = max(int(case_count or 0), 1)
    layout_count = getattr(panel, "_section_plot_layout_case_count", None)
    if layout_count is not None and int(layout_count) != normalized_count:
        return False

    current_width = _available_section_width(panel)
    current_layout = choose_section_grid_layout(normalized_count, current_width)
    if current_layout.columns != layout.columns:
        return False
    if current_layout.canvas_width_px >= layout.canvas_width_px:
        return current_layout.canvas_width_px == layout.canvas_width_px

    container_width = _fallback_section_container_width(panel)
    return container_width is not None and container_width >= layout.canvas_width_px


def _section_tab_is_visible(panel, section_tab_index: int) -> bool:
    """判断断面图页当前是否可见，无法读取时按可刷新处理。"""
    notebook = getattr(panel, "notebook", None)
    current_getter = getattr(notebook, "currentIndex", None)
    if not callable(current_getter):
        return True
    try:
        return int(current_getter()) == int(section_tab_index)
    except Exception:
        return True


def _run_pending_section_resize_refresh(panel) -> None:
    """执行一次由 viewport resize 触发的延迟重排。"""
    setattr(panel, "_section_plot_resize_refresh_pending", False)
    section_tab_index = getattr(panel, "_section_plot_tab_index", 1)
    refreshed = refresh_section_plot_when_visible(panel, section_tab_index, force=True)
    if refreshed and _section_visible_refresh_is_stable(panel):
        _finish_section_visible_refresh(panel)


def _mark_section_plot_needs_visible_refresh_if_hidden(panel) -> None:
    """隐藏页签内绘图后标记一次可见刷新，避免首次显示沿用临时尺寸。"""
    section_tab_index = getattr(panel, "_section_plot_tab_index", 1)
    if not _section_tab_is_visible(panel, section_tab_index):
        setattr(panel, "_section_plot_needs_visible_refresh", True)
        setattr(panel, "_section_plot_visible_refresh_retries", 0)


def _install_section_viewport_resize_refresh(panel) -> None:
    """监听断面图 viewport 尺寸变化，停留在断面图页时同步重排。"""
    if getattr(panel, "_section_plot_resize_refresh_connected", False):
        return
    scroll = getattr(panel, "_section_plot_scroll", None)
    viewport = _widget_viewport(scroll)
    installer = getattr(viewport, "installEventFilter", None)
    if not callable(installer):
        return
    try:
        from PySide6.QtCore import QEvent, QObject, QTimer
    except Exception:
        return

    class _ResizeFilter(QObject):
        """转发 viewport resize 事件，延迟到本轮布局稳定后重画。"""

        def __init__(self, owner):
            super().__init__(viewport)
            self._owner = owner

        def eventFilter(self, obj, event):
            try:
                if event.type() == QEvent.Resize:
                    section_tab_index = getattr(self._owner, "_section_plot_tab_index", 1)
                    if _section_tab_is_visible(self._owner, section_tab_index):
                        if not getattr(self._owner, "_section_plot_resize_refresh_pending", False):
                            setattr(self._owner, "_section_plot_resize_refresh_pending", True)
                            QTimer.singleShot(
                                0,
                                lambda owner=self._owner: _run_pending_section_resize_refresh(owner),
                            )
            except Exception:
                pass
            return False

    resize_filter = _ResizeFilter(panel)
    try:
        installer(resize_filter)
    except Exception:
        return
    setattr(panel, "_section_plot_resize_filter", resize_filter)
    setattr(panel, "_section_plot_resize_refresh_connected", True)


def refresh_section_plot_when_visible(panel, current_index: int | None = None, *, force: bool = False) -> bool:
    """断面图页显示时，按当前真实宽度重新绘制已有工况断面图。"""
    section_tab_index = getattr(panel, "_section_plot_tab_index", 1)
    if current_index is not None and int(current_index) != section_tab_index:
        return False
    if getattr(panel, "_section_plot_refreshing", False):
        return False
    if not getattr(panel, "_all_results", None):
        return False
    updater = getattr(panel, "_update_section_plot_all", None)
    if not callable(updater):
        return False
    case_count = _section_success_case_count(panel)
    if not force and _can_keep_existing_section_layout(panel, case_count):
        _reset_section_horizontal_scroll(panel)
        _force_section_scroll_repaint(
            getattr(panel, "_section_plot_scroll", None),
            getattr(panel, "section_canvas", None),
        )
        return True
    setattr(panel, "_section_plot_refreshing", True)
    try:
        updater()
    finally:
        setattr(panel, "_section_plot_refreshing", False)
    return True


def _visible_section_widths(panel) -> tuple[int | None, int | None, int | None]:
    """读取可见断面图的 viewport、滚动区和父容器宽度。"""
    scroll = getattr(panel, "_section_plot_scroll", None)
    viewport_width = _read_widget_width(_widget_viewport(scroll))
    scroll_width = _read_widget_width(scroll)
    container_width = _fallback_section_container_width(panel)
    return viewport_width, scroll_width, container_width


def _expected_visible_section_width(panel) -> int | None:
    """判断首次可见刷新应等待的目标宽度。"""
    viewport_width, scroll_width, container_width = _visible_section_widths(panel)
    if viewport_width is not None:
        if (
            container_width is not None
            and container_width > viewport_width + _VISIBLE_REFRESH_PARENT_GAP_PX
        ):
            return container_width
        return viewport_width
    if scroll_width is not None:
        if (
            container_width is not None
            and container_width > scroll_width + _VISIBLE_REFRESH_PARENT_GAP_PX
        ):
            return container_width
        return scroll_width
    return container_width


def _section_visible_refresh_is_stable(panel) -> bool:
    """判断画布宽度是否已经追上断面图首次可见后的真实区域宽度。"""
    layout = getattr(panel, "_section_plot_layout", None)
    layout_width = getattr(layout, "canvas_width_px", None)
    expected_width = _expected_visible_section_width(panel)
    if layout_width is None or expected_width is None:
        return True
    return int(layout_width) >= int(expected_width) - _VISIBLE_REFRESH_WIDTH_TOLERANCE_PX


def _section_visible_viewport_has_caught_up(panel) -> bool:
    """判断当前 viewport 是否已经追上预渲染画布宽度。"""
    layout = getattr(panel, "_section_plot_layout", None)
    layout_width = getattr(layout, "canvas_width_px", None)
    viewport_width, _, expected_width = _visible_section_widths(panel)
    if layout_width is None or viewport_width is None:
        return True
    target_width = expected_width if expected_width is not None else layout_width
    required_width = min(int(layout_width), int(target_width))
    return int(viewport_width) >= required_width - _VISIBLE_REFRESH_WIDTH_TOLERANCE_PX


def _section_visible_refresh_is_ready(panel) -> bool:
    """判断首次可见刷新是否已可直接收口，无需完整重画。"""
    return _section_visible_refresh_is_stable(panel) and _section_visible_viewport_has_caught_up(panel)


def _finish_section_visible_refresh(panel) -> None:
    """清除断面图首次可见刷新状态。"""
    setattr(panel, "_section_plot_needs_visible_refresh", False)
    setattr(panel, "_section_plot_visible_refresh_retries", 0)


def _repaint_existing_section_plot(panel) -> None:
    """复用已预渲染断面图，只刷新滚动区显示。"""
    _reset_section_horizontal_scroll(panel)
    _force_section_scroll_repaint(
        getattr(panel, "_section_plot_scroll", None),
        getattr(panel, "section_canvas", None),
    )


def _queue_section_tab_refresh(panel, section_tab_index: int, delay_ms: int) -> bool:
    """安排一次断面图页签延迟刷新，避免同一轮重复排队。"""
    if getattr(panel, "_section_plot_tab_refresh_pending", False):
        return True
    setattr(panel, "_section_plot_tab_refresh_pending", True)
    _run_section_plot_refresh_later(
        delay_ms,
        lambda owner=panel, tab_index=section_tab_index: _run_pending_section_tab_refresh(
            owner,
            tab_index,
        ),
    )
    return True


def _run_pending_section_tab_refresh(panel, section_tab_index: int) -> None:
    """执行一次由页签进入触发的延迟重排。"""
    setattr(panel, "_section_plot_tab_refresh_pending", False)
    current_index = _current_notebook_index(panel)
    if int(current_index) != int(section_tab_index):
        return
    force = bool(getattr(panel, "_section_plot_needs_visible_refresh", False))
    if force and _section_visible_refresh_is_stable(panel) and not _section_visible_viewport_has_caught_up(panel):
        retries = int(getattr(panel, "_section_plot_visible_refresh_retries", 0)) + 1
        setattr(panel, "_section_plot_visible_refresh_retries", retries)
        if retries >= _VISIBLE_REFRESH_MAX_RETRIES:
            _finish_section_visible_refresh(panel)
            _repaint_existing_section_plot(panel)
            return
        _queue_section_tab_refresh(panel, section_tab_index, _VISIBLE_REFRESH_RETRY_DELAY_MS)
        return

    refreshed = refresh_section_plot_when_visible(panel, current_index, force=force)
    if not force:
        return
    if not refreshed:
        _finish_section_visible_refresh(panel)
        return

    if _section_visible_refresh_is_ready(panel):
        _finish_section_visible_refresh(panel)
        return

    retries = int(getattr(panel, "_section_plot_visible_refresh_retries", 0)) + 1
    setattr(panel, "_section_plot_visible_refresh_retries", retries)
    if retries >= _VISIBLE_REFRESH_MAX_RETRIES:
        _finish_section_visible_refresh(panel)
        return

    setattr(panel, "_section_plot_needs_visible_refresh", True)
    _queue_section_tab_refresh(panel, section_tab_index, _VISIBLE_REFRESH_RETRY_DELAY_MS)


def _current_notebook_index(panel) -> int:
    """读取当前页签索引，无法读取时默认断面图页。"""
    notebook = getattr(panel, "notebook", None)
    current_getter = getattr(notebook, "currentIndex", None)
    if callable(current_getter):
        try:
            return int(current_getter())
        except Exception:
            pass
    return int(getattr(panel, "_section_plot_tab_index", 1))


def _run_section_plot_refresh_later(delay_ms: int, callback: Callable) -> None:
    """在 Qt 布局稳定后执行断面图刷新，测试中可替换该调度器。"""
    try:
        from PySide6.QtCore import QTimer
    except Exception:
        callback()
        return
    QTimer.singleShot(delay_ms, callback)


def _schedule_section_tab_refresh(panel, current_index: int | None) -> bool:
    """进入断面图页时按需要延迟强制刷新。"""
    section_tab_index = getattr(panel, "_section_plot_tab_index", 1)
    if current_index is not None and int(current_index) != int(section_tab_index):
        return False
    if getattr(panel, "_section_plot_needs_visible_refresh", False):
        if _section_visible_refresh_is_ready(panel):
            _finish_section_visible_refresh(panel)
            _repaint_existing_section_plot(panel)
            return True
        return _queue_section_tab_refresh(panel, section_tab_index, 0)
    return refresh_section_plot_when_visible(panel, current_index)


def schedule_section_plot_restore_refresh(panel) -> bool:
    """项目恢复完成后，延迟按最终可视宽度重排当前断面图页。"""
    if not getattr(panel, "_all_results", None):
        return False

    def _refresh_after_restore():
        refresh_section_plot_when_visible(panel, _current_notebook_index(panel), force=True)

    _run_section_plot_refresh_later(0, _refresh_after_restore)
    return True


def connect_section_tab_refresh(panel, section_tab_index: int = 1) -> None:
    """连接页签切换事件，进入断面图页时重新按真实宽度布局。"""
    if getattr(panel, "_section_plot_tab_refresh_connected", False):
        return
    notebook = getattr(panel, "notebook", None)
    signal = getattr(notebook, "currentChanged", None)
    connector = getattr(signal, "connect", None)
    if not callable(connector):
        return
    setattr(panel, "_section_plot_tab_index", section_tab_index)
    connector(lambda index: _schedule_section_tab_refresh(panel, index))
    _install_section_viewport_resize_refresh(panel)
    setattr(panel, "_section_plot_tab_refresh_connected", True)


def configure_section_grid_canvas(
    panel,
    case_count: int,
    available_width_px: int | None = None,
    *,
    row_height_px: int | None = None,
    layout_options: SectionGridOptions | None = None,
) -> SectionGridLayout:
    """调整 Matplotlib 画布高度，让多行断面图由滚动区承载。"""
    width = int(available_width_px or _available_section_width(panel))
    layout = choose_section_grid_layout(
        case_count,
        width,
        row_height_px=row_height_px,
        layout_options=layout_options,
    )
    canvas = getattr(panel, "section_canvas", None)

    _apply_section_canvas_size(panel, layout)
    _reset_section_horizontal_scroll(panel)
    _force_section_scroll_repaint(getattr(panel, "_section_plot_scroll", None), canvas)
    setattr(panel, "_section_plot_layout", layout)
    setattr(panel, "_section_plot_layout_case_count", max(int(case_count or 0), 1))
    setattr(panel, "_section_plot_axis_anchor", layout.axis_anchor)
    _mark_section_plot_needs_visible_refresh_if_hidden(panel)
    return layout


def clear_section_plot_state(panel) -> None:
    """清空断面图画布、子图交互映射和滚动布局状态。"""
    fig = getattr(panel, "section_fig", None)
    clear = getattr(fig, "clear", None)
    if callable(clear):
        try:
            clear()
        except Exception:
            pass

    reset_section_axis_dialogs(panel)
    default_layout = choose_section_grid_layout(1, _available_section_width(panel))
    _apply_section_canvas_size(panel, default_layout)
    setattr(panel, "_section_plot_layout", None)
    setattr(panel, "_section_plot_layout_case_count", None)
    _reset_section_horizontal_scroll(panel)

    canvas = getattr(panel, "section_canvas", None)
    draw = getattr(canvas, "draw", None)
    if callable(draw):
        try:
            draw()
        except Exception:
            pass
    _force_section_scroll_repaint(getattr(panel, "_section_plot_scroll", None), canvas)


def create_section_plot_scroll_area(canvas):
    """创建只承载断面图画布的滚动区。"""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QScrollArea

    scroll = QScrollArea()
    scroll.setWidgetResizable(False)
    scroll.setFrameShape(QScrollArea.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll.setStyleSheet("QScrollArea{border:none;background:#FFFFFF;}")
    viewport = scroll.viewport()
    if viewport is not None:
        viewport.setAutoFillBackground(True)
        viewport.setAttribute(Qt.WA_StaticContents, False)
    if hasattr(canvas, "setAttribute"):
        canvas.setAttribute(Qt.WA_StaticContents, False)
    scroll.setWidget(canvas)
    _connect_section_scroll_repaint(scroll, canvas)
    return scroll


def reset_section_axis_dialogs(panel) -> None:
    """清空当前断面图子图与放大弹窗的映射。"""
    setattr(panel, "_section_axis_dialogs", {})


def register_section_axis_dialog(panel, ax, title: str, draw_func: Callable) -> None:
    """登记一个子图，供双击时重绘为大图。"""
    payloads = getattr(panel, "_section_axis_dialogs", None)
    if not isinstance(payloads, dict):
        payloads = {}
        setattr(panel, "_section_axis_dialogs", payloads)
    payloads[ax] = SectionAxisDialogPayload(title=title, draw_func=draw_func)


def handle_section_plot_double_click(panel, event) -> bool:
    """处理 Matplotlib 双击事件，命中子图时弹出该工况大图。"""
    if not getattr(event, "dblclick", False):
        return False
    ax = getattr(event, "inaxes", None)
    if ax is None:
        return False
    payload = getattr(panel, "_section_axis_dialogs", {}).get(ax)
    if payload is None:
        return False
    show_section_plot_dialog(panel, payload.title, payload.draw_func)
    return True


def connect_section_plot_double_click(panel) -> None:
    """为断面图画布连接一次双击放大事件。"""
    canvas = getattr(panel, "section_canvas", None)
    if canvas is None or getattr(panel, "_section_plot_double_click_cid", None) is not None:
        return
    connector = getattr(canvas, "mpl_connect", None)
    if not callable(connector):
        return
    cid = connector("button_press_event", lambda event: handle_section_plot_double_click(panel, event))
    setattr(panel, "_section_plot_double_click_cid", cid)


def show_section_plot_dialog(parent, title: str, draw_func: Callable) -> None:
    """打开单个工况的大图查看窗口。"""
    from PySide6.QtWidgets import QDialog, QVBoxLayout
    from matplotlib.figure import Figure

    try:
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
        from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavToolbar
    except ImportError:
        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
        from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavToolbar

    dialog = QDialog(parent if hasattr(parent, "window") else None)
    dialog.setWindowTitle(f"断面图 - {title}")
    layout = QVBoxLayout(dialog)
    fig = Figure(figsize=(8, 6), dpi=_FIG_DPI)
    canvas = FigureCanvas(fig)
    toolbar = NavToolbar(canvas, dialog)
    layout.addWidget(toolbar)
    layout.addWidget(canvas)
    ax = fig.subplots()
    draw_func(ax)
    fig.tight_layout()
    canvas.draw()
    dialog.resize(920, 720)
    dialog.exec()
