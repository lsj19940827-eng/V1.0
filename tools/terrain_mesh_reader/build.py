"""Build the Windows x64 reader using the pinned official Rhino3dm package.

The downloadable SDK is unnecessary: Windows .NET Framework csc is sufficient.
The package and notices stay in this directory for offline reproducibility.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import urllib.request
import zipfile
import time
import uuid

DIRECTORY = Path(__file__).resolve().parent
VERSION = "8.35.0"
PACKAGE_SHA256 = "068a4099c28874da85456b814bdfc919ca5813ea14ba485af02c538abc288213"
URL = f"https://api.nuget.org/v3-flatcontainer/rhino3dm/{VERSION}/rhino3dm.{VERSION}.nupkg"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(download=False):
    package = DIRECTORY / "vendor" / f"rhino3dm.{VERSION}.nupkg"
    package.parent.mkdir(exist_ok=True)
    if not package.exists():
        if not download:
            raise FileNotFoundError("Pinned package missing; use --download to obtain official NuGet package")
        with urllib.request.urlopen(URL, timeout=60) as response, package.open("wb") as stream:
            shutil.copyfileobj(response, stream)
    if sha256(package) != PACKAGE_SHA256:
        raise RuntimeError("Pinned official Rhino3dm package bytes changed or download is incomplete")
    binary = DIRECTORY / "bin"
    binary.mkdir(exist_ok=True)
    with zipfile.ZipFile(package) as archive:
        managed = [name for name in archive.namelist()
                   if name.startswith("lib/net48/") and name.endswith("Rhino3dm.dll")]
        if not managed:
            managed = [name for name in archive.namelist()
                       if name.startswith("lib/net45/") and name.endswith("Rhino3dm.dll")]
        if len(managed) != 1:
            raise RuntimeError("Official NuGet managed .NET Framework assembly not found")
        files = managed + [name for name in archive.namelist()
                           if name.startswith("runtimes/win-x64/native/") and name.endswith(".dll")]
        if len(files) < 2:
            raise RuntimeError("Official NuGet Windows x64 native library not found")
        files += [name for name in archive.namelist() if "license" in name.lower()
                  and not name.endswith("/")]
        for name in files:
            target_file = binary / Path(name).name
            content = archive.read(name)
            if not target_file.is_file() or target_file.read_bytes() != content:
                target_file.write_bytes(content)
    shutil.copyfile(DIRECTORY / "LICENSE-Rhino3dm.txt", binary / "LICENSE-Rhino3dm.txt")
    compiler = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
    if not compiler.exists():
        raise RuntimeError("Windows .NET Framework C# compiler not installed")
    target = binary / "TerrainMeshReader.exe"
    staging = target.with_name(target.stem + "-" + uuid.uuid4().hex + ".exe")
    try:
        subprocess.run([str(compiler), "/nologo", "/optimize+", "/platform:x64", "/target:exe",
                        f"/out:{staging}", f"/reference:{binary / 'Rhino3dm.dll'}",
                        "/reference:System.Drawing.dll", "/reference:System.Web.Extensions.dll",
                        str(DIRECTORY / "Program.cs")], check=True)
        deadline = time.monotonic() + 60
        while True:
            try:
                staging.replace(target)
                break
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.05)
    finally:
        if staging.exists():
            staging.unlink()
    manifest = {"package": "Rhino3dm", "version": VERSION, "source_url": URL,
                "license": "MIT", "requires_rhino_installation": False,
                "source_sha256": sha256(DIRECTORY / "Program.cs"),
                "package_sha256": sha256(package),
                "files": {p.name: sha256(p) for p in binary.iterdir() if p.is_file()}}
    (DIRECTORY / "build-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    print(json.dumps(build(parser.parse_args().download), indent=2))
