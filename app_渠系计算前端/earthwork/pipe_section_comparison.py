"""Switch between the source drawing and the parameterized pipe section."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRectF, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QPushButton, QStackedWidget, QTabBar, QToolButton, QVBoxLayout, QWidget,
)

from 土石方计算.services.section_scheme_catalog import section_scheme_catalog_path

from .parameter_section_view import ParameterSectionView
from .pipe_standard_drawing_details import pipe_standard_drawing_source, pipe_standard_drawing_variants
from .section_scheme_view import SectionSchemeView


STANDARD_DRAWING_TITLE = "亭子口二期标准横断面图"


def _drawing_focus(renderer, bounds):
    """Frame the drawing's main ink while keeping the whole SVG available."""
    if renderer is None or bounds.isEmpty():
        return bounds
    scale = 850 / max(bounds.width(), bounds.height())
    width = max(1, round(bounds.width() * scale))
    height = max(1, round(bounds.height() * scale))
    sample = QImage(width, height, QImage.Format_Grayscale8)
    sample.fill(255)
    painter = QPainter(sample)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter, QRectF(0, 0, width, height))
    painter.end()
    scanlines = np.asarray(sample.constBits()).reshape(height, sample.bytesPerLine())
    ink = 255 - scanlines[:, :width]
    if not ink.any():
        return bounds

    # A tiny ink percentile keeps stray fragments of adjacent CAD drawings
    # from shrinking the primary section. Coordinates are used only for fit.
    intervals = []
    for axis, size in ((0, width), (1, height)):
        cumulative = np.cumsum(ink.sum(axis=axis))
        start, end = np.searchsorted(cumulative, cumulative[-1] * np.array([.006, .994]))
        margin = max(round(size * .025), 3)
        intervals.append((max(0, start - margin) / size, min(size, end + margin + 1) / size))
    (left, right), (top, bottom) = intervals
    return QRectF(bounds.left() + bounds.width() * left, bounds.top() + bounds.height() * top,
                  bounds.width() * (right - left), bounds.height() * (bottom - top))


