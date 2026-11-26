"""One section-only calculation boundary for route collections and flat pits."""
from __future__ import annotations

from copy import deepcopy
import json
import math

import numpy as np
from shapely.geometry import LineString, mapping

from .contracts import ConstructionInputError
from .workbench_diagnostics import TerrainSourceChanged
from .construction_rules import normalize_construction_inputs
from .earthwork_scope import (trenchless_exclusion, trenchless_method, require_disjoint_trenchless_ranges,
                              trenchless_excavation_quantities, trenchless_exclusions, current_exclusion_records,
                              serializable_trenchless_facts, is_trenchless_exclusion, trenchless_live_route_id)
from .network_alignment import NetworkAlignment
from .network_project import serialize_network, calculate_network_request
from .network_section_calculator import (calculate_network_sections, _Sections, _profile,
                                        _net_section, _split_backfill, polygon_metrics, _section_structure_fields,
                                        BACKFILL_VOLUME_KEYS,
                                        section_result_publishable, trenchless_only_result)
from .independent_project import input_hash, terrain_identity
from .sluice_gate import GATE_QUANTITY_METHOD, is_sluice_gate, workbench_gate_quantities
from .workbench_scope import AssetDataPending, DEFERRED_FIELD, DEFERRED_SCOPE, missing_construction_fields, tunnel_deferrals

SUPPORTED={"trapezoidal_channel","compound_trapezoidal_channel","rectangular_channel","u_channel","rectangular_culvert",
           "circular_culvert","arch_culvert","circular_siphon","circular_channel","rectangular_pit",
           "aqueduct_u","aqueduct_rectangular","arch_tunnel","circular_tunnel","flat_bottom_tunnel","horseshoe_tunnel"}
DEFAULT_ACCURACY={"sampling_mode":"fixed","profile_step":20.,"relative_tolerance":.03,"absolute_tolerance":50.,
                  "max_refinements":0,"arc_segments":64,"lateral_step":1.,"chord_tolerance":.04,
                  "terrain_event_policy":"regular","material_joint_policy":"section_union",
                  "overlap_policy":"independent_sections",
                  "per_asset_relative_tolerance":.05,"per_asset_absolute_tolerance":100.,"lateral_refinement":False}


def _outside_unbound_pipe(asset):
    pipe = asset.get("kind") in {"pipe","pressure_pipe","siphon"} or asset.get("section_type") == "circular_siphon"
    mode = asset.get("construction", {}).get("installation_mode", "buried")
    return pipe and mode in {"exposed","elevated","above_ground","open"} and not asset.get("section_scheme_binding")


def asset_requires_section_terrain(asset):
    return (asset.get("enabled", True) and not asset.get(DEFERRED_FIELD) and asset.get("section_type") in SUPPORTED
            and asset.get("section_type") != "rectangular_pit" and asset.get("kind") != "pit"
            and not trenchless_method(asset) and not _outside_unbound_pipe(asset))


def workbench_requires_section_terrain(inputs):
    """Match the ordinary scope of the workbench before opening a terrain file."""
    from .workbench_automatic_ranges import has_workbench_automatic_ranges
    if has_workbench_automatic_ranges(inputs):
        return True
    networks = inputs.get("networks", [inputs])
    return any(asset_requires_section_terrain(asset) for network in networks for asset in network.get("assets", []))


def _collection(value):
    if "networks" in value:
        result=deepcopy({key:item for key,item in value.items() if key!="networks"})
        result["networks"]=[serialize_network(n) for n in value.get("networks",[])]
        result.setdefault("pits",[]);result.setdefault("excluded",[])
        result["excluded"]=[serializable_trenchless_facts(record) if is_trenchless_exclusion(record) else record
                            for record in result["excluded"]]
        return result
    return {"networks":[serialize_network(value)],"pits":[],"excluded":[],"diagnostics":[]}


def _shift_profile(asset, delta):
    for key in ("profile_points",):
        for p in asset.get(key,[]):
            p["station"]+=delta
    for p in asset.get("alignment",{}).get("profile_points",[]):
        p["station"]+=delta
    if asset.get("design_profile"):
        for e in asset["design_profile"].get("elements",[]):
            for k in ("station_start","station_end","center_station"):
                if k in e:e[k]+=delta


def _pit_elements(element, asset):
    """Split at all physical material/shape discontinuities, without tiny spans."""
    from .pit_sections import pit_config, offset_at_height
    cfg=pit_config(asset); section=asset["section"]; c=asset.get("construction",{})
    positions={element["station_start"],element["station_end"]}
    local=asset["pit_local_start"]
    ext=float(c.get("bedding_extension",0))
    for half in (cfg["length"]/2,float(section.get("foundation_length",0))/2,
                 float(section.get("foundation_length",0))/2+ext):
        for x in (-half,half):
            s=asset["station_start"]+x-local
            if element["station_start"]<s<element["station_end"]:positions.add(s)
    for member in asset.get("associated_pier_occupancy",[]):
        for key in ("local_start","local_end"):
            s=asset["station_start"]+float(member[key])-local
            if element["station_start"]<s<element["station_end"]:positions.add(s)
    for side,direction in (("front",1),("back",-1)):
        height=0.
        for grade in cfg["grades"][side][:-1]:
            height+=grade.height
            for upper in (False,True):
                x=direction*(cfg["length"]/2+offset_at_height(cfg["grades"][side],height,upper_side=upper))
                s=asset["station_start"]+x-local
                if element["station_start"]<s<element["station_end"]:positions.add(s)
    result=[]; a=np.asarray(element["start_xy"]);b=np.asarray(element["end_xy"])
    for start,end in zip(sorted(positions),sorted(positions)[1:]):
        part=deepcopy(element);part.update(station_start=start,station_end=end,length=end-start)
        part["start_xy"]=(a+(b-a)*(start-element["station_start"])/element["length"]).tolist()
        part["end_xy"]=(a+(b-a)*(end-element["station_start"])/element["length"]).tolist()
        result.append(part)
    return result


