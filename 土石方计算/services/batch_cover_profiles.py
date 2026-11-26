"""Pure batch preparation of terrain-derived pipe profiles and confirmations.

This module is shared by the desktop and file runners.  It does not import Qt,
open dialogs, read files, or replace hydraulic design elevations of channels.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math

from .earthwork_scope import trenchless_exclusion, trenchless_method

AUTOMATIC_ENGINEERING_COVER_POLICY = "single_centered_pipe_engineering_2m_v1"
DEFAULT_WORKBENCH_COVER_M = 2.5
ENGINEERING_COVER_CONTROL_STEP_M = 2.
# These quantity revisions share the same confirmed cover profile geometry.
_COMPATIBLE_COVER_CONTRACTS = {
    "workbench_engineering_sections_4.12_automatic_unsupported_ranges": (
        "workbench_engineering_sections_4.11_trenchless_bore",
        "workbench_engineering_sections_4.10_special_pipe_material_lengths",
    ),
}
# Keep in sync with the effective survey defaults in independent_terrain.py.
_COVER_TERRAIN_DEFAULTS = {
    "conflict_policy": "points_priority",
    "duplicate_point_policy": "max",
    "contour_crossing_policy": "release_conflicting_segments",
    "automatic_boundary": True,
    "boundary_gap_factor": 4.,
    "filter_elevation_outliers": True,
}


def generate_workbench_cover_preview(tin, alignment, pipes, *, cover_depth,
        cover_segments=None, spacing=0., sample_step=10., generation_options=None, cancelled=None):
    """Use the existing continuous 2 m control axis for an ordinary single pipe.

    Profile controls are independent of earthwork section spacing. Explicit
    exact generation and multi-pipe/offset layouts retain their existing path;
    no continuity tolerance or terrain-coverage requirement is relaxed here.
    """
    from .design_profiles import generate_cover_profile, prepare_pipe_layout
    options = dict(generation_options or {})
    requested_policy = options.pop("sampling_policy", None)
    layout = prepare_pipe_layout(pipes, spacing)
    applicable = len(layout) == 1 and abs(float(layout[0]["offset"])) <= 1e-8
    automatic = applicable and requested_policy in {None, "engineering"}
    policy = "engineering" if automatic else (requested_policy or "exact")
    if policy == "engineering" and not applicable:
        policy = "exact"
    control_step = ENGINEERING_COVER_CONTROL_STEP_M if automatic else float(sample_step)
    preview = generate_cover_profile(tin, alignment, pipes, cover_depth=cover_depth,
        cover_segments=cover_segments, spacing=spacing, sample_step=control_step,
        sampling_policy=policy, cancelled=cancelled, **options)
    if not preview.get("valid") or not preview.get("design_profile"):
        return preview
    covers, excess = [], []
    for sample in preview.get("samples", []):
        target = float(sample["requested_cover"])
        for pipe in sample.get("pipes", []):
            limits = pipe.get("side_limits") or [pipe]
            for limit in limits:
                value = float(limit.get("actual_cover", pipe["actual_cover"]))
                covers.append(value)
                excess.append(value-target)
    summary = {"basis": "saved_profile_control_point_real_pipe_top_samples",
        "sample_count": len(covers),
        "minimum_sampled_actual_cover_m": min(covers) if covers else None,
        "maximum_sampled_actual_cover_m": max(covers) if covers else None,
        "minimum_additional_probe_cover_m": preview.get("minimum_checked_cover"),
        "minimum_sampled_excess_cover_m": min(excess) if excess else None,
        "maximum_sampled_excess_cover_m": max(excess) if excess else None}
    if excess:
        import numpy as np
        summary.update(mean_sampled_excess_cover_m=float(np.mean(excess)),
            median_sampled_excess_cover_m=float(np.median(excess)),
            p95_sampled_excess_cover_m=float(np.quantile(excess, .95)))
    metadata = {"sampling_policy": policy, "control_step_m": control_step,
        "requested_sample_step_m": float(sample_step),
        "earthwork_section_spacing_changed": False,
        "automatic_policy": AUTOMATIC_ENGINEERING_COVER_POLICY if automatic else None}
    preview.update(sampling_policy=policy, control_step_m=control_step,
        cover_generation_options=metadata, actual_cover_summary=summary)
    if automatic:
        preview.setdefault("diagnostics", []).append({"code": "automatic_continuous_pipe_cover",
            "severity": "info", "message": "单管按2m纵断面控制点自动生成连续管轴，土方断面间距保持当前设置；按实际管顶复核目标最小覆土，并保留地形造成的覆土余量。"})
    return preview


def bind_cover_generation_metadata(asset, preview):
    """Persist only a newly generated preview's actual method and deviations."""
    if preview.get("cover_generation_options"):
        asset["cover_generation_options"] = deepcopy(preview["cover_generation_options"])
        asset["cover_actual_cover_summary"] = deepcopy(preview.get("actual_cover_summary") or {})


