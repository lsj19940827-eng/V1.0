from __future__ import annotations

import hashlib
import json
import zipfile

import pytest

from tools import repair_runtime_patch, release_snapshot


def _make_snapshot(tmp_path, *, corrupted_program=False):
    program = b"official-program"
    program_hash = hashlib.sha256(program).hexdigest()
    case_path = "_internal/data/siphon_cases/工况1.siphon.json"
    files = {"program.exe": program_hash, case_path: "official-case-hash"}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"files": files}), encoding="utf-8")
    full_path = tmp_path / "full.zip"
    full_path.write_bytes(b"official-full-archive")
    patch_path = tmp_path / "official-patch.zip"
    meta = {
        "type": "universal_patch", "version": "1.4.6", "min_version": "1.3.0",
        "source_versions": ["1.3.0", "1.4.5"],
        "included_files": ["program.exe", case_path],
        "deleted": ["_internal/data/siphon_autosave.json"],
        "target_files": files,
        "allowed_source_hashes": {"program.exe": ["old-program-hash"], case_path: ["old-case-hash"]},
    }
    with zipfile.ZipFile(patch_path, "w") as archive:
        archive.writestr("patch_manifest.json", json.dumps(meta))
        archive.writestr("program.exe", b"corrupted" if corrupted_program else program)
        archive.writestr(case_path, b"bundled-case")
    snapshot = {
        "manifest": {"path": str(manifest_path)},
        "patch_zip": {"path": str(patch_path), "sha256": release_snapshot.sha256_file(str(patch_path))},
        "full_zip": {"path": str(full_path), "sha256": release_snapshot.sha256_file(str(full_path))},
    }
    return snapshot, program, meta


def test_snapshot_repair_preserves_program_hashes_and_source_coverage(tmp_path, monkeypatch):
    snapshot, program, original_meta = _make_snapshot(tmp_path)
    monkeypatch.setattr(release_snapshot, "load_release_snapshot", lambda *_args: snapshot)

    result = repair_runtime_patch.prepare_snapshot_runtime_patch_repair("1.4.6", str(tmp_path / "repaired"))

    with zipfile.ZipFile(result["patch_zip"]) as archive:
        meta = json.loads(archive.read("patch_manifest.json"))
        assert archive.namelist() == ["patch_manifest.json", "program.exe"]
        assert archive.read("program.exe") == program
    assert meta["source_versions"] == original_meta["source_versions"]
    assert meta["min_version"] == "1.3.0"
    assert meta["allowed_source_hashes"] == {"program.exe": ["old-program-hash"]}
    assert meta["deleted"] == []
    assert result["published"] is False
    assert release_snapshot.sha256_file(snapshot["patch_zip"]["path"]) == snapshot["patch_zip"]["sha256"]


def test_snapshot_repair_rejects_program_payload_mismatch(tmp_path, monkeypatch):
    snapshot, _program, _meta = _make_snapshot(tmp_path, corrupted_program=True)
    monkeypatch.setattr(release_snapshot, "load_release_snapshot", lambda *_args: snapshot)
    output_dir = tmp_path / "repaired"

    with pytest.raises(ValueError, match="目标哈希不一致"):
        repair_runtime_patch.prepare_snapshot_runtime_patch_repair("1.4.6", str(output_dir))

    assert list(output_dir.iterdir()) == []
