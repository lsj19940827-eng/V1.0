"""发布快照与版本清单加固测试。"""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import release
from tools import release_snapshot


def test_strip_patch_fields_removes_patch_related_entries():
    version_data = {
        "latest_version": "1.3.0",
        "download_url": "https://example.com/full.zip",
        "patch_url": "https://example.com/patch.zip",
        "patch_url_direct": "https://example.com/patch.zip",
        "patch_url_proxy": "https://proxy.example/patch.zip",
        "patch_size_mb": 72.74,
        "patch_base_version": "1.3.0",
        "min_patch_version": "1.3.0",
        "patch_sha256": "patch-sha256",
    }

    cleaned = release_snapshot.strip_patch_fields(version_data)

    assert cleaned["latest_version"] == "1.3.0"
    assert "patch_url" not in cleaned
    assert "patch_url_direct" not in cleaned
    assert "patch_url_proxy" not in cleaned
    assert "patch_size_mb" not in cleaned
    assert "patch_base_version" not in cleaned
    assert "min_patch_version" not in cleaned
    assert "patch_sha256" not in cleaned


def test_write_release_snapshot_copies_manifest_and_records_hashes(tmp_path):
    snapshot_root = tmp_path / "snapshots"
    full_zip = tmp_path / "CanalHydraulicCalc-V1.3.0.zip"
    patch_zip = tmp_path / "CanalHydraulicCalc-V1.3.0-patch.zip"
    manifest_file = tmp_path / "manifest-V1.3.0.json"
    full_zip.write_bytes(b"full-zip")
    patch_zip.write_bytes(b"patch-zip")
    manifest_file.write_text(json.dumps({"version": "1.3.0"}, ensure_ascii=False), encoding="utf-8")
    version_data = {
        "latest_version": "1.3.0",
        "download_url": "https://example.com/full.zip",
        "download_sha256": "full-sha256",
        "patch_url": "https://example.com/patch.zip",
        "patch_sha256": "patch-sha256",
    }

    snapshot_file = release_snapshot.write_release_snapshot(
        version="1.3.0",
        tag_name="v1.3.0",
        full_zip_path=str(full_zip),
        full_download_url="https://example.com/full.zip",
        version_data=version_data,
        manifest_path=str(manifest_file),
        patch_zip_path=str(patch_zip),
        patch_download_url="https://example.com/patch.zip",
        snapshot_root=str(snapshot_root),
    )

    payload = json.loads(Path(snapshot_file).read_text(encoding="utf-8"))
    copied_manifest = Path(snapshot_file).with_name("manifest.json")

    assert payload["version"] == "1.3.0"
    assert payload["tag_name"] == "v1.3.0"
    assert payload["full_zip"]["sha256"] == release_snapshot.sha256_file(str(full_zip))
    assert payload["patch_zip"]["sha256"] == release_snapshot.sha256_file(str(patch_zip))
    assert copied_manifest.exists()
    assert json.loads(copied_manifest.read_text(encoding="utf-8")) == {"version": "1.3.0"}


def test_build_version_data_includes_package_checksums(tmp_path):
    full_zip = tmp_path / "CanalHydraulicCalc-V1.3.0.zip"
    patch_zip = tmp_path / "CanalHydraulicCalc-V1.3.0-patch.zip"
    full_zip.write_bytes(b"full-zip")
    patch_zip.write_bytes(b"patch-zip")
    assets = {
        "full_zip": str(full_zip),
        "full_size_mb": 100.0,
        "patch_zip": str(patch_zip),
        "patch_size_mb": 12.74,
        "patch_min_version": "1.3.0",
    }
    urls = {
        "download_url": "https://example.com/full.zip",
        "patch_url": "https://example.com/patch.zip",
    }

    version_data = release._build_version_data("1.3.0", urls, assets, "补丁加固")

    assert version_data["download_sha256"] == release_snapshot.sha256_file(str(full_zip))
    assert version_data["patch_sha256"] == release_snapshot.sha256_file(str(patch_zip))
    assert version_data["patch_url"] == "https://example.com/patch.zip"


def test_build_version_data_omits_patch_when_close_to_full_package(tmp_path):
    full_zip = tmp_path / "CanalHydraulicCalc-V1.3.4.zip"
    patch_zip = tmp_path / "CanalHydraulicCalc-V1.3.4-patch.zip"
    full_zip.write_bytes(b"full-zip")
    patch_zip.write_bytes(b"patch-zip")
    assets = {
        "full_zip": str(full_zip),
        "full_size_mb": 100.0,
        "patch_zip": str(patch_zip),
        "patch_size_mb": 80.28,
        "patch_min_version": "1.3.0",
    }
    urls = {
        "download_url": "https://example.com/full.zip",
        "patch_url": "https://example.com/patch.zip",
    }

    version_data = release._build_version_data("1.3.4", urls, assets, "补丁过大")

    assert version_data["download_url"] == "https://example.com/full.zip"
    assert "patch_url" not in version_data
    assert "patch_sha256" not in version_data
