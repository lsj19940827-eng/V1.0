# -*- coding: utf-8 -*-
"""授权校验模块的回归单元测试。"""

import importlib
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _reload_license_checker():
    """重新加载授权模块，避免进程内缓存串到其他测试。"""
    if "license_checker" in sys.modules:
        return importlib.reload(sys.modules["license_checker"])
    return importlib.import_module("license_checker")


def test_get_machine_guid_uses_hidden_subprocess_flags_on_windows(monkeypatch):
    """Windows 下读取 MachineGuid 时应静默拉起系统命令。"""
    license_checker = _reload_license_checker()
    call = {}

    def fake_check_output(cmd, **kwargs):
        call["cmd"] = cmd
        call["kwargs"] = kwargs
        return "MachineGuid    REG_SZ    abc-123".encode("gbk")

    monkeypatch.setattr(license_checker.os, "name", "nt", raising=False)
    monkeypatch.setattr(
        license_checker.subprocess,
        "CREATE_NO_WINDOW",
        0x08000000,
        raising=False,
    )
    monkeypatch.setattr(license_checker.subprocess, "check_output", fake_check_output)

    machine_guid = license_checker._get_machine_guid()

    assert machine_guid == "ABC-123"
    assert call["cmd"] == [
        "reg",
        "query",
        r"HKLM\SOFTWARE\Microsoft\Cryptography",
        "/v",
        "MachineGuid",
    ]
    assert call["kwargs"]["creationflags"] == 0x08000000
    assert call["kwargs"]["stderr"] is license_checker.subprocess.DEVNULL
    assert call["kwargs"]["timeout"] == 5


def test_machine_id_candidates_cache_reuses_hardware_lookup_within_process(monkeypatch):
    """同一进程内重复取机器码时不应再次触发底层硬件采集。"""
    license_checker = _reload_license_checker()
    calls = {"primary": 0, "legacy": 0}

    def fake_primary():
        calls["primary"] += 1
        return "primary-id"

    def fake_legacy():
        calls["legacy"] += 1
        return "legacy-id"

    monkeypatch.setattr(license_checker, "_get_machine_id_primary", fake_primary)
    monkeypatch.setattr(license_checker, "_get_machine_id_legacy", fake_legacy)

    candidates = license_checker.get_machine_id_candidates()
    machine_id = license_checker.get_machine_id()

    assert candidates == ["primary-id", "legacy-id"]
    assert machine_id == "primary-id"
    assert calls == {"primary": 1, "legacy": 1}
