"""Editable 2D drawings and numeric workbooks from one section snapshot."""
from __future__ import annotations

from ..services.construction_rules import bedding_applicable
from .quantity_policy import overlap_policy_note

from collections import defaultdict
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np

NAMES = {"ground":"原地面", "outer":"结构外包", "net_void":"结构净空",
         "concrete":"结构混凝土", "bedding":"垫层", "construction":"施工边界",
         "excavation":"天然开挖", "backfill":"周边回填", "embankment":"新增填筑"}
COLORS = {"ground":8,"outer":7,"net_void":7,"concrete":8,"bedding":6,
          "construction":4,"excavation":1,"backfill":2,"embankment":5,
          "pipe_wall":7,"lining":3}
NAMES.update(pipe_wall="非混凝土管壁",lining="管道内衬")
NAMES.update(overburden="覆盖层开挖（简化）",bedrock="基岩开挖（简化）",interface="简化基覆界面")
COLORS.update(overburden=30,bedrock=1,interface=3)
SECTION_HATCH_PAPER_SPACING_MM = 0.5
ANSI31_ISO_SPACING = 3.175
PLAN_BOUNDARY_LAYERS={"excavation":"开挖开口线","embankment":"填筑边界线","combined":"挖填联合包络线"}
PLAN_ENVELOPE_GRID_M=1e-5
PLAN_ENVELOPE_CLEANUP_M=.10
PLAN_ENVELOPE_BEVEL_M=.25
PLAN_ENVELOPE_SIMPLIFY_M=.005
PLAN_ENVELOPE_DEGENERATE_WIDTH_M=.001
PLAN_ENVELOPE_DEGENERATE_STATION_M=.0001
VOLUMES = [("excavation_volume","天然开挖"),("backfill_volume","周边回填"),
           ("embankment_volume","新增填筑"),("total_fill_volume","总填方"),
           ("concrete_volume","结构混凝土"),("bedding_volume","垫层")]
LAYER_VOLUMES = [("overburden_volume","覆盖层开挖（简化）"),("bedrock_volume","基岩开挖（简化）"),
                 ("unclassified_excavation_volume","未分层挖方")]


def section_sampling_note(payload):
    """Describe the chosen spacing and integration method in saved outputs."""
    accuracy=(payload.get("inputs") or {}).get("accuracy",{})
    validation=payload.get("validation") or {}
    if validation.get("trenchless_only"):
        return "非开挖圆孔断面积乘计量长度。"
    if validation.get("sluice_gate_only"):
        return "闸底板和两侧边墙分别按矩形截面积乘闸长计量。"
    mode=validation.get("sampling_mode",accuracy.get("sampling_mode","adaptive"))
    if mode=="fixed":
        step=float(accuracy.get("profile_step",20.))
        if _has_curve_sampling(payload):
            return f"常规最大间距{step:g}m，弯道自动加密，平均断面法。弯道新增断面参与算量和包络，均剖切真实地形。"
        return f"固定间距{step:g}m，平均断面法。沿线路统一布置，仅在结构和材料起止处补必要断面。"
    return "自适应加密，实际地形剖切、真实中点积分；复算结果见计算记录。"


def _has_curve_sampling(payload):
    validation=payload.get("validation") or {}
    inputs=payload.get("inputs") or {}
    return validation.get("fixed_sampling_contract",inputs.get("fixed_sampling_contract"))=="route_grid_curves_2"


_SAMPLING_REASON_NAMES={"route_grid":"常规间距", "asset_boundary":"结构区段端点",
    "construction_interface":"结构或材料交界", "curve_start":"圆弧起点BC", "curve_end":"圆弧终点EC",
    "curve_midpoint":"圆弧中点MC", "curve_subdivision":"弯道加密"}


def layered_volume_columns(payload):
    """Legacy results retain their existing columns and missing values stay blank."""
    rows=[payload,*payload.get("rows",payload.get("assets",[])),*payload.get("segments",[])]
    return [(key,name) for key,name in LAYER_VOLUMES if any(key in row for row in rows)]


def layered_scope_note(payload):
    if not layered_volume_columns(payload) and not any(_is_layered(s) for s in payload.get("sections",[])):
        return ""
    scope=payload.get("layered_excavation_scope") or {}
    layered=scope.get("layered_asset_ids")
    if layered is None:
        layered=sorted({str(s["asset_id"]) for s in payload.get("sections",[]) if _is_layered(s)})
    unlayered=scope.get("unlayered_asset_ids")
    if unlayered is None:
        all_ids={str(row["asset_id"]) for row in payload.get("rows",payload.get("assets",[]))}
        unlayered=sorted(all_ids-set(map(str,layered)))
    note="简化基覆界面按原地面高程减去用户输入的竖直覆盖层厚度；覆盖层和基岩开挖为天然开挖子项，不重复累加。"
    if layered:note+=f"分层范围：已设置{len(layered)}个对象，详见分项工程量。"
    if unlayered:note+=f"另有{len(unlayered)}个未分层对象；两层小计仅覆盖已设分层对象。"
    return note


def special_material_scope_note(payload):
    """Describe the independently adopted material and earthwork bases."""
    block=payload.get("special_pipe_materials") or {}
    if block.get("length_mode_active") is False:return ""
    if not (block.get("length_mode_active") or block.get("applied") or block.get("rows") or
            any(group.get("applied") for group in block.get("groups",[])) or
            payload.get("special_pipe_material_items")):
        return ""
    return (block.get("scope_note") or
        "特殊管段材料按长度计；一般构造按长度比例扣减；土方保留原施工构造及实际地形，未随长度材料变化作位置修正。")


def _special_material_export_tables(payload):
    """Keep unlocated length records separate from physical station records."""
    block=payload.get("special_pipe_materials") or {}
    if not special_material_scope_note(payload):return []
    groups=block.get("groups",[])
    group_map={str(group.get("group_id")):group for group in groups}
    group_rows=[]
    for group in groups:
        group_rows.append([group.get("route_id"),group.get("asset_id"),group.get("name"),
            group.get("group_id"),{"length":"按长度","station":"按起止桩号"}.get(group.get("mode"),group.get("mode")),
            group.get("available_length_m"),group.get("special_length_m"),group.get("general_length_m"),
            group.get("soil_basis_label"),group.get("scope_note") or special_material_scope_note(payload)])
    items=payload.get("special_pipe_material_items") or []
    item_rows=[]
    for item in items:
        group=group_map.get(str(item.get("group_id")),{})
        item_rows.append([item.get("route_id",group.get("route_id")),item.get("asset_id",group.get("asset_id")),
            item.get("asset_name",group.get("name")),item.get("group_id"),item.get("record_id"),
            "按占比" if "object_percent" in item else "按长度","未定位",None,None,item.get("scheme_title") or item.get("name"),
            item.get("length_m"),item.get("length_source") or "实际管轴长度",
            item.get("component_id"),item.get("name"),item.get("material"),item.get("grade"),item.get("unit"),
            item.get("rate"),item.get("baseline_quantity"),item.get("general_deduction_quantity"),
            item.get("special_addition_quantity"),item.get("quantity"),
            item.get("method"),group.get("soil_basis_label")])
    adjustments=[]
    for item in block.get("adjustments",[]):
        group=group_map.get(str(item.get("group_id")),{})
        adjustments.append([item.get("route_id",group.get("route_id")),item.get("asset_id",group.get("asset_id")),
            item.get("group_id"),item.get("component_id"),item.get("name"),item.get("material"),item.get("grade"),
            item.get("unit"),item.get("baseline_quantity"),
            item.get("deducted_quantity",item.get("general_deduction_quantity")),
            item.get("added_quantity",item.get("special_addition_quantity")),
            item.get("final_quantity",item.get("quantity"))])
    return [("特殊管段计量设置",["线路","对象编号","对象名称","规格组","材料采用方式","可用实际总长m",
                "特殊净长度m","剩余一般长度m","土方采用依据","材料与土方计量说明"],group_rows),
            ("特殊管段材料明细",["线路","对象编号","对象名称","规格组","记录编号","材料采用方式","位置状态",
                "起点m","终点m","采用构造","长度m","长度依据","构件编号","分项名称","材料","等级","单位",
                "每米用量","一般基准量","一般构造扣减量","特殊构造增加量","采用后数量","计量方法","土方采用依据"],item_rows),
            ("特殊构造替换汇总",["线路","对象编号","规格组","构件编号","分项名称","材料","等级","单位",
                "一般基准量","一般构造扣减量","特殊构造增加量","采用后数量"],adjustments)]


def _is_layered(section):
    return (section.get("geology") or {}).get("mode")=="surface_thickness"


def _component_role(spec):
    identity=json.dumps([spec.get(key,"") for key in ("component_id","name","material","grade")],ensure_ascii=False,separators=(",",":"))
    role="component_"+hashlib.sha256(identity.encode("utf8")).hexdigest()[:16]
    material={"mortar":"砂浆","membrane":"防渗膜","geomembrane":"防渗膜","concrete":"混凝土","geotextile":"土工布","steel":"钢材"}.get(spec.get("material"),str(spec.get("material") or "材料"))
    name="_".join(str(part) for part in (material,spec.get("name") or spec.get("component_id"),spec.get("grade")) if part)
    NAMES.setdefault(role,re.sub(r'[<>/\\":;?*|=]',"_",name)[:200])
    COLORS.setdefault(role,3 if spec.get("unit")=="m2" else 6 if spec.get("material")=="mortar" else 30)
    return role


def _ensure_material_layer(model,role):
    name=NAMES[role]
    if name not in model.doc.layers:model.doc.layers.new(name,dxfattribs={"color":COLORS[role]})


def component_lines(section):
    """Surface components remain actual open lines, never filled areas."""
    from shapely.geometry import shape
    def lines(value):
        if value.is_empty:return
        if value.geom_type in ("LineString","LinearRing"):
            yield np.asarray(value.coords,float)
        else:
            for child in getattr(value,"geoms",()):yield from lines(child)
    for spec in section.get("structure_geometry",{}).get("component_surfaces",{}).values():
        geometry=spec.get("geometry")
        if not geometry:continue
        value=shape(geometry) if isinstance(geometry,dict) else geometry
        role=_component_role(spec)
        for line in lines(value):yield role,line


def polygons(data):
    from shapely.geometry import shape
    if not data: return []
    value = shape(data) if isinstance(data,dict) else data
    if value.is_empty: return []
    if value.geom_type == "Polygon": return [value] if value.area>0 else []
    return [p for child in getattr(value,"geoms",()) for p in polygons(child)]


def geometry_items(section):
    """Areas retain holes; outlines never become fictitious solid material."""
    excavation_roles=("overburden","bedrock") if _is_layered(section) else ("excavation",)
    for role in (*excavation_roles,"backfill","embankment"):
        for poly in polygons(section.get("roles",{}).get(role,{}).get("geometry")):
            yield role,poly,True
    structure=section.get("structure_geometry",{})
    for role,data in structure.get("materials",{}).items():
        mapped=role if role in NAMES else "concrete"
        for poly in polygons(data): yield mapped,poly,True
    for spec in structure.get("component_regions",{}).values():
        role=_component_role(spec)
        for poly in polygons(spec.get("geometry")):yield role,poly,True
    for role in ("outer","net_void"):
        if role=="net_void" and any(p.get("earthwork_envelope_only") for p in structure.get("pipes",[])):continue
        for poly in polygons(structure.get(role)):
            yield role,poly,False
    construction=section.get("construction_geometry",{})
    if not structure.get("outer"):
        for poly in polygons(construction.get("permanent")):
            yield "outer",poly,False
    # Calculation domains have artificial caps. Draw their genuine line
    # fragments through construction_lines(), never as closed section polygons.


def ground_parts(section):
    yield from _finite_parts(section.get("ground_points",[]))


def _finite_parts(points):
    part=[]
    for u,z in points:
        if u is None or z is None or not math.isfinite(float(u)) or not math.isfinite(float(z)):
            if len(part)>1: yield np.asarray(part,float)
            part=[]
        else: part.append((float(u),float(z)))
    if len(part)>1: yield np.asarray(part,float)


def interface_parts(section):
    geology=section.get("geology") or {}
    if geology.get("mode")=="surface_thickness":
        yield from _finite_parts(geology.get("interface_points",[]))


def section_limits(section):
    bounds=[poly.bounds for _,poly,_ in geometry_items(section)]
    bounds.extend((float(line[:,0].min()),float(line[:,1].min()),float(line[:,0].max()),float(line[:,1].max())) for _,line in component_lines(section) if len(line))
    if bounds:
        left=min(b[0] for b in bounds)-2; right=max(b[2] for b in bounds)+2
        bottom=min(b[1] for b in bounds);top=max(b[3] for b in bounds)
    else:
        left,right,bottom,top=-10.,10.,0.,1.
    ground=[part[(part[:,0]>=left)&(part[:,0]<=right)] for part in ground_parts(section)]
    values=[a for a in ground if len(a)]
    values.extend(part[(part[:,0]>=left)&(part[:,0]<=right)] for part in interface_parts(section)
                  if len(part) and np.any((part[:,0]>=left)&(part[:,0]<=right)))
    if values:
        bottom=min(bottom,min(float(a[:,1].min()) for a in values))
        top=max(top,max(float(a[:,1].max()) for a in values))
    return left,right,bottom,top


def _construction_segments(section, bounds=None):
    """Original excavation/finished edges with domain closures removed.

    Clip line segments rather than filled polygons, so clipping cannot add a
    fictitious closure along a view boundary. Edges connected to a recorded
    top/bottom domain cap are calculation scaffolding and are omitted wholly.
    """
    from shapely.geometry import LineString, box
    left,right,bottom,top = bounds or section_limits(section)
    padding = max(.3,(top-bottom)*.035)
    window = box(left,bottom-padding,right,top+padding)
    domain = polygons(section.get("domain"))
    cap = (min(p.bounds[1] for p in domain),max(p.bounds[3] for p in domain)) if domain else None
    for role in ("excavation","target"):
        for poly in polygons(section.get("construction_geometry",{}).get(role)):
            for ring in (poly.exterior,*poly.interiors):
                values=np.asarray(ring.coords,dtype=float)
                start, end = values[:-1], values[1:]
                distances = np.hypot(*(end-start).T)
                keep = distances > 1e-10
                if cap:
                    on_cap = (np.abs(values[:, 1, None]-cap) <= 1e-6).any(axis=1)
                    keep &= ~(on_cap[:-1] | on_cap[1:])
                inside = ((values[:, 0] >= left) & (values[:, 0] <= right)
                          & (values[:, 1] >= bottom-padding) & (values[:, 1] <= top+padding))
                for i in np.flatnonzero(keep):
                    if inside[i] and inside[i+1]:
                        # A segment already inside the closed clipping window
                        # has exactly the original endpoints and direction.
                        if distances[i] > 1e-9:
                            yield role, values[i:i+2]
                        continue
                    first, last = start[i], end[i]
                    clipped=LineString([first,last]).intersection(window)
                    parts=[clipped] if clipped.geom_type=="LineString" else getattr(clipped,"geoms",())
                    for line in parts:
                        if line.geom_type=="LineString" and line.length>1e-9:
                            yield role,np.asarray(line.coords,dtype=float)


def construction_lines(section, bounds=None):
    """Drawable original edge fragments; clipping never creates closures."""
    return [line for _,line in _construction_segments(section,bounds)]


def _construction_labels(section,bounds):
    """Labels are measured from saved edges, including each separate bench."""
    outside=polygons(section.get("structure_geometry",{}).get("outer"))
    outer_left=min((p.bounds[0] for p in outside),default=0.)
    outer_right=max((p.bounds[2] for p in outside),default=0.)
    outer_top=max((p.bounds[3] for p in outside),default=math.inf)
    materials=[p for data in section.get("structure_geometry",{}).get("materials",{}).values() for p in polygons(data)]
    material_left=min((p.bounds[0] for p in materials),default=outer_left)
    material_right=max((p.bounds[2] for p in materials),default=outer_right)
    seen=set()
    for role,line in _construction_segments(section,bounds):
        for a,b in zip(line[:-1],line[1:]):
            if a[0]>b[0]:a,b=b,a
            dx,dz=b-a;key=tuple(np.round(np.r_[a,b],7))
            if key in seen:continue
            seen.add(key)
            if abs(dz)>1e-7:
                if abs(dx)>1e-7:
                    yield (a+b)/2, f"{'挖坡' if role=='excavation' else '完成坡'}1:{abs(dx/dz):.3g}",abs(dx)+abs(dz)
                continue
            if abs(dx)<1e-5:continue
            pieces=[]
            if role=="target":
                left_name,right_name=("左平台","右平台") if abs(a[1]-outer_top)<1e-6 else ("左完成面宽","右完成面宽")
                if a[0]<outer_left-1e-6:pieces.append((a[0],min(b[0],outer_left),left_name))
                if b[0]>outer_right+1e-6:pieces.append((max(a[0],outer_right),b[0],right_name))
                if not pieces:pieces=[(a[0],b[0],"完成宽")]
            else:
                # The lowest horizontal is the actual trench floor; all other
                # horizontals are benches, rather than artificial domain caps.
                floors=polygons(section.get("construction_geometry",{}).get("excavation"))
                floor=min((p.bounds[1] for p in floors),default=math.inf)
                pieces=[(a[0],b[0],"槽底宽" if abs(a[1]-floor)<1e-6 else "马道宽")]
                if abs(a[1]-floor)<1e-6:
                    if a[0]<material_left-1e-6:pieces.append((a[0],min(b[0],material_left),"左工作面"))
                    if b[0]>material_right+1e-6:pieces.append((max(a[0],material_right),b[0],"右工作面"))
            for l,r,label in pieces:
                if r-l>1e-5:yield np.array([(l+r)/2,a[1]]),f"{label}{r-l:.3f}m",r-l


def longitudinal_values(section):
    """Real saved geometry levels; missing coverage remains None."""
    from shapely.geometry import LineString
    values={"design_base":section.get("design_elevation"),"ground":None}
    for part in ground_parts(section):
        if part[:,0].min()<=0<=part[:,0].max():
            order=np.argsort(part[:,0]);values["ground"]=float(np.interp(0,part[order,0],part[order,1]));break
    for part in interface_parts(section):
        if part[:,0].min()<=0<=part[:,0].max():
            order=np.argsort(part[:,0]);values["interface"]=float(np.interp(0,part[order,0],part[order,1]));break
    structure=section.get("structure_geometry",{})
    outer=polygons(structure.get("outer"))
    if not outer:outer=polygons(section.get("construction_geometry",{}).get("permanent"))
    if outer:
        values["outer_top"]=max(p.bounds[3] for p in outer)
        values["outer_bottom"]=min(p.bounds[1] for p in outer)
    bedding=polygons(structure.get("materials",{}).get("bedding"))
    if bedding:values["bedding_bottom"]=min(p.bounds[1] for p in bedding)
    for index,(pipe,center) in enumerate(zip(structure.get("pipes",[]),structure.get("pipe_centers",[])),1):
        nearby=min(outer,key=lambda p:abs(p.centroid.x-center[0])) if outer else None
        values[f"pipe_{index}_axis"]=float(center[1])
        if nearby:
            values[f"pipe_{index}_top"]=nearby.bounds[3]
            values[f"pipe_{index}_bottom"]=nearby.bounds[1]
        values[f"pipe_{index}_ground"]=None
        for part in ground_parts(section):
            if part[:,0].min()<=center[0]<=part[:,0].max():
                order=np.argsort(part[:,0]);values[f"pipe_{index}_ground"]=float(np.interp(center[0],part[order,0],part[order,1]));break
    target=polygons(section.get("construction_geometry",{}).get("target"))
    domain=polygons(section.get("domain"))
    cap=max((p.bounds[3] for p in domain),default=math.inf)
    finishes=[]
    for p in target:
        result=p.intersection(LineString([(0,p.bounds[1]-1),(0,p.bounds[3]+1)]))
        if not result.is_empty and result.bounds[3]<cap-1e-6:finishes.append(result.bounds[3])
    values["finished"]=max(finishes) if finishes else None
    floors=polygons(section.get("construction_geometry",{}).get("excavation"))
    if floors:values["construction_floor"]=min(p.bounds[1] for p in floors)
    return values


def _assets(payload):
    inputs=payload.get("inputs",{})
    if inputs.get("network"): return inputs["network"].get("assets",[])
    work=inputs.get("workbench",inputs.get("workbench_inputs",{}))
    return [a for n in work.get("networks",[]) for a in n.get("assets",[])]+work.get("pits",[])


def select_sections(payload,interval=20.,all_sections=False):
    values=payload.get("sections",[])
    if all_sections: return list(values)
    if not math.isfinite(float(interval)) or interval<=0: raise ValueError("出图间距必须为正数")
    key_reasons = {"asset_boundary", "construction_interface", "curve_start", "curve_midpoint", "curve_end"}
    by_asset=defaultdict(list)
    for section in values: by_asset[section["asset_id"]].append(section)
    chosen=[]; assets={a["asset_id"]:a for a in _assets(payload)}
    for aid,sections in by_asset.items():
        sections=sorted(sections,key=lambda r:(r["station"],str(r.get("side",""))))
        stations=np.asarray([r["station"] for r in sections])
        keys={float(stations[0]),float(stations[-1])}
        if stations[-1]-stations[0]<=interval:keys.add(float((stations[0]+stations[-1])/2))
        asset=assets.get(aid,{})
        for field in ("station_start","station_end"):
            if field in asset: keys.add(float(asset[field]))
        keys.update(float(section["station"]) for section in sections
                    if not key_reasons.isdisjoint(section.get("sampling_reasons") or ()))
        for k in range(int((stations[-1]-stations[0])/interval)+1):keys.add(float(stations[0]+k*interval))
        indexes=set()
        for station in keys:
            index=int(np.abs(stations-station).argmin());actual=stations[index]
            indexes.update(np.flatnonzero(np.abs(stations-actual)<1e-8).tolist())
        # A saved one-sided discontinuity is mandatory even between grid stations.
        unique,counts=np.unique(stations,return_counts=True)
        for station in unique[counts>1]:indexes.update(np.flatnonzero(stations==station).tolist())
        chosen.extend(sections[i] for i in sorted(indexes))
    return sorted(chosen,key=lambda r:(str(r["asset_id"]),float(r["station"]),str(r.get("side",""))))


def _tag(entity,identity):
    entity.set_xdata("QX_SECTION_AREA",[(1000,str(identity))])
    return entity


def _add_section_polyline(model, points, *, close=False, dxfattribs):
    """Set all XY vertices at once for an ordinary straight-edged polyline."""
    entity = model.add_lwpolyline([], close=close, dxfattribs=dxfattribs)
    vertices = np.zeros((len(points), entity.lwpoints.VERTEX_SIZE), dtype=np.float64)
    vertices[:, :2] = points
    entity.lwpoints.values = vertices
    return entity


