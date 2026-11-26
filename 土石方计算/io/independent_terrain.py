"""Read existing meshes or build a source-backed terrain without Rhino."""
from __future__ import annotations

import hashlib
import json
import csv
import tempfile
import zipfile
from copy import deepcopy
from pathlib import Path

import numpy as np

from ..models.terrain import TINModel, TerrainPoint, ConstraintEdge


_MIN_PROJECTED_TWICE_AREA_M2 = 1e-12


class TerrainImportError(ValueError):
    """Actionable survey ambiguity or conflict; the UI can show the report."""

    def __init__(self, message, import_report):
        super().__init__(message)
        self.import_report = import_report


def _mesh_digest(points, triangles):
    digest = hashlib.sha256()
    for array in (np.asarray(points, dtype="<f8"), np.asarray(triangles, dtype="<i8")):
        digest.update(array.tobytes())
    return digest.hexdigest()


def file_sha256(path, cancelled=None):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            if cancelled and cancelled():
                raise InterruptedError("已取消地形读取")
            digest.update(chunk)
    return digest.hexdigest()


def _projected_twice_area(points, triangles):
    xy = points[triangles, :2]
    a, b = xy[:, 1] - xy[:, 0], xy[:, 2] - xy[:, 0]
    return a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]


def validate_mesh(points, triangles):
    points = np.asarray(points, dtype=np.float64)
    raw = np.asarray(triangles)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) < 3 or not np.isfinite(points).all():
        raise ValueError("地形必须包含至少三个有限的 XYZ 顶点")
    if raw.ndim != 2 or raw.shape[1] != 3 or not len(raw) or not np.issubdtype(raw.dtype, np.integer):
        raise ValueError("地形面必须是非空的三顶点整数索引")
    triangles = raw.astype(np.int64, copy=False)
    if triangles.min() < 0 or triangles.max() >= len(points):
        raise ValueError("地形三角面引用了不存在的顶点")
    if np.any(np.abs(_projected_twice_area(points, triangles)) <= _MIN_PROJECTED_TWICE_AREA_M2):
        raise ValueError("地形包含平面投影退化的三角面；请检查地形网格")
    return points, triangles


def _import_progress(progress, cancelled, stage, message):
    if cancelled and cancelled():
        raise InterruptedError("已取消地形处理")
    if progress:
        progress(stage, 0.0, message)


def _survey_corridor(path, options):
    if options.get("route_corridor") is None or options.get("released_constraint_segments"):
        return None
    from ezdxf.lldxf.validator import is_binary_dxf_file
    from .terrain_corridor import TerrainCorridor

    return None if is_binary_dxf_file(path) else TerrainCorridor(options["route_corridor"])


def _survey_scan_options(corridor, progress, cancelled):
    if corridor is None:
        return {}

    def scanned(total, kept):
        _import_progress(progress, cancelled, "terrain_sources",
                         f"正在读取工程走廊地形。已扫描 {total:,} 个原图对象，保留 {kept:,} 个测点及等高线片段。")

    return {"corridor": corridor, "on_scanned": scanned}


def load_terrain(path, *, mesh_index=None, units="m", cancelled=None,
                 terrain_mode="combined", terrain_options=None, progress=None) -> TINModel:
    """Load a mesh unchanged, or build survey points/contours as constrained TIN.

    The unit argument is an explicit declaration for exchange files without
    a unit header. A 3dm's own model units are always checked by its reader.
    ``terrain_options`` accepts point_layers, contour_layers, curve_tolerance,
    contour_interval (0 keeps every original vertex), automatic_boundary,
    boundary_gap_factor, filter_elevation_outliers, quality_policy, boundary,
    holes, core_console, excluded_sources, released_constraint_segments,
    duplicate_point_policy, contour_crossing_policy and clean_output_dir. Raw
    survey imports also save a clean GCD/contour DXF, point table and source
    report; set export_clean_terrain=False for a deliberate read-only operation. The confirmed
    default points_priority retains measured heights while touching contour
    constraints yield locally. Point/point and contour/contour contradictions
    use max and release_conflicting_segments respectively, with complete
    original source/height and local release records. A caller can select stop
    for explicit review. Conflicts not resolved by those rules still raise
    TerrainImportError with source identities and location.
    ``points`` mode keeps only measurement
    sources while ``combined`` also preserves accepted contour constraints.
    A route_corridor bounds an ASCII survey read before mesh construction.
    Existing face meshes and manually selected original constraint indices
    retain their unscoped behavior.
    """
    _import_progress(progress, cancelled, "terrain_read", "正在读取并核对原始地形资料。")
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"地形文件不存在：{path}")
    if units != "m":
        raise ValueError("请将地形坐标统一为米后导入")
    if terrain_mode not in ("points", "combined"):
        raise ValueError("地形模式请选择 points 或 combined")
    options = dict(terrain_options or {})
    source_hash = file_sha256(path, cancelled)
    suffix = path.suffix.lower()
    metadata = {}
    if suffix == ".3dm":
        from tools.terrain_mesh_reader.reader import read_mesh
        points, triangles, metadata = read_mesh(path, mesh_index=mesh_index, cancelled=cancelled)
    elif suffix == ".npz":
        with np.load(path, allow_pickle=False) as values:
            points = values["points"] if "points" in values else values["vertices"]
            triangles = values["triangles"] if "triangles" in values else values["faces"]
            if "import_report" in values:
                metadata = json.loads(str(values["import_report"].item()))
            saved_constraints = values.get("constraint_edges", np.empty((0, 2), dtype=np.int64))
            measured_points = values.get("measured_points", np.empty((0, 3), dtype=np.float64))
            contour_points = values.get("source_contour_points", np.empty((0, 3), dtype=np.float64))
            contour_offsets = values.get("source_contour_offsets", np.array([0], dtype=np.int64))
            source_identities = json.loads(str(values.get("source_identities", np.array("{}")).item()))
            used_measured_points = values.get("used_measured_points", measured_points)
    elif suffix == ".json":
        values = json.loads(path.read_text(encoding="utf-8-sig"))
        if values.get("unit_system", values.get("units", "m")) not in ("m", "Meters"):
            raise ValueError("网格资源不是米制坐标")
        points = values.get("vertices", values.get("points"))
        triangles = values.get("faces", values.get("triangles"))
        if points is None or triangles is None:
            raise ValueError("该文件没有现成的三角网")
    elif suffix == ".dxf":
        import ezdxf
        from .dxf_terrain_reader import DXFTerrainReader
        reader = DXFTerrainReader(str(path))
        corridor = _survey_corridor(path, options)
        _import_progress(progress, cancelled, "terrain_sources", "正在识别测点、等高线并排除原图杂项。")
        data = (reader.read_terrain_sources(terrain_options=options, cancelled=cancelled,
                    **_survey_scan_options(corridor, progress, cancelled)) if corridor is not None else None)
        if data is not None and data["report"]["source_has_3dface"]:
            data = None
        if data is None:
            document = ezdxf.readfile(path)
            if document.modelspace().query("3DFACE"):
                points, triangles = _read_dxf_faces(path, document=document)
            else:
                reader._doc = document
                data = reader.read_terrain_sources(terrain_options=options, cancelled=cancelled)
        if data is not None:
            data["report"].update(path=str(path), source_sha256=source_hash, terrain_mode=terrain_mode)
            tin = _build_survey_tin(data["sources"], data["report"], path, terrain_mode, options, cancelled, progress)
            return _finish_survey(tin, path, source_hash, terrain_mode, cancelled, progress)
    elif suffix in (".csv", ".xyz", ".txt", ".tsv"):
        try:
            sources, report = _read_point_table(path, options, cancelled)
        except TerrainImportError as exc:
            exc.import_report.update(path=str(path), source_sha256=source_hash, terrain_mode=terrain_mode)
            raise
        report.update(path=str(path), source_sha256=source_hash, terrain_mode=terrain_mode)
        tin = _build_survey_tin(sources, report, path, terrain_mode, options, cancelled, progress)
        return _finish_survey(tin, path, source_hash, terrain_mode, cancelled, progress)
    elif suffix == ".dwg":
        from .terrain_preprocessor import convert_dwg_to_dxf
        from .dxf_terrain_reader import DXFTerrainReader
        _import_progress(progress, cancelled, "terrain_convert", "正在转换原始 DWG 地形图，首次读取需启动 CAD 读取组件。")
        with tempfile.TemporaryDirectory(prefix="qx-section-terrain-") as temporary:
            converted = Path(temporary) / "survey.dxf"
            conversion = convert_dwg_to_dxf(path, converted, cancelled=cancelled,
                                             core_console=options.get("core_console"),
                                             cache_dir=Path(options["clean_output_dir"])/".dwg-cache" if options.get("clean_output_dir") else None)
            _import_progress(progress, cancelled, "terrain_sources", "正在识别测点、等高线并排除原图杂项。")
            corridor = _survey_corridor(converted, options)
            data = DXFTerrainReader(str(converted)).read_terrain_sources(
                terrain_options=options, cancelled=cancelled,
                **_survey_scan_options(corridor, progress, cancelled))
            data["report"]["dwg_conversion"] = conversion
            data["report"].update(path=str(path), source_sha256=source_hash, terrain_mode=terrain_mode)
            tin = _build_survey_tin(data["sources"], data["report"], path, terrain_mode, options, cancelled, progress)
        return _finish_survey(tin, path, source_hash, terrain_mode, cancelled, progress)
    else:
        raise ValueError("请选择 DXF/DWG 测量图、CSV/XYZ 测点或已有地形网格（3DM、JSON、NPZ）")
    _import_progress(progress, cancelled, "terrain_validate", "正在校验计算地形及原图完整性。")
    points, triangles = validate_mesh(points, triangles)
    if file_sha256(path, cancelled) != source_hash:
        raise ValueError("读取期间地形文件已改变，请重新读取")
    tin = TINModel(points=points, triangles=triangles,
                   source_files=[str(path)], source_mtimes=[path.stat().st_mtime])
    if suffix == ".npz":
        tin.constraint_edges = [ConstraintEdge(int(i), int(j)) for i, j in saved_constraints]
        tin.measured_points = np.asarray(measured_points, dtype=np.float64)
        tin.source_contours = [contour_points[first:last].tolist()
                               for first, last in zip(contour_offsets[:-1], contour_offsets[1:])]
        tin.used_measured_points = np.asarray(used_measured_points, dtype=np.float64)
        tin.point_source_identities = source_identities.get("points", [])
        tin.contour_source_identities = source_identities.get("contours", [])
    if options.get("boundary") is not None or options.get("holes"):
        _clip_survey_mesh(tin, options.get("boundary"), options.get("holes", []), cancelled)
        points, triangles = tin.points, tin.triangles
    original_source = metadata.get("original_source", {"path": metadata.get("path"),
                                                       "source_sha256": metadata.get("source_sha256")})
    tin.import_report = {**metadata, "path": str(path), "source_sha256": source_hash,
                         "units": "m", "vertex_count": len(points), "face_count": len(triangles),
                         "bounds": [points.min(axis=0).tolist(), points.max(axis=0).tolist()],
                         "topology": "existing_mesh", "mesh_index": metadata.get("mesh_index", mesh_index)}
    # A mesh request never changes the actual persisted survey mode. The UI
    # can offer explicit rebuilding below; default cache loads stay byte exact.
    tin.import_report["load_operation"] = "reuse_existing_mesh"
    tin.import_report["requested_terrain_mode"] = terrain_mode
    tin.import_report["terrain_sha256"] = _mesh_digest(tin.points, tin.triangles)
    if original_source.get("source_sha256"):
        tin.import_report["original_source"] = original_source
    if hasattr(tin, "boundary_report"):
        tin.import_report["boundary_report"] = tin.boundary_report
        tin.import_report["topology"] = "existing_mesh_explicit_clip"
    return tin


