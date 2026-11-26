"""Construction dimensions for the sluice gate at a hydraulic node."""
from __future__ import annotations

import math

from 推求水面线.shared.section_lining import SECTION_SUMMARY_LINING_TYPES, gate_reference_lining

from .construction_rules import structural_lining_thicknesses
from .contracts import ConstructionInputError, finite_number


DEFAULT_GATE_LINING_MULTIPLIER = 1.5
GATE_QUANTITY_METHOD = "sluice_gate_rectangular_concrete"
GATE_THICKNESS_FIELDS = ("base_thickness", "wall_thickness_left", "wall_thickness_right")
GATE_SECTION_FIELDS = ("inner_width", "inner_height", *GATE_THICKNESS_FIELDS)
GATE_FIELD_LABELS = {
    "construction.gate_length": "闸长",
    "construction.gate_lining_multiplier": "衬砌厚度倍率",
    "section.inner_width": "闸室净宽",
    "section.inner_height": "边墙高",
    "section.base_thickness": "底板厚度",
    "section.wall_thickness_left": "左边墙厚度",
    "section.wall_thickness_right": "右边墙厚度",
    "gate_station": "闸中心桩号",
}


def is_sluice_gate(asset):
    return asset.get("section_type") == "sluice_gate"


def _flow_section(asset):
    from 推求水面线.core.connection_channel import flow_section_key

    return flow_section_key(asset.get("flow_section"))


def _finite_or_none(value):
    try:
        return finite_number(value, "闸结构参数")
    except (ConstructionInputError, OverflowError):
        return None


def gate_reference_asset(inputs, network, asset):
    """Find the current part of the reference channel at the gate station."""
    source = network.get("source_identity")
    networks = [network, *(route for route in inputs.get("networks", [])
                           if route is not network and source and route.get("source_identity") == source)]
    return select_gate_reference(asset, (reference for route in networks for reference in route.get("assets", [])))


def select_gate_reference(asset, candidates):
    """Prefer the same flow section, the closest interval and then the upstream side."""
    station = _finite_or_none(asset.get("gate_station"))
    reference_id = asset.get("gate_reference_asset_id")
    flow = _flow_section(asset)
    ranked = []
    for reference in candidates:
        if reference.get("kind") not in {"open_channel", "culvert"}:
            continue
        if reference.get("transition_candidate_id") or reference.get("source_type") == "自动估算连接段":
            continue
        start, end = (_finite_or_none(reference.get(key)) for key in ("station_start", "station_end"))
        if start is None or end is None or end <= start:
            continue
        reference_flow = _flow_section(reference)
        if reference_flow != flow:
            continue
        identities = {reference.get(key) for key in ("asset_id", "source_identity",
            "section_scheme_root_asset_id", "drawing_root_asset_id", "parent_asset_id")}
        is_chosen = reference_id is not None and reference_id in identities
        if station is None and not is_chosen:
            continue
        distance = max(start - station, station - end, 0.) if station is not None else 0.
        downstream = start >= station if station is not None else False
        ranked.append(((distance, downstream, not is_chosen), reference))
    return min(ranked, key=lambda item: item[0])[1] if ranked else None


def reference_gate_dimensions(reference):
    if reference is None:
        return {}
    section = reference.get("section") or {}
    width = _finite_or_none(section.get("inner_width"))
    height = _finite_or_none(section.get("wall_height")) or _finite_or_none(section.get("inner_height"))
    diameter = _finite_or_none(section.get("inner_diameter"))
    radius = _finite_or_none(section.get("inner_radius"))
    if not diameter and radius and radius > 0:
        diameter = 2 * radius
    if reference.get("section_type") == "circular_culvert" and diameter and diameter > 0:
        width = height = diameter
    if reference.get("section_type") == "u_channel" and (width is None or width <= 0):
        width = diameter
    return {key: value for key, value in (("inner_width", width), ("inner_height", height))
            if value is not None and value > 0 and math.isfinite(value)}


def reference_gate_lining(asset, reference=None):
    """Prefer the neighboring water-profile section over the project channel settings."""
    lining = dict(asset.get("water_profile_lining") or {})
    if "water_profile_lining" not in asset and str(asset.get("source_type") or "").strip().endswith("闸"):
        lining = gate_reference_lining("rect_channel")
    if reference is None:
        return lining
    if "water_profile_lining" in reference:
        adjacent = reference["water_profile_lining"] or {}
    else:
        # Older sources carry the section values but no dedicated water-profile
        # field. Use their actual lining, skipping workbench construction assumptions.
        sources = reference.get("parameter_sources") or {}
        section = {key: value for key, value in (reference.get("section") or {}).items()
                   if not str(sources.get(f"section.{key}", "")).startswith("施工参数假定")}
        section_kind = SECTION_SUMMARY_LINING_TYPES.get(reference.get("source_type"))
        adjacent = gate_reference_lining(section_kind)
        adjacent.update({key: value for key, value in
                         structural_lining_thicknesses({**reference, "section": section}).items() if value is not None})
    lining.update({key: value for key, value in adjacent.items() if value is not None})
    return lining


def resolve_gate_section(asset, reference=None):
    """Resolve empty fields from the current reference without editing either input."""
    section = dict(asset.get("section") or {})
    for key, value in reference_gate_dimensions(reference).items():
        if section.get(key) in (None, ""):
            section[key] = value
    construction = asset.get("construction") or {}
    multiplier = _finite_or_none(construction.get(
        "gate_lining_multiplier", DEFAULT_GATE_LINING_MULTIPLIER))
    if multiplier is None or multiplier <= 0:
        return section
    thicknesses = reference_gate_lining(asset, reference)
    for key in GATE_THICKNESS_FIELDS:
        thickness = _finite_or_none(thicknesses.get(key))
        if section.get(key) in (None, "") and thickness is not None and thickness > 0:
            derived = thickness * multiplier
            if math.isfinite(derived):
                section[key] = derived
    return section