def _ring(model,ring,role,transform,identity):
    _ensure_material_layer(model,role)
    points=[transform(x,z) for x,z in ring.coords]
    return _tag(_add_section_polyline(model,points,close=True,dxfattribs={"layer":NAMES[role]}),identity)


def _hatch(model,poly,role,transform,identity,ratio):
    _ensure_material_layer(model,role)
    hatch=_tag(model.add_hatch(color=COLORS[role],dxfattribs={"layer":NAMES[role]}),identity)
    spacing_m = SECTION_HATCH_PAPER_SPACING_MM * ratio / 1000
    hatch.set_pattern_fill("ANSI31",color=COLORS[role],scale=spacing_m / ANSI31_ISO_SPACING,style=0)
    hatch.paths.add_polyline_path([transform(x,z) for x,z in poly.exterior.coords],is_closed=True,flags=1)
    for ring in poly.interiors:
        hatch.paths.add_polyline_path([transform(x,z) for x,z in ring.coords],is_closed=True,flags=0)
    return hatch


def _translate_section_members(members, dx, dy):
    from ezdxf.math import Matrix44, OCSTransform

    translation = Matrix44.translate(dx, dy, 0.)
    for entity in members:
        if entity.dxftype() == "LWPOLYLINE" and entity.dxf.extrusion == (0., 0., 1.):
            # Section polylines use the world XY plane. A pure translation
            # moves their coordinates without rebuilding their packed arrays.
            entity.lwpoints.values[:, :2] += (dx, dy)
        elif entity.dxftype() == "HATCH":
            # ezdxf's HATCH.translate() reapplies the existing pattern scale.
            transform = OCSTransform(entity.dxf.extrusion, translation)
            entity.paths.transform(transform, elevation=entity.dxf.elevation.z)
        else:
            entity.translate(dx, dy, 0.)


def _section_entity_bounds(entities):
    from ezdxf import bbox
    from ezdxf.entities.boundary_paths import PolylinePath

    straight, other = [], []
    for entity in entities:
        if entity.dxftype() in {"LWPOLYLINE", "HATCH"} and entity.dxf.extrusion == (0., 0., 1.):
            if entity.dxftype() == "LWPOLYLINE":
                vertices = entity.lwpoints.values
                if len(vertices) >= 2 and not vertices[:, 4].any():
                    straight.append(vertices[:, :2])
                    continue
            elif all(isinstance(path, PolylinePath) and len(path.vertices) >= 2 and not path.has_bulge()
                     for path in entity.paths.paths):
                straight.extend(np.asarray(path.vertices)[:, :2] for path in entity.paths.paths)
                continue
        other.append(entity)
    extent = bbox.extents(other, fast=True)
    if straight:
        points = np.concatenate(straight)
        extent.extend([points.min(axis=0), points.max(axis=0)])
    return [extent.extmin.x, extent.extmin.y, extent.extmax.x, extent.extmax.y]


def _text_units(value):
    import unicodedata
    return sum(1. if unicodedata.east_asian_width(c) in "WF" else .62 for c in str(value))


def _wrapped(value,width,height):
    # CJK glyphs in the exported simhei font are wider than DXF char_height.
    maximum=max(1.,(width-1)/(height*1.6))
    rows=[];current="";units=0.
    # Keep a station, ratio or numeric quantity together in narrow captions.
    # Long identifiers can still wrap when they exceed the entire line width.
    tokens=re.findall(r"[A-Za-z0-9_+\-][A-Za-z0-9_+.\-:/%²³]*|.",str(value),re.DOTALL)
    for token in tokens:
        if token=="\n":
            rows.append(current);current="";units=0.;continue
        for part in ([token] if _text_units(token)<=maximum else list(token)):
            amount=_text_units(part)
            if current and units+amount>maximum:
                rows.append(current.rstrip());current="";units=0.
            if not current and part.isspace():continue
            current+=part;units+=amount
    if current or not rows:rows.append(current)
    return rows


def _paper_text(layout,text,position,width,height=2.5):
    content=str(text).replace("\\","\\\\").replace("{","\\{").replace("}","\\}").replace("^","^ ").replace("\n","\\P")
    return layout.add_mtext(content,dxfattribs={"char_height":height,"width":width,"style":"中文","layer":"标注","insert":position,"attachment_point":1})


def _view_tag(entity,view_id):
    entity.set_xdata("QX_DRAWING_VIEW",[(1000,str(view_id))]);return entity


def _caption(section,payload,row,asset,ratio,detail=False):
    if payload.get("_concise_drawing"):
        from .concise_quantities import section_quantity_labels,station_label
        name=str(row.get("name",asset.get("name",section["asset_id"])))
        if name.strip() in {"","-","—","/","未命名"}:
            from ..services.structure_quantities import structure_category
            name=structure_category(payload,row or asset)
        side={"left":"前","right":"后"}.get(section.get("side"),"")
        title=f"{name}  {station_label(section['station'])}{side}  1:{ratio:g}"
        return title,section_quantity_labels(section,asset)
    from .network_exporter import structure_label
    name=str(row.get("name",asset.get("name",section["asset_id"])))
    position=(f"局部切片 {section.get('local_position',section['station']):.3f}m" if section.get("coordinate_kind")=="pit_local_slice" else f"桩号 {section['station']:.3f}m")
    side={"left":" / 变化前","right":" / 变化后"}.get(section.get("side"),"")
    title=f"{'TEST ' if payload.get('test_only') else ''}{name} / {position}{side}"
    components=section.get("structure_geometry",{})
    pipes=components.get("pipes",[])
    definition=asset.get("section",{});construction=asset.get("construction",{})
    envelope_only=definition.get("earthwork_envelope_only") is True or any(p.get("earthwork_envelope_only") for p in pipes)
    lines=[f"{structure_label(payload,row or asset)} / {'结构详图' if detail else '施工横断面'}　1:{ratio:g}"]
    parameters=[]
    if not pipes:
        fields=[("base_thickness","底板"),("wall_thickness_left","左墙"),("wall_thickness_right","右墙")]
        if asset.get("section_type") in ("rectangular_culvert","arch_culvert"):fields.append(("roof_thickness","顶板"))
        for key,label in fields:
            value=definition.get(key,definition.get("wall_thickness") if key.startswith("wall_") else None)
            if isinstance(value,(int,float)):parameters.append(f"{label}t={value:.3f}m")
        if definition.get("material_grade"):parameters.append(str(definition["material_grade"]))
    if bedding_applicable(asset) and isinstance(construction.get("bedding_thickness"),(int,float)) and construction["bedding_thickness"]>0:
        parameters.append(f"垫层{construction.get('bedding_grade') or ''} t={construction['bedding_thickness']:.3f}m")
    materials={"mortar":"砂浆","membrane":"防渗膜","geomembrane":"防渗膜","concrete":"混凝土","geotextile":"土工布","steel":"钢材"}
    for key in ("component_regions","component_surfaces"):
        for spec in components.get(key,{}).values():
            material=materials.get(spec.get("material"),spec.get("name") or spec.get("material") or "材料")
            grade=str(spec.get("grade") or "")
            text=(grade+material if spec.get("material") in ("mortar","concrete","steel") else material+(f"（{grade}）" if grade else ""))
            thickness=spec.get("thickness_m")
            if isinstance(thickness,(int,float)) and thickness>0 and f"{thickness*1000:g}mm" not in grade:
                text+=f" t={thickness:.3f}m" if thickness>=.01 else f" t={thickness*1000:g}mm"
            if text not in parameters:parameters.append(text)
    if parameters:lines.append("；".join(parameters))
    if not detail:
        if _is_layered(section):
            thickness=(section.get("geology") or {}).get("thickness")
            lines.append(f"假定分界：地表下{float(thickness):.3f}m" if isinstance(thickness,(float,int)) else "假定分界：地表竖直偏移")
        elif layered_volume_columns(payload):
            lines.append("未分层")
        slope_notes=[]
        if _is_layered(section):
            slopes=(section.get("geology") or {}).get("slopes") or {}
            for role,label in (("overburden","覆盖层"),("bedrock","基岩")):
                values=[f"{side}1:{value:g}" for side,key in (("左","left"),("右","right"))
                        if isinstance(value:=slopes.get(role,{}).get(key,construction.get(role+'_slope_'+key)),(int,float))]
                if values:slope_notes.append(label+"挖坡 "+" ".join(values))
        else:
            for key,label in (("excavation_slope_","挖坡"),("bank_slope_","填坡")):
                values=[f"{side}1:{value:g}" for side,suffix in (("左","left"),("右","right"))
                        if isinstance(value:=construction.get(key+suffix),(int,float))]
                if values:slope_notes.append(label+" "+" ".join(values))
        if slope_notes:lines.append("；".join(slope_notes))
    if pipes:
        for index,pipe in enumerate(pipes,1):
            material=pipe.get("material") or definition.get("material") or ""
            material={"ductile_iron":"球墨铸铁","di":"球墨铸铁","steel":"钢材","concrete":"混凝土","other":"其他"}.get(material,material)
            grade=pipe.get("material_grade") or definition.get("material_grade") or ""
            prefix=f"管{index} {material}{grade}"
            nominal=pipe.get("nominal_diameter_m",definition.get("nominal_diameter_m"))
            if isinstance(nominal,(int,float)):prefix+=f" DN{nominal*1000:g}"
            if pipe.get("earthwork_envelope_only",definition.get("earthwork_envelope_only")):
                lines.append(f"{prefix}：施工外径{pipe['outer_diameter']:.3f}m；轴▽{pipe['axis_elevation']:.3f}；仅外包络，管壁及内衬未计")
            else:
                lines.append(f"{prefix}：外径{pipe['outer_diameter']:.3f}m；内径{pipe['inner_diameter']:.3f}m；壁厚{pipe['wall_thickness']:.3f}m；轴▽{pipe['axis_elevation']:.3f}")
    elif envelope_only:
        lines.append("仅外包络，管壁及内衬未计")
    seat=construction.get("pipe_seat") or construction.get("pipe_support") or {}
    if seat.get("enabled",True) and seat.get("material_role")=="bedding":
        angle=float(seat.get("support_angle",seat.get("angle",120.)))
        base=float(seat.get("base_thickness",0.))
        note=f"包角垫层{angle:g}°；管底下厚{base:.3f}m"
        if seat.get("bottom_width_mode")=="support_chord":
            note+="；侧边竖直"
        elif seat.get("bottom_width_mode")=="trench_bottom":
            left=construction.get("working_space_left");right=construction.get("working_space_right")
            if pipes and isinstance(left,(int,float)) and isinstance(right,(int,float)):
                width=(max(float(p.get("offset",0))+float(p["outer_diameter"])/2 for p in pipes)
                    -min(float(p.get("offset",0))-float(p["outer_diameter"])/2 for p in pipes)+left+right)
                note+=f"；槽底宽{width:.3f}m"
            note+="；侧边沿挖坡" if seat.get("side_boundary_mode","excavation")=="excavation" else "；侧边竖直"
        if construction.get("working_space_reference")=="pipe_outer":
            left=construction.get("working_space_left");right=construction.get("working_space_right")
            if isinstance(left,(int,float)) and isinstance(right,(int,float)):
                note+=f"；管外工作面左{left:.3f}/右{right:.3f}m"
        lines.append(note)
    if special_material_scope_note(payload):
        lines.append("土方依据断面；长度材料另见特殊材料清单")
    return title,lines


def _normal_pipe_detail(section):
    """Per-pipe normal disks with true dimensions and saved absolute axis Z.

    Drawing Y is each pipe's binormal coordinate placed at its axis label.
    It does not represent absolute top/bottom Z or a common physical plane.
    Foundations retain their real construction-cut view elsewhere.
    """
    from shapely.geometry import Point
    from shapely.ops import unary_union
    from shapely.geometry import mapping
    structure=section.get("structure_geometry",{});pipes=structure.get("pipes",[])
    centers=structure.get("pipe_centers",[])
    if not pipes or len(pipes)!=len(centers):return None
    outers=[];voids=[];materials={"concrete":[],"pipe_wall":[],"lining":[]};saved_pipes=[]
    for pipe,center in zip(pipes,centers):
        ro=float(pipe["outer_diameter"])/2;ri=float(pipe["inner_diameter"])/2
        wall_inner=ro-float(pipe["wall_thickness"])
        circle=lambda radius:Point(float(center[0]),float(center[1])).buffer(radius,quad_segs=32)
        outer,void,inner_wall=circle(ro),circle(ri),circle(wall_inner)
        outers.append(outer);voids.append(void)
        materials["concrete" if pipe.get("material_category")=="concrete" else "pipe_wall"].append(outer.difference(inner_wall))
        if pipe.get("lining_thickness",0):
            materials["concrete" if pipe.get("lining_material_category")=="concrete" else "lining"].append(inner_wall.difference(void))
        saved_pipes.append({key:pipe[key] for key in ("outer_diameter","inner_diameter","wall_thickness","offset","material_category","material","earthwork_envelope_only") if key in pipe})
        saved_pipes[-1]["axis_elevation"]=float(center[1])
    detail=dict(section);detail.update(roles={},construction_geometry={},ground_points=[],domain=None,normal_pipe_detail=True)
    detail["structure_geometry"]={"outer":mapping(unary_union(outers)),"net_void":mapping(unary_union(voids)),
        "materials":{key:mapping(unary_union(values)) for key,values in materials.items()},
        "pipes":saved_pipes,"pipe_centers":[list(map(float,center)) for center in centers]}
    if any(p.get("earthwork_envelope_only") for p in pipes):
        from shapely.geometry import Polygon
        detail["structure_geometry"]["net_void"]=mapping(Polygon())
    return detail


def _create_sheet(doc,name,pw,ph,title,payload):
    layout=doc.layouts.new(name);layout.page_setup(size=(pw,ph),margins=(10,10,10,10),units="mm")
    # AutoCAD requires the overall paperspace viewport to remain on layer 0.
    for viewport in layout.query("VIEWPORT"):
        if viewport.dxf.id==1:viewport.dxf.layer="0"
    layout.add_lwpolyline([(10,10),(pw-10,10),(pw-10,ph-10),(10,ph-10)],close=True,dxfattribs={"layer":"图框"})
    if payload.get("calculation_deferred_assets"):title+="（部分计量）"
    _paper_text(layout,title+(" TEST" if payload.get("test_only") else ""),(15,ph-13),pw-30,3.5)
    footer_text="单位：m"
    if not payload.get("_concise_drawing"):
        if payload.get("quantity_scope_issues"):footer_text+="；未计项见量表"
        if special_material_scope_note(payload):footer_text+="；土方沿用原依据，长度材料另列"
        if _has_curve_sampling(payload):footer_text+="；"+section_sampling_note(payload)
    footer=_paper_text(layout,footer_text,(15,17),pw-30)
    if "QX_DRAWING_META" not in doc.appids:doc.appids.new("QX_DRAWING_META")
    accuracy=(payload.get("inputs") or {}).get("accuracy",{})
    metadata=[(1000,"input_hash="+str(payload.get("input_hash",""))),
        (1000,"overlap_policy="+str(accuracy.get("overlap_policy",""))),
        (1000,"sampling_mode="+str((payload.get("validation") or {}).get("sampling_mode",accuracy.get("sampling_mode","")))),
        (1000,"calculation_contract="+str(payload.get("calculation_contract","")))]
    validation=payload.get("validation") or {};inputs=payload.get("inputs") or {}
    contract=validation.get("fixed_sampling_contract",inputs.get("fixed_sampling_contract"))
    if contract:metadata.append((1000,"fixed_sampling_contract="+str(contract)))
    if _has_curve_sampling(payload):
        metadata.append((1000,"sampling_policy=route_grid_with_curve_sections"))
        for key,value in (validation.get("curve_sampling") or {}).items():
            if isinstance(value,(bool,int,float)):metadata.append((1000,"curve_sampling."+key+"="+str(value)))
    if isinstance(accuracy.get("profile_step"),(int,float)):metadata.append((1040,float(accuracy["profile_step"])))
    footer.set_xdata("QX_DRAWING_META",metadata)
    return layout


def _excluded_description(item):
    original=item.get("original_asset_snapshot") or {}
    start=item.get("station_start",original.get("station_start"));end=item.get("station_end",original.get("station_end"))
    span=f"{start:.3f}～{end:.3f}m" if start is not None and end is not None else ""
    return f"{item.get('name',original.get('name',item.get('asset_id','')))} {span}：{item.get('reason',item.get('code',''))}"


def _excluded_scope_sheets(doc,payload,pw,ph):
    """Keep construction spans outside the open-cut scope visible in the DXF."""
    rows=payload.get("excluded_assets",[])
    if not rows:return []
    bore_quantities={(r.get("route_id"),r.get("asset_id"),r.get("station_start"),r.get("station_end")):
                     r.get("trenchless_excavation_volume") for r in payload.get("trenchless_excavation_rows",[])}
    pages=[];layout=None;y=0.;expected=[]
    paragraphs=[]
    for i,item in enumerate(rows,1):
        original=item.get("original_asset_snapshot") or {}
        start=item.get("station_start",original.get("station_start"));end=item.get("station_end",original.get("station_end"))
        span=f"{start:.3f}～{end:.3f}m" if start is not None and end is not None else ""
        method=item.get("construction_method","")
        bore=bore_quantities.get((item.get("route_id"),item.get("asset_id"),start,end))
        status=f"洞挖 {bore:.3f}m³，明挖及回填未计" if bore is not None else "未计挖填"
        if item.get("scope_status")=="automatic_deferred":
            status += "，"+item.get("reason", "")
        paragraphs.append(f"{i}. {item.get('name',original.get('name',item.get('asset_id','')))} {span} {method}：{status}")
    for paragraph in paragraphs:
        for line in _wrapped(paragraph,pw-40,2.5):
            if layout is None or y<27.:
                title="非明挖区段及未计对象" if payload.get("trenchless_excavation_volume") is not None else "未计区段"
                layout=_create_sheet(doc,f"计量范围{len(pages)+1:03d}",pw,ph,title,payload)
                pages.append(layout.name);y=ph-27.
            entity=_paper_text(layout,line,(20.,y),pw-40,2.5)
            expected.append((entity.dxf.handle,entity.plain_text()));y-=4.2
        y-=3.
    return {"layouts":pages,"excluded_count":len(rows),"texts":expected}


def _supplementary_quantity_sheets(doc,payload,pw,ph):
    """Preserve full adopted evidence without adding text-only drawing sheets."""
    items=[r for r in payload.get("quantity_items",[]) if r.get("support_row_id")]
    tables=_supplementary_export_tables(payload)
    if not items and not tables:return {}
    content={"schema":"qx.dxf.supplementary_quantities.1",
        "tables":[{"title":title,"headers":headers,"records":rows} for title,headers,rows in tables],
        "support_quantity_items":items}
    if special_material_scope_note(payload):
        content["special_pipe_materials"]=deepcopy(payload.get("special_pipe_materials") or {})
        content["special_pipe_material_items"]=deepcopy(payload.get("special_pipe_material_items") or [])
        content["special_pipe_material_sections"]=deepcopy(payload.get("special_pipe_material_sections") or [])
    return {"layouts":[],"support_quantity_count":len(items),"texts":[],
            **_store_hidden_evidence(doc,"SUPPLEMENTARY_QUANTITIES",content)}


def _store_hidden_evidence(doc,record_name,content):
    encoded=json.dumps(content,ensure_ascii=False,sort_keys=True,separators=(",",":"))
    # GeoJSON from Shapely contains tuples; the persisted JSON representation
    # deliberately uses arrays. Compare readback to that canonical value.
    content=json.loads(encoded)
    dictionary_name="QX_SECTION_EVIDENCE"
    dictionary=doc.rootdict.get_required_dict(dictionary_name)
    record=dictionary.add_xrecord(record_name)
    # XRECORD has no XDATA 16 KB limit. Each group-code-1 value stays below
    # 255 bytes even when every Unicode code point needs four UTF-8 bytes.
    chunks=[encoded[index:index+60] for index in range(0,len(encoded),60)]
    record.reset((1,chunk) for chunk in chunks)
    return {"hidden_record_path":[dictionary_name,record_name],"hidden_record_handle":record.dxf.handle,
        "hidden_records":content,"hidden_records_sha256":hashlib.sha256(encoded.encode("utf8")).hexdigest(),
        "hidden_record_chunk_count":len(chunks)}


def _verify_supplementary_hidden_records(doc,audit):
    try:
        dictionary_name,record_name=audit["hidden_record_path"]
        record=doc.rootdict[dictionary_name][record_name]
    except KeyError as error:
        raise ValueError("DXF附属计量隐藏记录保存回读丢失") from error
    if record.dxftype()!="XRECORD" or record.dxf.handle!=audit["hidden_record_handle"]:
        raise ValueError("DXF附属计量隐藏记录身份改变")
    if len(record.tags)!=audit["hidden_record_chunk_count"] or any(tag.code!=1 for tag in record.tags):
        raise ValueError("DXF附属计量隐藏记录字段改变")
    encoded="".join(tag.value for tag in record.tags)
    if (hashlib.sha256(encoded.encode("utf8")).hexdigest()!=audit["hidden_records_sha256"]
            or json.loads(encoded)!=audit["hidden_records"]):
        raise ValueError("DXF附属计量隐藏记录保存回读改变")
    audit["saved_hidden_records_exact"]=True


def _scale_for(bounds,width,height):
    required=max((bounds[2]-bounds[0])*1000/max(10.,width-4),(bounds[3]-bounds[1])*1000/max(10.,height-4))
    return next((r for r in (50,100,200,250,500,1000,2000,5000,10000,20000,50000,100000) if r>=required),math.ceil(required/10000)*10000)


def _drawing_foundation_members(payload,asset):
    members={member["component_id"]:member for member in asset.get("section",{}).get("discrete_components",[])
        if member.get("excavate") and (member.get("scope_category")=="foundation" or member.get("generated_aqueduct_foundation_member"))}
    for pit in _workbench_input(payload).get("pits",[]):
        if (pit.get("generated_aqueduct_foundation")
                and pit.get("parent_asset_id") in {asset.get("asset_id"),asset.get("original_asset_id")}):
            member=pit.get("source_component") or {}
            if member.get("component_id"):members.setdefault(member["component_id"],member)
    return list(members.values())


