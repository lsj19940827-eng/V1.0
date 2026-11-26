# -*- coding: utf-8 -*-
"""保留来源和缺失信息，不把水力占位记录当成施工设计。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import fields, is_dataclass
from enum import Enum
import hashlib
from math import hypot, atan, degrees, radians, sin, cos
from pathlib import Path

from ..services.contracts import ConstructionInputError, finite_number
from ..services.construction_rules import normalize_asset_construction
from ..services.pipe_dimensions import mark_imported_pipe_diameter


_TYPE_MAP = {
    "明渠-梯形": ("open_channel", "trapezoidal_channel"),
    "明渠-矩形": ("open_channel", "rectangular_channel"),
    "明渠-U形": ("open_channel", "u_channel"),
    "明渠-复式梯形": ("open_channel", "compound_trapezoidal_channel"),
    "明渠-圆形": ("culvert", "circular_culvert"),
    "暗涵-圆形": ("culvert", "circular_culvert"),
    "暗涵-矩形": ("culvert", "rectangular_culvert"),
    "暗涵-圆拱直墙型": ("culvert", "arch_culvert"),
    "倒虹吸": ("siphon", "circular_siphon"),
    "隧洞-圆形": ("tunnel", "circular_tunnel"),
}


def _freeze(value):
    """领域枚举和数据类转为独立 JSON 数据，保留全部来源字段。"""
    if isinstance(value,dict):
        return {str(k):_freeze(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):
        return [_freeze(v) for v in value]
    if isinstance(value,Enum):
        return _freeze(value.value)
    if is_dataclass(value):
        return {f.name:_freeze(getattr(value,f.name)) for f in fields(value)}
    return deepcopy(value)


def _as_dict(value):
    if isinstance(value, dict):
        return _freeze(value)
    for method in ("to_project_dict", "to_dict"):
        if hasattr(value, method):
            return _freeze(getattr(value, method)())
    if is_dataclass(value):
        return _freeze(value)
    raise ConstructionInputError("适配器只接受纯字典或可序列化领域节点")


def _issue(message, *, severity="warning", asset_id=None, source_row=None):
    result = {"severity": severity, "message": message}
    if asset_id is not None:
        result["asset_id"] = asset_id
    if source_row is not None:
        result["source_row"] = source_row
    return result


def _assets_from_records(records, source, *, circular_means_culvert=False):
    """按连续建筑物分组；不跨越缺口拼接，也不抛弃单点记录。"""
    assets, issues, groups = [], [], []
    chainage = finite_number(source.get("start_station", 0.0), "start_station")
    previous = None
    for record in records:
        row = deepcopy(record)
        x = finite_number(row.get("x"), "X")
        y = finite_number(row.get("y"), "Y")
        if previous is not None:
            chainage += hypot(x - previous[0], y - previous[1])
        previous = (x, y)
        row["derived_chord_station"] = chainage
        # 来源存在真实曲线桩号时保留，尚未匹配曲线位置前不静默用于几何。
        key = (row.get("structure_type"), row.get("name", ""))
        if not groups or groups[-1][0] != key:
            groups.append((key, []))
        groups[-1][1].append(row)
    for index, (key, group) in enumerate(groups):
        raw_type, name = key
        mapped = _TYPE_MAP.get(raw_type)
        if circular_means_culvert and raw_type == "明渠-圆形":
            mapped = ("culvert", "circular_culvert")
        kind, section_type = mapped or ("unsupported", "unsupported")
        asset_id = f"source-{index + 1:04d}"
        points = [{"x": r["x"], "y": r["y"], "station": r["derived_chord_station"],
                   "source_row": r.get("source_row"), "turn_radius": r.get("turn_radius"),
                   "original_station": r.get("station")} for r in group]
        section = deepcopy(group[0].get("section", {}))
        # 同段尺寸冲突必须后续显式分段，不能只使用第一行掩盖变化。
        conflicts = [r.get("source_row") for r in group if r.get("section", {}) != section]
        if conflicts:
            issues.append(_issue("同一对象包含不同或缺失的断面尺寸，施工准备前须显式覆盖或分段",
                                 asset_id=asset_id))
        profile = []
        if all(r.get("invert_elevation") is not None for r in group) and kind != "siphon":
            profile = [{"station": r["derived_chord_station"], "elevation": r["invert_elevation"]}
                       for r in group]
        asset = {"asset_id": asset_id, "name": name or f"{raw_type} {index + 1}",
                 "kind": kind, "section_type": section_type, "source_type": raw_type,
                 "enabled": mapped is not None and len(points) >= 2,
                 "station_start": points[0]["station"], "station_end": points[-1]["station"],
                 "alignment": {"plan_points": points, "profile_points": profile,
                               "start_station": points[0]["station"],
                               "station_basis": "plan_chord_unresolved_curves",
                               "plan_geometry": "source_ip_polyline",
                               "elevation_reference": "inner_invert" if kind != "siphon" else "pipe_axis"},
                 "section": section, "construction": {}, "geometry_sections": [],
                 "section_variation_requires_resolution": bool(conflicts),
                 "original_fields": {"records": group, "source": deepcopy(source)},
                 "test_overrides": {}, "is_test": False}
        if mapped is None:
            issues.append(_issue(f"{raw_type} 尚无本次施工模板，原记录已保留并停用", asset_id=asset_id))
        if len(points) < 2:
            issues.append(_issue("对象只有一个平面点，无法生成有长度实体；记录已保留", asset_id=asset_id))
        if not profile:
            issues.append(_issue("缺少可用纵断面；起始水位不能代替渠底或管轴高程", asset_id=asset_id))
        mark_imported_pipe_diameter(asset, source="Excel/水面线来源管径D(m)")
        normalize_asset_construction(asset)
        assets.append(asset)
    if len(groups) > 1:
        issues.append(_issue("不同结构组间的连接段未自动补建；需在模型中检查间隙并补齐真实过渡资料"))
    return {"assets": assets, "source": deepcopy(source), "issues": issues}


def load_batch_sample(path) -> dict:
    """只读导入批量样表；程序结构形式“明渠-圆形”按圆管涵施工。"""
    from openpyxl import load_workbook
    from openpyxl.utils import get_column_letter
    path = Path(path).resolve()
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    workbook = load_workbook(path, read_only=True, data_only=False)
    try:
        sheet = workbook["导入模板"] if "导入模板" in workbook.sheetnames else workbook.active
        rows = sheet.iter_rows(values_only=True)
        metadata = next(rows, ())
        headers = [str(v or "").strip() for v in next(rows, ())]
        if not {"结构形式", "X", "Y"}.issubset(headers):
            raise ConstructionInputError("样表第二行必须包含结构形式、X、Y列")
        source = {"path": str(path), "sha256": digest, "sheet": sheet.title,
                  "kind": "batch_xlsx", "header_row": 2,
                  "channel_name": metadata[1] if len(metadata) > 1 else "",
                  "start_water_level": metadata[5] if len(metadata) > 5 else None,
                  "start_station": metadata[7] if len(metadata) > 7 and metadata[7] is not None else 0,
                  "circular_means_culvert": True}
        records = []
        for row_number, values in enumerate(rows, 3):
            if not any(v is not None and v != "" for v in values):
                continue
            raw = dict(zip(headers, values))
            for field in ("X", "Y"):
                if isinstance(raw.get(field), str) and raw[field].startswith("="):
                    raise ConstructionInputError(f"{field}{row_number} 为公式，须使用已核验的数值快照")
            section = {}
            for field, header in (("inner_width", "底宽B(m)"), ("inner_diameter", "直径D(m)"),
                                  ("inner_radius", "半径R(m)"), ("inner_side_slope", "边坡系数m"),
                                  ("inner_height", "暗涵高度H(m)"), ("wall_height", "直墙高度H直(m)")):
                if raw.get(header) is not None and raw.get(header) != "":
                    section[field] = finite_number(raw[header], header)
            if raw.get("结构形式") == "明渠-U形":
                for field, header in (("u_arc_angle_degrees", "圆心角(°)"),
                                      ("u_side_angle_degrees", "倒角角度(°)")):
                    if raw.get(header) is not None and raw[header] != "":
                        section[field] = finite_number(raw[header], header)
            if "圆拱" in str(raw.get("结构形式", "")) and raw.get("圆心角(°)") not in (None, ""):
                section["arch_angle_degrees"] = finite_number(raw["圆心角(°)"], "圆心角(°)")
            records.append({"source_row": row_number, "source_range": f"A{row_number}:{get_column_letter(len(headers))}{row_number}",
                            "structure_type": raw.get("结构形式"), "name": str(raw.get("建筑物名称") or ""),
                            "x": finite_number(raw.get("X"), f"X{row_number}"),
                            "y": finite_number(raw.get("Y"), f"Y{row_number}"),
                            "turn_radius": raw.get("转弯半径(m)"), "section": section, "raw": raw})
    finally:
        workbook.close()
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ConstructionInputError("读取期间源文件发生变化，请重新导入")
    source["record_count"] = len(records)
    return _assets_from_records(records, source, circular_means_culvert=source["circular_means_culvert"])


PROFILE_SIZE_FIELDS = {
    "inner_width": ("B", "b", "底宽b", "底宽B"),
    "inner_diameter": ("D", "直径D", "diameter"),
    "inner_radius": ("R_circle", "内半径R", "R"),
    "inner_side_slope": ("m", "边坡m"),
    "wall_height": ("H_straight", "直墙高度H直"),
}


def adapt_profile_nodes(nodes, *, source=None) -> dict:
    """接受水面线冻结节点；保留真实字段，不读取或改变界面控件。"""
    records = []
    for index, value in enumerate(nodes):
        raw = _as_dict(value)
        params = raw.get("section_params", {})
        section = {}
        for target, keys in PROFILE_SIZE_FIELDS.items():
            for key in keys:
                if key in params and params[key] is not None:
                    section[target] = finite_number(params[key], key)
                    break
        shape = str(raw.get("structure_type", ""))
        if shape == "明渠-U形":
            if params.get("theta_deg") is not None:
                section["u_arc_angle_degrees"] = finite_number(params["theta_deg"], "theta_deg")
            for name in ("alpha_deg", "chamfer_angle"):
                if params.get(name) is not None:
                    section["u_side_angle_degrees"] = finite_number(params[name], name)
                    break
            else:
                if section.get("inner_side_slope") is not None:
                    section["u_side_angle_degrees"] = degrees(atan(section["inner_side_slope"]))
        elif "圆拱" in shape and params.get("theta_deg") is not None:
            section["arch_angle_degrees"] = finite_number(params["theta_deg"], "theta_deg")
        if raw.get("structure_height") is not None and float(raw["structure_height"]) > 0:
            section["inner_height"] = finite_number(raw["structure_height"], "structure_height")
        section.update(deepcopy(raw.get("section") or {}))
        if "圆拱" in shape and "wall_height" not in section and all(k in section for k in ("inner_height","inner_width","arch_angle_degrees")):
            half = radians(section["arch_angle_degrees"])/2
            if 0 < half <= radians(90):
                section["wall_height"] = section["inner_height"]-section["inner_width"]/(2*sin(half))*(1-cos(half))
        # 默认零高程可能只是未计算节点；仅在明确已有水深/结构高度时认作结果。
        bottom = raw.get("bottom_elevation")
        if not (raw.get("water_depth", 0) or raw.get("structure_height", 0)):
            bottom = None
        records.append({"source_row": index + 1, "profile_row_id": raw.get("profile_row_id"),
                        "structure_type": raw.get("structure_type"), "name": raw.get("name", ""),
                        "x": raw.get("x"), "y": raw.get("y"), "turn_radius": raw.get("turn_radius"),
                        "station": raw.get("station_MC"), "invert_elevation": bottom,
                        "section": section, "raw": raw})
    result_source = {"kind": "frozen_profile_nodes", "record_count": len(records), **(source or {})}
    if records and records[0].get("station") is not None:
        result_source.setdefault("start_station",records[0]["station"])
    return _assets_from_records(records, result_source,
                                circular_means_culvert=bool(result_source.get("circular_means_culvert", False)))


def adapt_siphon_config(config, *, name=None, plan_points=None) -> dict:
    """专项纵断面的 elevation 为管轴高程，禁止以水面线底高程代替。"""
    raw = _as_dict(config)
    plan = plan_points if plan_points is not None else raw.get("plan_feature_points", [])
    records = []
    for index, value in enumerate(plan):
        point = _as_dict(value)
        records.append({"source_row": index + 1, "structure_type": "倒虹吸",
                        "name": name or raw.get("name", "倒虹吸专项"), "x": point.get("x"),
                        "y": point.get("y"), "station": point.get("chainage"),
                        "turn_radius": point.get("turn_radius"),
                        "section": {"inner_diameter": raw.get("diameter"), "pipe_count": raw.get("num_pipes")},
                        "raw": point})
    result = _assets_from_records(records, {"kind": "frozen_siphon_config", "record_count": len(records)})
    if not result["assets"]:
        result["issues"].append(_issue("专项缺少平面特征点", severity="error"))
        return result
    asset = result["assets"][0]
    longitudinal = [_as_dict(v) for v in raw.get("longitudinal_nodes", [])]
    profile = [{"station": p.get("chainage"), "elevation": p.get("elevation"),
                "vertical_curve_radius": p.get("vertical_curve_radius", 0), "original": p}
               for p in longitudinal]
    asset["alignment"]["profile_points"] = profile
    asset["alignment"]["profile_station_basis"] = "siphon_axis_chainage"
    asset["alignment"]["elevation_reference"] = "pipe_axis"
    asset["alignment"]["source_plan_feature_points"] = [_as_dict(v) for v in plan]
    asset["original_fields"]["siphon_config"] = raw
    asset["alignment"]["curves_require_resolution"] = bool(
        any(p.get("vertical_curve_radius", 0) for p in profile)
        or any(p.get("turn_radius", 0) for p in asset["alignment"]["source_plan_feature_points"]))
    if not asset["alignment"]["curves_require_resolution"]:
        source_points=asset["alignment"]["source_plan_feature_points"]
        stations=[p.get("chainage") for p in source_points]
        if all(value is not None for value in stations):
            stations=[finite_number(value,"专项平面桩号") for value in stations]
            if any(abs((stations[i+1]-stations[i])-hypot(source_points[i+1]["x"]-source_points[i]["x"],
                        source_points[i+1]["y"]-source_points[i]["y"]))>1e-5 for i in range(len(stations)-1)):
                asset["alignment"]["curves_require_resolution"]=True
                result["issues"].append(_issue("专项桩号与平面直线距离不一致，须解析曲线或修正来源",asset_id=asset["asset_id"]))
            else:
                for point,station in zip(asset["alignment"]["plan_points"],stations):
                    point["station"]=station
                asset["station_start"],asset["station_end"]=stations[0],stations[-1]
                asset["alignment"]["start_station"]=stations[0]
                asset["alignment"]["station_basis"]="siphon_axis_chainage"
    # 专项两种桩号必须明确一致；不能把弦长与圆弧桩号直接拼接。
    if profile:
        result["issues"] = [i for i in result["issues"] if "缺少可用纵断面" not in i["message"]]
    return result


def adapt_support_foundations(foundations, *, source=None) -> dict:
    """把已给定的镇墩、支墩或基础作为独立实体，不沿全管线铺满基础。"""
    assets=[]
    for index,value in enumerate(foundations):
        raw=_as_dict(value)
        label=raw.get("name") or f"独立基础 {index+1}"
        width=finite_number(raw.get("width"),"基础宽度")
        length=finite_number(raw.get("length"),"基础长度")
        height=finite_number(raw.get("height"),"基础高度")
        if min(width,length,height)<=0:raise ConstructionInputError(f"{label}：基础尺寸必须为正数")
        center=raw.get("center",[])
        direction=raw.get("direction",[])
        if len(center)!=2 or len(direction)!=2:
            raise ConstructionInputError(f"{label}：必须明确基础中心和水平朝向")
        x,y=(finite_number(v,"基础中心") for v in center)
        dx,dy=(finite_number(v,"基础方向") for v in direction)
        norm=hypot(dx,dy)
        if norm<=1e-12:raise ConstructionInputError(f"{label}：基础方向不能为零")
        dx,dy=dx/norm,dy/norm
        bottom=finite_number(raw.get("base_elevation"),"基础底高程")
        start=finite_number(raw.get("station_start",0.0),"基础起点桩号")
        points=[{"x":x-dx*length/2,"y":y-dy*length/2,"station":start},
                {"x":x+dx*length/2,"y":y+dy*length/2,"station":start+length}]
        assets.append({"asset_id":raw.get("asset_id") or f"support-{index+1:04d}","name":label,
            "kind":"support","section_type":"box_foundation","enabled":True,
            "support_type":raw.get("support_type","foundation"),"linked_asset_id":raw.get("linked_asset_id"),
            "alignment":{"plan_points":points,"profile_points":[{"station":p["station"],"elevation":bottom} for p in points],
                "plan_geometry":"explicit_straight_foundation","elevation_reference":"foundation_base"},
            "section":{"foundation_width":width,"foundation_height":height},
            "construction":deepcopy(raw.get("construction",{})),"geometry_sections":[],
            "original_fields":{"foundation":raw,"source":deepcopy(source or {})},
            "is_test":False,"test_overrides":{}})
    return {"assets":assets,"source":deepcopy(source or {"kind":"explicit_support_foundations"}),"issues":[]}


def import_workbench_project(project_snapshot):
    """Main-program section importer; preserve legacy adapter behavior above."""
    from .workbench_sources import import_workbench_project as import_sources
    return import_sources(project_snapshot)
