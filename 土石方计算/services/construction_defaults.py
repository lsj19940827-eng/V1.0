"""Explicit editable construction assumptions for a freshly imported design.

Only missing construction, thickness and material values are filled. Hydraulic
geometry and design elevations are never generated or overwritten here.
"""
from __future__ import annotations

from copy import deepcopy
import math
from .batch_cover_profiles import DEFAULT_WORKBENCH_COVER_M


def _value(asset, path):
    if path in {"section.wall_thickness_left", "section.wall_thickness_right", "section.pipe_spacing"}:
        from .section_parameter_decisions import parameter_value
        return parameter_value(asset, path)[0]
    current = asset
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def refresh_quantity_basis(inputs):
    """Refresh current cover metadata without filling parameters or editing history."""
    from .batch_cover_profiles import is_pressure_cover_asset
    from .earthwork_scope import trenchless_method
    depths = set()
    for network in inputs.get("networks", []):
        for asset in network.get("assets", []):
            construction = asset.get("construction") or {}
            if (not asset.get("enabled", True) or not is_pressure_cover_asset(asset)
                    or trenchless_method(asset) or construction.get("burial_mode") != "cover_depth"
                    or construction.get("installation_mode", "buried") != "buried"):
                continue
            segments = construction.get("cover_segments") or [{"cover_depth": construction.get("cover_depth")}]
            for segment in segments:
                try:
                    depth = float(segment.get("cover_depth"))
                except (TypeError, ValueError):
                    continue
                if math.isfinite(depth) and depth >= 0:
                    depths.add(depth)
    depths = sorted(depths)
    basis = deepcopy(inputs.get("quantity_basis") or {})
    basis.setdefault("design_elevation_source", "water_profile_calculation")
    basis.setdefault("construction_parameters", "assumed")
    basis["pipe_cover_depth_m"] = depths[0] if len(depths) == 1 else None
    basis.pop("pipe_cover_depths_m", None)
    if len(depths) > 1:
        basis["pipe_cover_depths_m"] = depths
    label = str(basis.get("label") or "水面线设计高程＋施工参数假定")
    for marker in ("（覆土控制区段管顶覆土", "（管顶覆土"):
        position = label.rfind(marker)
        if position >= 0 and label.endswith("）"):
            label = label[:position]
            break
    if len(depths) == 1:
        label += f"（覆土控制区段管顶覆土{depths[0]:g}m）"
    elif depths:
        label += "（覆土控制区段管顶覆土按各对象参数）"
    basis["label"] = label
    inputs["quantity_basis"] = basis
    return deepcopy(basis)


