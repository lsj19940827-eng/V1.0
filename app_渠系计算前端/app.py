# -*- coding: utf-8 -*-
"""
渠系建筑物水力计算系统 —— 主入口

侧边导航 + 面板切换框架
支持模块：明渠设计、渡槽设计、隧洞设计、暗涵设计、倒虹吸设计、有压管道设计、推求水面线
"""

import os

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QFrame, QStackedWidget, QSizePolicy, QMenu
)
from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QIcon, QShortcut, QKeySequence, QAction

from qfluentwidgets import (
    PushButton, InfoBar, InfoBarPosition
)

from app_渠系计算前端.panel_registry import PanelDescriptor, PanelRegistry
from version import APP_VERSION
from app_渠系计算前端.styles import (
    P, BD, T1, T2, NAV_STYLE
)
from app_渠系计算前端.report_meta import ProjectSettingsDialog
from app_渠系计算前端.project_manager import ProjectManager
from app_渠系计算前端.startup_context import StartupContext
from app_渠系计算前端.webengine_diagnostics import EMERGENCY_SINGLE_PROCESS_ENV
from app_渠系计算前端.debug_utils import debug_print
from app_渠系计算前端.bootstrap import _resolve_app_icon_path

_MODULE_TOOLTIPS = {
    "open_channel": "梯形/矩形/圆形明渠",
    "aqueduct": "U形/矩形渡槽",
    "tunnel": "圆形/圆拱直墙/马蹄形",
    "culvert": "矩形/圆拱直墙型暗涵",
    "siphon": "倒虹吸管水力计算",
    "pressure_pipe": "有压管道水力计算",
    "water_profile": "断面批量计算 + 水面线推求",
}


def _create_open_channel_panel():
    from app_渠系计算前端.open_channel.panel import OpenChannelPanel

    return OpenChannelPanel()


def _create_aqueduct_panel():
    from app_渠系计算前端.aqueduct.panel import AqueductPanel

    return AqueductPanel()


def _create_tunnel_panel():
    from app_渠系计算前端.tunnel.panel import TunnelPanel

    return TunnelPanel()


def _create_culvert_panel():
    from app_渠系计算前端.culvert.panel import CulvertPanel

    return CulvertPanel()


def _create_siphon_panel(*, siphon_manager):
    from app_渠系计算前端.siphon.panel import SiphonPanel

    return SiphonPanel(
        siphon_manager=siphon_manager,
        siphon_name="单倒虹吸",
    )


def _create_pressure_pipe_panel():
    from app_渠系计算前端.pressure_pipe.panel import PressurePipePanel

    return PressurePipePanel()


def _create_water_profile_panel(*, siphon_manager, pressure_pipe_manager):
    from app_渠系计算前端.water_profile.panel import WaterProfilePanel

    return WaterProfilePanel(
        siphon_manager=siphon_manager,
        pressure_pipe_manager=pressure_pipe_manager,
    )


