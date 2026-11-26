"""按冻结施工域规划局部重算，无法证明复用安全时回到全量计算。"""

from __future__ import annotations

from copy import deepcopy
import math

from shapely.geometry import LineString, MultiPoint, Polygon
from shapely.errors import ShapelyError
from shapely.ops import unary_union

from .contracts import content_hash


CONTEXT_VERSION = "asset-domain-v1"


def _normalized_resources(value):
    """只消除有内容摘要的资源路径，不忽略任何几何或施工参数。"""
    result = deepcopy(value)
    terrain = result.get("terrain", {})
    if terrain.get("mesh_sha256"):
        terrain.pop("mesh_path", None)
    evidence = terrain.get("source_preprocessing") or {}
    for path, digest in (("native_sources_path", "native_sources_sha256"),
                         ("raw_native_sources_path", "raw_native_sources_sha256"),
                         ("quality_report_path", "quality_report_sha256"),
                         ("height_resolution_path", "height_resolution_sha256")):
        if evidence.get(digest):
            evidence.pop(path, None)
    assets = result.get("assets", [])
    for asset in assets:
        alignment = asset.get("alignment", {})
        for path, digest in (("native_curve_path", "native_curve_sha256"),
                             ("native_axis_path", "native_axis_sha256")):
            if alignment.get(digest):
                alignment.pop(path, None)
        for curve in alignment.get("native_pipe_curves", []):
            if curve.get("sha256"):
                curve.pop("path", None)
    return result


def _domain_geometry(asset):
    sections = asset.get("geometry_sections", [])
    if len(sections) < 2:
        raise ValueError("局部影响规划缺少已准备的施工断面")
    rings = []
    all_points = []
    for section in sections:
        origin, lateral = section["origin"], section["lateral"]
        points = [[origin[0] + lateral[0] * p[0], origin[1] + lateral[1] * p[0], p[1]]
                  for ring in section["domain"] for p in ring]
        if not points or not all(math.isfinite(float(v)) for p in points for v in p):
            raise ValueError("施工域为空或包含非有限坐标")
        rings.append(points)
        all_points.extend(points)
    footprints = []
    for first, last in zip(rings, rings[1:]):
        hull = MultiPoint([p[:2] for p in first + last]).convex_hull
        if not isinstance(hull, Polygon) or hull.area <= 0:
            raise ValueError("施工域平面投影退化")
        footprints.append([list(p) for p in hull.exterior.coords])
    endpoints = []
    for ring in (rings[0], rings[-1]):
        unique = sorted({tuple(p[:2]) for p in ring})
        if len(unique) < 2:
            raise ValueError("施工端面平面投影退化")
        endpoints.append([list(unique[0]), list(unique[-1])])
    bounds = [min(p[i] for p in all_points) for i in range(3)] + [
        max(p[i] for p in all_points) for i in range(3)]
    return {"footprints": footprints, "endpoints": endpoints, "bounds": bounds}


def build_reuse_context(snapshot):
    """记录可审计的上下文、逐资产身份和保守施工域，不包含提交状态。"""
    normalized = _normalized_resources(snapshot)
    common = {key: normalized.get(key) for key in (
        "schema_version", "project_id", "coordinate_reference", "terrain", "settings")}
    context = {"version": CONTEXT_VERSION, "context_hash": content_hash(common),
               "asset_hashes": {}, "asset_domains": {}, "unsafe_asset_ids": []}
    for asset in normalized["assets"]:
        if not asset.get("enabled", True):
            continue
        identifier = asset["asset_id"]
        if identifier in context["asset_hashes"]:
            raise ValueError("局部影响规划发现重复资产身份")
        context["asset_hashes"][identifier] = content_hash(asset)
        context["asset_domains"][identifier] = _domain_geometry(asset)
        alignment = asset.get("alignment", {})
        # 原生空间曲线在采样点之间的完整包络由 Rhino 掌握，首版不从采样猜复用范围。
        if any(alignment.get(key) for key in ("native_curve_sha256", "native_axis_sha256",
                                               "native_pipe_curves")):
            context["unsafe_asset_ids"].append(identifier)
    return context


def full_recompute_plan(context, reason):
    return {"version": CONTEXT_VERSION, "mode": "full", "reason": str(reason),
            "affected_asset_ids": sorted(context["asset_hashes"]), "reused_asset_ids": [],
            "changed_asset_ids": [], "removed_asset_ids": []}


