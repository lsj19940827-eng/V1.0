"""Editable quantities and review geometry; never label an open mesh a solid."""
from __future__ import annotations
import csv
import json
import math
import os
from pathlib import Path


def export_result(payload, path):
    from app_渠系计算前端.runtime_platform import ensure_safe_windows_platform_queries
    ensure_safe_windows_platform_queries()
    if payload.get("status") != "READY" or not payload.get("converged"):
        raise ValueError("只有完整且已收敛的当前结果可以导出")
    path = Path(path).resolve()
    terrain = payload.get("terrain") or payload.get("terrain_metadata") or {}
    if terrain.get("path"):
        source = Path(terrain["path"]).resolve()
        same_source = os.path.normcase(str(path)) == os.path.normcase(str(source))
        if not same_source:
            try:
                same_source = path.samefile(source)
            except FileNotFoundError:
                pass  # A new result has no inode to compare yet.
        if same_source:
            raise ValueError("成果必须另存为新文件，不能覆盖原地形或其链接")
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    if suffix == ".json":
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    elif suffix in (".xlsx", ".csv"):
        _export_table(payload, path)
    elif suffix == ".dxf":
        _export_dxf(payload, path)
    elif suffix == ".3dm":
        from .independent_model_exporter import export_review_model
        return export_review_model(payload, path)
    else:
        raise ValueError("请选择 XLSX、CSV、DXF、3DM 或完整计算记录 JSON")
    return str(path.resolve())


def _rows(payload):
    rows = [["统计项", "数值", "单位"]]
    if payload.get("test_only"):
        rows.append(["用途","算法验收示例；示例设计参数不代表正式施工设计",""])
    for name, key in (("天然开挖", "excavation_volume"), ("结构周边回填", "backfill_volume"),
                      ("新增填筑", "embankment_volume"), ("总填方", "total_fill_volume"), ("设计面差分填方", "surface_fill_volume")):
        value = payload.get(key)
        rows.append([name, "不适用" if value is None else value, "m³"])
    rows += [["计算方法", payload.get("integration_method", ""), ""],
             ["地形 SHA256", payload.get("terrain", {}).get("source_sha256", ""), ""],
             ["输入 SHA256", payload.get("input_hash", ""), ""], [],
             ["起桩", "止桩", "长度 m", "挖方 m³", "周边回填 m³", "新增填筑 m³", "总填方 m³", "设计面差分填方 m³"]]
    for segment in payload.get("segments", []):
        rows.append([segment.get(key) for key in ("station_start", "station_end", "length",
                     "excavation_volume", "backfill_volume", "embankment_volume", "total_fill_volume", "surface_fill_volume")])
    rows += [[], ["加密轮次", "断面数 / 评估数", "挖方 m³", "挖方加密差 m³",
                  "差分填方加密差 m³", "回填加密差 m³", "新增填筑加密差 m³"]]
    for record in payload.get("convergence_history", []):
        change = record.get("successive_change")
        changes = list(change) if isinstance(change, (list,tuple)) else [change,None,None,None]
        rows.append([record.get("iteration", record.get("refinement", "")),
                     record.get("section_count", record.get("evaluation_count", "")),
                     record.get("excavation_volume", ""), *changes])
    return rows


def _export_table(payload, path):
    rows = _rows(payload)
    if path.suffix.lower() == ".csv":
        with path.open("w", newline="", encoding="utf-8-sig") as stream:
            csv.writer(stream).writerows(rows)
        return
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "工程量与计算依据"
    for row in rows:
        sheet.append(row)
    sheet.freeze_panes = "A2"
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="17365D")
    for column, width in zip("ABCDEFGH", (24, 24, 16, 27, 27, 27, 27, 27)):
        sheet.column_dimensions[column].width = width
    for row in sheet:
        for cell in row:
            if isinstance(cell.value, (int, float)):
                cell.number_format = "0.000"
            cell.alignment = Alignment(vertical="center")
    if payload.get("areas"):
        area_sheet = workbook.create_sheet("断面面积")
        area_sheet.append(["桩号 m", "挖方面积 m²", "差分填方面积 m²", "回填面积 m²", "新增填筑面积 m²"])
        for row in payload["areas"]:
            area_sheet.append([row.get(k) for k in ("station", "excavation_area", "surface_fill_area",
                                                   "backfill_area", "embankment_area")])
        for column in "ABCDE":
            area_sheet.column_dimensions[column].width = 22
    workbook.save(path)


