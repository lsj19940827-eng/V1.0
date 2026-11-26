"""Carry confirmed non-open-cut construction settings onto refreshed source data."""

from copy import deepcopy
from dataclasses import dataclass
from math import isclose

from .earthwork_scope import (
    TRENCHLESS_SECTION_OVERRIDE, is_trenchless_exclusion, trenchless_edit_key,
    trenchless_exclusion, trenchless_live_route_id,
)
from .network_alignment import NetworkAlignment

_PLAN_TOLERANCE_M = 1e-5


@dataclass(frozen=True)
class _BoreLocation:
    network_index: int | None
    item_index: int
    item: dict
    record: dict
    alignment: NetworkAlignment | dict | None = None


def _bore_locations(inputs):
    """Use the same precedence as quantity calculation for duplicate identities."""
    locations = {}
    for index, record in enumerate(inputs.get("excluded", ())):
        if is_trenchless_exclusion(record) and (key := trenchless_edit_key(record)) is not None:
            locations[key] = _BoreLocation(None, index, record, record)
    for network_index, network in enumerate(inputs.get("networks", ())):
        owner = trenchless_live_route_id(network)
        for index, asset in enumerate(network.get("assets", ())):
            if not asset.get("enabled", True):
                continue
            record = trenchless_exclusion(asset, route_id=owner)
            if record is not None and (key := trenchless_edit_key(record)) is not None:
                locations[key] = _BoreLocation(network_index, index, asset, record, network.get("alignment"))
    return locations


def _plan_positions(location):
    from ..adapters.workbench_sources import trenchless_plan_alignment

    alignment = location.alignment
    try:
        if isinstance(alignment, dict):
            alignment = NetworkAlignment.from_dict(alignment)
        plan = trenchless_plan_alignment(location.record, alignment)
        if plan is not None:
            return tuple(coordinate for factor in (0., .25, .5, .75, 1.)
                         for coordinate in plan.get_xy_at_station(plan.start_station + plan.total_length * factor))
    except (AttributeError, TypeError, ValueError, KeyError, IndexError):
        return None
    return None


def _same_bore_source(current, previous):
    # A specialist crossing may replace the water-profile exclusion. Its names,
    # indices and source IDs are not interchangeable without the plan evidence.
    prefixes = {key[1].partition(":")[0] for key in (current, previous)}
    source_link = current[1] == previous[1] or prefixes == {"water_profile", "pressure"}
    return source_link and current[2] == previous[2] and all(
        isclose(a, b, abs_tol=_PLAN_TOLERANCE_M, rel_tol=0.)
        for a, b in zip(current[3:], previous[3:]))


def replay_trenchless_section_overrides(inputs, previous_inputs, *, same_project=False):
    """Keep explicit bore settings on uniquely matched objects after source refresh."""
    current_name, previous_name = inputs.get("project_name"), previous_inputs.get("project_name")
    if not same_project and current_name and previous_name and current_name != previous_name:
        return inputs
    previous = _bore_locations(previous_inputs)
    overrides = {key: location.item[TRENCHLESS_SECTION_OVERRIDE] for key, location in previous.items()
                 if location.item.get(TRENCHLESS_SECTION_OVERRIDE)}
    if not overrides:
        return inputs

    current = _bore_locations(inputs)
    exact = current.keys() & previous.keys() if same_project else set()
    matches = {key: [key] for key in exact}
    remaining = {key: _plan_positions(location) for key, location in previous.items() if key not in exact}
    for key in current.keys() - exact:
        candidates = [(other, points) for other, points in remaining.items()
                      if points and _same_bore_source(key, other)]
        if not candidates or not (points := _plan_positions(current[key])):
            continue
        matches[key] = [other for other, prior in candidates
                        if all(isclose(a, b, abs_tol=_PLAN_TOLERANCE_M, rel_tol=0.) for a, b in zip(points, prior))]

    counts = {}
    for candidates in matches.values():
        for key in candidates:
            counts[key] = counts.get(key, 0) + 1
    updates = {}
    for key, candidates in matches.items():
        if len(candidates) != 1:
            continue
        other, = candidates
        if (counts[other] == 1 and other in overrides
                and current[key].item.get(TRENCHLESS_SECTION_OVERRIDE) != overrides[other]):
            updates[key] = overrides[other]
    if not updates:
        return inputs

    result = deepcopy(inputs)
    for key, settings in updates.items():
        location = current[key]
        items = (result["excluded"] if location.network_index is None
                 else result["networks"][location.network_index]["assets"])
        items[location.item_index][TRENCHLESS_SECTION_OVERRIDE] = deepcopy(settings)
    return result