def prepare_workbench_inputs(tin, inputs, *, include_independent_pits=False, collect_deferrals=False):
    """Internal stations order ownership only; returned records restore source stations."""
    source=_collection(inputs); elements=[];assets=[];excluded=current_exclusion_records(source.get("excluded",[]))
    source["pits"]=[p for p in source.get("pits",[]) if not p.get("generated_aqueduct_foundation")]
    normalize_construction_inputs(source)
    for raw in source["networks"]:
        active = [asset for asset in raw.get("assets", []) if not asset.get(DEFERRED_FIELD)
                  and asset.get("pipe_profile_choice") != "pending_gap"]
        route_keys = {raw.get(key) for key in ("route_id", "source_identity", "network_id") if raw.get(key)}
        scoped = [dict(record, route_id=None) for record in
                  trenchless_exclusions({"networks": [], "excluded":excluded})
                  if record.get("route_id") in route_keys]
        if scoped:
            require_disjoint_trenchless_ranges([dict(asset, route_id=None) for asset in active]+scoped)
        else:
            require_disjoint_trenchless_ranges(active)
    from .default_section_schemes import ensure_default_section_schemes
    source,defaults=ensure_default_section_schemes(source)
    if defaults["errors"]:
        raise ConstructionInputError("；".join(defaults["errors"]))
    seen=set(); cursor=0.;pending=[]
    has_gates = False
    for ni, raw in enumerate(source["networks"]):
        route_id=str(raw.get("route_id",raw.get("network_id",raw.get("name",f"route-{ni+1}"))))
        originals=[]
        for original in raw.get("assets", []):
            if is_sluice_gate(original):
                has_gates |= bool(original.get("enabled", True))
                continue
            if original.get("pipe_profile_choice") == "pending_gap":
                from .pipe_profile_partitions import pending_gap_record
                excluded.append(pending_gap_record(original,route_id))
                continue
            if original.get("enabled",True) and original.get(DEFERRED_FIELD):
                excluded.append(deepcopy(original[DEFERRED_FIELD]))
                continue
            non_open_cut=trenchless_exclusion(original,route_id=trenchless_live_route_id(raw) or route_id)
            if non_open_cut:
                excluded.append(non_open_cut)
            else:
                originals.append(original)
        if not originals:
            continue
        alignment=NetworkAlignment.from_dict(raw["alignment"]) if raw.get("alignment") is not None else None
        delta=cursor-alignment.start_station if alignment is not None else 0.
        if alignment is not None:
            for e in alignment.elements:
                e=deepcopy(e);e["station_start"]+=delta;e["station_end"]+=delta
                e["route_id"]=route_id;elements.append(e)
        for original in originals:
            if original.get("section_type") in {"box_foundation","rectangular_pit"} or original.get("kind")=="pit":
                if not include_independent_pits:
                    excluded.append({"asset_id":original.get("asset_id"),"route_id":route_id,"name":original.get("name"),
                        "section_type":original.get("section_type","rectangular_pit"),"station_start":original.get("station_start"),"station_end":original.get("station_end"),
                        "reason":"用户已确认首版暂不计闸基/独立基坑，原数据保留，数量未计量", "code":"pit_deferred_first_version",
                        "original_asset_snapshot":deepcopy(original)})
                    continue
                if not original.get("enabled",True):
                    excluded.append({"asset_id":original.get("asset_id"),"name":original.get("name"),
                        "section_type":original.get("section_type"),"reason":"施工对象已禁用","original_asset_snapshot":deepcopy(original)})
                    continue
                if alignment is None:raise ConstructionInputError("基坑缺少实际平面轴线")
                from .pit_sections import legacy_gate_as_pit
                pit=legacy_gate_as_pit(original,alignment) if original.get("section_type")=="box_foundation" else deepcopy(original)
                source["pits"].append(pit)
                continue
            pipe=original.get("kind") in {"pipe","pressure_pipe","siphon"} or original.get("section_type")=="circular_siphon"
            installation=original.get("construction",{}).get("installation_mode","buried")
            outside=_outside_unbound_pipe(original)
            if original.get("section_type") not in SUPPORTED or not original.get("enabled",True) or outside:
                excluded.append({"asset_id":original.get("asset_id"),"route_id":route_id,
                                 "name":original.get("name"),"section_type":original.get("section_type"),
                                 "station_start":original.get("station_start"),"station_end":original.get("station_end"),
                                 "installation_mode":installation,
                                 "reason":"用户选择本次不计量" if not original.get("enabled",True) else
                                          "明/架空管道基础未纳入首版施工范围" if outside else "未纳入首版施工范围"});continue
            if alignment is None:
                raise ConstructionInputError(f"{original.get('name',original['asset_id'])}：缺少实际平面轴线")
            from .aqueduct_frames import validate_aqueduct_frame_generation
            validate_aqueduct_frame_generation(original,tin,alignment=raw["alignment"])
            try:
                if pipe:
                    from .section_geometry import pipe_specs
                    pipe_specs(original.get("section") or {},require_material=True)
                    if original.get("construction",{}).get("installation_mode") is None:
                        raise ConstructionInputError("缺少 construction.installation_mode，须明确埋管/明管/架空")
                missing = missing_construction_fields(original, check_tunnel_section=collect_deferrals)
                if missing:
                    raise ConstructionInputError(f"待补齐 {', '.join(missing)}")
            except ConstructionInputError as error:
                message = f"{original.get('name', original['asset_id'])}：{error}"
                if not collect_deferrals:
                    raise ConstructionInputError(message) from error
                pending.append({"code": "missing_construction", "asset_id": original["asset_id"],
                                "route_id": route_id, "message": message})
                continue
            a=deepcopy(original);old_id=a["asset_id"]
            identifier=old_id if old_id not in seen else f"{route_id}::{old_id}"
            if identifier in seen:raise ConstructionInputError("施工对象来源身份重复")
            seen.add(identifier);a["asset_id"]=identifier
            from .dedicated_structure_geometry import aqueduct_foundation_pits
            generated=aqueduct_foundation_pits(original,alignment,route_id=route_id,parent_asset_id=identifier)
            if generated:
                source["pits"].extend(generated)
                removed={item["parent_component_id"] for item in generated}
                a["shared_foundation_footprints"]=[deepcopy(member) for member in original["section"].get("discrete_components",[])
                    if member["component_id"] in removed]
                for member in a["shared_foundation_footprints"]:
                    for key in ("station_start","station_end"):member[key]+=delta
                a["section"]["discrete_components"]=[member for member in a["section"].get("discrete_components",[])
                    if member["component_id"] not in removed]
                a["section"]["component_specs"]=[spec for spec in a["section"].get("component_specs",[])
                    if spec.get("component_id") not in removed]
                a["generated_foundation_ids"]=[item["asset_id"] for item in generated]
            a.update(original_asset_id=old_id,route_id=route_id,station_offset=delta,workbench_geometry=True)
            a["station_start"]+=delta;a["station_end"]+=delta
            _shift_profile(a,delta)
            for member in a.get("section",{}).get("discrete_components",[]):
                for key in ("station_start","station_end"):
                    if member.get(key) is not None:member[key]+=delta
            from .dedicated_structure_geometry import register_dedicated_components
            register_dedicated_components(a)
            assets.append(a)
        if alignment is not None:cursor+=alignment.total_length
    if pending:
        raise AssetDataPending("存在施工参数待补的对象",code="recoverable_asset_inputs",diagnostics=pending)
    for pi, original in enumerate(source.get("pits",[])):
        if not include_independent_pits and not original.get("generated_aqueduct_foundation"):
            excluded.append({"asset_id":original.get("asset_id",original.get("pit_id")),"name":original.get("name"),
                "section_type":original.get("section_type","rectangular_pit"),"code":"pit_deferred_first_version",
                "reason":"用户已确认首版暂不计闸基/独立基坑，原数据保留，数量未计量", "original_asset_snapshot":deepcopy(original)})
            continue
        from .pit_sections import pit_route
        a=deepcopy(original);a.setdefault("section_type","rectangular_pit")
        if not a.get("enabled",True):
            excluded.append({"asset_id":a.get("asset_id"),"name":a.get("name"),"section_type":a["section_type"],"reason":"施工对象已禁用"})
            continue
        identifier=a.get("asset_id",f"pit-{pi+1}")
        if identifier in seen:raise ConstructionInputError("基坑与渠道对象身份重复")
        seen.add(identifier);a["asset_id"]=identifier
        e,cfg,lo=pit_route(a,tin,station_start=cursor)
        a.update(station_start=cursor,station_end=e["station_end"],pit_local_start=lo,
                 original_asset_id=identifier,route_id="independent_pits",station_offset=cursor-lo,
                 workbench_geometry=True,kind="pit")
        a["profile_points"]=[{"station":cursor,"elevation":cfg["floor"]},
                             {"station":e["station_end"],"elevation":cfg["floor"]}]
        e["route_id"]=a["route_id"]
        elements.extend(_pit_elements(e,a));assets.append(a);cursor=e["station_end"]
    from .unmeasured_terrain_scope import AUTOMATIC_TERRAIN_GAP_CODE
    if (not assets and not has_gates and not trenchless_exclusions({"networks": [], "excluded":excluded})
            and not any(r.get("code") in {"automatic_unsupported_pipe_range", AUTOMATIC_TERRAIN_GAP_CODE}
                        for r in excluded) and not tunnel_deferrals(excluded)):
        deferred=[row for row in excluded if row.get("scope_status")=="automatic_deferred"]
        if deferred:
            raise AssetDataPending("当前没有资料完整的计量对象，详见各对象待补原因",
                                   code="no_ready_assets",diagnostics=[dict(row,message=row["reason"]) for row in deferred])
        raise ConstructionInputError("没有参数完整且纳入本期的施工对象")
    # These separate physical elements have no connecting geometry. Their
    # internal continuous numbers are never exposed as surveyed chainage.
    network={"schema_version":"1.0","alignment":NetworkAlignment(elements,[],start_station=0) if elements else None,
             "assets":assets,"test_only":any(n.get("test_only") for n in source["networks"]),
             "calculation_scope":"included_assets","excluded_assets":excluded}
    return source,network,excluded