def gate_station_range(asset):
    center = _finite_or_none(asset.get("gate_station"))
    length = _finite_or_none((asset.get("construction") or {}).get("gate_length"))
    if center is None or length is None or length <= 0:
        return None, None
    start, end = center - length / 2, center + length / 2
    return (start, end) if math.isfinite(start) and math.isfinite(end) and start < end else (None, None)


def gate_missing_fields(asset, reference=None):
    section = resolve_gate_section(asset, reference)
    fields = [(f"section.{key}", section.get(key)) for key in GATE_SECTION_FIELDS]
    construction = asset.get("construction") or {}
    fields.append(("construction.gate_length", construction.get("gate_length")))
    if any((asset.get("section") or {}).get(key) in (None, "") for key in GATE_THICKNESS_FIELDS):
        fields.append(("construction.gate_lining_multiplier",
                       construction.get("gate_lining_multiplier", DEFAULT_GATE_LINING_MULTIPLIER)))
    missing = [path for path, value in fields if (_finite_or_none(value) or 0.) <= 0.]
    if _finite_or_none(asset.get("gate_station")) is None:
        missing.append("gate_station")
    elif "construction.gate_length" not in missing and gate_station_range(asset) == (None, None):
        missing.append("construction.gate_length")
    return missing


def gate_quantity_items(asset, reference=None):
    if gate_missing_fields(asset, reference):
        return []
    section = resolve_gate_section(asset, reference)
    width, height, base, left, right = (float(section[field]) for field in GATE_SECTION_FIELDS)
    length = float(asset["construction"]["gate_length"])
    start, end = gate_station_range(asset)
    volume_dimensions = (
        ("gate_base_slab", "闸底板混凝土", width + left + right, base, "闸长 ×（闸室净宽＋左右边墙厚度）× 底板厚度"),
        ("gate_left_wall", "闸左边墙混凝土", left, height, "闸长 × 左边墙厚度 × 边墙高"),
        ("gate_right_wall", "闸右边墙混凝土", right, height, "闸长 × 右边墙厚度 × 边墙高"),
    )
    dimensions = {key: float(section[key]) for key in GATE_SECTION_FIELDS}
    dimensions["gate_length"] = length
    dimensions["gate_station"] = float(asset["gate_station"])
    if reference is not None:
        dimensions["reference_asset_id"] = reference.get("asset_id")
    shared = {"asset_id": asset["asset_id"], "original_asset_id": asset["asset_id"],
              "asset_name": asset.get("name", ""), "section_type": "sluice_gate", "kind": "gate",
              "station_start": start, "station_end": end, "length_m": length, "flow_section": asset.get("flow_section"),
              "quantity_basis_label": "矩形截面积乘闸长",
              "method": GATE_QUANTITY_METHOD, "material": "concrete", "grade": section.get("concrete_grade") or "",
              "unit": "m3", "geometry_included": False, "status": "current_construction_parameters"}
    items = [{**shared, "component_id": key, "name": label, "quantity": length * breadth * depth,
              "formula": formula, "input_snapshot": dict(dimensions)}
             for key, label, breadth, depth, formula in volume_dimensions]
    if any(not math.isfinite(item["quantity"]) for item in items):
        raise ConstructionInputError("闸混凝土量超出有效数值范围")
    return items


def workbench_gate_quantities(inputs):
    """Return measured sluice gate components and the outstanding dimensions."""
    networks = inputs.get("networks", [inputs])
    gates = [(network, asset) for network in networks for asset in network.get("assets", [])
             if is_sluice_gate(asset) and asset.get("enabled", True)]
    if not gates:
        return [], []
    from .workbench_automatic_ranges import restore_workbench_automatic_ranges

    # Automatic terrain rules may temporarily remove the reference channel's cut,
    # while its adopted concrete thickness remains the gate's design basis.
    references = restore_workbench_automatic_ranges(inputs)
    items, pending = [], []
    for network, asset in gates:
        route = str(network.get("route_id") or network.get("network_id") or network.get("name", ""))
        reference_network = next((entry for entry in references.get("networks", [references])
                                  if (entry.get("route_id") or entry.get("network_id") or entry.get("name", "")) == route), network)
        reference = gate_reference_asset(references, reference_network, asset)
        missing = gate_missing_fields(asset, reference)
        if missing:
            pending.append({"route_id": route, "asset_id": asset["asset_id"], "name": asset.get("name"),
                            "status": "pending", "message": "填写" + "、".join(GATE_FIELD_LABELS[path] for path in missing)})
            continue
        items.extend({**item, "route_id": route} for item in gate_quantity_items(asset, reference))
    return items, pending


def workbench_has_ready_gates(inputs):
    return bool(workbench_gate_quantities(inputs)[0])


def gate_only_publishable(payload):
    items = [item for item in payload.get("quantity_items") or [] if item.get("method") == GATE_QUANTITY_METHOD]
    return (payload.get("integration_method") == GATE_QUANTITY_METHOD and bool(items)
            and not any(payload.get(key) for key in ("assets", "rows", "sections", "segments"))
            and all(payload.get(key) == 0. for key in ("excavation_volume", "backfill_volume", "embankment_volume")))


def gate_quantities_match_snapshot(payload, source):
    items = [item for item in payload.get("quantity_items") or [] if item.get("method") == GATE_QUANTITY_METHOD]
    try:
        expected, _ = workbench_gate_quantities(source)
    except (KeyError, TypeError, ValueError):
        return False
    return items == expected
