"""Read fixed Rhino terrain topology without Rhino, retaining Point3d precision."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import time

import numpy as np

from filesystem_paths import filesystem_path, resolved_path

DIRECTORY = Path(__file__).resolve().parent
HELPER = DIRECTORY / "bin" / "TerrainMeshReader.exe"


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def decode_mesh_binary(path):
    """Decode double XYZ/int32 faces and reject corrupt/truncated transport."""
    path = Path(path)
    with path.open("rb") as stream:
        if stream.read(8) != b"QXTIN01\0":
            raise ValueError("Unknown terrain mesh transport format")
        counts = stream.read(8)
        if len(counts) != 8:
            raise ValueError("Truncated terrain mesh header")
        vertices, triangles = struct.unpack("<ii", counts)
        if vertices < 3 or triangles < 1:
            raise ValueError("Empty or invalid terrain mesh counts")
        expected = 16 + vertices * 24 + triangles * 12
        if path.stat().st_size != expected:
            raise ValueError("Terrain mesh transport byte length disagrees with counts")
        points = np.fromfile(stream, dtype="<f8", count=vertices * 3).reshape(vertices, 3)
        faces = np.fromfile(stream, dtype="<i4", count=triangles * 3).reshape(triangles, 3)
    if not np.isfinite(points).all():
        raise ValueError("Terrain mesh contains nonfinite XYZ")
    if (faces < 0).any() or (faces >= vertices).any():
        raise ValueError("Terrain faces reference nonexistent vertices")
    return points, faces.astype(np.int64)


def read_mesh(path, mesh_index=None, cancelled=None):
    """Return `(float64 XYZ, int64 triangles, metadata)` from saved .3dm.

    The package is installed beside the helper. There is no use of RhinoCore,
    RhinoCommon, mesh rebuilding, vertex conversion to float32, or GUI startup.
    Cancellation stops only this child process and does not terminate Rhino.
    """
    path = resolved_path(path)
    source = filesystem_path(path)
    if mesh_index is not None and (int(mesh_index) != mesh_index or mesh_index < 0):
        raise ValueError("mesh_index must be a nonnegative integer")
    if not source.is_file():
        raise FileNotFoundError(path)
    if not HELPER.is_file():
        raise RuntimeError("Terrain Mesh reader is not built; run tools/terrain_mesh_reader/build.py")
    with tempfile.TemporaryDirectory(prefix="qx-tin-read-") as temporary:
        binary = Path(temporary) / "terrain.bin"
        # The native 3dm reader rejects the Windows extended-path prefix.
        command = [str(HELPER), str(HELPER.parent), str(path), str(binary)]
        if mesh_index is not None:
            command.append(str(int(mesh_index)))
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8", errors="replace",
                                   creationflags=creationflags)
        try:
            while process.poll() is None:
                if cancelled and cancelled():
                    process.terminate()
                    process.communicate(timeout=10)
                    raise RuntimeError("Terrain mesh reading cancelled")
                time.sleep(.05)
            stdout, stderr = process.communicate()
            stdout = (stdout or "").strip()
            stderr = (stderr or "").strip()
            if process.returncode:
                diagnostic = stderr or stdout or "helper returned no diagnostic output"
                raise ValueError(f"Cannot read saved terrain mesh (helper exit code {process.returncode}): {diagnostic}")
            if not stdout:
                raise ValueError("Terrain mesh helper returned no metadata (helper exit code 0)")
            points, triangles = decode_mesh_binary(binary)
            metadata = json.loads(stdout)
            metadata.update({"source_path": str(path), "source_sha256": _sha256(source),
                             "reader_sha256": _sha256(HELPER),
                             "coordinates": "float64 Point3dAt; original mesh topology",
                             "requires_rhino_installation": False,
                             "requires_rhino_license": False})
            return points, triangles, metadata
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
