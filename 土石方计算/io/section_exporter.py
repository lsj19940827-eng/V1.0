"""Save section-area quantities and optional terrain/section drawings.

The quantity record is independent of the drawing exporters. No solid model,
mesh closure check or three-dimensional Boolean is used here.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
import shutil

import numpy as np
from filesystem_paths import filesystem_path, resolved_path

METHOD = "exact_tin_actual_midpoint_section_integration"
VOLUMES = ("excavation_volume", "backfill_volume", "embankment_volume", "total_fill_volume")
MATERIAL_VOLUMES = ("concrete_volume", "bedding_volume")
ROLE_NAMES = {"excavation": "天然开挖", "backfill": "结构周边回填", "embankment": "新增填筑"}
COLORS = {"ground": (100, 100, 100, 255), "permanent": (40, 40, 40, 255),
          "excavation": (210, 55, 45, 255), "backfill": (215, 160, 25, 255),
          "embankment": (45, 115, 205, 255), "construction": (40, 155, 150, 255),
          "route": (145, 65, 170, 255)}


def sha(path):
    with filesystem_path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _source_records(payload, *, include_terrain_provenance=True):
    values=[payload.get("terrain",{}),payload.get("network_file",{})]
    terrain=payload.get("terrain") or {}
    if terrain.get("cache_path"):
        values.append({"path":terrain["cache_path"],"sha256":terrain.get("cache_sha256")})
    inputs = payload.get("inputs") or {}
    choice = inputs.get("terrain_choice") or {}
    source_hash = terrain.get("source_sha256")
    snapshot_source = (source_hash and Path(terrain.get("path") or "").suffix.lower() == ".npz"
                       and choice.get("cache_file_sha256") == choice.get("loaded_source_sha256") == source_hash)
    # A bound mesh snapshot is the adopted input. The original CAD filename
    # records where it was built and may no longer exist on this computer.
    def visit(node):
        if isinstance(node,dict):
            if node.get("path") and (node.get("sha256") or node.get("source_sha256")):values.append(node)
            for key, value in node.items():
                if node is choice and key == "original_source" and snapshot_source and not include_terrain_provenance:
                    continue
                visit(value)
        elif isinstance(node,list):
            for value in node:visit(value)
    visit(inputs);return values


def _verify_sources(payload):
    from ..services.drawing_bindings import validate_active_bindings
    validate_active_bindings((payload.get("inputs") or {}).get("workbench") or {},raise_on_error=True)
    verified={}
    for source in _source_records(payload, include_terrain_provenance=False):
        # sha256 fingerprints this resource's actual bytes; source_sha256 can
        # identify its parent DXF and is only the legacy fallback.
        expected = source.get("sha256") or source.get("source_sha256")
        if source.get("path") and expected:
            path=resolved_path(source["path"])
            # Route files can be referenced by both the network and workbench
            # snapshots. Cache only within this check: the post-write check
            # must still read the actual bytes again.
            if path not in verified:verified[path]=sha(path)
            if verified[path]!=expected:
                raise ValueError("源文件已改变，请重新计算后导出")


def _role(section, role):
    return section.get("roles", {}).get(role, {})


def _csv(payload, path, table):
    from .structure_quantity_tables import (exclusion_label, save_structure_csv, trenchless_csv_rows,
                                             trenchless_summary_columns)
    if table == "structure_summary":
        return save_structure_csv(payload, path)
    from .network_exporter import structure_label
    from .workbench_drawings import layered_scope_note,layered_volume_columns,section_sampling_note,special_material_scope_note
    from .quantity_policy import overlap_policy_note
    from ..services.sluice_gate import GATE_QUANTITY_METHOD
    sections = payload.get("sections", [])
    records = payload.get("segments", []) if table == "segments" else sections
    layer_columns=layered_volume_columns(payload)
    layer_roles=[(key.removesuffix("_volume"),name) for key,name in layer_columns if key!="unclassified_excavation_volume"]
    layer_note=layered_scope_note(payload)
    special_note=special_material_scope_note(payload)
    bore_columns=trenchless_summary_columns(payload)
    bore_rows=trenchless_csv_rows(payload)
    gate_items = [item for item in payload.get("quantity_items", []) if item.get("method") == GATE_QUANTITY_METHOD]
    component_columns={}
    for item in payload.get("quantity_items",[]):
        if item.get("component_id") not in {"concrete","bedding"}:
            key=(item["component_id"],item.get("material",""),item.get("grade",""),item["unit"])
            component_columns.setdefault(key,item)
    def component_values(row,*,section=False):
        values={}
        for item in row.get("quantity_components" if section else "quantity_items",[]):
            key=(item["component_id"],item.get("material",""),item.get("grade",""),item["unit"])
            value=item.get("section_measure") if section else item.get("quantity")
            if value is not None:values[key]=values.get(key,0.)+float(value)
        return [values.get(key) for key in component_columns]
    def component_headers(*,section=False,physical=False):
        return [("土方几何基准 " if physical and special_note else "")+str(item.get("name",key[0]))+" "+str(item.get("grade", ""))+" "+
                (("断面积m²" if key[3]=="m3" else "铺设展开长m") if section else
                 {"m3":"m³","m2":"m²"}.get(key[3],key[3])) for key,item in component_columns.items()]
    physical_material_names=(["衬砌/结构混凝土（土方几何基准）","垫层（土方几何基准）"] if special_note else ["衬砌/结构混凝土","垫层"])
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        concrete_summary="衬砌/结构混凝土（土方几何基准）" if special_note and payload.get("soil_basis_material_totals") else "衬砌/结构混凝土"
        from ..services.workbench_scope import deferred_scope_note
        partial_note=deferred_scope_note(payload)
        title=partial_note or ("全线TEST算量" if payload.get("test_only") else "全线工程量")
        total="本次已计合计" if partial_note else "全线合计"
        writer.writerow([title, *ROLE_NAMES.values(), "总填方",concrete_summary,"垫层",*[name for _,name in layer_columns],*component_headers(),*[name for _,name in bore_columns]])
        writer.writerow([total+("（各列单位）" if component_columns else " m³"), *(payload[key] for key in VOLUMES),*(payload.get(key) for key in MATERIAL_VOLUMES),*(payload.get(key) for key,_ in layer_columns),*component_values(payload),*(payload.get(key) for key,_ in bore_columns)])
        method_row=["计算方法",payload.get("integration_method",METHOD)]
        if (payload.get("validation") or {}).get("sampling_mode")=="fixed":method_row.append(section_sampling_note(payload))
        policy_note=overlap_policy_note(payload)
        if policy_note:method_row.extend(["重叠计量口径",policy_note])
        writer.writerow(method_row);writer.writerow(["输入摘要", payload.get("input_hash", "")])
        writer.writerow(["地形摘要", payload.get("terrain", {}).get("source_sha256", "")]);writer.writerow([])
        if layer_note:writer.writerow(["简化分层及计量范围",layer_note])
        if special_note:writer.writerow(["材料与土方采用依据",special_note+"；以下逐对象、逐桩或分段的材料列为土方几何基准，正式采用后材料见全线合计及特殊材料明细。"])
        excluded=payload.get("excluded_assets",[])
        if excluded:
            writer.writerow([exclusion_label(payload),"来源施工类型","起桩 m","止桩 m","未计原因","排除规则"])
            for item in excluded:
                writer.writerow([item.get("name",item.get("asset_id","")),item.get("construction_method",item.get("source_type","")),
                    item.get("station_start"),item.get("station_end"),item.get("reason",""),item.get("rule",item.get("code",""))])
        writer.writerows(bore_rows)
        if gate_items:
            writer.writerow(["闸", "流量段号", "起桩 m", "止桩 m", "分项", "工程量 m³"])
            for item in gate_items:
                writer.writerow([item["asset_name"], item.get("flow_section"), item["station_start"],
                                 item["station_end"], item["name"], item["quantity"]])
        if table == "assets":
            writer.writerow(["对象编号", "名称", "类型", "起桩 m", "止桩 m", "真长 m", "天然开挖 m³", "结构周边回填 m³", "新增填筑 m³", "总填方 m³",*[name+" m³" for name in physical_material_names],*[name+" m³" for _,name in layer_columns],*component_headers(physical=True)])
            for row in payload.get("rows", payload.get("assets", [])):
                writer.writerow([row["asset_id"], row.get("name", ""), structure_label(payload, row),
                    row["station_start"], row["station_end"], row.get("length", row["station_end"]-row["station_start"]),
                    *(row[key] for key in VOLUMES),*(row.get(key) for key in MATERIAL_VOLUMES),*(row.get(key) for key,_ in layer_columns),*component_values(row)])
        elif table == "sections":
            writer.writerow(["断面编号", "对象编号", "桩号 m", "线元编号", "单侧取值", "中心X m", "中心Y m", "切向X", "切向Y", "右侧曲率 1/m", "设计高程 m",
                *[name+suffix for name in ROLE_NAMES.values() for suffix in ("面积 m²", "横向一阶矩 m³", "曲线修正面积 m²")],*[name+"面积 m²" for name in physical_material_names],*[name+suffix for _,name in layer_roles for suffix in ("面积 m²", "横向一阶矩 m³", "曲线修正面积 m²")],*(["假定覆盖层竖直厚度 m"] if layer_roles else []),*component_headers(section=True,physical=True)])
            for row in records:
                xy, tangent = row.get("center_xy", [None, None]), row.get("tangent", [None, None])
                if isinstance(tangent, (int, float)):tangent = [math.cos(tangent), math.sin(tangent)]
                writer.writerow([row["section_id"], row["asset_id"], row["station"], row.get("primitive_id", ""), row.get("side", ""),
                    *xy, *tangent, row.get("curvature_right"), row.get("design_elevation"),
                    *[value for role in ROLE_NAMES for value in (_role(row, role).get("area"), _role(row, role).get("first_moment_u"), _role(row, role).get("weighted_area"))],
                    *(row.get("material_areas",{}).get(key) for key in ("concrete","bedding")),
                    *[value for role,_ in layer_roles for value in (_role(row,role).get("area"),_role(row,role).get("first_moment_u"),_role(row,role).get("weighted_area"))],
                    *([(row.get("geology") or {}).get("thickness")] if layer_roles else []),*component_values(row,section=True)])
        elif table == "segments":
            writer.writerow(["对象编号", "起桩 m", "止桩 m", "中桩 m", "段长 m", "起点断面", "中点断面", "终点断面", "天然开挖 m³", "结构周边回填 m³", "新增填筑 m³", "总填方 m³",*[name+" m³" for name in physical_material_names], "积分公式",*[name+" m³" for _,name in layer_columns],*component_headers(physical=True)])
            for row in records:
                writer.writerow([row["asset_id"], row["station_start"], row["station_end"], row.get("mid_station"),
                    row.get("length", row["station_end"]-row["station_start"]), row.get("start_section_id"), row.get("mid_section_id"), row.get("end_section_id"),
                    *(row[key] for key in VOLUMES),*(row.get(key) for key in MATERIAL_VOLUMES), row.get("integration_rule", ""),*(row.get(key) for key,_ in layer_columns),*component_values(row)])
        else:raise ValueError("CSV表类型须为assets、sections、segments或structure_summary")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        saved = list(csv.reader(stream))
    expected = len(payload.get("rows", payload.get("assets", []))) if table == "assets" else len(records)
    if len(saved) != expected+7+bool(layer_note)+bool(special_note)+(len(excluded)+1 if excluded else 0)+len(bore_rows)+len(gate_items)+bool(gate_items):raise ValueError("CSV保存后的记录数改变")
    return {"table": table, "record_count": expected, "saved_record_count_exact": True}


def _display_sections(payload, interval=25.):
    groups = {}
    for section in payload.get("sections", []):groups.setdefault(section["asset_id"], []).append(section)
    chosen = []
    for values in groups.values():
        values = sorted(values, key=lambda row: (row["station"], str(row.get("side", "")), str(row["section_id"])))
        selected = {0, len(values)-1, min(range(len(values)), key=lambda i: abs(values[i]["station"]-(values[0]["station"]+values[-1]["station"])/2))}
        last = -math.inf
        for i, section in enumerate(values):
            if section["station"]-last >= interval:selected.add(i);last=section["station"]
        chosen.extend(values[i] for i in sorted(selected))
    return sorted(chosen, key=lambda row: (row["station"], row["asset_id"], str(row["section_id"])))


def _polygons(geometry):
    from shapely.geometry import shape
    if not geometry:return []
    value = shape(geometry)
    if value.is_empty:return []
    if value.geom_type == "Polygon":return [value]
    return [polygon for child in getattr(value, "geoms", []) for polygon in _polygons(child.__geo_interface__)]


def _drawing_paths(section):
    paths = []
    for role in ROLE_NAMES:
        for polygon in _polygons(_role(section, role).get("geometry")):
            paths.extend((role, np.asarray(ring.coords, dtype=float), True) for ring in [polygon.exterior, *polygon.interiors])
    for role, geometry in section.get("construction_geometry", {}).items():
        layer = "permanent" if role == "permanent" else "construction"
        for polygon in _polygons(geometry):
            paths.extend((layer, np.asarray(ring.coords, dtype=float), True) for ring in [polygon.exterior, *polygon.interiors])
    if paths:
        left = min(float(p[:, 0].min()) for _, p, _ in paths)-2
        right = max(float(p[:, 0].max()) for _, p, _ in paths)+2
    else:left, right = -25., 25.
    current = []
    for point in section.get("ground_points", []):
        if point[1] is None or not math.isfinite(float(point[1])):
            if len(current)>1:paths.extend(_clip_ground(current,left,right))
            current=[]
        else:current.append(point)
    if len(current)>1:paths.extend(_clip_ground(current,left,right))
    return paths


def _clip_ground(points, left, right):
    from shapely.geometry import LineString, box
    line = LineString(points);zmin=min(p[1] for p in points)-1;zmax=max(p[1] for p in points)+1
    clipped=line.intersection(box(left,zmin,right,zmax))
    values=[clipped] if clipped.geom_type=="LineString" else getattr(clipped,"geoms",[])
    return [("ground",np.asarray(part.coords,dtype=float),False) for part in values if part.geom_type=="LineString" and len(part.coords)>1]


def _world(section, points):
    tangent=section.get("tangent")
    if isinstance(tangent,(int,float)):tx,ty=math.cos(tangent),math.sin(tangent)
    elif tangent is not None:tx,ty=map(float,tangent)
    else:tx,ty=math.cos(section["tangent_angle"]),math.sin(section["tangent_angle"])
    xy=section["center_xy"]
    return np.column_stack((xy[0]+points[:,0]*ty,xy[1]-points[:,0]*tx,points[:,1]))


class DrawingExportError(ValueError):
    """A drawing could not be generated or verified from a valid quantity snapshot."""


def _dxf(payload,path,*,drawing_options=None):
    from ezdxf.lldxf.const import DXFError
    from shapely.errors import GEOSException
    from .workbench_drawings import save_dxf
    options={"concise":True,"include_plan":False,"include_profile":False,**dict(drawing_options or {})}
    try:
        metadata = save_dxf(payload, path, **options)
    except (ValueError, DXFError, GEOSException) as error:
        raise DrawingExportError(str(error)) from error
    metadata["concise"]=bool(options["concise"])
    return metadata


def _legacy_dxf(payload,path):
    import ezdxf
    from ezdxf import bbox
    document=ezdxf.new("R2013");document.units=6;document.appids.new("QX_SECTION_AREA")
    for name,color in {"ground":8,"permanent":7,"construction":4,"excavation":1,"backfill":2,"embankment":5}.items():
        document.layers.new(name,dxfattribs={"color":color})
    model=document.modelspace();views=[]
    for section in _display_sections(payload):
        paths=_drawing_paths(section)
        if not paths:continue
        left=min(float(p[:,0].min()) for _,p,_ in paths);right=max(float(p[:,0].max()) for _,p,_ in paths)
        bottom=min(float(p[:,1].min()) for _,p,_ in paths);top=max(float(p[:,1].max()) for _,p,_ in paths)
        title=f"{'TEST ' if payload.get('test_only') else ''}{section['asset_id']} S={section['station']:.3f} Z0={bottom:.3f}"
        views.append((section,paths,left,right,bottom,top,title,max(right-left,len(title)*.3),top-bottom+1.5))
    widths=[max((view[7] for i,view in enumerate(views) if i%4==col),default=0) for col in range(4)]
    xstarts=[0.]
    for width in widths[:-1]:xstarts.append(xstarts[-1]+width+2)
    ystarts=[0.]
    for start in range(0,len(views),4):ystarts.append(ystarts[-1]-max(v[8] for v in views[start:start+4])-2)
    records=[]
    for index,(section,paths,left,right,bottom,top,title,width,height) in enumerate(views):
        x,y=xstarts[index%4],ystarts[index//4];tag=str(section["section_id"])
        for layer,points,closed in paths:
            entity=model.add_lwpolyline([(float(u-left+x),float(z-top+y)) for u,z in points],close=closed,dxfattribs={"layer":layer})
            entity.set_xdata("QX_SECTION_AREA",[(1000,tag)])
        title_entity=model.add_text(title,dxfattribs={"height":.25,"insert":(x,y-(top-bottom)-.75)})
        title_entity.set_xdata("QX_SECTION_AREA",[(1000,tag)])
        records.append({"section_id":section["section_id"],"asset_id":section["asset_id"],"station":section["station"],"base_elevation":bottom,"view_id":tag})
    document.saveas(path);saved=ezdxf.readfile(path)
    if saved.audit().errors:raise ValueError("保存后的断面DXF审计失败")
    groups={}
    for entity in saved.modelspace():
        if entity.has_xdata("QX_SECTION_AREA"):groups.setdefault(entity.get_xdata("QX_SECTION_AREA")[0].value,[]).append(entity)
    if set(groups)!=set(str(row["section_id"]) for row in records):raise ValueError("保存后的断面DXF分组改变")
    bounds=[]
    for record in records:
        extent=bbox.extents(groups[str(record["section_id"])])
        if not extent.has_data:raise ValueError("保存后的断面DXF缺少范围")
        bounds.append([extent.extmin.x,extent.extmin.y,extent.extmax.x,extent.extmax.y])
    for i,a in enumerate(bounds):
        for b in bounds[i+1:]:
            if min(a[2],b[2])-max(a[0],b[0])>1e-8 and min(a[3],b[3])-max(a[1],b[1])>1e-8:
                raise ValueError("保存后的断面DXF排版重叠")
    return {"saved_reopened":True,"audit_errors":0,"display_interval_m":25.,"display_section_count":len(records),
            "complete_section_count":len(payload.get("sections",[])),"sections":records,"saved_view_bounds":bounds,"saved_no_overlap":True}


def _model(payload,path):
    import rhino3dm as rhino
    from tools.terrain_mesh_reader.reader import read_mesh
    source=Path(payload["terrain"]["path"])
    if source.suffix.lower()!=".3dm":raise ValueError("地形与断面展示3DM需要原地形3DM文件")
    document=rhino.File3dm.Read(str(source))
    if document is None:raise ValueError("无法读取原地形3DM")
    original_ids={str(obj.Attributes.Id) for obj in document.Objects}
    original_mesh_count=sum(isinstance(obj.Geometry,rhino.Mesh) for obj in document.Objects)
    layers={}
    for key,color in COLORS.items():
        layer=rhino.Layer();layer.Name="断面法 · "+({**ROLE_NAMES,"ground":"原地形断面","permanent":"设计外包","construction":"施工轮廓","route":"设计路线"}[key]);layer.Color=color
        layers[key]=document.Layers.Add(layer)
    expected=[];selected=_display_sections(payload)
    def add(points,layer,name):
        points=np.asarray(points,dtype=np.float64)
        if len(points)>1:points=points[np.r_[True,np.any(points[1:]!=points[:-1],axis=1)]]
        if len(points)<2:return
        attributes=rhino.ObjectAttributes();attributes.LayerIndex=layers[layer];attributes.Name=name
        attributes.SetUserString("qx_section_method",METHOD);attributes.SetUserString("qx_section_role",layer)
        identity=document.Objects.AddPolyline([rhino.Point3d(*point) for point in points],attributes)
        expected.append((identity,points))
    route=[]
    for section in selected:
        for layer,points,_ in _drawing_paths(section):add(_world(section,points),layer,f"{section['section_id']} S={section['station']:.3f}")
        route.append([*section["center_xy"],section["design_elevation"]])
    add(route,"route","设计路线（采样展示）")
    document.Strings["qx_quantity_method"]=METHOD
    document.Strings["qx_integration_method"]=payload.get("integration_method",METHOD)
    from .workbench_drawings import section_sampling_note
    document.Strings["qx_sampling_note"]=section_sampling_note(payload)
    document.Strings["qx_input_hash"]=payload["input_hash"]
    document.Strings["qx_model_purpose"]="原地形与设计、施工、挖填断面曲线展示；数量取自二维面积沿路线积分"
    if not document.Write(str(path),8):raise ValueError("断面展示3DM保存失败")
    saved=rhino.File3dm.Read(str(path))
    if saved is None or not original_ids.issubset({str(obj.Attributes.Id) for obj in saved.Objects}):raise ValueError("展示模型原对象身份改变")
    for identity,points in expected:
        obj=saved.Objects.FindId(identity)
        polyline=None if obj is None else obj.Geometry.TryGetPolyline()
        actual=None if polyline is None else np.asarray([[p.X,p.Y,p.Z] for p in polyline],dtype=np.float64)
        if actual is None or not np.array_equal(actual,points):raise ValueError("展示断面曲线保存后坐标改变")
    for index in range(original_mesh_count):
        before,before_faces,_=read_mesh(source,mesh_index=index)
        after,after_faces,_=read_mesh(path,mesh_index=index)
        if not np.array_equal(before,after) or not np.array_equal(before_faces,after_faces):raise ValueError("展示模型改变了原地形坐标或三角面")
    return {"saved_reopened":True,"model_purpose":"terrain_and_section_curves_only","quantity_requires_closed_solids":False,
            "display_interval_m":25.,"display_section_count":len(selected),"complete_section_count":len(payload.get("sections",[])),
            "added_curve_count":len(expected),"saved_curve_xyz_exact":True,"full_original_terrain_exact":True,
            "original_object_ids_preserved":True,"original_mesh_count":original_mesh_count}


def export_section_result(payload,path,calculation=None,*,table=None,drawing_options=None,cancelled=None,channel_name="",write_audit=True):
    def check_cancelled():
        if cancelled and cancelled():raise InterruptedError("成果导出已取消")
    check_cancelled()
    from ..services.network_section_calculator import section_result_publishable
    from ..services.sluice_gate import GATE_QUANTITY_METHOD
    validation=payload.get("validation") or {}
    trenchless_only=validation.get("trenchless_only") is True
    gate_only = validation.get("sluice_gate_only") is True
    method=payload.get("trenchless_excavation_policy") if trenchless_only else METHOD
    if gate_only:
        method = GATE_QUANTITY_METHOD
    if payload.get("method")!=method or not section_result_publishable(payload):
        raise ValueError("只能导出已完成的固定间距成果或已收敛的自适应断面法成果")
    from .quantity_policy import require_independent_section_export
    require_independent_section_export(payload)
    if payload.get("defined_scope") and payload.get("partial_acceptance") is not True:
        raise ValueError("局部范围成果须明确标记局部验收后导出")
    if payload.get("kind")=="workbench":
        from ..services.workbench_identity import result_contract_is_current
        if not result_contract_is_current(payload):
            raise ValueError("断面算法已更新，请重新计算后导出；历史断面和数量仍保留")
        from ..services.pipe_axis_continuity import require_pipe_axis_continuity
        require_pipe_axis_continuity((payload.get("inputs") or {}).get("workbench", {}))
    display_path = resolved_path(path)
    path = filesystem_path(display_path, extended=True)
    if trenchless_only and path.suffix.lower() not in {".json", ".csv", ".xlsx"}:
        raise ValueError("非开挖洞挖成果请选择Excel、CSV或JSON")
    if gate_only and path.suffix.lower() not in {".json", ".csv", ".xlsx"}:
        raise ValueError("闸结构工程量可导出为Excel、CSV或JSON")
    if validation.get("automatic_terrain_unmeasured_only") and path.suffix.lower() not in {".json", ".csv", ".xlsx"}:
        raise ValueError("地形缺测区段清单可导出为Excel、CSV或JSON")
    if validation.get("automatic_tunnel_exposed_only") and path.suffix.lower() not in {".json", ".csv", ".xlsx"}:
        raise ValueError("隧洞露顶待计区段清单可导出为Excel、CSV或JSON")
    _verify_sources(payload);path.parent.mkdir(parents=True,exist_ok=True)
    sidecar=path.with_suffix(path.suffix+".audit.json")
    targets=(path,sidecar) if write_audit else (path,)
    for original in (item.get("path") for item in _source_records(payload)):
        if not original:
            continue
        source = filesystem_path(resolved_path(original), extended=True)
        if any(target == source or target.exists() and source.is_file() and target.samefile(source)
               for target in targets):
            raise ValueError("成果须另存，不能覆盖原地形或全线输入")
    if table is None:table="sections" if "断面" in path.stem else "segments" if "积分" in path.stem or "逐段" in path.stem else "assets"
    from .output_staging import output_staging
    with output_staging(path.parent) as temporary:
        temporary=Path(temporary);staged=temporary/("result"+path.suffix.lower())
        if path.suffix.lower()==".json":
            serialized=json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False)
            staged.write_text(serialized,encoding="utf8")
            if json.loads(staged.read_text(encoding="utf8"))!=json.loads(serialized):raise ValueError("JSON保存后记录改变")
            metadata={"saved_reopened":True,"all_records_exact":True}
        elif path.suffix.lower()==".csv":metadata=_csv(payload,staged,table)
        elif path.suffix.lower()==".dxf":metadata=_dxf(payload,staged,drawing_options=drawing_options)
        elif path.suffix.lower()==".xlsx":
            from .concise_quantities import save_concise_xlsx
            metadata=save_concise_xlsx(payload,staged,channel_name=channel_name)
        elif path.suffix.lower()==".3dm":metadata=_model(payload,staged)
        else:raise ValueError("断面法成果请选择JSON、CSV、Excel或DXF")
        if payload.get("defined_scope") and path.suffix.lower() in {".dxf", ".xlsx"}:
            if metadata.get("concise") or (drawing_options or {}).get("envelopes_only") or (drawing_options or {}).get("opening_only"):
                metadata.update(defined_scope=payload["defined_scope"],partial_acceptance=True)
            else:
                from .scope_annotations import annotate_saved_scope
                metadata=annotate_saved_scope(payload,staged,metadata)
        if not write_audit:
            _verify_sources(payload)
            check_cancelled()
            staged.replace(path)
            return str(display_path)
        accuracy=(payload.get("inputs") or {}).get("accuracy",{})
        report={**metadata,"path":str(display_path),"sha256":sha(staged),"input_hash":payload["input_hash"],"method":method,
                "integration_method":payload.get("integration_method",method),
                "sampling_mode":None if trenchless_only or gate_only else validation.get("sampling_mode",accuracy.get("sampling_mode","adaptive")),
                "profile_step_m":None if trenchless_only or gate_only else accuracy.get("profile_step"),
                "convergence_checked":validation.get("convergence_checked",bool(payload.get("converged"))),
                "converged":bool(payload.get("converged")),
                "quantity_method_independent_of_3D_export":True,"terrain_sha256":payload.get("terrain",{}).get("source_sha256")}
        from ..services.workbench_scope import deferred_scope_metadata
        report.update(deferred_scope_metadata(payload))
        audit=temporary/'audit.json';audit.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf8")
        _verify_sources(payload)
        check_cancelled()
        old=temporary/'previous';old_audit=temporary/'previous_audit'
        existed,existed_audit=path.exists(),sidecar.exists()
        if existed:shutil.copy2(path,old)
        if existed_audit:shutil.copy2(sidecar,old_audit)
        committed=False
        try:staged.replace(path);committed=True;audit.replace(sidecar)
        except BaseException:
            if committed:
                if existed:old.replace(path)
                else:path.unlink(missing_ok=True)
                if existed_audit:old_audit.replace(sidecar)
                else:sidecar.unlink(missing_ok=True)
            raise
    return str(display_path)
