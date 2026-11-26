"""Versioned, project-scoped drawing facts adopted by real design objects.

Current hydraulic dimensions and profiles drive geometry; example dimensions
are reference information and never constrain or replace the current design.
Bindings are portable snapshots and are revalidated when imported design changes.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re

from .engineering_drawings import ARCHIVED_DRAWING_IDS, DrawingLibraryError, catalog_path, load_catalog

TEMPLATE_SCHEMA = "engineering_drawing_templates_1.0"
BINDING_SCHEMA = "engineering_drawing_binding_1.0"
_EPS = 1e-7
_PROJECTS = {
    "mapeng": ("马鹏支渠", "马鹏支"),
    "shihe": ("石河分干渠", "石河分干"),
    "left": ("左干渠", "左干"),
    "tangniwan": ("塘泥湾倒虹管", "塘泥湾倒虹吸", "塘泥湾"),
}
_HYDRAULIC = frozenset({"inner_width", "inner_height", "inner_radius", "inner_diameter",
    "inner_side_slope", "wall_height", "arch_angle_degrees", "outer_diameter",
    "u_arc_angle_degrees", "u_side_angle_degrees", "structural_inner_height", "pipes"})


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode("utf8")).hexdigest()


def _file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _drawing_resources(template):
    root = catalog_path().parent
    catalog = load_catalog(include_archived=True)
    drawing = next(row for row in catalog["drawings"] if row["drawing_id"] == template["drawing_id"])
    paths = [(root / "catalog.json", "drawing_catalog"), (root / "templates.json", "drawing_templates")]
    paths.extend((root / reference, "drawing_evidence") for reference in drawing.get("source_refs", []))
    original = Path(__file__).resolve().parents[2] / "横断面图+算量" / drawing["file_name"]
    if original.is_file():
        paths.append((original, "drawing_original"))
    result = []
    for path, role in paths:
        if not path.is_file():
            raise DrawingLibraryError(f"图纸编译证据资源缺失：{path.name}")
        digest = _file_digest(path)
        if role == "drawing_original" and digest != template["source_sha256"]:
            raise DrawingLibraryError("原始图纸字节已改变，须重新审阅后才可绑定：" + path.name)
        result.append({"path": str(path.resolve()), "sha256": digest, "role": role,
                       "drawing_id": template["drawing_id"], "source_sha256": template["source_sha256"]})
    return result


def _get(value, path):
    for part in path.split("."):
        match = re.fullmatch(r"([^\[]+)\[(\d+)\]", part)
        if match:
            rows = value.get(match[1]) if isinstance(value, dict) else None
            index = int(match[2])-1
            value = rows[index] if isinstance(rows, list) and 0 <= index < len(rows) else None
        else:
            value = value.get(part) if isinstance(value, dict) else None
    return value


def _set(value, path, item):
    keys = path.split(".")
    for key in keys[:-1]:
        match = re.fullmatch(r"([^\[]+)\[(\d+)\]", key)
        if match:
            rows = value.setdefault(match[1], [])
            index = int(match[2])-1
            if index < 0:
                raise ValueError("逐管来源序号必须从1开始")
            while len(rows) <= index:
                rows.append({})
            value = rows[index]
        else:
            value = value.setdefault(key, {})
    value[keys[-1]] = deepcopy(item)


def _same(a, b):
    if isinstance(a, (float, int)) and not isinstance(a, bool) and isinstance(b, (float, int)) and not isinstance(b, bool):
        return math.isfinite(float(a)) and math.isfinite(float(b)) and math.isclose(float(a), float(b), rel_tol=1e-7, abs_tol=1e-6)
    return a == b


def _replayable_override(field):
    """Retain construction edits while refreshing all current hydraulic inputs."""
    if not isinstance(field,str):
        return False
    keys=field.split(".")
    if len(keys)<2 or keys[0] not in {"section","construction"}:
        return False
    if keys[0]=="construction":
        return True
    if re.fullmatch(r"pipes\[[1-9]\d*\]",keys[1]):
        return len(keys)==3 and keys[2] in {"wall_thickness","lining_thickness","material","lining_material","material_grade"}
    return keys[1].split("[",1)[0] not in _HYDRAULIC


def _read_templates(path=None):
    """Read the versioned source registry, including snapshots needed by saved projects."""
    target = Path(path) if path else catalog_path().with_name("templates.json")
    try:
        data = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise DrawingLibraryError(f"无法读取可执行断面模板：{target.name}；{exc}") from exc
    if data.get("schema") != TEMPLATE_SCHEMA or not isinstance(data.get("templates"), list):
        raise DrawingLibraryError("可执行断面模板格式不受支持。")
    catalog = {row["drawing_id"]: row for row in load_catalog(target.with_name("catalog.json"), include_archived=True)["drawings"]}
    result, ids = [], set()
    for raw in data["templates"]:
        row = deepcopy(raw)
        identifier = row.get("template_id")
        source = catalog.get(row.get("drawing_id"))
        if not identifier or identifier in ids or not source or row.get("source_sha256") != source["sha256"]:
            raise DrawingLibraryError("断面模板的编号或原图摘要不一致，请重新核对资料版本。")
        ids.add(identifier)
        for field in row.get("fields", {}):
            keys = field.split(".")
            parameter = keys[1].split("[",1)[0] if len(keys)>1 else ""
            if keys[0] not in {"section", "construction"} or len(keys) < 2 or parameter in _HYDRAULIC:
                raise DrawingLibraryError(f"断面模板不得改写水力净尺寸或设计高程：{field}")
        row["template_sha256"] = _digest(raw)
        result.append(row)
    return result


def list_templates(path=None):
    """Return templates available for new bindings."""
    return [row for row in _read_templates(path) if row["drawing_id"] not in ARCHIVED_DRAWING_IDS]


def _project_context(inputs, supplied=None, network=None):
    context = deepcopy(supplied if supplied is not None else inputs.get("drawing_project_context") or {})
    if isinstance(context, str):
        context = {"project_name": context}
    names = [context.get("project_name", ""), inputs.get("project_name", ""), inputs.get("case_name", ""),
             _get(inputs, "design_source.water_profile_provenance.channel_name") or ""]
    if network:
        names.extend((network.get("name", ""), (network.get("source") or {}).get("project_name", "")))
    known = {key for key, aliases in _PROJECTS.items() if any(alias in str(name) for name in names for alias in aliases)}
    key = context.get("project_key")
    if key and key not in _PROJECTS:
        return context, "", "工程身份未在本批图纸中登记"
    if len(known) > 1 or key and known and known != {key}:
        return context, "", "明确工程名与已绑定工程身份冲突"
    key = key or next(iter(known), "")
    if not key:
        return context, "", "须明确对应的工程身份，不能用文件名或相同桩号匹配"
    context["project_key"] = key
    context.setdefault("project_identity", key + (":" + str(context["project_id"]) if context.get("project_id") else ""))
    return context, key, ""


def _finite(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _asset_id(asset):
    return asset.get("drawing_root_asset_id") or asset.get("parent_asset_id") or asset.get("asset_id")


def _constraints(template, asset, context, *, check_bedding=False, preview=False):
    problems = []
    if asset.get("section_type") not in template["section_types"] or asset.get("kind") not in template["asset_kinds"]:
        problems.append("结构类型不适用")
    # Drawing construction families use the actual design B/H/R and angles.
    # Their example dimensions are never geometric admission limits.
    if template.get("requires_station_mapping") and not (context.get("station_mapping_confirmed") or
            asset.get("drawing_station_mapping", {}).get("confirmed")):
        problems.append("尚未核对原图K桩号与当前真实线路桩号映射；不能仅凭相同数值套用施工分区")
    if template.get("cover_depth_max_m") is not None:
        maximum = template["cover_depth_max_m"]
        minimum = template.get("cover_depth_min_m", 0.)
        depth = next((v for v in (_get(asset, "construction.final_cover_depth"),
            _get(asset, "construction.cover_depth"), context.get("cover_depth_m")) if v is not None), None)
        if _finite(depth) is None and not context.get("scope_confirmed"):
            problems.append(f"尚未核对图纸覆土适用范围 {minimum:g}～{maximum:g}m")
        elif _finite(depth) is not None and not minimum <= float(depth) <= maximum:
            problems.append(f"覆土高度超过原图适用范围 {minimum:g}～{maximum:g}m")
    required_variant = template.get("required_variant")
    actual_variant = _get(asset, "construction.drawing_variant") or context.get("drawing_variant")
    if required_variant and actual_variant != required_variant:
        problems.append("须明确专项施工工况：" + required_variant)
    if check_bedding and template["template_id"] == "tangniwan_general":
        construction = asset.get("construction", {})
        seat = construction.get("pipe_seat") or construction.get("pipe_support") or {}
        enclosure = construction.get("encasement") or construction.get("pipe_encasement") or {}
        concrete_below_pipe = (
            seat.get("enabled", True) and seat.get("material_role", "concrete") == "concrete"
            and (_finite(seat.get("base_thickness")) or 0) > 0
            or enclosure.get("enabled", True) and (_finite(enclosure.get("bottom_thickness")) or 0) > 0
        )
        depth = construction.get("bedding_thickness")
        if preview and (depth is None or _is_assumption(asset, "construction.bedding_thickness")):
            depth = template["fields"]["construction.bedding_thickness"]
        if (concrete_below_pipe and (_finite(depth) or 0) > 0
                and construction.get("bedding_reference") != "pipe_seat_bottom"):
            problems.append("管底已有混凝土管座或包封。如需在其下另铺砂砾石，请将垫层基准设为管座底。")
    return problems


def _range_rows(template, asset):
    a, b = _finite(asset.get("station_start")), _finite(asset.get("station_end"))
    if a is None or b is None or b <= a:
        return []
    ranges = template.get("station_ranges")
    if ranges is None:
        return [{"station_start": a, "station_end": b, "scope_label": template.get("scope_label", "本对象全段"), "source_handles": []}]
    result = []
    for row in ranges:
        if row.get("status") != "verified_source":
            continue
        left, right = max(a, row["station_start"]), min(b, row["station_end"])
        if right > left + _EPS:
            result.append({**deepcopy(row), "station_start": left, "station_end": right})
    return result


def _mapping_context(inputs, context, *, mapping_cache=None):
    """Prefer a freshly inferable route check over a persisted checkbox."""
    result = deepcopy(context)
    if result.get("project_key") == "mapeng":
        from .drawing_station_mapping import infer_drawing_station_mapping
        if mapping_cache is None:
            current = infer_drawing_station_mapping(inputs)
        else:
            if "mapeng_station_mapping" not in mapping_cache:
                mapping_cache["mapeng_station_mapping"] = infer_drawing_station_mapping(inputs)
            current = mapping_cache["mapeng_station_mapping"]
        if current.get("confirmed"):
            result["station_mapping_evidence"] = current
            result["station_mapping_confirmed"] = True
    return result


def _scope_problems(template, scope, context):
    if not template.get("requires_station_mapping"):
        return []
    evidence = context.get("station_mapping_evidence") or {}
    if not evidence:
        return []
    handles = set(scope.get("source_handles", []))
    blocked = [row for row in evidence.get("blocked_ranges", []) if row.get("station_handle") in handles
               or handles.intersection(row.get("source_handles", []))]
    if blocked:
        return ["原图分区行与当前结构/完整范围冲突，不得截取局部交集后套用：" +
                "、".join(str(row.get("station_handle") or row.get("source_handles")) for row in blocked)]
    if not evidence.get("confirmed"):
        return ["原图桩号映射证据未通过，确认复选框不能替代实际核对"]
    if evidence.get("safe_ranges") is not None:
        safe = [row for row in evidence["safe_ranges"] if row.get("station_handle") in handles
                or handles.intersection(row.get("source_handles", []))]
        if not safe:
            return ["原图分区行未包含在已通过核对的安全范围中"]
    return []


def _is_assumption(asset, field):
    source = asset.get("parameter_sources", {}).get(field, "")
    if not isinstance(source, str) or field in asset.get("drawing_user_overrides", {}):
        return False
    if source.startswith("管道施工默认值："):
        record = asset.get("pipe_construction_default_source_values", {}).get(field) or {}
        return "adopted_value" in record and _same(_get(asset, field), record["adopted_value"])
    return source.startswith("施工参数假定：")


def _drawing_fields(template, asset):
    fields = dict(template.get("fields", {}))
    if template["template_id"] == "tangniwan_general":
        # This binding measures a separate 15 cm gravel layer. The table's
        # automatic sand cradle would otherwise deepen and widen that layer.
        construction = asset.get("construction", {})
        key = "pipe_seat" if construction.get("pipe_seat") else "pipe_support"
        seat = construction.get(key) or {}
        prefix = "construction." + key + "."
        if (seat.get("enabled") and seat.get("material_role") == "bedding"
                and all(_is_assumption(asset, prefix + name) for name in seat)):
            fields[prefix + "enabled"] = False
    return fields


def _preview(template, asset):
    changes, preserved = [], []
    fields = _drawing_fields(template, asset)
    for field, desired in fields.items():
        previous = _get(asset, field)
        if _same(previous, desired):
            continue
        record = {"field": field, "previous": deepcopy(previous), "current": deepcopy(desired)}
        if previous is None or _is_assumption(asset, field):
            changes.append(record)
        elif field == "section.component_specs":
            existing = {row.get("component_id"): row for row in previous} if isinstance(previous, list) else {}
            additions = [row for row in desired if row.get("component_id") not in existing]
            if additions:
                changes.append({**record, "current": deepcopy(previous) + deepcopy(additions)})
            if any(row.get("component_id") in existing and existing[row["component_id"]] != row for row in desired):
                preserved.append(record)
        else:
            preserved.append(record)
    return changes, preserved


def binding_candidates(inputs, project_context=None):
    """Return source-scoped proposals; only ``status=ready`` can be adopted.

    Every row is itself a complete binding request. Unknown projects, shape
    mismatches and missing construction conditions are visible but never active.
    """
    templates, result = list_templates(), []
    for network in inputs.get("networks", []):
        context, key, context_problem = _project_context(inputs, project_context, network)
        context = _mapping_context(inputs, context)
        for asset in network.get("assets", []):
            if not asset.get("enabled", True):
                continue
            for template in templates:
                if asset.get("section_type") not in template["section_types"]:
                    continue
                if key and template["project_key"] != key:
                    continue
                ranges = _range_rows(template, asset)
                for scope in ranges:
                    reasons = ([context_problem] if context_problem else []) + _constraints(
                        template, asset, context, check_bedding=True, preview=True) + _scope_problems(template, scope, context)
                    if any(not value for value in (network.get("network_id"),network.get("source_identity"),_asset_id(asset),asset.get("source_identity"))):
                        reasons.append("缺少稳定的工程对象或来源线路身份，须先读取正式设计成果")
                    changes, preserved = _preview(template, asset)
                    result.append({"schema": BINDING_SCHEMA, "network_id": network.get("network_id"),
                        "network_source_identity": deepcopy(network.get("source_identity")),
                        "asset_id": _asset_id(asset), "asset_name": asset.get("name", ""),
                        "source_identity": deepcopy(asset.get("source_identity")),
                        "project_identity": context.get("project_identity"), "project_context": context,
                        "template_id": template["template_id"], "template_version": template["version"],
                        "source_sha256": template["source_sha256"], "template_sha256": template["template_sha256"],
                        "drawing_id": template["drawing_id"], "title": template["title"],
                        "station_start": scope["station_start"], "station_end": scope["station_end"],
                        "scope_label": scope["scope_label"],
                        "source_handles": sorted(set(template.get("source_handles", []) + scope.get("source_handles", []))),
                        "status": "needs_context" if context_problem else ("incompatible" if reasons else "ready"),
                        "auto_applicable": not reasons, "reasons": reasons, "changes": changes,
                        "preserved_overrides": preserved, "warnings": deepcopy(template.get("warnings", []))})
    return result


def _binding_key(binding):
    return _canonical([binding.get(key) for key in ("network_id", "asset_id", "template_id", "station_start", "station_end")])


def _matching_assets(inputs, binding):
    if any(not binding.get(key) for key in ("network_id", "network_source_identity", "asset_id", "source_identity")):
        raise ValueError("图纸绑定缺少稳定的设计对象或来源线路身份")
    network = next((row for row in inputs.get("networks", []) if row.get("network_id") == binding.get("network_id")), None)
    if network is None or not _same(network.get("source_identity"), binding.get("network_source_identity")):
        raise ValueError("原线路身份已改变或不存在，绑定未重放")
    assets = [asset for asset in network.get("assets", []) if binding.get("asset_id") in (asset.get("asset_id"), _asset_id(asset))
              and _same(asset.get("source_identity"), binding.get("source_identity"))]
    if not assets:
        raise ValueError("原设计对象身份已改变或不存在，禁止按相同桩号转绑")
    return network, assets


def _validate_request(inputs, binding, template, *, mapping_cache=None, check_bedding=False):
    for field, expected in (("template_version", template["version"]), ("source_sha256", template["source_sha256"]),
                            ("template_sha256", template["template_sha256"])):
        if binding.get(field) != expected:
            raise ValueError("图纸或模板版本已改变，旧绑定须复核：" + field)
    if "template_snapshot" in binding and binding["template_snapshot"] != template:
        raise ValueError("保存的模板快照与当前模板不一致，须重新核对")
    network, family = _matching_assets(inputs, binding)
    context, key, problem = _project_context(inputs, inputs.get("drawing_project_context") or binding.get("project_context"), network)
    if problem:
        raise ValueError(problem)
    if key != template["project_key"] or binding.get("project_identity") != context.get("project_identity"):
        raise ValueError("工程身份与图纸绑定不一致，禁止跨工程套用")
    # Construction conditions may have been explicitly confirmed in the saved
    # binding; project identity still comes from current live inputs above.
    for name in ("scope_confirmed", "cover_depth_m", "drawing_variant", "station_mapping_confirmed"):
        if name not in context and name in (binding.get("project_context") or {}):
            context[name] = binding["project_context"][name]
    if "station_mapping_evidence" not in context and (binding.get("project_context") or {}).get("station_mapping_evidence"):
        context["station_mapping_evidence"] = deepcopy(binding["project_context"]["station_mapping_evidence"])
    context = _mapping_context(inputs, context, mapping_cache=mapping_cache)
    start, end = _finite(binding.get("station_start")), _finite(binding.get("station_end"))
    if start is None or end is None or end <= start:
        raise ValueError("绑定桩号必须有限且递增")
    targets = sorted((asset for asset in family if asset["station_end"] > start + _EPS and asset["station_start"] < end - _EPS),
                     key=lambda row: row["station_start"])
    cursor = start
    for asset in targets:
        if asset["station_start"] > cursor + _EPS:
            raise ValueError("绑定范围存在未属于原对象的线路缺段")
        a, b = max(start, asset["station_start"]), min(end, asset["station_end"])
        if a < cursor - _EPS:
            raise ValueError("原对象施工范围互相重叠，须先核对线路区段")
        if a < start - _EPS or b > end + _EPS:
            raise ValueError("绑定范围越界")
        constraints = _constraints(template, asset, context, check_bedding=check_bedding)
        if constraints:
            raise ValueError("；".join(constraints))
        allowed = _range_rows(template, asset)
        for row in allowed:
            if row["station_start"] < b - _EPS and row["station_end"] > a + _EPS:
                mapping_problems = _scope_problems(template, row, context)
                if mapping_problems:
                    raise ValueError("；".join(mapping_problems))
        spans = sorted((max(a, r["station_start"]), min(b, r["station_end"])) for r in allowed
                       if r["station_start"] < b - _EPS and r["station_end"] > a + _EPS)
        covered = a
        for left, right in spans:
            if left > covered + _EPS:
                break
            covered = max(covered, right)
        if covered < b - _EPS:
            raise ValueError("绑定范围超出原图明确适用区段，疑点行不能自动生效")
        cursor = max(cursor, b)
    if not targets or start < targets[0]["station_start"] - _EPS or cursor < end - _EPS:
        raise ValueError("绑定范围超出原设计对象，禁止外推或补造线路")
    return network, targets, start, end


def _slice(network, asset, start, end):
    """Reuse the editor's stable parent/range contract and exact profile clip."""
    if abs(start - asset["station_start"]) < _EPS and abs(end - asset["station_end"]) < _EPS:
        return asset
    from .design_profiles import clip_design_profile, evaluate_profile, profile_break_stations
    rows, root, parts, selected = network["assets"], _asset_id(asset), [], None
    for left, right, adopted in ((asset["station_start"], start, False), (start, end, True), (end, asset["station_end"], False)):
        if right <= left + _EPS:
            continue
        part = deepcopy(asset)
        part.update(station_start=left, station_end=right,
                    asset_id=root + f"-{left:.3f}-{right:.3f}", parent_asset_id=root, drawing_root_asset_id=root)
        # The common network alignment remains exact; clipping this profile
        # preserves line and vertical-arc formulas rather than sampled chords.
        if part.get("design_profile"):
            part["design_profile"] = clip_design_profile(part["design_profile"], left, right)
            part["profile_points"] = [{"station": station, "elevation": evaluate_profile(part["design_profile"], station)[0]}
                                      for station in profile_break_stations(part["design_profile"])]
        part["geometry_sections"] = []
        parts.append(part)
        if adopted:
            selected = part
    index = rows.index(asset)
    rows[index:index + 1] = parts
    return selected


