# -*- coding: utf-8 -*-
"""
应用内更新对话框

提供：
- 检查更新（后台线程）
- 显示更新日志
- 下载进度条
- 一键更新
"""

import os
import sys

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QTextEdit, QWidget, QSizePolicy, QApplication,
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont

from version import APP_VERSION, APP_NAME


# ============================================================
# 后台线程：检查更新
# ============================================================
class CheckUpdateThread(QThread):
    """后台检查远程版本"""
    finished = Signal(object)  # UpdateInfo or None

    def run(self):
        from updater import check_for_update
        info = check_for_update()
        self.finished.emit(info)


# ============================================================
# 后台线程：下载更新包
# ============================================================
class DownloadThread(QThread):
    """后台下载更新 zip"""
    progress = Signal(int, int)   # (downloaded, total)
    finished = Signal(str)        # 文件路径
    error = Signal(str)           # 错误信息

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.url = url

    def run(self):
        try:
            from updater import download_update
            path = download_update(
                self.url,
                progress_callback=lambda d, t: self.progress.emit(d, t),
            )
            self.finished.emit(path)
        except Exception as e:
            self.error.emit(str(e))


# ============================================================
# 更新对话框
# ============================================================
class UpdateDialog(QDialog):
    """应用内更新对话框"""

    def __init__(self, parent=None, auto_check: bool = False):
        super().__init__(parent)
        self.setWindowTitle("检查更新")
        self.setMinimumSize(500, 400)
        self.resize(520, 440)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self._update_info = None
        self._zip_path = None
        self._is_patch = False
        self._check_thread = None
        self._download_thread = None

        self._init_ui()

        if auto_check:
            QTimer.singleShot(100, self._on_check)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # ---- 当前版本 ----
        ver_layout = QHBoxLayout()
        ver_label = QLabel(f"当前版本：<b>V{APP_VERSION}</b>")
        ver_label.setFont(QFont("Microsoft YaHei", 11))
        ver_layout.addWidget(ver_label)
        ver_layout.addStretch()

        self._status_label = QLabel("点击下方按钮检查更新")
        self._status_label.setStyleSheet("color: #666;")
        ver_layout.addWidget(self._status_label)
        layout.addLayout(ver_layout)

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
                height: 22px;
                background: #F5F5F5;
            }
            QProgressBar::chunk {
                background: #1976D2;
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

    # ---- 检查更新 ----
    def _on_check(self):
        self._btn_check.setEnabled(False)
        self._btn_check.setText("正在检查...")
        self._status_label.setText("正在连接服务器...")
        self._status_label.setStyleSheet("color: #1976D2;")
        self._info_text.clear()
        self._btn_download.setVisible(False)

        self._check_thread = CheckUpdateThread(self)
        self._check_thread.finished.connect(self._on_check_finished)
        self._check_thread.start()

    def _on_check_finished(self, info):
        self._btn_check.setEnabled(True)
        self._btn_check.setText("检查更新")

        if info is None:
            self._status_label.setText("⚠ 无法连接到更新服务器")
            self._status_label.setStyleSheet("color: #E65100;")
            self._info_text.setPlainText(
                "检查更新失败，可能的原因：\n\n"
                "1. 网络未连接\n"
                "2. 更新服务器暂时不可用\n"
                "3. 防火墙阻止了连接\n\n"
                "请稍后再试，或联系技术支持获取最新版本。"
            )
            return

        self._update_info = info

        if info.has_update:
            self._status_label.setText(
                f"✨ 发现新版本 V{info.latest_version}"
            )
            self._status_label.setStyleSheet("color: #388E3C; font-weight: bold;")

            changelog_lines = [
                f"<h3>新版本 V{info.latest_version}</h3>",
                f"<p style='color:#666;'>发布日期：{info.release_date}</p>",
            ]
            if info.has_patch and info.patch_size_mb:
                changelog_lines.append(
                    f"<p style='color:#666;'>补丁包：{info.patch_size_mb:.1f} MB"
                    f"（全量包 {info.file_size_mb:.1f} MB）</p>"
                )
            elif info.file_size_mb:
                changelog_lines.append(
                    f"<p style='color:#666;'>文件大小：{info.file_size_mb:.1f} MB</p>"
                )
            changelog_lines.append("<hr>")
            changelog_lines.append("<h4>更新内容：</h4>")

            # 将 \n 分隔的 changelog 转为 HTML 列表
            for line in info.changelog.split("\n"):
                line = line.strip()
                if line.startswith("- "):
                    changelog_lines.append(f"<li>{line[2:]}</li>")
                elif line:
                    changelog_lines.append(f"<p>{line}</p>")

            if info.is_forced:
                changelog_lines.append(
                    "<p style='color:red; font-weight:bold;'>"
                    "⚠ 当前版本过旧，必须更新后才能继续使用。"
                    "</p>"
                )

            self._info_text.setHtml("\n".join(changelog_lines))
            self._btn_download.setVisible(True)
        else:
            self._status_label.setText("✅ 已是最新版本")
            self._status_label.setStyleSheet("color: #388E3C; font-weight: bold;")
            self._info_text.setPlainText(
                f"当前版本 V{APP_VERSION} 已是最新版本，无需更新。"
            )

    # ---- 下载更新 ----
    def _on_download(self):
        if not self._update_info or not self._update_info.download_url:
            return

        self._btn_download.setEnabled(False)
        self._btn_check.setEnabled(False)
        self._progress_bar.setVisible(True)
        self._progress_bar.setValue(0)

        # 优先下载补丁包
        info = self._update_info
        if info.has_patch:
            self._is_patch = True
            url = info.patch_url
            self._btn_download.setText("正在下载补丁包...")
            self._status_label.setText("正在下载增量补丁包...")
        else:
            self._is_patch = False
            url = info.download_url
            self._btn_download.setText("正在下载...")
            self._status_label.setText("正在下载全量更新包...")
        self._status_label.setStyleSheet("color: #1976D2;")

        self._download_thread = DownloadThread(url, self)
        self._download_thread.progress.connect(self._on_download_progress)
        self._download_thread.finished.connect(self._on_download_finished)
        self._download_thread.error.connect(self._on_download_error)
        self._download_thread.start()

    def _on_download_progress(self, downloaded: int, total: int):
        if total > 0:
            pct = int(downloaded * 100 / total)
            self._progress_bar.setMaximum(100)
            self._progress_bar.setValue(pct)
            mb_done = downloaded / (1024 * 1024)
            mb_total = total / (1024 * 1024)
            self._progress_bar.setFormat(
                f"{mb_done:.1f} / {mb_total:.1f} MB  ({pct}%)"
            )
        else:
            # 未知总大小 → 使用忙碌模式
            self._progress_bar.setMaximum(0)
            mb_done = downloaded / (1024 * 1024)
            self._status_label.setText(f"已下载 {mb_done:.1f} MB ...")

    def _on_download_finished(self, zip_path: str):
        self._zip_path = zip_path
        self._progress_bar.setValue(100)
        self._progress_bar.setFormat("下载完成！")
        self._status_label.setText("✅ 下载完成，准备安装更新...")
        self._status_label.setStyleSheet("color: #388E3C; font-weight: bold;")

        self._btn_download.setText("立即安装更新")
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
        # 重绑定点击事件为「安装」
        self._btn_download.clicked.disconnect()
        self._btn_download.clicked.connect(self._on_install)

    def _on_download_error(self, error_msg: str):
        # 补丁包下载失败时，自动回退到全量包
        if self._is_patch and self._update_info and self._update_info.download_url:
            self._is_patch = False
            self._status_label.setText("补丁包下载失败，正在回退到全量包...")
            self._status_label.setStyleSheet("color: #E65100;")
            self._progress_bar.setValue(0)
            self._btn_download.setText("正在下载全量包...")
            self._download_thread = DownloadThread(
                self._update_info.download_url, self
            )
            self._download_thread.progress.connect(self._on_download_progress)
            self._download_thread.finished.connect(self._on_download_finished)
            self._download_thread.error.connect(self._on_download_error)
            self._download_thread.start()
            return

        self._btn_download.setEnabled(True)
        self._btn_download.setText("重试下载")
        self._btn_check.setEnabled(True)
        self._progress_bar.setVisible(False)
        self._status_label.setText("⚠ 下载失败")
        self._status_label.setStyleSheet("color: #E65100;")
        self._info_text.setPlainText(f"下载更新失败：\n\n{error_msg}\n\n请检查网络后重试。")

    # ---- 安装更新 ----
    def _on_install(self):
        if not self._zip_path:
            return

        from PySide6.QtWidgets import QMessageBox

        ret = QMessageBox.question(
            self,
            "确认更新",
            "安装更新需要关闭程序。\n\n"
            "请确保已保存所有工作，点击「是」开始更新。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return

        from updater import apply_update, launch_updater_and_exit

        try:
            bat_path = apply_update(self._zip_path, is_patch=self._is_patch)
            launch_updater_and_exit(bat_path)
        except Exception as e:
            QMessageBox.critical(
                self, "更新失败",
                f"生成更新脚本失败：\n{e}\n\n请手动下载最新版本。"
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
        super().__init__(parent)
        self.finished.connect(self._handle_result)

    def _handle_result(self, info):
        if info is not None and info.has_update:
            self.update_available.emit(info)
