"""Read a station/elevation line for the workbench profile editors."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from pathlib import Path


DXF_PROFILE_FILTER = "DXF (*.dxf)"


def _csv_points(raw):
    rows = csv.reader(io.StringIO(raw.decode("utf-8-sig")))
    points = []
    station_headers = {"station", "station_m", "chainage", "mc", "桩号", "桩号m", "桩号(m)"}
    elevation_headers = {
        "elevation", "elevation_m", "高程", "高程m", "高程(m)", "设计高程", "设计高程(m)",
    }
    for line_number, row in enumerate(rows, 1):
        values = [value.strip() for value in row]
        if not values:
            raise ValueError(f"纵断面CSV第{line_number}行为空，不能跨缺行连接轴线")
        if len(values) != 2:
            raise ValueError(f"纵断面CSV第{line_number}行须包含两列：桩号、高程")
        headers = [value.lower().replace(" ", "").replace("（", "(").replace("）", ")") for value in values]
        if line_number == 1 and headers[0] in station_headers and headers[1] in elevation_headers:
            continue
        try:
            station, elevation = map(float, values)
        except ValueError as error:
            raise ValueError(f"纵断面CSV第{line_number}行含无效桩号或高程，未导入任何数据") from error
        if not math.isfinite(station) or not math.isfinite(elevation):
            raise ValueError(f"纵断面CSV第{line_number}行含非有限数值")
        if points and station <= points[-1]["station"]:
            raise ValueError(f"纵断面CSV第{line_number}行桩号不递增或重复")
        points.append({"station": station, "elevation": elevation})
    return points


def _dxf_geometry(curve):
    if bool(getattr(curve, "closed", False)) or bool(getattr(curve, "is_closed", False)):
        raise ValueError("纵断面DXF轴线不能闭合，请提供有明确起止桩号的真实轴线")
    if tuple(curve.dxf.get("extrusion", (0, 0, 1))) != (0, 0, 1):
        raise ValueError("纵断面轴线坐标平面不明确，请另存为桩号—高程平面轴线")
    if curve.dxftype() == "POLYLINE":
        if not curve.is_2d_polyline:
            raise ValueError("纵断面DXF须为明确的二维桩号—高程轴线，不能忽略三维坐标")
        points = [(vertex.dxf.location.x, vertex.dxf.location.y, vertex.dxf.get("bulge", 0))
                  for vertex in curve.vertices]
    else:
        points = list(curve.get_points("xyb"))
    return {"vertices": [point[:2] for point in points], "bulges": [point[2] for point in points]}


def read_dxf_candidates(path, *, reference="pipe_axis"):
    """Read each model-space polyline independently, including its CAD identity."""
    import ezdxf
    from 土石方计算.services.design_profiles import normalize_design_profile
    from 土石方计算.io.independent_terrain import file_sha256

    path = Path(path).resolve()
    if path.suffix.lower() != ".dxf":
        raise ValueError("请选择 DXF 纵断面轴线文件")
    digest = file_sha256(path)
    try:
        drawing = ezdxf.readfile(path)
    except ezdxf.DXFError as error:
        raise ValueError(f"无法读取纵断面DXF：{error}") from error
    items = []
    for curve in drawing.modelspace().query("LWPOLYLINE POLYLINE"):
        item = {"handle": str(curve.dxf.handle), "layer": str(curve.dxf.layer)}
        try:
            item["profile"] = normalize_design_profile(_dxf_geometry(curve), reference=reference)
        except ValueError as error:
            item["error"] = str(error)
        items.append(item)
    if not items:
        raise ValueError(f"{path.name} 中没有二维多段线")
    if file_sha256(path) != digest:
        raise ValueError("读取期间轴线源文件已改变，请重新导入")
    units = drawing.header.get("$INSUNITS", 0)
    return items, {"path": str(path), "filename": path.name, "sha256": digest,
                   "declared_dxf_units": units, "source_insunits": units}


def read_profile_file(path, *, reference, units, dxf_only=False):
    from 土石方计算.services.design_profiles import normalize_design_profile

    path = Path(path).resolve()
    suffix = path.suffix.lower()
    if dxf_only and suffix != ".dxf":
        raise ValueError("请选择 DXF 纵断面轴线文件")
    if suffix == ".dxf":
        items, source = read_dxf_candidates(path, reference=reference)
        if len(items) != 1:
            raise ValueError("此文件含多条多段线，请在“工程与地形”的管线纵断面中导入并核对匹配结果")
        if "error" in items[0]:
            raise ValueError(items[0]["error"])
        return items[0]["profile"], dict(source, coordinate_units=units), None
    raw = path.read_bytes()
    declared_reference = declared_units = None
    if suffix == ".csv":
        value = _csv_points(raw)
    elif suffix == ".json":
        value = json.loads(raw.decode("utf-8-sig"))
        source = value.get("design_profile", value) if isinstance(value, dict) else value
        declared_reference = source.get("reference") if isinstance(source, dict) else None
    else:
        raise ValueError("请选择 CSV、DXF 或 JSON 纵断面文件")
    profile = normalize_design_profile(value, reference=declared_reference or reference)
    digest = hashlib.sha256(raw).hexdigest()
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError("读取期间轴线源文件已改变，请重新导入")
    source = {"path": str(path), "sha256": digest, "coordinate_units": units,
              "declared_dxf_units": declared_units, "source_insunits": declared_units}
    return profile, source, declared_reference