def cover_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    allow_nan=False, default=str).encode("utf8")).hexdigest()


def cover_parameters(network, asset, sample_step):
    """Return the same canonical generation parameters used by the desktop."""
    if network is None or network.get("alignment") is None:
        raise ValueError("先补齐真实平面轴线")
    from .design_profiles import clip_alignment, prepare_pipe_layout
    section = asset.get("section", {})
    pipes = section.get("pipes")
    if not pipes:
        count = float(section.get("pipe_count", 1))
        if not math.isfinite(count) or count < 1 or count != int(count):
            raise ValueError("管数须为正整数")
        pipes = [deepcopy(section) for _ in range(int(count))]
    else:
        pipes = deepcopy(pipes)
    mode = asset.get("cover_pipe_layout_mode")
    if mode not in {"spacing", "explicit_offsets"}:
        mode = "explicit_offsets" if any(p.get("offset") is not None for p in pipes) else "spacing"
    if mode == "spacing":
        for pipe in pipes:
            pipe.pop("offset", None)
    spacing = section.get("pipe_spacing")
    if spacing is None:
        if len(pipes) > 1:
            if not all(p.get("offset") is not None for p in pipes):
                raise ValueError("多管需明确管间净距，或提供每根管的真实横向偏距，再生成埋深预览")
            spacing = [float(b["offset"])-float(a["offset"])-(float(a["outer_diameter"])+float(b["outer_diameter"]))/2
                       for a, b in zip(pipes, pipes[1:])]
        else:
            spacing = 0.
    layout = prepare_pipe_layout(pipes, spacing)
    if mode == "explicit_offsets":
        gaps = list(spacing) if isinstance(spacing, (list, tuple)) else [spacing]*(len(layout)-1)
        actual = [b["offset"]-a["offset"]-(a["outer_diameter"]+b["outer_diameter"])/2
                  for a, b in zip(layout, layout[1:])]
        if any(abs(float(a)-float(b)) > 1e-7 for a, b in zip(gaps, actual)):
            raise ValueError("真实逐管横向偏距与填写净距不一致，请核对原始管道布置")
    depth = float(asset.get("construction", {}).get("cover_depth", DEFAULT_WORKBENCH_COVER_M))
    if not math.isfinite(depth) or depth < 0:
        raise ValueError("管顶埋深须为有限非负数")
    alignment = clip_alignment(network["alignment"], asset["station_start"], asset["station_end"])
    segments = deepcopy(asset.get("construction", {}).get("cover_segments"))
    rows = segments or [{"station_start": alignment.start_station, "station_end": alignment.end_station, "cover_depth": depth}]
    rows = sorted([{k: float(r[k]) for k in ("station_start", "station_end", "cover_depth")} for r in rows],
                  key=lambda r: r["station_start"])
    keys = ("kind", "station_start", "station_end", "length", "start_xy", "end_xy", "tangent_angle",
            "center_xy", "radius", "start_angle", "sweep_angle")
    relevant = {"plan": [{k: e[k] for k in keys if k in e} for e in alignment.elements],
                "range": [alignment.start_station, alignment.end_station], "layout_mode": mode,
                "pipes": [{k: p[k] for k in ("outer_diameter", "offset")} for p in layout],
                "spacing": list(spacing) if isinstance(spacing, (list, tuple)) else float(spacing),
                "cover_depth": depth, "cover_segments": rows, "sample_step": float(sample_step)}
    return alignment, pipes, spacing, depth, segments, mode, relevant


