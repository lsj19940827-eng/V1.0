# -*- coding: utf-8 -*-
"""
可视化发版工具

PySide6 + qfluentwidgets 界面，一键完成：
  调用 tools/release.py 的标准流程，包含本地、远端和线上更新强制验收。

用法：
    python tools/release_gui.py
"""

import os
import subprocess
import sys
import threading

# ---- 路径设置 ----
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
PROJECT_VENV_PYTHON = os.path.join(PROJECT_ROOT, ".venv", "Scripts", "python.exe")
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, SCRIPT_DIR)

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")


def _project_python() -> str:
    """Prefer the project's venv interpreter for reproducible release builds."""
    if os.path.exists(PROJECT_VENV_PYTHON):
        return PROJECT_VENV_PYTHON
    return sys.executable

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QGroupBox, QFrame, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QObject, QSize
from PySide6.QtGui import QFont, QColor, QTextCursor, QIcon

from qfluentwidgets import (
    PrimaryPushButton, PushButton, ComboBox, TextEdit,
    InfoBar, InfoBarPosition, ProgressBar,
)

from version import APP_VERSION, APP_NAME

# ---- 样式常量 ----
P = "#1976D2"
S = "#2E7D32"
W = "#F57C00"
E = "#D32F2F"
BG = "#F5F7FA"
CARD = "#FFFFFF"
BD = "#E0E0E0"
T1 = "#212121"
T2 = "#424242"


# ============================================================
# 信号桥：子线程 → 主线程
# ============================================================
class SignalBridge(QObject):
    log_signal = Signal(str, str)       # (message, color)
    step_signal = Signal(int, str)      # (step_index, status: 'running'|'done'|'error')
    finished_signal = Signal(bool, str) # (success, message)
    progress_signal = Signal(int)       # percent 0-100


def _run_release(level: str, changelog: str, bridge: SignalBridge):
    """界面只调用标准发布入口，所有验收失败都由子进程退出码拦截。"""
    active = 0
    bridge.step_signal.emit(active, "running")
    markers = (("[步骤 1/6]", 1), ("[步骤 2/6]", 2), ("[验收 U01-U07]", 3),
               ("[步骤 3/6]", 4), ("[步骤 4/6]", 5), ("[步骤 5/6]", 6),
               ("[验收 U08]", 7), ("[步骤 6/6]", 8), ("[验收 U09]", 9))
    try:
        command = [_project_python(), "-u", os.path.join(SCRIPT_DIR, "release.py"),
                   level, "-m", changelog]
        bridge.log_signal.emit("正在执行标准发布流程及强制更新验收。", "")
        bridge.progress_signal.emit(-1)
        with subprocess.Popen(command, cwd=PROJECT_ROOT, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                              errors="replace", env=dict(os.environ, PYTHONUTF8="1")) as process:
            for line in process.stdout:
                bridge.log_signal.emit(line.rstrip(), "")
                for marker, index in markers:
                    if marker in line and index > active:
                        bridge.step_signal.emit(active, "done")
                        active = index
                        bridge.step_signal.emit(active, "running")
            code = process.wait()
        if code != 0:
            raise RuntimeError(f"发布已停止（退出码 {code}），请查看验收日志处理失败项。")
        bridge.step_signal.emit(active, "done")
        bridge.progress_signal.emit(100)
        bridge.finished_signal.emit(True, "发布及在线更新验收全部通过。")
    except Exception as exc:
        bridge.step_signal.emit(active, "error")
        bridge.log_signal.emit(str(exc), E)
        bridge.finished_signal.emit(False, str(exc))