def plan_incremental_recompute(snapshot, previous_result=None, *, force_full=False):
    """编辑资产及其相交/端部邻域整段重算，复用边界不能切开旧公共单元。"""
    context = build_reuse_context(snapshot)
    full = lambda reason: full_recompute_plan(context, reason)
    if force_full:
        return context, full("用户要求全量复算")
    previous = previous_result or {}
    old = previous.get("reuse_context") or {}
    if (old.get("version") != CONTEXT_VERSION or not previous.get("engine_sha256")
            or not previous.get("result_id") or not previous.get("input_hash")
            or not previous.get("model_sha256") or not previous.get("model_path")):
        return context, full("上一版缺少可校验的局部复用身份")
    if old.get("context_hash") != context["context_hash"]:
        return context, full("地形、坐标、全局参数或封闭辅助面改变")
    if context["unsafe_asset_ids"] or old.get("unsafe_asset_ids"):
        return context, full("原生空间曲线的完整影响包络需要全量核验")
    if previous.get("units") != "m" or any(previous.get("validation", {}).get(key) is not True
            for key in ("closed_solids", "nonnegative_volumes", "topology_valid",
                        "section_check_passed", "overlap_resolved")):
        return context, full("上一版几何验收不完整")
    current_ids, old_ids = set(context["asset_hashes"]), set(old.get("asset_hashes", {}))
    if (old_ids != set(previous.get("processed_asset_ids", []))
            or not old_ids <= set(old.get("asset_domains", {}))
            or previous.get("geometry_hash") != previous["model_sha256"]):
        return context, full("旧资产范围、施工域或模型身份不完整")
    changed = {identifier for identifier in current_ids | old_ids
               if context["asset_hashes"].get(identifier) != old["asset_hashes"].get(identifier)}
    if not changed:
        return context, full("没有可缩小范围的输入变化")
    tolerance = float(snapshot["settings"].get("linear_tolerance", 0.001))
    if not math.isfinite(tolerance) or tolerance <= 0:
        return context, full("影响规划容差无效")
    try:
        envelopes, endpoints = {}, {}
        for identifier in current_ids | old_ids:
            domains = [c["asset_domains"][identifier] for c in (context, old)
                       if identifier in c.get("asset_domains", {})]
            if not domains:
                raise ValueError("旧施工域记录缺失")
            envelopes[identifier] = unary_union([Polygon(ring) for d in domains for ring in d["footprints"]])
            endpoints[identifier] = [LineString(line) for d in domains for line in d["endpoints"]]
        affected = set(changed)
        # 直接编辑区段的端部衔接邻段参与重算；不沿零体积相切端面无限传递。
        for identifier in changed:
            for other in current_ids | old_ids:
                if any(line.distance(envelopes[other]) <= tolerance for line in endpoints[identifier]):
                    affected.add(other)
        old_rows = previous.get("rows")
        if not isinstance(old_rows, list) or not old_rows:
            raise ValueError("旧分段成果缺失")
        while True:
            expanded = set(affected)
            for identifier in affected:
                for other in (current_ids | old_ids) - affected:
                    if envelopes[identifier].intersection(envelopes[other]).area > tolerance * tolerance:
                        expanded.add(other)
            for row in old_rows:
                participants = set(row.get("participants", []))
                if not participants or not participants <= old_ids or row.get("validation_status") != "PASS":
                    raise ValueError("旧公共单元身份或校验状态无效")
                if participants & affected:
                    expanded.update(participants)
            if expanded == affected:
                break
            affected = expanded
        retained = current_ids - affected
        if not retained:
            return context, full("相交及衔接影响范围覆盖全部启用资产")
    except (ValueError, KeyError, TypeError, ShapelyError) as error:
        return context, full("无法证明局部复用安全：" + str(error))
    plan = {"version": CONTEXT_VERSION, "mode": "incremental",
            "reason": "编辑区段及相交、端部衔接邻域重算，其余同身份实体复用",
            "changed_asset_ids": sorted(changed), "affected_asset_ids": sorted(current_ids & affected),
            "previous_affected_asset_ids": sorted(old_ids & affected), "reused_asset_ids": sorted(retained),
            "removed_asset_ids": sorted(old_ids - current_ids), "previous_result_id": previous["result_id"],
            "previous_input_hash": previous["input_hash"], "previous_geometry_hash": previous["model_sha256"],
            "previous_engine_sha256": previous["engine_sha256"]}
    return context, plan
