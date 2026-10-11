# -*- coding: utf-8 -*-
"""真实 Qt 线程边界、取消、失效与表1异步入口回归。"""
import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QTimer
from PySide6.QtWidgets import QApplication

from app_渠系计算前端.task_runner import TaskRunner


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def until(app, condition, seconds=8):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.002)
    assert condition(), "异步任务未按时结束"


def test_work_runs_off_ui_and_completion_runs_on_ui(app):
    runner = TaskRunner()
    started, release = threading.Event(), threading.Event()
    ui_thread = threading.get_ident()
    ticks, results = [], []

    def work(token):
        started.set()
        assert release.wait(5)
        token.raise_if_cancelled()
        return threading.get_ident()

    runner.submit(work, on_success=lambda result: results.append((result, threading.get_ident())))
    until(app, started.is_set)
    QTimer.singleShot(0, lambda: ticks.append(True))
    until(app, lambda: bool(ticks))
    assert runner.isRunning()
    release.set()
    until(app, lambda: not runner.isRunning())
    assert results[0][0] != ui_thread
    assert results[0][1] == ui_thread


@pytest.mark.parametrize("invalidate", [False, True])
def test_cancel_and_generation_prevent_late_success(app, invalidate):
    runner = TaskRunner()
    started, release = threading.Event(), threading.Event()
    callbacks = []

    def work(token):
        started.set()
        release.wait(5)
        return "旧结果"

    generation = runner.submit(work, on_success=lambda value: callbacks.append(value),
                               on_cancelled=lambda: callbacks.append("取消"))
    until(app, started.is_set)
    if invalidate:
        runner.invalidate()
        assert runner.generation > generation
    else:
        runner.cancel()
    release.set()
    until(app, lambda: not runner.isRunning())
    assert callbacks == ([] if invalidate else ["取消"])
    runner.submit(lambda token: "新结果", on_success=callbacks.append)
    until(app, lambda: not runner.isRunning())
    assert callbacks[-1] == "新结果"


def test_error_is_delivered_on_ui_and_runner_can_be_reused(app):
    runner = TaskRunner()
    errors = []
    failure = ValueError("测试错误")

    def fail(token):
        raise failure

    runner.submit(fail, on_error=lambda error: errors.append((error, threading.get_ident())))
    until(app, lambda: not runner.isRunning())
    assert errors[0][0] is failure
    assert errors[0][1] == threading.get_ident()


def test_result_application_failure_reaches_error_callback_and_allows_next_task(app):
    runner = TaskRunner()
    errors, states, results = [], [], []
    failure = ValueError("结果应用失败")
    ui_thread = threading.get_ident()
    runner.running_changed.connect(states.append)

    def apply_result(value):
        assert value == "待应用结果"
        raise failure

    def handle_error(error):
        errors.append((error, threading.get_ident()))
        runner.submit(lambda token: "后续结果", on_success=results.append)

    runner.submit(lambda token: "待应用结果", on_success=apply_result, on_error=handle_error)
    until(app, lambda: results == ["后续结果"] and not runner.isRunning())
    assert errors == [(failure, ui_thread)]
    assert states == [True, True, False]


def test_success_callback_can_submit_next_task_without_false_idle(app):
    runner = TaskRunner()
    states, results = [], []
    runner.running_changed.connect(states.append)

    def next_task(first):
        results.append(first)
        runner.submit(lambda token: 2, on_success=results.append)

    runner.submit(lambda token: 1, on_success=next_task)
    until(app, lambda: results == [1, 2] and not runner.isRunning())
    assert states == [True, True, False]


def test_destroying_owner_cancels_work_without_destroying_running_thread(app):
    owner = QObject()
    runner = TaskRunner(owner)
    started, stopped = threading.Event(), threading.Event()

    def work(token):
        started.set()
        deadline = time.monotonic() + 5
        while not token.is_cancelled and time.monotonic() < deadline:
            time.sleep(0.002)
        if token.is_cancelled:
            stopped.set()
        return None

    runner.submit(work)
    until(app, started.is_set)
    owner.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    until(app, stopped.is_set)
    from app_渠系计算前端.task_runner import _active_workers
    until(app, lambda: not _active_workers)


@pytest.fixture
def editor(app, monkeypatch):
    from app_渠系计算前端.batch import panel as module
    monkeypatch.setattr(module.BatchPanel, "_load_user_prefs", lambda self: None)
    monkeypatch.setattr(module, "SHARED_DATA_AVAILABLE", False)
    for name in ("warning", "error", "info", "success"):
        monkeypatch.setattr(module.InfoBar, name, lambda *args, **kwargs: None)
    value = module.BatchEditor()
    values = [""] * len(module.INPUT_HEADERS)
    for col, text in {module.COL_SEQ: "1", module.COL_SEGMENT: "1",
                      module.COL_BUILDING_NAME: "异步试验渠", module.COL_SECTION_TYPE: "明渠-梯形",
                      module.COL_Q: "2.5", module.COL_N: "0.014", module.COL_SLOPE: "2000",
                      module.COL_M: "1.5", module.COL_B: "2"}.items():
        values[col] = text
    value.input_table.setRowCount(1)
    for col, text in enumerate(values):
        value.input_table.setItem(0, col, module.QTableWidgetItem(text))
    value.detail_cb.setChecked(False)
    yield value, module
    value.cancel_calculation()
    until(app, lambda: not value.is_calculation_running())
    value.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("action", ["complete", "edit", "cancel"])
def test_batch_async_snapshot_and_atomic_application(app, editor, monkeypatch, action):
    value, module = editor
    started, release = threading.Event(), threading.Event()
    main_thread = threading.get_ident()
    threads, finished, discarded = [], [], []
    real = module.mingqu_calculate

    def delayed(**kwargs):
        threads.append(threading.get_ident())
        started.set()
        assert release.wait(5)
        return real(**kwargs)

    monkeypatch.setattr(module, "mingqu_calculate", delayed)
    value.batch_results = [{"previous": True}]
    value.calculation_finished.connect(finished.append)
    value.calculation_discarded.connect(lambda: discarded.append(True))
    if action == "complete":
        value._calculate_button.click()
        assert value.is_calculation_running()
    else:
        assert value.start_calculation()
    until(app, started.is_set)
    assert value.batch_results == [{"previous": True}]
    if action == "edit":
        value.input_table.item(0, module.COL_Q).setText("3.0")
    elif action == "cancel":
        value.cancel_calculation()
    release.set()
    until(app, lambda: not value.is_calculation_running())
    assert threads and threads[0] != main_thread
    if action == "complete":
        assert len(finished) == 1
        assert value.batch_results[0]["result"]["success"] is True
        assert value.result_table.rowCount() == 1
    else:
        assert not finished
        assert discarded == [True]
        assert value.batch_results == [{"previous": True}]
