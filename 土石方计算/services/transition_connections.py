"""Construction choices for hydraulic transitions and missing-IP connections."""
from copy import deepcopy
import hashlib
import json
import math

from .construction_rules import structural_lining_thicknesses
from .design_profiles import clip_alignment, clip_design_profile, evaluate_profile, normalize_design_profile
from .network_alignment import NetworkAlignment

_PRESSURE_TYPES = {"倒虹吸", "有压管道", "顶管", "定向钻"}
CONNECTION_SECTION_KINDS = {
    "rectangular_channel": "open_channel",
    "trapezoidal_channel": "open_channel",
    "compound_trapezoidal_channel": "open_channel",
    "u_channel": "open_channel",
    "rectangular_culvert": "culvert",
    "arch_culvert": "culvert",
    "circular_culvert": "culvert",
}
_CONNECTION_NETWORKS = {"native_transition_connection", "missing_ip_connection",
                        "estimated_water_profile_connection"}
_LOCAL_COMPONENT_FIELDS = {"component_specs", "discrete_components", "quantity_rules", "quantity_scope_not_applicable"}
_FLAT_BOTTOM_SECTIONS = {"rectangular_channel", "trapezoidal_channel", "rectangular_culvert"}


def connection_needs_settings(candidate):
    return not candidate.get("auto_applied") and candidate.get("status") not in {
        "applied", "automatic", "covered", "estimated"}


def connection_flow_section(*sources):
    from 推求水面线.core.connection_channel import flow_section_key

    known = {flow_section_key(source.get("flow_section")) for source in sources if source} - {""}
    return next(iter(known)) if len(known) == 1 else ""


def connection_design_flow(*sources):
    flows = {flow for source in sources if source
             if (flow := _finite(source.get("flow", source.get("Q")))) is not None and flow > 0}
    return next(iter(flows)) if len(flows) == 1 else None


def connection_channel_inputs(flow_section, design_flow, nodes, profile, *, settings=None):
    from .workbench_hydraulics import channel_calculator_defaults

    references = [node for node in nodes if str(node.get("structure_type") or "").startswith(("明渠", "暗涵"))]
    defaults = channel_calculator_defaults({"flow": design_flow}, flow_section=flow_section,
                                           references=references, settings=settings)
    points = (profile or {}).get("points") or []
    if len(points) >= 2 and "slope_inverse" not in defaults:
        fall = points[0]["elevation"] - points[-1]["elevation"]
        distance = points[-1]["station"] - points[0]["station"]
        if fall > 1e-9 and distance > 0. and math.isfinite(inverse := distance / fall):
            defaults["slope_inverse"] = inverse
    return defaults


def connection_source_inverts(start, end, upstream, downstream):
    """Use a known control only at its own station."""
    inverts = {}
    for key, station, node in (("start_invert", start, upstream), ("end_invert", end, downstream)):
        position = _station(node)
        elevation = _hydraulic_bottom(node)
        if elevation == 0. and not (node.get("water_depth") or node.get("structure_height")):
            elevation = None
        if position is not None and abs(position - station) <= 1e-7 and elevation is not None:
            inverts[key] = elevation
    return inverts


def transition_section_references(inputs, candidate):
    """Return the closest adjoining source asset of each supported construction form."""
    from .estimated_connections import _touching_sections

    references = [asset for asset in _touching_sections(inputs, candidate)
                  if CONNECTION_SECTION_KINDS.get(asset.get("section_type")) == asset.get("kind")
                  and asset.get("section_type") in CONNECTION_SECTION_KINDS]
    flow = connection_flow_section(candidate)
    if flow:
        references.sort(key=lambda asset: connection_flow_section(asset) != flow)
    result = {}
    for asset in references:
        result.setdefault(asset["section_type"], asset)
    return result


