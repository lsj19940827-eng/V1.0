"""Readable drawing evidence for the construction parameter editor."""
from __future__ import annotations

import json
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QLabel, QPlainTextEdit, QSizePolicy, QSpacerItem, QTableWidget,
    QTableWidgetItem, QToolButton, QTreeWidget, QTreeWidgetItem,
)

from .drawing_bindings_dialog import _LABELS


def drawing_option_title(scheme):
    return scheme.get("title") or scheme["scheme_id"]


_TABLE_STYLE = """
QTreeWidget, QTableWidget { background: white; alternate-background-color: #f5f8fb;
    color: #293f52; border: 1px solid #d4e0e9; }
QTreeWidget::item { padding: 4px 6px; }
QHeaderView::section { background: #eaf1f6; color: #3e596e; padding: 5px 6px;
    border: none; border-bottom: 1px solid #d4e0e9; }
"""
_VALUES = {
    **_LABELS, "sand": "砂料", "rockfill": "石渣", "sand_gravel": "砂砾料",
    "geotextile": "土工布", "geomembrane": "防渗膜", "ductile_iron": "球墨铸铁",
    "trench_bottom": "按槽底全宽", "support_chord": "按支承角弦宽",
    "support_chord_plus_sides": "弦宽加两侧外伸", "inner_diameter_offset": "管内径加两侧外伸",
    "explicit": "按指定底宽", "excavation": "沿开挖边坡", "vertical": "竖直侧边",
    "foundation_bottom": "基础底面", "lining_outer_bottom": "衬砌外底", "pipe_seat_bottom": "管座底面",
    "pipe_foundation": "管座、包封或底部垫层外缘", "pipe_outer": "管外壁", "occupancy": "结构及材料外缘",
    "buried": "明挖埋设", "elevated": "架空敷设", "exposed": "明管敷设",
    "with_membrane": "设复合膜", "without_membrane": "不设复合膜",
    "flat": "平底沟槽", "offset": "沿外轮廓开挖", "m3": "m³", "m2": "m²",
}
_FIELD_NAMES = {
    "enabled": "启用", "material_role": "材料归类", "separate_material": "单独列项计量",
    "bottom_width_mode": "底宽取法", "side_boundary_mode": "侧边界", "material": "材质",
    "grade": "材料等级", "name": "名称", "support_angle": "支承角（°）",
    "base_thickness": "底厚（m）", "extension": "每侧外伸（m）", "bottom_width": "底宽（m）",
    "left_thickness": "左侧厚度（m）", "right_thickness": "右侧厚度（m）",
    "top_thickness": "顶部厚度（m）", "bottom_thickness": "底部厚度（m）", "side_thickness": "侧面厚度（m）",
}
_PATH_LABELS = {
    "construction.bedding_reference": "垫层基准面", "construction.installation_mode": "管道敷设方式",
    "construction.working_space_reference": "工作面起算位置",
    "construction.foundation_replacement_material": "地基换填材料",
    "section.inner_chamfers": "内倒角（m）",
}


def _field_name(path):
    from .engineering_drawings_dialog import _field_label

    key = path.rsplit(".", 1)[-1]
    for prefix, group in (("construction.pipe_seat.", "管座"), ("construction.encasement.", "包封")):
        if path.startswith(prefix) and key in _FIELD_NAMES:
            return group + " · " + _FIELD_NAMES[key]
    pipe = re.fullmatch(r"section\.pipes\[(\d+)\]\.(.+)", path)
    if pipe:
        return "第" + pipe[1] + "根管 · " + _field_name("section." + pipe[2])
    if path in _PATH_LABELS:
        return _PATH_LABELS[path]
    label = _field_label(path)
    if label != key and not label.endswith(key):
        return label
    return _LABELS.get(path, "其他构造参数")


