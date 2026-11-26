"""Actual terrain identity for new workbench snapshots; legacy hashes stay intact."""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import struct
import numpy as np

COMPUTATION_CONTRACT="workbench_engineering_sections_4.12_automatic_unsupported_ranges"
_PREVIOUS_CONTRACT="workbench_engineering_sections_4.11_trenchless_bore"
_CURRENT_COMPATIBLE_CONTRACTS={COMPUTATION_CONTRACT,_PREVIOUS_CONTRACT,
    "workbench_engineering_sections_4.10_special_pipe_material_lengths"}
ENCASEMENT_SIDE_POLICY = "explicit_left_and_right_encasement_v1"


def measured_encasement_has_left_override(source, sections):
    """Only measured sections with a conflicting old common side value changed."""
    def changed(asset):
        c = asset.get("construction") or {}
        enclosure = c.get("encasement") or c.get("pipe_encasement") or {}
        if not enclosure.get("enabled", True):
            return False
        left, common = enclosure.get("left_thickness"), enclosure.get("side_thickness")
        if left is None or common is None:
            return False
        try:
            return float(left) != float(common)
        except (TypeError, ValueError):
            return True

    conflicts = set()
    has_variants = False
    for index, network in enumerate(source.get("networks", []), 1):
        route = str(network.get("route_id", network.get("network_id", network.get("name", f"route-{index}"))))
        for asset in network.get("assets", []):
            if asset.get("enabled", True):
                if changed(asset):
                    conflicts.add((route, asset.get("asset_id")))
                if asset.get("section_scheme_terrain_variants") or asset.get("section_scheme_selectors"):
                    has_variants = True
    if not conflicts and not has_variants:
        return False
    return any(changed(section["effective_asset"]) if section.get("effective_asset") else
               (str(section.get("route_id")), section.get("original_asset_id") or section.get("asset_id")) in conflicts
               for section in sections)


def _uses_bedding_slope_closure(asset):
    construction=asset.get("construction") or {}
    seat=construction.get("pipe_seat") or construction.get("pipe_support") or {}
    return (construction.get("installation_mode","buried") not in {"exposed","elevated","open","above_ground"}
            and seat.get("enabled",True) and seat.get("material_role","concrete")=="bedding"
            and seat.get("bottom_width_mode")=="trench_bottom"
            and seat.get("side_boundary_mode","excavation")=="excavation")