def _survey_source_identity(source):
    identity = {key: source.get(key) for key in ("kind", "layer", "source_handle", "source_kind")}
    identity.update({key: source[key] for key in ("fragment_id", "cad_source") if key in source})
    return identity


def _snapshot_digest(sources):
    digest=hashlib.sha256()
    for source in sources:
        identity=_survey_source_identity(source)
        digest.update(json.dumps(identity,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8"))
        values=np.asarray(source["points"],dtype="<f8")
        digest.update(np.asarray(values.shape,dtype="<i8").tobytes());digest.update(values.tobytes())
    return digest.hexdigest()


def _portable_options(options):
    def convert(value):
        if isinstance(value,np.ndarray):return value.tolist()
        if isinstance(value,np.generic):return value.item()
        if isinstance(value,Path):return str(value)
        if isinstance(value,set):return sorted(value)
        if hasattr(value,"__geo_interface__"):return value.__geo_interface__
        raise TypeError(f"地形设置不能保存：{type(value).__name__}")
    return json.loads(json.dumps(options,ensure_ascii=False,default=convert))


def _rebuild_options(report, overrides):
    options=deepcopy(report.get("terrain_options",{}))
    for key in ("conflict_policy","duplicate_point_policy","contour_crossing_policy"):
        if key in report:options.setdefault(key,report[key])
    boundary=report.get("boundary_report",{})
    if boundary.get("mode") in ("convex_hull","automatic_local_spacing"):
        options.setdefault("automatic_boundary",boundary["mode"]=="automatic_local_spacing")
    if "gap_factor" in boundary:options.setdefault("boundary_gap_factor",boundary["gap_factor"])
    for saved,key in (("requested_boundary","boundary"),("requested_holes","holes")):
        if saved in boundary:options.setdefault(key,deepcopy(boundary[saved]))
    quality=report.get("quality_report",{})
    if quality.get("enabled") is False:options.setdefault("filter_elevation_outliers",False)
    if "policy" in quality:options.setdefault("quality_policy",deepcopy(quality["policy"]))
    if "curve_tolerance_m" in report:options.setdefault("curve_tolerance",report["curve_tolerance_m"])
    for key in ("point_layers","contour_layers"):
        if report.get(key):options.setdefault(key,deepcopy(report[key]))
    if report.get("explicit_constraint_releases"):
        options.setdefault("released_constraint_segments",[[v["source_handle"],v["segment_index"]] for v in report["explicit_constraint_releases"]])
    if report.get("user_excluded_entities"):
        options.setdefault("excluded_sources",sorted({v["source_handle"] for v in report["user_excluded_entities"]}))
    options.update(deepcopy(overrides or {}))
    return options


def _cached_survey_sources(tin,report):
    def fail(message):
        raise TerrainImportError(message,{"requires_confirmation":False,"rebuild_error":"incomplete_survey_snapshot", "saved_terrain_mode":report.get("terrain_mode"),"details":message})
    try:points=np.asarray(getattr(tin,"measured_points",np.empty((0,3))),dtype=np.float64)
    except (TypeError,ValueError):fail("缓存原始测点 XYZ 数据无效")
    curves=getattr(tin,"source_contours",[])
    point_ids=getattr(tin,"point_source_identities",[]);curve_ids=getattr(tin,"contour_source_identities",[])
    counts=(report.get("original_point_count"),report.get("original_contour_count"))
    if counts[0] is None or counts[1] is None or len(points)!=counts[0] or len(curves)!=counts[1]:
        fail("缓存没有完整原始测点/等高线数量证据，不能切换建网模式；请导入原调查源")
    if points.ndim!=2 or points.shape[1]!=3 or not np.isfinite(points).all() or len(point_ids)!=len(points) or len(curve_ids)!=len(curves):
        fail("原始测量坐标或来源身份不完整，不能用现成网格顶点替代测点")
    original=report.get("original_source",{})
    original_hash=original.get("source_sha256") or report.get("source_sha256")
    valid_hash=original_hash and len(str(original_hash))==64 and all(c in "0123456789abcdef" for c in str(original_hash).lower())
    if not valid_hash or report.get("coordinates")!="original_WCS_float64" or report.get("source_unchanged") is not True:
        fail("缓存缺少原调查源 SHA 和原始高程保存证据")
    sources=[]
    for kind,values,identities in (("point",points,point_ids),("polyline",curves,curve_ids)):
        for value,identity in zip(values,identities):
            try:array=np.asarray(value,dtype=np.float64).reshape(-1,3)
            except (TypeError,ValueError):fail("原始测量对象没有完整 XYZ")
            if not isinstance(identity,dict) or identity.get("kind")!=kind or not identity.get("source_handle") or not identity.get("layer") or not identity.get("source_kind"):
                fail("原始测量对象的类型/图层/来源编号缺失")
            if not np.isfinite(array).all() or len(array)<(1 if kind=="point" else 2):fail("原始测量对象没有完整有限 XYZ")
            sources.append({**deepcopy(identity),"points":array.tolist()})
    if not sources:fail("缓存只有现成地形网格，缺少可重建的原始测量资料")
    checksum=_snapshot_digest(sources)
    if report.get("source_snapshot_sha256") and report["source_snapshot_sha256"]!=checksum:
        fail("缓存原始测量资料校验不一致，不能重建指定模式")
    return sources,checksum


def rebuild_terrain_mode(tin_or_snapshot, mode, *, terrain_options=None, cancelled=None) -> TINModel:
    """Explicitly rebuild measured sources; never relabel an existing mesh.

    Original survey bytes with matching SHA take priority. If unavailable or
    changed, a complete source-backed snapshot can recreate the approved
    survey. Both branches preserve the input TIN/cache and inherit its policies,
    declared boundary and holes. Bare meshes cannot fabricate survey modes.
    """
    if mode not in ("points","combined"):raise ValueError("重建模式请选择 points 或 combined")
    tin=load_terrain(tin_or_snapshot,cancelled=cancelled) if isinstance(tin_or_snapshot,(str,Path)) else tin_or_snapshot
    if not isinstance(tin,TINModel):raise TypeError("请提供 TINModel 或保存的地形快照路径")
    if cancelled and cancelled():raise InterruptedError("已取消地形模式重建")
    report=deepcopy(getattr(tin,"import_report",{}));options=_rebuild_options(report,terrain_options)
    original=deepcopy(report.get("original_source") or {"path":report.get("path"),"source_sha256":report.get("source_sha256")})
    check={"path":original.get("path"),"expected_sha256":original.get("source_sha256"),"status":"missing_source_identity"}
    source=Path(original["path"]).resolve() if original.get("path") else None
    survey_extensions={".dxf",".dwg",".csv",".xyz",".txt",".tsv"}
    if source and check["expected_sha256"]:
        if not source.is_file():check["status"]="source_missing"
        elif source.suffix.lower() not in survey_extensions:check["status"]="source_is_existing_mesh"
        else:
            try:
                check["actual_sha256"]=file_sha256(source,cancelled)
                check["status"]="sha256_matches" if check["actual_sha256"]==check["expected_sha256"] else "sha256_changed"
            except OSError as exc:check.update(status="source_unreadable",error=str(exc))
    parent_hash=report.get("terrain_sha256") or _mesh_digest(tin.points,tin.triangles)
    if check["status"]=="sha256_matches":
        rebuilt=load_terrain(source,terrain_mode=mode,terrain_options=options,cancelled=cancelled)
        if rebuilt.import_report.get("topology") in ("source_point_tin","source_constrained_tin"):
            rebuilt.import_report.update(original_source=original,load_operation="rebuild_survey_mode",
                mode_rebuild={"previous_mode":report.get("terrain_mode"),"requested_mode":mode,"basis":"verified_original_survey", "original_source_check":check,"parent_terrain_sha256":parent_hash,"input_snapshot_modified":False})
            return rebuilt
        check["status"]="verified_source_has_mesh_only"
    try:sources,checksum=_cached_survey_sources(tin,report)
    except TerrainImportError as exc:
        exc.import_report.update(requested_terrain_mode=mode,original_source_check=check)
        raise
    basis_path=Path(report.get("path") or (tin.source_files[0] if tin.source_files else "approved-in-memory-survey.npz"))
    cache_hash=file_sha256(basis_path,cancelled) if basis_path.is_file() and basis_path.suffix.lower()==".npz" else None
    if cache_hash and report.get("source_sha256") and cache_hash!=report["source_sha256"]:
        raise TerrainImportError("已加载的地形缓存字节已改变，请重新读取",
            {"rebuild_error":"snapshot_changed_since_load","path":str(basis_path),"expected_sha256":report["source_sha256"],"actual_sha256":cache_hash})
    build_report={"reader":"cached_survey_snapshot","source_insunits":6,"original_source":original,
                  "path":str(basis_path),"source_sha256":cache_hash or original.get("source_sha256"),
                  "snapshot_original_reader":report.get("snapshot_original_reader",report.get("reader")),
                  "point_entity_count":len(getattr(tin,"measured_points",[])),"contour_entity_count":len(getattr(tin,"source_contours",[]))}
    if "corridor_preparation" in report:
        build_report["corridor_preparation"] = deepcopy(report["corridor_preparation"])
    rebuilt=_build_survey_tin(sources,build_report,basis_path,mode,options,cancelled)
    rebuilt.points,rebuilt.triangles=validate_mesh(rebuilt.points,rebuilt.triangles)
    if cache_hash and file_sha256(basis_path,cancelled)!=cache_hash:raise ValueError("重建期间原地形缓存已改变，请重新读取")
    rebuilt.import_report.update(units="m",vertex_count=len(rebuilt.points),face_count=len(rebuilt.triangles),
        terrain_sha256=_mesh_digest(rebuilt.points,rebuilt.triangles),bounds=[rebuilt.points.min(axis=0).tolist(),rebuilt.points.max(axis=0).tolist()],
        load_operation="rebuild_survey_mode",mode_rebuild={"previous_mode":report.get("terrain_mode"),"requested_mode":mode,
        "basis":"complete_saved_survey_sources","original_source_check":check,"source_snapshot_sha256":checksum,
        "snapshot_checksum_verified":bool(report.get("source_snapshot_sha256")),"parent_terrain_sha256":parent_hash,"input_snapshot_modified":False})
    return rebuilt


def _read_dxf_faces(path, document=None):
    import ezdxf
    document = document or ezdxf.readfile(path)
    if document.header.get("$INSUNITS", 0) not in (0, 6):
        raise ValueError("DXF 图形单位不是米；请先转换单位")
    points, faces, lookup = [], [], {}
    for face in document.modelspace().query("3DFACE"):
        vertices = [tuple(getattr(face.dxf, f"vtx{i}")) for i in range(4)]
        if vertices[2] != vertices[3]:
            raise ValueError("DXF 含四边形面，请先转为三角面再导出")
        indices = []
        for vertex in vertices[:3]:
            if vertex not in lookup:
                lookup[vertex] = len(points)
                points.append(vertex)
            indices.append(lookup[vertex])
        faces.append(indices)
    if not faces:
        raise ValueError("DXF 未包含已有三角面")
    return points, np.asarray(faces, dtype=np.int64)


def _read_point_table(path, options, cancelled):
    content = path.read_text(encoding=options.get("encoding", "utf-8-sig"))
    rows = [(index, line.strip()) for index, line in enumerate(content.splitlines(), 1)
            if line.strip() and not line.lstrip().startswith(("#", "//"))]
    if not rows:
        raise ValueError("测点文件没有数据")
    delimiter = options.get("delimiter")
    if delimiter is None:
        first = rows[0][1]
        delimiter = next((v for v in (",", "\t", ";") if v in first), None)

    def cells(line):
        return next(csv.reader([line], delimiter=delimiter)) if delimiter else line.split()

    first = [v.strip() for v in cells(rows[0][1])]
    aliases = ({"x", "东坐标", "easting"}, {"y", "北坐标", "northing"}, {"z", "高程", "标高", "elevation", "height"})
    lower = [v.lower() for v in first]
    columns = options.get("columns")
    has_header = all(any(v in aliases[index] for v in lower) for index in range(3))
    if columns is not None:
        columns = [int(v) for v in columns]
        if len(columns) != 3 or len(set(columns)) != 3 or min(columns) < 0:
            raise ValueError("测点列索引应为三个不同的非负整数 [X,Y,Z]")
        start = 1 if has_header or options.get("has_header") else 0
    elif has_header:
        columns = [next(i for i, v in enumerate(lower) if v in names) for names in aliases]
        start = 1
    elif len(first) == 3:
        columns, start = [0, 1, 2], 0
    else:
        raise TerrainImportError("无法确定测点 X、Y、高程列，请核对列对应关系",
                                 {"reader": "point_table", "columns_preview": first,
                                  "requires_confirmation": True, "ambiguity": "xyz_columns"})
    sources, invalid = [], []
    for position, (line_number, line) in enumerate(rows[start:]):
        if cancelled and position % 256 == 0 and cancelled():
            raise InterruptedError("已取消地形读取")
        try:
            data = cells(line)
            xyz = [float(data[index].strip()) for index in columns]
            if not np.isfinite(xyz).all():
                raise ValueError("坐标或高程非有限数")
            sources.append({"kind": "point", "layer": "测点表", "source_handle": f"row:{line_number}",
                            "source_kind": "XYZ_ROW", "points": [xyz]})
        except (ValueError, IndexError) as exc:
            invalid.append({"row": line_number, "reason": str(exc)})
    return sources, {"reader": "point_table", "columns": columns,
                     "input_row_count": len(rows) - start, "invalid_entities": invalid,
                     "point_entity_count": len(sources), "contour_entity_count": 0,
                     "source_insunits": 6, "ambiguous_layers": []}


def _check_source_conflicts(sources, report, cancelled, *, reject=True):
    """Report duplicate XY and conflicting constraint intersections before CDT."""
    from scipy.spatial import cKDTree
    import shapely
    from shapely.strtree import STRtree

    arrays = [np.asarray(v["points"], dtype=np.float64) for v in sources]
    positions = np.concatenate(arrays)
    owners = np.concatenate([np.full(len(v), i, dtype=np.int64) for i, v in enumerate(arrays)])
    pairs = cKDTree(positions[:, :2]).query_pairs(1e-6, output_type="ndarray")
    conflicts = []

    def identity(index):
        return {k: sources[index].get(k) for k in ("kind", "source_handle", "layer", "source_kind", "fragment_id", "segment_offset")}

    def constraint_candidates(source_id, point):
        values = arrays[source_id]
        d = values[1:, :2]-values[:-1, :2]
        lengths2 = np.einsum("ij,ij->i", d, d)
        t = np.divide(np.einsum("ij,ij->i", point-values[:-1, :2], d), lengths2,
                      out=np.zeros(len(d)), where=lengths2 > 0)
        projections = values[:-1, :2]+np.clip(t, 0., 1.)[:, None]*d
        indices = np.flatnonzero((np.linalg.norm(projections-point, axis=1) <= 1e-6) & (lengths2 > 0))
        offset = int(sources[source_id].get("segment_offset", 0))
        return [{"source_handle": sources[source_id]["source_handle"], "segment_index": int(i)+offset,
                 "original_xyz": values[i:i+2].tolist()} for i in indices]

    if len(pairs):
        wrong = pairs[np.abs(positions[pairs[:, 0], 2] - positions[pairs[:, 1], 2]) > 1e-6]
        for first, last in wrong[:100]:
            source_a, source_b = int(owners[first]), int(owners[last])
            conflict = {"kind": "duplicate_xy_height", "xy": positions[first, :2].tolist(),
                        "elevations": [float(positions[first, 2]), float(positions[last, 2])],
                        "sources": [identity(source_a), identity(source_b)]}
            if sources[source_a]["kind"] == sources[source_b]["kind"] == "polyline":
                conflict["released_constraint_candidates"] = constraint_candidates(source_a, positions[first, :2]) + constraint_candidates(source_b, positions[first, :2])
            conflicts.append(conflict)
    curve_ids = [i for i, source in enumerate(sources) if source["kind"] == "polyline"]
    if curve_ids:
        # Local doubles avoid unnecessary cancellation at survey-coordinate scale.
        origin = positions[0, :2]
        curves = [shapely.LineString(arrays[i][:, :2] - origin) for i in curve_ids]
        tree = STRtree(curves)
        length_cache = {}

        def curve_lengths(curve_index, *, local=False):
            key = (curve_index, local)
            if key not in length_cache:
                xy = arrays[curve_ids[curve_index]][:, :2]
                if local:
                    xy = xy - origin
                length_cache[key] = np.r_[0., np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))]
            return length_cache[key]

        scatter_ids = [i for i, source in enumerate(sources) if source["kind"] == "point"]
        if scatter_ids:
            scattered = np.asarray([arrays[i][0, :2]-origin for i in scatter_ids])
            hits = tree.query(shapely.points(scattered), predicate="dwithin", distance=1e-6)
            for point_index, curve_index in hits.T:
                source_a, source_b = scatter_ids[int(point_index)], curve_ids[int(curve_index)]
                values = arrays[source_b]
                lengths = curve_lengths(int(curve_index))
                distance = curves[int(curve_index)].project(shapely.Point(scattered[int(point_index)]))
                line_z = float(np.interp(distance, lengths, values[:, 2]))
                if abs(float(arrays[source_a][0, 2])-line_z) > 1e-6:
                    conflicts.append({"kind": "point_on_contour_height", "xy": arrays[source_a][0, :2].tolist(),
                                      "elevations": [float(arrays[source_a][0, 2]), line_z],
                                      "sources": [identity(source_a), identity(source_b)]})
                if len(conflicts) >= 100:
                    break
        for index, curve in enumerate(curves):
            if cancelled and index % 32 == 0 and cancelled():
                raise InterruptedError("已取消地形冲突检查")
            # Exclude self and already checked pairs before exact predicates.
            # Dense survey lines otherwise repeat their most expensive checks.
            candidates = tree.query(curve)
            candidates = candidates[candidates > index]
            if len(candidates):
                shapely.prepare(curve)
                candidates = candidates[shapely.intersects(curve, tree.geometries[candidates])]
            for other in candidates:
                other = int(other)
                if other <= index:
                    continue
                intersection = curve.intersection(curves[other])
                coordinates = shapely.get_coordinates(intersection)
                if not len(coordinates):
                    continue
                source_a, source_b = curve_ids[index], curve_ids[other]
                z_values = []
                for source_id in (source_a, source_b):
                    values = arrays[source_id]
                    lengths = curve_lengths(index if source_id == source_a else other, local=True)
                    # Z is interpolated only along a source's original segment.
                    native_curve = curves[index] if source_id == source_a else curves[other]
                    distances = shapely.line_locate_point(native_curve, shapely.points(coordinates))
                    z_values.append(np.interp(distances, lengths, values[:, 2]))
                wrong = np.flatnonzero(np.abs(z_values[0] - z_values[1]) > 1e-6)
                for at in wrong[:max(0, 100-len(conflicts))]:
                    conflicts.append({"kind": "crossing_contour_height", "xy": (coordinates[at] + origin).tolist(),
                                      "elevations": [float(z_values[0][at]), float(z_values[1][at])],
                                      "sources": [identity(source_a), identity(source_b)],
                                      "released_constraint_candidates": constraint_candidates(source_a, coordinates[at]+origin)
                                                                        + constraint_candidates(source_b, coordinates[at]+origin)})
                if len(conflicts) >= 100:
                    break
            if len(conflicts) >= 100:
                break
    report["conflicts"] = conflicts
    if conflicts and reject:
        report["requires_confirmation"] = True
        raise TerrainImportError("地形存在同位置或相交等高线高程冲突，请核对原测量资料", report)
    return conflicts


