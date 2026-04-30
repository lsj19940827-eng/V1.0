from __future__ import annotations

from pathlib import Path
import sys

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_渠系计算前端 import bootstrap
from tools import gen_app_icon


REQUIRED_WINDOWS_ICON_SIZES = {
    (16, 16),
    (20, 20),
    (24, 24),
    (32, 32),
    (40, 40),
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
    existing_paths = {root_icon, shared_icon}

    monkeypatch.setattr(Path, "exists", lambda self: self in existing_paths)
    monkeypatch.setattr(bootstrap, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(bootstrap, "APP_ICON_FILE", root_icon)
    monkeypatch.setattr(bootstrap, "SHARED_LOGO_ICON_FILE", shared_icon)

    assert bootstrap._resolve_app_icon_path() == str(root_icon)


def test_resolve_app_icon_path_does_not_use_legacy_water_profile_icon(monkeypatch):
    """启动层不能再回退到推求水面线旧图标。"""
    project_root = Path("D:/fake-project")
    root_icon = project_root / "icon.ico"
    shared_icon = project_root / "app_渠系计算前端" / "resources" / "logo.ico"
    legacy_icon = project_root / "推求水面线" / "resources" / "app_icon.ico"

    monkeypatch.setattr(Path, "exists", lambda self: self == legacy_icon)
    monkeypatch.setattr(bootstrap, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(bootstrap, "APP_ICON_FILE", root_icon)
    monkeypatch.setattr(bootstrap, "SHARED_LOGO_ICON_FILE", shared_icon)

    assert bootstrap._resolve_app_icon_path() == ""


def test_generate_app_icon_writes_shared_blue_logo_icons(tmp_path):
    """图标生成脚本应从新 logo 本体生成根目录和共享资源两份 ICO。"""
    source_logo = ROOT / "app_渠系计算前端" / "resources" / "logo.png"
    root_icon = tmp_path / "icon.ico"
    shared_icon = tmp_path / "app_渠系计算前端" / "resources" / "logo.ico"

    generated = gen_app_icon.generate_icons(
        source_logo=source_logo,
        output_paths=[root_icon, shared_icon],
    )

    assert generated == [root_icon, shared_icon]
    assert REQUIRED_WINDOWS_ICON_SIZES <= _read_ico_sizes(root_icon)
    assert REQUIRED_WINDOWS_ICON_SIZES <= _read_ico_sizes(shared_icon)

    preview = Image.open(root_icon).ico.getimage((256, 256)).convert("RGBA")
    assert preview.getpixel((128, 128))[3] > 0
    assert preview.getpixel((20, 20))[3] == 0

    expected = Image.open(source_logo).convert("RGBA").resize(
        (256, 256),
        Image.Resampling.LANCZOS,
    )
    for point in [(30, 30), (70, 70), (128, 20), (20, 128)]:
        assert preview.getpixel(point) == expected.getpixel(point)
