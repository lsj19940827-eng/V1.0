# -*- coding: utf-8 -*-
"""
项目管理器 —— 负责项目的新建、打开、保存、自动保存等操作
"""

import copy
import os
import time
from datetime import datetime
from typing import Optional, Any, Dict, List, TYPE_CHECKING, Set

from PySide6.QtCore import QObject, Signal, QTimer, QSettings
from PySide6.QtWidgets import QFileDialog, QMessageBox

from app_渠系计算前端.styles import fluent_save_discard_cancel

from app_渠系计算前端.debug_utils import debug_print
from atomic_json import atomic_write_json
from app_渠系计算前端.project_codec import ProjectCodec
from app_渠系计算前端.project_session import ProjectSession, ProjectSnapshot
from app_渠系计算前端.task_runner import TaskRunner
from app_渠系计算前端.earthwork.project_resources import prepare_project_resources

if TYPE_CHECKING:
    from app_渠系计算前端.batch.panel import BatchPanel
    from app_渠系计算前端.panel_registry import PanelRegistry
    from app_渠系计算前端.water_profile.panel import WaterProfilePanel
    from app_渠系计算前端.open_channel.panel import OpenChannelPanel
    from app_渠系计算前端.aqueduct.panel import AqueductPanel
    from app_渠系计算前端.tunnel.panel import TunnelPanel
    from app_渠系计算前端.culvert.panel import CulvertPanel
    from app_渠系计算前端.siphon.panel import SiphonPanel
    from app_渠系计算前端.pressure_pipe.panel import PressurePipePanel
    from 推求水面线.managers.siphon_manager import SiphonManager
    from 推求水面线.managers.pressure_pipe_manager import PressurePipeManager


# 项目文件扩展名
PROJECT_EXT = ".qxproj"
PROJECT_FILTER = f"渠系项目文件 (*{PROJECT_EXT})"

# 自动保存目录（相对于程序目录）
AUTO_SAVE_DIR = os.path.join("data", "autosave")

# 自动保存间隔（毫秒）
AUTO_SAVE_INTERVAL_MS = 480_000  # 8分钟

# 每个项目保留的最大自动保存文件数
MAX_AUTO_SAVE_FILES = 3

# 最近项目最大数量
MAX_RECENT_PROJECTS = 5


