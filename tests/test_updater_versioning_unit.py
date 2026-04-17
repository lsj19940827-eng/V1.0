from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import updater


def test_compare_versions_supports_hotfix_segment():
    assert updater.compare_versions("1.0.9.1", "1.0.9") == 1
    assert updater.compare_versions("1.0.9", "1.0.9.1") == -1
    assert updater.compare_versions("1.0.10", "1.0.9.9") == 1
    assert updater.compare_versions("1.0.9.1", "1.0.9.1") == 0


def test_is_newer_detects_hotfix_release():
    assert updater.is_newer("1.0.9.1", "1.0.9") is True
    assert updater.is_newer("1.0.9.1", "1.0.9.1") is False


def test_updateinfo_offers_patch_for_supported_old_version(monkeypatch):
    monkeypatch.setattr(updater, "APP_VERSION", "1.0.9")
    info = updater.UpdateInfo(
        {
            "latest_version": "1.0.9.1",
            "download_url": "https://example.com/full.zip",
            "patch_url": "https://example.com/patch.zip",
            "min_patch_version": "1.0.9",
        }
    )

    assert info.is_newer_than_local is True
    assert info.has_update is True
    assert info.can_use_patch is True


def test_updateinfo_falls_back_to_full_package_below_patch_floor(monkeypatch):
    monkeypatch.setattr(updater, "APP_VERSION", "1.0.3")
    info = updater.UpdateInfo(
        {
            "latest_version": "1.0.9.1",
            "download_url": "https://example.com/full.zip",
            "patch_url": "https://example.com/patch.zip",
            "min_patch_version": "1.0.9",
        }
    )

    assert info.is_newer_than_local is True
    assert info.has_update is True
    assert info.can_use_patch is False


def test_updateinfo_prefers_direct_urls_when_available():
    info = updater.UpdateInfo(
        {
            "latest_version": "1.0.9.1",
            "download_url": "https://proxy.example/full.zip",
            "download_url_direct": "https://github.com/example/full.zip",
            "patch_url": "https://proxy.example/patch.zip",
            "patch_url_direct": "https://github.com/example/patch.zip",
        }
    )

    assert info.download_url == "https://github.com/example/full.zip"
    assert info.patch_url == "https://github.com/example/patch.zip"


def test_updateinfo_reads_package_checksums():
    info = updater.UpdateInfo(
        {
            "latest_version": "1.0.9.1",
            "download_url": "https://example.com/full.zip",
            "patch_url": "https://example.com/patch.zip",
            "download_sha256": "full-sha256",
            "patch_sha256": "patch-sha256",
        }
    )

    assert info.download_sha256 == "full-sha256"
    assert info.patch_sha256 == "patch-sha256"


def test_updateinfo_supports_prod_downgrade_offer(monkeypatch):
    monkeypatch.setattr(updater, "APP_VERSION", "1.1.1")
    info = updater.UpdateInfo(
        {
            "latest_version": "1.1.0",
            "download_url": "https://example.com/full.zip",
        }
    )
    info.allow_downgrade = True

    assert info.is_older_than_local is True
    assert info.can_offer_downgrade is True
    assert info.has_update is True


def test_check_for_update_always_uses_prod_manifest(monkeypatch):
    calls = []

    def fake_check_remote(url, source_name):
        calls.append((url, source_name))
        return None

    monkeypatch.setattr(updater, "_check_remote", fake_check_remote)
    updater.check_for_update()

    assert calls == [(updater._GITHUB_VERSION_URL, "github:prod")]
