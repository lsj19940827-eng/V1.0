# -*- coding: utf-8 -*-
"""施工断面准备；仅输出多边形和管轴，三维建模与布尔交给 Rhino。"""

from __future__ import annotations

from .construction_rules import effective_construction, normalize_asset_construction

from bisect import bisect_right
from copy import deepcopy
import math

from .contracts import ConstructionInputError, SECTION_TYPES, finite_number


def _number(data, key, *, positive=False, nonnegative=False):
    value = finite_number(data.get(key), key)
    if positive and value <= 0 or nonnegative and value < 0:
        raise ConstructionInputError(f"参数 {key} 必须为{'正数' if positive else '非负数'}")
    return value


def _close(points):
    result = [[float(x), float(z)] for x, z in points]
    if not result or result[0] != result[-1]:
        result.append(result[0][:])
    return result


def _rectangle(left, right, bottom, top):
    if left >= right or bottom >= top:
        raise ConstructionInputError("矩形范围必须有正宽度与高度")
    return _close([(left, bottom), (right, bottom), (right, top), (left, top)])


def _validate_ring(ring, name):
    """只检测和拒绝无效轮廓，不使用自动修复改变工程形状。"""
    if len(ring) < 4 or ring[0] != ring[-1]:
        raise ConstructionInputError(f"{name} 必须是闭合多边形")
    for point in ring:
        if len(point) != 2:
            raise ConstructionInputError(f"{name} 的点必须为偏距和高程")
        for value in point:
            finite_number(value, name)
    area2 = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:]))
    if area2 <= 1e-10:
        raise ConstructionInputError(f"{name} 必须按逆时针排列且面积为正")
    def cross(a, b, c):
        return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    edges = list(zip(ring, ring[1:]))
    for i, (a, b) in enumerate(edges):
        if math.hypot(a[0]-b[0], a[1]-b[1]) < 1e-12:
            raise ConstructionInputError(f"{name} 含零长度边")
        for j in range(i+2, len(edges)):
            if i == 0 and j == len(edges)-1:
                continue
            c, d = edges[j]
            ab_c, ab_d = cross(a,b,c), cross(a,b,d)
            cd_a, cd_b = cross(c,d,a), cross(c,d,b)
            if ab_c * ab_d < -1e-14 and cd_a * cd_b < -1e-14:
                raise ConstructionInputError(f"{name} 自相交")


def _offset_open_profile(inner, wall, base):
    """平行偏移衬砌下缘和侧壁，渠口封口线保持原高程。"""
    lines = []
    for a, b in zip(inner, inner[1:] + inner[:1]):
        dx, dz = b[0]-a[0], b[1]-a[1]
        length = math.hypot(dx, dz)
        if length <= 1e-12:
            raise ConstructionInputError("渠断面存在零长度边")
        thickness = 0.0 if a[1] == b[1] == max(p[1] for p in inner) else (
            base if a[1] == b[1] == 0 else wall)
        lines.append(([a[0]+dz/length*thickness, a[1]-dx/length*thickness], [dx, dz]))
    outer = []
    for index, (p, direction) in enumerate(lines):
        q, previous = lines[index-1]
        denom = previous[0]*direction[1]-previous[1]*direction[0]
        if abs(denom) < 1e-12:
            raise ConstructionInputError("相邻衬砌边平行，无法确定外轮廓")
        delta = [p[0]-q[0], p[1]-q[1]]
        t = (delta[0]*direction[1]-delta[1]*direction[0])/denom
        outer.append([q[0]+t*previous[0], q[1]+t*previous[1]])
    ring = _close(outer)
    _validate_ring(ring, "衬砌外包")
    return ring