def _source_key(source):
    return str(source["source_handle"]), str(source.get("fragment_id") or "")


def _retained_contour_fragments(source, blocked):
    values = np.asarray(source["points"], dtype=np.float64)
    derived, start, part = [], None, 0
    for edge, is_blocked in enumerate(np.r_[blocked, True]):
        if not is_blocked and start is None:
            start = edge
        if is_blocked and start is not None:
            part += 1
            derived.append({**source, "fragment_id": str(source.get("fragment_id", ""))+f"/part:{part}",
                            "segment_offset": int(source.get("segment_offset", 0))+start,
                            "points": values[start:edge+1].tolist()})
            start = None
    return derived


def _release_confirmed_constraints(sources, requests, report, *, report_key="explicit_constraint_releases"):
    """Release only explicitly identified original segment indices."""
    selected = {}
    for request in requests or []:
        if isinstance(request, dict):
            handle, index = request.get("source_handle"), request.get("segment_index")
        else:
            if len(request) != 2:
                raise ValueError("让位约束必须指定 [来源handle, 原片段索引]")
            handle, index = request
        if not isinstance(index, (int, np.integer)) or index < 0:
            raise ValueError("让位约束索引必须为非负整数")
        selected.setdefault(str(handle), set()).add(int(index))
    derived, releases, found = [], [], set()
    for source in sources:
        handle = str(source["source_handle"])
        if source["kind"] != "polyline" or handle not in selected:
            derived.append(source)
            continue
        values = np.asarray(source["points"], dtype=np.float64)
        blocked = np.zeros(len(values)-1, dtype=bool)
        offset = int(source.get("segment_offset", 0))
        for index in sorted(selected[handle]):
            local_index = index-offset
            if not 0 <= local_index < len(blocked):
                continue
            found.add((handle, index))
            blocked[local_index] = True
            releases.append({"source_handle": handle, "layer": source["layer"], "segment_index": index,
                             "original_xyz": values[local_index:local_index+2].tolist(),
                             "reason": "user_confirmed_local_constraint_release" if report_key == "explicit_constraint_releases" else "confirmed_rule_crossing_conflict_local_release",
                             "original_source_modified": False})
        if np.any(blocked):
            derived.extend(_retained_contour_fragments(source, blocked))
        else:
            derived.append(source)
    missing = {(handle, index) for handle, indices in selected.items() for index in indices}-found
    if missing:
        raise ValueError("指定让位的等高线来源/原片段索引不存在："+str(sorted(missing)))
    report[report_key] = report.get(report_key, [])+releases
    return derived