def _with_display_foundations(section,asset,payload):
    """Restore separately counted footings only on actual source-station cuts."""
    if section.get("coordinate_kind")=="pit_local_slice":return section
    station=section.get("station")
    if not isinstance(station,(int,float)):return section
    from ..services.dedicated_structure_geometry import _active_member
    from shapely.geometry import box,mapping
    from shapely.ops import unary_union
    active=[member for member in _drawing_foundation_members(payload,asset)
        if _active_member(member,float(station),section.get("side","right"))]
    if not active:return section
    result=deepcopy(section);structure=result.setdefault("structure_geometry",{})
    regions=structure.setdefault("component_regions",{});footings=[]
    for member in active:
        offset=float(member.get("offset",0.));half=float(member["width"])/2
        footing=box(offset-half,float(member["bottom_elevation"]),offset+half,float(member["top_elevation"]))
        regions[member["component_id"]]={**deepcopy(member),"geometry":mapping(footing),"display_only":True,
            "quantity_status":"counted_separately_in_foundation_pit"}
        footings.append(footing)
    structure["outer"]=mapping(unary_union([*polygons(structure.get("outer")),*footings]))
    result["display_foundation_component_ids"]=[member["component_id"] for member in active]
    return result


def _complete_frame_details(asset,sample,payload):
    """Each saved frame gets its actual column-and-footing parameter section."""
    members=asset.get("section",{}).get("discrete_components",[])
    foundations=_drawing_foundation_members(payload,asset)
    if not foundations:return []
    stations=sorted({float(member["frame_station"]) for member in members
        if member.get("generated_aqueduct_frame") and member.get("frame_station") is not None})
    if not stations:return []
    from ..services.design_profiles import normalize_design_profile,evaluate_profile
    from ..services.section_geometry import section_structure,structure_mapping
    profile=normalize_design_profile(asset);source=deepcopy(asset)
    existing={member["component_id"] for member in source["section"].get("discrete_components",[])}
    source["section"].setdefault("discrete_components",[]).extend(deepcopy(member) for member in foundations if member["component_id"] not in existing)
    details=[]
    for station in stations:
        elevation,slope=evaluate_profile(profile,station)
        structure=section_structure(source,elevation=elevation,slope=slope,station=station,side="right",arc_segments=128)
        region=structure.get("component_regions",{})
        foundation_ids=[key for key,spec in region.items() if spec.get("excavate") and not spec["geometry"].is_empty]
        if not foundation_ids:continue
        detail=deepcopy(sample)
        detail.update(section_id=f"{asset['asset_id']}:frame:{station:.12g}",station=station,design_elevation=elevation,
            roles={},construction_geometry={},ground_points=[],domain=None,frame_complete_detail=True,
            structure_geometry=structure_mapping(structure),display_foundation_component_ids=foundation_ids,
            quantity_status="display_only_not_added_to_totals")
        details.append(detail)
    return details


def _geometry_model(model,section,x,view_id,ratio,*,detail=False,concise=False,members=None,bounds=None):
    left,right,bottom,top=bounds or section_limits(section)
    ox=x-left+2.;oy=2.-bottom
    transform=lambda u,z:(float(u)+ox,float(z)+oy)
    made=[];holes=0
    for role,poly,fill in geometry_items(section):
        for ring in (poly.exterior,*poly.interiors):
            made.append(_view_tag(_ring(model,ring,role,transform,section["section_id"]),view_id))
        if fill:
            hatch = _hatch(model,poly,role,transform,section["section_id"],ratio)
            made.append(_view_tag(hatch,view_id))
            if role in ("concrete","bedding","pipe_wall","lining") or role.startswith("component_"):holes+=len(poly.interiors)
    for role,line in component_lines(section):
        _ensure_material_layer(model,role)
        made.append(_view_tag(_tag(model.add_lwpolyline([transform(*point) for point in line],dxfattribs={"layer":NAMES[role],"lineweight":35}),section["section_id"]),view_id))
    if not detail:
        for part in ground_parts(section):
            from shapely.geometry import LineString,box
            clipped=LineString(part).intersection(box(left,bottom-1,right,top+1))
            for line in ([clipped] if clipped.geom_type=="LineString" else getattr(clipped,"geoms",())):
                if line.geom_type=="LineString" and line.length>1e-9:
                    made.append(_view_tag(_tag(model.add_lwpolyline([transform(*v) for v in line.coords],dxfattribs={"layer":"原地面"}),section["section_id"]),view_id))
        for part in interface_parts(section):
            from shapely.geometry import LineString,box
            clipped=LineString(part).intersection(box(left,bottom-1,right,top+1))
            for line in ([clipped] if clipped.geom_type=="LineString" else getattr(clipped,"geoms",())):
                if line.geom_type=="LineString" and line.length>1e-9:
                    made.append(_view_tag(_tag(model.add_lwpolyline([transform(*v) for v in line.coords],dxfattribs={"layer":NAMES["interface"],"lineweight":35}),section["section_id"]),view_id))
        for line in construction_lines(section,(left,right,bottom,top)):
            entity = _add_section_polyline(model,line+(ox,oy),dxfattribs={"layer":"施工边界"})
            made.append(_view_tag(_tag(entity,section["section_id"]),view_id))
        txt=2.5*ratio/1000
        # Keep every grade readable in separate annotation rows. The leader
        # points to the genuine saved edge; it never adds a soil boundary.
        labels=[] if concise else sorted(_construction_labels(section,(left,right,bottom,top)),key=lambda item:(item[0][0],item[0][1]))
        left_height=right_height=top+2*txt
        for point,label,_ in labels:
            on_left=point[0]<0
            height=left_height if on_left else right_height
            if on_left:left_height+=2.2*txt
            else:right_height+=2.2*txt
            text_width=max(3.,_text_units(label))*txt
            label_x=left-text_width if on_left else right+txt
            end=transform(label_x+text_width if on_left else label_x,height)
            made.append(_view_tag(_tag(model.add_lwpolyline([transform(*point),end],dxfattribs={"layer":"标注"}),section["section_id"]),view_id))
            made.append(_view_tag(_tag(model.add_text(label,dxfattribs={"height":txt,"style":"中文","layer":"标注","insert":transform(label_x,height)}),section["section_id"]),view_id))
    elif section.get("normal_pipe_detail"):
        txt=2.5*ratio/1000;structure=section["structure_geometry"]
        right=max(p.bounds[2] for p in polygons(structure["outer"]))
        label_height=-math.inf
        for index,(pipe,center) in enumerate(zip(structure["pipes"],structure["pipe_centers"]),1):
            u,z=map(float,center);ro=pipe["outer_diameter"]/2;ri=pipe["inner_diameter"]/2
            dimensions=((ro,5*txt),) if pipe.get("earthwork_envelope_only") else ((ro,5*txt),(ri,2*txt))
            for radius,gap in dimensions:
                dim=model.add_linear_dim(base=transform(u-radius,z-ro-gap),p1=transform(u-radius,z),p2=transform(u+radius,z),
                    override={"dimtxt":txt,"dimasz":txt*.8,"dimexe":txt*.3,"dimexo":txt*.25,"dimgap":txt*.35,
                        "dimdec":3,"dimdsep":ord('.'),"dimtad":1,"dimclrd":7,"dimclrt":7,"dimtxsty":"中文","dimpost":"<>m"},dxfattribs={"layer":"标注"})
                dim.render();made.append(_view_tag(_tag(dim.dimension,section["section_id"]),view_id))
            label_height=max(z,label_height+1.8*txt)
            end=transform(right+5*txt,label_height)
            made.append(_view_tag(_tag(model.add_lwpolyline([transform(u,z),end],dxfattribs={"layer":"标注"}),section["section_id"]),view_id))
            made.append(_view_tag(_tag(model.add_text(f"管{index}轴▽{pipe['axis_elevation']:.3f}",dxfattribs={"height":txt,"style":"中文","layer":"标注","insert":end}),section["section_id"]),view_id))
    elif not section.get("frame_complete_detail"):
        txt=2.5*ratio/1000
        voids=polygons(section.get("structure_geometry",{}).get("net_void"))
        outside=polygons(section.get("structure_geometry",{}).get("outer"))
        if outside:
            l=min(p.bounds[0] for p in outside);r=max(p.bounds[2] for p in outside);b=min(p.bounds[1] for p in outside);t=max(p.bounds[3] for p in outside)
            components=[(spec,parts) for spec in section.get("structure_geometry",{}).get("component_regions",{}).values()
                        if (parts:=polygons(spec.get("geometry")))] if section.get("material_standard_detail") else []
            dim_floor=min([b,*[p.bounds[1] for _,parts in components for p in parts]])
            dimensions=[(transform(l,b),transform(r,b),transform(l,dim_floor-8*txt),0),(transform(l,b),transform(l,t),transform(l-8*txt,b),90)]
            if voids:
                v=min(voids,key=lambda p:abs(p.centroid.x));vl,vb,vr,vt=v.bounds
                dimensions.extend([(transform(vl,vb),transform(vr,vb),transform(vl,dim_floor-4*txt),0),(transform(vl,vb),transform(vl,vt),transform(l-4*txt,vb),90)])
            for first,last,base,angle in dimensions:
                dim=model.add_linear_dim(base=base,p1=first,p2=last,angle=angle,override={"dimtxt":txt,"dimasz":txt*.8,"dimexe":txt*.3,"dimexo":txt*.25,"dimgap":txt*.35,"dimdec":3,"dimdsep":ord('.'),"dimtad":1,"dimclrd":7,"dimclrt":7,"dimtxsty":"中文","dimpost":"<>m"},dxfattribs={"layer":"标注"})
                dim.render();made.append(_view_tag(_tag(dim.dimension,section["section_id"]),view_id))
            component_right=max([r,*[p.bounds[2] for _,parts in components for p in parts]])
            for index,(_spec,parts) in enumerate(components):
                pl=min(p.bounds[0] for p in parts);pr=max(p.bounds[2] for p in parts)
                low=min(p.bounds[1] for p in parts);high=max(p.bounds[3] for p in parts)
                for first,last,base,angle,label in ((transform(pl,low),transform(pr,low),transform(pl,dim_floor-(12+4*index)*txt),0,"宽"),
                        (transform(pr,low),transform(pr,high),transform(component_right+(3+4*index)*txt,low),90,"高")):
                    dim=model.add_linear_dim(base=base,p1=first,p2=last,angle=angle,
                        override={"dimtxt":txt,"dimasz":txt*.8,"dimexe":txt*.3,"dimexo":txt*.25,"dimgap":txt*.35,
                            "dimdec":3,"dimdsep":ord('.'),"dimtad":1,"dimclrd":7,"dimclrt":7,"dimtxsty":"中文","dimpost":label+"<>m"},
                        dxfattribs={"layer":"标注"})
                    dim.render();made.append(_view_tag(_tag(dim.dimension,section["section_id"]),view_id))
            marked=[] if section.get("material_standard_detail") else [("外顶",t),("外底",b)]
            if voids and not section.get("material_standard_detail"):marked.append(("净空顶",max(p.bounds[3] for p in voids)))
            last_label=-math.inf
            for name,height in sorted(marked,key=lambda v:v[1]):
                label_height=max(height,last_label+1.8*txt);last_label=label_height
                start=transform(r,height);end=transform(r+5*txt,label_height)
                made.append(_view_tag(_tag(model.add_lwpolyline([start,end],dxfattribs={"layer":"标注"}),section["section_id"]),view_id))
                made.append(_view_tag(_tag(model.add_text(f"{name}▽{height:.3f}",dxfattribs={"height":txt,"style":"中文","layer":"标注","insert":end}),section["section_id"]),view_id))
    if section.get("frame_complete_detail"):
        from ezdxf.enums import TextEntityAlignment
        txt=2.5*ratio/1000
        for spec in section.get("structure_geometry",{}).get("component_regions",{}).values():
            parts=polygons(spec.get("geometry"))
            if not spec.get("excavate") or not parts:continue
            l=min(p.bounds[0] for p in parts);r=max(p.bounds[2] for p in parts)
            b=min(p.bounds[1] for p in parts);t=max(p.bounds[3] for p in parts)
            for first,last,base,angle,prefix in ((transform(l,b),transform(r,b),transform(l,b-4*txt),0,"W"),
                    (transform(r,b),transform(r,t),transform(r+3*txt,b),90,"T")):
                dim=model.add_linear_dim(base=base,p1=first,p2=last,angle=angle,
                    override={"dimtxt":txt,"dimasz":txt*.8,"dimexe":txt*.3,"dimexo":txt*.25,"dimgap":txt*.35,
                        "dimdec":3,"dimdsep":ord('.'),"dimtad":1,"dimclrd":7,"dimclrt":7,"dimtxsty":"中文","dimpost":prefix+"=<>m"},
                    dxfattribs={"layer":"标注"})
                dim.render();made.append(_view_tag(_tag(dim.dimension,section["section_id"]),view_id))
            length=float(spec["station_end"])-float(spec["station_start"])
            text=model.add_text(f"L={length:.3f}m",dxfattribs={"height":txt,"style":"中文","layer":"标注"})
            text.set_placement(transform((l+r)/2,b-7*txt),align=TextEntityAlignment.MIDDLE_CENTER)
            made.append(_view_tag(_tag(text,section["section_id"]),view_id))
    # Put the necessary column height and footing levels on the actual cut,
    # rather than generating a separate page of calculation prose.
    active_columns=[]
    for spec in section.get("structure_geometry",{}).get("component_regions",{}).values():
        proof=spec.get("frame_height_basis") or {}
        if not spec.get("generated_aqueduct_frame") or proof.get("foundation_mode")!="weathering":continue
        parts=polygons(spec.get("geometry"))
        if parts:active_columns.append((spec,proof,parts))
    if active_columns and not concise:
        from ezdxf.enums import TextEntityAlignment
        txt=2.5*ratio/1000
        group_left=min(p.bounds[0] for _,_,parts in active_columns for p in parts)
        group_right=max(p.bounds[2] for _,_,parts in active_columns for p in parts)
        group_center=(group_left+group_right)/2;lanes={-1:0,1:0}
        for spec,proof,parts in sorted(active_columns,key=lambda item:abs(float(item[0].get("offset",0))),reverse=True):
            pl=min(p.bounds[0] for p in parts);pr=max(p.bounds[2] for p in parts)
            low=min(p.bounds[1] for p in parts);high=max(p.bounds[3] for p in parts)
            side=-1 if (pl+pr)/2<group_center else 1
            edge=pl if side<0 else pr
            lane=(group_left if side<0 else group_right)+side*(4+lanes[side]*7)*txt
            lanes[side]+=1
            dim=model.add_linear_dim(base=transform(lane,low),p1=transform(edge,low),p2=transform(edge,high),angle=90,
                override={"dimtxt":txt,"dimasz":txt*.8,"dimexe":txt*.3,"dimexo":txt*.25,"dimgap":txt*.35,
                    "dimdec":3,"dimdsep":ord('.'),"dimtad":1,"dimclrd":7,"dimclrt":7,"dimtxsty":"中文","dimpost":"H=<>m"},
                dxfattribs={"layer":"标注"})
            dim.render();made.append(_view_tag(_tag(dim.dimension,section["section_id"]),view_id))
            prior=math.inf
            for label,key in (("基顶","foundation_top_elevation"),("基底","foundation_bottom_elevation")):
                z=proof.get(key)
                if not isinstance(z,(int,float)) or not math.isfinite(z):continue
                label_z=min(float(z),prior-1.8*txt);prior=label_z
                end=transform(lane+side*2*txt,label_z)
                line=model.add_lwpolyline([transform(edge,z),end],dxfattribs={"layer":"标注"})
                made.append(_view_tag(_tag(line,section["section_id"]),view_id))
                text=model.add_text(f"{label}▽{z:.3f}",dxfattribs={"height":txt,"style":"中文","layer":"标注"})
                text.set_placement(end,align=TextEntityAlignment.MIDDLE_RIGHT if side<0 else TextEntityAlignment.MIDDLE_LEFT)
                made.append(_view_tag(_tag(text,section["section_id"]),view_id))
    if members is not None:members.extend(made)
    return _section_entity_bounds(made),holes,[ox,oy]


def _caption_rows(caption,width):
    title,notes=caption
    rows=_wrapped(title,width-8,3.)
    note_rows=[line for text in notes for line in _wrapped(text,width-8,2.5)]
    return rows,note_rows,5.2*len(rows)+4.3*len(note_rows)+3


def _paper_cell(layout,view,rectangle,caption,ratio,viewport_audit,*,tile=None,reserved_caption_h=0,tight=False):
    x,y,w,h=rectangle
    rows,note_rows,caption_h=_caption_rows(caption,w)
    caption_h=max(reserved_caption_h,caption_h)
    top=y+h-3
    _paper_text(layout,"\n".join(rows),(x+4,top),w-8,3.)
    if note_rows:_paper_text(layout,"\n".join(note_rows),(x+4,top-5.2*len(rows)-1),w-8,2.5)
    plot_w=w-8;plot_h=h-caption_h-6
    bounds=view["bounds"];cx=(bounds[0]+bounds[2])/2;cy=(bounds[1]+bounds[3])/2
    if tight:
        plot_w=min(plot_w,(bounds[2]-bounds[0])*1000/ratio+4)
        plot_h=min(plot_h,(bounds[3]-bounds[1])*1000/ratio+4)
    if plot_h<(4.-1e-8 if tight else 12.):raise ValueError("题签过长，当前图幅无法保持2.5mm文字；请选择A1图幅或精简显示名称")
    if tile:cx,cy=tile
    vp=layout.add_viewport(center=(x+w/2,y+3+plot_h/2),size=(plot_w,plot_h),view_center_point=(cx,cy),view_height=plot_h*ratio/1000)
    vp.dxf.flags=int(vp.dxf.flags)|16384
    _view_tag(vp,view["view_id"])
    viewport_audit.append({"layout":layout.name,"handle":vp.dxf.handle,"view_id":view["view_id"],"section_id":view["section_id"],"scale":ratio,"paper_size_mm":[plot_w,plot_h],"paper_cell_bounds_mm":[x,y,x+w,y+h],"view_height_m":plot_h*ratio/1000,"model_view_center":[cx,cy],"model_visible_bounds":[cx-plot_w*ratio/2000,cy-plot_h*ratio/2000,cx+plot_w*ratio/2000,cy+plot_h*ratio/2000]})
    return plot_w,plot_h


def _full_view_tiles(doc,view,caption,pw,ph,payload,ratio,prefix,page,viewports):
    width,height=pw-30,ph-40;title,notes=caption
    # Reserve the same caption height on every tile; otherwise wrapping a
    # tile number could reduce one viewport and leave an uncovered source band.
    reserve=5.2*len(_wrapped(title+" / 分幅999999/999999",width-8,3.))+4.3*sum(len(_wrapped(n,width-8,2.5)) for n in notes)+3
    plot_w,plot_h=width-8,height-reserve-6
    if plot_h<12:raise ValueError("题签过长，请选择A1图幅或缩短显示名称")
    mw,mh=plot_w*ratio/1000,plot_h*ratio/1000;actual=view["bounds"]
    nx=max(1,math.ceil((actual[2]-actual[0])/mw));ny=max(1,math.ceil((actual[3]-actual[1])/mh))
    for iy in range(ny):
        for ix in range(nx):
            page+=1;layout=_create_sheet(doc,f"{prefix}{page:03d}",pw,ph,prefix+" / 等比例分幅",payload)
            tile=(actual[0]+(ix+.5)*mw,actual[1]+(iy+.5)*mh) if nx*ny>1 else None
            _paper_cell(layout,view,(15,20,width,height),(title+f" / 分幅{iy*nx+ix+1}/{nx*ny}",notes),ratio,viewports,tile=tile,reserved_caption_h=reserve)
    return page


def _overview_section_sheet(doc,model,payload,selected,rows,assets,scale):
    """One editable, ten-column section board in one shared model viewport."""
    columns=min(10,len(selected));cell_w=70.;gap=2.
    # A shared viewport needs a shared physical scale, including automatic mode.
    prepared=[]
    for section in selected:
        asset=assets.get(section["asset_id"],{})
        section=_with_display_foundations(section,asset,payload)
        prepared.append((section,section_limits(section)))
    ratio=float(scale) if scale else max(_scale_for([b[0],b[2],b[1],b[3]],cell_w-8,40.) for _,b in prepared)
    factor=ratio/1000
    entries=[];holes=0
    for section,b in prepared:
        members=[];vid=str(section["section_id"])+":cross"
        actual,count,offset=_geometry_model(model,section,0.,vid,ratio,concise=True,members=members,bounds=b)
        holes+=count;cell_w=max(cell_w,(actual[2]-actual[0])/factor+8)
        asset=assets.get(section["asset_id"],{})
        view={"section_id":str(section["section_id"]),"view_id":vid,"asset_id":section["asset_id"],
            "station":section["station"],"scale":ratio,"bounds":actual,
            "source_bounds":[b[0],b[2],b[1],b[3]],"model_offset":offset,
            "display_foundation_component_ids":section.get("display_foundation_component_ids",[]),
            "quantity_status":"saved_section_quantities_unchanged"}
        entries.append({"section":section,"view":view,"members":members,
            "caption":_caption(section,payload,rows.get(section["asset_id"],{}),asset,ratio)})
    # Keep each route in its original order, and show its sections by station.
    route_order={}
    for asset in assets.values():
        route=str(asset.get("route_id",""))
        if route not in route_order:route_order[route]=len(route_order)
    def order(entry):
        section=entry["section"];asset=assets.get(section["asset_id"],{})
        route=str(asset.get("route_id",section.get("route_id","")))
        if route not in route_order:route_order[route]=len(route_order)
        return route_order[route],float(section["station"]),str(section.get("side",""))
    entries.sort(key=order)
    y=0.
    for start in range(0,len(entries),columns):
        row_entries=entries[start:start+columns]
        for entry in row_entries:
            title_rows,note_rows,cap_h=_caption_rows(entry["caption"],cell_w)
            entry.update(title_rows=title_rows,note_rows=note_rows,caption_h=cap_h)
        plot_h=max((e["view"]["bounds"][3]-e["view"]["bounds"][1])/factor for e in row_entries)
        cap_h=max(e["caption_h"] for e in row_entries)
        row_h=cap_h+plot_h+10.
        for column,entry in enumerate(row_entries):
            view=entry["view"];section=entry["section"];members=entry["members"]
            x=column*(cell_w+gap);b=view["bounds"]
            # Align drawing centres within columns and their bottoms within rows.
            dx=(x+cell_w/2)*factor-(b[0]+b[2])/2
            dy=(-y-row_h+3)*factor-b[1]
            _translate_section_members(members, dx, dy)
            view["geometry_bounds"]=[b[0]+dx,b[1]+dy,b[2]+dx,b[3]+dy]
            view["model_offset"]=[view["model_offset"][0]+dx,view["model_offset"][1]+dy]
            title=_paper_text(model,"\n".join(entry["title_rows"]),((x+4)*factor,(-y-3)*factor),(cell_w-8)*factor,3.*factor)
            members.append(_view_tag(_tag(title,section["section_id"]),view["view_id"]))
            if entry["note_rows"]:
                notes=_paper_text(model,"\n".join(entry["note_rows"]),((x+4)*factor,(-y-3-5.2*len(entry["title_rows"])-1)*factor),(cell_w-8)*factor,2.5*factor)
                members.append(_view_tag(_tag(notes,section["section_id"]),view["view_id"]))
            view["bounds"]=_section_entity_bounds(members)
            view["row_index"]=start//columns;view["column_index"]=column
            view["model_cell_bounds"]=[x*factor,(-y-row_h)*factor,(x+cell_w)*factor,-y*factor]
        y+=row_h+gap
    plot_w=columns*cell_w+(columns-1)*gap
    plot_h=y-gap
    pw,ph=plot_w+30.,plot_h+40.
    layout=_create_sheet(doc,"横断面001",pw,ph,"土石方施工横断面",payload)
    cx,cy=plot_w*factor/2,-plot_h*factor/2
    vp=layout.add_viewport(center=(15+plot_w/2,20+plot_h/2),size=(plot_w,plot_h),view_center_point=(cx,cy),view_height=plot_h*factor)
    vp.dxf.flags=int(vp.dxf.flags)|16384
    _view_tag(vp,"cross_sections:overview")
    views=[e["view"] for e in entries]
    record={"layout":layout.name,"handle":vp.dxf.handle,"view_id":"cross_sections:overview",
        "section_id":"overview","expected_view_ids":[v["view_id"] for v in views],"scale":ratio,
        "paper_size_mm":[plot_w,plot_h],"view_height_m":plot_h*factor,"model_view_center":[cx,cy],
        "model_visible_bounds":[0.,-plot_h*factor,plot_w*factor,0.]}
    return views,[record],holes,plot_w*factor,{"strategy":"single_overview_10_columns","columns":10,
        "used_columns":columns,"rows":math.ceil(len(views)/10),"section_count":len(views),
        "cross_section_layout_count":1,"viewport_count":1,"custom_paper_size_mm":[pw,ph],
        "paper_cell_gap_mm":gap,"cell_width_mm":cell_w}


