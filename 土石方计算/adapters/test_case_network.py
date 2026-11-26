"""Explicitly authorized TEST networks from raw workbooks and one fixed TIN.

This adapter cannot produce formal design input. Every introduced dimension,
rounded-corner allocation and generated elevation is marked as TEST.
"""
from __future__ import annotations

from copy import deepcopy
from collections import Counter
import hashlib
import json
import math

import numpy as np

from .source_adapters import load_batch_sample
from ..services.construction_rules import normalize_asset_construction
from ..services.network_alignment import build_ip_alignment
from ..core.tin_interpolator import TINInterpolator


TEST_DEFAULTS = {
    "profile_step": 10.0, "smoothing_length": 60.0, "wave_length": 500.0,
    "wave_amplitude": 0.8, "open_invert_depth": 0.6, "cover_depth": 1.0,
    "tunnel_cover": 6.0, "point_structure_length": 4.0,
    "burial_check_step": 2.0, "burial_cover_safety": 0.1, "burial_max_grade": 0.15,
    "buried_profile_safety_margin": 0.5,
    "section": {"inner_width": 2.0, "inner_height": 1.5, "inner_side_slope": 1.0,
                "inner_radius": 0.5, "inner_diameter": 1.4, "wall_thickness": 0.2,
                "base_thickness": 0.2, "roof_thickness": 0.2, "wall_height": 1.0,
                "arch_angle_degrees": 180.0, "pipe_count": 1, "pipe_spacing": 0.5,
                "compound_lower_height": 0.6, "compound_bench_width": 0.8,
                "compound_upper_slope": 1.0, "compound_lower_slope": 0.75,
                "compound_right_slope": 1.0, "foundation_width": 3.0, "foundation_height": 1.0},
    "construction": {"working_space_left": 0.5, "working_space_right": 0.5,
                     "excavation_slope_left": 0.5, "excavation_slope_right": 0.5,
                     "bedding_thickness": 0.15, "bedding_extension": 0.2,
                     "installation_mode": "buried", "bank_top_width_left": 0.5,
                     "bank_top_width_right": 0.5, "bank_slope_left": 1.5,
                     "bank_slope_right": 1.5, "excavation_clearance": 0.3}
}

# Only missing source U-shape angles use these legacy TEST defaults.
# Valid original angles (including a zero wall tilt) always take precedence.
U_ANGLE_DEFAULTS = {"u_arc_angle_degrees": 180.0, "u_side_angle_degrees": 0.0}


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _missing_runs(stations, grounds):
    runs, current = [], []
    for s, z in zip(stations, grounds):
        if not math.isfinite(float(z)):
            current.append(float(s))
        elif current:
            runs.append({"station_start": current[0], "station_end": current[-1], "sample_count": len(current)})
            current = []
    if current:
        runs.append({"station_start": current[0], "station_end": current[-1], "sample_count": len(current)})
    return runs


