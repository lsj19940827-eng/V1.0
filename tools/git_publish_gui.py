# -*- coding: utf-8 -*-
"""
Git 提交/推送工具（PySide6 + qfluentwidgets）

目标：
1) 支持在本地仓库进行 git add / commit / push
2) 支持分支与主干（master）推送
3) 支持选择 remote 与目标分支（local:remote）
4) 提供 Fluent 风格界面与日志输出

用法：
    py tools/git_publish_gui.py
"""

import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import datetime

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

from PySide6.QtCore import QObject, Signal, Qt, QSize, QSettings, QTimer
from PySide6.QtGui import QFont, QTextCursor, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QGroupBox,
    QMessageBox,
)

from qfluentwidgets import (
    PushButton,
    PrimaryPushButton,
    ComboBox,
    CheckBox,
    TextEdit,
    LineEdit,
    InfoBar,
    InfoBarPosition,
)

try:
    from version import APP_NAME
except Exception:
    APP_NAME = "Git Publish Tool"


P = "#1976D2"
S = "#2E7D32"
W = "#F57C00"
E = "#D32F2F"
BG = "#F5F7FA"
CARD = "#FFFFFF"
BD = "#E0E0E0"
T1 = "#212121"
T2 = "#424242"


def _run_git(args: list[str], cwd: str) -> tuple[int, str]:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = (result.stdout or "") + (("\n" + result.stderr) if result.stderr else "")
    return result.returncode, out.strip()


def _get_current_branch(cwd: str) -> str:
    code, out = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    if code != 0:
        return ""
    return out.strip()


def _list_local_branches(cwd: str) -> list[str]:
    code, out = _run_git(["branch", "--format=%(refname:short)"], cwd)
    if code != 0:
        return []
    items = [x.strip() for x in out.splitlines() if x.strip()]
    return items


def _list_remotes(cwd: str) -> list[str]:
    code, out = _run_git(["remote"], cwd)
    if code != 0:
        return []
    items = [x.strip() for x in out.splitlines() if x.strip()]
    return items


def _status_short(cwd: str) -> str:
    code, out = _run_git(["status", "-sb"], cwd)
    return out if code == 0 else "无法获取 git status"


def _repo_is_git(cwd: str) -> bool:
    code, _ = _run_git(["rev-parse", "--is-inside-work-tree"], cwd)
    return code == 0


@dataclass
class ActionConfig:
    do_add: bool = True
    do_commit: bool = False
    do_push: bool = False
    auto_commit_message: bool = False
    force_add_all: bool = False
    skip_master_confirm: bool = False


class Bridge(QObject):
    log = Signal(str, str)         # message, level
    done = Signal(bool, str)       # success, action_name
    refresh = Signal()


