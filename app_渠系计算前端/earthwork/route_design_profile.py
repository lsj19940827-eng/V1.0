"""Read-only design longitudinal profiles grouped by the engineering line."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from 土石方计算.services.batch_cover_profiles import is_pressure_cover_asset
from 土石方计算.services.design_profiles import clip_design_profile, normalize_design_profile
from 土石方计算.services.earthwork_scope import (
    _number, trenchless_exclusions, trenchless_intersections, trenchless_method,
)
from 土石方计算.services.section_scheme_bindings import format_station

from .pipe_design_preview import ProfilePreviewPane


def _span(start, end):
    left, right = _number(start), _number(end)
    if left is not None and right is not None and right > left:
        return left, right
    return None


def _asset_span(asset):
    return _span(asset.get("station_start"), asset.get("station_end"))


def _profile_in_span(source, span, *, reference=None):
    try:
        profile = normalize_design_profile(source, reference=reference)
        start = max(span[0], profile["station_start"])
        end = min(span[1], profile["station_end"])
        if end <= start:
            return None
        if (start, end) == (profile["station_start"], profile["station_end"]):
            return profile
        return clip_design_profile(profile, start, end)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        return None


@dataclass(frozen=True, slots=True)
class ChannelProfileGroup:
    name: str
    station_prefix: str
    station_bounds: tuple[float, float]
    members: tuple
    bores: tuple
    alignments: tuple

    @property
    def span(self):
        start, end = self.station_bounds
        return f"{format_station(start, self.station_prefix)} ～ {format_station(end, self.station_prefix)}"

    def read_profiles(self):
        for _, asset in self.members:
            if asset.get("pipe_profile_choice") == "pending_gap" or trenchless_method(asset):
                continue
            start, end = _asset_span(asset)
            selected = asset.get("design_profile")
            reference = selected.get("reference") if isinstance(selected, dict) else None
            if reference is None:
                reference = (asset.get("alignment") or {}).get("elevation_reference")
            profile = _profile_in_span(asset, (start, end), reference=reference)
            if profile is not None:
                yield profile
        for bore in self.bores:
            span = _asset_span(bore)
            original = bore.get("original_asset_snapshot") or bore
            source = bore.get("trenchless_route_profile") or original.get("trenchless_route_profile")
            if not source and not (original.get("longitudinal_is_example") or original.get("test_only")
                    or original.get("axis_source") == "terrain_and_user_cover_depth"
                    or (original.get("construction") or {}).get("burial_mode") == "cover_depth"):
                source = original
            if span is not None and source:
                clipped = max(self.station_bounds[0], span[0]), min(self.station_bounds[1], span[1])
                profile = _profile_in_span(source, clipped)
                if profile is not None:
                    yield profile


def channel_profile_groups(inputs, displayed_routes):
    """Return full-line previews for routes with channels or only non-open-cut spans.

    The application's displayed route IDs identify related network slices. A design
    profile is clipped to its existing asset interval, so missing portions stay gaps.
    """
    from .section_preparation import route_identity

    networks_by_group = defaultdict(list)
    bore_routes = dict(displayed_routes)
    for network in inputs.get("networks", ()):
        route = displayed_routes.get(route_identity(network))
        if route is not None:
            group, name = route
            networks_by_group[group].append((network, name))
            source_id = network.get("route_id") or network.get("source_identity") or network.get("network_id")
            if source_id:
                bore_routes.setdefault(str(source_id), route)
    all_bores = trenchless_exclusions(inputs)
    bores_by_group = defaultdict(list)
    for bore in all_bores:
        route_id = str(bore.get("route_id") or bore.get("network_id") or "")
        if route_id and (span := _asset_span(bore)) is not None:
            route_name = "当前渠道工程" if route_id == "water_profile" else route_id.removeprefix("pressure_route:")
            group, name = bore_routes.get(route_id, (route_id, bore.get("route_name") or route_name))
            bores_by_group[group].append((span, bore, name))
    result = {}
    for group in dict.fromkeys((*networks_by_group, *bores_by_group)):
        entries = networks_by_group.get(group, ())
        stationed = [(span, network, asset) for network, _ in entries for asset in network.get("assets", ())
                     if (span := _asset_span(asset)) is not None]
        includes_channel = any(not is_pressure_cover_asset(asset) and not trenchless_method(asset)
                               for _, _, asset in stationed)
        direct_bores = bores_by_group.get(group, ())
        if not includes_channel and (not direct_bores or any(not trenchless_method(asset)
                for network, _ in entries for asset in network.get("assets", ()))):
            continue

        extents = [span for span, _, _ in stationed]
        if not includes_channel:
            extents.extend(span for span, _, _ in direct_bores)
        for network, _ in entries:
            declared = network.get("source_route_extent")
            if isinstance(declared, (list, tuple)) and len(declared) == 2:
                extent = _span(*declared)
                if extent is not None:
                    extents.append(extent)
        start = min(extent[0] for extent in extents)
        end = max(extent[1] for extent in extents)
        if includes_channel:
            bores = tuple(bore for bore in all_bores
                          if any(trenchless_intersections([bore], network, start, end) for network, _ in entries))
        else:
            bores = tuple(bore for _, bore, _ in direct_bores)
        alignments = {id(network["alignment"]): network["alignment"]
                      for network, _ in entries if network.get("alignment")}
        for bore in bores:
            if elements := bore.get("plan_elements"):
                alignments[id(elements)] = {"elements": elements, "ip_points": [],
                                            "start_station": elements[0]["station_start"]}
        first, name = entries[0] if entries else ({}, direct_bores[0][2])
        result[group] = ChannelProfileGroup(
            name, first.get("station_prefix") or "K", (start, end),
            tuple((network, asset) for _, network, asset in sorted(stationed, key=lambda entry: entry[0][0])),
            bores, tuple(alignments.values()),
        )
    return result


class RouteDesignProfilePage(QWidget):
    """Display the adopted longitudinal design and available original ground."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("channelDesignProfilePage")
        self._group = None
        self._terrain = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 9, 6)
        layout.setSpacing(6)
        self.title = QLabel("设计纵断面")
        self.title.setTextFormat(Qt.PlainText)
        self.title.setStyleSheet("font-size:20px;font-weight:600;color:#18212E")
        layout.addWidget(self.title)
        self._preview = ProfilePreviewPane(self)
        self.chart, self.status = self._preview.chart, self._preview.status
        layout.addWidget(self._preview, 1)

    def set_context(self, group, *, terrain=None):
        if group is self._group and terrain is self._terrain:
            return
        self._group, self._terrain = group, terrain
        self.title.setText(f"{group.name} · 设计纵断面" if group else "设计纵断面")
        if self.isVisible():
            self._start()

    def _start(self):
        group = self._group
        if group is None:
            self._preview.clear()
            self.status.setText("暂无可预览的设计纵断面")
            return
        self._preview.prepare(group.read_profiles, terrain=self._terrain, alignment=group.alignments or None,
                              station_prefix=group.station_prefix, station_bounds=group.station_bounds)
        self._preview.start()

    def showEvent(self, event):
        super().showEvent(event)
        self._start()

    def hideEvent(self, event):
        self._preview.clear()
        super().hideEvent(event)
