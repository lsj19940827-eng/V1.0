"""Edit positioned pipe construction and unlocated material allowances together."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from math import fsum, inf

from .default_section_schemes import restore_default_section_range
from .earthwork_scope import trenchless_exclusions, trenchless_intersections, trenchless_range_covered
from .section_scheme_bindings import _overrides, _route, apply_section_scheme, format_station, parse_station
from .replacement_geometry import replacement_overrides
from .special_pipe_materials import (
    KEY, _axis_length, _binding_scheme, _config, _group, _number, _positioned_material, _special,
    apply_length_materials, is_segment_scheme, list_special_material_groups, validate_length_material_rows,
)


_STATION_TOLERANCE = 1e-7
_SPECIAL_OVERLAP_TOLERANCE = 1e-8


@dataclass(frozen=True)
class PositionedPipeSpan:
    group: dict
    start: float
    end: float


@dataclass(frozen=True)
class _PositionedPipeScope:
    groups: list[dict]
    boundaries: set[float]
    first: float
    last: float
    owners: dict
    exclusions: list[dict]
    excluded_by_route: dict


def is_special_pipe_object(asset):
    from .batch_cover_profiles import is_pressure_cover_asset
    return asset.get("kind") != "tunnel" and (
        is_pressure_cover_asset(asset) or asset.get("section_type") == "circular_culvert"
    )


def segment_records(group):
    records = []
    for part in group["parts"]:
        if group.get("source_groups") or not _special(part):
            continue
        scheme = _binding_scheme(part)
        binding = part["section_scheme_binding"]
        start, end = part["station_start"], part["station_end"]
        try:
            length = _axis_length(part)
        except (ValueError, KeyError):
            length = None
        overrides = {**deepcopy(binding.get("overrides") or {}), **_overrides(part)}
        replacement_overrides(part, scheme, {}, overrides)
        records.append({"key": "station-" + binding["binding_sha256"], "mode": "station",
            "scheme": scheme, "start": start, "end": end, "length": length,
            "soil_only": group["mode"] == "length" and not _positioned_material(group, part),
            "overrides": overrides})
    if group["mode"] == "length":
        for row in group["rows"]:
            record = {"key": row["record_id"], "mode": "ratio" if "object_percent" in row else "length",
                "scheme": row["scheme_snapshot"], "length": row["length_m"],
                "percent": row.get("object_percent"), "overrides": deepcopy(row.get("overrides", {}))}
            if "percent_basis" in row:
                record["percent_basis"] = row["percent_basis"]
            records.append(record)
    return records


def positioned_length(group, start, end):
    """Get the true axis length for a contiguous selected specification."""
    start, end = float(start), float(end)
    if end <= start:
        raise ValueError("终点桩号须大于起点桩号")
    pieces = [(part, max(start, part["station_start"]), min(end, part["station_end"]))
              for part in group["parts"] if part["station_start"] < end and part["station_end"] > start]
    if abs(fsum(b-a for _, a, b in pieces) - (end-start)) > _STATION_TOLERANCE:
        raise ValueError("起止桩号须位于本规格的连续管段内，跨规格或隧洞请分段填写")
    try:
        return fsum(_axis_length(part, a, b) for part, a, b in pieces)
    except (ValueError, KeyError):
        return None


def _snap_displayed_station(station, boundaries):
    """Keep a copied millimetre-rounded boundary on its original engineering station."""
    if abs(station - round(station, 3)) > _STATION_TOLERANCE:
        return station
    matches = [boundary for boundary in boundaries if round(boundary * 1000) / 1000 == station]
    return matches[0] if len(matches) == 1 else station


def _open_cut_spans(group, part, start, end, excluded):
    cursor = max(start, part["station_start"])
    stop = min(end, part["station_end"])
    for left, right in excluded:
        if right <= cursor:
            continue
        if left >= stop:
            break
        if left > cursor + _STATION_TOLERANCE:
            yield PositionedPipeSpan(group, cursor, left)
        cursor = max(cursor, right)
    if stop > cursor + _STATION_TOLERANCE:
        yield PositionedPipeSpan(group, cursor, stop)


def _positioned_pipe_scope(inputs, groups):
    groups = [group for group in groups if not group.get("source_groups")]
    boundaries = {part[key] for group in groups for part in group["parts"]
                  for key in ("station_start", "station_end")}
    if not boundaries:
        raise ValueError("当前管道没有明挖区段")
    first, last = min(boundaries), max(boundaries)
    routes = {group["route_id"] for group in groups}
    owners = {_route(network): network for network in inputs.get("networks", [inputs])
              if _route(network) in routes}
    exclusions = trenchless_exclusions(inputs)
    excluded_by_route = {
        route: [(left, right) for left, right in trenchless_intersections(exclusions, owner, -inf, inf)
                if left <= last and right >= first]
        for route, owner in owners.items()
    }
    boundaries.update(station for intervals in excluded_by_route.values() for pair in intervals for station in pair
                      if first <= station <= last)
    return _PositionedPipeScope(groups, boundaries, first, last, owners, exclusions, excluded_by_route)


def positioned_pipe_spans(inputs, groups, start, end, *, prefix="K", allow_trenchless=True):
    """Resolve typed chainage to unique open-cut spans and intervening non-open-cut gaps."""
    scope = _positioned_pipe_scope(inputs, groups)
    start, end = (_snap_displayed_station(value, scope.boundaries) for value in (start, end))
    if not allow_trenchless:
        _validate_open_cut_row(start, end, _known_non_open_cut(scope), prefix)
    return _resolve_positioned_pipe_spans(scope, start, end, prefix)


def _resolve_positioned_pipe_spans(scope, start, end, prefix):
    groups, first, last = scope.groups, scope.first, scope.last
    if end <= start:
        raise ValueError("终点桩号须大于起点桩号")
    if start < first - _STATION_TOLERANCE or end > last + _STATION_TOLERANCE:
        interval = f"{format_station(first, prefix)} ～ {format_station(last, prefix)}"
        object_name = "倒虹吸" if all(group["section_type"] == "circular_siphon" for group in groups) else "管道"
        raise ValueError(f"起止桩号须位于当前{object_name}范围 {interval}")
    pieces = [
        span
        for group in groups for part in group["parts"]
        if part["station_start"] < end and part["station_end"] > start
        for span in _open_cut_spans(group, part, start, end, scope.excluded_by_route.get(group["route_id"], ()))
    ]
    if not pieces:
        raise ValueError("起止桩号范围内没有明挖管段")
    spans, gaps = [], []
    boundary = start
    for span in sorted(pieces, key=lambda piece: (piece.start, piece.end)):
        if span.start < boundary - _STATION_TOLERANCE:
            raise ValueError("起止桩号同时落在多个重叠的明挖管段，请核对工程区段")
        if span.start > boundary + _STATION_TOLERANCE:
            gaps.append((boundary, span.start))
        if spans and spans[-1].group is span.group and abs(span.start - spans[-1].end) <= _STATION_TOLERANCE:
            spans[-1] = PositionedPipeSpan(span.group, spans[-1].start, span.end)
        else:
            spans.append(span)
        boundary = span.end
    if end > boundary + _STATION_TOLERANCE:
        gaps.append((boundary, end))
    if gaps:
        for left, right in gaps:
            if not any(trenchless_range_covered(scope.exclusions, owner, left, right, allow_partial=True)
                       for owner in scope.owners.values()):
                interval = f"{format_station(left, prefix)} ～ {format_station(right, prefix)}"
                raise ValueError(f"{interval} 未匹配明挖或已知非开挖区段，请核对起止桩号")
    specification = _positioned_specification(spans[0])
    if any(_positioned_specification(span) != specification for span in spans[1:]):
        raise ValueError("起止桩号跨不同管道尺寸或材质，请分段填写")
    return spans, gaps


def _positioned_specification(span):
    return span.group["section_type"], span.group["specification"]["section"]


def _validate_positioned_overlap(records, start, end, editing):
    if any(record["mode"] == "station" and record["key"] != editing
           and record["start"] < end - _SPECIAL_OVERLAP_TOLERANCE
           and record["end"] > start + _SPECIAL_OVERLAP_TOLERANCE for record in records):
        raise ValueError("起止桩号与已设特殊段重叠，请调整范围或编辑原记录")


def _known_non_open_cut(scope):
    return sorted({interval for intervals in scope.excluded_by_route.values() for interval in intervals})


def _validate_open_cut_row(start, end, non_open_cut, prefix):
    if start is None:
        blocked = [(left, right) for left, right in non_open_cut if left < end <= right]
        instruction = "终点桩号位于", "请按明挖范围填写"
        missing = "起点桩号"
    elif end is None:
        blocked = [(left, right) for left, right in non_open_cut if left <= start < right]
        instruction = "起点桩号位于", "请按明挖范围填写"
        missing = "终点桩号"
    else:
        blocked = [(left, right) for left, right in non_open_cut if start < end and left < end and right > start]
        instruction = "所填范围包含", "请按两侧明挖范围分行填写"
        missing = None
    if blocked:
        intervals = "、".join(f"{format_station(left, prefix)} ～ {format_station(right, prefix)}"
                             for left, right in blocked)
        location, action = instruction
        raise ValueError(f"{location}非开挖区段 {intervals}，{action}")
    if missing:
        raise ValueError(f"缺少{missing}")


def positioned_pipe_ranges(inputs, groups, ranges, *, prefix="K", editing=None, editing_group=None):
    """Resolve station rows that each lie wholly within open-cut construction."""
    scope = _positioned_pipe_scope(inputs, groups)
    non_open_cut = _known_non_open_cut(scope)
    resolved, records_by_group = [], {}
    for row, (start, end) in enumerate(ranges, 1):
        has_start, has_end = (value is not None and bool(str(value).strip()) for value in (start, end))
        if not has_start and not has_end:
            continue
        try:
            start, end = (_snap_displayed_station(parse_station(value, prefix=prefix), scope.boundaries)
                          if present else None for value, present in ((start, has_start), (end, has_end)))
            _validate_open_cut_row(start, end, non_open_cut, prefix)
            spans, _ = _resolve_positioned_pipe_spans(scope, start, end, prefix)
            for span in spans:
                group_id = span.group["group_id"]
                if group_id not in records_by_group:
                    records_by_group[group_id] = segment_records(span.group)
                _validate_positioned_overlap(records_by_group[group_id], span.start, span.end,
                                             editing if group_id == editing_group else None)
        except ValueError as error:
            raise ValueError(f"第 {row} 行，{error}") from error
        resolved.append((spans[0].start, spans[-1].end, row, spans))
    if not resolved:
        raise ValueError("请填写起点桩号和终点桩号")
    resolved.sort(key=lambda interval: (interval[0], interval[1]))
    for previous, current in zip(resolved, resolved[1:]):
        if current[0] < previous[1] - _SPECIAL_OVERLAP_TOLERANCE:
            first, second = sorted((previous[2], current[2]))
            raise ValueError(f"第 {first} 行与第 {second} 行的桩号范围重叠")
    reference_row, reference_spans = resolved[0][2:4]
    specification = _positioned_specification(reference_spans[0])
    spans = []
    for _, _, row, pieces in resolved:
        if _positioned_specification(pieces[0]) != specification:
            first, second = sorted((reference_row, row))
            raise ValueError(f"第 {first} 行与第 {second} 行的管道尺寸或材质不同，请分别保存")
        spans.extend(pieces)
    return spans, []


def save_positioned_pipe_spans(inputs, spans, *, scheme, overrides=None, editing=None, editing_group=None):
    """Apply all resolved spans to a candidate before publishing the edited input."""
    spans = tuple(spans)
    if not spans:
        raise ValueError("请填写起点桩号和终点桩号")
    result = inputs
    if editing and (len(spans) != 1 or spans[0].group["group_id"] != editing_group):
        result = save_pipe_segment(result, editing_group, editing=editing, remove=True)
        editing = None
    for span in spans:
        result = save_pipe_segment(result, span.group["group_id"], mode="station", scheme=scheme,
                                   start=span.start, end=span.end, overrides=overrides, editing=editing)
    if result.get(KEY):
        touched = {span.group["group_id"] for span in spans}
        for group in list_special_material_groups(result):
            if group["configured"] and touched.intersection(group.get("source_groups", ())):
                validate_length_material_rows(group, group["rows"])
    return result


def _open_joint_mode(inputs, group, edited, activate_length):
    """Keep the adopted material basis of older projects on the first edit."""
    result = deepcopy(inputs)
    config = _config(result)
    saved = config["groups"].get(group["group_id"])
    if saved is None or saved["mode"] == "station" and not activate_length:
        return result
    if not saved.get("keep_positioned_sections"):
        if saved["mode"] == "length":
            saved["soil_only_ranges"] = [[part["station_start"], part["station_end"]]
                for part in group["parts"] if _special(part)]
        elif saved.get("rows"):
            saved["previous_length_rows"] = saved.pop("rows")
    saved["keep_positioned_sections"] = True
    if edited and edited["mode"] == "station":
        saved["soil_only_ranges"] = [span for span in saved.get("soil_only_ranges", [])
            if span != [edited["start"], edited["end"]]]
    return result


def save_pipe_segment(inputs, group_id, *, mode=None, scheme=None, start=None, end=None,
                      quantity=None, overrides=None, editing=None, remove=False, percent_basis=None):
    group = _group(inputs, group_id)
    if not any(is_special_pipe_object(part) for part in group["parts"]):
        raise ValueError("请选择有压管道、圆管涵或倒虹吸")
    records = segment_records(group)
    old = next((r for r in records if r["key"] == editing), None)
    if editing is not None and old is None:
        raise ValueError("这条特殊段已更新，请从清单重新选择")
    if remove and old is None:
        raise ValueError("请选择要移除的特殊段")
    if not remove and mode not in {"station", "length", "ratio"}:
        raise ValueError("请选择桩号、总长度或比例")
    if not remove and mode == "station" and group.get("source_groups"):
        raise ValueError("请按起止桩号选择明挖施工范围")
    if not remove and (not scheme or not is_segment_scheme(group, scheme)):
        raise ValueError("请选择当前可用的特殊施工做法")
    identity = dict(route_id=group["route_id"], asset_id=group["asset_id"])
    unlocated = not remove and mode in {"length", "ratio"}
    result = _open_joint_mode(inputs, group, old, unlocated)
    if old and old["mode"] == "station":
        result = restore_default_section_range(result, **identity,
            station_start=old["start"], station_end=old["end"])
    if not remove and mode == "station":
        positioned_length(group, start, end)
        owner = next((network for network in inputs.get("networks", [inputs])
                      if _route(network) == group["route_id"]), None)
        if owner is not None and trenchless_intersections(trenchless_exclusions(inputs), owner, float(start), float(end)):
            raise ValueError("所选范围包含定向钻或顶管，请按明挖区段设置")
        _validate_positioned_overlap(records, start, end, editing)
        result = apply_section_scheme(result, **identity, scheme=scheme, station_start=start,
                                      station_end=end, overrides=overrides)
    rows = [deepcopy(row) for row in group["rows"] if row["record_id"] != editing] if group["mode"] == "length" else []
    if unlocated:
        row = {"scheme_id": scheme["scheme_id"], "scheme_snapshot": scheme, "overrides": overrides or {}}
        if old and old["mode"] != "station":
            row["record_id"] = editing
        if mode == "ratio":
            row.update(object_percent=_number(quantity, "特殊段占比", positive=True), length_source="按当前对象整条管轴的比例折算")
            basis = percent_basis if percent_basis is not None else (old or {}).get("percent_basis")
            if basis is not None:
                row["percent_basis"] = basis
        else:
            row["length_m"] = _number(quantity, "特殊长度", positive=True)
        rows.append(row)
    if unlocated or old and old["mode"] != "station":
        result = apply_length_materials(result, group_id, rows, keep_positioned=True)
        result[KEY]["groups"][group_id]["keep_positioned_sections"] = True
    saved = (result.get(KEY) or {}).get("groups", {}).get(group_id)
    if saved and saved.get("mode") == "length":
        # Saving a located section also changes the residual space available
        # for unlocated allowances. Validate both before publishing the copy.
        current = _group(result, group_id)
        validate_length_material_rows(current, current["rows"])
    return result