class ProjectManager(QObject):
    """项目管理器"""

    # 信号
    project_changed = Signal(str)       # 项目路径变化时发射，参数为新路径（空串表示新项目）
    dirty_changed = Signal(bool)        # 脏状态变化时发射
    status_message = Signal(str)        # 状态栏消息
    project_open_progress = Signal(str, bool)  # 阶段提示，是否可取消

    def __init__(self, parent=None):
        super().__init__(parent)

        # ---- 状态 ----
        self._current_path: str = ""     # 当前项目路径（空串表示新建未保存）
        self.session = ProjectSession()
        self._auto_save_runner = TaskRunner(self)
        self._project_open_runner = TaskRunner(self)
        self._project_open_runner.running_changed.connect(self._on_project_open_running_changed)
        self._opening_path = ""
        self._is_dirty: bool = False     # 是否有未保存的修改

        # ---- 运行时引用（由 MainWindow 设置）----
        self._panel_registry: Optional["PanelRegistry"] = None
        self._connected_panel_ids: Set[int] = set()
        self._initial_panel_data: Dict[str, Any] = {}
        self._reset_on_first_visit: Set[str] = set()
        self._restoring_project = False
        self._project_restore_error = ''

        # ---- Manager 引用（由 MainWindow 设置）----
        self._siphon_manager: Optional["SiphonManager"] = None
        self._pressure_pipe_manager: Optional["PressurePipeManager"] = None

        # ---- 自动保存定时器 ----
        self._auto_save_timer = QTimer(self)
        self._auto_save_timer.setInterval(AUTO_SAVE_INTERVAL_MS)
        self._auto_save_timer.timeout.connect(self._do_auto_save)

        # ---- 最近项目列表 ----
        self._recent_projects: List[str] = []
        self._load_recent_projects()

    # ----------------------------------------------------------------
    # 属性
    # ----------------------------------------------------------------
    @property
    def current_path(self) -> str:
        return self._current_path

    @property
    def is_dirty(self) -> bool:
        return self._is_dirty

    @property
    def recent_projects(self) -> List[str]:
        return list(self._recent_projects)

    # ----------------------------------------------------------------
    # 运行时绑定
    # ----------------------------------------------------------------
    def bind_runtime(
        self,
        panel_registry: "PanelRegistry",
        services: Optional[Dict[str, Any]] = None,
    ) -> None:
        """绑定运行时面板注册表与相关 manager。"""
        services = services or {}

        if self._panel_registry is not None:
            try:
                self._panel_registry.instance_created.disconnect(self._on_panel_instance_created)
            except Exception:
                pass

        self._panel_registry = panel_registry
        self._siphon_manager = services.get("siphon_manager")
        self._pressure_pipe_manager = services.get("pressure_pipe_manager")
        self._bind_manager_paths(self._current_path)
        self._connected_panel_ids.clear()
        self._initial_panel_data.clear()
        self._reset_on_first_visit.clear()

        self._panel_registry.instance_created.connect(self._on_panel_instance_created)
        for descriptor in self._panel_registry.descriptors:
            panel = self._panel_registry.get_existing(descriptor.key)
            if panel is not None:
                self._on_panel_instance_created(descriptor.key, panel)

    def _on_panel_instance_created(self, key: str, panel: Any) -> None:
        descriptor = self._panel_registry.descriptor_for_key(key)
        if descriptor and hasattr(panel, 'to_project_dict'):
            # 首次装配时保存干净默认值，切换到空工程不能沿用上一工程的输入和结果。
            state = copy.deepcopy(panel.to_project_dict())
            if descriptor.project_slot == 'water_profile_panel' and isinstance(state.get('ui_settings'), dict):
                # 保持新建工程原有的空基础信息规则，不把首屏示例名称和流量作为新工程数据。
                level = panel.channel_level_combo.itemText(0)
                state['ui_settings'].update({
                    'channel_name': '', 'start_water_level': '', 'design_flows_text': '',
                    'max_flows_text': '', 'start_station_text': '0', 'roughness': '0.017',
                    'channel_level': level,
                })
                state['project_settings'] = {}
                state.setdefault('merged_section', {})['flow_segments_text'] = ''
                state.setdefault('batch_panel_compat', {}).update({
                    'channel_name': '', 'start_water_level': '', 'start_station': '0',
                    'channel_level': level, 'flow_segments': '',
                })
            self._initial_panel_data[descriptor.project_slot] = state
        self._connect_panel_dirty_signal(panel)
        if descriptor and descriptor.project_slot in self._reset_on_first_visit:
            # 工程中空缺的模块首次访问时也采用干净初始状态，避免带入启动示例。
            self._restore_panel(descriptor.project_slot, panel, None)
            self._reset_on_first_visit.discard(descriptor.project_slot)

    def _restore_panel(self, slot: str, panel: Any, payload: Any, *, take_ownership: bool = False) -> None:
        """先恢复干净默认值，再走原有版本迁移入口，避免默认字段遮蔽旧格式。"""
        def restore(state, *, owned=False):
            if slot == 'earthwork_panel':
                from app_渠系计算前端.earthwork.workbench_panel import SectionWorkbenchPanel
                if isinstance(panel, SectionWorkbenchPanel):
                    panel.from_project_dict(state, normalized=True, take_ownership=owned)
                    return
            state = copy.deepcopy(state)
            if slot in ('water_profile_panel', 'batch_panel'):
                panel.from_project_dict(state, skip_dirty_signal=True)
            else:
                panel.from_project_dict(state)

        old_restoring = self._restoring_project
        self._restoring_project = True
        try:
            if hasattr(panel, 'reset_to_default'):
                panel.reset_to_default()
            else:
                restore(self._initial_panel_data.get(slot, {}))
            if isinstance(payload, dict) and payload:
                restore(payload, owned=take_ownership)
        finally:
            self._restoring_project = old_restoring

    def _connect_panel_dirty_signal(self, panel: Any) -> None:
        if panel is None or not hasattr(panel, "data_changed"):
            return
        panel_id = id(panel)
        if panel_id in self._connected_panel_ids:
            return
        panel.data_changed.connect(self.mark_dirty)
        self._connected_panel_ids.add(panel_id)

    def _get_panel(self, project_slot: str, *, create_missing: bool = True) -> Any:
        if project_slot == "batch_panel" or self._panel_registry is None:
            return None
        descriptor = self._panel_registry.descriptor_for_project_slot(project_slot)
        if descriptor is None:
            return None
        if create_missing:
            return self._panel_registry.get(descriptor.key)
        return self._panel_registry.get_existing(descriptor.key)

    def _get_primary_channel_panel(self, *, create_missing: bool = True) -> Any:
        batch_panel = self._get_panel("batch_panel", create_missing=create_missing)
        if batch_panel is not None:
            return batch_panel
        return self._get_panel("water_profile_panel", create_missing=create_missing)

    def _iter_project_panel_entries(
        self,
        *,
        create_missing: bool = True,
        exclude_slots: Optional[Set[str]] = None,
    ) -> List[tuple[str, Any, str]]:
        if self._panel_registry is None:
            return []

        exclude_slots = exclude_slots or set()
        entries: List[tuple[str, Any, str]] = []
        for descriptor in self._panel_registry.descriptors:
            project_slot = descriptor.project_slot
            if not project_slot or project_slot in exclude_slots:
                continue
            panel = self._panel_registry.get(descriptor.key) if create_missing else self._panel_registry.get_existing(descriptor.key)
            entries.append((project_slot, panel, descriptor.attr_name))
        return entries

    # ----------------------------------------------------------------
    # 脏状态管理
    # ----------------------------------------------------------------
    def mark_dirty(self):
        """标记项目为已修改"""
        if self._restoring_project:
            return
        self.session.changed()
        if not self._is_dirty:
            self._is_dirty = True
            self.dirty_changed.emit(True)

    def _clear_dirty(self):
        """清除脏状态"""
        if self._is_dirty:
            self._is_dirty = False
            self.dirty_changed.emit(False)

    # ----------------------------------------------------------------
    # 自动保存
    # ----------------------------------------------------------------
    def start_auto_save(self):
        """启动自动保存定时器"""
        if not self._auto_save_timer.isActive():
            self._auto_save_timer.start()

    def stop_auto_save(self):
        """停止自动保存定时器"""
        self._auto_save_timer.stop()

    def _do_auto_save(self):
        """界面线程只采集快照，序列化和磁盘写入交给统一后台任务。"""
        if not self._is_dirty or self._auto_save_runner.isRunning():
            return
        try:
            auto_save_path = self._get_auto_save_path()
            snapshot = self.session.capture(self._collect_project_data())

            def write_snapshot(token):
                token.raise_if_cancelled()
                saved_data = prepare_project_resources(snapshot.data, auto_save_path, cancel_check=token.raise_if_cancelled)
                token.raise_if_cancelled()
                atomic_write_json(auto_save_path, saved_data)
                return auto_save_path

            def saved(path):
                # 自动保存只生成恢复副本，永远不确认正式工程已保存。
                if snapshot.generation == self.session.generation:
                    self.status_message.emit(f"自动保存完成: {os.path.basename(path)}")
                self._cleanup_old_auto_saves(os.path.dirname(path))

            def failed(error):
                self.status_message.emit(f"自动保存失败: {error}")

            self._auto_save_runner.submit(write_snapshot, on_success=saved, on_error=failed)
        except Exception as e:
            self.status_message.emit(f"自动保存失败: {e}")

    def finish_background_save(self, timeout_ms: int = 1000) -> bool:
        """关闭时收尾已启动的保存；超时让窗口保持打开，避免销毁活跃线程。"""
        finished = self._auto_save_runner.wait(timeout_ms)
        if finished:
            self.stop_auto_save()
        return finished

    def finish_background_tasks(self, timeout_ms: int = 1000) -> bool:
        """关闭时取消计算回写，再收尾磁盘写入；使用总超时避免界面长时间等待。"""
        deadline = time.monotonic() + max(0, timeout_ms) / 1000
        if self._project_open_runner.isRunning():
            self.cancel_project_open()
            remaining = max(0, int((deadline - time.monotonic()) * 1000))
            if not self._project_open_runner.wait(remaining):
                return False
        for _label, runner in self._iter_calculation_runners():
            if not runner.isRunning():
                continue
            if hasattr(runner, 'invalidate'):
                runner.invalidate()
            elif hasattr(runner, 'cancel'):
                runner.cancel()
            elif hasattr(runner, 'requestInterruption'):
                runner.requestInterruption()
            remaining = max(0, int((deadline - time.monotonic()) * 1000))
            if not hasattr(runner, 'wait') or not runner.wait(remaining):
                return False
        remaining = max(0, int((deadline - time.monotonic()) * 1000))
        return self.finish_background_save(remaining)

    def _confirm_saved(self, snapshot: ProjectSnapshot) -> None:
        """旧快照不能清除保存过程中产生的新修改。"""
        if self.session.confirm_saved(snapshot):
            self._clear_dirty()

    def _cleanup_old_auto_saves(self, auto_dir: str):
        """清理旧的自动保存文件，每个项目前缀只保留最近 MAX_AUTO_SAVE_FILES 个"""
        try:
            suffix = f"_autosave{PROJECT_EXT}"
            all_files = [f for f in os.listdir(auto_dir) if f.endswith(suffix)]
            prefix_groups: Dict[str, list] = {}
            for f in all_files:
                # 文件名格式: {项目名}_{级别}_{YYYYMMDD}_{HHMMSS}_autosave.qxproj
                # 去掉后缀后按最后两个 _ 分割出时间戳，剩余部分作为项目前缀
                stem = f[:-len(suffix)]  # 例: "南峰寺_支渠_20260304_214133"
                parts = stem.rsplit("_", 2)
                prefix = parts[0] if len(parts) >= 3 else stem
                prefix_groups.setdefault(prefix, []).append(f)

            for prefix, files in prefix_groups.items():
                files.sort(reverse=True)
                for old_file in files[MAX_AUTO_SAVE_FILES:]:
                    try:
                        os.remove(os.path.join(auto_dir, old_file))
                    except OSError:
                        pass
        except OSError:
            pass

    def _get_auto_save_path(self) -> str:
        """获取自动保存文件路径"""
        # 确保自动保存目录存在
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        auto_dir = os.path.join(app_dir, AUTO_SAVE_DIR)
        os.makedirs(auto_dir, exist_ok=True)

        # 生成文件名：渠道名_级别_时间戳
        channel_name = "未命名"
        channel_level = ""
        primary_panel = self._get_primary_channel_panel(create_missing=False)
        if primary_panel:
            channel_name = primary_panel.channel_name_edit.text().strip() or "未命名"
            channel_level = primary_panel.channel_level_combo.currentText().strip()

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c for c in channel_name if c.isalnum() or c in "_ -")[:20]
        safe_level = "".join(c for c in channel_level if c.isalnum() or c in "_ -")[:10]

        filename = f"{safe_name}_{safe_level}_{timestamp}_autosave{PROJECT_EXT}"
        return os.path.join(auto_dir, filename)

    # ----------------------------------------------------------------
    # 新建项目
    # ----------------------------------------------------------------
    def new_project(self) -> bool:
        """新建项目，返回是否成功"""
        self.cancel_project_open()
        # 检查是否需要保存当前项目
        if not self._check_save_before_close():
            return False

        try:
            self._apply_project_transaction(ProjectCodec.normalize({}), "")
        except Exception as exc:
            QMessageBox.critical(None, '新建失败', str(exc))
            return False
        self._current_path = ""
        self._clear_dirty()
        self.project_changed.emit("")
        self.status_message.emit("已新建项目")
        return True

    def _reset_panels(self):
        """重置所有面板到初始状态"""
        self._require_panels_idle()
        if self._panel_registry is not None:
            for slot, panel, _label in self._iter_project_panel_entries(create_missing=False):
                if panel is not None:
                    self._restore_panel(slot, panel, None)
            self._reset_on_first_visit = {
                slot for slot, panel, _label in self._iter_project_panel_entries(create_missing=False)
                if panel is None
            }
            return

        # 兼容尚未绑定注册表的独立面板调用。
        batch_panel = self._get_panel("batch_panel", create_missing=False)
        if batch_panel:
            try:
                # 清空表格
                batch_panel.input_table.setRowCount(0)
                batch_panel.channel_name_edit.clear()
                batch_panel.start_wl_edit.clear()
                batch_panel.start_station_edit.setText("0")
                batch_panel.channel_level_combo.setCurrentIndex(0)
                batch_panel.batch_results.clear()
            except Exception:
                pass

        water_profile_panel = self._get_panel("water_profile_panel", create_missing=False)
        if water_profile_panel:
            try:
                # 清空表格和数据
                water_profile_panel.nodes.clear()
                water_profile_panel.calculated_nodes.clear()
                water_profile_panel._update_table_from_nodes_full([])
                if hasattr(water_profile_panel, "_clear_section_tables"):
                    water_profile_panel._clear_section_tables()
                water_profile_panel.channel_name_edit.clear()
                water_profile_panel.start_wl_edit.clear()
                water_profile_panel.design_flow_edit.clear()
                water_profile_panel.max_flow_edit.clear()
                water_profile_panel.start_station_edit.setText("0")
                water_profile_panel.roughness_edit.setText("0.017")
                water_profile_panel.channel_level_combo.setCurrentIndex(0)
            except Exception:
                pass

        for _key, panel, label in self._iter_project_panel_entries(
            create_missing=False,
            exclude_slots={"water_profile_panel"},
        ):
            if panel and hasattr(panel, "reset_to_default"):
                try:
                    panel.reset_to_default()
                except Exception as e:
                    print(f"[ProjectManager] 重置{label}失败: {e}")

    def _iter_calculation_runners(self):
        """只查询已存在面板和内嵌批量后端，不为状态检查创建页面。"""
        seen = set()
        for slot, panel, label in self._iter_project_panel_entries(create_missing=False):
            if panel is None:
                continue
            names = ('calculation_runner', '_batch_worker')
            if slot == 'earthwork_panel':
                names += ('runner',)
            for owner in (panel, getattr(panel, '_batch_backend', None)):
                if owner is None:
                    continue
                for name in names:
                    runner = getattr(owner, name, None)
                    if runner is not None and id(runner) not in seen:
                        seen.add(id(runner))
                        yield label, runner

    def _require_panels_idle(self):
        """后台任务及结果回调应用完成前不切换工程。"""
        for label, runner in self._iter_calculation_runners():
            if runner.isRunning():
                raise RuntimeError(f'{label} 正在批量计算或执行其他计算任务，请等待计算完成后再切换工程。')

    # ----------------------------------------------------------------
    # 打开项目
    # ----------------------------------------------------------------
    def open_project(self, path: Optional[str] = None) -> bool:
        """打开项目，返回是否成功"""
        self.cancel_project_open()
        # 检查是否需要保存当前项目
        if not self._check_save_before_close():
            return False

        # 如果没有指定路径，弹出文件选择对话框
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                None,
                "打开项目",
                "",
                PROJECT_FILTER
            )
            if not path:
                return False

        # 检查文件是否存在
        if not os.path.exists(path):
            QMessageBox.warning(None, "错误", f"文件不存在：\n{path}")
            return False

        # 加载项目
        try:
            self._load_from_file(path)
            self._confirm_project_open(path)
            return True
        except Exception as e:
            QMessageBox.critical(None, "加载失败", f"无法加载项目文件：\n{e}")
            return False

    def open_project_async(self, path: Optional[str] = None) -> bool:
        """后台读取所选工程，成功后在界面线程完成未保存确认与恢复事务。"""
        if self._opening_path:
            self.status_message.emit("已有工程正在打开，可等待或取消当前打开操作。")
            return False
        if not path:
            path, _ = QFileDialog.getOpenFileName(self.parent(), "打开项目", "", PROJECT_FILTER)
            if not path:
                return False
        try:
            self._require_panels_idle()
        except RuntimeError as exc:
            self.status_message.emit(str(exc))
            return False

        path = os.fspath(path)
        name = os.path.basename(path)
        generation = self.session.generation
        start_path = self._current_path
        start_saved_revision = self.session.saved_revision
        target_path = os.path.normcase(os.path.abspath(path))

        def read(token):
            data = ProjectCodec.read(path)
            token.raise_if_cancelled()
            earthwork = data.get("earthwork_panel") or {}
            # Decode owns the original session snapshot. Detach the live
            # workbench state here, where copying a large result keeps Qt free.
            detached = copy.deepcopy(earthwork) if earthwork.get("kind") == "section_workbench" else None
            return data, detached

        def apply(decoded):
            if self.session.generation != generation:
                return
            if (self._current_path and os.path.normcase(os.path.abspath(self._current_path)) == target_path
                    and (self._current_path != start_path or self.session.saved_revision != start_saved_revision)):
                self.status_message.emit(f"项目 {name} 在读取期间已保存，继续使用当前内容。")
                return
            self._require_panels_idle()
            self.project_open_progress.emit(f"正在恢复项目 {name}", False)
            data, detached = decoded
            if not self.open_loaded_project(path, data, detached_earthwork=detached):
                cancelled()

        def failed(error):
            if self.session.generation == generation:
                detail = "找不到项目文件，可重新选择。" if isinstance(error, FileNotFoundError) else str(error)
                self.status_message.emit(f"打开项目 {name} 未完成。{detail}")

        def cancelled():
            if self.session.generation == generation:
                self.status_message.emit(f"已取消打开项目 {name}")

        self._opening_path = path
        self.project_open_progress.emit(f"正在读取项目 {name}", True)
        try:
            self._project_open_runner.submit(read, on_success=apply, on_error=failed, on_cancelled=cancelled)
        except RuntimeError as exc:
            self._on_project_open_running_changed(False)
            failed(exc)
            return False
        return True

    def cancel_project_open(self) -> None:
        if self._project_open_runner.isRunning():
            self._project_open_runner.cancel()
            self.project_open_progress.emit("正在取消打开项目，当前读取步骤结束后返回。", False)

    def _on_project_open_running_changed(self, running: bool) -> None:
        if not running:
            self._opening_path = ""
            self.project_open_progress.emit("", False)

    def open_loaded_project(self, path: str, data: Dict[str, Any], *, detached_earthwork=None) -> bool:
        """Commit a decoded project, optionally consuming two owned snapshots."""
        self.cancel_project_open()
        same_project = bool(self._current_path and os.path.normcase(os.path.abspath(self._current_path))
                            == os.path.normcase(os.path.abspath(path)))
        saved_revision = self.session.saved_revision
        if not self._check_save_before_close():
            return False
        # Saving the same file in the prompt makes the earlier read obsolete.
        if not same_project or saved_revision == self.session.saved_revision:
            self._apply_project_transaction(data, path, normalized=True, detached_earthwork=detached_earthwork)
        self._confirm_project_open(path)
        return True

    def _confirm_project_open(self, path: str) -> None:
        self._current_path = path
        self._clear_dirty()
        self._add_recent_project(path)
        self.project_changed.emit(path)
        self.status_message.emit(f"已打开项目: {os.path.basename(path)}")

    # ----------------------------------------------------------------
    # 保存项目
    # ----------------------------------------------------------------
    def save_project(self) -> bool:
        """保存项目（如果是新项目则另存为），返回是否成功"""
        if not self._current_path:
            return self.save_as_project()

        try:
            snapshot = self._save_to_file(self._current_path)
            self._confirm_saved(snapshot)
            self.status_message.emit(f"已保存: {os.path.basename(self._current_path)}")
            return True
        except Exception as e:
            QMessageBox.critical(None, "保存失败", f"无法保存项目：\n{e}")
            return False

    def save_as_project(self) -> bool:
        """另存为项目，返回是否成功"""
        # 生成默认文件名
        default_name = self._generate_default_filename()

        path, _ = QFileDialog.getSaveFileName(
            None,
            "另存为项目",
            default_name,
            PROJECT_FILTER
        )
        if not path:
            return False

        # 确保有正确的扩展名
        if not path.lower().endswith(PROJECT_EXT):
            path += PROJECT_EXT

        water_profile_panel = self._get_panel("water_profile_panel", create_missing=False)
        old_first_jump_marker = None
        marker_reset_applied = False
        if water_profile_panel and hasattr(water_profile_panel, "reset_first_success_auto_jump_marker"):
            try:
                if hasattr(water_profile_panel, "get_first_success_auto_jump_marker"):
                    old_first_jump_marker = water_profile_panel.get_first_success_auto_jump_marker()
                water_profile_panel.reset_first_success_auto_jump_marker()
                marker_reset_applied = True
            except Exception:
                marker_reset_applied = False

        try:
            snapshot = self._save_to_file(path)
            self._bind_manager_paths(path)
            self._current_path = path
            self.session.path = path
            self._confirm_saved(snapshot)
            self._add_recent_project(path)
            self.project_changed.emit(path)
            self.status_message.emit(f"已保存: {os.path.basename(path)}")
            return True
        except Exception as e:
            if marker_reset_applied and water_profile_panel and hasattr(water_profile_panel, "set_first_success_auto_jump_marker"):
                try:
                    water_profile_panel.set_first_success_auto_jump_marker(
                        bool(old_first_jump_marker)
                    )
                except Exception:
                    pass
            QMessageBox.critical(None, "保存失败", f"无法保存项目：\n{e}")
            return False

    def _generate_default_filename(self) -> str:
        """生成默认文件名：渠道名_级别_时间戳"""
        channel_name = "新项目"
        channel_level = ""

        primary_panel = self._get_primary_channel_panel(create_missing=False)
        if primary_panel:
            channel_name = primary_panel.channel_name_edit.text().strip() or "新项目"
            channel_level = primary_panel.channel_level_combo.currentText().strip()

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c for c in channel_name if c.isalnum() or c in "_ -")[:30]
        safe_level = "".join(c for c in channel_level if c.isalnum() or c in "_ -")[:10]

        if safe_level:
            return f"{safe_name}_{safe_level}_{timestamp}{PROJECT_EXT}"
        else:
            return f"{safe_name}_{timestamp}{PROJECT_EXT}"

    # ----------------------------------------------------------------
    # 关闭前检查
    # ----------------------------------------------------------------
    def _check_save_before_close(self) -> bool:
        """关闭/新建/打开前检查是否需要保存，返回是否继续"""
        debug_print(f"[DEBUG] _check_save_before_close called, _is_dirty={self._is_dirty}")
        if not self._is_dirty:
            return True

        debug_print(f"[DEBUG] Showing save dialog, parent={self.parent()}")
        result = fluent_save_discard_cancel(
            self.parent(),
            "保存项目",
            "当前项目有未保存的修改，是否保存？",
            save_text="保存",
            discard_text="放弃",
            cancel_text="取消"
        )
        debug_print(f"[DEBUG] Dialog result: {result}")

        if result == 'save':
            return self.save_project()
        elif result == 'discard':
            return True
        else:  # cancel
            return False

    def check_save_on_close(self) -> bool:
        """窗口关闭时检查保存，返回是否允许关闭"""
        return self._check_save_before_close()

    # ----------------------------------------------------------------
    # 文件读写与工程事务
    # ----------------------------------------------------------------
    def _bind_manager_paths(self, path: str) -> None:
        """路径绑定不触发磁盘读取，工程内容只由解码后的快照提交。"""
        for manager in (self._siphon_manager, self._pressure_pipe_manager):
            if manager is not None and hasattr(manager, 'bind_project_path'):
                manager.bind_project_path(path)

    def _save_to_file(self, path: str) -> ProjectSnapshot:
        """采集独立快照并原子写入，失败时保持旧工程与未保存状态。"""
        snapshot = self.session.capture(self._collect_project_data())
        saved_data = prepare_project_resources(snapshot.data, path)
        atomic_write_json(path, saved_data)
        return snapshot

    def _load_from_file(self, path: str) -> Dict[str, Any]:
        """先完成版本和关键数据块校验，再一次提交到运行时。"""
        data = ProjectCodec.read(path)
        self._apply_project_transaction(data, path, normalized=True)
        return data

    def _apply_project_transaction(self, data: Dict[str, Any], path: str, *, normalized: bool = False,
                                   detached_earthwork=None) -> None:
        """任一关键模块恢复失败即回滚，成功后才切换工程会话。"""
        self._require_panels_idle()
        previous = None if self._project_restore_error else self._collect_project_data()
        previous_path = self.session.path
        old_restoring = self._restoring_project
        self._restoring_project = True
        try:
            self._restore_project_data(data, normalized=normalized, detached_earthwork=detached_earthwork)
            self._bind_manager_paths(path)
        except Exception as exc:
            if previous is not None:
                try:
                    self._restore_project_data(previous)
                    self._bind_manager_paths(previous_path)
                except Exception as rollback_exc:
                    self._project_restore_error = str(rollback_exc)
                    raise RuntimeError(f'{exc}；恢复原界面也失败，已暂停保存，请重新打开工程。') from exc
            else:
                self._project_restore_error = str(exc)
            raise
        finally:
            self._restoring_project = old_restoring
        self.session.commit(data, path, take_ownership=detached_earthwork is not None)
        self._project_restore_error = ''

    def _collect_project_data(self, *, include_earthwork: bool = True) -> Dict[str, Any]:
        """收集所有面板数据"""
        if self._project_restore_error:
            raise RuntimeError('工程界面尚未完整恢复，请重新打开工程后再保存。')
        defaults = {
            "version": "2.0",
            "created_at": datetime.now().isoformat(),
            "merged_panel": None,
            "batch_panel": None,
            "water_profile_panel": None,
            "open_channel_panel": None,
            "aqueduct_panel": None,
            "tunnel_panel": None,
            "culvert_panel": None,
            "siphon_panel": None,
            "pressure_pipe_panel": None,
            "spillway_steep_chute_panel": None,
            "earthwork_panel": None,
            "siphon_manager_data": None,
            "pressure_pipe_manager_data": None,
            "report_meta": None,
        }
        data = self.session.copy_extra_fields(defaults)
        data.update(defaults)

        # ---- 合并面板（双写：merged_panel + water_profile_panel）----
        water_profile_data = None
        water_profile_panel = self._get_panel("water_profile_panel", create_missing=False)
        if water_profile_panel:
            try:
                water_profile_data = water_profile_panel.to_project_dict()
                data["merged_panel"] = water_profile_data
                data["water_profile_panel"] = water_profile_data
            except Exception as e:
                raise RuntimeError(f"收集水面线数据失败：{e}") from e

        # ---- 批量面板（双写窗口：优先真实batch_panel，否则写兼容块）----
        batch_panel = self._get_panel("batch_panel", create_missing=False)
        if batch_panel:
            try:
                data["batch_panel"] = batch_panel.to_project_dict()
            except Exception as e:
                raise RuntimeError(f"收集批量计算数据失败：{e}") from e
        elif isinstance(water_profile_data, dict):
            compat_batch = water_profile_data.get("batch_panel_compat")
            if isinstance(compat_batch, dict) and compat_batch:
                data["batch_panel"] = compat_batch

        # ---- 其余面板数据 ----
        excluded_slots = {"water_profile_panel"}
        if not include_earthwork:
            excluded_slots.add("earthwork_panel")
        for key, panel, label in self._iter_project_panel_entries(
            create_missing=False, exclude_slots=excluded_slots
        ):
            if panel:
                try:
                    data[key] = panel.to_project_dict()
                except Exception as e:
                    raise RuntimeError(f"收集 {label} 数据失败：{e}") from e

        # ---- Manager 数据 ----
        if self._siphon_manager:
            try:
                data["siphon_manager_data"] = self._siphon_manager.to_dict()
            except Exception as e:
                raise RuntimeError(f"收集倒虹吸管理数据失败：{e}") from e

        if self._pressure_pipe_manager:
            try:
                data["pressure_pipe_manager_data"] = self._pressure_pipe_manager.to_dict()
            except Exception as e:
                raise RuntimeError(f"收集有压管道管理数据失败：{e}") from e

        # ---- 项目设置（report_meta）双写：存入 .qxproj 同时保留 QSettings ----
        try:
            from app_渠系计算前端.report_meta import load_meta
            meta = load_meta()
            from dataclasses import asdict
            data["report_meta"] = asdict(meta)
        except Exception as e:
            raise RuntimeError(f"收集项目设置失败：{e}") from e

        return data

    def collect_earthwork_source(self) -> Dict[str, Any]:
        """Recover an equivalent saved water calculation after an older batch sync."""
        current = self._collect_project_data(include_earthwork=False)
        live = current.get("merged_panel") or current.get("water_profile_panel") or {}
        if (live.get("calculated_nodes") or not live.get("water_result_input_signature")
                or not self.current_path or self.session.path != self.current_path):
            return current

        from app_渠系计算前端.water_profile.panel import EDITABLE_COLS
        from app_渠系计算前端.water_profile.saved_results import matches_batch_resync

        try:
            saved = ProjectCodec.read(self.current_path)
        except (OSError, ValueError):
            return current
        water = saved.get("merged_panel") or saved.get("water_profile_panel") or {}
        manager_slots = ("pressure_pipe_manager_data", "siphon_manager_data")
        if (any(saved.get(key) != current.get(key) for key in manager_slots)
                or not matches_batch_resync(live, water, EDITABLE_COLS)):
            return current
        self._require_panels_idle()
        panel = self._get_panel("water_profile_panel", create_missing=False)
        if panel is None:
            return current
        try:
            self._restore_panel("water_profile_panel", panel, water)
            if not panel.is_water_result_current():
                raise ValueError("项目文件中的水面线成果与恢复后的输入不一致。")
        except Exception:
            self._restore_panel("water_profile_panel", panel, live)
            raise
        snapshot = self._collect_project_data(include_earthwork=False)
        snapshot["earthwork_recovered_saved_water"] = True
        return snapshot

    def _restore_project_data(self, data: Dict[str, Any], *, normalized: bool = False, detached_earthwork=None):
        """恢复所有面板数据"""
        if not normalized:
            data = ProjectCodec.normalize(data)
        if detached_earthwork is not None:
            data = {**data, "earthwork_panel": detached_earthwork}
        if (data.get("earthwork_panel") or {}).get("kind") == "section_workbench":
            from 土石方计算.adapters.workbench_sources import with_saved_batch_bore_diameters
            from 土石方计算.services.pipe_profile_sources import with_saved_water_axes
            data = with_saved_batch_bore_diameters(with_saved_water_axes(data))
        existing_slots = {
            slot for slot, panel, _label in self._iter_project_panel_entries(create_missing=False)
            if panel is not None
        }
        batch_panel_data = data.get("batch_panel")
        water_profile_data = data.get("merged_panel") or data.get("water_profile_panel")
        # 没有保存数据的未访问页面继续保持未创建；已有页面仍需清空旧工程状态。
        water_profile_panel = self._get_panel("water_profile_panel", create_missing=bool(water_profile_data))
        if water_profile_panel:
            try:
                self._restore_panel('water_profile_panel', water_profile_panel, water_profile_data)
            except Exception as e:
                raise RuntimeError(f"恢复水面线数据失败：{e}") from e
            earthwork = data.get("earthwork_panel") or {}
            if earthwork.get("kind") == "section_workbench" and earthwork.get("source_project_hash"):
                from app_渠系计算前端.water_profile.saved_results import (
                    has_legacy_earthwork_source, restored_legacy_earthwork_source_hash,
                )

                if has_legacy_earthwork_source(water_profile_data or {}):
                    live_water = water_profile_panel.to_project_dict()
                    restored_hash = restored_legacy_earthwork_source_hash(data, live_water)
                    if restored_hash:
                        data = {**data, "earthwork_panel": {**earthwork, "source_project_hash": restored_hash}}

        # ---- 兼容恢复 batch_panel（老界面/回滚版本需要）----
        if (not batch_panel_data) and isinstance(water_profile_data, dict):
            compat_batch = water_profile_data.get("batch_panel_compat")
            if isinstance(compat_batch, dict):
                batch_panel_data = compat_batch
        batch_panel = self._get_panel("batch_panel")
        if batch_panel and batch_panel_data:
            try:
                self._restore_panel('batch_panel', batch_panel, batch_panel_data)
            except Exception as e:
                raise RuntimeError(f"恢复批量计算数据失败：{e}") from e

        # ---- 其余面板数据 ----
        for key, panel, label in self._iter_project_panel_entries(
            create_missing=False, exclude_slots={"water_profile_panel"}
        ):
            if panel is None and data.get(key):
                panel = self._get_panel(key)
            if panel and (data.get(key) or key in existing_slots):
                try:
                    self._restore_panel(key, panel, data.get(key),
                                        take_ownership=key == "earthwork_panel" and detached_earthwork is not None)
                except Exception as e:
                    raise RuntimeError(f"恢复 {label} 数据失败：{e}") from e

        # ---- Manager 数据 ----
        if self._siphon_manager and data.get("siphon_manager_data"):
            try:
                self._siphon_manager.from_dict(data["siphon_manager_data"])
            except Exception as e:
                raise RuntimeError(f"恢复倒虹吸管理数据失败：{e}") from e

        if self._pressure_pipe_manager and data.get("pressure_pipe_manager_data"):
            try:
                self._pressure_pipe_manager.from_dict(data["pressure_pipe_manager_data"])
            except Exception as e:
                raise RuntimeError(f"恢复有压管道管理数据失败：{e}") from e

        # ---- 项目设置（report_meta）双写：从 .qxproj 恢复并同步到 QSettings ----
        if data.get("report_meta"):
            try:
                from app_渠系计算前端.report_meta import ReportMeta, save_meta
                meta_dict = data["report_meta"]
                meta = ReportMeta(**meta_dict)
                save_meta(meta)
            except Exception as e:
                raise RuntimeError(f"恢复报告信息失败：{e}") from e

        self._reset_on_first_visit = {
            slot for slot, panel, _label in self._iter_project_panel_entries(create_missing=False)
            if panel is None
        }

    # ----------------------------------------------------------------
    # 最近项目
    # ----------------------------------------------------------------
    def _load_recent_projects(self):
        """从 QSettings 加载最近项目列表"""
        settings = QSettings("ShuiFa", "QuxiDesign")
        self._recent_projects = settings.value("recent_projects", []) or []
        # 过滤掉不存在的文件
        self._recent_projects = [p for p in self._recent_projects if os.path.exists(p)]

    def _save_recent_projects(self):
        """保存最近项目列表到 QSettings"""
        settings = QSettings("ShuiFa", "QuxiDesign")
        settings.setValue("recent_projects", self._recent_projects)

    def _add_recent_project(self, path: str):
        """添加项目到最近项目列表"""
        # 移除已存在的相同路径
        if path in self._recent_projects:
            self._recent_projects.remove(path)

        # 添加到列表开头
        self._recent_projects.insert(0, path)

        # 限制数量
        self._recent_projects = self._recent_projects[:MAX_RECENT_PROJECTS]

        # 保存
        self._save_recent_projects()

    def clear_recent_projects(self):
        """清空最近项目列表"""
        self._recent_projects.clear()
        self._save_recent_projects()

    # ----------------------------------------------------------------
    # 窗口标题
    # ----------------------------------------------------------------
    def get_window_title(self, base_title: str) -> str:
        """获取窗口标题，包含项目名和修改标记"""
        if self._current_path:
            project_name = os.path.basename(self._current_path)
        else:
            project_name = "新项目"

        dirty_mark = " *" if self._is_dirty else ""
        return f"{project_name}{dirty_mark} - {base_title}"
