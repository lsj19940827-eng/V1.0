# -*- coding: utf-8 -*-
"""界面长任务的统一运行边界：后台工作只接收数据与取消令牌。"""

from __future__ import annotations

import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, QThread, Signal, Slot


class TaskCancelled(Exception):
    """任务在明确的检查点响应取消请求。"""


class CancellationToken:
    """与界面无关、可在线程间安全使用的取消令牌。"""

    def __init__(self, generation: int):
        self.generation = generation
        self._event = threading.Event()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self):
        self._event.set()

    def raise_if_cancelled(self):
        if self.is_cancelled:
            raise TaskCancelled("任务已取消")


# 线程不以页面为父对象，页面提前销毁时仍保留至线程真正结束。
_active_workers: set[QThread] = set()


class _Worker(QThread):
    def __init__(self, work: Callable, token: CancellationToken):
        super().__init__()
        self.work = work
        self.token = token
        self.value = None
        self.error = None

    def run(self):
        try:
            self.token.raise_if_cancelled()
            self.value = self.work(self.token)
            self.token.raise_if_cancelled()
        except Exception as exc:
            self.error = exc
        finally:
            # 释放可能捕获较大输入快照的工作函数。
            self.work = None


class TaskRunner(QObject):
    """串行管理一个任务，结果回调始终回到创建本对象的线程。"""

    running_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._generation = 0
        self._worker = None
        self._callbacks = (None, None, None)

    @property
    def generation(self) -> int:
        return self._generation

    def isRunning(self) -> bool:
        # 完成回调尚未应用时同样视为运行，防止切换工程后写回旧结果。
        return self._worker is not None

    def submit(self, work, *, on_success=None, on_error=None, on_cancelled=None) -> int:
        """提交 work(token)，工作或成功回调中的异常交由错误回调处理。"""
        if QThread.currentThread() != self.thread():
            raise RuntimeError("任务必须从所属界面线程提交")
        if self.isRunning():
            raise RuntimeError("上一任务尚未结束")
        self._generation += 1
        token = CancellationToken(self._generation)
        worker = _Worker(work, token)
        self._worker = worker
        self._callbacks = (on_success, on_error, on_cancelled)
        worker.finished.connect(self._on_thread_finished)
        # 即使所属页面被销毁，后台线程也只收到取消，不会被强制析构。
        self.destroyed.connect(token.cancel)
        _active_workers.add(worker)
        worker.finished.connect(lambda: _active_workers.discard(worker))
        worker.finished.connect(worker.deleteLater)
        self.running_changed.emit(True)
        worker.start()
        return self._generation

    def cancel(self):
        if self._worker is not None:
            self._worker.token.cancel()

    def invalidate(self):
        """使当前任务失效；迟到的结果不再触发业务回调。"""
        self._generation += 1
        self.cancel()

    def wait(self, timeout_ms=0) -> bool:
        """关闭阶段等待当前任务，普通交互应使用取消和完成信号。"""
        worker = self._worker
        if worker is None:
            return True
        finished = worker.wait(max(0, int(timeout_ms)))
        if finished and QThread.currentThread() == self.thread():
            self._on_thread_finished()
        return finished

    @Slot()
    def _on_thread_finished(self):
        worker = self._worker
        if worker is None or worker.isRunning():
            return
        self._worker = None
        success, error, cancelled = self._callbacks
        self._callbacks = (None, None, None)
        try:
            self.destroyed.disconnect(worker.token.cancel)
        except (RuntimeError, TypeError):
            pass
        try:
            if worker.token.generation != self._generation:
                return
            if worker.token.is_cancelled or isinstance(worker.error, TaskCancelled):
                if cancelled is not None:
                    cancelled()
            elif worker.error is not None:
                if error is not None:
                    error(worker.error)
            elif success is not None:
                try:
                    success(worker.value)
                except Exception as exc:
                    # 结果应用失败也交给业务错误入口，避免只出现在 Qt 标准错误中。
                    # 错误回调本身不在捕获范围内，防止重复处理或覆盖原始错误。
                    if error is None:
                        raise
                    error(exc)
        finally:
            # 成功回调可能接着提交下一任务，此时不能把新任务误标为空闲。
            if not self.isRunning():
                self.running_changed.emit(False)