def make_fixed_test_profile(alignment, reference_tin, settings=None):
    """Generate one fixed TEST base profile and retain all missing-ground facts.

    Missing ground is never filled in the terrain. For design generation only,
    gaps between valid samples are explicitly interpolated before smoothing.
    Outside end support the design uses the nearest supported end elevation,
    with that assumption recorded in the missing report.
    """
    cfg = {**TEST_DEFAULTS, **(settings or {})}
    step = float(cfg["profile_step"])
    if step <= 0 or cfg["smoothing_length"] < 0 or cfg["wave_length"] <= 0:
        raise ValueError("TEST纵断面采样和波长必须为正，平顺长度不得为负")
    count = max(1, math.ceil(alignment.total_length/step))
    stations = np.linspace(alignment.start_station, alignment.end_station, count+1)
    coordinates = np.asarray([alignment.get_xy_at_station(s) for s in stations])
    grounds = TINInterpolator(reference_tin).query_batch(coordinates)
    valid = np.isfinite(grounds)
    if valid.sum() < 2:
        raise ValueError("基准点云地形在线路上不足两个有效高程，不能生成真实地形TEST纵断面")
    design_ground = np.interp(stations, stations[valid], grounds[valid])
    sigma = float(cfg["smoothing_length"])/max(alignment.total_length/count, 1e-9)
    if sigma > 0:
        # A normalized Gaussian affects design only, not the original TIN.
        half = max(1, math.ceil(3*sigma))
        x = np.arange(-half, half+1)
        kernel = np.exp(-0.5*(x/sigma)**2)
        kernel /= kernel.sum()
        design_ground = np.convolve(np.pad(design_ground, (half, half), mode="edge"), kernel, mode="valid")
    wave = cfg["wave_amplitude"]*np.sin(2*np.pi*(stations-alignment.start_station)/cfg["wave_length"])
    base = design_ground+wave
    rows = [{"station": float(s), "elevation": float(z)} for s, z in zip(stations, base)]
    samples = [{"station": float(s), "x": float(xy[0]), "y": float(xy[1]),
                "ground_elevation": float(z) if math.isfinite(float(z)) else None,
                "design_reference": float(d)} for s, xy, z, d in zip(stations, coordinates, grounds, base)]
    report = {"test_only": True, "source": deepcopy(getattr(reference_tin, "import_report", {})),
              "valid_ground_samples": int(valid.sum()), "missing_ground_samples": int((~valid).sum()),
              "missing_ground_runs": _missing_runs(stations, grounds),
              "test_design_gap_treatment": "interpolate_supported_samples_for_design_only; nearest_end_if_outside_support; terrain_is_not_extrapolated",
              "smoothing_length_m": cfg["smoothing_length"], "wave_amplitude_m": cfg["wave_amplitude"],
              "wave_length_m": cfg["wave_length"], "profile_step_m": step,
              "profile_sha256": _hash(rows), "same_profile_required_for_both_terrain_modes": True}
    return rows, samples, report


def _section(asset, defaults):
    section = deepcopy(defaults["section"])
    if asset.get("section_type") == "u_channel":
        for key, value in U_ANGLE_DEFAULTS.items():
            section.setdefault(key, value)
    variants = {}
    for record in asset["original_fields"]["records"]:
        for key, value in record.get("section", {}).items():
            if value is not None and (float(value) > 0 or key in {"inner_side_slope", "u_side_angle_degrees"} and float(value) >= 0):
                variants.setdefault(key, []).append(float(value))
    selected = {key: Counter(values).most_common(1)[0][0] for key, values in variants.items()}
    section.update(selected)
    return section


