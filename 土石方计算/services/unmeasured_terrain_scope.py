"""Reversible station boundaries for unavailable surveyed terrain."""
from copy import deepcopy

from .unsupported_pipe_scope import (
    AUTOMATIC_UNSUPPORTED_PIPE_FIELD,
    _RangeScopePolicy,
    apply_detected_exclusions,
    automatic_scope_matches_snapshot,
    automatic_scope_report,
    has_automatic_source_assets,
    restore_automatic_exclusions,
)


AUTOMATIC_TERRAIN_GAP_CODE = "survey_terrain_unmeasured"
AUTOMATIC_TERRAIN_GAP_FIELD = "terrain_unmeasured_ranges"
AUTOMATIC_TERRAIN_GAP_POLICY = "automatic_terrain_gaps_v1"
_SCOPE = _RangeScopePolicy(
    AUTOMATIC_TERRAIN_GAP_POLICY, AUTOMATIC_TERRAIN_GAP_CODE,
    AUTOMATIC_TERRAIN_GAP_FIELD, "automatic_terrain_gap_origin",
    "automatic_terrain_gap_inactive_drawings", "地形缺测区段", "surveyed",
    "unmeasured", "地形缺测", terrain_gaps=True,
)
_ASSET_ALIASES = (
    "asset_id", "source_asset_id", "parent_asset_id", "source_original_asset_id",
    "original_asset_id", "drawing_root_asset_id", "section_scheme_root_asset_id",
)


def restore_automatic_terrain_gaps(inputs):
    """Return the user-owned selected ranges before re-evaluating the terrain."""
    return restore_automatic_exclusions(inputs, _policy=_SCOPE)


def apply_detected_terrain_gaps(inputs, detected_ranges):
    """Split surveyed sections at the missing spans without changing their design."""
    return apply_detected_exclusions(inputs, detected_ranges, _policy=_SCOPE)


def has_terrain_gap_source_assets(inputs):
    return has_automatic_source_assets(inputs, _policy=_SCOPE)


def terrain_gap_scope_report(inputs):
    return automatic_scope_report(inputs, _policy=_SCOPE)


def terrain_gap_scope_matches_snapshot(payload, source):
    """Check gap scope after undoing the later, independently bound floating cuts."""
    if AUTOMATIC_UNSUPPORTED_PIPE_FIELD in source:
        try:
            source = restore_automatic_exclusions(source)
        except (KeyError, TypeError, ValueError):
            return False
    return automatic_scope_matches_snapshot(payload, source, _policy=_SCOPE)


def _aliases(record, fields):
    return {str(record[k]) for k in fields if record.get(k)}


def _matches_owner(asset_id, row, inputs, *, origin=None):
    routes = _aliases(row, ("network_id", "route_id"))
    owners = _aliases(row, _ASSET_ALIASES)
    if asset_id in owners or any(asset_id == f"{route}::{owner}" for route in routes for owner in owners):
        return True
    for network in inputs.get("networks", []):
        if not routes.intersection(_aliases(network, ("network_id", "route_id", "source_identity"))):
            continue
        for asset in network.get("assets", []):
            key = asset.get("asset_id")
            if asset_id != key and not any(asset_id == f"{route}::{key}" for route in routes):
                continue
            source_ref = (asset.get(origin) or {}).get("source_asset_ref") if origin else None
            if source_ref and source_ref == row.get("source_asset_ref"):
                return True
            # A retained child identifies the rest of the original building.
            if owners.intersection(_aliases(asset, _ASSET_ALIASES)):
                return True
    return False


def terrain_gap_at(inputs, asset_id, station, side="right"):
    """Find a saved gap from an original, retained, or excluded asset ID."""
    state = inputs.get(AUTOMATIC_TERRAIN_GAP_FIELD)
    if not isinstance(state, dict) or state.get("policy") != AUTOMATIC_TERRAIN_GAP_POLICY:
        return None
    matches = []
    for row in state["ranges"]:
        a, b = row["station_start"], row["station_end"]
        if not (a < station < b or station == a and side == "right" or station == b and side == "left"):
            continue
        if _matches_owner(asset_id, row, inputs):
            matches.append(row)
    return deepcopy(matches[0]) if len(matches) == 1 else None


def terrain_gap_section_record(row, asset_id, station, side="right"):
    from ..io.concise_quantities import station_label
    start = station_label(row["station_start"])
    end = station_label(row["station_end"])
    return {
        "section_id": f"skipped-{asset_id}-{float(station).hex()}-{side}",
        "asset_id": asset_id, "station": float(station), "side": side, "view_only": True,
        "skipped": True, "skip_code": AUTOMATIC_TERRAIN_GAP_CODE,
        "excluded_range": deepcopy(row), "roles": {},
        "message": f"地形缺测区段 {start}～{end}，长度 {row['length_m']:.3f} m，已跳过。",
    }
