"""Group calculated cut/fill rows by their original engineering structure.

Several engineering forms share a calculation section (a pressure pipe may
use ``circular_culvert``).  Resolve the saved input identity before classifying
the section, and keep generated foundation pits with their parent structure.
This module only groups saved quantities; it never recalculates them.
"""
from __future__ import annotations

import math
from collections import defaultdict


EARTHWORK_VOLUME_KEYS = (
    "excavation_volume", "backfill_volume", "embankment_volume", "total_fill_volume",
)
STRUCTURE_CATEGORY_ORDER = (
    "明渠-圆形（圆管涵）", "明渠-U形", "明渠-矩形", "明渠-梯形", "明渠-复式梯形",
    "暗渠", "倒虹吸", "有压管道", "渡槽", "隧洞", "闸", "连接段估算", "其他结构",
)
_CHANNEL_CATEGORIES = {
    "circular_channel": STRUCTURE_CATEGORY_ORDER[0],
    "u_channel": "明渠-U形",
    "rectangular_channel": "明渠-矩形",
    "trapezoidal_channel": "明渠-梯形",
    "compound_trapezoidal_channel": "明渠-复式梯形",
}


def _result_rows(payload):
    return payload.get("rows", payload.get("assets", [])) or []


def _text(value):
    return str(value or "").strip()


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _route_id(network):
    return _text(network.get("route_id") or network.get("network_id") or network.get("name"))


def _input_assets(payload):
    inputs = payload.get("inputs") or {}
    network = inputs.get("network")
    if isinstance(network, dict):
        for asset in network.get("assets", []):
            yield asset, _text(asset.get("route_id")) or _route_id(network)
    work = inputs.get("workbench") or inputs.get("workbench_inputs") or {}
    if isinstance(work, dict):
        for network in work.get("networks", []):
            for asset in network.get("assets", []):
                yield asset, _text(asset.get("route_id")) or _route_id(network)
        for asset in work.get("pits", []):
            yield asset, _text(asset.get("route_id")) or "independent_pits"


def _same_structure(candidates):
    """Never choose an arbitrary different form from duplicate source IDs."""
    return len({(_text(asset.get("kind")), _text(asset.get("section_type")),
                 _text(asset.get("source_type"))) for asset, _ in candidates}) == 1


