"""Pipe sources and per-building construction settings in the earthwork workbench."""
from __future__ import annotations

from copy import deepcopy
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

from 土石方计算.services.section_scheme_bindings import format_station
from 土石方计算.services.workbench_automatic_ranges import restore_workbench_automatic_ranges

from .section_preparation import _display_routes, asset_root, building_display_name, flow_section_label, route_identity
from .pipe_construction_objects import construction_objects, profile_source_groups, source_scope_asset, source_scope_key
from .pipe_profile_mapping import profile_key, profile_objects


class PipeConstructionFlowMixin:
    def _build_pipe_construction(self):
        from .pipe_general_section import PipeGeneralSectionWidget
        from .pipe_profile_sources import PipeProfileSourcesWidget
        from .pipe_special_segments import PipeSpecialSegmentsWidget
        from .route_design_profile import RouteDesignProfilePage

        self._pipe_rows = {}
        self._channel_profile_groups = {}
        self._channel_profile_key = None
        self._pipe_key = None
        self._pipe_profile_member = None
        self._pipe_exact_profile = False
        self._pipe_inputs = {}
        self._pipe_source_index = {}
        self._pipe_construction_groups = {}
        self._pipe_construction_index = {}
        self._pipe_general_context = None
        self._pipe_special_key = None
        self._pipe_special_context = None
        self.pipe_page = QWidget()
        self.pipe_page.setObjectName("pipeConstructionPage")
        workspace = QVBoxLayout(self.pipe_page)
        workspace.setContentsMargins(12, 9, 9, 6)
        workspace.setSpacing(6)
        self.pipe_title = QLabel()
        self.pipe_title.setTextFormat(Qt.PlainText)
        self.pipe_title.setStyleSheet("font-size:20px;font-weight:600;color:#18212E")
        workspace.addWidget(self.pipe_title)
        self.pipe_span = QLabel()
        self.pipe_span.setTextFormat(Qt.PlainText)
        self.pipe_span.setStyleSheet("color:#596578")
        workspace.addWidget(self.pipe_span)
        self.pipe_segments = PipeSpecialSegmentsWidget(before_commit=self._pipe_special_edit_ready)
        self.pipe_general = PipeGeneralSectionWidget()
        self.pipe_general.inputs_applied.connect(self._apply_pipe_changes)
        self.pipe_general.draft_changed.connect(self._workspace_draft_changed)
        self.pipe_general.conflicting_draft_requested.connect(
            lambda scope: self._guard(lambda: self._open_pipe_general_draft(*scope)))
        self.pipe_general_scroll = QScrollArea()
        self.pipe_general_scroll.setFrameShape(QScrollArea.NoFrame)
        self.pipe_general_scroll.setWidgetResizable(True)
        self.pipe_general_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.pipe_general_scroll.setWidget(self.pipe_general)
        workspace.addWidget(self.pipe_general_scroll, 1)

        self.pipe_special_page = QWidget()
        self.pipe_special_page.setObjectName("pipeSpecialWorkspace")
        special_workspace = QVBoxLayout(self.pipe_special_page)
        special_workspace.setContentsMargins(12, 9, 9, 6)
        special_workspace.setSpacing(6)
        self.pipe_special_title = QLabel()
        self.pipe_special_title.setTextFormat(Qt.PlainText)
        self.pipe_special_title.setStyleSheet("font-size:20px;font-weight:600;color:#18212E")
        special_workspace.addWidget(self.pipe_special_title)
        self.pipe_special_span = QLabel()
        self.pipe_special_span.setTextFormat(Qt.PlainText)
        self.pipe_special_span.setStyleSheet("color:#596578")
        special_workspace.addWidget(self.pipe_special_span)
        self.pipe_segments.inputs_applied.connect(self._apply_pipe_changes)
        self.pipe_segments.draft_changed.connect(self._workspace_draft_changed)
        self.pipe_segments.source_requested.connect(lambda r, a: self._guard(lambda: self._show_pipe_source(r, a, exact=False)))
        special_workspace.addWidget(self.pipe_segments, 1)
        self.pipe_profile_page = QWidget()
        self.pipe_profile_page.setObjectName("pipeProfileWorkspace")
        profile_workspace = QVBoxLayout(self.pipe_profile_page)
        profile_workspace.setContentsMargins(12, 9, 9, 6)
        profile_workspace.setSpacing(6)
        self.pipe_profile_title = QLabel()
        self.pipe_profile_title.setTextFormat(Qt.PlainText)
        self.pipe_profile_title.setStyleSheet("font-size:20px;font-weight:600;color:#18212E")
        profile_workspace.addWidget(self.pipe_profile_title)
        self.pipe_profile_editor = PipeProfileSourcesWidget()
        self.pipe_profile_editor.inputs_applied.connect(lambda inputs, key: self._guard(
            lambda: self._on_pipe_profile_applied(inputs, key), notice="设计纵断面"))
        self.pipe_profile_editor.cover_preview_requested.connect(self._on_pipe_cover_preview_requested)
        self.pipe_profile_editor.cover_generation_requested.connect(lambda key: self._guard(
            lambda: self._prepare_object_cover(key, exact=self._pipe_exact_profile), notice="覆土纵断面"))
        self.pipe_profile_editor.draft_changed.connect(self._workspace_draft_changed)
        profile_workspace.addWidget(self.pipe_profile_editor, 1)
        self.section_views.addWidget(self.pipe_page)
        self.section_views.addWidget(self.pipe_special_page)
        self.section_views.addWidget(self.pipe_profile_page)
        self.route_profile_page = RouteDesignProfilePage()
        self.section_views.addWidget(self.route_profile_page)

    def _refresh_pipe_objects(self):
        from .route_design_profile import channel_profile_groups

        inputs = restore_workbench_automatic_ranges(self._inputs)
        self._pipe_inputs = inputs
        self._pipe_general_context = None
        self._pipe_special_context = None
        self.pipe_segments.invalidate_material_groups()
        self._pipe_rows = profile_source_groups(inputs)
        self._channel_profile_groups = channel_profile_groups(inputs, _display_routes(inputs, self._source_channel_name))
        self._pipe_source_index = {}
        for scope, members in self._pipe_rows.items():
            for owner, asset in members:
                profile_route, asset_id = profile_key(owner, asset)
                for route in (route_identity(owner), profile_route):
                    for identifier in (asset_id, asset_root(asset)):
                        self._pipe_source_index.setdefault((route, identifier), (scope, owner, asset))
        self._pipe_construction_groups = construction_objects(inputs)
        member_sets = [self._pipe_member_ids(key) for key in self._pipe_construction_groups]
        member_sets += [(member,) for group in member_sets for member in group]
        self.pipe_general.set_live_inputs(inputs, member_sets=member_sets)
        self._pipe_construction_index = {}
        for identity, parts in self._pipe_construction_groups.items():
            for owner, asset in parts:
                route_id = route_identity(owner)
                member = (identity, owner, asset)
                self._pipe_construction_index[(route_id, asset["asset_id"])] = member
                self._pipe_construction_index[profile_key(owner, asset)] = member
                self._pipe_construction_index.setdefault((route_id, asset_root(asset)), member)
        page = self.section_views.currentWidget()
        if page is self.pipe_special_page:
            if self._pipe_special_key and (entry := self._pipe_entry(*self._pipe_special_key)):
                self._bind_pipe_specials(inputs, entry[0])
                return
            self._pipe_special_key = None
        elif page is self.pipe_profile_page:
            if self._pipe_profile_member and (source := self._pipe_source_entry(*self._pipe_profile_member)):
                self._bind_pipe_profile(inputs, source, exact=self._pipe_exact_profile)
                return
            self._pipe_profile_member = None
        elif page is self.route_profile_page:
            if scope := self._channel_profile_groups.get(self._channel_profile_key):
                self.route_profile_page.set_context(scope, terrain=self._tin)
                return
            self._channel_profile_key = None
        elif page is self.pipe_page:
            selection = self._workbench_object or self._pipe_key
            if selection and (entry := self._pipe_entry(*selection)):
                self._bind_pipe_section(inputs, selection, entry)
                return
        else:
            return
        self.section_views.setCurrentWidget(self.section_scroll)
        self._workbench_object = None
        if self.workflow_stack.currentWidget() is self.section_page:
            self.show_project_and_terrain()

    def _pipe_entry(self, route_id, identifier):
        return self._pipe_construction_index.get((route_id, identifier))

    def _pipe_source_entry(self, route_id, identifier):
        return self._pipe_source_index.get((route_id, identifier))

    def _pending_pipe_profile(self):
        return self.pipe_profile_editor.first_unapplied_edit(self._pipe_inputs)

    def _is_exact_pipe_source_member(self, selection):
        entry = self._pipe_source_entry(*selection)
        if not entry:
            return False
        _, _, asset = entry
        return selection[1] == asset["asset_id"] and bool(asset.get("parent_asset_id"))

    def _show_pipe_segments(self, route_id, identifier, *, add=False):
        if add:
            return self._show_pipe_specials(route_id, identifier, add=True)
        selection = route_id, identifier
        entry = self._pipe_entry(*selection)
        if not entry:
            raise ValueError("请从工程对象列表选择有压管道、圆管涵或倒虹吸。")
        if not self._finish_pipe_navigation():
            return False
        self._navigate_workflow(1, prepare=False)
        self._bind_pipe_section(self._pipe_inputs, selection, entry)
        self.section_views.setCurrentWidget(self.pipe_page)
        self._sync_workbench_navigation()
        return True

    def _pipe_special_labels(self, key):
        return self._pipe_scope_labels(self._pipe_construction_groups[key])

    def _pipe_profile_labels(self, key):
        return self._pipe_scope_labels(self._pipe_rows[key])

    @staticmethod
    def _pipe_scope_labels(members):
        owner = members[0][0]
        asset = source_scope_asset(members)
        start, end = asset["station_start"], asset["station_end"]
        prefix = owner.get("station_prefix") or "K"
        span = (f"{format_station(start, prefix)} ～ {format_station(end, prefix)}"
                if start is not None and end is not None else "")
        return building_display_name(asset), span

    def _show_pipe_specials(self, route_id, identifier, *, add=False):
        entry = self._pipe_entry(route_id, identifier)
        if not entry:
            raise ValueError("请从工程对象列表选择管线的特殊施工段。")
        key, owner, asset = entry
        if not self._finish_pipe_navigation():
            return False
        self._navigate_workflow(1, prepare=False)
        self._bind_pipe_specials(self._pipe_inputs, key)
        self._select_pipe_table_row(profile_key(owner, asset))
        self.section_views.setCurrentWidget(self.pipe_special_page)
        self._sync_workbench_navigation()
        if add:
            self.pipe_segments.open_add()
        return True

    def _bind_pipe_specials(self, inputs, key):
        self._pipe_special_key = self._workbench_object = key
        name, span = self._pipe_special_labels(key)
        self.pipe_special_title.setText(name)
        self.pipe_special_span.setText(span)
        self.pipe_special_span.setVisible(bool(span))
        if self._pipe_special_context != key and self.pipe_segments.set_context(
                inputs, *key, member_identities=self._pipe_member_ids(key), route_level=True):
            self._pipe_special_context = key

    def _bind_pipe_section(self, inputs, selection, entry):
        self._pipe_key, owner, asset = entry
        member = route_identity(owner), asset_root(asset)
        preferred = selection[1] if selection[1] != member[1] else None
        self._workbench_object = (member[0], asset["asset_id"]) if preferred else member
        self._select_pipe_table_row(profile_key(owner, asset))
        self.pipe_title.setText(building_display_name(asset))
        start, end = asset.get("station_start"), asset.get("station_end")
        prefix = owner.get("station_prefix") or "K"
        span = (" ～ ".join(format_station(value, prefix) for value in (start, end))
                if start is not None and end is not None else "")
        flow = flow_section_label(asset.get("flow_section")) if asset.get("kind") == "siphon" else ""
        self.pipe_span.setText(" · ".join(filter(None, (flow, span))))
        self.pipe_span.setVisible(bool(self.pipe_span.text()))
        self._set_pipe_general_context(inputs, (member,), preferred)

    def _bind_pipe_profile(self, inputs, source, *, exact):
        scope, owner, asset = source
        self._pipe_profile_member = self._workbench_object = profile_key(owner, asset) if exact else scope
        self._pipe_exact_profile = exact
        name, _ = self._pipe_profile_labels(scope)
        self.pipe_profile_title.setText(f"{name} · 设计纵断面")
        self.pipe_profile_editor.set_context(
            inputs, selected=self._pipe_profile_member, terrain=self._tin, exact=exact)

    def _refresh_visible_design_profile(self):
        if self.workflow_stack.currentIndex() != 1:
            return
        page = self.section_views.currentWidget()
        if (page is self.pipe_profile_page and self._pipe_profile_member
                and (source := self._pipe_source_entry(*self._pipe_profile_member))):
            self._bind_pipe_profile(self._pipe_inputs, source, exact=self._pipe_exact_profile)
        elif page is self.route_profile_page and (scope := self._channel_profile_groups.get(self._channel_profile_key)):
            self.route_profile_page.set_context(scope, terrain=self._tin)

    def _pipe_member_ids(self, key):
        return tuple(dict.fromkeys((route_identity(owner), asset_root(asset))
                                   for owner, asset in self._pipe_construction_groups[key]))

    def _set_pipe_general_context(self, inputs, members, preferred_asset_id=None):
        context = members, preferred_asset_id
        if self._pipe_general_context == context:
            return
        self.pipe_general.set_context(inputs, members, preferred_asset_id=preferred_asset_id)
        self._pipe_general_context = context

    def _open_pipe_general_draft(self, member, scopes):
        if not self._show_pipe_segments(*member):
            return False
        self._set_pipe_general_context(self._pipe_inputs, scopes)
        self.pipe_general.error.setText("请保存或取消当前一般段参数后继续。")
        self.pipe_general.error.show()
        self.pipe_general_scroll.ensureWidgetVisible(self.pipe_general.error)
        return True

    def _pipe_special_edit_ready(self):
        members = self._pipe_member_ids(self._pipe_special_key)
        pending = self.pipe_general.first_unapplied_edit(include_scope=True, member_scope=members)
        if pending is None:
            return True
        self._open_pipe_general_draft(*pending)
        return False

    def _require_applied_special_segment(self):
        if not self.pipe_segments.finish_inline_edit():
            if self._pipe_special_key:
                self._show_pipe_specials(*self._pipe_special_key)
            return False
        pending = self.pipe_segments.first_unapplied_edit()
        if pending and self._pipe_entry(*pending):
            self._show_pipe_specials(*pending)
            self.pipe_segments.error.setText("请保存本段，或取消这次编辑后继续算量。")
            self.pipe_segments.error.show()
            self.pipe_segments.scroll.ensureWidgetVisible(self.pipe_segments.error)
            return False
        return True

    def _show_pipe_source(self, route_id, identifier, *, exact=None):
        source = self._pipe_source_entry(route_id, identifier)
        if not source:
            raise ValueError("当前管线的来源区段已变化，请重新选择对象。")
        if exact is None:
            exact = self._is_exact_pipe_source_member((route_id, identifier))
        if not self._finish_pipe_navigation():
            return False
        self._navigate_workflow(1, prepare=False)
        self._bind_pipe_profile(self._pipe_inputs, source, exact=exact)
        self._select_pipe_table_row(self._pipe_profile_member)
        self.section_views.setCurrentWidget(self.pipe_profile_page)
        self._sync_workbench_navigation()
        if not self._restoring and not self.runner.isRunning():
            self._restore_map_tin()
        self.pipe_profile_editor.source.setFocus(Qt.OtherFocusReason)
        return True

    def _show_channel_profile(self, key):
        scope = self._channel_profile_groups.get(key)
        if scope is None:
            raise ValueError("当前线路已变化，请重新选择设计纵断面。")
        if not self._finish_pipe_navigation():
            return False
        self._navigate_workflow(1, prepare=False)
        self._channel_profile_key = key
        self._workbench_object = None
        self.route_profile_page.set_context(scope, terrain=self._tin)
        self.section_views.setCurrentWidget(self.route_profile_page)
        self._sync_workbench_navigation()
        if not self._restoring and not self.runner.isRunning():
            self._restore_map_tin()
        return True

    def _select_pipe_table_row(self, key):
        for row, (network, asset) in enumerate(self._all_assets()):
            if network and profile_key(network, asset) == tuple(key):
                self.table.selectRow(row)
                return True
        return False

    def _on_pipe_profile_applied(self, inputs, selected):
        editing = self.section_views.currentWidget() is self.pipe_profile_page
        exact = self._pipe_exact_profile
        self._apply_pipe_changes(inputs)
        if selected:
            if (editing and self.section_views.currentWidget() is not self.pipe_profile_page
                    and self._pipe_source_entry(*selected)):
                self._show_pipe_source(*selected, exact=exact)
            self._select_pipe_table_row(selected)
            self._prepare_object_cover(selected, exact=exact)

    def _on_pipe_cover_preview_requested(self, inputs, key, candidate, candidates):
        exact = self._pipe_exact_profile
        self._guard(lambda: self.generate_cover(source_inputs=inputs, source_key=key, candidate=candidate,
            candidates=candidates, on_applied=lambda: self.pipe_profile_editor.discard_draft(key, exact=exact)),
            notice="覆土纵断面")

    def _apply_pipe_changes(self, inputs):
        from .workbench_panel import restore_inputs
        self._inputs = restore_inputs(inputs)
        self._refresh_source_diagnostics()
        self._invalidate()
        self._refresh_assets()
        self._rebase_auxiliary_draft()

    def _prepare_object_cover(self, key, *, exact=False):
        """Resolve the measured pipe length from the chosen depth and current terrain."""
        from 土石方计算.services.batch_cover_profiles import needs_cover_generation, prepare_batch_cover_profiles

        key = tuple(key)
        if exact:
            member = profile_objects(self._pipe_inputs).get(key)
            entry = (member,) if member else ()
        else:
            entry = self._pipe_rows.get(source_scope_key(self._pipe_rows, key))
        if not entry or self.runner.isRunning() or (self._tin is None and not self.terrain_path.text()):
            return
        request = self._cover_request()
        networks = {}
        for owner, part in entry:
            if ((part.get("pipe_profile_choice") == "cover_depth" or part.get("cover_confirmation")
                 or (part.get("siphon_axis_choice") or {}).get("mode") == "cover_depth")
                    and needs_cover_generation(part, owner, request, self._tin)):
                networks.setdefault(id(owner), {**owner, "assets": []})["assets"].append(part)
        if not networks:
            return
        source = restore_workbench_automatic_ranges(self._inputs)
        scoped = {"networks": deepcopy(list(networks.values()))}
        project, revision = self.project_id, self._input_revision

        def work(token):
            tin = self._ensure_tin(token, request)
            if not getattr(tin, "import_report", {}).get("cache_sha256"):
                tin = self._cache_tin(tin, token, request["options"])
            result, report = prepare_batch_cover_profiles(tin, scoped, cover_depth=None,
                sample_step=request["cover_sample_step"], terrain_request=request, raise_on_error=False,
                cancelled=lambda:token.is_cancelled)
            return tin, result, report

        def accept(outcome):
            if project != self.project_id or revision != self._input_revision:
                return
            tin, prepared, report = outcome
            parts_by_key = profile_objects(prepared)
            completed = {(row["route_id"], row["asset_id"]) for row in report["completed"]}
            if completed:
                self._accept_tin(tin)
                for key, (owner, part) in profile_objects(source).items():
                    if key in parts_by_key and (route_identity(owner), key[1]) in completed:
                        part.clear()
                        part.update(parts_by_key[key][1])
                self._apply_pipe_changes(source)
            if report["failures"]:
                message = "；".join(row["message"] for row in report["failures"])
                self.feedback.fail(message)
                self._log(message)

        self._submit_task(work, title="管顶覆土纵断面", message="正在按当前地形生成管轴并计算实际长度。",
                          on_success=accept, success_message="已生成管顶覆土纵断面。")
