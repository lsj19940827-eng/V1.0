"""Apply an explicit local supported-trench assumption without changing design."""
from __future__ import annotations

from copy import deepcopy
import math


def apply_assumed_supported_trench(inputs, asset_id, start, end, *, network_id=None,
        reason="", terrain_request=None, tin=None):
    """Return split source assets with a local vertical supported excavation.

    The original continuous profile is clipped analytically. Existing generated
    cover must have a valid terrain confirmation; its exact same geometry is
    rebound to each child range. No terrain is sampled or extrapolated here.
    """
    from .batch_cover_profiles import (is_pressure_cover_asset, cover_confirmed,
        cover_input_hash, cover_profile_hash)
    from .design_profiles import clip_design_profile, profile_break_stations, evaluate_profile
    from .pipe_axis_continuity import require_pipe_axis_continuity

    start, end = float(start), float(end)
    if not all(math.isfinite(v) for v in (start, end)) or end <= start:
        raise ValueError("局部支护范围须为有限、递增的真实源桩号")
    prepared = deepcopy(inputs)
    matches = [(network, i, asset) for network in prepared.get("networks", [])
        if network_id is None or network_id in {network.get("network_id"), network.get("route_id"), network.get("name")}
        for i, asset in enumerate(network.get("assets", [])) if asset.get("asset_id") == asset_id]
    if len(matches) != 1:
        raise ValueError("局部支护须明确唯一管道对象及其路线")
    network, index, original = matches[0]
    if not is_pressure_cover_asset(original) or not original.get("enabled", True):
        raise ValueError("局部支护直槽仅适用于当前启用的埋设压力管道/倒虹吸")
    if original.get("construction", {}).get("installation_mode") in {"exposed", "elevated", "above_ground", "open"}:
        raise ValueError("明管/架空管不能按局部埋管支护直槽处理")
    a, b = float(original["station_start"]), float(original["station_end"])
    if start < a-1e-7 or end > b+1e-7:
        raise ValueError("局部支护范围须位于原管道真实范围内")
    start, end = max(a, start), min(b, end)
    if not original.get("design_profile"):
        raise ValueError("局部支护须保留已有完整真实或已确认的覆土纵断面")
    generated = original.get("axis_source") == "terrain_and_user_cover_depth"
    request = deepcopy({k:v for k,v in (terrain_request or {}).items() if k != "tin"})
    if not request and tin is not None:
        report = deepcopy(getattr(tin, "import_report", {}))
        request = {"path": report.get("path", ""), "mode": report.get("terrain_mode", "combined"),
                   "options": deepcopy(report.get("terrain_options") or {}), "identity": report}
    request.setdefault("cover_sample_step", 10.)
    if generated and ("mode" not in request or "options" not in request):
        raise ValueError("裁切已生成的覆土轴线须提供原地形身份与覆土采样参数")
    if generated and not cover_confirmed(original, network, request, tin):
        raise ValueError("原管顶覆土确认已失效，不能用局部施工假定绕过地形/参数核对")

    message = (f"{original.get('name', asset_id)} K{start:.3f}～K{end:.3f}："
        "暂按两侧支护直槽（开挖坡比0）计沟槽挖填，工作面、垫层、管轴和原地形保持；支护结构工程量未计。")
    context = {"code": "assumed_supported_pipe_trench", "severity": "info", "asset_id": asset_id,
        "source_identity": deepcopy(original.get("source_identity")), "station_start": start, "station_end": end,
        "source_station_basis": "true_plan_arclength", "excavation_slope_left": 0., "excavation_slope_right": 0.,
        "support_structure_quantities_included": False, "reason": str(reason), "message": message}
    children, assumptions = [], []
    original_snapshot = deepcopy(original.get("original_asset_snapshot") or original)
    for left, right, supported in ((a, start, False), (start, end, True), (end, b, False)):
        if right <= left:
            continue
        child = deepcopy(original)
        child.update(asset_id=asset_id+f"-{left:.9f}-{right:.9f}", parent_asset_id=asset_id,
                     station_start=left, station_end=right, geometry_sections=[],
                     original_asset_snapshot=deepcopy(original_snapshot))
        child["design_profile"] = clip_design_profile(original, left, right)
        child["profile_points"] = [{"station": s, "elevation": evaluate_profile(child, s)[0]}
                                   for s in profile_break_stations(child)]
        if child.get("construction", {}).get("cover_segments"):
            child["construction"]["cover_segments"] = [{**row,
                "station_start": max(left, float(row["station_start"])),
                "station_end": min(right, float(row["station_end"]))}
                for row in child["construction"]["cover_segments"]
                if min(right, float(row["station_end"])) > max(left, float(row["station_start"]))]
        if isinstance(child.get("alignment"), dict) and "profile_points" in child["alignment"]:
            child["alignment"]["profile_points"] = deepcopy(child["profile_points"])
        if supported:
            child["name"] = str(original.get("name") or asset_id) + "（局部支护直槽）"
            construction = child.setdefault("construction", {})
            for side in ("left", "right"):
                construction["excavation_slope_"+side] = 0.
                construction.pop("excavation_stages_"+side, None)
                field = "construction.excavation_slope_"+side
                child.setdefault("parameter_sources", {})[field] = "局部施工假定：支护直槽；支护结构数量未计；"+str(reason)
                assumptions.append({"asset_id": child["asset_id"], "parent_asset_id": asset_id,
                    "name": child["name"], "field": field, "value": 0., "station_start": left, "station_end": right,
                    "reason": message + (" 原因："+str(reason) if reason else "")})
            child["supported_trench_assumption"] = deepcopy(context)
        if generated:
            child["cover_confirmation"] = {"schema_version": "1.0",
                "input_sha256": cover_input_hash(network, child, request, tin),
                "profile_sha256": cover_profile_hash(child),
                "confirmation_source": "derived_from_confirmed_source_profile",
                "parent_asset_id": asset_id, "parent_confirmation": deepcopy(original["cover_confirmation"])}
        children.append(child)
    network["assets"][index:index+1] = children
    require_pipe_axis_continuity(prepared)
    for child in children:
        if generated and not cover_confirmed(child, network, request, tin):
            raise ValueError("派生管段覆土身份未能恢复，原输入保持")
    prepared.setdefault("construction_assumptions", []).extend(assumptions)
    prepared.setdefault("diagnostics", []).append(deepcopy(context))
    basis = prepared.setdefault("quantity_basis", {})
    basis.setdefault("local_supported_trenches", []).append({**deepcopy(context),
        "supported_asset_id": next(c["asset_id"] for c in children if c.get("supported_trench_assumption"))})
    basis["local_construction_note"] = "；".join(c["message"] for c in basis["local_supported_trenches"])
    if "局部支护直槽" not in basis.get("label", ""):
        basis["label"] = basis.get("label", "施工参数假定") + "；局部支护直槽（支护结构量未计）"
    report = {**deepcopy(context), "valid": True, "parent_asset_id": asset_id,
        "children": [{"asset_id": c["asset_id"], "station_start": c["station_start"], "station_end": c["station_end"],
            "supported": bool(c.get("supported_trench_assumption")), "cover_confirmation": deepcopy(c.get("cover_confirmation"))}
            for c in children], "design_profile_changed": False, "terrain_extrapolated": False}
    prepared.setdefault("assumed_supported_trench_reports", []).append(deepcopy(report))
    return prepared, report
