# -*- coding: utf-8 -*-
"""倒虹吸自动确认（仅进程内有效）单元测试。"""

import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from 推求水面线.managers.siphon_manager import SiphonManager, SiphonConfig
from app_渠系计算前端.siphon.multi_siphon_dialog import MultiSiphonDialog


def _temp_test_dir(prefix: str) -> str:
    base = ROOT / ".pytest_tmp"
    base.mkdir(parents=True, exist_ok=True)
    return tempfile.mkdtemp(prefix=prefix, dir=str(base))


def test_runtime_confirm_flag_is_process_scoped():
    temp_dir = _temp_test_dir("siphon-runtime-confirm-")
    try:
        project_path = str(Path(temp_dir) / f"demo_project_{uuid4().hex}")
        manager = SiphonManager(project_path)

        assert manager.is_runtime_confirmed("虹吸A") is False
        manager.mark_runtime_confirmed("虹吸A")
        assert manager.is_runtime_confirmed("虹吸A") is True

        # 同进程新实例仍可读取到确认态（用于“关闭窗口后再次打开自动确认”）
        manager2 = SiphonManager(project_path)
        assert manager2.is_runtime_confirmed("虹吸A") is True
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_config_to_panel_dict_uses_runtime_confirm_only():
    temp_dir = _temp_test_dir("siphon-runtime-confirm-")
    try:
        project_path = str(Path(temp_dir) / f"demo_project_{uuid4().hex}")
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
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_update_siphon_result_persists_velocity_and_loads_compatibly():
    temp_dir = _temp_test_dir("siphon-runtime-confirm-")
    try:
        project_path = str(Path(temp_dir) / f"demo_project_{uuid4().hex}")
        manager = SiphonManager(project_path)

        manager.update_siphon_result("siphon-c", total_head_loss=1.25, diameter=0.9, velocity=1.23)
        manager.save_config()

        reloaded = SiphonManager(project_path)
        config = reloaded.get_siphon_config("siphon-c")
        assert config is not None
        assert config.total_head_loss == 1.25
        assert config.diameter == 0.9
        assert config.velocity == 1.23

        reloaded._config["siphons"]["legacy"] = {
            "total_head_loss": 0.88,
            "diameter": 0.7,
        }
        compat = reloaded.get_siphon_config("legacy")
        assert compat is not None
        assert compat.velocity is None
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