def transition_section_defaults(inputs, candidate, section_type=None):
    """Provide an editable copy of the selected source geometry and lining."""
    references = transition_section_references(inputs, candidate)
    suggested = candidate.get("suggested_section") or {}
    shape = section_type or next(iter(references), None) or suggested.get("section_type") or "rectangular_channel"
    defaults = deepcopy(suggested) if shape == suggested.get("section_type") else {}
    defaults.update(section_type=shape, kind=CONNECTION_SECTION_KINDS.get(shape))
    defaults["section"] = defaults.get("section") or {}
    defaults["construction"] = defaults.get("construction") or {}
    reference = references.get(shape)
    if reference is not None:
        defaults.update(reference_name=reference.get("name"), reference_asset_id=reference.get("asset_id"))
        for group in ("section", "construction"):
            defaults[group].update({key: deepcopy(value) for key, value in (reference.get(group) or {}).items()
                                    if value is not None and key not in _LOCAL_COMPONENT_FIELDS})
    if shape == "circular_culvert":
        section = defaults["section"]
        defaults["diameter_m"] = (section.get("outer_diameter") or section.get("nominal_diameter_m")
                                  or section.get("inner_diameter") or defaults.get("diameter_m"))
    else:
        lining_reference = reference or next(iter(references.values()), None)
        for key, value in structural_lining_thicknesses(lining_reference).items():
            if defaults["section"].get(key) is None and value is not None:
                defaults["section"][key] = value
        if shape == "u_channel" and defaults["section"].get("u_bottom_thickness") is None:
            base = defaults["section"].get("base_thickness")
            if base is not None:
                defaults["section"]["u_bottom_thickness"] = base
        # A flat-bottom reference can also provide corresponding dimensions
        # when the user chooses another flat-bottom form.
        if shape in _FLAT_BOTTOM_SECTIONS and reference is None:
            flat = next((asset for asset in references.values()
                         if asset["section_type"] in _FLAT_BOTTOM_SECTIONS), None)
            if flat is not None:
                for key in ("inner_width", "inner_height"):
                    value = _finite((flat.get("section") or {}).get(key))
                    if defaults["section"].get(key) is None and value is not None and value > 0:
                        defaults["section"][key] = value
                defaults.update(reference_name=flat.get("name"), reference_asset_id=flat.get("asset_id"))
    return defaults


def _finite(value):
    try:
        value = float(value)
    except (ValueError, TypeError):
        return None
    return value if math.isfinite(value) else None


def _station(node):
    return next((_finite(node[key]) for key in ("station_MC", "station_mc", "chainage", "station")
                 if node.get(key) is not None), None)


def _hydraulic_bottom(node):
    value = _finite(node.get("bottom_elevation"))
    if node.get("structure_type") in _PRESSURE_TYPES and not node.get("structure_height"):
        return None
    return value


def _connection_profile(upstream, downstream, start, end):
    """Use real channel beds, or continue a declared adjacent design grade."""
    left, right = _hydraulic_bottom(upstream), _hydraulic_bottom(downstream)
    basis = "相邻水面线节点实际渠底高程"
    if left is not None and right is None:
        inherited = _finite(downstream.get("bottom_elevation"))
        if inherited is not None and abs(inherited - left) <= .0005:
            right = left
            basis = "承压进口继承相邻渠底，保留上游未取整高程"
        else:
            grade = _finite(upstream.get("slope_i"))
            if grade is None:
                return None
            right = left - grade * (end - start)
            basis = "上游水面线实际渠底及明确设计底坡延续到连接末端"
    elif right is not None and left is None:
        grade = _finite(downstream.get("slope_i"))
        if grade is None:
            return None
        left = right + grade * (end - start)
        basis = "下游水面线实际渠底及明确设计底坡延续到连接起点"
    if left is None or right is None:
        return None
    return {"reference": "inner_invert", "points": [
        {"station": start, "elevation": left}, {"station": end, "elevation": right}], "basis": basis}


def _source_asset(inputs, node):
    identity = node.get("profile_row_id")
    if not identity:
        return None
    for network in inputs.get("networks", []):
        for asset in network.get("assets", []):
            records = (asset.get("original_fields") or {}).get("records") or []
            if any(row.get("profile_row_id") == identity for row in records):
                return asset
    return None


def _uncovered(start, end, occupied):
    cursor = start
    gaps = []
    for a, b in sorted(occupied):
        if b <= cursor or a >= end:
            continue
        if a > cursor + 1e-7:
            gaps.append((cursor, min(a, end)))
        cursor = max(cursor, b)
        if cursor >= end - 1e-7:
            break
    if cursor < end - 1e-7:
        gaps.append((cursor, end))
    return gaps


