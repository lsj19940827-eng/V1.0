import json
from pathlib import Path
import sys
import zipfile
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import build
from tools import patch_builder


def test_select_universal_patch_manifest_files_applies_floor():
    manifest_files = [
        "manifest-V1.2.9.json",
        "manifest-V1.3.0.json",
        "manifest-V1.3.1.json",
        "manifest-V1.3.2.json",
        "manifest-V1.3.3.json",
    ]

    selected = build._select_universal_patch_manifest_files(
        manifest_files,
        current_version="1.3.3",
    )

    assert selected == [
        "manifest-V1.3.0.json",
        "manifest-V1.3.1.json",
        "manifest-V1.3.2.json",
    ]


def test_select_universal_patch_manifest_files_excludes_current_and_future():
    manifest_files = [
        "manifest-V1.2.9.json",
        "manifest-V1.3.0.json",
        "manifest-V1.3.3.json",
        "manifest-V1.3.4.json",
    ]

    selected = build._select_universal_patch_manifest_files(
        manifest_files,
        current_version="1.3.3",
    )

    assert selected == ["manifest-V1.3.0.json"]


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


def test_should_keep_universal_patch_when_archive_over_64mb_but_smaller_than_full_package():
    should_skip, reason = build._should_skip_universal_patch(
        {
            "changed_count": 7,
            "deleted_count": 0,
            "size_mb": 80.28,
        },
        full_size_mb=360.0,
    )

    assert should_skip is False
    assert reason == ""


def test_should_skip_universal_patch_when_archive_is_close_to_full_package():
    should_skip, reason = build._should_skip_universal_patch(
        {
            "changed_count": 7,
            "deleted_count": 0,
            "size_mb": 280.0,
        },
        full_size_mb=360.0,
    )

    assert should_skip is True
    assert "完整包" in reason


def test_resolve_update_helper_icon_file_prefers_shared_shield_icon(monkeypatch):
    project_root = Path("D:/fake-build-icon")
    shared_resources = project_root / "app_渠系计算前端" / "resources"
    shield_logo = shared_resources / "license_shield.ico"
    helper_logo = shared_resources / "update_helper.ico"
    app_icon = project_root / "icon.ico"
    existing_paths = {str(shield_logo), str(helper_logo), str(app_icon)}

    monkeypatch.setattr(
        build,
        "SHARED_UPDATE_HELPER_ICON_FILE",
        str(shield_logo),
        raising=False,
    )
    monkeypatch.setattr(build, "UPDATE_HELPER_ICON_FILE", str(helper_logo))
    monkeypatch.setattr(build, "ICON_FILE", str(app_icon))
    monkeypatch.setattr(build.os.path, "exists", lambda path: path in existing_paths)

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


def test_hidden_imports_include_word_export_dependencies():
    hidden_imports = build.get_hidden_imports()

    assert "docx" in hidden_imports
    assert "latex2mathml" in hidden_imports
    assert "lxml" in hidden_imports


def test_verify_import_groups_include_word_export_dependencies():
    verify_groups = build.get_verify_import_groups()

    assert verify_groups["Word导出依赖"] == [
        "docx",
        "latex2mathml",
        "lxml",
    ]


def test_collect_data_packages_include_latex2mathml_runtime_data():
    collect_data_packages = build.get_collect_data_packages()

    assert "latex2mathml" in collect_data_packages


def test_find_missing_imports_reports_missing_modules_by_group():
    missing = build._find_missing_imports(
        {
            "Word导出依赖": ["docx", "latex2mathml", "lxml"],
            "第三方库": ["pandas"],
        },
        importer=lambda name: None if name in {"latex2mathml", "pandas"} else (_ for _ in ()).throw(ModuleNotFoundError(name)),
    )

    assert missing == {
        "Word导出依赖": ["docx", "lxml"],
    }


def test_ensure_required_imports_available_exits_with_install_hint(capsys):
    with pytest.raises(SystemExit) as exc_info:
        build.ensure_required_imports_available(
            import_groups={"Word导出依赖": ["docx", "latex2mathml", "lxml"]},
            importer=lambda name: None if name == "latex2mathml" else (_ for _ in ()).throw(ModuleNotFoundError(name)),
        )

    captured = capsys.readouterr()

    assert exc_info.value.code == 1
    assert "Word导出依赖" in captured.out
    assert "pip install python-docx latex2mathml lxml" in captured.out


def test_get_build_search_paths_cover_non_package_module_directories():
    search_paths = build._get_build_search_paths()

    assert str(Path(build.PROJECT_ROOT)) in search_paths
    assert str(Path(build.PROJECT_ROOT) / "calc_渠系计算算法内核") in search_paths
    assert str(Path(build.PROJECT_ROOT) / "倒虹吸水力计算系统") in search_paths
    assert str(Path(build.PROJECT_ROOT) / "推求水面线") in search_paths


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

    assert result["source_versions"] == ["1.0.9", "1.0.9.1"]
    assert patch_manifest["source_versions"] == ["1.0.9", "1.0.9.1"]
    assert patch_manifest["allowed_source_hashes"]["keep.txt"] == ["old-hash-a", "old-hash-b"]
    assert patch_manifest["allowed_source_hashes"]["new.txt"] == [
        patch_builder.MISSING_FILE_SENTINEL,
        "old-new-hash",
    ]
    assert patch_manifest["allowed_source_hashes"]["obsolete.txt"] == [
        patch_builder.MISSING_FILE_SENTINEL,
        "old-obsolete-hash",
    ]


def test_generate_manifest_excludes_runtime_autosave_artifacts(tmp_path):
    dist_dir = tmp_path / "dist"
    (dist_dir / "_internal" / "data" / "autosave").mkdir(parents=True)
    (dist_dir / "_internal" / "data" / "siphon_autosave.json").write_text("{}", encoding="utf-8")
    (dist_dir / "_internal" / "data" / "autosave" / "draft.qxproj").write_text("draft", encoding="utf-8")
    (dist_dir / "keep.txt").write_text("keep", encoding="utf-8")

    manifest = patch_builder.generate_manifest(str(dist_dir), version="1.1.0")

    assert "keep.txt" in manifest["files"]
    assert "_internal/data/siphon_autosave.json" not in manifest["files"]
    assert "_internal/data/autosave/draft.qxproj" not in manifest["files"]
