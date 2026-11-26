"""Traceable section rates and multi-unit component quantities."""
from __future__ import annotations

from copy import deepcopy
import math
import re

import numpy as np

from .contracts import ConstructionInputError

PREFIX = "component__"
_GAUSS_X, _GAUSS_W = np.polynomial.legendre.leggauss(5)


def component_role(component_id):
    if not isinstance(component_id, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", component_id):
        raise ConstructionInputError("材料构件编号须为字母开头的稳定英文编号")
    return PREFIX + component_id


def extra_material_roles(assets):
    roles = set()
    for asset in assets:
        from .pipe_dimensions import is_pipe_asset
        if is_pipe_asset(asset):
            section = asset.get("section", {})
            count = len(section["pipes"]) if section.get("pipes") else int(section.get("pipe_count", 1))
            for index in range(1, count + 1):
                roles.update(component_role(f"{kind}_{index}") for kind in ("pipe_wall", "pipe_lining"))
        variants = [asset]
        if asset.get("section_scheme_terrain_variants"):
            from .section_terrain_variants import terrain_variant_asset
            variants.extend(terrain_variant_asset(asset, code, validate=False, apply_selectors=False)
                            for code in asset["section_scheme_terrain_variants"])
        from .drawing_bindings import _set
        from .section_scheme_bindings import _field_paths
        selectors = [*(asset.get("section_scheme_selectors") or []),
            *(row for variant in (asset.get("section_scheme_terrain_variants") or {}).values()
              for row in variant.get("selectors", []))]
        for current in list(variants):
            for selector in selectors:
                expanded = deepcopy(current)
                for path, value in _field_paths(selector.get("fields") or {}, template=True)[0].items():
                    _set(expanded, path, value)
                variants.append(expanded)
        for current in variants:
            for key in ("retaining_wall_profile", "foundation_replacement_profile", "rockfill_profile", "gabion_profile"):
                if current.get("section", {}).get(key):
                    roles.add(component_role({"retaining_wall_profile":"retaining_wall", "rockfill_profile":"rockfill", "gabion_profile":"gabion"}.get(key,key)))
            construction = current.get("construction", {})
            replacement = construction.get("foundation_replacement") or {}
            if float(replacement.get("thickness", construction.get("foundation_replacement_thickness", 0)) or 0) > 0:
                roles.add(component_role("foundation_replacement"))
            for key, identifier in (("pipe_seat", "pipe_seat"), ("encasement", "pipe_encasement")):
                alias = "pipe_support" if key == "pipe_seat" else "pipe_encasement"
                spec = construction.get(key) or construction.get(alias) or {}
                if spec.get("enabled", True) and spec.get("separate_material"):
                    roles.add(component_role(identifier))
            seen = set()
            for spec in current.get("section", {}).get("component_specs", []):
                cid = spec.get("component_id")
                role = component_role(cid)
                if cid in seen:
                    raise ConstructionInputError("同一断面的材料构件编号重复：" + cid)
                seen.add(cid)
                if spec.get("unit") == "m3":
                    roles.add(role)
                elif spec.get("unit") != "m2":
                    raise ConstructionInputError("当前断面材料构件只支持m3体积与m2铺设面积")
    return tuple(sorted(roles))


def material_identity(asset, role):
    section = asset.get("section", {})
    if role.startswith(PREFIX):
        spec = next((x for x in section.get("component_specs", [])
                     if component_role(x["component_id"]) == role), {})
    else:
        spec = (section.get("material_specs") or {}).get(role, {})
    grade = spec.get("grade") or (section.get("material_grade") if role == "concrete" else
                                 asset.get("construction", {}).get("bedding_grade") if role == "bedding" else None)
    return spec.get("material", role), grade


def surface_rate(geometry, curvature=0., slope=0.):
    """Actual swept area per route metre, including cross-slope orientation.

    For R(s,t)=(axis(s)+u(t)*normal(s), z(s)+v(t)), the Jacobian is
    sqrt((1+k*u)^2*(du^2+dv^2) + grade^2*du^2).  Thus a vertical wall and
    a horizontal bed have different grade corrections.
    """
    if geometry.is_empty:
        return 0.
    parts = [geometry] if geometry.geom_type in {"LineString", "LinearRing"} else list(geometry.geoms)
    total = 0.
    for line in parts:
        points = list(line.coords)
        for (u0, v0), (u1, v1) in zip(points, points[1:]):
            du, dv = u1-u0, v1-v0
            if du == dv == 0:
                continue
            u = (u0+u1)/2 + _GAUSS_X*du/2
            total += float(np.sum(_GAUSS_W*np.sqrt((1+curvature*u)**2*(du*du+dv*dv)+slope*slope*du*du)))/2
    if not math.isfinite(total):
        raise ConstructionInputError("材料铺设面积的曲线或纵坡无效")
    return total


def _metadata(asset, spec, component_id, unit, method):
    bindings = asset.get("drawing_bindings") or []
    binding = asset.get("drawing_binding") or (bindings[-1] if bindings else {})
    return {"component_id": component_id, "name": spec.get("name", component_id),
            "material": spec.get("material", "未明确"), "grade": spec.get("grade", ""),
            "unit": unit, "method": method,
            "source_ids": deepcopy(spec.get("source_ids", [])),
            "source_handles": deepcopy(spec.get("source_handles", spec.get("handles", []))),
            "drawing_id": binding.get("drawing_id", ""),
            "template_id": binding.get("template_id", ""),
            "source_sha256": binding.get("source_sha256", ""),
            "drawing_sources": deepcopy(bindings),
            "status": "drawing_bound" if binding else "current_construction_parameters"}


def nonconcrete_pipe_components(asset, structure):
    """Keep each actual non-concrete annulus separate, including its material."""
    result = []
    section = asset.get("section", {})
    for index, pipe in enumerate(structure.get("pipes", []), 1):
        ro = pipe["outer_diameter"] / 2
        rw, ri = ro-pipe["wall_thickness"], pipe["inner_diameter"]/2
        for kind, key, area, label, material, grade in (
                ("pipe_wall", "pipe_wall_regions", math.pi*(ro*ro-rw*rw), "管壁", pipe.get("material"),
                 pipe.get("material_grade", section.get("material_grade", ""))),
                ("pipe_lining", "pipe_lining_regions", math.pi*(rw*rw-ri*ri), "管内衬", pipe.get("lining_material"),
                 pipe.get("lining_grade", section.get("lining_grade", "")))):
            regions = structure.get(key, [])
            if len(regions) < index or regions[index-1].is_empty:
                continue
            if not material:
                raise ConstructionInputError(f"第{index}根{label}缺少实际材料，不能计为零")
            result.append({"component_id": f"{kind}_{index}", "name": f"第{index}根{label}",
                "material": material, "grade": grade, "geometry": regions[index-1],
                "normal_area": area, "offset": pipe["offset"], "vertical_slope": pipe["vertical_slope"]})
    return result


def section_components(asset, value, net, metrics):
    asset = value.get("effective_asset", asset)
    structure = value.get("structure")
    if structure is None:
        return []
    section = asset.get("section", {})
    result = []
    # Single-station queries share physical pipe rates with batch integration;
    # their initial polygon metrics do not carry the axis correction yet.
    if structure.get("pipes") and "concrete" in metrics and "quantity_method" not in metrics["concrete"]:
        rate = 0.
        for pipe, region in zip(structure["pipes"], structure.get("pipe_material_regions", [])):
            if region.is_empty:
                continue
            ownership = net["concrete"].intersection(region).area / region.area
            if 1e-7 < ownership < 1-1e-7:
                raise ConstructionInputError("管材发生部分空间归属，须明确实际边界")
            rate += pipe["concrete_normal_area"] * math.hypot(1+value["curvature"]*pipe["offset"],pipe["vertical_slope"]) * ownership
        support = net["concrete"].difference(structure["pipe_concrete"])
        rate += 0. if support.is_empty else support.area*(1+value["curvature"]*support.centroid.x)
        metrics["concrete"].update(weighted_area=rate,quantity_method="normal_material_area_actual_spatial_axis_length")
    for role, label in (("concrete", "衬砌/结构混凝土"), ("bedding", "垫层/找平")):
        if role not in metrics:
            continue
        spec = dict((section.get("material_specs") or {}).get(role, {}))
        spec.setdefault("name", label)
        spec.setdefault("material", "concrete" if role == "concrete" else asset.get("construction", {}).get("bedding_material", "bedding"))
        if role == "concrete":
            spec.setdefault("grade", section.get("material_grade", ""))
        else:
            spec.setdefault("grade", asset.get("construction", {}).get("bedding_grade", ""))
        result.append({**_metadata(asset, spec, role, "m3", metrics[role].get("quantity_method", "section_region_actual_midpoint_Simpson")),
                       "section_measure": net[role].area, "rate": metrics[role]["weighted_area"]})
    for spec in nonconcrete_pipe_components(asset, structure):
        cid = spec["component_id"]
        role = component_role(cid)
        ownership = net[role].intersection(spec["geometry"]).area / spec["geometry"].area
        if 1e-7 < ownership < 1-1e-7:
            raise ConstructionInputError("非混凝土管材发生部分空间归属，须明确实际边界")
        rate = spec["normal_area"]*math.hypot(1+value["curvature"]*spec["offset"],spec["vertical_slope"])*ownership
        method = metrics[role].get("quantity_method", "normal_material_area_actual_spatial_axis_length")
        metrics[role].update(weighted_area=rate, quantity_method=method)
        result.append({**_metadata(asset, spec, cid, "m3", method),
                       "section_measure": net[role].area, "rate": rate})
    for cid, component in structure.get("component_regions", {}).items():
        role = component_role(cid)
        result.append({**_metadata(asset, component, cid, "m3", "section_region_actual_midpoint_Simpson"),
                       "section_measure": net[role].area, "rate": metrics[role]["weighted_area"]})
    for cid, component in structure.get("component_surfaces", {}).items():
        # A partially allocated physical material surface requires a dedicated
        # clipping rule. Do not manufacture a net area using a volume ratio.
        for rid, region in structure.get("component_regions", {}).items():
            original = region["geometry"].area
            if original and abs(net[component_role(rid)].area-original) > max(1e-8, original*1e-7):
                raise ConstructionInputError("材料层发生空间扣重，关联铺设面积须补充实际边界，不能按体积比例折算")
        line = component["geometry"]
        result.append({**_metadata(asset, component, cid, "m2", "swept_surface_actual_curvature_and_grade_Simpson"),
                       "section_measure": line.length,
                       "rate": surface_rate(line, value["curvature"], value["slope"])})
    return result


def integrate_components(records, length, asset, start, end):
    maps = [{(x["component_id"], x["unit"]): x for x in group} for group in records]
    keys = set(maps[0])
    if any(set(group) != keys for group in maps[1:]):
        raise ConstructionInputError("积分段材料构件发生突变，须在变化桩号分段")
    result = []
    for key in sorted(keys):
        source = maps[0][key]
        if any((x[key].get("material"), x[key].get("grade")) != (source.get("material"), source.get("grade")) for x in maps[1:]):
            raise ConstructionInputError("积分段材料等级发生变化，须拆分区段")
        metadata = {k: deepcopy(v) for k, v in source.items() if k not in {"rate", "section_measure"}}
        result.append({**metadata, "asset_id": asset["asset_id"], "asset_name": asset.get("name", ""),
                       "station_start": start, "station_end": end,
                       "quantity": length/6*sum(c*group[key]["rate"] for c, group in zip((1, 4, 1), maps))})
    return result


def aggregate_components(segments, assets):
    accum = {}
    for segment in segments:
        for item in segment.get("quantity_items", []):
            key = (item["asset_id"], item["component_id"], item["material"], item["grade"], item["unit"])
            if key not in accum:
                accum[key] = {**deepcopy(item), "quantity": 0.}
            row = accum[key]
            row["quantity"] += item["quantity"]
            row["station_start"] = min(row["station_start"], item["station_start"])
            row["station_end"] = max(row["station_end"], item["station_end"])
    return list(accum.values())