def _compact_section_sheets(doc,model,payload,selected,rows,assets,pw,ph,scale):
    """Pack complete section drawings and their captions at the chosen scale.

    Paper cells follow station order. Model groups use a separate two-dimensional
    shelf containing each *visible viewport*, so tight spacing cannot admit a
    neighbouring section, including the blank part of an oversized section tile.
    """
    width,height=pw-30,ph-40
    entries=[];holes=0
    for section in selected:
        row=rows.get(section["asset_id"],{});asset=assets.get(section["asset_id"],{})
        section=_with_display_foundations(section,asset,payload)
        left,right,bottom,top=section_limits(section)
        # Preserve the existing automatic scale selection. Packing changes the
        # space occupied by each drawing, never its physical ratio or quantities.
        _,_,cap_h=_caption_rows(_caption(section,payload,row,asset,50),width/2)
        ratio=float(scale) if scale else _scale_for([left,bottom,right,top],width/2-8,max(15.,height/2-cap_h-6))
        members=[];vid=str(section["section_id"])+":cross"
        actual,count,offset=_geometry_model(model,section,0.,vid,ratio,concise=True,members=members,
                                            bounds=(left,right,bottom,top))
        holes+=count
        view={"section_id":str(section["section_id"]),"view_id":vid,"asset_id":section["asset_id"],
            "station":section["station"],"scale":ratio,"bounds":actual,
            "source_bounds":[left,bottom,right,top],"model_offset":offset,
            "display_foundation_component_ids":section.get("display_foundation_component_ids",[]),
            "quantity_status":"saved_section_quantities_unchanged"}
        entries.append({"view":view,"caption":_caption(section,payload,row,asset,ratio),"members":members})

    def tile_extent(entry):
        title,notes=entry["caption"];view=entry["view"];b=view["bounds"];ratio=view["scale"]
        reserve=5.2*len(_wrapped(title+" / 分幅999999/999999",width-8,3.))+4.3*sum(len(_wrapped(n,width-8,2.5)) for n in notes)+3
        plot_h=height-reserve-6
        if plot_h<12:raise ValueError("题签过长，请选择A1图幅或缩短显示名称")
        mw,mh=(width-8)*ratio/1000,plot_h*ratio/1000
        nx=max(1,math.ceil((b[2]-b[0])/mw));ny=max(1,math.ceil((b[3]-b[1])/mh))
        if nx*ny==1:
            cx,cy=(b[0]+b[2])/2,(b[1]+b[3])/2
            return [cx-mw/2,cy-mh/2,cx+mw/2,cy+mh/2],1
        return [b[0],b[1],b[0]+nx*mw,b[1]+ny*mh],nx*ny

    def paper_plan(preferred_width):
        pages=[];cells=[];x=y=row_h=0.;occupied=0.;tile_pages=0
        for entry in entries:
            view=entry["view"];b=view["bounds"];ratio=view["scale"]
            plot_w=(b[2]-b[0])*1000/ratio+4
            plot_h=(b[3]-b[1])*1000/ratio+4
            w=min(width,max(preferred_width,plot_w+8))
            while True:
                _,_,cap_h=_caption_rows(entry["caption"],w)
                h=cap_h+plot_h+6
                if h<=height+1e-8 or w>=width:break
                w=min(width,w+10.)
            if plot_w+8>width+1e-8 or h>height+1e-8:
                if cells:pages.append(cells);cells=[]
                extent,count=tile_extent(entry)
                pages.append({"tile":entry,"extent":extent});tile_pages+=count
                x=y=row_h=0.
                continue
            if x and x+w>width+1e-8:x=0.;y+=row_h+2.;row_h=0.
            if y+h>height+1e-8:
                pages.append(cells);cells=[];x=y=row_h=0.
            cells.append((entry,(15+x,ph-20-y-h,w,h)))
            occupied+=w*h;x+=w+2.;row_h=max(row_h,h)
        if cells:pages.append(cells)
        return (sum(isinstance(page,list) for page in pages)+tile_pages,occupied),pages

    # Test several caption widths; a narrow cell saves horizontal space but can
    # need extra text rows. Choose the fewest pages, then the least occupied area.
    _,pages=min((paper_plan(w) for w in (50.,55.,60.,65.,70.,80.,90.,100.,120.,140.,160.,195.,width)),key=lambda item:item[0])
    for page in pages:
        if isinstance(page,dict):page["tile"]["model_extent"]=page["extent"]
        else:
            for entry,_ in page:
                b=entry["view"]["bounds"];pad=2.*entry["view"]["scale"]/1000
                entry["model_extent"]=[b[0]-pad,b[1]-pad,b[2]+pad,b[3]+pad]
    area=sum((e["model_extent"][2]-e["model_extent"][0])*(e["model_extent"][3]-e["model_extent"][1]) for e in entries)
    row_width=max(max(e["model_extent"][2]-e["model_extent"][0] for e in entries),math.sqrt(area*width/height))
    gap=max(.01,min(e["view"]["scale"] for e in entries)/1000)
    x=y=row_h=rightmost=0.
    for entry in entries:
        b=entry["model_extent"];w,h=b[2]-b[0],b[3]-b[1]
        if x and x+w>row_width:x=0.;y+=row_h+gap;row_h=0.
        dx,dy=x-b[0],-y-b[3]
        _translate_section_members(entry.pop("members"), dx, dy)
        view=entry["view"];old=view["bounds"]
        view["bounds"]=[old[0]+dx,old[1]+dy,old[2]+dx,old[3]+dy]
        view["model_offset"]=[view["model_offset"][0]+dx,view["model_offset"][1]+dy]
        rightmost=max(rightmost,x+w);x+=w+gap;row_h=max(row_h,h)
    viewports=[];page_number=0
    for page in pages:
        if isinstance(page,dict):
            entry=page["tile"];view=entry["view"]
            page_number=_full_view_tiles(doc,view,entry["caption"],pw,ph,payload,view["scale"],"横断面",page_number,viewports)
        else:
            page_number+=1
            layout=_create_sheet(doc,f"横断面{page_number:03d}",pw,ph,"土石方施工横断面",payload)
            for entry,rectangle in page:
                view=entry["view"]
                _paper_cell(layout,view,rectangle,entry["caption"],view["scale"],viewports,tight=True)
    return [e["view"] for e in entries],viewports,holes,rightmost,{"strategy":"compact_actual_bounds","cross_section_layout_count":page_number,"paper_cell_gap_mm":2.,"viewport_padding_mm":2.}


def _special_material_label(item):
    name=str(item.get("name") or item.get("component_id") or "材料")
    if item.get("material")=="rockfill" and name=="基础换填层":name="石渣换填"
    grade=str(item.get("grade") or "")
    return name if not grade or grade in name else grade+name


def _special_material_dxf(doc,payload,model,x,pw,ph,viewports):
    """Draw actual standard geometry, with no invented station or world location."""
    note=special_material_scope_note(payload)
    if not note:return [],0,x,{}
    block=payload.get("special_pipe_materials") or {}
    records=payload.get("special_pipe_material_sections") or []
    row_map={(str(row.get("group_id")),str(row.get("record_id"))):row for row in block.get("rows",[])}
    views=[];holes=0;page=0
    for index,record in enumerate(records,1):
        geometry=record.get("geometry") or record.get("standard_section") or {}
        if not polygons(geometry.get("outer")):continue
        row=row_map.get((str(record.get("group_id")),str(record.get("record_id"))),{})
        components=row.get("components",row.get("unit_rates",[]))
        specs={str(item.get("component_id")):item for item in components}
        regions={}
        for role in ("pipe_seat","pipe_encasement","foundation_replacement"):
            if not polygons(geometry.get(role)):continue
            spec=specs.get(role,{})
            regions[role]={"component_id":role,"name":spec.get("name") or
                {"pipe_seat":"混凝土管座","pipe_encasement":"混凝土包封","foundation_replacement":"石渣换填"}[role],
                "material":spec.get("material") or ("rockfill" if role=="foundation_replacement" else "concrete"),
                "grade":spec.get("grade"),"unit":"m3","geometry":geometry[role]}
        standard={"section_id":"length-standard:"+str(record.get("group_id"))+":"+str(record.get("record_id",index)),
            "asset_id":record.get("asset_id",row.get("asset_id")),"material_standard_detail":True,
            "structure_geometry":{"outer":geometry["outer"],"net_void":geometry.get("net_void"),
                "materials":({"bedding":geometry["bedding"]} if polygons(geometry.get("bedding")) else {}),
                "component_regions":regions},"roles":{},"ground_points":[],"construction_geometry":{}}
        bounds=section_limits(standard);title=record.get("title") or row.get("title") or row.get("scheme_title") or "特殊管段"
        length=record.get("length_m",row.get("length_m"))
        notes=[("长度 L="+format(float(length),"g")+"m；" if isinstance(length,(int,float)) else "")+"按长度计材料，未定位",
            "管轴法向典型构造；图中坐标为相对尺寸，非实际桩号或高程"]
        for item in components:
            if isinstance(item.get("rate"),(int,float)):
                unit={"m3":"m3/m","m2":"m2/m"}.get(item.get("unit"),str(item.get("unit") or "")+"/m")
                notes.append(f"{_special_material_label(item)}：{item['rate']:.6g}{unit}")
        caption=(str(title)+" / 典型构造（未定位）",notes)
        width,height=pw-30,ph-40
        caption_h=5.2*len(_wrapped(caption[0],width-8,3.))+4.3*sum(len(_wrapped(n,width-8,2.5)) for n in notes)+3.
        plot_h=max(15.,height-caption_h-6)
        required=max((bounds[1]-bounds[0])*1000/(width-8),(bounds[3]-bounds[2])*1000/plot_h)
        ratio=20. if required<=20. else _scale_for([bounds[0],bounds[2],bounds[1],bounds[3]],width-8,plot_h)
        caption=(caption[0]+f"  1:{ratio:g}",caption[1])
        clearance=ratio*pw/1000+10.;x+=clearance
        vid=standard["section_id"]+":standard"
        actual,count,offset=_geometry_model(model,standard,x,vid,ratio,detail=True);holes+=count;x=actual[2]+clearance
        view={"section_id":standard["section_id"],"view_id":vid,"asset_id":standard["asset_id"],
            "station":None,"scale":ratio,"bounds":actual,"model_offset":offset,
            "geometry_origin":"unlocated_standard_material_section","quantity_status":"display_only_not_added_to_totals",
            "group_id":record.get("group_id"),"record_id":record.get("record_id")}
        views.append(view)
        page=_full_view_tiles(doc,view,caption,pw,ph,payload,ratio,"特殊构造",page,viewports)
    # This is an explicitly requested length list, not an along-route schedule.
    pages=[];texts=[];layout=None;y=0.
    lines=["材料按长度；土方保留原依据；回填未随长度材料变化修正。"]
    for row in block.get("rows",[]):
        name=row.get("asset_name") or row.get("name") or row.get("asset_id") or "管段"
        title=row.get("title") or row.get("scheme_title") or row.get("scheme_id") or "特殊构造"
        length=row.get("length_m")
        length_note=f"L={length:g}m" if isinstance(length,(int,float)) else "长度待核"
        lines.append(f"{name} / {title} / {length_note} / 未定位")
        for item in row.get("components",row.get("unit_rates",[])):
            quantity=item.get("quantity");rate=item.get("rate")
            if quantity is None and isinstance(rate,(int,float)) and isinstance(length,(int,float)):quantity=rate*length
            amount=f"{quantity:.6g}" if isinstance(quantity,(int,float)) else "待核"
            unit={"m3":"m3","m2":"m2"}.get(item.get("unit"),str(item.get("unit") or ""))
            lines.append(f"  {_special_material_label(item)}：{amount}{unit}")
    for item in block.get("adjustments",[]):
        quantity=item.get("final_quantity",item.get("quantity"))
        if not isinstance(quantity,(int,float)):continue
        unit={"m3":"m3","m2":"m2"}.get(item.get("unit"),str(item.get("unit") or ""))
        lines.append(f"采用后 {_special_material_label(item)}：{quantity:.6g}{unit}")
    for text in lines:
        wrapped=_wrapped(text,pw-40,2.5)
        for line in wrapped:
            if layout is None or y<28.:
                layout=_create_sheet(doc,f"特殊材料清单{len(pages)+1:03d}",pw,ph,"特殊管段长度与材料清单（未定位）",payload)
                pages.append(layout.name);y=ph-28.
            entity=_paper_text(layout,line,(20.,y),pw-40,2.5);texts.append((entity.dxf.handle,entity.plain_text()));y-=4.5
        y-=1.8
    return views,holes,x,{"layouts":pages,"texts":texts,"standard_section_count":len(views),
        "length_record_count":len(block.get("rows",[])),"no_fictitious_station":True,"scope_note":note}


