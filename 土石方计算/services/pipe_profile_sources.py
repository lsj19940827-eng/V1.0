"""Water-profile design geometry and explicit longitudinal choices on project refresh."""
from copy import deepcopy

from .design_profiles import (
    DesignProfileError, clip_design_profile, evaluate_profile, normalize_design_profile,
    profile_break_stations, sync_bound_axis_controls,
)
from .siphon_axis_choices import is_siphon_axis_asset, siphon_source_boundary


def _profile_runs(parts, start, end, reference):
    pieces = []
    for part in parts:
        profile = normalize_design_profile(part, reference=reference)
        left = max(start, profile["station_start"])
        right = min(end, profile["station_end"])
        if right > left:
            pieces.append(clip_design_profile(profile, left, right))
    runs = []
    last_end = None
    for piece in sorted(pieces, key=lambda p: p["station_start"]):
        if last_end is not None and piece["station_start"] < last_end - 1e-7:
            raise DesignProfileError("设计纵断面存在缺段或重叠，请核对多段线", station=piece["station_start"])
        if last_end is None or piece["station_start"] > last_end + 1e-7:
            runs.append([])
        runs[-1].extend(piece["elements"])
        last_end = piece["station_end"]
    return [normalize_design_profile({"elements": run}, reference=reference) for run in runs]


def water_profile_runs(source, start, end, *, reference):
    """Separate connected real entities; the flattened vertex list may cross tunnels."""
    def entities(value):
        if isinstance(value, dict) and value.get("parts"):
            for part in value["parts"]:
                yield from entities(part)
        else:
            yield value
    return _profile_runs(entities(source), start, end, reference)


def clip_water_profile_parts(raw, start, end, *, reference):
    runs = water_profile_runs(raw, start, end, reference=reference)
    if not runs:
        raise DesignProfileError("水面线设计线未覆盖当前管段", code="missing_design_profile", station=start)
    if len(runs) > 1:
        raise DesignProfileError("设计纵断面存在缺段或重叠", station=runs[0]["station_end"])
    return clip_design_profile(runs[0], start, end)


def _local_water_geometry(parts, start, end):
    runs = _profile_runs(parts, start, end, parts[0]["reference"])
    whole = None
    if (len(runs) == 1 and runs[0]["station_start"] <= start + 1e-7 and runs[0]["station_end"] >= end - 1e-7):
        whole = runs.pop()
    return whole, runs


def water_profile_spans(asset):
    """Intervals for review before adopting a discontinuous water-profile axis."""
    parts = asset.get("water_profile_parts") or []
    if not parts:
        return []
    spans = []
    cursor, end = asset["station_start"], asset["station_end"]
    for part in _profile_runs(parts, cursor, end, parts[0]["reference"]):
        left, right = part["station_start"], part["station_end"]
        if left > cursor + 1e-7:
            spans.append((cursor, left, "pending"))
        spans.append((left, right, "mapped"))
        cursor = right
    if cursor < end - 1e-7:
        spans.append((cursor, end, "pending"))
    return spans


def adopt_water_profile_parts(inputs, network, asset):
    """Apply reviewed coverage to one object, preserving its adjacent objects and the gap."""
    from .imported_design_profiles import _find_selected_network
    from .pipe_profile_partitions import partition_piece

    owner = _find_selected_network(inputs, asset, network)
    matches = [item for item in (owner or {}).get("assets", ()) if item.get("asset_id") == asset.get("asset_id")]
    if len(matches) != 1:
        raise ValueError("工程对象已变化，请重新选择。")
    original = matches[0]
    parts = original.get("water_profile_parts") or []
    spans = water_profile_spans(original)
    if not parts or not any(state == "mapped" for _, _, state in spans):
        raise ValueError("当前对象没有可采用的水面线设计线。")
    updated = deepcopy(inputs)
    i = next(i for i, row in enumerate(inputs["networks"]) if row is owner)
    j = next(j for j, item in enumerate(owner["assets"]) if item is original)
    children = []
    for start, end, state in spans:
        part = partition_piece(original, start, end, state)
        part.pop("water_profile_parts", None)
        if state == "mapped":
            profile, _ = _local_water_geometry(parts, start, end)
            for field in ("profile_source_file", "profile_import_mapping", "cover_preview_confirmed",
                          "cover_confirmation", "axis_preview_sha256", "axis_cover_samples"):
                part.pop(field, None)
            part.update(water_profile_design_profile=profile, pipe_profile_choice="water_profile")
            _apply_profile(part, profile, "water_profile_real_elevation")
        else:
            part.pop("water_profile_design_profile", None)
        children.append(part)
    updated["networks"][i]["assets"][j:j+1] = children
    return updated


