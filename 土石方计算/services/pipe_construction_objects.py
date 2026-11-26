"""Construction objects retain the individual asset keys used by calculation."""
from __future__ import annotations

from collections import defaultdict

from .batch_cover_profiles import is_pressure_cover_asset
from .construction_rules import is_circular_culvert
from .earthwork_scope import (
    _number, trenchless_exclusions, trenchless_method, trenchless_range_covered,
)
from .imported_design_profiles import _route_fingerprint, _route_namespace
from .section_scheme_bindings import _root, _route
from .siphon_axis_choices import is_siphon_axis_asset


_UNNAMED_PIPE = {"", "-", "—", "/", "未命名", "有压管道", "管道"}


def _construction_object(asset):
    return (asset.get("enabled", True) and asset.get("kind") != "tunnel"
            and (is_pressure_cover_asset(asset) or is_circular_culvert(asset))
            and not trenchless_method(asset))


def _pressure_run(asset):
    return is_pressure_cover_asset(asset) and not is_siphon_axis_asset(asset)


def _pressure_name(asset):
    values = (str(asset.get(field) or "").strip() for field in ("base_name", "name"))
    return next((value for value in values if value not in _UNNAMED_PIPE), "")


def _source_route_key(network, route_id):
    namespace = _route_namespace(network)
    fingerprint = _route_fingerprint(network)
    if namespace[0] and fingerprint:
        return namespace, fingerprint, network.get("station_prefix")
    return route_id


def _start(member):
    start = _number(member[1].get("station_start"))
    return start if start is not None else float("inf")


def _linked(previous, following, exclusions):
    owner, before = previous[-1]
    _, after = following[0]
    if not (_pressure_run(before) and _pressure_run(after)):
        return False
    previous_name = next((name for _, asset in reversed(previous) if (name := _pressure_name(asset))), "")
    following_name = next((name for _, asset in following if (name := _pressure_name(asset))), "")
    if previous_name and following_name and previous_name != following_name:
        return False
    return trenchless_range_covered(exclusions, owner, _number(before.get("station_end")),
                                    _number(after.get("station_start")))


def construction_objects(inputs):
    """Map each display key to its source (network, asset) members in station order."""
    return _group_objects(inputs, _construction_object)


def pipe_objects_by_scope(inputs):
    return _group_objects(inputs, lambda asset: is_pressure_cover_asset(asset) and not trenchless_method(asset))


def _group_objects(inputs, include):
    roots = {}
    route_keys = {}
    for network in inputs.get("networks", []):
        route_id = _route(network) or str(network.get("source_identity") or "")
        if not route_id:
            continue
        for asset in network.get("assets", []):
            root = _root(asset)
            if root and include(asset):
                key = route_id, root
                roots.setdefault(key, []).append((network, asset))
                if id(network) not in route_keys:
                    route_keys[id(network)] = _source_route_key(network, route_id)

    by_source_route = defaultdict(list)
    for key, members in roots.items():
        members.sort(key=_start)
        by_source_route[route_keys[id(members[0][0])]].append((key, members))

    exclusions = trenchless_exclusions(inputs)
    objects = {}
    for route_objects in by_source_route.values():
        combined = None
        for key, members in sorted(route_objects, key=lambda item: _start(item[1][0])):
            if combined and _linked(combined, members, exclusions):
                combined.extend(members)
            else:
                combined = members
                objects[key] = combined
    return objects
