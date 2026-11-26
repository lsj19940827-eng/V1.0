"""Visible task navigation and the persistent section/construction workspace."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QButtonGroup, QComboBox,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
    QSizePolicy, QSplitter, QStackedWidget, QVBoxLayout, QWidget)

from app_渠系计算前端.task_feedback import TaskFeedbackWidget
from 土石方计算.services.batch_cover_profiles import is_pressure_cover_asset
from 土石方计算.services.sluice_gate import gate_reference_asset, is_sluice_gate

from .gate_section_page import GateSectionPage
from .section_preparation import SectionPreparationMixin, asset_root, building_display_name, route_identity
from .pipe_construction_flow import PipeConstructionFlowMixin
from .workbench_readiness import workbench_readiness


_SOURCE_ACTIONS = {"design", "terrain", "retry_terrain"}
_ACTION_LABELS = {
    "design": "读取设计资料",
    "terrain": "导入地形图",
    "retry_terrain": "恢复地形",
    "draft": "处理草稿",
    "task": "处理待办",
    "scope": "选择计量区段",
    "confirm": "确认算量范围",
}


def terrain_source_name(path):
    source = Path(path)
    stem = source.stem.lower()
    if len(stem) == 64 and all(char in "0123456789abcdef" for char in stem):
        suffix = source.suffix.lower()
        names = {".dwg": "地形图", ".dxf": "地形图", ".npz": "地形网格"}
        return "随工程保存的" + names.get(suffix, "地形资料")
    return source.name


def _terrain_file_available(path):
    try:
        return bool(path and Path(path).is_file())
    except OSError:
        return False


class _SectionWorkspaceContent(QWidget):
    def heightForWidth(self, width):
        # QScrollArea otherwise treats wrapped labels' preferred height as a
        # minimum and grows the whole editor beyond the viewport. Its middle
        # area already scrolls, so reserve only the actual minimum at this width.
        return max(self.minimumSizeHint().height(), self.layout().minimumHeightForWidth(width))


class WorkbenchWorkflowMixin(PipeConstructionFlowMixin, SectionPreparationMixin):
    def _build_workflow_header(self, root):
        self._section_workspace = None
        self._section_drafts = {}
        self._gate_objects = {}
        self._workspace_inputs = None
        self._workspace_source = None
        self._workspace_preview_basis = None
        self._applying_workspace = False
        self._pending_workspace_state = None
        self._workbench_object = None
        self._workbench_design_stale = False
        self._readiness_cache = None
        self.setStyleSheet(self.styleSheet() + """
            QWidget#sectionEarthworkWorkbench {background:#FFFFFF;}
            QPushButton[workspaceAction="true"] {
                padding:5px 10px;border:1px solid #DDE3EB;border-radius:5px;background:#FFFFFF;color:#243246;}
            QPushButton[workspaceAction="true"]:hover {background:#F7F8FB;}
            QPushButton[workspaceAction="true"]:disabled {color:#79879A;background:#F7F8FB;}
        """)
        heading = QHBoxLayout()
        title = QLabel("土石方算量")
        title.setStyleSheet("font-size:18px;font-weight:600")
        heading.addWidget(title)
        self.workbench_project_name = QLabel()
        self.workbench_project_name.setTextFormat(Qt.PlainText)
        self.workbench_project_name.setStyleSheet("color:#536478;padding-left:8px;")
        heading.addWidget(self.workbench_project_name)
        heading.addStretch()
        self.workbench_calculate = QPushButton()
        self.workbench_calculate.setObjectName("workbenchCalculate")
        self._style_step_button(self.workbench_calculate, "#3346A2", "#27377E")
        self.workbench_calculate.clicked.connect(lambda: self._guard(
            self._open_workbench_primary_action, notice="算量准备"))
        heading.addWidget(self.workbench_calculate)
        root.addLayout(heading)

        shell = QSplitter(Qt.Horizontal)
        shell.setObjectName("earthworkWorkspace")
        shell.setChildrenCollapsible(False)
        shell.setHandleWidth(3)
        root.addWidget(shell, 1)
        rail = self.workbench_rail = QWidget()
        rail.setObjectName("earthworkObjectRail")
        rail.setMinimumWidth(168)
        rail.setStyleSheet("""
            QWidget#earthworkObjectRail {background:#F7F8FB;border-right:1px solid #DDE3EB;}
            QWidget#earthworkObjectRail QPushButton[checkable="true"] {
                text-align:left;padding:7px 9px;border:0;border-radius:5px;background:transparent;}
            QWidget#earthworkObjectRail QPushButton:hover {background:#F0F2F7;}
            QWidget#earthworkObjectRail QPushButton:checked {background:#E9EEFF;color:#3346A2;font-weight:600;}
        """)
        self.workbench_rail_layout = QVBoxLayout(rail)
        self.workbench_rail_layout.setContentsMargins(8, 8, 8, 8)
        self.workbench_rail_layout.setSpacing(4)
        self.workflow_button_group = QButtonGroup(self)
        self.workflow_button_group.setExclusive(True)
        self.source_page_button = QPushButton("工程与地形")
        self.results_page_button = QPushButton("算量与成果")
        self.workflow_buttons = (self.source_page_button, self.results_page_button)
        for index, button, action in (
                (0, self.source_page_button, self.show_project_and_terrain),
                (2, self.results_page_button, self._show_workbench_results)):
            button.setProperty("checkable", True)
            button.setCheckable(True)
            button.setMinimumHeight(31)
            button.clicked.connect(lambda _checked=False, callback=action: self._guard(callback))
            self.workflow_button_group.addButton(button, index)
            self.workbench_rail_layout.addWidget(button)
        shell.addWidget(rail)
        main = QWidget()
        content = QVBoxLayout(main)
        content.setContentsMargins(8, 0, 0, 0)
        content.setSpacing(5)
        shell.addWidget(main)
        shell.setStretchFactor(0, 0)
        shell.setStretchFactor(1, 1)
        shell.setSizes([212, 950])
        # Older host integrations may still address the section-entry button.
        self.parameter_button = self.drawing_library_button = self.binding_button = self.source_page_button
        self.workflow_hint = QLabel()
        self.workflow_hint.setWordWrap(True)
        self.workflow_hint.setStyleSheet("color:#4D6178;padding:3px 0;")
        content.addWidget(self.workflow_hint)
        self.feedback = TaskFeedbackWidget(self)
        self.progress = self.feedback.bar
        content.addWidget(self.feedback)
        self.feedback.hide()
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._request_cancel)
        self.feedback.header_layout.addWidget(self.cancel_button)
        self.cancel_button.hide()
        self.workflow_stack = QStackedWidget()
        content.addWidget(self.workflow_stack, 1)

        # Each action stays with the source it changes.
        self.source_page = QWidget()
        self.source_page.setObjectName("workbenchSources")
        self.source_page.setStyleSheet("""
            QWidget#workbenchSourceContent {background:#FFFFFF;}
            QWidget#workbenchSources QGroupBox {
                border:1px solid #DDE3EB;border-radius:6px;margin-top:8px;background:#FFFFFF;}
            QWidget#workbenchSources QGroupBox::title {
                subcontrol-origin:margin;left:10px;padding:0 4px;background:#FFFFFF;color:#18212E;}
            QWidget#workbenchSources QPushButton[sourceAction="true"] {
                padding:6px 10px;border:1px solid #DDE3EB;border-radius:5px;background:#FFFFFF;color:#243246;}
            QWidget#workbenchSources QPushButton[sourceAction="true"]:hover {background:#F7F8FB;}
            QWidget#workbenchSources QPushButton[sourcePrimary="true"] {
                background:#3346A2;color:white;border-color:#3346A2;font-weight:600;}
            QWidget#workbenchSources QPushButton[sourcePrimary="true"]:hover {background:#27377E;}
            QWidget#workbenchSources QPushButton[sourceAction="true"]:disabled {
                color:#79879A;background:#F7F8FB;border-color:#DDE3EB;}
        """)
        source_outer = QHBoxLayout(self.source_page)
        source_outer.setContentsMargins(0, 0, 0, 0)
        source_scroll = self.source_scroll = QScrollArea()
        source_scroll.setWidgetResizable(True)
        source_scroll.setFrameShape(QScrollArea.NoFrame)
        source_scroll.setFixedWidth(340)
        source_outer.addWidget(source_scroll)
        source_content = QWidget()
        source_content.setObjectName("workbenchSourceContent")
        source_scroll.setWidget(source_content)
        source = QVBoxLayout(source_content)
        source.setContentsMargins(0, 4, 0, 4)
        self.source_guidance = QLabel()
        self.source_guidance.setWordWrap(True)
        self.source_guidance.setStyleSheet("color:#4D6178;padding:4px 2px;")
        source.addWidget(self.source_guidance)
        project_group = QGroupBox("设计资料")
        project = QVBoxLayout(project_group)
        self.design_stale_label = QLabel("水面线成果需更新")
        self.design_stale_label.setStyleSheet("color:#895514;")
        self.design_stale_label.hide()
        project.addWidget(self.design_stale_label)
        self.input_label = QLabel("尚未读取设计资料。")
        self.input_label.setTextFormat(Qt.PlainText)
        self.input_label.setWordWrap(True)
        project.addWidget(self.input_label)
        project_actions = QHBoxLayout()
        self.import_button = QPushButton("读取水面线成果")
        self.import_button.setProperty("sourceAction", True)
        self.import_button.setToolTip("带入当前工程中已计算的线路、桩号和设计断面。")
        self.import_button.clicked.connect(self._read_current_project_from_button)
        project_actions.addWidget(self.import_button)
        self.load_button = QPushButton("打开项目文件")
        self.load_button.setProperty("sourceAction", True)
        self.load_button.setToolTip("打开已保存的水面线或土石方算量项目。")
        self.load_button.clicked.connect(lambda: self._guard(lambda: self._run_workspace_action(self.choose_input)))
        project_actions.addWidget(self.load_button)
        project.addLayout(project_actions)
        source.addWidget(project_group)
        terrain_group = QGroupBox("计算地形")
        terrain = QVBoxLayout(terrain_group)
        self.terrain_path = QLineEdit()
        self.terrain_path.setReadOnly(True)
        self.terrain_path.setPlaceholderText("导入原始地形图，自动识别测点与等高线")
        self.terrain_path.setToolTip("支持DWG、DXF、测点表及已有地形网格")
        self.terrain_path.hide()
        self.terrain_source_label = QLabel("尚未导入地形")
        self.terrain_source_label.setTextFormat(Qt.PlainText)
        self.terrain_source_label.setWordWrap(True)
        terrain.addWidget(self.terrain_source_label)
        self.terrain_path.textChanged.connect(self._refresh_terrain_source_label)
        terrain_actions = QHBoxLayout()
        self.terrain_button = QPushButton("导入地形图")
        self.terrain_button.setProperty("sourceAction", True)
        self.terrain_button.setToolTip("支持地形图、测点表和已有地形网格。")
        self.terrain_button.clicked.connect(self.choose_terrain)
        terrain_actions.addWidget(self.terrain_button)
        self.terrain_recovery = QWidget()
        recovery_actions = QHBoxLayout(self.terrain_recovery)
        recovery_actions.setContentsMargins(0, 0, 0, 0)
        self.terrain_retry_button = QPushButton("重试地形")
        self.terrain_retry_button.setProperty("sourceAction", True)
        self.terrain_retry_button.clicked.connect(self._retry_pending_terrain)
        recovery_actions.addWidget(self.terrain_retry_button)
        self.keep_terrain_button = QPushButton("沿用当前地形")
        self.keep_terrain_button.setProperty("sourceAction", True)
        self.keep_terrain_button.clicked.connect(self._discard_pending_terrain)
        recovery_actions.addWidget(self.keep_terrain_button)
        recovery_actions.addStretch()
        self.terrain_recovery.hide()
        self.terrain_mode = QComboBox()
        self.terrain_mode.addItem("等高点+等高线（自动处理）", "combined")
        self.terrain_mode.hide()
        terrain_actions.addStretch()
        terrain.addLayout(terrain_actions)
        self.terrain_import_hint = QLabel()
        self.terrain_import_hint.setTextFormat(Qt.PlainText)
        self.terrain_import_hint.setWordWrap(True)
        self.terrain_import_hint.hide()
        terrain.addWidget(self.terrain_import_hint)
        terrain.addWidget(self.terrain_recovery)
        source.addWidget(terrain_group)
        profile_group = QGroupBox("天然地形纵断面")
        profile_actions = QVBoxLayout(profile_group)
        self.centerline_source_button = QPushButton("剖纵断面")
        self.centerline_source_button.setProperty("sourceAction", True)
        self.centerline_source_button.clicked.connect(lambda: self._guard(self.open_centerline_profile))
        profile_actions.addWidget(self.centerline_source_button, alignment=Qt.AlignLeft)
        source.addWidget(profile_group)
        self._build_source_preparation(source)
        source.addStretch()
        source_plan = QVBoxLayout()
        source_plan.setContentsMargins(6, 4, 0, 0)
        source_outer.addLayout(source_plan, 1)
        self.workflow_stack.addWidget(self.source_page)
        self._build_terrain_plan(source_plan)

        self.section_page = QWidget()
        section_outer = QVBoxLayout(self.section_page)
        section_outer.setContentsMargins(0, 0, 0, 0)
        self._build_section_preparation(section_outer)
        self.section_scroll = QScrollArea()
        self.section_scroll.setWidgetResizable(True)
        self.section_scroll.setFrameShape(QScrollArea.NoFrame)
        self.section_views.addWidget(self.section_scroll)
        section_content = _SectionWorkspaceContent()
        self.section_scroll.setWidget(section_content)
        section = QVBoxLayout(section_content)
        section.setContentsMargins(12, 9, 9, 6)
        section.setSpacing(6)
        context_actions = QHBoxLayout()
        heading = QVBoxLayout()
        heading.setSpacing(6)
        self.section_title = QLabel()
        self.section_title.setTextFormat(Qt.PlainText)
        self.section_title.setStyleSheet("font-size:20px;font-weight:600;color:#18212E")
        heading.addWidget(self.section_title)
        self.section_span = QLabel()
        self.section_span.setTextFormat(Qt.PlainText)
        self.section_span.setStyleSheet("color:#596578")
        heading.addWidget(self.section_span)
        context_actions.addLayout(heading)
        context_actions.addStretch(1)
        self.other_profile_button = QPushButton("编辑设计高程")
        self.other_profile_button.clicked.connect(lambda: self._guard(self._edit_control_elevations))
        context_actions.addWidget(self.other_profile_button)
        self.culvert_cover_button = QPushButton("预览覆土纵断面")
        self.culvert_cover_button.clicked.connect(lambda: self._guard(lambda: self._run_editor_tool(self.generate_cover)))
        context_actions.addWidget(self.culvert_cover_button)
        section.addLayout(context_actions)
        self.section_editor_layout = QVBoxLayout()
        self.section_editor_layout.setContentsMargins(0, 0, 0, 0)
        section.addLayout(self.section_editor_layout, 1)
        self.section_empty_label = QLabel("请选择工程对象")
        self.section_empty_label.setAlignment(Qt.AlignCenter)
        self.section_empty_label.setWordWrap(True)
        self.section_editor_layout.addWidget(self.section_empty_label)
        self.workspace_status = QLabel()
        self.workspace_status.setWordWrap(True)
        self.workspace_status.hide()
        section.addWidget(self.workspace_status)
        self._build_section_scope()
        self._build_pipe_construction()
        self._build_section_object_summary()
        self.gate_page = GateSectionPage(self.section_views)
        self.gate_page.draft_changed.connect(self._workspace_draft_changed)
        self.gate_page.applied.connect(self._apply_gate_section)
        self.section_views.addWidget(self.gate_page)
        self.workflow_stack.addWidget(self.section_page)
        self.section_views.currentChanged.connect(self._sync_workbench_navigation)

        self.workflow_stack.addWidget(self._build_results_page())
        self.source_page_button.setChecked(True)

    def show_project_and_terrain(self):
        return self._navigate_workflow(0, prepare=False)

    def _navigate_workflow(self, index, *, prepare=True):
        index = max(0, min(2, int(index)))
        if (index != 1 and self.workflow_stack.currentIndex() == 1
                and self.section_views.currentWidget() is self.pipe_special_page
                and not self.pipe_segments.finish_inline_edit()):
            self._sync_workbench_navigation()
            return False
        if self.workflow_stack.currentIndex() != index:
            self._clear_design_notice()
        if not self.runner.isRunning() and not self.feedback.active:
            self.feedback.hide()
        self.workflow_stack.setCurrentIndex(index)
        if (index == 1 and prepare and self.section_views.currentWidget() is self.section_scroll
                and self._workbench_object is not None and not self.runner.isRunning()):
            self._ensure_section_workspace()
        self._sync_workbench_navigation()
        self._refresh_workflow()
        return True

    def _sync_workbench_navigation(self, *_):
        page = self.workflow_stack.currentIndex()
        view = self.section_views.currentWidget()
        object_open = page == 1 and view in (
            self.section_scroll, self.pipe_page, self.pipe_special_page, self.pipe_profile_page,
            self.route_profile_page, self.section_object_summary, self.gate_page)
        self.workflow_button_group.setExclusive(False)
        for button in self.workflow_buttons:
            button.setChecked(page == self.workflow_button_group.id(button))
        self.workflow_button_group.setExclusive(True)
        key = self._workbench_object if object_open else None
        if key and view is self.pipe_profile_page:
            entry = self._pipe_source_entry(*key)
            key = entry[0] if entry else None
        elif page == 1 and view is self.route_profile_page:
            key = self._channel_profile_key
        self._select_preparation_object(key, view=view)

    def _gate_entry(self, route_id, asset_id):
        return self._gate_objects.get((route_id, asset_id))

    def _show_gate_section(self, owner, asset, *, field=None):
        if not self._finish_pipe_navigation():
            return
        key = route_identity(owner), str(asset["asset_id"])
        self._navigate_workflow(1, prepare=False)
        self._workbench_object = key
        self.gate_page.bind(key, owner, asset, gate_reference_asset(self._inputs, owner, asset))
        self.section_views.setCurrentWidget(self.gate_page)
        self._sync_workbench_navigation()
        if field in self.gate_page.edits:
            self.gate_page.edits[field].setFocus()

    def _apply_gate_section(self, key, candidate):
        entry = self._gate_entry(*key)
        if entry is None:
            return
        owner, asset = entry
        owner["assets"][owner["assets"].index(asset)] = candidate
        self.gate_page.accept(key)
        self._refresh_source_diagnostics()
        self._invalidate()
        self._refresh_assets()
        self._rebase_auxiliary_draft()
        self._log(f"{candidate['name']}的闸室结构设置已应用。")

    def _refresh_gate_context(self):
        entries = {(route_identity(owner), str(asset["asset_id"])): (owner, asset)
                   for owner in self._inputs.get("networks", ()) for asset in owner.get("assets", ())
                   if is_sluice_gate(asset)}
        self._gate_objects = entries
        self.gate_page.retain_drafts(entries)
        if self.section_views.currentWidget() is self.gate_page and self._workbench_object in entries:
            owner, asset = entries[self._workbench_object]
            self.gate_page.bind(self._workbench_object, owner, asset, gate_reference_asset(self._inputs, owner, asset))

    def _workbench_readiness(self):
        snapshot = self._section_preparation()
        path = self.terrain_path.text().strip()
        cache = self._terrain_identity.get("cache_path")
        cache_available = bool(self._terrain_identity.get("cache_sha256")) and _terrain_file_available(cache)
        had_terrain = bool(path or cache or self._pending_terrain_note)
        terrain_ready = not self._terrain_import_failed and (
            _terrain_file_available(path) or cache_available)
        flags = (terrain_ready, had_terrain and not terrain_ready,
                 self._workspace_has_draft(), self._workbench_design_stale and bool(self._source_hash))
        cached = self._readiness_cache
        if cached is None or cached[0] is not snapshot or cached[1] != flags:
            state = workbench_readiness(snapshot, terrain_ready=flags[0], terrain_failed=flags[1],
                                        has_draft=flags[2], design_stale=flags[3])
            self._readiness_cache = snapshot, flags, state
        return self._readiness_cache[2]

    @staticmethod
    def _workbench_action_text(readiness, action=None):
        action = action or ("confirm" if readiness.can_calculate else readiness.action)
        if action == "design" and readiness.design_stale:
            return "更新水面线成果"
        if action == "task" and readiness.priority_task:
            return readiness.priority_task.action_label
        return _ACTION_LABELS[action]

    def _refresh_workbench_primary_action(self, readiness, busy):
        action = "confirm" if readiness.can_calculate else readiness.action
        on_source = self.workflow_stack.currentWidget() is self.source_page
        on_results = self.workflow_stack.currentWidget() is self.results_page
        self.workbench_calculate.setText(self._workbench_action_text(readiness, action))
        self.workbench_calculate.setEnabled(not busy)
        self.workbench_calculate.setVisible(not on_results and not (on_source and action in _SOURCE_ACTIONS)
            and not (action == "scope" and self.section_views.currentWidget() is self.section_scope and not on_source))

    def _open_workbench_primary_action(self):
        return self._open_workbench_readiness_action()

    def _show_workbench_results(self):
        self._results_preparing = False
        return self._navigate_workflow(2)

    def _open_workbench_readiness_action(self, action=None):
        readiness = self._workbench_readiness()
        action = action or ("confirm" if readiness.can_calculate else readiness.action)
        if action in _SOURCE_ACTIONS:
            if not self._navigate_workflow(0):
                return False
            if action == "design":
                self._focus_design_source()
            else:
                target = self.terrain_retry_button if action == "retry_terrain" and self._pending_terrain_path else self.terrain_button
                self.source_scroll.ensureWidgetVisible(target)
                target.setFocus(Qt.OtherFocusReason)
            return True
        if action == "draft":
            return self._require_applied_workspace()
        if action == "task" and readiness.priority_task:
            self._open_section_task(readiness.priority_task)
            return True
        if action == "scope":
            return self._open_section_scope()
        if action == "confirm" and readiness.can_calculate:
            self._require_current_project_source()
            if self._navigate_workflow(2, prepare=False):
                self._show_calculation_confirmation()
                return True
        return False

    def _set_workspace_status(self, text):
        self.workspace_status.setText(text)
        self.workspace_status.setVisible(bool(text))

    def _focus_design_source(self):
        target = self.import_button if self.import_button.isEnabled() else self.load_button
        self.source_scroll.ensureWidgetVisible(target)
        target.setFocus(Qt.OtherFocusReason)

    def _refresh_source_actions(self, readiness):
        self.design_stale_label.setVisible(readiness.design_stale)
        can_read_current_design = self._project_provider is not None
        self.import_button.setEnabled(can_read_current_design)
        primary = None
        if readiness.action == "design":
            primary = self.import_button if can_read_current_design else self.load_button
            guidance = ("读取最新的水面线成果，更新线路和设计断面。" if readiness.design_stale else
                        "读取当前工程的水面线成果，或打开已保存的项目文件。" if can_read_current_design else
                        "打开已保存的水面线或土石方算量项目。")
        elif readiness.action == readiness.terrain_action:
            primary = (self.terrain_retry_button
                       if readiness.terrain_action == "retry_terrain" and self._pending_terrain_path
                       else self.terrain_button)
            guidance = "导入地形图后，即可核对计量范围。"
        elif readiness.can_calculate:
            guidance = "可从左侧选择建筑物查看施工断面，或直接确认算量范围。"
        else:
            guidance = "在「算量准备」中查看待办和计量范围。"
        self.source_guidance.setText(guidance)
        for button in (self.import_button, self.load_button, self.terrain_button, self.terrain_retry_button):
            active = button is primary
            if button.property("sourcePrimary") != active:
                button.setProperty("sourcePrimary", active)
                button.style().unpolish(button)
                button.style().polish(button)
                button.update()

    def _refresh_terrain_source_label(self):
        path = self.terrain_path.text().strip()
        pending = self._pending_terrain_path
        lines = []
        if path:
            caption = "当前地形：" if self._tin is not None else "工程地形："
            lines.append(caption + terrain_source_name(path))
        if pending:
            lines.append("待导入：" + terrain_source_name(pending))
        self.terrain_source_label.setText("\n".join(lines) or "尚未导入地形")
        self.terrain_source_label.setToolTip("\n".join(filter(None, (path, pending))))
        self.terrain_button.setText("更换地形图" if path else "导入地形图")
        self.terrain_retry_button.setText("重试地形" if self._pending_terrain_note else "导入所选地形")
        show_recovery = bool(pending) and not self.runner.isRunning()
        self.terrain_recovery.setVisible(show_recovery)
        self.terrain_retry_button.setVisible(show_recovery)
        self.keep_terrain_button.setVisible(bool(pending and path) and not self.runner.isRunning())
        if pending:
            hint = self._pending_terrain_note or "读取完成后采用所选地形。"
        elif self._terrain_map_note:
            hint = self._terrain_map_note
        elif self.map_terrain_runner.isRunning():
            hint = "正在恢复工程中保存的地形。"
        else:
            hint = ""
        self.terrain_import_hint.setText(hint)
        self.terrain_import_hint.setVisible(bool(hint))

    def _retry_pending_terrain(self):
        if self._pending_terrain_path:
            self._guard(lambda: self.load_terrain_path(self._pending_terrain_path))

    def _discard_pending_terrain(self):
        self._pending_terrain_path = ""
        self._pending_terrain_note = ""
        self.feedback.hide()
        self._refresh_workflow()

    def _show_records(self):
        self._navigate_workflow(2, prepare=False)
        self.records_toggle.setChecked(True)
        self.messages.ensureCursorVisible()

    def _workspace_has_draft(self):
        return bool((self._section_workspace is not None and self._section_workspace.has_pending_draft())
            or (self._pending_workspace_state or {}).get("editor", {}).get("pending_draft")
            or self._section_drafts
            or self.gate_page.first_draft()
            or self.pipe_general.first_unapplied_edit()
            or self._pending_pipe_profile()
            or self.pipe_segments.first_unapplied_edit()
            or self._pending_trenchless_edit())

    def _pending_profile_edit_target(self, profile):
        scope = self._pipe_source_entry(*profile)
        target = self.pipe_profile_editor.draft_location(profile)
        member = self._pipe_source_entry(*target)
        return (target if member and scope and member[0] == scope[0] else profile)

    def _workbench_draft_label(self):
        target = self.pipe_general.first_unapplied_edit()
        if not target and (profile := self._pending_pipe_profile()):
            profile_target = self._pending_profile_edit_target(profile)
            source = self._pipe_source_entry(*profile_target)
            if source:
                _, owner, asset = source
                target = route_identity(owner), asset["asset_id"]
        if not target:
            target = self.pipe_segments.first_unapplied_edit()
        if not target:
            target = self.gate_page.first_draft()
        if not target and (key := self._pending_trenchless_edit()) is not None:
            row = self._trenchless_draft_row(key)
            return f"草稿待应用 · {row.name} · {row.span}"
        if not target:
            editor = self._section_workspace
            if editor is not None and editor.has_pending_draft():
                target = editor.selected_route_id(), editor.selected_asset_id()
            else:
                restored = (self._pending_workspace_state or {}).get("editor", {})
                target = (restored.get("route_id"), restored.get("part_id") or restored.get("group_id"))
                if not target[1]:
                    target = next(iter(self._section_drafts), target)
        for row in self._section_preparation().rows:
            if row.route_id != target[0]:
                continue
            if row.asset_id == target[1]:
                return f"草稿待应用 · {row.name} · {row.span}"
            for part in row.parts:
                if part.asset_id == target[1]:
                    return f"草稿待应用 · {row.name} · {part.span}"
        return "草稿待应用"

    def _require_applied_workspace(self):
        if not self._workspace_has_draft():
            return True
        general = self.pipe_general.first_unapplied_edit(include_scope=True)
        if general and self._pipe_entry(*general[0]):
            self._open_pipe_general_draft(*general)
            return False
        profile = self._pending_pipe_profile()
        if profile and self._pipe_source_entry(*profile):
            self._show_pipe_source(*self._pending_profile_edit_target(profile),
                                   exact=self.pipe_profile_editor.draft_is_exact(profile))
            return False
        if not self._require_applied_special_segment():
            return False
        if (key := self.gate_page.first_draft()) and (entry := self._gate_entry(*key)):
            self._show_gate_section(*entry)
            return False
        if (key := self._pending_trenchless_edit()) is not None:
            self._show_section_object_summary(self._trenchless_draft_row(key))
            self.section_bore_card.select_edit(key)
            return False
        self._show_section_detail()
        if self._section_workspace is None:
            self._ensure_section_workspace()
        if self._section_workspace is not None:
            if not self._section_workspace.has_pending_draft() and self._section_drafts:
                route_id, asset_id = next(iter(self._section_drafts))
                self._open_section_preparation_item(route_id, asset_id)
            self._section_workspace.set_inspection_mode(False)
            self._workbench_object = (self._section_workspace.selected_route_id(), self._section_workspace.selected_asset_id())
            self._sync_workbench_navigation()
        message = "当前断面还有未应用修改。请先“应用到上述范围”或“放弃未应用修改”，再继续；输入已保留。"
        self._set_workspace_status(message)
        return False

    def _select_workspace_asset(self):
        if self._section_workspace is None:
            return False
        identity = self._section_workspace.selected_asset_id()
        route = self._section_workspace.selected_route_id()
        for row, (owner, asset) in enumerate(self._all_assets()):
            if asset.get("asset_id") == identity and route_identity(owner) == route:
                self.table.selectRow(row)
                return True
        return False

    def _run_workspace_action(self, callback, *, select_asset=False):
        if not self._require_applied_workspace():
            return
        if select_asset and not self._select_workspace_asset():
            return
        callback()
        if (self.workflow_stack.currentIndex() == 1 and self.section_views.currentWidget() is self.section_scroll
                and not self.runner.isRunning()):
            self._ensure_section_workspace()

    def _run_editor_tool(self, callback):
        if not self._select_workspace_asset():
            raise ValueError("请先选择要设置的工程对象。")
        callback()
        if (not self.runner.isRunning() and self.workflow_stack.currentIndex() == 1
                and self.section_views.currentWidget() is self.section_scroll):
            self._ensure_section_workspace()

    def _rebase_auxiliary_draft(self):
        """Keep typed edits on the current inputs after changing a source or template."""
        from .workbench_panel import serialize_inputs

        editor = self._section_workspace
        if editor is None or not editor.has_pending_draft():
            return
        current = serialize_inputs(self._inputs)
        if current == self._workspace_inputs:
            return
        self._workspace_source = None
        state = editor.export_workspace_state()
        def edited_spans(inputs):
            return [(asset.get("asset_id"),asset.get("station_start"),asset.get("station_end"))
                    for owner in inputs.get("networks",()) if route_identity(owner)==state["route_id"]
                    for asset in owner.get("assets",()) if asset_root(asset)==state["group_id"]]
        previous = edited_spans(self._workspace_inputs)
        if not previous or previous != edited_spans(current):
            return
        # Only replay values the user actually typed. The other fields should
        # take their values from the newly adopted template or design profile.
        dirty = {}
        for path, value in state["parameter_text"].items():
            baseline = state["parameter_baseline"].get(path)
            try:
                unchanged = float(value)==baseline if value.strip() else baseline is None
            except ValueError:
                unchanged = False
            if not unchanged:
                dirty[path] = value
        state["parameter_text"] = dirty
        state["parameter_baseline"] = {k:v for k,v in state["parameter_baseline"].items() if k in dirty}
        self._pending_workspace_state = {"basis":self._workspace_basis(current),"editor":state}
        self._dispose_section_workspace()
        if self.workflow_stack.currentIndex() == 1 and self.section_views.currentWidget() is self.section_scroll:
            QTimer.singleShot(0, self, lambda: self._ensure_section_workspace()
                              if self._section_workspace is None and not self._shutting_down else None)

    def _edit_control_elevations(self):
        if self._select_workspace_asset():
            self.import_profile()
            self._rebase_auxiliary_draft()
            self._ensure_section_workspace()

    def _workspace_preview_context(self, request, accuracy):
        from 土石方计算.services.workbench_calculator import query_workbench_section
        def preview(inputs, asset_id, station, side="right", token=None, route_id=None):
            if token is None:
                from types import SimpleNamespace
                token = SimpleNamespace(is_cancelled=False, raise_if_cancelled=lambda: None)
            tin = self._ensure_tin(token, request)
            token.raise_if_cancelled()
            identity = f"{route_id}::{asset_id}" if route_id else asset_id
            return query_workbench_section(tin, inputs, identity, station, side, accuracy)
        return preview

    def _workspace_source_is_current(self):
        return (self._workspace_source is not None and self._workspace_source[0] is self._inputs
                and self._workspace_source[1] == self._input_revision)

    def _ensure_section_workspace(self):
        from .workbench_panel import serialize_inputs
        if self._tin is None and self.terrain_path.text() and not getattr(self, "_terrain_import_failed", False):
            if not self.runner.isRunning():
                request = self._terrain_request()
                def loaded(tin):
                    if self.terrain_path.text() != request["path"]:
                        return
                    self._accept_tin(tin)
                    self._ensure_section_workspace()
                def failed(error):
                    self._terrain_import_failed = True
                    self._log("断面工作区地形读取失败：" + str(error))
                    self._set_workspace_status("地形读取失败，请在「工程与地形」重新导入。")
                    self._ensure_section_workspace()
                self._submit_task(lambda token: self._ensure_tin(token, request),
                    title="准备断面地形", message="正在读取地形，供断面预览和排架逐柱取高。",
                    on_success=loaded, on_error=failed, transient_success=True)
            return self._section_workspace
        editor = self._section_workspace
        # A source change still uses the full persisted snapshot, but navigating
        # between objects of the same project does not copy every route again.
        snapshot = self._workspace_inputs if self._workspace_source_is_current() else serialize_inputs(self._inputs)
        request, accuracy = self._terrain_request(), self._accuracy()
        preview_options = {key: value for key, value in request.items() if key not in {"tin", "terrain_progress"}}
        preview_basis = id(request["tin"]), preview_options, accuracy
        if editor is not None and snapshot == self._workspace_inputs:
            self._workspace_source = self._inputs, self._input_revision
            if preview_basis != self._workspace_preview_basis:
                editor.set_preview_context(self._workspace_preview_context(request, accuracy), request["tin"])
                self._workspace_preview_basis = preview_basis
            self._apply_section_open_request(editor)
            self._refresh_workspace_actions()
            return editor
        if editor is not None and editor.has_pending_draft():
            self._set_workspace_status("设计资料已更新。请先处理当前草稿。")
            return editor
        selected = editor.selected_asset_id() if editor else None
        route = editor.selected_route_id() if editor else None
        if not selected:
            try:
                owner, asset = self.selected_asset()
                selected = asset.get("asset_id")
                route = route_identity(owner)
            except ValueError:
                pass
        self._dispose_section_workspace()
        if not self._all_assets():
            self.section_empty_label.show()
            return None
        from .engineering_drawings_dialog import EngineeringDrawingsDialog
        inspection = self._section_open_request is not None and self._section_open_request[2] is None
        editor = EngineeringDrawingsDialog(self.section_page, inputs=self._inputs,
            preview_callback=self._workspace_preview_context(request, accuracy), terrain=request["tin"], embedded=True,
            prepare_defaults=not inspection)
        # The outer page must shrink to the viewport; the embedded editor owns
        # scrolling in its middle area and keeps range/adoption controls fixed.
        editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        self._section_workspace = editor
        self._workspace_inputs = snapshot
        self._workspace_source = self._inputs, self._input_revision
        self._workspace_preview_basis = preview_basis
        editor.use_workbench_navigation()
        self.section_empty_label.hide()
        self.section_editor_layout.addWidget(editor)
        editor.inputs_applied.connect(self._section_workspace_applied)
        editor.use_focused_pipe_editor = True
        editor.pipe_special_requested.connect(lambda r, a: self._guard(lambda: self._show_pipe_segments(r, a, add=True)))
        editor.draft_changed.connect(self._workspace_draft_changed)
        editor.asset_choice.currentIndexChanged.connect(self._refresh_workspace_actions)
        editor.station_edit.editingFinished.connect(self._refresh_workspace_actions)
        editor.ranges_table.cellClicked.connect(self._refresh_workspace_actions)
        editor.request_calculation.connect(lambda: self._navigate_workflow(2))
        editor.discard_draft_button.clicked.connect(self._discard_saved_workspace)
        restoring_draft = (self._pending_workspace_state or {}).get("editor", {}).get("pending_draft")
        if editor.default_report["changed"] and not restoring_draft:
            self._section_workspace_applied(editor.updated_inputs)
            snapshot = self._workspace_inputs
        if selected:
            editor.select_asset(selected, route_id=route)
        saved_state = self._pending_workspace_state
        restored = not saved_state
        if saved_state:
            saved_editor = saved_state.get("editor") or {}
            if saved_state.get("basis") == self._workspace_basis(snapshot):
                restored = editor.restore_workspace_state(saved_editor)
            if restored or not saved_editor.get("pending_draft"):
                self._pending_workspace_state = None
                restored = True
        editor.show()
        self._set_workspace_status("")
        if not restored:
            self._set_workspace_status("工程资料已更新。原草稿可随工程恢复，或点击「放弃未应用修改」。")
            editor.discard_draft_button.setEnabled(True)
        self._apply_section_open_request(editor)
        self._refresh_workspace_actions()
        return editor

    def _refresh_workspace_actions(self, *_):
        busy = self.runner.isRunning() or getattr(self, "_ui_busy", False)
        self.preparation_transition_button.setEnabled(not busy and bool(self._inputs.get("transition_candidates")))
        asset = owner = None
        if self._section_workspace is not None:
            identity = self._section_workspace.selected_asset_id()
            route = self._section_workspace.selected_route_id()
            owner, asset = next(((network, item) for network, item in self._all_assets()
                                if item.get("asset_id") == identity and route_identity(network) == route), (None, None))
        else:
            try:owner, asset = self.selected_asset()
            except ValueError:pass
        if self.section_views.currentWidget() is self.section_scroll:
            title = span = ""
            if asset:
                key = route_identity(owner), asset_root(asset)
                row = next((candidate for candidate in self._section_preparation().rows
                            if (candidate.route_id, candidate.asset_id) == key), None)
                title = row.name if row else building_display_name(asset)
                span = " · ".join(filter(None, (row.flow_section, row.span))) if row else ""
            self.section_title.setText(title)
            self.section_title.setVisible(bool(title))
            self.section_span.setText(span)
            self.section_span.setVisible(bool(span))
        editable = bool(asset and not self._deferred_asset(asset))
        other_profile = bool(editable and owner is not None and not is_pressure_cover_asset(asset)
                             and asset.get("station_start") is not None and asset.get("station_end") is not None)
        self.other_profile_button.setVisible(other_profile)
        self.other_profile_button.setEnabled(other_profile and not busy)
        culvert_cover = other_profile and asset.get("section_type") in {"circular_culvert", "circular_channel"}
        self.culvert_cover_button.setVisible(culvert_cover)
        self.culvert_cover_button.setEnabled(culvert_cover and not busy)

    def _workspace_draft_changed(self):
        self.data_changed.emit()
        self._refresh_workflow()

    def _discard_saved_workspace(self):
        self._pending_workspace_state = None
        self._ensure_section_workspace()

    def _section_workspace_applied(self, inputs):
        from 土石方计算.services.section_scheme_bindings import validate_section_scheme_bindings
        from .workbench_panel import serialize_inputs
        if self._workspace_inputs != serialize_inputs(self._inputs):
            self._workspace_source = None
            self._set_workspace_status("工程资料已更新。请重新载入断面后核对本次修改。")
            self._log("断面工作区资料已过期，已阻止旧草稿覆盖更新后的工程。")
            QTimer.singleShot(0, self._ensure_section_workspace)
            return
        candidate = copy.deepcopy(inputs)
        validate_section_scheme_bindings(candidate, raise_on_error=True)
        self._inputs = candidate
        self._refresh_source_diagnostics()
        self._workspace_inputs = serialize_inputs(self._inputs)
        self._invalidate()
        self._refresh_assets()
        self._select_workspace_asset()
        self._set_workspace_status("")
        self._log("断面与施工设置已应用；历史成果保留，重新算量采用当前设置。")

    def _dispose_section_workspace(self):
        editor = getattr(self, "_section_workspace", None)
        if editor is not None:
            editor.dispose_workspace()
            self.section_editor_layout.removeWidget(editor)
            editor.hide()
            editor.deleteLater()
        self._section_workspace = None
        self._workspace_inputs = None
        self._workspace_source = None
        self._workspace_preview_basis = None

    def _set_workflow_busy(self, busy):
        self.source_page.setEnabled(not busy)
        self.section_page.setEnabled(not busy)
        self.preparation_tree.setEnabled(not busy)
        for widget in (self.calculate_button, self.sampling_controls, self.query_button,
                       self.output_directory, self.output_directory_button, self.auto_delivery,
                       self.drawing_settings_button):
            widget.setEnabled(not busy)
        if not busy and self._section_workspace is not None and not self._shutting_down:
            # Profile import/cover generation may finish after the toolbar callback.
            from .workbench_panel import serialize_inputs
            if self._workspace_inputs != serialize_inputs(self._inputs):
                self._workspace_source = None
                QTimer.singleShot(0, lambda: self._guard(self._ensure_section_workspace)
                    if not self._shutting_down else None)

    @staticmethod
    def _workspace_basis(snapshot):
        return hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False,
            separators=(",", ":"), default=str).encode("utf8")).hexdigest()

    def _saved_workspace_state(self):
        if self._pending_workspace_state is not None:
            return copy.deepcopy(self._pending_workspace_state)
        if self._section_workspace is None:
            return None
        return {"basis": self._workspace_basis(self._workspace_inputs),
                "editor": self._section_workspace.export_workspace_state()}

    def _restore_section_drafts(self, drafts):
        live = {(route_identity(owner), asset_root(asset)) for owner, asset in self._all_assets()}
        for state in drafts:
            if not isinstance(state, dict) or not state.get("pending_draft"):
                continue
            route, group = state.get("route_id"), state.get("group_id")
            if isinstance(route, str) and isinstance(group, str) and (route, group) in live:
                self._section_drafts[route, group] = copy.deepcopy(state)

    def _restore_workflow_editor(self, state):
        if self.workflow_stack.currentIndex() != 1:
            return
        view = state.get("workbench_view")
        if view == "scope":
            self._open_section_scope()
            return
        if view == "route_profile":
            group = state.get("route_profile_group")
            if isinstance(group, str) and group in self._channel_profile_groups:
                self._show_channel_profile(group)
            else:
                self.show_project_and_terrain()
            return
        key = state.get("workbench_object") or state.get("pipe_construction_object")
        if view == "overview" or not isinstance(key, (tuple, list)) or len(key) != 2:
            self.show_project_and_terrain()
            return
        if view == "profile" and self._pipe_source_entry(*key):
            self._show_pipe_source(*key, exact=bool(state.get("pipe_exact_profile")))
        elif pipe_entry := self._pipe_entry(*key):
            if view == "pipe_specials" or (view in {None, "section"} and self._restored_pipe_special_draft(
                    state, pipe_entry[0])):
                self._show_pipe_specials(*key)
            elif view == "pipe_section":
                self._show_pipe_segments(*key)
            else:
                self._open_section_preparation_item(*key)
        else:
            self._open_section_preparation_item(*key)

    def _restored_pipe_special_draft(self, state, key):
        members = set(self._pipe_member_ids(key))
        return any((draft.get("route_id"), draft.get("asset_id")) in members
                   for draft in state.get("pipe_special_drafts") or () if isinstance(draft, dict))

    def _saved_workbench_view(self):
        if self.workflow_stack.currentWidget() is not self.section_page:
            return None
        if self.section_views.currentWidget() is self.pipe_page:
            return "pipe_section"
        if self.section_views.currentWidget() is self.pipe_profile_page:
            return "profile"
        if self.section_views.currentWidget() is self.route_profile_page:
            return "route_profile"
        if self.section_views.currentWidget() is self.pipe_special_page:
            return "pipe_specials"
        if self.section_views.currentWidget() is self.section_object_summary:
            return "object"
        if self.section_views.currentWidget() is self.gate_page:
            return "gate"
        return "scope" if self.section_views.currentWidget() is self.section_scope else "section"