def _adopt_fields(asset, template, binding, report, replace_assumptions):
    asset.setdefault("drawing_root_asset_id", binding["asset_id"])
    sources = asset.setdefault("parameter_sources", {})
    evidence = asset.setdefault("drawing_parameter_sources", {})
    overrides = asset.setdefault("drawing_user_overrides", {})
    replayed={}
    for row in binding.get("user_overrides",[]):
        field=row.get("field")
        if not _replayable_override(field) or not (row["station_start"]<=asset["station_start"]+_EPS
                and row["station_end"]>=asset["station_end"]-_EPS):
            continue
        if field in replayed and not _same(replayed[field],row["value"]):
            raise ValueError("同一区段存在相互冲突的用户覆盖："+field)
        replayed[field]=deepcopy(row["value"])
        _set(asset,field,row["value"])
        overrides[field]=deepcopy(row["value"])
        sources[field]="用户覆盖：保留已保存的区段施工参数"
    fields = _drawing_fields(template, asset)
    if asset.get("section_type", "").startswith("circular") and "section.wall_thickness" in fields:
        # These are existing geometry aliases, not independent new dimensions.
        fields.update({"section." + key: fields["section.wall_thickness"] for key in
                       ("base_thickness", "wall_thickness_left", "wall_thickness_right", "roof_thickness")})
    for field, value in replayed.items():
        if field not in fields:
            report["preserved_overrides"].append({"asset_id":asset["asset_id"],"field":field,
                "value":deepcopy(value),"reason":"保留本区段用户修改；不要求该字段属于图纸模板"})
    for field, desired in fields.items():
        previous, prior = _get(asset, field), evidence.get(field)
        source = sources.get(field, "")
        user_changed = field in overrides or str(source).startswith("用户") or prior and not _same(previous, prior.get("adopted_value"))
        allow = previous is None or replace_assumptions and _is_assumption(asset, field)
        if field == "section.component_specs" and previous is not None and not user_changed:
            existing = {row.get("component_id"): row for row in previous} if isinstance(previous, list) else {}
            additions = [row for row in desired if row.get("component_id") not in existing]
            conflicts = [row for row in desired if row.get("component_id") in existing and not _same(existing[row["component_id"]], row)]
            if not conflicts:
                desired = deepcopy(previous) + deepcopy(additions)
                allow = True
        if user_changed or not allow and not _same(previous, desired):
            overrides[field] = deepcopy(previous)
            report["preserved_overrides"].append({"asset_id": asset["asset_id"], "field": field,
                "value": deepcopy(previous), "drawing_value": deepcopy(desired), "reason": "保留用户覆盖或原设计；图纸不覆盖明确来源值"})
            continue
        original = deepcopy(prior.get("original_value")) if prior else deepcopy(previous)
        evidence[field] = {"template_id": template["template_id"], "template_version": template["version"],
            "drawing_id": template["drawing_id"], "source_sha256": template["source_sha256"],
            "source_handles": deepcopy(binding.get("source_handles", template.get("source_handles", []))),
            "original_value": original, "adopted_value": deepcopy(desired)}
        sources[field] = f"图纸依据：{template['title']} / {template['version']} / {template['source_sha256'][:12]}"
        if not _same(previous, desired):
            _set(asset, field, desired)
            report["field_changes"].append({"asset_id": asset["asset_id"], "field": field,
                "previous": deepcopy(previous), "current": deepcopy(desired), "template_id": template["template_id"]})
    asset["geometry_sections"] = []
    asset["missing_fields"] = [path for path in asset.get("missing_fields", []) if _get(asset, path) is None]
    record = {key: deepcopy(binding.get(key)) for key in ("template_id", "template_version", "source_sha256",
        "template_sha256", "drawing_id", "source_handles", "project_identity", "station_start", "station_end", "scope_label")}
    current = asset.setdefault("drawing_bindings", [])
    current[:] = [row for row in current if row.get("template_id") != record["template_id"]]
    current.append(record)
    _refresh_pipe_derivations(asset, template, binding, report)


