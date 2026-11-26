# -*- coding: utf-8 -*-
"""挖填资源随主工程保存；只复制明确引用的几何文件。"""

from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path
import shutil
import uuid
from filesystem_paths import filesystem_path as _filesystem_path, resolved_path as _resolved_path


def _hash_file(path):
    digest = hashlib.sha256()
    with _filesystem_path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _references(payload):
    if payload.get("kind")=="section_workbench":
        yield from _section_references(payload)
    terrain = payload.get("terrain")
    if isinstance(terrain, dict) and terrain.get("mesh_path"):
        yield "terrain.mesh_path", terrain, "mesh_path", "mesh_sha256", "terrain"
    evidence = terrain.get("source_preprocessing") if isinstance(terrain, dict) else None
    if isinstance(evidence, dict):
        for field, digest, role in (("native_sources_path", "native_sources_sha256", "terrain_source"),
                                    ("raw_native_sources_path", "raw_native_sources_sha256", "terrain_source"),
                                    ("quality_report_path", "quality_report_sha256", "terrain_audit"),
                                    ("height_resolution_path", "height_resolution_sha256", "terrain_audit")):
            if evidence.get(field):
                yield f"terrain.source_preprocessing.{field}", evidence, field, digest, role
    result = payload.get("last_result")
    if isinstance(result, dict) and result.get("model_path"):
        yield "last_result.model_path", result, "model_path", "model_sha256", "model"
    for asset in payload.get("assets", []):
        alignment = asset.get("alignment") or {}
        for field, digest in (("native_curve_path", "native_curve_sha256"), ("native_axis_path", "native_axis_sha256")):
            if alignment.get(field):
                yield f"assets/{asset.get('asset_id')}/alignment/{field}", alignment, field, digest, "native_curve"
        for index, curve in enumerate(alignment.get("native_pipe_curves", [])):
            if curve.get("path"):
                yield f"assets/{asset.get('asset_id')}/alignment/native_pipe_curves/{index}", curve, "path", "sha256", "native_curve"
    if isinstance(result, dict):
        for field in ("calculation_input", "calculation_snapshot"):
            if isinstance(result.get(field), dict):
                for key, node, path, digest, role in _references(result[field]):
                    yield f"last_result.{field}/" + key, node, path, digest, role
        if result.get("calculation_snapshot_path"):
            yield ("last_result.calculation_snapshot_path", result, "calculation_snapshot_path",
                   "calculation_snapshot_sha256", "calculation_snapshot")


def _section_references(payload):
    """Explicit file identities of the independent section workbench.

    The saved result can refer to a previous terrain while the current draft
    uses a new one; both identities travel with the project.
    """
    def terrain(value,prefix):
        if not isinstance(value,dict):return
        for path,digest,role in (("path","source_sha256","terrain_source_file"),
                                 ("cache_path","cache_sha256","terrain_cache")):
            if value.get(path):yield prefix+"."+path,value,path,digest,role
        clean=value.get("clean_terrain",{})
        if isinstance(clean,dict):
            for path,digest in (("dxf_path","dxf_sha256"),("points_path","points_sha256"),("sources_path","sources_sha256"),("report_path","report_sha256")):
                if clean.get(path):yield prefix+".clean_terrain."+path,clean,path,digest,"terrain_source_file"
    def inputs(value,prefix):
        if not isinstance(value,dict):return
        for i,item in enumerate(value.get("input_files") or []):
            if isinstance(item,dict) and item.get("path"):
                yield f"{prefix}.input_files/{i}",item,"path","sha256","input_file"
        for network_index, network in enumerate(value.get("networks") or []):
            for asset_index, asset in enumerate(network.get("assets") or []):
                source = (asset.get("siphon_axis_input") or {}).get("source") or {}
                if source.get("kind") in {"quantity_dxf", "quantity_input"} and source.get("path"):
                    key = f"{prefix}.networks/{network_index}/assets/{asset_index}/siphon_axis_input"
                    yield key,source,"path","sha256","input_file"
        for nested in ("workbench","workbench_inputs"):
            if isinstance(value.get(nested),dict):yield from inputs(value[nested],prefix+"."+nested)
    yield from terrain(payload.get("terrain"),"terrain")
    yield from inputs(payload.get("inputs"),"inputs")
    yield from inputs(payload.get("workbench_inputs"),"workbench_inputs")
    result=payload.get("last_result")
    if isinstance(result,dict):
        yield from terrain(result.get("terrain"),"last_result.terrain")
        yield from inputs(result.get("inputs"),"last_result.inputs")


def _atomic_copy(source, target, digest):
    source = _filesystem_path(source)
    target = _filesystem_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and _hash_file(target) == digest:
        return
    # 临时文件名不重复资源哈希，避免正式路径可用时临时路径却超过系统长度限制。
    temporary = target.with_name(f".{uuid.uuid4().hex}.tmp")
    try:
        shutil.copyfile(source, temporary)
        if _hash_file(temporary) != digest:
            raise ValueError("复制期间几何资源发生变化，停止保存")
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def _resource_extension(role,path=None):
    if role in {"terrain_source_file","terrain_cache","input_file"}:
        extension=Path(path).suffix.lower() if path else ""
        if extension and (len(extension)>12 or not extension[1:].isalnum()):
            raise ValueError("断面工作台资源扩展名无效")
        return extension or ".bin"
    return {"terrain": ".json", "terrain_source": ".jsonl", "terrain_audit": ".json",
            "calculation_snapshot": ".json"}.get(role, ".3dm")


