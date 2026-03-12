# -*- coding: utf-8 -*-
"""
项目管理器 —— 负责项目的新建、打开、保存、自动保存等操作
"""

import json
import os
from datetime import datetime
from typing import Optional, Any, Dict, List, TYPE_CHECKING

from PySide6.QtCore import QObject, Signal, QTimer, QSettings
from PySide6.QtWidgets import QFileDialog, QMessageBox

from app_渠系计算前端.styles import fluent_save_discard_cancel

if TYPE_CHECKING:
    from app_渠系计算前端.batch.panel import BatchPanel
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

    def __init__(self, parent=None):
        super().__init__(parent)

        # ---- 状态 ----
        self._current_path: str = ""     # 当前项目路径（空串表示新建未保存）
        self._is_dirty: bool = False     # 是否有未保存的修改

        # ---- 面板引用（由 MainWindow 设置）----
        self._batch_panel: Optional["BatchPanel"] = None
        self._water_profile_panel: Optional["WaterProfilePanel"] = None
        self._open_channel_panel: Optional["OpenChannelPanel"] = None
        self._aqueduct_panel: Optional["AqueductPanel"] = None
        self._tunnel_panel: Optional["TunnelPanel"] = None
        self._culvert_panel: Optional["CulvertPanel"] = None
        self._siphon_panel: Optional["SiphonPanel"] = None
        self._pressure_pipe_panel: Optional["PressurePipePanel"] = None
        self._earthwork_panel = None

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
    # 面板设置
    # ----------------------------------------------------------------
    def set_panels(
        self,
        batch_panel: "BatchPanel" = None,
        water_profile_panel: "WaterProfilePanel" = None,
        open_channel_panel: "OpenChannelPanel" = None,
        aqueduct_panel: "AqueductPanel" = None,
        tunnel_panel: "TunnelPanel" = None,
        culvert_panel: "CulvertPanel" = None,
        siphon_panel: "SiphonPanel" = None,
        pressure_pipe_panel: "PressurePipePanel" = None,
        earthwork_panel=None,
        siphon_manager: "SiphonManager" = None,
        pressure_pipe_manager: "PressurePipeManager" = None,
    ):
        """设置需要管理的面板引用，并连接脏状态信号"""
        self._batch_panel = batch_panel
        self._water_profile_panel = water_profile_panel
        self._open_channel_panel = open_channel_panel
        self._aqueduct_panel = aqueduct_panel
        self._tunnel_panel = tunnel_panel
        self._culvert_panel = culvert_panel
        self._siphon_panel = siphon_panel
        self._pressure_pipe_panel = pressure_pipe_panel
        self._earthwork_panel = earthwork_panel
        self._siphon_manager = siphon_manager
        self._pressure_pipe_manager = pressure_pipe_manager

        # 连接面板的data_changed信号到mark_dirty
        for panel in [batch_panel, water_profile_panel, open_channel_panel,
                      aqueduct_panel, tunnel_panel, culvert_panel,
                      siphon_panel, pressure_pipe_panel, earthwork_panel]:
            if panel and hasattr(panel, 'data_changed'):
                panel.data_changed.connect(self.mark_dirty)

    # ----------------------------------------------------------------
    # 脏状态管理
    # ----------------------------------------------------------------
    def mark_dirty(self):
        """标记项目为已修改"""
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
        """执行自动保存"""
        if not self._is_dirty:
            return

        try:
            auto_save_path = self._get_auto_save_path()
            self._save_to_file(auto_save_path)
            self.status_message.emit(f"自动保存完成: {os.path.basename(auto_save_path)}")
            self._cleanup_old_auto_saves(os.path.dirname(auto_save_path))
        except Exception as e:
            self.status_message.emit(f"自动保存失败: {e}")

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
        if self._batch_panel:
            channel_name = self._batch_panel.channel_name_edit.text().strip() or "未命名"
            channel_level = self._batch_panel.channel_level_combo.currentText().strip()
        elif self._water_profile_panel:
            channel_name = self._water_profile_panel.channel_name_edit.text().strip() or "未命名"
            channel_level = self._water_profile_panel.channel_level_combo.currentText().strip()

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
        # 检查是否需要保存当前项目
        if not self._check_save_before_close():
            return False

        # 清空面板数据
        self._reset_panels()

        # 重置状态
        self._current_path = ""
        self._clear_dirty()
        self.project_changed.emit("")
        self.status_message.emit("已新建项目")
        return True

    def _reset_panels(self):
        """重置所有面板到初始状态"""
        if self._batch_panel:
            try:
                # 清空表格
                self._batch_panel.input_table.setRowCount(0)
                self._batch_panel.channel_name_edit.clear()
                self._batch_panel.start_wl_edit.clear()
                self._batch_panel.start_station_edit.setText("0")
                self._batch_panel.channel_level_combo.setCurrentIndex(0)
                self._batch_panel.batch_results.clear()
            except Exception:
                pass

        if self._water_profile_panel:
            try:
                # 清空表格和数据
                self._water_profile_panel.nodes.clear()
                self._water_profile_panel.calculated_nodes.clear()
                self._water_profile_panel._update_table_from_nodes_full()
                if hasattr(self._water_profile_panel, "_clear_section_tables"):
                    self._water_profile_panel._clear_section_tables()
                self._water_profile_panel.channel_name_edit.clear()
                self._water_profile_panel.start_wl_edit.clear()
                self._water_profile_panel.design_flow_edit.clear()
                self._water_profile_panel.max_flow_edit.clear()
                self._water_profile_panel.start_station_edit.setText("0")
                self._water_profile_panel.roughness_edit.setText("0.017")
                self._water_profile_panel.channel_level_combo.setCurrentIndex(0)
            except Exception:
                pass

    # ----------------------------------------------------------------
    # 打开项目
    # ----------------------------------------------------------------
    def open_project(self, path: Optional[str] = None) -> bool:
        """打开项目，返回是否成功"""
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
            data = self._load_from_file(path)
            self._current_path = path
            self._clear_dirty()
            self._add_recent_project(path)
            self.project_changed.emit(path)
            # project_changed 信号会触发 set_project_path，可能覆盖刚恢复的 manager 数据
            # 对于新版 .qxproj（含 manager 数据），需要重新应用以确保 .qxproj 数据为准
            self._reapply_manager_data(data)
            self.status_message.emit(f"已打开项目: {os.path.basename(path)}")
            return True
        except Exception as e:
            QMessageBox.critical(None, "加载失败", f"无法加载项目文件：\n{e}")
            return False

    # ----------------------------------------------------------------
    # 保存项目
    # ----------------------------------------------------------------
    def save_project(self) -> bool:
        """保存项目（如果是新项目则另存为），返回是否成功"""
        if not self._current_path:
            return self.save_as_project()

        try:
            self._save_to_file(self._current_path)
            self._clear_dirty()
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

        old_first_jump_marker = None
        marker_reset_applied = False
        if self._water_profile_panel and hasattr(self._water_profile_panel, "reset_first_success_auto_jump_marker"):
            try:
                if hasattr(self._water_profile_panel, "get_first_success_auto_jump_marker"):
                    old_first_jump_marker = self._water_profile_panel.get_first_success_auto_jump_marker()
                self._water_profile_panel.reset_first_success_auto_jump_marker()
                marker_reset_applied = True
            except Exception:
                marker_reset_applied = False

        try:
            self._save_to_file(path)
            self._current_path = path
            self._clear_dirty()
            self._add_recent_project(path)
            # 快照 manager 数据，防止 project_changed 触发 set_project_path 时被覆盖/清空
            manager_snapshot = self._snapshot_manager_data()
            self.project_changed.emit(path)
            self._reapply_manager_data(manager_snapshot)
            self.status_message.emit(f"已保存: {os.path.basename(path)}")
            return True
        except Exception as e:
            if marker_reset_applied and self._water_profile_panel and hasattr(self._water_profile_panel, "set_first_success_auto_jump_marker"):
                try:
                    self._water_profile_panel.set_first_success_auto_jump_marker(
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

        if self._batch_panel:
            channel_name = self._batch_panel.channel_name_edit.text().strip() or "新项目"
            channel_level = self._batch_panel.channel_level_combo.currentText().strip()
        elif self._water_profile_panel:
            channel_name = self._water_profile_panel.channel_name_edit.text().strip() or "新项目"
            channel_level = self._water_profile_panel.channel_level_combo.currentText().strip()

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
        print(f"[DEBUG] _check_save_before_close called, _is_dirty={self._is_dirty}")
        if not self._is_dirty:
            return True

        print(f"[DEBUG] Showing save dialog, parent={self.parent()}")
        result = fluent_save_discard_cancel(
            self.parent(),
            "保存项目",
            "当前项目有未保存的修改，是否保存？",
            save_text="保存",
            discard_text="放弃",
            cancel_text="取消"
        )
        print(f"[DEBUG] Dialog result: {result}")

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
    # Manager 数据保护（防止 set_project_path 覆盖）
    # ----------------------------------------------------------------
    def _snapshot_manager_data(self) -> Dict[str, Any]:
        """快照当前 manager 内存数据"""
        result: Dict[str, Any] = {}
        if self._siphon_manager:
            try:
                result["siphon_manager_data"] = self._siphon_manager.to_dict()
            except Exception:
                pass
        if self._pressure_pipe_manager:
            try:
                result["pressure_pipe_manager_data"] = self._pressure_pipe_manager.to_dict()
            except Exception:
                pass
        return result

    def _reapply_manager_data(self, data: Dict[str, Any]):
        """将 manager 数据重新写回（仅当数据存在时覆盖）"""
        if self._siphon_manager and data.get("siphon_manager_data"):
            try:
                self._siphon_manager.from_dict(data["siphon_manager_data"])
            except Exception as e:
                print(f"[ProjectManager] 重新应用SiphonManager数据失败: {e}")
        if self._pressure_pipe_manager and data.get("pressure_pipe_manager_data"):
            try:
                self._pressure_pipe_manager.from_dict(data["pressure_pipe_manager_data"])
            except Exception as e:
                print(f"[ProjectManager] 重新应用PressurePipeManager数据失败: {e}")

    # ----------------------------------------------------------------
    # 文件读写
    # ----------------------------------------------------------------
    def _save_to_file(self, path: str):
        """保存项目到文件"""
        data = self._collect_project_data()

        # 确保目录存在
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load_from_file(self, path: str) -> Dict[str, Any]:
        """从文件加载项目，返回原始数据字典"""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self._restore_project_data(data)
        return data

    def _collect_project_data(self) -> Dict[str, Any]:
        """收集所有面板数据"""
        data = {
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
            "earthwork_panel": None,
            "siphon_manager_data": None,
            "pressure_pipe_manager_data": None,
            "report_meta": None,
        }

        # ---- 合并面板（双写：merged_panel + water_profile_panel）----
        water_profile_data = None
        if self._water_profile_panel:
            try:
                water_profile_data = self._water_profile_panel.to_project_dict()
                data["merged_panel"] = water_profile_data
                data["water_profile_panel"] = water_profile_data
            except Exception as e:
                print(f"[ProjectManager] 收集WaterProfilePanel数据失败: {e}")

        # ---- 批量面板（双写窗口：优先真实batch_panel，否则写兼容块）----
        if self._batch_panel:
            try:
                data["batch_panel"] = self._batch_panel.to_project_dict()
            except Exception as e:
                print(f"[ProjectManager] 收集BatchPanel数据失败: {e}")
        elif isinstance(water_profile_data, dict):
            compat_batch = water_profile_data.get("batch_panel_compat")
            if isinstance(compat_batch, dict) and compat_batch:
                data["batch_panel"] = compat_batch

        # ---- 其余面板数据 ----
        _panel_keys = [
            ("open_channel_panel", self._open_channel_panel, "OpenChannelPanel"),
            ("aqueduct_panel", self._aqueduct_panel, "AqueductPanel"),
            ("tunnel_panel", self._tunnel_panel, "TunnelPanel"),
            ("culvert_panel", self._culvert_panel, "CulvertPanel"),
            ("siphon_panel", self._siphon_panel, "SiphonPanel"),
            ("pressure_pipe_panel", self._pressure_pipe_panel, "PressurePipePanel"),
            ("earthwork_panel", self._earthwork_panel, "EarthworkPanel"),
        ]
        for key, panel, label in _panel_keys:
            if panel:
                try:
                    data[key] = panel.to_project_dict()
                except Exception as e:
                    print(f"[ProjectManager] 收集{label}数据失败: {e}")

        # ---- Manager 数据 ----
        if self._siphon_manager:
            try:
                data["siphon_manager_data"] = self._siphon_manager.to_dict()
            except Exception as e:
                print(f"[ProjectManager] 收集SiphonManager数据失败: {e}")

        if self._pressure_pipe_manager:
            try:
                data["pressure_pipe_manager_data"] = self._pressure_pipe_manager.to_dict()
            except Exception as e:
                print(f"[ProjectManager] 收集PressurePipeManager数据失败: {e}")

        # ---- 项目设置（report_meta）双写：存入 .qxproj 同时保留 QSettings ----
        try:
            from app_渠系计算前端.report_meta import load_meta
            meta = load_meta()
            from dataclasses import asdict
            data["report_meta"] = asdict(meta)
        except Exception as e:
            print(f"[ProjectManager] 收集report_meta数据失败: {e}")

        return data

    def _restore_project_data(self, data: Dict[str, Any]):
        """恢复所有面板数据"""
        # ---- 合并面板恢复（读取优先级：merged_panel > water_profile_panel）----
        batch_panel_data = data.get("batch_panel")
        merged_panel_data = data.get("merged_panel")
        water_profile_data = merged_panel_data if merged_panel_data else data.get("water_profile_panel")
        if isinstance(water_profile_data, dict) and isinstance(batch_panel_data, dict):
            if not isinstance(water_profile_data.get("batch_panel_compat"), dict):
                water_profile_data = dict(water_profile_data)
                water_profile_data["batch_panel_compat"] = batch_panel_data
        if self._water_profile_panel and water_profile_data:
            try:
                self._water_profile_panel.from_project_dict(water_profile_data, skip_dirty_signal=True)
            except Exception as e:
                print(f"[ProjectManager] 恢复WaterProfilePanel数据失败: {e}")

        # ---- 兼容恢复 batch_panel（老界面/回滚版本需要）----
        if (not batch_panel_data) and isinstance(water_profile_data, dict):
            compat_batch = water_profile_data.get("batch_panel_compat")
            if isinstance(compat_batch, dict):
                batch_panel_data = compat_batch
        if self._batch_panel and batch_panel_data:
            try:
                self._batch_panel.from_project_dict(batch_panel_data, skip_dirty_signal=True)
            except Exception as e:
                print(f"[ProjectManager] 恢复BatchPanel数据失败: {e}")

        # ---- 其余面板数据 ----
        _panel_keys = [
            ("open_channel_panel", self._open_channel_panel, "OpenChannelPanel"),
            ("aqueduct_panel", self._aqueduct_panel, "AqueductPanel"),
            ("tunnel_panel", self._tunnel_panel, "TunnelPanel"),
            ("culvert_panel", self._culvert_panel, "CulvertPanel"),
            ("siphon_panel", self._siphon_panel, "SiphonPanel"),
            ("pressure_pipe_panel", self._pressure_pipe_panel, "PressurePipePanel"),
            ("earthwork_panel", self._earthwork_panel, "EarthworkPanel"),
        ]
        for key, panel, label in _panel_keys:
            if panel and data.get(key):
                try:
                    panel.from_project_dict(data[key])
                except Exception as e:
                    print(f"[ProjectManager] 恢复{label}数据失败: {e}")

        # ---- Manager 数据 ----
        if self._siphon_manager and data.get("siphon_manager_data"):
            try:
                self._siphon_manager.from_dict(data["siphon_manager_data"])
            except Exception as e:
                print(f"[ProjectManager] 恢复SiphonManager数据失败: {e}")

        if self._pressure_pipe_manager and data.get("pressure_pipe_manager_data"):
            try:
                self._pressure_pipe_manager.from_dict(data["pressure_pipe_manager_data"])
            except Exception as e:
                print(f"[ProjectManager] 恢复PressurePipeManager数据失败: {e}")

        # ---- 项目设置（report_meta）双写：从 .qxproj 恢复并同步到 QSettings ----
        if data.get("report_meta"):
            try:
                from app_渠系计算前端.report_meta import ReportMeta, save_meta
                meta_dict = data["report_meta"]
                meta = ReportMeta(**meta_dict)
                save_meta(meta)
            except Exception as e:
                print(f"[ProjectManager] 恢复report_meta数据失败: {e}")

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