def _refresh_pipe_derivations(asset, template, binding, report):
    """Recompute only previously declared derived/assumed circular envelopes."""
    section = asset.get("section", {})
    if not asset.get("section_type", "").startswith("circular") or "section.wall_thickness" not in template.get("fields", {}):
        return
    sources, evidence = asset.setdefault("parameter_sources", {}), asset.setdefault("drawing_parameter_sources", {})
    outer_path = "section.outer_diameter"
    if (section.get("inner_diameter") is not None and section.get("wall_thickness") is not None
            and str(sources.get(outer_path, "")).startswith("水力内径＋")
            and outer_path not in asset.get("drawing_user_overrides", {})):
        old = section.get("outer_diameter")
        new = float(section["inner_diameter"]) + 2*(float(section["wall_thickness"]) + float(section.get("lining_thickness") or 0.))
        section["outer_diameter"] = new
        if not _same(old, new):
            report["field_changes"].append({"asset_id": asset["asset_id"], "field": outer_path,
                "previous": old, "current": new, "template_id": template["template_id"], "reason": "沿原声明的内径和管壁推导规则重算外径"})
    for index, pipe in enumerate(section.get("pipes") or [], 1):
        previous_wall = pipe.get("wall_thickness")
        previous_outer = pipe.get("outer_diameter")
        for key in ("wall_thickness", "material"):
            path = f"section.pipes[{index}].{key}"
            if section.get(key) is None:
                continue
            override = next((row for row in binding.get("user_overrides", []) if row.get("field") == path
                and row["station_start"] <= asset["station_start"] + _EPS and row["station_end"] >= asset["station_end"] - _EPS), None)
            if override:
                pipe[key] = deepcopy(override["value"])
                asset.setdefault("drawing_user_overrides", {})[path] = deepcopy(override["value"])
                sources[path] = "用户覆盖：保留已保存的逐管施工参数"
                report["preserved_overrides"].append({"asset_id": asset["asset_id"], "field": path,
                    "value": deepcopy(override["value"]), "drawing_value": section[key]})
            elif pipe.get(key) is None or str(sources.get(path, "")).startswith("施工参数假定："):
                old = pipe.get(key)
                pipe[key] = deepcopy(section[key])
                sources[path] = f"图纸依据：{template['title']} / 采用本对象统一管壁设置"
                evidence[path] = {"template_id": template["template_id"], "source_sha256": template["source_sha256"],
                    "source_handles": deepcopy(binding.get("source_handles", [])), "original_value": old,
                    "adopted_value": deepcopy(pipe[key])}
                if not _same(old, pipe[key]):
                    report["field_changes"].append({"asset_id": asset["asset_id"], "field": path,
                        "previous": old, "current": deepcopy(pipe[key]), "template_id": template["template_id"]})
        if (previous_wall is not None and pipe.get("inner_diameter") is not None
                and _same(previous_outer, float(pipe["inner_diameter"])+2*(float(previous_wall)+float(pipe.get("lining_thickness") or 0.)))
                and not _same(previous_wall, pipe.get("wall_thickness"))):
            pipe["outer_diameter"] = float(pipe["inner_diameter"])+2*(float(pipe["wall_thickness"])+float(pipe.get("lining_thickness") or 0.))


