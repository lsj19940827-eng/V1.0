"""Automatic unsupported-range preparation shared by calculation entry points."""
from __future__ import annotations

from copy import deepcopy
import math

from .contracts import ConstructionInputError
from .unsupported_pipe_scope import (
    AUTOMATIC_UNSUPPORTED_PIPE_CODE, AUTOMATIC_UNSUPPORTED_PIPE_FIELD,
    apply_detected_exclusions, automatic_scope_report, restore_automatic_exclusions,
)


UNSUPPORTED_ONLY_INTEGRATION = "automatic_unsupported_ranges_no_measured_sections"


def prepare_automatic_unsupported_ranges(tin, inputs, *, cancelled=None, progress=None):
    """Re-evaluate the original selected ranges against this run's actual TIN."""
    from .workbench_calculator import _collection
    from .default_section_schemes import ensure_default_section_schemes
    from .unsupported_pipe_ranges import detect_unsupported_ranges

    def check():
        if cancelled and cancelled():
            raise ConstructionInputError("计算已取消")
    check()
    previous = bool(inputs.get(AUTOMATIC_UNSUPPORTED_PIPE_FIELD))
    restored = restore_automatic_exclusions(_collection(inputs))
    if tin is None:
        return restored if previous else inputs
    for index, network in enumerate(restored.get("networks", [])):
        if not network.get("network_id"):
            network["network_id"] = str(network.get("route_id") or network.get("source_identity")
                or network.get("name") or f"network-{index}")
    candidate, defaults = ensure_default_section_schemes(restored)
    if defaults["errors"]:
        raise ConstructionInputError("；".join(defaults["errors"]))
    ranges = detect_unsupported_ranges(tin, candidate, cancelled=cancelled, progress=progress)
    check()
    if not ranges and not previous:
        return inputs
    prepared, report = apply_detected_exclusions(candidate, ranges)
    if ranges and progress:
        progress("unsupported_ranges", 1.,
            f"已跳过{report['range_count']}处悬空区段，共{report['total_length_m']:.3f}m。")
    return prepared


def attach_automatic_scope(payload, source):
    if AUTOMATIC_UNSUPPORTED_PIPE_FIELD not in source:
        return payload
    report = automatic_scope_report(source)
    if report is not None:
        payload[AUTOMATIC_UNSUPPORTED_PIPE_FIELD] = deepcopy(report)
    return payload


def unsupported_only_result(excluded, *, test_only=False, cancelled=None):
    """An empty measured scope still produces its complete skipped-range table."""
    from .network_section_calculator import NetworkSectionCalculationResult
    if cancelled and cancelled():
        raise ConstructionInputError("计算已取消")
    if not any(r.get("code") == AUTOMATIC_UNSUPPORTED_PIPE_CODE for r in excluded):
        raise ConstructionInputError("没有可计量的断面")
    quantities = dict.fromkeys(("excavation_volume", "backfill_volume", "embankment_volume",
        "concrete_volume", "bedding_volume", "total_fill_volume"), 0.)
    return NetworkSectionCalculationResult(quantities, [], [], [], [],
        {"converged": False, "convergence_checked": False, "sampling_mode": "fixed",
         "automatic_unsupported_only": True, "overlap_policy": "independent_sections",
         "integration_method": UNSUPPORTED_ONLY_INTEGRATION},
        test_only=test_only, excluded_assets=deepcopy(excluded))


def unsupported_only_publishable(payload):
    """Validate the empty scope explicitly rather than inventing zero-area cuts."""
    from .unsupported_pipe_scope import AUTOMATIC_UNSUPPORTED_PIPE_POLICY
    validation = payload.get("validation") or {}
    automatic = [r for r in payload.get("excluded_assets", [])
        if r.get("code") == AUTOMATIC_UNSUPPORTED_PIPE_CODE]
    if not (validation.get("automatic_unsupported_only") is True and automatic
            and payload.get("method") == "exact_tin_actual_midpoint_section_integration"
            and payload.get("integration_method") == UNSUPPORTED_ONLY_INTEGRATION
            and validation.get("overlap_policy") == "independent_sections"
            and all(not payload.get(k) for k in ("assets", "rows", "sections", "segments"))
            and all(payload.get(k + "_volume") == 0. for k in
                ("excavation", "backfill", "embankment", "concrete", "bedding", "total_fill"))):
        return False
    for row in automatic:
        try:
            a, b, length = (float(row[k]) for k in ("station_start", "station_end", "length_m"))
            if (row.get("policy") != AUTOMATIC_UNSUPPORTED_PIPE_POLICY
                    or not math.isfinite(a + b + length) or b <= a
                    or not math.isclose(length, b-a, abs_tol=1e-9, rel_tol=0)):
                return False
        except (KeyError, TypeError, ValueError):
            return False
    return True


def skipped_range_at(inputs, asset_id, station, side="right"):
    """Return a saved automatic interval without creating an artificial section."""
    from .unmeasured_terrain_scope import _matches_owner
    from .unsupported_pipe_scope import _ORIGIN

    if AUTOMATIC_UNSUPPORTED_PIPE_FIELD not in inputs:
        return None
    rows = automatic_scope_report(inputs)
    if not rows:
        return None
    matches=[]
    for row in rows.get("ranges", []):
        a, b = row["station_start"], row["station_end"]
        in_range = a <= station < b if side == "right" else a < station <= b
        if in_range and _matches_owner(asset_id, row, inputs, origin=_ORIGIN):
            matches.append(row)
    return deepcopy(matches[0]) if len(matches)==1 else None


def skipped_section_record(row, asset_id, station, side="right"):
    from ..io.concise_quantities import station_label
    message=(f"悬空区段 {station_label(row['station_start'])}～{station_label(row['station_end'])}，"
        f"长度{row['length_m']:.3f}m，已跳过。")
    return {"section_id":f"skipped-{asset_id}-{float(station).hex()}-{side}",
        "asset_id":asset_id,"station":float(station),"side":side,"view_only":True,
        "skipped":True,"skip_code":AUTOMATIC_UNSUPPORTED_PIPE_CODE,
        "excluded_range":deepcopy(row),"message":message,"roles":{}}