def _crossing_measurement_evidence(sources, conflict):
    from scipy.spatial import cKDTree
    measured = [source for source in sources if source["kind"] == "point"]
    if not measured:
        return {"nearby_measurements": [], "support": "no_independent_measurements_near_crossing",
                "source_heights_unchanged": True}
    xyz = np.asarray([source["points"][0] for source in measured], dtype=np.float64)
    distances, indices = cKDTree(xyz[:, :2]).query(conflict["xy"], k=min(24, len(xyz)))
    distances, indices = np.atleast_1d(distances), np.atleast_1d(indices)
    nearest = [{"source_handle": measured[int(i)]["source_handle"], "layer": measured[int(i)]["layer"],
                "xyz": xyz[int(i)].tolist(), "distance_m": float(distance)}
               for distance, i in zip(distances[:8], indices[:8])]
    close = distances <= 30.
    evidence = {"nearby_measurements": nearest, "measurement_count_within_30m": int(close.sum()),
                "support": "original_nearby_measurements_only", "source_heights_unchanged": True}
    if close.sum() >= 3:
        values = xyz[indices[close]]
        relative = values[:, :2]-np.asarray(conflict["xy"])
        a = np.c_[relative, np.ones(len(values))]
        if np.linalg.matrix_rank(a) == 3:
            w = 1/np.maximum(5., distances[close])
            plane = np.linalg.lstsq(a*w[:, None], values[:, 2]*w, rcond=None)[0]
            evidence.update(local_plane_height_diagnostic=float(plane[2]),
                            local_plane_rms_residual_m=float(np.sqrt(np.mean((values[:, 2]-a@plane)**2))),
                            diagnostic_used_to_create_elevation=False)
    return evidence