def _section_outer(section_type, section, arc_segments):
    """返回以渠底或管轴为基准的外包轮廓，永久占位包含全部内部空腔。"""
    if section_type == "box_foundation":
        width = _number(section,"foundation_width",positive=True)
        height = _number(section,"foundation_height",positive=True)
        return [_rectangle(-width/2,width/2,0,height)], {"reference":"foundation_base","height":height}
    is_open = section_type.endswith("channel")
    wall = _number(section, "wall_thickness", positive=not is_open, nonnegative=is_open)
    if section_type in {"circular_culvert", "circular_siphon", "circular_channel"}:
        diameter = _number(section, "inner_diameter", positive=True)
        radius = diameter/2 + wall
        count = _number(section, "pipe_count", positive=True)
        if count != int(count):
            raise ConstructionInputError("pipe_count 必须为正整数")
        spacing = _number(section, "pipe_spacing", nonnegative=True)
        pitch = 2*radius + spacing
        offsets = [(index-(int(count)-1)/2)*pitch for index in range(int(count))]
        rings = [_close([(offset+radius*math.cos(2*math.pi*i/arc_segments),
                          radius*math.sin(2*math.pi*i/arc_segments)) for i in range(arc_segments)])
                 for offset in offsets]
        return rings, {"outer_diameter": 2*radius, "pipe_offsets": offsets,
                       "reference": "pipe_axis", "height": radius,
                       "height_basis": "above_pipe_axis"}
    if section_type == "u_channel":
        radius = _number(section, "inner_radius", positive=True)
        height = _number(section, "inner_height", positive=True)
        theta = finite_number(section.get("u_arc_angle_degrees", 180.0), "U形底弧圆心角")
        alpha = finite_number(section.get("u_side_angle_degrees", 0.0), "U形侧墙外倾角")
        if not 0 < theta <= 360 or not 0 <= alpha < 90:
            raise ConstructionInputError("U形底弧圆心角须在(0,360]度，侧墙外倾角须在[0,90)度")
        half = math.radians(theta)/2
        alpha = math.radians(alpha)
        join_height = radius*(1-math.cos(half))
        if height < join_height-1e-12:
            raise ConstructionInputError("U形渠高不得低于底弧段高度")
        outer_radius = radius+wall
        # 原净形：底弧圆心(0,R)，侧墙由弧端按alpha外倾。
        # 外包为等法向壁厚；偏移侧墙与外圆求交，非切接时保留真实角部。
        px = radius*math.sin(half)+wall*math.cos(alpha)
        pz = join_height-wall*math.sin(alpha)
        ux, uz = math.sin(alpha), math.cos(alpha)
        projection = px*ux+(pz-radius)*uz
        discriminant = projection*projection+outer_radius**2-px**2-(pz-radius)**2
        if discriminant < -1e-12:
            raise ConstructionInputError("U形外壁与外底弧不能衔接")
        if abs(half+alpha-math.pi/2) < 1e-12:
            jx, jz = outer_radius*math.sin(half), radius-outer_radius*math.cos(half)
        else:
            root = math.sqrt(max(0.0, discriminant))
            distance = min((-projection-root, -projection+root), key=abs)
            jx, jz = px+distance*ux, pz+distance*uz
        right_angle = math.atan2(jz-radius, jx)
        if jz > height:
            # 大于半圆的底弧外偏后可能越过渠顶，沿实际渠顶截断外包。
            right_angle = math.asin((height-radius)/outer_radius)
            jx, jz = outer_radius*math.cos(right_angle), height
        half_count = max(1, math.ceil((math.pi/2+right_angle)*arc_segments/math.pi))
        left_angle, end_angle = math.pi-right_angle, 2*math.pi+right_angle
        points = [(outer_radius*math.cos(left_angle+(end_angle-left_angle)*i/(2*half_count)),
                   radius+outer_radius*math.sin(left_angle+(end_angle-left_angle)*i/(2*half_count)))
                  for i in range(2*half_count+1)]
        # 精确复用交点，避免三角函数末位差制造侧墙端缝。
        points[0], points[-1] = (-jx,jz), (jx,jz)
        top_x = px+(height-pz)*math.tan(alpha)
        if height > jz+1e-12:
            points += [(top_x,height),(-top_x,height)]
        ring = _close(points)
        _validate_ring(ring,"U形衬砌外包")
        return [ring], {"reference": "inner_invert", "height": height,
                       "u_arc_angle_degrees": theta, "u_side_angle_degrees": math.degrees(alpha),
                       "u_shell_thickness_basis": "uniform_normal_wall_thickness"}
    width = _number(section, "inner_width", positive=True)
    base = _number(section, "base_thickness", positive=not is_open, nonnegative=is_open)
    if section_type == "arch_culvert":
        wall_height = _number(section, "wall_height", nonnegative=True)
        angle = _number(section, "arch_angle_degrees", positive=True)
        roof = _number(section, "roof_thickness", positive=True)
        if angle > 180:
            raise ConstructionInputError("圆拱暗涵模板仅支持不大于180度的上拱")
        half_angle = math.radians(angle)/2
        inner_radius = width/(2*math.sin(half_angle))
        center = wall_height-inner_radius*math.cos(half_angle)
        outer_radius = inner_radius+roof
        half_width = width/2+wall
        if half_width > outer_radius:
            raise ConstructionInputError("侧墙外宽大于拱外半径，无法衔接外拱")
        end_angle = math.acos(half_width/outer_radius)
        points = [(-half_width,-base),(half_width,-base)]
        points += [(outer_radius*math.cos(end_angle+i*(math.pi-2*end_angle)/arc_segments),
                    center+outer_radius*math.sin(end_angle+i*(math.pi-2*end_angle)/arc_segments))
                   for i in range(arc_segments+1)]
        return [_close(points)], {"reference": "inner_invert", "height": center+outer_radius}
    height = _number(section, "inner_height", positive=True)
    if section_type == "rectangular_culvert":
        roof = _number(section, "roof_thickness", positive=True)
        return [_rectangle(-width/2-wall,width/2+wall,-base,height+roof)], {
            "reference": "inner_invert", "height": height+roof}
    if section_type == "rectangular_channel":
        inner = [(-width/2,0),(width/2,0),(width/2,height),(-width/2,height)]
    elif section_type == "trapezoidal_channel":
        slope = _number(section, "inner_side_slope", nonnegative=True)
        inner = [(-width/2,0),(width/2,0),(width/2+slope*height,height),
                 (-width/2-slope*height,height)]
    elif section_type == "compound_trapezoidal_channel":
        lower_h = _number(section, "compound_lower_height", positive=True)
        bench = _number(section, "compound_bench_width", positive=True)
        upper_m = _number(section, "compound_upper_slope", nonnegative=True)
        lower_m = _number(section, "compound_lower_slope", nonnegative=True)
        right_m = _number(section, "compound_right_slope", nonnegative=True)
        if lower_h >= height:
            raise ConstructionInputError("复式梯形平台高差必须小于总渠高")
        left_lower = -width/2-lower_m*lower_h
        inner = [(-width/2,0),(width/2,0),(width/2+right_m*height,height),
                 (left_lower-bench-upper_m*(height-lower_h),height),
                 (left_lower-bench,lower_h),(left_lower,lower_h)]
    else:
        raise ConstructionInputError(f"不支持的断面类型：{section_type}")
    return [_offset_open_profile(inner,wall,base)], {"reference": "inner_invert", "height": height}