def _restore_record_coordinates(payload, assets):
    lookup={a["asset_id"]:a for a in assets}
    for table in ("rows","assets","sections","segments"):
        for record in payload.get(table,[]):
            a=lookup[record["asset_id"]];delta=a["station_offset"]
            record["route_id"]=a["route_id"];record["original_asset_id"]=a["original_asset_id"]
            for k in ("station","station_start","station_end","mid_station"):
                if k in record:record[k]-=delta
            for item in record.get("quantity_items",[]):
                for key in ("station_start","station_end"):
                    if key in item:item[key]-=delta
            if a["section_type"]=="rectangular_pit":
                record["coordinate_kind"]="pit_local_slice"
                if "station" in record:record["local_position"]=record["station"]
    for item in payload.get("quantity_items",[]):
        if item.get("method") == GATE_QUANTITY_METHOD:
            continue
        asset=lookup[item["asset_id"]]
        item["route_id"]=asset["route_id"]
        item["original_asset_id"]=asset["original_asset_id"]
        for key in ("station_start","station_end"):
            if key in item:item[key]-=asset["station_offset"]
    for diagnostic in payload.get("diagnostics",[]):
        for record in diagnostic.get("affected_locations",[]):
            asset=lookup.get(record.get("asset_id"))
            if asset:
                record["route_id"]=asset["route_id"]
                for key in ("station","station_start","station_end"):
                    if key in record:record[key]-=asset["station_offset"]
    return payload


