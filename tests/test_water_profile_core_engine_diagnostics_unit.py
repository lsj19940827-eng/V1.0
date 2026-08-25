# -*- coding: utf-8 -*-
"""水面线核心计算引擎加载失败诊断回归测试。"""

from pathlib import Path

from app_渠系计算前端.water_profile.core_engine_diagnostics import (
    CORE_ENGINE_LOG_NAME,
    _safe_current_directory,
    _should_skip_default_log_write,
    build_core_engine_copyable_details,
    build_core_engine_user_message,
    record_core_engine_import_failure,
)


def test_record_import_failure_writes_utf8_log_and_exposes_missing_module(tmp_path):
    """缺失模块应同时进入 UTF-8 日志、界面摘要和可复制详情。"""
    error = ModuleNotFoundError(
        "No module named 'core.spillway_steep_chute_adapter'",
        name="core.spillway_steep_chute_adapter",
    )

    failure = record_core_engine_import_failure(
        error,
        log_dir=tmp_path,
        traceback_text="测试调用栈：适配器导入失败",
    )

    log_path = Path(failure.log_path)
    assert log_path == tmp_path / CORE_ENGINE_LOG_NAME
    assert log_path.exists()
    log_text = log_path.read_text(encoding="utf-8")
    assert "水面线核心计算引擎加载失败" in log_text
    assert "core.spillway_steep_chute_adapter" in log_text
    assert "测试调用栈：适配器导入失败" in log_text

    user_message = build_core_engine_user_message(
        failure,
        action_name="执行计算",
    )
    assert "无法执行计算" in user_message
    assert "缺少或无法加载模块：core.spillway_steep_chute_adapter" in user_message
    assert "完整安装包覆盖安装" in user_message
    assert str(log_path) in user_message

    details = build_core_engine_copyable_details(failure)
    assert "测试调用栈：适配器导入失败" in details
    assert str(log_path) in details


def test_record_import_failure_keeps_diagnostic_when_log_directory_is_unwritable(
    tmp_path,
    monkeypatch,
):
    """日志写入失败不能再次打断面板导入。"""
    error = ImportError("DLL load failed while importing hydraulic_calc")

    def _raise_permission_error(*_args, **_kwargs):
        raise PermissionError("测试目录不可写")

    monkeypatch.setattr(Path, "mkdir", _raise_permission_error)
    failure = record_core_engine_import_failure(error, log_dir=tmp_path)

    assert failure.log_path == ""
    assert "PermissionError" in failure.log_write_error
    assert "DLL load failed" in failure.diagnostic_text
    user_message = build_core_engine_user_message(failure)
    assert "诊断日志写入失败" in user_message
    assert "完整安装包覆盖安装" in user_message


def test_unknown_failure_still_provides_recovery_guidance():
    """历史状态没有保留异常对象时，也必须给出明确恢复办法。"""
    user_message = build_core_engine_user_message(None, action_name="插入渐变段")
    details = build_core_engine_copyable_details(None)

    assert "无法插入渐变段" in user_message
    assert "未取得具体导入异常" in user_message
    assert "完整安装包覆盖安装" in user_message
    assert "软件版本" in details


def test_current_directory_failure_does_not_break_diagnostics(monkeypatch):
    """当前目录失效时仍要返回可用诊断文字。"""
    monkeypatch.setattr(
        "app_渠系计算前端.water_profile.core_engine_diagnostics.os.getcwd",
        lambda: (_ for _ in ()).throw(FileNotFoundError("目录已删除")),
    )

    current_directory = _safe_current_directory()

    assert "无法读取当前目录" in current_directory
    assert "目录已删除" in current_directory


def test_pytest_process_skips_default_user_log_but_keeps_explicit_temp_log(tmp_path):
    """回归测试不能污染真实用户日志，显式临时目录仍允许写入。"""
    assert _should_skip_default_log_write(None) is True
    assert _should_skip_default_log_write(tmp_path) is False