class _Classifier:
    def __init__(self, payload):
        self.inputs = list(_input_assets(payload))
        self.results = [(row, _text(row.get("route_id"))) for row in _result_rows(payload)]

    def _lookup(self, row, entries, *, route=None, identities=None):
        if identities is None:
            identities = [row.get(key) for key in (
                "asset_id", "original_asset_id", "section_scheme_root_asset_id", "drawing_root_asset_id",
            )]
        route = _text(row.get("route_id")) if route is None else _text(route)
        for identity in dict.fromkeys(_text(value) for value in identities if value):
            candidates = [(asset, source_route) for asset, source_route in entries
                          if _text(asset.get("asset_id")) == identity]
            if not candidates:
                continue
            if route:
                matching = [(asset, source_route) for asset, source_route in candidates if source_route == route]
                if matching:
                    candidates = matching
                else:
                    candidates = [(asset, source_route) for asset, source_route in candidates if not source_route]
                    if not candidates:
                        continue
            if len(candidates) == 1 or _same_structure(candidates):
                return candidates[0][0]
        return None

    def category(self, row, seen=None):
        seen = set() if seen is None else seen
        marker = (_text(row.get("route_id")), _text(row.get("asset_id")), id(row))
        if marker in seen:
            return "其他结构"
        seen = seen | {marker}
        source = self._lookup(row, self.inputs)
        asset = dict(source or {})
        asset.update({key: value for key, value in row.items() if value is not None})

        # These pits also occur under elevated pressure pipes.  The historical
        # generated_aqueduct_foundation flag alone does not determine the form.
        parent_id = asset.get("parent_asset_id")
        if parent_id and (asset.get("generated_aqueduct_foundation")
                          or asset.get("kind") == "pit"
                          or asset.get("section_type") in {"rectangular_pit", "box_foundation"}):
            parent_route = asset.get("parent_route_id") or asset.get("route_id")
            parent = self._lookup(asset, self.results, route=parent_route,
                                  identities=[parent_id, asset.get("parent_original_asset_id")])
            if parent is None:
                parent = self._lookup(asset, self.inputs, route=parent_route,
                                      identities=[parent_id, asset.get("parent_original_asset_id")])
            if parent is not None:
                category = self.category(parent, seen)
                if category != "其他结构":
                    return category

        kind = _text(asset.get("kind"))
        section = _text(asset.get("section_type"))
        source_type = _text(asset.get("source_type"))
        if section == "sluice_gate":
            return "闸"
        if source_type == "自动估算连接段":
            return "连接段估算"
        if kind in {"pipe", "pressure_pipe"}:
            return "有压管道"
        if kind == "siphon":
            return "倒虹吸"
        if kind == "aqueduct" or section.startswith("aqueduct_"):
            return "渡槽"
        if kind == "tunnel" or section.endswith("_tunnel"):
            return "隧洞"
        if source_type in {"有压管道", "顶管", "定向钻"}:
            return "有压管道"
        if source_type.startswith("倒虹吸"):
            return "倒虹吸"
        if source_type.startswith("渡槽"):
            return "渡槽"
        if source_type.startswith("隧洞"):
            return "隧洞"
        # Explicit dark-channel identity takes precedence over shared round
        # geometry; 明渠-圆形 and its old circular_channel alias stay together.
        if source_type.startswith(("暗渠", "暗涵")) or source_type in {"矩形暗渠", "矩形暗涵", "圆形暗涵"}:
            return "暗渠"
        if source_type.startswith("明渠-"):
            if source_type in {"明渠-圆形", "明渠-圆形（圆管涵）"}:
                return STRUCTURE_CATEGORY_ORDER[0]
            return "明渠-U形" if source_type in {"明渠-U型", "明渠-u形"} else source_type
        if section in _CHANNEL_CATEGORIES:
            return _CHANNEL_CATEGORIES[section]
        if section == "circular_culvert":
            return STRUCTURE_CATEGORY_ORDER[0]
        if kind == "culvert" or section in {"rectangular_culvert", "arch_culvert"}:
            return "暗渠"
        if section == "circular_siphon":
            return "倒虹吸"
        # A split row may retain only its parent identity in older snapshots.
        if parent_id:
            parent = self._lookup(asset, self.inputs, identities=[parent_id])
            if parent is not None:
                return self.category(parent, seen)
        return "其他结构"


def structure_category(payload, row):
    """Return one engineering category using route-aware saved input identity."""
    return _Classifier(payload).category(row)


def _row_length(row):
    length = _number(row.get("length"))
    if length is not None and length >= 0:
        return length
    start, end = _number(row.get("station_start")), _number(row.get("station_end"))
    if start is not None and end is not None and end >= start:
        return end - start
    return None


def classified_earthwork(payload, volume_columns=None):
    """Return present categories with original rows and unrounded saved totals.

    ``volume_columns`` accepts field names or ``(field, label)`` pairs.  A
    column with no measured values remains ``None``.  Excluded input objects
    never become zero-quantity result rows.  ``length`` sums the result rows'
    measured lengths (foundation pits therefore contribute their slice span).
    """
    columns = EARTHWORK_VOLUME_KEYS if volume_columns is None else volume_columns
    keys = list(dict.fromkeys(column if isinstance(column, str) else column[0] for column in columns))
    classifier = _Classifier(payload)
    grouped = defaultdict(list)
    for row in _result_rows(payload):
        grouped[classifier.category(row)].append(row)
    order = {category: index for index, category in enumerate(STRUCTURE_CATEGORY_ORDER)}

    def sort_key(category):
        if category in order:
            return order[category], ""
        if category.startswith("明渠-"):
            return order["暗渠"] - .5, category
        return order["其他结构"], category

    result = []
    for category in sorted(grouped, key=sort_key):
        rows = grouped[category]
        totals = {}
        for key in keys:
            values = [_number(row.get(key)) for row in rows]
            values = [value for value in values if value is not None]
            totals[key] = math.fsum(values) if values else None
        lengths = [_row_length(row) for row in rows]
        result.append({"category": category, "rows": rows, "totals": totals,
                       "asset_count": len(rows),
                       "length": math.fsum(value for value in lengths if value is not None)})
    return result
