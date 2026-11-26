"""Filesystem paths for Windows I/O and ordinary paths for saved project data."""
import os
from pathlib import Path


def filesystem_path(path, *, extended=False):
    path = Path(path)
    if os.name != "nt":
        return path
    absolute = os.path.abspath(path)
    if absolute.startswith("\\\\?\\"):
        return path
    # Directory creation reserves space for a filename. Staging directories
    # also need the prefix for their as-yet unnamed children.
    if not extended and len(absolute) < 260 and len(os.path.dirname(absolute)) < 248:
        return path
    if absolute.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + absolute[2:])
    return Path("\\\\?\\" + absolute)


def resolved_path(path):
    resolved = filesystem_path(path, extended=True).resolve()
    value = str(resolved)
    if os.name == "nt" and value.startswith("\\\\?\\UNC\\"):
        return Path("\\\\" + value[8:])
    if os.name == "nt" and value.startswith("\\\\?\\"):
        return Path(value[4:])
    return resolved
