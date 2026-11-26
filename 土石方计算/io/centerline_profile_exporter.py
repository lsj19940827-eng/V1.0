"""Editable, independently saved centreline profiles with verified readback."""
from __future__ import annotations

from copy import deepcopy
import csv
import hashlib
from itertools import groupby, islice, zip_longest
import json
import math
from pathlib import Path
import tempfile

from .output_staging import output_staging


_APP = "QX_CENTERLINE_PROFILE"
_REFERENCES = {"invert": "设计渠底", "inner_invert": "设计内底", "axis": "管轴", "pipe_axis": "管轴", "common_outer_bottom": "共同外管底",
               "outer_bottom": "共同外管底", "foundation_bottom": "基础底", "bottom": "设计底"}


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _hash(value):
    return hashlib.sha256(_encoded(value)).hexdigest()


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label}必须是有限数值")
    return float(value)


def validate_centerline_profile(profile):
    """Reject non-profile JSON and invalid gaps before saving or displaying it."""
    if not isinstance(profile, dict) or profile.get("kind") != "centerline_longitudinal" or profile.get("schema_version") != "1.0":
        raise ValueError("不是受支持的中心轴线纵断面成果")
    start = _number(profile.get("station_start"), "起桩")
    end = _number(profile.get("station_end"), "止桩")
    if end <= start:
        raise ValueError("纵断面止桩必须大于起桩")
    if _number(profile.get("sample_step"), "纵断面采样间距") <= 0:
        raise ValueError("纵断面采样间距必须为正数")
    points = profile.get("points")
    if not isinstance(points, list) or len(points) < 2:
        raise ValueError("纵断面至少需要两个点")
    previous = start
    for point in points:
        if not isinstance(point, dict):
            raise ValueError("纵断面点记录无效")
        station = _number(point.get("station"), "点桩号")
        if station < start or station > end or station < previous:
            raise ValueError("纵断面点桩号须递增并处于所选范围内")
        previous = station
        for key in ("x", "y"):
            _number(point.get(key), "平面坐标")
        for key in ("ground_elevation", "design_elevation"):
            if point.get(key) is not None:
                _number(point[key], "高程")
        for key in ("design_reference", "design_label", "asset_id", "ground_run_id", "design_run_id"):
            if point.get(key) is not None and not isinstance(point[key], (str, int)):
                raise ValueError("纵断面连续段或基准标识无效")
    if points[0]["station"] != start or points[-1]["station"] != end:
        raise ValueError("纵断面点须包含所选范围的起止桩号")
    for gap in profile.get("missing_ranges", []):
        if not isinstance(gap, dict):
            raise ValueError("缺测区间记录无效")
        a = _number(gap.get("station_start"), "缺测起桩")
        b = _number(gap.get("station_end"), "缺测止桩")
        if not start <= a < b <= end:
            raise ValueError("缺测区间超出纵断面范围")
    if not isinstance(profile.get("metadata", {}), dict) or not isinstance(profile.get("source_identity", {}), dict):
        raise ValueError("纵断面来源信息无效")
    _encoded(profile)
    return profile


def _design_label(point):
    return str(point.get("design_label") or _REFERENCES.get(point.get("design_reference"), "已有设计高程"))


def _runs(profile, role):
    if role == "design":
        return _design_runs(profile)
    key = role + "_elevation"
    run_key = role + "_run_id"
    result, current, identity = [], [], None
    for point in profile["points"]:
        z = point.get(key)
        this_id = (point.get(run_key),) if role == "ground" else (
            point.get(run_key), point.get("asset_id"), point.get("design_reference"), _design_label(point))
        gap = bool(current) and role == "ground" and any(
            current[-1]["station"] < float(g["station_end"]) and point["station"] > float(g["station_start"])
            for g in profile.get("missing_ranges", []))
        if z is None or this_id != identity or gap:
            if current:
                result.append(current)
            current = []
        identity = this_id
        if z is not None:
            if current and current[-1]["station"] == point["station"] and current[-1][key] == z:
                continue
            current.append(point)
    if current:
        result.append(current)
    return result