def validate_construction_profile(asset, settings) -> dict:
    """独立参数校验入口，问题可直接显示在参数编辑器中。"""
    try:
        _section_outer(asset.get("section_type"), asset.get("section", {}), 32)
        construction = effective_construction(asset)
        mode=construction.get("installation_mode","buried")
        if asset.get("section_type") in {"circular_culvert","circular_siphon","circular_channel"} and mode not in {
            "buried","exposed","elevated"}:
            raise ConstructionInputError("管道安装方式必须为 buried/exposed/elevated")
        if mode=="buried" or asset.get("section_type") not in {"circular_culvert","circular_siphon","circular_channel"}:
            for field in ("working_space_left", "working_space_right", "bedding_thickness", "bedding_extension"):
                _number(construction,field,nonnegative=True)
            for side in ("left","right"):
                _excavation_side(0.0,0.0,10000.0,side,construction)
        if construction.get("target_mode") not in {"restore_terrain","union_terrain","finished_profile"}:
            raise ConstructionInputError("必须明确恢复原地面、原地面并入堤身或设计完成面")
        base, top = _number(settings,"base_z"), _number(settings,"clip_top_z")
        if base >= top:
            raise ConstructionInputError("共同域底高程必须低于上裁剪高程")
    except ConstructionInputError as exc:
        return {"valid":False,"issues":[{"severity":"error","message":str(exc)}]}
    return {"valid":True,"issues":[]}


