from __future__ import annotations

from pathlib import Path
import sys

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_渠系计算前端 import bootstrap


REQUIRED_WINDOWS_ICON_SIZES = {
    (16, 16),
    (24, 24),
    (32, 32),
    (48, 48),
    (64, 64),
    (128, 128),
    (256, 256),
}


def _read_ico_sizes(path: Path) -> set[tuple[int, int]]:
    """读取 ICO 文件内包含的全部尺寸。"""
    icon = Image.open(path)
    return set(icon.ico.sizes())


def test_packaged_app_icons_include_taskbar_sizes():
    """主程序图标需要包含 Windows 任务栏常用尺寸。"""
    for icon_path in [
        ROOT / "icon.ico",
        ROOT / "app_渠系计算前端" / "resources" / "logo.ico",
    ]:
        assert REQUIRED_WINDOWS_ICON_SIZES <= _read_ico_sizes(icon_path)


def test_resolve_app_icon_path_prefers_multisize_root_icon(monkeypatch):
    """启动层优先使用根目录的主程序多尺寸图标。"""
    project_root = Path("D:/fake-project")
    root_icon = project_root / "icon.ico"
    shared_icon = project_root / "app_渠系计算前端" / "resources" / "logo.ico"
    legacy_icon = project_root / "推求水面线" / "resources" / "app_icon.ico"
    existing_paths = {root_icon, shared_icon, legacy_icon}

    monkeypatch.setattr(Path, "exists", lambda self: self in existing_paths)
    monkeypatch.setattr(bootstrap, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(bootstrap, "APP_ICON_FILE", root_icon)
    monkeypatch.setattr(bootstrap, "SHARED_LOGO_ICON_FILE", shared_icon)
    monkeypatch.setattr(bootstrap, "WATER_PROFILE_ICON_FILE", legacy_icon)

    assert bootstrap._resolve_app_icon_path() == str(root_icon)
