"""Validate actual support for buried pipes restored to original terrain.

This checks saved section geometry only. It never changes the axis, terrain,
materials or integration and does not require the pipe crown to be buried.
"""
from __future__ import annotations

from bisect import bisect_right
import math
from shapely.geometry import shape, LineString, Polygon, box
from shapely.errors import ShapelyError

from .contracts import ConstructionInputError
from .construction_rules import is_circular_culvert
from .earthwork_scope import trenchless_method


class SupportValidationError(ConstructionInputError):
    def __init__(self,message,diagnostics):
        super().__init__(message)
        self.code="unsupported_buried_restore"
        self.diagnostics=diagnostics


def support_required(asset):
    if trenchless_method(asset):return False
    construction=asset.get("construction",{})
    pipe=asset.get("kind") in {"pipe","pressure_pipe","siphon"} or asset.get("section_type")=="circular_siphon"
    closed=asset.get("section_type") in {"rectangular_culvert","arch_culvert","circular_culvert"}
    return (closed or pipe and construction.get("installation_mode")=="buried") and construction.get("target_mode")=="restore_terrain"


def _finite(value,label):
    if value is None or isinstance(value,bool):raise ValueError(label+" 未知")
    value=float(value)
    if not math.isfinite(value):raise ValueError(label+" 缺测或非有限值")
    return value


def inspect_section_support(asset,record):
    if not support_required(asset):return {"applicable":False,"passed":True,"checked_contacts":0,"diagnostics":[]}
    common={"asset_id":record.get("asset_id",asset.get("asset_id")),"station":record.get("station"),
            "side":record.get("side","right"),"mode":"buried_restore_terrain"}
    diagnostics=[];clearances=[];fill_supported=0
    try:
        ground=[(_finite(x,"地面偏距"),_finite(z,"地面高程")) for x,z in record.get("ground_points",[])]
        if len(ground)<2 or any(b[0]<=a[0] for a,b in zip(ground,ground[1:])):raise ValueError("原地面折线未知或偏距不递增")
        positions=[x for x,z in ground]
        def ground_at(x):
            if not positions[0]<=x<=positions[-1]:raise ValueError("支承足迹超出已知原地面，禁止外推")
            j=bisect_right(positions,x)-1
            if j==len(ground)-1:return ground[j][1]
            x0,z0=ground[j];x1,z1=ground[j+1]
            return z0+(x-x0)/(x1-x0)*(z1-z0)
        structure=record.get("structure_geometry") or {}
        pipes=structure.get("pipes")
        if asset.get("section_type","").startswith("circular") and not pipes:raise ValueError("真实逐管外底未知")
        measured_data=(record.get("construction_geometry") or {}).get("measured")
        if measured_data is None:raise ValueError("实际垫层/管座/包封支承几何未知")
        measured=shape(measured_data)
        if not measured.is_valid:raise ValueError("实际支承几何无效")
        if measured.is_empty and _finite(asset.get("construction",{}).get("bedding_thickness"),"垫层厚度")>0:raise ValueError("非零垫层缺实际支承几何")
        contacts=[];footprints=[]
        if not measured.is_empty:
            components=[measured] if measured.geom_type=="Polygon" else list(measured.geoms)
            for component in components:
                if component.is_empty:continue
                if component.geom_type!="Polygon":raise ValueError("实际支承足迹不能解析")
                coords=[(_finite(x,"支承偏距"),_finite(z,"支承高程")) for x,z in component.exterior.coords]
                bottom=min(z for x,z in coords);found=False
                for (x0,z0),(x1,z1) in zip(coords,coords[1:]):
                    if z0==bottom and z1==bottom and x0!=x1:
                        lo,hi=sorted((x0,x1));footprints.append((lo,hi,bottom));contacts.extend((x,bottom,"material_footprint") for x in
                            [lo,*[x for x in positions if lo<x<hi],hi]);found=True
                if not found:raise ValueError("实际支承底部没有可核查的平底足迹")
        elif pipes:
            contacts=[(_finite(p.get("outer_bottom_offset",p.get("offset")),"逐管真实外底足点偏距"),_finite(p.get("outer_bottom"),"逐管真实外底"),"pipe_outer_bottom") for p in pipes]
        else:
            # Flat closed culvert foundations use the actual material foot,
            # including separated wall feet when an arch has no bottom slab.
            material=(structure.get("materials") or {}).get("concrete")
            if material is None:raise ValueError("暗涵真实结构底部未知")
            material=shape(material)
            if material.is_empty or not material.is_valid:raise ValueError("暗涵真实结构底部未知或无效")
            components=[material] if material.geom_type=="Polygon" else list(material.geoms)
            for component in components:
                if component.geom_type!="Polygon":raise ValueError("暗涵实际支承足迹不能解析")
                coords=[(_finite(x,"支承偏距"),_finite(z,"支承高程")) for x,z in component.exterior.coords]
                bottom=min(z for x,z in coords);found=False
                for (x0,z0),(x1,z1) in zip(coords,coords[1:]):
                    if z0==bottom and z1==bottom and x0!=x1:
                        lo,hi=sorted((x0,x1));contacts.extend((x,bottom,"culvert_material_footprint") for x in
                            [lo,*[x for x in positions if lo<x<hi],hi]);found=True
                if not found:raise ValueError("暗涵实际结构底部没有可核查的平底足迹")
        if not contacts:raise ValueError("实际支承接触点未知")
        final_target = None
        final_support = None
        if is_circular_culvert(asset):
            target_data=(record.get("construction_geometry") or {}).get("target")
            if target_data is not None:
                final_target=shape(target_data)
                if not final_target.is_valid:raise ValueError("实际完成土体无效，不能确认填筑支承")
                rounding=256*max(math.ulp(z) for _,z in ground+[(x,z) for x,z,_ in contacts])
                final_support=final_target.buffer(rounding)
                # Verify the whole footing strip, including target-boundary
                # events between natural-ground vertices. A floating pad or
                # an interior gap must not pass by touching sampled points.
                for lo,hi,support in footprints:
                    low=min(support,*(z for _,z in ground))-1.
                    original_soil=Polygon([(positions[0],low),(positions[-1],low),*reversed(ground)])
                    required_fill=box(lo,low,hi,support).difference(original_soil)
                    if not required_fill.is_empty and not final_support.covers(required_fill):
                        diagnostics.append({**common,"code":"floating_buried_support", "offset_start":lo,
                            "offset_end":hi,"support_elevation":support,"contact_kind":"material_footprint_strip",
                            "message":"原地面以上的垫层/管座底部仍有未被实际填筑土体连续覆盖的空隙，不能确认支承"})
        for x,support,kind in contacts:
            terrain=ground_at(x);clearance=terrain-support;clearances.append(clearance)
            rounding=256*max(math.ulp(terrain),math.ulp(support),math.ulp(1.))
            if clearance < -rounding:
                # A separately counted embankment may support a closed round
                # culvert above natural ground. Check the entire vertical
                # column down to actual ground, rather than accepting a top
                # contact or overlooking the gap. Pressure pipes keep their
                # original-ground guard and are never reclassified here.
                column=LineString([(x,terrain),(x,support)])
                if final_support is not None and final_support.covers(column):
                    fill_supported+=1
                    continue
                diagnostics.append({**common,"code":"floating_buried_support","offset":x,
                    "support_elevation":support,"terrain_elevation":terrain,"gap_m":-clearance,
                    "contact_kind":kind,"rounding_bound_m":rounding,
                    "message":"恢复原地面无法支承该埋管/暗涵，请调整完成面/指定覆土，或核对为明管/架空类型；真实轴线与地形保持原值"})
    except (KeyError,TypeError,ValueError,OverflowError,ShapelyError) as error:
        diagnostics.append({**common,"code":"unknown_buried_support","message":str(error)+"；原地面支承不能确认，须补齐后计算"})
    return {"applicable":True,"passed":not diagnostics,"checked_contacts":len(clearances),
            "supported_by_counted_embankment_contacts":fill_supported,
            "minimum_ground_above_support_m":min(clearances) if clearances else None,"diagnostics":diagnostics}