def _summary(value):
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (float, int)):
        return str(value).removesuffix(".0")
    if isinstance(value, list):
        if value and all(isinstance(item, dict) and item.get("name") for item in value):
            return "、".join(str(item["name"]) for item in value)
        if value and all(isinstance(item, (int, float)) for item in value):
            return " × ".join(_summary(item) for item in value)
        return f"共 {len(value)} 项"
    if isinstance(value, dict):
        corners = {"bottom_left": "左下", "bottom_right": "右下", "top_left": "左上", "top_right": "右上"}
        if value and value.keys() <= corners.keys():
            return "，".join(label + " " + _summary(value[key]) for key, label in corners.items() if key in value)
        detail = [str(value[key]) for key in ("name", "grade") if value.get(key)]
        return " · ".join(detail) if detail else f"共 {len(value)} 项"
    if value is None or value == "":
        return "未填写"
    return _VALUES.get(str(value), str(value))


def _heading(form, title):
    heading = QLabel(title)
    heading.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    font = heading.font()
    font.setBold(True)
    heading.setFont(font)
    form.addRow(heading)


def _table(headers, rows, *, editable=()):
    table = QTableWidget(len(rows), len(headers))
    table.setStyleSheet(_TABLE_STYLE)
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().hide()
    table.setShowGrid(False)
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    for row, values in enumerate(rows):
        for col, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setToolTip(str(value))
            if col not in editable:
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            table.setItem(row, col, item)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    table.horizontalHeader().setStretchLastSection(True)
    height = table.horizontalHeader().sizeHint().height() + table.verticalHeader().defaultSectionSize() * min(5, len(rows)) + 6
    table.setFixedHeight(height)
    return table


def _component_table(components):
    names = {c["component_id"]: c.get("name") or "前置构件" for c in components if c.get("component_id")}
    rows = []
    for item in components:
        key = "thickness_m" if item.get("geometry_kind") == "outer_offset_layer" or "nominal_thickness_m" not in item else "nominal_thickness_m"
        ref = item.get("after_component_id")
        position = names.get(ref, "前置构件") + "外侧" if ref else "结构外偏 " + _summary(item.get("offset_m", 0.)) + " m"
        thickness = item.get(key)
        rows.append((item.get("name") or "独立构件", _summary(item.get("material")), _summary(item.get("unit")),
                     "" if thickness is None else str(thickness), item.get("grade") or "", position))
    table = _table(("构件名称", "材质", "单位", "厚度（m）", "材料等级", "铺设位置"), rows, editable=(3, 4))
    for row, item in enumerate(components):
        if item.get("geometry_kind") == "outer_surface":
            table.item(row, 3).setToolTip("膜的名义厚度，铺设面积按实际铺设面计算。")
    return table


def _source_title(asset, path, source, bindings):
    if source.get("geometry_derived"):
        return "本段换填几何 · " + ("用户设定" if source.get("user_override") else "随本段参数计算")
    identifier = source.get("scheme_id") or source.get("template_id")
    if asset.get("drawing_sources_preview") and source.get("user_override") and not identifier:
        return "本段用户设定"
    binding = bindings.get(identifier, {})
    title = source.get("title") or binding.get("title")
    if not title:
        note = asset.get("parameter_sources", {}).get(path, "")
        if isinstance(note, str) and note.startswith(("图纸依据：", "图纸断面方案：")):
            title = note.partition("：")[2].split(" / ", 1)[0]
    title = title or "工程图纸"
    if source.get("user_override"):
        return title + " · 用户设定"
    if source.get("inherited"):
        return title + " · 沿用工程值"
    return title