def result_contract_is_current(payload):
    """Keep unaffected saved results without relabelling their contract/hash.

    Old full-width bedding omitted the two wedges at the excavation slopes.
    Those snapshots remain historical until the user elects to recalculate.
    The pre-existing 4.4 trenchless-scope compatibility guard still applies.
    """
    snapshot=payload.get("inputs") or {}
    from ..io.quantity_policy import uses_independent_sections
    if not uses_independent_sections(payload):
        return False
    recorded=payload.get("calculation_contract")
    if recorded!=snapshot.get("calculation_contract"):
        return False
    source=snapshot.get("workbench") or {}
    from .sluice_gate import gate_quantities_match_snapshot
    if not gate_quantities_match_snapshot(payload, source):
        return False
    if (snapshot.get("encasement_side_policy") != ENCASEMENT_SIDE_POLICY
            and measured_encasement_has_left_override(source, payload.get("sections") or ())):
        return False
    from .tunnel_exposure_scope import TUNNEL_EXPOSED_FIELD, restore_tunnel_exposure, tunnel_scope_matches_snapshot
    exclusions = payload.get("excluded_assets") or []
    has_tunnel_scope = (TUNNEL_EXPOSED_FIELD in source or TUNNEL_EXPOSED_FIELD in payload
                        or any(row.get("code") == "tunnel_exposed" for row in exclusions))
    if has_tunnel_scope:
        if not tunnel_scope_matches_snapshot(payload, source):
            return False
        try:
            range_source = restore_tunnel_exposure(source)
        except (KeyError, TypeError, ValueError):
            return False
    else:
        range_source = source
    from .unsupported_pipe_scope import (AUTOMATIC_UNSUPPORTED_PIPE_FIELD,
        AUTOMATIC_UNSUPPORTED_PIPE_CODE,automatic_scope_matches_snapshot)
    automatic=(AUTOMATIC_UNSUPPORTED_PIPE_FIELD in range_source or AUTOMATIC_UNSUPPORTED_PIPE_FIELD in payload
        or any(row.get("code")==AUTOMATIC_UNSUPPORTED_PIPE_CODE for row in exclusions))
    if automatic and not automatic_scope_matches_snapshot(payload,range_source):
        return False
    from .unmeasured_terrain_scope import (AUTOMATIC_TERRAIN_GAP_FIELD,
        AUTOMATIC_TERRAIN_GAP_CODE, terrain_gap_scope_matches_snapshot)
    has_terrain_gaps = (AUTOMATIC_TERRAIN_GAP_FIELD in range_source or AUTOMATIC_TERRAIN_GAP_FIELD in payload
        or any(row.get("code")==AUTOMATIC_TERRAIN_GAP_CODE for row in exclusions))
    if has_terrain_gaps and not terrain_gap_scope_matches_snapshot(payload,range_source):
        return False
    if ((automatic or has_tunnel_scope or has_terrain_gaps)
            and (snapshot.get("terrain_choice") or {}).get("kind") == "not_required_for_trenchless_only"):
        return False
    from .workbench_scope import deferred_scope_matches_snapshot
    if not deferred_scope_matches_snapshot(payload,source):
        return False
    from .earthwork_scope import (LEGACY_TRENCHLESS_EXCAVATION_RULE, NOMINAL_TRENCHLESS_EXCAVATION_RULE,
                                  trenchless_exclusions, trenchless_excavation_quantities)
    has_bores = (payload.get("trenchless_excavation_rows") or trenchless_exclusions(source)
                 or trenchless_exclusions({"networks": [], "excluded":exclusions}))
    if has_bores:
        if recorded not in {COMPUTATION_CONTRACT, _PREVIOUS_CONTRACT}:
            return False
        policy = payload.get("trenchless_excavation_policy")
        open_cut_volume = payload.get("excavation_volume", 0.)
        bore = trenchless_excavation_quantities(exclusions, open_cut_volume, policy=policy)
        if not bore or any(payload.get(key) != value for key, value in bore.items()):
            return False
        if policy == LEGACY_TRENCHLESS_EXCAVATION_RULE:
            nominal = trenchless_excavation_quantities(exclusions, open_cut_volume,
                                                      policy=NOMINAL_TRENCHLESS_EXCAVATION_RULE)
            if nominal != {**bore, "trenchless_excavation_policy": NOMINAL_TRENCHLESS_EXCAVATION_RULE}:
                return False
    from .tunnel_source_parameters import uses_explicit_tunnel_base,TUNNEL_LINING_GEOMETRY_POLICY
    if uses_explicit_tunnel_base(source):
        if (payload.get("tunnel_lining_geometry_policy")!=TUNNEL_LINING_GEOMETRY_POLICY
                or snapshot.get("tunnel_lining_geometry_policy")!=TUNNEL_LINING_GEOMETRY_POLICY):
            return False
    if recorded in _CURRENT_COMPATIBLE_CONTRACTS:
        # A saved length schedule must have passed the material-only boundary;
        # adding its input records to an older uncorrected quantity table is
        # not a valid recalculation. Soil geometry remains independently saved.
        if source.get("special_pipe_materials"):
            from .section_scheme_bindings import _digest
            try:
                return (payload.get("special_pipe_materials_policy")=="special_pipe_materials_1.0"
                    and payload.get("special_pipe_materials_input_hash")==_digest(source["special_pipe_materials"]))
            except (ValueError,TypeError):
                return False
        return True
    if source.get("special_pipe_materials"):
        return False
    # General buried defaults change only previously unassigned pipe sections.
    # Historical quantities, input hashes and contract labels stay untouched.
    from .default_section_schemes import pending_default_section_assets
    if pending_default_section_assets(source):
        return False
    if recorded=="workbench_engineering_sections_4.9_general_buried_defaults":
        return True
    if recorded=="workbench_engineering_sections_4.8_support_dn_aqueduct_frames":
        return True
    # Preserve unaffected 4.7 results under their original contract and hash.
    # New schedules, DN envelopes and terrain-generated frames need a new run.
    if recorded=="workbench_engineering_sections_4.7_section_scheme_terrain_variants":
        source=snapshot.get("workbench") or {}
        assets=[a for n in source.get("networks",[]) for a in n.get("assets",[])]+list(source.get("pits",[]))
        return (bool(assets) and (snapshot.get("accuracy") or {}).get("overlap_policy")=="independent_sections"
            and not source.get("slope_support_rows") and not source.get("slope_support_templates")
            and not any((a.get("section") or {}).get("aqueduct_frame_layout")
                or (a.get("section") or {}).get("nominal_diameter_m")
                or any(p.get("nominal_diameter_m") for p in (a.get("section") or {}).get("pipes",[])) for a in assets))
    if (recorded not in {"workbench_engineering_sections_4.6_pipe_bedding_slope_closure",
                        "workbench_engineering_sections_4.5_trenchless_excluded",
                        "workbench_engineering_sections_4.4_independent_sections"}
            or (snapshot.get("accuracy") or {}).get("overlap_policy")!="independent_sections"):
        return False
    source=snapshot.get("workbench") or {}
    assets=[a for n in source.get("networks",[]) for a in n.get("assets",[])]+list(source.get("pits",[]))
    if not assets:
        return False
    if source.get("section_scheme_bindings") or any(a.get("section_scheme_binding") for a in assets):
        return False
    for asset in assets:
        c=asset.get("construction") or {};s=asset.get("section") or {}
        if (c.get("foundation_replacement") or c.get("foundation_replacement_thickness")
                or c.get("bedding_reference") or s.get("retaining_wall_profile")
                or s.get("foundation_replacement_profile") or s.get("gabion_profile")
                or s.get("rockfill_profile") or c.get("floor_steps")):
            return False
    if recorded=="workbench_engineering_sections_4.6_pipe_bedding_slope_closure":
        return True
    if any(_uses_bedding_slope_closure(a) for a in assets):
        return False
    if recorded=="workbench_engineering_sections_4.5_trenchless_excluded":
        return True
    from .earthwork_scope import trenchless_method, TRENCHLESS_EXCLUSION_RULE
    if any(trenchless_method(a) is not None for a in assets):
        return False
    exclusions=[*source.get("excluded",[]),*payload.get("excluded_assets",[])]
    return not any(e.get("code")==TRENCHLESS_EXCLUSION_RULE
                   or trenchless_method(e.get("original_asset_snapshot") or e) is not None
                   for e in exclusions)