def _resolve_crossing_constraints(sources, conflicts, report, cancelled, policy):
    if policy not in ("release_conflicting_segments", "stop"):
        raise ValueError("相交等高线规则请选择 release_conflicting_segments 或 stop")
    report["contour_crossing_policy"] = policy
    original_conflicts = list(conflicts)
    processed = []
    for _ in range(8):
        crossings = [value for value in conflicts if all(s.get("kind") == "polyline" for s in value["sources"])]
        if not crossings or policy == "stop":
            break
        requests = []
        for crossing in crossings:
            candidates = crossing.get("released_constraint_candidates", [])
            if not candidates:
                continue
            requests.extend([[v["source_handle"], v["segment_index"]] for v in candidates])
            processed.append({**crossing, "local_support_diagnostic": _crossing_measurement_evidence(sources, crossing),
                              "action": "release_only_original_conflicting_segments", "original_source_modified": False})
        if not requests:
            break
        sources = _release_confirmed_constraints(sources, requests, report, report_key="automatic_constraint_releases")
        conflicts = _check_source_conflicts(sources, report, cancelled, reject=False)
        original_conflicts.extend(v for v in conflicts if v not in original_conflicts)
    report["contour_crossing_resolutions"] = processed
    report["conflicts"] = original_conflicts
    return sources, conflicts