def calculate_workbench(tin, workbench_inputs, *, accuracy=None, cancelled=None, progress=None,
                        include_independent_pits=False, collect_deferrals=False, split_tunnel_exposure=False):
    from .workbench_diagnostics import restore_workbench_error
    from .drawing_bindings import validate_active_bindings
    from .slope_support_quantities import calculate_slope_support_quantities
    from .unmeasured_terrain_scope import AUTOMATIC_TERRAIN_GAP_CODE
    from .workbench_automatic_ranges import prepare_workbench_automatic_ranges, unmeasured_only_result
    # Reject malformed schedule data before the expensive terrain/section run.
    # Missing cross-slope construction remains an explicit partial-scope issue.
    calculate_slope_support_quantities(workbench_inputs)
    if workbench_inputs.get("drawing_binding_issues"):
        raise ConstructionInputError("原图绑定与当前设计存在待核项，请重新绑定对应区段后算量")
    validate_active_bindings(workbench_inputs,raise_on_error=True)
    from .section_scheme_bindings import validate_section_scheme_bindings
    validate_section_scheme_bindings(workbench_inputs,raise_on_error=True)
    if workbench_inputs.get("special_pipe_materials"):
        from .special_pipe_materials import validate_special_pipe_materials
        validate_special_pipe_materials(workbench_inputs,raise_on_error=True)
    if cancelled and cancelled():raise ConstructionInputError("计算已取消，未发布成果")
    # Recalculation uses the current measurement contract. Saved settings must
    # not reactivate refinement or deduct overlaps between independent cuts.
    settings={**DEFAULT_ACCURACY,**dict(accuracy or {}),"sampling_mode":"fixed",
              "max_refinements":0,"lateral_refinement":False,"overlap_policy":"independent_sections"}
    settings.pop("terrain_selection_width",None)
    workbench_inputs=prepare_workbench_automatic_ranges(tin,workbench_inputs,settings,
        cancelled=cancelled,progress=progress,collect_deferrals=collect_deferrals)
    source,network,excluded=prepare_workbench_inputs(tin,workbench_inputs,
        include_independent_pits=include_independent_pits,collect_deferrals=collect_deferrals)
    from .tunnel_exposure_scope import TUNNEL_EXPOSED_FIELD, apply_tunnel_exposure, exposed_tunnel_only_result
    if (collect_deferrals or split_tunnel_exposure) and tin is not None and network["assets"]:
        from .tunnel_exposure import find_tunnel_exposure
        try:
            ranges = find_tunnel_exposure(tin, network, settings, cancelled=cancelled, progress=progress)
        except ValueError as error:
            restore_workbench_error(error, network["assets"], coordinate_basis="internal")
            raise
        if ranges:
            source, report = apply_tunnel_exposure(source, ranges)
            if progress:
                progress("construction", 0., f"{report['range_count']} 处隧洞露顶待计，共 {report['total_length_m']:.3f} m，其余洞段继续计量。")
            source, network, excluded = prepare_workbench_inputs(tin, source,
                include_independent_pits=include_independent_pits, collect_deferrals=collect_deferrals)
    # A default section binding adds its own digest/count metadata. That alone
    # is not a hydraulic/construction basis and must not create one only when
    # the same defaults were applied before entering this function.
    basis = source.get("quantity_basis") or {}
    if any(key not in {"section_scheme_binding_sha256", "section_scheme_binding_count"} for key in basis):
        from .construction_defaults import refresh_quantity_basis
        refresh_quantity_basis(source)
    ready_payload=None
    gate_takeoff = workbench_gate_quantities(source)
    if not network["assets"]:
        if TUNNEL_EXPOSED_FIELD in source:
            result = exposed_tunnel_only_result(excluded, test_only=network["test_only"])
        elif any(row.get("code")==AUTOMATIC_TERRAIN_GAP_CODE for row in excluded):
            result=unmeasured_only_result(excluded,test_only=network["test_only"],cancelled=cancelled)
        elif any(row.get("code")=="automatic_unsupported_pipe_range" for row in excluded):
            from .unsupported_pipe_calculation import unsupported_only_result
            result=unsupported_only_result(excluded,test_only=network["test_only"],cancelled=cancelled)
        elif gate_takeoff[0] and trenchless_excavation_quantities(excluded).get("trenchless_excavation_volume") is None:
            from .network_section_calculator import NetworkSectionCalculationResult
            quantities = dict.fromkeys(("excavation_volume", "backfill_volume", "embankment_volume",
                                        "concrete_volume", "bedding_volume", "total_fill_volume"), 0.)
            result = NetworkSectionCalculationResult(quantities, [], [], [], [],
                {"converged": False, "convergence_checked": False, "sluice_gate_only": True,
                 "integration_method": GATE_QUANTITY_METHOD, "overlap_policy": "independent_sections"},
                test_only=network["test_only"], method=GATE_QUANTITY_METHOD, excluded_assets=excluded,
                quantity_items=gate_takeoff[0])
            tin = None
        elif gate_takeoff[1] and not trenchless_exclusions({"networks": [], "excluded": excluded}):
            raise AssetDataPending("闸施工参数待补", code="no_ready_assets", diagnostics=gate_takeoff[1])
        else:
            result=trenchless_only_result(excluded,test_only=network["test_only"],cancelled=cancelled)
            tin=None
    elif tin is None:
        raise ConstructionInputError("含明挖断面的工程须先读取天然地形")
    elif len(source["networks"])==1 and not source.get("pits") and not excluded:
        try:
            result,ready_payload=calculate_network_request(tin,network,accuracy=settings,cancelled=cancelled,
                progress=progress,method="sections",collect_deferrals=collect_deferrals)
        except ValueError as error:
            restore_workbench_error(error,network["assets"],coordinate_basis="internal")
            raise
    else:
        from .network_project import select_network_terrain, retry_network_terrain_selection
        width=100.;bbox=tin.get_bbox();limit=math.hypot(bbox[2]-bbox[0],bbox[3]-bbox[1])+1
        selected=select_network_terrain(tin,network,width,cancelled=cancelled)
        probed_sections=set()
        while True:
            try:
                result=calculate_network_sections(selected,network,cancelled=cancelled,progress=progress,
                    keep_sections=True,**settings)
                break
            except ValueError as error:
                try:
                    selected,width=retry_network_terrain_selection(tin,network,selected,width,limit,error,
                        settings,probed_sections,cancelled=cancelled,progress=progress)
                except ValueError as final_error:
                    restore_workbench_error(final_error,network["assets"],coordinate_basis="internal")
                    raise
    return _finalize_workbench(tin,source,network,excluded,result,settings,
        ready_payload=ready_payload,cancelled=cancelled,progress=progress,
        gate_takeoff=gate_takeoff,
        include_independent_pits=include_independent_pits,
        split_tunnel_exposure=collect_deferrals or split_tunnel_exposure,
        terrain_selection=deepcopy(selected.import_report.get("selection",{})) if "selected" in locals() else None)