def capture_drawing_overrides(inputs):
    """Capture parameter edits into saved bindings before a source reimport."""
    bindings = deepcopy(inputs.get("drawing_bindings", []))
    for binding in bindings:
        records = []
        try:
            _, family = _matching_assets(inputs, binding)
        except ValueError:
            continue
        for asset in family:
            if asset["station_start"] >= binding["station_end"] - _EPS or asset["station_end"] <= binding["station_start"] + _EPS:
                continue
            fields = set(asset.get("drawing_user_overrides", {})) | set(asset.get("drawing_parameter_sources", {}))
            for field in fields:
                if not _replayable_override(field):
                    continue
                previous = asset.get("drawing_parameter_sources", {}).get(field)
                value = _get(asset, field)
                if field in asset.get("drawing_user_overrides", {}) or previous and not _same(value, previous.get("adopted_value")):
                    records.append({"field": field, "value": deepcopy(value),
                        "station_start": max(asset["station_start"], binding["station_start"]),
                        "station_end": min(asset["station_end"], binding["station_end"])})
        binding["user_overrides"] = records
    inputs["drawing_bindings"] = deepcopy(bindings)
    return bindings


def apply_drawing_bindings(inputs, bindings, *, replace_assumptions=True):
    """Adopt validated bindings in place; reject each invalid request atomically."""
    return _apply_bindings(inputs, bindings, list_templates(), replace_assumptions=replace_assumptions)


