import json
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import build
from tools import patch_builder


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


def test_build_universal_patch_includes_allowed_source_hashes(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "keep.txt").write_text("new-keep", encoding="utf-8")
    (dist_dir / "new.txt").write_text("brand-new", encoding="utf-8")

    new_manifest = patch_builder.generate_manifest(str(dist_dir), version="1.1.0")
    output_path = tmp_path / "patch.zip"
    old_manifests = [
        (
            "1.0.9",
            {
                "version": "1.0.9",
                "files": {
                    "keep.txt": "old-hash-a",
                    "obsolete.txt": "old-obsolete-hash",
                },
            },
        ),
        (
            "1.0.9.1",
            {
                "version": "1.0.9.1",
                "files": {
                    "keep.txt": "old-hash-b",
                    "new.txt": "old-new-hash",
                },
            },
        ),
    ]

    result = patch_builder.build_universal_patch(
        str(dist_dir),
        old_manifests,
        new_manifest,
        str(output_path),
    )

    assert result is not None
    with zipfile.ZipFile(output_path, "r") as zf:
        patch_manifest = json.loads(zf.read("patch_manifest.json").decode("utf-8"))

    assert patch_manifest["allowed_source_hashes"]["keep.txt"] == ["old-hash-a", "old-hash-b"]
    assert patch_manifest["allowed_source_hashes"]["new.txt"] == [
        patch_builder.MISSING_FILE_SENTINEL,
        "old-new-hash",
    ]
    assert patch_manifest["allowed_source_hashes"]["obsolete.txt"] == [
        patch_builder.MISSING_FILE_SENTINEL,
        "old-obsolete-hash",
    ]
