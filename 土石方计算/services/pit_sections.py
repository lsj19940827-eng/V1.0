"""Rectangular flat-bottom pits cut as actual vertical sections.

Four independent side slopes expand rectangular horizontal footprints; end
slopes constrain the lowest elevation of each transverse slice. Quantities
are integrated from these slices, never from terrain-triangle volume sums.
"""
from __future__ import annotations

import math
import numpy as np
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from .contracts import ConstructionInputError, finite_number
from .section_geometry import number, slope_grades, validated


def legacy_gate_as_pit(asset,alignment, *, strict=True):
    """Carry determined gate location/base into a pit; never guess its length."""
    from copy import deepcopy
    from .network_section_calculator import _profile,_profile_at
    result=deepcopy(asset);s=result.setdefault("section",{});c=result.setdefault("construction",{})
    station=(float(asset["station_start"])+float(asset["station_end"]))/2
    placement=result.setdefault("placement",{})
    placement.setdefault("center_xy",list(alignment.get_xy_at_station(station)))
    element=next(e for e in alignment.elements if e["station_start"]<=station<=e["station_end"])
    if element["kind"]=="line":angle=element["tangent_angle"]
    else:
        sign=math.copysign(1.,element["sweep_angle"])
        angle=element["start_angle"]+sign*(station-element["station_start"])/element["radius"]+sign*math.pi/2
    placement.setdefault("direction",[math.cos(angle),math.sin(angle)])
    if s.get("floor_elevation") is None:
        from .design_profiles import evaluate_profile
        try:
            if asset.get("design_profile"):z,_=evaluate_profile(asset,station)
            else:z,_=_profile_at(_profile(asset,{}),station)
        except ValueError:
            if strict:raise
        else:
            # Legacy foundation reference is concrete underside. Pit floor is
            # bedding underside, so explicit bedding is accounted exactly once.
            s["floor_elevation"]=z-float(c.get("bedding_thickness",0) or 0)
            result.setdefault("parameter_sources",{})["section.floor_elevation"]="legacy foundation control elevation at midpoint minus explicit bedding; confirm the new flat-bottom pit design"
    result.update(section_type="rectangular_pit",kind="pit",legacy_section_type="box_foundation")
    result["original_fields"]={**deepcopy(asset.get("original_fields",{})),"legacy_asset_snapshot":deepcopy(asset)}
    required=[f"section.{k}" for k in ("bottom_length","bottom_width","foundation_length","foundation_width","foundation_height","floor_elevation") if s.get(k) is None]
    required += [f"construction.excavation_slope_{side}" for side in ("left","right","front","back")
                 if c.get("excavation_stages_"+side) is None and c.get("excavation_slope_"+side) is None]
    result["missing_fields"]=required
    if required and strict:
        raise ConstructionInputError(f"闸基 {asset.get('name',asset['asset_id'])} 已转换为矩形平底基坑，待补齐：{', '.join(required)}")
    return result


def offset_at_height(grades, height, *, upper_side=True):
    offset=0.; remaining=max(0.,height)
    for grade in grades:
        used=min(remaining,grade.height)
        offset+=grade.ratio*used; remaining-=used
        if remaining<=1e-10:
            return offset+(grade.berm_width if upper_side and not math.isinf(grade.height) and abs(used-grade.height)<=1e-10 else 0)
        offset+=grade.berm_width
    raise ConstructionInputError("基坑分级坡未覆盖计算高程")


def height_for_offset(grades, offset):
    remaining=max(0.,offset); height=0.
    if remaining<=1e-9:
        return 0.
    for grade in grades:
        reach=grade.ratio*grade.height if grade.ratio else 0.
        if grade.ratio and remaining<=reach:
            return height+remaining/grade.ratio
        remaining-=reach; height+=grade.height
        if math.isinf(height):
            return math.inf
        if remaining<=grade.berm_width+1e-10:
            return height
        remaining-=grade.berm_width
    return math.inf


def pit_config(asset):
    s=asset.get("section",{}); c=asset.get("construction",{})
    if c.get("excavation_base_mode","flat")!="flat":
        raise ConstructionInputError("矩形基坑首版只支持矩形平底，不能按结构外轮廓底面计算")
    if c.get("target_mode","restore_terrain")!="restore_terrain":
        raise ConstructionInputError("矩形基坑首版只恢复原地面")
    length=number(s,"bottom_length",positive=True); width=number(s,"bottom_width",positive=True)
    floor=finite_number(s.get("floor_elevation",s.get("bottom_elevation")),"坑底标高")
    placement=asset.get("placement",asset)
    center=placement.get("center_xy",placement.get("center"))
    if center is None or len(center)!=2:
        raise ConstructionInputError("独立基坑须有实际中心坐标")
    center=[finite_number(v,"坑中心坐标") for v in center]
    direction=placement.get("direction")
    if direction is None:
        angle=math.radians(finite_number(placement.get("angle_degrees"),"基坑方位角"))
        direction=[math.cos(angle),math.sin(angle)]
    direction=np.asarray(direction,dtype=float)
    if direction.shape!=(2,) or not np.isfinite(direction).all() or np.linalg.norm(direction)<=0:
        raise ConstructionInputError("基坑方位必须为有效方向")
    direction/=np.linalg.norm(direction)
    grades={side:slope_grades(c,side) for side in ("left","right","front","back")}
    fw=number(s,"foundation_width",0); fl=number(s,"foundation_length",0)
    if (fw>0)!=(fl>0):
        raise ConstructionInputError("基础长宽须同时明确")
    if fw and (fw+number(c,"working_space_left",0)+number(c,"working_space_right",0)>width+1e-8 or
               fl+number(c,"working_space_front",0)+number(c,"working_space_back",0)>length+1e-8):
        raise ConstructionInputError("施工坑底总尺寸未包含结构及所需工作面；不能重复添加工作面")
    return dict(length=length,width=width,floor=floor,center=center,direction=direction,grades=grades)