def restore_drawing_bindings(inputs, saved_bindings):
    """Restore previously adopted snapshots and their user overrides on source reimport."""
    return _apply_bindings(inputs, saved_bindings, _read_templates(), restore=True)


def _apply_bindings(inputs, bindings, registry, *, replace_assumptions=True, restore=False):
    templates = {row["template_id"]: row for row in registry}
    report = {"applied": [], "rejected": [], "field_changes": [], "preserved_overrides": [], "requires_recalculation": False}
    bindings = deepcopy(list(bindings or []))
    for binding in bindings:
        template = templates.get(binding.get("template_id"))
        if not template:
            report["rejected"].append({"binding": binding, "reason": "图纸模板不存在"})
            continue
        snapshot, partial = deepcopy(inputs), {"field_changes": [], "preserved_overrides": []}
        try:
            if restore and (binding.get("schema") != BINDING_SCHEMA or "template_snapshot" not in binding):
                raise ValueError("恢复图纸绑定需要原工程保存的精确模板快照")
            network, targets, start, end = _validate_request(snapshot, binding, template)
            # Saved user overrides may introduce genuine new construction
            # boundaries; preserve them with the same exact clipping contract.
            boundaries = sorted({start, end} | {float(row[key]) for row in binding.get("user_overrides", [])
                for key in ("station_start", "station_end") if start < float(row[key]) < end})
            for left, right in zip(boundaries, boundaries[1:]):
                targets = [asset for asset in network["assets"] if binding["asset_id"] in (asset.get("asset_id"), _asset_id(asset))
                    and _same(asset.get("source_identity"), binding.get("source_identity"))
                    and asset["station_start"] < right - _EPS and asset["station_end"] > left + _EPS]
                for asset in targets:
                    selected = _slice(network, asset, max(left, asset["station_start"]), min(right, asset["station_end"]))
                    _adopt_fields(selected, template, binding, partial, replace_assumptions)
            # Replayed user construction fields must still satisfy the chosen
            # engineering scope (for example a box cover-depth limit).
            _validate_request(snapshot,binding,template,check_bedding=True)
            saved = {key: deepcopy(value) for key, value in binding.items() if key not in {
                "status", "auto_applicable", "reasons", "changes", "preserved_overrides"}}
            saved["schema"] = BINDING_SCHEMA
            saved["template_snapshot"] = deepcopy(template)
            records = snapshot.setdefault("drawing_bindings", [])
            records[:] = [row for row in records if _binding_key(row) != _binding_key(saved)]
            records.append(saved)
            files = snapshot.setdefault("input_files", [])
            for resource in _drawing_resources(template):
                files[:] = [row for row in files if not (isinstance(row, dict)
                    and row.get("path") == resource["path"] and str(row.get("role", "")).startswith("drawing_")
                    and row.get("sha256") != resource["sha256"])]
                if not any(row.get("sha256") == resource["sha256"] for row in files if isinstance(row, dict)):
                    files.append(resource)
            snapshot.setdefault("drawing_project_context", deepcopy(binding.get("project_context") or {}))
            if not snapshot["drawing_project_context"]:
                snapshot["drawing_project_context"] = deepcopy(binding.get("project_context") or {})
            # A changed source, material or construction parameter invalidates
            # old prepared sections and enters the normal result fingerprint.
            basis = snapshot.setdefault("quantity_basis", {})
            basis["construction_parameters"] = "drawing_bound_with_explicit_assumptions"
            basis["drawing_binding_count"] = len(records)
            basis["drawing_binding_sha256"] = _digest(records)
            basis["label"] = "水面线设计高程＋真实图纸绑定（未绑定字段保留原设计/施工假定）"
            inputs.clear()
            inputs.update(snapshot)
            report["applied"].append(deepcopy(saved))
            report["field_changes"].extend(partial["field_changes"])
            report["preserved_overrides"].extend(partial["preserved_overrides"])
        except (ValueError, KeyError, TypeError, OSError) as exc:
            report["rejected"].append({"binding": binding, "reason": str(exc)})
    report["requires_recalculation"] = bool(report["field_changes"] or report["applied"])
    report["applied_count"] = len(report["applied"])
    report["rejected_count"] = len(report["rejected"])
    return report