def _constrain_buried_profile(asset, alignment, interp, cfg):
    """Lower a TEST design below the fixed reference ground; never move TIN.

    The greatest grade-bounded lower envelope preserves every sampled cover
    constraint. Only collinear controls are removed, retaining the same design.
    Five lateral probes use the highest outer crown conservatively at each
    offset, including both outer edges. Missing ground remains a failed audit.
    """
    st, section = asset["section_type"], asset["section"]
    if st == "arch_tunnel":
        height = section["wall_height"]+section["inner_width"]/2+section["roof_thickness"]
        halfwidth = section["inner_width"]/2+section["wall_thickness"]+cfg["construction"]["excavation_clearance"]
        cover = float(cfg["tunnel_cover"])
    elif st in {"circular_culvert", "circular_siphon", "circular_channel"}:
        height = section["inner_diameter"]/2+section["wall_thickness"]
        halfwidth, cover = height, float(cfg["cover_depth"])
    else:
        return None
    start, end = asset["station_start"], asset["station_end"]
    count = max(1, math.ceil((end-start)/float(cfg["burial_check_step"])))
    stations = sorted({*np.linspace(start, end, count+1), *[p["station"] for p in asset["profile_points"]],
                       *[s for s in alignment.primitive_break_stations if start < s < end]})
    offsets = np.linspace(-halfwidth, halfwidth, 5)
    coordinates = []
    for station in stations:
        xy = np.asarray(alignment.get_xy_at_station(station))
        angle = alignment.get_tangent_angle_at_station(station)
        lateral = np.array([math.sin(angle), -math.cos(angle)])
        coordinates.extend(xy+offset*lateral for offset in offsets)
    ground = interp.query_batch(np.asarray(coordinates)).reshape(-1, 5)
    valid = np.isfinite(ground).all(axis=1)
    if not valid.all():
        return {"test_only": True, "passed": False, "missing_ground_station_count": int((~valid).sum()),
                "missing_ground_stations": [float(s) for s, ok in zip(stations, valid) if not ok],
                "minimum_required_cover": cover, "profile_modified": False,
                "reason": "实际结构横向包络存在缺测，未使用外推地形制造覆土通过"}
    ground_low = ground.min(axis=1)
    old = np.interp(stations, [p["station"] for p in asset["profile_points"]], [p["elevation"] for p in asset["profile_points"]])
    limited = np.minimum(old, ground_low-cover-height-float(cfg["burial_cover_safety"]))
    grade = float(cfg["burial_max_grade"])
    for i in range(1, len(stations)):
        limited[i] = min(limited[i], limited[i-1]+grade*(stations[i]-stations[i-1]))
    for i in range(len(stations)-2, -1, -1):
        limited[i] = min(limited[i], limited[i+1]+grade*(stations[i+1]-stations[i]))
    keep = [0]
    for i in range(1, len(stations)-1):
        a = (limited[i]-limited[keep[-1]])/(stations[i]-stations[keep[-1]])
        b = (limited[i+1]-limited[i])/(stations[i+1]-stations[i])
        if abs(a-b) > 1e-9:
            keep.append(i)
    keep.append(len(stations)-1)
    profile = [{"station": float(stations[i]), "elevation": float(limited[i])} for i in keep]
    asset["profile_points"] = profile
    asset["alignment"]["profile_points"] = deepcopy(profile)
    actual = ground_low-(limited+height)
    return {"test_only": True, "passed": bool(np.min(actual) >= cover-1e-8),
            "profile_modified": bool(np.max(old-limited) > 1e-8),
            "ground_source": "fixed_reference_GCD_original_TIN", "reference_source_sha256": interp._tin.import_report.get("source_sha256") if hasattr(interp._tin, "import_report") else None,
            "minimum_required_cover": cover, "actual_minimum_cover": float(np.min(actual)),
            "actual_maximum_cover": float(np.max(actual)), "max_test_lowering": float(np.max(old-limited)),
            "maximum_grade": grade, "sample_station_count": len(stations), "lateral_probe_count": 5,
            "outer_crown_relative_height": height, "outer_halfwidth_checked": halfwidth,
            "ground_check_step_m": cfg["burial_check_step"], "cover_safety_m": cfg["burial_cover_safety"],
            "missing_ground_station_count": 0, "output_profile_points": len(profile),
            "profile_sha256": _hash(profile),
            "method": "largest_grade_bounded_minorant_of_original_TEST_profile_and_sampled_ground_cover_limits",
            "scope": "实际最小覆土为基准GCD沿线≤2m间距、全外包宽5个横向探针的审查值，地形未改；计算核心仍须检验完整实际施工包络"}


