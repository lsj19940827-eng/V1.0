# -*- coding: utf-8 -*-
"""
应用内更新对话框

提供：
- 检查更新（后台线程）
- 显示更新日志、文件大小
- 下载进度条（速度 + ETA）
- 取消下载
- 代理→直连无缝切换
- 一键更新
"""

import os
import threading
import time

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QTextEdit, QMessageBox, QComboBox,
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont

from version import APP_VERSION


# ============================================================
# 后台线程：检查更新
# ============================================================
class CheckUpdateThread(QThread):
    """后台检查远程版本"""
    finished = Signal(object)  # UpdateInfo or None

    def __init__(self, parent=None, allow_downgrade: bool = False):
        super().__init__(parent)
        self.allow_downgrade = allow_downgrade

    def run(self):
        from updater import check_for_update
        info = check_for_update(allow_downgrade=self.allow_downgrade)
        self.finished.emit(info)


# ============================================================
# 后台线程：下载更新包（支持取消）
# ============================================================
class DownloadThread(QThread):
    """后台下载更新 zip，支持 cancel_event 取消"""
    progress = Signal(int, int)   # (downloaded, total)
    finished = Signal(str)        # 文件路径
    error = Signal(str)           # 错误信息
    cancelled = Signal()          # 用户取消

    def __init__(self, url, expected_sha256: str = "", parent=None):
        super().__init__(parent)
        self.url = url
        self.expected_sha256 = expected_sha256
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_event.set()

    def run(self):
        try:
            from updater import download_update
            path = download_update(
                self.url,
                progress_callback=lambda d, t: self.progress.emit(d, t),
                expected_sha256=self.expected_sha256,
                cancel_event=self._cancel_event,
            )
            self.finished.emit(path)
        except InterruptedError:
            self.cancelled.emit()
        except Exception as e:
            self.error.emit(str(e))


