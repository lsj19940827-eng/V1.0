"""Apply terrain coverage scope before checking supported pipe intervals."""
from copy import deepcopy
import math


def restore_workbench_automatic_ranges(inputs):
    from .unsupported_pipe_scope import AUTOMATIC_UNSUPPORTED_PIPE_FIELD, restore_automatic_exclusions
    from .unmeasured_terrain_scope import AUTOMATIC_TERRAIN_GAP_FIELD, restore_automatic_terrain_gaps
    from .tunnel_exposure_scope import TUNNEL_EXPOSED_FIELD, restore_tunnel_exposure

    if TUNNEL_EXPOSED_FIELD in inputs:
        inputs = restore_tunnel_exposure(inputs)
    if AUTOMATIC_UNSUPPORTED_PIPE_FIELD in inputs:
        inputs = restore_automatic_exclusions(inputs)
    if AUTOMATIC_TERRAIN_GAP_FIELD in inputs:
        inputs = restore_automatic_terrain_gaps(inputs)
    return inputs


def has_workbench_automatic_ranges(inputs):
    from .unsupported_pipe_scope import has_automatic_source_assets
    from .unmeasured_terrain_scope import has_terrain_gap_source_assets
    from .tunnel_exposure_scope import TUNNEL_EXPOSED_FIELD

    return (bool((inputs.get(TUNNEL_EXPOSED_FIELD) or {}).get("source_assets"))
            or has_automatic_source_assets(inputs) or has_terrain_gap_source_assets(inputs))


def prepare_workbench_automatic_ranges(tin, inputs, settings, *, cancelled=None, progress=None,
                                       collect_deferrals=False):
    from .unmeasured_terrain_scope import AUTOMATIC_TERRAIN_GAP_FIELD, apply_detected_terrain_gaps
    from .unmeasured_terrain_ranges import detect_unmeasured_terrain_ranges
    from .unsupported_pipe_calculation import prepare_automatic_unsupported_ranges
    from .workbench_calculator import _collection, workbench_requires_section_terrain

    restored = restore_workbench_automatic_ranges(inputs)
    ranges = []
    if tin is not None and workbench_requires_section_terrain(restored):
        candidate = _collection(restored)
        for index, network in enumerate(candidate["networks"], 1):
            if not network.get("network_id"):
                network["network_id"] = str(network.get("route_id") or network.get("source_identity")
                                            or network.get("name") or f"route-{index}")
        ranges = detect_unmeasured_terrain_ranges(tin, candidate, accuracy=settings,
            cancelled=cancelled, progress=progress, collect_deferrals=collect_deferrals)
    if ranges:
        from .construction_rules import normalize_construction_inputs
        from .default_section_schemes import ensure_default_section_schemes
        from .contracts import ConstructionInputError

        normalize_construction_inputs(candidate)
        candidate, defaults = ensure_default_section_schemes(candidate)
        if defaults["errors"]:
            raise ConstructionInputError("；".join(defaults["errors"]))
        inputs, report = apply_detected_terrain_gaps(candidate, ranges)
        if progress:
            progress("terrain_coverage", 1.,
                     f"已跳过{report['range_count']}处地形缺测区段，共{report['total_length_m']:.3f}m。")
    elif restored is not inputs:
        inputs = restored
    return prepare_automatic_unsupported_ranges(tin, inputs, cancelled=cancelled, progress=progress)


def skipped_workbench_section(inputs, asset_id, station, side):
    from .pipe_profile_partitions import pending_gap_section
    from .unsupported_pipe_calculation import skipped_range_at, skipped_section_record
    from .unmeasured_terrain_scope import terrain_gap_at, terrain_gap_section_record
    from .tunnel_exposure_scope import tunnel_exposure_at

    pending = pending_gap_section(inputs,asset_id,station,side)
    if pending is not None:return pending
    gap = terrain_gap_at(inputs, asset_id, station, side)
    if gap is not None:
        return terrain_gap_section_record(gap, asset_id, station, side)
    unsupported = skipped_range_at(inputs, asset_id, station, side)
    if unsupported is not None:
        return skipped_section_record(unsupported, asset_id, station, side)
    exposed = tunnel_exposure_at(inputs, asset_id, station, side)
    if exposed is not None:
        from ..io.concise_quantities import station_label
        start, end = (station_label(exposed[key]) for key in ("station_start", "station_end"))
        return {"section_id": f"skipped-{asset_id}-{station.hex()}-{side}", "asset_id": asset_id,
                "station": station, "side": side, "view_only": True, "skipped": True,
                "skip_code": exposed["code"], "excluded_range": exposed, "roles": {},
                "message": f"隧洞露顶待计 {start}～{end}，长度 {exposed['length_m']:.3f} m。"}
    return None


UNMEASURED_ONLY_INTEGRATION = "automatic_unmeasured_terrain_no_measured_sections"


def unmeasured_only_result(excluded, *, test_only=False, cancelled=None):
    from .contracts import ConstructionInputError
    from .network_section_calculator import NetworkSectionCalculationResult

    if cancelled and cancelled():
        raise ConstructionInputError("计算已取消")
    quantities = dict.fromkeys(("excavation_volume", "backfill_volume", "embankment_volume",
                               "concrete_volume", "bedding_volume", "total_fill_volume"), 0.)
    return NetworkSectionCalculationResult(
        quantities, [], [], [], [],
        {"converged": False, "convergence_checked": False, "sampling_mode": "fixed",
         "automatic_terrain_unmeasured_only": True, "overlap_policy": "independent_sections",
         "integration_method": UNMEASURED_ONLY_INTEGRATION},
        test_only=test_only, excluded_assets=deepcopy(excluded),
    )


def unmeasured_only_publishable(payload):
    from .unmeasured_terrain_scope import AUTOMATIC_TERRAIN_GAP_CODE

    validation = payload.get("validation") or {}
    rows = [row for row in payload.get("excluded_assets", [])
            if row.get("code") == AUTOMATIC_TERRAIN_GAP_CODE]
    if not (rows and payload.get("method") == "exact_tin_actual_midpoint_section_integration"
            and payload.get("integration_method") == UNMEASURED_ONLY_INTEGRATION
            and validation.get("overlap_policy") == "independent_sections"
            and all(not payload.get(k) for k in ("assets", "rows", "sections", "segments"))
            and all(payload.get(k+"_volume") == 0.
                    for k in ("excavation", "backfill", "embankment", "concrete", "bedding", "total_fill"))):
        return False
    for row in rows:
        try:
            a, b, length = (float(row[k]) for k in ("station_start", "station_end", "length_m"))
        except (KeyError, TypeError, ValueError):
            return False
        if not math.isfinite(a+b+length) or b <= a or not math.isclose(length, b-a, rel_tol=0., abs_tol=1e-9):
            return False
    return True
