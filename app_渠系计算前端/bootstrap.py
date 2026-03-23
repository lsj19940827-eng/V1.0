# -*- coding: utf-8 -*-
"""Application bootstrap and startup orchestration."""

import os
import sys
from typing import Iterable, Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont
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


def initialize_runtime_environment() -> None:
    """Apply process-wide settings before QApplication is created."""
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
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
    """Configure Matplotlib once the application object exists."""
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
    """Return a styled QApplication instance."""
    argv_list = list(argv) if argv is not None else sys.argv
    app = QApplication.instance() or QApplication(argv_list)
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei", 10))
    app.setStyleSheet(GLOBAL_STYLE)
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