def require_section_support(asset,record):
    report=inspect_section_support(asset,record)
    if not report["passed"]:
        first=report["diagnostics"][0];station=first.get("station")
        label=f" K{station:.3f}" if isinstance(station,(int,float)) else ""
        raise SupportValidationError(f"{asset.get('name',first.get('asset_id','管道'))}{label}：{first['message']}",report["diagnostics"])
    return report


def require_workbench_support(assets,records,*,cancelled=None):
    lookup={asset["asset_id"]:asset for asset in assets};checked=contacts=fill_supported=0;minimum=None
    for record in records:
        if cancelled and cancelled():raise ConstructionInputError("计算已取消，未发布成果")
        asset=lookup.get(record.get("asset_id"))
        if asset is None:raise SupportValidationError("支承核查缺少实际施工对象身份",[{"code":"unknown_support_asset","asset_id":record.get("asset_id")}])
        report=require_section_support(asset,record)
        if report["applicable"]:
            checked+=1;contacts+=report["checked_contacts"]
            fill_supported+=report.get("supported_by_counted_embankment_contacts",0)
            value=report.get("minimum_ground_above_support_m")
            if value is not None:minimum=value if minimum is None else min(minimum,value)
    return {"passed":True,"checked_sections":checked,"checked_contacts":contacts,
            "supported_by_counted_embankment_contacts":fill_supported,
            "minimum_ground_above_support_m":minimum,"scope":"buried_pipe_and_closed_culvert_restore_support",
            "pipe_crown_may_be_exposed":True,"axis_and_original_terrain_unchanged":True}