def _yield_contour_constraints(sources, conflicts, report):
    """Measurement priority removes only original segments touching a conflict.

    The source contour and its Z are retained for display/audit. Derived
    contour fragments do not reconnect across the yielded interval.
    """
    from collections import defaultdict
    by_handle = {_source_key(source): index for index, source in enumerate(sources)}
    affected = defaultdict(list)
    seen = set()
    for conflict in conflicts:
        roles = {value.get("kind"): value for value in conflict["sources"]}
        curve, point = roles["polyline"], roles["point"]
        key = (_source_key(point), _source_key(curve), tuple(conflict["xy"]))
        if key in seen:
            continue
        seen.add(key)
        affected[by_handle[_source_key(curve)]].append((conflict, point, curve))
    derived, resolutions = [], []
    for index, source in enumerate(sources):
        if index not in affected:
            derived.append(source)
            continue
        values = np.asarray(source["points"], dtype=np.float64)
        first, last = values[:-1, :2], values[1:, :2]
        d = last-first
        length2 = np.einsum("ij,ij->i", d, d)
        blocked = np.zeros(len(d), dtype=bool)
        for conflict, point, curve in affected[index]:
            xy = np.asarray(conflict["xy"])
            t = np.divide(np.einsum("ij,ij->i", xy-first, d), length2,
                          out=np.zeros(len(d)), where=length2 > 0)
            projections = first + np.clip(t, 0., 1.)[:, None]*d
            touching = (np.linalg.norm(projections-xy, axis=1) <= 1e-6)
            touching &= length2 > 0
            blocked |= touching
            point_source = sources[by_handle[_source_key(point)]]
            contour_at = next(i for i, value in enumerate(conflict["sources"]) if value["kind"] == "polyline")
            resolutions.append({"rule": "points_priority", "xy": conflict["xy"],
                                "point_source": point, "contour_source": curve,
                                "original_point_elevation": point_source["points"][0][2],
                                "adopted_elevation": point_source["points"][0][2],
                                "original_contour_elevations": conflict["elevations"],
                                "original_contour_elevation": conflict["elevations"][contour_at],
                                "yielded_segment_indices": (np.flatnonzero(touching)+int(source.get("segment_offset", 0))).tolist(),
                                "yielded_segments": [values[i:i+2].tolist() for i in np.flatnonzero(touching)],
                                "original_source_modified": False})
        derived.extend(_retained_contour_fragments(source, blocked))
    report["conflict_resolutions"] = resolutions
    report["conflict_rule"] = "original_measurement_height; touching_original_contour_segments_yield; never_reconnect_gap"
    report["requires_confirmation"] = False
    return derived


def _resolve_duplicate_measurements(sources, report, policy):
    """Use the confirmed higher measurement; retain every original for display."""
    from scipy.spatial import cKDTree
    if policy not in ("max", "stop"):
        raise ValueError("重复测点高程规则请选择 max 或 stop")
    report["duplicate_point_policy"] = policy
    points = [(i, source) for i, source in enumerate(sources) if source["kind"] == "point"]
    report["duplicate_point_resolutions"] = []
    if policy == "stop" or len(points) < 2:
        return sources
    positions = np.asarray([source["points"][0] for _, source in points], dtype=np.float64)
    pairs = cKDTree(positions[:, :2]).query_pairs(1e-6, output_type="ndarray")
    parents = np.arange(len(points))

    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = int(parents[i])
        return i

    for a, b in pairs:
        parents[root(int(b))] = root(int(a))
    groups = {}
    for i in np.unique(pairs):
        groups.setdefault(root(int(i)), []).append(int(i))
    excluded = set()
    for indices in groups.values():
        chosen = max(indices, key=lambda i: positions[i, 2])
        adopted = points[chosen][1]
        discarded = [points[i][1] for i in indices if i != chosen]
        excluded.update(points[i][0] for i in indices if i != chosen)
        report["duplicate_point_resolutions"].append({
            "rule": "max", "xy": adopted["points"][0][:2],
            "adopted_elevation": adopted["points"][0][2],
            "adopted_source": {k: adopted.get(k) for k in ("source_handle", "layer", "source_kind")},
            "discarded_from_tin": [{"source_handle": v["source_handle"], "layer": v["layer"],
                                     "original_xyz": v["points"][0]} for v in discarded],
            "original_source_modified": False})
    report["duplicate_point_excluded_count"] = len(excluded)
    return [source for i, source in enumerate(sources) if i not in excluded]


def _face_edge_keys(faces):
    return {(min(a, b), max(a, b)) for i, j, k in faces for a, b in ((i, j), (j, k), (k, i))}


def _remove_degenerate_survey_faces(tin, report):
    """Drop numerical slivers generated by meshing, without filling or remeshing."""
    twice_area = np.abs(_projected_twice_area(tin.points, tin.triangles))
    degenerate = twice_area <= _MIN_PROJECTED_TWICE_AREA_M2
    if not degenerate.any():
        return
    retained = tin.triangles[~degenerate]
    if not len(retained):
        raise ValueError("测量资料建网后没有有效的平面投影三角面")

    used = np.zeros(len(tin.points), dtype=bool)
    used[retained] = True
    remap = np.cumsum(used, dtype=np.int64) - 1
    if tin.constraint_edges:
        removed = tin.triangles[degenerate]
        touched = np.zeros(len(tin.points), dtype=bool)
        touched[removed] = True
        neighbors = retained[np.count_nonzero(touched[retained], axis=1) >= 2]
        unsupported_edges = _face_edge_keys(removed) - _face_edge_keys(neighbors)
        tin.constraint_edges = [
            ConstraintEdge(int(remap[edge.i]), int(remap[edge.j]))
            for edge in tin.constraint_edges
            if used[edge.i] and used[edge.j] and (min(edge.i, edge.j), max(edge.i, edge.j)) not in unsupported_edges
        ]
    tin.points, tin.triangles = tin.points[used], remap[retained]
    tin.spatial_index = None
    diagnostic = report.setdefault("degenerate_projected_faces_filtered", {
        "threshold_twice_projected_area_m2": _MIN_PROJECTED_TWICE_AREA_M2,
        "face_count": 0,
        "removed_projected_area_m2": 0.0,
    })
    diagnostic["face_count"] += int(np.count_nonzero(degenerate))
    diagnostic["removed_projected_area_m2"] += float(twice_area[degenerate].sum() * 0.5)