def cover_terrain(request, tin=None):
    actual = tin if tin is not None else request.get("tin")
    report = getattr(actual, "import_report", None) or request.get("identity", {})
    return {"requested_mode": request["mode"], "actual_mode": report.get("terrain_mode") or "mesh",
            "source_sha256": report.get("source_sha256"), "cache_sha256": report.get("cache_sha256"),
            "original_source_sha256": (report.get("original_source") or {}).get("source_sha256"),
            "options": deepcopy(request["options"])}


def _cover_generation_identity(network, asset, request):
    options = asset.get("cover_generation_options") or {}
    step = (options["control_step_m"] if options.get("automatic_policy") == AUTOMATIC_ENGINEERING_COVER_POLICY
            else request["cover_sample_step"])
    return cover_parameters(network, asset, step)[-1]


def _effective_terrain_options(options):
    return {key: value for key, value in options.items()
            if key != "clean_output_dir" and (key not in _COVER_TERRAIN_DEFAULTS
                                               or value != _COVER_TERRAIN_DEFAULTS[key])}


def _cover_binding_hash(generation, terrain, contract):
    return cover_hash({"generation": generation, "terrain": terrain, "calculation_contract": contract})


def cover_input_hash(network, asset, request, tin=None):
    from .workbench_identity import COMPUTATION_CONTRACT

    generation = _cover_generation_identity(network, asset, request)
    terrain = cover_terrain(request, tin)
    terrain["options"] = _effective_terrain_options(terrain["options"])
    return _cover_binding_hash(generation, terrain, COMPUTATION_CONTRACT)


def _matches_cover_input(recorded, network, asset, request, tin):
    from .workbench_identity import COMPUTATION_CONTRACT

    generation = _cover_generation_identity(network, asset, request)
    terrain = cover_terrain(request, tin)
    effective_options = _effective_terrain_options(terrain["options"])
    contract = COMPUTATION_CONTRACT
    if recorded == _cover_binding_hash(generation, {**terrain, "options": effective_options}, contract):
        return True
    if recorded == _cover_binding_hash(generation, terrain, contract):
        return True

    # A raw survey hash alone cannot establish that a rebuilt mesh is identical.
    # A saved import can also identify the option values before an output move.
    actual = tin if tin is not None else request.get("tin")
    report = getattr(actual, "import_report", None) or request.get("identity", {})
    source_path = str(report.get("path") or request.get("path") or "")
    if not (terrain["cache_sha256"] or (terrain["source_sha256"] and source_path.lower().endswith(".npz"))):
        return False
    saved_options = report.get("terrain_options") or {}
    option_versions = (terrain["options"], effective_options)
    if saved_options not in option_versions and _effective_terrain_options(saved_options) == effective_options:
        option_versions = (*option_versions, saved_options)
    return any(recorded == _cover_binding_hash(generation, {**terrain, "options": options}, version)
               for version in (contract, *_COMPATIBLE_COVER_CONTRACTS.get(contract, ()))
               for options in option_versions)


def cover_profile_hash(asset):
    from .design_profiles import normalize_design_profile
    return cover_hash(normalize_design_profile(asset))