def _excavation_side(offset, floor, top, side, construction):
    """分级坡逐级外扩；末级延伸至上裁剪面，中间平台宽度单列。"""
    direction=-1 if side=="left" else 1
    stages=construction.get("excavation_stages_"+side)
    if stages is None:
        slope=_number(construction,"excavation_slope_"+side,nonnegative=True)
        return [[offset,floor],[offset+direction*slope*(top-floor),top]]
    if not isinstance(stages,list) or not stages:
        raise ConstructionInputError("分级开挖坡必须为非空级段列表")
    points=[[offset,floor]]
    for index,stage in enumerate(stages):
        height=_number(stage,"height",positive=True)
        slope=_number(stage,"slope",nonnegative=True)
        berm=_number(stage,"berm_width",nonnegative=True)
        end_z=top if index==len(stages)-1 else points[-1][1]+height
        if end_z>=top and index<len(stages)-1:
            raise ConstructionInputError("中间分级坡已超过上裁剪面，请提高clip_top_z或调整级高")
        x=points[-1][0]+direction*slope*(end_z-points[-1][1])
        points.append([x,end_z])
        if index<len(stages)-1 and berm>0:
            points.append([x+direction*berm,end_z])
    return points


def build_construction_section(asset, *, station, origin, tangent, settings, vertical_slope=0.0):
    """正偏距向右，第二坐标为绝对高程；共同域只用于裁剪。"""
    stype, section, construction = asset["section_type"], asset["section"], effective_construction(asset)
    arc_segments = int(settings.get("arc_segments",64))
    if arc_segments < 16 or arc_segments > 2048:
        raise ConstructionInputError("arc_segments 必须在16至2048之间")
    rings, metadata = _section_outer(stype,section,arc_segments)
    z = finite_number(origin[2],"设计高程")
    # 倾斜圆管在竖直横断面中为椭圆，施工槽和垫层须覆盖真实外包。
    vertical_factor = math.hypot(1.0, finite_number(vertical_slope,"管轴纵坡")) if (
        metadata["reference"]=="pipe_axis") else 1.0
    permanent = [[[x, y*vertical_factor+z] for x,y in ring] for ring in rings]
    p_left=min(p[0] for ring in permanent for p in ring)
    p_right=max(p[0] for ring in permanent for p in ring)
    p_bottom=min(p[1] for ring in permanent for p in ring)
    p_top=max(p[1] for ring in permanent for p in ring)
    unburied=metadata["reference"]=="pipe_axis" and construction.get("installation_mode","buried") in {"exposed","elevated"}
    bedding=0.0 if unburied else _number(construction,"bedding_thickness",nonnegative=True)
    extension=0.0 if unburied else _number(construction,"bedding_extension",nonnegative=True)
    left=p_left-extension-(0.0 if unburied else _number(construction,"working_space_left",nonnegative=True))
    right=p_right+extension+(0.0 if unburied else _number(construction,"working_space_right",nonnegative=True))
    floor=p_bottom-bedding
    base,top=_number(settings,"base_z"),_number(settings,"clip_top_z")
    if not base < floor <= p_bottom < p_top < top:
        raise ConstructionInputError("共同域上下界未完整覆盖结构、垫层和槽底")
    if stype in {"u_channel","trapezoidal_channel"} and not unburied:
        from .section_geometry import section_structure, add_foundation_materials, channel_crown_excavation_path
        structure=add_foundation_materials(section_structure(asset,elevation=z,arc_segments=arc_segments),construction)
        lower=channel_crown_excavation_path(asset,structure)
        right_trace=_excavation_side(*lower[-1],top,"right",construction)
        left_trace=_excavation_side(*lower[0],top,"left",construction)
        excavation=[_close([*lower,*right_trace[1:],*reversed(left_trace)])]
    else:
        excavation=[] if unburied else [_close(_excavation_side(right,floor,top,"right",construction)+
                                               list(reversed(_excavation_side(left,floor,top,"left",construction))))]
    # 明渠墙顶以上必须保持开敞，不能把施工槽内该区域恢复成填土。
    open_air=[]
    if stype.endswith("channel") and stype!="circular_channel":
        from shapely.geometry import Polygon, box
        for ring in excavation:
            above=Polygon(ring).intersection(box(-1e12,p_top,1e12,top))
            if not above.is_empty:
                from shapely.geometry.polygon import orient
                open_air.append(_close(list(orient(above,sign=1).exterior.coords)))
    measured=[] if bedding == 0 else [_rectangle(p_left-extension,p_right+extension,floor,p_bottom)]
    mode=construction.get("target_mode")
    target=[]
    if mode == "union_terrain":
        crest=z+metadata["height"]
        shoulder_left=_number(construction,"bank_top_width_left",nonnegative=True)
        shoulder_right=_number(construction,"bank_top_width_right",nonnegative=True)
        slope_left=_number(construction,"bank_slope_left",nonnegative=True)
        slope_right=_number(construction,"bank_slope_right",nonnegative=True)
        crown_left,crown_right=p_left-shoulder_left,p_right+shoulder_right
        target=[_close([(crown_left-slope_left*(crest-base),base),
                       (crown_right+slope_right*(crest-base),base),
                       (crown_right,crest),(crown_left,crest)])]
    elif mode == "finished_profile":
        profile=construction.get("target_profile")
        if not profile or len(profile)<2:
            raise ConstructionInputError("finished_profile 必须提供从左到右的 target_profile")
        if any(profile[i][0]>=profile[i+1][0] for i in range(len(profile)-1)):
            raise ConstructionInputError("target_profile 偏距必须递增")
        target=[_close([(profile[0][0],base),(profile[-1][0],base)]+list(reversed(profile)))]
    elif mode != "restore_terrain":
        raise ConstructionInputError("target_mode 未明确")
    all_rings=excavation+permanent+measured+target+open_air
    minimum=min(p[0] for ring in all_rings for p in ring)
    maximum=max(p[0] for ring in all_rings for p in ring)
    domain=[_rectangle(minimum,maximum,base,top)]
    for name, region in (("开挖",excavation),("永久占位",permanent),("垫层",measured),("目标包络",target),("明渠开敞空间",open_air)):
        for ring in region:
            _validate_ring(ring,name)
            if any(p[1] < base-1e-9 or p[1] > top+1e-9 for p in ring):
                raise ConstructionInputError(f"{name} 超出共同域上下界")
    dx,dy=finite_number(tangent[0],"tangent_x"),finite_number(tangent[1],"tangent_y")
    length=math.hypot(dx,dy)
    if length<=1e-12:
        raise ConstructionInputError("横断面切向量不能为零")
    dx,dy=dx/length,dy/length
    return {"station":float(station),"origin":list(origin),"tangent":[dx,dy,0.0],
            "lateral":[dy,-dx,0.0],"up":[0.0,0.0,1.0],
            "coordinate_mode":"offset_absolute_elevation","excavation":excavation,
            "target":target,"permanent":permanent,"measured":measured,"open_air":open_air,
            "measured_envelope":deepcopy(measured),"domain":domain,
            "target_mode":mode,"trench_floor_z":floor,
            "domain_semantics":"calculation_clip_only", "template_metadata":metadata}


