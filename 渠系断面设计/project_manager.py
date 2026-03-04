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

from 渠系断面设计.styles import fluent_save_discard_cancel

if TYPE_CHECKING:
    from 渠系断面设计.batch.panel import BatchPanel
    from 渠系断面设计.water_profile.panel import WaterProfilePanel
    from 渠系断面设计.open_channel.panel import OpenChannelPanel
    from 渠系断面设计.aqueduct.panel import AqueductPanel
    from 渠系断面设计.tunnel.panel import TunnelPanel
    from 渠系断面设计.culvert.panel import CulvertPanel
    from 渠系断面设计.siphon.panel import SiphonPanel
    from 渠系断面设计.pressure_pipe.panel import PressurePipePanel


# 项目文件扩展名
PROJECT_EXT = ".qxproj"
PROJECT_FILTER = f"渠系项目文件 (*{PROJECT_EXT})"

# 自动保存目录（相对于程序目录）
AUTO_SAVE_DIR = "data"

# 自动保存间隔（毫秒）
AUTO_SAVE_INTERVAL_MS = 60_000  # 1分钟

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

        # 连接面板的data_changed信号到mark_dirty
        if batch_panel and hasattr(batch_panel, 'data_changed'):
            batch_panel.data_changed.connect(self.mark_dirty)
        if water_profile_panel and hasattr(water_profile_panel, 'data_changed'):
            water_profile_panel.data_changed.connect(self.mark_dirty)
        if open_channel_panel and hasattr(open_channel_panel, 'data_changed'):
            open_channel_panel.data_changed.connect(self.mark_dirty)
        if aqueduct_panel and hasattr(aqueduct_panel, 'data_changed'):
            aqueduct_panel.data_changed.connect(self.mark_dirty)
        if tunnel_panel and hasattr(tunnel_panel, 'data_changed'):
            tunnel_panel.data_changed.connect(self.mark_dirty)
        if culvert_panel and hasattr(culvert_panel, 'data_changed'):
            culvert_panel.data_changed.connect(self.mark_dirty)
        if siphon_panel and hasattr(siphon_panel, 'data_changed'):
            siphon_panel.data_changed.connect(self.mark_dirty)
        if pressure_pipe_panel and hasattr(pressure_pipe_panel, 'data_changed'):
            pressure_pipe_panel.data_changed.connect(self.mark_dirty)

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
        except Exception as e:
            self.status_message.emit(f"自动保存失败: {e}")

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
            self._load_from_file(path)
            self._current_path = path
            self._clear_dirty()
            self._add_recent_project(path)
            self.project_changed.emit(path)
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

        try:
            self._save_to_file(path)
            self._current_path = path
            self._clear_dirty()
            self._add_recent_project(path)
            self.project_changed.emit(path)
            self.status_message.emit(f"已保存: {os.path.basename(path)}")
            return True
        except Exception as e:
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
    # 文件读写
    # ----------------------------------------------------------------
    def _save_to_file(self, path: str):
        """保存项目到文件"""
        data = self._collect_project_data()

        # 确保目录存在
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load_from_file(self, path: str):
        """从文件加载项目"""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self._restore_project_data(data)

    def _collect_project_data(self) -> Dict[str, Any]:
        """收集所有面板数据"""
        data = {
            "version": "1.1",
            "created_at": datetime.now().isoformat(),
            "batch_panel": None,
            "water_profile_panel": None,
            "open_channel_panel": None,
            "aqueduct_panel": None,
            "tunnel_panel": None,
            "culvert_panel": None,
            "siphon_panel": None,
            "pressure_pipe_panel": None,
        }

        if self._batch_panel:
            try:
                data["batch_panel"] = self._batch_panel.to_project_dict()
            except Exception as e:
                print(f"[ProjectManager] 收集BatchPanel数据失败: {e}")

        if self._water_profile_panel:
            try:
                data["water_profile_panel"] = self._water_profile_panel.to_project_dict()
            except Exception as e:
                print(f"[ProjectManager] 收集WaterProfilePanel数据失败: {e}")

        if self._open_channel_panel:
            try:
                data["open_channel_panel"] = self._open_channel_panel.to_project_dict()
            except Exception as e:
                print(f"[ProjectManager] 收集OpenChannelPanel数据失败: {e}")

        if self._aqueduct_panel:
            try:
                data["aqueduct_panel"] = self._aqueduct_panel.to_project_dict()
            except Exception as e:
                print(f"[ProjectManager] 收集AqueductPanel数据失败: {e}")

        if self._tunnel_panel:
            try:
                data["tunnel_panel"] = self._tunnel_panel.to_project_dict()
            except Exception as e:
                print(f"[ProjectManager] 收集TunnelPanel数据失败: {e}")

        if self._culvert_panel:
            try:
                data["culvert_panel"] = self._culvert_panel.to_project_dict()
            except Exception as e:
                print(f"[ProjectManager] 收集CulvertPanel数据失败: {e}")

        if self._siphon_panel:
            try:
                data["siphon_panel"] = self._siphon_panel.to_project_dict()
            except Exception as e:
                print(f"[ProjectManager] 收集SiphonPanel数据失败: {e}")

        if self._pressure_pipe_panel:
            try:
                data["pressure_pipe_panel"] = self._pressure_pipe_panel.to_project_dict()
            except Exception as e:
                print(f"[ProjectManager] 收集PressurePipePanel数据失败: {e}")

        return data

    def _restore_project_data(self, data: Dict[str, Any]):
        """恢复所有面板数据"""
        if self._batch_panel and data.get("batch_panel"):
            try:
                self._batch_panel.from_project_dict(data["batch_panel"])
            except Exception as e:
                print(f"[ProjectManager] 恢复BatchPanel数据失败: {e}")

        if self._water_profile_panel and data.get("water_profile_panel"):
            try:
                self._water_profile_panel.from_project_dict(data["water_profile_panel"])
            except Exception as e:
                print(f"[ProjectManager] 恢复WaterProfilePanel数据失败: {e}")

        if self._open_channel_panel and data.get("open_channel_panel"):
            try:
                self._open_channel_panel.from_project_dict(data["open_channel_panel"])
            except Exception as e:
                print(f"[ProjectManager] 恢复OpenChannelPanel数据失败: {e}")

        if self._aqueduct_panel and data.get("aqueduct_panel"):
            try:
                self._aqueduct_panel.from_project_dict(data["aqueduct_panel"])
            except Exception as e:
                print(f"[ProjectManager] 恢复AqueductPanel数据失败: {e}")

        if self._tunnel_panel and data.get("tunnel_panel"):
            try:
                self._tunnel_panel.from_project_dict(data["tunnel_panel"])
            except Exception as e:
                print(f"[ProjectManager] 恢复TunnelPanel数据失败: {e}")

        if self._culvert_panel and data.get("culvert_panel"):
            try:
                self._culvert_panel.from_project_dict(data["culvert_panel"])
            except Exception as e:
                print(f"[ProjectManager] 恢复CulvertPanel数据失败: {e}")

        if self._siphon_panel and data.get("siphon_panel"):
            try:
                self._siphon_panel.from_project_dict(data["siphon_panel"])
            except Exception as e:
                print(f"[ProjectManager] 恢复SiphonPanel数据失败: {e}")

        if self._pressure_pipe_panel and data.get("pressure_pipe_panel"):
            try:
                self._pressure_pipe_panel.from_project_dict(data["pressure_pipe_panel"])
            except Exception as e:
                print(f"[ProjectManager] 恢复PressurePipePanel数据失败: {e}")

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