def prepare_project_resources(data, project_path, *, cancel_check=None):
    """先完成资源快照，调用方随后才原子提交工程正文。"""
    saved = copy.deepcopy(data)
    payload = saved.get("earthwork_panel")
    if not isinstance(payload, dict) or not payload:
        return saved
    section_workbench=payload.get("kind")=="section_workbench"
    if section_workbench and not payload.get("project_id"):
        payload["project_id"]=str(uuid.uuid4())
    if not section_workbench and payload.get("result_status") != "MISSING":
        from 土石方计算.services.workspace import EarthworkWorkspace
        EarthworkWorkspace._check_calculation_snapshot(payload.get("last_result") or {})
    project = _resolved_path(project_path)
    resource_dir = project.with_name(project.name + ".resources")
    if not _resolved_path(resource_dir).is_relative_to(project.parent):
        raise ValueError("工程资源目录不能通过链接指向工程目录之外")
    portable = {}
    prior_issues = {item.get("resource"): item for item in payload.get("resource_issues", [])}
    retained_issues = []
    for key, node, path_field, hash_field, role in _references(payload):
        if cancel_check:
            cancel_check()
        source = Path(node[path_field])
        if key in prior_issues and payload.get("result_status") == "MISSING":
            # 已明确缺失的旧模型不阻止保存新的参数；缺失状态和资源身份随工程保留。
            digest = node.get(hash_field)
            if isinstance(digest, str) and len(digest) == 64:
                target = resource_dir / (digest + _resource_extension(role,source))
                relative = target.relative_to(project.parent).as_posix()
                node[path_field] = relative
                portable[key] = {"path": relative, "sha256": digest, "role": role}
                retained_issues.append(prior_issues[key])
                continue
        if not source.is_absolute() or not _filesystem_path(source).is_file():
            raise ValueError(f"挖填{role}资源缺失，工程未保存：{source}")
        source = _resolved_path(source)
        digest = _hash_file(source)
        expected = node.get(hash_field)
        if expected and digest != expected:
            raise ValueError(f"挖填{role}资源哈希不符，工程未保存：{source}")
        extension = _resource_extension(role,source)
        target = resource_dir / (digest + extension)
        _atomic_copy(source, target, digest)
        relative = target.relative_to(project.parent).as_posix()
        node[path_field] = relative
        node[hash_field] = digest
        portable[key] = {"path": relative, "sha256": digest, "role": role}
    payload["relative_resource_paths"] = portable
    if retained_issues:
        payload["resource_issues"] = retained_issues
    else:
        payload.pop("resource_issues", None)
    if cancel_check:
        cancel_check()
    return saved


def restore_project_resources(data, project_path, *, copy_input=True):
    """先核对随工程携带的文件，再恢复到该工程专属计算缓存。"""
    restored = copy.deepcopy(data) if copy_input else data
    payload = restored.get("earthwork_panel")
    if not isinstance(payload, dict):
        return restored
    portable = payload.get("relative_resource_paths")
    if not portable:
        return restored
    if not isinstance(portable, dict):
        raise ValueError("挖填相对资源索引必须为对象")
    project = _resolved_path(project_path)
    project_id = payload.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        raise ValueError("携带几何资源的挖填工程必须具有稳定工程身份")
    cache_base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
    cache = cache_base / "CanalHydraulics" / "earthwork" / hashlib.sha256(project_id.encode("utf-8")).hexdigest()[:24] / "portable_resources"
    issues = []
    for key, node, path_field, hash_field, role in _references(payload):
        entry = portable.get(key)
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            issues.append({"resource": key, "message": "随工程资源索引缺失"})
            continue
        source = _resolved_path(project.parent / entry["path"])
        digest = entry.get("sha256")
        if (not isinstance(digest, str) or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)):
            raise ValueError("挖填资源哈希格式无效")
        if not source.is_relative_to(project.parent):
            raise ValueError("挖填资源相对路径越出了工程所在目录")
        if node.get(hash_field) and node[hash_field] != digest:
            raise ValueError("挖填资源索引与数据哈希不一致")
        # 缺失资源保留为缺失路径，不能拿旧缓存悄悄顶替。
        node[path_field] = str(_filesystem_path(source))
        if not _filesystem_path(source).is_file():
            issues.append({"resource": key, "message": f"缺少随工程资源：{entry['path']}"})
            continue
        if _hash_file(source) != digest:
            issues.append({"resource": key, "message": f"随工程资源已改变，哈希不符：{entry['path']}"})
            continue
        target = cache / (digest + _resource_extension(role,source))
        _atomic_copy(source, target, digest)
        # Windows 应用缓存可能经目录别名重定向，跨进程只传与会话根一致的真实路径。
        node[path_field] = str(_filesystem_path(_resolved_path(target)))
        node[hash_field] = digest
    if not issues and payload.get("kind")!="section_workbench":
        from 土石方计算.services.workspace import EarthworkWorkspace
        EarthworkWorkspace._check_calculation_snapshot(payload.get("last_result") or {})
    if issues:
        payload["resource_issues"] = issues
        if payload.get("last_result"):
            payload["result_status"] = "MISSING"
            if payload.get("kind")=="section_workbench":payload["valid_result"]=False
    else:
        payload.pop("resource_issues", None)
    return restored