def _build_survey_tin(sources, report, path, terrain_mode, options, cancelled, progress=None):
    from ..core.tin_builder import TINBuilder
    from .terrain_quality import clean_terrain_sources
    from .dxf_terrain_reader import DXFTerrainReader

    report = dict(report)
    raw_points = [source for source in sources if source["kind"] == "point"]
    raw_curves = [source for source in sources if source["kind"] == "polyline"]
    report["terrain_options"] = _portable_options(options)
    # The portable cache can verify all original XYZ and identities before a
    # later mode rebuild; used mesh vertices are never substituted as survey.
    report["source_snapshot_sha256"] = _snapshot_digest(raw_points+raw_curves)
    if report.get("source_insunits", 0) not in (0, 6):
        raise TerrainImportError("测量图单位不是米，请核对图形单位", report)
    if report.get("invalid_entities") or report.get("missing_selected_layers"):
        raise TerrainImportError("测量资料包含无效对象或指定图层不存在，请核对导入报告", report)
    if not sources or report.get("ambiguous_layers"):
        scope = (report.get("corridor_preparation") or {}).get("counts", {})
        if not sources and (scope.get("original_point_entities") or scope.get("original_polyline_entities")):
            report["scope_issue"] = "no_survey_sources_in_route_corridor"
            raise TerrainImportError("原图有测量对象，但当前工程走廊内没有可用对象，请核对平面坐标和测图范围", report)
        report["requires_confirmation"] = True
        raise TerrainImportError("未识别到有效测量资料，请选择测点及等高线图层", report)
    excluded = set(map(str, options.get("excluded_sources", [])))
    report["user_excluded_entities"] = [{k: source.get(k) for k in ("kind", "layer", "source_handle")}
                                         for source in sources if str(source.get("source_handle")) in excluded]
    sources = [source for source in sources if str(source.get("source_handle")) not in excluded]
    original_curves = [source for source in sources if source["kind"] == "polyline"]
    report["original_contour_count"] = len(original_curves)
    if terrain_mode == "points":
        sources = [source for source in sources if source["kind"] == "point"]
        report["contours_not_used_in_points_mode"] = len(original_curves)
    if not sources:
        raise TerrainImportError("所选模式或来源排除后没有有效测量资料", report)
    _import_progress(progress, cancelled, "terrain_conflicts", "正在检查重复测点及等高线高程冲突。")
    sources = _resolve_duplicate_measurements(sources, report, options.get("duplicate_point_policy", "max"))
    if terrain_mode == "combined":
        sources = _release_confirmed_constraints(sources, options.get("released_constraint_segments", []), report)
    if cancelled and cancelled():
        raise InterruptedError("已取消地形处理")
    report["input_entity_count"] = len(sources)
    # Conflict checking precedes quality filtering: an outlier heuristic must
    # not silently choose one of two measurements at exactly the same XY.
    policy = options.get("conflict_policy", "points_priority")
    if policy not in ("points_priority", "stop"):
        raise ValueError("高程冲突规则请选择 points_priority 或 stop")
    report["conflict_policy"] = policy
    conflicts = _check_source_conflicts(sources, report, cancelled, reject=False)
    sources, conflicts = _resolve_crossing_constraints(sources, conflicts, report, cancelled,
                                                        options.get("contour_crossing_policy", "release_conflicting_segments"))
    fatal = [value for value in conflicts if {s.get("kind") for s in value["sources"]} != {"point", "polyline"}]
    if fatal or conflicts and policy == "stop":
        report["requires_confirmation"] = True
        report["unresolved_conflicts"] = fatal if fatal else conflicts
        raise TerrainImportError("地形存在未解决的测点或等高线高程冲突，请核对原测量资料", report)

    class Token:
        def raise_if_cancelled(self):
            if cancelled and cancelled():
                raise InterruptedError("已取消地形处理")

    _import_progress(progress, cancelled, "terrain_quality", "正在筛查异常高程，保留有效原始测点与等高线。")
    if options.get("filter_elevation_outliers", True):
        cleaned = clean_terrain_sources(sources, cancel_token=Token(), policy=options.get("quality_policy"))
        sources, quality = cleaned["sources"], cleaned["report"]
    else:
        quality = {"enabled": False, "removed_point_count": 0, "removed_contour_count": 0,
                   "removed_entities": [], "output_entity_count": len(sources)}
    report["quality_report"] = quality
    source_points = [v for v in sources if v["kind"] == "point"]
    source_curves = [v for v in sources if v["kind"] == "polyline"]
    display_curves = raw_curves
    clean_sources = source_points + source_curves
    if terrain_mode == "points" and options.get("export_clean_terrain", True) and path.suffix.lower() in (".dxf", ".dwg"):
        # The point-only mesh still delivers a complete clean survey drawing.
        # Curves are checked against independent measured points, not omitted.
        if options.get("filter_elevation_outliers", True):
            all_cleaned = clean_terrain_sources(source_points + original_curves, cancel_token=Token(),
                                                policy=options.get("quality_policy"))
            clean_sources = source_points + [v for v in all_cleaned["sources"] if v["kind"] == "polyline"]
            report["clean_drawing_quality_report"] = all_cleaned["report"]
        else:
            clean_sources = source_points + original_curves
    if conflicts:
        retained_handles = {_source_key(v) for v in sources}
        retained_conflicts = [v for v in conflicts if all(_source_key(s) in retained_handles for s in v["sources"])]
        sources = _yield_contour_constraints(sources, retained_conflicts, report)
        source_points = [v for v in sources if v["kind"] == "point"]
        source_curves = [v for v in sources if v["kind"] == "polyline"]
    _import_progress(progress, cancelled, "terrain_build", "正在建立计算三角网并识别有效测量范围。")
    builder = TINBuilder()
    if terrain_mode == "combined":
        interval = float(options.get("contour_interval", 0.0))
        if not np.isfinite(interval) or interval < 0:
            raise ValueError("等高线加密间距必须有限且不小于零")
        for index, source in enumerate(source_curves):
            if cancelled and index % 32 == 0 and cancelled():
                raise InterruptedError("已取消地形建网")
            values = DXFTerrainReader._discretize_contour(source["points"], interval)
            builder.add_contour_points(values, [ConstraintEdge(i, i+1) for i in range(len(values)-1)])
    builder.add_elevation_points([TerrainPoint(*source["points"][0], source=source["source_handle"])
                                 for source in source_points])
    if cancelled and cancelled():
        raise InterruptedError("已取消地形建网")
    try:
        tin = builder.build(source_files=[str(path)], filter_outliers=False,
                            auto_boundary=options.get("automatic_boundary", True),
                            boundary_gap_factor=float(options.get("boundary_gap_factor", 4.0)),
                            allow_constraint_intersections=True)
        if cancelled and cancelled():
            raise InterruptedError("已取消地形建网")
        _remove_degenerate_survey_faces(tin, report)
    except ValueError as exc:
        report["build_error"] = str(exc)
        raise TerrainImportError(str(exc), report) from exc
    if options.get("boundary") is not None or options.get("holes"):
        _clip_survey_mesh(tin, options.get("boundary"), options.get("holes", []), cancelled)
        _remove_degenerate_survey_faces(tin, report)
    tin.measured_points = np.asarray([v["points"][0] for v in raw_points], dtype=np.float64).reshape(-1, 3)
    tin.used_measured_points = np.asarray([v["points"][0] for v in source_points], dtype=np.float64).reshape(-1, 3)
    tin.source_contours = [v["points"] for v in display_curves]
    tin.source_identities = [_survey_source_identity(source) for source in sources]
    tin.point_source_identities = [_survey_source_identity(source) for source in raw_points]
    tin.contour_source_identities = [_survey_source_identity(source) for source in raw_curves]
    tin.quality_report = quality
    tin.import_report = {**report, "topology": "source_constrained_tin" if tin.constraint_edges else "source_point_tin",
                         "terrain_mode": terrain_mode, "accepted_point_count": len(source_points),
                         "original_point_count": len(raw_points), "original_contour_count": len(raw_curves),
                         "accepted_contour_count": len(source_curves),
                         "used_contour_count": len(source_curves) if terrain_mode == "combined" else 0,
                         "constraint_edge_count": len(tin.constraint_edges),
                         "boundary_report": getattr(tin, "boundary_report", {}),
                         "coordinates": "original_WCS_float64", "uses_rhino": False,
                         "source_unchanged": True}
    if options.get("export_clean_terrain", True) and path.suffix.lower() in (".dxf", ".dwg"):
        from .terrain_clean_export import export_clean_terrain_sources
        _import_progress(progress, cancelled, "terrain_export", "正在保存净化地形图、测点表与来源记录。")
        tin.import_report["clean_terrain"] = export_clean_terrain_sources(
            clean_sources, path, options.get("clean_output_dir"),
            import_report=tin.import_report, cancelled=cancelled)
    return tin


def _finish_survey(tin, path, source_hash, terrain_mode, cancelled, progress=None):
    _import_progress(progress, cancelled, "terrain_validate", "正在校验计算地形及原图完整性。")
    tin.points, tin.triangles = validate_mesh(tin.points, tin.triangles)
    if file_sha256(path, cancelled) != source_hash:
        raise ValueError("读取期间原始测量文件已改变，请重新读取")
    tin.import_report.update(path=str(path), source_sha256=source_hash, units="m", terrain_mode=terrain_mode,
                             vertex_count=len(tin.points), face_count=len(tin.triangles),
                             terrain_sha256=_mesh_digest(tin.points, tin.triangles),
                             bounds=[tin.points.min(axis=0).tolist(), tin.points.max(axis=0).tolist()])
    return tin


