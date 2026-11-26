"""Replay local measurement choices and explicit construction on fresh imports."""
from copy import deepcopy
import math

from .drawing_bindings import _slice


def _key(network, asset):
    route = network.get("source_identity") or network.get("route_id") or network.get("network_id")
    source = (asset.get("source_identity") or asset.get("drawing_root_asset_id")
              or asset.get("section_scheme_root_asset_id") or asset.get("parent_asset_id") or asset.get("asset_id"))
    return str(route or ""), str(source or ""), asset.get("kind"), asset.get("section_type")


def _range(asset):
    try:
        start, end = float(asset["station_start"]), float(asset["station_end"])
    except (ValueError, TypeError, KeyError):
        return None
    return (start, end) if math.isfinite(start) and math.isfinite(end) and end > start else None


def _value(asset, path):
    value = asset
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            return False, None
        value = value[key]
    return True, value


def _leaves(path, value):
    if isinstance(value, dict):
        return [(nested, item) for key, child in value.items()
                for nested, item in _leaves(path + "." + key, child)]
    return [(path, value)]


def _construction_choices(asset):
    sources = asset.get("parameter_sources") or {}
    paths = set(asset.get("drawing_user_overrides") or {})
    paths.update(path for path, source in sources.items() if str(source).startswith("用户"))
    selected = {}
    for path in sorted(paths):
        if not path.startswith("construction."):
            continue
        present, value = _value(asset, path)
        if present:
            selected.update(_leaves(path, value))
    return selected


def _tunnel_selection(asset):
    if asset.get("kind") != "tunnel":
        return None
    mode=asset.get("tunnel_lining_selection_mode")
    section=asset.get("section") or {}
    if mode == "source_library":
        selected={"rock_class":section.get("rock_class")}
    elif mode == "manual":
        selected={key:deepcopy(section[key]) for key in ("base_thickness","lining_thickness") if key in section}
    else:
        return None
    for key in ("shotcrete_thickness","shotcrete_grade"):
        path="section."+key
        if key in section and (path in (asset.get("drawing_user_overrides") or {})
                or str((asset.get("parameter_sources") or {}).get(path,"")).startswith("用户")):
            selected[key]=deepcopy(section[key])
    return {"section":selected,"tunnel_lining_selection_mode":mode}


def _apply_choices(target, choices):
    priority = target.get("source_tunnel_parameter_paths") or []
    applied, skipped = [], []
    for path, value in choices.items():
        if any(path == p or path.startswith(p + ".") for p in priority):
            skipped.append(path)
            continue
        current = target
        keys = path.split(".")
        for key in keys[:-1]:
            current = current.setdefault(key, {})
        current[keys[-1]] = deepcopy(value)
        target.setdefault("drawing_user_overrides", {})[path] = deepcopy(value)
        target.setdefault("parameter_sources", {})[path] = "用户覆盖：重读保留已填写的分段施工参数"
        applied.append(path)
    if applied:
        target.update(parameter_source="user_confirmed", workbench_geometry=True)
    return applied, skipped


def replay_calculation_selection(new_inputs, previous_inputs):
    """Return a copy, split only fresh profiles, and retain supported old choices.

    The host first establishes source-project identity. New ranges without an
    intersecting historical choice retain their current inclusion and defaults.
    """
    result = deepcopy(new_inputs)
    report = {"replayed": [], "warnings": [], "source_fields_preferred": []}
    history = {}
    for network in previous_inputs.get("networks", []):
        for asset in network.get("assets", []):
            span = _range(asset)
            if span is None or asset.get("transition_candidate_id"):
                continue
            history.setdefault(_key(network, asset), []).append({
                "station_start": span[0], "station_end": span[1], "enabled": asset.get("enabled", True),
                "asset_id": asset["asset_id"], "name": asset.get("name"),
                "construction": _construction_choices(asset), "tunnel_selection":_tunnel_selection(asset)})
    matched = set()
    for network in result.get("networks", []):
        for original in list(network.get("assets", [])):
            span = _range(original)
            if span is None or original.get("transition_candidate_id"):
                continue
            key = _key(network, original)
            prior = history.get(key) or []
            if not prior:
                continue
            matched.add(key)
            start, end = span
            cuts = sorted({start, end, *(max(start, min(end, row[field]))
                for row in prior for field in ("station_start", "station_end"))})
            for a, b in zip(cuts, cuts[1:]):
                if b <= a + 1e-7:
                    continue
                owners = [row for row in prior
                          if row["station_start"] <= a + 1e-7 and row["station_end"] >= b - 1e-7]
                if not owners:
                    continue
                flags = {row["enabled"] for row in owners}
                choices = {}
                conflict = len(flags) != 1
                tunnel_choices=[owner["tunnel_selection"] for owner in owners if owner["tunnel_selection"]]
                if tunnel_choices and any(value!=tunnel_choices[0] for value in tunnel_choices[1:]):
                    conflict=True
                for owner in owners:
                    for path, value in owner["construction"].items():
                        if path in choices and choices[path] != value:
                            conflict = True
                        choices[path] = value
                if conflict:
                    report["warnings"].append({"asset_id": original["asset_id"], "station_start": a,
                        "station_end": b, "message": "原分段计量或施工选择存在冲突，当前范围保留本次来源设置"})
                    continue
                current = next(asset for asset in network["assets"]
                    if _key(network, asset) == key and asset["station_start"] <= a + 1e-7
                    and asset["station_end"] >= b - 1e-7)
                target = _slice(network, current, a, b)
                target["enabled"] = next(iter(flags))
                if tunnel_choices:
                    from .tunnel_source_parameters import refresh_tunnel_source_parameters
                    previous=tunnel_choices[0]
                    refresh_tunnel_source_parameters(target,previous)
                    for field in ("shotcrete_thickness","shotcrete_grade"):
                        path="section."+field
                        if field in previous["section"] and path not in target.get("source_tunnel_parameter_paths",[]):
                            value=deepcopy(previous["section"][field])
                            target.setdefault("section",{})[field]=value
                            target.setdefault("drawing_user_overrides",{})[path]=deepcopy(value)
                            target.setdefault("parameter_sources",{})[path]="用户覆盖：重读保留已填写的隧洞喷护参数"
                    if (target.get("source_tunnel_lining_selection_required")
                            and previous["tunnel_lining_selection_mode"]=="source_library"):
                        rock=previous["section"].get("rock_class") or "原选类别"
                        report["warnings"].append({"asset_id":target["asset_id"],"station_start":a,"station_end":b,
                            "code":"tunnel_lining_selection_pending", "message":
                            f"{target.get('name') or target['asset_id']} K{a:.3f}～{b:.3f}：当前水面线已无{rock}衬砌方案，请重新选择围岩方案或明确填写实际厚度"})
                applied, skipped = _apply_choices(target, choices)
                report["replayed"].append({"asset_id": target["asset_id"], "station_start": a,
                    "station_end": b, "enabled": target["enabled"], "construction_fields": applied})
                if skipped:
                    report["source_fields_preferred"].append({"asset_id": target["asset_id"],
                        "station_start": a, "station_end": b, "fields": skipped})
    for key, rows in history.items():
        if key not in matched:
            report["warnings"].append({"asset_id": rows[0]["asset_id"],
                "message": f"{rows[0].get('name') or rows[0]['asset_id']}：来源对象已变化，原计量/施工选择未移到其他对象",
                "previous_choices": deepcopy(rows)})
    result["unmatched_calculation_selection"] = deepcopy(report["warnings"])
    return result, report