def pit_route(asset, tin, *, station_start=0.):
    cfg=pit_config(asset)
    maximum=float(np.max(tin.points[:,2])); height=max(0.,maximum-cfg["floor"])
    # Shrink a proven upper bound using complete ORIGINAL faces intersecting
    # the corresponding four-sided footprint. A distant mountain must not
    # demand fictitious pit sections hundreds of metres beyond the gate.
    # Starting with global maximum means every actual cut remains inside each
    # successive box; using all vertices of intersecting faces is conservative.
    d=cfg["direction"];normal=np.array([d[1],-d[0]]);center=np.asarray(cfg["center"])
    candidate_ids=None
    for _ in range(16):
        ext={side:offset_at_height(cfg["grades"][side],height) for side in cfg["grades"]}
        xs=(-cfg["length"]/2-ext["back"],cfg["length"]/2+ext["front"])
        ys=(-cfg["width"]/2-ext["left"],cfg["width"]/2+ext["right"])
        corners=np.asarray([center+x*d+y*normal for x in xs for y in ys]);lo=corners.min(axis=0);hi=corners.max(axis=0)
        chunks=[];maximum_local=-math.inf
        ids=np.arange(len(tin.triangles)) if candidate_ids is None else candidate_ids
        for start in range(0,len(ids),100_000):
            chunk=ids[start:start+100_000];xyz=tin.points[tin.triangles[chunk]]
            mask=((xyz[:,:,:2].max(axis=1)>=lo)&(xyz[:,:,:2].min(axis=1)<=hi)).all(axis=1)
            if mask.any():
                chunks.append(chunk[mask]);maximum_local=max(maximum_local,float(xyz[mask,:,2].max()))
        if not chunks:raise ConstructionInputError("基坑施工范围内无原始地形三角片")
        candidate_ids=np.concatenate(chunks);new_height=max(0.,maximum_local-cfg["floor"])
        if new_height>=height-1e-8:break
        height=new_height
    front=offset_at_height(cfg["grades"]["front"],height)
    back=offset_at_height(cfg["grades"]["back"],height)
    lo=-cfg["length"]/2-back; hi=cfg["length"]/2+front
    if hi-lo<=0:
        raise ConstructionInputError("基坑切片范围无效")
    center=np.asarray(cfg["center"]); d=cfg["direction"]
    element={"kind":"line","station_start":station_start,"station_end":station_start+hi-lo,
             "length":hi-lo,"start_xy":(center+lo*d).tolist(),"end_xy":(center+hi*d).tolist(),
             "tangent_angle":math.atan2(d[1],d[0])}
    return element,cfg,lo


