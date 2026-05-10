"""Gitee 镜像发版能力测试。"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import release


def test_get_gitee_token_requires_local_secret(monkeypatch):
    monkeypatch.delenv("GITEE_TOKEN", raising=False)
    monkeypatch.setattr(release, "_load_env", lambda: {})

    with pytest.raises(SystemExit):
        release._get_gitee_token()


def test_upload_gitee_assets_returns_mirror_urls(tmp_path, monkeypatch):
    full_zip = tmp_path / "CanalHydraulicCalc-V1.3.8.zip"
    patch_zip = tmp_path / "CanalHydraulicCalc-V1.3.8-patch.zip"
    full_zip.write_bytes(b"full")
    patch_zip.write_bytes(b"patch")
    calls: list[tuple[str, str, object, str]] = []

    def fake_api(method, url, token, data=None, raw_body=None, content_type="application/json"):
        calls.append((method, url, data, content_type))
        if url.endswith("/releases"):
            return {"id": 42, "html_url": "https://gitee.com/example/releases/v1.3.8"}
        if url.endswith("/attach_files"):
            filename = Path(data["file_path"]).name
            return {"browser_download_url": f"https://gitee.com/example/releases/download/{filename}"}
        raise AssertionError(url)

    monkeypatch.setattr(release, "_gitee_api", fake_api)

    urls = release.step_create_gitee_release_and_upload_assets(
        "v1.3.8",
        "V1.3.8",
        "更新说明",
        {
            "full_zip": str(full_zip),
            "patch_zip": str(patch_zip),
            "patch_size_mb": 1.0,
            "full_size_mb": 100.0,
        },
        "token",
    )

    assert urls == {
        "download_url_mirrors": [
            "https://gitee.com/example/releases/download/CanalHydraulicCalc-V1.3.8.zip"
        ],
        "patch_url_mirrors": [
            "https://gitee.com/example/releases/download/CanalHydraulicCalc-V1.3.8-patch.zip"
        ],
    }
    assert calls[0][0] == "POST"
    assert calls[0][2]["tag_name"] == "v1.3.8"
    assert calls[0][2]["target_commitish"] == "master"
    assert calls[1][3] == "multipart/form-data"


def test_build_version_data_includes_mirror_urls(tmp_path):
    full_zip = tmp_path / "CanalHydraulicCalc-V1.3.8.zip"
    patch_zip = tmp_path / "CanalHydraulicCalc-V1.3.8-patch.zip"
    full_zip.write_bytes(b"full")
    patch_zip.write_bytes(b"patch")

    version_data = release._build_version_data(
        "1.3.8",
        {
            "download_url": "https://github.com/example/full.zip",
            "download_url_mirrors": ["https://gitee.com/example/full.zip"],
            "patch_url": "https://github.com/example/patch.zip",
            "patch_url_mirrors": ["https://gitee.com/example/patch.zip"],
        },
        {
            "full_zip": str(full_zip),
            "full_size_mb": 100.0,
            "patch_zip": str(patch_zip),
            "patch_size_mb": 1.0,
            "patch_min_version": "1.3.0",
        },
        "更新说明",
    )

    assert version_data["download_url"] == "https://github.com/example/full.zip"
    assert version_data["download_url_mirrors"] == ["https://gitee.com/example/full.zip"]
    assert version_data["patch_url"] == "https://github.com/example/patch.zip"
    assert version_data["patch_url_mirrors"] == ["https://gitee.com/example/patch.zip"]