class GitPublishWindow(QWidget):
    def __init__(self, repo_root: str):
        super().__init__()
        self.repo_root = repo_root
        self.settings = QSettings("CanalHydraulicCalc", "GitPublishTool")
        self.bridge = Bridge()
        self.bridge.log.connect(self._on_log)
        self.bridge.done.connect(self._on_done)
        self.bridge.refresh.connect(self._refresh_repo_info)
        self._running = False
        self._sync_reminder_shown = False
        self._last_sync_branch = ""

        self.setWindowTitle(f"Git 提交推送工具 — {APP_NAME}")
        self.resize(920, 760)
        self.setMinimumSize(860, 700)
        self._init_icon()
        self._init_ui()
        self._refresh_repo_info()
        QTimer.singleShot(0, self._show_weekly_sync_reminder_if_needed)

    def _info_parent(self):
        return self

    def _init_icon(self):
        logo_ico = os.path.join(PROJECT_ROOT, "app_渠系计算前端", "resources", "logo.ico")
        logo_svg = os.path.join(PROJECT_ROOT, "app_渠系计算前端", "resources", "logo.svg")
        if os.path.exists(logo_ico):
            self.setWindowIcon(QIcon(logo_ico))
        elif os.path.exists(logo_svg):
            self.setWindowIcon(QIcon(logo_svg))

    def _init_ui(self):
        self.setStyleSheet(f"""
            QWidget {{ background: {BG}; font-family: 'Microsoft YaHei', sans-serif; }}
            QGroupBox {{
                font-size: 14px; font-weight: bold; color: {P};
                border: 1px solid {BD}; border-radius: 6px;
                margin-top: 12px; padding: 14px 10px 10px 10px; background: {CARD};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin; left: 12px;
                padding: 0 6px; background: {CARD};
            }}
            QLabel {{ color: {T1}; font-size: 13px; }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        title_row = QHBoxLayout()
        logo_path = os.path.join(PROJECT_ROOT, "app_渠系计算前端", "resources", "logo.ico")
        if os.path.exists(logo_path):
            icon_label = QLabel()
            icon_label.setFixedSize(32, 32)
            icon_label.setPixmap(QIcon(logo_path).pixmap(QSize(32, 32)))
            title_row.addWidget(icon_label)

        title = QLabel("Git 上传（Commit + Push）")
        title.setFont(QFont("Microsoft YaHei", 16, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {P};")
        title.setText("Git 一键云备份（自动 Commit + Push）")
        title_row.addWidget(title)
        title_row.addStretch()
        root.addLayout(title_row)

        info_group = QGroupBox("仓库状态")
        info_layout = QVBoxLayout(info_group)
        self.repo_label = QLabel(f"仓库路径: {self.repo_root}")
        self.branch_label = QLabel("当前分支: -")
        self.status_label = QLabel("状态: -")
        self.sync_status_label = QLabel("每周同步状态: 未记录")
        info_layout.addWidget(self.repo_label)
        info_layout.addWidget(self.branch_label)
        info_layout.addWidget(self.status_label)
        info_layout.addWidget(self.sync_status_label)
        root.addWidget(info_group)

        op_group = QGroupBox("发布操作")
        op_layout = QVBoxLayout(op_group)
        op_layout.setSpacing(8)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Remote:"))
        self.remote_combo = ComboBox()
        self.remote_combo.setMinimumWidth(160)
        row1.addWidget(self.remote_combo)

        row1.addWidget(QLabel("本地分支:"))
        self.local_branch_combo = ComboBox()
        self.local_branch_combo.setMinimumWidth(220)
        row1.addWidget(self.local_branch_combo)
        self.local_branch_combo.currentTextChanged.connect(self._on_local_branch_changed)

        row1.addWidget(QLabel("目标远端分支:"))
        self.remote_branch_edit = LineEdit()
        self.remote_branch_edit.setMinimumWidth(220)
        row1.addWidget(self.remote_branch_edit)
        row1.addStretch()
        op_layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.add_before_commit_cb = CheckBox("提交前自动暂存（git add -A）")
        self.add_before_commit_cb.setChecked(True)
        self.push_tags_cb = CheckBox("同时推送 tags")
        self.force_with_lease_cb = CheckBox("强推（--force-with-lease）")
        self.allow_master_push_cb = CheckBox("允许推送到 master（需二次确认）")
        self.push_after_weekly_sync_cb = CheckBox("每周同步后自动推送")
        self.push_after_weekly_sync_cb.setChecked(True)

        row2.addWidget(self.add_before_commit_cb)
        row2.addWidget(self.push_tags_cb)
        row2.addWidget(self.force_with_lease_cb)
        row2.addWidget(self.allow_master_push_cb)
        self.allow_master_push_cb.setChecked(True)
        row2.addWidget(self.push_after_weekly_sync_cb)
        row2.addStretch()
        op_layout.addLayout(row2)

        op_layout.addWidget(QLabel("Commit 信息："))
        self.commit_edit = TextEdit()
        self.commit_edit.setPlaceholderText("例如：fix: 修复明渠面板导出异常")
        self.commit_edit.setPlaceholderText("可留空：一键云备份会自动生成提交信息")
        self.commit_edit.setFixedHeight(72)
        op_layout.addWidget(self.commit_edit)

        row3 = QHBoxLayout()
        self.btn_refresh = PushButton("刷新状态")
        self.btn_checkout = PushButton("切换到选中分支")
        self.btn_weekly_sync = PushButton("每周同步 master → 选中分支")
        self.btn_commit = PushButton("仅提交")
        self.btn_push = PushButton("仅推送")
        self.btn_commit_push = PrimaryPushButton("提交并推送")

        self.btn_refresh.clicked.connect(self._refresh_repo_info)
        self.btn_checkout.clicked.connect(self._checkout_selected_branch)
        self.btn_weekly_sync.clicked.connect(self._run_weekly_sync)
        self.btn_commit.clicked.connect(lambda: self._run_action(ActionConfig(do_add=True, do_commit=True, do_push=False), "提交"))
        self.btn_push.clicked.connect(lambda: self._run_action(ActionConfig(do_add=False, do_commit=False, do_push=True), "推送"))
        self.btn_commit_push.clicked.connect(lambda: self._run_action(ActionConfig(do_add=True, do_commit=True, do_push=True), "提交并推送"))

        self.btn_commit_push.setText("一键云备份")
        self.btn_commit_push.setToolTip("自动 git add -A、自动提交并推送到 GitHub")
        self.btn_commit_push.clicked.disconnect()
        self.btn_commit_push.clicked.connect(self._run_one_click_backup)

        row3.addWidget(self.btn_refresh)
        row3.addWidget(self.btn_checkout)
        row3.addWidget(self.btn_weekly_sync)
        row3.addWidget(self.btn_commit)
        row3.addWidget(self.btn_push)
        row3.addWidget(self.btn_commit_push)
        row3.addStretch()
        op_layout.addLayout(row3)

        root.addWidget(op_group)

        log_group = QGroupBox("执行日志")
        log_layout = QVBoxLayout(log_group)
        self.log_edit = TextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMinimumHeight(260)
        log_layout.addWidget(self.log_edit)
        root.addWidget(log_group, 1)

    def _set_running(self, running: bool):
        self._running = running
        for w in [
            self.btn_refresh, self.btn_checkout, self.btn_weekly_sync,
            self.btn_commit, self.btn_push, self.btn_commit_push,
        ]:
            w.setEnabled(not running)

    def _read_weekly_sync_record(self) -> tuple[str, str]:
        branch = str(self.settings.value("weekly_sync/branch", ""))
        ts = str(self.settings.value("weekly_sync/time", ""))
        return branch, ts

    def _save_weekly_sync_record(self, branch: str):
        now_iso = datetime.now().replace(microsecond=0).isoformat()
        self.settings.setValue("weekly_sync/branch", branch)
        self.settings.setValue("weekly_sync/time", now_iso)

    def _format_weekly_sync_status(self) -> tuple[str, bool]:
        branch, ts = self._read_weekly_sync_record()
        if not ts:
            return "每周同步状态: 未记录（建议立即执行一次）", True
        try:
            dt = datetime.fromisoformat(ts)
            days = (datetime.now() - dt).days
            dt_txt = dt.strftime("%Y-%m-%d %H:%M")
            if days >= 7:
                return (
                    f"每周同步状态: 上次 {dt_txt} 同步到 {branch or '-'}（已 {days} 天，建议马上同步）",
                    True,
                )
            return (
                f"每周同步状态: 上次 {dt_txt} 同步到 {branch or '-'}（{days} 天前）",
                False,
            )
        except Exception:
            return "每周同步状态: 记录异常（建议重新执行一次同步）", True

    def _refresh_weekly_sync_status_label(self):
        text, is_warning = self._format_weekly_sync_status()
        color = W if is_warning else S
        self.sync_status_label.setText(text)
        self.sync_status_label.setStyleSheet(f"color: {color};")

    def _show_weekly_sync_reminder_if_needed(self):
        if self._sync_reminder_shown:
            return
        _, is_warning = self._format_weekly_sync_status()
        if is_warning:
            InfoBar.warning(
                title="每周同步提醒",
                content="建议现在执行一次 master → 合并分支 同步，避免长期漂移。",
                parent=self._info_parent(),
                position=InfoBarPosition.TOP,
                duration=5000,
            )
        self._sync_reminder_shown = True

    def _append_log(self, msg: str, level: str = "info"):
        color_map = {
            "info": "#ABB2BF",
            "ok": "#98C379",
            "warn": "#E5C07B",
            "err": "#E06C75",
        }
        color = color_map.get(level, color_map["info"])
        cursor = self.log_edit.textCursor()
        cursor.movePosition(QTextCursor.End)
        escaped = msg.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
        cursor.insertHtml(
            f'<span style="color:{color}; font-family:Consolas, monospace; font-size:12px;">{escaped}</span><br>'
        )
        self.log_edit.setTextCursor(cursor)
        self.log_edit.ensureCursorVisible()

    def _on_log(self, msg: str, level: str):
        self._append_log(msg, level)

    def _on_done(self, success: bool, action_name: str):
        self._set_running(False)
        if success and action_name == "每周同步":
            if self._last_sync_branch:
                self._save_weekly_sync_record(self._last_sync_branch)
            self._refresh_weekly_sync_status_label()
        if success:
            content = "操作成功完成"
            if action_name == "每周同步":
                content = "master 已同步到目标分支，已记录本周同步时间"
            InfoBar.success(
                title=f"{action_name}完成",
                content=content,
                parent=self._info_parent(),
                position=InfoBarPosition.TOP,
                duration=3000,
            )
        else:
            InfoBar.error(
                title=f"{action_name}失败",
                content="请查看日志定位问题",
                parent=self._info_parent(),
                position=InfoBarPosition.TOP,
                duration=4000,
            )

    def _refresh_repo_info(self):
        if not _repo_is_git(self.repo_root):
            self.branch_label.setText("当前分支: (非 git 仓库)")
            self.status_label.setText("状态: 无法读取")
            self.sync_status_label.setText("每周同步状态: 无法读取（当前目录不是 git 仓库）")
            return

        current = _get_current_branch(self.repo_root)
        self.branch_label.setText(f"当前分支: {current or '-'}")
        self.status_label.setText(f"状态: {_status_short(self.repo_root)}")
        self._refresh_weekly_sync_status_label()

        branches = _list_local_branches(self.repo_root)
        remotes = _list_remotes(self.repo_root)

        self.local_branch_combo.clear()
        if branches:
            self.local_branch_combo.addItems(branches)
            idx = branches.index(current) if current in branches else 0
            self.local_branch_combo.setCurrentIndex(max(0, idx))
        self.remote_combo.clear()
        self.remote_combo.addItems(remotes or ["origin"])
        if remotes:
            try:
                self.remote_combo.setCurrentIndex(remotes.index("origin"))
            except ValueError:
                self.remote_combo.setCurrentIndex(0)

    def _on_local_branch_changed(self, text: str):
        if text:
            self.remote_branch_edit.setText(text)

    def _confirm_master_push(self, target_branch: str) -> bool:
        if target_branch != "master":
            return True
        if not self.allow_master_push_cb.isChecked():
            QMessageBox.warning(
                self,
                "禁止推送到 master",
                "目标分支是 master，但未勾选“允许推送到 master（需二次确认）”。",
            )
            return False
        ret = QMessageBox.question(
            self,
            "确认推送到 master",
            "你即将推送到远端 master 分支，是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return ret == QMessageBox.Yes

    def _checkout_selected_branch(self):
        if self._running:
            return
        branch = self.local_branch_combo.currentText().strip()
        if not branch:
            return
        self._set_running(True)

        def worker():
            self.bridge.log.emit(f"$ git checkout {branch}", "info")
            code, out = _run_git(["checkout", branch], self.repo_root)
            if out:
                self.bridge.log.emit(out, "ok" if code == 0 else "err")
            self.bridge.refresh.emit()
            self.bridge.done.emit(code == 0, "切换分支")

        threading.Thread(target=worker, daemon=True).start()

    def _run_weekly_sync(self):
        if self._running:
            return
        remote = self.remote_combo.currentText().strip() or "origin"
        target_branch = self.local_branch_combo.currentText().strip() or _get_current_branch(self.repo_root)
        if not target_branch:
            InfoBar.warning(
                title="缺少目标分支",
                content="请先选择要同步的本地分支",
                parent=self._info_parent(),
                position=InfoBarPosition.TOP,
                duration=3000,
            )
            return
        if target_branch == "master":
            InfoBar.warning(
                title="同步目标不建议为 master",
                content="请选择合并分支（如 feature/merged-panel）执行 master → 分支 同步。",
                parent=self._info_parent(),
                position=InfoBarPosition.TOP,
                duration=4000,
            )
            return

        ret = QMessageBox.question(
            self,
            "确认每周同步",
            (
                f"将执行：\n"
                f"1) git fetch {remote}\n"
                f"2) git checkout {target_branch}\n"
                f"3) git merge {remote}/master --no-edit\n"
                f"{'4) git push ' + remote + ' ' + target_branch if self.push_after_weekly_sync_cb.isChecked() else ''}\n\n"
                "是否继续？"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if ret != QMessageBox.Yes:
            return

        self._set_running(True)
        self._last_sync_branch = target_branch

        def run_step(args: list[str], ok_message: str = "") -> bool:
            cmd = "$ git " + " ".join(args)
            self.bridge.log.emit(cmd, "info")
            code, out = _run_git(args, self.repo_root)
            if out:
                level = "ok" if code == 0 else "err"
                self.bridge.log.emit(out, level)
            if code == 0 and ok_message:
                self.bridge.log.emit(ok_message, "ok")
            return code == 0

        def worker():
            success = True
            success = success and run_step(["fetch", remote], "fetch 完成")
            if success:
                success = success and run_step(["checkout", target_branch], f"已切换到 {target_branch}")
            if success:
                success = success and run_step(
                    ["merge", f"{remote}/master", "--no-edit"],
                    "master 同步到目标分支完成",
                )
            if success and self.push_after_weekly_sync_cb.isChecked():
                success = success and run_step(["push", remote, target_branch], "已推送同步结果")

            self.bridge.refresh.emit()
            self.bridge.done.emit(success, "每周同步")

        threading.Thread(target=worker, daemon=True).start()

    def _build_auto_commit_message(self, local_branch: str) -> str:
        branch = local_branch or _get_current_branch(self.repo_root) or "unknown"
        now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return f"backup({branch}): {now_text}"

    def _run_one_click_backup(self):
        self.add_before_commit_cb.setChecked(True)
        self.push_tags_cb.setChecked(False)
        self.force_with_lease_cb.setChecked(False)
        self.allow_master_push_cb.setChecked(True)
        self._run_action(
            ActionConfig(
                do_add=True,
                do_commit=True,
                do_push=True,
                auto_commit_message=True,
                force_add_all=True,
                skip_master_confirm=True,
            ),
            "一键云备份",
        )

    def _run_action_legacy(self, cfg: ActionConfig, action_name: str):
        if self._running:
            return

        remote = self.remote_combo.currentText().strip() or "origin"
        local_branch = self.local_branch_combo.currentText().strip() or _get_current_branch(self.repo_root)
        remote_branch = self.remote_branch_edit.text().strip() or local_branch
        commit_msg = self.commit_edit.toPlainText().strip()

        if cfg.do_commit and not commit_msg:
            InfoBar.warning(
                title="缺少提交信息",
                content="请填写 Commit 信息",
                parent=self._info_parent(),
                position=InfoBarPosition.TOP,
                duration=3000,
            )
            return
        if cfg.do_push and not self._confirm_master_push(remote_branch):
            return

        self._set_running(True)

        def worker():
            success = True
            if cfg.do_add and self.add_before_commit_cb.isChecked():
                self.bridge.log.emit("$ git add -A", "info")
                code, out = _run_git(["add", "-A"], self.repo_root)
                if out:
                    self.bridge.log.emit(out, "ok" if code == 0 else "err")
                success = success and (code == 0)

            if success and cfg.do_commit:
                self.bridge.log.emit(f"$ git commit -m \"{commit_msg}\"", "info")
                code, out = _run_git(["commit", "-m", commit_msg], self.repo_root)
                if out:
                    low = out.lower()
                    if "nothing to commit" in low:
                        self.bridge.log.emit(out, "warn")
                        code = 0
                    else:
                        self.bridge.log.emit(out, "ok" if code == 0 else "err")
                success = success and (code == 0)

            if success and cfg.do_push:
                push_args = ["push", remote]
                if self.force_with_lease_cb.isChecked():
                    push_args.append("--force-with-lease")
                push_args.append(f"{local_branch}:{remote_branch}")
                self.bridge.log.emit("$ git " + " ".join(push_args), "info")
                code, out = _run_git(push_args, self.repo_root)
                if out:
                    self.bridge.log.emit(out, "ok" if code == 0 else "err")
                success = success and (code == 0)

                if success and self.push_tags_cb.isChecked():
                    tag_args = ["push", remote, "--tags"]
                    self.bridge.log.emit("$ git " + " ".join(tag_args), "info")
                    code, out = _run_git(tag_args, self.repo_root)
                    if out:
                        self.bridge.log.emit(out, "ok" if code == 0 else "err")
                    success = success and (code == 0)

            self.bridge.refresh.emit()
            self.bridge.done.emit(success, action_name)

        threading.Thread(target=worker, daemon=True).start()

    def _run_action(self, cfg: ActionConfig, action_name: str):
        if self._running:
            return

        remote = self.remote_combo.currentText().strip() or "origin"
        local_branch = self.local_branch_combo.currentText().strip() or _get_current_branch(self.repo_root)
        remote_branch = self.remote_branch_edit.text().strip() or local_branch
        commit_msg = self.commit_edit.toPlainText().strip()

        if cfg.do_commit and not commit_msg:
            if cfg.auto_commit_message:
                commit_msg = self._build_auto_commit_message(local_branch)
                self.commit_edit.setPlainText(commit_msg)
                self._append_log(f"Auto commit message: {commit_msg}", "info")
            else:
                InfoBar.warning(
                    title="缺少 Commit 信息",
                    content="请填写 Commit 信息",
                    parent=self._info_parent(),
                    position=InfoBarPosition.TOP,
                    duration=3000,
                )
                return

        if cfg.do_push and (not cfg.skip_master_confirm) and (not self._confirm_master_push(remote_branch)):
            return

        self._set_running(True)

        def worker():
            success = True
            if cfg.do_add and (cfg.force_add_all or self.add_before_commit_cb.isChecked()):
                self.bridge.log.emit("$ git add -A", "info")
                code, out = _run_git(["add", "-A"], self.repo_root)
                if out:
                    self.bridge.log.emit(out, "ok" if code == 0 else "err")
                success = success and (code == 0)

            if success and cfg.do_commit:
                self.bridge.log.emit(f"$ git commit -m \"{commit_msg}\"", "info")
                code, out = _run_git(["commit", "-m", commit_msg], self.repo_root)
                if out:
                    low = out.lower()
                    if "nothing to commit" in low:
                        self.bridge.log.emit(out, "warn")
                        code = 0
                    else:
                        self.bridge.log.emit(out, "ok" if code == 0 else "err")
                success = success and (code == 0)

            if success and cfg.do_push:
                push_args = ["push", remote]
                if self.force_with_lease_cb.isChecked():
                    push_args.append("--force-with-lease")
                push_args.append(f"{local_branch}:{remote_branch}")
                self.bridge.log.emit("$ git " + " ".join(push_args), "info")
                code, out = _run_git(push_args, self.repo_root)
                if out:
                    self.bridge.log.emit(out, "ok" if code == 0 else "err")
                success = success and (code == 0)

                if success and self.push_tags_cb.isChecked():
                    tag_args = ["push", remote, "--tags"]
                    self.bridge.log.emit("$ git " + " ".join(tag_args), "info")
                    code, out = _run_git(tag_args, self.repo_root)
                    if out:
                        self.bridge.log.emit(out, "ok" if code == 0 else "err")
                    success = success and (code == 0)

            self.bridge.refresh.emit()
            self.bridge.done.emit(success, action_name)

        threading.Thread(target=worker, daemon=True).start()


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei", 10))
    window = GitPublishWindow(PROJECT_ROOT)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
