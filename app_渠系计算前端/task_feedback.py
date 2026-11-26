"""Visible, honest feedback for a cancellable background task."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar


class TaskFeedbackWidget(QWidget):
    """Keep elapsed time moving even when a calculation has no measurable total.

    Worker callbacks must arrive on the GUI thread. A stage percentage describes
    that stage/iteration only; successful publication is a separate terminal state.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.active = False
        self.generation = 0
        self._cancel_requested = False
        self._started = self._last_progress = None
        self._title = ""
        self.setObjectName("taskFeedback")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(3)
        row = QHBoxLayout()
        self.header_layout = row
        self.state_label = QLabel("尚未开始计算")
        self.state_label.setStyleSheet("font-weight:600;color:#17365D")
        self.elapsed_label = QLabel()
        self.elapsed_label.setStyleSheet("color:#52677F")
        row.addWidget(self.state_label, 1)
        row.addWidget(self.elapsed_label)
        layout.addLayout(row)
        self.message_label = QLabel("开始后会显示当前步骤和已用时间。")
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setFormat("等待开始")
        self.bar.setToolTip("百分比表示当前处理阶段或计算轮次；全流程结束后会单独提示完成。")
        layout.addWidget(self.bar)
        self.waiting_label = QLabel()
        self.waiting_label.setWordWrap(True)
        self.waiting_label.setStyleSheet("color:#8A5A16")
        self.waiting_label.hide()
        layout.addWidget(self.waiting_label)
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    @staticmethod
    def _duration(seconds):
        seconds = max(0, int(seconds))
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}小时{minutes:02d}分{seconds:02d}秒"
        if minutes:
            return f"{minutes}分{seconds:02d}秒"
        return f"{seconds}秒"

    def start(self, title, message=""):
        # Chained calculation -> delivery keeps the full one-click elapsed time.
        now = time.monotonic()
        if not self.active:
            self._started = now
        self.active = True
        self.generation += 1
        self._cancel_requested = False
        self._title = title
        self._last_progress = now
        self.state_label.setText(title + "进行中")
        self.message_label.setText(message or "正在准备，请稍候。")
        self.bar.setRange(0, 0)
        self.waiting_label.hide()
        self._tick()
        self._timer.start()
        return self.generation

    def update_progress(self, stage, fraction, message):
        if not self.active or self._cancel_requested:
            return
        self._last_progress = time.monotonic()
        self.message_label.setText(str(message))
        self.waiting_label.hide()
        # Unknown totals and stage-completion checkpoints stay animated until
        # the next stage or the explicit final callback; never leave a false 100%.
        value = float(fraction)
        if not math.isfinite(value) or value <= 0 or value >= 1:
            self.bar.setRange(0, 0)
        else:
            self.bar.setRange(0, 100)
            self.bar.setFormat("本轮计算 %p%" if stage in {"sections", "integration", "convergence"} else "当前步骤 %p%")
            self.bar.setValue(min(99, round(value * 100)))
        self._tick()

    def _tick(self):
        if self._started is None:
            return
        now = time.monotonic()
        self.elapsed_label.setText("已用 " + self._duration(now - self._started))
        if self.active and not self._cancel_requested and now - self._last_progress >= 15:
            self.bar.setRange(0, 0)
            self.waiting_label.setText("当前步骤已有 " + self._duration(now - self._last_progress)
                                       + "未返回新进度；复杂地形或密集断面可能耗时较长，可继续等待或取消。")
            self.waiting_label.show()

    def request_cancel(self):
        if not self.active:
            return
        self._cancel_requested = True
        self.state_label.setText("正在取消" + self._title)
        self.message_label.setText("已收到取消请求，正在等待当前步骤响应，请稍候。")
        self.bar.setRange(0, 0)
        self.waiting_label.hide()

    def _finish(self, title, message, *, success):
        self._tick()
        self.active = False
        self._timer.stop()
        self.state_label.setText(title)
        self.message_label.setText(str(message))
        self.bar.setRange(0, 100)
        self.bar.setValue(100 if success else 0)
        self.bar.setFormat("已完成" if success else title)
        self.waiting_label.hide()

    def succeed(self, message=""):
        self._finish(self._title + "完成", message or "处理完成，可以继续操作。", success=True)

    def fail(self, message):
        self._finish(self._title + "未完成", message, success=False)

    def cancelled(self, message=""):
        self._finish("已取消" + self._title, message or "本次任务已取消，可以修改输入后重新开始。", success=False)

    def stop(self):
        self.generation += 1
        if self.active:
            self._finish("任务已停止", "工程或输入已切换，旧任务的进度不再显示。", success=False)
        else:
            self._timer.stop()
