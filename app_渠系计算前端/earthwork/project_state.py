# -*- coding: utf-8 -*-
"""挖填工程数据的纯数据校验，不导入 Qt 或连接 Rhino。"""

from __future__ import annotations

import copy
import math
from typing import Any


def source_channel_name(water_panel: dict[str, Any]) -> str:
    settings = water_panel.get("project_settings") or {}
    ui_settings = water_panel.get("ui_settings") or {}
    batch = water_panel.get("batch_panel_compat") or {}
    name = str(settings.get("渠道名称") or settings.get("channel_name") or ui_settings.get("channel_name")
               or batch.get("channel_name") or settings.get("project_name") or "").strip()
    level = str(settings.get("渠道级别") or settings.get("channel_level") or ui_settings.get("channel_level")
                or batch.get("channel_level") or "").strip()
    return name + level if name and level and not name.endswith(level) else name


def _same_automatic_pressure_draft(saved, reference):
    derived_fields = {"missing_fields", "source_missing_fields", "parameter_sources",
                      "pipe_construction_default_source_values"}
    if {key: value for key, value in saved.items() if key != "assets"} != {
            key: value for key, value in reference.items() if key != "assets"}:
        return False
    asset, = saved["assets"]
    original, = reference["assets"]
    sources = original.get("parameter_sources") or {}
    return (all(sources.get(key) == value for key, value in (asset.get("parameter_sources") or {}).items())
            and {key: value for key, value in asset.items() if key not in derived_fields}
            == {key: value for key, value in original.items() if key not in derived_fields})


def _references_pressure_draft(value, identifiers):
    if isinstance(value, str):
        return any(identifier in value for identifier in identifiers)
    if isinstance(value, dict):
        return any(_references_pressure_draft(key, identifiers) or _references_pressure_draft(item, identifiers)
                   for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_references_pressure_draft(item, identifiers) for item in value)
    return False


def remove_duplicate_pressure_profile_drafts(project, water):
    """Remove untouched legacy route-only drafts from the editable input snapshot."""
    earthwork = project.get("earthwork_panel") or {}
    inputs = earthwork.get("workbench_inputs") or {}
    networks = inputs.get("networks") or []
    ui = earthwork.get("ui_state") or {}
    if (earthwork.get("kind") != "section_workbench" or earthwork.get("last_result") is not None
            or not earthwork.get("source_project_hash") or not water.get("calculated_nodes")
            or water.get("water_result_current") is False
            or (water.get("merged_section") or {}).get("sync_ready") is False):
        return

    drafts = [network for network in networks if not network.get("alignment")
              and (network.get("source") or {}).get("kind") == "pressure_pipe_manager_data"
              and len(network.get("assets") or []) == 1]
    if not drafts or not any((network.get("source") or {}).get("kind") == "water_profile_panel"
                             and network.get("alignment") for network in networks):
        return
    workspace = ui.get("section_workspace") or {}
    if not isinstance(workspace, dict):
        return
    editor = workspace.get("editor") or {}
    if not isinstance(editor, dict) or editor.get("pending_draft"):
        return

    from 土石方计算.adapters.workbench_sources import (
        _hydraulic_original_ip_points, _pressure_profile_only_route_keys,
        import_plan_alignment, import_workbench_project,
    )
    from 土石方计算.services.construction_defaults import apply_assumed_construction
    from 土石方计算.services.workbench_identity import source_project_hash

    if earthwork["source_project_hash"] != source_project_hash(project):
        return
    nodes = water["calculated_nodes"]
    try:
        import_plan_alignment(water, fallback_points=_hydraulic_original_ip_points(water, nodes))
        profile_keys = _pressure_profile_only_route_keys(project, water, nodes)
        routes = (project.get("pressure_pipe_manager_data") or {}).get("routes") or {}
        selected_routes = {network["source"]["route_key"]: routes[network["source"]["route_key"]]
                           for network in drafts if network["source"].get("route_key") in profile_keys}
        if not selected_routes:
            return
        reference = import_workbench_project({"pressure_pipe_manager_data": {"routes": selected_routes}})
        assumed = copy.deepcopy(reference)
        apply_assumed_construction(assumed)
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
        return

    references = {network["source"]["route_key"]: (network, default) for network, default in
                  zip(reference["networks"], assumed["networks"])}
    for network in drafts:
        route_key = network["source"].get("route_key")
        if not any(_same_automatic_pressure_draft(network, candidate)
                   for candidate in references.get(route_key, ()) if len(candidate["assets"]) == 1):
            continue
        asset_id = network["assets"][0]["asset_id"]
        source_identity = network["assets"][0]["source_identity"]
        identifiers = (asset_id, source_identity, network["network_id"], network["source_identity"])
        remaining = [item for item in inputs["networks"] if item is not network]
        related_rows = {"diagnostics", "construction_assumptions"}
        associated_data = {key: value for key, value in inputs.items() if key not in related_rows | {"networks"}}
        if _references_pressure_draft((remaining, associated_data, ui.get("connection_draft"),
                                       ui.get("pipe_general_drafts"), ui.get("pipe_special_drafts"),
                                       ui.get("pipe_profile_drafts")), identifiers):
            continue
        inputs["networks"] = remaining
        alignment_message = f"{route_key}：缺少至少两个真实平面点"
        inputs["diagnostics"] = [row for row in inputs.get("diagnostics", [])
                                 if row.get("asset_id") != asset_id and row.get("source_identity") != source_identity
                                 and not (row.get("code") == "invalid_plan_alignment"
                                          and row.get("message") == alignment_message)]
        if "construction_assumptions" in inputs:
            inputs["construction_assumptions"] = [row for row in inputs["construction_assumptions"]
                                                  if row.get("asset_id") != asset_id]
        for key in ("section_workspace", "query_view", "pipe_construction_object", "workbench_object"):
            if _references_pressure_draft(ui.get(key), identifiers):
                ui[key] = None


