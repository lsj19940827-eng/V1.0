from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import build


def test_select_universal_patch_manifest_files_applies_floor():
    manifest_files = [
        "manifest-V1.0.4.json",
        "manifest-V1.0.8.3.json",
        "manifest-V1.0.9.json",
        "manifest-V1.0.9.1.json",
        "manifest-V1.1.0.json",
        "manifest-V1.1.0.1.json",
    ]

    selected = build._select_universal_patch_manifest_files(
        manifest_files,
        current_version="1.1.0.1",
    )

    assert selected == [
        "manifest-V1.0.9.json",
        "manifest-V1.0.9.1.json",
        "manifest-V1.1.0.json",
    ]


def test_select_universal_patch_manifest_files_excludes_current_and_future():
    manifest_files = [
        "manifest-V1.0.9.json",
        "manifest-V1.1.0.1.json",
        "manifest-V1.1.0.2.json",
    ]

    selected = build._select_universal_patch_manifest_files(
        manifest_files,
        current_version="1.1.0.1",
    )

    assert selected == ["manifest-V1.0.9.json"]
