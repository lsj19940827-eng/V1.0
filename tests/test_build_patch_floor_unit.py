import json
from pathlib import Path
import sys
import zipfile
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import build
from tools import patch_builder


def test_select_universal_patch_manifest_files_applies_floor():
    manifest_files = [
        "manifest-V1.1.8.json",
        "manifest-V1.1.9.json",
        "manifest-V1.2.0.json",
        "manifest-V1.2.1.json",
        "manifest-V1.2.2.json",
        "manifest-V1.2.2.1.json",
    ]

    selected = build._select_universal_patch_manifest_files(
        manifest_files,
        current_version="1.2.2",
    )

    assert selected == [
        "manifest-V1.1.9.json",
        "manifest-V1.2.0.json",
        "manifest-V1.2.1.json",
    ]


def test_select_universal_patch_manifest_files_excludes_current_and_future():
    manifest_files = [
        "manifest-V1.1.8.json",
        "manifest-V1.1.9.json",
        "manifest-V1.2.2.json",
        "manifest-V1.2.3.json",
    ]

    selected = build._select_universal_patch_manifest_files(
        manifest_files,
        current_version="1.2.2",
    )

    assert selected == ["manifest-V1.1.9.json"]


def test_should_skip_universal_patch_when_deleted_files_too_many():
    should_skip, reason = build._should_skip_universal_patch(
        {
            "changed_count": 248,
            "deleted_count": 5358,
        }
    )

    assert should_skip is True
    assert "deleted_count=5358" in reason


def test_should_skip_universal_patch_when_total_coverage_too_large():
    should_skip, reason = build._should_skip_universal_patch(
        {
            "changed_count": 250,
            "deleted_count": 80,
        }
    )

    assert should_skip is True
    assert "changed+deleted=330" in reason


def test_should_keep_universal_patch_when_coverage_is_small():
    should_skip, reason = build._should_skip_universal_patch(
        {
            "changed_count": 22,
            "deleted_count": 0,
        }
    )

    assert should_skip is False
    assert reason == ""


def test_resolve_update_helper_icon_file_prefers_shared_shield_icon(monkeypatch):
    project_root = Path(tempfile.mkdtemp(prefix="build-update-helper-icon-"))
    shared_resources = project_root / "app_渠系计算前端" / "resources"
    shared_resources.mkdir(parents=True)
    shield_logo = shared_resources / "license_shield.ico"
    shield_logo.write_bytes(b"shield-logo")
    helper_logo = shared_resources / "update_helper.ico"
    helper_logo.write_bytes(b"legacy-helper-logo")
    app_icon = project_root / "icon.ico"
    app_icon.write_bytes(b"legacy-app-icon")

    monkeypatch.setattr(
        build,
        "SHARED_UPDATE_HELPER_ICON_FILE",
        str(shield_logo),
        raising=False,
    )
    monkeypatch.setattr(build, "UPDATE_HELPER_ICON_FILE", str(helper_logo))
    monkeypatch.setattr(build, "ICON_FILE", str(app_icon))

    assert build._resolve_update_helper_icon_file() == str(shield_logo)


def test_hidden_imports_include_pressure_pipe_result_helpers():
    hidden_imports = build.get_hidden_imports()

    assert "utils.pressure_pipe_result_helpers" in hidden_imports
    assert "推求水面线.utils.pressure_pipe_result_helpers" in hidden_imports


def test_verify_import_groups_include_pressure_pipe_result_helpers():
    verify_groups = build.get_verify_import_groups()

    assert (
        "utils.pressure_pipe_result_helpers"
        in verify_groups["推求水面线"]
    )
    assert (
        "推求水面线.utils.pressure_pipe_result_helpers"
        in verify_groups["推求水面线"]
    )


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