def validate_independent_modes(data: dict[str, Any]) -> None:
    """Validate new explicit selectors before touching an existing project."""
    if "section_source" in data and data["section_source"] not in ("manual", "asset"):
        raise ValueError("未知计算断面来源")
    for key in ("use_linear_grades", "use_site_grades"):
        if key in data and not isinstance(data[key], bool):
            raise ValueError("分级边坡启用状态必须为布尔值")


def normalize_earthwork_payload(payload: dict[str, Any], *, copy_input: bool = True) -> dict[str, Any]:
    """在工程恢复前校验，旧原型仅保留为未验证历史数据。"""
    if not isinstance(payload, dict):
        raise ValueError("挖填工程量数据必须是对象")
    data = copy.deepcopy(payload) if copy_input else payload
    if not data:
        return data
    version = data.get("schema_version")
    if version is None:
        return {
            "schema_version": "1.0",
            "legacy_payload": data,
            "migration_status": "legacy_unverified",
            "assets": [],
            "last_result": None,
        }
    if version != "1.0":
        raise ValueError(f"挖填数据版本 {version!r} 不受支持，请使用兼容版本打开")
    if data.get("kind")=="section_workbench":
        if not isinstance(data.get("project_id"),str) or not data["project_id"]:
            raise ValueError("断面工作台工程必须具有稳定工程身份")
        inputs=data.get("workbench_inputs",data.get("inputs"))
        if not isinstance(inputs,dict):raise ValueError("断面工作台 inputs 必须为对象")
        for key in ("networks","pits","excluded","diagnostics"):
            values=inputs.get(key,[])
            if not isinstance(values,list) or any(not isinstance(v,dict) for v in values):
                raise ValueError(f"断面工作台 {key} 必须为对象列表")
        identifiers=[asset.get("asset_id") for network in inputs.get("networks",[]) for asset in network.get("assets",[])]+[pit.get("asset_id",pit.get("pit_id")) for pit in inputs.get("pits",[])]
        if any(not value for value in identifiers) or len(set(identifiers))!=len(identifiers):
            raise ValueError("断面工作台对象身份必须完整且唯一")
        if "valid_result" in data and not isinstance(data["valid_result"],bool):
            raise ValueError("断面工作台成果有效状态必须为布尔值")
    independent = data.get("independent")
    network = data.get("network")
    if network is not None and (not isinstance(network, dict) or network.get("schema_version", "1.0") != "1.0"):
        raise ValueError("全线算量工程格式不受支持")
    if independent is not None and (not isinstance(independent, dict) or independent.get("schema_version", "1.0") != "1.0"):
        raise ValueError("独立算量工程格式不受支持")
    if independent is not None:
        validate_independent_modes(independent)
    for key in ("coordinate_reference", "terrain", "settings", "last_result", "ui_state"):
        if data.get(key) is not None and not isinstance(data[key], dict):
            raise ValueError(f"挖填数据 {key} 必须是对象或空值")
    assets = data.get("assets", [])
    if not isinstance(assets, list) or any(not isinstance(item, dict) for item in assets):
        raise ValueError("挖填数据 assets 必须是由对象组成的列表")
    asset_ids = [item.get("asset_id") for item in assets if item.get("asset_id")]
    if len(set(asset_ids)) != len(asset_ids):
        raise ValueError("挖填建筑物标识重复，不能确定模型与数量的归属")

    def non_finite_path(value: Any) -> str | None:
        if isinstance(value, float) and not math.isfinite(value):
            return ""
        if isinstance(value, dict):
            for key, child in value.items():
                suffix = non_finite_path(child)
                if suffix is not None:
                    return f".{key}{suffix}"
        elif isinstance(value, list):
            for index, child in enumerate(value):
                suffix = non_finite_path(child)
                if suffix is not None:
                    return f"[{index}]{suffix}"
        return None

    from 土石方计算.services.construction_rules import normalize_construction_inputs
    migrations = normalize_construction_inputs(data)
    if migrations:
        data["valid_result"] = False
        data["construction_rule_migrations"] = [*data.get("construction_rule_migrations", []), *migrations]
        reasons = []
        if any(item.get("code") == "u_channel_no_bedding_v1" for item in migrations):
            reasons.append("U形明渠已取消垫层，结构底板及底弧衬砌保留")
        if any(item.get("code") == "circular_culvert_restore_terrain_v1" for item in migrations):
            reasons.append("圆管涵（明渠-圆形）已按回填至原地面修正")
        data["stale_result_reason"] = "；".join(reasons) + "，请重新计算"
    bad_path = non_finite_path(data)
    if bad_path is not None:
        raise ValueError(f"挖填数据 earthwork_panel{bad_path} 含非有限数值")
    return data
