"""Save the ordinary one-click deliverables from one calculation snapshot."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import uuid
from filesystem_paths import filesystem_path, resolved_path
from .network_section_calculator import BACKFILL_VOLUME_KEYS


def delivery_directory(root, inputs, *, project_name=""):
    """Use a fresh directory so a repeated run preserves previous deliverables."""
    names = dict.fromkeys(str(n.get("name") or n.get("network_name") or "").strip()
                          for n in inputs.get("networks", []))
    name = str(project_name or "").strip() or "、".join(n for n in names if n) or "土石方算量"
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)[:65].strip(" .") or "土石方算量"
    return resolved_path(root) / (name + "_" + datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:4])


def _delivery_storage_path(directory):
    cache = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    identity = os.path.normcase(str(resolved_path(directory)))
    key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return filesystem_path(cache / "CanalHydraulics" / "earthwork" / "deliveries" / key, extended=True)


def delivery_support_directory(directory):
    """Find the application records, including those in older delivery folders."""
    storage = _delivery_storage_path(directory)
    return filesystem_path(resolved_path(storage if storage.is_dir() else directory))


def delivery_project_path(directory):
    return filesystem_path(delivery_support_directory(directory) / "算量工程.qxproj")


def read_delivery_manifest(directory):
    if not directory:
        return {}
    try:
        if not filesystem_path(directory, extended=True).is_dir():
            return {}
        path = filesystem_path(delivery_support_directory(directory) / "成果清单.json")
        manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    if not isinstance(manifest, dict):
        return {}
    if "delivery_directory" in manifest:
        published_path = manifest["delivery_directory"]
        current_path = os.path.normcase(str(resolved_path(directory)))
        if not isinstance(published_path, str) or os.path.normcase(published_path) != current_path:
            return {}
    return manifest


def delivery_matches_result(directory, input_hash, project_id, *, require_project_id=False):
    if not input_hash:
        return False
    manifest = read_delivery_manifest(directory)
    saved_id = manifest.get("project_id")
    if require_project_id and not saved_id:
        return False
    return (manifest.get("status") in ("READY", "READY_WITH_DRAWING_ISSUES")
            and manifest.get("input_hash") == input_hash
            and (not saved_id or saved_id == project_id))


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_workbench_delivery(payload, directory, *, workbench_state=None,
                            drawing_options=None, project_snapshot=None, cancelled=None, progress=None):
    """Publish Excel and drawings, with recovery and verification in app storage.

    A drawing-specific failure preserves the verified quantities and records
    the drawing for another export.
    """
    from ..io.section_exporter import DrawingExportError, export_section_result
    from ..io.workbench_drawings import section_sampling_note
    from .network_section_calculator import section_result_publishable
    from ..io.output_staging import output_staging
    from ..io.quantity_policy import require_independent_section_export
    from ..io.structure_quantity_tables import trenchless_summary_columns
    from .unmeasured_terrain_scope import AUTOMATIC_TERRAIN_GAP_FIELD
    from .tunnel_exposure_scope import TUNNEL_EXPOSED_FIELD, TUNNEL_EXPOSED_ONLY
    from app_渠系计算前端.earthwork.project_resources import prepare_project_resources
    from app_渠系计算前端.project_codec import ProjectCodec

    if not section_result_publishable(payload):
        raise ValueError("成果尚未完成固定间距计算或自适应收敛复核，不能保存为有效交付")
    require_independent_section_export(payload)
    validation = payload.get("validation") or {}
    unsupported_only = bool(validation.get("automatic_unsupported_only"))
    unmeasured_only = bool(validation.get("automatic_terrain_unmeasured_only"))
    has_sections = bool(payload.get("sections"))
    bore_columns = trenchless_summary_columns(payload)
    directory = resolved_path(directory)
    target = filesystem_path(directory, extended=True)
    storage = _delivery_storage_path(directory)
    if target.exists():
        raise ValueError("成果目录已存在，请使用新的目录以保留原成果：" + str(directory))
    target.parent.mkdir(parents=True, exist_ok=True)
    storage.parent.mkdir(parents=True, exist_ok=True)

    def check():
        if cancelled and cancelled():
            raise InterruptedError("成果保存已取消，计算结果保留")

    def report(fraction, message):
        check()
        if progress:
            progress("delivery", fraction, message)

    drawing_failures = {}
    report(0., "正在保存工程量和图纸" if has_sections else "正在保存工程量")
    with (output_staging(directory.parent, prefix=".earthwork-delivery-") as temp,
          output_staging(storage.parent, prefix=".earthwork-delivery-") as state_temp):
        staging = Path(temp) / "成果"
        staging.mkdir()
        support = Path(state_temp) / "工程记录"
        support.mkdir()
        channel_name = ((workbench_state or {}).get("ui_state") or {}).get("source_channel_name", "")
        export_section_result(payload, staging / "工程量.xlsx", cancelled=cancelled, channel_name=channel_name)
        if has_sections:
            report(.25, "工程量表已保存并核对，正在生成施工断面图")
            section_options = {**dict(drawing_options or {}), "concise": True,
                               "include_plan": False, "include_profile": False}
            drawing_exports = (
                ("施工断面.dxf", section_options),
                ("挖填平面外包络.dxf", {"envelopes_only": True}),
            )
            for filename, options in drawing_exports:
                try:
                    export_section_result(payload, staging / filename, drawing_options=options, cancelled=cancelled)
                except DrawingExportError as error:
                    drawing_failures[filename] = str(error)
        if drawing_failures:
            report(.65, "已核对可保存的文件，待补导图纸将列在成果页")
        else:
            report(.65, "图纸已保存并核对" if has_sections else "工程量表已保存并核对")
        for audit_path in staging.glob("*.audit.json"):
            audit=json.loads(audit_path.read_text(encoding="utf8"))
            audit["path"]=str(directory / audit_path.name.removesuffix(".audit.json"))
            (support / audit_path.name).write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding="utf8")
            audit_path.unlink()

        state = deepcopy({k: v for k, v in workbench_state.items() if k != "last_result"}) if workbench_state is not None else {
            "schema_version": "1.0", "kind": "section_workbench", "project_id": str(uuid.uuid4()),
            "workbench_inputs": deepcopy(payload.get("inputs", {}).get("workbench", {})),
            "terrain": deepcopy(payload.get("terrain", {})),
            "terrain_mode": payload.get("terrain", {}).get("terrain_mode", "combined"),
            "terrain_options": deepcopy(payload.get("terrain", {}).get("terrain_options", {})),
            "settings": deepcopy(payload.get("inputs", {}).get("accuracy", {})),
        }
        delivery_project_id = state.setdefault("project_id", str(uuid.uuid4()))
        state.update(last_result=payload, result_status="READY",
                     last_delivery_path=str(directory), output_directory=str(directory.parent))
        if not project_snapshot:
            state["source_project_hash"] = None
        elif not state.get("source_project_hash"):
            from . import workbench_identity
            # A long-running calculation can have imported the pure identity
            # helper before an application-side source-schema migration.
            import importlib
            workbench_identity=importlib.reload(workbench_identity)
            state["source_project_hash"] = workbench_identity.source_project_hash(project_snapshot)
        state["drawing_options"] = dict(drawing_options or {})
        project = support / "算量工程.qxproj"
        complete_project = {key: value for key, value in (project_snapshot or {"version": "2.0"}).items()
                            if key != "earthwork_panel"}
        complete_project["earthwork_panel"] = state
        saved = prepare_project_resources(complete_project, project, cancel_check=check)
        project.write_text(json.dumps(saved, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf8")
        reopened = ProjectCodec.read(str(project))["earthwork_panel"]
        reopened_result = reopened.get("last_result", {})
        if (reopened.get("result_status") != "READY" or reopened.get("resource_issues")
                or reopened_result.get("input_hash") != payload.get("input_hash")):
            raise ValueError("工程保存后关联资料或计算身份未能恢复")
        if bore_columns and (reopened_result.get("trenchless_excavation_rows") != payload["trenchless_excavation_rows"]
                or any(reopened_result.get(key) != payload.get(key) for key, _ in bore_columns)):
            raise ValueError("工程保存后非开挖洞挖工程量回读不一致")
        if any(reopened_result.get(key) != payload.get(key) for key in BACKFILL_VOLUME_KEYS):
            raise ValueError("工程保存后周边回填分项工程量回读不一致")
        if reopened_result.get(AUTOMATIC_TERRAIN_GAP_FIELD) != payload.get(AUTOMATIC_TERRAIN_GAP_FIELD):
            raise ValueError("工程保存后地形缺测区段回读不一致")
        if reopened_result.get(TUNNEL_EXPOSED_FIELD) != payload.get(TUNNEL_EXPOSED_FIELD):
            raise ValueError("工程保存后隧洞待计区段回读不一致")
        del reopened_result, reopened, saved, state

        basis = payload.get("quantity_basis") or {}
        from .workbench_scope import deferred_scope_metadata
        report(.9, "正在核对成果文件清单")
        files = [{"path": str(p.relative_to(staging)), "sha256": _sha(p), "size": p.stat().st_size}
                 for p in sorted(staging.rglob("*")) if p.is_file()]
        accuracy=(payload.get("inputs") or {}).get("accuracy",{})
        sampling_note = section_sampling_note(payload)
        if validation.get(TUNNEL_EXPOSED_ONLY):
            sampling_note = "本次无已计施工断面，隧洞露顶待计区段见工程量表。"
        elif unmeasured_only:
            sampling_note = "本次无已计施工断面，地形缺测区段见工程量表。"
        elif unsupported_only:
            sampling_note = "本次无已计施工断面，悬空区段见工程量表。"
        manifest = {"status": "READY_WITH_DRAWING_ISSUES" if drawing_failures else "READY",
                    "project_id": delivery_project_id, "input_hash": payload["input_hash"],
                    "delivery_directory": str(directory),
                    "sampling_mode":validation.get("sampling_mode",accuracy.get("sampling_mode","adaptive")) if has_sections else None,
                    "fixed_sampling_contract":validation.get("fixed_sampling_contract"),
                    "curve_sampling":deepcopy(validation.get("curve_sampling",{})),
                    "profile_step_m":accuracy.get("profile_step") if has_sections else None,
                    "integration_method":payload.get("integration_method",payload.get("method")),
                    "convergence_checked":validation.get("convergence_checked",bool(payload.get("converged"))),
                    "converged":bool(payload.get("converged")),
                    "sampling_note":sampling_note,
                    "terrain_sha256": payload.get("terrain", {}).get("source_sha256"),
                    "section_count": len(payload.get("sections", [])),
                    "segment_count": len(payload.get("segments", [])), "test_only": bool(payload.get("test_only")),
                    "quantity_basis":deepcopy(basis),"water_profile_included":bool(project_snapshot),
                    "quantity_items":deepcopy(payload.get("quantity_items",[])),
                    "drawing_binding_validation":deepcopy(payload.get("drawing_binding_validation",{})),
                    "quantities": {key: payload.get(key) for key in ("excavation_volume", "backfill_volume", "embankment_volume", "total_fill_volume", "concrete_volume", "bedding_volume")},
                    "files": files}
        manifest["quantities"].update({key:payload[key] for key in BACKFILL_VOLUME_KEYS if key in payload})
        if drawing_failures:
            manifest["drawing_failures"] = drawing_failures
        if bore_columns:
            manifest["quantities"].update({key:payload.get(key) for key, _ in bore_columns})
            manifest["trenchless_excavation_rows"] = deepcopy(payload["trenchless_excavation_rows"])
            manifest["trenchless_excavation_complete"] = payload.get("trenchless_excavation_complete")
        if payload.get(AUTOMATIC_TERRAIN_GAP_FIELD):
            manifest[AUTOMATIC_TERRAIN_GAP_FIELD] = deepcopy(payload[AUTOMATIC_TERRAIN_GAP_FIELD])
        if payload.get(TUNNEL_EXPOSED_FIELD):
            manifest[TUNNEL_EXPOSED_FIELD] = deepcopy(payload[TUNNEL_EXPOSED_FIELD])
        manifest.update(deferred_scope_metadata(payload))
        (support / "成果清单.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf8")
        check()
        support.rename(storage)
        try:
            staging.rename(target)
        except BaseException:
            storage.rename(support)
            raise
    if progress:
        progress("delivery", 1., "成果已保存：" + str(directory))
    return str(directory)
