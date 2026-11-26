"""Apply selected construction fields to explicitly selected buried-pipe objects."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy

from .earthwork_scope import trenchless_method
from .pipe_special_segments import is_special_pipe_object
from .section_scheme_bindings import _digest, _get, _root, _route, _set
from .special_pipe_materials import KEY, _number, _positioned_material, _special, list_special_material_groups


BATCH_FIELDS = {
    "working_space": ("单侧施工工作面宽度（左右各，m）",
                      ("construction.working_space_left", "construction.working_space_right")),
    "manual_backfill_height": ("人工夯实至管顶以上（m）",
                               ("construction.backfill_partition.above_crown_height_m",)),
}


def pipe_batch_objects(inputs):
    objects = {}
    for network in inputs.get("networks", []):
        for part in network.get("assets", []):
            if (not is_special_pipe_object(part) or not part.get("enabled", True)
                    or part.get("pipe_profile_choice")=="pending_gap" or trenchless_method(part)
                    or (part.get("construction") or {}).get("installation_mode", "buried") not in {None,"buried"}):
                continue
            key = (_route(network), _root(part))
            if all(key):
                objects.setdefault(key, (network, []))[1].append(part)
    return objects


def _spec_parts(group):
    scopes = group.get("part_scopes") or [(group["route_id"], group["asset_id"], part["asset_id"])
                                          for part in group["parts"]]
    return {(route, root, part["station_start"], part["station_end"])
            for (route, root, _), part in zip(scopes, group["parts"], strict=True)}


def _merged_settings(old_groups, config, target):
    """Keep each former group's adopted material/earthwork mode when pools merge."""
    active = [g for g in old_groups if g["configured"]]
    if len(old_groups)==1:
        return deepcopy(config["groups"][active[0]["group_id"]])
    rows, dormant, soil_only = [], [], []
    for group in active:
        prior = config["groups"][group["group_id"]]
        if group["mode"]=="length":
            rows.extend(deepcopy(group["rows"]))
            soil_only.extend([part["station_start"],part["station_end"]] for part in group["parts"]
                             if _special(part) and not _positioned_material(group,part))
        else:
            dormant.extend(deepcopy(group["rows"]))
        config.setdefault("archived_groups",[]).append({
            "archive_id":"batch-"+_digest([group["group_id"],prior,target["group_id"]])[:20],
            "old_group_id":group["group_id"],"route_id":group["route_id"],"asset_id":group["asset_id"],
            "reason":"统一施工参数后同规格材料合并", "configuration":deepcopy(prior)})
    mode = "length" if any(g["mode"]=="length" for g in active) else "station"
    retained = rows if mode=="length" else dormant
    seen = set()
    for i,row in enumerate(retained):
        if row["record_id"] in seen:
            row["record_id"] = "merged-"+_digest([target["group_id"],i,row])[:20]
        seen.add(row["record_id"])
    return {"mode":mode,"rows":retained,"keep_positioned_sections":True,"soil_only_ranges":soil_only,
            "length_basis":"actual_pipe_axis_length"}


def _rebind_materials(before, result, changed, widths):
    """The general working space is part of a material-pool signature."""
    old_groups = [g for g in list_special_material_groups(before)
                  if any(part[:2] in changed for part in _spec_parts(g))]
    if not any(g["configured"] for g in old_groups):
        return
    new_groups = {g["group_id"]:g for g in list_special_material_groups(result, include_pipe_scopes=True)}
    by_part = {(bool(g.get("source_groups")), part): key for key,g in new_groups.items() for part in _spec_parts(g)}
    mapped = defaultdict(list)
    for group in old_groups:
        scoped = bool(group.get("source_groups"))
        destinations = {by_part.get((scoped, part)) for part in _spec_parts(group)}
        if len(destinations)!=1 or None in destinations:
            raise ValueError("原规格已分成不同材料规格，请分别核对各规格工作面。")
        mapped[destinations.pop()].append(group)
    config = result[KEY]
    replacements = {}
    old_ids = {g["group_id"] for g in old_groups if g["configured"]}
    for key,groups in mapped.items():
        if not any(g["configured"] for g in groups):
            continue
        if key in config["groups"] and key not in old_ids:
            raise ValueError("目标规格有历史材料设置，请先在该对象的特殊施工段页核对。")
        target = new_groups[key]
        saved = _merged_settings(groups,config,target)
        saved.update(route_id=target["route_id"],asset_id=target["asset_id"],
                     specification_sha256=_digest(target["specification"]))
        if saved["mode"]=="length":
            for row in saved.get("rows",[]):
                row.setdefault("overrides",{}).update(widths)
        replacements[key] = saved
    for key in old_ids:
        del config["groups"][key]
    config["groups"].update(replacements)


def apply_pipe_batch_parameters(inputs, selected, values):
    """Return a detached candidate or None for an unchanged selection."""
    if not values:
        return None
    selected = set(selected)
    if not selected:
        raise ValueError("请勾选要应用施工参数的对象。")
    fields = {}
    for key,value in values.items():
        if key not in BATCH_FIELDS:
            raise ValueError("请选择表内的施工参数。")
        label, paths = BATCH_FIELDS[key]
        numeric = _number(value,label)
        fields.update({path:numeric for path in paths})
    result = deepcopy(inputs)
    objects = pipe_batch_objects(result)
    if not selected.issubset(objects):
        raise ValueError("工程对象的埋管范围已变化，请重新选择。")
    changed, width_changed = set(), set()
    for key in selected:
        for part in objects[key][1]:
            for path,value in fields.items():
                if _get(part,path)==value:
                    continue
                _set(part,path,value)
                part.setdefault("drawing_user_overrides",{})[path]=value
                part.setdefault("parameter_sources",{})[path]="用户覆盖：批量施工参数设置"
                changed.add(key)
                if path in BATCH_FIELDS["working_space"][1]:
                    width_changed.add(key)
    if not changed:
        return None
    if result.get(KEY) and width_changed:
        _rebind_materials(inputs,result,width_changed,{p:fields[p] for p in BATCH_FIELDS["working_space"][1]})
    return result