def validate_active_bindings(inputs, *, raise_on_error=False):
    """Check exact active snapshots and available source bytes without mutation.

    A portable installation need not contain the original author's directory.
    Its compiled source facts and saved exact template snapshot remain required;
    whenever an original DXF is available its real bytes are also checked.
    """
    errors, count = [], 0
    try:
        templates = {row["template_id"]: row for row in _read_templates()}
    except DrawingLibraryError as exc:
        if not inputs.get("drawing_bindings"):
            return {"valid": True, "errors": [], "checked_count": 0}
        errors.append(str(exc))
        templates = {}
    checked_sources = set()
    # All bindings in this read-only validation see the same live inputs.
    # Applying bindings uses the uncached default because its snapshot changes.
    mapping_cache = {}
    for binding in inputs.get("drawing_bindings", []):
        count += 1
        template = templates.get(binding.get("template_id"))
        if not template:
            errors.append("采用的模板已不存在：" + str(binding.get("template_id")))
            continue
        try:
            if not isinstance(binding.get("template_snapshot"), dict):
                raise ValueError("已采用的图纸绑定缺少精确模板快照")
            _validate_request(inputs, binding, template, mapping_cache=mapping_cache, check_bedding=True)
            if template["drawing_id"] not in checked_sources:
                _drawing_resources(template)
                checked_sources.add(template["drawing_id"])
        except (DrawingLibraryError, ValueError, KeyError, TypeError, OSError) as exc:
            errors.append(str(exc))
    for resource in inputs.get("input_files", []):
        if not isinstance(resource, dict) or not str(resource.get("role", "")).startswith("drawing_"):
            continue
        path = Path(resource.get("path") or "")
        if path.is_file():
            try:
                if _file_digest(path) != resource.get("sha256"):
                    errors.append("采用的图纸证据资源字节已改变：" + path.name)
            except OSError as exc:
                errors.append("无法核对采用的图纸证据：" + str(exc))
    result = {"valid": not errors, "errors": sorted(set(errors)), "checked_count": count}
    if errors and raise_on_error:
        raise DrawingLibraryError("图纸绑定已失效，须复核或重新绑定：\n" + "\n".join(result["errors"]))
    return result
