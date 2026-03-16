import importlib.util
import sys
import time
import types
from pathlib import Path


def _load_compat_module():
    module_path = (
        Path(__file__).resolve().parents[1]
        / "app_渠系计算前端"
        / "qfluentwidgets_compat.py"
    )
    spec = importlib.util.spec_from_file_location(
        "test_qfluentwidgets_compat_module",
        module_path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_darkdetect_timeout_guard_falls_back_quickly(monkeypatch):
    compat = _load_compat_module()
    fake_darkdetect = types.ModuleType("darkdetect")

    def _slow_theme():
        time.sleep(0.2)
        return "Dark"

    def _slow_listener(callback):
        time.sleep(0.2)
        callback("Dark")

    fake_darkdetect.theme = _slow_theme
    fake_darkdetect.listener = _slow_listener
    monkeypatch.setitem(sys.modules, "darkdetect", fake_darkdetect)

    compat.ensure_qfluentwidgets_compat(
        timeout_seconds=0.01,
        fallback_theme="Light",
    )

    started = time.perf_counter()
    theme = fake_darkdetect.theme()
    theme_elapsed = time.perf_counter() - started

    started = time.perf_counter()
    listener_result = fake_darkdetect.listener(lambda *_: None)
    listener_elapsed = time.perf_counter() - started

    assert theme == "Light"
    assert theme_elapsed < 0.1
    assert listener_result is None
    assert listener_elapsed < 0.1
    assert getattr(fake_darkdetect, compat._PATCH_FLAG, False) is True


def test_darkdetect_stub_is_installed_when_module_is_missing(monkeypatch):
    compat = _load_compat_module()
    monkeypatch.delitem(sys.modules, "darkdetect", raising=False)

    compat.ensure_qfluentwidgets_compat(
        timeout_seconds=0.01,
        fallback_theme="Light",
    )

    stub_darkdetect = sys.modules["darkdetect"]

    assert stub_darkdetect.theme() == "Light"
    assert stub_darkdetect.listener(lambda *_: None) is None
    assert stub_darkdetect.isDark() is False
    assert stub_darkdetect.isLight() is True
    assert getattr(stub_darkdetect, compat._PATCH_FLAG, False) is True