class NavButton(PushButton):
    """侧边导航按钮（选中态高亮）"""

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setText(text)
        self._selected = False
        self.setFixedHeight(42)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._update_style()

    def set_selected(self, selected: bool):
        self._selected = selected
        self._update_style()

    def _update_style(self):
        if self._selected:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: {P}; color: white;
                    border: none; border-radius: 6px;
                    font-size: 13px; font-weight: bold;
                    text-align: left; padding: 0 16px;
                }}
                QPushButton:hover {{ background: #1565C0; }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {T1};
                    border: none; border-radius: 6px;
                    font-size: 13px;
                    text-align: left; padding: 0 16px;
                }}
                QPushButton:hover {{ background: #E8EAF6; }}
            """)


# ============================================================
# 主窗口
# ============================================================
class MainWindow(QMainWindow):
    """渠系建筑物水力计算系统 —— 主窗口"""

    def __init__(self, startup_context: StartupContext):
        super().__init__()
        self.startup_context = startup_context
        self._base_title = f"渠系建筑物水力计算系统 V{APP_VERSION}"
        self.setWindowTitle(self._base_title)
        self._cached_update_info = None
        self._silent_checker = None
        self._update_prompt_shown = False
        self._pending_force_full_package_once = False
        self._nav_buttons = []

        self._init_runtime_services()
        self._panel_registry = self._build_panel_registry()

        # ---- 根据屏幕分辨率自适应窗口尺寸 ----
        screen = QApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            sw, sh = avail.width(), avail.height()
            # 最小尺寸：不超过可用屏幕的 85%
            min_w = min(1200, int(sw * 0.85))
            min_h = min(800, int(sh * 0.85))
            # 初始尺寸：不超过可用屏幕的 92%
            init_w = min(1400, int(sw * 0.92))
            init_h = min(900, int(sh * 0.90))
        else:
            min_w, min_h = 1200, 800
            init_w, init_h = 1400, 900
        self.setMinimumSize(min_w, min_h)
        self.resize(init_w, init_h)

        # 图标路径
        _res_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources")
        self._ico_logo_path = os.path.join(_res_dir, "logo.ico")
        self._png_logo_path = os.path.join(_res_dir, "logo.png")
        self._svg_logo_path = os.path.join(_res_dir, "logo.svg")

        # 设置窗口图标，保持与 QApplication 和任务栏图标一致。
        _icon_src = _resolve_app_icon_path()
        if _icon_src:
            self.setWindowIcon(QIcon(_icon_src))

        self._init_ui()

        # ---- 项目管理器初始化 ----
        self._init_project_manager()
        self._update_recent_menu()

        # ---- 快捷键绑定 ----
        self._init_shortcuts()

        # 默认选中第一个
        self._switch_to(0)
        self.statusBar().showMessage(f"就绪 | 渠系建筑物水力计算系统 V{APP_VERSION}")

        self._notify_optional_runtime_degradations()

    def __getattr__(self, name):
        panel_registry = self.__dict__.get("_panel_registry")
        if panel_registry is not None:
            panel = panel_registry.get_by_attr_name(name)
            if panel is not None:
                return panel
        raise AttributeError(f"{type(self).__name__!s} has no attribute {name!r}")

    def _init_runtime_services(self):
        from 推求水面线.managers.siphon_manager import SiphonManager
        from 推求水面线.managers.pressure_pipe_manager import PressurePipeManager

        self.siphon_manager = SiphonManager()
        self.pressure_pipe_manager = PressurePipeManager()

    def _build_panel_registry(self) -> PanelRegistry:
        descriptors = [
            PanelDescriptor(
                key="open_channel",
                title="明渠设计",
                nav_order=0,
                attr_name="open_channel_panel",
                factory=_create_open_channel_panel,
                project_slot="open_channel_panel",
            ),
            PanelDescriptor(
                key="aqueduct",
                title="渡槽设计",
                nav_order=1,
                attr_name="aqueduct_panel",
                factory=_create_aqueduct_panel,
                project_slot="aqueduct_panel",
            ),
            PanelDescriptor(
                key="tunnel",
                title="隧洞设计",
                nav_order=2,
                attr_name="tunnel_panel",
                factory=_create_tunnel_panel,
                project_slot="tunnel_panel",
            ),
            PanelDescriptor(
                key="culvert",
                title="暗涵设计",
                nav_order=3,
                attr_name="culvert_panel",
                factory=_create_culvert_panel,
                project_slot="culvert_panel",
            ),
            PanelDescriptor(
                key="siphon",
                title="倒虹吸设计",
                nav_order=4,
                attr_name="siphon_panel",
                factory=lambda: _create_siphon_panel(siphon_manager=self.siphon_manager),
                project_slot="siphon_panel",
            ),
            PanelDescriptor(
                key="pressure_pipe",
                title="有压管道设计",
                nav_order=5,
                attr_name="pressure_pipe_panel",
                factory=_create_pressure_pipe_panel,
                project_slot="pressure_pipe_panel",
            ),
            PanelDescriptor(
                key="water_profile",
                title="推求水面线",
                nav_order=6,
                attr_name="water_profile_panel",
                factory=lambda: _create_water_profile_panel(
                    siphon_manager=self.siphon_manager,
                    pressure_pipe_manager=self.pressure_pipe_manager,
                ),
                project_slot="water_profile_panel",
            ),
        ]
        return PanelRegistry(descriptors, self)

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_lay = QHBoxLayout(central)
        main_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.setSpacing(0)

        # ---- 左侧导航栏 ----
        nav_panel = QFrame()
        nav_panel.setObjectName("navPanel")
        nav_panel.setFixedWidth(180)
        nav_panel.setStyleSheet(NAV_STYLE)
        nav_lay = QVBoxLayout(nav_panel)
        nav_lay.setContentsMargins(10, 10, 10, 10)
        nav_lay.setSpacing(4)

        # 标题区域（Apple Pro 风格）
        brand_card = QFrame()
        brand_card.setObjectName("navBrandCard")
        brand_lay = QVBoxLayout(brand_card)
        brand_lay.setContentsMargins(12, 14, 12, 14)
        brand_lay.setSpacing(4)

        logo_lbl = QLabel()
        logo_lbl.setObjectName("navBrandLogo")
        logo_lbl.setFixedSize(48, 48)
        logo_lbl.setAlignment(Qt.AlignCenter)
        # 优先加载共享新 Logo，避免回退到旧模块图标。
        _logo_src = next(
            (
                path for path in (
                    self._svg_logo_path,
                    self._png_logo_path,
                    self._ico_logo_path,
                    _resolve_app_icon_path(),
                )
                if path and os.path.exists(path)
            ),
            "",
        )
        if os.path.exists(_logo_src):
            logo_pix = QIcon(_logo_src).pixmap(QSize(40, 40))
            logo_lbl.setPixmap(logo_pix)
        brand_lay.addWidget(logo_lbl, 0, Qt.AlignHCenter)

        title_lbl = QLabel("渠系建筑物")
        title_lbl.setObjectName("navTitle")
        brand_lay.addWidget(title_lbl)

        subtitle_lbl = QLabel("水力计算系统")
        subtitle_lbl.setObjectName("navSubtitle")
        brand_lay.addWidget(subtitle_lbl)

        ver_lbl = QLabel(f"V{APP_VERSION}")
        ver_lbl.setObjectName("navVersion")
        brand_lay.addWidget(ver_lbl, 0, Qt.AlignHCenter)

        nav_lay.addWidget(brand_card)
        nav_lay.addSpacing(8)

        # 分割线
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{BD};")
        nav_lay.addWidget(sep)
        nav_lay.addSpacing(6)

        # 导航按钮
        for idx, descriptor in enumerate(self._panel_registry.descriptors):
            btn = NavButton(descriptor.title)
            btn.setToolTip(_MODULE_TOOLTIPS.get(descriptor.key, descriptor.title))
            btn.clicked.connect(lambda checked, i=idx: self._switch_to(i))
            nav_lay.addWidget(btn)
            self._nav_buttons.append(btn)

        nav_lay.addStretch()

        # ---- 项目管理按钮（下拉菜单）----
        sep_proj = QFrame()
        sep_proj.setFrameShape(QFrame.HLine)
        sep_proj.setStyleSheet(f"color:{BD};")
        nav_lay.addWidget(sep_proj)
        nav_lay.addSpacing(4)

        self.btn_project = PushButton("📁 项目管理")
        self.btn_project.setToolTip("项目文件：新建/打开/保存整个工程")
        self.btn_project.setFixedHeight(36)
        self.btn_project.setStyleSheet(f"""
            QPushButton {{
                background: #E3F2FD; color: {P};
                border: 1px solid #90CAF9; border-radius: 6px;
                font-size: 12px; font-weight: bold;
                text-align: center; padding: 0 8px;
            }}
            QPushButton:hover {{ background: #BBDEFB; }}
            QPushButton::menu-indicator {{ width: 0px; }}
        """)

        # 创建下拉菜单
        self.project_menu = QMenu(self)
        self.project_menu.setStyleSheet(f"""
            QMenu {{
                background: white;
                border: 1px solid #E0E0E0;
                border-radius: 6px;
                padding: 4px;
            }}
            QMenu::item {{
                padding: 8px 24px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background: #E3F2FD;
                color: {P};
            }}
            QMenu::separator {{
                height: 1px;
                background: #E0E0E0;
                margin: 4px 8px;
            }}
        """)

        self.act_new = QAction("📄 新建项目", self)
        self.act_new.setShortcut("Ctrl+N")
        self.act_open = QAction("📂 打开项目...", self)
        self.act_open.setShortcut("Ctrl+O")
        self.act_save = QAction("💾 保存项目", self)
        self.act_save.setShortcut("Ctrl+S")
        self.act_save_as = QAction("📥 另存为...", self)
        self.act_save_as.setShortcut("Ctrl+Shift+S")

        self.project_menu.addAction(self.act_new)
        self.project_menu.addAction(self.act_open)
        self.project_menu.addSeparator()
        self.project_menu.addAction(self.act_save)
        self.project_menu.addAction(self.act_save_as)
        self.project_menu.addSeparator()

        # 最近项目子菜单
        self.recent_menu = self.project_menu.addMenu("📋 最近项目")
        # 注：_update_recent_menu() 延迟到 _init_project_manager() 之后调用

        self.btn_project.setMenu(self.project_menu)
        nav_lay.addWidget(self.btn_project)
        nav_lay.addSpacing(4)

        # 项目设置按钮
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet(f"color:{BD};")
        nav_lay.addWidget(sep2)
        nav_lay.addSpacing(4)
        btn_proj_settings = PushButton("⚙ 项目设置")
        btn_proj_settings.setToolTip("设置工程名称、人员、基本资料等计算书信息")
        btn_proj_settings.setFixedHeight(36)
        btn_proj_settings.clicked.connect(self._open_project_settings)
        btn_proj_settings.setStyleSheet(f"""
            QPushButton {{
                background: #E8F4FD; color: {P};
                border: 1px solid #B3D7F0; border-radius: 6px;
                font-size: 12px; font-weight: bold;
                text-align: center; padding: 0 8px;
            }}
            QPushButton:hover {{ background: #CCE8FA; }}
        """)
        nav_lay.addWidget(btn_proj_settings)
        nav_lay.addSpacing(4)

        # 检查更新按钮
        btn_update = PushButton("\U0001F504 检查更新")
        btn_update.setToolTip("检查是否有新版本可用")
        btn_update.setFixedHeight(36)
        btn_update.clicked.connect(self._open_update_dialog)
        btn_update.setStyleSheet(f"""
            QPushButton {{
                background: #FFF3E0; color: #E65100;
                border: 1px solid #FFE0B2; border-radius: 6px;
                font-size: 12px; font-weight: bold;
                text-align: center; padding: 0 8px;
            }}
            QPushButton:hover {{ background: #FFE0B2; }}
        """)
        nav_lay.addWidget(btn_update)
        nav_lay.addSpacing(4)

        # 版权信息
        author_lbl = QLabel("四川水发设计公司\n工程设计院\n© All Rights Reserved")
        author_lbl.setStyleSheet(f"font-size:11px;color:{T2};padding:6px 4px;")
        author_lbl.setAlignment(Qt.AlignCenter)
        nav_lay.addWidget(author_lbl)

        main_lay.addWidget(nav_panel)

        # ---- 右侧内容区 ----
        self.stack = QStackedWidget()
        main_lay.addWidget(self.stack, 1)

        # 第一阶段仍保持即时实例化，但改为通过注册表装配。
        self._panel_registry.create_all_eagerly()
        for descriptor in self._panel_registry.descriptors:
            panel = self._panel_registry.get(descriptor.key)
            setattr(self, descriptor.attr_name, panel)
            self.stack.addWidget(panel)

    # ----------------------------------------------------------------
    # 项目管理
    # ----------------------------------------------------------------
    def _init_project_manager(self):
        """初始化项目管理器"""
        self.project_manager = ProjectManager(self)
        self.project_manager.bind_runtime(
            self._panel_registry,
            services={
                "siphon_manager": self.siphon_manager,
                "pressure_pipe_manager": self.pressure_pipe_manager,
            },
        )

        # 连接信号
        self.project_manager.project_changed.connect(self._on_project_changed)
        self.project_manager.dirty_changed.connect(self._on_dirty_changed)
        self.project_manager.status_message.connect(self._on_status_message)

        # 连接菜单动作
        self.act_new.triggered.connect(self.project_manager.new_project)
        self.act_open.triggered.connect(lambda: self.project_manager.open_project())
        self.act_save.triggered.connect(self.project_manager.save_project)
        self.act_save_as.triggered.connect(self.project_manager.save_as_project)

        # 启动自动保存
        self.project_manager.start_auto_save()

    def _init_shortcuts(self):
        """初始化快捷键"""
        # Ctrl+N: 新建项目
        shortcut_new = QShortcut(QKeySequence("Ctrl+N"), self)
        shortcut_new.activated.connect(self.project_manager.new_project)

        # Ctrl+O: 打开项目
        shortcut_open = QShortcut(QKeySequence("Ctrl+O"), self)
        shortcut_open.activated.connect(lambda: self.project_manager.open_project())

        # Ctrl+S: 保存项目
        shortcut_save = QShortcut(QKeySequence("Ctrl+S"), self)
        shortcut_save.activated.connect(self.project_manager.save_project)

        # Ctrl+Shift+S: 另存为
        shortcut_save_as = QShortcut(QKeySequence("Ctrl+Shift+S"), self)
        shortcut_save_as.activated.connect(self.project_manager.save_as_project)

    def _on_project_changed(self, path: str):
        """项目路径变化时更新窗口标题"""
        self._update_window_title()
        self._update_recent_menu()

        # 更新 SiphonManager 的项目路径
        if hasattr(self, 'siphon_manager') and self.siphon_manager:
            self.siphon_manager.set_project_path(path)
            print(f"[SiphonManager] 项目路径已更新: {path}")

        # 更新 PressurePipeManager 的项目路径
        if hasattr(self, 'pressure_pipe_manager') and self.pressure_pipe_manager:
            self.pressure_pipe_manager.set_project_path(path)
            print(f"[PressurePipeManager] 项目路径已更新: {path}")

    def _on_dirty_changed(self, is_dirty: bool):
        """脏状态变化时更新窗口标题"""
        self._update_window_title()

    def _on_status_message(self, message: str):
        """显示状态栏消息"""
        self.statusBar().showMessage(message, 5000)

    def _update_window_title(self):
        """更新窗口标题"""
        self.setWindowTitle(self.project_manager.get_window_title(self._base_title))

    def _update_recent_menu(self):
        """更新最近项目菜单"""
        self.recent_menu.clear()
        recent = self.project_manager.recent_projects

        if not recent:
            act_empty = self.recent_menu.addAction("(无最近项目)")
            act_empty.setEnabled(False)
        else:
            for path in recent:
                import os
                name = os.path.basename(path)
                act = self.recent_menu.addAction(name)
                act.setToolTip(path)
                act.triggered.connect(lambda checked, p=path: self.project_manager.open_project(p))

            self.recent_menu.addSeparator()
            act_clear = self.recent_menu.addAction("清空最近项目")
            act_clear.triggered.connect(self._clear_recent_and_update)

    def _clear_recent_and_update(self):
        """清空最近项目并更新菜单"""
        self.project_manager.clear_recent_projects()
        self._update_recent_menu()

    def _open_project_settings(self):
        dlg = ProjectSettingsDialog(self)
        dlg.exec()

    def _notify_optional_runtime_degradations(self):
        """提醒当前会话是否显式启用了 WebEngine 应急模式。"""
        if self.startup_context.webengine_mode != "single-process":
            return
        self.statusBar().showMessage(
            "当前会话已启用 Qt WebEngine 应急单进程模式，仅用于排障。",
            12000,
        )
        try:
            InfoBar.warning(
                title="已启用 WebEngine 应急模式",
                content=(
                    "当前会话已通过隐藏开关启用 Qt WebEngine 单进程模式。"
                    f"如标准模式恢复，请移除环境变量 {EMERGENCY_SINGLE_PROCESS_ENV}。"
                ),
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP_RIGHT,
                duration=12000,
                parent=self,
            )
        except Exception:
            pass

    def prepare_update_prompt(self, *, force_full_package_once: bool = False):
        """Mark that this session should immediately open the update dialog."""
        self._update_prompt_shown = True
        self._pending_force_full_package_once = bool(force_full_package_once)

    # ---- 更新相关 ----
    def _open_update_dialog(self, force_full_package_once=None):
        """打开更新对话框，并支持本次强制走全量包。"""
        from app_渠系计算前端.update_dialog import UpdateDialog

        if force_full_package_once is None:
            force_full_package_once = self._pending_force_full_package_once
            self._pending_force_full_package_once = False
        cached = getattr(self, "_cached_update_info", None)
        dlg = UpdateDialog(
            self,
            auto_check=(cached is None),
            info=cached,
            force_full_package_once=bool(force_full_package_once),
        )
        dlg.exec()

    def start_silent_update_check(self):
        """启动时后台静默检查更新"""
        if not self.startup_context.update_checks_enabled:
            return
        self._cached_update_info = None
        from app_渠系计算前端.update_dialog import SilentUpdateChecker
        self._silent_checker = SilentUpdateChecker(self)
        self._silent_checker.update_available.connect(self._on_update_available)
        self._silent_checker.start()

    def _on_update_available(self, info):
        """静默检查发现新版本时，直接弹出更新对话框。"""
        self._cached_update_info = info
        if self._update_prompt_shown:
            return
        self._update_prompt_shown = True
        self.statusBar().showMessage(
            f"发现新版本 V{info.latest_version}，已打开更新窗口。",
            10000,
        )
        QTimer.singleShot(500, self._open_update_dialog)

    def closeEvent(self, event):
        """关闭窗口前检查项目保存，保存倒虹吸面板状态"""
        debug_print("[DEBUG] MainWindow closeEvent called")
        # 检查项目是否需要保存
        if hasattr(self, 'project_manager'):
            debug_print("[DEBUG] project_manager exists, calling check_save_on_close")
            if not self.project_manager.check_save_on_close():
                debug_print("[DEBUG] User cancelled close, ignoring event")
                event.ignore()
                return
        else:
            debug_print("[DEBUG] No project_manager found")

        debug_print("[DEBUG] Proceeding with close")
        self.hide()
        try:
            self.siphon_panel._save_autosave()
        except Exception:
            pass
        try:
            import matplotlib.pyplot as plt
            plt.close('all')
        except Exception:
            pass
        super().closeEvent(event)

    def _switch_to(self, index: int):
        """切换到指定模块"""
        if index >= self.stack.count():
            return
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate(self._nav_buttons):
            btn.set_selected(i == index)
        panel_titles = [descriptor.title for descriptor in self._panel_registry.descriptors]
        if index < len(panel_titles):
            self.statusBar().showMessage(f"当前模块: {panel_titles[index]}", 5000)

def main():
    from app_渠系计算前端.bootstrap import run

    return run()


if __name__ == "__main__":
    import sys

    sys.exit(main())
