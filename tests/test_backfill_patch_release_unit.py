# -*- coding: utf-8 -*-
"""已发版本补挂补丁脚本单元测试。"""

import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import backfill_patch_release, patch_builder, release_snapshot


def _make_full_zip(zip_path: Path, version: str, files: dict[str, str]) -> Path:
    """构造一个带版本根目录的全量包。"""
    root_name = f"{backfill_patch_release.APP_NAME_EN}-V{version}"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel_path, content in files.items():
            zf.writestr(f"{root_name}/{rel_path}", content)
    return zip_path


def _write_snapshot(
    snapshot_root: Path,
    *,
    version: str,
    manifest_payload: dict,
    full_zip_path: Path,
) -> Path:
    """写入最小可用发布快照。"""
    version_dir = snapshot_root / f"v{version}"
    version_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = version_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    snapshot_path = version_dir / "snapshot.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "version": version,
                "tag_name": f"v{version}",
                "manifest": {
                    "path": str(manifest_path),
                },
                "full_zip": {
                    "path": str(full_zip_path),
                    "name": full_zip_path.name,
                    "download_url": f"https://example.com/{full_zip_path.name}",
                    "sha256": release_snapshot.sha256_file(str(full_zip_path)),
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return snapshot_path


def test_resolve_snapshot_inputs_only_uses_requested_base_version(tmp_path):
    """回补补丁时只应读取指定旧版本和目标版本的快照 manifest。"""
    snapshot_root = tmp_path / "snapshots"
    for version in ("1.2.8", "1.2.9", "1.3.0", "1.3.4"):
        full_zip = _make_full_zip(
            tmp_path / f"CanalHydraulicCalc-V{version}.zip",
            version,
            {"keep.txt": version},
        )
        _write_snapshot(
            snapshot_root,
            version=version,
            manifest_payload={"version": version, "files": {}},
            full_zip_path=full_zip,
        )

    inputs = backfill_patch_release._resolve_snapshot_inputs(
        snapshot_root=str(snapshot_root),
        target_version="1.3.4",
        base_version="1.3.0",
        download_dir=str(tmp_path / "download"),
    )

    assert Path(inputs["base_manifest_path"]).as_posix().endswith("v1.3.0/manifest.json")
    assert Path(inputs["target_manifest_path"]).as_posix().endswith("v1.3.4/manifest.json")
    assert Path(inputs["full_zip_path"]).name == "CanalHydraulicCalc-V1.3.4.zip"


def test_prepare_backfill_patch_artifacts_writes_release_compatible_patch_info(tmp_path):
    """本地回补补丁时应基于快照生成兼容正式发版链路的 patch-info.json。"""
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    snapshot_root = tmp_path / "snapshots"
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    (target_dir / "keep.txt").write_text("new-content", encoding="utf-8")
    (target_dir / "new.txt").write_text("brand-new", encoding="utf-8")

    new_manifest = patch_builder.generate_manifest(str(target_dir), version="1.3.4")
    _write_snapshot(
        snapshot_root,
        version="1.3.4",
        manifest_payload=new_manifest,
        full_zip_path=_make_full_zip(
            dist_dir / "CanalHydraulicCalc-V1.3.4.zip",
            "1.3.4",
            {
                "keep.txt": "new-content",
                "new.txt": "brand-new",
            },
        ),
    )
    _write_snapshot(
        snapshot_root,
        version="1.3.0",
        manifest_payload={
            "version": "1.3.0",
            "files": {
                "keep.txt": "old-hash-keep",
            },
        },
        full_zip_path=_make_full_zip(
            tmp_path / "CanalHydraulicCalc-V1.3.0.zip",
            "1.3.0",
            {"keep.txt": "old-content"},
        ),
    )

    artifacts = backfill_patch_release.prepare_backfill_patch_artifacts(
        target_version="1.3.4",
        base_version="1.3.0",
        dist_dir=str(dist_dir),
        snapshot_root=str(snapshot_root),
    )

    assert Path(artifacts["patch_zip"]).name == "CanalHydraulicCalc-V1.3.4-patch.zip"
    assert artifacts["patch_info"]["min_version"] == "1.3.0"
    assert artifacts["patch_info"]["patch_name"] == "CanalHydraulicCalc-V1.3.4-patch.zip"
    assert artifacts["patch_result"]["deleted_count"] == 0
    assert artifacts["target_snapshot"]["version"] == "1.3.4"

    patch_manifest = json.loads(
        zipfile.ZipFile(artifacts["patch_zip"], "r").read("patch_manifest.json").decode("utf-8")
    )
    assert patch_manifest["min_version"] == "1.3.0"
    assert patch_manifest["included_files"] == ["keep.txt", "new.txt"]
    assert patch_manifest["allowed_source_hashes"]["keep.txt"] == ["old-hash-keep"]
    assert patch_manifest["allowed_source_hashes"]["new.txt"] == [
        patch_builder.MISSING_FILE_SENTINEL
    ]


def test_build_backfilled_version_data_preserves_full_package_fields(tmp_path):
    """回补 Gist 时只补补丁字段，不改原有全量包字段。"""
    patch_zip = tmp_path / "CanalHydraulicCalc-V1.3.4-patch.zip"
    patch_zip.write_bytes(b"patch-data")
    existing = {
        "latest_version": "1.3.4",
        "download_url": "https://example.com/full.zip",
        "download_url_direct": "https://example.com/full.zip",
        "download_url_proxy": "https://proxy.example/full.zip",
        "changelog": "- 旧说明",
        "release_date": "2026-04-16",
        "min_version": "1.0.0",
        "file_size_mb": 351.1,
        "channel": "stable",
    }

    merged = backfill_patch_release.build_backfilled_version_data(
        existing,
        patch_url_direct="https://github.com/example/patch.zip",
        patch_zip_path=str(patch_zip),
        patch_size_mb=5.4,
        min_patch_version="1.3.0",
    )

    assert merged["download_url"] == existing["download_url"]
    assert merged["download_url_direct"] == existing["download_url_direct"]
    assert merged["download_url_proxy"] == existing["download_url_proxy"]
    assert merged["changelog"] == existing["changelog"]
    assert merged["patch_url"] == "https://github.com/example/patch.zip"
    assert merged["patch_url_direct"] == "https://github.com/example/patch.zip"
    assert merged["patch_url_proxy"] == backfill_patch_release.release._proxied_url(
        "https://github.com/example/patch.zip"
    )
    assert merged["patch_size_mb"] == 5.4
    assert merged["patch_sha256"] == release_snapshot.sha256_file(str(patch_zip))
    assert merged["min_patch_version"] == "1.3.0"
    assert merged["patch_base_version"] == "1.3.0"


def test_backfill_patch_release_updates_existing_release_and_gist(monkeypatch, tmp_path):
    """主流程应补挂 patch 资产，并只补齐 Gist 的 patch 字段。"""
    patch_zip = tmp_path / "CanalHydraulicCalc-V1.3.4-patch.zip"
    patch_zip.write_bytes(b"patch-data")
    captured = {
        "deleted_urls": [],
        "patched_gist": None,
        "uploaded": None,
    }
    existing_version_data = {
        "latest_version": "1.3.4",
        "download_url": "https://example.com/full.zip",
        "download_url_direct": "https://example.com/full.zip",
        "download_url_proxy": "https://proxy.example/full.zip",
        "changelog": "- 旧说明",
        "release_date": "2026-04-16",
        "min_version": "1.0.0",
        "file_size_mb": 351.1,
        "channel": "stable",
    }

    monkeypatch.setattr(
        backfill_patch_release,
        "prepare_backfill_patch_artifacts",
        lambda **_kwargs: {
            "patch_zip": str(patch_zip),
            "patch_info_path": str(tmp_path / "patch-info.json"),
            "patch_info": {
                "size_mb": 5.4,
                "min_version": "1.3.0",
                "patch_name": patch_zip.name,
            },
            "patch_result": {
                "changed_count": 7,
                "deleted_count": 0,
                "min_version": "1.3.0",
            },
        },
    )
    monkeypatch.setattr(backfill_patch_release.release, "_get_token", lambda: "token")

    def _fake_api(method, url, token, data=None, raw_body=None, content_type="application/json"):
        assert token == "token"
        if method == "GET" and url == "https://api.github.com/user":
            return {"login": "tester"}
        if method == "GET" and url.endswith("/releases/tags/v1.3.4"):
            return {
                "upload_url": "https://uploads.github.com/repos/example/releases/1/assets{?name,label}",
                "html_url": "https://github.com/example/release/v1.3.4",
                "assets": [
                    {
                        "name": "CanalHydraulicCalc-V1.3.4-patch.zip",
                        "id": 101,
                    }
                ],
            }
        if method == "DELETE" and url.endswith("/releases/assets/101"):
            captured["deleted_urls"].append(url)
            return {}
        if method == "GET" and url.endswith(f"/gists/{backfill_patch_release.GIST_ID}"):
            return {
                "files": {
                    "version.json": {
                        "content": json.dumps(existing_version_data, ensure_ascii=False)
                    }
                }
            }
        if method == "PATCH" and url.endswith(f"/gists/{backfill_patch_release.GIST_ID}"):
            captured["patched_gist"] = data
            return {}
        raise AssertionError(f"未预期的 API 调用：{method} {url}")

    monkeypatch.setattr(backfill_patch_release.release, "_github_api", _fake_api)
    monkeypatch.setattr(
        backfill_patch_release.release,
        "_upload_release_asset",
        lambda upload_url, file_path, token: captured.update(
            {
                "uploaded": (upload_url, file_path, token),
            }
        ) or "https://github.com/example/patch.zip",
    )

    result = backfill_patch_release.backfill_patch_release(
        target_version="1.3.4",
        base_version="1.3.0",
    )

    assert captured["deleted_urls"] == [
        "https://api.github.com/repos/lsj19940827-eng/V1.0/releases/assets/101"
    ]
    assert captured["uploaded"] == (
        "https://uploads.github.com/repos/example/releases/1/assets{?name,label}",
        str(patch_zip),
        "token",
    )
    patched_content = json.loads(
        captured["patched_gist"]["files"]["version.json"]["content"]
    )
    assert patched_content["download_url"] == existing_version_data["download_url"]
    assert patched_content["patch_url"] == "https://github.com/example/patch.zip"
    assert patched_content["patch_sha256"] == release_snapshot.sha256_file(str(patch_zip))
    assert patched_content["min_patch_version"] == "1.3.0"
    assert result["patch_url_direct"] == "https://github.com/example/patch.zip"


def test_backfill_patch_release_stops_before_upload_when_gist_version_mismatched(
    monkeypatch,
    tmp_path,
):
    """Gist 最新版本不匹配时，应在上传前直接停止。"""
    patch_zip = tmp_path / "CanalHydraulicCalc-V1.3.4-patch.zip"
    patch_zip.write_bytes(b"patch-data")
    calls = {
        "uploaded": False,
        "deleted": False,
    }

    monkeypatch.setattr(
        backfill_patch_release,
        "prepare_backfill_patch_artifacts",
        lambda **_kwargs: {
            "patch_zip": str(patch_zip),
            "patch_info_path": str(tmp_path / "patch-info.json"),
            "patch_info": {
                "size_mb": 5.4,
                "min_version": "1.3.0",
                "patch_name": patch_zip.name,
            },
            "patch_result": {
                "changed_count": 7,
                "deleted_count": 0,
                "min_version": "1.3.0",
            },
        },
    )
    monkeypatch.setattr(backfill_patch_release.release, "_get_token", lambda: "token")

    def _fake_api(method, url, token, data=None, raw_body=None, content_type="application/json"):
        assert token == "token"
        if method == "GET" and url == "https://api.github.com/user":
            return {"login": "tester"}
        if method == "GET" and url.endswith(f"/gists/{backfill_patch_release.GIST_ID}"):
            return {
                "files": {
                    "version.json": {
                        "content": json.dumps(
                            {
                                "latest_version": "1.3.5",
                                "download_url": "https://example.com/full.zip",
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            }
        if method == "GET" and url.endswith("/releases/tags/v1.3.4"):
            return {
                "upload_url": "https://uploads.github.com/repos/example/releases/1/assets{?name,label}",
                "html_url": "https://github.com/example/release/v1.3.0",
                "assets": [],
            }
        if method == "DELETE":
            calls["deleted"] = True
            return {}
        if method == "PATCH":
            raise AssertionError("不应回写 Gist")
        raise AssertionError(f"未预期的 API 调用：{method} {url}")

    monkeypatch.setattr(backfill_patch_release.release, "_github_api", _fake_api)
    monkeypatch.setattr(
        backfill_patch_release.release,
        "_upload_release_asset",
        lambda *args, **kwargs: calls.update({"uploaded": True}) or "unexpected",
    )

    with pytest.raises(RuntimeError) as exc_info:
        backfill_patch_release.backfill_patch_release(
            target_version="1.3.4",
            base_version="1.3.0",
        )

    assert "latest_version=1.3.5" in str(exc_info.value)
    assert calls["deleted"] is False
    assert calls["uploaded"] is False