# ============================================================
# 更新对话框
# ============================================================
class UpdateDialog(QDialog):
    """应用内更新对话框"""

    def __init__(
        self,
        parent=None,
        auto_check: bool = False,
        info=None,
        force_full_package_once: bool = False,
    ):
        """
        info: 可选，已有的 UpdateInfo（由静默检查传入，跳过重复网络请求）
        """
        super().__init__(parent)
        self.setWindowTitle("检查更新")
        self.setMinimumSize(520, 420)
        self.resize(540, 460)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self._update_info = None
        self._zip_path = None
        self._is_patch = False
        self._is_downgrade = False
        self._patch_failed = False     # 避免重试时再次尝试已失败的 patch
        self._force_full_package_once = force_full_package_once
        self._check_thread = None
        self._download_thread = None
        self._active_channel = "prod"
        self._dl_start_time = 0.0      # 下载开始时间，用于速度计算

        self._init_ui()

        if info is not None:
            QTimer.singleShot(0, lambda: self._on_check_finished(info))
                # 直接展示已有结果，不再发起网络请求
            # cached result reuse
            # legacy channel cache path removed
                # 缓存结果与当前通道不一致时，直接按当前通道重查
            # legacy re-check path removed
        elif auto_check:
            QTimer.singleShot(100, self._on_check)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # ---- 顶部：版本 + 状态 ----
        top_layout = QHBoxLayout()
        ver_label = QLabel(f"当前版本：<b>V{APP_VERSION}</b>")
        ver_label.setFont(QFont("Microsoft YaHei", 11))
        top_layout.addWidget(ver_label)
        top_layout.addStretch()
        self._status_label = QLabel("点击下方按钮检查更新")
        self._status_label.setStyleSheet("color: #888; font-size: 12px;")
        top_layout.addWidget(self._status_label)
        layout.addLayout(top_layout)

        # ---- 更新通道 ----
        channel_layout = QHBoxLayout()
        channel_layout.setSpacing(8)
        channel_layout.addWidget(QLabel("更新通道："))

        self._channel_combo = QComboBox()
        self._channel_combo.setFixedWidth(220)
        self._channel_combo.addItem("正式（稳定）", "prod")
        saved_channel = "prod"
        idx = 0
        self._channel_combo.setCurrentIndex(idx)
        self._channel_combo.currentIndexChanged.connect(self._on_channel_changed)
        self._channel_combo.setVisible(False)
        channel_layout.addWidget(self._channel_combo)
        channel_layout.addStretch()
        # channel layout intentionally hidden from end users

        self._channel_tip_label = QLabel("")
        self._channel_tip_label.setWordWrap(True)
        self._channel_tip_label.setStyleSheet("color: #E65100; font-size: 12px;")
        self._channel_tip_label.setVisible(False)
        layout.addWidget(self._channel_tip_label)
        self._on_channel_changed()

        # ---- 更新信息区 ----
        self._info_text = QTextEdit()
        self._info_text.setReadOnly(True)
        self._info_text.setPlaceholderText("更新日志将显示在此处...")
        self._info_text.setStyleSheet("""
            QTextEdit {
                background: #FAFAFA;
                border: 1px solid #E0E0E0;
                border-radius: 6px;
                padding: 8px;
                font-size: 13px;
            }
        """)
        layout.addWidget(self._info_text, 1)

        # ---- 进度条 ----
        self._progress_bar = QProgressBar()
        self._progress_bar.setVisible(False)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #B3D7F0;
                border-radius: 4px;
                text-align: center;
                height: 24px;
                background: #F5F5F5;
                font-size: 12px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #1976D2, stop:1 #42A5F5);
                border-radius: 3px;
            }
        """)
        layout.addWidget(self._progress_bar)

        # ---- 按钮区 ----
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self._btn_check = QPushButton("检查更新")
        self._btn_check.setFixedHeight(36)
        self._btn_check.setCursor(Qt.PointingHandCursor)
        self._btn_check.setStyleSheet("""
            QPushButton {
                background: #1976D2; color: white;
                border: none; border-radius: 6px;
                font-size: 13px; font-weight: bold;
                padding: 0 24px;
            }
            QPushButton:hover { background: #1565C0; }
            QPushButton:disabled { background: #B0BEC5; }
        """)
        self._btn_check.clicked.connect(self._on_check)
        btn_layout.addWidget(self._btn_check)

        self._btn_download = QPushButton("下载并更新")
        self._btn_download.setFixedHeight(36)
        self._btn_download.setCursor(Qt.PointingHandCursor)
        self._btn_download.setVisible(False)
        self._btn_download.setStyleSheet("""
            QPushButton {
                background: #388E3C; color: white;
                border: none; border-radius: 6px;
                font-size: 13px; font-weight: bold;
                padding: 0 24px;
            }
            QPushButton:hover { background: #2E7D32; }
            QPushButton:disabled { background: #A5D6A7; }
        """)
        self._btn_download.clicked.connect(self._on_download)
        btn_layout.addWidget(self._btn_download)

        btn_layout.addStretch()

        # 取消按钮（下载中显示，替换关闭按钮位置）
        self._btn_cancel = QPushButton("取消下载")
        self._btn_cancel.setFixedHeight(36)
        self._btn_cancel.setCursor(Qt.PointingHandCursor)
        self._btn_cancel.setVisible(False)
        self._btn_cancel.setStyleSheet("""
            QPushButton {
                background: #F5F5F5; color: #C62828;
                border: 1px solid #EF9A9A; border-radius: 6px;
                font-size: 13px;
                padding: 0 24px;
            }
            QPushButton:hover { background: #FFEBEE; }
        """)
        self._btn_cancel.clicked.connect(self._on_cancel)
        btn_layout.addWidget(self._btn_cancel)

        self._btn_close = QPushButton("关闭")
        self._btn_close.setFixedHeight(36)
        self._btn_close.setCursor(Qt.PointingHandCursor)
        self._btn_close.setStyleSheet("""
            QPushButton {
                background: #F5F5F5; color: #333;
                border: 1px solid #E0E0E0; border-radius: 6px;
                font-size: 13px;
                padding: 0 24px;
            }
            QPushButton:hover { background: #EEEEEE; }
        """)
        self._btn_close.clicked.connect(self.close)
        btn_layout.addWidget(self._btn_close)

        layout.addLayout(btn_layout)

    def _current_channel(self) -> str:
        channel = "prod"
        if False:
            return "test"
        return "prod"

    def _on_channel_changed(self):
        channel = self._current_channel()
        channel = "prod"
        if channel == "test":
            self._channel_tip_label.setText(
                "⚠ 测试版可能不稳定，建议仅用于验证；如需稳定生产，请切回正式通道。"
            )
        else:
            self._channel_tip_label.setText(
                "正式通道更稳定；若当前安装了测试构建，可在此通道执行降级安装。"
            )

    def _bind_download_handler(self, handler):
        try:
            self._btn_download.clicked.disconnect()
        except Exception:
            pass
        self._btn_download.clicked.connect(handler)

    def _reset_download_button(self):
        self._btn_download.setEnabled(True)
        self._btn_download.setStyleSheet("""
            QPushButton {
                background: #388E3C; color: white;
                border: none; border-radius: 6px;
                font-size: 13px; font-weight: bold;
                padding: 0 24px;
            }
            QPushButton:hover { background: #2E7D32; }
            QPushButton:disabled { background: #A5D6A7; }
        """)
        self._bind_download_handler(self._on_download)

    def _download_button_text(self) -> str:
        info = self._update_info
        if not info:
            return "下载并更新"
        if self._is_downgrade:
            if info.file_size_mb:
                return f"下载正式版并降级 ({info.file_size_mb:.1f} MB)"
            return "下载正式版并降级"
        if (
            not self._force_full_package_once
            and info.can_use_patch
            and not self._patch_failed
            and info.patch_size_mb
        ):
            return f"下载增量补丁包 ({info.patch_size_mb:.1f} MB)"
        if info.file_size_mb:
            return f"下载全量包 ({info.file_size_mb:.1f} MB)"
        return "下载并更新"

    # ---- 检查更新 ----
    def _on_check(self):
        self._reset_download_button()
        self._zip_path = None
        self._is_downgrade = False
        self._active_channel = "prod"
        self._btn_check.setEnabled(False)
        self._btn_check.setText("正在检查...")
        channel_name = "正式通道"
        self._status_label.setText(f"正在连接{channel_name}服务器...")
        self._status_label.setStyleSheet("color: #1976D2; font-size: 12px;")
        self._info_text.clear()
        self._btn_download.setVisible(False)
        self._patch_failed = False

        self._check_thread = CheckUpdateThread(
            self,
            allow_downgrade=True,
        )
        self._check_thread.finished.connect(self._on_check_finished)
        self._check_thread.start()

    def _on_check_finished(self, info):
        self._btn_check.setEnabled(True)
        self._btn_check.setText("检查更新")

        if info is None:
            self._status_label.setText("⚠ 无法连接到更新服务器")
            self._status_label.setStyleSheet("color: #E65100; font-size: 12px;")
            is_test_channel = False
            channel_hint = ""
            self._info_text.setPlainText(
                "检查更新失败，可能的原因：\n\n"
                "1. 网络未连接\n"
                "2. 更新服务器暂时不可用\n"
                "3. 防火墙阻止了连接\n\n"
                f"{channel_hint}"
                "请稍后再试，或联系技术支持获取最新版本。"
            )
            return

        self._update_info = info
        self._active_channel = "prod"
        self._is_downgrade = bool(info.allow_downgrade and info.can_offer_downgrade)

        if info.is_newer_than_local:
            self._status_label.setText(f"✨ 发现新版本 V{info.latest_version}")
            self._status_label.setStyleSheet(
                "color: #388E3C; font-weight: bold; font-size: 12px;"
            )

            lines = [
                f"<h3 style='margin:0 0 4px 0;'>新版本 V{info.latest_version}</h3>",
                f"<p style='color:#666; margin:2px 0;'>发布日期：{info.release_date}</p>",
            ]
            if (
                not self._force_full_package_once
                and info.can_use_patch
                and not self._patch_failed
                and info.patch_size_mb
            ):
                lines.append(
                    f"<p style='color:#1976D2; margin:2px 0;'>"
                    f"补丁包：<b>{info.patch_size_mb:.1f} MB</b>"
                    f"&nbsp;&nbsp;<span style='color:#999;'>（全量包 {info.file_size_mb:.1f} MB）</span></p>"
                )
            if self._force_full_package_once and info.file_size_mb:
                lines.append(
                    f"<p style='color:#E65100; margin:2px 0;'>"
                    f"本次将直接下载全量包：<b>{info.file_size_mb:.1f} MB</b></p>"
                )
            elif info.file_size_mb:
                lines.append(
                    f"<p style='color:#666; margin:2px 0;'>"
                    f"下载大小：<b>{info.file_size_mb:.1f} MB</b></p>"
                )
            lines.append("<hr style='margin:8px 0;'>")
            lines.append("<b>更新内容：</b>")
            for line in info.changelog.split("\n"):
                line = line.strip()
                if line.startswith("- "):
                    lines.append(f"<li style='margin:2px 0;'>{line[2:]}</li>")
                elif line:
                    lines.append(f"<p style='margin:2px 0;'>{line}</p>")
            if info.is_forced:
                lines.append(
                    "<p style='color:red; font-weight:bold; margin-top:8px;'>"
                    "⚠ 当前版本过旧，必须更新后才能继续使用。</p>"
                )

            self._info_text.setHtml("\n".join(lines))
            self._btn_download.setText(self._download_button_text())
            self._btn_download.setVisible(True)
        elif self._is_downgrade:
            self._status_label.setText(f"↩ 可降级到正式版 V{info.latest_version}")
            self._status_label.setStyleSheet(
                "color: #E65100; font-weight: bold; font-size: 12px;"
            )

            lines = [
                f"<h3 style='margin:0 0 4px 0;'>正式版 V{info.latest_version}</h3>",
                f"<p style='color:#666; margin:2px 0;'>发布日期：{info.release_date}</p>",
                "<p style='color:#E65100; margin:6px 0;'>"
                "当前版本高于正式通道，可选择下载正式版执行降级。</p>",
            ]
            if info.file_size_mb:
                lines.append(
                    f"<p style='color:#666; margin:2px 0;'>"
                    f"下载大小：<b>{info.file_size_mb:.1f} MB</b></p>"
                )
            lines.append("<hr style='margin:8px 0;'>")
            lines.append("<b>正式版更新内容：</b>")
            for line in info.changelog.split("\n"):
                line = line.strip()
                if line.startswith("- "):
                    lines.append(f"<li style='margin:2px 0;'>{line[2:]}</li>")
                elif line:
                    lines.append(f"<p style='margin:2px 0;'>{line}</p>")
            self._info_text.setHtml("\n".join(lines))
            self._btn_download.setText(self._download_button_text())
            self._btn_download.setVisible(True)
        else:
            self._status_label.setText("✅ 已是最新版本")
            self._status_label.setStyleSheet(
                "color: #388E3C; font-weight: bold; font-size: 12px;"
            )
            self._info_text.setPlainText(
                f"当前版本 V{APP_VERSION} 已是最新版本，无需更新。"
            )

    # ---- 下载更新 ----
    def _on_download(self):
        if not self._update_info or not self._update_info.download_url:
            return

        info = self._update_info
        if self._is_downgrade:
            self._is_patch = False
            url = info.download_urls
            expected_sha256 = info.download_sha256
            size_text = f"{info.file_size_mb:.1f} MB" if info.file_size_mb else "未知大小"
            label = f"正在下载正式版（降级）({size_text}) ..."
        # 优先下载补丁包（除非已知 patch 失败）
        elif (
            not self._force_full_package_once
            and info.can_use_patch
            and not self._patch_failed
        ):
            self._is_patch = True
            url = info.patch_urls
            expected_sha256 = info.patch_sha256
            label = f"正在下载增量补丁包 ({info.patch_size_mb:.1f} MB) ..."
        else:
            self._is_patch = False
            url = info.download_urls
            expected_sha256 = info.download_sha256
            label = f"正在下载全量包 ({info.file_size_mb:.1f} MB) ..."

        self._btn_download.setEnabled(False)
        self._btn_download.setText("正在下载...")
        self._btn_check.setEnabled(False)
        self._progress_bar.setVisible(True)
        self._progress_bar.setMaximum(100)
        self._progress_bar.setValue(0)
        self._progress_bar.setFormat("准备中...")
        self._btn_cancel.setVisible(True)
        self._btn_close.setVisible(False)
        self._status_label.setText(label)
        self._status_label.setStyleSheet("color: #1976D2; font-size: 12px;")
        self._dl_start_time = time.monotonic()

        self._download_thread = DownloadThread(url, expected_sha256, self)
        self._download_thread.progress.connect(self._on_download_progress)
        self._download_thread.finished.connect(self._on_download_finished)
        self._download_thread.error.connect(self._on_download_error)
        self._download_thread.cancelled.connect(self._on_download_cancelled)
        self._download_thread.start()

    def _on_download_progress(self, downloaded: int, total: int):
        if total > 0:
            pct = int(downloaded * 100 / total)
            self._progress_bar.setMaximum(100)
            self._progress_bar.setValue(pct)
            mb_done = downloaded / (1024 * 1024)
            mb_total = total / (1024 * 1024)

            # 计算速度 + ETA
            elapsed = time.monotonic() - self._dl_start_time
            if elapsed > 0.5:  # 至少等0.5秒才显示速度
                speed_bytes = downloaded / elapsed
                speed_mb = speed_bytes / (1024 * 1024)
                remaining = total - downloaded
                eta_sec = remaining / speed_bytes if speed_bytes > 0 else 0
                if eta_sec >= 60:
                    eta_str = f"剩余约 {int(eta_sec/60)} 分 {int(eta_sec%60)} 秒"
                else:
                    eta_str = f"剩余约 {int(eta_sec)+1} 秒"
                fmt = f"{mb_done:.1f} / {mb_total:.1f} MB  ·  {speed_mb:.1f} MB/s  ·  {eta_str}"
            else:
                fmt = f"{mb_done:.1f} / {mb_total:.1f} MB  ({pct}%)"

            self._progress_bar.setFormat(fmt)
        else:
            self._progress_bar.setMaximum(0)
            mb_done = downloaded / (1024 * 1024)
            self._status_label.setText(f"已下载 {mb_done:.1f} MB ...")

    def _on_download_finished(self, zip_path: str):
        self._zip_path = zip_path
        self._progress_bar.setValue(100)
        self._progress_bar.setFormat("✓ 下载完成")
        self._status_label.setText("✅ 下载完成，点击按钮立即安装")
        self._status_label.setStyleSheet(
            "color: #388E3C; font-weight: bold; font-size: 12px;"
        )
        self._btn_cancel.setVisible(False)
        self._btn_close.setVisible(True)

        self._btn_download.setText("立即安装并降级" if self._is_downgrade else "立即安装更新")
        self._btn_download.setEnabled(True)
        self._btn_download.setStyleSheet("""
            QPushButton {
                background: #D32F2F; color: white;
                border: none; border-radius: 6px;
                font-size: 13px; font-weight: bold;
                padding: 0 24px;
            }
            QPushButton:hover { background: #C62828; }
        """)
        self._btn_download.clicked.disconnect()
        self._btn_download.clicked.connect(self._on_install)

    def _on_download_cancelled(self):
        """用户点取消后恢复 UI"""
        self._progress_bar.setVisible(False)
        self._btn_cancel.setVisible(False)
        self._btn_close.setVisible(True)
        self._btn_download.setEnabled(True)
        self._btn_check.setEnabled(True)
        self._status_label.setText("已取消下载")
        self._status_label.setStyleSheet("color: #888; font-size: 12px;")
        self._btn_download.setText(self._download_button_text())

    def _on_cancel(self):
        """点击取消按钮"""
        if self._download_thread and self._download_thread.isRunning():
            self._btn_cancel.setEnabled(False)
            self._btn_cancel.setText("正在取消...")
            self._download_thread.cancel()

    def _on_download_error(self, error_msg: str):
        # patch 下载失败 → 自动回退全量包（仅一次，记录 _patch_failed）
        if self._is_patch and self._update_info and self._update_info.download_url:
            self._is_patch = False
            self._patch_failed = True
            self._status_label.setText("补丁包下载失败，正在切换到全量包...")
            self._status_label.setStyleSheet("color: #E65100; font-size: 12px;")
            self._progress_bar.setValue(0)
            self._progress_bar.setFormat("准备中...")
            self._dl_start_time = time.monotonic()
            info = self._update_info
            self._btn_download.setText(
                f"正在下载全量包 ({info.file_size_mb:.1f} MB) ..."
            )
            self._download_thread = DownloadThread(
                self._update_info.download_urls,
                self._update_info.download_sha256,
                self,
            )
            self._download_thread.progress.connect(self._on_download_progress)
            self._download_thread.finished.connect(self._on_download_finished)
            self._download_thread.error.connect(self._on_download_error)
            self._download_thread.cancelled.connect(self._on_download_cancelled)
            self._download_thread.start()
            return

        # 全量包也失败
        self._btn_cancel.setVisible(False)
        self._btn_close.setVisible(True)
        self._btn_download.setEnabled(True)
        self._btn_download.setText("重试下载")
        self._btn_check.setEnabled(True)
        self._progress_bar.setVisible(False)
        self._status_label.setText("⚠ 下载失败")
        self._status_label.setStyleSheet("color: #E65100; font-size: 12px;")
        self._info_text.setPlainText(
            f"下载更新失败：\n\n{error_msg}\n\n请检查网络后重试。"
        )
        # 下次点重试跳过 patch（已失败）
        self._patch_failed = True

    def closeEvent(self, event):
        """关闭时若正在下载，先取消再关闭"""
        if self._download_thread and self._download_thread.isRunning():
            self._download_thread.cancel()
            self._download_thread.wait(3000)
        super().closeEvent(event)

    def _is_project_dirty(self) -> bool:
        parent = self.parent()
        project_manager = getattr(parent, "project_manager", None)
        return bool(project_manager and getattr(project_manager, "is_dirty", False))

    def _confirm_save_before_install(self) -> bool:
        """询问用户是否先保存项目再继续安装。"""
        title = "保存后继续安装"
        content = (
            "检测到当前项目还有未保存修改。\n\n"
            "是否先保存项目，然后继续安装已经下载好的更新包？"
        )
        try:
            from app_渠系计算前端.styles import fluent_question

            return bool(
                fluent_question(
                    self,
                    title,
                    content,
                    yes_text="保存并继续安装",
                    no_text="稍后再说",
                )
            )
        except Exception:
            box = QMessageBox(self)
            box.setWindowTitle(title)
            box.setText(content)
            box.setIcon(QMessageBox.Question)
            save_button = box.addButton("保存并继续安装", QMessageBox.AcceptRole)
            box.addButton("稍后再说", QMessageBox.RejectRole)
            box.setDefaultButton(save_button)
            box.exec()
            return box.clickedButton() is save_button

    def _ensure_project_saved_before_install(self) -> bool:
        """安装前确保项目已保存，保存成功后继续复用已下载更新包。"""
        if not self._is_project_dirty():
            return True

        if not self._confirm_save_before_install():
            self._status_label.setText("已下载更新包，保存项目后可继续安装")
            self._status_label.setStyleSheet("color: #E65100; font-size: 12px;")
            return False

        parent = self.parent()
        project_manager = getattr(parent, "project_manager", None)
        if not project_manager or not hasattr(project_manager, "save_project"):
            QMessageBox.warning(
                self,
                "暂时无法安装",
                "未找到项目保存入口，请先手动保存项目后再安装更新。",
            )
            return False

        try:
            saved = bool(project_manager.save_project())
        except Exception as exc:
            QMessageBox.critical(
                self,
                "保存失败",
                f"保存项目时出现异常：\n{exc}\n\n已下载更新包仍会保留，请保存后再次点击“立即安装更新”。",
            )
            return False

        if not saved:
            self._status_label.setText("项目尚未保存，已下载更新包仍会保留")
            self._status_label.setStyleSheet("color: #E65100; font-size: 12px;")
            return False

        return True

    def _validate_before_install(self) -> bool:
        if not self._ensure_project_saved_before_install():
            return False

        from updater import ensure_update_package_ready, UpdatePreparationError

        try:
            expected_sha256 = ""
            if self._update_info:
                expected_sha256 = (
                    self._update_info.patch_sha256
                    if self._is_patch
                    else self._update_info.download_sha256
                )
            ensure_update_package_ready(self._zip_path, expected_sha256)
        except UpdatePreparationError as exc:
            QMessageBox.warning(self, "暂时无法安装", str(exc))
            return False
        except Exception as exc:
            QMessageBox.critical(
                self,
                "安装前检查失败",
                f"安装前检查时出现异常：\n{exc}\n\n请稍后重试，或重新下载更新包。",
            )
            return False

        return True

    # ---- 安装更新 ----
    def _on_install(self):
        if not self._zip_path:
            return
        if not self._validate_before_install():
            return

        if self._is_downgrade:
            title_text = "确认降级安装"
            body_text = (
                "将安装正式版并覆盖当前版本（降级）。\n\n"
                "请确认已备份项目并保存所有工作，点击「确定」继续。"
            )
        else:
            title_text = "确认安装更新"
            body_text = "安装更新需要关闭程序，请确保已保存所有工作。\n\n点击「确定」立即关闭并更新。"

        try:
            from qfluentwidgets import MessageBox as FluentMessageBox
            w = FluentMessageBox(
                title_text,
                body_text,
                self,
            )
            if not w.exec():
                return
        except Exception:
            from PySide6.QtWidgets import QMessageBox
            ret = QMessageBox.question(
                self, "确认更新",
                body_text,
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if ret != QMessageBox.Yes:
                return

        from updater import create_update_session, launch_updater_and_exit
        try:
            expected_sha256 = ""
            if self._update_info:
                expected_sha256 = (
                    self._update_info.patch_sha256
                    if self._is_patch
                    else self._update_info.download_sha256
                )
            session_path = create_update_session(
                self._zip_path,
                is_patch=self._is_patch,
                target_version=self._update_info.latest_version if self._update_info else APP_VERSION,
                current_version=APP_VERSION,
                expected_package_sha256=expected_sha256,
                full_download_url=self._update_info.download_url if self._update_info else "",
                full_download_urls=self._update_info.download_urls if self._update_info else [],
                full_package_sha256=self._update_info.download_sha256 if self._update_info else "",
                full_package_size_mb=self._update_info.file_size_mb if self._update_info else 0,
            )
            launch_updater_and_exit(session_path)
        except Exception as e:
            QMessageBox.critical(
                self, "更新失败",
                f"启动安装助手失败：\n{e}\n\n请重新下载更新包后重试。"
            )


# ============================================================
# 启动时静默检查（非阻塞、不弹窗，仅在有更新时通知）
# ============================================================
class SilentUpdateChecker(CheckUpdateThread):
    """
    启动时的静默更新检查。
    只在发现新版本时发出信号，由主窗口决定如何提示。
    """
    update_available = Signal(object)  # UpdateInfo

    def __init__(self, parent=None):
        super().__init__(parent, allow_downgrade=False)
        self.finished.connect(self._handle_result)

    def _handle_result(self, info):
        if info is not None and info.has_update:
            self.update_available.emit(info)

