"""Batch workbook -> production section calculator -> production water profile.

The original workbook is read only. Construction assumptions belong to the
earthwork stage; no terrain-derived elevation enters this calculation.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import fields, asdict
import hashlib
from itertools import zip_longest
import json
import math
from pathlib import Path
import re


def _sha(path):
    with Path(path).open("rb") as stream:return hashlib.file_digest(stream,"sha256").hexdigest()


@contextmanager
def _batch_sheet_rows(path, *, include_formulas):
    if path.suffix.lower() == ".xls":
        import xlrd
        book = xlrd.open_workbook(str(path))
        try:
            sheet = book.sheet_by_index(0)
            yield sheet.name, ((number + 1, sheet.row_values(number)) for number in range(sheet.nrows))
        finally:
            book.release_resources()
        return

    from openpyxl import load_workbook
    with path.open("rb") as stream, path.open("rb") as formula_stream:
        book = load_workbook(stream, data_only=True, read_only=True)
        try:
            formula_book = load_workbook(formula_stream, data_only=False, read_only=True)
            try:
                sheet = book.active
                rows = sheet.iter_rows(values_only=True)
                formulas = formula_book[sheet.title].iter_rows(values_only=True)

                def read_rows():
                    header_row = 3
                    for number, values in enumerate(rows, 1):
                        if number == 1 and values and "渠道名称" in str(values[0] or ""):
                            header_row = 2
                        if not include_formulas and number > header_row:
                            yield number, values
                            continue
                        raw = next(formulas, ())
                        yield number, tuple(_cached_batch_value(value, formula, keep_formula=include_formulas)
                            for value, formula in zip_longest(values, raw))

                yield sheet.title, read_rows()
            finally:
                formula_book.close()
        finally:
            book.close()


def _cached_batch_value(value, formula, *, keep_formula):
    if value is not None or not isinstance(formula, str) or not formula.startswith("="):
        return value
    numeric = formula[1:].strip()
    if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", numeric):
        return float(numeric)
    return formula if keep_formula else None


def read_batch_workbook(path, *, for_centerline=False):
    """Use the desktop batch table's header mapping and import conventions."""
    from app_渠系计算前端.batch.schema import (
        COL_BUILDING_NAME, COL_SECTION_TYPE, COL_X, COL_Y, _excel_header_mapping,
        _map_excel_row_by_headers, infer_gate_section_type, normalize_project_section_type,
    )

    path = Path(path).resolve()
    digest = _sha(path) if for_centerline else None
    with _batch_sheet_rows(path, include_formulas=for_centerline) as (sheet_name, sheet_rows):
        _, info = next(sheet_rows, (1, ()))
        if not info or "渠道名称" not in str(info[0] or ""):
            _, info = next(sheet_rows, (2, ()))
        _, headers = next(sheet_rows, (3, ()))
        headers = list(headers)
        mapping = _excel_header_mapping(headers)
        if not mapping:
            raise ValueError("未识别批量Excel表头，请使用主程序批量计算模板")
        if for_centerline and not {COL_X, COL_Y}.issubset(mapping.values()):
            raise ValueError("批量计算表格缺少中心轴线 X、Y 坐标列")
        rows = []
        source_rows = []
        for number, values in sheet_rows:
            if not any(v is not None and str(v).strip() for v in values):
                continue
            row = _map_excel_row_by_headers([str(v).strip() if v is not None else "" for v in values], mapping)
            structure = infer_gate_section_type(row[COL_SECTION_TYPE], row[COL_BUILDING_NAME])
            if not structure:
                continue
            row[COL_SECTION_TYPE] = normalize_project_section_type(structure)
            rows.append(row)
            source_rows.append(number)

        def cell(column):
            return info[column - 1] if len(info) >= column else None

        start = cell(8)
        if isinstance(start, str) and "+" in start.lstrip("+"):
            match = re.search(r"([+-]?\d+)\+(\d+(?:\.\d+)?)", start)
            if not match:
                raise ValueError("起始桩号不能解析")
            start = float(match[1]) * 1000 + float(match[2])
        final_digest = _sha(path)
        if digest is not None and digest != final_digest:
            raise ValueError("读取期间批量计算表格已改变，请重新选择文件")
        metadata = {
            "channel_name": str(cell(2) or path.stem), "channel_level": str(cell(4) or "支渠"),
            "start_station": float(start or 0), "source_path": str(path), "source_sha256": final_digest,
            "source_sheet": sheet_name, "source_rows": source_rows, "headers": headers, "header_mapping": mapping,
        }
        if for_centerline:
            return rows, metadata
        water = cell(6)
        if water is None:
            raise ValueError("原表缺少起始水位高程")
        metadata["start_water_level"] = float(water)
        manual = {}
        value = cell(10)
        if value is not None:
            for i, text in enumerate(re.split(r"[,，]", str(value)), 1):
                if text.strip():
                    manual[i] = float(text)
        metadata["manual_qmax_by_segment"] = manual
        return rows, metadata