def _key(network, asset):
    return (network.get("source_identity") or network.get("network_id"),
            asset.get("source_identity") or asset.get("asset_id"))


def pipe_profile_choice(asset):
    explicit = asset.get("pipe_profile_choice")
    if explicit:
        return explicit
    if (asset.get("axis_source") == "terrain_and_user_cover_depth" or asset.get("cover_confirmation")
            or (asset.get("siphon_axis_choice") or {}).get("mode") == "cover_depth"):
        return "cover_depth"
    if (asset.get("construction") or {}).get("burial_mode") == "cover_depth":
        for path in ("construction.burial_mode", "construction.cover_depth", "construction.cover_segments"):
            if path in (asset.get("drawing_user_overrides") or {}) or str(
                    (asset.get("parameter_sources") or {}).get(path, "")).startswith("用户"):
                return "cover_depth"
    if (asset.get("axis_source") in ("user_input_real_elevation", "supplied_profile_dxf")
            or asset.get("profile_source") == "user_input_real_elevation"
            or asset.get("profile_source_file")):
        return "quantity_dxf"
    return ""


def _apply_profile(asset, profile, source):
    profile = clip_design_profile(profile, asset["station_start"], asset["station_end"])
    points = [{"station": s, "elevation": evaluate_profile(profile, s)[0]} for s in profile_break_stations(profile)]
    asset.update(design_profile=profile, profile_points=points, axis_source=source, profile_source=source)
    asset.setdefault("alignment", {}).update(profile_points=deepcopy(points), elevation_reference=profile["reference"])
    asset.setdefault("construction", {}).update(burial_mode="actual_axis", axis_confirmed=True)
    sync_bound_axis_controls(asset)
    asset["missing_fields"] = [f for f in asset.get("missing_fields") or [] if f != "design_profile"]


def _previous_asset(network, asset, previous, boundaries):
    candidates = previous.get(_key(network, asset)) or []
    if not candidates and is_siphon_axis_asset(asset):
        candidates = boundaries.get(siphon_source_boundary(asset)) or []
    a, b = asset.get("station_start"), asset.get("station_end")
    if a is None or b is None:
        return None
    covering = [item for item in candidates
                if item.get("station_start") is not None and item.get("station_end") is not None
                and item["station_start"] <= a + 1.e-7 and b <= item["station_end"] + 1.e-7]
    return covering[0] if len(covering) == 1 else None


