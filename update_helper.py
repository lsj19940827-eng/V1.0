# -*- coding: utf-8 -*-
"""
独立更新助手。

职责：
1. 从主程序接收更新会话文件。
2. 复制自身到临时目录，再由临时 runner 真正执行安装。
3. 展示安装阶段窗口、成功页和失败页。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import updater


STAGE_ORDER = [
    ("prepare", "准备安装"),
    ("wait", "等待主程序退出"),
    ("validate", "校验安装环境"),
    ("backup", "备份当前版本"),
    ("apply", "解压并应用更新"),
    ("cleanup", "清理临时文件"),
    ("done", "安装完成"),
]


def _source_launch_context() -> tuple[str, dict[str, str]]:
    project_root = updater._get_project_root()
    return project_root, updater._with_pythonpath(os.environ, project_root)


def _creationflags() -> int:
    if os.name != "nt":
        return 0
    return (
        getattr(subprocess, "CREATE_NO_WINDOW", 0)
        | getattr(subprocess, "DETACHED_PROCESS", 0)
    )


def _launch_detached(
    cmd: list[str],
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
):
    subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        creationflags=_creationflags(),
        close_fds=False,
    )


def _spawn_runner(session_path: str):
    session = updater.UpdateSession.from_file(session_path)
    if getattr(sys, "frozen", False):
        runner_dir = os.path.join(tempfile.gettempdir(), f"canal-updater-runner-{session.session_id}")
        os.makedirs(runner_dir, exist_ok=True)
        runner_entry = os.path.join(runner_dir, os.path.basename(sys.executable))
        shutil.copy2(sys.executable, runner_entry)
        cmd = [runner_entry, "--run-session", session_path]
        _launch_detached(cmd)
        return

    project_root, env = _source_launch_context()
    helper_entry = os.path.join(project_root, "update_helper.py")
    cmd = [updater._prefer_windowed_python(), helper_entry, "--run-session", session_path]
    _launch_detached(cmd, cwd=project_root, env=env)


def _launch_main_app(
    session: updater.UpdateSession,
    *,
    open_update_dialog: bool = False,
    force_full_package: bool = False,
):
    cwd = None
    env = None
    if getattr(sys, "frozen", False) and os.path.exists(session.main_exe_path):
        cmd = [session.main_exe_path]
    elif session.main_script_path and os.path.exists(session.main_script_path):
        cwd, env = _source_launch_context()
        cmd = [updater._prefer_windowed_python(), session.main_script_path]
    else:
        return

    if open_update_dialog:
        cmd.append(updater.UPDATE_FLAG_OPEN_DIALOG)
    if force_full_package:
        cmd.append(updater.UPDATE_FLAG_FORCE_FULL_PACKAGE)
    _launch_detached(cmd, cwd=cwd, env=env)


def _open_path(path: str):
    if not path or not os.path.exists(path):
        return
    if os.name == "nt":
        os.startfile(path)
        return
    subprocess.Popen(["xdg-open", path])


class InstallWorker(QObject):
    stage_changed = Signal(str, str)
    completed = Signal(dict)

    def __init__(self, session_path: str):
        super().__init__()
        self.session_path = session_path

    def run(self):
        result = updater.run_update_session(
            self.session_path,
            stage_callback=lambda key, text: self.stage_changed.emit(key, text),
        )
        self.completed.emit(result)


class UpdateHelperWindow(QWidget):
    def __init__(self, session_path: str):
        super().__init__()
        self.session_path = session_path
        self.session = updater.UpdateSession.from_file(session_path)
        self.result: dict | None = None
        self._installing = True
        self._stage_labels: dict[str, QLabel] = {}
        self._worker_thread: QThread | None = None
        self._worker: InstallWorker | None = None
        self._setup_ui()
        self._start_worker()

    def _setup_ui(self):
        self.setWindowTitle("安装更新")
        self.setMinimumSize(560, 460)
        self.resize(620, 520)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        icon_path = os.path.join(updater._get_project_root(), "icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        title = QLabel("正在安装新版本")
        title.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
        root.addWidget(title)

        self.status_label = QLabel(
            f"即将把 V{self.session.current_version} 更新到 V{self.session.target_version}"
        )
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #555; font-size: 13px;")
        root.addWidget(self.status_label)

        stage_card = QFrame()
        stage_card.setStyleSheet(
            "QFrame { background: #F7F9FC; border: 1px solid #DCE3EB; border-radius: 10px; }"
        )
        stage_layout = QVBoxLayout(stage_card)
        stage_layout.setContentsMargins(16, 16, 16, 16)
        stage_layout.setSpacing(10)

        for key, text in STAGE_ORDER:
            label = QLabel(f"○ {text}")
            label.setStyleSheet("color: #7A869A; font-size: 13px;")
            stage_layout.addWidget(label)
            self._stage_labels[key] = label
        self.result_stage_label = QLabel("")
        self.result_stage_label.setVisible(False)
        self.result_stage_label.setStyleSheet(
            "color: #C62828; font-size: 13px; font-weight: bold;"
        )
        stage_layout.addWidget(self.result_stage_label)
        root.addWidget(stage_card)

        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setPlaceholderText("安装日志会显示在这里。")
        self.detail_text.setStyleSheet(
            "QTextEdit { background: white; border: 1px solid #DCE3EB; border-radius: 8px; font-size: 12px; }"
        )
        root.addWidget(self.detail_text, 1)

        self.footer_label = QLabel("安装过程中请不要关闭此窗口。")
        self.footer_label.setStyleSheet("color: #666; font-size: 12px;")
        root.addWidget(self.footer_label)

        button_row = QHBoxLayout()
        button_row.addStretch()

        self.btn_open_log = QPushButton("查看日志")
        self.btn_open_log.clicked.connect(self._open_log_path)
        self.btn_open_log.setVisible(False)
        button_row.addWidget(self.btn_open_log)

        self.btn_open_workdir = QPushButton("打开更新目录")
        self.btn_open_workdir.clicked.connect(self._open_work_dir)
        self.btn_open_workdir.setVisible(False)
        button_row.addWidget(self.btn_open_workdir)

        self.btn_retry = QPushButton("重新下载后再试")
        self.btn_retry.clicked.connect(self._retry_download)
        self.btn_retry.setVisible(False)
        button_row.addWidget(self.btn_retry)

        self.btn_launch = QPushButton("启动新版本")
        self.btn_launch.clicked.connect(self._launch_updated_app)
        self.btn_launch.setVisible(False)
        button_row.addWidget(self.btn_launch)

        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.close)
        self.btn_close.setVisible(False)
        button_row.addWidget(self.btn_close)

        root.addLayout(button_row)

    def _start_worker(self):
        self._worker_thread = QThread(self)
        self._worker = InstallWorker(self.session_path)
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
        self._worker.stage_changed.connect(self._on_stage_changed)
        self._worker.completed.connect(self._on_completed)
        self._worker.completed.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._worker.deleteLater)
        self._worker_thread.start()

    def _set_installing(self, installing: bool):
        self._installing = installing
        self.btn_close.setVisible(not installing)

    def _set_stage_state(self, stage_key: str):
        reached = False
        for key, text in STAGE_ORDER:
            label = self._stage_labels[key]
            if key == stage_key:
                reached = True
                label.setText(f"● {text}")
                label.setStyleSheet("color: #1565C0; font-size: 13px; font-weight: bold;")
                continue
            if not reached:
                label.setText(f"✓ {text}")
                label.setStyleSheet("color: #2E7D32; font-size: 13px;")
            else:
                label.setText(f"○ {text}")
                label.setStyleSheet("color: #7A869A; font-size: 13px;")

    def _append_detail(self, text: str):
        self.detail_text.append(text)

    def _on_stage_changed(self, stage_key: str, text: str):
        if stage_key in self._stage_labels:
            self._set_stage_state(stage_key)
        self.status_label.setText(text)
        self._append_detail(text)

    def _on_completed(self, result: dict):
        self.result = result
        if result.get("success"):
            self._stage_labels["done"].setText("✓ 安装完成")
            self._stage_labels["done"].setStyleSheet("color: #2E7D32; font-size: 13px; font-weight: bold;")
            self.status_label.setText("安装完成，可以启动新版本。")
            self.footer_label.setText("旧版本备份和临时文件已经清理。")
            self.btn_launch.setVisible(True)
            self._append_detail(f"安装日志：{result.get('log_path', '')}")
            return

        rollback_ok = result.get("rollback_ok")
        fail_text = "安装失败，已自动回滚到旧版本。" if rollback_ok else "安装失败，且自动回滚未完成。"
        self.status_label.setText(fail_text)
        self.footer_label.setText("可以查看日志或打开更新目录继续排查。")
        self._append_detail(result.get("error", "安装失败"))
        self._append_detail(f"安装日志：{result.get('log_path', '')}")
        self.btn_open_log.setVisible(True)
        self.btn_open_workdir.setVisible(True)
        self.btn_retry.setVisible(True)
        self.btn_close.setText("关闭")

    def _open_work_dir(self):
        target = self.session.work_dir
        if self.result and self.result.get("work_dir"):
            target = self.result["work_dir"]
        _open_path(target)

    def _open_log_path(self):
        if self.result and self.result.get("log_path"):
            _open_path(self.result["log_path"])
            return
        _open_path(self.session.log_dir)

    def _launch_updated_app(self):
        _launch_main_app(self.session, open_update_dialog=False)
        self.close()

    def _retry_download(self):
        _launch_main_app(self.session, open_update_dialog=True)
        self.close()


def _update_helper_on_completed(self, result: dict):
    self.result = result
    self._set_installing(False)
    if result.get("success"):
        self._stage_labels["done"].setText("✓ 安装完成")
        self._stage_labels["done"].setStyleSheet(
            "color: #2E7D32; font-size: 13px; font-weight: bold;"
        )
        self.status_label.setText("安装完成，可以启动新版本。")
        self.footer_label.setText("旧版本备份和临时文件已经清理。")
        self.btn_launch.setVisible(True)
        self._append_detail(f"安装日志：{result.get('log_path', '')}")
        return

    rollback_ok = result.get("rollback_ok")
    self.status_label.setText(
        "安装失败，已自动回滚到旧版本。"
        if rollback_ok
        else "安装失败，且自动回滚未完成。"
    )
    self.footer_label.setText("可以查看日志或打开更新目录继续排查。")
    self.result_stage_label.setText(
        "安装失败并回滚" if rollback_ok else "安装失败，回滚未完成"
    )
    self.result_stage_label.setVisible(True)
    self._append_detail(result.get("user_message", "安装未完成，请重新下载后再试。"))
    self._append_detail(f"安装日志：{result.get('log_path', '')}")
    self.btn_open_log.setVisible(True)
    self.btn_open_workdir.setVisible(True)
    self.btn_retry.setVisible(True)
    if result.get("retry_mode") == updater.RETRY_MODE_FULL_PACKAGE:
        self.btn_retry.setText("重新下载完整安装包")
    else:
        self.btn_retry.setText("重新下载后再试")
    self.btn_close.setText("关闭")


def _update_helper_retry_download(self):
    force_full_package = (
        bool(self.result) and self.result.get("retry_mode") == updater.RETRY_MODE_FULL_PACKAGE
    )
    _launch_main_app(
        self.session,
        open_update_dialog=True,
        force_full_package=force_full_package,
    )
    self.close()


def _update_helper_close_event(self, event):
    if self._installing:
        event.ignore()
        self.footer_label.setText("安装正在进行中，请等待当前步骤结束。")
        return
    super(UpdateHelperWindow, self).closeEvent(event)


UpdateHelperWindow._on_completed = _update_helper_on_completed
UpdateHelperWindow._retry_download = _update_helper_retry_download
UpdateHelperWindow.closeEvent = _update_helper_close_event


def _run_session_ui(session_path: str) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(updater.UPDATE_HELPER_NAME)
    app.setFont(QFont("Microsoft YaHei", 10))
    window = UpdateHelperWindow(session_path)
    window.show()
    return app.exec()


def _show_direct_launch_hint() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(updater.UPDATE_HELPER_NAME)
    app.setFont(QFont("Microsoft YaHei", 10))
    QMessageBox.information(
        None,
        "更新助手说明",
        "请双击 CanalHydraulicCalc.exe 启动软件。\n\n本程序仅在自动更新时由系统调用，不能单独运行。",
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CanalHydraulicCalc update helper")
    parser.add_argument("--spawn-session")
    parser.add_argument("--run-session")
    args = parser.parse_args(argv)

    session_path = args.spawn_session or args.run_session
    if not session_path:
        return _show_direct_launch_hint()

    if args.spawn_session:
        _spawn_runner(session_path)
        return 0
    return _run_session_ui(session_path)


if __name__ == "__main__":
    raise SystemExit(main())