def _finalize_workbench(tin,source,network,excluded,result,settings,*,ready_payload=None,
        cancelled=None,progress=None,include_independent_pits=False,terrain_selection=None,
        split_tunnel_exposure=False, gate_takeoff=None):
    """One source/ground/support/identity boundary for live and retained sampling."""
    from .workbench_diagnostics import restore_workbench_error
    payload = ready_payload if ready_payload is not None else result.to_dict()
    if not section_result_publishable(payload):
        from .network_section_calculator import NetworkSectionCalculationError
        error=NetworkSectionCalculationError("断面工程量未收敛，不能发布当前成果",code="not_converged",
            diagnostics=[c for c in result.convergence_history[-1]["checks"] if not c["passed"] and c.get("admission_required",True)])
        restore_workbench_error(error,network["assets"],coordinate_basis="internal")
        raise error
    if cancelled and cancelled():raise ConstructionInputError("计算已取消，未发布成果")
    identity=deepcopy(getattr(tin,"import_report",{}))
    if identity.get("path") and identity.get("source_sha256"):
        from ..io.independent_terrain import file_sha256
        if file_sha256(identity["path"], cancelled=cancelled)!=identity["source_sha256"]:
            raise TerrainSourceChanged("计算期间源地形改变，须重新读取")
    _restore_record_coordinates(payload, network["assets"])
    bore = trenchless_excavation_quantities(excluded, payload["excavation_volume"])
    payload.update(bore)
    from .aqueduct_components import quantity_rule_items, quantity_scope_issues
    original_assets={}
    for ni,route in enumerate(source["networks"]):
        rid=str(route.get("route_id",route.get("network_id",route.get("name",f"route-{ni+1}"))))
        for original in route.get("assets",[]):
            original_assets[(rid,original["asset_id"])]=original
    source_assets=[]
    for included in network["assets"]:
        if included.get("generated_aqueduct_foundation"):continue
        asset=deepcopy(included)
        delta=asset.get("station_offset",0.)
        for key in ("station_start","station_end"):
            asset[key]-=delta
        for member in asset.get("section",{}).get("discrete_components",[]):
            for key in ("station_start","station_end"):member[key]-=delta
        original=original_assets.get((asset.get("route_id"),asset.get("original_asset_id")))
        if original is not None:
            # Foundation entities run as actual four-sided pits. Preserve
            # their parent declarations for the scope-to-quantity audit.
            for key in ("discrete_components","quantity_rules","quantity_scope_not_applicable"):
                if key in original.get("section",{}):
                    asset.setdefault("section",{})[key]=deepcopy(original["section"][key])
        source_assets.append(asset)
    quantity_items=payload.setdefault("quantity_items",[])
    gate_items, gate_pending = gate_takeoff if gate_takeoff is not None else workbench_gate_quantities(source)
    if not (payload.get("validation") or {}).get("sluice_gate_only"):
        quantity_items.extend(gate_items)
    from .tunnel_exposure_scope import TUNNEL_EXPOSURE_ORIGIN, scope_tunnel_quantity_rules
    tunnel_rules, scope_issues = scope_tunnel_quantity_rules(source, source_assets)
    scope_issues.extend(gate_pending)
    for asset in source_assets:
        if asset.get(TUNNEL_EXPOSURE_ORIGIN):
            rules = tunnel_rules.get(asset["asset_id"], [])
            asset["section"]["quantity_rules"] = [item["input_snapshot"] for item in rules]
        else:
            rules = quantity_rule_items(asset)
        for item in rules:
            item.update(route_id=asset.get("route_id"),original_asset_id=asset.get("original_asset_id"))
            quantity_items.append(item)
        if asset.get("kind")=="tunnel":
            row=next((r for r in payload["assets"] if r["asset_id"]==asset["asset_id"]),None)
            if row is not None:
                c=asset.get("construction",{})
                quantity_items.append({"component_id":"tunnel_overbreak_fill","name":"隧洞超挖环隙填充",
                    "material":c.get("overbreak_material") or "填充材质未明确", "grade":c.get("overbreak_grade") or "",
                    "unit":"m3","method":"excavation_minus_lining_and_shotcrete_section_integration",
                    "asset_id":row["asset_id"],"asset_name":asset.get("name",""),
                    "station_start":asset["station_start"],"station_end":asset["station_end"],
                    "quantity":row["backfill_volume"],"geometry_included":True,"included_in_backfill_volume":True,
                    "status":"current_construction_parameters"})
                if row["backfill_volume"]>1e-8 and not c.get("overbreak_material"):
                    scope_issues.append({"asset_id":asset["asset_id"],"name":asset.get("name"),"message":"隧洞超挖环隙已计体积，填充材质和等级尚未明确"})
        scope_issues.extend(quantity_scope_issues(asset,quantity_items))
        scheme=(asset.get("section_scheme_binding") or {}).get("scheme_snapshot") or {}
        if scheme:
            missing=scheme.get("uncounted_items") or scheme.get("missing_items") or ["钢筋", "止水", "排水", "支护及其他附属项目"]
            for item in missing:
                label=item.get("name",item.get("message",str(item))) if isinstance(item,dict) else str(item)
                message=(label+"：未录入独立支护清单的部分仍未计"
                    if source.get("slope_support_rows") and "支护" in label else label+"：本轮未计")
                scope_issues.append({"asset_id":asset["asset_id"],"name":asset.get("name"),
                    "message":message, "status":"not_counted", "scheme_id":scheme.get("scheme_id")})
    from .slope_support_quantities import calculate_slope_support_quantities
    support_schedule=calculate_slope_support_quantities(source)
    quantity_items.extend(support_schedule["quantity_items"])
    scope_issues.extend(support_schedule["scope_issues"])
    scope_issues.extend({"asset_id":row["asset_id"], "name":row["name"], "status":"pending",
                         "message":f"{row['construction_method']}洞挖量待补资料：{row['issue']}"}
                        for row in bore.get("trenchless_excavation_rows", []) if row["status"]=="pending")
    deferred=[row for row in excluded if row.get("scope_status")=="automatic_deferred"] + tunnel_deferrals(excluded)
    if deferred:
        payload["calculation_deferred_assets"]=deepcopy(deferred)
        scope_issues.extend({**row,"status":"pending","message":row["reason"]} for row in deferred)
    payload["slope_support"]=support_schedule
    payload["quantity_scope_issues"]=scope_issues
    from .unmeasured_terrain_scope import AUTOMATIC_TERRAIN_GAP_CODE
    terrain_gaps = any(row.get("code")==AUTOMATIC_TERRAIN_GAP_CODE for row in excluded)
    payload["quantity_scope_complete"]=not scope_issues and not terrain_gaps
    if source.get("special_pipe_materials"):
        from .special_pipe_materials import (
            build_special_material_baseline_inputs, apply_special_material_quantities,
        )
        reference_inputs,changed=build_special_material_baseline_inputs(source)
        reference_payload=None
        if changed:
            if cancelled and cancelled():raise ConstructionInputError("计算已取消，未发布成果")
            if progress:progress("material_reference",0.,"保留原土方，正在计算一般构造材料参照")
            def reference_progress(stage,fraction,message):
                if progress:progress("material_reference",fraction,"一般构造材料参照："+str(message))
            # This separate run supplies material reference quantities only.
            # Its ground, cut/fill, sections and scheme bindings must never
            # replace the original positioned construction/soil snapshot.
            _,reference_payload=calculate_workbench(tin,reference_inputs,accuracy=settings,
                cancelled=cancelled,progress=reference_progress,
                split_tunnel_exposure=split_tunnel_exposure,
                include_independent_pits=include_independent_pits)
        payload=apply_special_material_quantities(source,payload,baseline_payload=reference_payload)
        quantity_items=payload.get("quantity_items",[])
    payload["all_concrete_volume"]=math.fsum(float(item["quantity"]) for item in quantity_items
        if item.get("unit")=="m3" and ("concrete" in str(item.get("material","")).lower()
            or "shotcrete" in str(item.get("material","")).lower()
            or "混凝土" in str(item.get("material",""))))
    from .support_validation import require_workbench_support
    if progress:progress("validation",1.,"校核实际埋管支承，确认后发布成果")
    try:
        payload["support_validation"]=require_workbench_support(network["assets"],payload["sections"],cancelled=cancelled)
    except ValueError as error:
        restore_workbench_error(error,network["assets"],coordinate_basis="source")
        raise
    from .workbench_identity import terrain_choice,COMPUTATION_CONTRACT
    from .drawing_bindings import validate_active_bindings
    payload["drawing_binding_validation"]=validate_active_bindings(source,raise_on_error=True)
    from .section_scheme_bindings import validate_section_scheme_bindings
    payload["section_scheme_binding_validation"]=validate_section_scheme_bindings(source,raise_on_error=True)
    no_terrain_kind = "not_required_for_sluice_gate_only" if result.validation.get("sluice_gate_only") else "not_required_for_trenchless_only"
    snapshot={"workbench":source,"accuracy":settings,"calculation_method":"sections","calculation_contract":COMPUTATION_CONTRACT,
              "terrain_choice":terrain_choice(tin,identity) if tin is not None else {"kind":no_terrain_kind}}
    if all(key in payload for key in BACKFILL_VOLUME_KEYS):
        snapshot["backfill_partition_policy"] = "pipe_outer_crown_height_v1"
    from .workbench_identity import ENCASEMENT_SIDE_POLICY, measured_encasement_has_left_override
    if measured_encasement_has_left_override(source, payload["sections"]):
        if (payload.get("validation") or {}).get("retained_actual_sampling_reassessed"):
            raise ConstructionInputError("包封设有单独的左侧厚度，请按实际左右侧厚重新算量")
        snapshot["encasement_side_policy"] = ENCASEMENT_SIDE_POLICY
    if settings.get("sampling_mode")=="fixed" and payload["sections"]:
        from .network_section_calculator import FIXED_SAMPLING_CONTRACT
        snapshot["fixed_sampling_contract"]=FIXED_SAMPLING_CONTRACT
    if source.get("quantity_basis"):
        snapshot["quantity_basis"]=deepcopy(source["quantity_basis"])
    if include_independent_pits:snapshot["legacy_independent_pit_API"]=True
    from .tunnel_source_parameters import uses_explicit_tunnel_base,TUNNEL_LINING_GEOMETRY_POLICY
    if uses_explicit_tunnel_base(source):
        snapshot["tunnel_lining_geometry_policy"]=TUNNEL_LINING_GEOMETRY_POLICY
        payload["tunnel_lining_geometry_policy"]=TUNNEL_LINING_GEOMETRY_POLICY
    payload.update(schema_version="1.0",kind="workbench",status="READY",inputs=snapshot,calculation_contract=COMPUTATION_CONTRACT,
                   terrain=identity,input_hash=input_hash(snapshot,terrain_identity(identity)),
                   excluded_assets=excluded,calculation_scope=DEFERRED_SCOPE if deferred else "included_assets",
                   diagnostics=[*payload.get("diagnostics",[]),*source.get("diagnostics",[])])
    from .unsupported_pipe_calculation import attach_automatic_scope
    attach_automatic_scope(payload,source)
    if terrain_gaps:
        from .unmeasured_terrain_scope import AUTOMATIC_TERRAIN_GAP_FIELD, terrain_gap_scope_report
        payload[AUTOMATIC_TERRAIN_GAP_FIELD]=terrain_gap_scope_report(source)
    from .tunnel_exposure_scope import TUNNEL_EXPOSED_FIELD, tunnel_exposure_report
    if TUNNEL_EXPOSED_FIELD in source:
        payload[TUNNEL_EXPOSED_FIELD] = tunnel_exposure_report(source)
    payload["default_section_scheme_policy"]="general_buried_with_explicit_exceptions_1.0"
    if source.get("quantity_basis"):
        payload["quantity_basis"]=deepcopy(source["quantity_basis"])
    payload["materials"]={r:payload.get(r+"_volume",0.) for r in ("concrete","bedding")}
    payload["materials"]["all_concrete"]=payload["all_concrete_volume"]
    if terrain_selection is not None:payload["terrain_selection"]=terrain_selection
    from .survey_support import review_survey_support
    survey_review=review_survey_support(tin,payload["sections"],cancelled=cancelled)
    if survey_review is not None:payload["survey_support"]=survey_review
    json.dumps(payload,ensure_ascii=False,allow_nan=False)
    # The dataclass and payload both expose source coordinates, not internal
    # ownership stations. Input snapshots retain original route geometries.
    result.assets=payload["assets"];result.sections=payload["sections"]
    result.segments=payload["segments"]
    result.quantity_items=deepcopy(payload["quantity_items"])
    if gate_items:
        result.quantities["all_concrete_volume"] = payload["all_concrete_volume"]
    if payload.get("special_pipe_materials_policy"):
        # Newly adopted supports may not exist among the soil solver's roles.
        # Keep the public result object and the serialized quantity table equal.
        result.quantities.update({key:deepcopy(value) for key,value in payload.items()
            if key=="all_concrete_volume" or key.startswith("component__") and key.endswith("_volume")})
    for key in result.quantities:
        if key in payload:result.quantities[key]=deepcopy(payload[key])
    if isinstance(payload.get("quantities"),dict):
        for key in result.quantities:
            if key in payload:payload["quantities"][key]=deepcopy(payload[key])
    result.excluded_assets=deepcopy(excluded)
    result.trenchless_excavation=deepcopy(bore)
    return result,payload