def _design_runs(profile):
    """Track each design series across a station's interleaved object rows.

    An absent/null series at a sampled station closes only that series. Another
    object's row at the same station must not fragment a valid overlapping line.
    """
    result, active = [], {}
    for _station, rows in groupby(profile["points"], key=lambda point: point["station"]):
        represented = {}
        for point in rows:
            identity = (point.get("design_run_id"), point.get("asset_id"),
                        point.get("design_reference"), _design_label(point))
            represented.setdefault(identity, []).append(point)
        for identity in list(active):
            if identity not in represented:
                result.append(active.pop(identity))
        for identity, points in represented.items():
            for point in points:
                if point.get("design_elevation") is None:
                    if identity in active:
                        result.append(active.pop(identity))
                    continue
                run = active.setdefault(identity, [])
                if run and run[-1]["station"] == point["station"] and run[-1]["design_elevation"] == point["design_elevation"]:
                    continue
                run.append(point)
    result.extend(active.values())
    return result


def profile_line_runs(profile, role):
    """Return continuous ground or design records for display and editable export."""
    if role not in {"ground", "design"}:
        raise ValueError("纵断面图线类型必须为 ground 或 design")
    return _runs(profile, role)


def profile_design_label(point):
    """Use the stored engineering datum and source qualification as its label."""
    return _design_label(point)


def _staging(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".profile-", suffix=path.suffix, delete=False) as stream:
        temporary = Path(stream.name)
    return path, temporary


def _write_json(path, value):
    target, temporary = _staging(path)
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        if json.loads(temporary.read_text(encoding="utf-8")) != value:
            raise ValueError("纵断面JSON保存重开核验失败")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def _file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _station(value):
    sign = "-" if value < 0 else ""
    value = abs(value)
    return f"{sign}{int(value // 1000)}+{value % 1000:07.3f}"


def _nice_step(span, count=7):
    value = max(span / count, 1e-9)
    power = 10 ** math.floor(math.log10(value))
    return next(f * power for f in (1, 2, 2.5, 5, 10) if f * power >= value)


def _chunks(text):
    return [(1, text[i:i + 200]) for i in range(0, len(text), 200)]


def _saved_profile(doc):
    record = doc.rootdict.get(_APP).get("PROFILE")
    return json.loads("".join(str(tag.value) for tag in record.tags if tag.code == 1))