# ============================================================
# 主界面
# ============================================================
class ReleaseWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"发版工具 — {APP_NAME}")
        self.setMinimumSize(720, 680)
        self.resize(780, 760)

        # 窗口图标
        _logo = os.path.join(PROJECT_ROOT, "app_渠系计算前端", "resources", "logo.ico")
        if not os.path.exists(_logo):
            _logo = os.path.join(PROJECT_ROOT, "app_渠系计算前端", "resources", "logo.svg")
        if os.path.exists(_logo):
            self.setWindowIcon(QIcon(_logo))
        self._bridge = SignalBridge()
        self._bridge.log_signal.connect(self._on_log)
        self._bridge.step_signal.connect(self._on_step)
        self._bridge.finished_signal.connect(self._on_finished)
        self._bridge.progress_signal.connect(self._on_progress)
        self._running = False
        self._step_labels = []
        self._init_ui()

    def _info_parent(self):
        return self

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

        main_lay = QVBoxLayout(self)
        main_lay.setContentsMargins(20, 16, 20, 16)
        main_lay.setSpacing(12)

        # ---- 标题（Logo + 文字） ----
        title_row = QHBoxLayout()
        title_row.setSpacing(10)

        _logo_path = os.path.join(PROJECT_ROOT, "app_渠系计算前端", "resources", "logo.ico")
        if not os.path.exists(_logo_path):
            _logo_path = os.path.join(PROJECT_ROOT, "app_渠系计算前端", "resources", "logo.svg")
        if os.path.exists(_logo_path):
            logo_lbl = QLabel()
            logo_lbl.setFixedSize(36, 36)
            logo_pix = QIcon(_logo_path).pixmap(QSize(36, 36))
            logo_lbl.setPixmap(logo_pix)
            title_row.addWidget(logo_lbl)

        title = QLabel(f"一键发版")
        title.setFont(QFont("Microsoft YaHei", 16, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {P}; padding: 4px 0;")
        title_row.addWidget(title)
        title_row.addStretch()
        main_lay.addLayout(title_row)

        ver_label = QLabel(f"当前版本: V{APP_VERSION}")
        ver_label.setStyleSheet(f"font-size: 14px; color: {T2}; padding-bottom: 4px;")
        main_lay.addWidget(ver_label)
        self._ver_label = ver_label

        # ---- 配置区 ----
        config_group = QGroupBox("发版配置")
        config_lay = QVBoxLayout(config_group)
        config_lay.setSpacing(10)

        # 版本级别
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("版本级别:"))
        self._level_combo = ComboBox()
        self._level_combo.addItems(["hotfix — 热修复", "patch — 补丁版本", "minor — 次版本", "major — 主版本"])
        self._level_combo.setCurrentIndex(0)
        self._level_combo.setFixedWidth(260)
        row1.addWidget(self._level_combo)

        # 预览新版本号
        self._preview_label = QLabel()
        self._preview_label.setStyleSheet(f"color: {S}; font-weight: bold; font-size: 13px;")
        self._update_version_preview()
        self._level_combo.currentIndexChanged.connect(self._update_version_preview)
        row1.addWidget(self._preview_label)
        row1.addStretch()
        config_lay.addLayout(row1)

        # 更新日志
        config_lay.addWidget(QLabel("更新日志:"))
        self._changelog_edit = QTextEdit()
        self._changelog_edit.setPlaceholderText(
            "每行一条，例如：\n- 修复水面线计算bug\n- 新增批量导出功能\n- 优化界面响应速度"
        )
        self._changelog_edit.setFixedHeight(100)
        self._changelog_edit.setStyleSheet(
            f"QTextEdit {{ border: 1px solid {BD}; border-radius: 6px;"
            f" background: #FAFBFC; padding: 8px; font-size: 13px; }}"
        )
        config_lay.addWidget(self._changelog_edit)

        main_lay.addWidget(config_group)

        # ---- 步骤进度区 ----
        steps_group = QGroupBox("执行进度")
        steps_lay = QVBoxLayout(steps_group)
        steps_lay.setSpacing(6)

        step_names = [
            "检查发布条件",
            "递增版本号",
            "构建发布包",
            "本地安装与更新验收",
            "提交代码与版本标签",
            "创建发布记录",
            "上传发布包",
            "完整下载并核验远端文件",
            "切换正式更新清单",
            "应用内线上升级验收",
        ]
        for i, name in enumerate(step_names):
            lbl = QLabel(f"  ○  {name}")
            lbl.setStyleSheet(f"color: {T2}; font-size: 13px; padding: 2px 4px;")
            lbl.setFixedHeight(24)
            steps_lay.addWidget(lbl)
            self._step_labels.append(lbl)

        self._progress = ProgressBar()
        self._progress.setFixedHeight(4)
        self._progress.setValue(0)
        steps_lay.addWidget(self._progress)

        main_lay.addWidget(steps_group)

        # ---- 日志区 ----
        log_group = QGroupBox("日志")
        log_lay = QVBoxLayout(log_group)
        self._log_edit = QTextEdit()
        self._log_edit.setReadOnly(True)
        self._log_edit.setStyleSheet(
            f"QTextEdit {{ border: 1px solid {BD}; border-radius: 6px;"
            f" background: #1E1E2E; padding: 10px;"
            f" font-family: 'Consolas', 'Courier New', monospace;"
            f" font-size: 12px; color: #E0E0E0; }}"
        )
        self._log_edit.setMinimumHeight(120)
        log_lay.addWidget(self._log_edit)
        main_lay.addWidget(log_group, 1)

        # ---- 按钮 ----
        btn_lay = QHBoxLayout()
        btn_lay.addStretch()

        self._start_btn = PrimaryPushButton("开始发版")
        self._start_btn.setFixedSize(160, 40)
        self._start_btn.setFont(QFont("Microsoft YaHei", 13, QFont.Weight.Bold))
        self._start_btn.clicked.connect(self._on_start)
        btn_lay.addWidget(self._start_btn)

        btn_lay.addStretch()
        main_lay.addLayout(btn_lay)

    def _get_level(self) -> str:
        return self._level_combo.currentText().split(" ")[0]

    def _calc_new_version(self, level: str) -> str:
        parts = [int(x) for x in APP_VERSION.split(".")]
        if len(parts) == 3:
            parts.append(0)

        if level == "major":
            parts = [parts[0] + 1, 0, 0, 0]
        elif level == "minor":
            parts = [parts[0], parts[1] + 1, 0, 0]
        elif level == "patch":
            parts = [parts[0], parts[1], parts[2] + 1, 0]
        else:  # hotfix
            parts = [parts[0], parts[1], parts[2], parts[3] + 1]

        return ".".join(str(x) for x in parts) if parts[3] > 0 else ".".join(str(x) for x in parts[:3])

    def _update_version_preview(self):
        level = self._get_level()
        new_ver = self._calc_new_version(level)
        self._preview_label.setText(f"→ V{new_ver}")

    def _on_start(self):
        if self._running:
            return

        self._running = True
        self._start_btn.setEnabled(False)
        self._start_btn.setText("发版中...")
        self._log_edit.clear()
        self._progress.setValue(0)

        # 重置步骤状态
        for lbl in self._step_labels:
            name = lbl.text().lstrip(" ○●✓✗ ")
            lbl.setText(f"  ○  {name}")
            lbl.setStyleSheet(f"color: {T2}; font-size: 13px; padding: 2px 4px;")

        level = self._get_level()
        changelog = self._changelog_edit.toPlainText().strip()

        t = threading.Thread(
            target=_run_release,
            args=(level, changelog, self._bridge),
            daemon=True,
        )
        t.start()

    def _on_log(self, msg: str, color: str):
        cursor = self._log_edit.textCursor()
        cursor.movePosition(QTextCursor.End)

        if color == S:
            html_color = "#98C379"
        elif color == E:
            html_color = "#E06C75"
        elif color == W:
            html_color = "#E5C07B"
        else:
            html_color = "#ABB2BF"

        escaped = msg.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        escaped = escaped.replace("\n", "<br>")
        cursor.insertHtml(
            f'<span style="color:{html_color}; font-family: Consolas, monospace; font-size: 12px;">'
            f'{escaped}</span><br>'
        )
        self._log_edit.setTextCursor(cursor)
        self._log_edit.ensureCursorVisible()

    def _on_step(self, idx: int, status: str):
        if idx >= len(self._step_labels):
            return
        lbl = self._step_labels[idx]
        # 提取步骤名
        name = lbl.text()
        for prefix in ["  ○  ", "  ●  ", "  ✓  ", "  ✗  "]:
            if name.startswith(prefix):
                name = name[len(prefix):]
                break

        if status == "running":
            lbl.setText(f"  ●  {name}")
            lbl.setStyleSheet(
                f"color: {P}; font-size: 13px; font-weight: bold; padding: 2px 4px;"
            )
            # 进度条
            pct = int((idx / len(self._step_labels)) * 100)
            self._progress.setValue(pct)
        elif status == "done":
            lbl.setText(f"  ✓  {name}")
            lbl.setStyleSheet(
                f"color: {S}; font-size: 13px; font-weight: bold; padding: 2px 4px;"
            )
            pct = int(((idx + 1) / len(self._step_labels)) * 100)
            self._progress.setValue(pct)
        elif status == "error":
            lbl.setText(f"  ✗  {name}")
            lbl.setStyleSheet(
                f"color: {E}; font-size: 13px; font-weight: bold; padding: 2px 4px;"
            )

    def _on_progress(self, pct: int):
        if pct < 0:
            # indeterminate — just pulse
            self._progress.setValue(30)
        else:
            self._progress.setValue(min(pct, 100))

    def _on_finished(self, success: bool, msg: str):
        self._running = False
        self._start_btn.setEnabled(True)
        self._start_btn.setText("开始发版")

        if success:
            self._progress.setValue(100)
            InfoBar.success(
                title="发版成功",
                content=msg,
                parent=self._info_parent(), position=InfoBarPosition.TOP, duration=8000,
            )
            # 更新显示的版本号
            from version import APP_VERSION as new_ver
            self._ver_label.setText(f"当前版本: V{new_ver}")
        else:
            # 标记失败步骤
            for lbl in self._step_labels:
                if lbl.text().startswith("  ●"):
                    name = lbl.text()[5:]
                    lbl.setText(f"  ✗  {name}")
                    lbl.setStyleSheet(
                        f"color: {E}; font-size: 13px; font-weight: bold; padding: 2px 4px;"
                    )
            InfoBar.error(
                title="发版失败",
                content=msg[:200],
                parent=self._info_parent(), position=InfoBarPosition.TOP, duration=8000,
            )


# ============================================================
# 入口
# ============================================================
def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei", 10))
    w = ReleaseWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
