"""Asynchronous design-axis and terrain preview in the earthwork workbench."""
from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from math import isfinite

import numpy as np
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from app_渠系计算前端.task_runner import TaskRunner
from 土石方计算.services.design_profiles import evaluate_profile, normalize_design_profile
from 土石方计算.services.section_scheme_bindings import format_station
from .pipe_preview_chart import PipePreviewChart


@dataclass(frozen=True, slots=True)
class ProfilePreviewSeries:
    profile: object
    role: str


def _sample_design(read_profiles, token):
    lines = []
    references = set()
    roles = []
    label = {"pipe_axis": "设计管轴", "inner_invert": "净内底", "common_outer_bottom": "共同外管底"}
    for raw in read_profiles():
        token.raise_if_cancelled()
        role = ""
        if isinstance(raw, ProfilePreviewSeries):
            raw, role = raw.profile, raw.role
        profile = normalize_design_profile(raw)
        reference = profile["reference"]
        if not role:
            references.add(reference)
        roles.append((role, reference))
        stations = [*np.linspace(profile["station_start"], profile["station_end"], 201)]
        for element in profile["elements"]:
            start, end = element["station_start"], element["station_end"]
            stations.extend((start, end))
            if element["kind"] == "arc":
                stations.extend(np.linspace(start, end, 17)[1:-1])
                if start < element["center_station"] < end:
                    stations.append(element["center_station"])
        stations = np.unique(stations)
        elevations = np.empty_like(stations)
        for i, station in enumerate(stations):
            if i % 256 == 0:
                token.raise_if_cancelled()
            elevations[i] = evaluate_profile(profile, station)[0]
        lines.append((stations, elevations))
    if not lines:
        raise ValueError("没有可预览的设计纵断面")
    reference_label = label.get(next(iter(references)), "设计线") if len(references) == 1 else "设计线"
    if not any(role for role, _ in roles):
        return lines, reference_label, None
    cover_labels = {**label, "pipe_axis": "管轴"}
    styles = []
    for role, reference in roles:
        labels = {"cover": "覆土" + cover_labels.get(reference, "生成线"), "trenchless": "非开挖管轴"}
        styles.append((role, labels.get(role, reference_label)))
    return lines, reference_label, styles


def sample_ground(terrain, alignment, bounds, token, *, extra_stations=()):
    from 土石方计算.services.network_alignment import NetworkAlignment
    from 土石方计算.services.profile_preview_terrain import sample_ground_points

    token.raise_if_cancelled()
    alignments = alignment if isinstance(alignment, tuple) else (alignment,)
    alignments = [NetworkAlignment.from_dict(a) if isinstance(a, dict) else a for a in alignments]
    station_runs, xy_runs = [], []
    cursor = bounds[0]
    spacing = (bounds[1] - bounds[0]) / 300
    extra_stations = np.sort(extra_stations)
    for part in sorted(alignments, key=lambda a: a.start_station):
        start = max(cursor, part.start_station)
        end = min(bounds[1], part.end_station)
        if end <= start:
            continue
        if station_runs and start > cursor + 1e-6:
            station_runs.append(np.array([np.nan]))
        stations = np.linspace(start, end, max(2, round((end - start) / spacing) + 1))
        first, last = extra_stations.searchsorted([start, end])
        if last > first:
            stations = np.union1d(stations, extra_stations[first:last])
        station_runs.append(stations)
        xy_runs.append(np.asarray([part.get_xy_at_station(s) for s in stations]))
        cursor = end
    if not xy_runs:
        return np.empty(0), np.empty(0)
    stations = np.concatenate(station_runs)
    valid = np.isfinite(stations)
    elevations = np.full(stations.shape, np.nan)
    elevations[valid] = sample_ground_points(terrain, np.concatenate(xy_runs), token)
    return stations, elevations


