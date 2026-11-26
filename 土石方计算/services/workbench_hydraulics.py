"""Adopt known hydraulic input values for the construction sizing calculator."""
from __future__ import annotations

import math

from 推求水面线.core.connection_channel import flow_section_key


_FIELDS = {
    "flow": ("flow", "Q"),
    "increase_percent": ("increase_percent",),
    "roughness": ("roughness", "n"),
    "slope_inverse": ("slope_inverse", "slope_inv"),
    "minimum_velocity": ("minimum_velocity", "v_min"),
    "maximum_velocity": ("maximum_velocity", "v_max"),
    "bottom_width": ("bottom_width", "B"),
    "max_flow": ("max_flow", "Q_max", "Q_increased"),
}
_ALLOW_ZERO = {"increase_percent", "minimum_velocity"}


def _number(value, *, zero=False):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and (number > 0 or zero and number == 0) else None


def _node_values(node):
    section = node.get("section_params") or {}
    values = {}
    for field, aliases in _FIELDS.items():
        candidates = (layer.get(key) for layer in (node, section) for key in aliases)
        value = next((number for candidate in candidates
                      if (number := _number(candidate, zero=field in _ALLOW_ZERO)) is not None), None)
        if value is not None:
            values[field] = value
    slope = _number(node.get("slope_i"))
    if slope and math.isfinite(inverse := 1. / slope):
        values.setdefault("slope_inverse", inverse)
    return values


def _setting_flow(settings, flow_section, list_keys, single_keys):
    for key in list_keys:
        values = settings.get(key)
        if not isinstance(values, (list, tuple)) or not values:
            continue
        index = int(flow_section) - 1 if flow_section.isdecimal() else -1
        if not flow_section and len(values) == 1:
            index = 0
        return _number(values[index]) if 0 <= index < len(values) else None
    if flow_section in {"", "1"}:
        return next((number for key in single_keys if (number := _number(settings.get(key))) is not None), None)
    return None


def _common_value(references, key):
    values = [item[key] for item in references if key in item]
    if values and all(math.isclose(value, values[0], rel_tol=1e-9, abs_tol=1e-12) for value in values):
        return values[0]
    return None


def channel_calculator_defaults(source, *, flow_section=None, settings=None, references=()):
    """Fill calculator inputs from the source and corroborating values in its flow section."""
    settings = settings or {}
    segment = flow_section_key(source.get("flow_section") if flow_section is None else flow_section)
    values = _node_values(source)
    peers = [_node_values(node) for node in references if flow_section_key(node.get("flow_section")) == segment]
    design_flow = _setting_flow(settings, segment, ("设计流量列表", "design_flows"), ("设计流量", "design_flow"))
    if "flow" not in values:
        flow = _common_value(peers, "flow") or design_flow
        if flow is not None:
            values["flow"] = flow
    flow = values.get("flow")
    maximum = values.pop("max_flow", None)
    if flow is not None and "increase_percent" not in values:
        compatible = [item for item in peers if math.isclose(item.get("flow", 0.), flow, rel_tol=1e-9)]
        if maximum is None and design_flow is not None and math.isclose(flow, design_flow, rel_tol=1e-9):
            maximum = _setting_flow(settings, segment, ("加大流量列表", "max_flows"), ("加大流量", "max_flow"))
        if maximum is None:
            maximum = _common_value(compatible, "max_flow")
        if maximum is not None and maximum >= flow:
            proportion = (maximum - flow) / flow * 100.
            if math.isfinite(proportion):
                values["increase_percent"] = round(proportion, 10)
        elif maximum is None:
            proportion = _common_value(compatible, "increase_percent")
            if proportion is not None:
                values["increase_percent"] = proportion
    for field in ("roughness", "slope_inverse", "minimum_velocity", "maximum_velocity", "bottom_width"):
        if field not in values and (value := _common_value(peers, field)) is not None:
            values[field] = value
    if "roughness" not in values:
        roughness = _number(settings.get("糙率", settings.get("roughness")))
        if roughness is not None:
            values["roughness"] = roughness
    return values