class PipeDrawingView(SectionSchemeView):
    enlargement_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._focus_bounds = QRectF()
        self._fit_full = False
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        overlay = QVBoxLayout(self.viewport())
        overlay.setContentsMargins(7, 7, 7, 7)
        self.case_controls = QWidget()
        controls = QHBoxLayout(self.case_controls)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(4)
        self.terrain_case = QComboBox()
        self.terrain_case.setAccessibleName("地形示意")
        self.previous_case = self._case_arrow(Qt.LeftArrow, "上一张断面图", -1)
        self.next_case = self._case_arrow(Qt.RightArrow, "下一张断面图", 1)
        controls.addWidget(self.previous_case)
        controls.addWidget(self.terrain_case)
        controls.addWidget(self.next_case)
        overlay.addStretch()
        overlay.addWidget(self.case_controls, 0, Qt.AlignRight)
        self.case_controls.hide()

    def _case_arrow(self, arrow, label, direction):
        button = QToolButton()
        button.setArrowType(arrow)
        button.setFixedSize(26, 26)
        button.setAccessibleName(label)
        button.setToolTip(label)
        button.clicked.connect(lambda: self._step_case(direction))
        return button

    def _step_case(self, direction):
        count = self.terrain_case.count()
        if count > 1:
            self.terrain_case.setCurrentIndex((self.terrain_case.currentIndex() + direction) % count)

    def _reset(self):
        self._focus_bounds = QRectF()
        self._fit_full = False
        super()._reset()

    def set_image(self, path=None):
        super().set_image(path)
        if self.source_path:
            bounds = self.scene().itemsBoundingRect()
            self._focus_bounds = _drawing_focus(self._renderer, bounds)
            self.fit_section()

    def _fit_bounds(self):
        return self.sceneRect() if self._fit_full or self._focus_bounds.isEmpty() else self._focus_bounds

    def fit_section(self):
        self._fit_full = False
        self.fit_to_window()

    def fit_full_drawing(self):
        self._fit_full = True
        self.fit_to_window()

    def mouseDoubleClickEvent(self, event):
        if self.source_path and event.button() == Qt.LeftButton:
            self.enlargement_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class _PipeParameterSectionView(ParameterSectionView):
    enlargement_requested = Signal()

    def mouseDoubleClickEvent(self, event):
        if self.geometry_model is not None and event.button() == Qt.LeftButton:
            self.enlargement_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class PipeSectionComparison(QWidget):
    model_enlargement_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pipeSectionComparison")
        self.source = PipeDrawingView()
        self.terrain_case = self.source.terrain_case
        self.terrain_case.currentIndexChanged.connect(self._refresh_source)
        self.model = _PipeParameterSectionView(show_pipe_trench=True)
        self._source_request = None
        self._source_scheme = {}
        self._input_files = ()
        self.source.enlargement_requested.connect(self._open_source)
        self.model.enlargement_requested.connect(self.model_enlargement_requested)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        header = QHBoxLayout()
        self.tabs = QTabBar()
        self.tabs.setAccessibleName("断面图类型")
        self.tabs.setExpanding(False)
        self.tabs.setStyleSheet("""
            QTabBar::tab {color:#4C5768;background:#F7F8FB;border:1px solid transparent;
                padding:5px 10px;margin-right:4px;border-radius:5px;}
            QTabBar::tab:selected {color:#3346A2;background:#E9EEFF;border-color:transparent;}
        """)
        self.tabs.addTab("参数化断面")
        self.tabs.addTab(STANDARD_DRAWING_TITLE)
        header.addWidget(self.tabs)
        header.addStretch(1)
        self.model_terrain_case = QComboBox()
        self.model_terrain_case.setAccessibleName("地形示意")
        self.model_terrain_case.setModel(self.terrain_case.model())
        self.model_terrain_case.currentIndexChanged.connect(self.terrain_case.setCurrentIndex)
        self.terrain_case.currentIndexChanged.connect(self.model_terrain_case.setCurrentIndex)
        header.addWidget(self.model_terrain_case)
        self.enlarge_button = QPushButton()
        self.enlarge_button.setObjectName("enlargePipeSection")
        self.enlarge_button.clicked.connect(self._enlarge_current)
        header.addWidget(self.enlarge_button)
        layout.addLayout(header)
        self.panes = QStackedWidget()
        for title, view in (("参数化断面", self.model), (STANDARD_DRAWING_TITLE, self.source)):
            view.setAccessibleName(title)
            view.setToolTip("滚轮缩放，拖动平移")
            view.setMinimumSize(155, 215)
            self.panes.addWidget(view)
        layout.addWidget(self.panes, 1)
        self.tabs.currentChanged.connect(self._switch_preview)
        self._switch_preview(0)

    def _switch_preview(self, index):
        if self.panes.currentIndex() != index:
            self.panes.setCurrentIndex(index)
        model = self.panes.currentWidget() is self.model
        self.model_terrain_case.setVisible(model and self.terrain_case.count() > 1)
        self.enlarge_button.setText("放大编辑" if model else "放大图纸")
        self.enlarge_button.setVisible(model or bool(self.source.source_path))

    def _enlarge_current(self):
        if self.panes.currentWidget() is self.model:
            self.model_enlargement_requested.emit()
        else:
            self._open_source()

    def set_source(self, scheme, input_files=()):
        previous = (self.terrain_case.currentData()
                    if scheme.get("scheme_id") == self._source_scheme.get("scheme_id") else None)
        self._source_scheme, self._input_files = scheme, input_files
        title = STANDARD_DRAWING_TITLE if scheme.get("drawing_id") in {None, "tzk"} else "断面图纸"
        self.tabs.setTabText(1, title)
        self.source.setAccessibleName(title)
        with QSignalBlocker(self.terrain_case), QSignalBlocker(self.model_terrain_case):
            self.terrain_case.clear()
            for case, label in pipe_standard_drawing_variants(scheme):
                self.terrain_case.addItem(label, case)
            self.terrain_case.setCurrentIndex(max(0, self.terrain_case.findData(previous)))
            self.model_terrain_case.setCurrentIndex(self.terrain_case.currentIndex())
        self.source.case_controls.setVisible(self.terrain_case.count() > 1)
        self._refresh_source()

    def _refresh_source(self):
        case = self.terrain_case.currentData()
        scheme = self._source_scheme
        reference = pipe_standard_drawing_source(scheme, case)
        self._source_request = (scheme, reference, section_scheme_catalog_path().parent, self._input_files)
        if reference:
            self.source.show_scheme_drawing(*self._source_request)
        else:
            self.source.show_message("该断面暂无图纸。")
        self._switch_preview(self.tabs.currentIndex())
        self.model.set_pipe_terrain_case(case)

    def _open_source(self):
        if not self.source.source_path or self._source_request is None:
            return
        dialog = QDialog(self.window(), Qt.Window | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        dialog.setObjectName("enlargedPipeStandardDrawing")
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.setWindowTitle(self.source.accessibleName())
        dialog.setStyleSheet("""
            QDialog#enlargedPipeStandardDrawing { background:#F4F7FA; }
            QDialog#enlargedPipeStandardDrawing QPushButton {
                color:#23425C; background:white; border:1px solid #C5D3DF;
                border-radius:5px; min-height:30px; padding:0 10px;
            }
            QDialog#enlargedPipeStandardDrawing QPushButton:hover { background:#EAF3FA; }
            QGraphicsView#enlargedPipeStandardDrawingView { border:1px solid #D1DCE5; }
        """)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(6)
        view = PipeDrawingView(dialog)
        view.setObjectName("enlargedPipeStandardDrawingView")
        view.setAccessibleName(self.source.accessibleName())
        view.setMinimumSize(360, 250)
        view.show_scheme_drawing(*self._source_request)
        if self.terrain_case.count() > 1:
            view.terrain_case.setModel(self.terrain_case.model())
            view.terrain_case.setCurrentIndex(self.terrain_case.currentIndex())
            view.terrain_case.currentIndexChanged.connect(self.terrain_case.setCurrentIndex)
            self.terrain_case.currentIndexChanged.connect(view.terrain_case.setCurrentIndex)
            view.terrain_case.currentIndexChanged.connect(lambda: view.show_scheme_drawing(*self._source_request))
            view.case_controls.show()

        tools = QHBoxLayout()
        tools.addStretch()
        for label, tip, callback in (
            ("−", "缩小", lambda: view.zoom(1 / 1.18)),
            ("+", "放大", lambda: view.zoom(1.18)),
            ("适合窗口", "让横断面填满窗口", view.fit_section),
            ("显示全图", "查看裁出的全部图纸范围", view.fit_full_drawing),
        ):
            button = QPushButton(label)
            button.setAccessibleName(tip)
            button.setToolTip(tip)
            button.clicked.connect(callback)
            tools.addWidget(button)
        layout.addLayout(tools)
        layout.addWidget(view, 1)
        available = dialog.screen().availableGeometry()
        bounds = view._fit_bounds()
        aspect = bounds.width() / max(bounds.height(), 1)
        limit_width, limit_height = int(available.width() * .94), int(available.height() * .92)
        width = min(limit_width, max(480, round((limit_height - 58) * aspect)))
        height = min(limit_height, max(390, round(width / max(aspect, .1)) + 58))
        dialog.resize(width, height)
        dialog.open()

    def set_model(self, asset, scheme, pending=()):
        self.model.set_section_parameters(asset, scheme, pending)