def calculate_batch_water_profile(path,*,cancelled=None,progress=None,pipe_material="预应力钢筒混凝土管_n014"):
    """Return a main-program snapshot and exact calculated water-profile nodes."""
    from app_渠系计算前端.runtime_platform import ensure_safe_windows_platform_queries
    ensure_safe_windows_platform_queries()
    from app_渠系计算前端.batch.calculation_service import BatchCalculationRequest,BatchCalculationService
    from app_渠系计算前端.batch.schema import (COL_SECTION_TYPE,COL_PIPE_MATERIAL,COL_TURN_RADIUS,
        COL_Q,COL_N,COL_SLOPE,COL_M,is_pressure_pipe_like_section_type)
    from 推求水面线.shared.shared_data_manager import SharedDataManager
    from 推求水面线.models.data_models import ChannelNode,ProjectSettings
    from 推求水面线.models.enums import StructureType
    from 推求水面线.core.calculation_service import calculate_profile
    def checkpoint():
        if cancelled and cancelled():raise InterruptedError("水面线计算已取消")
    def report(fraction,message):
        checkpoint()
        if progress:progress("water_profile",fraction,message)
    rows,meta=read_batch_workbook(path);assumptions=[]
    for row,source_row in zip(rows,meta["source_rows"]):
        if is_pressure_pipe_like_section_type(row[COL_SECTION_TYPE]) and not row[COL_PIPE_MATERIAL]:
            row[COL_PIPE_MATERIAL]=pipe_material
            assumptions.append({"source_row":source_row,"field":"pipe_material","value":pipe_material,
                "reason":"原表管材为空，暂按与n=0.014对应的混凝土管计算，可在主程序修改。"})
    report(.05,"已读取原Excel，正在执行正式批量断面计算")
    request=BatchCalculationRequest(tuple(tuple(r) for r in rows),use_increase=True,include_details=True,
        manual_qmax_by_segment=tuple(meta["manual_qmax_by_segment"].items()),
        imported_rows=tuple(range(len(rows))))
    batch=BatchCalculationService().calculate(request)
    if batch.fail_count:raise ValueError("批量断面计算失败："+json.dumps(batch.error_details,ensure_ascii=False))
    manager=object.__new__(SharedDataManager);manager._init_data_storage()
    results=[];nodes=[];allowed={f.name for f in fields(ChannelNode)};flows={};maxflows={}
    for item in batch.batch_results:
        r=deepcopy(item["result"]);row=item["input"]
        radius_text = "" if row[COL_TURN_RADIUS] is None else str(row[COL_TURN_RADIUS]).strip()
        structure = row[COL_SECTION_TYPE]
        gate = StructureType.is_diversion_gate_str(structure)
        r.update(section_type=structure,building_name=row[2] or (structure if gate else ""),flow_section=str(row[1]),
            coord_X=float(row[4]),coord_Y=float(row[5]),turn_radius=float(row[COL_TURN_RADIUS] or 0),
            turn_radius_text=radius_text, turn_radius_is_explicit=float(row[COL_TURN_RADIUS] or 0)>0,
            Q=float(row[COL_Q] or 0) if gate else float(row[COL_Q]),
            n=float(row[COL_N] or .014),slope_inv=float(row[COL_SLOPE] or 0))
        r.setdefault("m",float(row[COL_M] or 0));results.append(r)
        sr=manager._extract_section_result("Excel正式批量计算",r)
        if sr is None:raise ValueError("正式断面结果不能映射到水面线节点")
        params=sr.to_node_params();node=ChannelNode(**{k:v for k,v in params.items() if k in allowed and v is not None})
        node.section_params={k:v for k,v in node.section_params.items() if v is not None}
        node.structure_type=StructureType.from_string(structure);node.turn_radius=sr.turn_radius
        if node.structure_type == StructureType.GATE:
            node.custom_gate_type = structure
        node.turn_radius_text=radius_text
        node.turn_radius_is_explicit=node.turn_radius>0
        node.turn_radius_source="input" if node.turn_radius_is_explicit else ""
        node.structure_height=float(sr.H_total or 0);node.velocity_increased=float(sr.V_max or 0)
        node.section_params["use_increase"]=True
        if row[COL_PIPE_MATERIAL]:node.section_params["pipe_material"]=row[COL_PIPE_MATERIAL]
        node.profile_row_id=f"xlsx-row-{meta['source_rows'][len(nodes)]}"
        nodes.append(node)
        segment=int(float(row[1] or 1))
        if not gate or node.flow > 0:
            flows.setdefault(segment,node.flow)
        qmax=float(sr.Q_max or 0)
        if qmax>0:maxflows.setdefault(segment,qmax)
    from app_渠系计算前端.water_profile.panel import calculate_final_max_flow_values
    design=[flows[k] for k in sorted(flows)]
    maximum=calculate_final_max_flow_values(design,[maxflows.get(k,meta["manual_qmax_by_segment"].get(k,0)) for k in sorted(flows)])
    settings=ProjectSettings(channel_name=meta["channel_name"],channel_level=meta["channel_level"],
        start_station=meta["start_station"],start_water_level=meta["start_water_level"],
        design_flow=design[0],max_flow=maximum[0],design_flows=design,max_flows=maximum)
    report(.35,"批量断面已完成，正在准备真实线路和渐变段")
    from 推求水面线.core.calculator import WaterProfileCalculator
    calculator=WaterProfileCalculator(settings)
    calculator.preprocess_nodes(nodes);calculator.calculate_geometry(nodes)
    nodes=calculator.prepare_transitions(nodes)
    report(.5,"正在调用倒虹吸及有压管道正式水损计算")
    from 推求水面线.shared.turn_radius import apply_default_turn_radii
    original_diameter_sources={}
    geometry_rebuild_count=0
    for _ in range(3):
        checkpoint()
        radii_before=[n.turn_radius for n in nodes]
        pipe_results=_calculate_pipe_losses(nodes,settings)
        for record in pipe_results:
            if record.get("diameter_source")=="engine_design_from_assumed_velocity":
                original_diameter_sources[(record.get("type"),record.get("name"))]=record["diameter_source"]
        # A siphon diameter can first become known in its hydraulic kernel.
        # Rebuild its nD arcs and rerun the losses on that same final geometry.
        apply_default_turn_radii(nodes,multiplier=settings.pipe_turn_radius_n)
        if all(math.isclose(before,n.turn_radius,abs_tol=1e-12,rel_tol=1e-12)
               for before,n in zip(radii_before,nodes)):
            break
        calculator.calculate_geometry(nodes)
        geometry_rebuild_count+=1
    else:
        raise ValueError("管径与转弯半径尚未形成一致线路，请核对管道参数")
    for record in pipe_results:
        original=original_diameter_sources.get((record.get("type"),record.get("name")))
        if original:record["diameter_source"]=original
    for record in pipe_results:
        if record.get("diameter_source")=="engine_design_from_assumed_velocity":
            assumptions.append({"name":record["name"],"field":"siphon_design_velocity","value":2.0,
                "resulting_diameter":record["diameter"],"reason":"原表倒虹吸D为空，拟定流速暂取2.0m/s，由正式倒虹吸内核计算并按标准档位取整；可在主程序修改。"})
    if pipe_results:
        assumptions.append({"field":"pressure_hydraulics_mode","value":"正式专项仅平面独立计算",
            "reason":"原Excel未附管道纵断面；专项先按原表真实平面线型计算水损，土石方管轴另按地形覆土2.5m生成。未填写的附属构件未另加局损。"})
    report(.7,"正在正式计算水面线、渐变段及渠底渠顶高程")
    raw_nodes=[n.to_project_dict() for n in nodes]
    calculated=calculate_profile(nodes,settings,checkpoint)
    calculated_nodes=calculated.nodes
    for node in calculated_nodes:
        if not all(math.isfinite(float(getattr(node,k))) for k in ("water_level","bottom_elevation","top_elevation")):
            raise ValueError("水面线含非有限高程")
    merged={"version":"1.0","project_settings":settings.to_dict(),"nodes":raw_nodes,
        "calculated_nodes":[n.to_project_dict() for n in calculated_nodes],
        "ui_settings":{"channel_name":settings.channel_name,"channel_level":settings.channel_level,
            "start_water_level":str(settings.start_water_level),"start_station_text":str(settings.start_station),
            "design_flows_text":",".join(map(str,design)),"max_flows_text":",".join(map(str,maximum))},
        "merged_section":{"sync_ready":True,"transition_topology_prepared":True},
        "batch_panel_compat":{"channel_name":settings.channel_name,"channel_level":settings.channel_level,
            "start_water_level":str(settings.start_water_level),"start_station_text":str(settings.start_station),
            "input_rows":rows,"batch_results":batch.batch_results}}
    snapshot={"version":"2.0","merged_panel":merged,"water_profile_provenance":{
        **meta,"assumptions":assumptions,"batch_success_count":batch.success_count,"batch_skip_count":batch.skip_count,
        "calculated_node_count":len(calculated_nodes),"pipe_hydraulic_results":pipe_results,
        "default_radius_geometry_rebuild_count":geometry_rebuild_count,
        "calculation_entry":"推求水面线.core.calculation_service.calculate_profile",
        "uses_terrain_for_open_channel_elevation":False}}
    report(1.,"正式水面线和渠底渠顶高程已计算")
    return snapshot