def cover_confirmed(asset, network, request, tin=None):
    from .design_profiles import normalize_design_profile
    from .pipe_axis_continuity import inspect_pipe_axis_continuity
    binding = asset.get("cover_confirmation") or {}
    try:
        continuous = inspect_pipe_axis_continuity({"networks": [{**network, "assets": [asset]}]}, scope="all")["valid"]
        if not (binding.get("schema_version") == "1.0" and asset.get("cover_preview_confirmed") is True
                and asset.get("axis_source") == "terrain_and_user_cover_depth" and continuous
                and binding.get("profile_sha256") == cover_profile_hash(asset)):
            return False
        recorded = binding.get("input_sha256")
        if _matches_cover_input(recorded, network, asset, request, tin):
            return True
        # Earlier continuous 2 m profiles predate persisted generation options.
        # Try their original control spacing while preserving all geometry checks.
        if asset.get("cover_generation_options") or normalize_design_profile(asset)["reference"] != "pipe_axis":
            return False
        legacy_request = {**request, "cover_sample_step": ENGINEERING_COVER_CONTROL_STEP_M}
        layout = cover_parameters(network, asset, ENGINEERING_COVER_CONTROL_STEP_M)[-1]["pipes"]
        if len(layout) != 1 or abs(float(layout[0]["offset"])) > 1e-8:
            return False
        return _matches_cover_input(recorded, network, asset, legacy_request, tin)
    except (ValueError, TypeError, KeyError, AttributeError):
        return False


def is_pressure_cover_asset(asset):
    return (asset.get("kind") in {"pipe", "pressure_pipe", "siphon"}
            or asset.get("section_type") == "circular_siphon"
            or asset.get("source_type") in {"有压管道", "倒虹吸"})


def has_supplied_design_profile(asset):
    """Reserve supplied or confirmed design data, even when coverage is incomplete."""
    construction = asset.get("construction") or {}
    if asset.get("axis_source") == "terrain_and_user_cover_depth" or construction.get("burial_mode") == "cover_depth":
        return False
    return bool(asset.get("design_profile") or asset.get("profile_points")
                or (asset.get("alignment") or {}).get("profile_points")
                or asset.get("axis_source") in {"user_input_real_elevation", "water_profile_real_elevation"}
                or construction.get("burial_mode") == "actual_axis" and construction.get("axis_confirmed"))


def has_actual_design_profile(asset):
    """Recognize a complete explicit design profile."""
    if not has_supplied_design_profile(asset) or not asset.get("design_profile"):
        return False
    try:
        from .design_profiles import normalize_design_profile, clip_design_profile
        profile = normalize_design_profile(asset)
        clip_design_profile(profile, asset["station_start"], asset["station_end"])
        return profile["reference"] in {"pipe_axis", "common_outer_bottom", "inner_invert"}
    except (ValueError, TypeError, KeyError):
        return False


def needs_cover_generation(asset, network, request, tin=None, *, preserve_actual_design=True):
    from .pipe_profile_partitions import awaiting_water_profile_parts
    if trenchless_method(asset):
        return False
    if not is_pressure_cover_asset(asset) or not asset.get("enabled", True):
        return False
    if asset.get("pipe_profile_choice") == "pending_gap" or awaiting_water_profile_parts(asset):
        return False
    if (asset.get("siphon_axis_choice") or {}).get("status") in {"mismatch", "pending"}:
        return False
    if asset.get("construction", {}).get("installation_mode") in {"exposed", "elevated", "above_ground", "open"}:
        return False
    if preserve_actual_design and has_supplied_design_profile(asset):
        return False
    return not cover_confirmed(asset, network, request, tin)


class BatchCoverProfileError(ValueError):
    def __init__(self, report, prepared_inputs):
        self.report = report
        self.diagnostics = report["failures"]
        self.prepared_inputs = prepared_inputs
        super().__init__(f"批量覆土纵断面有{len(report['failures'])}个对象未完成；已保留已完成对象及逐项原因")