def save_centerline_profile_dxf(profile, path, horizontal_scale=1000, vertical_scale=1000, *, write_audit=True):
    """Save independent editable runs; all unscaled values survive in XRECORD."""
    import ezdxf
    from ezdxf.enums import TextEntityAlignment

    validate_centerline_profile(profile)
    hs, vs = _number(horizontal_scale, "横向比例分母"), _number(vertical_scale, "竖向比例分母")
    if hs <= 0 or vs <= 0:
        raise ValueError("横纵比例分母必须为正数")
    ratio = hs / vs
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 6
    doc.header["$MEASUREMENT"] = 1
    doc.styles.new("QX_CN", dxfattribs={"font": "simhei.ttf"})
    for layer, color in (("轴线天然地面", 3), ("轴线设计高程", 1), ("坐标刻度", 8), ("说明文字", 7), ("地形缺测", 6)):
        doc.layers.new(layer, dxfattribs={"color": color})
    doc.appids.new(_APP)
    msp = doc.modelspace()
    start, end = float(profile["station_start"]), float(profile["station_end"])
    all_z = [float(p[k]) for p in profile["points"] for k in ("ground_elevation", "design_elevation") if p.get(k) is not None]
    low, high = (min(all_z), max(all_z)) if all_z else (0., 1.)
    tick_z = _nice_step(max(high - low, 1.))
    datum = math.floor(low / tick_z) * tick_z
    top = max(datum + tick_z, math.ceil(high / tick_z) * tick_z)
    # Short inspection ranges should remain legible when opened at their extents.
    # Annotation size can shrink independently of the explicitly stated geometry scale.
    text_height = min(hs * .0025, (end - start) / 45)
    graph_height = (top - datum) * ratio
    margin = max(text_height * 5, (end - start) * .035)

    def text(value, x, y, *, layer="说明文字", height=None, center=False, right=False):
        entity = msp.add_text(str(value), dxfattribs={"height": height or text_height, "style": "QX_CN", "layer": layer})
        entity.set_placement((x, y), align=TextEntityAlignment.CENTER if center else TextEntityAlignment.RIGHT if right else TextEntityAlignment.LEFT)
        return entity

    expected = []
    for role, layer in (("ground", "轴线天然地面"), ("design", "轴线设计高程")):
        for run in _runs(profile, role):
            xy = [(float(p["station"]), (float(p[role + "_elevation"]) - datum) * ratio) for p in run]
            if len(xy) < 2:
                entity = msp.add_point(xy[0], dxfattribs={"layer": layer})
            else:
                entity = msp.add_lwpolyline(xy, dxfattribs={"layer": layer})
            label = "天然地面" if role == "ground" else _design_label(run[0])
            entity.set_xdata(_APP, [(1000, role), (1000, label), (1040, datum), (1040, ratio)])
            expected.append({"handle": entity.dxf.handle, "points": xy})
    msp.add_line((start, 0), (end, 0), dxfattribs={"layer": "坐标刻度"})
    msp.add_line((start, 0), (start, graph_height), dxfattribs={"layer": "坐标刻度"})
    tick_x = _nice_step(end - start)
    ticks = sorted({start, end, *[i * tick_x for i in range(math.ceil(start / tick_x), math.floor(end / tick_x) + 1)]})
    label_stations = []
    for station in ticks:
        msp.add_line((station, 0), (station, -text_height), dxfattribs={"layer": "坐标刻度"})
        if station in (start, end) or all(abs(station - other) >= text_height * 8 for other in (start, end, *label_stations)):
            text(_station(station), station, -text_height * 2.4, center=True)
            label_stations.append(station)
    z = datum
    while z <= top + tick_z * 1e-7:
        y = (z - datum) * ratio
        msp.add_line((start, y), (end, y), dxfattribs={"layer": "坐标刻度"})
        text(f"{z:g}", start - text_height, y, right=True)
        z += tick_z
    text("高程(m)", start - margin, graph_height + text_height * 2)
    text("桩号(m)", end, -text_height * 4)
    title_y = graph_height + text_height * 7
    metadata = profile.get("metadata", {})
    test_only = bool(metadata.get("test_only") or any(point.get("design_is_test") for point in profile["points"]))
    text(("TEST " if test_only else "") + str(profile.get("route_name") or "当前线路") + " 中心轴线纵断面", start, title_y, height=text_height * 1.5)
    text(f"起止桩号 {_station(start)} ～ {_station(end)}；横向 1:{hs:g}；竖向 1:{vs:g}", start, title_y - text_height * 2.5)
    for gap in profile.get("missing_ranges", []):
        a, b = float(gap["station_start"]), float(gap["station_end"])
        y = graph_height + text_height
        msp.add_line((a, y), (b, y), dxfattribs={"layer": "地形缺测"})
        text("地形缺测", (a + b) / 2, y + text_height * 1.4, layer="地形缺测", center=True)
    record = doc.rootdict.add_new_dict(_APP).add_xrecord("PROFILE")
    record.reset(_chunks(_encoded(profile).decode("utf-8")))
    # Make the model immediately visible in CAD after opening.
    view_bottom = -text_height * 6
    view_top = title_y + text_height * 3
    doc.set_modelspace_vport(height=max(view_top - view_bottom, (end - start) / 1.6),
                             center=((start + end) / 2, (view_top + view_bottom) / 2))
    target, temporary = _staging(path)
    try:
        doc.saveas(temporary)
        saved = ezdxf.readfile(temporary)
        auditor = saved.audit()
        if auditor.errors or _saved_profile(saved) != profile:
            raise ValueError("纵断面DXF保存重开或真实高程核验失败")
        for item in expected:
            entity = saved.entitydb.get(item["handle"])
            actual = [(float(x), float(y)) for x, y in entity.get_points("xy")] if entity.dxftype() == "LWPOLYLINE" else [tuple(entity.dxf.location)[:2]]
            if len(actual) != len(item["points"]) or any(a != b for a, b in zip(actual, item["points"])):
                raise ValueError("纵断面DXF折线点保存重开核验失败")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    audit = {"saved_reopened": True, "audit_errors": 0, "actual_points_verified": True,
             "missing_ranges_disconnected": True, "design_runs_disconnected": True,
             "raw_profile_verified": True, "profile_sha256": _hash(profile), "sha256": _file_hash(target),
             "test_only": test_only, "design_issue_count": len(metadata.get("design_issues", [])),
             "ground_run_count": len(_runs(profile, "ground")), "design_run_count": len(_runs(profile, "design")),
             "horizontal_scale": hs, "vertical_scale": vs, "vertical_exaggeration": ratio, "elevation_datum": datum}
    if write_audit:
        _write_json(target.with_suffix(target.suffix + ".audit.json"), audit)
    return audit


