"""Temporary output directories with the destination folder's normal access."""
from contextlib import contextmanager
import shutil
import uuid
from filesystem_paths import filesystem_path, resolved_path


@contextmanager
def output_staging(parent, prefix=".section-export-"):
    parent=resolved_path(parent)
    working=filesystem_path(parent/(prefix+uuid.uuid4().hex), extended=True)
    # Windows treats mkdir(0700) specially; published outputs should inherit.
    working.mkdir(mode=0o777)
    try:
        yield working
    finally:
        resolved=resolved_path(working)
        if resolved!=parent and resolved.is_relative_to(parent) and working.exists():
            shutil.rmtree(working)