class ProfilePreviewPane(QWidget):
    """Show the design and ground using one cancellable sampling pipeline."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.runner = TaskRunner(self)
        self.runner.running_changed.connect(self._running_changed)
        self._waiting = False
        self._profiles = []
        self._reference = ""
        self._styles = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.status = QLabel("正在准备设计纵断面…")
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        self.status.setAccessibleName("纵断面加载状态")
        top.addWidget(self.status, 1)
        top.addWidget(QLabel("纵向倍率"))
        self.scale = QComboBox()
        self.scale.setAccessibleName("纵向倍率")
        self.scale.setToolTip("1× 表示桩号和高程每米的显示长度相同")
        options = (("1× 等比例", 1.), ("2×", 2.), ("5×", 5.), ("10×", 10.), ("适应高度", None))
        self.scale.addItems([label for label, _ in options])
        self.chart = PipePreviewChart()
        self.scale.setCurrentIndex(next(i for i, (_, factor) in enumerate(options)
                                        if factor == self.chart.vertical_exaggeration))
        self.scale.currentIndexChanged.connect(lambda index: self.chart.set_vertical_exaggeration(options[index][1]))
        top.addWidget(self.scale)
        layout.addLayout(top)
        layout.addWidget(self.chart, 1)

    def prepare(self, read_profiles, *, terrain=None, alignment=None, cache=None, key=None,
                station_prefix="K", station_bounds=None):
        self.clear()
        self._read_profiles = read_profiles
        self._terrain = terrain
        self._alignment = alignment
        self._cache = {} if cache is None else cache
        self._key = key
        self._station_prefix = station_prefix
        self._station_bounds = None
        if station_bounds is not None:
            try:
                start, end = map(float, station_bounds)
            except (TypeError, ValueError):
                pass
            else:
                if isfinite(start) and isfinite(end) and end > start:
                    self._station_bounds = start, end
        self._waiting = True
        self.status.setText("正在准备设计纵断面…")

    def clear(self):
        self._waiting = False
        self.runner.invalidate()
        if self._profiles:
            self.chart.set_data([])
            self._profiles = []

    def _running_changed(self, running):
        if not running and self._waiting:
            self.start()

    def start(self):
        if not self._waiting or self.runner.isRunning() or not self.isVisible():
            return
        self._waiting = False
        if self._key is not None and self._key in self._cache:
            self._profiles, self._reference, self._styles, ground = self._cache[self._key]
            self._show_result(ground)
            return
        self.runner.submit(partial(_sample_design, self._read_profiles), on_success=self._show_design,
                           on_error=lambda exc: self.status.setText(f"设计纵断面读取失败　{exc}"))

    def _show_design(self, result):
        self._profiles, self._reference, self._styles = result
        if self._terrain is None or self._alignment is None:
            self._show_result(None)
            return
        self.chart.set_data(self._profiles, reference_label=self._reference, station_bounds=self._station_bounds,
                            series_styles=self._styles)
        self.status.setText("正在读取沿线原地面高程…")
        ground = partial(sample_ground, self._terrain, self._alignment, self._preview_bounds())
        cover_stations = [stations for (stations, _), (role, _) in zip(self._profiles, self._styles or ())
                          if role == "cover"]
        if cover_stations:
            ground = partial(ground, extra_stations=np.concatenate(cover_stations))
        self.runner.submit(ground,
                           on_success=self._show_result,
                           on_error=lambda exc: self.status.setText(f"原地面高程读取失败　{exc}"))

    def _preview_bounds(self):
        return self._station_bounds or (min(xs[0] for xs, _ in self._profiles),
                                        max(xs[-1] for xs, _ in self._profiles))

    def _show_result(self, ground):
        self.chart.set_data(self._profiles, ground, self._reference, station_bounds=self._station_bounds,
                            series_styles=self._styles)
        if ground is not None and not np.isfinite(ground[1]).any():
            self.status.setText("此段沿线缺少原地面高程")
        else:
            start, end = self._preview_bounds()
            first = format_station(start, self._station_prefix)
            last = format_station(end, self._station_prefix)
            self.status.setText(f"桩号范围　{first} ～ {last}")
        if self._key is not None and self._key not in self._cache:
            if len(self._cache) >= 6:
                self._cache.pop(next(iter(self._cache)))
            self._cache[self._key] = self._profiles, self._reference, self._styles, ground


class ProfilePreviewDialog(QDialog):
    def __init__(self, parent, title, read_profiles, terrain, alignment, cache, key, station_prefix,
                 station_bounds=None):
        super().__init__(parent)
        self.setObjectName("pipeDesignPreview")
        self.setWindowTitle(title)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.resize(780, 415)
        layout = QVBoxLayout(self)
        self._preview = ProfilePreviewPane(self)
        self.chart, self.scale, self.status = self._preview.chart, self._preview.scale, self._preview.status
        self._preview.prepare(read_profiles, terrain=terrain, alignment=alignment, cache=cache, key=key,
                              station_prefix=station_prefix, station_bounds=station_bounds)
        self.finished.connect(lambda _: self._preview.runner.invalidate())
        layout.addWidget(self._preview, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText("返回")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def start(self):
        self._preview.start()


def show_profile_preview(parent, title, read_profiles, *, terrain=None, alignment=None, cache_key=None,
                         station_prefix="K", station_bounds=None):
    for opened in parent.findChildren(ProfilePreviewDialog, options=Qt.FindDirectChildrenOnly):
        if opened.isVisible():
            opened.raise_()
            opened.activateWindow()
            return opened
    if (not hasattr(parent, "_profile_preview_cache") or parent._preview_terrain is not terrain):
        parent._profile_preview_cache = {}
        parent._preview_terrain = terrain
    if cache_key is not None and station_bounds is not None:
        cache_key = cache_key, tuple(station_bounds)
    dialog = ProfilePreviewDialog(parent, title, read_profiles, terrain, alignment,
                                  parent._profile_preview_cache, cache_key, station_prefix, station_bounds)
    dialog.open()
    QTimer.singleShot(0, dialog, dialog.start)
    return dialog
