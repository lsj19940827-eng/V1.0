"""Repeatable real-case calculation using the production calculation services.

The optional 工程量流程.json keeps project construction choices beside source
files. Without it, filenames are matched and the ordinary construction defaults
are used. Source drawings and workbooks are always read only.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import gc
import json
from pathlib import Path
import re
import uuid

MANIFEST_NAME = "工程量流程.json"
DEFAULT_WORKFLOW_PARAMETERS = {
    "cover_depth_m": 2.0,
    "profile_units": "m",
    "profile_reference": "pipe_axis",
    "profile_step_m": 20.0,
    "overlap_policy": "independent_sections",
    "construction_defaults": "按管径分档的工作面、120°砂支承、人工及机械回填",
}
TERRAIN_OPTIONS = {
    "conflict_policy": "points_priority", "duplicate_point_policy": "max",
    "contour_crossing_policy": "release_conflicting_segments",
    "automatic_boundary": True, "boundary_gap_factor": 4.0,
    "filter_elevation_outliers": True,
}


def _resolve(base, value):
    return str((base / value).resolve()) if value else None


def _prefix(first, second):
    length = 0
    for a, b in zip(first, second):
        if a != b:
            break
        length += 1
    return length


def discover_quantity_cases(folder):
    """Return source paths and saved choices, requiring unique file matches."""
    from .batch_water_profile import read_batch_workbook
    base = Path(folder).resolve()
    manifest = base / MANIFEST_NAME
    if manifest.is_file():
        document = json.loads(manifest.read_text(encoding="utf-8-sig"))
        cases = []
        for source in document.get("cases", []):
            case = deepcopy(source)
            for key in ("workbook", "terrain", "profile", "terrain_cache"):
                if key in case:
                    case[key] = _resolve(base, case[key])
            for profile in case.get("additional_profiles", []):
                profile["path"] = _resolve(base, profile["path"])
            case["workflow_manifest"] = str(manifest)
            for key in ("workbook", "terrain"):
                if not case.get(key) or not Path(case[key]).is_file():
                    raise ValueError(f"{case.get('name', '算例')}缺少{key}文件")
            cases.append(case)
        if not cases:
            raise ValueError("工程量流程清单没有算例")
        return cases
    workbooks = sorted(p for p in base.glob("*.xlsx") if not p.name.startswith("~$"))
    terrains = sorted([*base.glob("*.dwg"), *base.glob("*.npz"), *base.glob("*.3dm")])
    profiles = sorted(p for p in base.glob("*.dxf") if "地形" not in p.stem)
    cases = []
    for workbook in workbooks:
        _, metadata = read_batch_workbook(workbook)
        name = metadata["channel_name"]
        def match(paths, required):
            ranked = sorted([(_prefix(workbook.stem, p.stem), p) for p in paths], reverse=True)
            if len(paths) == 1:
                return str(paths[0].resolve())
            if not ranked or ranked[0][0] < 2:
                if required:
                    raise ValueError(f"{name}缺少匹配地形文件")
                return None
            if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
                raise ValueError(f"{name}有多个同名资料，请在{MANIFEST_NAME}中指定文件")
            return str(ranked[0][1].resolve())
        cases.append({"name": name, "workbook": str(workbook.resolve()),
                      "terrain": match(terrains, True), "profile": match(profiles, False)})
    if not cases:
        raise ValueError("资料文件夹中没有批量计算表xlsx")
    return cases


from .imported_design_profiles import read_quantity_profile, prepare_imported_profile


def bind_quantity_profile(inputs, profile, source, *, station_offset=None):
    """Match a whole route or continuous pressure tail by its actual extent."""
    from .batch_cover_profiles import is_pressure_cover_asset
    from .design_profiles import clip_design_profile, evaluate_profile, profile_break_stations
    from .siphon_axis_choices import configure_siphon_axis, is_siphon_axis_asset
    assets = [a for n in inputs.get("networks", []) for a in n.get("assets", [])]
    pressure = [a for a in assets if is_pressure_cover_asset(a) and a.get("kind") != "siphon"]
    if not pressure:
        pressure = [a for a in assets if is_pressure_cover_asset(a)]
    if not pressure:
        raise ValueError("纵断面文件没有对应的管道对象")
    a, b = min(x["station_start"] for x in pressure), max(x["station_end"] for x in pressure)
    first, last = profile["station_start"], profile["station_end"]
    if station_offset is None:
        if abs((last-first)-(b-a)) > .001:
            raise ValueError(f"纵断面长{last-first:.3f}m与有压管道范围{b-a:.3f}m不符，请填写profile_station_offset_m")
        station_offset = a-first
    adopted, mapping = prepare_imported_profile(profile, {"station_start": a, "station_end": b},
        inputs=inputs, station_offset=station_offset)
    report = {**source, "station_offset_m": float(station_offset),
              "terminal_rounding_m": mapping["terminal_rounding_m"], "assets": [], "trenchless": []}
    for asset in pressure:
        if is_siphon_axis_asset(asset):
            configure_siphon_axis(asset, mode="exact", profile=profile,
                source={**source, "kind": "quantity_dxf"}, station_offset=station_offset, strict=True)
        else:
            clipped = clip_design_profile(adopted, asset["station_start"], asset["station_end"])
            asset["design_profile"] = clipped
            asset["profile_points"] = [{"station": s, "elevation": evaluate_profile(clipped, s)[0]}
                                       for s in profile_break_stations(clipped)]
            asset.setdefault("alignment", {}).update(profile_points=deepcopy(asset["profile_points"]),
                                                     elevation_reference=clipped["reference"])
        asset.setdefault("construction", {}).update(burial_mode="actual_axis", axis_confirmed=True)
        asset.update(axis_source="supplied_profile_dxf", profile_source=deepcopy(source),
                     cover_preview_confirmed=True)
        asset["missing_fields"] = [x for x in asset.get("missing_fields", []) if x != "design_profile"]
        report["assets"].append(asset["asset_id"])
        for diagnostic in inputs.get("diagnostics", []):
            if diagnostic.get("asset_id") == asset["asset_id"] and diagnostic.get("field") == "design_profile":
                diagnostic.update(resolved=True, resolution="supplied_profile_dxf")
    for exclusion in inputs.get("excluded", []):
        if exclusion.get("construction_method") not in {"顶管", "定向钻"}:
            continue
        start, end = exclusion.get("station_start"), exclusion.get("station_end")
        if start is not None and end is not None and start >= a-.001 and end <= b+.001:
            actual = clip_design_profile(adopted, start, end)
            exclusion["trenchless_route_profile"] = actual
            exclusion.setdefault("original_asset_snapshot", {}).update(design_profile=actual,
                axis_source="supplied_profile_dxf", construction={"burial_mode": "actual_axis"})
            report["trenchless"].append(exclusion.get("source_identity"))
    return report


def prepare_quantity_inputs(project, *, options=None, profile_path=None, profile_units="m", additional_profiles=None):
    """Produce editable ordinary workbench inputs from fresh batch calculation."""
    from ..adapters.workbench_sources import estimate_workbench_project_connections, import_workbench_project
    from .construction_defaults import apply_assumed_construction
    from .default_section_schemes import ensure_default_section_schemes
    from .transition_connections import apply_transition_candidates
    options = deepcopy(options or {})
    cover_depth = float(options.get("cover_depth_m", 2.0))
    inputs = import_workbench_project(project, siphon_cover_depth=cover_depth)
    if options.get("connector_diameter_m"):
        ids = [r["candidate_id"] for r in inputs.get("transition_candidates", [])
               if r.get("source_kind", "native_transition") == "native_transition"
               and r.get("status") not in {"applied", "automatic"}]
        inputs, report = apply_transition_candidates(inputs, ids,
            diameter_m=options["connector_diameter_m"], confirmed=True)
        if not report["valid"]:
            raise ValueError("；".join(r["message"] for r in report["failures"]))
    inputs = estimate_workbench_project_connections(inputs, project)
    excluded_names = set(options.get("exclude_asset_names", []))
    for network in inputs["networks"]:
        for asset in list(network["assets"]):
            if asset.get("name") in excluded_names:
                inputs["excluded"].append({k: deepcopy(asset.get(k)) for k in
                    ("asset_id", "name", "source_type", "station_start", "station_end")})
                inputs["excluded"][-1].update(code="user_excluded_structure", reason="按工程已选计量范围")
                network["assets"].remove(asset)
    inputs["networks"] = [n for n in inputs["networks"] if n.get("assets")]
    apply_assumed_construction(inputs, cover_depth=cover_depth)
    for network in inputs["networks"]:
        for asset in network["assets"]:
            c = asset.setdefault("construction", {})
            c.update(deepcopy(options.get("construction", {})))
            if options.get("working_space_m") is not None:
                c.update(working_space_left=options["working_space_m"], working_space_right=options["working_space_m"])
            if options.get("sand_bedding_m") is not None and asset["section_type"].startswith("circular"):
                c.update(bedding_thickness=0., bedding_extension=0., pipe_seat={"enabled": True,
                    "material_role": "bedding", "support_angle": 120.,
                    "base_thickness": options["sand_bedding_m"], "bottom_width_mode": "trench_bottom",
                    "material": "sand", "name": "砂垫层"})
    inputs, schemes = ensure_default_section_schemes(inputs)
    if schemes["errors"]:
        raise ValueError(str(schemes["errors"]))
    if profile_path:
        profile, source = read_quantity_profile(profile_path, coordinate_units=profile_units,
            reference=options.get("profile_reference", "pipe_axis"))
        inputs["supplied_profile"] = bind_quantity_profile(inputs, profile, source,
            station_offset=options.get("profile_station_offset_m"))
    from .imported_design_profiles import bind_imported_route_profile
    additions = []
    for item in additional_profiles or []:
        matches = [(n, a) for n in inputs["networks"] for a in n.get("assets", [])
                   if a.get("name") == item["asset_name"]]
        if len(matches) != 1:
            raise ValueError("补充纵线未找到唯一命名管段："+item["asset_name"])
        network, asset = matches[0]
        profile, source = read_quantity_profile(item["path"], coordinate_units=item.get("profile_units", profile_units),
            reference=item.get("profile_reference", "pipe_axis"))
        # A named local profile can exceed the billed outlet slightly. Adopt
        # its true coordinates at the selected inlet and clip only the outlet.
        offset = item.get("station_offset_m", asset["station_start"]-profile["station_start"])
        mapping = {"station_offset_m": offset, "source_units": item.get("profile_units", profile_units),
                   "mapping_basis": "命名管段真实进口与纵线局部起桩对齐"}
        inputs, report = bind_imported_route_profile(inputs, network, asset, profile,
            source=source, mapping=mapping, scope="current")
        report.update(asset_name=item["asset_name"],
            cropped_tail_length_m=profile["station_end"]+offset-asset["station_end"])
        additions.append(report)
    if additions:
        inputs["additional_profiles"] = additions
    inputs["quantity_basis"] = {"overlap_policy": "independent_sections",
        "design_elevation_source": "supplied_profile_and_water_profile", "construction_parameters": "editable_workflow_parameters",
        "label": "纵断面及水面线高程；工程施工参数；各断面独立计量"}
    inputs["workflow_parameters"] = options
    return inputs


def _serializable(inputs):
    from .network_project import serialize_network
    return {**deepcopy({k: v for k, v in inputs.items() if k != "networks"}),
            "networks": [serialize_network(n) for n in inputs.get("networks", [])]}


def run_quantity_case(case, output, *, progress=None, cancelled=None,
                      construction_overrides=None, profile_units="m"):
    """Calculate and save the three exports plus a portable editable project."""
    from .batch_water_profile import calculate_batch_water_profile
    from ..io.independent_terrain import file_sha256, load_terrain, save_terrain
    from .batch_cover_profiles import prepare_batch_cover_profiles
    from .pipe_axis_continuity import calculate_checked_workbench
    from .workbench_delivery import delivery_project_path, save_workbench_delivery
    from .workbench_calculator import DEFAULT_ACCURACY
    def check():
        if cancelled and cancelled():
            raise InterruptedError("工程量计算已取消")
    name = str(case.get("name") or Path(case["workbook"]).stem)
    safe = re.sub(r'[<>:"/\\|?*]', "_", name)
    directory = Path(output).resolve()/safe
    if directory.exists():
        directory = directory.with_name(safe+"_"+datetime.now().strftime("%H%M%S")+"_"+uuid.uuid4().hex[:4])
    directory.mkdir(parents=True)
    def report(stage, fraction, message):
        check()
        record = {"stage": stage, "fraction": fraction, "message": message}
        (directory/"运行进度.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf8")
        if progress:
            progress(stage, fraction, f"{name}：{message}")
    def write(name, value):
        (directory/name).write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")), encoding="utf8")
    paths = {k: str(Path(case[k]).resolve()) for k in ("workbook", "terrain", "profile", "workflow_manifest") if case.get(k)}
    paths.update({"additional_profile_"+str(i+1): str(Path(p["path"]).resolve())
                  for i, p in enumerate(case.get("additional_profiles", []))})
    hashes = {k: file_sha256(p, cancelled) for k, p in paths.items()}
    report("water_profile", 0., "读取批量表并计算水面线")
    project = calculate_batch_water_profile(paths["workbook"], progress=report, cancelled=cancelled)
    write("水面线计算工程.qxproj", project)
    options = deepcopy(case.get("parameters", {}))
    options.update(deepcopy(construction_overrides or {}))
    inputs = prepare_quantity_inputs(project, options=options, profile_path=paths.get("profile"),
        profile_units=options.get("profile_units", profile_units), additional_profiles=case.get("additional_profiles"))
    inputs.update(case_name=name, input_files=[{"path": p, "sha256": hashes[k]} for k, p in paths.items()])
    report("terrain", 0., "读取原始地形")
    cache = Path(case["terrain_cache"]) if case.get("terrain_cache") else None
    if cache and cache.is_file():
        tin = load_terrain(cache, cancelled=cancelled)
        original = tin.import_report.get("original_source") or {}
        if original.get("source_sha256") != hashes["terrain"]:
            raise ValueError("地形缓存与本次原图不同，请移除缓存选择后重新计算")
        tin.import_report["cache_reuse"] = {"raw_source_path": paths["terrain"],
            "raw_source_sha256": hashes["terrain"], "cache_path": str(cache.resolve()),
            "cache_sha256": file_sha256(cache), "verified_raw_source_unchanged": True}
    else:
        terrain_options = {**TERRAIN_OPTIONS, "clean_output_dir": str(directory/"干净地形")}
        tin = load_terrain(paths["terrain"], cancelled=cancelled, progress=report,
            terrain_options=terrain_options, terrain_mode="combined")
    terrain_path = directory/"计算地形.npz"
    save_terrain(tin, terrain_path, cancelled=cancelled)
    tin.import_report.update(cache_path=str(terrain_path), cache_sha256=file_sha256(terrain_path))
    write("地形来源.json", tin.import_report)
    request = {"path": str(terrain_path), "identity": deepcopy(tin.import_report),
               "mode": "combined", "options": deepcopy(tin.import_report.get("terrain_options") or {})}
    tin.source_contours = []; tin.point_source_identities = []; tin.contour_source_identities = []
    gc.collect()
    inputs, cover = prepare_batch_cover_profiles(tin, inputs, cover_depth=None,
        terrain_request=request, sample_step=20., progress=report, cancelled=cancelled)
    write("计算输入.json", _serializable(inputs)); write("覆土生成记录.json", cover)
    accuracy = {**DEFAULT_ACCURACY, "profile_step": float(options.get("profile_step_m", 20.)),
                "overlap_policy": "independent_sections"}
    result, payload = calculate_checked_workbench(tin, inputs, terrain_request=request,
        accuracy=accuracy, progress=report, cancelled=cancelled, split_tunnel_exposure=True)
    write("计算结果.json", payload)
    delivery = directory/"成果"
    save_workbench_delivery(payload, delivery, project_snapshot=project,
        drawing_options={"interval": accuracy["profile_step"], "all_sections": True,
                         "include_plan": False, "include_profile": False},
        progress=report, cancelled=cancelled)
    for key, path in paths.items():
        if file_sha256(path, cancelled) != hashes[key]:
            raise ValueError("计算期间源资料发生变化："+path)
    summary = {"case_name": name, "directory": str(delivery),
        "project_path": str(delivery_project_path(delivery)), "source_sha256": hashes,
        "files": [str(p) for p in delivery.iterdir() if p.is_file()],
        "quantities": payload["quantities"], "trenchless_excavation_volume": payload.get("trenchless_excavation_volume", 0.),
        "total_excavation_volume": payload.get("total_excavation_volume", payload["quantities"].get("excavation_volume", 0.)),
        "section_count": len(payload.get("sections", [])),
        "segment_count": len(payload.get("segments", [])), "overlap_policy": "independent_sections",
        "input_hash": payload["input_hash"]}
    write("完成记录.json", summary)
    report("complete", 1., "算量成果已保存")
    return summary


def run_quantity_folder(folder, output, *, progress=None, cancelled=None,
                        construction_overrides=None, profile_units="m"):
    cases = discover_quantity_cases(folder)
    results = []
    for case in cases:
        overrides = (construction_overrides or {}).get(case["name"], {})
        results.append(run_quantity_case(case, output, progress=progress, cancelled=cancelled,
            construction_overrides=overrides, profile_units=profile_units))
        gc.collect()
    return {"cases": results, "directory": str(Path(output).resolve()),
            "project_path": results[-1]["project_path"]}