def _same_plan(first, second, start, end):
    if first is None or second is None:
        return False
    if isinstance(first, dict):
        first = NetworkAlignment.from_dict(first)
    if isinstance(second, dict):
        second = NetworkAlignment.from_dict(second)
    a = max(start, first.start_station, second.start_station)
    b = min(end, first.end_station, second.end_station)
    return b > a + 1e-7 and all(
        math.dist(first.get_xy_at_station(s), second.get_xy_at_station(s)) <= 1e-4
        for s in (a, (a + b) / 2, b))


def collect_transition_candidates(inputs, nodes, alignment, *, settings=None):
    """List unoccupied physical source transitions and bounded routing gaps."""
    if alignment is None:
        return []
    occupied = [(a["station_start"], a["station_end"])
                for n in inputs.get("networks", []) for a in n.get("assets", [])
                if a.get("station_start") is not None and a.get("station_end") is not None
                and _same_plan(n.get("alignment"), alignment, a["station_start"], a["station_end"])]
    occupied.extend((a["station_start"], a["station_end"]) for a in inputs.get("excluded", [])
                    if a.get("station_start") is not None and a.get("station_end") is not None)
    candidates = []
    seen = set()
    for index, transition in enumerate(nodes):
        if not transition.get("is_transition"):
            continue
        upstream = next((n for n in reversed(nodes[:index]) if not n.get("is_transition")), None)
        downstream = next((n for n in nodes[index + 1:] if not n.get("is_transition")), None)
        if upstream is None or downstream is None:
            continue
        start, end = _station(upstream), _station(downstream)
        if start is None or end is None or end <= start + 1e-7:
            continue
        if start < alignment.start_station - 1e-7 or end > alignment.end_station + 1e-7:
            continue
        profile = _connection_profile(upstream, downstream, start, end)
        left, right = _source_asset(inputs, upstream), _source_asset(inputs, downstream)
        same_section = (left is not None and right is not None
            and left["kind"] == right["kind"] and left["kind"] in {"open_channel", "culvert"}
            and left["section_type"] == right["section_type"] and left["section"] == right["section"])
        suggestion = {"kind": "culvert", "section_type": "circular_culvert",
                      "diameter_m": None, "section": {}, "construction": {}}
        if same_section:
            suggestion.update(kind=left["kind"], section_type=left["section_type"],
                section=deepcopy(left["section"]), construction=deepcopy(left["construction"]),
                diameter_m=left["section"].get("outer_diameter"))
        for a, b in _uncovered(start, end, occupied):
            identity = [upstream.get("profile_row_id"), downstream.get("profile_row_id"), a, b]
            candidate_id = "transition-" + hashlib.sha256(
                json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
            if candidate_id in seen:
                continue
            seen.add(candidate_id)
            reasons = []
            candidate_profile = None
            if profile:
                normalized = normalize_design_profile(profile["points"], reference=profile["reference"])
                candidate_profile = {**deepcopy(profile), "points": [
                    {"station": s, "elevation": evaluate_profile(normalized, s)[0]} for s in (a, b)]}
            else:
                reasons.append("缺少可靠连接渠底高程或相邻明确设计底坡")
            length = _finite(transition.get("transition_length"))
            extent_known = length is not None and abs(length - (end - start)) <= 1e-5
            if not extent_known:
                reasons.append("原生渐变长度与相邻实际里程不一致，需核定施工范围")
            if not same_section:
                reasons.append("渐变两侧施工断面不同，需明确连接构造及尺寸")
            automatic = same_section and candidate_profile is not None and extent_known
            flow = connection_flow_section(transition) or connection_flow_section(upstream, downstream)
            design_flow = connection_design_flow(transition) or connection_design_flow(upstream, downstream)
            channel_inputs = connection_channel_inputs(flow, design_flow, (upstream, downstream), candidate_profile,
                                                       settings=settings)
            source_inverts = connection_source_inverts(a, b, upstream, downstream)
            candidates.append({"candidate_id": candidate_id,
                "name": f"{upstream.get('name') or '上游'}至{downstream.get('name') or '下游'}连接段",
                "station_start": a, "station_end": b, "length_m": b - a,
                "source_node_ids": [upstream.get("profile_row_id"), downstream.get("profile_row_id")],
                "source_types": [upstream.get("structure_type"), downstream.get("structure_type")],
                "source_sections": [deepcopy(upstream.get("section_params") or {}),
                                    deepcopy(downstream.get("section_params") or {})],
                "source_kind": "native_transition",
                **({"flow_section": flow} if flow else {}),
                **({"design_flow": design_flow} if design_flow is not None else {}),
                **({"channel_inputs": channel_inputs} if channel_inputs else {}),
                **({"source_inverts": source_inverts} if source_inverts else {}),
                "source_transition": deepcopy(transition), "source_transition_length_m": length,
                "plan_alignment": clip_alignment(alignment, a, b).to_dict(), "profile": candidate_profile,
                "suggested_section": deepcopy(suggestion),
                "status": "ready" if automatic else "needs_parameters", "reasons": reasons,
                "extent_confirmed": extent_known, "auto_applicable": automatic, "auto_applied": False})
    from .estimated_connections import collect_missing_ip_candidates
    candidates.extend(collect_missing_ip_candidates(inputs, nodes, alignment, candidates, settings=settings))
    return sorted(candidates, key=lambda candidate: (candidate["station_start"], candidate["station_end"]))


def _new_asset(inputs, candidate, options):
    from .pipe_dimensions import mark_imported_pipe_diameter
    from .section_geometry import number

    suggested = candidate["suggested_section"]
    section_type = options.get("section_type") or suggested["section_type"]
    kind = CONNECTION_SECTION_KINDS.get(section_type)
    if kind is None:
        raise ValueError("请选择已支持的连接段施工断面")
    use_suggestion = section_type == suggested["section_type"]
    use_envelope = use_suggestion and (suggested.get("section") or {}).get("earthwork_envelope_only")
    defaults = suggested if use_envelope else transition_section_defaults(inputs, candidate, section_type)
    section = deepcopy(defaults.get("section") or {})
    supplied_section = deepcopy(options.get("section") or {})
    section.update(supplied_section)
    diameter = None
    if section_type == "circular_culvert":
        if "diameter_m" in options:
            diameter = number(options, "diameter_m", positive=True)
            if not supplied_section:
                section = {}
        elif "inner_diameter" in supplied_section and "nominal_diameter_m" not in supplied_section:
            # A newly entered net diameter defines actual construction geometry.
            # Do not inherit the old DN envelope fixed to a different diameter.
            section = supplied_section
            number(section, "inner_diameter", positive=True)
        elif not section.get("inner_diameter") and not section.get("nominal_diameter_m"):
            diameter = number(defaults, "diameter_m", positive=True)
    elif section_type == "u_channel":
        number(section, "inner_radius", positive=True)
        number(section, "inner_height", positive=True)
    else:
        number(section, "inner_width", positive=True)
        number(section, "wall_height" if section_type == "arch_culvert" else "inner_height",
               positive=section_type != "arch_culvert")
    manual_profile = options.get("profile")
    profile = options.get("profile") or candidate.get("profile")
    if not profile:
        raise ValueError("请填写连接段两端净内底高程")
    if not isinstance(profile, dict) or profile.get("reference") != "inner_invert":
        raise ValueError("连接渠底须明确采用净内底高程")
    normalized = normalize_design_profile(profile.get("points") or profile, reference="inner_invert")
    start, end = candidate["station_start"], candidate["station_end"]
    if (abs(normalized["elements"][0]["station_start"] - start) > 1e-7
            or abs(normalized["elements"][-1]["station_end"] - end) > 1e-7):
        raise ValueError("连接高程范围须完整对应候选起止桩号")
    construction = deepcopy(defaults.get("construction") or {})
    supplied_construction = deepcopy(options.get("construction") or {})
    construction.update(supplied_construction)
    if kind == "culvert":
        mode = supplied_construction.get("target_mode")
        # For a configured closed connector, restoring terrain means exactly
        # that, even for a round culvert with legacy embankment parameters.
        if mode is None and candidate.get("source_kind") == "missing_ip_gap":
            mode = "restore_terrain"
        if mode == "restore_terrain":
            construction.update(target_mode=mode, retain_culvert_support_fill=False)
            construction.pop("final_cover_depth", None)
        elif mode == "cover_above_terrain":
            construction["retain_culvert_support_fill"] = False
            number(construction, "final_cover_depth")
            for side in ("left", "right"):
                number(construction, "bank_slope_"+side, 1.5)
                number(construction, "bank_top_width_"+side, 0.)
                if "bank_slope_"+side in supplied_construction and "bank_stages_"+side not in supplied_construction:
                    construction.pop("bank_stages_"+side, None)
    missing_ip = candidate.get("source_kind") == "missing_ip_gap"
    asset_id = candidate["candidate_id"]
    points = [{"station": e["station_start"], "elevation": e["z_start"]}
              for e in normalized["elements"]]
    points.append({"station": end, "elevation": evaluate_profile(normalized, end)[0]})
    asset = {"asset_id": asset_id, "name": candidate["name"], "source_identity": asset_id,
        "kind": kind, "section_type": section_type,
        **({"flow_section": candidate["flow_section"]} if candidate.get("flow_section") else {}),
        "source_type": "缺口施工连接" if missing_ip else "原生渐变施工连接",
        "station_start": start, "station_end": end, "section": section, "construction": construction,
        "enabled": True, "missing_fields": [], "geometry_sections": [],
        "design_profile": normalized, "profile_points": points,
        "alignment": {"profile_points": deepcopy(points), "elevation_reference": "inner_invert"},
        "original_fields": {"transition_candidate": {key: deepcopy(value) for key, value in candidate.items()
            if key not in {"status", "auto_applied", "asset_id", "asset_ids", "adopted_section_type",
                           "adopted_section", "adopted_construction", "adopted_profile", "estimated_asset_ids",
                           "replayed_from_candidate_id"}}},
        "profile_boundary_basis": profile.get("basis", "用户核定连接渠底"),
        "parameter_source": "user_confirmed", "transition_candidate_id": asset_id,
        "quantity_scope_notes": ["按已采用施工断面计入对应结构分类。"]}
    if manual_profile:
        asset["connection_profile_override"] = deepcopy(manual_profile)
    if diameter is not None:
        mark_imported_pipe_diameter(asset, diameter=diameter, source="用户核定连接圆管涵直径")
    return asset


def _remove_connections(inputs, ids):
    if not ids:
        return
    for network in inputs.get("networks", []):
        network["assets"] = [asset for asset in network.get("assets", []) if asset.get("asset_id") not in ids]
    inputs["networks"] = [network for network in inputs.get("networks", [])
        if network.get("assets") or (network.get("source") or {}).get("kind") not in _CONNECTION_NETWORKS]
    for key in ("construction_assumptions", "connector_estimates"):
        if key in inputs:
            inputs[key] = [record for record in inputs[key] if record.get("asset_id") not in ids]


def _adopted_settings(candidate, asset):
    candidate.update(asset_id=asset["asset_id"], adopted_section_type=asset["section_type"],
                     adopted_section=deepcopy(asset["section"]), adopted_construction=deepcopy(asset["construction"]),
                     adopted_profile={"reference": "inner_invert", "points": deepcopy(asset["profile_points"]),
                                      "basis": asset.get("profile_boundary_basis")})


def apply_transition_candidates(inputs, candidate_ids, *, section_type="circular_culvert",
        diameter_m=None, construction=None, confirmed=False, overrides=None):
    """Apply a selected batch atomically and return editable copies with a report."""
    from .construction_defaults import apply_assumed_construction
    from .section_geometry import section_structure
    result = deepcopy(inputs)
    report = {"valid": True, "applied": [], "failures": [], "skipped": []}
    ids = list(dict.fromkeys(candidate_ids))
    if not confirmed:
        raise ValueError("采用连接施工候选须由用户确认断面及尺寸")
    lookup = {row["candidate_id"]: row for row in result.get("transition_candidates", [])}
    pending = []
    for identifier in ids:
        candidate = lookup.get(identifier)
        if candidate is None:
            report["failures"].append({"candidate_id": identifier, "message": "连接候选已不存在，请刷新资料"})
            continue
        options = {"section_type": section_type, "construction": construction}
        if diameter_m is not None:
            options["diameter_m"] = diameter_m
        options.update(deepcopy((overrides or {}).get(identifier) or {}))
        if candidate["status"] in {"applied", "automatic", "estimated"} and not options.get("replace_existing"):
            report["skipped"].append({"candidate_id": identifier, "message": "该连接已采用"})
            continue
        try:
            asset = _new_asset(result, candidate, options)
            start, end = candidate["station_start"], candidate["station_end"]
            replaced = _connection_assets(result, candidate, include_estimates=True) if options.get("replace_existing") else []
            if any(old["station_start"] < start-1e-7 or old["station_end"] > end+1e-7 for old in replaced):
                raise ValueError("现有估算跨出该连接范围，需重新读取来源")
            replace_ids = {old["asset_id"] for old in replaced}
            if options.get("replace_existing"):
                replace_ids.update(candidate.get("estimated_asset_ids") or [])
            if replaced:
                asset["enabled"] = any(old.get("enabled", True) for old in replaced)
            for network in result.get("networks", []):
                for existing in network.get("assets", []):
                    if (existing.get("asset_id") not in replace_ids and existing.get("station_start") is not None
                            and existing.get("station_end") is not None
                            and min(end, existing["station_end"]) - max(start, existing["station_start"]) > 1e-7
                            and _same_plan(network.get("alignment"), candidate["plan_alignment"], start, end)):
                        raise ValueError("连接范围已有施工对象，请刷新候选后再采用")
            for excluded in result.get("excluded", []):
                a, b = excluded.get("station_start"), excluded.get("station_end")
                if a is not None and b is not None and min(end, b) - max(start, a) > 1e-7:
                    raise ValueError("连接范围已被排除，请刷新候选后再采用")
            for other, _, other_network, _ in pending:
                if (min(end, other["station_end"]) - max(start, other["station_start"]) > 1e-7
                        and _same_plan(other_network["alignment"], candidate["plan_alignment"], start, end)):
                    raise ValueError("选择的连接范围互相重叠")
            source = "missing_ip_connection" if candidate.get("source_kind") == "missing_ip_gap" else "native_transition_connection"
            network = {"schema_version": "1.0", "network_id": identifier,
                "name": candidate["name"], "source_identity": identifier, "source": {"kind": source},
                "alignment": NetworkAlignment.from_dict(candidate["plan_alignment"]),
                "assets": [asset], "test_only": False, "status": "DRAFT"}
            defaults = apply_assumed_construction({"networks": [network]})
            section_structure(asset)
            pending.append((candidate, replace_ids, network, defaults["assumptions"]))
        except (ValueError, TypeError, KeyError) as error:
            report["failures"].append({"candidate_id": identifier, "message": str(error)})
    if report["failures"]:
        report["valid"] = False
        return deepcopy(inputs), report
    for candidate, replace_ids, network, assumptions in pending:
        _remove_connections(result, replace_ids)
        asset, = network["assets"]
        result.setdefault("networks", []).append(network)
        result.setdefault("construction_assumptions", []).extend(assumptions)
        candidate.pop("estimated_asset_ids", None)
        candidate.pop("asset_ids", None)
        candidate.update(status="applied", auto_applied=False)
        _adopted_settings(candidate, asset)
        for issue in result.get("diagnostics", []):
            if (issue.get("code") == "unassigned_design_range" and issue.get("station") is not None
                    and abs(issue["station"] - candidate["station_start"]) <= 1e-7):
                issue.update(resolved=True, resolution="connection_construction_adopted")
        report["applied"].append({"candidate_id": candidate["candidate_id"], "asset_id": asset["asset_id"],
            "name": asset["name"], "station_start": asset["station_start"], "station_end": asset["station_end"],
            "section_type": asset["section_type"]})
    return result, report


def automatically_apply_same_section_connections(inputs):
    """Use matching ordinary sections only when the native extent and beds are explicit."""
    ids = [row["candidate_id"] for row in inputs.get("transition_candidates", [])
           if row.get("auto_applicable") and row["status"] not in {"applied", "automatic"}]
    if not ids:
        return inputs
    choices = {row["candidate_id"]: {"section_type": row["suggested_section"]["section_type"]}
               for row in inputs["transition_candidates"] if row["candidate_id"] in ids}
    result, report = apply_transition_candidates(inputs, ids, confirmed=True, overrides=choices)
    if report["valid"]:
        for row in result["transition_candidates"]:
            if row["candidate_id"] in ids:
                row.update(status="automatic", auto_applied=True)
    return result


def _candidate_source_key(candidate):
    identities = candidate.get("source_node_ids") or []
    types = candidate.get("source_types") or []
    if len(identities) != 2 or not all(identities):
        return None
    return tuple(identities), tuple(types), candidate.get("source_kind", "native_transition"), candidate.get("source_partition")


def _connection_assets(inputs, candidate, *, include_estimates=False):
    identifier = candidate["candidate_id"]
    linked_ids = set(candidate.get("asset_ids") or []) | {candidate.get("asset_id", identifier)}
    if include_estimates:
        linked_ids.update(candidate.get("estimated_asset_ids") or [])
    linked_ids.discard(None)
    return sorted([asset for network in inputs.get("networks", []) for asset in network.get("assets", [])
                   if asset.get("transition_candidate_id") == identifier
                   or not linked_ids.isdisjoint((asset.get("asset_id"), asset.get("parent_asset_id"),
                                                  asset.get("source_identity")))],
                  key=lambda asset: asset["station_start"])


def _has_manual_round_estimate(candidate, assets):
    return (candidate.get("status") == "estimated"
            and candidate.get("adopted_section_type") == "circular_culvert"
            and any(asset.get("parameter_source") == "user_confirmed"
                    or asset.get("drawing_user_overrides") for asset in assets))


def adopt_edited_round_estimates(inputs):
    """Keep explicit edits made outside the connection dialog as adopted settings."""
    replaced = set()
    for candidate in inputs.get("transition_candidates", ()):
        if candidate.get("status") != "estimated" or candidate.get("adopted_section_type") != "circular_culvert":
            continue
        assets = _connection_assets(inputs, candidate, include_estimates=True)
        if not _has_manual_round_estimate(candidate, assets):
            continue
        identifier = candidate["candidate_id"]
        replaced.update(candidate.pop("estimated_asset_ids", ()))
        for asset in assets:
            asset.update(transition_candidate_id=identifier, source_type="缺口施工连接")
            asset.get("original_fields", {}).pop("estimated_connection", None)
        candidate.update(status="applied", auto_applied=False, asset_ids=[asset["asset_id"] for asset in assets])
        _adopted_settings(candidate, assets[0])
    if replaced:
        inputs["connector_estimates"] = [row for row in inputs.get("connector_estimates", ())
                                         if row["asset_id"] not in replaced]


def _replay_connection(inputs, candidate, previous_candidate, previous_assets):
    """Recreate chosen construction against the new profile and source plan."""
    identifier = candidate["candidate_id"]
    first = previous_assets[0]
    start, end = candidate["station_start"], candidate["station_end"]
    old_start, old_end = previous_candidate["station_start"], previous_candidate["station_end"]
    moved = abs(start - old_start) > 1e-7 or abs(end - old_end) > 1e-7
    if len(previous_assets) > 1 and moved:
        raise ValueError("源连接范围已变化，旧分段施工参数需重新核定适用桩号")
    if (abs(previous_assets[0]["station_start"] - old_start) > 1e-7
            or abs(previous_assets[-1]["station_end"] - old_end) > 1e-7):
        raise ValueError("旧连接施工选择只覆盖部分来源范围，需重新核定")
    manual = deepcopy(first.get("connection_profile_override"))
    if manual and moved:
        points = manual.get("points") or []
        if len(points) != 2:
            raise ValueError("源连接范围已变化，需重新设置多点连接渠底")
        points[0]["station"], points[-1]["station"] = start, end
    options = {"section_type": first["section_type"], "section": first.get("section"),
               "construction": first.get("construction"), "profile": manual, "replace_existing": True}
    attempt, applied = apply_transition_candidates(inputs, [identifier], confirmed=True,
        overrides={identifier: options})
    if not applied["valid"]:
        raise ValueError("；".join(row["message"] for row in applied["failures"]))
    network = next(n for n in attempt["networks"]
                   if any(a.get("transition_candidate_id") == identifier for a in n.get("assets", [])))
    fresh = next(a for a in network["assets"] if a.get("transition_candidate_id") == identifier)
    cursor = old_start
    replacement = []
    for index, previous in enumerate(previous_assets):
        if abs(previous["station_start"] - cursor) > 1e-7:
            raise ValueError("旧连接施工选择存在未明确区间，需重新核定")
        cursor = previous["station_end"]
        a, b = (start, end) if len(previous_assets) == 1 else (previous["station_start"], previous["station_end"])
        asset = deepcopy(fresh)
        for key in ("kind", "section_type", "section", "construction", "enabled", "parameter_source", "parameter_sources",
                    "drawing_user_overrides", "section_scheme_user_overrides", "workbench_geometry"):
            if key in previous:
                asset[key] = deepcopy(previous[key])
        asset.update(station_start=a, station_end=b)
        if len(previous_assets) > 1:
            asset["asset_id"] = f"{identifier}-part-{index + 1}"
            asset["parent_asset_id"] = identifier
        profile = clip_design_profile(fresh["design_profile"], a, b)
        points = [{"station": element["station_start"], "elevation": element["z_start"]}
                  for element in profile["elements"]]
        points.append({"station": b, "elevation": evaluate_profile(profile, b)[0]})
        asset.update(design_profile=profile, profile_points=points)
        asset["alignment"] = {"profile_points": deepcopy(points), "elevation_reference": profile["reference"]}
        replacement.append(asset)
    network["assets"] = replacement
    selected = next(row for row in attempt["transition_candidates"] if row["candidate_id"] == identifier)
    selected.update(status="applied", auto_applied=False, replayed_from_candidate_id=previous_candidate["candidate_id"],
                    asset_ids=[asset["asset_id"] for asset in replacement])
    _adopted_settings(selected, replacement[0])
    return attempt


def replay_transition_connections(new_inputs, previous_inputs):
    """Return a copy with confirmed local choices on fresh source elevations.

    The caller establishes that the two imports belong to the same project.
    Unmatched choices remain audit records and do not contribute geometry.
    """
    result = deepcopy(new_inputs)
    report = {"replayed": [], "pending_review": [], "skipped": []}
    pending = deepcopy(previous_inputs.get("unmatched_transition_choices") or [])
    choices = [row for row in previous_inputs.get("transition_candidates", [])
               if row.get("status") in {"applied", "automatic"}
               or row.get("status") == "estimated" and row.get("adopted_section_type") == "circular_culvert"]
    for previous in choices:
        estimated = previous.get("status") == "estimated"
        previous_assets = _connection_assets(previous_inputs, previous, include_estimates=estimated)
        if estimated and not _has_manual_round_estimate(previous, previous_assets):
            continue
        if not previous_assets:
            report["skipped"].append({"candidate_id": previous["candidate_id"],
                                      "message": "旧候选没有已采用施工对象"})
            continue
        source_key = _candidate_source_key(previous)
        current = [row for row in result.get("transition_candidates", [])
                   if row.get("source_types") == previous.get("source_types")]
        matches = [row for row in current if row["candidate_id"] == previous["candidate_id"]]
        if not matches and source_key is not None:
            matches = [row for row in current if _candidate_source_key(row) == source_key]
        reason = "连接来源已变化，未找到唯一对应的原生连接，原施工选择保留待核"
        manual_profile = previous_assets[0].get("connection_profile_override")
        if len(matches) == 1 and (matches[0].get("profile") or manual_profile):
            try:
                result = _replay_connection(result, matches[0], previous, previous_assets)
                report["replayed"].append({"candidate_id": matches[0]["candidate_id"],
                    "previous_candidate_id": previous["candidate_id"],
                    "source_elevations_refreshed": not bool(manual_profile), "construction_part_count": len(previous_assets)})
                continue
            except (ValueError, KeyError, TypeError) as error:
                reason = "连接来源刷新后需核定：" + str(error)
        elif len(matches) == 1:
            reason = "新来源缺少可靠连接高程，原施工选择保留待核"
        entry = {"candidate_id": previous["candidate_id"], "name": previous.get("name"),
                 "reason": reason, "previous_candidate": deepcopy(previous),
                 "previous_assets": deepcopy(previous_assets)}
        pending = [row for row in pending if row["candidate_id"] != previous["candidate_id"]]
        pending.append(entry)
    result["unmatched_transition_choices"] = pending
    report["pending_review"] = [{"candidate_id": row["candidate_id"], "name": row.get("name"),
                                  "message": row["reason"]} for row in pending]
    for row in report["pending_review"]:
        message = f"{row.get('name') or row['candidate_id']}：{row['message']}"
        diagnostic = {"code": "transition_source_changed", "severity": "warning",
                      "candidate_id": row["candidate_id"], "message": message}
        if diagnostic not in result.setdefault("diagnostics", []):
            result["diagnostics"].append(diagnostic)
    return result, report