def pit_slice(asset, station, center, tangent, interp, *, terrain_min,terrain_max, side="right"):
    from ..adapters.independent_assets import _ground_component, _ground_at
    from ..core.construction_geometry import compute_construction_state, _polygonal
    cfg=pit_config(asset); s=asset["section"]; c=asset.get("construction",{})
    local=station-asset["station_start"]+asset["pit_local_start"]
    beyond=max(0.,abs(local)-cfg["length"]/2)
    endside="front" if local>0 else "back"
    hmin=height_for_offset(cfg["grades"][endside],beyond)
    normal=np.array([tangent[1],-tangent[0]])
    baseline=cfg["floor"]
    top=max(terrain_max,baseline)+2.; bottom=min(terrain_min,baseline)-2.
    if not math.isfinite(hmin):
        raise ConstructionInputError("基坑端部范围不符竖直边坡")
    zmin=baseline+hmin
    hmax=top-baseline
    def x_at(h,side):
        return (-1 if side=="left" else 1)*(cfg["width"]/2+offset_at_height(cfg["grades"][side],h))
    def side_points(side):
        sign=-1 if side=="left" else 1
        result=[(x_at(hmin,side),baseline+hmin)]
        cumulative=0.
        for grade in cfg["grades"][side][:-1]:
            cumulative+=grade.height
            if hmin<cumulative<hmax:
                before=offset_at_height(cfg["grades"][side],cumulative,upper_side=False)
                after=offset_at_height(cfg["grades"][side],cumulative,upper_side=True)
                result.append((sign*(cfg["width"]/2+before),baseline+cumulative))
                if after!=before:result.append((sign*(cfg["width"]/2+after),baseline+cumulative))
        result.append((x_at(hmax,side),baseline+hmax))
        return result
    excavation=validated(Polygon([*reversed(side_points("left")),*side_points("right")]),"基坑施工切片")
    # Only actual soil intersection is needed, but a complete connected ground
    # profile must support the bottom footprint and every relevant slope toe.
    required=(x_at(hmin,"left"),x_at(hmin,"right"))
    ground=_ground_component(interp,np.asarray(center),normal,required)
    gl,gr=ground[0][0],ground[-1][0]
    domain=box(gl,bottom,gr,top)
    soil=Polygon([(gl,bottom),(gr,bottom),*reversed(ground)])
    cut=_polygonal(soil.intersection(excavation))
    # If the raw slope still crosses the measurement boundary below ground,
    # it has not demonstrably daylighted. Do not clip it into a valid result.
    for edge in (gl,gr):
        g=_ground_at(ground,edge)
        if excavation.contains(__import__('shapely').Point(edge,g-1e-6)):
            raise ConstructionInputError("基坑侧坡未在有效测区接地")
    foundation=Polygon(); bedding=Polygon()
    fw=number(s,"foundation_width",0); fl=number(s,"foundation_length",0)
    bed=number(c,"bedding_thickness",0); ext=number(c,"bedding_extension",0)
    def inside_extent(half):
        # Compare canonical material-event stations, not a subtract/add
        # round-trip local coordinate. At 2.2m the latter may land one ULP
        # inside the opposite interval and double-count an endpoint slice.
        start=asset["station_start"]-half-asset["pit_local_start"]
        end=asset["station_start"]+half-asset["pit_local_start"]
        if station==start:return side=="right"
        if station==end:return side=="left"
        return start<station<end
    if fw and inside_extent(fl/2):
        support_ground=[_ground_at(ground,-fw/2),_ground_at(ground,fw/2),
                        *[z for x,z in ground if -fw/2<x<fw/2]]
        if min(support_ground)<baseline-1e-7:
            raise ConstructionInputError("矩形坑底高于基础支承范围内的原地面；仅恢复原地面无法形成有效支承，请核对坑底高程")
        fh=number(s,"foundation_height",positive=True)
        foundation=box(-fw/2,baseline+bed,fw/2,baseline+bed+fh)
    if bed and fw and inside_extent(fl/2+ext):
        bedding=box(-fw/2-ext,baseline,fw/2+ext,baseline+bed)
    associated=[]
    for member in asset.get("associated_pier_occupancy",[]):
        start=asset["station_start"]+finite_number(member.get("local_start"),"关联柱沿线起点")-asset["pit_local_start"]
        end=asset["station_start"]+finite_number(member.get("local_end"),"关联柱沿线终点")-asset["pit_local_start"]
        active=(side=="right" if station==start else side=="left" if station==end else start<station<end)
        if not active:continue
        x=finite_number(member.get("offset"),"关联柱横偏距")
        width=number(member,"width",positive=True)
        low=finite_number(member.get("bottom_elevation"),"关联柱底高程")
        high=finite_number(member.get("top_elevation"),"关联柱顶高程")
        if high<=low:raise ConstructionInputError("关联柱顶高程须大于柱底")
        associated.append(box(x-width/2,low,x+width/2,high))
    # The pier already has its own material quantity in the parent aqueduct.
    # Its local footprint remains occupied soil in this pit and is not fill.
    permanent=unary_union([foundation,*associated]) if associated else foundation
    measured=bedding
    state=compute_construction_state(soil,cut,soil,permanent,measured,area_tolerance=1e-6)
    shapes=[g for g in (cut,foundation,bedding) if not g.is_empty]
    if shapes:
        left=min(g.bounds[0] for g in shapes); right=max(g.bounds[2] for g in shapes)
    else:
        left,right=required
    cropped=[(left,_ground_at(ground,left)),*[(x,z) for x,z in ground if left<x<right],(right,_ground_at(ground,right))]
    roles={"excavation":cut,"target":soil,"permanent":permanent,"measured":bedding,
           "open_air":Polygon(),"removal":Polygon(),"concrete":foundation,"bedding":bedding}
    structure={"outer":foundation,"net_void":Polygon(),"materials":{"concrete":foundation,"bedding":bedding},
               "measured":bedding,"occupancy":unary_union([permanent,bedding])}
    return dict(design_elevation=baseline,slope=0.,ground=cropped,soil=soil,roles=roles,
                domain=box(left,bottom,right,top),daylight=[left,right],target_bounds=[left,right],structure=structure,
                gross={"excavation":state.excavation,"backfill":state.backfill,"embankment":state.embankment,
                       "concrete":foundation,"bedding":bedding},floor_path=[(left,zmin),(right,zmin)],
                finished_profile=[],local_position=local)