def _interpolate_profile(profile, station):
    positions=[p["station"] for p in profile]
    if station<positions[0]-1e-8 or station>positions[-1]+1e-8:
        raise ConstructionInputError("设计纵断面未覆盖完整平面范围")
    index=min(max(bisect_right(positions,station)-1,0),len(profile)-2)
    a,b=profile[index],profile[index+1]
    ratio=(station-a["station"])/(b["station"]-a["station"])
    return a["elevation"]+(b["elevation"]-a["elevation"])*ratio


def _alignment_samples(asset, settings):
    """原生曲线优先使用 Rhino 真实采样点，不再沿旧 IP 折线求值。"""
    alignment=asset["alignment"]
    native=alignment.get("native_samples")
    if alignment.get("source")=="rhino_curve" or native is not None:
        if not alignment.get("native_curve_path") or not alignment.get("native_curve_sha256"):
            raise ConstructionInputError("原生曲线绑定缺少资源路径或摘要")
        if not isinstance(native,list) or len(native)<2:
            raise ConstructionInputError("原生曲线至少需要两个真实采样点")
        samples=deepcopy(native)
        for sample in samples:
            sample["station"]=finite_number(sample.get("station"),"原生曲线桩号")
            for key in ("origin","tangent"):
                if len(sample.get(key,[]))!=3:
                    raise ConstructionInputError("原生曲线采样缺少三维 origin/tangent")
                sample[key]=[finite_number(v,key) for v in sample[key]]
            sample["vertical_slope"]=finite_number(sample.get("vertical_slope"),"原生曲线纵坡")
        if any(b["station"]<=a["station"] for a,b in zip(samples,samples[1:])):
            raise ConstructionInputError("原生曲线桩号必须严格递增")
        return samples
    if alignment.get("curves_require_resolution") or (
        alignment.get("plan_geometry")=="source_ip_polyline" and
        any(p.get("turn_radius",0) for p in alignment["plan_points"])):
        raise ConstructionInputError("原平纵曲线尚未解析；不可把 IP 折线冒充真实曲线")
    points=alignment["plan_points"]
    profile=deepcopy(alignment["profile_points"])
    if len(points)<2 or len(profile)<2:
        raise ConstructionInputError("平面与纵断面各至少需要两个点")
    for point in profile:
        point["station"]=finite_number(point.get("station"),"纵断面桩号")
        point["elevation"]=finite_number(point.get("elevation"),"纵断面高程")
    if any(b["station"]<=a["station"] for a,b in zip(profile,profile[1:])):
        raise ConstructionInputError("纵断面桩号必须严格递增")
    stations=[finite_number(p.get("station"),"平面桩号") for p in points]
    if any(b<=a for a,b in zip(stations,stations[1:])):
        raise ConstructionInputError("平面桩号必须严格递增，重复位置须先解决")
    spacing=finite_number(settings.get("section_max_spacing",10.0),"section_max_spacing")
    if spacing<=0:
        raise ConstructionInputError("section_max_spacing 必须为正数")
    plan_samples=[]
    for a,b in zip(points,points[1:]):
        count=max(1,math.ceil((b["station"]-a["station"])/spacing))
        ratios={step/count for step in range(count)}
        ratios.update((p["station"]-a["station"])/(b["station"]-a["station"])
                      for p in profile if a["station"]<p["station"]<b["station"])
        for ratio in sorted(ratios):
            plan_samples.append({"x":a["x"]+(b["x"]-a["x"])*ratio,
                                 "y":a["y"]+(b["y"]-a["y"])*ratio,
                                 "station":a["station"]+(b["station"]-a["station"])*ratio})
    plan_samples.append(deepcopy(points[-1]))
    samples=[]
    for index,p in enumerate(plan_samples):
        before=plan_samples[max(0,index-1)];after=plan_samples[min(len(plan_samples)-1,index+1)]
        elevation=_interpolate_profile(profile,p["station"])
        slopes=[]
        for neighbor in (before,after):
            distance=math.hypot(neighbor["x"]-p["x"],neighbor["y"]-p["y"])
            if distance>1e-12:
                slopes.append(abs(_interpolate_profile(profile,neighbor["station"])-elevation)/distance)
        samples.append({"station":p["station"],"origin":[p["x"],p["y"],elevation],
                        "tangent":[after["x"]-before["x"],after["y"]-before["y"],0],
                        "vertical_slope":max(slopes or [0.0])})
    return samples


