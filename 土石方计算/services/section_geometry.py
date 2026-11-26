"""Explicit section geometry for the section-method workbench (metres).

The filled outer envelope excludes earth; material rings exclude the hydraulic
void. These are deliberately different objects. No solid kernel is used.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import math

from shapely import affinity
from shapely.geometry import LineString, Polygon, box, mapping
from shapely.ops import linemerge, unary_union
from shapely.geometry.polygon import orient

from .contracts import ConstructionInputError, finite_number
from .construction_rules import effective_construction, normalized_construction, is_circular_culvert

PIPE_BEDDING_EXCAVATION_RULE = "pipe_bedding_actual_excavation_closure_v1"


@lru_cache(maxsize=16)
def _circle_directions(count):
    return tuple((math.cos(2*math.pi*i/count),math.sin(2*math.pi*i/count)) for i in range(count))


def _material_category(value, *, strict=False, label="材料"):
    name=str(value or "").strip().lower()
    if name in {"concrete","rc","reinforced_concrete","混凝土","钢筋混凝土","混凝土管","钢筋混凝土管"}:
        return "concrete"
    if name in {"steel","other","plastic","pvc","pe","hdpe","frpm","grp","gfrp","di","ductile_iron",
                "stainless_steel","钢","钢管","钢材","不锈钢","塑料","塑料管","其他","球墨铸铁管",
                "hdpe管","玻璃钢夹砂管"}:
        return "other"
    if strict:raise ConstructionInputError(f"{label}未明确材料分类，请选择混凝土、钢材或其他材料")
    return "unknown"


def number(data, key, default=None, *, positive=False):
    value = finite_number(data.get(key, default), key)
    if value < 0 or (positive and value <= 0):
        raise ConstructionInputError(f"{key} 必须为{'正数' if positive else '非负数'}")
    return value


def rings(shape):
    if shape.is_empty:
        return []
    parts = [shape] if shape.geom_type == "Polygon" else shape.geoms
    result = []
    for part in parts:
        if part.geom_type != "Polygon":
            continue
        if part.interiors:
            raise ConstructionInputError("占位外包不应含孔洞")
        result.append([list(p) for p in orient(part, sign=1).exterior.coords])
    return result


def validated(shape, label):
    if not shape.is_valid or not math.isfinite(shape.area):
        raise ConstructionInputError(f"{label}轮廓无效；不能自动修复改变构造")
    return shape


def clearance_from_pipe_offsets(pipes):
    """Clear gaps between consecutive pipes with known offsets and outside diameters."""
    if len(pipes) < 2 or not all(p.get("offset") is not None for p in pipes):
        return None
    gaps = [finite_number(b["offset"], "管横向偏距") - finite_number(a["offset"], "管横向偏距")
            - (a["outer_diameter"] + b["outer_diameter"]) / 2 for a, b in zip(pipes, pipes[1:])]
    return [0. if -1e-8 <= g < 0. else g for g in gaps]


def pipe_specs(section, *, require_material=False, recommended_material="concrete", require_lining_material=None):
    """Canonical pipes and clear horizontal spacing, with no guessed material."""
    from .pipe_dimensions import CONSTRUCTION_WALL, MATERIAL_OUTER, effective_pipe_section
    section = effective_pipe_section(section)
    raw = section.get("pipes")
    if raw is None:
        count = number(section, "pipe_count", 1, positive=True)
        if count != int(count):
            raise ConstructionInputError("pipe_count 必须为正整数")
        raw = [deepcopy(section) for _ in range(int(count))]
    if not isinstance(raw, list) or not raw:
        raise ConstructionInputError("pipes 必须为非空管道列表")
    envelope_only = section.get("earthwork_envelope_only") is True
    pipes = []
    require_lining_material=bool(require_material) if require_lining_material is None else bool(require_lining_material)
    for i, entry in enumerate(raw):
        p = deepcopy(entry)
        if p.get("wall_thickness", section.get("wall_thickness")) is not None:
            if number(p, "wall_thickness", section.get("wall_thickness")) < 0:
                raise ConstructionInputError("管壁厚度不能为负")
        if p.get("earthwork_envelope_only", envelope_only) is True:
            # These zero-thickness dimensions are geometry placeholders only.
            # The user's outside diameter is the sole dimensional input; no
            # pipe-wall or hydraulic-bore quantity is inferred from it.
            outer = number(p, "outer_diameter", section.get("outer_diameter"), positive=True)
            reference_inner = next((value for value in (
                p.get("construction_inner_diameter_m"), p.get("hydraulic_inner_diameter_m"), p.get("inner_diameter"),
                p.get("nominal_diameter_m"), section.get("hydraulic_inner_diameter_m"), section.get("inner_diameter"),
                section.get("nominal_diameter_m")) if value is not None), None)
            p.update(earthwork_envelope_only=True, outer_diameter=outer,
                     inner_diameter=outer, wall_thickness=0., lining_thickness=0.,
                     inner_diameter_is_placeholder=True, material=p.get("material") or section.get("material"),
                     material_category="unknown", lining_material=None,
                     lining_material_category="unknown", concrete_normal_area=0.)
            if reference_inner is not None:
                p["reference_inner_diameter_m"] = finite_number(reference_inner, "高程换算净内径")
            pipes.append(p)
            continue
        wall = number(p, "wall_thickness", section.get("wall_thickness"), positive=True)
        lining = number(p, "lining_thickness", section.get("lining_thickness", 0))
        inner = p.get("construction_inner_diameter_m", p.get("inner_diameter"))
        occupied_outer = p.get("outer_diameter") if p.get(CONSTRUCTION_WALL) is not None else None
        outer = p.get(MATERIAL_OUTER) if occupied_outer is not None else p.get("outer_diameter")
        if inner is None and outer is None:
            raise ConstructionInputError(f"第{i+1}根管缺内径或外径")
        if inner is None:
            outer = finite_number(outer, "outer_diameter")
            inner = outer-2*(wall+lining)
        else:
            inner = finite_number(inner, "inner_diameter")
            derived = inner+2*(wall+lining)
            if outer is not None and not math.isclose(float(outer), derived, rel_tol=1e-7, abs_tol=1e-7):
                raise ConstructionInputError(f"第{i+1}根管内径、外径、壁厚及内衬不一致")
            outer = derived
        if inner <= 0 or outer <= inner:
            raise ConstructionInputError(f"第{i+1}根管尺寸无效")
        if occupied_outer is not None and occupied_outer < outer - 1e-8:
            raise ConstructionInputError(f"第{i+1}根管施工占用直径不能小于实际管外径 {outer:g} m")
        if occupied_outer is not None:
            p[MATERIAL_OUTER] = outer
        material = p.get("material") or section.get("material")
        if not material or str(material).strip().lower() in {"unknown", "none", "未知", "待补齐", ""}:
            if require_material:
                raise ConstructionInputError(f"第{i+1}根有压管道/倒虹吸缺少管材，须补齐后计算")
            material = recommended_material
            p["material_source"] = "section_type_recommendation" if recommended_material else "unknown"
        p.update(inner_diameter=inner, outer_diameter=outer if occupied_outer is None else occupied_outer, wall_thickness=wall,
                 lining_thickness=lining, material=material)
        category=_material_category(material,strict=require_material,label=f"第{i+1}根管壁")
        lining_material=p.get("lining_material") or section.get("lining_material")
        if lining and lining_material=="same_as_wall":
            lining_material=material;p["lining_material_source"]="explicit_same_as_wall"
        if lining and not lining_material and require_lining_material:
            raise ConstructionInputError(f"第{i+1}根管内衬厚度非零，须补齐 lining_material")
        lining_category=_material_category(lining_material,strict=bool(lining and require_lining_material),label=f"第{i+1}根管内衬")
        p.update(material_category=category,lining_material=lining_material,lining_material_category=lining_category)
        ro=outer/2;rw=ro-wall;ri=inner/2
        p["concrete_normal_area"]=(math.pi*(ro*ro-rw*rw) if category=="concrete" else 0.)+(
            math.pi*(rw*rw-ri*ri) if lining and lining_category=="concrete" else 0.)
        pipes.append(p)
    spacing = section.get("pipe_spacing")
    if spacing is None:
        spacing = clearance_from_pipe_offsets(pipes)
        if spacing is not None:
            for p in pipes:
                p["spacing_source"] = "derived_from_explicit_pipe_offsets"
        elif len(pipes) > 1 and require_material:
            raise ConstructionInputError("多管缺少管间净距 pipe_spacing，须补齐后计算")
        else:
            spacing = 0
    gaps = [spacing]*(len(pipes)-1) if not isinstance(spacing, list) else spacing
    if len(gaps) != len(pipes)-1:
        raise ConstructionInputError("管间净距数量须为管数减一")
    gaps = [finite_number(g, "pipe_spacing") for g in gaps]
    if any(g < 0 for g in gaps):
        raise ConstructionInputError("管间净距不能为负")
    width = sum(p["outer_diameter"] for p in pipes)+sum(gaps)
    cursor = -width/2
    for i, p in enumerate(pipes):
        computed = cursor+p["outer_diameter"]/2
        p["offset"] = finite_number(p.get("offset", computed), "管横向偏距")
        cursor += p["outer_diameter"]+(gaps[i] if i < len(gaps) else 0)
    for a, b in zip(pipes, pipes[1:]):
        if b["offset"]-a["offset"] < (a["outer_diameter"]+b["outer_diameter"])/2-1e-8:
            raise ConstructionInputError("多管外包重叠或布置次序不符")
    return pipes


def _offset_polygon(inner, left, right, base):
    lines = []
    crest = max(z for _, z in inner)
    for a, b in zip(inner, inner[1:]+inner[:1]):
        dx, dz = b[0]-a[0], b[1]-a[1]
        length = math.hypot(dx, dz)
        thickness = 0 if a[1] == b[1] == crest else (
            base if a[1] == b[1] == 0 else right if (a[0]+b[0])/2 > 0 else left)
        lines.append(([a[0]+dz/length*thickness, a[1]-dx/length*thickness], [dx, dz]))
    points = []
    for i, (p, v) in enumerate(lines):
        q, u = lines[i-1]
        den = u[0]*v[1]-u[1]*v[0]
        if abs(den) < 1e-12:
            raise ConstructionInputError("相邻结构边不能确定厚度交点")
        t = ((p[0]-q[0])*v[1]-(p[1]-q[1])*v[0])/den
        points.append((q[0]+t*u[0], q[1]+t*u[1]))
    return validated(Polygon(points), "结构外包")


def _u_outer(section, left, right, bottom, count):
    r = number(section, "inner_radius", positive=True)
    height = number(section, "inner_height", positive=True)
    half = math.radians(number(section, "u_arc_angle_degrees", 180, positive=True))/2
    alpha = math.radians(number(section, "u_side_angle_degrees", 0))
    if half > math.pi or alpha >= math.pi/2 or height < r*(1-math.cos(half))-1e-10:
        raise ConstructionInputError("U形圆心角、墙倾角或渠高无效")
    radius = r+bottom
    joins = []
    corners = []
    tops = []
    for thickness in (left, right):
        px = r*math.sin(half)+thickness*math.cos(alpha)
        pz = r*(1-math.cos(half))-thickness*math.sin(alpha)
        ux, uz = math.sin(alpha), math.cos(alpha)
        dot = px*ux+(pz-r)*uz
        discriminant = dot*dot+radius*radius-px*px-(pz-r)**2
        if discriminant < -1e-10:
            # A wall thicker than the bottom arc has no circle/parallel-wall
            # intersection. The actual radial construction joint is retained,
            # rather than silently changing either independent thickness.
            x,z=radius*math.sin(half),r-radius*math.cos(half)
            corner=(px,pz)
        else:
            t = min((-dot-math.sqrt(max(0, discriminant)), -dot+math.sqrt(max(0, discriminant))), key=abs)
            x, z = px+t*ux, pz+t*uz
            corner=None
        if z > height:
            z = height
            x = math.sqrt(max(0, radius*radius-(height-r)**2))
        joins.append((x, z))
        corners.append(corner)
        tops.append((px+(height-pz)*math.tan(alpha), height))
    start = math.pi-math.atan2(joins[0][1]-r, joins[0][0])
    end = 2*math.pi+math.atan2(joins[1][1]-r, joins[1][0])
    n = max(2, math.ceil((end-start)*count/math.pi))
    angles=sorted({start+(end-start)*i/n for i in range(n+1)}|{a for a in (math.pi,1.5*math.pi,2*math.pi) if start<a<end})
    points = [(radius*math.cos(a), r+radius*math.sin(a)) for a in angles]
    points[0], points[-1] = (-joins[0][0], joins[0][1]), joins[1]
    if corners[1] and corners[1][1]<height:
        points.append(corners[1])
    if height > joins[1][1]+1e-10:
        points.append(tops[1])
    if height > joins[0][1]+1e-10:
        points.append((-tops[0][0], height))
    if corners[0] and corners[0][1]<height:
        points.append((-corners[0][0],corners[0][1]))
    return validated(Polygon(points), "U形外包")


def _chamfered_rectangular_void(section, width, height):
    """Cut explicit corner haunches from a clear B/H rectangle, in metres."""
    raw = section.get("inner_chamfers", section.get("inner_chamfer", 0.))
    keys = ("bottom_left", "bottom_right", "top_right", "top_left")
    if isinstance(raw, dict):
        unknown = set(raw).difference(keys)
        if unknown:
            raise ConstructionInputError("内倒角存在未知角点：" + "、".join(sorted(unknown)))
        values = [raw.get(key, 0.) for key in keys]
    else:
        values = [raw] * 4
    corners = []
    for key, value in zip(keys, values):
        if isinstance(value, (list, tuple)):
            if len(value) != 2:
                raise ConstructionInputError(f"内倒角 {key} 须为横、竖两尺寸")
            dx, dz = (finite_number(v, f"inner_chamfers.{key}") for v in value)
        else:
            dx = dz = finite_number(value, f"inner_chamfers.{key}")
        if min(dx, dz) < 0 or bool(dx) != bool(dz):
            raise ConstructionInputError(f"内倒角 {key} 须为同时为零或同时为正的尺寸")
        if dx >= width or dz >= height:
            raise ConstructionInputError(f"内倒角 {key} 超出净空")
        corners.append((dx, dz))
    bl, br, tr, tl = corners
    if (bl[0]+br[0] >= width or tl[0]+tr[0] >= width or
            bl[1]+tl[1] >= height or br[1]+tr[1] >= height):
        raise ConstructionInputError("相邻内倒角重叠或消除了净腔直边")
    half = width/2
    points = [(-half+bl[0], 0.), (half-br[0], 0.), (half, br[1]),
              (half, height-tr[1]), (half-tr[0], height),
              (-half+tl[0], height), (-half, height-tl[1]), (-half, bl[1])]
    points = [p for i, p in enumerate(points) if p != points[i-1]]
    return validated(Polygon(points), "暗涵内倒角净腔")


def _current_section(asset):
    """Use current design dimensions; drawing example sizes are reference only."""
    section = dict(asset["section"])
    if section.get("wall_thickness") is not None:
        for key in ("wall_thickness_left", "wall_thickness_right"):
            if section.get(key) is None:
                section.pop(key, None)
    return section


def _component_offset_envelope(asset, outer, distance, elevation, count):
    """Outer normal offset, retaining the open crown instead of bridging it."""
    if not distance:
        return outer
    stype, section = asset["section_type"], _current_section(asset)
    if stype == "u_channel":
        wall = number(section, "wall_thickness", section.get("wall_thickness_left", 0.))
        left = number(section, "wall_thickness_left", wall)
        right = number(section, "wall_thickness_right", wall)
        base = number(section, "u_bottom_thickness", section.get("base_thickness", wall))
        return affinity.translate(_u_outer(section, left+distance, right+distance,
                                           base+distance, count), yoff=elevation)
    if stype.startswith("circular"):
        raise ConstructionInputError("圆管附加法向材料层须提供各管真实内外径，不能套用明渠外衬模板")
    expanded = outer.buffer(distance, join_style=2)
    if stype.endswith("channel"):
        xmin, ymin, xmax, crest = expanded.bounds
        expanded = expanded.intersection(box(xmin, ymin, xmax, outer.bounds[3]))
    return validated(expanded, "独立材料层外轮廓")


def _component_surface(envelope, *, open_crown):
    if not open_crown:
        return envelope.boundary
    crest = envelope.bounds[3]
    parts = [envelope] if envelope.geom_type == "Polygon" else envelope.geoms
    edges = []
    for part in parts:
        coordinates = list(part.exterior.coords)
        edges.extend(LineString([a, b]) for a, b in zip(coordinates, coordinates[1:])
                     if not (abs(a[1]-crest) < 1e-10 and abs(b[1]-crest) < 1e-10))
    joined = unary_union(edges)
    return linemerge(joined) if joined.geom_type == "MultiLineString" else joined


def _add_section_components(structure, asset, *, elevation, arc_segments):
    """Compile extra material sections and actual laid surfaces, without factors."""
    specs = asset["section"].get("component_specs", [])
    if not isinstance(specs, list):
        raise ConstructionInputError("component_specs 须为独立材料构件列表")
    regions, surfaces, offsets = {}, {}, {}
    occupied = structure["outer"]
    for raw in specs:
        if not isinstance(raw, dict):
            raise ConstructionInputError("独立材料构件须为参数对象")
        if raw.get("component_id") in {member.get("component_id") for member in asset["section"].get("discrete_components",[])}:
            continue
        spec = deepcopy(raw)
        if not spec.get("enabled", True):
            continue
        identifier = str(spec.get("component_id", "")).strip()
        if not identifier or identifier in regions or identifier in surfaces:
            raise ConstructionInputError("独立材料 component_id 为空或重复")
        name = str(spec.get("name") or identifier)
        kind = spec.get("geometry_kind")
        if not str(spec.get("material") or "").strip():
            raise ConstructionInputError(f"{name} 缺少材料身份")
        after = spec.get("after_component_id")
        if after is not None:
            if after not in offsets:
                raise ConstructionInputError(f"{name} 的前置材料层不存在或顺序不符")
            start = offsets[after]
            if "offset_m" in spec and not math.isclose(number(spec, "offset_m"), start,
                                                       rel_tol=0., abs_tol=1e-10):
                raise ConstructionInputError(f"{name} 的 offset_m 与前置材料层冲突")
        else:
            # Every layer has an explicit location. Array order alone never
            # silently moves a layer or membrane to a different contact face.
            start = number(spec, "offset_m", 0.)
        inner = _component_offset_envelope(asset, structure["outer"], start, elevation, arc_segments)
        if kind == "outer_offset_layer":
            if spec.get("unit", "m3") != "m3":
                raise ConstructionInputError(f"{name} 实体材料层计量单位须为 m3")
            thickness = number(spec, "thickness_m", positive=True)
            finish = start+thickness
            extended = _component_offset_envelope(asset, structure["outer"], finish, elevation, arc_segments)
            geometry = validated(extended.difference(inner), name)
            if geometry.is_empty or geometry.area <= 0:
                raise ConstructionInputError(f"{name} 材料层没有有效面积")
            if geometry.intersection(occupied).area > 1e-8:
                raise ConstructionInputError(f"{name} 与结构或其他独立材料层占据同一区域")
            spec.update(component_id=identifier, name=name, unit="m3", offset_m=start,
                        thickness_m=thickness, geometry=geometry, section_measure=float(geometry.area),
                        occupies_space=True)
            regions[identifier] = spec
            occupied = unary_union([occupied, geometry])
            offsets[identifier] = finish
        elif kind == "outer_surface":
            if spec.get("unit", "m2") != "m2":
                raise ConstructionInputError(f"{name} 铺设面计量单位须为 m2")
            geometry = _component_surface(inner, open_crown=asset["section_type"].endswith("channel"))
            if geometry.is_empty or not geometry.is_simple:
                raise ConstructionInputError(f"{name} 铺设面无效")
            spec.update(component_id=identifier, name=name, unit="m2", offset_m=start,
                        geometry=geometry, section_measure=float(geometry.length), occupies_space=False)
            surfaces[identifier] = spec
            offsets[identifier] = start
        else:
            raise ConstructionInputError(f"{name} 尚不支持几何计量方法 {kind}")
    source = asset["section"]
    reference_dimensions = deepcopy(source.get("reference_dimensions") or {})
    if not isinstance(reference_dimensions, dict):
        reference_dimensions = {"drawing_reference": reference_dimensions}
    if "structural_inner_height" in source:
        # Compatibility with an earlier candidate: this field is historical
        # reference data and must never override the current waterline height.
        reference_dimensions.setdefault("legacy_structural_inner_height", source["structural_inner_height"])
    if reference_dimensions:
        structure["reference_dimensions"] = reference_dimensions
    if "inner_height" in source:
        structure["hydraulic_inner_height"] = deepcopy(source["inner_height"])
    structure.update(component_regions=regions, component_surfaces=surfaces)
    return structure


def section_structure(asset, *, elevation=0., slope=0., arc_segments=64, station=None, side="right",plan_curvature=0.):
    """Return filled outer/net void and real material polygons in section XY."""
    from .dedicated_structure_geometry import is_dedicated_structure, dedicated_structure
    if is_dedicated_structure(asset):
        return dedicated_structure(asset,elevation=elevation,slope=slope,
                                   arc_segments=arc_segments,station=station,side=side)
    from .construction_templates import _section_outer
    from .pipe_dimensions import MATERIAL_OUTER
    stype, s = asset["section_type"], _current_section(asset)
    if stype.startswith("circular"):
        pressure = asset.get("kind") in {"pipe", "pressure_pipe", "siphon"} or stype == "circular_siphon"
        pipes = pipe_specs(s, require_material=bool(asset.get("workbench_geometry") and pressure),
                           require_lining_material=bool(asset.get("workbench_geometry")))
        factor = math.hypot(1., slope)
        reference = (asset.get("design_profile") or {}).get("reference", asset.get("alignment", {}).get("elevation_reference", "pipe_axis"))
        if any(p.get("earthwork_envelope_only") for p in pipes) and reference not in {"pipe_axis", "inner_invert", "common_outer_bottom"}:
            raise ConstructionInputError("管道外包络须明确真实管轴、净内底或共同外管底高程")
        first_reference_inner = pipes[0].get("reference_inner_diameter_m", pipes[0]["inner_diameter"])
        if reference == "inner_invert" and pipes[0].get("earthwork_envelope_only"):
            if "reference_inner_diameter_m" not in pipes[0]:
                raise ConstructionInputError("仅外包络采用净内底高程时须有来源水力D或DN；否则须给真实管轴高程")
            if first_reference_inner <= 0 or first_reference_inner > pipes[0]["outer_diameter"] + 1e-8:
                raise ConstructionInputError("高程换算净内径大于施工占位外径，须明确实际尺寸或管轴高程")
        helix=bool(plan_curvature and slope)
        if plan_curvature and station is not None and asset.get("design_profile"):
            from .design_profiles import pipe_profile_circle
            if pipe_profile_circle(asset,pipes[0]["outer_diameter"]/2,pipes[0]["outer_diameter"]/2,station,side):
                from .finite_pipe_sections import UnsupportedPipeGeometry
                raise UnsupportedPipeGeometry("算法尚不支持同一桩号水平圆弧与真实竖向圆弧耦合的管面剖切",
                    diagnostics=[{"asset_id":asset.get("asset_id"),"station":station,"side":side,"plan_curvature":plan_curvature}])
        if reference=="inner_invert":
            base=elevation+(first_reference_inner-pipes[0]["outer_diameter"])/2*factor
        else:
            base = elevation if reference == "common_outer_bottom" else elevation-pipes[0]["outer_diameter"]/2*factor
        if helix:
            from .finite_pipe_sections import pipe_height
            first=pipes[0]
            height0=pipe_height(first["outer_diameter"]/2,first["offset"],plan_curvature,slope)
            base=elevation if reference=="common_outer_bottom" else elevation-height0
            if reference=="inner_invert":base=elevation+pipe_height(first_reference_inner/2,first["offset"],plan_curvature,slope)-height0
        outer, void, concrete, other, lining = [], [], [], [], []
        centers = []; pipe_material_regions=[];pipe_wall_regions=[];pipe_lining_regions=[]
        for p in pipes:
            center = base+p["outer_diameter"]/2*factor
            pipe_slope=slope; circle_profile=None
            if helix:
                center=base+pipe_height(p["outer_diameter"]/2,p["offset"],plan_curvature,slope)
            elif station is not None and asset.get("design_profile"):
                from .design_profiles import evaluate_pipe_axis, pipe_profile_circle
                center,pipe_slope=evaluate_pipe_axis(asset,p["outer_diameter"]/2,pipes[0]["outer_diameter"]/2,station,side)
                circle_profile=pipe_profile_circle(asset,p["outer_diameter"]/2,pipes[0]["outer_diameter"]/2,station,side)
                if circle_profile:
                    support_squared=circle_profile["support_radius"]**2-(station-circle_profile["center_station"])**2
                    if support_squared<=1e-12:raise ConstructionInputError("共同外底圆弧接近竖直切线")
                    base=circle_profile["center_elevation"]+circle_profile["branch"]*math.sqrt(support_squared)
            pipe_factor=math.hypot(1.,pipe_slope)
            def circle(radius):
                if helix:
                    from .finite_pipe_sections import helix_outline
                    points,_,_=helix_outline(radius,p["offset"],plan_curvature,slope,arc_segments)
                    return validated(Polygon([(x,z+center) for x,z in points]),"真实水平弯曲有坡管断面")
                points=[]
                for cosine,sine in _circle_directions(arc_segments):
                    height=center+pipe_factor*radius*sine
                    if circle_profile:
                        branch=circle_profile["branch"]
                        rr=circle_profile["radius"]+branch*radius*sine
                        radicand=rr*rr-(station-circle_profile["center_station"])**2
                        if radicand<=1e-12:
                            raise ConstructionInputError("真实竖弯管外包接近竖直切线，须补充可解析过渡")
                        height=circle_profile["center_elevation"]+branch*math.sqrt(radicand)
                    points.append((p["offset"]+radius*cosine,height))
                return validated(Polygon(points),"真实管断面")
            o, n = circle(p["outer_diameter"]/2), circle(p["inner_diameter"]/2)
            actual_outer = p.get(MATERIAL_OUTER, p["outer_diameter"]) if p["wall_thickness"] else p["outer_diameter"]
            material_outline = o if actual_outer == p["outer_diameter"] else circle(actual_outer/2)
            wall_inner = circle(actual_outer/2-p["wall_thickness"])
            wall = material_outline.difference(wall_inner)
            wall_concrete=p["material_category"]=="concrete"
            (concrete if wall_concrete else other).append(wall)
            pipe_wall_regions.append(Polygon() if wall_concrete else wall)
            pipe_lining_region=Polygon()
            pipe_concrete=[wall] if wall_concrete else []
            if p["lining_thickness"]:
                lining_shape=wall_inner.difference(n)
                if p["lining_material_category"]=="concrete":
                    concrete.append(lining_shape);pipe_concrete.append(lining_shape)
                else:
                    lining.append(lining_shape);pipe_lining_region=lining_shape
            outer.append(o); void.append(n); centers.append([p["offset"], center])
            p["vertical_slope"]=pipe_slope
            p["axis_elevation"]=center
            p["outer_bottom"]=o.bounds[1]
            p["outer_top"]=o.bounds[3]
            if helix:
                from .finite_pipe_sections import helix_outline
                _,_,foot=helix_outline(p["outer_diameter"]/2,p["offset"],plan_curvature,slope,arc_segments)
                p.update(outer_bottom_offset=foot,outer_top_offset=foot,plan_curvature=plan_curvature,
                    actual_plan_grade=slope/(1+plan_curvature*p["offset"]),
                    section_model="finite_helix_normal_disk_radial_cut",
                    section_model_scope="local_one_sided_constant_horizontal_curvature_and_profile_line; no inferred transition")
            pipe_material_regions.append(unary_union(pipe_concrete) if pipe_concrete else Polygon())
            pipe_lining_regions.append(pipe_lining_region)
        materials = {"concrete":unary_union(concrete), "pipe_wall":unary_union(other), "lining":unary_union(lining)}
        result = {"outer":unary_union(outer), "net_void":unary_union(void), "materials":materials,
                "pipe_centers":centers,"pipe_material_regions":pipe_material_regions,"pipe_concrete":unary_union(concrete),
                "pipe_wall_regions":pipe_wall_regions,"pipe_lining_regions":pipe_lining_regions,
                "pipes":pipes, "reference":reference, "support_elevation":base, "section_type":stype}
        from .section_scheme_components import apply_scheme_profiles
        from .dedicated_structure_geometry import add_buried_pipe_members
        result=apply_scheme_profiles(_add_section_components(result, asset, elevation=elevation, arc_segments=arc_segments),asset,elevation)
        return add_buried_pipe_members(result,asset,station,side)
    if asset.get("workbench_geometry") and stype!="box_foundation":
        if not any(k in s for k in ("wall_thickness","wall_thickness_left")):
            raise ConstructionInputError("缺少有效侧墙/衬砌厚度")
        if not any(k in s for k in ("base_thickness","u_bottom_thickness")):
            raise ConstructionInputError("缺少有效底板/底弧厚度")
    wall = number(s, "wall_thickness", s.get("wall_thickness_left", 0))
    left, right = number(s, "wall_thickness_left", wall), number(s, "wall_thickness_right", wall)
    base = number(s, "base_thickness", wall if stype == "u_channel" else 0)
    roof = number(s, "roof_thickness", 0)
    advanced = asset.get("workbench_geometry", False) or any(k in s for k in ("wall_thickness_left", "wall_thickness_right", "u_bottom_thickness", "component_specs"))
    if stype == "box_foundation":
        outer = Polygon(_section_outer(stype, s, arc_segments)[0][0]); net = Polygon()
    elif stype == "u_channel":
        outer = _u_outer(s, left, right, number(s, "u_bottom_thickness", base), arc_segments) if advanced else Polygon(_section_outer(stype, s, arc_segments)[0][0])
        net = Polygon(_section_outer(stype, {**s, "wall_thickness":0, "base_thickness":0}, arc_segments)[0][0])
    elif stype == "arch_culvert":
        width, h = number(s, "inner_width", positive=True), number(s, "wall_height")
        angle = math.radians(number(s, "arch_angle_degrees", 180, positive=True))/2
        if angle > math.pi/2 or roof <= 0:
            raise ConstructionInputError("拱形暗涵须有有效圆拱角度及顶厚")
        radius = width/(2*math.sin(angle)); cz = h-radius*math.cos(angle)
        def arch(l, r, rad, floor):
            a = math.acos(r/rad); b = math.pi-math.acos(l/rad)
            return validated(Polygon([(-l,floor),(r,floor)]+[(rad*math.cos(a+(b-a)*i/arc_segments),cz+rad*math.sin(a+(b-a)*i/arc_segments)) for i in range(arc_segments+1)]), "圆拱")
        outer = arch(width/2+left, width/2+right, radius+roof, -base)
        net = arch(width/2,width/2,radius,0)
    elif stype == "rectangular_culvert":
        width, h = number(s,"inner_width",positive=True), number(s,"inner_height",positive=True)
        if min(left,right,base,roof) <= 0:
            raise ConstructionInputError("暗涵墙、底板和顶板厚度必须为正")
        outer = box(-width/2-left,-base,width/2+right,h+roof)
        net = _chamfered_rectangular_void(s, width, h)
    else:
        zero = {**s,"wall_thickness":0,"base_thickness":0}
        net = Polygon(_section_outer(stype, zero, arc_segments)[0][0])
        outer = _offset_polygon(list(net.exterior.coords)[:-1], left,right,base) if advanced else Polygon(_section_outer(stype,s,arc_segments)[0][0])
    if net.difference(outer).area > 1e-7:
        raise ConstructionInputError("结构外包没有完整包含净空")
    concrete = validated(outer.difference(net), "结构材料")
    result = {"outer":affinity.translate(outer,yoff=elevation),"net_void":affinity.translate(net,yoff=elevation),
            "materials":{"concrete":affinity.translate(concrete,yoff=elevation)},"reference":"inner_invert",
            "section_type":stype}
    from .section_scheme_components import apply_scheme_profiles
    return apply_scheme_profiles(_add_section_components(result, asset, elevation=elevation, arc_segments=arc_segments),asset,elevation)


def add_foundation_materials(structure, construction, *, arc_segments=64):
    """Add finite bedding/support/encasement, reject conflicting materials."""
    construction = normalized_construction(structure.get("section_type"), construction)
    outer = structure["outer"]
    materials = deepcopy(structure["materials"])
    left,bottom,right,top = outer.bounds
    extension = number(construction,"bedding_extension",0)
    thickness = number(construction,"bedding_thickness",0)
    bedding = box(left-extension,bottom-thickness,right+extension,bottom) if thickness else Polygon()
    initial_bedding=bedding
    seat = construction.get("pipe_seat") or construction.get("pipe_support")
    encasement = construction.get("encasement") or construction.get("pipe_encasement")
    support = []
    support_specs = []
    bedding_seats = []
    closure_tops=[]
    if seat and seat.get("enabled",True):
        if not structure.get("pipes"):
            raise ConstructionInputError("管座只用于圆管")
        seat_role=seat.get("material_role","concrete")
        if seat_role not in {"concrete","bedding"}:
            raise ConstructionInputError("管座材料归类仅支持 concrete/bedding")
        for p,center in zip(structure["pipes"], structure["pipe_centers"]):
            radius = p["outer_diameter"]/2
            angle = math.radians(number(seat,"support_angle",seat.get("angle",120),positive=True))/2
            if angle > math.pi:
                raise ConstructionInputError("管座支承角不能超过360度")
            vertical_radius=(float(p["axis_elevation"])-float(p["outer_bottom"])) if seat_role=="bedding" else radius
            height = number(seat,"height", vertical_radius*(1-math.cos(angle)))
            width_mode=seat.get("bottom_width_mode","explicit")
            if width_mode in {"support_chord","support_chord_plus_sides"}:
                if not 0<angle<math.pi/2:
                    raise ConstructionInputError("按包角弦宽封闭的管基须采用0至180度包角")
                width=2*radius*math.sin(angle)
                if width_mode=="support_chord_plus_sides":width+=2*number(seat,"extension",0)
            elif width_mode=="inner_diameter_offset":
                width=p["inner_diameter"]+2*number(seat,"extension",0)
            elif width_mode=="explicit":
                width = number(seat,"bottom_width", p["outer_diameter"]+2*number(seat,"extension",0),positive=True)
            elif width_mode=="trench_bottom":
                # The working spaces are already part of this complete base.
                # Angle defines its upper elevation; stale explicit height,
                # bottom_width or extension must not override this mode.
                height=vertical_radius*(1-math.cos(angle))
                seat_left=left-number(construction,"working_space_left",0)
                seat_right=right+number(construction,"working_space_right",0)
                if seat_role=="bedding":
                    side_mode=seat.get("side_boundary_mode","excavation")
                    if side_mode not in {"excavation","vertical"}:
                        raise ConstructionInputError("垫层侧边界仅支持 excavation/vertical")
                    if side_mode=="excavation":closure_tops.append(bottom+height)
            else:
                raise ConstructionInputError("管基底宽模式无效，请采用明确底宽、包角弦宽、净径加边距或槽底宽")
            floor = bottom-number(seat,"base_thickness",0)
            if width_mode=="trench_bottom":
                body=box(seat_left,floor,seat_right,bottom+height)
            else:
                body = box(center[0]-width/2,floor,center[0]+width/2,bottom+height)
            region=body.difference(outer)
            (bedding_seats if seat_role=="bedding" else support).append(region)
            if seat_role!="bedding":support_specs.append(("pipe_seat",seat,region))
    if bedding_seats:
        # A pipe bedding cradle includes the flat base and the part climbing
        # the lower pipe. Their shared volume is a single material region.
        bedding=unary_union([bedding,*bedding_seats])
    if encasement and encasement.get("enabled",True):
        left_key = "left_thickness" if encasement.get("left_thickness") is not None else "side_thickness"
        body = box(left-number(encasement,left_key,0),
                   bottom-number(encasement,"bottom_thickness",0),
                   right+number(encasement,"right_thickness",encasement.get("side_thickness",0)),
                   top+number(encasement,"top_thickness",0))
        region=body.difference(outer)
        support.append(region);support_specs.append(("pipe_encasement",encasement,region))
    for index, body in enumerate(support):
        if any(body.intersection(previous).area > 1e-7 for previous in support[:index]):
            raise ConstructionInputError("管座/包封构造相互重叠，请调整构造")
    support = unary_union(support)
    reference=construction.get("bedding_reference","pipe_outer_bottom")
    if reference not in {"pipe_outer_bottom","pipe_seat_bottom","foundation_bottom"}:
        raise ConstructionInputError("垫层高程基准无效")
    if reference=="pipe_seat_bottom" and thickness:
        if support.is_empty:raise ConstructionInputError("管座底垫层要求先明确混凝土管座/包封")
        sl,sb,sr,_=support.bounds
        bedding=box(sl-extension,sb-thickness,sr+extension,sb) if thickness else Polygon()
        initial_bedding=bedding
    separate=[]
    regions=deepcopy(structure.get("component_regions",{}))
    for cid,spec,region in support_specs:
        if not spec.get("separate_material"):continue
        separate.append(region)
        if cid in regions:region=unary_union([regions[cid]["geometry"],region])
        regions[cid]={"component_id":cid,"name":spec.get("name", "管座" if cid=="pipe_seat" else "管道包封"),
            "material":spec.get("material","concrete"),"grade":spec.get("grade",""),"unit":"m3",
            "geometry":region,"section_measure":region.area,"occupies_space":True}
    concrete = unary_union([materials.get("concrete",Polygon()),support.difference(unary_union(separate))])
    # Shared boundaries have zero area; real material overlaps are errors.
    if bedding.intersection(unary_union([concrete,support])).area > 1e-7:
        raise ConstructionInputError("混凝土管座/包封与垫层占据同一区域，请调整构造")
    components = [spec["geometry"] for spec in structure.get("component_regions", {}).values()]
    for spec in structure.get("component_regions", {}).values():
        if spec["geometry"].intersection(unary_union([bedding, support])).area > 1e-7:
            raise ConstructionInputError(f"{spec['name']} 与管座/包封/垫层占据同一区域，请调整构造")
    materials.update(concrete=validated(concrete,"混凝土"),bedding=bedding)
    measured = unary_union([bedding,support,*components])
    if construction.get("working_space_reference") == "pipe_foundation":
        # The working space starts at the seat, encasement or its underlying
        # bedding edge, independently of wider gabions above the pipe.
        bases = [part.bounds for part in (support, bedding) if not part.is_empty]
        if bases:
            structure["pipe_foundation_span"] = (min(bounds[0] for bounds in bases), max(bounds[2] for bounds in bases))
    replacement=construction.get("foundation_replacement") or {}
    depth=number(replacement,"thickness",construction.get("foundation_replacement_thickness",0))
    if replacement.get("enabled",True) and depth:
        envelope=unary_union([outer,measured])
        fl,fb,fr,_=envelope.bounds
        width_reference=replacement.get("width_reference","excavation_bottom")
        if width_reference=="excavation_bottom":
            if replacement.get("excavation_follows_outline") and any(k == "pipe_seat" for k, _, _ in support_specs):
                # The dimension chains on the C / paddy drawings start at
                # the actual seat edges, including a row of unequal pipes.
                seat_bounds = [region.bounds for kind, _, region in support_specs if kind == "pipe_seat"]
                fl, fr = min(bound[0] for bound in seat_bounds), max(bound[2] for bound in seat_bounds)
            elif construction.get("working_space_reference")=="pipe_outer" or (seat or {}).get("bottom_width_mode")=="trench_bottom":
                fl,fr=left,right
            fl-=number(construction,"working_space_left",0);fr+=number(construction,"working_space_right",0)
        elif width_reference!="foundation":raise ConstructionInputError("基础换填宽度基准无效")
        trench_left, trench_right = fl, fr
        if replacement.get("excavation_follows_outline") and width_reference == "foundation":
            trench_left -= number(construction, "working_space_left", 0)
            trench_right += number(construction, "working_space_right", 0)
        width=replacement.get("width",construction.get("foundation_replacement_width"))
        if width is not None:
            width=finite_number(width,"换填宽度")
            if width<=0:raise ConstructionInputError("换填宽度须大于0")
            mid=(fl+fr)/2;fl,fr=mid-width/2,mid+width/2
        side=number(replacement,"side_slope",0)
        low_left,low_right=fl+side*depth,fr-side*depth
        if low_left>=low_right:raise ConstructionInputError("换填层收坡后底宽须大于0")
        region=validated(Polygon([(fl,fb),(fr,fb),(low_right,fb-depth),(low_left,fb-depth)]),"基础换填")
        if replacement.get("excavation_follows_outline"):
            # The concrete seat / culvert is excavated from the top rim. The
            # replacement itself has its own sides, bounded by the lower rim.
            outline = [(fl, fb), (low_left, fb-depth), (low_right, fb-depth), (fr, fb)]
            if trench_left < fl:
                outline.insert(0, (trench_left, fb))
            if trench_right > fr:
                outline.append((trench_right, fb))
            structure["replacement_excavation_floor"] = outline
        material=replacement.get("material",construction.get("foundation_replacement_material"))
        if not material:raise ConstructionInputError("基础换填层须明确材料")
        regions["foundation_replacement"]={"component_id":"foundation_replacement","name":replacement.get("name","基础换填层"),
            "material":material,"grade":replacement.get("grade",""),"unit":"m3","geometry":region,
            "section_measure":region.area,"occupies_space":True}
        measured=unary_union([measured,region]);components.append(region)
    structure["component_regions"]=regions
    if measured.is_empty:measured=Polygon()
    if concrete.is_empty:materials["concrete"]=Polygon()
    structure.update(materials=materials, measured=measured,
                     occupancy=unary_union([outer,measured]))
    if closure_tops:
        # Keep a rectangle only as the unresolved floor/template anchor. Its
        # material is replaced after the actual TIN-clipped cut is available.
        structure["bedding_excavation_closure"]={"rule":PIPE_BEDDING_EXCAVATION_RULE,
            "top_elevation":max(closure_tops),"base_elevation":measured.bounds[1],
            "initial_bedding":initial_bedding,"other_measured":unary_union([support,*components])}
    return structure


def _close_bedding_to_actual_excavation(structure, excavation, soil):
    from ..core.construction_geometry import _polygonal
    pending=structure.get("bedding_excavation_closure")
    if not pending:return structure
    top=pending["top_elevation"]
    low=pending["base_elevation"]
    if excavation.is_empty:
        clipped=Polygon()
    else:
        left,_,right,_=excavation.bounds
        clipped=excavation.intersection(soil).intersection(box(left,low,right,top))
    bedding=_polygonal(unary_union([pending["initial_bedding"],clipped.difference(structure["outer"])]))
    concrete=structure["materials"].get("concrete",Polygon())
    if bedding.intersection(concrete).area>1e-7:
        raise ConstructionInputError("沿开挖边坡封闭的垫层与混凝土管座/包封占据同一区域")
    for spec in structure.get("component_regions",{}).values():
        if bedding.intersection(spec["geometry"]).area>1e-7:
            raise ConstructionInputError(f"{spec['name']} 与沿开挖边坡封闭的垫层占据同一区域")
    measured=_polygonal(unary_union([bedding,pending["other_measured"]]))
    structure["materials"]={**structure["materials"],"bedding":validated(bedding,"沿开挖边坡封闭的垫层")}
    structure.update(measured=measured,occupancy=_polygonal(unary_union([structure["outer"],measured])),
        bedding_side_boundary={"mode":"excavation","rule":pending["rule"],
            "top_elevation":top,"base_elevation":low,"resolved_from_actual_excavation":True})
    return structure


def structure_mapping(structure, *, geometry_mapper=mapping):
    return {"outer":geometry_mapper(structure["outer"]),"net_void":geometry_mapper(structure["net_void"]),
            "materials":{k:geometry_mapper(v) for k,v in structure["materials"].items()},
            **{key:{identifier:{**{k:v for k,v in spec.items() if k!="geometry"},
                                "geometry":geometry_mapper(spec["geometry"])}
                    for identifier,spec in structure.get(key,{}).items()}
               for key in ("component_regions","component_surfaces")},
            **{key:structure[key] for key in ("hydraulic_inner_height", "reference_dimensions") if key in structure},
            **({"bedding_side_boundary":dict(structure["bedding_side_boundary"])} if structure.get("bedding_side_boundary") else {}),
            **({"pipe_centers":structure["pipe_centers"],"pipes":structure["pipes"]} if "pipes" in structure else {})}


def translate_structure(structure, elevation):
    result=dict(structure)
    if "replacement_excavation_floor" in structure:
        result["replacement_excavation_floor"] = [(x, z + elevation) for x, z in structure["replacement_excavation_floor"]]
    for key in ("outer","net_void","measured","occupancy","pipe_concrete","tunnel_excavation_outline"):
        if key in result:result[key]=affinity.translate(result[key],yoff=elevation)
    result["materials"]={k:affinity.translate(g,yoff=elevation) for k,g in structure["materials"].items()}
    for key in ("component_regions", "component_surfaces"):
        if key in result:
            result[key] = {identifier:{**spec, "geometry":affinity.translate(spec["geometry"],yoff=elevation)}
                           for identifier,spec in structure[key].items()}
    if "pipe_material_regions" in result:
        result["pipe_material_regions"]=[affinity.translate(g,yoff=elevation) for g in structure["pipe_material_regions"]]
    for key in ("pipe_wall_regions","pipe_lining_regions"):
        if key in result:result[key]=[affinity.translate(g,yoff=elevation) for g in structure[key]]
    if "pipe_centers" in result:
        result["pipe_centers"]=[[x,z+elevation] for x,z in structure["pipe_centers"]]
        result["pipes"]=[{**p,**{key:p[key]+elevation for key in ("axis_elevation","outer_bottom","outer_top") if key in p}} for p in structure["pipes"]]
    if "support_elevation" in result:result["support_elevation"]+=elevation
    for key in ("bedding_excavation_closure","bedding_side_boundary"):
        if key in result:
            result[key]=dict(result[key])
            for name in ("top_elevation","base_elevation"):
                result[key][name]+=elevation
            for name in ("initial_bedding","other_measured"):
                if name in result[key]:result[key][name]=affinity.translate(result[key][name],yoff=elevation)
    return result


def slope_grades(construction, side, *, filling=False):
    from ..models.section import SlopeGrade
    prefix = "bank" if filling else "excavation"
    stages = construction.get(prefix+"_stages_"+side)
    if stages is None:
        return [SlopeGrade(number(construction,prefix+"_slope_"+side),math.inf,0)]
    if not isinstance(stages,list) or not stages:
        raise ConstructionInputError(f"{prefix}_stages_{side} 必须为非空级段")
    return [SlopeGrade(number(g,"slope"),math.inf if i==len(stages)-1 else number(g,"height",positive=True),
                       number(g,"berm_width",0)) for i,g in enumerate(stages)]


def trace_to_ground(start, ground, grades, direction, *, filling=False):
    from ..core.cross_section import CrossSectionCalculator
    if not filling:
        return CrossSectionCalculator._trace_slope(*start,ground,grades,direction)
    point = tuple(start); points = [point]
    for grade in grades:
        vector = (direction*grade.ratio,-1.)
        hit = CrossSectionCalculator._ray_ground_hit(point,vector,ground,grade.height)
        if hit is not None:
            if hit[0] > 1e-9:
                points.append(hit[1])
            return points
        if math.isinf(grade.height):
            raise ConstructionInputError("填筑边坡在有效地形内未接地")
        point = (point[0]+vector[0]*grade.height,point[1]-grade.height)
        if not ground[0][0] <= point[0] <= ground[-1][0]:
            raise ConstructionInputError("填筑边坡超出有效地形")
        points.append(point)
        if grade.berm_width:
            hit = CrossSectionCalculator._ray_ground_hit(point,(direction,0),ground,grade.berm_width)
            if hit:
                points.append(hit[1]); return points
            point = (point[0]+direction*grade.berm_width,point[1]); points.append(point)
    raise ConstructionInputError("填筑分级边坡尚未接地")


def channel_crown_excavation_path(asset, structure):
    """Follow the channel exterior below its crown; add crown platforms only.

    U/trapezoidal lining sits against the excavation. A bottom working-space
    trench would excavate fictitious soil outside that lining and then refill
    it. The upper permanent slope begins at the crown platform's outer edge.
    """
    c = effective_construction(asset)
    envelope = structure["occupancy"]
    clearance = number(c, "excavation_clearance", 0.)
    if clearance:
        expanded = envelope.buffer(clearance, join_style=2)
        envelope = expanded.intersection(box(expanded.bounds[0],expanded.bounds[1],
                                            expanded.bounds[2],structure["outer"].bounds[3]))
    path = _component_surface(envelope, open_crown=True)
    if path.geom_type != "LineString":
        raise ConstructionInputError("渠顶起坡要求连通的渠身及附层外轮廓，请核对材料层")
    points = list(path.coords)
    if points[0][0] > points[-1][0]:
        points.reverse()
    crest = structure["outer"].bounds[3]
    if any(abs(p[1]-crest)>1e-7 for p in (points[0],points[-1])):
        raise ConstructionInputError("不能确定渠顶两侧平台起点")
    left = number(c, "bank_top_width_left", 0.)
    right = number(c, "bank_top_width_right", 0.)
    points = [(points[0][0]-left,crest),*points,(points[-1][0]+right,crest)]
    return [p for i,p in enumerate(points) if i==0 or p!=points[i-1]]


def construction_floor_steps(construction, structure):
    """Return explicit stepped-floor coordinates above a documented local datum."""
    raw = construction.get("floor_steps")
    if raw is None:
        return None
    if isinstance(raw, dict):
        if raw.get("reference", "foundation_bottom") != "foundation_bottom":
            raise ConstructionInputError("阶梯开挖底面须以当前基础最低点为高程基准")
        raw = raw.get("points")
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        raise ConstructionInputError("阶梯开挖底面至少需要两个偏距和相对高程点")
    base = structure["occupancy"].bounds[1]
    points = []
    for point in raw:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ConstructionInputError("阶梯底面每点须为[偏距,相对基础底高程]")
        x, dz = finite_number(point[0], "阶梯偏距"), finite_number(point[1], "阶梯相对高程")
        current = (x, base + dz)
        if not points or points[-1] != current:
            points.append(current)
    if len(points) < 2 or points[-1][0] <= points[0][0] or any(b[0] < a[0] for a,b in zip(points,points[1:])):
        raise ConstructionInputError("阶梯底面偏距须从左到右非递减，且总宽度大于零")
    from shapely.geometry import LineString
    if not LineString(points).is_simple:
        raise ConstructionInputError("阶梯底面存在自交或竖直反折，请核对坐标顺序")
    return points


def construction_on_ground(asset, structure, ground, *, bottom, top):
    """Actual finite construction polygons with independently traced sides."""
    from .layered_excavation import validate_layer_asset, trace_layered_to_ground
    if structure.get("bedding_excavation_closure"):
        # Clone on both first use and cache hits. Resolved material belongs to
        # this ground cut, never the reusable structure/template dictionary.
        structure=translate_structure(structure,0.)
    layers = validate_layer_asset(asset)
    if structure.get("dedicated_construction"):
        if layers is not None:
            raise ConstructionInputError("专用结构施工断面暂不支持覆盖层/基岩分层放坡")
        from .dedicated_structure_geometry import dedicated_construction_on_ground
        return dedicated_construction_on_ground(asset,structure,ground,bottom=bottom,top=top)
    from ..adapters.independent_assets import _ground_at
    from shapely.geometry import LineString
    c = effective_construction(asset)
    if ("retaining_wall" in structure.get("component_regions", {})
            and not c.get("floor_steps")):
        return _channel_and_retaining_wall_on_ground(asset,structure,ground,bottom=bottom,top=top)
    outer, measured = structure["outer"], structure["measured"]
    occupancy = structure["occupancy"]
    pl,pb,pr,pt = outer.bounds
    left,floor,right,_ = occupancy.bounds
    workspace_reference = c.get("working_space_reference", "occupancy")
    if workspace_reference not in {"occupancy", "pipe_outer", "pipe_foundation"}:
        raise ConstructionInputError("工作面基准须选结构外缘、管外壁或管基外缘")
    seat=c.get("pipe_seat") or c.get("pipe_support") or {}
    if seat.get("enabled",True) and seat.get("bottom_width_mode")=="trench_bottom":
        # This mode explicitly spans outer wall plus the entered work spaces.
        # Reusing its occupancy bounds would add the same work spaces twice.
        workspace_reference="pipe_outer"
    if workspace_reference == "pipe_outer":
        if not structure.get("pipes"):
            raise ConstructionInputError("pipe_outer 工作面基准只用于圆管外壁")
        left,right = pl,pr
    elif workspace_reference == "pipe_foundation":
        left, right = structure.get("pipe_foundation_span", (pl, pr))
    unburied = c.get("installation_mode","buried") in {"exposed","elevated","open","above_ground"}
    wl,wr = (0.,0.) if unburied else (number(c,"working_space_left",0),number(c,"working_space_right",0))
    replacement = c.get("foundation_replacement") or {}
    if ("foundation_replacement" in structure.get("component_regions", {})
            and replacement.get("width_reference") == "excavation_bottom"
            and workspace_reference != "pipe_outer"):
        # This registered foundation already extends through the full working
        # width.  Adding work spaces again would enlarge both excavation and fill.
        wl,wr=0.,0.
    mode = c.get("excavation_base_mode","flat")
    if mode not in {"flat","offset"}:
        raise ConstructionInputError("施工底面仅支持 flat/offset")
    floor_path = [(left-wl,floor),(right+wr,floor)]
    crown_start = asset["section_type"] in {"u_channel", "trapezoidal_channel"}
    explicit_steps = construction_floor_steps(c,structure)
    if explicit_steps is not None:
        required_left = (pl if workspace_reference == "pipe_outer" else left)-wl
        required_right = (pr if workspace_reference == "pipe_outer" else right)+wr
        if explicit_steps[0][0] > required_left+1e-8 or explicit_steps[-1][0] < required_right-1e-8:
            raise ConstructionInputError("阶梯底面须完整覆盖结构、材料层及左右工作面")
        ceiling = max(top, occupancy.bounds[3]+1., *(z+1. for _,z in explicit_steps))
        above = Polygon([*explicit_steps,(explicit_steps[-1][0],ceiling),(explicit_steps[0][0],ceiling)])
        if not above.is_valid or occupancy.difference(above).area > max(1e-8,occupancy.area*1e-9):
            raise ConstructionInputError("阶梯底面切入结构或材料实体，请降低相应阶梯高程")
        floor_path=explicit_steps
        left,right=floor_path[0][0],floor_path[-1][0]
        floor=min(z for _,z in floor_path)
        bottom=min(bottom,floor-2.)
        crown_start=False
    elif structure.get("replacement_excavation_floor") and not unburied and mode == "flat":
        floor_path = structure["replacement_excavation_floor"]
        left, right = floor_path[0][0], floor_path[-1][0]
        floor = min(z for _, z in floor_path)
    elif crown_start and not unburied:
        floor_path = channel_crown_excavation_path(asset,structure)
        left,right = floor_path[0][0],floor_path[-1][0]
        floor = min(z for _,z in floor_path)
    elif mode == "offset" and not unburied:
        clearance = number(c,"excavation_clearance",0)
        shape = occupancy.buffer(clearance,join_style=2) if clearance else occupancy
        parts = [shape] if shape.geom_type=="Polygon" else shape.geoms
        xs = sorted({x for p in parts for x,z in p.exterior.coords})
        lower = []
        for x in xs:
            q = shape.intersection(LineString([(x,bottom),(x,top)]))
            if not q.is_empty:
                lower.append((x,q.bounds[1]))
        if not lower:
            raise ConstructionInputError("不能解析结构外轮廓施工底面")
        floor_path = [(lower[0][0]-wl,lower[0][1]),*lower,(lower[-1][0]+wr,lower[-1][1])]
        if workspace_reference == "pipe_outer":
            # Preserve the actual bedding/support bottom, while the explicit
            # outside-wall workspace sets the trench's horizontal limits.
            left,right = pl-wl,pr+wr
            if left > occupancy.bounds[0]+1e-8 or right < occupancy.bounds[2]-1e-8:
                raise ConstructionInputError("管外壁工作面不足以容纳垫层或支承构造")
            floor_path = [(left,floor),*lower,(right,floor)]
        # Consecutive duplicate points are not physical edges.
        floor_path = [p for i,p in enumerate(floor_path) if i==0 or p!=floor_path[i-1]]
        left,right = floor_path[0][0],floor_path[-1][0]
        floor = min(z for _,z in floor_path)
    else:
        left,right = floor_path[0][0],floor_path[-1][0]
    for x in (left,right,pl,pr):
        _ground_at(ground,x)
    excavation = Polygon()
    daylight = [left,right]
    if not unburied:
        traces = []
        for i,(side,direction) in enumerate((("left",-1),("right",1))):
            foot = floor_path[0 if i==0 else -1]
            if _ground_at(ground,foot[0]) > foot[1]+1e-9:
                trace = (trace_layered_to_ground(foot,ground,c,side,direction) if layers is not None
                         else trace_to_ground(foot,ground,slope_grades(c,side),direction))
            else:
                trace = [foot]
            traces.append(trace); daylight[i]=trace[-1][0]
        points = [*floor_path,*traces[1][1:],(traces[1][-1][0],top),
                  (traces[0][-1][0],top),*list(reversed(traces[0]))]
        excavation = validated(Polygon(points),"施工开挖")
    target_mode = c.get("target_mode","restore_terrain")
    target,removal,open_air = Polygon(),Polygon(),Polygon()
    finish_line = []
    is_open = asset["section_type"].endswith("channel") and asset["section_type"]!="circular_channel"
    cover_modes = {"cover_depth", "cover_above_terrain"}
    cover_above_terrain = target_mode == "cover_above_terrain"
    # Restoring a round culvert's underground trench must not erase an
    # explicitly parameterised support embankment where the unchanged design
    # crosses a hollow. Retain only the part above original terrain; never cut
    # original soil down to the pipe crown. With no embankment design, the
    # original-ground support guard remains authoritative.
    retain_support_fill = (target_mode == "restore_terrain" and is_circular_culvert(asset)
        and c.get("retain_culvert_support_fill", True) and not unburied
        and all(c.get("bank_top_width_"+side) is not None and
            (c.get("bank_slope_"+side) is not None or c.get("bank_stages_"+side))
            for side in ("left", "right")))
    retain_terrain = cover_above_terrain or retain_support_fill
    if target_mode in cover_modes or target_mode == "union_terrain" or retain_support_fill:
        crest = pt+(number(c,"final_cover_depth",c.get("cover_depth",0)) if target_mode in cover_modes else 0)
        crowns = [(pl-number(c,"bank_top_width_left",0),crest),(pr+number(c,"bank_top_width_right",0),crest)]
        if crown_start and target_mode=="union_terrain" and not unburied:
            # Both cut and final soil use the same actual platform edges,
            # including outer mortar/membrane layers. Otherwise a fictitious
            # wedge is excavated and refilled outside every material offset.
            crowns=[floor_path[0],floor_path[-1]]
        traces=[]
        for i,(side,direction) in enumerate((("left",-1),("right",1))):
            g = _ground_at(ground,crowns[i][0])
            filling = g < crest-1e-9
            if abs(g-crest) <= 1e-9 or cover_above_terrain and not filling:
                trace=[crowns[i]]
            else:
                trace = (trace_layered_to_ground(crowns[i],ground,c,side,direction)
                         if layers is not None and not filling else
                         trace_to_ground(crowns[i],ground,slope_grades(c,side,filling=filling),direction,filling=filling))
            traces.append(trace)
        finish_line = [*reversed(traces[0]),*traces[1]]
        fl,fr = finish_line[0][0],finish_line[-1][0]
        # A zero slope meets terrain vertically. At the footprint boundary
        # that line is a drawing edge, while the soil polygon must end at the
        # inner surface point; otherwise its closing wall retraces the edge.
        soil_line=list(finish_line)
        while len(soil_line)>2 and soil_line[0][0]==soil_line[1][0]:soil_line.pop(0)
        while len(soil_line)>2 and soil_line[-1][0]==soil_line[-2][0]:soil_line.pop()
        target = validated(Polygon([(fl,bottom),(fr,bottom),*reversed(soil_line)]),"最终土体")
        if not retain_terrain:
            removal = box(fl,bottom,fr,top).difference(target)
            # The outside terrain is retained; within the specified footprint
            # the finished surface is explicit, including platform excavation.
            excavation = unary_union([excavation,removal]) if not unburied else Polygon()
    elif target_mode=="finished_profile":
        profile = c.get("target_profile")
        if not profile or len(profile)<2 or any(a[0]>=b[0] for a,b in zip(profile,profile[1:])):
            raise ConstructionInputError("目标完成面须有从左至右递增的偏距")
        finish_line = [(finite_number(x,"偏距"),finite_number(z,"标高")) for x,z in profile]
        target = Polygon([(finish_line[0][0],bottom),(finish_line[-1][0],bottom),*reversed(finish_line)])
        removal = box(finish_line[0][0],bottom,finish_line[-1][0],top).difference(target)
        excavation=unary_union([excavation,removal])
    elif target_mode!="restore_terrain":
        raise ConstructionInputError("必须明确恢复原地面、渠堤或覆土完成面")
    if is_open:
        if target_mode=="restore_terrain":
            open_air=excavation.intersection(box(left,bottom,right,top)).intersection(box(-1e12,pt,1e12,top))
        else:
            # Above the channel crown the central open space stays clear;
            # shoulder slopes outside the platform keep their own elevation.
            open_air=box(pl,pt,pr,top)
    bounds=[g.bounds for g in (outer,measured,excavation,target,removal,open_air) if not g.is_empty]
    x0,x1=min(b[0] for b in bounds),max(b[2] for b in bounds)
    _ground_at(ground,x0);_ground_at(ground,x1)
    domain=box(x0,bottom,x1,top)
    cropped=[(x0,_ground_at(ground,x0)),*[(x,z) for x,z in ground if x0<x<x1],(x1,_ground_at(ground,x1))]
    soil=Polygon([(x0,bottom),(x1,bottom),*reversed(cropped)])
    final=soil
    if not target.is_empty:
        if retain_terrain:
            final=unary_union([soil,target])
            # The complete final boundary is carried by roles.target; a
            # lower, buried crown line is not a finished-ground profile.
            finish_line=[]
        else:
            footprint=box(target.bounds[0],bottom,target.bounds[2],top)
            final=unary_union([soil.difference(footprint),target])
    final=final.difference(open_air)
    structure=_close_bedding_to_actual_excavation(structure,excavation,soil)
    measured=structure["measured"]
    roles={"permanent":outer,"measured":measured,"excavation":excavation,"target":final,
           "open_air":open_air,"removal":removal}
    return {"roles":roles,"soil":soil,"target":final,"domain":domain,"ground":cropped,"structure":structure,
            "daylight":daylight,"target_bounds":[x0,x1],"floor":floor,
            "floor_path":floor_path,"finished_profile":finish_line}


def _channel_and_retaining_wall_on_ground(asset, structure, ground, *, bottom, top):
    """Separate explicit wall foundations from the channel's crown excavation."""
    from ..adapters.independent_assets import _ground_at
    main = translate_structure(structure,0.)
    wall_spec = main["component_regions"].pop("retaining_wall")
    wall = wall_spec["geometry"]
    main["measured"] = main["measured"].difference(wall)
    main["occupancy"] = main["occupancy"].difference(wall)
    channel = construction_on_ground(asset,main,ground,bottom=bottom,top=top)
    wall_asset = deepcopy(asset)
    wall_asset["section_type"] = "rectangular_culvert"
    wall_asset["construction"] = effective_construction(asset)
    wall_asset["construction"].update(target_mode="restore_terrain",excavation_base_mode="flat")
    wall_asset["construction"].pop("floor_steps",None)
    wall_structure = {"outer":wall,"net_void":Polygon(),"measured":Polygon(),"occupancy":wall,"materials":{}}
    foundation = construction_on_ground(wall_asset,wall_structure,ground,bottom=bottom,top=top)
    result = dict(channel)
    left = min(channel["domain"].bounds[0],foundation["domain"].bounds[0])
    right = max(channel["domain"].bounds[2],foundation["domain"].bounds[2])
    lower = min(channel["domain"].bounds[1],foundation["domain"].bounds[1])
    cropped = [(left,_ground_at(ground,left)),*[(x,z) for x,z in ground if left<x<right],(right,_ground_at(ground,right))]
    soil = Polygon([(left,lower),(right,lower),*reversed(cropped)])
    # Only the channel changes its specified finished surface. The wall's
    # surrounding terrain is restored, even when its footing lies outside it.
    target = unary_union([soil.difference(channel["soil"]),channel["target"]])
    combined = channel["structure"]
    combined.setdefault("component_regions",{})["retaining_wall"] = wall_spec
    combined["measured"] = unary_union([combined["measured"],wall])
    combined["occupancy"] = unary_union([combined["occupancy"],wall])
    roles = dict(channel["roles"])
    roles.update(measured=combined["measured"],target=target,
        excavation=unary_union([channel["roles"]["excavation"],foundation["roles"]["excavation"]]))
    result.update(roles=roles,soil=soil,target=target,structure=combined,ground=cropped,
        domain=box(left,lower,right,top),target_bounds=[left,right],
        daylight=[min(channel["daylight"][0],foundation["daylight"][0]),max(channel["daylight"][1],foundation["daylight"][1])],
        floor=min(channel["floor"],foundation["floor"]),
        independent_excavation_floor_paths=[channel["floor_path"],foundation["floor_path"]])
    return result