def _clip_survey_mesh(tin, boundary, holes, cancelled):
    """Clip only intersected original faces; new Z follows their original plane."""
    import shapely
    import triangle
    from shapely.geometry import Polygon
    from shapely import affinity
    if boundary is None:
        from shapely.ops import unary_union
        domain = unary_union(shapely.polygons(tin.points[tin.triangles, :2]))
    elif isinstance(boundary, dict):
        domain = shapely.geometry.shape(boundary)
    else:
        domain = Polygon(boundary)
    for hole in holes:
        domain = domain.difference(Polygon(hole))
    if domain.is_empty or not domain.is_valid:
        raise ValueError("测量边界或缺测孔洞无效")
    origin = tin.points[0, :2].copy()
    local_domain = affinity.translate(domain, xoff=-origin[0], yoff=-origin[1])
    footprints = shapely.polygons(tin.points[tin.triangles, :2] - origin)
    contained = shapely.covered_by(footprints, local_domain)
    intersects = shapely.intersects(footprints, local_domain)
    original_face_count = len(tin.triangles)
    points, faces = tin.points.tolist(), tin.triangles[contained].tolist()

    def xy_key(xy):
        return tuple(np.rint((np.asarray(xy)-origin)/1e-8).astype(np.int64))

    lookup = {xy_key(p[:2]): i for i, p in enumerate(points)}
    for position, index in enumerate(np.flatnonzero(intersects & ~contained)):
        if cancelled and position % 128 == 0 and cancelled():
            raise InterruptedError("已取消地形范围裁剪")
        intersection = footprints[index].intersection(local_domain)
        polygons = [intersection] if intersection.geom_type == "Polygon" else list(getattr(intersection, "geoms", []))
        original = tin.points[tin.triangles[index]].copy()
        original[:, :2] -= origin
        plane = np.linalg.solve(np.column_stack([original[:, :2] - original[0, :2], np.ones(3)]), original[:, 2])
        for polygon in polygons:
            if polygon.geom_type != "Polygon" or polygon.area <= 1e-12:
                continue
            vertices, edges, seeds = [], [], []
            for ring in [polygon.exterior, *polygon.interiors]:
                coords = list(ring.coords)[:-1]
                start = len(vertices)
                vertices.extend(coords)
                edges.extend((start+i, start+(i+1) % len(coords)) for i in range(len(coords)))
            for ring in polygon.interiors:
                seeds.append(list(Polygon(ring).representative_point().coords)[0])
            data = {"vertices": np.asarray(vertices), "segments": np.asarray(edges)}
            if seeds:
                data["holes"] = np.asarray(seeds)
            built = triangle.triangulate(data, "p")
            indices = []
            for xy in built.get("vertices", []):
                z = float(np.dot([*(xy-original[0, :2]), 1.], plane))
                world = (float(xy[0]+origin[0]), float(xy[1]+origin[1]), z)
                key = xy_key(world[:2])
                if key not in lookup:
                    lookup[key] = len(points)
                    points.append(world)
                elif abs(points[lookup[key]][2]-z) > 1e-6:
                    raise ValueError("原地形相同平面位置存在冲突高程，不能生成范围裁剪顶点")
                indices.append(lookup[key])
            faces.extend([[indices[int(v)] for v in face] for face in built.get("triangles", [])])
    if not faces:
        raise ValueError("裁剪范围内没有有效测量地形")
    used, inverse = np.unique(np.asarray(faces, dtype=np.int64), return_inverse=True)
    remap = {int(old): i for i, old in enumerate(used)}
    tin.points, tin.triangles = np.asarray(points, dtype=np.float64)[used], inverse.reshape(-1, 3)
    actual_edges = {tuple(sorted((int(a), int(b)))) for face in tin.triangles
                    for a, b in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0]))}
    tin.constraint_edges = [ConstraintEdge(remap[e.i], remap[e.j]) for e in tin.constraint_edges
                            if e.i in remap and e.j in remap and tuple(sorted((remap[e.i], remap[e.j]))) in actual_edges]
    tin.boundary_report = {**getattr(tin, "boundary_report", {}), "explicit_boundary": True,
                          "hole_count": len(holes), "faces_before_explicit_clip": original_face_count,
                          "faces_after_explicit_clip": len(tin.triangles), "z_interpolation": "original_triangle_plane",
                          "requested_boundary": boundary, "requested_holes": holes}


def select_terrain(tin, bounds):
    """Select original triangles meeting a working bounding box; no remesh."""
    xmin, ymin, xmax, ymax = map(float, bounds)
    if not np.isfinite([xmin, ymin, xmax, ymax]).all() or xmax <= xmin or ymax <= ymin:
        raise ValueError("局部地形范围无效")
    selected = []
    for start in range(0, len(tin.triangles), 100_000):
        faces = tin.triangles[start:start+100_000]
        xy = tin.points[faces, :2]
        low, high = xy.min(axis=1), xy.max(axis=1)
        mask = ((high[:, 0] >= xmin) & (low[:, 0] <= xmax)
                & (high[:, 1] >= ymin) & (low[:, 1] <= ymax))
        if mask.any():
            selected.append(faces[mask])
    triangles = np.concatenate(selected) if selected else np.empty((0,3), dtype=np.int64)
    if not len(triangles):
        raise ValueError("工程范围与有效地形没有交集")
    used, inverse = np.unique(triangles, return_inverse=True)
    local = TINModel(points=tin.points[used].copy(), triangles=inverse.reshape(-1, 3),
                     source_files=list(tin.source_files), source_mtimes=list(tin.source_mtimes))
    local.import_report = {**getattr(tin, "import_report", {}), "selection_bounds": list(bounds),
                           "selected_faces": len(triangles), "preserved_original_faces": True}
    return local


def save_terrain(tin, path, *, cancelled=None):
    """Portable cache, with original doubles and triangle connectivity."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        curves = [np.asarray(v, dtype=np.float64).reshape(-1, 3) for v in getattr(tin, "source_contours", [])]
        curve_points = np.concatenate(curves) if curves else np.empty((0, 3), dtype=np.float64)
        offsets = np.r_[0, np.cumsum([len(v) for v in curves])].astype(np.int64)
        arrays = dict(points=tin.points, triangles=tin.triangles,
                            constraint_edges=np.asarray([[e.i, e.j] for e in tin.constraint_edges], dtype=np.int64).reshape(-1, 2),
                            measured_points=np.asarray(getattr(tin, "measured_points", np.empty((0, 3))), dtype=np.float64),
                            used_measured_points=np.asarray(getattr(tin, "used_measured_points", getattr(tin, "measured_points", np.empty((0, 3)))), dtype=np.float64),
                            source_contour_points=curve_points, source_contour_offsets=offsets,
                            source_identities=np.array(json.dumps({"points": getattr(tin, "point_source_identities", []),
                                                                  "contours": getattr(tin, "contour_source_identities", [])}, ensure_ascii=False)),
                            import_report=np.array(json.dumps(getattr(tin, "import_report", {}), ensure_ascii=False)))
        # Standard NPZ/NPY members, with faster lossless compression. Keep all
        # doubles, indices and metadata; existing np.load readers are unchanged.
        class CancellableWriter:
            def __init__(self, member):
                self.member = member

            def write(self, data):
                if cancelled and cancelled():
                    raise InterruptedError("已取消计算地形缓存保存")
                return self.member.write(data)

            def flush(self):
                return self.member.flush()

        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
            for name, values in arrays.items():
                if cancelled and cancelled():
                    raise InterruptedError("已取消计算地形缓存保存")
                with archive.open(name + ".npy", "w", force_zip64=True) as member:
                    np.lib.format.write_array(CancellableWriter(member), np.asanyarray(values), allow_pickle=False)
    return str(path.resolve())


def export_cached_clean_terrain(tin, output_dir=None, *, source_path=None, cancelled=None):
    """Save a clean survey drawing from an approved cache without rebuilding."""
    from .terrain_clean_export import export_clean_terrain_snapshot
    if source_path is not None:
        report = getattr(tin, "import_report", {})
        original = report.get("original_source") or {}
        expected = original.get("source_sha256")
        candidate = Path(source_path).resolve()
        if expected and file_sha256(candidate, cancelled) != expected:
            raise ValueError("指定原图与地形缓存来源不一致，请重新导入")
        if original:
            report["original_source"] = {**original, "path": str(candidate)}
    return export_clean_terrain_snapshot(tin, output_dir, cancelled=cancelled)