def _fill_source_tree(tree, asset, sources, labels):
    tree.clear()
    bindings = {b["template_id"]: b for b in (asset.get("drawing_bindings") or []) if b.get("template_id")}
    binding = asset.get("section_scheme_binding") or {}
    snapshot = binding.get("scheme_snapshot") or {}
    if snapshot.get("scheme_id"):
        bindings[snapshot["scheme_id"]] = snapshot
    groups = {}
    comparisons = {}
    for path, source in sources.items():
        if path == "construction.foundation_replacement.excavation_follows_outline":
            continue
        if source.get("user_override") and not source.get("geometry_derived"):
            drawing = source.get("drawing_value")
            if drawing is None and path not in (binding.get("inherited_fields") or {}):
                drawing = (binding.get("resolved_fields") or {}).get(path)
            if drawing is not None and drawing != source.get("adopted_value"):
                comparisons[path] = _summary(drawing)
    tree.setColumnHidden(2, not comparisons)
    # Put engineering decisions first so a differing project value can be read
    # beside its exact source-table value without scrolling past default rows.
    for path, source in sorted(sources.items(), key=lambda item: not item[1].get("user_override")):
        if path == "construction.foundation_replacement.excavation_follows_outline":
            continue
        title = _source_title(asset, path, source, bindings)
        if title not in groups:
            group = QTreeWidgetItem(tree, [title])
            group.setFirstColumnSpanned(True)
            font = group.font(0)
            font.setBold(True)
            group.setFont(0, font)
            groups[title] = group
        value = _summary(source.get("adopted_value"))
        name = _field_name(path)
        item = QTreeWidgetItem(groups[title], [labels.get(path, name) if name == "其他构造参数" else name,
                                               value, comparisons.get(path, "")])
        item.setData(0, Qt.UserRole, path)
        item.setToolTip(1, source.get("geometry_basis") or value)
    tree.expandAll()
    lines = min(12, len(sources) + len(groups))
    tree.setFixedHeight(tree.header().sizeHint().height() + tree.sizeHintForRow(0) * lines + 8)


def size_match_description(match):
    schedule, field, value, row = match
    if schedule is None:
        return "当前结构采用通用构造，表外尺寸按本段设计值填写。"
    table = schedule.get("source_table") or "图纸尺寸表"
    if field == "section.pipes":
        return f"{table}　各管规格不同，按本段设计尺寸。"
    if value is None:
        return f"{table}　填写断面尺寸后匹配图纸。"
    if field == "section.nominal_diameter_m":
        size = f"DN {value * 1000:g}"
    else:
        name = {"section.inner_diameter": "净内径", "section.inner_radius": "净内半径",
                "section.inner_width": "净宽"}.get(field, "尺寸")
        size = f"{name} {value:g} m"
    if row is None:
        return f"{table}　{size} 为表外规格，采用通用构造，尺寸按本段设计值填写。"
    return f"{table}　{size} 对应 {row['match_value']:g} m 档"


def refresh_drawing_preview(dialog, changes, labels, schedule_fields=None, size_match=None, replacement=None):
    """Display a draft projection. The persisted evidence remains the initial snapshot."""
    sources = dict(dialog.asset.get("drawing_parameter_sources") or {})
    if schedule_fields is not None:
        scheme = dialog.asset["section_scheme_binding"]["scheme_snapshot"]
        metadata = {key: scheme.get(key) for key in ("scheme_id", "drawing_id", "source_sha256", "source_handles")}
        sources = {path: {**metadata, "drawing_value": value, "adopted_value": value}
                   for path, value in schedule_fields.items()}
        dialog.drawing_size_match.setText(size_match_description(size_match))
        row = size_match[3]
        if row:
            for path in {*row.get("fields", {}), *row.get("derived_fields", {})} & sources.keys():
                sources[path]["size_row_handles"] = row.get("source_handles") or []
    values = {**(dialog.asset.get("drawing_user_overrides") or {}), **changes}
    for path, value in values.items():
        sources[path] = {**sources.get(path, {}), "user_override": True, "adopted_value": value}
    if replacement:
        for path, row in replacement.items():
            sources[path] = {**sources.get(path, {}), **row}
            sources[path].pop("drawing_value", None)
    if sources == getattr(dialog, "_shown_drawing_sources", None):
        return
    _fill_source_tree(dialog.drawing_source_tree, dialog.asset, sources, labels)
    section = dialog.asset.get("section", {})
    if hasattr(dialog, "drawing_specs_table"):
        for row, (key, original) in enumerate(section["material_specs"].items()):
            spec = changes.get("section.material_specs." + key, original)
            grade = spec.get("grade") or "未填写"
            item = dialog.drawing_specs_table.item(row, 2)
            item.setText(grade)
            item.setToolTip(grade)
    dialog.drawing_material_details.setPlainText(_records_text(section.get("material_specs") or {},
        section.get("component_specs") or [], sources))
    dialog._shown_drawing_sources = sources


