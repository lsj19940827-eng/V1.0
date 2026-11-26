"""挖填工作区的纯数据状态、Rhino 任务及可恢复发布。"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import threading
import time
from uuid import uuid4
import zipfile

import numpy as np

from 土石方计算.bridge.server import RhinoBridge, BridgeError, atomic_json, file_hash

VOLUME_KEYS = ("cut_volume", "backfill_volume", "embankment_volume", "fill_volume")
ACTIVE_STATES = {"VALIDATING", "QUEUED", "RUNNING", "CHECKING", "PREPARED", "COMMITTING"}
TERMINAL_STATES = {"READY", "FAILED", "CANCELLED", "STALE", "DISCONNECTED"}
UI_ACTIONS = {"terrain", "axis", "calculate", "cancel", "show_stage", "select", "section"}
DISPLAY_ROLES = {"all", "terrain", "structure", "cut", "backfill", "embankment"}
_ACTIVE_SESSION_LOCK = threading.RLock()


def without_credentials(value):
    """公开状态递归去掉凭据字段，不改动原工程或插件消息。"""
    if isinstance(value, dict):
        hidden = {"token", "access_token", "refresh_token", "authorization", "client_secret"}
        return {key: without_credentials(item) for key, item in value.items()
                if str(key).lower() not in hidden}
    if isinstance(value, list):
        return [without_credentials(item) for item in value]
    return copy.deepcopy(value)


def now_text():
    return datetime.now(timezone.utc).isoformat()


def content_hash(data):
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, allow_nan=False,
                     separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def default_data(project_id=None):
    return {
        "schema_version": "1.0", "project_id": project_id or uuid4().hex,
        "project_generation": 1,
        "revisions": {"terrain": 0, "design": 0, "construction": 0},
        "coordinate_reference": {"units": "m", "local_origin": [0.0, 0.0, 0.0],
                                 "axis_order": "xy", "vertical_datum": "项目高程"},
        "terrain": {}, "assets": [],
        "settings": {"linear_tolerance": 0.001, "volume_absolute_tolerance": 0.001,
                     "section_relative_tolerance": 0.005, "section_interval": 10.0,
                     "curve_chord_tolerance": 0.01, "test_only": False},
        "last_result": None, "result_status": "EMPTY", "source": {},
    }


class EarthworkWorkspace:
    """界面只提交数据；网络回调在锁内更新状态，不访问 Qt。"""

    def __init__(self, data=None, resource_root=None):
        self._lock = threading.RLock()
        self._provided_root = Path(resource_root).resolve() if resource_root else None
        self._data = default_data()
        self._job = None
        self._events = []
        self._event_sequence = 0
        self._last_message = "尚未连接 Rhino"
        self._progress = None
        self._closed = False
        self._active_session_path = None
        self.bridge = None
        self.restore(data or self._data)

    @property
    def data(self):
        return self._data

    @property
    def resource_root(self):
        return self.bridge.resource_root

    def restore(self, data):
        if not isinstance(data, dict):
            raise ValueError("挖填工程数据必须为对象")
        if data.get("schema_version") not in (None, "1.0"):
            raise ValueError("不支持此挖填工程版本")
        restored = default_data(data.get("project_id"))
        restored.update(copy.deepcopy(data))
        if not isinstance(restored.get("assets"), list) or not isinstance(restored.get("terrain"), dict):
            raise ValueError("建筑物或地形数据格式无效")
        # 无新模式标记的数据只作历史记录保留，不认证旧工程量。
        if data and "schema_version" not in data:
            restored = default_data()
            restored.update(legacy_payload=copy.deepcopy(data), migration_status="legacy_unverified")
        restored["schema_version"] = "1.0"
        if not isinstance(restored["project_id"], str) or not restored["project_id"]:
            raise ValueError("工程身份无效")
        old_bridge = self.bridge
        if old_bridge is not None:
            self._clear_active_session(old_bridge)
            old_bridge.close()
        project_id = restored["project_id"]
        root = self._provided_root
        if root is None:
            cache_base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
            root = cache_base / "CanalHydraulics" / "earthwork" / hashlib.sha256(
                project_id.encode("utf-8")).hexdigest()[:24]
        self.bridge = RhinoBridge(project_id, root, self._receive)
        with self._lock:
            self._data = restored
            self._data["project_generation"] = int(restored.get("project_generation", 0)) + 1
            self._job = None
            self._events = []
            self._closed = False
            self._last_message = "等待连接 Rhino"
            if restored.get("last_result") and restored.get("result_status") != "MISSING":
                self._data["result_status"] = "DISCONNECTED"
            self._recover_intent()

    def _recover_intent(self):
        journal = self.resource_root / "state" / "pending_commit.json"
        if not journal.is_file():
            return
        try:
            record = json.loads(journal.read_text(encoding="utf-8"))
            if (record.get("project_id") == self._data["project_id"]
                    and record.get("input_hash") == self._input_hash()):
                self._job = record
                self._job["state"] = "COMMITTING"
                self._last_message = "有待恢复的模型提交，连接 Rhino 后核对"
        except (OSError, ValueError, KeyError):
            self._last_message = "待提交记录不可读，保留历史结果并重新计算"

    def to_dict(self):
        with self._lock:
            result = copy.deepcopy(self._data)
            # 工程只保存正式或过期结果，不保存当前凭据、端口及运行任务。
            result.pop("connection", None)
            result.pop("token", None)
            return result

    def start_bridge(self):
        self._closed = False
        with _ACTIVE_SESSION_LOCK:
            discovery = self.bridge.start()
            cache_base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
            pointer = cache_base / "CanalHydraulics" / "earthwork" / "active-session.json"
            # 活动指针只帮助 Rhino 找到本机发现文件，不能复制认证信息。
            atomic_json(pointer, {"discovery_path": discovery, "project_id": self.bridge.project_id})
            self._active_session_path = pointer
        return discovery

    def _clear_active_session(self, bridge):
        pointer = self._active_session_path
        if pointer is None:
            return
        with _ACTIVE_SESSION_LOCK:
            try:
                active = json.loads(pointer.read_text(encoding="utf-8"))
                if (not isinstance(active, dict) or active.get("project_id") != bridge.project_id
                        or Path(active.get("discovery_path", "")).resolve() != bridge.discovery_path):
                    return
                # 同一资源目录也可能已建立新会话，此时旧工作区不得删除新指针。
                if bridge.discovery_path.is_file():
                    discovery = json.loads(bridge.discovery_path.read_text(encoding="utf-8"))
                    if not isinstance(discovery, dict) or discovery.get("session_id") != bridge.session_id:
                        return
                pointer.unlink()
            except (OSError, ValueError, TypeError):
                pass
            finally:
                self._active_session_path = None

    def close(self):
        with self._lock:
            if self._job and self._job["state"] in ACTIVE_STATES:
                self.cancel_job(self._job["job_id"])
            self._closed = True
        self._clear_active_session(self.bridge)
        self.bridge.close()

    def set_assets(self, assets):
        if not isinstance(assets, list):
            raise ValueError("建筑物应为列表")
        with self._lock:
            self._data["assets"] = copy.deepcopy(assets)
            self.invalidate("design")

    def set_terrain(self, terrain):
        with self._lock:
            self._validate_terrain(terrain)
            self._data["terrain"] = copy.deepcopy(terrain)
            self.invalidate("terrain")

    def invalidate(self, kind="construction"):
        if kind not in ("terrain", "design", "construction"):
            raise ValueError("未知输入修订类型")
        with self._lock:
            revisions = self._data.setdefault("revisions", {})
            revisions[kind] = int(revisions.get(kind, 0)) + 1
            if self._data.get("last_result"):
                self._data["result_status"] = "STALE"
            if self._job and self._job["state"] in ACTIVE_STATES:
                job_id = self._job["job_id"]
                self._job["state"] = "STALE"
                self.bridge.discard(job_id=job_id)
                self.bridge.enqueue("cancel", {"job_id": job_id})
                self._last_message = "输入已改变，旧任务结果不可发布"
            self._record_event("input_changed", {"kind": kind})

    def request_terrain(self, source_path=None, **options):
        if source_path:
            source = Path(source_path).resolve()
            if not source.is_file() or source.suffix.lower() not in (".dwg", ".dxf", ".3dm"):
                raise ValueError("请选择存在的 DWG、DXF 或 3DM")
            payload = {"source_path": str(source), **options}
            return self.bridge.enqueue("terrain_import", payload)
        return self.bridge.enqueue("terrain_select", options)

    def sample_terrain(self, points_xy, request_id=None):
        points = np.asarray(points_xy, dtype=float)
        if points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all():
            raise ValueError("地形查询点必须为有限的二维坐标")
        request_id = request_id or uuid4().hex
        self.bridge.enqueue("sample_terrain", {"points_xy": points.tolist(), "request_id": request_id})
        return request_id

    def select(self, asset_id):
        return self.bridge.enqueue("select", {"asset_id": str(asset_id)})

    def show_stage(self, role):
        if role not in DISPLAY_ROLES:
            raise ValueError("未知施工显示阶段")
        return self.bridge.enqueue("show_stage", {"role": role})

    def section(self, station, asset_id=None):
        if not math.isfinite(float(station)):
            raise ValueError("剖切桩号必须为有限数值")
        return self.bridge.enqueue("section", {"station": float(station), "asset_id": asset_id})

    def _input(self):
        return {key: copy.deepcopy(self._data[key]) for key in (
            "schema_version", "project_id", "revisions", "coordinate_reference",
            "terrain", "assets", "settings")}

    def _input_hash(self):
        logical_input = self._input()
        # 资源位置属于保存方式；相同内容搬迁后仍代表同一份设计和地形。
        terrain = logical_input["terrain"]
        if terrain.get("mesh_sha256"):
            terrain.pop("mesh_path", None)
        evidence = terrain.get("source_preprocessing") or {}
        for field, hash_field in (("native_sources_path", "native_sources_sha256"),
                                  ("raw_native_sources_path", "raw_native_sources_sha256"),
                                  ("quality_report_path", "quality_report_sha256"),
                                  ("height_resolution_path", "height_resolution_sha256")):
            if evidence.get(hash_field):
                evidence.pop(field, None)
        for asset in logical_input["assets"]:
            alignment = asset.get("alignment", {})
            for field, hash_field in (("native_curve_path", "native_curve_sha256"),
                                      ("native_axis_path", "native_axis_sha256")):
                if alignment.get(hash_field):
                    alignment.pop(field, None)
            for curve in alignment.get("native_pipe_curves", []):
                if curve.get("sha256"):
                    curve.pop("path", None)
        return content_hash(logical_input)

    def create_job(self, *, force_full=False):
        with self._lock:
            if not self.bridge.connected:
                raise ValueError("请先连接 Rhino 文档")
            if self._job and self._job["state"] in ACTIVE_STATES:
                raise ValueError("上一项挖填任务尚未结束")
            if not self._data["terrain"]:
                raise ValueError("请先选择或导入有效地形")
            terrain_document = self._data["terrain"].get("document_id")
            if terrain_document != self.bridge.client["document_id"]:
                raise ValueError("地形绑定的 Rhino 文档已改变，请在当前文档重新选择或导入地形")
            if not self._data["assets"]:
                raise ValueError("请先导入线路和建筑物")
            snapshot = self._input()
            snapshot["snapshot_id"] = uuid4().hex
            snapshot["project_generation"] = self._data["project_generation"]
            snapshot["input_hash"] = self._input_hash()
            previous_result = copy.deepcopy(self._data.get("last_result"))
            job_id = uuid4().hex
            self._job = {
                "project_id": self._data["project_id"], "job_id": job_id,
                "input_hash": snapshot["input_hash"], "snapshot_id": snapshot["snapshot_id"],
                "state": "VALIDATING", "created_at": now_text(),
                "document_id": self.bridge.client["document_id"],
            }
            self._progress = 0.0
            self._last_message = "正在准备施工参数"
        # 数据冻结后释放锁，准备大量断面时界面仍能读状态或取消任务。
        try:
            # 文件系统别名必须先解析再核对边界；原生进程不能只收到等价目录的另一种写法。
            for owner, field, hash_field in self._input_resource_references(snapshot):
                resource = self.bridge.resource_path(owner[field])
                if owner.get(hash_field) and file_hash(resource) != owner[hash_field]:
                    raise ValueError("计算资源哈希不匹配，不能使用同名旧资源")
                owner[field] = str(resource)
            bounds = self._validate_terrain(snapshot["terrain"])
            self._complete_calculation_domain(snapshot, bounds)
            capabilities = (self.bridge.client or {}).get("capabilities", [])
            if "terrain_box_bounds_v1" in capabilities:
                from .local_domains import derive_local_domains
                snapshot["assets"] = derive_local_domains(
                    snapshot["assets"], snapshot["settings"], snapshot["terrain"],
                    lambda boxes: self._query_terrain_box_bounds(boxes, job_id))
            elif snapshot["settings"].get("automatic_local_domains"):
                raise ValueError("当前Rhino组件不支持逐段TIN施工范围，请使用配套新版组件")
            from .construction_templates import prepare_assets
            snapshot["assets"] = prepare_assets(snapshot["assets"], snapshot["settings"])
            from .contracts import validate_snapshot
            validation = validate_snapshot(snapshot)
            if isinstance(validation, dict) and not validation.get("valid", True):
                raise ValueError("；".join(item.get("message", "输入校验失败")
                                         for item in validation.get("issues", [])))
            job_root = self.resource_root / "jobs" / job_id
            from .impact_planner import plan_incremental_recompute, full_recompute_plan
            reuse_context, incremental_plan = plan_incremental_recompute(
                snapshot, previous_result, force_full=force_full)
            if incremental_plan["mode"] == "incremental":
                try:
                    old_model = Path(previous_result["model_path"])
                    if file_hash(old_model) != previous_result["model_sha256"]:
                        raise ValueError("旧模型摘要不匹配")
                    reuse_root = job_root / "reuse"
                    reuse_root.mkdir(parents=True, exist_ok=True)
                    copied_model = reuse_root / "previous.3dm"
                    shutil.copyfile(old_model, copied_model)
                    if file_hash(copied_model) != previous_result["model_sha256"]:
                        raise ValueError("复用模型复制校验失败")
                    reusable = copy.deepcopy(previous_result)
                    reusable["model_path"] = str(copied_model)
                    previous_path = reuse_root / "previous-result.json"
                    atomic_json(previous_path, reusable)
                    incremental_plan.update(previous_result_path=str(previous_path),
                                            previous_result_sha256=file_hash(previous_path))
                except (OSError, ValueError, KeyError) as error:
                    incremental_plan = full_recompute_plan(reuse_context, "旧资源不可复用，改为全量计算：" + str(error))
            snapshot["reuse_context"] = reuse_context
            snapshot["incremental_plan"] = incremental_plan
            snapshot_path = job_root / "snapshot.json"
            atomic_json(snapshot_path, snapshot)
            snapshot_sha256 = file_hash(snapshot_path)
            with self._lock:
                if (not self._job or self._job["job_id"] != job_id
                        or self._job["state"] != "VALIDATING"
                        or self._input_hash() != snapshot["input_hash"]):
                    raise BridgeError("准备期间输入改变或任务已取消", 409)
                self._job.update(state="QUEUED", snapshot_path=str(snapshot_path),
                                 snapshot_sha256=snapshot_sha256, reuse_context=reuse_context)
                self._last_message = ("局部重算已提交 Rhino，包含相交及端部衔接邻段"
                                      if incremental_plan["mode"] == "incremental" else "全量任务已提交 Rhino")
                self.bridge.enqueue("calculate", {
                    "job_id": job_id, "input_hash": snapshot["input_hash"],
                    "snapshot_path": str(snapshot_path), "snapshot_sha256": snapshot_sha256,
                    "result_dir": str(job_root / "result"),
                })
                self._save_job()
                return job_id
        except Exception as exc:
            with self._lock:
                if self._job and self._job["job_id"] == job_id and self._job["state"] == "VALIDATING":
                    self._job["state"] = "FAILED"
                    self._last_message = str(exc)
                    self._save_job()
            raise

    def _query_terrain_box_bounds(self, boxes, job_id):
        request_id = uuid4().hex
        sequence = self._event_sequence
        self.bridge.enqueue("terrain_box_bounds", {"request_id": request_id, "boxes_xy": boxes})
        deadline = time.monotonic() + 300.
        while time.monotonic() < deadline:
            with self._lock:
                if self._closed or not self._job or self._job["job_id"] != job_id or self._job["state"] != "VALIDATING":
                    raise BridgeError("局部TIN施工范围准备已取消或输入已改变", 409)
                for event in self._events:
                    if event["id"] > sequence and event["event"] == "terrain_box_bounds" and event.get("request_id") == request_id:
                        return copy.deepcopy(event.get("bounds"))
                    if event["id"] > sequence and event["event"] == "failure":
                        raise BridgeError(event.get("message", "局部TIN范围查询失败"))
                self._last_message = "正在按实际TIN逐段推导施工辅助范围"
            time.sleep(.04)
        raise TimeoutError("局部TIN施工范围查询超时，未启动工程量计算")

    def cancel_job(self, job_id):
        with self._lock:
            if self._job is None or self._job["job_id"] != job_id:
                return
            if self._job["state"] in TERMINAL_STATES:
                return
            previous_state = self._job["state"]
            self._job["state"] = "CANCELLED"
            self.bridge.discard(job_id=job_id)
            if previous_state == "COMMITTING":
                self.bridge.enqueue("rollback", self._commit_payload())
            self.bridge.enqueue("cancel", {"job_id": job_id})
            self._last_message = "任务已取消，保留上一版完整结果"
            self._save_job()
            self._clear_intent()

    def status(self):
        with self._lock:
            connected = self.bridge.connected
            state = self._job["state"] if self._job else "IDLE"
            if not connected and state in ACTIVE_STATES and self.bridge.client:
                state = "DISCONNECTED"
            return without_credentials({
                "project_id": self._data["project_id"],
                "connected": connected, "job_state": state,
                "job_id": self._job["job_id"] if self._job else None,
                "progress": self._progress, "message": self._last_message,
                "result": self._data.get("last_result"),
                "result_status": self._data.get("result_status", "EMPTY"),
                "design_revision": self._data.get("revisions", {}).get("design", 0),
                "project_generation": self._data.get("project_generation", 0),
                "events": self._events[-200:],
                "document": self.bridge.client,
                "assets": self._asset_summaries(),
            })

    def _asset_summaries(self):
        settings = self._data.get("settings", {})
        summaries = []
        for asset in self._data["assets"]:
            alignment = asset.get("alignment") or {}
            sampling = alignment.get("sampling") or {}
            stations = alignment.get("native_samples") or alignment.get("plan_points") or []
            start = asset.get("station_start")
            end = asset.get("station_end")
            if stations:
                start = stations[0].get("station") if start is None else start
                end = stations[-1].get("station") if end is None else end
            summaries.append({
                "asset_id": asset.get("asset_id"), "name": asset.get("name", ""),
                "kind": asset.get("kind"), "section_type": asset.get("section_type"),
                "enabled": asset.get("enabled") is not False,
                "station_start": start, "station_end": end,
                "elevation_reference": alignment.get("elevation_reference"),
                "sample_spacing": sampling.get("maximum_spacing", settings.get("section_interval", 10.0)),
                "chord_tolerance": sampling.get("chord_tolerance", settings.get("curve_chord_tolerance", 0.01)),
                "native_curve": {"bound": bool(alignment.get("native_curve_path")),
                                 "curve_id": alignment.get("native_curve_id")},
            })
        return summaries

    def _queue_ui_action(self, payload):
        action = payload.get("action")
        data = payload.get("data", {})
        if not isinstance(action, str) or action not in UI_ACTIONS:
            raise BridgeError("未知 Rhino 界面操作")
        if not isinstance(data, dict):
            raise BridgeError("界面操作 data 必须为对象")
        asset_id = data.get("asset_id")
        if action in ("axis", "select") or "asset_id" in data:
            known = {asset.get("asset_id") for asset in self._data["assets"]}
            if not isinstance(asset_id, str) or not asset_id or asset_id not in known:
                raise BridgeError("界面操作的建筑物不属于当前工程")
        if action == "show_stage" and (not isinstance(data.get("role"), str)
                                       or data["role"] not in DISPLAY_ROLES):
            raise BridgeError("未知施工显示阶段")
        if action == "section":
            station = data.get("station")
            if (isinstance(station, bool) or not isinstance(station, (int, float))
                    or not math.isfinite(station)):
                raise BridgeError("剖切桩号必须为有限数值")
        # 只排队已验证的动作，全部由主程序轮询后在 Qt 主线程执行。
        self._record_event("ui_action", {"action": action, "data": data})
        return {"ok": True, "event_id": self._event_sequence}

    def complete_ui_action(self, action, error=None):
        """主线程反馈操作结果，供 Rhino 工作台下一次读取状态时展示。"""
        if not isinstance(action, str) or action not in UI_ACTIONS:
            raise BridgeError("未知 Rhino 界面操作")
        with self._lock:
            ok = error is None
            message = "工作台请求已处理" if ok else "工作台操作失败：" + str(error)
            self._last_message = message
            self._record_event("ui_action_result", {"action": action, "ok": ok, "message": message})
            return {"ok": ok, "message": message, "event_id": self._event_sequence}

    def _save_job(self):
        if self._job:
            atomic_json(self.resource_root / "jobs" / self._job["job_id"] / "job.json", self._job)

    def _record_event(self, event, payload):
        self._event_sequence += 1
        self._events.append({"id": self._event_sequence, "event": event,
                             "time": now_text(), **copy.deepcopy(payload)})
        if len(self._events) > 400:
            self._events = self._events[-200:]

    def _current_job(self, payload, *, allow_ready=False):
        if not self._job or payload.get("job_id") != self._job["job_id"]:
            raise BridgeError("任务不属于当前工程", 409)
        job = self._job
        if job["state"] in {"CANCELLED", "STALE", "FAILED"}:
            raise BridgeError("该任务已取消、失效或失败", 409)
        if job["state"] == "READY" and not allow_ready:
            raise BridgeError("任务已完成", 409)
        if (payload.get("input_hash", job["input_hash"]) != job["input_hash"]
                or self._input_hash() != job["input_hash"]):
            job["state"] = "STALE"
            raise BridgeError("输入已改变，禁止提交旧结果", 409)
        return job

    def _validate_terrain(self, terrain):
        if not isinstance(terrain, dict) or not terrain.get("mesh_path"):
            raise ValueError("地形缺少计算网文件")
        path = Path(terrain["mesh_path"]).resolve()
        # 打开历史工程允许资源来自保存时的路径，网络消息另检查本机会话根。
        if not path.is_file():
            raise ValueError("地形资源缺失，请重新定位或导入工程包")
        expected = terrain.get("mesh_sha256")
        if expected and file_hash(path) != expected:
            raise ValueError("地形资源哈希不匹配，不能使用同名旧地形")
        mesh = json.loads(path.read_text(encoding="utf-8-sig"))
        vertices = np.asarray(mesh.get("vertices"), dtype=float)
        faces = np.asarray(mesh.get("faces"))
        if (vertices.ndim != 2 or vertices.shape[1] != 3 or len(vertices) < 3
                or not np.isfinite(vertices).all()):
            raise ValueError("地形顶点无效")
        if (faces.ndim != 2 or faces.shape[1] != 3 or len(faces) == 0
                or not np.issubdtype(faces.dtype, np.integer)
                or faces.min() < 0 or faces.max() >= len(vertices)):
            raise ValueError("地形三角面索引无效")
        terrain["mesh_sha256"] = file_hash(path)
        return vertices.min(axis=0).tolist(), vertices.max(axis=0).tolist()

    @staticmethod
    def _complete_calculation_domain(snapshot, bounds):
        """封闭辅助面从真实地形和设计几何推导，绝不填补缺失的设计高程。"""
        settings = snapshot["settings"]
        bottom, top = float(bounds[0][2]), float(bounds[1][2])
        for asset in snapshot["assets"]:
            if not asset.get("enabled", True):
                continue
            from .construction_rules import effective_construction
            section, construction = asset.get("section", {}), effective_construction(asset)
            sizes = [float(value) for key, value in section.items()
                     if key in {"inner_height", "inner_diameter", "inner_radius", "wall_height",
                                "base_thickness", "wall_thickness", "roof_thickness"}
                     and isinstance(value, (int, float)) and not isinstance(value, bool)
                     and math.isfinite(value) and value >= 0]
            clearance = max(1.0, sum(sizes)) + float(construction.get("bedding_thickness") or 0.0)
            alignment = asset.get("alignment", {})
            elevations = [point.get("elevation") for point in alignment.get("profile_points", [])]
            elevations.extend(point.get("origin", [None, None, None])[2]
                              for point in alignment.get("native_samples", []))
            for value in elevations:
                if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                    bottom = min(bottom, value - clearance)
                    top = max(top, value + clearance)
        settings.setdefault("base_z", bottom - 1.0)
        settings.setdefault("clip_top_z", top + 1.0)
        for field in ("base_z", "clip_top_z"):
            if not isinstance(settings[field], (int, float)) or not math.isfinite(settings[field]):
                raise ValueError("计算封闭辅助高程必须为有限值")
        if settings["base_z"] >= bounds[0][2] or settings["clip_top_z"] <= bounds[1][2]:
            raise ValueError("计算封闭辅助面未完整包住原地形，请调整底高程和顶高程")
        snapshot["derived_calculation_domain"] = {
            "base_z": settings["base_z"], "clip_top_z": settings["clip_top_z"],
            "basis": "terrain_and_design_envelope", "not_design_elevation": True,
        }

    def _validate_result(self, result):
        if not isinstance(result, dict) or not result.get("result_id") or not result.get("geometry_hash"):
            raise BridgeError("几何结果身份不完整")
        rows = result.get("rows")
        if not isinstance(rows, list) or not rows:
            raise BridgeError("几何结果缺少工程量明细")
        expected_assets = {asset["asset_id"] for asset in self._data["assets"]
                           if asset.get("enabled", True)}
        processed = result.get("processed_asset_ids")
        if (not isinstance(processed, list) or len(processed) != len(set(processed))
                or set(processed) != expected_assets):
            raise BridgeError("几何结果未完整覆盖本次启用的建筑物")
        if result.get("units") != "m":
            raise BridgeError("几何成果必须使用米制工程单位")
        validation = result.get("validation", {})
        for key in ("closed_solids", "nonnegative_volumes", "topology_valid",
                    "section_check_passed", "overlap_resolved"):
            if validation.get(key) is not True:
                raise BridgeError("几何验收未通过：" + key)
        totals = {key: 0.0 for key in VOLUME_KEYS}
        seen_segments = set()
        settings = self._data["settings"]
        absolute_tol = float(settings.get("volume_absolute_tolerance", 0.001))
        relative_tol = float(settings.get("section_relative_tolerance", 0.005))
        if not (math.isfinite(absolute_tol) and absolute_tol > 0
                and math.isfinite(relative_tol) and 0 < relative_tol <= 0.1):
            raise BridgeError("方量复核容差无效")
        for row in rows:
            participants = row.get("participants")
            if (not isinstance(participants, list) or not participants
                    or len(participants) != len(set(participants))
                    or not set(participants).issubset(expected_assets)):
                raise BridgeError("工程量单元的建筑物归属无效")
            expected_owner = participants[0] if len(participants) == 1 else "__common__"
            if row.get("asset_id") != expected_owner:
                raise BridgeError("公共工程量单元的归属与参与建筑物不一致")
            segment_id = row.get("segment_id")
            if not segment_id or segment_id in seen_segments:
                raise BridgeError("工程量单元缺少唯一身份或重复")
            seen_segments.add(segment_id)
            for key in VOLUME_KEYS:
                value = row.get(key)
                ref = row.get("ref_" + key)
                if (isinstance(value, bool) or not isinstance(value, (int, float))
                        or not math.isfinite(value) or value < 0):
                    raise BridgeError("工程量必须为非负有限值：" + key)
                if (isinstance(ref, bool) or not isinstance(ref, (int, float))
                        or not math.isfinite(ref) or ref < 0):
                    raise BridgeError("缺少独立断面复核：" + key)
                if abs(value - ref) > max(absolute_tol, relative_tol * max(value, ref)):
                    raise BridgeError("断面复核未收敛：" + str(segment_id) + "/" + key)
                totals[key] += value
            if abs(row["fill_volume"] - row["backfill_volume"] - row["embankment_volume"]) > max(
                    1e-8, 1e-10 * row["fill_volume"]):
                raise BridgeError("填方分项不等于总填方")
        for key, total in totals.items():
            reported = result.get("totals", {}).get(key)
            if (not isinstance(reported, (int, float)) or not math.isfinite(reported)
                    or abs(reported - total) > max(1e-8, 1e-10 * total)):
                raise BridgeError("工程量汇总与明细不符：" + key)
        model_path = self.bridge.resource_path(result.get("model_path", ""))
        if (file_hash(model_path) != result.get("model_sha256")
                or result["geometry_hash"] != result.get("model_sha256")):
            raise BridgeError("三维模型文件校验失败")
        validated = copy.deepcopy(result)
        # 插件返回的快照字段不能作为证明，只能由当前任务保存的文件回读建立。
        for field in ("calculation_snapshot", "calculation_snapshot_path", "calculation_snapshot_sha256",
                      "calculation_snapshot_id", "calculation_snapshot_verified"):
            validated.pop(field, None)
        validated["calculation_snapshot_verified"] = False
        job = self._job or {}
        snapshot = None
        if job.get("snapshot_path") and job.get("snapshot_sha256"):
            snapshot_path = self.bridge.resource_path(job["snapshot_path"])
            raw = snapshot_path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != job["snapshot_sha256"]:
                raise BridgeError("实际计算快照文件已改变，不能发布工程量")
            snapshot = json.loads(raw.decode("utf-8-sig"))
            if (not isinstance(snapshot, dict)
                    or snapshot.get("input_hash") != job.get("input_hash")
                    or snapshot.get("input_hash") != result.get("input_hash")
                    or snapshot.get("snapshot_id") != job.get("snapshot_id")
                    or snapshot.get("project_id") != self._data["project_id"]):
                raise BridgeError("实际计算快照身份与任务或成果不符")
            if without_credentials(snapshot) != snapshot:
                raise BridgeError("实际计算快照含会话凭据，不能保存为成果依据")
            reuse = snapshot.get("incremental_plan") or {}
            if reuse.get("previous_result_path"):
                previous_path = self.bridge.resource_path(reuse["previous_result_path"])
                if file_hash(previous_path) != reuse.get("previous_result_sha256"):
                    raise BridgeError("实际计算快照的复用资源校验失败")
                previous = json.loads(previous_path.read_text(encoding="utf-8-sig"))
                previous_model = self.bridge.resource_path(previous.get("model_path", ""))
                if file_hash(previous_model) != previous.get("model_sha256"):
                    raise BridgeError("实际计算快照的复用模型校验失败")
        if result.get("reuse_context") is not None:
            expected_context = job.get("reuse_context")
            if result["reuse_context"] != expected_context:
                raise BridgeError("局部复用上下文与冻结任务不一致")
            digest = result.get("engine_sha256", "")
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise BridgeError("原生运行文件身份缺失，不能建立局部复用依据")
            if snapshot is not None:
                if snapshot.get("reuse_context") != expected_context:
                    raise BridgeError("实际计算快照复用上下文不符")
                validated.update(calculation_snapshot=snapshot,
                                 calculation_snapshot_path=str(snapshot_path),
                                 calculation_snapshot_sha256=job["snapshot_sha256"],
                                 calculation_snapshot_id=snapshot["snapshot_id"],
                                 calculation_snapshot_verified=True)
        # 历史量表必须保留计算当时的输入，不能读取之后编辑的参数作为依据。
        validated["calculation_input"] = self._input()
        validated["test_only"] = bool(
            self._data["settings"].get("test_only") or any(
                asset.get("test_only") or asset.get("is_test") for asset in self._data["assets"]
                if asset.get("enabled", True)))
        return validated

    def _commit_payload(self):
        return {key: self._job.get(key) for key in (
            "job_id", "commit_id", "result_id", "input_hash", "geometry_hash")}

    def _clear_intent(self):
        path = self.resource_root / "state" / "pending_commit.json"
        if path.is_file():
            path.unlink()

    def _receive(self, operation, payload):
        with self._lock:
            if operation == "status":
                return self.status()
            if operation == "action":
                return self._queue_ui_action(payload)
            if operation == "disconnect":
                if self._job and self._job["state"] in ACTIVE_STATES:
                    self.cancel_job(self._job["job_id"])
                if self._data.get("last_result") and self._data.get("result_status") != "MISSING":
                    self._data["result_status"] = "DISCONNECTED"
                if payload.get("reason") == "document_closed":
                    self._last_message = "Rhino 文档已关闭，重新打开后核对模型与工程量关联"
                    self._record_event("document_closed", {"document_id": payload.get("document_id")})
                else:
                    self._last_message = "Rhino 已断开连接"
                self._record_event("disconnected", {})
                return {"ok": True}
            if operation == "hello":
                if (self._job and self._job["state"] in ACTIVE_STATES
                        and self._job["document_id"] != payload["document_id"]):
                    raise BridgeError("任务绑定另一 Rhino 文档，请先取消或恢复原文档", 409)
                self._last_message = "已连接 Rhino " + str(payload.get("rhino_version", ""))
                previous = self._data.get("last_result")
                if previous and self._data.get("result_status") != "MISSING":
                    restored = payload.get("published_result") or {}
                    same_model = (restored.get("geometry_verified") is True
                                  and restored.get("object_count", 0) > 0
                                  and all(restored.get(key) == previous.get(key) for key in
                                          ("result_id", "input_hash", "geometry_hash", "document_id"))
                                  and payload["document_id"] == previous.get("document_id")
                                  and previous.get("input_hash") == self._input_hash())
                    self._data["result_status"] = "READY" if same_model else "STALE"
                    self._last_message = ("已恢复 Rhino 模型与工程量关联" if same_model
                                          else "已连接 Rhino，历史模型与当前工程尚未核对一致")
                if self._job and self._job["state"] == "COMMITTING":
                    self.bridge.enqueue("commit", self._commit_payload())
                self._record_event("connected", {"document_id": payload["document_id"]})
                return {"ok": True}
            if operation == "terrain":
                terrain = copy.deepcopy(payload.get("terrain", payload))
                self.bridge.resource_path(terrain.get("mesh_path", ""))
                if terrain.get("document_id") != self.bridge.client["document_id"]:
                    raise BridgeError("地形不属于当前 Rhino 文档", 409)
                self.set_terrain(terrain)
                self._last_message = "地形已接收"
                self._record_event("terrain_received", {"terrain": terrain})
                return {"ok": True, "terrain_revision": self._data["revisions"]["terrain"]}
            if operation == "event":
                event = payload.get("event", "message")
                self._record_event(event, payload)
                if event == "document_closed":
                    # 文档生命周期不改变设计输入；旧插件的关闭事件仍须保持可恢复指纹。
                    if self._job and self._job["state"] in ACTIVE_STATES:
                        self.cancel_job(self._job["job_id"])
                    if self._data.get("last_result") and self._data.get("result_status") != "MISSING":
                        self._data["result_status"] = "DISCONNECTED"
                    self._last_message = "Rhino 文档已关闭，重新打开后核对模型与工程量关联"
                elif event in ("model_modified", "model_undone"):
                    self.invalidate("design")
                    self._last_message = "Rhino 模型已改变，原工程量需重新核对"
                return {"ok": True}
            if operation == "failure":
                if payload.get("job_id"):
                    job = self._current_job(payload)
                    if job["state"] == "COMMITTING":
                        self.bridge.enqueue("rollback", self._commit_payload())
                    job["state"] = "FAILED"
                    self._save_job()
                    self._clear_intent()
                self._last_message = str(payload.get("message", "Rhino 计算失败"))
                self._record_event("failure", {"code": payload.get("code"), "message": self._last_message})
                return {"ok": True}
            if operation == "progress":
                job = self._current_job(payload)
                if job["state"] not in ("PREPARED", "COMMITTING"):
                    job["state"] = "RUNNING"
                progress = payload.get("progress")
                if progress is not None:
                    progress = float(progress)
                    if not math.isfinite(progress) or not 0 <= progress <= 1:
                        raise BridgeError("进度须为 0 至 1")
                self._progress = progress
                self._last_message = str(payload.get("message", "Rhino 正在计算"))
                return {"ok": True}
            if operation == "result":
                job = self._current_job(payload, allow_ready=True)
                result = payload.get("result", {})
                if job["state"] in ("COMMITTING", "READY"):
                    if result.get("result_id") != job.get("result_id"):
                        raise BridgeError("同一任务不能提交不同结果", 409)
                    return {"ok": True, "state": job["state"], "commit_id": job["commit_id"]}
                if result.get("input_hash") != job["input_hash"]:
                    raise BridgeError("结果输入指纹不符", 409)
                if result.get("document_id") != job["document_id"]:
                    raise BridgeError("结果文档身份不符", 409)
                job["state"] = "CHECKING"
                try:
                    result = self._validate_result(result)
                except Exception:
                    job["state"] = "FAILED"
                    self._save_job()
                    raise
                result_path = self.resource_root / "jobs" / job["job_id"] / "prepared_result.json"
                atomic_json(result_path, result)
                job.update(state="COMMITTING", commit_id=uuid4().hex,
                           result_id=result["result_id"], geometry_hash=result["geometry_hash"],
                           result_path=str(result_path))
                atomic_json(self.resource_root / "state" / "pending_commit.json", job)
                self._save_job()
                self.bridge.enqueue("commit", self._commit_payload())
                self._last_message = "量算检查通过，正在确认 Rhino 模型提交"
                return {"ok": True, "state": "COMMITTING", "commit_id": job["commit_id"]}
            if operation == "committed":
                job = self._current_job(payload, allow_ready=True)
                for key in ("commit_id", "result_id", "geometry_hash", "document_id"):
                    if payload.get(key) != job.get(key):
                        raise BridgeError("模型提交确认不匹配：" + key, 409)
                if job["state"] == "READY":
                    return {"ok": True, "state": "READY"}
                if job["state"] != "COMMITTING":
                    raise BridgeError("当前没有可提交结果", 409)
                result = json.loads(Path(job["result_path"]).read_text(encoding="utf-8"))
                result["published_at"] = now_text()
                result["status"] = "READY"
                # 正式文件写成功以后才切换内存正式量表。
                atomic_json(self.resource_root / "state" / "published_result.json", result)
                self._data["last_result"] = result
                self._data["result_status"] = "READY"
                job["state"] = "READY"
                self._progress = 1.0
                self._last_message = "模型与工程量已同步"
                self._save_job()
                self.bridge.enqueue("publish", self._commit_payload())
                self._clear_intent()
                self._record_event("result_published", {"result_id": result["result_id"]})
                return {"ok": True, "state": "READY"}
            raise BridgeError("未知工作区事件")

    def export_package(self, path):
        """导出带资源的工程包，不带发现文件、凭据或未完成任务。"""
        path = Path(path)
        if path.suffix.lower() != ".qxearth":
            path = path.with_suffix(".qxearth")
        data = without_credentials(self.to_dict())
        sources = self._input_resource_references(data)
        result = data.get("last_result") or {}
        self._check_calculation_snapshot(result)
        if result.get("model_path"):
            sources.append((result, "model_path", "model_sha256"))
        sources.extend(self._input_resource_references(result.get("calculation_input") or {}))
        sources.extend(self._input_resource_references(result.get("calculation_snapshot") or {}))
        if result.get("calculation_snapshot_path"):
            sources.append((result, "calculation_snapshot_path", "calculation_snapshot_sha256"))
        archived = []
        for owner, field, hash_field in sources:
            source = Path(owner[field])
            if not source.is_file():
                raise ValueError("资源缺失，不能导出完整工程包：" + str(source))
            digest = file_hash(source)
            if owner.get(hash_field) and owner[hash_field] != digest:
                raise ValueError("资源已改变，不能导出为同一计算结果")
            target = "resources/" + digest + source.suffix.lower()
            owner[field] = target
            owner[hash_field] = digest
            archived.append((source, target))
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + "." + uuid4().hex + ".tmp")
        try:
            with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(data, ensure_ascii=False, allow_nan=False))
                for archive_name, source_path in dict((target, source) for source, target in archived).items():
                    archive.write(source_path, archive_name)
            os.replace(temp, path)
        finally:
            if temp.exists():
                temp.unlink()
        return str(path)

    @staticmethod
    def _input_resource_references(data):
        references = []
        terrain = data.get("terrain", {})
        if terrain.get("mesh_path"):
            references.append((terrain, "mesh_path", "mesh_sha256"))
        evidence = terrain.get("source_preprocessing") or {}
        for field, hash_field in (("native_sources_path", "native_sources_sha256"),
                                  ("raw_native_sources_path", "raw_native_sources_sha256"),
                                  ("quality_report_path", "quality_report_sha256"),
                                  ("height_resolution_path", "height_resolution_sha256")):
            if evidence.get(field):
                references.append((evidence, field, hash_field))
        for asset in data.get("assets", []):
            alignment = asset.get("alignment", {})
            for field, hash_field in (("native_curve_path", "native_curve_sha256"),
                                      ("native_axis_path", "native_axis_sha256")):
                if alignment.get(field):
                    references.append((alignment, field, hash_field))
            for curve in alignment.get("native_pipe_curves", []):
                if curve.get("path"):
                    references.append((curve, "path", "sha256"))
        return references

    @classmethod
    def _snapshot_content(cls, data):
        """带摘要的资源可搬迁，冻结施工断面和参数必须保持原值。"""
        value = copy.deepcopy(data)
        for owner, field, hash_field in cls._input_resource_references(value):
            owner[field] = "sha256:" + str(owner.get(hash_field, ""))
        return value

    @classmethod
    def _check_calculation_snapshot(cls, result, raw=None):
        if result.get("calculation_snapshot_verified") is not True:
            return
        snapshot = result.get("calculation_snapshot")
        path = result.get("calculation_snapshot_path")
        if not isinstance(snapshot, dict) or not path or not result.get("calculation_snapshot_sha256"):
            raise ValueError("成果缺少实际计算快照证据")
        if raw is None:
            raw = Path(path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != result["calculation_snapshot_sha256"]:
            raise ValueError("实际计算快照校验失败")
        frozen = json.loads(raw.decode("utf-8-sig"))
        if (not isinstance(frozen, dict)
                or without_credentials(frozen) != frozen
                or cls._snapshot_content(frozen) != cls._snapshot_content(snapshot)
                or snapshot.get("input_hash") != result.get("input_hash")
                or snapshot.get("snapshot_id") != result.get("calculation_snapshot_id")):
            raise ValueError("实际计算快照内容或冻结身份校验失败")

    def import_package(self, path):
        """只提取清单明确引用并校验哈希的资源，禁止压缩包路径越界。"""
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            if manifest.get("schema_version") != "1.0":
                raise ValueError("不支持此挖填工程包版本")
            if without_credentials(manifest) != manifest:
                raise ValueError("挖填工程包不能包含会话凭据")
            resources = []
            result = manifest.get("last_result") or {}
            references = self._input_resource_references(manifest)
            references.append((result, "model_path", "model_sha256"))
            references.extend(self._input_resource_references(result.get("calculation_input") or {}))
            references.extend(self._input_resource_references(result.get("calculation_snapshot") or {}))
            if result.get("calculation_snapshot_path"):
                references.append((result, "calculation_snapshot_path", "calculation_snapshot_sha256"))
            for owner, field, hash_key in references:
                if field not in owner:
                    continue
                source = owner[field]
                relative = Path(source)
                if relative.is_absolute() or ".." in relative.parts or not source.startswith("resources/"):
                    raise ValueError("工程包资源路径无效")
                raw = archive.read(source)
                if hashlib.sha256(raw).hexdigest() != owner.get(hash_key):
                    raise ValueError("工程包资源校验失败")
                resources.append((owner, field, relative.name, raw))
                if owner is result and field == "calculation_snapshot_path":
                    self._check_calculation_snapshot(result, raw)
            if result.get("calculation_snapshot_verified") is True and not result.get("calculation_snapshot_path"):
                raise ValueError("成果缺少实际计算快照证据")
            # 所有资源校验完成后先落盘，最后一次性切换工程；保留恢复时递增的代次。
            project_id = manifest.get("project_id")
            if not isinstance(project_id, str) or not project_id:
                raise ValueError("工程包身份无效")
            cache_base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
            target_root = self._provided_root or (cache_base / "CanalHydraulics" / "earthwork" /
                                                  hashlib.sha256(project_id.encode("utf-8")).hexdigest()[:24])
            for owner, field, name, raw in resources:
                target = target_root / "imports" / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
                owner[field] = str(target.resolve())
            self.restore(manifest)
        return self.to_dict()