_SOURCE_PRESENTATION_FIELDS=frozenset({
    "profile_row_id", "pressure_pipe_row_identity", "row_id", "ui_settings", "table_state", "node_table_rows",
    "node_numeric_display_values", "extra_caches", "detail_report_text", "detail_text_cache",
    "last_modified", "last_run_at", "created_at", "updated_at", "calculated_at",
    "radius_applied_at", "settings_collapsed", "transition_settings_collapsed",
    "first_success_auto_jump_done", "length_rule_nudge_seen",
})


def _source_design_value(value):
    """Discard saved presentation identity without rounding any design number."""
    if isinstance(value,dict):
        return {key:_source_design_value(item) for key,item in value.items()
                if key not in _SOURCE_PRESENTATION_FIELDS}
    if isinstance(value,(list,tuple)):
        return [_source_design_value(item) for item in value]
    return value


def source_project_hash(snapshot):
    """Fingerprint the source design consumed by the workbench, independent of UI.

    Project loading writes the water-panel compatibility alias, fills empty
    managers, rebuilds display caches, and assigns IDs to auxiliary nodes. None
    changes the design. Prefer calculated nodes just as the source adapter does;
    retain original batch IP inputs and readiness so edited, stale design data
    still invalidates a previously imported workbench.
    """
    snapshot=snapshot or {}
    panels=[snapshot.get("merged_panel") or {},snapshot.get("water_profile_panel") or {}]
    panel=next((p for p in panels if p.get("calculated_nodes") or p.get("nodes")),panels[0] or panels[1])
    calculated=panel.get("calculated_nodes") or []
    section=panel.get("merged_section") or {}
    batch = panel.get("batch_panel_compat") or {}
    if not batch.get("input_rows"):
        batch = snapshot.get("batch_panel") or {}
    batch_rows = batch.get("input_rows") or []
    value={
        "schema":"workbench_source_design_1.0",
        "project_settings":_source_design_value(panel.get("project_settings") or {}),
        "nodes":_source_design_value(calculated or panel.get("nodes") or []),
        "calculated":bool(calculated),
        "sync_ready":bool(section.get("sync_ready",bool(calculated))),
        "original_ip_rows":_source_design_value(batch_rows),
    }
    if batch_rows and (headers := batch.get("input_header_order")):
        from app_渠系计算前端.batch.schema import INPUT_HEADERS
        if list(headers) != INPUT_HEADERS:
            value["original_ip_headers"] = list(headers)
    library=(panel.get("extra_caches") or {}).get("custom_rock_lining") or {}
    source_nodes=calculated or panel.get("nodes") or []
    has_tunnel=any(isinstance(node,dict) and any(token in str(node.get("structure_type") or
        node.get("section_type") or "").lower() for token in ("隧洞","tunnel")) for node in source_nodes)
    if library and has_tunnel:
        value["tunnel_lining_library"]=_source_design_value(library)
    saved_lining = (panel.get("extra_caches") or {}).get("custom_struct_thickness")
    if saved_lining:
        from 推求水面线.shared.section_lining import SECTION_SUMMARY_LINING_TYPES, gate_reference_lining

        types = {str(node.get("structure_type") or "") for node in source_nodes
                 if isinstance(node, dict) and not node.get("is_transition")}
        section_kinds = {SECTION_SUMMARY_LINING_TYPES[kind] for kind in types if kind in SECTION_SUMMARY_LINING_TYPES}
        if any(kind.strip().endswith("闸") for kind in types):
            section_kinds.add("rect_channel")
        lining = {kind: saved for kind in section_kinds
                  if (saved := gate_reference_lining(kind, saved_lining)) != gate_reference_lining(kind)}
        if lining:
            value["water_profile_lining"] = lining
    for name,buckets in (("siphon_manager_data",("siphons",)),
                         ("pressure_pipe_manager_data",("pipes","routes","segments"))):
        manager=snapshot.get(name) or {}
        value[name]={key:_source_design_value(manager.get(key) or {}) for key in buckets}
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,default=str,
                                     separators=(",",":")).encode("utf8")).hexdigest()


