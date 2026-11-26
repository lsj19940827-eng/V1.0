"""Draw a longitudinal profile in engineering coordinates using Qt."""
from __future__ import annotations

from math import ceil, floor, isfinite, log10

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF, QTransform
from PySide6.QtWidgets import QSizePolicy, QWidget

from .profile_chart_navigation import MOUSE_NAVIGATION_HINT, scaled_zoom, wheel_steps, zoom_limits


def _polylines(series):
    """Each input series and each non-finite sample delimit a separate run."""
    runs = []
    for stations, elevations in series:
        line = QPolygonF()
        for x, z in zip(stations, elevations, strict=True):
            if isfinite(x) and isfinite(z):
                line.append(QPointF(float(x), float(z)))
            elif not line.isEmpty():
                runs.append(line)
                line = QPolygonF()
        if not line.isEmpty():
            runs.append(line)
    return runs


def _ticks(low, high, count):
    rough = (high-low) / count
    unit = 10. ** floor(log10(rough))
    step = next(m * unit for m in (1., 2., 2.5, 5., 10.) if m * unit >= rough)
    decimals = max(0, 1 - floor(log10(step)))
    for i in range(ceil(low/step - 1e-10), floor(high/step + 1e-10) + 1):
        value = i * step
        label = f"{value:.{decimals}f}"
        if "." in label:
            label = label.rstrip("0").rstrip(".")
        yield value, label


class PipePreviewChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pipePreviewChart")
        self.setAccessibleName("设计纵断面图")
        self.setMinimumSize(310, 165)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setToolTip(MOUSE_NAVIGATION_HINT)
        self.vertical_exaggeration = 5.
        self._design = []
        self._design_styles = []
        self._ground = []
        self._bounds = None
        self._reference = "设计管轴"
        self._source_profiles = None
        self._zoom = 1.
        self._view_center = None
        self._drag_position = None

    def set_data(self, profiles, ground=None, reference_label="设计管轴", *, station_bounds=None, series_styles=None):
        # The same profile can be displayed before its asynchronous ground trace arrives.
        if profiles is not self._source_profiles:
            self.reset_view()
        self._source_profiles = profiles
        self._reference = reference_label
        self._design = []
        self._design_styles = []
        styled = (((series, ("", reference_label)) for series in profiles) if series_styles is None
                  else zip(profiles, series_styles, strict=True))
        for series, style in styled:
            runs = _polylines([series])
            self._design.extend(runs)
            self._design_styles.extend([style] * len(runs))
        self._ground = _polylines([ground]) if ground is not None else []
        rects = [line.boundingRect() for line in self._design + self._ground]
        self._bounds = (min(r.left() for r in rects), max(r.right() for r in rects),
                        min(r.top() for r in rects), max(r.bottom() for r in rects)) if rects else None
        if self._bounds is not None and station_bounds is not None:
            left, right, low, high = self._bounds
            self._bounds = min(left, station_bounds[0]), max(right, station_bounds[1]), low, high
        self.update()

    def set_vertical_exaggeration(self, value):
        if value is not None:
            value = float(value)
            if not isfinite(value) or value <= 0:
                raise ValueError("纵向倍率须为正数")
        self.vertical_exaggeration = value
        self.update()

    def _layout(self):
        if self._bounds is None:
            return None
        xmin, xmax, zmin, zmax = self._bounds
        metrics = self.fontMetrics()
        label_height = metrics.height()
        left_margin = max(48, metrics.horizontalAdvance(f"{zmin:.3f}") + 10,
                          metrics.horizontalAdvance(f"{zmax:.3f}") + 10)
        end_margin = max(16, metrics.horizontalAdvance(f"{xmax:.1f}") / 2 + 5)
        plot = QRectF(self.rect()).adjusted(left_margin, label_height + 12, -end_margin, -2 * label_height - 12)
        if plot.width() < 1 or plot.height() < 1:
            return None
        padding = (xmax-xmin) * .02 if xmax > xmin else .5
        left, right = xmin-padding, xmax+padding
        sx = plot.width() / (right-left)
        # Keep the requested vertical scale in pixels/metre, with space for peaks.
        relief = zmax-zmin
        if self.vertical_exaggeration is None:
            sy = plot.height() / (relief * 1.12 if relief else 2.)
        else:
            sy = sx * self.vertical_exaggeration
            if relief:
                sy = min(sy, plot.height() / (relief * 1.12))
                if self.vertical_exaggeration == 1. and sy < sx:
                    # Zoom out horizontally as well to preserve true equal scale.
                    sx = sy
                    centre_x = (xmin + xmax) / 2
                    half_width = plot.width() / (2 * sx)
                    left, right = centre_x - half_width, centre_x + half_width
        centre_x, centre_z = self._view_center or ((left + right) / 2, zmin + relief / 2)
        half_x = (right - left) / (2 * self._zoom)
        half_z = plot.height() / (2 * sy * self._zoom)
        return plot, centre_x-half_x, centre_x+half_x, centre_z-half_z, centre_z+half_z, sy/sx

    @property
    def effective_vertical_exaggeration(self):
        layout = self._layout()
        return layout[-1] if layout else None

    def reset_view(self):
        self._zoom = 1.
        self._view_center = None
        self._drag_position = None
        self.unsetCursor()
        self.update()

    def wheelEvent(self, event):
        layout = self._layout()
        position = event.position()
        steps = wheel_steps(event)
        if layout is None or not layout[0].contains(position) or not steps or self._drag_position is not None:
            event.ignore()
            return
        plot, left, right, low, high, _ = layout
        target = scaled_zoom(self._zoom, steps)
        if target != self._zoom:
            factor = self._zoom / target
            x = left + (right-left) * (position.x()-plot.left()) / plot.width()
            z = low + (high-low) * (plot.bottom()-position.y()) / plot.height()
            self._view_center = (sum(zoom_limits((left, right), x, factor)) / 2,
                                 sum(zoom_limits((low, high), z, factor)) / 2)
            self._zoom = target
            self.update()
        event.accept()

    def mousePressEvent(self, event):
        layout = self._layout()
        if event.button() == Qt.LeftButton and layout is not None and layout[0].contains(event.position()):
            self._drag_position = event.position()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        layout = self._layout()
        if self._drag_position is None or layout is None:
            super().mouseMoveEvent(event)
            return
        plot, left, right, low, high, _ = layout
        movement = event.position() - self._drag_position
        self._view_center = ((left + right) / 2 - movement.x() * (right-left) / plot.width(),
                             (low + high) / 2 + movement.y() * (high-low) / plot.height())
        self._drag_position = event.position()
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._drag_position is not None and event.button() == Qt.LeftButton:
            self._drag_position = None
            self.unsetCursor()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        layout = self._layout()
        if event.button() == Qt.LeftButton and layout is not None and layout[0].contains(event.position()):
            self.reset_view()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#ffffff"))
        layout = self._layout()
        if layout is None:
            return
        plot, left, right, low, high, ratio = layout
        sx, sy = plot.width() / (right-left), plot.height() / (high-low)
        transform = QTransform(sx, 0., 0., -sy, plot.left()-left*sx, plot.bottom()+low*sy)
        metrics = painter.fontMetrics()
        height = metrics.height()
        text = QColor("#34465a")
        grid = QColor("#e1e7eb")
        design_pens = {"": QPen(QColor("#176bb0"), 2.), "cover": QPen(QColor("#087f72"), 2.),
                       "trenchless": QPen(QColor("#6b607a"), 2., Qt.DashLine)}
        ground_pen = QPen(QColor("#926a43"), 1.8, Qt.DashLine)
        painter.setPen(text)
        painter.drawText(QRectF(8, 3, plot.width(), height+2), Qt.AlignLeft | Qt.AlignVCenter, "高程 (m)")
        edge = plot.right()
        legend = [(label, design_pens[role]) for role, label in dict.fromkeys(self._design_styles)]
        if self._ground:
            legend.append(("原地面", ground_pen))
        for label, pen in reversed(legend):
            width = metrics.horizontalAdvance(label)
            painter.setPen(text)
            painter.drawText(QRectF(edge-width, 3, width+1, height+2), Qt.AlignVCenter, label)
            edge -= width + 5
            painter.setPen(pen)
            painter.drawLine(QPointF(edge-20, 4+height/2), QPointF(edge, 4+height/2))
            edge -= 34

        tick_width = max(58, metrics.horizontalAdvance(f"{left:.2f}") + 12,
                         metrics.horizontalAdvance(f"{right:.2f}") + 12)
        for value, label in _ticks(left, right, max(2, floor(plot.width() / tick_width))):
            x = plot.left() + (value-left) * sx
            painter.setPen(grid)
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            width = metrics.horizontalAdvance(label) + 4
            painter.setPen(text)
            painter.drawText(QRectF(x-width/2, plot.bottom()+3, width, height+1), Qt.AlignCenter, label)
        for value, label in _ticks(low, high, max(2, floor(plot.height() / max(34, height*2)))):
            y = plot.bottom() - (value-low) * sy
            painter.setPen(grid)
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(text)
            painter.drawText(QRectF(1, y-height/2, plot.left()-7, height+1), Qt.AlignRight | Qt.AlignVCenter, label)

        painter.setPen(QColor("#afbbc6"))
        painter.drawRect(plot)
        painter.save()
        painter.setClipRect(plot)
        painter.setRenderHint(QPainter.Antialiasing)
        runs = [(line, ground_pen) for line in self._ground]
        runs.extend((line, design_pens[role]) for line, (role, _) in zip(self._design, self._design_styles, strict=True))
        for line, pen in runs:
            painter.setPen(pen)
            if line.size() == 1:
                painter.drawPoint(transform.map(line[0]))
            else:
                painter.drawPolyline(transform.map(line))
        painter.restore()
        footer = QRectF(6, self.height()-height-5, self.width()-14, height+2)
        painter.setPen(text)
        painter.drawText(footer, Qt.AlignCenter, "桩号 (m)")
        painter.drawText(footer, Qt.AlignRight | Qt.AlignVCenter, f"实际纵向倍率 {ratio:.3g}×")