def reassess_workbench_sampling(tin,workbench_inputs,sampling,*,sampling_accuracy,sampling_identity,
        accuracy=None,cancelled=None,progress=None):
    """Reassess recorded engineering checks without resampling or changing quantities.

    The caller supplies the original run's input/terrain/file hashes. Actual
    interval and lateral spacing remain the values in the saved history.
    """
    from pathlib import Path
    from ..io.independent_terrain import file_sha256
    from .network_section_calculator import NetworkSectionCalculationResult
    from .pipe_axis_continuity import require_pipe_axis_continuity
    binding=dict(sampling_identity)
    for key in ("path","sha256","input_path","input_sha256","terrain_sha256"):
        if not binding.get(key):raise ConstructionInputError("实际采样复核缺少原运行绑定："+key)
    if file_sha256(binding["path"])!=binding["sha256"] or file_sha256(binding["input_path"])!=binding["input_sha256"]:
        raise ConstructionInputError("实际采样或原运行输入已改变")
    if json.loads(Path(binding["input_path"]).read_text(encoding="utf-8-sig"))!=workbench_inputs:
        raise ConstructionInputError("复核输入与实际采样运行输入不一致")
    if getattr(tin,"import_report",{}).get("source_sha256")!=binding["terrain_sha256"]:
        raise ConstructionInputError("实际采样与复核地形身份不一致")
    from .default_section_schemes import pending_default_section_assets
    if pending_default_section_assets(workbench_inputs):
        raise ConstructionInputError("未设置特殊范围的管道已采用一般埋管断面，须重新计算，不能沿用旧数量")
    require_pipe_axis_continuity(workbench_inputs,cancelled=cancelled)
    source,network,excluded=prepare_workbench_inputs(tin,workbench_inputs)
    if trenchless_exclusions({"networks": [], "excluded":excluded}):
        raise ConstructionInputError("非开挖洞段采用当前洞挖规则，须重新算量后另存")
    settings={**dict(sampling_accuracy),"relative_tolerance":DEFAULT_ACCURACY["relative_tolerance"],
        "per_asset_relative_tolerance":DEFAULT_ACCURACY["per_asset_relative_tolerance"],
        "per_asset_absolute_tolerance":DEFAULT_ACCURACY["per_asset_absolute_tolerance"],
        "absolute_tolerance":DEFAULT_ACCURACY["absolute_tolerance"],**dict(accuracy or {})}
    recorded_overlap=sampling_accuracy.get("overlap_policy","spatial_union")
    requested_overlap=settings.get("overlap_policy",DEFAULT_ACCURACY["overlap_policy"])
    if recorded_overlap!=requested_overlap:
        raise ConstructionInputError("断面重叠计量口径已改变，须重新计算，不能沿用旧扣重数量")
    settings["overlap_policy"]=requested_overlap
    settings["lateral_refinement"]=bool(sampling_accuracy.get("lateral_refinement",True))
    if sampling.get("validation",{}).get("sampling_mode")=="fixed" or settings.get("sampling_mode")=="fixed":
        raise ConstructionInputError("固定间距成果须重新算量后调整精度设置")
    if settings.get("terrain_event_policy")!="regular":
        raise ConstructionInputError("已存采样复核入口仅用于显式常规工程断面法")
    by_id={r["asset_id"]:r for r in sampling["assets"]}
    if set(by_id)!={a["asset_id"] for a in network["assets"]}:
        raise ConstructionInputError("实际采样施工对象范围与输入不一致")
    for asset in network["assets"]:
        for key in ("station_start","station_end"):
            if not math.isclose(by_id[asset["asset_id"]][key],asset[key],abs_tol=1e-8,rel_tol=0.):
                raise ConstructionInputError("实际采样对象桩号与输入不一致")
    quantities=sampling["quantities"]
    for key,value in quantities.items():
        if not key.endswith("_volume"):
            continue
        amounts = (r.get(key, 0.) for r in by_id.values()) if key in BACKFILL_VOLUME_KEYS else (r[key] for r in by_id.values())
        if not math.isclose(value,math.fsum(amounts),rel_tol=1e-10,abs_tol=1e-6):
            raise ConstructionInputError("实际采样分项与汇总不一致："+key)
    history=deepcopy(sampling["convergence_history"])
    old_abs=float(sampling_accuracy["absolute_tolerance"]);old_rel=float(sampling_accuracy["relative_tolerance"])
    old_asset=float(sampling_accuracy.get("per_asset_relative_tolerance",old_rel))
    old_asset_abs=float(sampling_accuracy.get("per_asset_absolute_tolerance",old_abs))
    for h in history:
        for check in h["checks"]:
            interval=check.get("scope")=="interval"
            previous_rel=old_rel if interval or check["asset_id"]=="GLOBAL" else old_asset
            if previous_rel<=0:raise ConstructionInputError("原采样复算门槛无法解析")
            previous_abs=old_abs if interval or check["asset_id"]=="GLOBAL" else old_asset_abs
            amount=max(0.,(check["allowed_m3"]-previous_abs)/previous_rel)
            relative=settings["relative_tolerance"] if interval or check["asset_id"]=="GLOBAL" else settings["per_asset_relative_tolerance"]
            check["previous_allowed_m3"]=check["allowed_m3"]
            absolute=settings["absolute_tolerance"] if interval or check["asset_id"]=="GLOBAL" else settings["per_asset_absolute_tolerance"]
            check["allowed_m3"]=absolute+relative*amount
            check["passed"]=check["difference_m3"]<=check["allowed_m3"]
            check["admission_required"]=not interval
        required=[c for c in h["checks"] if c["admission_required"]]
        h["passed"]=bool(required) and all(c["passed"] for c in required)
        h["convergence_scope"]="global_and_per_asset"
        h["reference_interval_failed_count"]=sum(not c["passed"] for c in h["checks"] if not c["admission_required"])
    validation={**sampling["validation"],"converged":history[-1]["passed"],
        "global_and_per_asset_convergence":history[-1]["passed"],"convergence_scope":"global_and_per_asset",
        "local_interval_checks_reference_only":True,"relative_tolerance":settings["relative_tolerance"],
        "per_asset_relative_tolerance":settings["per_asset_relative_tolerance"],"per_asset_absolute_tolerance_m3":settings["per_asset_absolute_tolerance"],"absolute_tolerance_m3":settings["absolute_tolerance"],
        "retained_actual_sampling_reassessed":True,"sampling_identity":binding,"original_accuracy":dict(sampling_accuracy)}
    diagnostic={"code":"retained_sampling_engineering_review","severity":"info",
        "message":f"保留已完成的全部实际断面、积分段和数量，不重算。全线按{settings['relative_tolerance']*100:g}%＋{settings['absolute_tolerance']:g}m³、逐对象按{settings['per_asset_relative_tolerance']*100:g}%＋{settings['per_asset_absolute_tolerance']:g}m³重新复核；实际间距见逐轮记录。"}
    retained_diagnostics=[d for d in sampling.get("diagnostics",[]) if d.get("code")!="regular_engineering_sections"]
    result=NetworkSectionCalculationResult(quantities,sampling["assets"],sampling["sections"],sampling["segments"],
        history,validation,diagnostics=[*retained_diagnostics,diagnostic],test_only=bool(network.get("test_only")),
        layered_excavation_scope=deepcopy(sampling.get("layered_excavation_scope",{})))
    payload={**sampling,**quantities,"method":result.method,"integration_method":result.method,"status":"READY" if result.converged else "NOT_CONVERGED",
        "converged":result.converged,"publishable":result.converged,"units":"m","test_only":result.test_only,"rows":[dict(row) for row in result.assets],
        "convergence_history":history,"validation":validation,"diagnostics":result.diagnostics}
    return _finalize_workbench(tin,source,network,excluded,result,settings,ready_payload=payload,cancelled=cancelled,progress=progress)