def terrain_choice(tin,report=None):
    report=getattr(tin,"import_report",{}) if report is None else report
    mesh=hashlib.sha256()
    for array,dtype in ((tin.points,"<f8"),(tin.triangles,"<i8")):
        array=np.asarray(array)
        for start in range(0,len(array),100_000):
            mesh.update(np.ascontiguousarray(array[start:start+100_000],dtype=dtype).tobytes())
    constraints=hashlib.sha256();edges=getattr(tin,"constraint_edges",[]) or []
    for edge in edges:
        i,j=(edge.i,edge.j) if hasattr(edge,"i") else edge[:2]
        constraints.update(struct.pack("<qq",int(i),int(j)))
    path=report.get("path")
    return {"schema":"workbench_terrain_choice_1.0","terrain_mode":report.get("terrain_mode") or "existing_mesh",
            "actual_mesh_sha256":mesh.hexdigest(),"vertex_count":len(tin.points),"face_count":len(tin.triangles),
            "actual_constraint_sha256":constraints.hexdigest(),"constraint_count":len(edges),
            "processing_options":deepcopy(report.get("terrain_options") or {}),
            "topology":report.get("topology"),"loaded_source_sha256":report.get("source_sha256"),
            "cache_file_sha256":report.get("source_sha256") if path and Path(path).suffix.lower()==".npz" else None,
            "original_source":deepcopy(report.get("original_source") or {}),"units":report.get("units","m")}
