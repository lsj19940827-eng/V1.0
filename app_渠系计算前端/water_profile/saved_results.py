"""Recognize a table rebuilt by the batch sync without new hydraulic inputs."""


_CALCULATED_NODE_FIELDS = {
    "profile_row_id", "water_level", "head_loss_friction", "head_loss_bend",
    "head_loss_total", "head_loss_cumulative", "pressure_pipe_window_override",
}
_GENERATED_ROW_METADATA = {
    "_profile_row_id", "_numeric_display_values", "_pressure_pipe_window_override",
}
_RADIUS_METADATA = (
    "turn_radius_text", "turn_radius_is_explicit", "turn_radius_source",
    "turn_radius_default_value", "turn_radius_default_diameter",
    "turn_radius_default_diameter_source", "turn_radius_default_multiplier",
)


def has_restorable_water_result(saved):
    return bool(saved.get("calculated_nodes") and saved.get("water_result_current") is not False)


def has_legacy_earthwork_source(saved):
    if not has_restorable_water_result(saved):
        return False
    settings = saved.get("project_settings") or {}
    return (not saved.get("water_result_input_signature") or "channel_name" in settings
            or "管道默认转弯半径倍数n" not in settings
            or any(any(key not in node for key in _RADIUS_METADATA) for node in saved["calculated_nodes"]))


def legacy_water_settings_match(saved_settings, ui_settings, current_settings):
    """Accept only known settings representation changes on project restore."""
    from 推求水面线.models.data_models import ProjectSettings

    if saved_settings == current_settings:
        return True
    expected = dict(saved_settings)
    expected.setdefault("管道默认转弯半径倍数n", ProjectSettings().pipe_turn_radius_n)
    if "channel_name" in expected:
        alias = expected.pop("channel_name")
        saved_name = expected.get("渠道名称", alias)
        ui_name = ui_settings.get("channel_name")
        if isinstance(alias, str) and isinstance(ui_name, str) and alias.strip() == ui_name.strip():
            saved_name = alias.strip()
        expected["渠道名称"] = saved_name
    return expected == current_settings


def _with_legacy_radius_metadata(node):
    if all(key in node for key in _RADIUS_METADATA):
        return node
    from 推求水面线.models.data_models import ChannelNode

    restored_node = ChannelNode.from_project_dict(node)
    return {**{key: getattr(restored_node, key) for key in _RADIUS_METADATA}, **node}


def restored_legacy_earthwork_source_hash(snapshot, live_water):
    """Carry a matching saved source binding forward through lossless restoration."""
    from 土石方计算.services.workbench_identity import source_project_hash

    saved_water = snapshot.get("merged_panel") or snapshot.get("water_profile_panel") or {}
    binding = (snapshot.get("earthwork_panel") or {}).get("source_project_hash")
    if not binding or not has_restorable_water_result(saved_water) or live_water.get("water_result_current") is not True:
        return None
    if binding != source_project_hash(snapshot):
        return None
    current_settings = live_water.get("project_settings") or {}
    if not legacy_water_settings_match(saved_water.get("project_settings") or {},
                                       saved_water.get("ui_settings") or {}, current_settings):
        return None
    expected_water = {
        **saved_water,
        "project_settings": current_settings,
        "calculated_nodes": [_with_legacy_radius_metadata(node) for node in saved_water["calculated_nodes"]],
    }
    restored_hash = source_project_hash({**snapshot, "merged_panel": live_water})
    expected_hash = source_project_hash({**snapshot, "merged_panel": expected_water})
    return restored_hash if restored_hash == expected_hash else None


def _node_inputs(node):
    inputs = {key: value for key, value in node.items() if key not in _CALCULATED_NODE_FIELDS}
    section = inputs.get("section_params")
    if isinstance(section, dict):
        inputs["section_params"] = {key: value for key, value in section.items()
                                   if key != "pressure_pipe_window_override"}
    return inputs


def _row_metadata(row):
    metadata = dict(row.get("cell_data") or {})
    metadata["0"] = {key: value for key, value in (metadata.get("0") or {}).items()
                     if key not in _GENERATED_ROW_METADATA}
    if "隧洞" not in row["cells"][2]:
        metadata["0"].pop("_flat_bottom_tunnel_source_allowed", None)
    return metadata


def _cell_input(row, column):
    text = str(row["cells"][column]).strip()
    if column < 5:
        return text
    if text in {"", "-", "—"}:
        return None
    metadata = (row.get("cell_data") or {}).get("0") or {}
    record = (metadata.get("_numeric_display_values") or {}).get(str(column)) or {}
    if record.get("text") == text and "value" in record:
        return record["value"]
    try:
        return float(text)
    except ValueError:
        return text


def matches_batch_resync(live, saved, editable_columns):
    """Check the saved calculation basis and reject new input after a batch sync."""
    if live.get("calculated_nodes") or not saved.get("calculated_nodes") or saved.get("water_result_current") is not True:
        return False
    signature = saved.get("water_result_input_signature")
    if not signature or live.get("water_result_input_signature") != signature:
        return False
    saved_section = saved.get("merged_section") or {}
    live_section = live.get("merged_section") or {}
    if not (saved_section.get("sync_ready") and live_section.get("sync_ready")
            and saved_section.get("transition_topology_prepared") and not live_section.get("transition_topology_prepared")):
        return False
    if saved_section.get("result_rows") != live_section.get("result_rows"):
        return False
    for key in ("project_settings", "ui_settings", "water_result_settings", "extra_caches", "pressure_pipe_calc_records"):
        if saved.get(key) != live.get(key):
            return False
    batch = saved.get("batch_panel_compat") or {}
    live_batch = live.get("batch_panel_compat") or {}
    if not batch.get("input_rows") or {k: v for k, v in batch.items() if k != "detail_text_cache"} != {
            k: v for k, v in live_batch.items() if k != "detail_text_cache"}:
        return False

    saved_rows = (saved.get("table_state") or {}).get("rows") or []
    live_rows = (live.get("table_state") or {}).get("rows") or []
    saved_nodes, live_nodes = saved.get("nodes") or [], live.get("nodes") or []
    if not (len(saved_rows) == len(live_rows) == len(saved_nodes) == len(live_nodes) > 0):
        return False
    for before, after, saved_node, live_node in zip(saved_rows, live_rows, saved_nodes, live_nodes):
        if (_node_inputs(saved_node) != _node_inputs(live_node) or _row_metadata(before) != _row_metadata(after)
                or before.get("parameters") != after.get("parameters")):
            return False
        for column in editable_columns:
            previous, current = _cell_input(before, column), _cell_input(after, column)
            if previous == current:
                continue
            if current is None and column == 24 and previous == live_node.get("roughness"):
                continue
            override = saved_node.get("pressure_pipe_window_override") or {}
            if current is None and column == 38 and override.get("enabled"):
                continue
            return False
    return True