def query_workbench_section(tin,workbench_inputs,asset_id,station,side="right",accuracy=None,*,include_independent_pits=False):
    from .network_section_projection import Catalog
    from .workbench_diagnostics import restore_workbench_error
    from .section_scheme_bindings import validate_section_scheme_bindings
    from .workbench_automatic_ranges import prepare_workbench_automatic_ranges, skipped_workbench_section
    skipped=skipped_workbench_section(workbench_inputs,asset_id,float(station),side)
    if skipped is not None:
        return skipped
    settings={**DEFAULT_ACCURACY,**dict(accuracy or {}),"overlap_policy":"independent_sections"}
    selected_identity = None
    # Independent cuts do not depend on unfinished parameters of other assets.
    # Keep calculation validation strict, but let the board work on one object.
    if settings["overlap_policy"]=="independent_sections" and workbench_inputs.get("networks"):
        candidates=[]
        seen=set()
        from .earthwork_scope import trenchless_method
        for ni,route in enumerate(workbench_inputs["networks"]):
            route_id=str(route.get("route_id",route.get("network_id",route.get("name",f"route-{ni+1}"))))
            for item in route.get("assets",[]):
                original_id=item.get("asset_id")
                # Match the formal preparation's naming without validating
                # another route's unfinished design or construction values.
                pipe=item.get("kind") in {"pipe","pressure_pipe","siphon"} or item.get("section_type")=="circular_siphon"
                outside=pipe and (item.get("construction") or {}).get("installation_mode","buried") in {"exposed","elevated","above_ground","open"}
                included=(item.get("enabled",True) and item.get("section_type") in SUPPORTED
                    and item.get("section_type") not in {"box_foundation","rectangular_pit"}
                    and item.get("kind")!="pit" and not trenchless_method(item)
                    and not (outside and not item.get("section_scheme_binding")))
                formal_id=original_id if original_id not in seen else f"{route_id}::{original_id}"
                if included:seen.add(formal_id)
                root=item.get("section_scheme_root_asset_id") or item.get("drawing_root_asset_id")
                aliases={original_id,root,formal_id,f"{route_id}::{original_id}"}
                if root is not None:aliases.add(f"{route_id}::{root}")
                if asset_id in aliases and item.get("station_start",math.inf)-1e-7<=station<=item.get("station_end",-math.inf)+1e-7:
                    candidates.append((route,item,route_id,formal_id))
        if len(candidates)>1:
            directed=[pair for pair in candidates if (pair[1]["station_start"]<=station<pair[1]["station_end"]
                if side=="right" else pair[1]["station_start"]<station<=pair[1]["station_end"])]
            if directed:candidates=directed
        if len(candidates)>1:
            raise ConstructionInputError("断面对象身份不存在或存在歧义")
        if len(candidates)==1:
            route,item,route_id,selected_identity=candidates[0]
            asset_id=item["asset_id"]
            root=item.get("section_scheme_root_asset_id") or item.get("drawing_root_asset_id")
            workbench_inputs=deepcopy(workbench_inputs)
            workbench_inputs["networks"]=[{**deepcopy(route),"route_id":route_id,"assets":[deepcopy(item)]}]
            workbench_inputs["pits"]=[]
            binding=item.get("section_scheme_binding") or {}
            workbench_inputs["section_scheme_bindings"]=[deepcopy(binding)] if binding else []
            workbench_inputs["section_scheme_binding_issues"]=[issue for issue in workbench_inputs.get("section_scheme_binding_issues",[])
                if isinstance(issue,dict) and issue.get("asset_id") in {item.get("asset_id"),root}
                and (not (issue.get("route_id") or issue.get("network_id"))
                     or str(issue.get("route_id") or issue.get("network_id")) in {route_id,str(route.get("network_id") or "")})]
    validate_section_scheme_bindings(workbench_inputs,raise_on_error=True)
    source,network,excluded=prepare_workbench_inputs(tin,workbench_inputs,include_independent_pits=include_independent_pits)
    assets=sorted(network["assets"],key=lambda a:(a["station_start"],a["station_end"],a["asset_id"]))
    matches=[a for a in assets if a["asset_id"]==asset_id or a["original_asset_id"]==asset_id]
    if not matches:
        matches=[a for a in assets if (a.get("section_scheme_root_asset_id") or a.get("drawing_root_asset_id"))==asset_id
                 and a["station_start"]-a["station_offset"]-1e-7<=station<=a["station_end"]-a["station_offset"]+1e-7]
        if len(matches)>1:
            directed=[a for a in matches if (a["station_start"]-a["station_offset"]<=station<a["station_end"]-a["station_offset"]
                if side=="right" else a["station_start"]-a["station_offset"]<station<=a["station_end"]-a["station_offset"])]
            if directed:matches=directed
    if len(matches)!=1:raise ConstructionInputError("断面对象身份不存在或存在歧义")
    a=matches[0];internal=float(station)+a["station_offset"]
    if selected_identity is not None:
        a["asset_id"]=selected_identity
    profiles=[_profile(item,network) for item in assets]
    evaluator=_Sections(tin,network["alignment"],assets,profiles,settings["arc_segments"])
    evaluator.material_joint_policy=settings["material_joint_policy"]
    evaluator.overlap_policy=settings["overlap_policy"]
    origin=np.asarray(network["alignment"].get_xy_at_station(network["alignment"].start_station))
    bbox=tin.get_bbox();width=math.hypot(bbox[2]-bbox[0],bbox[3]-bbox[1])+1
    catalog=Catalog(network["alignment"],assets,origin,{item["asset_id"]:width for item in assets})
    evaluator.catalog=catalog
    part=catalog.parts[catalog.part_at(a["asset_id"],internal,side)]
    try:
        value=evaluator.exact(part,internal,side)
        net,diag=_net_section(evaluator,value,{},settings["lateral_step"])
    except ValueError as error:
        from .unmeasured_terrain_ranges import is_unmeasured_terrain_error
        if is_unmeasured_terrain_error(error):
            scoped=prepare_workbench_automatic_ranges(tin,source,settings)
            skipped=skipped_workbench_section(scoped,asset_id,float(station),side)
            if skipped is not None:
                return skipped
        restore_workbench_error(error,assets,coordinate_basis="internal",asset_id=a["asset_id"],station=internal,side=side)
        raise
    from .component_quantities import section_components
    from .layered_excavation import layer_config
    configurations=[layer_config(item.get("construction",{})) for item in assets]
    if any(config is not None for config in configurations):
        from .network_section_calculator import _layer_section
        net,_=_layer_section(value,net,value.get("effective_asset",a)["construction"],include_unclassified=any(config is None for config in configurations))
    net = _split_backfill(value, net)
    value["quantity_components"]=section_components(a,value,net,{r:polygon_metrics(g,value["curvature"]) for r,g in net.items()})
    record={"section_id":f"view-{a['asset_id']}-{float(station).hex()}-{side}","asset_id":a["asset_id"],
            "station":float(station),"side":side,"route_id":a["route_id"],"view_only":True,
            "center_xy":value["center"].tolist(),"tangent":value["tangent"].tolist(),
            "design_elevation":value["design_elevation"],"ground_points":[list(p) for p in value["ground"]],
            "roles":{r:{**polygon_metrics(g,value["curvature"]),"geometry":mapping(g)} for r,g in net.items()},
            "construction_geometry":{r:mapping(g) for r,g in value["roles"].items()},
            "overlap_diagnostics":diag,**_section_structure_fields(value,net)}
    if a["section_type"]=="rectangular_pit":record.update(coordinate_kind="pit_local_slice",local_position=float(station))
    from .support_validation import require_section_support
    try:
        record["support_validation"]=require_section_support(a,record)
    except ValueError as error:
        if any(row.get("code")=="floating_buried_support" for row in getattr(error,"diagnostics",[])):
            scoped=prepare_workbench_automatic_ranges(tin,source,settings)
            skipped=skipped_workbench_section(scoped,asset_id,float(station),side)
            if skipped is not None:
                return skipped
        restore_workbench_error(error,assets,coordinate_basis="source",asset_id=a["asset_id"],station=float(station),side=side)
        raise
    return record


