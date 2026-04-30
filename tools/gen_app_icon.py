# -*- coding: utf-8 -*-
"""从共享新 Logo 生成主程序和资源目录使用的多尺寸 ICO 图标。"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_LOGO_FILE = PROJECT_ROOT / "app_渠系计算前端" / "resources" / "logo.png"
OUTPUT_ICON_FILES = (
    PROJECT_ROOT / "icon.ico",
    PROJECT_ROOT / "app_渠系计算前端" / "resources" / "logo.ico",
)
ICON_SIZES = (
    (16, 16),
    (20, 20),
    (24, 24),
    (32, 32),
    (40, 40),
    (48, 48),
    (64, 64),
    (128, 128),
    (256, 256),
)


def _lanczos_filter() -> int:
    """返回当前 Pillow 版本可用的高质量缩放算法。"""
    resampling = getattr(Image, "Resampling", Image)
    return resampling.LANCZOS


def create_base_icon(source_logo: Path = SOURCE_LOGO_FILE) -> Image.Image:
    """直接读取蓝色新 Logo 本体作为基础图标。"""
    source_logo = Path(source_logo)
    if not source_logo.exists():
        raise FileNotFoundError(f"未找到新 Logo 源文件：{source_logo}")
    return Image.open(source_logo).convert("RGBA")


def save_multisize_icon(base_icon: Image.Image, output_path: Path) -> Path:
    """把基础图标保存成 Windows 常用多尺寸 ICO。"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    resized_images = [
        base_icon.resize(size, _lanczos_filter())
        for size in ICON_SIZES
    ]
    resized_images[-1].save(
        output_path,
        format="ICO",
        sizes=ICON_SIZES,
        append_images=resized_images[:-1],
    )
    return output_path


def generate_icons(
    *,
    source_logo: Path = SOURCE_LOGO_FILE,
    output_paths: Iterable[Path] = OUTPUT_ICON_FILES,
) -> list[Path]:
    """从共享新 Logo 生成所有需要保持一致的 ICO 文件。"""
    base_icon = create_base_icon(Path(source_logo))
    generated: list[Path] = []
    for output_path in output_paths:
        generated.append(save_multisize_icon(base_icon, Path(output_path)))
    return generated


def main() -> None:
    """命令行入口：重新生成主程序图标和共享资源图标。"""
    for icon_path in generate_icons():
        print(f"图标已生成: {icon_path}")


if __name__ == "__main__":
    main()