def prepare_batch_cover_profiles(tin, inputs, *, cover_depth=DEFAULT_WORKBENCH_COVER_M, sample_step=10.,
        terrain_request=None, asset_ids=None, confirmed=True, cancelled=None, progress=None,
        raise_on_error=True, generation_options=None, only_pending=True, preserve_actual_design=True):
    """Generate and bind all selected pressure/siphon profiles without dialogs.

    A supplied ``cover_depth`` is an explicit uniform user setting.  Use None
    to retain each object's entered depth and optional depth segments.  The
    input dictionary is preserved; a caller applies the returned copy only
    after the batch is complete.  Hydraulic channel/culvert profiles stay as
    imported from the calculated water profile.
    """
    from .pipe_axis_continuity import apply_checked_cover_preview
    from .design_profiles import _check_cover_cancelled
    if not confirmed:
        raise ValueError("批量覆土生成须有用户已填写并确认的覆土参数")
    if not math.isfinite(float(sample_step)) or float(sample_step) <= 0:
        raise ValueError("覆土纵断面采样间距须为有限正数")
    prepared = deepcopy(inputs)
    report_data = getattr(tin, "import_report", {})
    request = dict(terrain_request or {"path": report_data.get("path", ""),
        "mode": report_data.get("terrain_mode", "combined"), "options": deepcopy(report_data.get("terrain_options") or {}),
        "identity": deepcopy(report_data), "tin": tin})
    request["cover_sample_step"] = float(sample_step)
    selected_ids = None if asset_ids is None else set(asset_ids)
    candidates = [(network, index, asset) for network in prepared.get("networks", [])
                for index, asset in enumerate(network.get("assets", []))
                if asset.get("enabled", True) and not asset.get("calculation_deferred")
                and (asset["asset_id"] in selected_ids if selected_ids is not None
                                                   else is_pressure_cover_asset(asset))]
    report = {"schema_version": "1.0", "source": "terrain_and_user_cover_depth", "valid": True,
              "requested_cover_m": cover_depth, "sample_step_m": float(sample_step),
              "requested_sample_step_m": float(sample_step),
              "automatic_engineering_policy": AUTOMATIC_ENGINEERING_COVER_POLICY,
              "terrain": cover_terrain(request, tin), "completed": [], "failures": [], "skipped": []}
    selected = []
    for network, index, asset in candidates:
        _check_cover_cancelled(cancelled)
        non_open_cut=trenchless_exclusion(asset)
        if non_open_cut:
            report["skipped"].append({"asset_id":asset["asset_id"],"name":asset.get("name"),
                "reason":non_open_cut["reason"],"code":non_open_cut["code"]})
            continue
        binding_asset = asset
        if cover_depth is not None:
            binding_asset = deepcopy(asset)
            binding_asset.setdefault("construction", {})["cover_depth"] = float(cover_depth)
            binding_asset["construction"].pop("cover_segments", None)
        from .pipe_profile_partitions import awaiting_water_profile_parts
        if awaiting_water_profile_parts(asset):
            reason = "水面线纵断面分段待确认"
        elif asset.get("construction", {}).get("installation_mode") in {"exposed", "elevated", "above_ground", "open"}:
            reason = "明管/架空管不自动改为埋管"
        elif asset.get("pipe_profile_choice") == "pending_gap":
            reason = "设计纵断面缺口待补"
        elif (asset.get("siphon_axis_choice") or {}).get("status") in {"mismatch", "pending"}:
            reason = asset["siphon_axis_choice"].get("message") or "倒虹吸纵断面待补"
        elif preserve_actual_design and has_supplied_design_profile(asset):
            reason = ("已有完整实际设计纵断面，保留设计成果" if has_actual_design_profile(asset)
                      else "保留实际设计纵断面资料，桩号覆盖或高程待核")
        elif only_pending and cover_confirmed(binding_asset, network, request, tin):
            reason = "已有与当前参数及地形一致的覆土纵断面"
        else:
            selected.append((network, index, asset))
            continue
        report["skipped"].append({"asset_id": asset["asset_id"], "name": asset.get("name"), "reason": reason})
    route_indexes = {id(network): i for i, network in enumerate(prepared["networks"], 1)}
    for number, (network, index, asset) in enumerate(selected, 1):
        if cancelled and cancelled():
            raise InterruptedError("批量覆土纵断面生成已取消；原输入保留")
        route = route_indexes[id(network)]
        context = {"asset_id": asset["asset_id"], "name": asset.get("name"),
                   "route_id": str(network.get("route_id",network.get("network_id",network.get("name",f"route-{route}")))),
                   "station_start": asset.get("station_start"), "station_end": asset.get("station_end")}
        if progress:
            progress("cover_profiles", (number-1)/max(1, len(selected)),
                     f"按管顶覆土生成纵断面 {number}/{len(selected)}：{asset.get('name', asset['asset_id'])}")
        try:
            candidate = deepcopy(asset)
            construction = candidate.setdefault("construction", {})
            if cover_depth is not None:
                depth = float(cover_depth)
                if not math.isfinite(depth) or depth < 0:
                    raise ValueError("管顶覆土须为有限非负数")
                construction["cover_depth"] = depth
                construction.pop("cover_segments", None)
            construction["burial_mode"] = "cover_depth"
            construction.setdefault("installation_mode", "buried")
            alignment, pipes, spacing, depth, segments, mode, relevant = cover_parameters(network, candidate, sample_step)
            preview = generate_workbench_cover_preview(tin, alignment, pipes, cover_depth=depth,
                cover_segments=segments, spacing=spacing, sample_step=sample_step, generation_options=generation_options,
                cancelled=cancelled)
            updated = apply_checked_cover_preview(network, candidate, preview, confirmed=True)
            updated.update(cover_pipe_layout_mode=mode, cover_preview_confirmed=True)
            bind_cover_generation_metadata(updated, preview)
            updated["cover_confirmation"] = {"schema_version": "1.0",
                "input_sha256": cover_input_hash(network, updated, request, tin),
                "profile_sha256": cover_profile_hash(updated), "confirmation_source": "user_parameter_batch"}
            updated["profile_source"] = {"kind": "terrain_with_user_pipe_top_cover", "cover_m": depth,
                "terrain_source_sha256": report_data.get("source_sha256"),
                "original_terrain_sha256": (report_data.get("original_source") or {}).get("source_sha256")}
            network["assets"][index] = updated
            covers = [float(p.get("minimum_actual_cover", p["actual_cover"]))
                      for row in preview.get("samples", []) for p in row.get("pipes", [])]
            report["completed"].append({**context, "cover_m": depth,
                "minimum_sampled_cover_m": min(covers) if covers else None,
                "profile_element_count": len(preview["design_profile"]["elements"]),
                "sample_count": len(preview.get("samples", [])),
                "sampling_policy": preview.get("sampling_policy", "exact"),
                "control_step_m": preview.get("control_step_m", float(sample_step)),
                "actual_cover_summary": deepcopy(preview.get("actual_cover_summary") or {}),
                "preview_sha256": preview.get("preview_sha256"),
                "confirmation": deepcopy(updated["cover_confirmation"])})
        except (ValueError, TypeError, KeyError) as error:
            _check_cover_cancelled(cancelled)
            code=getattr(error,"code","cover_profile_failed")
            message=str(error)
            if code=="missing_terrain" and report_data.get("corridor_preparation"):
                message="当前计算地形范围不足："+message
            report["failures"].append({**context, "message": message, "code": code,
                                       "station": getattr(error, "station", None),
                                       "diagnostics": deepcopy(getattr(error, "diagnostics", []))})
    report["valid"] = not report["failures"]
    completed_ids={row["asset_id"] for row in report["completed"]}
    for issue in prepared.get("diagnostics",[]):
        if issue.get("asset_id") in completed_ids and (issue.get("code")=="missing_design_profile" or issue.get("field")=="design_profile"):
            issue.update(resolved=True,resolution="automatic_terrain_cover_profile")
    for network in prepared.get("networks",[]):
        network["missing_fields"]=sorted({field for asset in network.get("assets",[])
                                          for field in asset.get("missing_fields",[])})
    report["completed_count"] = len(report["completed"])
    report["selected_count"] = len(selected)
    report["effective_control_steps_m"] = sorted({row["control_step_m"] for row in report["completed"]})
    if progress:
        progress("cover_profiles", 1., f"批量覆土纵断面已完成{len(report['completed'])}/{len(selected)}个对象")
    if report["failures"] and raise_on_error:
        raise BatchCoverProfileError(report, prepared)
    return prepared, report
