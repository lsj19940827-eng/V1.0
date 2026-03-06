# -*- coding: utf-8 -*-
"""倒虹吸自动确认（仅进程内有效）单元测试。"""

import os
from types import SimpleNamespace
from uuid import uuid4

from 推求水面线.managers.siphon_manager import SiphonManager, SiphonConfig
from 渠系断面设计.siphon.multi_siphon_dialog import MultiSiphonDialog


def _project_path():
    base = os.path.join(os.getcwd(), "data", "_test_runtime_confirm")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, f"demo_project_{uuid4().hex}")


def test_runtime_confirm_flag_is_process_scoped():
    project_path = _project_path()
    manager = SiphonManager(project_path)

    assert manager.is_runtime_confirmed("虹吸A") is False
    manager.mark_runtime_confirmed("虹吸A")
    assert manager.is_runtime_confirmed("虹吸A") is True

    # 同进程新实例仍可读取到确认态（用于“关闭窗口后再次打开自动确认”）
    manager2 = SiphonManager(project_path)
    assert manager2.is_runtime_confirmed("虹吸A") is True


def test_config_to_panel_dict_uses_runtime_confirm_only():
    project_path = _project_path()
    manager = SiphonManager(project_path)
    fake_dialog = SimpleNamespace(manager=manager)

    # 模拟历史文件中残留 calculated_at（重启后不应自动确认）
    config = SiphonConfig(
        name="虹吸B",
        Q=1.0,
        v_guess=2.0,
        roughness_n=0.014,
        calculated_at="2026-03-05 10:00:00",
        num_pipes=2,
    )

    data = MultiSiphonDialog._config_to_panel_dict(fake_dialog, config)
    assert "calculated_at" not in data
    assert data["num_pipes"] == 2

    # 标记为本次运行已确认后，应触发自动确认
    manager.mark_runtime_confirmed("虹吸B")
    data2 = MultiSiphonDialog._config_to_panel_dict(fake_dialog, config)
    assert data2.get("calculated_at")
