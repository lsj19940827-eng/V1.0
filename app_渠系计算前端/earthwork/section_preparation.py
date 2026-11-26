"""Whole-line construction preparation and scope editing for the workbench."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QModelIndex, QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox, QGroupBox, QHeaderView, QHBoxLayout, QLabel, QPushButton, QStackedWidget,
    QStyledItemDelegate, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from 土石方计算.io.network_exporter import SECTION_NAMES
from 土石方计算.services.batch_cover_profiles import (
    ENGINEERING_COVER_CONTROL_STEP_M, cover_parameters, has_supplied_design_profile, is_pressure_cover_asset,
)
from 土石方计算.services.earthwork_scope import (
    is_trenchless_exclusion, trenchless_edit_key, trenchless_excavation_quantities, trenchless_exclusion,
    trenchless_live_route_id, trenchless_method, update_trenchless_section,
)
from 土石方计算.services.imported_design_profiles import _route_fingerprint, _route_namespace
from 土石方计算.services.section_scheme_bindings import format_station
from 土石方计算.services.sluice_gate import gate_missing_fields, gate_reference_asset, gate_station_range, is_sluice_gate
from 土石方计算.services.transition_connections import connection_needs_settings
from 土石方计算.services.workbench_automatic_ranges import restore_workbench_automatic_ranges
from 土石方计算.services.workbench_calculator import asset_requires_section_terrain
from 土石方计算.services.workbench_scope import (
    calculation_asset_data_issue, missing_construction_fields, supports_partial_calculation,
)

from .choice_display import ChoiceDisplay
from .pipe_profile_mapping import profile_key
from .trenchless_section import TrenchlessSectionCard


_PIPE_SPECIAL_SCOPE_ROLE = Qt.UserRole + 3
_PIPE_PROFILE_SCOPE_ROLE = Qt.UserRole + 4
_CHANNEL_PROFILE_SCOPE_ROLE = Qt.UserRole + 5


_FIELD_LABELS = {
    "gate_length": "闸长",
    "gate_station": "闸中心桩号",
    "gate_lining_multiplier": "衬砌厚度倍率",
    "base_thickness": "底板厚度",
    "roof_thickness": "顶板厚度",
    "wall_thickness_left": "左侧壁厚",
    "wall_thickness_right": "右侧壁厚",
    "wall_thickness": "壁厚",
    "outer_diameter": "施工外径",
    "inner_width": "净宽",
    "inner_height": "净高",
    "inner_diameter": "净径",
    "inner_radius": "净半径",
    "bottom_width": "底宽",
    "wall_height": "直墙高度",
    "arch_angle_degrees": "拱部圆心角",
    "pipe_spacing": "并管间距",
    "installation_mode": "敷设方式",
    "working_space_left": "左侧工作面",
    "working_space_right": "右侧工作面",
    "bedding_thickness": "垫层厚度",
    "bedding_extension": "垫层外伸",
    "excavation_slope_left": "左侧开挖坡比",
    "excavation_slope_right": "右侧开挖坡比",
    "bank_top_width_left": "左侧渠顶宽度",
    "bank_top_width_right": "右侧渠顶宽度",
    "bank_slope_left": "左侧外坡",
    "bank_slope_right": "右侧外坡",
    "target_mode": "回填完成面",
    "rock_class": "围岩类别",
    "lining_thickness": "衬砌厚度",
    "shotcrete_thickness": "喷混凝土厚度",
    "overbreak_thickness": "超挖厚度",
    "cover_depth": "管顶埋深",
    "final_cover_depth": "完成面覆土厚度",
    "excavation_clearance": "开挖预留间隙",
}


def construction_field_label(field):
    key = field.rsplit(".", 1)[-1]
    return _FIELD_LABELS.get(key, key)


@dataclass(frozen=True)
class PreparationTask:
    route_id: str
    asset_id: str
    name: str
    route_name: str
    span: str
    message: str
    action: str
    action_label: str
    field: str | None = None


@dataclass(frozen=True)
class PreparationPart:
    asset_id: str
    span: str
    enabled: bool
    editable: bool
    status: str
    is_bore: bool = False
    requires_terrain: bool = True


@dataclass(frozen=True)
class PreparationRow:
    route_id: str
    asset_id: str
    route_name: str
    name: str
    structure: str
    span: str
    status: str
    parts: tuple[PreparationPart, ...]
    issues: tuple[PreparationTask, ...] = ()
    detail: str = ""
    route_group: str = ""
    start: float | None = None
    is_bore: bool = False
    bore_sections: tuple[tuple[str, dict], ...] = ()
    flow_section: str = ""


@dataclass(frozen=True)
class PreparationSnapshot:
    rows: tuple[PreparationRow, ...]
    allow_partial: bool

    @property
    def ready(self):
        return tuple(row for row in self.rows if row.status == "ready")

    @property
    def pending(self):
        return tuple(row for row in self.rows if row.status == "pending")

    @property
    def excluded(self):
        return tuple(row for row in self.rows if row.status == "excluded")

    @property
    def tasks(self):
        return tuple(task for row in self.rows for task in row.issues)

    @property
    def has_ready_work(self):
        return any(row.status == "ready" or any(part.status == "ready" for part in row.parts)
                   for row in self.rows)

    @property
    def priority_task(self):
        if not self.has_ready_work:
            return next(iter(self.tasks), None)
        if not self.allow_partial:
            return next((task for task in self.tasks if task.action not in {"bore_source", "transition"}), None)
        return None

def route_identity(network):
    if network is None:
        return ""
    return str(network.get("route_id") or network.get("network_id") or network.get("source_identity") or "")


def asset_root(asset):
    return str(asset.get("section_scheme_root_asset_id") or asset.get("drawing_root_asset_id")
               or asset.get("parent_asset_id") or asset.get("asset_id") or "")


def _span(asset, prefix):
    start, end = asset.get("station_start"), asset.get("station_end")
    try:
        if start is not None and end is not None:
            return f"{format_station(start, prefix)} ～ {format_station(end, prefix)}"
    except ValueError:
        pass
    return "桩号待补"


def building_structure(asset):
    if is_sluice_gate(asset):
        return "闸"
    method = trenchless_method(asset)
    if method:
        return method["method"]
    kind = asset.get("kind")
    if kind in {"pipe", "pressure_pipe"}:
        return "有压管道"
    if kind == "siphon":
        return "倒虹吸"
    return SECTION_NAMES.get(asset.get("section_type"), asset.get("section_type") or "基坑")


def building_display_name(asset, structure=None):
    for field in ("base_name", "name"):
        name = str(asset.get(field) or "").strip()
        if name not in {"", "-", "—", "/", "未命名"}:
            return name
    return structure or building_structure(asset)


def flow_section_label(value):
    label = str(value or "").strip()
    if not label or "流量段" in label:
        return label
    return f"第{label}流量段" if label.isdecimal() else f"流量段 {label}"


def _missing_value(asset, field):
    value = asset
    for key in field.split("."):
        value = value.get(key) if isinstance(value, dict) else None
    return value is None or isinstance(value, (list, dict)) and not value


def _preparation_part(network, asset):
    if network is None:
        return (), ""
    cover = is_pressure_cover_asset(asset) and not has_supplied_design_profile(asset)
    issue = calculation_asset_data_issue(network, asset, require_profile=not cover)
    if issue:
        code, message = issue
        directions = {"missing_alignment": ("source", "核对线路资料"),
                      "missing_station_range": ("source", "核对设计桩号"),
                      "missing_profile": ("profile", "设置设计纵断面"
                                          if is_pressure_cover_asset(asset) else "补充设计纵断面")}
        return ((message, *directions[code]),), ""
    detail = ""
    if cover:
        try:
            owner = network
            if isinstance(network["alignment"], dict):
                from 土石方计算.services.network_alignment import NetworkAlignment
                owner = {**network, "alignment": NetworkAlignment.from_dict(network["alignment"])}
            cover_parameters(owner, asset, ENGINEERING_COVER_CONTROL_STEP_M)
        except (ValueError, TypeError, KeyError) as error:
            return ((f"覆土纵断面待核：{error}", "parameters", "核对管道与覆土参数"),), ""
        detail = "算量时按当前地形复核覆土纵断面" if asset.get("cover_preview_confirmed") else "算量时按覆土生成纵断面"
    fields = set(asset.get("missing_fields", ())) | set(asset.get("source_missing_fields", ()))
    try:
        fields.update(missing_construction_fields(asset, check_tunnel_section=True))
    except ValueError as error:
        return ((str(error), "parameters", "核对分层开挖参数"),), ""
    fields.difference_update({"alignment", "station_range", "design_profile"})
    section = asset.get("section") or {}
    if section.get("wall_thickness") is not None:
        fields.difference_update({"section.wall_thickness_left", "section.wall_thickness_right"})
    missing = [field for field in sorted(fields) if _missing_value(asset, field)]
    if missing:
        names = [construction_field_label(field) for field in missing]
        return ((f"待补 {'、'.join(names)}", "parameters", "核对施工参数", missing[0]),), ""
    return (), detail


def _bore_identity_and_issues(record):
    rows = trenchless_excavation_quantities([record]).get("trenchless_excavation_rows", ())
    if not rows:
        return None, (("非开挖洞挖量待补：缺少有效施工资料", "bore_source", "核对非开挖设计资料"),), None
    row = rows[0]
    source_id = row["source_identity"] or row["asset_id"]
    identity = (row["route_id"], source_id, row["construction_method"],
                row["station_start"], row["station_end"]) if source_id else None
    issues = ((f"{row['construction_method']}洞挖量待补：{row['issue']}",
               "bore_source", "核对非开挖设计资料"),) if row["status"] == "pending" else ()
    return identity, issues, row


def _display_routes(source, channel_name):
    """Use shared source geometry for display groups, retaining precise edit keys."""
    networks = source.get("networks", ())
    groups = {}
    names = {}
    hydraulic_groups = set()
    references = {}
    for network in networks:
        route = route_identity(network)
        kind = (network.get("source") or {}).get("kind")
        if kind in {"estimated_water_profile_connection", "missing_ip_connection", "native_transition_connection"}:
            continue
        fingerprint = _route_fingerprint(network) if network.get("source_route_extent") else None
        namespace = _route_namespace(network)
        key = (namespace, fingerprint, network.get("station_prefix")) if fingerprint and namespace[0] else route
        group = groups.setdefault(key, route)
        name = str(network.get("name") or route)
        if kind == "water_profile_panel":
            hydraulic_groups.add(group)
            name = channel_name or name
        names[route] = group, name
        for asset in network.get("assets", ()):
            for identifier in (asset_root(asset), asset.get("asset_id")):
                if identifier:
                    references.setdefault(str(identifier), set()).add((group, name))

    estimates = {str(item.get("asset_id")): str(item.get("reference_asset_id"))
                 for item in source.get("connector_estimates", ()) if item.get("reference_asset_id")}
    main = names[next(iter(hydraulic_groups))] if len(hydraulic_groups) == 1 else None
    for network in networks:
        route = route_identity(network)
        if route in names:
            continue
        kind = (network.get("source") or {}).get("kind")
        if kind == "estimated_water_profile_connection":
            owners = references.get(estimates.get(route, ""), set())
            if len(owners) == 1:
                names[route] = next(iter(owners))
            elif not owners and route in estimates and main:
                # Some estimated connectors reference a water-profile row which
                # has no live earthwork asset. The owning water-profile source
                # is still explicit when the project has one hydraulic group.
                names[route] = main
        elif kind in {"missing_ip_connection", "native_transition_connection"} and main:
            names[route] = main
        names.setdefault(route, (route, str(network.get("name") or route)))
    if main:
        names.setdefault("water_profile", main)
    return names


def pending_connection_entries(source, displayed_routes, channel_name):
    for candidate in source.get("transition_candidates") or ():
        identifier = candidate.get("candidate_id")
        if not identifier or not connection_needs_settings(candidate):
            continue
        route_id = str(candidate.get("route_id") or "water_profile")
        route_group, route_name = displayed_routes.get(
            route_id, ("", candidate.get("route_name") or channel_name or "连接段"))
        name = candidate.get("name") or "连接段"
        span = _span(candidate, "K")
        detail = "；".join(candidate.get("reasons") or ["核对连接断面、尺寸与高程"])
        task = PreparationTask(route_id, identifier, name, route_name, span,
                               detail, "transition", "设置连接段")
        row = PreparationRow(route_id, identifier, route_name, name, "连接段", span, "pending", (),
                             issues=(task,), detail=detail, route_group=route_group,
                             start=candidate.get("station_start"))
        yield candidate, row


def preparation_snapshot(inputs, *, channel_name=""):
    """Summarize the ranges selected for a fresh run without modifying the project."""
    from 土石方计算.services.default_section_schemes import ensure_default_section_schemes, pending_default_section_assets

    source = restore_workbench_automatic_ranges(inputs)
    default_pending = {id(asset) for _, asset in pending_default_section_assets(source)}
    default_catalog = None
    displayed_routes = _display_routes(source, channel_name)
    groups = {}
    for network in source.get("networks", ()):
        for asset in network.get("assets", ()):
            groups.setdefault((route_identity(network), asset_root(asset)), []).append((network, asset))
    for asset in source.get("pits", ()):
        if not asset.get("generated_aqueduct_foundation"):
            groups.setdefault(("", asset_root(asset)), []).append((None, asset))

    rows = []
    live_ids = set()
    effective_bores = set()
    for (route_id, asset_id), members in groups.items():
        network, first = members[0]
        route_group, route_name = displayed_routes.get(route_id, ("", "独立建筑物"))
        prefix = (network or {}).get("station_prefix") or "K"
        method = trenchless_method(first)
        structure = method["method"] if method else building_structure(first)
        name = building_display_name(first, structure)
        parts, issues, annotations = [], [], []
        bounds = []
        bore_sections = []
        for owner, asset in members:
            identifier = str(asset.get("asset_id") or asset_id)
            live_ids.add((route_id, identifier))
            span = _span(asset, prefix) if owner is not None else "局部建筑物"
            gate = is_sluice_gate(asset)
            if gate:
                start, end = gate_station_range(asset)
                if start is not None and end is not None:
                    span = _span({"station_start": start, "station_end": end}, prefix)
                    bounds.append((start, end))
                elif asset.get("gate_station") is not None:
                    station = float(asset["gate_station"])
                    span = f"中心 {format_station(station, prefix)}"
                    bounds.append((station, station))
            if asset.get("station_start") is not None and asset.get("station_end") is not None:
                bounds.append((float(asset["station_start"]), float(asset["station_end"])))
            enabled = asset.get("enabled", True)
            # A previous run's object deferral is reevaluated with current inputs.
            # Preserve the calculator's route identity order for bore records.
            bore_route = trenchless_live_route_id(owner) if owner else None
            bore = trenchless_exclusion(asset, route_id=bore_route) if enabled else None
            scoped = gate or bore is not None or asset_requires_section_terrain({**asset, "calculation_deferred": None})
            if enabled and gate:
                missing = gate_missing_fields(asset, gate_reference_asset(source, owner, asset))
                names = "、".join(construction_field_label(field) for field in missing)
                part_issues = ((f"待补 {names}", "gate", "设置闸室结构", missing[0]),) if missing else ()
            elif bore:
                identity, part_issues, measured = _bore_identity_and_issues(bore)
                if identity is not None and owner is not None:
                    effective_bores.add(identity)
                if measured is not None:
                    if asset.get("calculation_deferred") or asset.get("pipe_profile_choice") == "pending_gap":
                        measured["editable"] = False
                    bore_sections.append((span, measured))
            elif enabled and scoped:
                part_issues, annotation = _preparation_part(owner, asset)
                if id(asset) in default_pending and any(issue[1] == "parameters" for issue in part_issues):
                    if default_catalog is None:
                        from 土石方计算.services.section_scheme_catalog import load_section_schemes
                        from 土石方计算.services.section_scheme_bindings import validate_section_scheme_bindings
                        default_catalog = load_section_schemes() if validate_section_scheme_bindings(source)["valid"] else []
                    if default_catalog:
                        # Only this unbound range needs a preview. Preparing the entire project
                        # for every row would repeatedly copy unrelated routes into the UI.
                        one_route = {"route_id": route_id, "assets": [asset]}
                        prepared, report = ensure_default_section_schemes({"networks": [one_route]}, default_catalog)
                        if report["applied_count"]:
                            adopted = prepared["networks"][0]["assets"][0]
                            part_issues, annotation = _preparation_part(owner, adopted)
                if annotation:
                    annotations.append(annotation)
            else:
                part_issues = ()
            status = ("pending" if part_issues else "ready") if enabled and scoped else "excluded"
            parts.append(PreparationPart(identifier, span, enabled, not asset.get("generated_aqueduct_foundation"),
                                         status, is_bore=bool(bore), requires_terrain=not gate))
            issues.extend(PreparationTask(route_id, identifier, name, route_name, span, *issue)
                          for issue in part_issues)

        flags = {part.status for part in parts}
        status = "pending" if "pending" in flags else "ready" if "ready" in flags else "excluded"
        span = parts[0].span
        if bounds and len(parts) > 1:
            span = _span({"station_start": min(start for start, _ in bounds),
                          "station_end": max(end for _, end in bounds)}, prefix)
        if method and status == "ready":
            detail = "非开挖圆孔单列"
        elif "excluded" in flags and len(flags) > 1:
            detail = "部分区段不计"
        elif status == "excluded":
            detail = "手动排除" if not any(part.enabled for part in parts) else "按现有计量范围排除"
        else:
            detail = "；".join(dict.fromkeys(annotations))
        rows.append(PreparationRow(route_id, asset_id, route_name, name, structure, span,
                                   status, tuple(parts), tuple(issues), detail, route_group,
                                   min((start for start, _ in bounds), default=None),
                                   is_bore=bool(method), bore_sections=tuple(bore_sections),
                                   flow_section=flow_section_label(first.get("flow_section"))))

    archived_rows = []
    # The calculator reads archived bores first, then replaces their matching
    # identities with live objects. Among archived copies the last one wins.
    for record in reversed(source.get("excluded", ())):
        route_id = str(record.get("route_id") or record.get("network_id") or "")
        identifier = str(record.get("asset_id") or record.get("source_identity") or "")
        if (route_id, identifier) in live_ids or not route_id and any(key[1] == identifier for key in live_ids):
            continue
        trenchless = is_trenchless_exclusion(record)
        measured = None
        part_issues = ()
        if trenchless:
            identity, part_issues, measured = _bore_identity_and_issues(record)
            if identity is not None:
                if identity in effective_bores:
                    continue
                effective_bores.add(identity)
        route_group, route_name = displayed_routes.get(route_id,
            (route_id, record.get("route_name") or route_id or "其他建筑物"))
        name = str(record.get("name") or record.get("construction_method") or "独立对象")
        span = _span(record, "K")
        issues = tuple(PreparationTask(route_id, identifier, name, route_name, span, *issue)
                       for issue in part_issues)
        status = ("pending" if issues else "ready") if trenchless else "excluded"
        detail = "非开挖圆孔单列" if trenchless else str(record.get("reason") or record.get("message") or "现行计量范围外")
        method = trenchless_method(record.get("original_asset_snapshot") or record) or trenchless_method(record)
        structure = method["method"] if method else str(record.get("construction_method") or "—")
        archived_rows.append(PreparationRow(route_id, identifier, route_name, name, structure,
                                            span, status, (), issues=issues, detail=detail,
                                            route_group=route_group, start=record.get("station_start"),
                                            is_bore=trenchless or bool(method),
                                            bore_sections=((span, measured),) if measured else ()))
    rows.extend(reversed(archived_rows))
    rows.extend(row for _, row in pending_connection_entries(source, displayed_routes, channel_name))
    group_order = {group: order for order, group in enumerate(dict.fromkeys(row.route_group for row in rows))}
    rows.sort(key=lambda row: (group_order[row.route_group], float(row.start) if row.start is not None else float("inf")))
    return PreparationSnapshot(tuple(rows), supports_partial_calculation(source))


_STYLES = """
QTreeWidget {background:#fff;border:1px solid #DAE4EE;border-radius:5px;alternate-background-color:#F3F7FB;color:#21384D;}
QTreeWidget::item {min-height:28px;}
QTreeWidget::item:selected {background:#DCEBFE;color:#183E69;}
QHeaderView::section {background:#EDF3F9;color:#47617A;border:0;border-right:1px solid #DAE4EE;padding:5px;}
"""


def _label(text, *, heading=False):
    label = QLabel(text)
    label.setTextFormat(Qt.PlainText)
    label.setWordWrap(True)
    label.setStyleSheet("color:#193A5D;font-size:19px;font-weight:600;" if heading else "color:#516981;")
    return label


def _tree(headers, name):
    widget = QTreeWidget()
    widget.setObjectName(name)
    widget.setHeaderLabels(headers)
    widget.setAlternatingRowColors(True)
    widget.setRootIsDecorated(False)
    widget.setUniformRowHeights(True)
    widget.header().setStretchLastSection(False)
    for column in range(len(headers)):
        widget.header().setSectionResizeMode(column, QHeaderView.Stretch if column == 0 else QHeaderView.ResizeToContents)
    return widget


class _WorkbenchObjectDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index: QModelIndex):
        super().initStyleOption(option, index)
        if index.parent().isValid():
            station = index.siblingAtColumn(2).data()
            status = index.siblingAtColumn(3).data()
            if status in {"待补", "本次不计"}:
                option.text += f"  ·  {status}"
            if station:
                option.text += "\u2028" + station

    def sizeHint(self, option, index: QModelIndex):
        size = super().sizeHint(option, index)
        double_line = index.parent().isValid() and index.siblingAtColumn(2).data()
        size.setHeight(max(size.height() + 6, 43 if double_line else 27))
        return size


class SectionPreparationMixin:
    """Widgets for project preparation, persistent object detail and measurement scope."""

    def _build_section_preparation(self, layout):
        self._section_open_request = None
        self._preparation_snapshot = None
        self._preparation_inputs = None
        self._preparation_channel_name = ""
        self._rendered_preparation = None
        self._rendered_pipe_groups = None
        self._rendered_draft_label = None
        self._scope_snapshot = None
        self._scope_has_draft = None
        self._preparation_items = {}
        self._preparation_pipe_special_items = {}
        self._preparation_pipe_profile_items = {}
        self._preparation_channel_profile_items = {}
        self.section_views = QStackedWidget()
        layout.addWidget(self.section_views, 1)

        separator = QWidget()
        separator.setFixedHeight(1)
        separator.setStyleSheet("background:#DDE3EB;")
        self.workbench_rail_layout.addWidget(separator)
        self.preparation_tree = _tree(("建筑物", "结构", "桩号范围", "状态"), "sectionPreparationObjects")
        self.preparation_tree.setAccessibleName("工程对象")
        self.preparation_tree.setHeaderHidden(True)
        self.preparation_tree.setRootIsDecorated(True)
        self.preparation_tree.setIndentation(10)
        self.preparation_tree.setUniformRowHeights(False)
        self.preparation_tree.setAlternatingRowColors(False)
        self.preparation_tree.setItemDelegate(_WorkbenchObjectDelegate(self.preparation_tree))
        self.preparation_tree.setStyleSheet("""
            QTreeWidget {background:transparent;border:0;font-size:12px;}
            QTreeWidget::item {padding-left:4px;}
            QTreeWidget::item:selected {background:#E9EEFF;color:#3346A2;}
        """)
        for column in (1, 2, 3):
            self.preparation_tree.setColumnHidden(column, True)
        self.preparation_tree.setWordWrap(True)
        self.preparation_tree.itemClicked.connect(self._preparation_object_clicked)
        self.preparation_tree.itemActivated.connect(self._preparation_object_clicked)
        self.workbench_rail_layout.addWidget(self.preparation_tree, 1)

    def _build_source_preparation(self, source):
        self.preparation_group = QGroupBox("算量准备")
        layout = QVBoxLayout(self.preparation_group)
        self.preparation_status = _label("")
        layout.addWidget(self.preparation_status)
        controls = QHBoxLayout()
        self.preparation_scope_button = QPushButton("计量范围")
        self.preparation_scope_button.setProperty("sourceAction", True)
        self.preparation_scope_button.clicked.connect(lambda: self._guard(self._open_section_scope))
        controls.addWidget(self.preparation_scope_button)
        self.preparation_transition_button = QPushButton("连接段设置")
        self.preparation_transition_button.setProperty("sourceAction", True)
        self.preparation_transition_button.clicked.connect(lambda: self._guard(
            lambda: self._run_workspace_action(self.open_transition_connections)))
        controls.addWidget(self.preparation_transition_button)
        controls.addStretch(1)
        layout.addLayout(controls)
        self.preparation_task_title = _label("待处理")
        layout.addWidget(self.preparation_task_title)
        self.preparation_tasks = _tree(("待办事项",), "sectionPreparationTasks")
        self.preparation_tasks.setAccessibleName("待处理")
        self.preparation_tasks.setHeaderHidden(True)
        self.preparation_tasks.setUniformRowHeights(False)
        self.preparation_tasks.setWordWrap(True)
        self.preparation_tasks.setStyleSheet("""
            QTreeWidget {background:transparent;border:0;}
            QTreeWidget::item {padding:5px 8px;border-bottom:1px solid #DDE3EB;}
            QTreeWidget::item:selected {background:#E9EEFF;color:#3346A2;}
        """)
        self.preparation_tasks.itemClicked.connect(self._preparation_task_clicked)
        self.preparation_tasks.itemActivated.connect(self._preparation_task_clicked)
        layout.addWidget(self.preparation_tasks)
        source.addWidget(self.preparation_group)

    def _build_section_scope(self):
        scope = self.section_scope = QWidget()
        scope.setObjectName("sectionScope")
        scope.setStyleSheet(_STYLES)
        layout = QVBoxLayout(scope)
        layout.setContentsMargins(8, 8, 8, 8)
        top = QHBoxLayout()
        top.addWidget(_label("计量范围", heading=True), 1)
        done = QPushButton("返回工程与地形")
        done.clicked.connect(self.show_project_and_terrain)
        top.addWidget(done)
        layout.addLayout(top)
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("结构"))
        self.preparation_scope_filter = QComboBox()
        self.preparation_scope_filter.currentIndexChanged.connect(self._render_preparation_scope)
        self.preparation_scope_display = ChoiceDisplay(self.preparation_scope_filter)
        filter_row.addWidget(self.preparation_scope_display)
        filter_row.addStretch(1)
        self.preparation_scope_draft = _label("草稿待应用 · 当前可查看计量范围")
        self.preparation_scope_draft.hide()
        filter_row.addWidget(self.preparation_scope_draft)
        self.preparation_scope_actions = {}
        for enabled in (True, False):
            button = self.preparation_scope_actions[enabled] = QPushButton()
            button.clicked.connect(lambda _checked=False, value=enabled: self._guard(
                lambda: self._change_preparation_scope(self._visible_scope_parts(), value)))
            filter_row.addWidget(button)
        layout.addLayout(filter_row)
        self.preparation_scope_tree = _tree(("线路 / 建筑物", "结构", "桩号范围", "计量范围"), "sectionPreparationScope")
        self.preparation_scope_tree.itemChanged.connect(self._preparation_scope_change)
        layout.addWidget(self.preparation_scope_tree, 1)
        self.section_views.addWidget(scope)

    def _build_section_object_summary(self):
        self.section_object_summary = QWidget()
        layout = QVBoxLayout(self.section_object_summary)
        layout.setContentsMargins(12, 9, 9, 6)
        layout.setSpacing(6)
        self.section_object_name = _label("", heading=True)
        self.section_object_name.setStyleSheet("font-size:20px;font-weight:600;color:#18212E;")
        self.section_object_span = _label("")
        self.section_object_span.setStyleSheet("color:#596578;")
        self.section_object_detail = _label("")
        self.section_bore_card = TrenchlessSectionCard()
        self.section_bore_card.save_requested.connect(lambda key, diameter, clearance: self._guard(
            lambda: self._apply_trenchless_section(key, diameter, clearance), notice="非开挖施工参数"))
        self.section_bore_card.draft_changed.connect(self._workspace_draft_changed)
        self.section_object_action = QPushButton()
        self.section_object_action.clicked.connect(lambda: self._guard(self._open_section_summary_source))
        header = QHBoxLayout()
        header.addWidget(self.section_object_name, 1)
        header.addWidget(self.section_object_action)
        layout.addLayout(header)
        layout.addWidget(self.section_object_span)
        layout.addWidget(self.section_object_detail)
        layout.addWidget(self.section_bore_card)
        layout.addStretch(1)
        self.section_views.addWidget(self.section_object_summary)

    def _open_section_summary_source(self):
        if task := self._section_object_task:
            self._open_section_task(task)

    def _show_section_object_summary(self, row):
        if not self._finish_pipe_navigation():
            return
        self._workbench_object = (row.route_id, row.asset_id)
        self._bind_section_object_summary(row)
        self._navigate_workflow(1, prepare=False)
        self.section_views.setCurrentWidget(self.section_object_summary)
        self._sync_workbench_navigation()

    def _bind_section_object_summary(self, row):
        self.section_object_name.setText(row.name)
        self.section_object_span.setText(row.span)
        self.section_object_detail.setText(row.detail or row.structure)
        self._section_object_task = row.issues[0] if row.issues and not row.is_bore else None
        self.section_object_detail.setVisible(not row.is_bore)
        self.section_bore_card.setVisible(row.is_bore)
        self.section_object_action.setVisible(self._section_object_task is not None)
        if self._section_object_task:
            self.section_object_action.setText(self._section_object_task.action_label)
        if row.is_bore:
            self.section_bore_card.set_section(row.bore_sections, excluded=row.status == "excluded")

    def _trenchless_draft_row(self, key):
        return next((row for row in self._section_preparation().rows
                     if sum(bore.get("editable", True) and trenchless_edit_key(bore) == key
                            for _, bore in row.bore_sections) == 1), None)

    def _pending_trenchless_edit(self):
        card = self.section_bore_card
        key = card.first_unapplied_edit()
        if key is not None and self._trenchless_draft_row(key) is None:
            keys = {trenchless_edit_key(bore) for row in self._section_preparation().rows
                    for _, bore in row.bore_sections}
            card.retain_drafts({item for item in keys if item is not None and self._trenchless_draft_row(item)})
            key = card.first_unapplied_edit()
        return key

    def _apply_trenchless_section(self, key, diameter, clearance):
        updated = update_trenchless_section(self._inputs, key,
            bore_diameter_override_m=diameter, radial_clearance_m=clearance)
        if updated is not self._inputs:
            self._inputs = updated
            self._invalidate()
            self._refresh_assets()
            self._rebase_auxiliary_draft()
        self.section_bore_card.accept_edit(key)

    def _section_preparation(self):
        channel_name = getattr(self, "_source_channel_name", "")
        if (self._preparation_snapshot is None or self._preparation_inputs is not self._inputs
                or self._preparation_channel_name != channel_name):
            self._preparation_snapshot = preparation_snapshot(self._inputs, channel_name=channel_name)
            self._preparation_inputs = self._inputs
            self._preparation_channel_name = channel_name
        return self._preparation_snapshot

    def _refresh_section_preparation(self, readiness=None):
        if not hasattr(self, "preparation_scope_tree"):
            return
        readiness = readiness or self._workbench_readiness()
        snapshot = readiness.snapshot
        has_connections = bool(self._inputs.get("transition_candidates"))
        self.preparation_transition_button.setVisible(has_connections)
        previous = self._rendered_preparation
        if (previous is None or snapshot is not previous.snapshot
                or self._rendered_pipe_groups is not self._pipe_construction_groups):
            self._render_preparation_objects(snapshot)
            if self.section_views.currentWidget() is self.section_object_summary:
                row = next((item for item in snapshot.rows
                            if (item.route_id, item.asset_id) == self._workbench_object), None)
                if row is not None and row.is_bore:
                    self._bind_section_object_summary(row)
        if readiness is not previous:
            self._refresh_preparation_object_descriptions(readiness)
        draft_label = self._workbench_draft_label() if readiness.has_draft else ""
        self.preparation_group.setVisible(bool(readiness.has_design or draft_label or has_connections))
        if readiness is not previous or draft_label != self._rendered_draft_label:
            self._render_source_preparation(readiness, draft_label)
        if self.section_views.currentWidget() is self.section_scope and (
                self._scope_snapshot is not snapshot or readiness.has_draft != self._scope_has_draft):
            self._render_preparation_scope()

    def _render_source_preparation(self, readiness, draft_label):
        snapshot = readiness.snapshot
        ready_label = "资料齐备" if readiness.has_draft else "本次可算"
        self.preparation_status.setText(
            f"{ready_label} {readiness.ready_count}   ·   待补 {readiness.pending_count}   ·   本次不计 {readiness.excluded_count}"
            if readiness.has_design else "尚未读取设计资料")
        self.preparation_scope_button.setEnabled(any(row.parts for row in snapshot.rows))
        tasks = self.preparation_tasks
        tasks.clear()
        self._rendered_preparation = readiness
        self._rendered_draft_label = draft_label
        has_tasks = bool(draft_label or snapshot.tasks)
        self.preparation_tasks.setVisible(has_tasks)
        self.preparation_task_title.setVisible(has_tasks)
        pending_connections = sum(task.action == "transition" for task in snapshot.tasks)
        self.preparation_transition_button.setText(
            f"连接段设置（{pending_connections}）" if pending_connections else "连接段设置")
        if draft_label:
            item = QTreeWidgetItem(tasks, [draft_label])
            item.setData(0, Qt.UserRole, "draft")
        for task in snapshot.tasks:
            item = QTreeWidgetItem(tasks, [f"{task.route_name} · {task.name} · {task.span}\n{task.message} · {task.action_label}"])
            item.setToolTip(0, item.text(0))
            item.setData(0, Qt.UserRole, task)
        task_height = sum(max(52, tasks.sizeHintForRow(row)) for row in range(tasks.topLevelItemCount()))
        tasks.setFixedHeight(min(task_height + 2, 250))

    def _refresh_preparation_object_descriptions(self, readiness):
        descriptions = {"ready": "可算", "partial": "部分区段可算", "pending": "待补资料", "excluded": "本次不计"}
        if readiness.has_draft:
            descriptions.update(ready="资料齐备，待处理草稿", partial="部分区段资料齐备，待处理草稿")
        for entry in readiness.rows:
            row = entry.row
            item = self._preparation_items.get((row.route_id, row.asset_id))
            if item is None:
                continue
            description = descriptions[entry.status]
            if entry.status != "excluded" and readiness.design_stale:
                description = "待更新水面线成果"
            elif entry.awaiting_terrain:
                description += "，待补地形"
            item.setData(0, Qt.AccessibleDescriptionRole, description)

    def _render_preparation_objects(self, snapshot):
        tree = self.preparation_tree
        self._rendered_pipe_groups = self._pipe_construction_groups
        scroll = tree.verticalScrollBar().value()
        collapsed = {item.data(0, Qt.UserRole + 1)
                     for row in range(tree.topLevelItemCount())
                     if not (item := tree.topLevelItem(row)).isExpanded()}
        expanded_parts = {key for key, item in self._preparation_items.items() if item.childCount() and item.isExpanded()}
        tree.clear()
        self._preparation_items = {}
        self._preparation_pipe_special_items = {}
        self._preparation_pipe_profile_items = {}
        self._preparation_channel_profile_items = {}
        parents = {}
        pipe_special_entries = {}
        names = {"ready": "可算", "pending": "待补", "excluded": "本次不计"}
        for row in snapshot.rows:
            key = row.route_group or row.route_name
            parent = parents.get(key)
            if parent is None:
                parent = QTreeWidgetItem(tree, [row.route_name])
                parent.setFirstColumnSpanned(True)
                parent.setFlags(parent.flags() & ~Qt.ItemIsSelectable)
                parent.setData(0, Qt.UserRole + 1, key)
                parent.setForeground(0, QBrush(QColor("#536478")))
                parents[key] = parent
                if channel := self._channel_profile_groups.get(key):
                    self._preparation_channel_profile_items[key] = self._pipe_scope_item(
                        parent, "设计纵断面", "", (channel.name, channel.span), _CHANNEL_PROFILE_SCOPE_ROLE, key)
            if source := self._pipe_source_entry(row.route_id, row.asset_id):
                scope = source[0]
                if scope not in self._preparation_pipe_profile_items:
                    title = "管线纵断面" if key in self._preparation_channel_profile_items else "设计纵断面"
                    self._preparation_pipe_profile_items[scope] = self._pipe_scope_item(
                        parent, title, row.structure, self._pipe_profile_labels(scope),
                        _PIPE_PROFILE_SCOPE_ROLE, scope)
            if pipe_entry := self._pipe_entry(row.route_id, row.asset_id):
                pipe_special_entries.setdefault(pipe_entry[0], (parent, row.structure))
            visible_status = row.detail if row.status == "ready" and row.detail else names[row.status]
            caption = " · ".join(filter(None, (row.name, row.flow_section)))
            item = QTreeWidgetItem(parent, [caption, row.structure, row.span, visible_status])
            item.setData(0, Qt.AccessibleTextRole, f"{caption} {row.span}")
            item.setData(0, Qt.AccessibleDescriptionRole, visible_status)
            item.setToolTip(0, f"{row.route_name} · {caption}\n{row.span}")
            if row.detail:
                item.setToolTip(3, row.detail)
            if row.asset_id:
                key = (row.route_id, row.asset_id)
                item.setData(0, Qt.UserRole, key)
                self._preparation_items[key] = item
                for part in row.parts:
                    part_key = row.route_id, part.asset_id
                    if part_key != key and self._is_exact_pipe_source_member(part_key):
                        child = QTreeWidgetItem(item, [part.span])
                        child.setData(0, Qt.UserRole, part_key)
                        child.setData(0, Qt.AccessibleTextRole, f"{row.name} {part.span}")
                        child.setToolTip(0, f"{row.name} · {part.span}")
                        self._preparation_items[part_key] = child
                    else:
                        self._preparation_items.setdefault(part_key, item)
                item.setExpanded(key in expanded_parts)
        for scope, (parent, structure) in pipe_special_entries.items():
            self._preparation_pipe_special_items[scope] = self._pipe_scope_item(
                parent, "特殊施工段", structure, self._pipe_special_labels(scope),
                _PIPE_SPECIAL_SCOPE_ROLE, scope)
        for key, parent in parents.items():
            parent.setExpanded(key not in collapsed)
        self._sync_workbench_navigation()
        tree.verticalScrollBar().setValue(scroll)

    @staticmethod
    def _pipe_scope_item(parent, title, structure, labels, role, scope):
        name, span = labels
        item = QTreeWidgetItem(parent, [title, structure, span])
        item.setData(0, role, scope)
        item.setData(0, Qt.AccessibleTextRole, f"{name} 全线{title} {span}")
        item.setToolTip(0, f"{name} · 全线{title}\n{span}")
        return item

    def _select_preparation_object(self, key, *, view=None):
        items = self._preparation_items
        if view is self.pipe_special_page:
            items = self._preparation_pipe_special_items
        elif view is self.pipe_profile_page:
            items = self._preparation_pipe_profile_items
        elif view is self.route_profile_page:
            items = self._preparation_channel_profile_items
        item = items.get(key)
        if item is not self.preparation_tree.currentItem():
            if item is not None:
                parent = item.parent()
                while parent is not None:
                    parent.setExpanded(True)
                    parent = parent.parent()
            self.preparation_tree.setCurrentItem(item)

    def _preparation_object_clicked(self, item, _column):
        if scope := item.data(0, _PIPE_SPECIAL_SCOPE_ROLE):
            QTimer.singleShot(0, self, lambda: self._guard(lambda: self._show_pipe_specials(*scope)))
        elif scope := item.data(0, _PIPE_PROFILE_SCOPE_ROLE):
            QTimer.singleShot(0, self, lambda: self._guard(lambda: self._show_pipe_source(*scope, exact=False)))
        elif scope := item.data(0, _CHANNEL_PROFILE_SCOPE_ROLE):
            QTimer.singleShot(0, self, lambda: self._guard(lambda: self._show_channel_profile(scope)))
        elif key := item.data(0, Qt.UserRole):
            QTimer.singleShot(0, self, lambda: self._guard(lambda: self._open_section_preparation_item(*key)))

    def _preparation_task_clicked(self, item, _column):
        task = item.data(0, Qt.UserRole)
        if task == "draft":
            self._queue_preparation_navigation(self._require_applied_workspace)
        elif isinstance(task, PreparationTask):
            self._queue_preparation_navigation(lambda: self._open_section_task(task))

    def _queue_preparation_navigation(self, callback):
        def open_after_item_signal():
            if self.workflow_stack.currentWidget() is self.source_page:
                self._guard(callback)
        QTimer.singleShot(0, self, open_after_item_signal)

    def _finish_pipe_navigation(self):
        if (self.workflow_stack.currentIndex() == 1 and self.section_views.currentWidget() is self.pipe_special_page
                and not self.pipe_segments.finish_inline_edit()):
            self._sync_workbench_navigation()
            return False
        return True

    def _open_section_scope(self):
        if not self._finish_pipe_navigation():
            return
        self._navigate_workflow(1, prepare=False)
        self.section_views.setCurrentWidget(self.section_scope)
        self._render_preparation_scope()

    def _scope_rows(self):
        selected = self.preparation_scope_filter.currentData()
        return tuple(row for row in self._section_preparation().rows
                     if row.parts and (selected is None or row.structure == selected))

    def _render_preparation_scope(self, *_):
        tree = self.preparation_scope_tree
        self._scope_snapshot = self._section_preparation()
        self._scope_has_draft = self._workspace_has_draft()
        self.preparation_scope_draft.setVisible(self._scope_has_draft)
        selected = (self.preparation_scope_filter.currentData()
                    if self.preparation_scope_filter.count() > 1 else None)
        structures = sorted({row.structure for row in self._scope_snapshot.rows if row.parts})
        with QSignalBlocker(self.preparation_scope_filter):
            self.preparation_scope_filter.clear()
            if len(structures) != 1:
                self.preparation_scope_filter.addItem("全部结构", None)
            for structure in structures:
                self.preparation_scope_filter.addItem(structure, structure)
            self.preparation_scope_filter.setCurrentIndex(max(0, self.preparation_scope_filter.findData(selected)))
        self.preparation_scope_display.refresh()
        scroll = tree.verticalScrollBar().value()
        visible_parts = [part for row in self._scope_rows() for part in row.parts if part.editable]
        for enabled, button in self.preparation_scope_actions.items():
            count = sum(part.enabled != enabled for part in visible_parts)
            button.setText(f"{'纳入' if enabled else '排除'}所列区段（{count}）")
            button.setEnabled(bool(count) and not self._scope_has_draft)
        with QSignalBlocker(tree):
            tree.clear()
            for row in self._scope_rows():
                for part in row.parts:
                    state = "已排除" if not part.enabled else "已勾选 · 当前不计" if part.status == "excluded" else "已纳入"
                    item = QTreeWidgetItem(tree, [f"{row.route_name} / {row.name}", row.structure, part.span, state])
                    if part.editable:
                        item.setCheckState(0, Qt.Checked if part.enabled else Qt.Unchecked)
                        if self._scope_has_draft:
                            item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
                        else:
                            item.setData(0, Qt.UserRole, (row.route_id, part.asset_id))
        tree.verticalScrollBar().setValue(scroll)

    def _visible_scope_parts(self):
        return {(row.route_id, part.asset_id) for row in self._scope_rows()
                for part in row.parts if part.editable}

    def _preparation_scope_change(self, item, _column):
        key = item.data(0, Qt.UserRole)
        if key:
            enabled = item.checkState(0) == Qt.Checked
            # The scope refresh replaces tree items. Defer until Qt finishes
            # dispatching the item's check-state change.
            QTimer.singleShot(0, self, lambda: self._guard(lambda: self._change_preparation_scope({key}, enabled)))

    def _change_preparation_scope(self, keys, enabled):
        if not self._require_applied_workspace():
            return
        # A deliberate selection edit uses the same pre-recalculation source
        # ranges as the scope page, including previously auto-skipped spans.
        source = restore_workbench_automatic_ranges(self._inputs)
        parts = [(route_identity(network), asset) for network in source.get("networks", ())
                 for asset in network.get("assets", ())]
        parts.extend(("", asset) for asset in source.get("pits", ()))
        selected = [asset for route, asset in parts
                    if (route, str(asset.get("asset_id"))) in keys and asset.get("enabled", True) != enabled]
        if not selected:
            return
        if source is not self._inputs:
            self._inputs = source
        self._apply_inclusion(selected, enabled)

    def _open_section_task(self, task):
        self._open_section_preparation_item(task.route_id, task.asset_id, action=task.action, field=task.field)
        if task.action in {"source", "bore_source"}:
            self.workflow_hint.setText(f"{task.route_name} · {task.name} · {task.span}：{task.message}。核对线路设计资料后重新读取工程成果。")
            self.workflow_hint.show()

    def _open_section_preparation_item(self, route_id, asset_id, *, action=None, field=None):
        if (row := self._gate_entry(route_id, asset_id)) is not None:
            self._show_gate_section(*row, field=field)
            return
        if action is None:
            row = next((row for row in self._section_preparation().rows if row.route_id == route_id
                        and (row.asset_id == asset_id or any(part.asset_id == asset_id for part in row.parts))), None)
            if row and not row.is_bore and row.issues and (row.issues[0].action == "transition"
                    or row.parts and all(part.span == "桩号待补" for part in row.parts)):
                action = row.issues[0].action
            if row and action is None and (not row.parts or row.is_bore):
                self._show_section_object_summary(row)
                return
        if action == "transition":
            self.open_transition_connections(candidate_id=asset_id)
            return
        if action == "profile":
            selection = route_id, asset_id
            if source := self._pipe_source_entry(*selection):
                exact = self._is_exact_pipe_source_member(selection) or source[2].get("pipe_profile_choice") == "pending_gap"
                self._show_pipe_source(*selection, exact=exact)
                return
        if action in {"source", "bore_source"}:
            if self._navigate_workflow(0, prepare=False):
                self._focus_design_source()
            return
        if action is not None and self._workspace_has_draft():
            self._require_applied_workspace()
            return
        entry = self._pipe_entry(route_id, asset_id)
        if entry and entry[2].get("kind") != "culvert" and action in {None, "parameters", "profile"}:
            if not self._show_pipe_segments(route_id, asset_id):
                return
            if action is None:
                return
            if action == "parameters" and field and self.pipe_general.focus_parameter(
                    field, station=entry[2].get("station_start")):
                return
            if self._select_pipe_table_row(profile_key(entry[1], entry[2])):
                if action == "profile":
                    self.import_profile()
                else:
                    self.edit_parameters()
            return
        if not self._finish_pipe_navigation():
            return
        self._section_open_request = (route_id, asset_id, action, field)
        self._workbench_object = (route_id, asset_id)
        self._show_section_detail()
        self._sync_workbench_navigation()
        self._ensure_section_workspace()

    def _show_section_detail(self):
        self._navigate_workflow(1, prepare=False)
        self.section_views.setCurrentWidget(self.section_scroll)

    def _apply_section_open_request(self, editor):
        if self._section_open_request is None:
            return
        route_id, asset_id, action, field = self._section_open_request
        self._section_open_request = None
        if not editor.select_asset(asset_id, route_id=route_id, drafts=self._section_drafts):
            self._workbench_object = (editor.selected_route_id(), editor.selected_asset_id())
            self._sync_workbench_navigation()
            if not editor.has_pending_draft():
                self._set_workspace_status("当前对象的设计区段待核对。")
            return
        self._set_workspace_status("")
        self._select_workspace_asset()
        if action is None:
            editor.open_inline_parameters()
        else:
            editor.set_inspection_mode(False)
        if action == "profile":
            self.other_profile_button.setFocus()
            self._run_workspace_action(self.import_profile, select_asset=True)
        elif action == "parameters" and not editor.focus_parameter(field):
            self._run_workspace_action(self.edit_parameters, select_asset=True)
