"""Read-only engineering drawing evidence, separate from quantity inputs."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys


CATALOG_SCHEMA = "engineering_drawing_catalog_1.0"
CATALOG_STATUS = "reference_library_only"
NOTICE = "资料已入库；本入口只查依据，尚未绑定区段或改变现有计算参数。"
_RESOURCE = Path("土石方计算/resources/engineering_drawings/catalog.json")
# The bundled "pipe" source is the retired 塘泥湾 drawing, including layouts 1—1 to 5—5.
ARCHIVED_DRAWING_IDS = frozenset({"pipe"})


class DrawingLibraryError(ValueError):
    """An unavailable source library must not prevent ordinary calculation."""


def catalog_path():
    """Resolve source checkout, one-folder and extracted frozen resources."""
    source_root = Path(__file__).resolve().parents[2]
    bases = []
    if getattr(sys, "_MEIPASS", None):
        bases.append(Path(sys._MEIPASS))
    bases.extend((Path(sys.executable).resolve().parent, source_root))
    candidates = [base / _RESOURCE for base in bases]
    return next((path for path in candidates if path.is_file()), source_root / _RESOURCE)


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DrawingLibraryError(f"无法读取工程断面资料：{Path(path).name}；{error}") from error


def load_catalog(path=None, *, include_archived=False):
    data = _read_json(path or catalog_path())
    if not isinstance(data, dict) or data.get("schema") != CATALOG_SCHEMA:
        raise DrawingLibraryError("工程断面资料库格式不受支持，请核对随程序提供的资料文件。")
    if data.get("status") != CATALOG_STATUS:
        raise DrawingLibraryError("工程断面资料库状态不明确，未作为计算依据启用。")
    drawings = data.get("drawings")
    if not isinstance(drawings, list) or any(not isinstance(item, dict) for item in drawings):
        raise DrawingLibraryError("工程断面资料库缺少有效的图纸目录。")
    identities = [item.get("drawing_id") for item in drawings]
    if any(not isinstance(value, str) or not value for value in identities) or len(set(identities)) != len(identities):
        raise DrawingLibraryError("工程断面资料库的图纸编号缺失或重复。")
    if not include_archived:
        data["drawings"] = [item for item in drawings if item["drawing_id"] not in ARCHIVED_DRAWING_IDS]
    return data


def list_drawings(path=None):
    return deepcopy(load_catalog(path)["drawings"])


def _evidence_path(root, reference):
    value = reference.get("path", reference.get("file", "")) if isinstance(reference, dict) else reference
    if not isinstance(value, str) or not value.strip():
        raise DrawingLibraryError("图纸原始文字证据未提供文件名。")
    path = (root / value).resolve()
    if not path.is_relative_to(root) or path.suffix.lower() != ".json":
        raise DrawingLibraryError("图纸证据必须为资料库内的相对 JSON 文件。")
    return path


def _text_records(value, *, inherited=None):
    """Keep layout and original entity fields when flattening evidence JSON."""
    inherited = inherited or {}
    if isinstance(value, list):
        for item in value:
            yield from _text_records(item, inherited=inherited)
    elif isinstance(value, dict):
        if value.get("schema") == "engineering_drawing_evidence_1.0":
            # Compiled evidence also keeps derived tables/templates and a
            # complete dimension backup. Neither is another original text.
            yield from _text_records(value.get("texts", []), inherited=inherited)
            if not value.get("text_index_includes_dimensions"):
                yield from _text_records(value.get("dimensions", []), inherited=inherited)
            return
        context = dict(inherited)
        for key in ("layout", "layout_name", "block_path", "drawing_id"):
            if value.get(key) is not None:
                context[key] = value[key]
        text = next((value[key] for key in ("raw_text", "text", "plain_text", "content")
                     if isinstance(value.get(key), str)), None)
        if text is not None:
            record = {**context, **deepcopy(value)}
            record.setdefault("raw_text", text)
            record.setdefault("layout", record.get("layout_name", "未标明布局"))
            yield record
            if value.get("handle"):
                return
        # Evidence containers differ between DXF readers. Recurse without
        # dropping layout TEXT/MTEXT or dimension records in auxiliary arrays.
        for key, child in value.items():
            if isinstance(child, (dict, list)):
                if key == "layouts" and isinstance(child, dict):
                    for layout, records in child.items():
                        yield from _text_records(records, inherited={**context, "layout": layout})
                else:
                    yield from _text_records(child, inherited=context)


def load_evidence_texts(drawing, path=None, *, warnings=None):
    """Return all original text records; report unreadable evidence separately.

    ``evidence_files`` accepts relative JSON names or {path: ...} entries.
    Original records remain intact and get a ``_evidence_file`` locator.
    """
    root = Path(path or catalog_path()).resolve().parent
    errors = []
    records = []
    references = drawing.get("evidence_files") or []
    if isinstance(references, (str, dict)):
        references = [references]
    for reference in references:
        try:
            source = _evidence_path(root, reference)
            for record in _text_records(_read_json(source)):
                record["_evidence_file"] = str(source.relative_to(root))
                records.append(record)
        except DrawingLibraryError as error:
            errors.append(str(error))
    if errors:
        if warnings is None:
            raise DrawingLibraryError("\n".join(errors))
        warnings.extend(errors)
    return records