def save_dxf(payload,path,*,interval=20.,all_sections=False,paper="A3",scale=1000,include_plan=True,include_profile=True,envelopes_only=False,opening_only=False,sections_only=False,concise=False,section_layout="overview"):
    if envelopes_only or opening_only:return save_plan_envelopes_dxf(payload,path,opening_only=opening_only)
    if sections_only:include_plan=include_profile=False
    if concise:payload={**payload,"_concise_drawing":True}
    import ezdxf
    from ezdxf import bbox
    from .network_exporter import structure_label
    if paper not in ("A3","A1"):raise ValueError("图幅请选择A3或A1")
    if not math.isfinite(float(scale)) or scale<0:raise ValueError("比例必须为正数或0（自动）")
    if section_layout not in ("overview","pages"):raise ValueError("断面排版请选择总览长图或按图幅分页")
    selected=select_sections(payload,interval,all_sections)
    if not selected:raise ValueError("当前成果没有可出图断面")
    doc=ezdxf.new("R2013");doc.units=6
    for app in ("QX_SECTION_AREA","QX_DRAWING_VIEW"):doc.appids.new(app)
    # AutoCAD TEXT does not reliably use TTC font collections even when its
    # MTEXT fallback appears correct. Use one installed, complete CJK TTF.
    chinese=doc.styles.new("中文",dxfattribs={"font":"simhei.ttf","bigfont":""})
    chinese.set_extended_font_data("SimHei",italic=False,bold=False)
    for key,name in list(NAMES.items()):
        if name not in doc.layers:doc.layers.new(name,dxfattribs={"color":COLORS[key]})
    for name,color in (("标注",7),("图框",8),("纵断面管轴",3),("纵断面管顶",5),("纵断面管底",6),("完成面",4),("地形剖切点",8),("断面位置",3)):
        if name not in doc.layers:doc.layers.new(name,dxfattribs={"color":color})
    model=doc.modelspace();rows={r["asset_id"]:r for r in payload.get("rows",payload.get("assets",[]))};assets={a["asset_id"]:a for a in _assets(payload)}
    pw,ph=(841.,594.) if paper=="A1" else (420.,297.)
    columns,row_count=(3,4) if concise and scale>=500 else (2,2)
    capacity=columns*row_count
    cw,ch=(pw-30)/columns,(ph-40)/row_count
    views=[];details=[];viewports=[];expected_holes=0;x=0.;page=0;slot=capacity;layout=None
    compact_layout={}
    if concise:
        if section_layout=="overview":
            views,viewports,expected_holes,x,compact_layout=_overview_section_sheet(doc,model,payload,selected,rows,assets,scale)
        else:
            views,viewports,expected_holes,x,compact_layout=_compact_section_sheets(doc,model,payload,selected,rows,assets,pw,ph,scale)
    for section in ([] if concise else selected):
        row=rows.get(section["asset_id"],{});asset=assets.get(section["asset_id"],{})
        section=_with_display_foundations(section,asset,payload)
        bounds=section_limits(section)
        initial=[bounds[0],bounds[2],bounds[1],bounds[3]]
        title,notes=_caption(section,payload,row,asset,50)
        caption_h=5.2*len(_wrapped(title,cw-8,3.))+4.3*sum(len(_wrapped(n,cw-8,2.5)) for n in notes)+3
        ratio=float(scale) if scale else _scale_for(initial,cw-8,max(15.,ch-caption_h-6))
        # The blank modelspace around a view must cover its complete viewport,
        # including an explicit large ratio or a partially filled last tile.
        # Both neighbours contribute clearance; disjoint entity bounds alone
        # do not prevent a paper viewport from showing a neighbouring group.
        clearance=ratio*pw/1000+10.
        x+=clearance
        vid=str(section["section_id"])+":cross"
        actual,holes,offset=_geometry_model(model,section,x,vid,ratio,concise=concise,bounds=bounds);expected_holes+=holes
        view={"section_id":str(section["section_id"]),"view_id":vid,"asset_id":section["asset_id"],"station":section["station"],"scale":ratio,"bounds":actual,"source_bounds":[bounds[0],bounds[2],bounds[1],bounds[3]],"model_offset":offset,
            "display_foundation_component_ids":section.get("display_foundation_component_ids",[]),"quantity_status":"saved_section_quantities_unchanged"}
        views.append(view);x=actual[2]+clearance
        caption=_caption(section,payload,row,asset,ratio)
        small_plot_w=cw-8;small_plot_h=ch-caption_h-6
        if actual[2]-actual[0]<=small_plot_w*ratio/1000+1e-8 and actual[3]-actual[1]<=small_plot_h*ratio/1000+1e-8:
            if slot>=capacity:page+=1;layout=_create_sheet(doc,f"横断面{page:03d}",pw,ph,"土石方施工横断面",payload);slot=0
            rectangle=(15+(slot%columns)*cw,20+(row_count-1-slot//columns)*ch,cw,ch)
            _paper_cell(layout,view,rectangle,caption,ratio,viewports);slot+=1
        else:
            page=_full_view_tiles(doc,view,caption,pw,ph,payload,ratio,"横断面",page,viewports)
            slot=capacity
    # One normal construction drawing per actual structure identity. Its clear
    # material rings remain readable when the earthwork section is 1:500+.
    by_asset=defaultdict(list)
    if not concise:
        for section in selected:by_asset[section["asset_id"]].append(section)
    detail_page=0;detail_slot=4;detail_layout=None
    for aid,values in by_asset.items():
        sample=values[len(values)//2];asset=assets.get(aid,{})
        detail=dict(sample);detail.update(roles={},construction_geometry={},ground_points=[],domain=None)
        origin="saved_vertical_section"
        normal_detail=_normal_pipe_detail(sample)
        if normal_detail is not None:
            detail=normal_detail;origin="per_pipe_transverse_binormal_normal_disks_saved_absolute_axis_Z"
        elif asset.get("section"):
            try:
                from ..services.section_geometry import section_structure,add_foundation_materials,structure_mapping
                structure=section_structure(asset,elevation=float(sample.get("design_elevation",0)),slope=0.,arc_segments=128)
                detail["structure_geometry"]=structure_mapping(add_foundation_materials(structure,asset.get("construction",{})))
                origin="parameter_normal_section"
            except (ValueError,KeyError):pass
        if not polygons(detail.get("structure_geometry",{}).get("outer")):continue
        db=section_limits(detail);ratio=50. if (db[1]-db[0])*20<cw-60 and (db[3]-db[2])*20<ch-70 else 100.
        clearance=ratio*pw/1000+10.;x+=clearance
        vid=str(sample["section_id"])+":detail:"+str(aid)
        actual,holes,offset=_geometry_model(model,detail,x,vid,ratio,detail=True);expected_holes+=holes;x=actual[2]+clearance
        view={"section_id":str(sample["section_id"]),"view_id":vid,"asset_id":aid,"station":sample["station"],"scale":ratio,"bounds":actual,"model_offset":offset,"geometry_origin":origin,"quantity_status":"not_added_to_totals"};details.append(view)
        caption=_caption(detail,payload,rows.get(aid,{}),asset,ratio,detail=True)
        title,notes=caption;cap_h=4*len(_wrapped(title,cw-8,3.))+3.35*sum(len(_wrapped(n,cw-8,2.5)) for n in notes)+3
        if actual[2]-actual[0]<=(cw-8)*ratio/1000 and actual[3]-actual[1]<=(ch-cap_h-6)*ratio/1000:
            if detail_slot>=4:detail_page+=1;detail_layout=_create_sheet(doc,f"结构详图{detail_page:03d}",pw,ph,"结构净空与真实材料详图",payload);detail_slot=0
            _paper_cell(detail_layout,view,(15+(detail_slot%2)*cw,20+(1-detail_slot//2)*ch,cw,ch),caption,ratio,viewports);detail_slot+=1
        else:
            detail_page=_full_view_tiles(doc,view,caption,pw,ph,payload,ratio,"结构详图",detail_page,viewports);detail_slot=4
    for aid,values in by_asset.items():
        asset=assets.get(aid,{})
        for detail in _complete_frame_details(asset,values[len(values)//2],payload):
            db=section_limits(detail)
            ratio=_scale_for([db[0],db[2],db[1],db[3]],cw-8,ch-30)
            clearance=ratio*pw/1000+10.;x+=clearance
            vid=str(detail["section_id"])+":frame_detail"
            actual,holes,offset=_geometry_model(model,detail,x,vid,ratio,detail=True)
            expected_holes+=holes;x=actual[2]+clearance
            view={"section_id":detail["section_id"],"view_id":vid,"asset_id":aid,"station":detail["station"],
                "scale":ratio,"bounds":actual,"model_offset":offset,"geometry_origin":"saved_frame_columns_and_full_foundations",
                "quantity_status":"display_only_not_added_to_totals",
                "foundation_component_ids":detail["display_foundation_component_ids"],
                "column_component_ids":[key for key,spec in detail["structure_geometry"]["component_regions"].items()
                    if spec.get("generated_aqueduct_frame") and polygons(spec.get("geometry"))]}
            details.append(view)
            caption=(f"{asset.get('name',aid)} / K{detail['station']:.3f} / 排架柱及扩大基础",[])
            if actual[2]-actual[0]<=(cw-8)*ratio/1000 and actual[3]-actual[1]<=(ch-25)*ratio/1000:
                if detail_slot>=4:
                    detail_page+=1;detail_layout=_create_sheet(doc,f"结构详图{detail_page:03d}",pw,ph,"排架柱及扩大基础",payload);detail_slot=0
                _paper_cell(detail_layout,view,(15+(detail_slot%2)*cw,20+(1-detail_slot//2)*ch,cw,ch),caption,ratio,viewports)
                detail_slot+=1
            else:
                detail_page=_full_view_tiles(doc,view,caption,pw,ph,payload,ratio,"结构详图",detail_page,viewports);detail_slot=4
    material_views,material_holes,x,material_audit=([],0,x,{}) if concise else _special_material_dxf(doc,payload,model,x,pw,ph,viewports)
    details.extend(material_views);expected_holes+=material_holes
    profile_audit=_longitudinal(doc,payload,pw,ph,scale=scale) if include_profile else []
    plan_audit=_plan(doc,payload,pw,ph,model_origin=(x+1000.,0.)) if include_plan else {}
    excluded_audit={} if concise else _excluded_scope_sheets(doc,payload,pw,ph)
    supplementary_audit=_supplementary_quantity_sheets(doc,payload,pw,ph)
    if "Layout1" in doc.layouts and len(doc.layouts)>2:doc.layouts.delete("Layout1")
    try:doc.layouts.set_active_layout("横断面001");doc.header["$TILEMODE"]=0
    except KeyError:pass
    source_texts={e.dxf.handle:e.dxf.text for e in model.query("TEXT")}
    source_mtexts={e.dxf.handle:e.text for e in model.query("MTEXT")}
    # Binary DXF keeps the same editable entities and double-precision values
    # without the text overhead of every vertex in a large section drawing.
    storage="bin" if concise else "asc"
    if compact_layout:compact_layout["dxf_storage"]="binary"
    doc.saveas(path,fmt=storage);saved=ezdxf.readfile(path)
    if saved.audit().errors:raise ValueError("DXF保存回读审计失败")
    for profile in profile_audit:
        for record in profile.pop("_line_records",[]):
            entity=saved.entitydb[record["handle"]]
            actual=np.asarray(list(entity.get_points("xy")))
            if not np.allclose(actual,record["points"],rtol=0,atol=1e-10):
                raise ValueError("纵断面保存回读实际比例或图线坐标改变")
            x0,y0,x1,y1=profile["paper_plot_bounds_mm"]
            if np.any(actual[:,0]<x0-1e-8) or np.any(actual[:,0]>x1+1e-8) or np.any(actual[:,1]<y0-1e-8) or np.any(actual[:,1]>y1+1e-8):
                raise ValueError("纵断面固定比例分幅图线超出绘图区")
        profile["saved_geometry_exact"]=True
    if excluded_audit:
        if any(saved.entitydb[handle].plain_text()!=value for handle,value in excluded_audit["texts"]):
            raise ValueError("DXF未计范围说明保存回读改变")
        excluded_audit["saved_texts_exact"]=True
    if supplementary_audit:
        if any(saved.entitydb[handle].plain_text()!=value for handle,value in supplementary_audit["texts"]):
            raise ValueError("DXF支护清单或排架取高说明保存回读改变")
        supplementary_audit["saved_texts_exact"]=True
        _verify_supplementary_hidden_records(saved,supplementary_audit)
    if material_audit:
        if any(saved.entitydb[handle].plain_text()!=value for handle,value in material_audit["texts"]):
            raise ValueError("DXF特殊管段长度材料清单保存回读改变")
        material_audit["saved_texts_exact"]=True
    groups=defaultdict(list)
    for entity in saved.modelspace():
        if not entity.has_xdata("QX_DRAWING_VIEW"):raise ValueError("模型空间存在没有图组身份的实体")
        groups[entity.get_xdata("QX_DRAWING_VIEW")[0].value].append(entity)
    expected_groups={v["view_id"] for v in views+details}
    if plan_audit.get("view_id"):expected_groups.add(plan_audit["view_id"])
    if set(groups)!=expected_groups:raise ValueError("保存后实际断面/详图/平面身份不一致")
    actual_bounds=[]
    for view in views+details:
        actual=_section_entity_bounds(groups[view["view_id"]])
        if not np.allclose(actual,view["bounds"],atol=1e-7,rtol=0):raise ValueError("DXF回读图形边界改变")
        actual_bounds.append(actual)
    if plan_audit.get("view_id"):
        extent=bbox.extents(groups[plan_audit["view_id"]],fast=True)
        actual=[extent.extmin.x,extent.extmin.y,extent.extmax.x,extent.extmax.y]
        actual_bounds.append(actual);plan_audit["saved_model_bounds"]=actual
    for record in viewports:
        vp=saved.entitydb[record["handle"]];actual_scale=1000*vp.dxf.view_height/vp.dxf.height
        if not math.isclose(actual_scale,record["scale"],rel_tol=1e-12):raise ValueError("保存的实际视口比例与标注不一致")
        record["saved_actual_scale"]=actual_scale
    from shapely.geometry import box
    from shapely.strtree import STRtree
    group_ids=[v["view_id"] for v in views+details]+([plan_audit["view_id"]] if plan_audit.get("view_id") else [])
    groups_by_id={identity:index for index,identity in enumerate(group_ids)}
    group_boxes=[box(*bounds) for bounds in actual_bounds];tree=STRtree(group_boxes)
    for index,geometry in enumerate(group_boxes):
        for other in tree.query(geometry,predicate="intersects"):
            if int(other)>index and geometry.intersection(group_boxes[int(other)]).area>1e-8:
                raise ValueError("DXF模型图组发生重叠")
    checked=list(viewports)
    if plan_audit.get("view_id"):
        checked.append({"handle":plan_audit["viewport_handle"],"view_id":plan_audit["view_id"],"scale":plan_audit["scale"]})
    for record in checked:
        vp=saved.entitydb[record["handle"]];visible=box(*vp.get_modelspace_limits())
        if not math.isclose(1000*vp.dxf.view_height/vp.dxf.height,record["scale"],rel_tol=1e-12):raise ValueError("视口实际比例不符")
        allowed=set(record.get("expected_view_ids",[record["view_id"]]))
        if not allowed.issubset(groups_by_id):raise ValueError("视口记录中存在没有保存的断面图组")
        observed=set()
        for index in tree.query(visible,predicate="intersects"):
            observed.add(group_ids[int(index)])
            if group_ids[int(index)] not in allowed and visible.intersection(group_boxes[int(index)]).area>1e-8:
                raise ValueError("保存后的实际视口串入其他图组："+record["view_id"]+" / "+group_ids[int(index)])
        if "expected_view_ids" in record:
            coverage=visible.buffer(1e-7)
            if observed!=allowed or any(not coverage.covers(group_boxes[groups_by_id[identity]]) for identity in allowed):
                raise ValueError("总览视口未完整覆盖全部断面")
            record["saved_all_section_groups_covered"]=True
        if record["view_id"]==plan_audit.get("view_id") and not visible.buffer(1e-7).covers(group_boxes[groups_by_id[record["view_id"]]]):
            raise ValueError("平面视口裁切了实际地形/轴线/标注")
    if plan_audit.get("view_id"):
        saved_points=[e for e in groups[plan_audit["view_id"]] if e.dxftype()=="POINT"]
        point_digest=hashlib.sha256(np.asarray([list(e.dxf.location) for e in saved_points],dtype="<f8").tobytes()).hexdigest()
        if point_digest!=plan_audit["point_xyz_sha256"]:raise ValueError("平面真实地形 XYZ 保存回读改变")
        plan_audit["saved_point_xyz_exact"]=True;plan_audit["saved_plan_all_geometry_covered"]=True
        _verify_plan_boundaries(saved,plan_audit)
    material_layers={NAMES[r] for r in ("concrete","bedding","pipe_wall","lining")}
    material_layers.update(name for role,name in NAMES.items() if role.startswith("component_"))
    holes=sum(max(0,len(e.paths.paths)-1) for e in saved.modelspace().query("HATCH") if e.dxf.layer in material_layers)
    if holes!=expected_holes:raise ValueError("材料内腔填充路径保存后改变")
    if any(saved.entitydb[h].dxf.text!=value for h,value in source_texts.items()):raise ValueError("中文标注保存回读改变")
    if any(saved.entitydb[h].text!=value for h,value in source_mtexts.items()):raise ValueError("断面题签保存回读改变")
    dimension_records=[]
    for dim in saved.modelspace().query("DIMENSION"):
        texts=[e.text if e.dxftype()=="MTEXT" else e.dxf.text for e in saved.blocks[dim.dxf.geometry] if e.dxftype() in ("MTEXT","TEXT")]
        if not texts or not any(any(c.isdigit() for c in text) for text in texts):raise ValueError("实际尺寸标注没有数字")
        dimension_records.append({"handle":dim.dxf.handle,"measurement_m":dim.get_measurement(),"rendered_text":texts})
    if compact_layout.get("strategy")=="single_overview_10_columns":paper="CUSTOM"
    return {"saved_reopened":True,"audit_errors":0,"saved_no_overlap":True,"saved_viewport_group_isolation_verified":True,"checked_viewport_count":len(checked),"saved_view_bounds":actual_bounds[:len(views)],"display_interval_m":interval,"all_sections":all_sections,"display_section_count":len(views),"complete_section_count":len(payload.get("sections",[])),"sections":views,"paper":paper,"layout_count":len(saved.layouts)-1,"section_layout":compact_layout,"editable_material_holes":holes==expected_holes,"material_hole_count":holes,"plan_included":include_plan,"profile_included":include_profile,"viewports":viewports,"actual_paper_scales_verified":True,"minimum_paper_text_height_mm":2.5,"detail_views":details,"profile":profile_audit,"plan":plan_audit,"excluded_scope":excluded_audit,"supplementary_quantities":supplementary_audit,"special_pipe_materials":material_audit,"text_unicode_saved_verified":True,"cjk_font":"simhei.ttf","dimensions":dimension_records}


def _longitudinal(doc,payload,pw,ph,*,scale=1000):
    from shapely.geometry import LineString,box
    by=defaultdict(list)
    for s in payload.get("sections",[]):by[s["asset_id"]].append(s)
    audit=[];page=0
    aliases={"design_base":("设计基准","结构净空"),"ground":("原地面","原地面"),"interface":("简化基覆界面","简化基覆界面"),"outer_top":("结构外顶","结构外包"),"outer_bottom":("结构外底","结构外包"),"bedding_bottom":("垫层底","垫层"),"finished":("完成面","完成面"),"construction_floor":("施工槽底","施工边界")}
    for aid,values in by.items():
        values=sorted(values,key=lambda r:(r["station"],str(r.get("side",""))))
        levels=[longitudinal_values(s) for s in values];start=values[0]["station"];end=values[-1]["station"]
        all_z=[float(z) for v in levels for z in v.values() if isinstance(z,(int,float)) and math.isfinite(z)]
        if not all_z:continue
        low,high=min(all_z),max(all_z);width=pw-70;height=ph-90
        horizontal=float(scale) if scale else _scale_for([start,0,end,1],width,height)
        vertical=float(scale) if scale else _scale_for([0,low,1,high],width,height)
        fx,fz=1000/horizontal,1000/vertical
        keys=sorted(set(k for v in levels for k in v))
        series=[]
        for key in keys:
            if key.startswith("pipe_"):
                parts=key.split("_");name=f"管{parts[1]}"+{"axis":"轴","top":"外顶","bottom":"外底","ground":"正上方地面"}[parts[-1]];layer={"axis":"纵断面管轴","top":"纵断面管顶","bottom":"纵断面管底","ground":"原地面"}[parts[-1]]
            else:name,layer=aliases.get(key,(key,"标注"))
            line=[];runs=[]
            for section,record in zip(values,levels):
                z=record.get(key)
                if isinstance(z,(float,int)) and math.isfinite(z):line.append((section["station"],z))
                else:
                    if len(line)>1:runs.append(LineString(line))
                    line=[]
            if len(line)>1:runs.append(LineString(line))
            series.append((name,layer,runs))
        station_span=width/fx;elevation_span=height/fz
        nx=max(1,math.ceil((end-start)/station_span-1e-12))
        ny=max(1,math.ceil((high-low)/elevation_span-1e-12))
        def line_parts(geometry):
            if geometry.geom_type=="LineString":
                yield geometry
            elif hasattr(geometry,"geoms"):
                for part in geometry.geoms:yield from line_parts(part)
        for iy in range(ny):
            z0=low+iy*elevation_span;z1=min(high,z0+elevation_span)
            for ix in range(nx):
                a=start+ix*station_span;b=min(end,a+station_span)
                # Full-sized tiles retain the selected scale; clipping at the
                # original TIN/profile line adds only exact boundary vertices.
                clip=box(a,z0,a+station_span,z0+elevation_span)
                tx=lambda st:35+(st-a)*fx;tz=lambda z:35+(z-z0)*fz
                page+=1;layout=_create_sheet(doc,f"纵断面{page:03d}",pw,ph,"纵断面 / "+str(aid),payload)
                drawn=[];line_records=[]
                for name,layer,runs in series:
                    made=False
                    for run in runs:
                        for part in line_parts(run.intersection(clip)):
                            if part.is_empty or len(part.coords)<2:continue
                            points=[(tx(st),tz(z)) for st,z in part.coords]
                            entity=layout.add_lwpolyline(points,dxfattribs={"layer":layer})
                            line_records.append({"handle":entity.dxf.handle,"points":points});made=True
                    if made:drawn.append(name)
                def ticks(first,last,factor,maximum,spacing):
                    span=(last-first)*factor
                    if span<spacing:return [first]
                    count=min(maximum,max(1,math.floor(span/spacing)))
                    return [first+(last-first)*index/count for index in range(count+1)]
                for station in ticks(a,b,fx,5,30.):
                    layout.add_line((tx(station),29),(tx(station),32),dxfattribs={"layer":"标注"})
                    _paper_text(layout,f"{station:.3f}",(tx(station)-12,27),26)
                for z in ticks(z0,z1,fz,4,8.):
                    layout.add_line((29,tz(z)),(32,tz(z)),dxfattribs={"layer":"标注"});_paper_text(layout,f"{z:.3f}",(12,tz(z)+1),20)
                _paper_text(layout,f"水平1:{horizontal:g}；竖向1:{vertical:g}；分幅{ix+1}/{nx}，高程分幅{iy+1}/{ny}",(20,ph-25),pw-40)
                _paper_text(layout," / ".join(drawn),(20,ph-32),pw-40)
                _paper_text(layout,f"本幅桩号 {a:.3f}～{b:.3f}m；高程 {z0:.3f}～{z1:.3f}m",(20,ph-39),pw-40)
                audit.append({"layout":layout.name,"asset_id":aid,"horizontal_scale":horizontal,"vertical_scale":vertical,"drawn_levels":drawn,"source_section_count":len(values),
                    "station_range":[a,b],"elevation_range":[z0,z1],"paper_plot_bounds_mm":[35.,35.,35.+width,35.+height],"tile":[ix,iy],"tile_count":[nx,ny],"_line_records":line_records})
    return audit


def _plan_boundary_intervals(section,role,*,exterior_envelope=False):
    """Project real earthwork regions separately, retaining lateral gaps."""
    roles=("excavation","embankment") if role=="combined" else (role,)
    intervals=sorted((p.bounds[0],p.bounds[2]) for source_role in roles for p in
        polygons(section.get("roles",{}).get(source_role,{}).get("geometry")))
    merged=[]
    for left,right in intervals:
        if right-left<=1e-9:continue
        if merged and left<=merged[-1][1]+1e-9:
            merged[-1]=(merged[-1][0],max(right,merged[-1][1]))
        else:merged.append((left,right))
    if exterior_envelope and merged:return [(merged[0][0],merged[-1][1])]
    return merged


def _plan_boundary_ring(points):
    clean=[]
    for point in points:
        if not clean or np.linalg.norm(point-clean[-1])>1e-9:clean.append(point)
    if len(clean)>1 and np.linalg.norm(clean[0]-clean[-1])<=1e-9:clean.pop()
    if len(clean)<3:return None
    return np.asarray(clean)


def _simple_plan_boundary_rings(points):
    """Repair only a local cell, retaining separate valid exterior/hole rings."""
    from shapely import make_valid
    from shapely.geometry import Polygon
    ring=_plan_boundary_ring(points)
    if ring is None:return
    polygon=Polygon(ring)
    if polygon.is_valid and polygon.area>1e-9:
        yield ring;return
    for part in polygons(make_valid(polygon)):
        if part.area<=1e-9:continue
        for boundary in (part.exterior,*part.interiors):
            clean=_plan_boundary_ring(np.asarray(boundary.coords))
            if clean is not None and Polygon(clean).is_valid and Polygon(clean).area>1e-9:yield clean


def _plan_boundary_transition(first,last):
    """Partition split/merge cells by cumulative occupied transverse width.

    Both saved endpoint interval sets are retained exactly. The intermediate
    correspondence is linear, just as for an ordinary pair of sections.
    Separate closed cells avoid inventing a filled lateral gap at either end.
    """
    cumulative=[]
    for _,edges in (first,last):
        widths=np.linalg.norm(edges[:,1]-edges[:,0],axis=1)
        cumulative.append(np.r_[0.,np.cumsum(widths)/widths.sum()])
    cuts=sorted(set(np.r_[cumulative[0],cumulative[1]].tolist()))
    for low,high in zip(cuts,cuts[1:]):
        if high-low<=1e-12:continue
        ends=[]
        for (_,edges),fractions in zip((first,last),cumulative):
            i=min(len(edges)-1,int(np.searchsorted(fractions,(low+high)/2,side="right"))-1)
            a,b=edges[i];span=fractions[i+1]-fractions[i]
            ends.append([a+(t-fractions[i])/span*(b-a) for t in (low,high)])
        for ring in _simple_plan_boundary_rings([ends[0][0],ends[1][0],ends[1][1],ends[0][1]]):
            yield [first[0],last[0]],ring


def _plan_boundary_runs(sections,role,coverage=(),*,exterior_envelope=False):
    """Close each sampled band without joining gaps or one-sided changes.

    These are drawing outlines interpolated between saved sections. No area
    or volume in the calculation snapshot is changed or deduplicated.
    """
    rows=[]
    def band_contours(parts,index):
        from shapely.geometry import Polygon
        if len(parts)<2 or parts[-1][0]["station"]-parts[0][0]["station"]<=1e-9:return
        points=[edge[index,0] for _,edge in parts]+[edge[index,1] for _,edge in reversed(parts)]
        ring=_plan_boundary_ring(points)
        if ring is not None and Polygon(ring).is_valid and Polygon(ring).area>1e-9:
            yield [s for s,_ in parts],ring
        elif len(parts)>2:
            # Split only the crossing portion, retaining long simple outlines
            # instead of drawing an internal end cap at every saved section.
            middle=len(parts)//2
            yield from band_contours(parts[:middle+1],index)
            yield from band_contours(parts[middle:],index)
        else:
            # Local overlaps remain independent; no footprint union changes
            # the independently measured section quantities.
            first,last=parts
            a,b=first[1][index];c,d=last[1][index]
            for cell in _simple_plan_boundary_rings([a,c,d,b]):
                yield [first[0],last[0]],cell
    def contours():
        if not rows:return
        for index in range(len(rows[0][1])):yield from band_contours(rows,index)
    for section in sorted(sections,key=lambda s:(s["station"],0 if s.get("side")=="left" else 1)):
        intervals=_plan_boundary_intervals(section,role,exterior_envelope=exterior_envelope)
        if not intervals:
            yield from contours();rows=[];continue
        tangent=section.get("tangent",[1.,0.])
        if isinstance(tangent,(int,float)):tangent=[math.cos(tangent),math.sin(tangent)]
        normal=np.asarray([tangent[1],-tangent[0]],dtype=float)
        edges=np.asarray(section["center_xy"],dtype=float)+np.asarray(intervals)[:,:,None]*normal
        if not np.all(np.isfinite(edges)):raise ValueError("开口线断面平面坐标无效")
        if rows:
            previous=rows[-1][0];same_station=abs(section["station"]-previous["station"])<=1e-9
            same_edges=edges.shape==rows[-1][1].shape and np.allclose(edges,rows[-1][1],atol=1e-8,rtol=0)
            if same_station and same_edges:
                rows.append((section,edges));continue
            covered=not coverage or any(a<=previous["station"]+1e-8 and section["station"]<=b+1e-8 for a,b in coverage)
            if same_station or not covered:
                yield from contours();rows=[]
            elif len(edges)!=len(rows[-1][1]):
                yield from contours()
                yield from _plan_boundary_transition(rows[-1],(section,edges))
                rows=[]
        rows.append((section,edges))
    yield from contours()


def _plan_boundary_coverage(payload,aid):
    spans=sorted((float(s["station_start"]),float(s["station_end"]))
        for s in payload.get("segments",[]) if s["asset_id"]==aid)
    merged=[]
    for start,end in spans:
        if merged and start<=merged[-1][1]+1e-8:merged[-1]=(merged[-1][0],max(end,merged[-1][1]))
        else:merged.append((start,end))
    return merged


def _plan_envelope_join_patches(payload,by,role):
    """Heal matching route cross-bars, including wedges that only touch points.

    The small local join hull includes witnesses inside both adjacent bands,
    so a merely touching cap cannot survive as a dangling interior seam.
    """
    from bisect import bisect_left,bisect_right
    from shapely import set_precision
    from shapely.geometry import MultiPoint,LineString
    rows={r["asset_id"]:r for r in payload.get("rows",payload.get("assets",[]))}
    routes=defaultdict(list);owners={};coverage={aid:_plan_boundary_coverage(payload,aid) for aid in by}
    for aid,sections in by.items():
        caps=[]
        for section in sections:
            limits=_plan_boundary_intervals(section,role,exterior_envelope=True)
            if not limits:continue
            tangent=section.get("tangent",[1.,0.])
            if isinstance(tangent,(int,float)):tangent=[math.cos(tangent),math.sin(tangent)]
            normal=np.asarray([tangent[1],-tangent[0]],float)
            center=np.asarray(section["center_xy"],float)
            route=section.get("route_id") or rows.get(aid,{}).get("route_id")
            key=("route",str(route)) if route is not None else ("asset",str(aid))
            cap={"section":section,"asset_id":aid,"station":float(section["station"]),
                "center":center,"edges":center+np.asarray(limits[0])[:,None]*normal,"route_key":key}
            caps.append(cap);routes[key].append(cap)
        caps.sort(key=lambda c:c["station"]);owners[aid]=(caps,[c["station"] for c in caps])
    def covered(aid,a,b):
        return not coverage[aid] or any(lo<=min(a,b)+1e-8 and max(a,b)<=hi+1e-8 for lo,hi in coverage[aid])
    for key,caps in routes.items():
        caps.sort(key=lambda c:c["station"]);stations=[c["station"] for c in caps]
        def witness(cap,direction):
            # Prefer this object's real neighbouring section. A very short
            # split may use the same route's neighbour at the shared joint.
            for values,positions in (owners[cap["asset_id"]],(caps,stations)):
                index=(bisect_left(positions,cap["station"]-.001)-1 if direction<0 else
                       bisect_right(positions,cap["station"]+.001))
                for attempt in range(24):
                    i=index+direction*attempt
                    if not 0<=i<len(values):break
                    other=values[i];ds=abs(other["station"]-cap["station"])
                    if np.linalg.norm(other["center"]-cap["center"])>2*ds+.02:continue
                    if other["asset_id"]==cap["asset_id"] and not covered(cap["asset_id"],cap["station"],other["station"]):continue
                    return other
            return None
        for i,first in enumerate(caps):
            for last in caps[i+1:bisect_right(stations,first["station"]+1e-5)]:
                if np.linalg.norm(first["center"]-last["center"])>.01:continue
                if first["asset_id"]==last["asset_id"] and not covered(first["asset_id"],first["station"],last["station"]):continue
                a,b=first["edges"];c,d=last["edges"]
                va=b-a;vb=d-c
                parallel=abs(float(va[0]*vb[1]-va[1]*vb[0]))<=1e-10*np.linalg.norm(va)*np.linalg.norm(vb)
                snapped_first=set_precision(LineString([a,b]),PLAN_ENVELOPE_GRID_M)
                snapped_last=set_precision(LineString([c,d]),PLAN_ENVELOPE_GRID_M)
                if parallel and snapped_first.intersection(snapped_last).length>1e-8:continue
                normal=va/np.linalg.norm(va);other_normal=vb/np.linalg.norm(vb)
                along=np.asarray([-normal[1],normal[0]]);other_along=np.asarray([-other_normal[1],other_normal[0]])
                # Width changes are real exterior steps, not a reason to grow
                # the patch. Only the perpendicular cap mismatch sets depth.
                mismatch=max(*(abs(float(np.dot(p-a,along))) for p in (c,d)),
                    *(abs(float(np.dot(p-c,other_along))) for p in (a,b)))
                depth=max(8*PLAN_ENVELOPE_GRID_M,2*mismatch)
                origin=(first["center"]+last["center"])/2
                limits=[sorted(float(np.dot(p-origin,normal)) for p in cap["edges"]) for cap in (first,last)]
                low=max(v[0] for v in limits);high=min(v[1] for v in limits)
                points=[];source_ids={str(first["section"]["section_id"]),str(last["section"]["section_id"])}
                for cap in (first,last):
                    projected=[float(np.dot(p-origin,normal)) for p in cap["edges"]]
                    if high-low>1e-6 and abs(projected[1]-projected[0])>1e-8:
                        fractions=np.asarray([(low-projected[0])/(projected[1]-projected[0]),
                            (high-projected[0])/(projected[1]-projected[0])])
                    else:fractions=np.asarray([0.,1.])
                    def trimmed(edges):return edges[0]+fractions[:,None]*(edges[1]-edges[0])
                    points.extend(trimmed(cap["edges"]))
                    for direction in (-1,1):
                        other=witness(cap,direction)
                        if other is None:continue
                        fraction=min(.25,depth/abs(other["station"]-cap["station"]))
                        points.extend(trimmed(cap["edges"]+fraction*(other["edges"]-cap["edges"])))
                        source_ids.add(str(other["section"]["section_id"]))
                hull=MultiPoint(points).convex_hull
                if hull.geom_type!="Polygon" or hull.area<=1e-9:continue
                checks=[]
                if high-low>1e-4:
                    checks=[[(origin+(low+.2*(high-low))*normal).tolist(),
                             (origin+(high-.2*(high-low))*normal).tolist()]]
                yield hull,{"role":role,"route_id":key[1],
                    "asset_ids":sorted({str(first["asset_id"]),str(last["asset_id"])}),
                    "section_ids":sorted(source_ids),"station_start":first["station"],"station_end":last["station"],
                    "check_lines":checks,"join_kind":"route_crossbar_with_interior_witnesses"}


def _plan_envelope_acute_corners(polygon):
    """Count visible pointed reversals, rather than tiny sampling vertices."""
    xy=np.asarray(polygon.exterior.coords[:-1],dtype=float)
    a=np.roll(xy,1,axis=0)-xy;b=np.roll(xy,-1,axis=0)-xy
    lengths=np.linalg.norm(a,axis=1)*np.linalg.norm(b,axis=1)
    angles=np.degrees(np.arccos(np.clip(np.sum(a*b,axis=1)/np.maximum(lengths,1e-30),-1.,1.)))
    return int(np.count_nonzero((angles<75.)&(np.minimum(np.linalg.norm(a,axis=1),np.linalg.norm(b,axis=1))>.03)))


def _prune_plan_envelope_spikes(polygon,*,tolerance,growth_limit_m=None):
    """Replace local pointed returns by their shoulder chord, in drawing only.

    A real taper has no opposite-turn shoulder. Requiring that shoulder, a
    narrow triangular change and retention of the body protects thin bands,
    ordinary width steps and genuine terminal triangles.
    """
    from shapely.geometry import Polygon
    source=polygon.simplify(tolerance,preserve_topology=True)
    width=2*source.area/source.length
    core=source.buffer(-.25*width)
    result=source;changes=[]
    for _ in range(len(source.exterior.coords)-3):
        xy=np.asarray(result.exterior.coords[:-1],dtype=float)
        if len(xy)<=3:break
        incoming=xy-np.roll(xy,1,axis=0);outgoing=np.roll(xy,-1,axis=0)-xy
        cross=incoming[:,0]*outgoing[:,1]-incoming[:,1]*outgoing[:,0]
        lengths=np.linalg.norm(incoming,axis=1)*np.linalg.norm(outgoing,axis=1)
        angles=np.degrees(np.arccos(np.clip(-np.sum(incoming*outgoing,axis=1)/np.maximum(lengths,1e-30),-1.,1.)))
        accepted=False
        for i in np.argsort(angles):
            if angles[i]>=35.:break
            prev=(i-1)%len(xy);nxt=(i+1)%len(xy)
            if not (cross[i]*cross[prev]<-1e-12 or cross[i]*cross[nxt]<-1e-12):continue
            a,b,c=xy[prev],xy[i],xy[nxt]
            triangle=Polygon([a,b,c])
            if triangle.area<=1e-10:continue
            # The inradius measures wedge thickness even when the tip falls
            # beyond the shoulder chord (the oblique return case).
            inradius=2*triangle.area/triangle.length
            if inradius>.25*width or triangle.area>.1*source.area:continue
            candidate=Polygon(np.delete(xy,i,axis=0))
            if not candidate.is_valid or candidate.area<.9*source.area:continue
            if abs(candidate.symmetric_difference(result).area-triangle.area)>max(1e-8,triangle.area*1e-8):continue
            if not core.is_empty and core.difference(candidate.buffer(1e-8)).area>1e-8:continue
            if growth_limit_m is not None and math.isfinite(growth_limit_m):
                if candidate.difference(result.buffer(max(0.,growth_limit_m)+1e-8)).area>1e-8:continue
            changes.append({"kind":"outward_spike" if candidate.area<result.area else "inward_slit",
                "tip_xy":b.tolist(),"shoulder_xy":[a.tolist(),c.tolist()],
                "tip_angle_degrees":float(angles[i]),"shoulder_chord_m":float(np.linalg.norm(c-a)),
                "wedge_inradius_m":float(inradius),"changed_area_m2":float(triangle.area)})
            result=candidate;accepted=True;break
        if not accepted:break
    return result,changes


def _regularize_plan_envelope(polygon,*,cleanup_limit_m=None,simplify_limit_m=None):
    """Remove local pointed returns and use a single straight bevel per corner.

    Work in local coordinates to retain sub-millimetre detail at survey XY.
    Bevels scale down for thin bands; erosion is retried when it cuts a neck.
    This drawing geometry never feeds back into section quantities.
    """
    from shapely.affinity import translate
    from shapely.geometry import Polygon
    if polygon.is_empty or not polygon.is_valid or polygon.area<=1e-9:
        raise ValueError("包络整形需要有效的非空外轮廓")
    ox,oy=polygon.bounds[:2]
    original=translate(Polygon(polygon.exterior),xoff=-ox,yoff=-oy)
    width=2*original.area/original.length
    tolerance=min(PLAN_ENVELOPE_SIMPLIFY_M,.025*width)
    if simplify_limit_m is not None:tolerance=min(tolerance,max(0.,simplify_limit_m))
    base,spikes=_prune_plan_envelope_spikes(original,tolerance=tolerance,growth_limit_m=cleanup_limit_m)
    cleanup=min(PLAN_ENVELOPE_CLEANUP_M,.2*width)
    if cleanup_limit_m is not None:cleanup=min(cleanup,max(0.,cleanup_limit_m))
    bevel=min(PLAN_ENVELOPE_BEVEL_M,.1*width)
    # Retaining the original prevents a numerical negative buffer from shaving
    # narrow source strips. Only the exterior is relevant to a plan envelope.
    closed = base
    cleanup_retries = 0
    while cleanup > 1e-8:
        buffered = base.buffer(cleanup, quad_segs=1, join_style="bevel")
        candidate = buffered.buffer(-cleanup, quad_segs=1, join_style="bevel")
        parts = [part for part in polygons(base.union(candidate)) if part.area > 1e-9]
        if len(parts) == 1:
            outline = Polygon(parts[0].exterior)
            if outline.is_valid:
                closed = outline
                break
        # Closing can create detached patches near closely spaced returns.
        # Reduce the radius and retain the connected source if none succeeds.
        cleanup *= .5
        cleanup_retries += 1
    else:
        cleanup = 0.
    beveled=closed;retries=0
    while bevel>1e-8:
        eroded=closed.buffer(-bevel,quad_segs=1,join_style="bevel")
        candidates=polygons(eroded)
        if len(candidates)==1 and candidates[0].area>1e-9:
            candidate=candidates[0].buffer(bevel,quad_segs=1,join_style="bevel")
            # Guard the eroded core as well as component count. A narrow neck
            # must not be lost and silently replaced by two rounded islands.
            core=closed.buffer(-2*bevel)
            if candidate.geom_type=="Polygon" and candidate.is_valid and candidate.area>=.5*closed.area and core.difference(candidate.buffer(1e-8)).area<1e-8:
                beveled=Polygon(candidate.exterior);break
        bevel*=.5;retries+=1
    else:bevel=0.
    tolerance=min(tolerance,bevel/4 if bevel else cleanup/4)
    result=beveled.simplify(tolerance,preserve_topology=True)
    if result.geom_type!="Polygon" or not result.is_valid or result.is_empty or result.area<=1e-9:
        raise ValueError("包络直线整形后未保留完整闭合外轮廓")
    result=Polygon(result.exterior)
    result,bevel_chains=_straighten_plan_envelope_bevels(result,base,
        chain_limit=2*(cleanup+bevel),deviation_limit=bevel/2)
    # Whole-region bounds allow a long, very thin slit to be filled without
    # confusing its old tip distance with a large displacement of the outline.
    allowance=2*(cleanup+bevel)+tolerance+1e-7
    if result.difference(base.buffer(allowance)).area>1e-8 or base.buffer(-allowance).difference(result.buffer(1e-8)).area>1e-8:
        raise ValueError("包络整形超出局部允许范围")
    for spike in spikes:
        spike["tip_xy"]=[spike["tip_xy"][0]+ox,spike["tip_xy"][1]+oy]
        spike["shoulder_xy"]=[[x+ox,y+oy] for x,y in spike["shoulder_xy"]]
    return translate(result,xoff=ox,yoff=oy),{
        "cleanup_radius_m":cleanup,"cleanup_retries":cleanup_retries,"rounding_radius_m":0.,"bevel_distance_m":bevel,"bevel_retries":retries,
        "spike_pruning":spikes,"corner_connection":"single_straight_bevel",
        "bevel_chains_straightened":bevel_chains,
        "simplify_tolerance_m":tolerance,"characteristic_width_m":width,
        "added_area_m2":float(result.difference(original).area),"removed_area_m2":float(original.difference(result).area),
        "vertices_before":len(original.exterior.coords)-1,"vertices_after":len(result.exterior.coords)-1,
        "acute_corners_before":_plan_envelope_acute_corners(original),
        "acute_corners_after":_plan_envelope_acute_corners(result),"topology_preserved":True}


def _straighten_plan_envelope_bevels(polygon,source,*,chain_limit,deviation_limit):
    """Collapse stacked buffer bevels to two endpoints, retaining source bends.

    Only a short chain between long sides is eligible. A surviving source
    vertex, a long sampled bend or an invalid chord prevents the replacement.
    """
    from shapely.geometry import LineString,Point,Polygon
    if chain_limit<=0 or deviation_limit<=0:return polygon,0
    xy=np.asarray(polygon.exterior.coords[:-1]);n=len(xy)
    lengths=np.linalg.norm(np.roll(xy,-1,axis=0)-xy,axis=1)
    long_edges=np.flatnonzero(lengths>chain_limit)
    if len(long_edges)<2:return polygon,0
    source_xy=np.asarray(source.exterior.coords[:-1]);remove=set();count=0
    for edge in long_edges:
        chain=[(int(edge)+1)%n];j=chain[0]
        while lengths[j]<=chain_limit:
            j=(j+1)%n;chain.append(j)
        if len(chain)<3 or sum(lengths[k] for k in chain[:-1])>chain_limit:continue
        interior=xy[chain[1:-1]]
        if np.any(np.min(np.linalg.norm(interior[:,None,:]-source_xy[None,:,:],axis=2),axis=1)<1e-8):continue
        chord=LineString([xy[chain[0]],xy[chain[-1]]])
        if max(chord.distance(Point(p)) for p in interior)>deviation_limit:continue
        proposed=remove|set(chain[1:-1])
        candidate=Polygon([p for i,p in enumerate(xy) if i not in proposed])
        if not candidate.is_valid or candidate.area<.9*polygon.area:continue
        remove=proposed;count+=1
    return (Polygon([p for i,p in enumerate(xy) if i not in remove]),count) if remove else (polygon,0)


def _plan_envelope_continuous_groups(parts,source_ids):
    """Join only numerical cracks within the same saved section continuity.

    Real empty station intervals stay separate even when their ends are close.
    Source IDs alone are insufficient: a witness can occur in distant patches.
    """
    from shapely.strtree import STRtree
    parent=list(range(len(parts)));tree=STRtree(parts)
    def root(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    for i,part in enumerate(parts):
        for raw in tree.query(part.buffer(10*PLAN_ENVELOPE_GRID_M)):
            j=int(raw)
            if j>i and source_ids[i]&source_ids[j] and part.distance(parts[j])<=10*PLAN_ENVELOPE_GRID_M:
                parent[root(j)]=root(i)
    groups=defaultdict(list)
    for i in range(len(parts)):groups[root(i)].append(i)
    return list(groups.values())


def _plan_opening_envelopes(payload,*,roles=None):
    """Union drawing footprints and export only their overall outer perimeter.

    Section quantities remain independent. This union is used exclusively to
    remove construction seams, overlapping outlines and interior rings in DXF.
    """
    from shapely import set_precision,union_all
    from shapely.geometry import Polygon
    from shapely.strtree import STRtree
    by=defaultdict(list)
    for section in payload.get("sections",[]):
        if section.get("center_xy"):by[section["asset_id"]].append(section)
    audit={"contours":[],"unconnected_sections":[],"source_fragment_counts":{},"continuous_joins":[],"join_patch_counts":{},
        "collapsed_fragment_counts":{},"precision_grid_m":PLAN_ENVELOPE_GRID_M,
        "source":"saved_section_outermost_envelopes","lateral_gaps_enveloped":True,
        "connection":"same_role_footprint_union_across_sections_and_assets; exterior_only",
        "envelope_basis":"leftmost_rightmost_earthwork_limits_per_saved_section; interior_lateral_gaps_omitted",
        "topology_transitions":"continuous_outer_limits_between_saved_sections; route_crossbars_stitched",
        "quantity_snapshot_unchanged":True,"quantity_deduplication":False,
        "perimeter_only":True,"interior_rings_omitted":0,"nested_components_absorbed":0,
        "degenerate_projection_slivers":[],
        "regularization":{"algorithm":"shoulder_chord_spike_pruning_and_straight_bevel_v2",
            "max_cleanup_radius_m":PLAN_ENVELOPE_CLEANUP_M,"max_rounding_radius_m":0.,"max_bevel_distance_m":PLAN_ENVELOPE_BEVEL_M,
            "max_simplify_tolerance_m":PLAN_ENVELOPE_SIMPLIFY_M,"thin_band_cleanup_fraction":.2,"thin_band_bevel_fraction":.1,
            "degenerate_projection_max_width_m":PLAN_ENVELOPE_DEGENERATE_WIDTH_M,
            "degenerate_projection_max_station_span_m":PLAN_ENVELOPE_DEGENERATE_STATION_M,
            "applies_to":list(PLAN_BOUNDARY_LAYERS),"drawing_only":True},"continuous_group_counts":{}}
    for role in (PLAN_BOUNDARY_LAYERS if roles is None else roles):
        fragments=[];regions=[];source_count=0;collapsed=0
        for aid,sections in by.items():
            connected=set()
            for sources,points in _plan_boundary_runs(sections,role,_plan_boundary_coverage(payload,aid),exterior_envelope=True):
                source_count+=1
                region=set_precision(Polygon(points),PLAN_ENVELOPE_GRID_M)
                if region.is_empty or region.area<=1e-9:
                    collapsed+=1;continue
                regions.append(region)
                fragments.append({"asset_id":str(aid),"station_start":float(sources[0]["station"]),
                    "station_end":float(sources[-1]["station"]),
                    "source_section_ids":[str(s["section_id"]) for s in sources]})
                connected.update(str(s["section_id"]) for s in sources)
            for section in sections:
                if str(section["section_id"]) not in connected and _plan_boundary_intervals(section,role):
                    audit["unconnected_sections"].append({"asset_id":str(aid),"role":role,
                        "section_id":str(section["section_id"]),"station":float(section["station"]),
                        "reason":"insufficient_saved_nonempty_sections_or_degenerate_plan_projection"})
        join_count=0
        for patch,join in _plan_envelope_join_patches(payload,by,role):
            region=set_precision(patch,PLAN_ENVELOPE_GRID_M)
            if region.is_empty or region.area<=1e-9:continue
            regions.append(region);join_count+=1;audit["continuous_joins"].append(join)
            fragments.append({"asset_id":join["asset_ids"][0],"station_start":join["station_start"],
                "station_end":join["station_end"],"source_section_ids":join["section_ids"]})
        audit["join_patch_counts"][role]=join_count
        audit["source_fragment_counts"][role]=source_count
        audit["collapsed_fragment_counts"][role]=collapsed
        if not regions:continue
        merged=union_all(regions,grid_size=PLAN_ENVELOPE_GRID_M)
        if not merged.is_valid:raise ValueError("平面开口线包络合并失败")
        parts=polygons(merged)
        audit["interior_rings_omitted"]+=sum(len(part.interiors) for part in parts)
        # Filling holes before a second union also absorbs islands inside those
        # holes. Otherwise their exterior would still be an unwanted inner line.
        outside=polygons(union_all([Polygon(part.exterior) for part in parts],grid_size=PLAN_ENVELOPE_GRID_M))
        audit["nested_components_absorbed"]+=max(0,len(parts)-len(outside))
        tree=STRtree(regions)
        provenance=[]
        for part in outside:
            provenance.append([int(i) for i in tree.query(part,predicate="intersects") if regions[int(i)].intersection(part).area>1e-9])
        ids=[{sid for i in indices for sid in fragments[i]["source_section_ids"]} for indices in provenance]
        groups=_plan_envelope_continuous_groups(outside,ids)
        audit["continuous_group_counts"][role]=len(groups)
        shaped=[]
        group_regions=[union_all([outside[i] for i in group]) for group in groups]
        for group_index,group in enumerate(groups):
            joined=group_regions[group_index]
            if len(group)>1:
                # This tolerance repairs a verified shared-source precision
                # crack; it is never applied between unrelated components.
                joined=joined.buffer(10*PLAN_ENVELOPE_GRID_M,quad_segs=1,join_style="bevel").buffer(-10*PLAN_ENVELOPE_GRID_M,quad_segs=1,join_style="bevel")
            for raw_part in polygons(joined):
                if raw_part.area<=1e-9:
                    audit["collapsed_fragment_counts"][role]+=1;continue
                clearance=min((raw_part.distance(other) for j,other in enumerate(group_regions) if j!=group_index),default=float("inf"))
                indices=sorted({j for i in group for j in provenance[i] if regions[j].distance(raw_part)<1e-7})
                contributors=[fragments[j] for j in indices]
                asset_ids={f["asset_id"] for f in contributors}
                station_span=sum(max(f["station_end"] for f in contributors if f["asset_id"]==aid)-
                    min(f["station_start"] for f in contributors if f["asset_id"]==aid) for aid in asset_ids)
                width=2*raw_part.area/raw_part.length
                if width<PLAN_ENVELOPE_DEGENERATE_WIDTH_M and station_span<=PLAN_ENVELOPE_DEGENERATE_STATION_M:
                    audit["degenerate_projection_slivers"].append({"role":role,"asset_ids":sorted(asset_ids),
                        "source_section_ids":sorted({sid for f in contributors for sid in f["source_section_ids"]}),
                        "station_span_m":station_span,"characteristic_width_m":width,"area_m2":raw_part.area,
                        "source_fragments":contributors,"world_xy":list(raw_part.exterior.coords),
                        "reason":"sub_millimetre_projection_from_near_zero_station_event; drawing_only_omission"})
                    continue
                part,regularization=_regularize_plan_envelope(raw_part,cleanup_limit_m=.45*clearance,simplify_limit_m=.04*clearance)
                regularization["other_continuous_group_clearance_m"]=clearance if math.isfinite(clearance) else None
                shaped.append((part,indices,regularization))
        shaped_tree=STRtree([item[0] for item in shaped])
        for i,(part,_,_) in enumerate(shaped):
            for j in shaped_tree.query(part,predicate="intersects"):
                if int(j)>i and part.intersection(shaped[int(j)][0]).area>1e-8:
                    raise ValueError("包络整形使真实间断范围相互重叠")
        for index,(part,indices,regularization) in enumerate(sorted(shaped,key=lambda item:item[0].bounds)):
            ring=_plan_boundary_ring(np.asarray(part.exterior.coords))
            if ring is None or Polygon(ring).area<=1e-9:continue
            contributors=[fragments[i] for i in indices]
            asset_ids=sorted({f["asset_id"] for f in contributors})
            ranges=[]
            for aid in asset_ids:
                spans=sorted((f["station_start"],f["station_end"]) for f in contributors if f["asset_id"]==aid)
                combined=[]
                for start,end in spans:
                    if combined and start<=combined[-1][1]+1e-8:combined[-1]=(combined[-1][0],max(end,combined[-1][1]))
                    else:combined.append((start,end))
                ranges.extend({"asset_id":aid,"station_start":a,"station_end":b} for a,b in combined)
            audit["contours"].append({"role":role,"outline_kind":"exterior_envelope",
                "asset_id":asset_ids[0] if len(asset_ids)==1 else f"envelope:{role}:{index}",
                "asset_ids":asset_ids,"station_ranges":ranges,
                "station_start":min(f["station_start"] for f in contributors),
                "station_end":max(f["station_end"] for f in contributors),
                "source_section_ids":sorted({sid for f in contributors for sid in f["source_section_ids"]}),
                "source_fragment_count":len(contributors),"envelope_area_m2":float(Polygon(ring).area),
                "regularization":regularization,
                "world_xy":ring.tolist()})
    for role in PLAN_BOUNDARY_LAYERS:
        audit[role+"_polyline_count"]=sum(r["role"]==role for r in audit["contours"])
    return audit


def _verify_plan_boundaries(saved,plan):
    from shapely import union_all
    from shapely.geometry import Polygon,LineString
    audit=plan["opening_boundaries"];records=audit["contours"]
    actual=[e for e in saved.modelspace() if e.dxf.layer in PLAN_BOUNDARY_LAYERS.values()]
    if {e.dxf.handle for e in actual}!={r["handle"] for r in records}:
        raise ValueError("平面开口线保存回读数量改变")
    offset=np.asarray(plan["world_xy_origin"])-np.asarray(plan["model_xy_origin"])
    verified_regions=defaultdict(list)
    for record in records:
        entity=saved.entitydb[record["handle"]]
        if entity.dxftype()!="LWPOLYLINE" or not entity.closed or entity.dxf.layer!=PLAN_BOUNDARY_LAYERS[record["role"]]:
            raise ValueError("平面开口线必须为对应图层的闭合多段线")
        points=np.asarray(list(entity.get_points("xy")))+offset
        if points.shape!=np.asarray(record["world_xy"]).shape or not np.allclose(points,record["world_xy"],atol=1e-7,rtol=0):
            raise ValueError("平面开口线保存回读坐标改变")
        if not Polygon(points).is_valid or Polygon(points).area<=1e-9:
            raise ValueError("平面开口线保存回读必须为无自交的有效闭合轮廓")
        if "regularization" in record and _plan_envelope_acute_corners(Polygon(points))!=record["regularization"]["acute_corners_after"]:
            raise ValueError("平面包络保存回读后的轮廓整形诊断改变")
        verified_regions[record["role"]].append(Polygon(points))
        identity=[tag.value for tag in entity.get_xdata("QX_PLAN_BOUNDARY")]
        if identity!=[record["asset_id"],record["role"],record["station_start"],record["station_end"],*record["asset_ids"]]:
            raise ValueError("平面开口线保存回读对象身份改变")
    audit["saved_closed_polylines_verified"]=True
    audit["saved_world_xy_verified"]=True
    audit["saved_simple_rings_verified"]=True
    audit["saved_exterior_envelopes_verified"]=True
    audit["saved_regularization_verified"]=True
    boundaries={role:union_all(regions).boundary for role,regions in verified_regions.items()}
    omitted_ids=defaultdict(set)
    for sliver in audit.get("degenerate_projection_slivers",[]):
        omitted_ids[sliver["role"]].update(sliver["source_section_ids"])
    skipped_joins=[]
    for join in audit.get("continuous_joins",[]):
        if join["role"] not in boundaries:
            if set(join["section_ids"])<=omitted_ids[join["role"]]:
                skipped_joins.append(join);continue
            raise ValueError("平面包络有效接头缺少对应轮廓")
        for line in join["check_lines"]:
            if boundaries[join["role"]].intersection(LineString(line)).length>1e-4:
                raise ValueError("平面包络连续接头仍残留内部封口线，请重新生成包络")
    audit["saved_continuous_joins_verified"]=True
    audit["checked_continuous_join_count"]=len(audit.get("continuous_joins",[]))-len(skipped_joins)
    audit["omitted_degenerate_join_count"]=len(skipped_joins)


def save_plan_envelopes_dxf(payload,path,*,opening_only=False):
    """A standalone world-coordinate drawing containing only three outlines."""
    import ezdxf
    doc=ezdxf.new("R2013");doc.units=6;doc.appids.new("QX_PLAN_BOUNDARY")
    model=doc.modelspace();audit=_plan_opening_envelopes(payload,roles=("excavation",) if opening_only else None)
    for role,layer in PLAN_BOUNDARY_LAYERS.items():
        if opening_only and role!="excavation":continue
        doc.layers.new(layer,dxfattribs={"color":COLORS.get(role,3)})
        if not opening_only and role!="combined":doc.layers.get(layer).off()
    for record in audit["contours"]:
        entity=model.add_lwpolyline(record["world_xy"],close=True,dxfattribs={"layer":PLAN_BOUNDARY_LAYERS[record["role"]]})
        entity.set_xdata("QX_PLAN_BOUNDARY",[(1000,record["asset_id"]),(1000,record["role"]),
            (1040,record["station_start"]),(1040,record["station_end"]),
            *((1000,aid) for aid in record["asset_ids"])])
        record["handle"]=entity.dxf.handle
    plan={"world_xy_origin":[0.,0.],"model_xy_origin":[0.,0.],"opening_boundaries":audit,
        "world_xy_rule":"world_xy = model_xy; metres; no drawing offset"}
    material_evidence=_supplementary_quantity_sheets(doc,payload,420.,297.) if special_material_scope_note(payload) else {}
    from ..services.workbench_scope import deferred_scope_metadata
    scope=deferred_scope_metadata(payload)
    scope_evidence=_store_hidden_evidence(doc,"CALCULATION_SCOPE",scope) if scope else {}
    doc.saveas(path);saved=ezdxf.readfile(path)
    if saved.audit().errors:raise ValueError("外包络DXF保存回读审计失败")
    _verify_plan_boundaries(saved,plan)
    if material_evidence:_verify_supplementary_hidden_records(saved,material_evidence)
    if scope_evidence:_verify_supplementary_hidden_records(saved,scope_evidence)
    return {"saved_reopened":True,"audit_errors":0,"plan_included":True,"envelopes_only":True,
        "opening_only":opening_only,"default_visible_role":"excavation" if opening_only else "combined",
        "world_coordinates_unchanged":True,"plan":plan,"special_pipe_materials":material_evidence,
        "special_pipe_material_scope_note":special_material_scope_note(payload),
        **({"calculation_scope_evidence":scope_evidence} if scope_evidence else {})}


def _plan(doc,payload,pw,ph,model_origin=(1000000.,0.)):
    values=[s for s in payload.get("sections",[]) if s.get("center_xy")]
    if not values:return {"ground_point_count":0,"source":"no_saved_plan_positions"}
    centers=np.asarray([s["center_xy"] for s in values],dtype=float);low=centers.min(axis=0);high=centers.max(axis=0)
    model=doc.modelspace();origin=np.asarray(model_origin,dtype=float)
    before=len(model)
    inputs=payload.get("inputs",{});work=inputs.get("workbench",inputs.get("workbench_inputs",{}))
    networks=([inputs["network"]] if inputs.get("network") else [])+work.get("networks",[])
    elements=[e for n in networks for e in n.get("alignment",{}).get("elements",[])]
    route_points=[]
    for e in elements:
        if e["kind"]=="arc":
            start=e["start_angle"];sweep=e["sweep_angle"]
            for key,angle in (("start_xy",start),("end_xy",start+sweep)):
                route_points.append(e[key] if key in e else
                    np.asarray(e["center_xy"])+e["radius"]*np.array([math.cos(angle),math.sin(angle)]))
            for angle in (0.,math.pi/2,math.pi,3*math.pi/2):
                delta=(angle-start)%(2*math.pi) if sweep>=0 else (start-angle)%(2*math.pi)
                if delta<=abs(sweep)+1e-12:route_points.append(np.asarray(e["center_xy"])+e["radius"]*np.array([math.cos(angle),math.sin(angle)]))
        else:route_points.extend([e["start_xy"],e["end_xy"]])
    if route_points:
        low=np.minimum(low,np.min(route_points,axis=0));high=np.maximum(high,np.max(route_points,axis=0))
    tx=lambda p:tuple((np.asarray(p,dtype=float)-low+origin).tolist())
    by=defaultdict(list);ground=[]
    for s in values:
        by[s["asset_id"]].append(s);tangent=s.get("tangent",[1.,0.])
        if isinstance(tangent,(int,float)):tangent=[math.cos(tangent),math.sin(tangent)]
        normal=np.asarray([tangent[1],-tangent[0]],dtype=float);center=np.asarray(s["center_xy"],dtype=float)
        for part in ground_parts(s):
            for u,z in part:ground.append([*(center+u*normal),float(z)])
    if ground:
        samples=np.asarray(ground,dtype=float);low=np.minimum(low,samples[:,:2].min(axis=0));high=np.maximum(high,samples[:,:2].max(axis=0))
        unique=np.unique(samples,axis=0);step=max(1,math.ceil(len(unique)/30000));shown=unique[::step]
        # These are actual TIN cut heights projected back to XY, not a new TIN.
    selected=select_sections(payload,20.,False);selected_ids={str(s["section_id"]) for s in selected}
    footprint=[]
    for s in values:
        tangent=s.get("tangent",[1.,0.])
        if isinstance(tangent,(int,float)):tangent=[math.cos(tangent),math.sin(tangent)]
        normal=np.asarray([tangent[1],-tangent[0]],dtype=float);center=np.asarray(s["center_xy"],dtype=float)
        for role in ("excavation","embankment"):
            for poly in polygons(s.get("roles",{}).get(role,{}).get("geometry")):
                footprint.extend([center+poly.bounds[0]*normal,center+poly.bounds[2]*normal])
        if str(s["section_id"]) in selected_ids:
            left,right,_,_=section_limits(s)
            footprint.extend([center+left*normal,center+right*normal])
    if footprint:
        low=np.minimum(low,np.min(footprint,axis=0));high=np.maximum(high,np.max(footprint,axis=0))
    # Reserve physical room for station/elevation text at the route extremes.
    ratio=_scale_for([low[0],low[1],high[0],high[1]],pw-80,ph-95)
    # An overview can see kilometres beyond its actual entities. Place its
    # entire physical viewport beyond every previously drawn model group.
    origin[0]+=ratio*pw/1000+10.
    display_points=[]
    if ground:
        for point in shown:
            xyz=(*tx(point[:2]),float(point[2]));display_points.append(xyz)
            model.add_point(xyz,dxfattribs={"layer":"地形剖切点"})
    text_height=2.5*ratio/1000;occupied=set();station_label_count=0
    grid=np.array([24.,8.])*ratio/1000
    def reserve_label(position,text):
        start=np.floor((np.asarray(position)-low)/grid).astype(int)
        end=np.floor((np.asarray(position)-low+np.array([_text_units(text)*text_height,text_height*1.7]))/grid).astype(int)
        cells={(ix,iy) for ix in range(start[0],end[0]+1) for iy in range(start[1],end[1]+1)}
        if occupied.intersection(cells):return False
        occupied.update(cells);return True
    for e in elements:
        if e["kind"]=="line":model.add_line(tx(e["start_xy"]),tx(e["end_xy"]),dxfattribs={"layer":"结构外包"})
        else:
            start=math.degrees(e["start_angle"]);end=math.degrees(e["start_angle"]+e["sweep_angle"])
            if e["sweep_angle"]<0:start,end=end,start
            model.add_arc(tx(e["center_xy"]),e["radius"],start_angle=start,end_angle=end,dxfattribs={"layer":"结构外包"})
    if "QX_PLAN_BOUNDARY" not in doc.appids:doc.appids.new("QX_PLAN_BOUNDARY")
    boundary_audit=_plan_opening_envelopes(payload)
    for role,layer in PLAN_BOUNDARY_LAYERS.items():
        if layer not in doc.layers:doc.layers.new(layer,dxfattribs={"color":COLORS.get(role,3)})
    for record in boundary_audit["contours"]:
        entity=model.add_lwpolyline([tx(point) for point in record["world_xy"]],close=True,
            dxfattribs={"layer":PLAN_BOUNDARY_LAYERS[record["role"]]})
        entity.set_xdata("QX_PLAN_BOUNDARY",[(1000,record["asset_id"]),(1000,record["role"]),
            (1040,record["station_start"]),(1040,record["station_end"]),
            *((1000,aid) for aid in record["asset_ids"])])
        record["handle"]=entity.dxf.handle
    for aid,sections in by.items():
        sections=sorted(sections,key=lambda r:(r["station"],str(r.get("side",""))))
        if not elements:model.add_lwpolyline([tx(s["center_xy"]) for s in sections],dxfattribs={"layer":"结构外包"})
        for s in sections:
            if str(s["section_id"]) not in selected_ids:continue
            l,r,_,_=section_limits(s);tangent=s.get("tangent",[1.,0.])
            if isinstance(tangent,(int,float)):tangent=[math.cos(tangent),math.sin(tangent)]
            n=np.asarray([tangent[1],-tangent[0]]);center=np.asarray(s["center_xy"])
            model.add_lwpolyline([tx(center+l*n),tx(center+r*n)],dxfattribs={"layer":"断面位置"})
            label=f"K{s['station']:.3f}" if s.get("coordinate_kind")!="pit_local_slice" else f"切片{s.get('local_position',s['station']):.3f}m"
            position=center+r*n+np.array([text_height,text_height])
            if reserve_label(position,label):
                model.add_text(label,dxfattribs={"height":text_height,"style":"中文","layer":"断面位置","insert":tx(position)});station_label_count+=1
    layout=_create_sheet(doc,"平面范围001",pw,ph,"施工范围平面图",payload)
    _paper_text(layout,f"1:{ratio:g}；原点X={low[0]:.3f} Y={low[1]:.3f}",(20,ph-25),pw-40)
    _paper_text(layout,"开挖 / 填筑 / 挖填边界",(20,ph-33),pw-40)
    center=(low+high)/2+np.array([10.,3.])*ratio/1000
    vp=layout.add_viewport(center=(pw/2,(ph-45)/2),size=(pw-40,ph-65),view_center_point=tx(center),view_height=(ph-65)*ratio/1000)
    cells=set();label_count=0
    if ground:
        spacing=15*ratio/1000
        for point in shown:
            cell=tuple(np.floor((point[:2]-low)/spacing).astype(int))
            if cell in cells:continue
            cells.add(cell);text=f"H{point[2]:.3f}";position=None
            # Stations remain near the route. Elevation labels use a separate
            # physical row, with a leader to their genuine section-ground point.
            for offset in ([3.,10.],[3.,-10.]):
                candidate=point[:2]+ratio/1000*np.asarray(offset)
                if reserve_label(candidate,text):position=candidate;break
            if position is None:continue
            label_count+=1
            model.add_lwpolyline([tx(point[:2]),tx(position)],dxfattribs={"layer":"地形剖切点"})
            model.add_text(text,dxfattribs={"height":text_height,"style":"中文","layer":"地形剖切点","insert":tx(position)})
    for entity in list(model)[before:]:_view_tag(entity,"plan:full")
    for role in PLAN_BOUNDARY_LAYERS:
        boundary_audit[role+"_polyline_count"]=sum(r["role"]==role for r in boundary_audit["contours"])
    return {"layout":layout.name,"view_id":"plan:full","scale":ratio,"world_xy_origin":low.tolist(),"model_xy_origin":origin.tolist(),"world_xy_rule":"world_xy = model_xy - model_xy_origin + world_xy_origin; Z unchanged","ground_point_count":len(ground),"displayed_ground_point_count":len(shown) if ground else 0,"ground_height_label_count":label_count,"point_xyz_sha256":hashlib.sha256(np.asarray(display_points,dtype="<f8").reshape(-1,3).tobytes()).hexdigest(),"point_z_is_original_section_ground_height":True,"source":"saved_TIN_section_ground_points_exact_world_projection","generated_surface":False,"section_line_count":len(selected_ids),"station_label_count":station_label_count,"route_element_count":len(elements),"route_geometry_source":"saved_analytic_lines_and_arcs" if elements else "saved_section_centers","viewport_handle":vp.dxf.handle,"opening_boundaries":boundary_audit}

def _cell_value(value):
    if isinstance(value,(dict,list,tuple)):
        return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))
    return value


_QUANTITY_COLUMNS=(
    ("asset_id","对象编号"),("asset_name","对象名称"),("station_start","起点m"),("station_end","终点m"),
    ("component_id","构件编号"),("name","分项/构件"),("material","材料"),("grade","等级"),
    ("quantity","工程量"),("unit","计量单位"),("method","计量方法"),("source_ids","来源编号"),
    ("source_handles","原图实体编号"),("drawing_id","图纸编号"),("template_id","模板编号"),
    ("source_sha256","原图SHA256"),("status","计量状态"),
    ("formula","计量公式"),("input_snapshot","采用参数快照"),
    ("measurement_mode","材料填写方式"),("group_id","规格组"),("record_id","长度记录编号"),
    ("scheme_title","特殊断面"),("length_m","实际轴线长度m"),("rate","每米用量"),
    ("baseline_quantity","一般基准量"),("general_deduction_quantity","一般构造扣减量"),
    ("special_addition_quantity","特殊构造增加量"),
)


def _quantity_row(item,defaults=None):
    merged={**(defaults or {}),**item}
    if merged.get("measurement_mode")=="length":
        merged["station_start"]=None;merged["station_end"]=None
    return [_cell_value(merged.get(key)) for key,_ in _QUANTITY_COLUMNS]


def _workbench_input(payload):
    inputs=payload.get("inputs",{})
    return inputs.get("workbench",inputs.get("workbench_inputs",{}))


_FRAME_FOUNDATION_COLUMNS=(
    "基础顶取高模式","所选持力层","强风化顶距地表深度m","强风化底距地表深度m","弱风化底距地表深度m",
    "基础底进入持力层深度m","扩大基础总厚度m","强风化顶高程m","强风化底高程m","弱风化顶高程m","弱风化底高程m",
    "所选持力层顶高程m","所选持力层底高程m","基础底高程m","基础顶高程m","界面假定及取高校核范围",
)


def _frame_foundation_export_values(record):
    mode=record.get("foundation_mode","offset")
    if mode!="weathering":
        return [mode,*([None]*(len(_FRAME_FOUNDATION_COLUMNS)-1))]
    weathering=record.get("weathering_foundation") or {}
    layer={"strong":"强风化","weak":"弱风化"}.get(record.get("bearing_layer"),record.get("bearing_layer"))
    if record.get("foundation_geometry_modeled"):
        scope="地层界面按地表高程向下竖直偏移，为用户假定；基础范围采用已记录的地形极值取高，承载力仍须设计核定。"
    else:
        scope="地层界面按各柱位地表高程向下竖直偏移，为用户假定；仅用于确定柱高，未自动生成扩大基础实体，未校核全基础范围的地层与承载条件。"
    if record.get("height_basis_scope"):scope+=" "+record["height_basis_scope"]
    return [mode,layer,*(weathering.get(key) for key in ("strong_top_depth_m","strong_bottom_depth_m","weak_bottom_depth_m",
        "embedment_m","foundation_thickness_m")),*(record.get(key) for key in ("strong_top_elevation","strong_bottom_elevation",
        "weak_top_elevation","weak_bottom_elevation","bearing_layer_top_elevation","bearing_layer_bottom_elevation",
        "foundation_bottom_elevation","foundation_top_elevation")),scope]


def _foundation_export_table(payload):
    rows={row["asset_id"]:row for row in payload.get("rows",payload.get("assets",[]))}
    records=[]
    for pit in _workbench_input(payload).get("pits",[]):
        if not pit.get("generated_aqueduct_foundation"):continue
        member=pit.get("source_component") or {};proof=member.get("frame_height_basis") or {}
        footprint=proof.get("foundation_footprint") or {};weathering=proof.get("weathering_foundation") or {}
        measured=rows.get(pit["asset_id"],{})
        start=pit.get("parent_station_start",member.get("station_start"))
        end=pit.get("parent_station_end",member.get("station_end"))
        length=None if start is None or end is None else float(end)-float(start)
        low=member.get("bottom_elevation");high=member.get("top_elevation")
        records.append([pit.get("parent_route_id"),pit.get("parent_asset_id"),pit.get("asset_id"),
            pit.get("parent_component_id"),member.get("column_component_id"),member.get("frame_column_id"),
            member.get("frame_station",None if start is None or end is None else (start+end)/2),member.get("name"),
            length,member.get("width"),None if low is None or high is None else high-low,member.get("material"),member.get("grade"),
            low,high,footprint.get("terrain_min_elevation"),footprint.get("terrain_max_elevation"),
            footprint.get("footprint_area_m2"),footprint.get("coverage_area_m2"),proof.get("bearing_layer"),
            proof.get("bearing_layer_top_elevation"),proof.get("bearing_layer_bottom_elevation"),weathering.get("embedment_m"),
            measured.get("concrete_volume"),measured.get("excavation_volume"),measured.get("backfill_volume"),measured.get("bedding_volume"),
            _cell_value(member.get("construction") or pit.get("construction")),_cell_value(footprint),
            "已计入工程量汇总，不另相加" if measured else "未匹配计算明细，不按零量理解"])
    if not records:return None
    return ("排架扩大基础",["线路","父对象编号","独立基坑编号","基础构件编号","关联柱编号","排架柱序号","排架中心源桩号m","名称",
        "沿线基础长m","横向基础宽m","基础厚m","材料","等级","基础底高程m","基础顶高程m","基础范围地形最低高程m","基础范围地形最高高程m",
        "基础平面面积m2","有效地形覆盖面积m2","所选持力层","采用持力层顶高程m","采用持力层底高程m","进入持力层深度m",
        "已计基础混凝土m3","已计基坑开挖m3","已计基坑回填m3","已计基坑垫层m3","四侧基坑参数","基础范围地形取高证据","计量归属"],records)


def _supplementary_export_tables(payload):
    """Export adopted inputs and height evidence from the saved result only."""
    tables=[]
    from .structure_quantity_tables import trenchless_excavation_table
    bore_table=trenchless_excavation_table(payload)
    if bore_table[2]:
        tables.append(bore_table)
    support_rows=[]
    for item in (payload.get("slope_support") or {}).get("rows", []):
        p=item.get("parameters") or {}
        support_rows.append([item["id"],item.get("name"),item.get("type"),item.get("length_m"),
            item.get("side_count"),item.get("total_length_m"),p.get("slope_width_m"),
            p.get("height_m"),p.get("slope_ratio"),p.get("shotcrete_thickness_m"),item.get("template_id"),
            _cell_value(item.get("included_components")),_cell_value(item.get("missing_components")),
            "已录分项齐全" if item.get("scope_complete") else "仍有未计分项"])
    if support_rows:
        tables.append(("支护计量设置",["记录编号","名称","支护类型","单侧长度m","侧数","计量总长度m",
            "坡面展开宽m","竖直坡高m","坡比1:m","喷层厚度m","复用模板","已计分项","未计分项","状态"],support_rows))
    frames=[];diameters=[]
    for route in _workbench_input(payload).get("networks", []):
        rid=route.get("route_id") or route.get("network_id") or route.get("name")
        for asset in route.get("assets", []):
            section=asset.get("section") or {}
            config=section.get("aqueduct_frame_layout") or {}
            members={m.get("component_id"):m for m in section.get("discrete_components", [])}
            for record in (config.get("generated_snapshot") or {}).get("columns", []):
                member=members.get(record["component_id"],{})
                frames.append([rid,asset.get("asset_id"),record["component_id"],member.get("name"),
                    record.get("station"),*(record.get("xy") or [None,None]),
                    record.get("inner_invert_elevation"),record.get("terrain_elevation"),
                    record.get("invert_to_column_top_m"),record.get("foundation_top_offset_m"),
                    record.get("top_elevation"),record.get("bottom_elevation"),record.get("height_m"),
                    member.get("width"),member.get("station_end",0)-member.get("station_start",0),
                    record.get("formula"),_cell_value((config.get("generated_snapshot") or {}).get("source_basis")),
                    *_frame_foundation_export_values(record)])
            if section.get("nominal_diameter_m") is not None or any(p.get("nominal_diameter_m") is not None for p in section.get("pipes", [])):
                for index,pipe in enumerate(section.get("pipes") or [section],1):
                    nominal=pipe.get("nominal_diameter_m",section.get("nominal_diameter_m"))
                    envelope=pipe.get("earthwork_envelope_only",section.get("earthwork_envelope_only"))
                    diameters.append([rid,asset.get("asset_id"),asset.get("name"),index,
                        None if nominal is None else float(nominal)*1000,
                        pipe.get("hydraulic_inner_diameter_m",section.get("hydraulic_inner_diameter_m")),
                        pipe.get("outer_diameter",section.get("outer_diameter")),pipe.get("wall_thickness",section.get("wall_thickness")),
                        pipe.get("diameter_basis",section.get("diameter_basis")),
                        "管壁/内衬材料未计" if envelope else "按明确构造计量",_cell_value(asset.get("quantity_scope_notes",[]))])
    if frames:
        tables.append(("渡槽排架柱高",["线路","对象编号","柱编号","名称","中心桩号m","柱位X","柱位Y",
            "净渠底高程m","柱位地形高程m","渠底至柱顶竖距m","基础顶相对地面高差m","柱顶高程m",
            "柱底高程m","柱高m","横向柱宽m","沿线柱厚m","取高公式","生成依据",*_FRAME_FOUNDATION_COLUMNS],frames))
    foundations=_foundation_export_table(payload)
    if foundations:tables.append(foundations)
    if diameters:
        tables.append(("管道直径依据",["线路","对象编号","名称","第几根管","公称DN","来源水力D(m)",
            "采用施工占位径m","明确壁厚m","直径采用依据","管材计量范围","范围说明"],diameters))
    tables.extend(_special_material_export_tables(payload))
    return tables


def _binding_title(binding,payload):
    saved=next((row for row in _workbench_input(payload).get("drawing_bindings",[])
        if row.get("template_id")==binding.get("template_id")),{})
    scheme=next((row for row in _workbench_input(payload).get("section_scheme_bindings",[])
        if row.get("scheme_id")==binding.get("template_id")),{})
    return (scheme.get("scheme_snapshot") or {}).get("title") or saved.get("title") or (saved.get("template_snapshot") or {}).get("title") or binding.get("title") or binding.get("drawing_id") or binding.get("template_id","")


def _binding_rows(payload):
    records=[]
    workbench=_workbench_input(payload)
    for binding in workbench.get("drawing_bindings",[]):
        template=binding.get("template_snapshot") or {}
        records.append([binding.get("project_identity"),binding.get("network_id"),binding.get("asset_id"),
            binding.get("station_start"),binding.get("station_end"),binding.get("template_id"),binding.get("template_version"),
            binding.get("drawing_id"),_binding_title(binding,payload),binding.get("source_sha256"),
            _cell_value(binding.get("source_handles")),binding.get("scope_label"),_cell_value(template.get("fields")),
            _cell_value(binding.get("user_overrides")),_cell_value(template.get("missing_items")),
            _cell_value(binding.get("warnings",template.get("warnings"))),binding.get("status","已绑定")])
    for binding in workbench.get("section_scheme_bindings",[]):
        scheme=binding.get("scheme_snapshot") or {}
        fields={"common":scheme.get("fields",{}),"terrain_variants":scheme.get("terrain_variants",{})}
        records.append([None,binding.get("route_id"),binding.get("asset_id"),
            binding.get("station_start"),binding.get("station_end"),binding.get("scheme_id"),scheme.get("version","1"),
            scheme.get("drawing_id"),scheme.get("title"),binding.get("source_sha256"),
            _cell_value(scheme.get("source_handles")),scheme.get("condition"),_cell_value(fields),
            _cell_value(binding.get("overrides")),_cell_value(scheme.get("missing_items") or ["钢筋、止水、排水、支护等附属项目本轮未计"]),
            _cell_value(scheme.get("warnings")),"已按区段采用；明渠工况按地形自动判别" if scheme.get("terrain_variants") else "已按区段采用"])
    for issue in workbench.get("drawing_binding_issues",[]):
        row=issue if isinstance(issue,dict) else {"message":str(issue)}
        records.append([row.get("project_identity"),row.get("network_id"),row.get("asset_id"),row.get("station_start"),row.get("station_end"),
            row.get("template_id"),None,row.get("drawing_id"),"绑定冲突/待核对",row.get("source_sha256"),None,None,None,None,None,
            _cell_value(row),"未采用/待核对"])
    return records


def _verify_table(saved,name,expected):
    sheet=saved[name]
    actual=list(sheet.iter_rows(min_row=2,values_only=True))
    if len(actual)!=len(expected):raise ValueError(name+"保存回读条目数改变")
    for row,reference in zip(actual,expected):
        if len(row)!=len(reference):raise ValueError(name+"保存回读字段数改变")
        for value,target in zip(row,reference):
            if value==target or value is None and target=="":continue
            if isinstance(value,(float,int)) and isinstance(target,(float,int)) and math.isclose(value,target,rel_tol=1e-14,abs_tol=1e-10):continue
            raise ValueError(name+"保存回读的工程量、单位或来源不一致")


def save_xlsx(payload,path):
    from openpyxl import Workbook,load_workbook
    from openpyxl.styles import Font,PatternFill,Alignment
    from .structure_quantity_tables import (CLASSIFICATION_NOTE,trenchless_quantity_note,exclusion_label,
                                             structure_tables,style_structure_tables,trenchless_summary_columns)
    wb=Workbook();summary=wb.active;summary.title="工程量汇总"
    basis=payload.get("quantity_basis") or {}
    layer_columns=layered_volume_columns(payload)
    volume_columns=[*VOLUMES,*layer_columns]
    bore_columns=trenchless_summary_columns(payload)
    summary_columns=[*volume_columns,*bore_columns]
    layer_roles=[(key.removesuffix("_volume"),name) for key,name in layer_columns if key!="unclassified_excavation_volume"]
    layer_note=layered_scope_note(payload)
    special_note=special_material_scope_note(payload)
    trenchless_only=(payload.get("validation") or {}).get("trenchless_only")
    physical_columns=[(key,(name+"（土方几何基准）") if special_note and key in {"concrete_volume","bedding_volume"} else name)
                      for key,name in volume_columns]
    summary_title="非开挖洞挖工程量" if trenchless_only else "断面法工程量"
    from ..services.workbench_scope import deferred_scope_note
    partial_note=deferred_scope_note(payload)
    if partial_note:summary_title+="（部分计量）"
    summary.append([("TEST" if not basis and payload.get("test_only") else "")+summary_title,"m³"])
    if partial_note:summary.append(["计量范围",partial_note])
    first_quantity_row=summary.max_row+1
    for key,name in summary_columns:
        label=name+"（土方几何基准）" if special_note and key=="concrete_volume" and payload.get("soil_basis_material_totals") else name
        summary.append([label,payload.get(key)])
    if payload.get("all_concrete_volume") is not None:
        summary.append(["全部已计混凝土（含分项构件）",payload["all_concrete_volume"]])
    summary.append(["输入SHA256",payload.get("input_hash","")]);summary.append(["地形SHA256",payload.get("terrain",{}).get("source_sha256","")])
    summary.append(["计量口径",trenchless_quantity_note(payload) if trenchless_only else
                    "断面法近似量；天然挖方；成型回填/填筑；未统计的历史材料量留空"])
    policy_note=overlap_policy_note(payload)
    if policy_note:summary.append(["重叠计量口径",policy_note])
    if (payload.get("validation") or {}).get("sampling_mode",((payload.get("inputs") or {}).get("accuracy") or {}).get("sampling_mode"))=="fixed":
        summary.append(["断面间距与方法",section_sampling_note(payload)])
    if basis.get("label"):summary.append(["计量依据",basis["label"]])
    if payload.get("quantity_scope_issues"):
        summary.append(["待补分项",f"{len(payload['quantity_scope_issues'])}项；详见计算说明，未计量不按零量理解"])
    classification_tables=structure_tables(payload,layer_columns)
    for title,headers,records in classification_tables:
        table=wb.create_sheet(title);table.append(headers)
        for record in records:table.append(record)
    summary.append(["结构分类输出","结构分类汇总及各结构类别独立工作表；仅统计土石方挖填，材料分项另表保留。"])
    explanation=wb.create_sheet("计算说明")
    explanation.append(["项目","内容"])
    explanation.append(["结构分类口径",CLASSIFICATION_NOTE])
    if bore_columns:
        explanation.append(["非开挖洞挖口径",trenchless_quantity_note(payload)])
        summary.append(["非开挖洞挖","区段及计量依据见非开挖洞挖明细。"])
    if policy_note:explanation.append(["重叠计量口径",policy_note])
    if special_note:
        summary.append(["材料与土方采用依据",special_note])
        explanation.append(["特殊管段长度材料",special_note])
        explanation.append(["逐桩及分段材料列","分项、断面和分段的混凝土/垫层及材料构件记录保留土方几何基准；正式采用后材料数量见材料构件工程量及特殊构造替换汇总，不将未定位长度分配到任意桩号。"])
    if layer_note:
        summary.append(["简化分层计量范围",layer_note])
        explanation.append(["简化分层及计量范围",layer_note])
    if basis.get("label"):
        explanation.append(["计量依据",basis["label"]])
        explanation.append(["设计高程来源","主程序水面线实际计算成果" if basis.get("design_elevation_source")=="water_profile_calculation" else basis.get("design_elevation_source","")])
        explanation.append(["施工参数来源","暂按假定施工参数，可在主程序编辑后重算" if basis.get("construction_parameters")=="assumed" else basis.get("construction_parameters","")])
        explanation.append(["管顶覆土m",basis.get("pipe_cover_depth_m")])
    accuracy=(payload.get("inputs") or {}).get("accuracy",{})
    if accuracy and not trenchless_only:
        explanation.append(["常规最大断面间距m" if _has_curve_sampling(payload) else "基本断面间距m",accuracy.get("profile_step")])
        if (payload.get("validation") or {}).get("sampling_mode",accuracy.get("sampling_mode"))=="fixed":
            explanation.append(["采样方式",section_sampling_note(payload)])
            explanation.append(["积分方式","平均断面积分 V=(A起+A止)×段长/2；弯道新增断面与常规断面共同组成积分区间。" if _has_curve_sampling(payload) else "平均断面积分 V=(A起+A止)×段长/2；仅剖切实际布置的端点和关键断面。"])
            if _has_curve_sampling(payload):
                curve=(payload.get("validation") or {}).get("curve_sampling") or {}
                if curve.get("max_turn_angle_deg") is not None and curve.get("max_chord_height_m") is not None:
                    explanation.append(["弯道布站控制",f"补圆弧起点BC、终点EC及中点MC；相邻断面转角不大于{curve['max_turn_angle_deg']:g}°，中心轴线弦高不大于{curve['max_chord_height_m']:g}m，且间距不超过常规最大值。"])
                if curve.get("added_section_count") is not None:
                    explanation.append(["弯道新增断面数",curve["added_section_count"]])
        else:
            explanation.append(["全线分项复算允许差",f"{accuracy.get('absolute_tolerance',10):g}m³＋{float(accuracy.get('relative_tolerance',.01))*100:g}%×该分项量"])
            explanation.append(["逐对象分项复算允许差",f"{accuracy.get('per_asset_absolute_tolerance',accuracy.get('absolute_tolerance',10)):g}m³＋{float(accuracy.get('per_asset_relative_tolerance',accuracy.get('relative_tolerance',.01)))*100:g}%×该分项量"])
            explanation.append(["采样方式","结构端点、解析线元及设计变坡点加断面；实际地形剖切、真实中点积分" if accuracy.get("terrain_event_policy")=="regular" else "原TIN事件加密断面"])
    for item in payload.get("diagnostics",[]):
        if item.get("resolved"):
            continue
        explanation.append([item.get("code","说明"),item.get("message",str(item))])
        for location in item.get("affected_locations",[]):
            explanation.append(["接头近似位置",f"{location['asset_id']}：{location['station_start']:.3f}～{location['station_end']:.3f}m；最大局部断面重叠面积 {location['maximum_overlap_area_m2']:.6g}m²"])
    excluded_label=exclusion_label(payload)
    explanation.append(["计量范围",f"断面法分项工程量所列对象；{excluded_label}如下。" if payload.get("excluded_assets") else "本表分项工程量所列全部对象。"])
    for item in payload.get("excluded_assets",[]):
        explanation.append([excluded_label,_excluded_description(item)])
    for item in payload.get("quantity_scope_issues",[]):
        explanation.append(["待补分项",f"{item.get('name') or item.get('asset_id','')}：{item.get('message','')}"])
    asset_rows=[[row["asset_id"],row.get("name",""),row.get("station_start"),row.get("station_end"),*[row.get(key) for key,_ in volume_columns]] for row in payload.get("rows",payload.get("assets",[]))]
    assets=wb.create_sheet("分项工程量");assets.append(["对象","名称","起点m","终点m",*[name+"m³" for _,name in physical_columns]])
    for row in asset_rows:assets.append(row)
    area_rows=[]
    for s in payload.get("sections",[]):
        row=[s["section_id"],s["asset_id"],s["station"],s.get("design_elevation"),*[s.get("roles",{}).get(r,{}).get("area") for r in ("excavation","backfill","embankment")],s.get("material_areas",{}).get("concrete"),s.get("material_areas",{}).get("bedding"),*[s.get("roles",{}).get(role,{}).get("area") for role,_ in layer_roles]]
        if layer_roles:row.append((s.get("geology") or {}).get("thickness"))
        if _has_curve_sampling(payload):
            row.extend(["；".join(_SAMPLING_REASON_NAMES.get(reason,reason) for reason in s.get("sampling_reasons",[])),"是" if s.get("curve_added") else "否"])
        area_rows.append(row)
    areas=wb.create_sheet("断面面积");areas.append(["断面ID","对象","位置m","设计高程m","挖m²","回填m²","填筑m²",
        "混凝土（土方几何基准）m²" if special_note else "混凝土m²","垫层（土方几何基准）m²" if special_note else "垫层m²",
        *[name+"m²" for _,name in layer_roles],*(["假定覆盖层竖直厚度m"] if layer_roles else []),
        *(["布站依据","弯道新增断面"] if _has_curve_sampling(payload) else [])])
    for row in area_rows:areas.append(row)
    default_rule="平均断面积分" if payload.get("integration_method")=="exact_tin_average_end_sections" else "真实中点辛普森积分"
    segment_rows=[[s["asset_id"],s["station_start"],s.get("mid_station"),s["station_end"],s.get("length",s["station_end"]-s["station_start"]),*[s.get(k) for k,_ in volume_columns],"平均断面积分" if s.get("integration_rule")=="average_end_sections" else s.get("integration_rule",default_rule)] for s in payload.get("segments",[])]
    segments=wb.create_sheet("分段积分");segments.append(["对象","起点m","中点m","终点m","段长m",*[name+"m³" for _,name in physical_columns],"积分公式"])
    for row in segment_rows:segments.append(row)
    quantity_items=payload.get("quantity_items") or [item for row in payload.get("rows",payload.get("assets",[])) for item in row.get("quantity_items",[])]
    quantity_rows=[_quantity_row(item) for item in quantity_items]
    quantities=wb.create_sheet("材料构件工程量");quantities.append([label for _,label in _QUANTITY_COLUMNS])
    for row in quantity_rows:quantities.append(row)
    quantity_segment_rows=[_quantity_row(item,{key:segment.get(key) for key in ("asset_id","asset_name","station_start","station_end")})
        for segment in payload.get("segments",[]) for item in segment.get("quantity_items",[])]
    material_segment_title="土方依据材料分段" if special_note else "材料构件分段明细"
    material_segments=wb.create_sheet(material_segment_title);material_segments.append([label for _,label in _QUANTITY_COLUMNS])
    for row in quantity_segment_rows:material_segments.append(row)
    binding_rows=_binding_rows(payload)
    bindings=wb.create_sheet("图纸绑定依据")
    bindings.append(["工程身份","线路编号","对象编号","起点m","终点m","模板编号","模板版本","图纸编号","图纸/模板名称", "原图SHA256",
        "原图实体编号","适用范围","图纸参数快照","保留用户覆盖","缺项及未计分项","警示或冲突","采用状态"])
    for row in binding_rows:bindings.append(row)
    supplementary_tables=_supplementary_export_tables(payload)
    for title,headers,records in supplementary_tables:
        table=wb.create_sheet(title);table.append(headers)
        for record in records:table.append(record)
    explanation.append(["材料构件计量","材料构件工程量按各行计量单位列项；m²铺设面积不并入m³体积。材料分项为既有结构/找平量的细分时，不与原汇总体积重复相加。"])
    for asset in _assets(payload):
        for field_path,source in asset.get("parameter_sources",{}).items():
            if str(source).startswith("用户"):
                explanation.append(["保留用户覆盖",f"{asset.get('name',asset.get('asset_id',''))}：{field_path}；{source}"])
    for sheet in wb:
        sheet.freeze_panes="A2";sheet.auto_filter.ref=sheet.dimensions
        for cell in sheet[1]:cell.font=Font(bold=True,color="FFFFFF");cell.fill=PatternFill("solid",fgColor="234E70")
        for column in sheet.columns:sheet.column_dimensions[column[0].column_letter].width=27 if column[0].column<=2 else 18
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                cell.alignment=Alignment(vertical="center")
                if isinstance(cell.value,(float,int)):cell.number_format="0.000"
    explanation.column_dimensions["A"].width=30
    explanation.column_dimensions["B"].width=110
    for row in explanation.iter_rows(min_row=2):
        row[1].alignment=Alignment(vertical="top",wrap_text=True)
        explanation.row_dimensions[row[0].row].height=34
    if _has_curve_sampling(payload):
        reason_column=areas.max_column-1
        areas.column_dimensions[areas.cell(1,reason_column).column_letter].width=38
        for row in areas.iter_rows(min_row=2):
            row[reason_column-1].alignment=Alignment(vertical="top",wrap_text=True)
            areas.row_dimensions[row[0].row].height=34
    for sheet in (quantities,material_segments,bindings):
        for row in sheet.iter_rows(min_row=2):
            for cell in row:cell.alignment=Alignment(vertical="top",wrap_text=True)
        for column in ("F","I","K","L","M","N","O","P","R","S"):
            sheet.column_dimensions[column].width=34
    for title,_headers,_records in supplementary_tables:
        for row in wb[title].iter_rows(min_row=2):
            for cell in row:cell.alignment=Alignment(vertical="top",wrap_text=True)
    style_structure_tables(wb,classification_tables)
    wb.save(path);saved=load_workbook(path,read_only=True,data_only=True)
    try:
        for index,(key,_) in enumerate(summary_columns,first_quantity_row):
            actual=saved["工程量汇总"].cell(index,2).value
            expected=payload.get(key)
            if actual==expected:continue
            if isinstance(actual,(float,int)) and isinstance(expected,(float,int)) and math.isclose(actual,expected,rel_tol=1e-14,abs_tol=1e-8):continue
            raise ValueError("Excel汇总回读不一致")
        if saved["断面面积"].max_row!=len(payload.get("sections",[]))+1:raise ValueError("Excel断面数改变")
        if saved["分段积分"].max_row!=len(payload.get("segments",[]))+1:raise ValueError("Excel积分段数改变")
        _verify_table(saved,"分项工程量",asset_rows)
        _verify_table(saved,"断面面积",area_rows)
        _verify_table(saved,"分段积分",segment_rows)
        _verify_table(saved,"材料构件工程量",quantity_rows)
        _verify_table(saved,material_segment_title,quantity_segment_rows)
        _verify_table(saved,"图纸绑定依据",binding_rows)
        for title,_headers,records in classification_tables:_verify_table(saved,title,records)
        for title,_headers,records in supplementary_tables:_verify_table(saved,title,records)
    finally:saved.close()
    return {"saved_reopened":True,"numeric_quantities_verified":True,"section_count":len(payload.get("sections",[])),"segment_count":len(payload.get("segments",[])),
        "quantity_item_count":len(quantity_rows),"quantity_segment_count":len(quantity_segment_rows),"drawing_binding_count":len(binding_rows),"component_units_sources_verified":True,
        "structure_category_count":len(classification_tables)-1,"structure_totals_verified":True}
