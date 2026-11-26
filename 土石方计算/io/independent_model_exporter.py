# -*- coding: utf-8 -*-
"""保存可在 Rhino 查看的世界坐标校核曲线，原 3DM 地形直接保留。"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import uuid

import numpy as np
import rhino3dm
from shapely.geometry import Polygon, MultiPolygon, shape

from ..core.tin_interpolator import TINInterpolator
from ..models.alignment import Alignment
from ..models.terrain import TINModel
from .independent_terrain import load_terrain


ROLES = {
    "design_axis": ("设计内底或管轴纵线", (80, 90, 220, 255)),
    "ground_centerline": ("地面中心纵线", (60, 170, 70, 255)),
    "section_origins": ("已知断面原点连线", (80, 90, 220, 255)),
    "ground_section": ("地面断面", (50, 170, 60, 255)),
    "design_section": ("施工设计断面", (70, 80, 220, 255)),
    "excavation_boundary": ("开挖断面边界", (210, 60, 40, 255)),
    "backfill_boundary": ("回填断面边界", (220, 180, 40, 255)),
    "embankment_boundary": ("填筑断面边界", (80, 180, 150, 255)),
    "excluded_occupancy": ("永久与另列材料占位", (140, 110, 180, 255)),
    "bottom_boundary": ("坑底边界", (60, 80, 220, 255)),
    "calculation_ground_boundary": ("计算范围地面交线", (210, 60, 40, 255)),
    "calculation_plan_boundary": ("计算范围平面参考 Z=0", (160, 80, 60, 255)),
    "review_note": ("算量依据与模型说明", (30, 30, 30, 255)),
}


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _number(value, name):
    if value is None or isinstance(value, bool):
        raise ValueError(f"缺少明确的{name}")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name}必须是有限数值")
    return result


def _runs(points):
    run = []
    for point in points:
        if len(point) == 2 and all(v is not None and math.isfinite(float(v)) for v in point):
            run.append(tuple(map(float, point)))
        else:
            if len(run) > 1:
                yield run
            run = []
    if len(run) > 1:
        yield run


def _polygon_rings(value):
    geometry = value if isinstance(value, (Polygon, MultiPolygon)) else shape(value)
    if not isinstance(geometry, (Polygon, MultiPolygon)) or not geometry.is_valid or geometry.has_z:
        raise ValueError("校核边界必须是有效二维 Polygon 或 MultiPolygon")
    for polygon in ([geometry] if isinstance(geometry, Polygon) else geometry.geoms):
        if not polygon.is_empty:
            for ring in [polygon.exterior, *polygon.interiors]:
                yield list(ring.coords)


class _Writer:
    def __init__(self, model, payload):
        self.model, self.payload = model, payload
        self.layers, self.expected = {}, []
        self.quantities = {}
        for key in ("excavation_volume", "backfill_volume", "embankment_volume", "surface_fill_volume"):
            if payload.get(key) is not None:
                self.quantities[key] = _number(payload[key], key)

    def attributes(self, role, details=None):
        if role not in self.layers:
            layer = rhino3dm.Layer()
            layer.Name = "独立算量校核 · "+ROLES[role][0]
            layer.Color = ROLES[role][1]
            self.layers[role] = self.model.Layers.Add(layer)
        attributes = rhino3dm.ObjectAttributes()
        attributes.Name = ROLES[role][0]
        attributes.LayerIndex = self.layers[role]
        values = {"qx_review_role": role, "qx_geometry_basis": "review_curves_not_quantity_solids",
                  "qx_input_hash": str(self.payload.get("input_hash", "")),
                  "qx_terrain_sha256": str((self.payload.get("terrain") or self.payload.get("terrain_metadata") or {}).get("source_sha256", "")),
                  "qx_quantity_basis": str(self.payload.get("integration_method", "independent_TIN_sections")),
                  "qx_units": "m", **{"qx_total_"+key: format(value, ".17g") for key, value in self.quantities.items()},
                  **(details or {})}
        for key, value in values.items():
            attributes.SetUserString(key, str(value))
        return attributes, {key: str(value) for key, value in values.items()}

    def curve(self, points, role, details=None):
        xyz = np.asarray(points, dtype=np.float64)
        if xyz.ndim != 2 or xyz.shape[1] != 3 or len(xyz) < 2 or not np.isfinite(xyz).all():
            raise ValueError("校核曲线至少需要两个有限世界 XYZ 点")
        original_count = len(xyz)
        keep = np.r_[True, np.any(np.diff(xyz, axis=0) != 0, axis=1)]
        xyz = xyz[keep]
        details = dict(details or {})
        minimum = float(np.min(np.linalg.norm(np.diff(xyz, axis=0), axis=1))) if len(xyz) > 1 else 0.0
        normalization = {"role": role, "station_m": details.get("qx_station_m"),
                         "original_point_count": original_count, "saved_point_count": len(xyz),
                         "removed_exact_consecutive_duplicates": original_count-len(xyz),
                         "minimum_nonzero_segment_length_m": minimum}
        representation, validation_log = "polyline", ""
        if len(xyz) == 1:
            # 精确相等的世界坐标仅形成一个位置，保留可追溯的点标记。
            representation = "point_marker_exact_zero_world_length"
            curve = None
        else:
            curve = rhino3dm.PolylineCurve([rhino3dm.Point3d(*point) for point in xyz])
            if not curve.IsValid:
                _, validation_log = curve.IsValidWithLog
                # Rhino 的 PolylineCurve 把非零微短边判为 IsCoincident。
                # 官方一阶非有理 NURBS 表示仍是同一折线，每个控制点保留。
                linear = curve.ToNurbsCurve()
                valid = (linear is not None and linear.IsValid and linear.Degree == 1
                         and not linear.IsRational and len(linear.Points) == len(xyz))
                if valid:
                    controls = np.asarray([[p.X, p.Y, p.Z] for p in linear.Points])
                    valid = np.array_equal(controls, xyz) and all(p.W == 1.0 for p in linear.Points)
                if not valid:
                    raise ValueError(f"校核曲线无效：role={role}，桩号={details.get('qx_station_m', '不适用')}，"
                                     f"点数={len(xyz)}，最短非零边={minimum:.17g}m；{validation_log.strip()}")
                curve, representation = linear, "degree1_nurbs_exact_polyline"
        details["qx_curve_representation"] = representation
        details["qx_removed_exact_duplicates"] = original_count-len(xyz)
        details["qx_minimum_nonzero_segment_m"] = format(minimum, ".17g")
        attributes, strings = self.attributes(role, details)
        identifier = (self.model.Objects.AddPoint(rhino3dm.Point3d(*xyz[0]), attributes) if curve is None
                      else self.model.Objects.AddCurve(curve, attributes))
        if identifier.int == 0:
            raise IOError(f"Rhino 校核成果未能加入文件：role={role}，桩号={details.get('qx_station_m', '不适用')}")
        normalization.update(representation=representation, original_polyline_validation_log=validation_log)
        self.expected.append({"id": identifier, "points": xyz.copy(), "strings": strings, "role": role,
                              "representation": representation,
                              "normalization": normalization if representation != "polyline" or original_count != len(xyz) else None})

    def note(self, terrain_attached):
        location = self.expected[0]["points"][0] if self.expected else np.zeros(3)
        text = "独立断面/地形分层算量校核。成果曲线不构成闭合计量实体。"
        text += " 原始地形网格已原样保留。" if terrain_attached else " 原始地形未附，仅保存校核成果曲线。"
        if "excavation_volume" in self.quantities:
            text += f" 天然挖方 {self.quantities['excavation_volume']:.3f} m³。"
        attributes, strings = self.attributes("review_note", {"qx_terrain_attached": str(terrain_attached).lower()})
        identifier = self.model.Objects.AddTextDot(text, rhino3dm.Point3d(*location), attributes)
        if identifier.int == 0:
            raise IOError("模型说明未能加入文件")
        self.expected.append({"id": identifier, "points": np.asarray([location]), "strings": strings, "role": "review_note"})


def _alignment(payload):
    calculation = payload.get("calculation_input") or {}
    inputs = payload.get("inputs") or {}
    data = calculation.get("alignment")
    if not data:
        asset = inputs.get("asset") or {}
        data = (asset.get("alignment") or {}).get("plan_points")
    if isinstance(data, dict):
        data = data.get("plan_points") or data.get("points")
    if not data and inputs.get("line_rows"):
        data = [{"station": s, "x": x, "y": y} for s, x, y, z in inputs["line_rows"]]
    if not data:
        return None
    rows = [(_number(p.get("station"), "线路桩号"), _number(p.get("x"), "线路X"), _number(p.get("y"), "线路Y")) for p in data]
    if len(rows) < 2 or any(b[0] <= a[0] or math.hypot(b[1]-a[1], b[2]-a[2]) == 0 for a, b in zip(rows, rows[1:])):
        raise ValueError("世界坐标线路必须按桩号递增且至少含两个不同位置")
    return Alignment.from_station_table(rows)


def _profile_value(payload, station):
    calculation, inputs = payload.get("calculation_input") or {}, payload.get("inputs") or {}
    profile = calculation.get("design_profile") or {}
    table = profile.get("station_elevation_table") or {}
    reference = "design_invert"
    if table:
        rows = sorted((_number(s, "设计纵断桩号"), _number(z, "设计纵断高程")) for s, z in table.items())
    elif profile.get("segments"):
        for segment in profile["segments"]:
            if segment["start_station"] <= station <= segment["end_station"]:
                return (_number(segment["start_invert_elevation"], "设计底高程")
                        +_number(segment["slope"], "设计纵坡")*(station-segment["start_station"])), reference
        return None, reference
    elif inputs.get("line_rows"):
        rows = [(_number(row[0], "设计纵断桩号"), _number(row[3], "施工底高程")) for row in inputs["line_rows"]]
    else:
        asset = inputs.get("asset") or {}
        data = asset.get("alignment") or {}
        reference = data.get("elevation_reference")
        if reference not in {"pipe_axis", "inner_invert", "foundation_base"}:
            return None, "unknown"
        rows = [(_number(p.get("station"), "设计纵断桩号"), _number(p.get("elevation"), "设计纵断高程"))
                for p in data.get("profile_points", [])]
        if "circular" in asset.get("section_type", "") and reference == "inner_invert":
            radius = _number((asset.get("section") or {}).get("inner_diameter"), "内径")/2
            rows = [(s, z+radius) for s, z in rows]
            reference = "pipe_axis"
    if len(rows) < 2 or any(b[0] <= a[0] for a, b in zip(rows, rows[1:])) or not rows[0][0] <= station <= rows[-1][0]:
        return None, reference
    return float(np.interp(station, [v[0] for v in rows], [v[1] for v in rows])), reference


def _linear(writer, payload):
    alignment = _alignment(payload)
    inputs = payload.get("inputs") or {}
    asset = inputs.get("asset") or {}
    source_alignment = asset.get("alignment") or {}
    native = bool(source_alignment.get("native_samples") or source_alignment.get("native_curve_path")
                  or source_alignment.get("source") == "rhino_curve" or source_alignment.get("curves_require_resolution"))
    sections = sorted((payload.get("sections") or [])+(payload.get("mid_sections") or []), key=lambda s: s["station"])
    if not sections:
        raise ValueError("当前结果缺少地面或开挖断面")
    if alignment is None and any(not s.get("origin") or not s.get("lateral") for s in sections):
        raise ValueError("缺少世界坐标线路或逐断面 origin/lateral，不能猜测断面位置")
    if native and any(not s.get("origin") or not s.get("lateral") for s in sections):
        raise ValueError("原生曲线已准备断面缺少世界 origin/lateral；不能由采样折线猜测原曲线位置")
    axes = {"design_axis": [], "ground_centerline": [], "section_origins": []}
    used_stations = set()
    for section in sections:
        station = _number(section.get("station"), "断面桩号")
        if station in used_stations:
            continue
        used_stations.add(station)
        if section.get("origin") is not None or section.get("lateral") is not None:
            origin = np.asarray(section.get("origin"), dtype=float)
            lateral = np.asarray(section.get("lateral"), dtype=float)
            if (origin.shape != (3,) or lateral.shape != (3,) or not np.isfinite(origin).all()
                    or not np.isfinite(lateral).all() or abs(lateral[2]) > 1e-10
                    or not math.isclose(float(np.linalg.norm(lateral[:2])), 1, abs_tol=1e-10)):
                raise ValueError("断面世界 origin/lateral 必须有限，lateral须为水平单位向量")
            if section.get("coordinate_mode") not in (None, "offset_absolute_elevation"):
                raise ValueError("断面坐标必须明确采用偏距与绝对高程")
            center, direction = origin[:2], lateral[:2]
            axes["section_origins"].append(origin.tolist())
        else:
            if not alignment.start_station <= station <= alignment.end_station:
                raise ValueError("断面桩号超出世界线路，禁止端值外推")
            center = np.asarray(alignment.get_xy_at_station(station))
            angle = alignment.get_tangent_angle_at_station(station)
            direction = np.asarray([math.sin(angle), -math.cos(angle)])
            direction[np.abs(direction) < 1e-15] = 0
        def world(points):
            return [[*(center+float(offset)*direction), float(z)] for offset, z in points]
        details = {"qx_station_m": format(station, ".17g"), "qx_section_coordinates": "left_negative_right_positive_absolute_elevation"}
        for name, value in (section.get("area_result") or {}).items():
            if name.endswith("area") or name == "excavation_total":
                if value is not None:
                    details["qx_section_"+name] = format(_number(value, name), ".17g")
        for key, role in (("ground_points", "ground_section"), ("design_points", "design_section"),
                          ("excavation_boundary", "excavation_boundary")):
            for run in _runs(section.get(key) or []):
                writer.curve(world(run), role, details)
        for key, role in (("backfill", "backfill_boundary"), ("embankment", "embankment_boundary"),
                          ("excluded_occupancy", "excluded_occupancy")):
            regions = section.get("construction_regions") or {}
            if regions.get(key):
                for ring in _polygon_rings(regions[key]):
                    writer.curve(world(ring), role, details)
        elevation, reference = _profile_value(payload, station)
        if elevation is not None:
            axes["design_axis"].append([*center, elevation])
        else:
            ground_center = (section.get("area_result") or {}).get("ground_elevation_center")
            if ground_center is not None and math.isfinite(float(ground_center)):
                axes["ground_centerline"].append([*center, float(ground_center)])
    for role, points in axes.items():
        if len(points) > 1:
            writer.curve(points, role, {"qx_reference": "declared_design_profile" if role == "design_axis" else "known_section_values"})


def _site(writer, payload, tin):
    calculation, inputs = payload.get("calculation_input") or {}, payload.get("inputs") or {}
    bottom = payload.get("bottom_boundary") or calculation.get("bottom_boundary")
    if not bottom and inputs.get("site_boundary"):
        bottom = Polygon(inputs["site_boundary"], inputs.get("site_holes", []))
    if bottom is None:
        raise ValueError("当前基坑结果缺少真实坑底边界")
    bottom_z = _number(calculation.get("bottom_elevation", inputs.get("bottom_elevation", payload.get("bottom_elevation"))), "施工坑底高程")
    for ring in _polygon_rings(bottom):
        writer.curve([[x, y, bottom_z] for x, y in ring], "bottom_boundary", {"qx_bottom_elevation_m": bottom_z})
    boundary = payload.get("calculation_boundary")
    if boundary is None:
        raise ValueError("当前基坑结果缺少计算范围")
    interp = TINInterpolator(tin) if tin is not None else None
    for ring in _polygon_rings(boundary):
        if interp is None:
            writer.curve([[x, y, 0] for x, y in ring], "calculation_plan_boundary",
                         {"qx_elevation_basis": "plan_reference_only_Z0_not_ground"})
            continue
        all_points, complete = [], True
        for a, b in zip(ring, ring[1:]):
            a, b = np.asarray(a), np.asarray(b)
            delta = b-a
            length = float(np.linalg.norm(delta))
            if length <= 0:
                continue
            direction = delta/length
            exact = interp.section_line(a, direction, 0, length)
            world = [[*(a+offset*direction), z] for offset, z in exact]
            world[0][:2], world[-1][:2] = a.tolist(), b.tolist()
            if any(not math.isfinite(p[2]) for p in world):
                complete = False
            all_points.extend(world if not all_points else world[1:])
        if complete and all_points:
            if not math.isclose(all_points[0][2], all_points[-1][2], rel_tol=1e-12, abs_tol=1e-10):
                raise ValueError("同一基坑边界闭合点具有矛盾地形高程")
            all_points[-1] = all_points[0][:]
            writer.curve(all_points, "calculation_ground_boundary", {"qx_elevation_basis": "exact_existing_TIN_edges", "qx_ground_coverage": "complete"})
        else:
            finite = []
            for point in all_points+[None]:
                if point is not None and math.isfinite(point[2]):
                    finite.append(point)
                else:
                    if len(finite) > 1:
                        writer.curve(finite, "calculation_ground_boundary", {"qx_elevation_basis": "exact_existing_TIN_edges", "qx_ground_coverage": "partial_not_closed"})
                    finite = []
            writer.curve([[x, y, 0] for x, y in ring], "calculation_plan_boundary",
                         {"qx_elevation_basis": "plan_reference_only_Z0_not_ground", "qx_ground_coverage": "partial"})


def _original_attributes(model):
    return {obj.Attributes.Id: {"name": obj.Attributes.Name, "layer": obj.Attributes.LayerIndex,
                                "user_strings": dict(obj.Attributes.GetUserStrings())} for obj in model.Objects}


def _verify_saved(source, path, mesh_index, original, expected):
    model = rhino3dm.File3dm.Read(str(path))
    if model is None or model.Settings.ModelUnitSystem != rhino3dm.UnitSystem.Meters:
        raise IOError("保存的 Rhino 校核模型无法读取或单位不为米")
    actual = {obj.Attributes.Id: obj for obj in model.Objects}
    if len(actual) != len(original)+len(expected):
        raise IOError("保存模型的原对象或校核对象数量不一致")
    for identifier, attributes in original.items():
        obj = actual.get(identifier)
        if obj is None or obj.Attributes.Name != attributes["name"] or obj.Attributes.LayerIndex != attributes["layer"] or dict(obj.Attributes.GetUserStrings()) != attributes["user_strings"]:
            raise IOError("保存后原始模型对象或属性发生改变")
    for record in expected:
        obj = actual.get(record["id"])
        if obj is None or any(obj.Attributes.GetUserString(k) != v for k, v in record["strings"].items()):
            raise IOError("保存后校核对象或算量属性不一致")
        if record["role"] == "review_note":
            point = obj.Geometry.Point
            points = np.asarray([[point.X, point.Y, point.Z]])
        elif isinstance(obj.Geometry, rhino3dm.PolylineCurve):
            points = np.asarray([[p.X, p.Y, p.Z] for p in (obj.Geometry.Point(i) for i in range(obj.Geometry.PointCount))])
        elif record.get("representation") == "degree1_nurbs_exact_polyline" and isinstance(obj.Geometry, rhino3dm.NurbsCurve):
            curve = obj.Geometry
            if not curve.IsValid or curve.Degree != 1 or curve.IsRational or any(p.W != 1.0 for p in curve.Points):
                raise IOError("保存后的微短边成果不再是原折线的一阶非有理表示")
            points = np.asarray([[p.X, p.Y, p.Z] for p in curve.Points])
        elif record.get("representation") == "point_marker_exact_zero_world_length" and isinstance(obj.Geometry, rhino3dm.Point):
            point = obj.Geometry.Location
            points = np.asarray([[point.X, point.Y, point.Z]])
        else:
            raise IOError("校核成果未保存为可核查折线")
        if not np.array_equal(points, record["points"]):
            raise IOError("保存后校核曲线世界坐标发生改变")
    mesh_report = {"original_terrain_attached": source is not None}
    if source is not None:
        from tools.terrain_mesh_reader.reader import read_mesh
        before_points, before_faces, before_info = read_mesh(source, mesh_index=mesh_index)
        after_points, after_faces, after_info = read_mesh(path, mesh_index=mesh_index)
        if not np.array_equal(before_points, after_points) or not np.array_equal(before_faces, after_faces):
            raise IOError("保存后的原地形 XYZ 或三角面发生改变；不交付该模型")
        if before_info["double_precision_vertices"] != after_info["double_precision_vertices"]:
            raise IOError("保存后的原地形精度标志发生改变")
        mesh_report.update(vertex_count=len(before_points), face_count=len(before_faces),
                           all_original_XYZ_equal=True, all_original_faces_equal=True,
                           double_precision_vertices=after_info["double_precision_vertices"], mesh_index=after_info["mesh_index"])
    return {"passed": True, **mesh_report, "original_object_count": len(original),
            "added_object_count": len(expected), "all_curve_world_coordinates_equal": True,
            "all_review_attributes_equal": True,
            "display_normalizations": [record["normalization"] for record in expected if record.get("normalization")],
            "quantity_basis": "independent_TIN_integration_not_review_curve_or_solid_volume"}


def export_review_model(payload, path) -> str:
    """保存并严格回读世界坐标 3DM 校核模型及相邻 .review-audit.json。

    3DM 来源直接保留原文档的地形对象，绝不遍历 Point3f 重建网格。
    其他来源仅附成果曲线；原地形未附的事实写入模型说明及属性。
    """
    if payload.get("status") != "READY" or not payload.get("converged"):
        raise ValueError("只有完整、已收敛的当前结果可以导出校核模型")
    if payload.get("units", "m") != "m":
        raise ValueError("世界坐标校核模型仅接受米制结果")
    target = Path(path).resolve()
    if target.suffix.lower() != ".3dm":
        raise ValueError("请选择 3DM 校核模型文件")
    terrain = payload.get("terrain") or payload.get("terrain_metadata") or {}
    source_path = Path(terrain["path"]).resolve() if terrain.get("path") else None
    if source_path is not None and os.path.normcase(str(source_path)) == os.path.normcase(str(target)):
        raise ValueError("校核模型须另存为新文件，不能覆盖原地形")
    source_hash = None
    if source_path is not None:
        if not source_path.is_file():
            raise FileNotFoundError(f"原地形文件不存在：{source_path}")
        source_hash = _hash(source_path)
        if terrain.get("source_sha256") and source_hash != terrain["source_sha256"]:
            raise ValueError("原地形文件已改变，不能导出旧计算结果")
    source = source_path if source_path is not None and source_path.suffix.lower() == ".3dm" else None
    mesh_index = terrain.get("mesh_index")
    if source is not None:
        from tools.terrain_mesh_reader.reader import read_mesh
        vertices, faces, metadata = read_mesh(source, mesh_index=mesh_index)
        mesh_index = metadata["mesh_index"]
        tin = TINModel(points=vertices, triangles=faces)
        model = rhino3dm.File3dm.Read(str(source))
        if model is None:
            raise IOError("原地形 3DM 无法读取")
    else:
        tin = load_terrain(source_path, mesh_index=mesh_index) if source_path is not None else None
        model = rhino3dm.File3dm()
        model.Settings.ModelUnitSystem = rhino3dm.UnitSystem.Meters
    original = _original_attributes(model)
    writer = _Writer(model, payload)
    if payload.get("kind") == "site":
        _site(writer, payload, tin)
    elif payload.get("kind") == "linear":
        _linear(writer, payload)
    else:
        raise ValueError("未知校核成果类型")
    if not writer.expected:
        raise ValueError("结果未包含可导出的校核曲线")
    writer.note(source is not None)
    model.Strings["qx_review_model"] = "curves_for_review_only_not_quantity_solids"
    model.Strings["qx_review_input_hash"] = str(payload.get("input_hash", ""))
    model.Strings["qx_review_terrain_attached"] = str(source is not None).lower()
    model.Strings["qx_review_quantities"] = json.dumps(writer.quantities, ensure_ascii=False, allow_nan=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent/f".qx-review-{uuid.uuid4().hex}.3dm"
    audit_path = target.with_name(target.name+".review-audit.json")
    audit_temporary = target.parent/f".qx-review-{uuid.uuid4().hex}.json"
    try:
        if not model.Write(str(temporary), 8):
            raise IOError("Rhino 校核模型保存失败")
        audit = _verify_saved(source, temporary, mesh_index, original, writer.expected)
        if source_path is not None and _hash(source_path) != source_hash:
            raise ValueError("导出期间原地形发生改变，未交付校核模型")
        audit.update(output_path=str(target), output_sha256=_hash(temporary), source_sha256=source_hash,
                     input_hash=payload.get("input_hash"), quantities=writer.quantities)
        audit_temporary.write_text(json.dumps(audit, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        os.replace(temporary, target)
        os.replace(audit_temporary, audit_path)
    finally:
        temporary.unlink(missing_ok=True)
        audit_temporary.unlink(missing_ok=True)
    return str(target)