def apply_assumed_construction(inputs, *, cover_depth=DEFAULT_WORKBENCH_COVER_M):
    """Fill live inputs in place and return an inspectable assumption report."""
    from .construction_rules import normalize_construction_inputs, is_circular_culvert
    from .batch_cover_profiles import is_pressure_cover_asset, has_supplied_design_profile
    from .pipe_dimensions import normalize_pipe_dimensions
    from .pipe_construction_defaults import apply_pipe_construction_defaults
    from .sluice_gate import is_sluice_gate
    if not math.isfinite(float(cover_depth)) or float(cover_depth) < 0:
        raise ValueError("管顶覆土须为有限非负数")
    assumptions = []

    def assign(asset, group, key, value, reason):
        node = asset.setdefault(group, {})
        if node.get(key) is not None:
            return
        node[key] = value
        path = group + "." + key
        asset.setdefault("parameter_sources", {})[path] = "施工参数假定：" + reason
        assumptions.append({"asset_id": asset["asset_id"], "name": asset.get("name"),
                            "field": path, "value": deepcopy(value), "reason": reason})

    assets = [a for network in inputs.get("networks", []) for a in network.get("assets", [])]
    for asset in assets:
        if is_sluice_gate(asset):
            continue
        normalize_pipe_dimensions(asset)
        pressure = is_pressure_cover_asset(asset)
        tunnel = asset.get("kind") == "tunnel"
        aqueduct = asset.get("kind") == "aqueduct"
        circular = asset.get("section_type", "").startswith("circular") and not tunnel
        section = asset.setdefault("section", {})
        if tunnel:
            default_paths = asset.setdefault("tunnel_construction_default_fields", [])
            for path in ("section.lining_thickness", "section.base_thickness", "section.shotcrete_thickness",
                         "construction.excavation_clearance"):
                if _value(asset, path) is None and path not in default_paths:
                    default_paths.append(path)
            assign(asset, "section", "lining_thickness", .30, "用户确认隧洞默认衬砌0.30m")
            if asset.get("section_type") in {"arch_tunnel", "flat_bottom_tunnel"}:
                assign(asset, "section", "base_thickness", .30, "用户确认隧洞默认衬砌0.30m")
            assign(asset, "section", "shotcrete_thickness", 0., "用户确认默认不计喷护")
            assign(asset, "construction", "excavation_clearance", 0., "用户确认默认不计超挖")
            if asset.get("source_tunnel_lining_selection_required"):
                asset["source_tunnel_lining_selection_required"] = False
                asset["tunnel_lining_selection_mode"] = "program_default"
                asset["missing_fields"] = [field for field in asset.get("missing_fields", [])
                                           if field != "section.rock_class"]
        elif circular and (section.get("earthwork_envelope_only") is True
                or section.get("nominal_diameter_m") is not None
                or any(p.get("nominal_diameter_m") is not None for p in section.get("pipes") or [])):
            # An explicit outside envelope is enough for excavation/backfill.
            # Do not manufacture a pipe bore, wall thickness, or material.
            assign(asset, "section", "pipe_count", len(section.get("pipes") or []) or 1, "按已给逐管布置；未给管数时按单管")
            if section.get("earthwork_envelope_only") is True or any(p.get("earthwork_envelope_only") for p in section.get("pipes") or []):
                note = "仅按已给管外径及来源高程基准计算管外包土方；管壁厚度未提供，管壁及内衬材料工程量未计。"
                notes = asset.setdefault("quantity_scope_notes", [])
                if note not in notes:
                    notes.append(note)
        elif circular:
            assign(asset, "section", "pipe_count", len(section.get("pipes") or []) or 1, "按已给逐管布置；未给管数时按单管")
            assign(asset, "section", "lining_thickness", 0., "未给内衬时暂不另设内衬")
            if section.get("wall_thickness") is None and section.get("inner_diameter") is not None and section.get("outer_diameter") is not None:
                section["wall_thickness"] = (float(section["outer_diameter"])-float(section["inner_diameter"]))/2-float(section.get("lining_thickness") or 0.)
                asset.setdefault("parameter_sources", {})["section.wall_thickness"] = "由设计已有内外径和内衬厚度推算"
            if section.get("nominal_diameter_m") is None:
                assign(asset, "section", "wall_thickness", .12 if pressure else .15,
                       "有压/倒虹吸管壁暂取0.12m，普通圆形管渠暂取0.15m")
                assign(asset, "section", "material", "concrete", "管壁材质未给时暂按混凝土")
            if float(section.get("lining_thickness") or 0.) > 0:
                assign(asset, "section", "lining_material", "same_as_wall", "内衬材质未给时暂与管壁相同")
            if section.get("inner_diameter") is None and section.get("inner_radius"):
                section["inner_diameter"] = 2*float(section["inner_radius"])
                asset.setdefault("parameter_sources", {})["section.inner_diameter"] = "水力设计内半径的两倍"
            if section.get("outer_diameter") is None and section.get("inner_diameter") is not None:
                section["outer_diameter"] = float(section["inner_diameter"])+2*(float(section["wall_thickness"])+float(section.get("lining_thickness") or 0.))
                asset.setdefault("parameter_sources", {})["section.outer_diameter"] = "水力内径＋管壁及内衬厚度"
            for alias in ("base_thickness", "wall_thickness_left", "wall_thickness_right", "roof_thickness"):
                assign(asset, "section", alias, section["wall_thickness"], "圆形管渠统一管壁厚度对应底、侧、顶厚度")
            for index, pipe in enumerate(section.get("pipes") or [], 1):
                for key in ("wall_thickness", "lining_thickness", "material", "lining_material"):
                    if pipe.get(key) is None and section.get(key) is not None:
                        pipe[key] = deepcopy(section[key])
                        path = f"section.pipes[{index}].{key}"
                        asset.setdefault("parameter_sources", {})[path] = "施工参数假定：采用本对象统一管壁/内衬设置"
                        assumptions.append({"asset_id": asset["asset_id"], "name": asset.get("name"), "field": path,
                                            "value": pipe[key], "reason": "采用本对象统一管壁/内衬设置"})
                if pipe.get("outer_diameter") is None and pipe.get("inner_diameter") is not None:
                    pipe["outer_diameter"] = float(pipe["inner_diameter"])+2*(float(pipe["wall_thickness"])+float(pipe.get("lining_thickness") or 0.))
        else:
            thickness = .15 if asset.get("kind") == "open_channel" else .30
            for key in ("base_thickness", "wall_thickness_left", "wall_thickness_right"):
                if _value(asset, "section." + key) is None:
                    assign(asset, "section", key, thickness, "明渠衬砌暂取0.15m；暗涵墙、底板暂取0.30m")
            if asset.get("kind") == "culvert":
                assign(asset, "section", "roof_thickness", .30, "暗涵顶板/拱圈暂取0.30m")
        if circular and not tunnel:
            raw_pipes = section.get("pipes") or []
            if not (len(raw_pipes) > 1 and all(p.get("offset") is not None for p in raw_pipes)):
                assign(asset, "section", "pipe_spacing", .5 if int(section["pipe_count"]) > 1 else 0.,
                       "多管相邻净距暂取0.50m；单管为0")
            pipe_defaults = apply_pipe_construction_defaults(asset)
            assumptions.extend(pipe_defaults["assumptions"])
        for side in (("left", "right", "front", "back") if aqueduct else ("left", "right")):
            if not circular:
                assign(asset, "construction", "working_space_"+side, .50, "左右施工工作面各0.50m")
            assign(asset, "construction", "excavation_slope_"+side, 1., "开挖坡比暂取1:1")
            if side in {"front","back"}:continue
            assign(asset, "construction", "bank_top_width_"+side, .50 if asset.get("kind") == "open_channel" else 0.,
                   "明渠左右平台各0.50m，其余为0")
            assign(asset, "construction", "bank_slope_"+side, 1.5, "填筑坡比暂取1:1.5")
        no_bedding = asset.get("section_type") == "u_channel" or tunnel
        if not circular:
            assign(asset, "construction", "bedding_thickness", 0. if no_bedding else .10,
                   "暗挖隧洞独立垫层暂设0，连续衬砌和喷护单列" if tunnel else "U形永久无垫层" if no_bedding else "非U形结构垫层暂取0.10m")
            assign(asset, "construction", "bedding_extension", 0. if no_bedding else .10,
                   "暗挖隧洞无独立垫层外伸" if tunnel else "U形永久无垫层" if no_bedding else "非U形结构垫层每侧外伸暂取0.10m")
        assign(asset, "construction", "excavation_base_mode", "flat", "开挖底面暂按平底沟槽")
        assign(asset, "construction", "target_mode", "restore_terrain" if pressure or tunnel or aqueduct or is_circular_culvert(asset) else "union_terrain",
               "圆管涵及埋管恢复原地面；其他明渠按结构和地形形成施工完成面")
        if pressure:
            assign(asset, "construction", "installation_mode", "buried", "未给敷设方式时暂按明挖埋管")
            assign(asset, "construction", "cover_depth", float(cover_depth), "用户可修改的管顶覆土参数")
            actual_axis = has_supplied_design_profile(asset)
            assign(asset, "construction", "burial_mode", "actual_axis" if actual_axis else "cover_depth",
                   "保留专项实际轴线" if actual_axis else "无专项实际轴线时按地形和覆土生成")
        asset["missing_fields"] = [field for field in asset.get("missing_fields", [])
            if not (field.startswith(("construction.", "section.")) and _value(asset, field) is not None)]
        if aqueduct and not section.get("discrete_components"):
            asset.setdefault("quantity_scope_notes", []).append("尚未输入渡槽拉杆、支承、墩台或基础离散构件；当前仅有槽身量，不能作为完整渡槽工程量")
        if tunnel and not section.get("quantity_rules"):
            asset.setdefault("quantity_scope_notes", []).append("排水孔、锚杆及灌浆等尚未设置独立计量规则，当前不含这些项目")
    changes = normalize_construction_inputs(inputs)
    lookup = {asset["asset_id"]: asset for asset in assets}
    for issue in inputs.get("diagnostics", []):
        asset = lookup.get(issue.get("asset_id"))
        if asset and issue.get("code") == "missing_construction" and _value(asset, issue.get("field", "")) is not None:
            issue.update(resolved=True, resolution="explicit_construction_assumption")
    basis = refresh_quantity_basis(inputs)
    existing = {(v.get("asset_id"), v.get("field")): v for v in inputs.get("construction_assumptions", [])}
    existing.update({(v["asset_id"], v["field"]): v for v in assumptions})
    inputs["construction_assumptions"] = list(existing.values())
    diagnostic = {"code": "explicit_construction_assumptions", "severity": "info",
        "message": "隧洞采用水面线净尺寸；未填衬砌及底板厚度默认0.30m，喷护及超挖默认0，保留已填设计参数。其余未给施工参数暂用：明渠衬砌0.15m、暗涵墙底顶及渡槽槽身0.30m；管道工作面和当前支承厚度按用户表7.2分档，各种支承分别采用、石渣换填按条件设置；槽底至管顶以上0.5m人工回填，其上机械回填。其余结构工作面0.50m、非U形非隧洞垫层0.10m、开挖1:1、填筑1:1.5；参数可编辑，U形明渠无底部垫层。DN管道按已给外包计算土方，管壁及内衬材料按实际设计参数计量。"}
    diagnostics = inputs.setdefault("diagnostics", [])
    if not any(d.get("code") == diagnostic["code"] for d in diagnostics):
        diagnostics.append(diagnostic)
    return {"assumptions": assumptions, "filled_count": len(assumptions), "construction_rule_changes": changes,
            "quantity_basis": deepcopy(basis)}
