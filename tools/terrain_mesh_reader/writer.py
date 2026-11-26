"""Append exact float64 calculation meshes through the bundled Rhino3dm.NET API.

Python's Rhino3dm mesh Add binding can accept Point3f values even with double
storage enabled. This transport sends unchanged binary float64 XYZ to the .NET
double Add overload and strictly rereads every original/appended mesh.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import time
import uuid
import numpy as np
from .reader import HELPER, _sha256


def _write_mesh_binary(path, vertices, faces):
    points = np.asarray(vertices, dtype='<f8', order='C')
    triangles = np.asarray(faces)
    if (points.ndim != 2 or points.shape[1] != 3 or len(points) < 3
            or not np.isfinite(points).all()):
        raise ValueError('Mesh vertices must be a finite float64 N by 3 array')
    if (triangles.ndim != 2 or triangles.shape[1] != 3 or len(triangles) < 1
            or not np.issubdtype(triangles.dtype, np.integer)
            or (triangles < 0).any() or (triangles >= len(points)).any()
            or max(len(points), len(triangles)) >= 2**31):
        raise ValueError('Mesh faces must be valid integer triangle indices')
    with Path(path).open('wb') as stream:
        stream.write(b'QXTIN01\0')
        stream.write(struct.pack('<ii', len(points), len(triangles)))
        points.tofile(stream)
        np.asarray(triangles, dtype='<i4', order='C').tofile(stream)


def append_meshes(source_path, output_path, mesh_specs, *, document_strings=None, cancelled=None):
    """Return saved-file metadata after adding all mesh specs in one write.

    Specs contain ``vertices``, ``faces``, optional ``name``, ``layer``, RGBA
    ``color``, string-valued ``user_strings``, and ``require_closed`` (True).
    Required closed meshes must also be valid, consistently oriented index
    manifolds before saving and after exact saved-file readback.
    ``source_path=None`` creates a new metre document. Existing source objects,
    mesh topology, double XYZ, ids and document metadata are retained. Failure
    preserves both the original source and an existing target unchanged.
    """
    source = None if source_path is None else Path(source_path).resolve()
    target = Path(output_path).resolve()
    if source is not None:
        if not source.is_file():
            raise FileNotFoundError(source)
        if source == target or target.exists() and source.samefile(target):
            raise ValueError('Appended model must not overwrite its source or a hard link to it')
    if not HELPER.is_file():
        raise RuntimeError('Rhino mesh helper is not built; run tools/terrain_mesh_reader/build.py')
    specs = list(mesh_specs)
    if not specs:
        raise ValueError('At least one calculation mesh is required')
    target.parent.mkdir(parents=True, exist_ok=True)
    source_hash = None if source is None else _sha256(source)
    staging = target.with_name(target.stem + '-append-' + uuid.uuid4().hex + '.3dm')
    process = None
    try:
        with tempfile.TemporaryDirectory(prefix='qx-mesh-append-') as temporary:
            temporary = Path(temporary)
            job = {'schema_version': '1.0', 'source': None if source is None else str(source),
                   'output': str(staging), 'document_strings': {str(k): str(v) for k, v in (document_strings or {}).items()},
                   'meshes': []}
            for number, spec in enumerate(specs):
                if cancelled and cancelled():
                    raise RuntimeError('Mesh append cancelled')
                binary = temporary / f'mesh-{number:04d}.bin'
                _write_mesh_binary(binary, spec['vertices'], spec['faces'])
                color = tuple(spec.get('color', (150, 150, 150, 255)))
                if len(color) == 3:
                    color += (255,)
                if len(color) != 4 or any(int(v) != v or not 0 <= v <= 255 for v in color):
                    raise ValueError('Mesh color must contain integer R, G, B, A in 0..255')
                job['meshes'].append({'binary_path': str(binary), 'name': str(spec.get('name', 'Calculation mesh')),
                    'layer': str(spec.get('layer', spec.get('name', 'Calculation mesh'))),
                    'color': list(color), 'user_strings': {str(k): str(v) for k, v in spec.get('user_strings', {}).items()},
                    'require_closed': bool(spec.get('require_closed', True))})
            config = temporary / 'append-job.json'
            config.write_text(json.dumps(job, ensure_ascii=False, allow_nan=False), encoding='utf8')
            creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
            # The metadata response is small, but files rather than pipes also
            # avoid blocking a child while the caller is polling cancellation.
            with (temporary/'stdout.log').open('w+', encoding='utf8') as stdout, (temporary/'stderr.log').open('w+', encoding='utf8') as stderr:
                process = subprocess.Popen([str(HELPER), '--append-meshes', str(config)], stdout=stdout, stderr=stderr,
                                           creationflags=creationflags)
                while process.poll() is None:
                    if cancelled and cancelled():
                        process.terminate()
                        process.wait(timeout=10)
                        raise RuntimeError('Mesh append cancelled')
                    time.sleep(.05)
                stdout.seek(0); stderr.seek(0)
                output, error = stdout.read().strip(), stderr.read().strip()
                if process.returncode:
                    raise ValueError('Cannot append exact calculation meshes: ' + (error or output))
            metadata = json.loads(output)
            if not metadata.get('passed') or not staging.is_file() or metadata.get('sha256') != _sha256(staging):
                raise ValueError('Native appended-model saved byte identity failed')
            records = metadata.get('meshes', [])
            if len(records) != len(specs) or not metadata.get('required_closed_meshes_valid_closed_oriented_by_indices'):
                raise ValueError('Native appended-model topology verification record is missing')
            for spec, record in zip(specs, records):
                if spec.get('require_closed', True) and (not all(record.get(key) is True for key in
                        ('valid', 'closed', 'manifold_by_actual_vertex_indices', 'oriented'))
                        or record.get('has_boundary') is not False):
                    raise ValueError('Native appended-model closed index topology verification failed')
            if source is not None and _sha256(source) != source_hash:
                raise ValueError('Source 3dm changed during append')
            if cancelled and cancelled():
                raise RuntimeError('Mesh append cancelled')
            staging.replace(target)
            metadata.update(path=str(target), writer_sha256=_sha256(HELPER),
                            writer_py_sha256=_sha256(Path(__file__)), source_unchanged=True,
                            requires_rhino_installation=False, requires_rhino_license=False)
            return metadata
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        if staging.exists():
            staging.unlink()