def refresh_pipe_profile_choices(inputs, previous_inputs):
    """Refresh water sources and retain local selections after re-slicing the same project."""
    if any(old.get("pipe_profile_partition") for network in previous_inputs.get("networks", [])
           for old in network.get("assets", [])):
        from .pipe_profile_partitions import restore_pipe_profile_partitions
        restore_pipe_profile_partitions(inputs, previous_inputs)
    previous, boundaries = {}, {}
    for network in previous_inputs.get("networks", []):
        for old in network.get("assets", []):
            previous.setdefault(_key(network, old), []).append(old)
            boundary = siphon_source_boundary(old)
            if boundary:
                boundaries.setdefault(boundary, []).append(old)
    retained_paths = set()
    for network in inputs.get("networks", []):
        for asset in network.get("assets", []):
            siphon = is_siphon_axis_asset(asset)
            if not siphon and asset.get("kind") not in {"pipe", "pressure_pipe"}:
                continue
            old = _previous_asset(network, asset, previous, boundaries)
            choice = pipe_profile_choice(old) if old else ""
            if asset.get("water_profile_parts"):
                whole, local = _local_water_geometry(asset["water_profile_parts"], asset["station_start"], asset["station_end"])
                if whole:
                    asset["water_profile_design_profile"] = whole
                if local:
                    asset["water_profile_parts"] = local
                else:
                    asset.pop("water_profile_parts", None)
            if choice:
                asset["pipe_profile_choice"] = choice
            if choice == "quantity_dxf":
                for file_source in (old.get("profile_source_file"), old.get("profile_source"),
                                    old.get("profile_import_mapping"), (old.get("siphon_axis_input") or {}).get("source")):
                    if isinstance(file_source, dict):
                        retained_paths.update(row["path"] for row in (file_source, *(file_source.get("curves") or []))
                                              if isinstance(row, dict) and row.get("path"))
            if choice == "pending_gap":
                asset["enabled"] = False
                for field in ("design_profile", "profile_points", "axis_source", "profile_source", "cover_preview_confirmed"):
                    asset.pop(field, None)
                asset.setdefault("alignment", {}).pop("profile_points", None)
                asset.setdefault("construction", {}).pop("axis_confirmed", None)
                continue
            # Siphons reapply native offsets and pending/alignment preferences in
            # refresh_siphon_axis_choices. Their fresh source copy remains selectable.
            if siphon:
                continue
            fresh = asset.get("water_profile_design_profile")
            if choice == "cover_depth":
                for field in ("design_profile", "profile_points", "axis_source", "profile_source", "cover_confirmation",
                              "cover_preview_confirmed", "axis_cover_samples", "axis_preview_sha256"):
                    asset.pop(field, None)
                asset.setdefault("alignment", {}).pop("profile_points", None)
                construction = asset.setdefault("construction", {})
                construction.update(burial_mode="cover_depth", axis_confirmed=False)
                for field in ("cover_depth", "cover_segments"):
                    if field in old.get("construction", {}):
                        construction[field] = deepcopy(old["construction"][field])
                continue
            if choice == "quantity_dxf" and old.get("design_profile"):
                _apply_profile(asset, old["design_profile"], "user_input_real_elevation")
                if old.get("axis_source") == "supplied_profile_dxf":
                    asset["axis_source"] = old["axis_source"]
                if isinstance(old.get("profile_source"), dict):
                    asset["profile_source"] = deepcopy(old["profile_source"])
                for field in ("profile_source_file", "profile_import_mapping", "cover_preview_confirmed"):
                    if field in old:
                        asset[field] = deepcopy(old[field])
            elif fresh:
                # A previous automatic cover default can be replayed as part of
                # general construction settings. The new actual profile owns this mode.
                _apply_profile(asset, fresh, "water_profile_real_elevation")
    known = {row.get("path") for row in inputs.get("input_files", [])}
    for file in previous_inputs.get("input_files", []):
        if file.get("path") in retained_paths - known:
            inputs.setdefault("input_files", []).append(deepcopy(file))
            known.add(file["path"])


def _same_source_points(old, fresh):
    def points(a):
        records = (a.get("original_fields") or {}).get("records") or []
        return {r["profile_row_id"]: (r["x"], r["y"]) for r in records if r.get("profile_row_id")
                and r.get("x") is not None and r.get("y") is not None}
    before, now = points(old), points(fresh)
    if not before or not now:
        return True
    shared = before.keys() & now.keys()
    return bool(shared) and all(before[k] == now[k] for k in shared)


