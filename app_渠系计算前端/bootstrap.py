# -*- coding: utf-8 -*-
"""应用启动编排，负责运行环境、全局样式、图标和主窗口装配。"""

import os
import sys
from pathlib import Path
from typing import Iterable, Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

import updater
from app_渠系计算前端.qfluentwidgets_compat import ensure_qfluentwidgets_compat
from app_渠系计算前端.startup_context import StartupContext
from app_渠系计算前端.styles import GLOBAL_STYLE
from app_渠系计算前端.webengine_diagnostics import (
    EMERGENCY_SINGLE_PROCESS_ENV,
    apply_emergency_single_process_mode,
    build_failure_instructions,
    build_failure_summary,
    emergency_single_process_requested,
    format_probe_report,
    is_webengine_probe_child_command,
    probe_standard_webengine,
    run_webengine_probe_child,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_ICON_FILE = PROJECT_ROOT / "icon.ico"
SHARED_LOGO_ICON_FILE = PROJECT_ROOT / "app_渠系计算前端" / "resources" / "logo.ico"
APP_USER_MODEL_ID = "CanalHydraulicCalc.App"
_PLATFORM_WMI_GUARD_FLAG = "_v1_platform_wmi_guard_installed"


def _resolve_app_icon_path() -> str:
    """返回主程序应使用的应用图标路径。"""
    for candidate in (
        APP_ICON_FILE,
        SHARED_LOGO_ICON_FILE,
    ):
        if candidate.exists():
            return str(candidate)
    return ""


def _set_windows_app_user_model_id() -> None:
    """设置 Windows 任务栏应用标识，减少旧图标缓存和分组异常。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            APP_USER_MODEL_ID
        )
    except Exception:
        pass


def ensure_safe_windows_platform_queries() -> None:
    """禁用 Python platform 的 Windows WMI 查询，避免第三方库导入时卡住。"""
    if not sys.platform.startswith("win"):
        return
    try:
        import platform as std_platform
    except Exception:
        return

    if getattr(std_platform, _PLATFORM_WMI_GUARD_FLAG, False):
        return

    def _disabled_wmi_query(*_args, **_kwargs):
        """让 platform 立即走非 WMI 回退路径。"""
        raise OSError("Windows WMI query disabled to avoid startup hang")

    try:
        std_platform._wmi_query = _disabled_wmi_query
        if hasattr(std_platform, "_wmi"):
            std_platform._wmi = None
        if hasattr(std_platform, "_uname_cache"):
            std_platform._uname_cache = None
        setattr(std_platform, _PLATFORM_WMI_GUARD_FLAG, True)
    except Exception:
        pass


def _apply_application_icon(app: QApplication) -> None:
    """把统一图标设置到 QApplication，供窗口和弹窗继承。"""
    icon_path = _resolve_app_icon_path()
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))


def initialize_runtime_environment() -> None:
    """创建 QApplication 前应用进程级设置。"""
    ensure_safe_windows_platform_queries()
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    _set_windows_app_user_model_id()
    if not QApplication.instance():
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )


def _get_dpi_scale(app: QApplication) -> float:
    screen = app.primaryScreen()
    if screen:
        return screen.devicePixelRatio()
    return 1.0


def _setup_matplotlib_dpi(app: QApplication) -> None:
    """在 QApplication 创建后配置 Matplotlib 显示比例。"""
    try:
        import matplotlib

        matplotlib.use("QtAgg")
        import matplotlib.pyplot as plt

        scale = _get_dpi_scale(app)
        fig_dpi = max(100, int(100 * scale))
        plt.rcParams["figure.dpi"] = fig_dpi
        plt.rcParams["savefig.dpi"] = 150

        base_font = max(10, int(10 * scale))
        plt.rcParams["font.size"] = base_font
        plt.rcParams["axes.titlesize"] = base_font + 2
        plt.rcParams["axes.labelsize"] = base_font
        plt.rcParams["xtick.labelsize"] = base_font - 1
        plt.rcParams["ytick.labelsize"] = base_font - 1
        plt.rcParams["legend.fontsize"] = base_font - 1
        plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "SimSun"]
        plt.rcParams["axes.unicode_minus"] = False
    except Exception:
        pass


def ensure_application(argv: Optional[Iterable[str]] = None) -> QApplication:
    """返回已应用全局样式和图标的 QApplication。"""
    argv_list = list(argv) if argv is not None else sys.argv
    app = QApplication.instance() or QApplication(argv_list)
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei", 10))
    app.setStyleSheet(GLOBAL_STYLE)
    _apply_application_icon(app)
    _setup_matplotlib_dpi(app)
    return app


def _show_webengine_startup_failure_dialog(result) -> None:
    """Display a blocking diagnosis before the main window is constructed."""
    summary = build_failure_summary(result)
    guidance_lines = build_failure_instructions(result)

    if result.failure_kind == "ipc-access-denied":
        informative = (
            "当前环境已确认不是业务页面内容问题，而是 Qt WebEngine 在首次导航时触发了 "
            "Chromium 多进程 IPC 的“拒绝访问”。"
        )
    elif result.failure_kind == "missing-process":
        informative = "当前环境缺少 QtWebEngineProcess.exe，标准模式无法启动。"
    elif result.failure_kind == "import-error":
        informative = "当前环境无法导入 Qt WebEngine 组件，标准模式无法启动。"
    elif result.failure_kind == "timeout":
        informative = "Qt WebEngine 标准模式预检在限定时间内没有完成，请先用诊断脚本确认系统环境。"
    else:
        informative = "Qt WebEngine 标准模式预检失败。为了避免主进程直接崩溃，本次未继续装配主窗口。"

    detail_lines = [
        format_probe_report(result),
        "",
        "提示：本程序默认不自动降级为 QTextBrowser。",
        f"如必须继续工作，可手动设置环境变量 {EMERGENCY_SINGLE_PROCESS_ENV}=1 后重启程序，"
        "仅作为 WebEngine 应急单进程模式使用。",
    ]

    box = QMessageBox()
    box.setIcon(QMessageBox.Critical)
    box.setWindowTitle("Qt WebEngine 启动诊断")
    box.setText(summary)
    box.setInformativeText(
        informative + "\n\n建议先执行以下排查：\n" + "\n".join(
            f"{idx}. {line}" for idx, line in enumerate(guidance_lines, start=1)
        )
    )
    box.setDetailedText("\n".join(detail_lines))
    box.setStandardButtons(QMessageBox.Close)
    box.exec()


def build_startup_context(*, update_checks_enabled: bool = True) -> Optional[StartupContext]:
    """Probe runtime capabilities and return immutable startup facts."""
    is_frozen_runtime = bool(getattr(sys, "frozen", False))
    if emergency_single_process_requested():
        flags = apply_emergency_single_process_mode()
        try:
            print(
                "[Runtime] Qt WebEngine emergency single-process mode enabled: "
                f"{flags}"
            )
        except Exception:
            pass
        return StartupContext(
            webengine_mode="single-process",
            webengine_probe_result=None,
            update_checks_enabled=update_checks_enabled,
            is_frozen_runtime=is_frozen_runtime,
        )

    result = probe_standard_webengine()
    if result.ok:
        return StartupContext(
            webengine_mode="standard",
            webengine_probe_result=result,
            update_checks_enabled=update_checks_enabled,
            is_frozen_runtime=is_frozen_runtime,
        )

    try:
        print(format_probe_report(result))
    except Exception:
        pass
    ensure_application()
    _show_webengine_startup_failure_dialog(result)
    return None


def _check_license() -> bool:
    from license_checker import check_license

    return bool(check_license())


def run(argv: Optional[Iterable[str]] = None) -> int:
    """Bootstrap the application and return the process exit code."""
    argv_list = list(argv) if argv is not None else list(sys.argv)
    initialize_runtime_environment()

    if is_webengine_probe_child_command(argv_list):
        return run_webengine_probe_child()

    ensure_qfluentwidgets_compat()

    if not _check_license():
        return 1

    startup_context = build_startup_context(update_checks_enabled=True)
    if startup_context is None:
        return 2

    app = ensure_application(argv_list)

    from app_渠系计算前端.app import MainWindow

    open_update_dialog = updater.UPDATE_FLAG_OPEN_DIALOG in argv_list
    force_full_package = updater.UPDATE_FLAG_FORCE_FULL_PACKAGE in argv_list

    window = MainWindow(startup_context)
    if open_update_dialog:
        window.prepare_update_prompt(force_full_package_once=force_full_package)
    window.show()
    if startup_context.update_checks_enabled:
        window.start_silent_update_check()
    if open_update_dialog:
        QTimer.singleShot(300, lambda: window._open_update_dialog())
    return app.exec()
