"""File identity and serialized input boundary for whole-route quantities."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from .network_alignment import NetworkAlignment
from .independent_project import input_hash, terrain_identity
from .construction_rules import normalize_construction_inputs
from ..models.terrain import TINModel


def load_network(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    data = json.loads(raw.decode("utf-8-sig"))
    if data.get("schema_version") != "1.0" or not isinstance(data.get("assets"), list):
        raise ValueError("请选择版本1.0的完整全线输入JSON")
    data["alignment"] = NetworkAlignment.from_dict(data["alignment"])
    return data, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def serialize_network(network):
    from .earthwork_scope import serializable_trenchless_facts, trenchless_method
    result = deepcopy({k: v for k, v in network.items() if k != "alignment"})
    alignment = network.get("alignment")
    result["alignment"] = alignment.to_dict() if isinstance(alignment, NetworkAlignment) else deepcopy(alignment)
    for i, asset in enumerate(result.get("assets", [])):
        if trenchless_method(asset):
            result["assets"][i] = serializable_trenchless_facts(asset)
    normalize_construction_inputs(result)
    return result


def validate_network_extent(network):
    alignment = network["alignment"]
    rows = network.get("assets") or []
    identifiers = [row.get("asset_id") for row in rows]
    if not rows or any(not value for value in identifiers) or len(set(identifiers)) != len(identifiers):
        raise ValueError("全线结构编号必须完整且唯一")
    if any(not row.get("enabled", True) for row in rows):
        raise ValueError("全线输入含未启用结构，不能将遗漏对象的数量发布为全线成果")
    spans = sorted((float(a["station_start"]), float(a["station_end"])) for a in rows)
    cursor = alignment.start_station
    for start, end in spans:
        if not math.isfinite(start+end) or end <= start or start < alignment.start_station-1e-7 or end > alignment.end_station+1e-7:
            raise ValueError("全线结构范围无效或越出解析路线")
        if start > cursor+1e-7:
            raise ValueError(f"全线桩号 {cursor:.3f} 至 {start:.3f} 未分配结构或连接段")
        cursor = max(cursor, end)
    if cursor < alignment.end_station-1e-7:
        raise ValueError("全线末端仍有未分配施工范围")


def select_network_terrain(tin, network, width=100.0, *, cancelled=None):
    """Conservative face selection; retain complete original triangles."""
    import shapely
    if not math.isfinite(width) or width <= 0:
        raise ValueError("全线地形预选宽度必须为正")
    alignment = network["alignment"]
    # The exact arcs lie within 5m of these chord bounds, well inside this
    # conservative margin. The calculator still verifies actual daylight.
    # Collections contain separate real elements. A line between two route
    # endpoints is not a construction corridor and must not select distant
    # terrain or introduce fictitious connections into spatial preparation.
    paths=[]
    for e in alignment.elements:
        n=max(1,math.ceil(e["length"]/min(5.,width/4)))
        if e["kind"]=="line":
            xy=np.asarray([e["start_xy"],e["end_xy"]])
        else:
            angles=e["start_angle"]+np.linspace(0,e["sweep_angle"],n+1)
            xy=np.asarray(e["center_xy"])+e["radius"]*np.column_stack([np.cos(angles),np.sin(angles)])
        paths.append(shapely.LineString(xy).buffer(width+5.))
    footprint = shapely.union_all(paths)
    shapely.prepare(footprint)
    chosen = []
    for start in range(0, len(tin.triangles), 100_000):
        if cancelled and cancelled():
            raise ValueError("已取消全线地形预选")
        faces = tin.triangles[start:start+100_000]
        xy = tin.points[faces, :2]
        lo, hi = xy.min(axis=1), xy.max(axis=1)
        bounds = shapely.box(lo[:, 0], lo[:, 1], hi[:, 0], hi[:, 1])
        selected = shapely.intersects(footprint, bounds)
        if selected.any():
            chosen.append(start+np.flatnonzero(selected))
    if not chosen:
        from .workbench_scope import AssetDataPending
        raise AssetDataPending("全线范围内没有原地形三角片，请核对坐标和单位",code="missing_terrain")
    face_ids = np.concatenate(chosen)
    original_faces = tin.triangles[face_ids]
    used, inverse = np.unique(original_faces, return_inverse=True)
    local = TINModel(tin.points[used].copy(), inverse.reshape(-1, 3),
                     source_files=list(tin.source_files), source_mtimes=list(tin.source_mtimes))
    local.import_report = {**deepcopy(getattr(tin, "import_report", {})),
                           "selection": {"kind": "whole_original_faces_near_exact_route",
                                         "margin_m": width+5.0, "selected_faces": len(face_ids),
                                         "selected_vertices": len(used), "retriangulated": False}}
    local.original_face_indices = face_ids
    return local


def _terrain_failure_text(error, assets):
    from .workbench_diagnostics import restore_workbench_diagnostics
    rows=restore_workbench_diagnostics(getattr(error,"diagnostics",None),assets,
        coordinate_basis="internal",code=getattr(error,"code",None),message=str(error))
    return "；".join(dict.fromkeys(row["message"] for row in rows)) or str(error)


def _stop_terrain_expansion(error, network, selected, width, original_faces, reason):
    """Preserve the actual exception and expose its original route station."""
    from .workbench_diagnostics import restore_workbench_error
    restore_workbench_error(error,network["assets"],coordinate_basis="internal")
    limited=bool(getattr(selected,"import_report",{}).get("corridor_preparation"))
    if limited:
        reason=reason.replace("原始三角片","已导入三角片").replace("原始测区","当前计算地形")
    context={"width_m":float(width),"selected_faces":len(selected.triangles),
             "original_faces":int(original_faces),"reason":reason,
             "terrain_scope":"source_corridor" if limited else "full_import"}
    error.terrain_search=context
    if (getattr(error,"code",None)=="missing_terrain_or_invalid_section"
            and any(phrase in str(error) for phrase in ("未接地","未与地面相交","超出有效地形","有效地形范围"))):
        error.code="section_terrain_unavailable"
    for row in getattr(error,"diagnostics",[]):
        row["terrain_search"]=deepcopy(context)
        if limited:row["message"]="当前计算地形范围不足："+row["message"]
    error.args=(f"地形预选宽度 {width:g}m：{reason}；{error}",)
    raise error


def _probe_original_section(tin, network, error, accuracy, *, cancelled=None):
    """Check only the failing section against every crossing original face.

    A full-terrain STRtree can be enormous. The vectorized half-plane filter
    retains complete original triangles crossing this one section line, across
    the entire measured extent, then builds only that small section index.
    """
    from .network_section_calculator import _Sections, _profile, NetworkSectionCalculationError
    from .network_section_projection import Catalog
    row=next((d for d in getattr(error,"diagnostics",[]) if isinstance(d,dict)
              and d.get("asset_id") and d.get("station") is not None),None)
    if row is None:return None
    asset=next((a for a in network["assets"] if a["asset_id"]==row["asset_id"]),None)
    if asset is None or not asset.get("workbench_geometry"):return None
    asset=deepcopy(asset);station=float(row["station"]);side=row.get("side","right")
    alignment=network["alignment"]
    profiles=[_profile(asset,network)]
    origin=np.asarray(alignment.get_xy_at_station(alignment.start_station))
    catalog=Catalog(alignment,[asset],origin,{asset["asset_id"]:0.})
    part=catalog.parts[catalog.part_at(asset["asset_id"],station,side)]
    center,tangent,_=catalog.center_tangent_curvature(part["part_id"],station)
    world=center+origin
    tolerance=max(1e-7,float(np.max(np.abs(world)))*np.finfo(float).eps*64)
    chosen=[]
    for start in range(0,len(tin.triangles),100_000):
        if cancelled and cancelled():raise ValueError("已取消失败断面的原地形核查")
        faces=tin.triangles[start:start+100_000]
        distances=(tin.points[faces,:2]-world)@tangent
        intersects=(distances.min(axis=1)<=tolerance)&(distances.max(axis=1)>=-tolerance)
        if intersects.any():chosen.append(start+np.flatnonzero(intersects))
    if not chosen:
        missing=deepcopy(row)
        if getattr(tin,"import_report",{}).get("corridor_preparation"):
            missing["message"]="该断面未穿越已导入的地形三角片"
        else:
            missing["message"]="该断面未穿越原始测量三角片，须补充真实地形"
        raise NetworkSectionCalculationError(missing["message"],code="section_terrain_unavailable",diagnostics=[missing])
    face_ids=np.concatenate(chosen)
    used,inverse=np.unique(tin.triangles[face_ids],return_inverse=True)
    section_tin=TINModel(tin.points[used].copy(),inverse.reshape(-1,3),
                         source_files=list(tin.source_files),source_mtimes=list(tin.source_mtimes))
    section_tin.original_face_indices=face_ids
    evaluator=_Sections(section_tin,alignment,[asset],profiles,int(accuracy.get("arc_segments",64)))
    evaluator.catalog=catalog
    value=evaluator.exact(part,station,side)
    bounds=value["domain"].bounds
    return max(abs(bounds[0]),abs(bounds[2]))+1.


def retry_network_terrain_selection(tin, network, selected, width, width_limit, error,
                                   accuracy, probed_sections, *, cancelled=None, progress=None):
    """Expand a temporary selection only after ruling out real source absence."""
    expandable=getattr(error,"code",None)=="section_terrain_unavailable" or any(phrase in str(error) for phrase in
        ("未接地","未与地面相交","超出有效地形","有效地形范围"))
    if not expandable:raise error
    detail=_terrain_failure_text(error,network["assets"])
    terrain_scope="当前计算地形" if getattr(tin,"import_report",{}).get("corridor_preparation") else "原始测区"
    if progress:progress("terrain",0.,f"地形预选宽度 {width:g}m；{detail}；核查{terrain_scope}")
    if len(selected.triangles)>=len(tin.triangles):
        _stop_terrain_expansion(error,network,selected,width,len(tin.triangles),"已覆盖全部原始三角片，继续扩宽不能补足地形")
    if width>=width_limit:
        _stop_terrain_expansion(error,network,selected,width,len(tin.triangles),"已达到原始测区最大搜索范围")
    rows=getattr(error,"diagnostics",[]) or []
    key=next(((d.get("asset_id"),d.get("station"),d.get("side","right")) for d in rows
              if isinstance(d,dict) and d.get("asset_id") and d.get("station") is not None),None)
    needed=None
    if key is not None and key not in probed_sections:
        probed_sections.add(key)
        try:
            needed=_probe_original_section(tin,network,error,accuracy,cancelled=cancelled)
        except ValueError as original_error:
            if cancelled and cancelled():raise
            _stop_terrain_expansion(original_error,network,selected,width,len(tin.triangles),
                                   "已用全部原始测区核查失败断面，仍不能形成有效施工断面")
    expanded=min(max(width*2,needed or 0.),width_limit)
    following=select_network_terrain(tin,network,expanded,cancelled=cancelled)
    previous_ids=getattr(selected,"original_face_indices",None)
    following_ids=getattr(following,"original_face_indices",None)
    if previous_ids is not None and following_ids is not None and np.array_equal(previous_ids,following_ids):
        _stop_terrain_expansion(error,network,selected,expanded,len(tin.triangles),
                               "扩宽后原始三角片未增加，继续重算不能补足地形")
    next_step="单断面核查当前计算地形后扩大预选" if terrain_scope=="当前计算地形" else "原测区单断面核查后扩大预选"
    if progress:progress("terrain",0.,f"地形预选宽度 {width:g}→{expanded:g}m；{detail}；{next_step}")
    return following,expanded


def calculate_network_request(tin, network, *, accuracy=None, cancelled=None, progress=None,
                              keep_solids=True, method="sections", collect_deferrals=False):
    if method != "sections":
        raise ValueError("土石方工作台只允许断面法，旧实体算量入口已停用")
    from app_渠系计算前端.runtime_platform import ensure_safe_windows_platform_queries
    ensure_safe_windows_platform_queries()
    frozen = serialize_network(network)
    restored = deepcopy(frozen)
    restored["alignment"] = NetworkAlignment.from_dict(frozen["alignment"])
    validate_network_extent(restored)
    accuracy = ({"profile_step":20.,"chord_tolerance":.04,"relative_tolerance":.01,
                 "absolute_tolerance":10.,**dict(accuracy or {}),"overlap_policy":"independent_sections",
                 "sampling_mode":"fixed","max_refinements":0,"lateral_refinement":False}
                if method == "sections" else dict(accuracy or {}))
    width = float(accuracy.pop("terrain_selection_width", 100.0))
    from .earthwork_scope import trenchless_method
    from .network_section_calculator import calculate_network_sections
    selected = None
    if all(trenchless_method(asset) for asset in restored["assets"]):
        tin = None
        result = calculate_network_sections(tin, restored, cancelled=cancelled, progress=progress,
                                            keep_sections=True, **accuracy)
    else:
        if tin is None:
            raise ValueError("含明挖断面的工程须先读取天然地形")
        selected = select_network_terrain(tin, restored, width, cancelled=cancelled)
        width_limit=math.hypot(tin.get_bbox()[2]-tin.get_bbox()[0],tin.get_bbox()[3]-tin.get_bbox()[1])+1
        probed_sections=set()
        while True:
            try:
                result = calculate_network_sections(selected, restored, cancelled=cancelled, progress=progress,
                                                    keep_sections=True, collect_deferrals=collect_deferrals, **accuracy)
                break
            except ValueError as error:
                if not any(a.get("workbench_geometry") for a in restored["assets"]):raise
                selected,width=retry_network_terrain_selection(tin,restored,selected,width,width_limit,error,
                    accuracy,probed_sections,cancelled=cancelled,progress=progress)
    payload = result.to_dict()
    from .network_section_calculator import section_result_publishable
    if not section_result_publishable(payload):
        from .network_section_calculator import NetworkSectionCalculationError
        raise NetworkSectionCalculationError("全线算量未收敛，不能发布部分成果",code="not_converged",
            diagnostics=[c for c in result.convergence_history[-1]["checks"] if not c["passed"] and c.get("admission_required",True)])
    identity = deepcopy(getattr(tin, "import_report", {}))
    if identity.get("path") and identity.get("source_sha256"):
        from ..io.independent_terrain import file_sha256
        if file_sha256(identity["path"]) != identity["source_sha256"]:
            raise ValueError("计算期间源地形已变化，请重新读取并计算")
    snapshot = {"network": frozen, "accuracy": {**accuracy, "terrain_selection_width": width}}
    if method == "sections":
        from .network_section_calculator import FIXED_SAMPLING_CONTRACT
        snapshot["calculation_method"] = method
        if not result.validation.get("trenchless_only"):
            snapshot["fixed_sampling_contract"] = FIXED_SAMPLING_CONTRACT
    payload.update(schema_version="1.0", kind="network", units="m", status="READY",
                   test_only=bool(frozen.get("test_only")), inputs=snapshot, terrain=identity,
                   input_hash=input_hash(snapshot, terrain_identity(identity)))
    if selected is not None:
        payload["terrain_selection"]=selected.import_report["selection"]
    if method == "sections":
        payload.setdefault("method", "exact_tin_actual_midpoint_section_integration")
        payload.setdefault("integration_method", payload["method"])
    json.dumps(payload, ensure_ascii=False, allow_nan=False)
    return result, payload