_CSV_HEADERS = ["桩号(m)", "X(m)", "Y(m)", "天然地面高程(m)", "设计高程(m)", "设计高程基准", "设计线名称", "对象标识", "地面连续段", "设计连续段"]
_CSV_KEYS = ["station", "x", "y", "ground_elevation", "design_elevation", "design_reference", "design_label", "asset_id", "ground_run_id", "design_run_id"]


def save_centerline_profile_csv(profile, path):
    validate_centerline_profile(profile)
    target, temporary = _staging(path)
    expected = [["" if p.get(key) is None else str(p[key]) for key in _CSV_KEYS] for p in profile["points"]]
    try:
        with temporary.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(_CSV_HEADERS)
            writer.writerows(expected)
        with temporary.open(encoding="utf-8-sig", newline="") as stream:
            saved = list(csv.reader(stream))
        if saved != [_CSV_HEADERS, *expected]:
            raise ValueError("纵断面CSV保存重开核验失败")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    audit = {"saved_reopened": True, "point_count": len(expected), "actual_points_verified": True,
             "profile_sha256": _hash(profile), "sha256": _file_hash(target)}
    _write_json(target.with_suffix(target.suffix + ".audit.json"), audit)
    return audit


_XLSX_HEADERS = _CSV_HEADERS[:7]
_XLSX_KEYS = _CSV_KEYS[:7]
_XLSX_ROWS_PER_SHEET = 1_048_575


def _elevation_row(point):
    values = tuple(point.get(key) for key in _XLSX_KEYS)
    reference = values[5]
    return (*values[:5], _REFERENCES.get(reference, reference), values[6])


