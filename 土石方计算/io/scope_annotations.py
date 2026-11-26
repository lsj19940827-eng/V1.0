"""Mark an already-saved partial TEST export without changing its quantities."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import math
from pathlib import Path


_FOOTER_APPID = "QX_DRAWING_META"


def _is_original_footer(entity):
    # New drawings identify their short footer through hidden metadata;
    # archived drawings retain the original visible prefix.
    return entity.has_xdata(_FOOTER_APPID) or "单位：m；输入 " in entity.plain_text()


def _sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _record_digest(value):
    return hashlib.sha256(repr(value).encode("utf8")).hexdigest()


def _station(value):
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError("局部验收范围桩号无效")
    millimetres = round(value * 1000)
    kilometres, remainder = divmod(millimetres, 1_000_000)
    return f"K{kilometres}+{remainder / 1000:07.3f}"


def _scope(payload):
    scope = deepcopy(payload["defined_scope"])
    deferred = scope.get("deferred_asset_id")
    excluded = deepcopy(payload.get("excluded_assets", []))
    matches = [item for item in excluded if item.get("asset_id") == deferred]
    if not deferred or not matches:
        raise ValueError("局部验收范围缺少实际未计对象记录")
    names = {str(item.get("name") or (item.get("original_asset_snapshot") or {}).get("name") or "")
             for item in matches}
    names.discard("")
    if len(names) != 1:
        raise ValueError("局部验收未计对象名称缺失或冲突")
    start, end = float(scope["station_start"]), float(scope["station_end"])
    if not math.isfinite(start) or not math.isfinite(end) or end <= start:
        raise ValueError("局部验收未计对象范围无效")
    rows = deepcopy(payload.get("rows", []))
    if any(row.get("original_asset_id", row.get("asset_id")) == deferred for row in rows):
        raise ValueError("未计对象仍包含工程量，不能标注为局部验收")
    for item in matches:
        original = item.get("original_asset_snapshot") or {}
        for key, expected in (("station_start", start), ("station_end", end)):
            actual = item.get(key, original.get(key))
            if actual is not None and float(actual) != expected:
                raise ValueError("局部验收未计对象实际范围与标注不一致")
    name = next(iter(names))
    description = f"{name}{_station(start)}-{_station(end)}未计"
    return scope, rows, excluded, description


def _dxf(path, label):
    import ezdxf
    from ezdxf import bbox
    from ezdxf.lldxf.tagwriter import TagCollector

    document = ezdxf.readfile(path)
    if document.audit().errors:
        raise ValueError("局部验收标注前DXF审计失败")

    def tags(entity):
        return tuple(TagCollector.dxftags(entity))

    model = {entity.dxf.handle: tags(entity) for entity in document.modelspace()}
    # Dimension blocks and other non-layout definitions are part of the saved
    # engineering record, even though they are not direct modelspace entities.
    blocks = {block.name: tuple(tags(entity) for entity in block)
              for block in document.blocks if not block.name.upper().startswith("*PAPER_SPACE")
              and block.name.upper() != "*MODEL_SPACE"}
    unchanged_paper, footers = {}, {}
    for layout in document.layouts:
        if layout.name == "Model":
            continue
        found = [entity for entity in layout.query("MTEXT") if _is_original_footer(entity)]
        if len(found) != 1:
            raise ValueError(f"{layout.name}缺少唯一原图脚，不能追加局部验收说明")
        footer = found[0]
        if "局部TEST：" in footer.plain_text():
            raise ValueError("局部验收图脚已经标注，不能重复追加")
        footers[layout.name] = {"handle": footer.dxf.handle, "text": footer.text,
                               "attributes": deepcopy(footer.dxf.all_existing_dxf_attribs()),
                               "nontext_tags": tuple(tag for tag in tags(footer) if tag.code not in (1, 3))}
        unchanged_paper[layout.name] = {entity.dxf.handle: tags(entity) for entity in layout
                                       if entity.dxf.handle != footer.dxf.handle}
        content = label.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("^", "^ ")
        footer.text += "；" + content
    if not footers:
        raise ValueError("DXF没有可标注的实际图纸页")
    document.saveas(path)
    saved = ezdxf.readfile(path)
    if saved.audit().errors:
        raise ValueError("局部验收标注DXF保存回读审计失败")
    saved_model = {entity.dxf.handle: tags(entity) for entity in saved.modelspace()}
    if saved_model != model:
        raise ValueError("局部验收标注改变了原模型实体")
    if {block.name: tuple(tags(entity) for entity in block)
        for block in saved.blocks if not block.name.upper().startswith("*PAPER_SPACE")
        and block.name.upper() != "*MODEL_SPACE"} != blocks:
        raise ValueError("局部验收标注改变了原结构或尺寸图块")
    spatial = None
    model_bounds = []
    projected_count = 0

    def overlaps(a, b):
        return (a[0] + 1e-7 < b[2] and b[0] < a[2] - 1e-7
                and a[1] + 1e-7 < b[3] and b[1] < a[3] - 1e-7)

    def viewport_content_overlaps(viewport, footer_bounds):
        nonlocal spatial, projected_count
        # A viewport may contain blank paper behind the existing footer. Only
        # its visible, projected model content can overlap the appended note.
        from shapely.geometry import box
        from shapely.strtree import STRtree
        if spatial is None:
            for entity in saved.modelspace():
                extent = bbox.extents([entity], fast=False)
                if extent.has_data:
                    model_bounds.append((extent.extmin.x, extent.extmin.y, extent.extmax.x, extent.extmax.y))
            spatial = STRtree([box(*bounds).buffer(1e-9) for bounds in model_bounds])
        direction = viewport.dxf.view_direction_vector
        if (not math.isclose(viewport.dxf.view_twist_angle, 0., abs_tol=1e-12)
                or tuple(direction) != (0., 0., 1.)):
            raise ValueError("局部验收图脚仅支持当前实际二维正投影视口")
        visible = viewport.get_modelspace_limits()
        factor = viewport.dxf.height / viewport.dxf.view_height
        center, target = viewport.dxf.center, viewport.dxf.view_center_point
        for index in spatial.query(box(*visible), predicate="intersects"):
            original = model_bounds[int(index)]
            clipped = (max(original[0], visible[0]), max(original[1], visible[1]),
                       min(original[2], visible[2]), min(original[3], visible[3]))
            projected = ((clipped[0] - target.x) * factor + center.x,
                         (clipped[1] - target.y) * factor + center.y,
                         (clipped[2] - target.x) * factor + center.x,
                         (clipped[3] - target.y) * factor + center.y)
            projected_count += 1
            if overlaps(footer_bounds, projected):
                return True
        return False

    pages = []
    for name, original in footers.items():
        layout = saved.layouts.get(name)
        footer = saved.entitydb[original["handle"]]
        if footer.plain_text().count(label) != 1 or not footer.text.startswith(original["text"] + "；"):
            raise ValueError("局部验收图脚文本保存回读不一致")
        if footer.dxf.all_existing_dxf_attribs() != original["attributes"]:
            raise ValueError("局部验收图脚位置、字高、宽度或样式改变")
        if tuple(tag for tag in tags(footer) if tag.code not in (1, 3)) != original["nontext_tags"]:
            raise ValueError("局部验收标注改变了原图脚元数据或其他属性")
        if {entity.dxf.handle: tags(entity) for entity in layout
            if entity.dxf.handle != footer.dxf.handle} != unchanged_paper[name]:
            raise ValueError("局部验收标注改变了原图纸内容或视口")
        frames = list(layout.query('LWPOLYLINE[layer=="图框"]'))
        if len(frames) != 1:
            raise ValueError("局部验收图脚无法核对实际图框")
        frame = bbox.extents(frames, fast=False)
        extent = bbox.extents([footer], fast=False)
        if not frame.has_data or not extent.has_data or not (
            frame.extmin.x - 1e-7 <= extent.extmin.x <= extent.extmax.x <= frame.extmax.x + 1e-7
            and frame.extmin.y - 1e-7 <= extent.extmin.y <= extent.extmax.y <= frame.extmax.y + 1e-7
        ):
            raise ValueError("局部验收图脚超出图框")
        for entity in layout:
            if entity is footer or entity.dxf.layer == "图框":
                continue
            if entity.dxftype() == "VIEWPORT" and entity.dxf.id == 1:
                continue
            other = bbox.extents([entity], fast=False)
            footer_bounds = (extent.extmin.x, extent.extmin.y, extent.extmax.x, extent.extmax.y)
            if other.has_data and overlaps(footer_bounds, (other.extmin.x, other.extmin.y, other.extmax.x, other.extmax.y)):
                if entity.dxftype() != "VIEWPORT" or viewport_content_overlaps(entity, footer_bounds):
                    raise ValueError("局部验收图脚与原图纸内容重叠")
        pages.append({"layout": name, "footer_handle": footer.dxf.handle,
                      "footer_bounds_mm": [extent.extmin.x, extent.extmin.y, extent.extmax.x, extent.extmax.y],
                      "frame_bounds_mm": [frame.extmin.x, frame.extmin.y, frame.extmax.x, frame.extmax.y]})
    return {"saved_reopened": True, "audit_errors": 0, "annotated_layout_count": len(pages),
            "all_original_model_entity_tags_exact": True, "all_original_structure_dimension_blocks_exact": True,
            "all_original_paper_entities_and_viewports_exact": True, "footer_attributes_exact": True,
            "footer_nontext_tags_including_metadata_exact": True,
            "original_model_entity_tags_sha256": _record_digest(model),
            "annotated_model_entity_tags_sha256": _record_digest(saved_model),
            "checked_actual_projected_model_entities": projected_count,
            "footer_inside_frame_without_content_overlap": True, "pages": pages}


def _xlsx(path, payload, rows, excluded, description):
    from openpyxl import load_workbook
    from openpyxl.styles import Alignment, Font

    workbook = load_workbook(path, data_only=False)
    if "工程量汇总" not in workbook.sheetnames or "计量范围说明" in workbook.sheetnames:
        raise ValueError("Excel汇总不存在或局部验收范围表已存在")

    def cells(sheet):
        return {(cell.row, cell.column): (cell.value, cell.data_type, cell.number_format,
                                          deepcopy(cell._style), deepcopy(cell.hyperlink), deepcopy(cell.comment))
                for row in sheet.iter_rows() for cell in row}

    original = {sheet.title: cells(sheet) for sheet in workbook}
    title = f"局部TEST断面法工程量（{description}）"
    workbook["工程量汇总"]["A1"] = title
    sheet = workbook.create_sheet("计量范围说明")
    explanation = str(payload.get("acceptance_scope") or "明确对象局部TEST；未计对象补齐后重新验收，当前不是完整全线验收。")
    lines = [["范围性质", "局部TEST；非完整全线验收"], ["未计范围", description],
             ["接受范围说明", explanation], ["输入SHA256", payload.get("input_hash", "")], [],
             ["计量状态", "对象编号", "名称", "起点m", "终点m", "类型", "说明"]]
    for row in rows:
        lines.append(["已计", row["asset_id"], row.get("name", ""), row.get("station_start"),
                      row.get("station_end"), row.get("section_type", row.get("kind", "")), "实际成果rows纳入范围"])
    for item in excluded:
        snapshot = item.get("original_asset_snapshot") or {}
        lines.append(["未计", item.get("asset_id", ""), item.get("name", snapshot.get("name", "")),
                      item.get("station_start", snapshot.get("station_start")),
                      item.get("station_end", snapshot.get("station_end")),
                      item.get("section_type", snapshot.get("section_type", "")),
                      item.get("reason", item.get("code", ""))])
    # Excel represents empty text cells as blank cells on save/reopen.
    lines = [[None if value == "" else value for value in line] for line in lines]
    for line in lines:
        sheet.append(line)
    sheet.freeze_panes = "A7"
    for column, width in {"A": 18, "B": 27, "C": 25, "D": 18, "E": 18, "F": 25, "G": 80}.items():
        sheet.column_dimensions[column].width = width
    for line in sheet:
        for cell in line:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            if isinstance(cell.value, (int, float)):
                cell.number_format = "0.000"
    for cell in sheet[6]:
        cell.font = Font(bold=True)
    workbook.save(path)
    workbook.close()
    saved = load_workbook(path, data_only=False)
    try:
        if saved.sheetnames != list(original) + ["计量范围说明"]:
            raise ValueError("局部验收标注改变了原Excel工作表")
        saved_original_cells = {}
        for name, before in original.items():
            actual = cells(saved[name])
            saved_original_cells[name] = actual
            expected = deepcopy(before)
            if name == "工程量汇总":
                a1 = expected[(1, 1)]
                expected[(1, 1)] = (title, *a1[1:])
            if actual != expected:
                raise ValueError("局部验收标注改变了原Excel工程量或记录单元格")
        actual_lines = [[saved["计量范围说明"].cell(i, j).value for j in range(1, len(line) + 1)]
                        for i, line in enumerate(lines, 1)]
        def same_value(actual, expected):
            if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
                return math.isclose(actual, expected, rel_tol=0., abs_tol=1e-10)
            return actual == expected
        if any(not all(same_value(actual, expected) for actual, expected in zip(actual_line, expected_line))
               for actual_line, expected_line in zip(actual_lines, lines)):
            raise ValueError("局部验收范围表保存回读不一致")
    finally:
        saved.close()
    def unchanged_cells(values):
        snapshot = deepcopy(values)
        snapshot["工程量汇总"].pop((1, 1))
        return snapshot
    return {"saved_reopened": True, "all_original_cells_except_summary_A1_exact": True,
            "all_original_numeric_and_record_cells_exact": True, "scope_sheet": "计量范围说明",
            "original_cells_except_summary_A1_sha256": _record_digest(unchanged_cells(original)),
            "annotated_cells_except_summary_A1_sha256": _record_digest(unchanged_cells(saved_original_cells)),
            "new_scope_station_float_save_roundtrip_tolerance_m": 1e-10,
            "actual_measured_row_count": len(rows), "actual_excluded_record_count": len(excluded)}


def annotate_saved_scope(payload, staged_path, metadata):
    """Annotate only this export's staging copy; normal full-scope paths are no-op."""
    if not payload.get("defined_scope") or payload.get("partial_acceptance") is not True:
        return metadata
    path = Path(staged_path)
    scope, rows, excluded, description = _scope(payload)
    label = "局部TEST：" + description
    before = _sha(path)
    if path.suffix.lower() == ".dxf":
        invariance = _dxf(path, label)
    elif path.suffix.lower() == ".xlsx":
        invariance = _xlsx(path, payload, rows, excluded, description)
    else:
        invariance = {"file_bytes_unchanged": True, "metadata_only": True}
    annotation = {"defined_scope": scope, "partial_acceptance": True, "formal_complete_line_acceptance": False,
                  "label": label, "acceptance_scope": payload.get("acceptance_scope"),
                  "actual_measured_rows": rows, "actual_excluded_assets": excluded,
                  "before_file_sha256": before, "after_file_sha256": _sha(path),
                  "saved_record_geometry_invariance": invariance}
    return {**deepcopy(metadata), "defined_scope": deepcopy(scope), "partial_acceptance": True,
            "formal_complete_line_acceptance": False, "scope_annotation": annotation}
