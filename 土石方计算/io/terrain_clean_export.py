"""Save automatic survey cleaning as a reusable GCD + contours drawing."""
from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import uuid

import ezdxf


def export_clean_terrain_sources(sources, source_path, output_dir=None, *, import_report=None, cancelled=None):
    """Stream accepted WCS sources without changing the original drawing."""
    from .terrain_preprocessor import PROVENANCE_APP
    from .independent_terrain import file_sha256

    source = Path(source_path).resolve()
    root = (Path(output_dir).resolve() if output_dir else
            source.parent / "地形自动净化" / source.stem)
    root.mkdir(parents=True, exist_ok=True)
    destination = root / ("terrain-" + uuid.uuid4().hex)
    destination.mkdir(mode=0o777)
    dxf_path = destination / (source.stem + "_GCD加等高线_净化.dxf")
    points_path = destination / "GCD高程点.csv"
    sources_path = destination / "地形来源.jsonl"
    report_path = destination / "地形净化报告.json"
    report = dict(import_report or {})
    point_count = sum(v["kind"] == "point" for v in sources)
    contour_count = sum(v["kind"] == "polyline" for v in sources)
    vertex_count = sum(len(v["points"]) for v in sources)
    digest = hashlib.sha256()
    try:
        # Build only the small DXF tables in memory. Stream dense contours with
        # Python's original float representation, including source identities.
        template = ezdxf.new("R2013")
        template.units = 6
        template.appids.new(PROVENANCE_APP)
        for layer, color in (("GCD", 1), ("SQX", 3), ("JQX", 2)):
            template.layers.new(layer, dxfattribs={"color": color, "lineweight": 0})
        buffer = io.StringIO()
        template.write(buffer)
        preamble, tail = buffer.getvalue().split("  0\nSECTION\n  2\nENTITIES\n", 1)
        tail = tail.removeprefix("  0\nENDSEC\n")
        seed = vertex_count + contour_count * 2 + point_count + 4096
        preamble = re.sub(r"(\$HANDSEED\n\s*5\n)[^\n]+", lambda m: m[1] + format(seed + 1, "X"), preamble)
        handle = 4096

        def next_handle():
            nonlocal handle
            handle += 1
            return format(handle, "X")

        def xyz_tags(position):
            return "".join(f"{code}\n{repr(float(value))}\n" for code, value in zip((10, 20, 30), position))

        with dxf_path.open("w", encoding="utf-8", newline="\n") as drawing, \
                points_path.open("w", encoding="utf-8-sig", newline="") as table, \
                sources_path.open("w", encoding="utf-8", newline="\n") as identities:
            drawing.write(preamble + "  0\nSECTION\n  2\nENTITIES\n")
            writer = csv.writer(table)
            writer.writerow(("X", "Y", "Z", "原图层", "原对象编号"))
            for index, item in enumerate(sources):
                if index % 128 == 0 and cancelled and cancelled():
                    raise InterruptedError("已取消地形净化成果保存")
                values = item["points"]
                origin = str(item.get("source_handle", index))
                original_layer = str(item.get("layer", item.get("source_layer", "")))
                layer = "GCD" if item["kind"] == "point" else ("JQX" if original_layer.upper() == "JQX" else "SQX")
                kind = "POINT" if layer == "GCD" else "POLYLINE"
                provenance = "GCD_INSERT" if layer == "GCD" else "CONTOUR_CENTERLINE"
                entity_handle = next_handle()
                drawing.write(f"0\n{kind}\n5\n{entity_handle}\n100\nAcDbEntity\n8\n{layer}\n370\n0\n")
                if kind == "POINT":
                    drawing.write("100\nAcDbPoint\n" + xyz_tags(values[0]))
                    writer.writerow((*values[0], original_layer, origin))
                else:
                    drawing.write("66\n1\n100\nAcDb3dPolyline\n70\n8\n10\n0.0\n20\n0.0\n30\n0.0\n")
                drawing.write(f"1001\n{PROVENANCE_APP}\n1000\n{provenance}\n1000\n{origin}\n1000\n{original_layer}\n")
                if kind == "POLYLINE":
                    for position in values:
                        drawing.write(f"0\nVERTEX\n5\n{next_handle()}\n330\n{entity_handle}\n100\nAcDbEntity\n8\n{layer}\n100\nAcDbVertex\n100\nAcDb3dPolylineVertex\n70\n32\n" + xyz_tags(position))
                    drawing.write(f"0\nSEQEND\n5\n{next_handle()}\n330\n{entity_handle}\n100\nAcDbEntity\n8\n{layer}\n")
                payload = json.dumps(item, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                identities.write(payload + "\n")
                digest.update(payload.encode("utf-8") + b"\n")
            drawing.write("0\nENDSEC\n" + tail)
        receipt = {"schema_version": "1.0", "output_dir": str(destination),
                   "source_path": str(source), "source_sha256": report.get("source_sha256"),
                   "dxf_path": str(dxf_path), "dxf_sha256": file_sha256(dxf_path, cancelled),
                   "points_path": str(points_path), "points_csv_path": str(points_path),
                   "points_sha256": file_sha256(points_path, cancelled),
                   "sources_path": str(sources_path), "sources_sha256": file_sha256(sources_path, cancelled),
                   "report_path": str(report_path), "point_count": point_count,
                   "contour_count": contour_count, "vertex_count": vertex_count,
                   "retained_xyz_sha256": digest.hexdigest(), "layers": ["GCD", "SQX", "JQX"],
                   "coordinates": "original_WCS_float64", "source_unchanged": True}
        report_path.write_text(json.dumps({**receipt, "processing": report}, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        receipt["report_sha256"] = file_sha256(report_path, cancelled)
        return receipt
    except BaseException:
        resolved_root = root.resolve()
        resolved_destination = destination.resolve()
        if resolved_destination != resolved_root and resolved_destination.is_relative_to(resolved_root):
            shutil.rmtree(resolved_destination)
        raise


def export_clean_terrain_snapshot(tin, output_dir=None, *, cancelled=None):
    """Export an approved portable survey snapshot without rebuilding its TIN."""
    from .independent_terrain import _cached_survey_sources, _resolve_duplicate_measurements, file_sha256

    report = dict(getattr(tin, "import_report", {}))
    original = dict(report.get("original_source") or {
        "path": report.get("path"), "source_sha256": report.get("source_sha256")})
    if not original.get("path") or not original.get("source_sha256"):
        raise ValueError("地形快照缺少原始测量资料的来源记录")
    source = Path(original["path"]).resolve()
    if source.is_file() and file_sha256(source, cancelled) != original["source_sha256"]:
        raise ValueError("原始地形图已改变，请重新导入后再导出净化图")
    sources, snapshot_checksum = _cached_survey_sources(tin, report)
    removed = {str(v.get("source_handle")) for v in report.get("quality_report", {}).get("removed_entities", [])}
    accepted = [v for v in sources if str(v.get("source_handle")) not in removed]
    # Earlier portable files preserve original survey points; reproduce their
    # approved duplicate rule rather than using arbitrary mesh vertices.
    duplicate_report = {}
    accepted = _resolve_duplicate_measurements(accepted, duplicate_report,
                                               report.get("duplicate_point_policy", "max"))
    receipt = export_clean_terrain_sources(accepted, source, output_dir,
        import_report={**report, "source_sha256": original["source_sha256"],
                       "clean_drawing_basis": "approved_original_survey_snapshot",
                       "snapshot_source_sha256": report.get("source_sha256"),
                       "snapshot_original_sources_sha256": snapshot_checksum,
                       "snapshot_duplicate_resolution": duplicate_report,
                       "tin_rebuilt": False}, cancelled=cancelled)
    tin.import_report["clean_terrain"] = receipt
    return receipt