def _saved_axis_updates(inputs, snapshot):
    from ..adapters.workbench_sources import _source_panel, import_workbench_project
    from .siphon_axis_choices import configure_siphon_axis

    candidates = [(i, j, network, asset)
                  for i, network in enumerate(inputs.get("networks") or [])
                  for j, asset in enumerate(network.get("assets") or [])
                  if (asset.get("source_identity") and not asset.get("water_profile_design_profile")
                      and (asset.get("kind") in {"pipe", "pressure_pipe"} or is_siphon_axis_asset(asset)))]
    if not candidates:
        return []
    panel = _source_panel(snapshot)
    if (panel.get("water_result_current") is False or (panel.get("merged_section") or {}).get("sync_ready") is False
            or snapshot.get("test_only")):
        return []
    pressure = snapshot.get("pressure_pipe_manager_data") or {}
    siphons = snapshot.get("siphon_manager_data") or {}
    if not (any(pressure.get(k) for k in ("routes", "pipes", "segments")) or siphons.get("siphons")):
        return []
    # Source import owns its copies. Historical workbench results and plotting
    # caches are intentionally outside this project-snapshot subset.
    design = import_workbench_project({"water_profile_panel": panel, "pressure_pipe_manager_data": pressure,
                                       "siphon_manager_data": siphons})
    sources, boundaries = {}, {}
    for network in design["networks"]:
        for asset in network["assets"]:
            if (asset.get("water_profile_design_profile") or asset.get("water_profile_parts")) and not asset.get("is_test"):
                sources.setdefault(_key(network, asset), []).append(asset)
                boundary = siphon_source_boundary(asset)
                if boundary:
                    boundaries.setdefault(boundary, []).append(asset)
    updates = []
    for i, j, network, old in candidates:
        source = _previous_asset(network, old, sources, boundaries)
        if source is None or not _same_source_points(old, source):
            continue
        start, end = old["station_start"], old["station_end"]
        if source.get("water_profile_design_profile"):
            water = clip_design_profile(source["water_profile_design_profile"], start, end)
            local = []
        else:
            water, local = _local_water_geometry(source["water_profile_parts"], start, end)
        if not water and (not local or local == old.get("water_profile_parts")):
            continue
        fresh = deepcopy(old)
        if not water:
            fresh["water_profile_parts"] = local
            updates.append((i, j, fresh))
            continue
        fresh.pop("water_profile_parts", None)
        fresh["water_profile_design_profile"] = water
        selected = pipe_profile_choice(old)
        original = old.get("design_profile") or old.get("profile_points") or (old.get("alignment") or {}).get("profile_points")
        if not original and selected in {"", "water_profile"}:
            if is_siphon_axis_asset(old):
                choice = (old.get("siphon_axis_choice") or {}).get("mode", "auto")
                axis_input = source["siphon_axis_input"]
                configure_siphon_axis(fresh, mode=choice, profile=axis_input["profile"], source=axis_input["source"])
            else:
                _apply_profile(fresh, water, "water_profile_real_elevation")
        updates.append((i, j, fresh))
    return updates


def inherit_saved_water_axes(saved_inputs, snapshot):
    """Supplement an editable saved workbench, without touching calculation history."""
    updates = _saved_axis_updates(saved_inputs, snapshot)
    for i, j, asset in updates:
        saved_inputs["networks"][i]["assets"][j] = asset
    return bool(updates)


def with_saved_water_axes(project):
    """Copy only the edited source objects when opening an older workbench project."""
    panel = project.get("earthwork_panel") or {}
    inputs = panel.get("workbench_inputs") or {}
    if panel.get("kind") != "section_workbench" or not inputs.get("networks"):
        return project
    updates = _saved_axis_updates(inputs, project)
    if not updates:
        return project
    networks = list(inputs["networks"])
    modified = set()
    for i, j, asset in updates:
        if i not in modified:
            networks[i] = dict(networks[i], assets=list(networks[i]["assets"]))
            modified.add(i)
        networks[i]["assets"][j] = asset
    updated_panel = dict(panel, workbench_inputs=dict(inputs, networks=networks), result_status="STALE")
    return dict(project, earthwork_panel=updated_panel)