def prepare_assets(assets, settings) -> list:
    """冻结参数后准备断面，原对象不变，错误中带对象名称。"""
    prepared=deepcopy(assets)
    for asset in prepared:
        normalize_asset_construction(asset)
        if not asset.get("enabled",True):
            asset["geometry_sections"]=[]
            continue
        try:
            validation=validate_construction_profile(asset,settings)
            if not validation["valid"]:
                raise ConstructionInputError(validation["issues"][0]["message"])
            if asset.get("section_variation_requires_resolution"):
                raise ConstructionInputError("来源段内断面尺寸不同或缺失，须显式分段或提供统一参数")
            alignment=asset["alignment"]
            samples=_alignment_samples(asset,settings)
            _,metadata=_section_outer(asset["section_type"],asset["section"],32)
            reference=alignment.get("elevation_reference")
            if metadata["reference"]=="pipe_axis" and reference=="inner_invert":
                shift=_number(asset["section"],"inner_diameter",positive=True)/2
                for sample in samples:sample["origin"][2]+=shift
                asset["geometry_elevation_transform"]={"from":"inner_invert","to":"pipe_axis",
                    "shift_m":shift,"basis":"inner_diameter_half"}
            elif reference!=metadata["reference"]:
                raise ConstructionInputError(f"纵断面高程含义必须明确为 {metadata['reference']}，当前为 {reference}")
            local_domains=asset.get("calculation_domain_sections")
            if local_domains is not None and (len(local_domains)!=len(samples) or any(
                    limit.get("station")!=sample["station"] for limit,sample in zip(local_domains,samples))):
                raise ConstructionInputError("局部施工辅助范围与冻结断面桩号不一致")
            sections=[]
            for index,p in enumerate(samples):
                section_settings=settings
                if local_domains is not None:
                    section_settings={**settings,"base_z":local_domains[index]["base_z"],
                                      "clip_top_z":local_domains[index]["clip_top_z"]}
                sections.append(build_construction_section(asset,station=p["station"],origin=p["origin"],
                    tangent=p["tangent"],vertical_slope=p["vertical_slope"],settings=section_settings))
            asset["geometry_sections"]=sections
            asset["target_mode"]=asset["construction"]["target_mode"]
            if asset["section_type"] in {"circular_culvert","circular_siphon","circular_channel"}:
                asset["permanent_mode"]="native_pipe"
                asset["outer_diameter"]=metadata["outer_diameter"]
                asset["pipe_offsets"]=metadata["pipe_offsets"]
                if alignment.get("native_curve_path") and len(metadata["pipe_offsets"])>1:
                    curves=alignment.get("native_pipe_curves",[])
                    if len(curves)!=len(metadata["pipe_offsets"]) or any(
                        not all(c.get(k) for k in ("path","sha256","curve_id")) for c in curves):
                        raise ConstructionInputError("空间曲线多管必须分别绑定各管原生轴线，不能猜测侧向偏移")
                asset["pipe_axes"]=[[[s["origin"][0]+s["lateral"][0]*offset,
                                       s["origin"][1]+s["lateral"][1]*offset,s["origin"][2]]
                                      for s in sections] for offset in metadata["pipe_offsets"]]
                asset["permanent_section_semantics"]="reference_only_native_normal_pipe_used"
            else:
                asset["permanent_mode"]="loft_sections"
            asset["station_start"]=samples[0]["station"]
            asset["station_end"]=samples[-1]["station"]
        except (ConstructionInputError,KeyError,TypeError) as exc:
            raise ConstructionInputError(f"{asset.get('name',asset.get('asset_id','对象'))}：{exc}") from exc
    return prepared