def _calculate_pipe_losses(nodes,settings):
    """Use the same independent-plan hydraulic kernels as the special dialogs."""
    import sys
    root=Path(__file__).resolve().parents[2]
    directory=str(root/"倒虹吸水力计算系统")
    if directory not in sys.path:sys.path.insert(0,directory)
    from siphon_hydraulics import HydraulicCore
    from siphon_models import GlobalParameters,GradientType,PlanFeaturePoint
    from 推求水面线.utils.siphon_extractor import SiphonDataExtractor
    from 推求水面线.utils.pressure_pipe_extractor import PressurePipeDataExtractor
    from 推求水面线.core.pressure_pipe_calc import calc_total_head_loss,calc_friction_loss
    from 推求水面线.models.pressure_pipe_override import set_pressure_pipe_window_override
    records=[]
    for group in SiphonDataExtractor.extract_siphons(nodes,settings):
        diameter=float(group.diameter_override or 0)
        specified=diameter>0
        velocity=group.design_flow/(math.pi*diameter**2/4) if specified else 2.0
        params=GlobalParameters(Q=group.design_flow,v_guess=velocity,roughness_n=group.roughness,
            inlet_type=GradientType.REVERSE_BEND,outlet_type=GradientType.REVERSE_BEND,
            v_channel_in=group.upstream_velocity,v_pipe_in=velocity,v_channel_out=velocity,
            v_pipe_out=group.downstream_velocity,xi_inlet=settings.siphon_transition_inlet_zeta,
            xi_outlet=settings.siphon_transition_outlet_zeta)
        result=HydraulicCore.execute_calculation(params,[],diameter_override=diameter if specified else None,
            plan_total_length=group.plan_total_length,
            plan_feature_points=[PlanFeaturePoint.from_dict(p) for p in group.plan_feature_points])
        diameter=float(result.diameter);velocity=float(result.velocity)
        nodes[group.outlet_row_index].head_loss_siphon=float(result.total_head_loss)
        for index in group.row_indices:
            nodes[index].velocity=velocity;nodes[index].section_params["D"]=diameter
        records.append({"name":group.name,"type":"倒虹吸","engine":"HydraulicCore.execute_calculation",
            "diameter_source":"Excel" if specified else "engine_design_from_assumed_velocity",**asdict(result)})
    for group in PressurePipeDataExtractor.extract_pipes(nodes,settings):
        result=calc_total_head_loss(group.name,group.design_flow,group.diameter,group.material_key,
            group.ip_points,group.upstream_velocity,group.downstream_velocity,
            inlet_transition_form=group.inlet_transition_form,outlet_transition_form=group.outlet_transition_form,
            inlet_transition_zeta=group.inlet_transition_zeta,outlet_transition_zeta=group.outlet_transition_zeta)
        record=asdict(result)
        bends_by_ip = {point["point_index"]: (loss, point)
                       for loss, point in zip(result.bend_losses, result.bend_details)}
        for position,index in enumerate(group.row_indices):
            node=nodes[index];node.velocity=result.pipe_velocity
            if position==0:continue  # The real inlet approach stays in the profile engine.
            previous=group.row_indices[position-1]
            length=max(0.,node.station_MC-nodes[previous].station_MC)
            friction,details=calc_friction_loss(group.design_flow,group.diameter,length,group.material_key)
            bend, bend_details = bends_by_ip.get(position, (0., {}))
            local=(result.inlet_transition_loss if position==1 else 0.)+(result.outlet_transition_loss if position==len(group.row_indices)-1 else 0.)
            identity=f"{group.identity or group.name}:row:{index}"
            set_pressure_pipe_window_override(node,{"identity":identity,"enabled":True,"storage_key":identity,
                "display_name":f"{group.name} 第{position}段","group_mode":"named_row_segment",
                "data_mode":"正式平面专项逐段回写","applied_at":"batch_water_profile",
                "target_row_index":index,"upstream_row_index":previous,"Q":group.design_flow,
                "D":group.diameter,"total_length":length,"pipe_velocity":result.pipe_velocity,
                "friction_loss":friction,"total_bend_loss":bend,"local_loss":local,
                "total_head_loss":friction+bend+local,"friction_details":details,
                "bend_details":{"source":"formal_group_plan_calculation","point_details":bend_details},
                "local_details":{"inlet_transition_loss":result.inlet_transition_loss if position==1 else 0.,
                    "outlet_transition_loss":result.outlet_transition_loss if position==len(group.row_indices)-1 else 0.},
                "calc_steps":result.calc_steps})
            node.pressure_pipe_named_group_result={}
        records.append({"type":"有压管道","engine":"calc_total_head_loss",**record})
    return records


def save_batch_water_profile(snapshot,directory):
    """Persist the real calculation snapshot and a plain elevation table."""
    import csv
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=True)
    project=directory/"水面线计算工程.qxproj"
    if project.exists():raise ValueError("原成果保留，请使用新水面线成果目录")
    project.write_text(json.dumps(snapshot,ensure_ascii=False,allow_nan=False,indent=2),encoding="utf8")
    rows=snapshot["merged_panel"]["calculated_nodes"]
    columns=("profile_row_id","flow_section","name","structure_type","is_transition","is_auto_inserted_channel",
        "x","y","station_BC","station_MC","station_EC","turn_radius","water_level","bottom_elevation","top_elevation","structure_height","water_depth","head_loss_total")
    target=directory/"渠底渠顶高程表.csv"
    with target.open("w",encoding="utf-8-sig",newline="") as stream:
        writer=csv.writer(stream);writer.writerow(columns)
        for row in rows:writer.writerow([row.get(k) for k in columns])
    (directory/"水力计算来源.json").write_text(json.dumps(snapshot["water_profile_provenance"],ensure_ascii=False,indent=2),encoding="utf8")
    return {"project_path":str(project),"elevations_path":str(target),"node_count":len(rows)}
