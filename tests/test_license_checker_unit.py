# -*- coding: utf-8 -*-
"""授权校验模块的回归单元测试。"""

import importlib
from pathlib import Path
import sys
import uuid


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
    calls = {"guid": 0, "uuid": 0, "disk": 0, "macs": 0}

    def fake_guid():
        calls["guid"] += 1
        return "CLONED-GUID"

    def fake_uuid():
        calls["uuid"] += 1
        return "HARDWARE-UUID"

    def fake_disk():
        calls["disk"] += 1
        return "DISK-SERIAL"

    def fake_macs():
        calls["macs"] += 1
        return ["AA:BB:CC:DD:EE:FF"]

    monkeypatch.setattr(license_checker, "_get_machine_guid", fake_guid)
    monkeypatch.setattr(license_checker, "_get_hardware_uuid", fake_uuid)
    monkeypatch.setattr(license_checker, "_get_disk_serial", fake_disk)
    monkeypatch.setattr(license_checker, "_get_physical_macs", fake_macs)
    monkeypatch.setattr(license_checker.platform, "node", lambda: "HOST-A")

    candidates = license_checker.get_machine_id_candidates()
    machine_id = license_checker.get_machine_id()

    assert candidates == [
        license_checker._get_machine_id_v2(
            "CLONED-GUID",
            "HARDWARE-UUID",
            "DISK-SERIAL",
        ),
        license_checker._get_machine_id_guid_legacy("CLONED-GUID"),
        license_checker._get_machine_id_legacy_from_parts(
            ["AA:BB:CC:DD:EE:FF"],
            "DISK-SERIAL",
            "HOST-A",
        ),
    ]
    assert machine_id == candidates[0]
    assert calls == {"guid": 1, "uuid": 1, "disk": 1, "macs": 1}


def test_machine_id_v2_distinguishes_cloned_windows_on_different_hardware():
    """相同 MachineGuid 的两台实体电脑必须得到不同主机器码。"""
    license_checker = _reload_license_checker()

    machine_a = license_checker._get_machine_id_v2(
        "SAME-WINDOWS-GUID",
        "HARDWARE-UUID-A",
        "DISK-A",
    )
    machine_b = license_checker._get_machine_id_v2(
        "SAME-WINDOWS-GUID",
        "HARDWARE-UUID-B",
        "DISK-B",
    )

    assert machine_a != machine_b


def test_extract_smbios_uuid_reads_type_1_structure():
    """固件表解析应按 SMBIOS 字节序读取 Type 1 系统 UUID。"""
    license_checker = _reload_license_checker()
    expected = uuid.UUID("00112233-4455-6677-8899-aabbccddeeff")
    type_zero = bytes([0, 4, 0, 0]) + b"\x00\x00"
    type_one = (
        bytes([1, 24, 1, 0])
        + bytes(4)
        + expected.bytes_le
        + b"\x00\x00"
    )

    actual = license_checker._extract_smbios_uuid(type_zero + type_one)

    assert actual == str(expected).upper()


def test_machine_id_v2_falls_back_to_guid_legacy_without_hardware_fields():
    """实体硬件字段不可用时应保持 V1.3.10 机器码不变。"""
    license_checker = _reload_license_checker()

    assert license_checker._get_machine_id_v2("GUID-A", "", "") == (
        license_checker._get_machine_id_guid_legacy("GUID-A")
    )


def test_machine_id_candidates_keep_guid_and_legacy_licenses_compatible(monkeypatch):
    """新版候选仍应接受 MachineGuid 单字段码和更早期硬件码。"""
    license_checker = _reload_license_checker()
    monkeypatch.setattr(license_checker, "_get_machine_guid", lambda: "GUID-A")
    monkeypatch.setattr(license_checker, "_get_hardware_uuid", lambda: "UUID-A")
    monkeypatch.setattr(license_checker, "_get_disk_serial", lambda: "DISK-A")
    monkeypatch.setattr(
        license_checker,
        "_get_physical_macs",
        lambda: ["00:11:22:33:44:55"],
    )
    monkeypatch.setattr(license_checker.platform, "node", lambda: "HOST-A")

    candidates = license_checker.get_machine_id_candidates()

    assert license_checker._get_machine_id_guid_legacy("GUID-A") in candidates
    assert license_checker._get_machine_id_legacy_from_parts(
        ["00:11:22:33:44:55"],
        "DISK-A",
        "HOST-A",
    ) in candidates


def test_activation_accepts_any_current_machine_id_candidate():
    """激活窗口应允许新主机器码和历史兼容机器码。"""
    license_checker = _reload_license_checker()

    assert license_checker._is_machine_id_accepted(
        "legacy-id",
        ["primary-id", "guid-id", "legacy-id"],
    )
    assert not license_checker._is_machine_id_accepted(
        "other-machine-id",
        ["primary-id", "guid-id", "legacy-id"],
    )