def _records_text(specs, components, sources):
    """Keep original paths, values and CAD identifiers together for copying."""
    blocks = []
    for item in [*specs.values(), *components]:
        blocks.append(str(item.get("name") or "材料记录") + "\n" + json.dumps(item, ensure_ascii=False, indent=2))
    groups = {}
    for path, source in sources.items():
        metadata = {k: v for k, v in source.items() if k not in {
            "original_value", "drawing_value", "adopted_value", "inherited", "user_override"}}
        key = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        values = {k: v for k, v in source.items() if k not in metadata}
        groups.setdefault(key, []).append(path + "  " + json.dumps(values, ensure_ascii=False))
    labels = {"scheme_id": "断面方案编号", "template_id": "模板编号", "drawing_id": "图纸编号",
              "source_sha256": "原图 SHA256", "source_handles": "原图实体编号",
              "size_row_handles": "尺寸表行实体编号", "geometry_basis": "计算依据",
              "version": "版本", "template_version": "模板版本"}
    for key, records in groups.items():
        lines = []
        for field, value in json.loads(key).items():
            if value is None or value == "" or value == []:
                continue
            content = "、".join(map(str, value)) if field.endswith("handles") and isinstance(value, list) else str(value)
            lines.append(labels.get(field, field) + "：" + content)
        if not lines:
            lines.append("本段参数记录")
        blocks.append("\n".join([*lines, *records]))
    return "\n\n".join(blocks)


def populate_drawing_details(dialog, form, specs, components, sources):
    if components:
        _heading(form, "独立材料 · 双击厚度或等级可修改")
        dialog.component_table = _component_table(components)
        form.addRow(dialog.component_table)
    if specs:
        _heading(form, "材料明细")
        rows = [(item.get("name") or _summary(key), _summary(item.get("material")), item.get("grade") or "未填写")
                for key, item in specs.items()]
        dialog.drawing_specs_table = _table(("材料名称", "材质", "等级"), rows)
        form.addRow(dialog.drawing_specs_table)
    if sources or dialog.asset.get("drawing_sources_preview"):
        _heading(form, "参数取值依据")
        scheme = (dialog.asset.get("section_scheme_binding") or {}).get("scheme_snapshot") or {}
        if dialog.asset.get("drawing_sources_preview") and scheme.get("dimension_schedules"):
            from 土石方计算.services.section_scheme_bindings import hydraulic_dimensions
            from 土石方计算.services.section_scheme_catalog import match_section_scheme_size

            match = match_section_scheme_size(scheme, hydraulic_dimensions(dialog.asset))
            dialog.drawing_size_match = QLabel(size_match_description(match))
            dialog.drawing_size_match.setWordWrap(True)
            form.addRow(dialog.drawing_size_match)
        tree = QTreeWidget()
        tree.setStyleSheet(_TABLE_STYLE)
        tree.setHeaderLabels(("构造参数", "本段拟采用值" if dialog.asset.get("drawing_sources_preview") else "绑定时采用值", "图纸原值"))
        tree.header().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        tree.header().setStretchLastSection(False)
        tree.setAlternatingRowColors(True)
        tree.setIndentation(16)
        _fill_source_tree(tree, dialog.asset, sources, {})
        dialog.drawing_source_tree = tree
        form.addRow(tree)
    toggle = QToolButton()
    toggle.setText("原图追溯记录")
    toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
    toggle.setAutoRaise(True)
    toggle.setCheckable(True)
    toggle.setArrowType(Qt.RightArrow)
    form.addRow(toggle)
    viewer = QPlainTextEdit()
    viewer.setReadOnly(True)
    viewer.setPlainText(_records_text(specs, components, sources))
    viewer.setMinimumHeight(140)
    form.addRow(viewer)
    form.addItem(QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding))
    viewer.hide()
    toggle.toggled.connect(viewer.setVisible)
    toggle.toggled.connect(lambda checked: toggle.setArrowType(Qt.DownArrow if checked else Qt.RightArrow))
    dialog.drawing_material_details = viewer
    dialog.drawing_trace_toggle = toggle
