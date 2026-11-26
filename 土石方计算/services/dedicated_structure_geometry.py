"""Parameter-driven aqueduct and mined tunnel sections.

Hydraulic clear dimensions come from the water-profile snapshot. Construction
layers and discrete members remain independent, editable construction inputs.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import math

import numpy as np
from shapely import affinity
from shapely.geometry import Polygon, Point, LineString, box
from shapely.ops import unary_union

from .contracts import ConstructionInputError, finite_number
from .workbench_scope import AssetDataPending

AQUEDUCT_TYPES = {"aqueduct_u", "aqueduct_rectangular"}
TUNNEL_TYPES = {"arch_tunnel", "circular_tunnel", "flat_bottom_tunnel", "horseshoe_tunnel"}
DEDICATED_TYPES = AQUEDUCT_TYPES | TUNNEL_TYPES


def is_pipe_bridge(asset):
    return (str(asset.get("section_type","")).startswith("circular")
        and asset.get("construction",{}).get("installation_mode") in {"elevated","exposed","above_ground","open"}
        and bool(asset.get("section",{}).get("discrete_components")))


def aqueduct_foundation_pits(asset, alignment, *, route_id="", parent_asset_id=None):
    """Derive real four-sided excavation routes without duplicating the footing."""
    if asset.get("section_type") not in AQUEDUCT_TYPES and not is_pipe_bridge(asset):
        return []
    result=[]
    for member in asset.get("section",{}).get("discrete_components",[]):
        if not member.get("excavate",False):continue
        _active_member(member,None,"right")
        c=(deepcopy(member.get("construction",{})) if member.get("generated_aqueduct_foundation_member") else
           {**deepcopy(asset.get("construction",{})),**deepcopy(member.get("construction",{}))})
        required=["working_space_"+side for side in ("left","right","front","back")]
        required += ["excavation_slope_"+side for side in ("left","right","front","back")
                     if not c.get("excavation_stages_"+side)]
        missing=[key for key in required if c.get(key) is None]
        if missing:raise ConstructionInputError("渡槽基础四侧开挖参数待补齐："+", ".join(missing))
        start,end=float(member["station_start"]),float(member["station_end"])
        middle=(start+end)/2
        if not asset["station_start"]<=start<end<=asset["station_end"]:
            raise ConstructionInputError("基础实体桩号越出渡槽来源范围")
        angle=alignment.get_tangent_angle_at_station(middle)
        direction=(math.cos(angle),math.sin(angle));normal=(direction[1],-direction[0])
        center=alignment.get_xy_at_station(middle)
        offset=finite_number(member.get("offset",0.),"基础横偏距")
        center=[center[i]+offset*normal[i] for i in (0,1)]
        low=finite_number(member.get("bottom_elevation"),"基础底高程")
        high=finite_number(member.get("top_elevation"),"基础顶高程")
        if high<=low:raise ConstructionInputError("基础顶高程须大于底高程")
        width=_number(member,"width",positive=True)
        bedding=_number(c,"bedding_thickness",default=0.)
        extension=_number(c,"bedding_extension",default=0.)
        ident=hashlib.sha256((route_id+":"+asset["asset_id"]+":"+member["component_id"]).encode()).hexdigest()[:16]
        c.update(target_mode="restore_terrain",excavation_base_mode="flat")
        result.append({"asset_id":"aqueduct-foundation-"+ident,
            "name":asset.get("name",asset["asset_id"])+" · "+member.get("name",member["component_id"]),
            "kind":"pit","section_type":"rectangular_pit","enabled":True,
            **({"flow_section": asset["flow_section"]} if asset.get("flow_section") else {}),
            "generated_aqueduct_foundation":True,"parent_asset_id":parent_asset_id or asset["asset_id"],
            "parent_original_asset_id":asset["asset_id"],
            "parent_component_id":member["component_id"],"parent_route_id":route_id,
            "parent_station_start":start,"parent_station_end":end,
            "section":{"bottom_length":end-start+2*extension+float(c["working_space_front"])+float(c["working_space_back"]),
                "bottom_width":width+2*extension+float(c["working_space_left"])+float(c["working_space_right"]),
                "floor_elevation":low-bedding,"foundation_width":width,"foundation_length":end-start,
                "foundation_height":high-low,"material_grade":member.get("grade", ""),
                "material_specs":{"concrete":{"material":member.get("material") or "concrete","grade":member.get("grade", ""),
                    "name":member.get("name",member["component_id"])}}},
            "placement":{"center_xy":center,"direction":list(direction)},"construction":c,
            "source_component":deepcopy(member),"source_identity":asset.get("source_identity")})
        if member.get("generated_aqueduct_foundation_member"):
            column=next((item for item in asset.get("section",{}).get("discrete_components",[])
                         if item.get("component_id")==member.get("column_component_id")),None)
            if column is None or not column.get("generated_aqueduct_frame"):
                raise ConstructionInputError("自动扩大基础缺少对应排架柱，请重新生成柱与基础")
            result[-1]["associated_pier_occupancy"]=[{
                "component_id":column["component_id"],"name":column.get("name",column["component_id"]),
                "local_start":float(column["station_start"])-middle,
                "local_end":float(column["station_end"])-middle,
                "offset":float(column.get("offset",0.))-offset,"width":float(column["width"]),
                "bottom_elevation":float(column["bottom_elevation"]),
                "top_elevation":float(column["top_elevation"])}]
    return result


def is_dedicated_structure(asset):
    return asset.get("section_type") in DEDICATED_TYPES or is_pipe_bridge(asset)


def _number(data, key, *, positive=False, default=None):
    value = finite_number(data.get(key, default), key)
    if value < 0 or positive and value <= 0:
        raise ConstructionInputError(key + ("须大于0" if positive else "不能为负"))
    return value


def _arc(center, radius, start, end, count):
    while end <= start:
        end += 360.
    n = max(4, math.ceil((end-start)/360*count))
    angles=sorted({*(start+(end-start)*i/n for i in range(n+1)),
                   *(float(a) for a in range(math.ceil(start/90)*90, math.floor(end/90)*90+1, 90))})
    return [(center[0]+radius*math.cos(math.radians(a)),
             center[1]+radius*math.sin(math.radians(a))) for a in angles]


def tunnel_void(asset, count=128):
    """Closed hydraulic void, with invert at z=0, using shared source geometry."""
    typ, s = asset["section_type"], asset["section"]
    if typ == "circular_tunnel":
        radius = _number(s, "inner_diameter", positive=True)/2
        return Point(0., radius).buffer(radius, quad_segs=max(4, count//4))
    if typ == "flat_bottom_tunnel":
        from calc_渠系计算算法内核.flat_bottom_circle import build_flat_bottom_circle_geometry
        g = build_flat_bottom_circle_geometry(_number(s, "inner_diameter", positive=True),
                                             _number(s, "bottom_width", positive=True))
        a = g["top_arc"]
        points = _arc(a["center"], a["radius"], a["start_deg"], a["end_deg"], count)
        points[0], points[-1] = a["start_point"], a["end_point"]
        return Polygon(points)
    if typ == "horseshoe_tunnel":
        from app_渠系计算前端.tunnel.geometry import build_standard_horseshoe_geometry
        subtype = int(s.get("horseshoe_type", 1))
        g = build_standard_horseshoe_geometry(subtype, _number(s, "inner_radius", positive=True))
        points = []
        for a in g["arcs"]:
            part = _arc(a["center"], a["radius"], a["start_deg"], a["end_deg"], count)
            part[0], part[-1] = a["start_point"], a["end_point"]
            points.extend(part if not points else part[1:])
        return Polygon(points)
    width = _number(s, "inner_width", positive=True)
    height = _number(s, "inner_height", positive=True)
    angle = _number(s, "arch_angle_degrees", positive=True, default=180.)
    if angle > 180:
        raise ConstructionInputError("隧洞顶拱角须不大于180度")
    radius = width/(2*math.sin(math.radians(angle)/2))
    rise = radius*(1-math.cos(math.radians(angle)/2))
    wall = s.get("wall_height", height-rise)
    wall = finite_number(wall, "wall_height")
    if wall < 0 or abs(wall+rise-height) > 1e-5:
        raise ConstructionInputError("隧洞直墙、顶拱与水面线总净高不一致")
    center = (0., wall-radius*math.cos(math.radians(angle)/2))
    points = [(-width/2, 0.), (width/2, 0.)]
    points += _arc(center, radius, 90-angle/2, 90+angle/2, count)
    return Polygon(points)


def _tunnel_lining_outer(asset, inner, arc_segments):
    section=asset["section"]
    lining=_number(section,"lining_thickness")
    for key in ("wall_thickness_left","wall_thickness_right","roof_thickness"):
        if section.get(key) is not None and not math.isclose(_number(section,key),lining,abs_tol=1e-9):
            raise ConstructionInputError("隧洞来源包含独立墙拱变厚尺寸，须补充墙拱连接构造后计算；已保留 "+key)
    outer=inner.buffer(lining,quad_segs=max(4,arc_segments//4),join_style=1) if lining else inner
    if section.get("base_thickness") is None:
        if asset.get("source_tunnel_parameters") and asset["section_type"] in {"arch_tunnel","flat_bottom_tunnel"}:
            raise ConstructionInputError("隧洞尚未明确底板厚度 t₀，请选择围岩方案或填写实际厚度")
        return outer
    base=_number(section,"base_thickness")
    if asset["section_type"] not in {"arch_tunnel","flat_bottom_tunnel"}:
        if not math.isclose(base,lining,abs_tol=1e-9):
            raise ConstructionInputError("圆形或马蹄形隧洞底弧与墙拱厚度不同，须补充底弧变厚连接构造；源 t₀、t 已保留")
        return outer
    width=_number(section,"inner_width" if asset["section_type"]=="arch_tunnel" else "bottom_width",positive=True)
    extent=max(abs(x) for x in outer.bounds)+1.
    above_floor=outer.intersection(box(-extent,0.,extent,extent))
    floor=box(-width/2-lining,-base,width/2+lining,0.) if base else Polygon()
    return unary_union([above_floor,floor])


def dedicated_break_stations(asset):
    return sorted({float(x[key]) for x in asset.get("section", {}).get("discrete_components", [])
                   for key in ("station_start", "station_end")})


def register_dedicated_components(asset):
    """Register every material role before the integration contract is created."""
    from .component_quantities import component_role
    if not is_dedicated_structure(asset) and not (str(asset.get("section_type","")).startswith("circular") and asset.get("section",{}).get("discrete_components")):
        return
    s = asset.setdefault("section", {})
    specs = s.setdefault("component_specs", [])
    ids = {x.get("component_id") for x in specs}
    candidates = []
    if asset["section_type"] in TUNNEL_TYPES:
        candidates.append({"component_id":"tunnel_shotcrete", "name":"隧洞喷射混凝土", "unit":"m3",
                           "material":"shotcrete", "grade":s.get("shotcrete_grade", "")})
    for member in s.get("discrete_components", []):
        cid = member.get("component_id")
        component_role(cid)
        _active_member(member, None, "right")
        _number(member, "width", positive=True)
        finite_number(member.get("offset",0.),"构件横偏距")
        lo=finite_number(member.get("bottom_elevation"),"构件底高程")
        hi=finite_number(member.get("top_elevation"),"构件顶高程")
        if hi<=lo:raise ConstructionInputError("离散构件顶高程必须大于底高程")
        if not member.get("material"):raise ConstructionInputError("离散构件须明确材料")
        if asset.get("station_start") is not None and (member["station_start"]<asset["station_start"] or member["station_end"]>asset["station_end"]):
            raise ConstructionInputError("离散构件桩号越出本对象范围，不能以零量忽略")
        candidates.append({**deepcopy(member), "unit":"m3"})
    if len({x["component_id"] for x in candidates}) != len(candidates):
        raise ConstructionInputError("离散构件编号重复")
    for spec in candidates:
        if spec["component_id"] not in ids:
            specs.append(spec)
            ids.add(spec["component_id"])


def _active_member(member, station, side):
    a = finite_number(member.get("station_start"), "构件起桩")
    b = finite_number(member.get("station_end"), "构件止桩")
    if b <= a:
        raise ConstructionInputError("离散构件起止桩必须递增")
    return station is not None and (a < station < b or station == a and side != "left" or station == b and side == "left")


def add_buried_pipe_members(structure,asset,station,side="right"):
    """Cut each explicitly located anchor body, keeping the actual pipe opening."""
    members=asset.get("section",{}).get("discrete_components") or []
    if not members:return structure
    result=deepcopy(structure);regions=result.setdefault("component_regions",{})
    shapes=[]
    for member in members:
        cid=member["component_id"];geometry=Polygon()
        if _active_member(member,station,side):
            offset=finite_number(member.get("offset",0.),"镇墩横偏距")
            width=_number(member,"width",positive=True)
            low=finite_number(member.get("bottom_elevation"),"镇墩底高程")
            high=finite_number(member.get("top_elevation"),"镇墩顶高程")
            if high<=low:raise ConstructionInputError("镇墩顶高程须大于底高程")
            geometry=box(offset-width/2,low,offset+width/2,high)
            if member.get("pipe_opening"):
                geometry=geometry.difference(structure["outer"])
            elif geometry.intersection(structure["outer"]).area>1e-8:
                raise ConstructionInputError("镇墩与管身相交，须明确管孔或修改实体边界")
            if any(geometry.intersection(g).area>1e-8 for g in shapes):
                raise ConstructionInputError("同断面离散镇墩实体重叠，须核对局部起止范围")
            if any(geometry.intersection(s["geometry"]).area>1e-8 for s in regions.values()):
                raise ConstructionInputError("镇墩与断面附加材料重叠")
            shapes.append(geometry)
        regions[cid]={**deepcopy(member),"unit":"m3","geometry":geometry,"section_measure":geometry.area}
    result["outer"]=unary_union([structure["outer"],*shapes])
    result["occupancy"]=unary_union([result["outer"],result.get("measured",Polygon())])
    return result


def dedicated_structure(asset, *, elevation=0., slope=0., arc_segments=64, station=None, side="right", **kwargs):
    from .section_geometry import section_structure, _add_section_components
    typ, s = asset["section_type"], asset["section"]
    if typ in AQUEDUCT_TYPES or is_pipe_bridge(asset):
        body_asset = deepcopy(asset)
        if typ in AQUEDUCT_TYPES:
            body_asset["section_type"] = "u_channel" if typ == "aqueduct_u" else "rectangular_channel"
        body_asset["section"].pop("discrete_components",None)
        discrete_ids={x["component_id"] for x in s.get("discrete_components",[])}
        body_asset["section"]["component_specs"]=[x for x in s.get("component_specs",[])
            if x.get("component_id") not in discrete_ids]
        result = section_structure(body_asset, elevation=elevation, slope=slope, arc_segments=arc_segments)
        result["section_type"] = typ
        result["dedicated_construction"] = True
        result["measured"] = Polygon()
        result["occupancy"] = result["outer"]
        regions = dict(result.get("component_regions",{}))
        foundations = []
        all_members = []
        for member in s.get("discrete_components", []):
            cid = member["component_id"]
            g = Polygon()
            if _active_member(member, station, side):
                offset = finite_number(member.get("offset", 0.), "构件横偏距")
                width = _number(member, "width", positive=True)
                low = finite_number(member.get("bottom_elevation"), "构件底高程")
                high = finite_number(member.get("top_elevation"), "构件顶高程")
                if high <= low:
                    raise ConstructionInputError("离散构件顶高程必须大于底高程")
                g = box(offset-width/2, low, offset+width/2, high)
                if member.get("pipe_opening") and result.get("pipes"):
                    g=g.difference(result["outer"])
                if g.intersection(result["outer"]).area > 1e-7:
                    raise ConstructionInputError("离散构件与槽身/管身重叠，须输入实际相接边界或明确管孔")
                if any(g.intersection(other).area > 1e-7 for other in all_members):
                    raise ConstructionInputError("离散构件相互重叠，须核对实际边界")
                all_members.append(g)
                if member.get("excavate", False):
                    foundations.append(g)
            regions[cid] = {**deepcopy(member), "geometry":g}
        result["component_regions"] = regions
        result["foundation_regions"] = foundations
        shared=[]
        for foundation in asset.get("shared_foundation_footprints",[]):
            if _active_member(foundation,station,side):
                fc={**asset.get("construction",{}),**foundation.get("construction",{})}
                x=finite_number(foundation.get("offset",0.),"基础偏距")
                half=_number(foundation,"width",positive=True)/2
                low=finite_number(foundation["bottom_elevation"],"基础底高程")-_number(fc,"bedding_thickness",default=0.)
                shared.append((x-half,x+half,low))
        result["shared_excavation_footprints"]=shared
        if all_members:
            result["outer"] = unary_union([result["outer"], *all_members])
            result["occupancy"] = result["outer"]
        result["materials"]["bedding"] = Polygon()
        return result
    inner = tunnel_void(asset, arc_segments)
    if not inner.is_valid or inner.area <= 0:
        raise ConstructionInputError("隧洞水力净空轮廓无效")
    lining = _number(s, "lining_thickness")
    shotcrete = _number(s, "shotcrete_thickness")
    outer = _tunnel_lining_outer(asset, inner, arc_segments)
    supported = outer.buffer(shotcrete, quad_segs=max(4, arc_segments//4), join_style=1) if shotcrete else outer
    result = {"outer":supported, "net_void":inner,
              "materials":{"concrete":outer.difference(inner), "bedding":Polygon()},
              "component_regions":{"tunnel_shotcrete":{"name":"隧洞喷射混凝土", "material":"shotcrete",
                  "grade":s.get("shotcrete_grade", ""), "geometry":supported.difference(outer)}},
              "measured":Polygon(), "occupancy":supported, "reference":"inner_invert",
              "section_type":typ, "dedicated_construction":True,
              "hydraulic_inner_height":inner.bounds[3]-inner.bounds[1]}
    # Other material layers retain the standard component geometry contract.
    regular = deepcopy(asset)
    regular["section"]["component_specs"] = [x for x in s.get("component_specs", [])
        if x.get("component_id") != "tunnel_shotcrete"]
    if regular["section"]["component_specs"]:
        existing=result["component_regions"]
        result = _add_section_components(result, regular, elevation=0., arc_segments=arc_segments)
        result["component_regions"]={**existing,**result["component_regions"]}
    clearance=_number(asset.get("construction",{}),"excavation_clearance",default=0.)
    construction=asset.get("construction",{})
    bedding=_number(construction,"bedding_thickness",default=0.)
    if bedding:
        if construction.get("bedding_reference")!="lining_outer_bottom":
            raise ConstructionInputError("隧洞垫层须明确 lining_outer_bottom 基准及底宽")
        width=construction.get("bedding_width")
        if width is None:
            if typ!="arch_tunnel":raise ConstructionInputError("该隧洞垫层须输入明确底宽")
            width=_number(s,"inner_width",positive=True)+2*lining
        else:width=finite_number(width,"隧洞垫层底宽")
        if width<=0:raise ConstructionInputError("隧洞垫层底宽须大于0")
        extension=_number(construction,"bedding_extension",default=0.)
        bottom=result["outer"].bounds[1]
        pad=box(-width/2-extension,bottom-bedding,width/2+extension,bottom)
        result["materials"]["bedding"]=pad
        result["measured"]=pad
        result["occupancy"]=unary_union([result["outer"],pad])
    envelope=result["occupancy"]
    result["tunnel_excavation_outline"]=envelope.buffer(clearance,quad_segs=max(4,arc_segments//4)) if clearance else envelope
    factor=math.hypot(1.,finite_number(slope,"隧洞纵坡"))
    transform=lambda g:affinity.translate(affinity.scale(g,xfact=1.,yfact=factor,origin=(0.,0.)),yoff=elevation)
    for key in ("outer","net_void","measured","occupancy","tunnel_excavation_outline"):
        result[key]=transform(result[key])
    result["materials"]={key:transform(g) for key,g in result["materials"].items()}
    for key in ("component_regions","component_surfaces"):
        if key in result:
            result[key]={cid:{**spec,"geometry":transform(spec["geometry"])} for cid,spec in result[key].items()}
    result["normal_to_vertical_factor"]=factor
    return result


def tunnel_outline_exposed(outline, ground):
    """Compare both piecewise-linear boundaries at all their lateral breaks."""
    offsets, heights = np.asarray(ground, dtype=float).T
    tolerance = 1e-6
    for polygon in ([outline] if outline.geom_type == "Polygon" else outline.geoms):
        lo, _, hi, crest = polygon.bounds
        if heights.min() >= crest-tolerance:
            continue
        x, z = np.asarray(polygon.exterior.coords).T
        if np.any(z > np.interp(x, offsets, heights) + tolerance):
            return True
        candidates = (offsets > lo) & (offsets < hi) & (heights < crest-tolerance)
        edge_min, edge_max = np.minimum(x[:-1], x[1:]), np.maximum(x[:-1], x[1:])
        for u, h in zip(offsets[candidates], heights[candidates]):
            edges = (edge_min < u) & (u < edge_max)
            left, right = x[:-1][edges], x[1:][edges]
            a, b = z[:-1][edges], z[1:][edges]
            if np.any(a + (b-a)*(u-left)/(right-left) > h + tolerance):
                return True
    return False


def dedicated_construction_on_ground(asset, structure, ground, *, bottom, top):
    from ..adapters.independent_assets import _ground_at
    from .section_geometry import construction_on_ground
    c = asset.get("construction", {})
    outer = structure["outer"]
    excavation, bedding = Polygon(), Polygon()
    if asset["section_type"] in TUNNEL_TYPES:
        bedding=structure["materials"].get("bedding",Polygon())
        _number(c, "excavation_clearance")
        excavation = structure["tunnel_excavation_outline"]
        if tunnel_outline_exposed(excavation, ground):
            raise AssetDataPending("暗挖隧洞开挖轮廓穿出原地面，待核明暗挖分界及明挖施工断面",
                                   code="tunnel_exposed")
    else:
        pieces = []
        bedding_parts = []
        for foundation in structure.get("foundation_regions", []):
            low = foundation.bounds[1]
            thick = _number(c, "bedding_thickness", default=0.)
            extension = _number(c, "bedding_extension", default=0.)
            pad = box(foundation.bounds[0]-extension, low-thick,
                      foundation.bounds[2]+extension, low) if thick else Polygon()
            fake = {"section_type":"rectangular_pit", "construction":{**c,"target_mode":"restore_terrain"}}
            part_structure = {"outer":foundation,"measured":pad,"occupancy":unary_union([foundation,pad])}
            prepared = construction_on_ground(fake, part_structure, ground, bottom=bottom, top=top)
            pieces.append(prepared["roles"]["excavation"])
            bedding_parts.append(pad)
        excavation = unary_union(pieces) if pieces else Polygon()
        bedding = unary_union(bedding_parts) if bedding_parts else Polygon()
        if excavation.is_empty: excavation=Polygon()
        if bedding.is_empty: bedding=Polygon()
        structure["materials"]["bedding"] = bedding
        structure["measured"] = bedding
    shapes = [g for g in (outer, excavation, bedding) if not g.is_empty]
    left, right = min(g.bounds[0] for g in shapes), max(g.bounds[2] for g in shapes)
    cropped = [(left, _ground_at(ground,left)), *[(x,z) for x,z in ground if left < x < right],
               (right, _ground_at(ground,right))]
    soil = Polygon([(left,bottom),(right,bottom),*reversed(cropped)])
    # A pier embedded within its explicitly configured footing pit occupies
    # an already designed excavation. Its overlap is allocated here and
    # deducted from the generated pit by the common spatial union policy.
    # Restrict this to the actual footing footprint, not an inferred pit.
    shared=structure.get("shared_excavation_footprints",[])
    if shared:
        covered=unary_union([box(l,low,r,top) for l,r,low in shared])
        borrowed=outer.intersection(soil).intersection(covered)
        excavation=unary_union([excavation,borrowed])
        if excavation.is_empty:excavation=Polygon()
    domain = box(left,bottom,right,top)
    roles = {"permanent":outer,"measured":bedding,"excavation":excavation,"target":soil,
             "open_air":Polygon(),"removal":Polygon()}
    return {"roles":roles,"soil":soil,"target":soil,"domain":domain,"ground":cropped,
            "daylight":[left,right],"target_bounds":[left,right],"floor":outer.bounds[1],
            "floor_path":[],"finished_profile":[]}
