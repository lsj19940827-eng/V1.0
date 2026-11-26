"""Model-space overview of the axes on one pipe profile drawing."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPainterPathStroker, QPen, QTransform
from PySide6.QtWidgets import QSizePolicy, QWidget

from 土石方计算.services.design_profiles import DesignProfile, evaluate_profile, normalize_design_profile

from .pipe_profile_mapping import FACTORS


def _drawing_path(profile):
    """Keep CAD corners and sample each bulge in the original coordinate system."""
    if not isinstance(profile, DesignProfile):
        profile = normalize_design_profile(profile)
    left = profile["station_start"]
    path = QPainterPath(QPointF(left, evaluate_profile(profile, left)[0]))
    for element in profile["elements"]:
        right = element["station_end"]
        if element["kind"] == "arc":
            start = element["station_start"]
            stations = [start + (right - start) * i / 24 for i in range(1, 24)]
            centre = element["center_station"]
            if start < centre < right:
                stations.append(centre)
            for x in sorted(stations):
                path.lineTo(x, evaluate_profile(profile, x)[0])
        path.lineTo(right, evaluate_profile(profile, right)[0])
    return path


class DrawingProfileLayout(QWidget):
    row_selected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dxfPressureDrawingLayout")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(125)
        self.setAccessibleName("DXF 管轴布置")
        self.setToolTip("点击图中的线可定位到匹配表中的对应行。")
        self._curves = None
        self._paths = {}
        self._chosen = set()
        self._units = {}
        self._visible = []
        self._selected = -1
        self._screen_paths = {}
        self.gap_rows = []
        self.gap_bounds = []

    def set_profiles(self, curves, assignments):
        if curves is not self._curves:
            self._curves = curves
            self._paths = {row: _drawing_path(curve["profile"]) for row, curve in enumerate(curves)
                           if "profile" in curve}
        self._chosen = {row for row, assignment in enumerate(assignments) if assignment[0] is not None}
        self._units = {row: assignments[row][1] for row in self._chosen}
        self._refresh_layout()

    def set_current_row(self, row):
        if self._selected != row:
            self._selected = row
            self._refresh_layout()

    def _refresh_layout(self):
        self._screen_paths.clear()
        self.gap_rows = []
        self.gap_bounds = []
        self._visible = []
        if not self._paths:
            self.setAccessibleDescription("暂无可预览的多段线")
            self.update()
            return
        current = self._selected if 0 <= self._selected < len(self._curves) else next(iter(self._paths))
        filename = self._curves[current]["source"]["path"]
        candidates = [row for row in self._paths if self._curves[row]["source"]["path"] == filename]
        chosen = sorted((row for row in candidates if row in self._chosen),
                        key=lambda row: self._curves[row]["profile"]["station_start"])
        self._visible = list(chosen or candidates)
        if self._selected in candidates and self._selected not in self._visible:
            self._visible.append(self._selected)
        if chosen:
            previous = chosen[0]
            end = self._curves[previous]["profile"]["station_end"]
            # Compare raw drawing coordinates, using the reader's metre tolerance.
            for row in chosen[1:]:
                profile = self._curves[row]["profile"]
                tolerance = .001 / max(FACTORS[self._units[previous]], FACTORS[self._units[row]])
                if profile["station_start"] > end + tolerance:
                    self.gap_rows.append((previous, row))
                    self.gap_bounds.append((end, profile["station_start"]))
                if profile["station_end"] > end:
                    previous, end = row, profile["station_end"]
        self._caption = (f"已选 {len(chosen)} 条管轴 · {len(self.gap_rows)} 处留空" if chosen
                         else f"{len(candidates)} 条候选线")
        self.setAccessibleDescription(self._caption)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        frame = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        painter.setPen(QColor("#d5dfe9"))
        painter.setBrush(QColor("#f8fafc"))
        painter.drawRoundedRect(frame, 6, 6)
        if not self._visible:
            painter.setPen(QColor("#5e7183"))
            painter.drawText(frame, Qt.AlignCenter, "暂无可预览的多段线")
            return
        painter.setPen(QColor("#294760"))
        painter.drawText(QPointF(12, 19), "DXF 管轴布置")
        painter.setPen(QColor("#566b7e"))
        caption = painter.fontMetrics().elidedText(self._caption, Qt.ElideRight, max(0, self.width()-127))
        painter.drawText(frame.adjusted(110, 3, -12, 0), Qt.AlignRight | Qt.AlignTop, caption)
        plot = frame.adjusted(15, 32, -15, -30)
        if plot.width() <= 0:
            return
        bounds = [self._paths[row].boundingRect() for row in self._visible]
        left, right = min(b.left() for b in bounds), max(b.right() for b in bounds)
        low, high = min(b.top() for b in bounds), max(b.bottom() for b in bounds)
        sx = plot.width() / (right - left)
        sy = plot.height() / (high - low) if high > low else 1.
        transform = QTransform(sx, 0., 0., -sy, plot.left() - left * sx,
                               plot.center().y() + (low + high) * .5 * sy)
        self._screen_paths.clear()
        for row in sorted(self._visible, key=lambda index: index == self._selected):
            screen_path = transform.map(self._paths[row])
            self._screen_paths[row] = screen_path
            if row in self._chosen:
                colour = "#1267ad" if row == self._selected else "#45789c"
            else:
                colour = "#738798"
            pen = QPen(QColor(colour), 2.8 if row == self._selected else 1.8)
            if self._chosen and row not in self._chosen:
                pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(screen_path)

        painter.setPen(QPen(QColor("#a15a21"), 1.1))
        label_width = painter.fontMetrics().horizontalAdvance("留空")
        y = plot.bottom() + 7
        for a, b in self.gap_bounds:
            x1, x2 = plot.left() + (a - left) * sx, plot.left() + (b - left) * sx
            painter.drawLine(QPointF(x1, y - 4), QPointF(x1, y))
            painter.drawLine(QPointF(x1, y), QPointF(x2, y))
            painter.drawLine(QPointF(x2, y), QPointF(x2, y - 4))
            if x2 - x1 >= label_width + 2:
                painter.drawText(QRectF(x1, y + 1, x2 - x1, 21), Qt.AlignHCenter | Qt.AlignTop, "留空")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            point = event.position()
            stroke = QPainterPathStroker()
            stroke.setWidth(12.)
            for row, path in reversed(self._screen_paths.items()):
                nearby = path.boundingRect().adjusted(-6, -6, 6, 6).contains(point)
                if nearby and stroke.createStroke(path).contains(point):
                    self.row_selected.emit(row)
                    event.accept()
                    return
        super().mousePressEvent(event)