def _finite_runs(points):
    run = []
    for point in points:
        if len(point) >= 2 and all(v is not None and math.isfinite(float(v)) for v in point[:2]):
            run.append(tuple(map(float, point[:2])))
        else:
            if len(run) > 1:
                yield run
            run = []
    if len(run) > 1:
        yield run


def _export_dxf(payload, path):
    import ezdxf
    from shapely.geometry import shape
    document = ezdxf.new("R2013")
    document.units = 6
    for name, color in (("原地面", 3), ("施工开挖", 1), ("结构周边回填", 30), ("新增填筑", 5),
                        ("结构及材料占位", 8), ("标注", 7), ("坑底边界", 5), ("开挖范围", 1)):
        document.layers.new(name, dxfattribs={"color": color})
    model = document.modelspace()
    if payload.get("kind") == "site":
        for key, layer in (("bottom_boundary", "坑底边界"), ("calculation_boundary", "开挖范围")):
            if payload.get(key):
                geometry = shape(payload[key])
                for part in ([geometry] if geometry.geom_type == "Polygon" else geometry.geoms):
                    for ring in [part.exterior, *part.interiors]:
                        model.add_lwpolyline(list(ring.coords), close=True, dxfattribs={"layer": layer})
    else:
        all_sections = payload.get("sections", [])
        def region_rings(section):
            for key, layer in (("excavation", "施工开挖"), ("backfill", "结构周边回填"), ("embankment", "新增填筑"),
                                ("excluded_occupancy", "结构及材料占位")):
                value = (section.get("construction_regions") or {}).get(key)
                if not value:
                    continue
                geometry = shape(value)
                for part in ([geometry] if geometry.geom_type == "Polygon" else geometry.geoms):
                    if part.geom_type == "Polygon" and not part.is_empty:
                        for ring in [part.exterior, *part.interiors]:
                            yield list(ring.coords), layer
        extents = []
        for section in all_sections:
            points = [p for key in ("ground_points", "design_points", "excavation_boundary")
                      for p in section.get(key, []) if p[0] is not None and p[1] is not None]
            points.extend(p for ring, _ in region_rings(section) for p in ring)
            if points:
                extents.append((max(p[0] for p in points)-min(p[0] for p in points),
                                max(p[1] for p in points)-min(p[1] for p in points)))
        column_width = max([100.0]+[width+30 for width,height in extents])
        row_height = max([60.0]+[height+25 for width,height in extents])
        for index, section in enumerate(payload.get("sections", [])):
            gx, gy = (index % 4) * column_width, -(index // 4) * row_height
            finite = [p for p in section.get("ground_points", []) if p[1] is not None]
            baseline = min([float(p[1]) for p in finite] + [float(p[1]) for p in section.get("design_points", [])])
            for key, layer in (("ground_points", "原地面"), ("design_points", "施工开挖"),
                               ("excavation_boundary", "施工开挖")):
                if key == "excavation_boundary" and (section.get("construction_regions") or {}).get("excavation"):
                    continue
                for run in _finite_runs(section.get(key, [])):
                    model.add_lwpolyline([(x+gx, z-baseline+gy) for x, z in run], dxfattribs={"layer": layer})
            for ring, layer in region_rings(section):
                model.add_lwpolyline([(x+gx, z-baseline+gy) for x, z in ring], close=True,
                                     dxfattribs={"layer": layer})
            text = f"S={section['station']:.3f}  Z0={baseline:.3f}m"
            model.add_text(text, dxfattribs={"height": 2.5, "insert": (gx-column_width/3, gy-6), "layer": "标注"})
    model.add_text(f"Cut={payload['excavation_volume']:.3f}m3", dxfattribs={"height": 3, "insert": (0, 12), "layer": "标注"})
    document.saveas(path)