def build_test_case_network(workbook_path, reference_tin, *, case_id=None, settings=None):
    """Build all original groups and every connector; retain point structures."""
    cfg = deepcopy(TEST_DEFAULTS)
    for key, value in (settings or {}).items():
        if key in {"section", "construction"}:
            cfg[key].update(value)
        else:
            cfg[key] = value
    source = load_batch_sample(workbook_path)
    raw_assets = source["assets"]
    records = [r for a in raw_assets for r in a["original_fields"]["records"]]
    alignment = build_ip_alignment(records, start_station=float(source["source"].get("start_station", 0)),
                                   allow_test_radius_adjustment=True)
    row_station = {p["source_row"]: p["route_station"] for p in alignment.ip_points}
    base_profile, ground_samples, profile_report = make_fixed_test_profile(alignment, reference_tin, cfg)
    base_s = [p["station"] for p in base_profile]
    base_z = [p["elevation"] for p in base_profile]
    reference_interp = TINInterpolator(reference_tin)
    prepared, adjustments = [], []
    spans = [[row_station[a["original_fields"]["records"][0]["source_row"]],
              row_station[a["original_fields"]["records"][-1]["source_row"]]] for a in raw_assets]
    for i, (asset, span) in enumerate(zip(raw_assets, spans)):
        if span[1] > span[0]+1e-8:
            continue
        anchor, wanted = span[0], float(cfg["point_structure_length"])
        before = anchor-spans[i-1][1] if i else 0.0
        after = spans[i+1][0]-anchor if i+1 < len(spans) else 0.0
        left = min(wanted/2 if after else wanted, max(0, before))
        right = min(wanted-left, max(0, after))
        span[:] = [anchor-left, anchor+right]
        if span[1] <= span[0]+1e-8:
            raise ValueError("单点结构没有可分配TEST长度；须明确相邻结构边界")
        adjustments.append({"asset_id": asset["asset_id"], "source_rows": [r["source_row"] for r in asset["original_fields"]["records"]],
                            "test_only": True, "action": "single_point_structure_TEST_extent",
                            "source_station": anchor, "station_start": span[0], "station_end": span[1],
                            "length": span[1]-span[0], "reason": "仅从原组间连接范围分配TEST结构长度，保持全线无缺口且不重复"})
    def prepare(asset, start, end, *, connector=False):
        a = deepcopy(asset)
        source_type = a.get("source_type", "TEST连接段")
        original_section_type = a.get("section_type")
        if connector:
            a.update(kind="test_connector", section_type="rectangular_channel")
        elif source_type.startswith("隧洞"):
            a.update(kind="tunnel", section_type="arch_tunnel")
        elif source_type == "有压管道":
            a.update(kind="pressure_pipe", section_type="circular_siphon")
        elif source_type == "分水闸":
            a.update(kind="gate", section_type="box_foundation")
        elif a.get("section_type") == "unsupported":
            raise ValueError(f"TEST网络仍无明确结构形状：{source_type}")
        section = _section(a, cfg) if not connector else deepcopy(cfg["section"])
        construction = deepcopy(cfg["construction"])
        st = a["section_type"]
        is_open = st.endswith("channel") and st != "circular_channel"
        reference = "inner_invert"
        shift = -cfg["open_invert_depth"]
        construction["target_mode"] = "union_terrain" if is_open else "restore_terrain"
        construction["excavation_method"] = "open_cut"
        if st in {"circular_culvert", "circular_siphon", "circular_channel"}:
            reference = "pipe_axis"
            shift = -cfg["cover_depth"]-section["inner_diameter"]/2-section["wall_thickness"]
        elif st == "arch_tunnel":
            shift = -cfg["tunnel_cover"]-section["wall_height"]-section["inner_width"]/2-section["roof_thickness"]
            construction["excavation_method"] = "underground"
            construction["outer_section_type"] = "arch_culvert"
        elif st == "box_foundation":
            reference = "foundation_base"
            shift = -0.5
        elif not is_open:
            shift = -cfg["cover_depth"]-section["inner_height"]-section["roof_thickness"]
        stations = sorted({start, end, *[s for s in base_s if start < s < end]})
        profile = [{"station": s, "elevation": float(np.interp(s, base_s, base_z))+shift} for s in stations]
        a.update(enabled=True, station_start=float(start), station_end=float(end), section=section,
                 construction=construction, profile_points=profile, is_test=True, test_only=True,
                 section_variation_requires_resolution=False)
        normalize_asset_construction(a)
        construction = a["construction"]
        a["alignment"] = {"elevation_reference": reference, "profile_points": deepcopy(profile),
                          "plan_geometry": "analytic_tangent_line_circular_arc", "station_basis": "true_plan_arclength",
                          "network_alignment": True, "curves_require_resolution": False}
        a["test_overrides"] = {"label": "用户授权TEST施工参数与真实基准地形生成的TEST纵断面，不是正式设计量",
                               "source_type": source_type, "source_section_type": original_section_type,
                               "test_section_type": st, "section": deepcopy(section), "construction": deepcopy(construction),
                               "base_profile_sha256": profile_report["profile_sha256"], "base_profile_shift": shift,
                               "elevation_reference": reference, "all_original_rows_retained": True,
                               "source_section_resolution": "TEST使用全部原组有效净尺寸的众数；其余统一TEST默认，原记录不改"}
        cover_audit = _constrain_buried_profile(a, alignment, reference_interp, cfg)
        if cover_audit is not None:
            margin = float(cfg["buried_profile_safety_margin"])
            if not math.isfinite(margin) or margin < 0:
                raise ValueError("地下结构TEST纵断面安全余量必须为非负有限数")
            if cover_audit.get("passed"):
                # Apply the common margin after the grade-bounded lower
                # envelope so its controls and slopes stay exactly the same.
                for point in a["profile_points"]:
                    point["elevation"] -= margin
                a["alignment"]["profile_points"] = deepcopy(a["profile_points"])
                a["test_overrides"]["base_profile_shift"] -= margin
                a["test_overrides"]["additional_uniform_TEST_lowering_m"] = margin
                for key in ("actual_minimum_cover", "actual_maximum_cover", "max_test_lowering", "cover_safety_m"):
                    cover_audit[key] += margin
                cover_audit["additional_uniform_TEST_lowering_m"] = margin
                cover_audit["profile_modified"] = cover_audit["profile_modified"] or margin > 0
                cover_audit["profile_sha256"] = _hash(a["profile_points"])
            a["test_overrides"]["actual_cover_audit"] = cover_audit
            a["test_overrides"]["profile_adjustment"] = "固定基准GCD真实覆土限制的低包络TEST纵断面，不随比较地形改变"
        return a
    for i, (asset, span) in enumerate(zip(raw_assets, spans)):
        if i and span[0] > spans[i-1][1]+1e-9:
            prev = raw_assets[i-1]
            connector = {"asset_id": f"test-connector-{i:04d}", "name": f"TEST连接 {i}", "source_type": "TEST连接段",
                         "original_fields": {"records": [], "source": deepcopy(source["source"]),
                                             "from_asset": prev["asset_id"], "to_asset": asset["asset_id"],
                                             "source_rows": [prev["original_fields"]["records"][-1]["source_row"], asset["original_fields"]["records"][0]["source_row"]]}}
            prepared.append(prepare(connector, spans[i-1][1], span[0], connector=True))
        prepared.append(prepare(asset, *span))
    for prev, cur in zip(prepared, prepared[1:]):
        if not math.isclose(prev["station_end"], cur["station_start"], abs_tol=1e-7):
            raise ValueError("TEST网络有未分配缺口或重叠")
    total = sum(a["station_end"]-a["station_start"] for a in prepared)
    if not math.isclose(total, alignment.total_length, abs_tol=1e-6):
        raise ValueError("TEST结构与连接总长度不等于全线真长")
    design_profiles_hash = _hash([{"asset_id": a["asset_id"],
                                   "elevation_reference": a["alignment"]["elevation_reference"],
                                   "profile_points": a["profile_points"]} for a in prepared])
    report = {"test_only": True, "case_id": case_id or source["source"]["channel_name"],
              "source": deepcopy(source["source"]), "source_record_count": len(records),
              "source_structure_group_count": len(raw_assets), "test_asset_count": len(prepared),
              "connector_count": sum(a["kind"] == "test_connector" for a in prepared),
              "source_type_record_counts": dict(Counter(r["structure_type"] for r in records)),
              "all_original_group_ids_retained": all(a["asset_id"] in {b["asset_id"] for b in prepared} for a in raw_assets),
              "total_true_length": alignment.total_length, "partitioned_asset_length": total,
              "final_test_profiles_sha256": design_profiles_hash,
              "radius_adjustments": alignment.adjustments, "point_extent_adjustments": adjustments,
              "profile_report": profile_report, "test_defaults": cfg,
              "buried_asset_cover_audits": [{"asset_id": a["asset_id"], "name": a["name"], "section_type": a["section_type"],
                                               **a["test_overrides"]["actual_cover_audit"]} for a in prepared if "actual_cover_audit" in a["test_overrides"]]}
    return {"schema_version": "1.0", "name": source["source"]["channel_name"]+"全线挖填TEST",
            "alignment": alignment, "assets": prepared, "profile_points": base_profile,
            "station_range": [alignment.start_station, alignment.end_station],
            "assumptions": {"purpose": "用户授权统一TEST施工参数，非正式设计工程量",
                            "reference_terrain": deepcopy(profile_report["source"]),
                            "fixed_profile_sha256": design_profiles_hash,
                            "reference_base_profile_sha256": profile_report["profile_sha256"],
                            "same_design_for_all_terrain_modes": True,
                            "geometry": "原IP解析相切直线圆弧，零半径原折点保留；竞争半径TEST调整逐项留痕",
                            "ip_to_route_boundary": "圆弧中点作为原IP结构边界，原坐标与原半径保留",
                            "point_structure_extents": deepcopy(adjustments),
                            "construction_defaults": deepcopy(cfg),
                            "tunnels": "原隧洞按暗挖结构保留，不转换为明挖暗涵",
                            "connectors": "原结构组间独立TEST矩形开敞连接段，范围连续且不重复"},
            "ground_samples": ground_samples, "report": report, "test_only": True}


def serializable_network(network):
    return {**{k: deepcopy(v) for k, v in network.items() if k != "alignment"},
            "alignment": network["alignment"].to_dict()}