def save_centerline_profile_xlsx(profile, path, *, cancel_check=None):
    """Save a numeric elevation table and verify each worksheet on readback."""
    from openpyxl import Workbook, load_workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    validate_centerline_profile(profile)
    points = profile["points"]
    pages = range(0, len(points), _XLSX_ROWS_PER_SHEET)
    workbook = Workbook(write_only=True)
    heading_font = Font(name="微软雅黑", bold=True, color="FFFFFF")
    heading_fill = PatternFill("solid", fgColor="234E70")
    for page, start in enumerate(pages, 1):
        end = min(start + _XLSX_ROWS_PER_SHEET, len(points))
        name = "高程表" if len(pages) == 1 else f"高程表 {page}"
        sheet = workbook.create_sheet(name)
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = f"A1:G{end - start + 1}"
        for column, width in enumerate((18, 19, 19, 23, 18, 22, 28), 1):
            sheet.column_dimensions[get_column_letter(column)].width = width
        headings = []
        for label in _XLSX_HEADERS:
            cell = WriteOnlyCell(sheet, value=label)
            cell.font, cell.fill = heading_font, heading_fill
            headings.append(cell)
        sheet.append(headings)
        for index in range(start, end):
            row = []
            for column, value in enumerate(_elevation_row(points[index])):
                cell = WriteOnlyCell(sheet, value=value)
                if column < 5 and value is not None:
                    cell.number_format = "0.000000"
                elif isinstance(value, str):
                    cell.data_type = "s"
                row.append(cell)
            sheet.append(row)

    target, temporary = _staging(path)
    try:
        workbook.save(temporary)
        if cancel_check:
            cancel_check()
        saved = load_workbook(temporary, read_only=True, data_only=True)
        try:
            for sheet, start in zip(saved.worksheets, pages, strict=True):
                end = min(start + _XLSX_ROWS_PER_SHEET, len(points))
                actual = sheet.iter_rows(max_col=len(_XLSX_KEYS), values_only=True)
                if next(actual, ()) != tuple(_XLSX_HEADERS):
                    raise ValueError("纵断面高程表表头回读不一致")
                expected = map(_elevation_row, islice(points, start, end))
                for index, (row, reference) in enumerate(zip_longest(actual, expected)):
                    if cancel_check and index % 4096 == 0:
                        cancel_check()
                    if row is None or reference is None or any(
                        value != original and not (
                            isinstance(value, (int, float)) and isinstance(original, (int, float))
                            and math.isclose(value, original, rel_tol=1e-15, abs_tol=1e-12)
                        ) for value, original in zip(row, reference, strict=True)
                    ):
                        raise ValueError("纵断面高程表桩号、坐标或高程回读不一致")
        finally:
            saved.close()
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return {"saved_reopened": True, "point_count": len(points), "actual_points_verified": True,
            "profile_sha256": _hash(profile), "sha256": _file_hash(target)}


def load_centerline_profile(path):
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict) or "profile" not in value or not isinstance(value.get("content_sha256"), str):
        raise ValueError("纵断面成果缺少内容校验信息")
    profile = value["profile"]
    validate_centerline_profile(profile)
    if _hash(profile) != value["content_sha256"]:
        raise ValueError("纵断面成果内容校验失败，文件可能已被修改")
    return profile


def save_centerline_profile_bundle(profile, directory, horizontal_scale=1000, vertical_scale=1000, cancelled=None):
    def check_cancelled():
        if cancelled and cancelled():
            raise ValueError("纵断面成果保存已取消")

    check_cancelled()
    validate_centerline_profile(profile)
    directory = Path(directory).resolve()
    if directory.exists():
        raise ValueError("纵断面成果目录已存在，请选择新的保存目录")
    directory.parent.mkdir(parents=True, exist_ok=True)
    names = {"json_path": "纵断面成果.json", "dxf_path": "中心轴线纵断面.dxf", "xlsx_path": "高程表.xlsx"}
    profile_hash = _hash(profile)
    with output_staging(directory.parent, prefix=".profile-export-") as staging:
        check_cancelled()
        json_path = staging / names["json_path"]
        _write_json(json_path, {"schema_version": "1.0", "content_sha256": profile_hash, "profile": profile})
        if load_centerline_profile(json_path) != profile:
            raise ValueError("纵断面成果JSON保存重开核验失败")
        check_cancelled()
        dxf = save_centerline_profile_dxf(profile, staging / names["dxf_path"],
            horizontal_scale=horizontal_scale, vertical_scale=vertical_scale, write_audit=False)
        check_cancelled()
        xlsx = save_centerline_profile_xlsx(profile, staging / names["xlsx_path"], cancel_check=check_cancelled)
        files = {names["json_path"]: _file_hash(json_path), names["dxf_path"]: dxf["sha256"],
                 names["xlsx_path"]: xlsx["sha256"]}
        check_cancelled()
        staging.rename(directory)
    audit = {"saved_reopened": True, "profile_sha256": profile_hash, "point_count": len(profile["points"]),
             "files": files, "source_identity": deepcopy(profile.get("source_identity", {})), "dxf": dxf, "xlsx": xlsx}
    paths = {key: str(directory / name) for key, name in names.items()}
    return {**paths, "directory": str(directory), "paths": paths, "sha256": deepcopy(files), "audit": audit}
