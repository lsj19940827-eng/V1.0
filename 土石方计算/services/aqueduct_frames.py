"""Generate explicitly designed aqueduct columns and optional spread footings.

The layout supplies all structural dimensions and support locations.  Only the
elevations are derived: no span, member size, bearing layer or excavation slope
is inferred from the reference illustrations. Generated boxes use the existing
``discrete_components`` section quantity path.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import math

from ..core.tin_interpolator import TINInterpolator
from .contracts import ConstructionInputError, content_hash, finite_number
from .dedicated_structure_geometry import AQUEDUCT_TYPES
from .design_profiles import evaluate_profile, normalize_design_profile
from .network_alignment import NetworkAlignment
from .workbench_identity import terrain_choice


FRAME_CONTRACT = "aqueduct_frames_profile_tin_1.0"
WEATHERING_FRAME_CONTRACT = "aqueduct_frames_weathering_profile_tin_1.0"
FOUNDATION_FRAME_CONTRACT = "aqueduct_frames_weathering_foundations_tin_1.0"
_GENERATED = "generated_aqueduct_frame"
_FOUNDATION_GENERATED = "generated_aqueduct_foundation_member"


def _height_terrain_basis(tin):
    # Column heights depend on the actual mesh/constraints and units, not on
    # whether identical mesh bytes were just packaged into a portable cache.
    choice = terrain_choice(tin)
    return {key: choice.get(key) for key in ("schema", "terrain_mode", "actual_mesh_sha256",
        "actual_constraint_sha256", "vertex_count", "face_count", "constraint_count", "processing_options", "units")}


def _number(value, label, *, positive=False, nonnegative=False):
    value = finite_number(value, label)
    if positive and value <= 0 or nonnegative and value < 0:
        raise ConstructionInputError(label + ("须大于0" if positive else "不能为负"))
    return value


def _alignment(asset, alignment):
    value = alignment if alignment is not None else asset.get("alignment")
    if isinstance(value, dict) and value.get("elements"):
        value = NetworkAlignment.from_dict(value)
    if not isinstance(value, NetworkAlignment):
        raise ConstructionInputError("排架取高缺少当前路线的真实平面线元，请先导入路线")
    return value


def _canonical_weathering_foundation(raw):
    if not isinstance(raw, dict):
        raise ConstructionInputError("请填写按风化层确定基础底所需的地层和基础参数")
    bearing = raw.get("bearing_layer")
    if bearing not in {"strong", "weak"}:
        raise ConstructionInputError("基础持力层须选择强风化或弱风化")
    strong_top = raw.get("strong_top_depth_m")
    strong_top = None if strong_top in (None, "") else _number(strong_top, "强风化层顶面距地表深度", nonnegative=True)
    strong_bottom = _number(raw.get("strong_bottom_depth_m"), "强风化层底面（弱风化层顶面）距地表深度", nonnegative=True)
    weak_bottom = raw.get("weak_bottom_depth_m")
    weak_bottom = None if weak_bottom in (None, "") else _number(weak_bottom, "弱风化层底面距地表深度", nonnegative=True)
    if bearing == "strong" and strong_top is None:
        raise ConstructionInputError("选择强风化持力层时须填写强风化层顶面距地表深度")
    if strong_top is not None and strong_bottom <= strong_top:
        raise ConstructionInputError("强风化层底面深度须大于顶面深度")
    if weak_bottom is not None and weak_bottom <= strong_bottom:
        raise ConstructionInputError("弱风化层底面深度须大于强风化层底面（弱风化层顶面）深度")
    embedment = _number(raw.get("embedment_m"), "基础底进入所选持力层深度", nonnegative=True)
    thickness = _number(raw.get("foundation_thickness_m"), "扩大基础总厚度", positive=True)
    selected_top = strong_top if bearing == "strong" else strong_bottom
    selected_bottom = strong_bottom if bearing == "strong" else weak_bottom
    if selected_bottom is not None and embedment >= selected_bottom-selected_top:
        raise ConstructionInputError("基础底进入深度已达到或穿过所选持力层下限，请核对地层深度或改选持力层")
    return {"bearing_layer": bearing, "strong_top_depth_m": strong_top,
            "strong_bottom_depth_m": strong_bottom, "weak_bottom_depth_m": weak_bottom,
            "embedment_m": embedment, "foundation_thickness_m": thickness}


def _canonical_foundation(raw, foundation_mode, columns):
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConstructionInputError("扩大基础设置格式无效")
    enabled = raw.get("enabled", False)
    if enabled not in (True, False) or not isinstance(enabled, bool):
        raise ConstructionInputError("扩大基础启用状态须为是或否")
    if not enabled:
        return None
    if foundation_mode != "weathering":
        raise ConstructionInputError("自动扩大基础须采用按风化层确定基础底的取高方式")
    length = _number(raw.get("length_m"), "扩大基础沿线长", positive=True)
    width = _number(raw.get("width_m"), "扩大基础横向宽", positive=True)
    if any(length < column["length"] or width < column["width"] for column in columns):
        raise ConstructionInputError("扩大基础长宽不能小于对应柱截面尺寸")
    material = raw.get("material", "concrete")
    if material != "concrete":
        raise ConstructionInputError("自动扩大基础材料须为混凝土")
    grade = raw.get("grade", "")
    if not isinstance(grade, str):
        raise ConstructionInputError("扩大基础混凝土等级须为文字")
    pit_raw = raw.get("pit_construction")
    if not isinstance(pit_raw, dict):
        raise ConstructionInputError("请明确扩大基础基坑四侧工作面和开挖坡比")
    pit = {}
    for side, label in (("left", "左"), ("right", "右"), ("front", "前"), ("back", "后")):
        for prefix, suffix in (("working_space_", "工作面"), ("excavation_slope_", "开挖坡比")):
            key = prefix+side
            pit[key] = _number(pit_raw.get(key), "基础基坑"+label+suffix, nonnegative=True)
    for key, label in (("bedding_thickness", "基础垫层厚度"), ("bedding_extension", "基础垫层外伸")):
        pit[key] = _number(pit_raw.get(key, 0.), label, nonnegative=True)
    return {"enabled": True, "length_m": length, "width_m": width,
            "material": material, "grade": grade.strip(), "pit_construction": pit}


def _canonical_layout(asset, raw):
    if not isinstance(raw, dict):
        raise ConstructionInputError("请填写渡槽排架布置")
    previous = asset.get("section", {}).get("aqueduct_frame_layout") or {}
    identity = str(asset.get("source_identity") or asset.get("asset_id") or "")
    if not identity:
        raise ConstructionInputError("渡槽缺少稳定来源编号，无法追踪生成的排架")
    default_id = "aqueduct-frames-" + hashlib.sha256(identity.encode("utf8")).hexdigest()[:16]
    layout_id = raw.get("layout_id") or previous.get("layout_id") or default_id
    if not isinstance(layout_id, str) or not layout_id.strip():
        raise ConstructionInputError("排架布置编号无效")
    if previous.get("layout_id") and layout_id != previous["layout_id"]:
        raise ConstructionInputError("已有排架布置的追踪编号不能更改")
    mode = raw.get("mode", "interval")
    result = {"layout_id": layout_id, "mode": mode,
              "invert_to_column_top_m": _number(raw.get("invert_to_column_top_m"), "净渠底至柱顶竖距", nonnegative=True)}
    foundation_mode = raw.get("foundation_mode", "offset")
    if foundation_mode == "weathering":
        result.update(foundation_mode="weathering",
                      weathering_foundation=_canonical_weathering_foundation(raw.get("weathering_foundation")))
    elif foundation_mode == "offset":
        # Keep the old canonical layout and contract byte-for-byte compatible.
        result["foundation_top_offset_m"] = _number(raw.get("foundation_top_offset_m"), "基础顶相对地面高差")
    else:
        raise ConstructionInputError("基础顶取高方式须选择地面高差或按风化层确定基础底")
    if mode == "interval":
        start = _number(raw.get("station_start"), "首排中心桩号")
        end = _number(raw.get("station_end"), "排架布置止桩号")
        spacing = _number(raw.get("spacing"), "排架间距", positive=True)
        if end < start:
            raise ConstructionInputError("排架布置止桩号不能小于首排中心桩号")
        count = math.floor((end-start)/spacing + 1e-10) + 1
        if count > 10000:
            raise ConstructionInputError("排架数量超过10000排，请核对间距和布置范围")
        stations = [start+i*spacing for i in range(count)]
        result.update(station_start=start, station_end=end, spacing=spacing)
    elif mode == "explicit":
        values = raw.get("stations")
        if not isinstance(values, list) or not values:
            raise ConstructionInputError("请填写至少一个排架中心桩号")
        if len(values) > 10000:
            raise ConstructionInputError("排架数量超过10000排，请分段设置")
        stations = [_number(value, f"第{i+1}排中心桩号") for i, value in enumerate(values)]
        if len(set(stations)) != len(stations):
            raise ConstructionInputError("排架中心桩号重复，请核对布置")
        stations.sort()
        result["stations"] = stations
    else:
        raise ConstructionInputError("排架布置方式须为等间距或指定桩号")
    columns = raw.get("columns")
    if not isinstance(columns, list) or not columns:
        raise ConstructionInputError("请填写每排柱的横偏距和截面尺寸")
    if len(columns)*len(stations) > 50000:
        raise ConstructionInputError("生成柱数量超过50000根，请分段设置")
    result["columns"] = []
    seen = set()
    for index, column in enumerate(columns):
        label = f"第{index+1}根柱"
        if not isinstance(column, dict):
            raise ConstructionInputError(label+"的截面参数格式无效")
        cid = column.get("column_id") or "column-"+str(index+1)
        if not isinstance(cid, str) or not cid.strip() or cid in seen:
            raise ConstructionInputError("每排柱的追踪编号无效或重复")
        seen.add(cid)
        material = column.get("material")
        if not isinstance(material, str) or not material.strip():
            raise ConstructionInputError(label+"须明确材料")
        grade = column.get("grade", "")
        if not isinstance(grade, str):
            raise ConstructionInputError(label+"的材料等级须为文字")
        result["columns"].append({"column_id": cid, "name": str(column.get("name") or label),
            "offset": _number(column.get("offset"), label+"横偏距"),
            "width": _number(column.get("width"), label+"横宽", positive=True),
            "length": _number(column.get("length"), label+"沿线厚度", positive=True),
            "material": material.strip(), "grade": grade.strip()})
    foundation = _canonical_foundation(raw.get("foundation"), foundation_mode, result["columns"])
    if foundation is not None:
        result["foundation"] = foundation
    return result, stations


def _member_values(member):
    """Fields which can change quantity or the interpretation of a generated box."""
    result = {key: deepcopy(member.get(key)) for key in (
        "component_id", "name", "material", "grade", "scope_category", "station_start", "station_end",
        "offset", "width", "bottom_elevation", "top_elevation", "excavate", _GENERATED,
        "aqueduct_frame_layout_id", "frame_station", "frame_column_id", "frame_height_basis")}
    # Do not add null keys to archived column hashes: old offset and point
    # weathering generations retain their exact existing validity contract.
    if member.get(_FOUNDATION_GENERATED):
        result.update({key: deepcopy(member.get(key)) for key in (
            _FOUNDATION_GENERATED, "column_component_id", "construction")})
    elif member.get("foundation_component_id"):
        result["foundation_component_id"] = member["foundation_component_id"]
    return result


def _is_generated(member):
    return member.get(_GENERATED) or member.get(_FOUNDATION_GENERATED)


def _weathering_column_base(config, ground):
    """Derive a column base at the footing top, without creating a footing."""
    weathering = config["weathering_foundation"]
    strong_top_depth = weathering["strong_top_depth_m"]
    strong_top = None if strong_top_depth is None else ground-strong_top_depth
    strong_bottom = ground-weathering["strong_bottom_depth_m"]
    weak_bottom_depth = weathering["weak_bottom_depth_m"]
    weak_bottom = None if weak_bottom_depth is None else ground-weak_bottom_depth
    bearing_top = strong_top if weathering["bearing_layer"] == "strong" else strong_bottom
    bearing_bottom = strong_bottom if weathering["bearing_layer"] == "strong" else weak_bottom
    foundation_bottom = bearing_top-weathering["embedment_m"]
    foundation_top = foundation_bottom+weathering["foundation_thickness_m"]
    if not math.isfinite(foundation_bottom) or not math.isfinite(foundation_top):
        raise ConstructionInputError("扩大基础顶底高程无效，请核对地层和基础参数")
    elevations = (strong_top, strong_bottom, weak_bottom, foundation_bottom, foundation_top)
    if any(value is not None and not math.isfinite(value) for value in elevations):
        raise ConstructionInputError("柱位风化层或基础顶底高程无效，请核对地层深度及基础参数")
    return foundation_top, {
        "foundation_mode": "weathering", "geology_method": "surface_vertical_offset",
        "weathering_foundation": deepcopy(weathering), "bearing_layer": weathering["bearing_layer"],
        "strong_top_elevation": strong_top, "strong_bottom_elevation": strong_bottom,
        "weak_top_elevation": strong_bottom, "weak_bottom_elevation": weak_bottom,
        "bearing_layer_top_elevation": bearing_top, "bearing_layer_bottom_elevation": bearing_bottom,
        "foundation_bottom_elevation": foundation_bottom, "foundation_top_elevation": foundation_top,
        "foundation_geometry_modeled": False,
        "height_basis_scope": "仅按柱位地面竖直下移推算地层与基础顶底；未生成扩大基础实体，未校核整个基础底面持力层条件，未计算基础土石方。",
        "foundation_bottom_formula": "基础底高程 = 柱位所选持力层顶面高程 - 基础底进入所选持力层深度",
        "foundation_top_formula": "基础顶高程 = 基础底高程 + 扩大基础总厚度",
        "formula": "H = 净渠底高程 - 净渠底至柱顶竖距 - 基础顶高程"}


class _FoundationTerrain:
    """Exact plane extrema over each rectangular footing in the existing TIN.

    Reuse the terrain cutter's frozen local coordinates and topology checks;
    do not retriangulate the survey, bridge holes, or sample only four corners.
    """
    def __init__(self, tin):
        from ..core.terrain_sections import TerrainSectionIndex
        self._index = TerrainSectionIndex(tin)

    def footprint(self, center_xy, angle, length, width):
        import numpy as np
        import shapely
        from shapely.geometry import Polygon
        from shapely.ops import unary_union

        index = self._index
        direction = np.array([math.cos(angle), math.sin(angle)])
        normal = np.array([direction[1], -direction[0]])
        center = np.asarray(center_xy, dtype=float)
        corners = [center+a*length/2*direction+b*width/2*normal
                   for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        footprint = Polygon(np.asarray(corners)-index._origin)
        indices = sorted(int(i) for i in index._tree.query(footprint, predicate="intersects"))
        index._check_topology(indices)
        pieces, samples = [], []
        count = 0
        for triangle in indices:
            intersection = index._tree.geometries[triangle].intersection(footprint)
            if intersection.is_empty:
                continue
            if intersection.area > 0:
                pieces.append(intersection)
                count += 1
            xy = shapely.get_coordinates(intersection)
            vertices = index._points[index._triangles[triangle]]
            gradient = np.linalg.solve(vertices[1:, :2]-vertices[0, :2], vertices[1:, 2]-vertices[0, 2])
            elevations = vertices[0, 2]+(xy-vertices[0, :2]) @ gradient
            world_xy = xy+index._origin
            samples.extend((float(point[0]), float(point[1]), float(z)) for point, z in zip(world_xy, elevations))
        covered = unary_union(pieces) if pieces else Polygon()
        coordinate_scale = max(1., float(np.max(np.abs(np.asarray(corners)-index._origin))))
        area_tolerance = np.finfo(float).eps*max(1., footprint.area, footprint.length*coordinate_scale)*64
        if not samples or footprint.difference(covered).area > area_tolerance:
            raise ConstructionInputError("扩大基础完整范围存在地形缺测，禁止仅按柱中心或基础四角外推")
        samples = sorted(set(samples))
        if any(not math.isfinite(value) for point in samples for value in point):
            raise ConstructionInputError("扩大基础范围的地形高程无效")
        low = min(samples, key=lambda point: (point[2], point[0], point[1]))
        high = max(samples, key=lambda point: (point[2], point[0], point[1]))
        return {"corners_xy": [list(map(float, point)) for point in corners],
                "terrain_min_elevation": low[2], "terrain_max_elevation": high[2],
                "terrain_min_point_xyz": list(low), "terrain_max_point_xyz": list(high),
                "coverage_area_m2": float(covered.area), "footprint_area_m2": float(footprint.area),
                "intersected_triangle_count": count, "sample_points_xyz": [list(point) for point in samples]}


def _foundation_column_base(config, ground, footprint):
    _, evidence = _weathering_column_base(config, ground)
    weathering, foundation = config["weathering_foundation"], config["foundation"]
    layer_top_depth = (weathering["strong_top_depth_m"] if weathering["bearing_layer"] == "strong"
                       else weathering["strong_bottom_depth_m"])
    layer_bottom_depth = (weathering["strong_bottom_depth_m"] if weathering["bearing_layer"] == "strong"
                          else weathering["weak_bottom_depth_m"])
    ground_min, ground_max = footprint["terrain_min_elevation"], footprint["terrain_max_elevation"]
    top_min, top_max = ground_min-layer_top_depth, ground_max-layer_top_depth
    bottom_min = None if layer_bottom_depth is None else ground_min-layer_bottom_depth
    bottom_max = None if layer_bottom_depth is None else ground_max-layer_bottom_depth
    foundation_bottom = top_min-weathering["embedment_m"]
    if bottom_max is not None and (foundation_bottom <= bottom_max or math.isclose(
            foundation_bottom, bottom_max, rel_tol=1e-12, abs_tol=1e-10)):
        raise ConstructionInputError("扩大基础水平基底在范围内达到或穿过所选持力层下限，请核对地形起伏、层厚或进入深度")
    foundation_top = foundation_bottom+weathering["foundation_thickness_m"]
    if any(not math.isfinite(value) for value in (foundation_bottom, foundation_top,
            foundation["length_m"]*foundation["width_m"]*weathering["foundation_thickness_m"])):
        raise ConstructionInputError("扩大基础顶底高程或方量无效，请核对地层和基础参数")
    evidence.update(
        geology_method="surface_vertical_offset_footprint_extrema", foundation_geometry_modeled=True,
        foundation_length_m=foundation["length_m"], foundation_width_m=foundation["width_m"],
        foundation_thickness_m=weathering["foundation_thickness_m"],
        foundation_material=foundation["material"], foundation_grade=foundation["grade"],
        foundation_volume_m3=foundation["length_m"]*foundation["width_m"]*weathering["foundation_thickness_m"],
        foundation_pit_construction=deepcopy(foundation["pit_construction"]),
        foundation_footprint=deepcopy(footprint), bearing_layer_top_min_elevation=top_min,
        bearing_layer_top_max_elevation=top_max, bearing_layer_bottom_min_elevation=bottom_min,
        bearing_layer_bottom_max_elevation=bottom_max, foundation_bottom_elevation=foundation_bottom,
        foundation_top_elevation=foundation_top,
        height_basis_scope="扩大基础按完整矩形范围与现有TIN逐面求交；层界按原地面竖直偏移假定，水平基底按层顶最低高程与进入深度确定并校核层底最高高程；不代表地基承载力设计。",
        foundation_bottom_formula="基础底高程 = 基础范围内所选持力层顶面最低高程 - 基础底进入所选持力层深度")
    return foundation_top, evidence


def generate_aqueduct_frames(asset, tin, *, layout=None, alignment=None):
    """Return a new asset with deterministic column boxes and inspectable sources.

    ``alignment`` accepts a ``NetworkAlignment`` or the serialized route
    alignment, in real source chainage before workbench station normalization.
    Interval end is a placement limit; an extra short terminal span is never
    silently added.  Stations refer to column centres, and the full column
    length must lie inside the owning aqueduct range.
    """
    if asset.get("section_type") not in AQUEDUCT_TYPES:
        raise ConstructionInputError("按地形生成排架仅适用于U形或矩形渡槽")
    if tin is None or getattr(tin, "is_empty", True):
        raise ConstructionInputError("排架取高缺少有效地形，请先载入当前工程地形")
    if getattr(tin, "num_triangles", 0) == 0:
        raise ConstructionInputError("排架取高缺少有效地形三角网")
    result = deepcopy(asset)
    section = result.setdefault("section", {})
    raw = layout if layout is not None else section.get("aqueduct_frame_layout")
    config, stations = _canonical_layout(asset, raw)
    line = _alignment(asset, alignment)
    try:
        profile = normalize_design_profile(asset)
    except ValueError as error:
        raise ConstructionInputError("排架取高："+str(error)) from error
    if profile["reference"] != "inner_invert":
        raise ConstructionInputError("渡槽排架取高须采用水面线净渠底高程，当前纵断面基准不符")
    lower = _number(asset.get("station_start"), "渡槽起桩")
    upper = _number(asset.get("station_end"), "渡槽止桩")
    if upper <= lower:
        raise ConstructionInputError("渡槽起止桩号须递增")
    if config["mode"] == "interval" and not lower <= config["station_start"] <= config["station_end"] <= upper:
        raise ConstructionInputError("排架布置起止桩号须位于当前渡槽区段内")
    interp = TINInterpolator(tin)
    foundation_terrain = _FoundationTerrain(tin) if config.get("foundation") else None
    generated, heights, foundation_records = [], [], []
    old_id = (section.get("aqueduct_frame_layout") or {}).get("layout_id")
    retained = [deepcopy(member) for member in section.get("discrete_components", [])
                if not (_is_generated(member) and member.get("aqueduct_frame_layout_id") in {old_id, config["layout_id"]})]
    for row, station in enumerate(stations):
        try:
            invert, _ = evaluate_profile(profile, station)
            center = line.get_xy_at_station(station)
            angle = line.get_tangent_angle_at_station(station)
        except ValueError as error:
            raise ConstructionInputError(f"第{row+1}排 K{station:.3f}：{error}") from error
        # Existing discrete foundations and section geometry use the right normal.
        normal = (math.sin(angle), -math.cos(angle))
        for column in config["columns"]:
            label = f"第{row+1}排 K{station:.3f} · {column['name']}"
            start, end = station-column["length"]/2, station+column["length"]/2
            if start < lower-1e-8 or end > upper+1e-8:
                raise ConstructionInputError(label+"：完整柱截面超出渡槽区段，请调整中心桩号或沿线厚度")
            xy = [center[i]+column["offset"]*normal[i] for i in (0, 1)]
            ground = interp.query(*xy)
            if ground is None or not math.isfinite(ground):
                raise ConstructionInputError(label+f"：柱位地形缺测（X={xy[0]:.3f}, Y={xy[1]:.3f}），禁止外推")
            top = invert-config["invert_to_column_top_m"]
            if foundation_terrain is not None:
                foundation = config["foundation"]
                foundation_start, foundation_end = station-foundation["length_m"]/2, station+foundation["length_m"]/2
                if foundation_start < lower-1e-8 or foundation_end > upper+1e-8:
                    raise ConstructionInputError(label+"：完整扩大基础超出渡槽区段，请调整中心桩号或基础沿线长")
                try:
                    footprint = foundation_terrain.footprint(xy, angle, foundation["length_m"], foundation["width_m"])
                    bottom, base_evidence = _foundation_column_base(config, ground, footprint)
                except (ValueError, ConstructionInputError) as error:
                    raise ConstructionInputError(label+"："+str(error)) from error
            elif config.get("foundation_mode") == "weathering":
                bottom, base_evidence = _weathering_column_base(config, ground)
            else:
                bottom = ground+config["foundation_top_offset_m"]
                base_evidence = {"foundation_top_offset_m": config["foundation_top_offset_m"],
                    "formula": "H = 净渠底高程 - 净渠底至柱顶竖距 - 柱位地形高程 - 基础顶相对地面高差"}
            height = top-bottom
            if height <= 0:
                raise ConstructionInputError(label+f"：柱高为{height:.3f}m，柱顶须高于基础顶，请核对扣减和基础高差")
            key = f"{config['layout_id']}:{station:.12g}:{column['column_id']}"
            cid = "aqueduct_frame_"+hashlib.sha256(key.encode("utf8")).hexdigest()[:20]
            foundation_cid = "aqueduct_footing_"+hashlib.sha256(key.encode("utf8")).hexdigest()[:20] if foundation_terrain is not None else None
            if foundation_cid:
                base_evidence["foundation_component_id"] = foundation_cid
            evidence = {"station": station, "column_id": column["column_id"], "xy": xy,
                "inner_invert_elevation": invert, "terrain_elevation": ground,
                "invert_to_column_top_m": config["invert_to_column_top_m"],
                "top_elevation": top, "bottom_elevation": bottom, "height_m": height,
                **base_evidence}
            member = {"component_id": cid, "name": f"排架{row+1} · {column['name']}",
                "material": column["material"], "grade": column["grade"], "scope_category": "pier",
                "station_start": start, "station_end": end, "offset": column["offset"],
                "width": column["width"], "bottom_elevation": bottom, "top_elevation": top,
                "excavate": False, _GENERATED: True, "aqueduct_frame_layout_id": config["layout_id"],
                "frame_station": station, "frame_column_id": column["column_id"],
                "frame_height_basis": deepcopy(evidence)}
            if foundation_cid:
                member["foundation_component_id"] = foundation_cid
            generated.append(member)
            heights.append({"component_id": cid, **evidence})
            if foundation_cid:
                foundation_member = {
                    "component_id": foundation_cid, "name": f"排架{row+1} · {column['name']}扩大基础",
                    "material": foundation["material"], "grade": foundation["grade"], "scope_category": "foundation",
                    "station_start": foundation_start, "station_end": foundation_end, "offset": column["offset"],
                    "width": foundation["width_m"], "bottom_elevation": evidence["foundation_bottom_elevation"],
                    "top_elevation": evidence["foundation_top_elevation"], "excavate": True,
                    "construction": deepcopy(foundation["pit_construction"]), _FOUNDATION_GENERATED: True,
                    "aqueduct_frame_layout_id": config["layout_id"], "frame_station": station,
                    "frame_column_id": column["column_id"], "column_component_id": cid,
                    "frame_height_basis": deepcopy(evidence)}
                generated.append(foundation_member)
                foundation_records.append({"component_id": foundation_cid, "column_component_id": cid, **deepcopy(evidence)})
    active = []
    for member in sorted([*retained, *generated], key=lambda item: float(item.get("station_start", -math.inf))):
        try:
            station_start = float(member["station_start"])
            station_end = float(member["station_end"])
        except (KeyError, TypeError, ValueError):
            continue  # Existing input validation reports incomplete manual rows.
        active = [other for other in active if other["station_end"] > station_start+1e-8]
        for other in active:
            if not _is_generated(member) and not _is_generated(other):
                continue
            try:
                ds = min(member["station_end"], other["station_end"])-max(member["station_start"], other["station_start"])
                dx = min(member["offset"]+member["width"]/2, float(other.get("offset", 0))+other["width"]/2)-max(member["offset"]-member["width"]/2, float(other.get("offset", 0))-other["width"]/2)
                dz = min(member["top_elevation"], other["top_elevation"])-max(member["bottom_elevation"], other["bottom_elevation"])
            except (KeyError, TypeError, ValueError):
                continue  # Existing input validation reports incomplete manual rows.
            if min(ds, dx, dz) > 1e-8:
                generated_member = member if _is_generated(member) else other
                raise ConstructionInputError(f"排架 K{generated_member['frame_station']:.3f} · {member.get('name', member.get('component_id'))} 与 {other.get('name',other.get('component_id'))} 实体重叠，请核对布置")
        if math.isfinite(station_start) and math.isfinite(station_end):
            active.append(member)
    occupied_ids = {member.get("component_id") for member in retained}
    if any(member["component_id"] in occupied_ids for member in generated):
        raise ConstructionInputError("生成排架的构件编号与现有手工构件重复，请核对来源")
    frame_contract = (FOUNDATION_FRAME_CONTRACT if foundation_terrain is not None else
                      WEATHERING_FRAME_CONTRACT if config.get("foundation_mode") == "weathering" else FRAME_CONTRACT)
    basis = {"contract": frame_contract, "layout_sha256": content_hash(config),
        "asset_range": [lower, upper], "profile_sha256": content_hash(profile),
        "alignment_sha256": content_hash(line.to_dict()), "terrain": _height_terrain_basis(tin)}
    snapshot = {"contract": frame_contract, "source_basis": basis,
        "terrain_file_provenance": terrain_choice(tin),
        "profile_snapshot": dict(profile), "alignment_snapshot": line.to_dict(),
        "columns": heights, "generated_members_sha256": content_hash([_member_values(member) for member in generated])}
    if foundation_terrain is not None:
        snapshot["foundations"] = foundation_records
    section["aqueduct_frame_layout"] = {**config, "generated_snapshot": snapshot}
    section["discrete_components"] = [*retained, *generated]
    # Remove stale generated specs; normal registration will recreate current ones.
    removed_ids = {member["component_id"] for member in asset.get("section", {}).get("discrete_components", [])
                   if _is_generated(member) and member.get("aqueduct_frame_layout_id") in {old_id, config["layout_id"]}}
    if "component_specs" in section:
        section["component_specs"] = [spec for spec in section["component_specs"] if spec.get("component_id") not in removed_ids]
    return result


def validate_aqueduct_frame_generation(asset, tin, *, alignment=None):
    """Reject stale or edited generated columns before source stations are shifted."""
    section = asset.get("section", {})
    config = section.get("aqueduct_frame_layout")
    members = [member for member in section.get("discrete_components", []) if _is_generated(member)]
    if not config and not members:
        return
    if not config or not isinstance(config, dict) or not config.get("generated_snapshot"):
        raise ConstructionInputError("渡槽排架缺少生成依据，请按当前水面线与地形重新生成")
    regenerated = generate_aqueduct_frames(asset, tin, alignment=alignment)
    expected = regenerated["section"]["aqueduct_frame_layout"]["generated_snapshot"]
    recorded = config["generated_snapshot"]
    if recorded.get("source_basis") != expected["source_basis"]:
        raise ConstructionInputError("渡槽排架的水面线、地形、路线或布置已变化，请重新生成排架后计算")
    comparable = lambda value: {key: item for key, item in value.items() if key != "terrain_file_provenance"}
    if (content_hash([_member_values(member) for member in members]) != expected["generated_members_sha256"]
            or comparable(recorded) != comparable(expected)):
        raise ConstructionInputError("渡槽排架生成构件或取高记录已变化，请重新生成排架后计算")