def enrich_saved_sections(payload):
    """Add material drawings to old records; no quantity or result identity changes."""
    from .section_geometry import section_structure, add_foundation_materials, structure_mapping
    result=deepcopy(payload)
    snapshot=result.get("inputs",{})
    networks=[snapshot["network"]] if "network" in snapshot else snapshot.get("workbench",{}).get("networks",[])
    assets={a["asset_id"]:a for n in networks for a in n.get("assets",[])}
    for record in result.get("sections",[]):
        if record.get("structure_geometry"):continue
        asset=assets.get(record.get("asset_id"))
        if not asset:continue
        asset=deepcopy(asset)
        if asset["section_type"]=="arch_tunnel":asset["section_type"]="arch_culvert"
        try:
            slope=record.get("vertical_slope")
            if slope is None:
                values=_profile(asset,{})
                from .network_section_calculator import _profile_at
                slope=_profile_at(values,record["station"],record.get("side","right"))[1]
            structure=section_structure(asset,elevation=record["design_elevation"],slope=slope,arc_segments=128)
            structure=add_foundation_materials(structure,asset.get("construction",{}))
            record["structure_geometry"]=structure_mapping(structure)
            record["material_areas"]={r:None for r in structure["materials"]}
            record["material_quantities_status"]="not_recalculated"
        except (ValueError,ConstructionInputError,KeyError) as exc:
            record["structure_geometry_issue"]=str(exc)
    return result
