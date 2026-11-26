"""Reversible pending ranges for underground tunnel sections that daylight."""
from copy import deepcopy
import math

from .unsupported_pipe_scope import (
    _RangeScopePolicy, apply_detected_exclusions, automatic_scope_matches_snapshot,
    automatic_scope_report, restore_automatic_exclusions,
)


TUNNEL_EXPOSED_CODE = "tunnel_exposed"
TUNNEL_EXPOSED_FIELD = "tunnel_exposed_ranges"
TUNNEL_EXPOSED_ONLY = "automatic_tunnel_exposed_only"
TUNNEL_EXPOSURE_ORIGIN = "automatic_tunnel_exposure_origin"
_ONLY_INTEGRATION = "automatic_tunnel_exposure_no_measured_sections"
_SCOPE = _RangeScopePolicy(
    "automatic_tunnel_exposure_v1", TUNNEL_EXPOSED_CODE, TUNNEL_EXPOSED_FIELD,
    TUNNEL_EXPOSURE_ORIGIN, "automatic_tunnel_exposure_inactive_drawings",
    "隧洞露顶待计区段", "buried", "daylight",
    "暗挖隧洞开挖轮廓穿出原地面，待核明暗挖分界和明挖施工断面", terrain_gaps=True,
)


def restore_tunnel_exposure(inputs):
    return restore_automatic_exclusions(inputs, _policy=_SCOPE)


def apply_tunnel_exposure(inputs, ranges):
    return apply_detected_exclusions(inputs, ranges, _policy=_SCOPE)


def tunnel_exposure_report(inputs):
    return automatic_scope_report(inputs, _policy=_SCOPE)


def tunnel_scope_matches_snapshot(payload, inputs):
    return automatic_scope_matches_snapshot(payload, inputs, _policy=_SCOPE)


def scope_tunnel_quantity_rules(source, retained_assets):
    from .aqueduct_components import quantity_rule_items

    retained = {}
    for asset in retained_assets:
        origin = asset.get(TUNNEL_EXPOSURE_ORIGIN)
        if origin:
            retained.setdefault(origin["source_asset_ref"], []).append(asset)
    rules_by_part = {}
    issues = []
    for original in (source.get(TUNNEL_EXPOSED_FIELD) or {}).get("source_assets", []):
        tunnel = original["asset"]
        parts = retained.get(original["source_asset_ref"], [])
        for item in quantity_rule_items(tunnel):
            part = next((candidate for candidate in parts
                         if candidate["station_start"]-1e-8 <= item["station_start"]
                         and item["station_end"] <= candidate["station_end"]+1e-8), None)
            if part is not None:
                rules_by_part.setdefault(part["asset_id"], []).append({**item, "asset_id": part["asset_id"]})
            else:
                issues.append({"asset_id": tunnel["asset_id"], "name": tunnel.get("name"),
                               "route_id": original["network_id"], "status": "pending",
                               "station_start": item["station_start"], "station_end": item["station_end"],
                               "message": f"{item['name']}需按隧洞待计区段复核分项数量"})
    return rules_by_part, issues


def exposed_tunnel_only_result(excluded, *, test_only=False):
    from .network_section_calculator import NetworkSectionCalculationResult

    quantities = dict.fromkeys(("excavation_volume", "backfill_volume", "embankment_volume",
                               "concrete_volume", "bedding_volume", "total_fill_volume"), 0.)
    return NetworkSectionCalculationResult(quantities, [], [], [], [], {
        "converged": False, "convergence_checked": False, "sampling_mode": "fixed",
        TUNNEL_EXPOSED_ONLY: True, "overlap_policy": "independent_sections",
        "integration_method": _ONLY_INTEGRATION,
    }, test_only=test_only, excluded_assets=deepcopy(excluded))


def exposed_tunnel_only_publishable(payload):
    rows = [r for r in payload.get("excluded_assets", []) if r.get("policy") == _SCOPE.key]
    if not (rows and payload.get("method") == "exact_tin_actual_midpoint_section_integration"
            and payload.get("integration_method") == _ONLY_INTEGRATION
            and (payload.get("validation") or {}).get("overlap_policy") == "independent_sections"
            and all(not payload.get(k) for k in ("assets", "rows", "sections", "segments"))
            and all(payload.get(k+"_volume") == 0.
                    for k in ("excavation", "backfill", "embankment", "concrete", "bedding", "total_fill"))):
        return False
    for row in rows:
        try:
            a, b, length = (float(row[k]) for k in ("station_start", "station_end", "length_m"))
        except (KeyError, TypeError, ValueError):
            return False
        if (row.get("code") != TUNNEL_EXPOSED_CODE or not math.isfinite(a+b+length) or b <= a
                or not math.isclose(b-a, length, rel_tol=0., abs_tol=1e-9)):
            return False
    return True


def tunnel_exposure_at(inputs, asset_id, station, side):
    from .unmeasured_terrain_scope import _matches_owner

    state = inputs.get(TUNNEL_EXPOSED_FIELD) or {}
    matches = [row for row in state.get("ranges", [])
               if (row["station_start"] <= station < row["station_end"] if side == "right"
                   else row["station_start"] < station <= row["station_end"])
               and _matches_owner(asset_id, row, inputs)]
    return deepcopy(matches[0]) if len(matches) == 1 else None
