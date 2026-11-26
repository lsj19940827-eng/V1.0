# -*- coding: utf-8 -*-
"""工程文件边界：版本检查、旧格式迁移及关键数据块校验。"""

import copy
import json
import os
import re
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any, Dict

from app_渠系计算前端.report_meta_model import ReportMeta


PROJECT_VERSION = "2.0"
PANEL_SLOTS = (
    "merged_panel", "batch_panel", "water_profile_panel", "open_channel_panel",
    "aqueduct_panel", "tunnel_panel", "culvert_panel", "siphon_panel",
    "pressure_pipe_panel", "spillway_steep_chute_panel", "earthwork_panel",
)
MANAGER_SECTIONS = {
    "siphon_manager_data": ("siphons",),
    "pressure_pipe_manager_data": ("pipes", "routes", "segments"),
}


class ProjectFormatError(ValueError):
    """工程格式不受支持或数据损坏，必须在改变界面前中止。"""


class ProjectCodec:
    """将历史文件转换成当前结构，不依赖页面和 Qt。"""

    @staticmethod
    def _check_version(value: Any, current: str, label: str) -> None:
        if value is None or value == "":
            return
        if not isinstance(value, str) or not re.fullmatch(r"\d+(?:\.\d+){0,2}", value):
            raise ProjectFormatError(f"{label}版本格式无效：{value!r}")
        parts = tuple(int(part) for part in value.split("."))
        supported = tuple(int(part) for part in current.split("."))
        parts += (0,) * (3 - len(parts))
        supported += (0,) * (3 - len(supported))
        if parts > supported:
            raise ProjectFormatError(f"{label}版本 {value} 高于当前支持的 {current}，请使用新版程序打开。")

    @classmethod
    def normalize(cls, source: Any, *, copy_input: bool = True) -> Dict[str, Any]:
        """保留未知字段，仅迁移已知旧字段；未来版本禁止写回。"""
        if not isinstance(source, dict):
            raise ProjectFormatError("工程文件根节点必须是 JSON 对象。")
        cls._check_version(source.get("version"), PROJECT_VERSION, "工程")
        data = copy.deepcopy(source) if copy_input else source
        for slot in PANEL_SLOTS:
            if data.get(slot) is not None and not isinstance(data[slot], dict):
                raise ProjectFormatError(f"工程模块 {slot} 的数据必须是 JSON 对象或 null。")
        if data.get("earthwork_panel"):
            from app_渠系计算前端.earthwork.project_state import normalize_earthwork_payload
            try:
                data["earthwork_panel"] = normalize_earthwork_payload(data["earthwork_panel"], copy_input=False)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ProjectFormatError(f"挖填工程量数据无效：{exc}") from exc
        for slot, sections in MANAGER_SECTIONS.items():
            payload = data.get(slot)
            if payload is None:
                payload = {}
            if not isinstance(payload, dict):
                raise ProjectFormatError(f"工程模块 {slot} 的数据必须是 JSON 对象或 null。")
            cls._check_version(payload.get("version"), "1.0", slot)
            for section in sections:
                bucket = payload.setdefault(section, {})
                if not isinstance(bucket, dict) or any(not isinstance(item, dict) for item in bucket.values()):
                    raise ProjectFormatError(f"{slot}.{section} 必须是由对象组成的 JSON 对象。")
            payload.setdefault("version", "1.0")
            data[slot] = payload

        meta = data.get("report_meta")
        if meta is not None:
            if not isinstance(meta, dict):
                raise ProjectFormatError("工程 report_meta 必须是 JSON 对象或 null。")
            field_names = {item.name for item in fields(ReportMeta)}
            unknown = set(meta) - field_names
            if unknown:
                raise ProjectFormatError(f"报告信息含未支持字段：{', '.join(sorted(unknown))}")
            for key, value in meta.items():
                if key == "extra_references":
                    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                        raise ProjectFormatError("报告附加依据必须是文本列表。")
                elif not isinstance(value, str):
                    raise ProjectFormatError(f"报告信息 {key} 必须是文本。")
        # 缺少工程报告块时使用干净工程默认值，不继承上一工程名称和人员。
        data["report_meta"] = asdict(ReportMeta(**(meta or {})))

        batch = data.get("batch_panel")
        water = data.get("merged_panel") or data.get("water_profile_panel")
        if not water and batch:
            aliases = {
                "channel_name": "channel_name", "channel_level": "channel_level",
                "start_water_level": "start_water_level", "start_station": "start_station_text",
                "flow_segments": "design_flows_text",
            }
            water = {
                "batch_panel_compat": copy.deepcopy(batch),
                "ui_settings": {target: str(batch[key]) for key, target in aliases.items() if key in batch},
            }
        if water:
            cls._check_version(water.get("version"), "1.0", "水面线")
            for key in ("ui_settings", "project_settings", "batch_panel_compat", "merged_section", "extra_caches"):
                if key in water and not isinstance(water[key], dict):
                    raise ProjectFormatError(f"水面线 {key} 必须是 JSON 对象。")
            for key in ("nodes", "calculated_nodes"):
                if key in water and (not isinstance(water[key], list)
                                     or any(not isinstance(node, dict) for node in water[key])):
                    raise ProjectFormatError(f"水面线 {key} 必须是由对象组成的列表。")
            if "table_state" in water:
                from 推求水面线.models.profile_state import ProfileTableState
                try:
                    water["table_state"] = ProfileTableState.from_dict(water["table_state"]).to_dict()
                except (TypeError, ValueError, OverflowError) as exc:
                    raise ProjectFormatError(f"水面线 table_state 无效：{exc}") from exc
            if batch and "batch_panel_compat" not in water:
                water["batch_panel_compat"] = copy.deepcopy(batch)
            data["merged_panel"] = water
            data["water_profile_panel"] = copy.deepcopy(water)
            if not batch and isinstance(water.get("batch_panel_compat"), dict):
                data["batch_panel"] = copy.deepcopy(water["batch_panel_compat"])

            earthwork = data.get("earthwork_panel") or {}
            ui_state = earthwork.get("ui_state") or {}
            source_hash = earthwork.get("source_project_hash")
            if earthwork.get("kind") == "section_workbench" and source_hash:
                from app_渠系计算前端.earthwork.project_state import (
                    remove_duplicate_pressure_profile_drafts, source_channel_name,
                )

                remove_duplicate_pressure_profile_drafts(data, water)
                if not ui_state.get("source_channel_name"):
                    from 土石方计算.services.workbench_identity import source_project_hash

                    channel_name = source_channel_name(water)
                    if channel_name and source_hash == source_project_hash(data):
                        earthwork["ui_state"] = {**ui_state, "source_channel_name": channel_name}
        data["version"] = PROJECT_VERSION
        return data

    @classmethod
    def read(cls, path: str) -> Dict[str, Any]:
        """仅在工程未内嵌管理数据时，显式导入同名历史旁文件。"""
        from filesystem_paths import filesystem_path, resolved_path
        path = filesystem_path(path, extended=True)
        with open(path, "r", encoding="utf-8") as handle:
            source = json.load(handle)
        if not isinstance(source, dict):
            return cls.normalize(source)
        # 先验证版本，不能为未来格式自动套用旧格式兼容逻辑。
        cls._check_version(source.get("version"), PROJECT_VERSION, "工程")
        base = os.path.splitext(os.fspath(path))[0]
        for slot, suffix in (("siphon_manager_data", ".siphon.json"),
                             ("pressure_pipe_manager_data", ".ppipe.json")):
            if source.get(slot) is None:
                sidecar = base + suffix
                if os.path.isfile(sidecar):
                    with open(sidecar, "r", encoding="utf-8") as handle:
                        source[slot] = json.load(handle)
        # JSON decoding owns this complete tree. Keep one copy through validation
        # and resource restoration, including large retained earthwork results.
        data = cls.normalize(source, copy_input=False)
        if data.get("earthwork_panel"):
            from app_渠系计算前端.earthwork.project_resources import restore_project_resources
            try:
                data = restore_project_resources(data, path, copy_input=False)
            except (OSError, TypeError, ValueError) as exc:
                raise ProjectFormatError(f"挖填工程资源无法恢复：{exc}") from exc
            workbench = data["earthwork_panel"]
            project = resolved_path(path)
            if workbench.get("kind") == "section_workbench" and project.name == "算量工程.qxproj":
                from 土石方计算.services.workbench_delivery import delivery_matches_result

                result = workbench.get("last_result") or {}
                old_delivery = workbench.get("last_delivery_path")
                if old_delivery and delivery_matches_result(project.parent, result.get("input_hash"),
                                                             workbench.get("project_id"), require_project_id=True):
                    if workbench.get("output_directory") == str(Path(old_delivery).parent):
                        workbench["output_directory"] = str(project.parent.parent)
                    workbench["last_delivery_path"] = str(project.parent)
        return data