def apply_test_profile(assets, *, ground_elevations=None, profile=None) -> list:
    """仅用于明确授权的测试；每项假定单列，绝不覆盖来源记录。"""
    profile=deepcopy(profile or {})
    ground_elevations=ground_elevations or {}
    result=deepcopy(assets)
    for asset in result:
        source_section_type=asset["section_type"]
        replacement=profile.get("section_type_overrides",{}).get(asset["asset_id"])
        if replacement:
            if replacement not in SECTION_TYPES:
                raise ConstructionInputError("测试替换类型不受支持")
            asset["section_type"]=replacement
            asset["kind"]="open_channel" if replacement.endswith("channel") else (
                "siphon" if replacement=="circular_siphon" else "support" if replacement=="box_foundation" else "culvert")
            asset["enabled"]=len(asset["alignment"]["plan_points"])>=2
        if not asset.get("enabled",True):
            continue
        points=asset["alignment"]["plan_points"]
        grounds=ground_elevations.get(asset["asset_id"])
        if grounds is None and "constant_ground_elevation" in profile:
            grounds=[profile["constant_ground_elevation"]]*len(points)
        if grounds is None or len(grounds)!=len(points):
            raise ConstructionInputError(f"{asset['name']}：必须提供与全部平面点逐项对应的真实地形采样")
        grounds=[finite_number(value,"地形采样高程") for value in grounds]
        section={"inner_width":2.0,"inner_height":1.5,"inner_side_slope":1.0,
                 "inner_radius":1.0,"inner_diameter":1.4,"wall_thickness":0.2,
                 "base_thickness":0.2,"roof_thickness":0.2,"wall_height":1.0,
                 "arch_angle_degrees":180.0,"pipe_count":1,"pipe_spacing":0.5,
                 "compound_lower_height":0.6,"compound_bench_width":0.8,
                 "compound_upper_slope":1.0,"compound_lower_slope":0.75,
                 "compound_right_slope":1.0,"foundation_width":2.0,"foundation_height":1.0}
        if asset["section_type"]==source_section_type:
            section.update({k:v for k,v in asset.get("section",{}).items() if v is not None})
        section.update(profile.get("section",{}))
        is_open=asset["kind"]=="open_channel" and asset["section_type"]!="circular_channel"
        construction={"working_space_left":0.5,"working_space_right":0.5,
                      "excavation_slope_left":0.5,"excavation_slope_right":0.5,
                      "bedding_thickness":0.15,"bedding_extension":0.2,"installation_mode":"buried",
                      "target_mode":"union_terrain" if is_open else "restore_terrain",
                      "bank_top_width_left":0.5,"bank_top_width_right":0.5,
                      "bank_slope_left":1.5,"bank_slope_right":1.5}
        construction.update(profile.get("construction",{}))
        burial=finite_number(profile.get("cover_depth",1.0),"测试覆土厚度")
        invert_depth=finite_number(profile.get("open_invert_depth",0.8),"测试渠底埋深")
        if burial<0:
            raise ConstructionInputError("测试覆土厚度不得为负")
        _,metadata=_section_outer(asset["section_type"],section,32)
        design=[]
        for p,ground in zip(points,grounds):
            if metadata["reference"]=="pipe_axis":
                installation=construction.get("installation_mode","buried")
                if installation=="buried":
                    elevation=ground-burial-metadata["outer_diameter"]/2
                else:
                    clearance=0.0 if installation=="exposed" else finite_number(profile.get("elevated_clearance",1.0),"测试架空净空")
                    if clearance<0:raise ConstructionInputError("测试架空净空不得为负")
                    elevation=ground+metadata["outer_diameter"]/2+clearance
            elif metadata["reference"]=="foundation_base":
                elevation=ground-finite_number(profile.get("foundation_embedment",0.5),"测试基础埋深")
            elif is_open:
                elevation=ground-invert_depth
            else:
                elevation=ground-burial-metadata["height"]
            design.append({"station":p["station"],"elevation":elevation})
        asset["section"]=section
        asset["construction"]=construction
        normalize_asset_construction(asset)
        construction=asset["construction"]
        asset["alignment"]["profile_points"]=design
        asset["alignment"]["elevation_reference"]=metadata["reference"]
        asset["alignment"]["plan_geometry"]="test_source_polyline"
        asset["alignment"]["station_basis"]="test_plan_chord"
        asset["alignment"]["curves_require_resolution"]=False
        asset["is_test"]=True
        asset["test_only"]=True
        asset["section_variation_requires_resolution"]=False
        asset["test_overrides"]={"label":"明确测试参数，不作为正式设计或工程量成果",
            "profile_id":str(profile.get("profile_id","rhino_acceptance_test_v1")),
            "section_type":asset["section_type"],"section":deepcopy(section),
            "construction":deepcopy(construction),"profile_points":deepcopy(design),
            "ground_elevations":grounds,"cover_depth":burial,"open_invert_depth":invert_depth,
            "plan_assumption":"保留所有原坐标，测试采用IP折线；原转弯半径仍保留在original_fields中",
            "ground_source":"explicit_constant_test_ground" if "constant_ground_elevation" in profile
                             and asset["asset_id"] not in ground_elevations else "sampled_terrain"}
        asset["geometry_sections"]=[]
    return result
