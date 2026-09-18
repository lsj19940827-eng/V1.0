# -*- coding: utf-8 -*-
"""TextExportSettingsDialog 双栏工作台 UI 单元测试。"""

import importlib.util
import os
import sys
import pytest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

from PySide6.QtCore import QEvent, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QAbstractItemView


def _get_qapp():
    return QApplication.instance() or QApplication([])


def _flush_events(rounds: int = 4):
    app = _get_qapp()
    for _ in range(max(1, rounds)):
        app.processEvents()


def _load_cad_tools():
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    matches = list(root.glob("*/water_profile/cad_tools.py"))
    assert matches, "未找到 cad_tools.py"
    spec = importlib.util.spec_from_file_location("cad_tools_text_export_dialog_ui_test_mod", matches[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cad_tools = _load_cad_tools()


@pytest.fixture(autouse=True)
def _dispose_dialogs():
    yield
    # 显式释放延迟删除的窗口，避免跨用例的快捷键和焦点相互干扰。
    app = _get_qapp()
    for widget in app.topLevelWidgets():
        if isinstance(widget, cad_tools.TextExportSettingsDialog):
            widget.hide()
            widget.deleteLater()
    app.sendPostedEvents(None, QEvent.DeferredDelete)


def _clear_dialog_ui_settings():
    dialog_cls = cad_tools.TextExportSettingsDialog
    settings = cad_tools.QSettings(dialog_cls._UI_SETTINGS_ORG, dialog_cls._UI_SETTINGS_APP)
    settings.clear()
    settings.sync()


def _enabled_ids(dlg):
    return [item["id"] for item in dlg._row_data_from_table() if item.get("enabled")]


def _list_ids(list_widget):
    out = []
    for row in range(list_widget.count()):
        item = list_widget.item(row)
        out.append(str(item.data(Qt.UserRole)))
    return out


def _enabled_list_ids(dlg):
    return _list_ids(dlg._enabled_list)


def _candidate_list_ids(dlg):
    return _list_ids(dlg._candidate_list) if dlg._candidate_list is not None else []


def _runtime_row_ids(dlg):
    return [rid for rid in dlg._runtime_row_labels.keys() if rid != "y_line_height"]


def _runtime_value_text(dlg, key):
    return dlg._runtime_row_labels[key]["value"].text()


def _expected_list_height(list_widget, row_count, *, clamp_to_count=True):
    expected_rows = min(row_count, list_widget.count()) if clamp_to_count else row_count
    return list_widget.content_height_for_rows(expected_rows, clamp_to_count=clamp_to_count)


def _find_row_widget(dlg, rid):
    widget = dlg._row_widgets.get(rid)
    if widget is None:
        raise AssertionError(f"row widget not found: {rid}")
    return widget


def _widget_rect_in_dialog(dlg, widget):
    top_left = widget.mapTo(dlg, widget.rect().topLeft())
    bottom_right = widget.mapTo(dlg, widget.rect().bottomRight())
    return QRect(top_left, bottom_right)


def _button_rect_in_dialog(dlg, button):
    top_left = button.mapTo(dlg, button.rect().topLeft())
    bottom_right = button.mapTo(dlg, button.rect().bottomRight())
    return QRect(top_left, bottom_right)


def _widget_rect_in_widget(container, widget):
    top_left = widget.mapTo(container, widget.rect().topLeft())
    bottom_right = widget.mapTo(container, widget.rect().bottomRight())
    return QRect(top_left, bottom_right)


def _dialog_contains_rect(dlg, rect):
    return dlg.rect().contains(rect.topLeft()) and dlg.rect().contains(rect.bottomRight())


def _find_button(dlg, text):
    for widget in dlg.findChildren(QPushButton):
        if widget.text() == text:
            return widget
    raise AssertionError(f"button not found: {text}")


def _assert_workbench_geometry_is_consistent(dlg):
    _flush_events(6)
    assert dlg._workbench_splitter is not None
    left_rect = _widget_rect_in_dialog(dlg, dlg._parameter_card)
    right_rect = _widget_rect_in_dialog(dlg, dlg._rows_card)
    ok_rect = _button_rect_in_dialog(dlg, dlg._btn_ok)
    cancel_rect = _button_rect_in_dialog(dlg, dlg._btn_cancel)

    assert _dialog_contains_rect(dlg, left_rect)
    assert _dialog_contains_rect(dlg, right_rect)
    assert _dialog_contains_rect(dlg, ok_rect)
    assert _dialog_contains_rect(dlg, cancel_rect)
    assert left_rect.right() < right_rect.left()
    assert left_rect.bottom() < ok_rect.top()
    assert right_rect.bottom() < ok_rect.top()


def test_initial_load_hides_be_and_bk_rows():
    _get_qapp()
    defaults = {
        "profile_row_items": [
            {"id": "station", "enabled": True},
            {"id": "building_name", "enabled": True},
            {"id": "be_ip_text", "enabled": True},
            {"id": "ip_name", "enabled": True},
            {"id": "bk_station", "enabled": True},
        ]
    }
    dlg = cad_tools.TextExportSettingsDialog(defaults=defaults)

    assert _enabled_ids(dlg)[:3] == ["station", "building_name", "ip_name"]
    assert "be_ip_text" not in _enabled_list_ids(dlg)
    assert "be_ip_text" not in _candidate_list_ids(dlg)
    assert "bk_station" not in _enabled_list_ids(dlg)
    assert "bk_station" not in _candidate_list_ids(dlg)

    dlg.deleteLater()


def test_dialog_defaults_show_profile_ratio_denominators():
    _get_qapp()
    dlg = cad_tools.TextExportSettingsDialog()

    assert dlg._entries["station_decimals"].text() == "2"
    assert dlg._entries["scale_x"].text() == "2000"
    assert dlg._entries["scale_y"].text() == "1000"

    dlg.deleteLater()


def test_dialog_uses_splitter_workbench_and_footer_stays_visible(monkeypatch):
    _get_qapp()
    _clear_dialog_ui_settings()
    large_rect = QRect(0, 0, 1600, 900)
    monkeypatch.setattr(cad_tools.TextExportSettingsDialog, "_available_geometry", lambda self: large_rect)
    dlg = cad_tools.TextExportSettingsDialog()
    dlg.show()
    _flush_events(6)

    assert dlg.width() == 1280
    assert dlg.height() == 792
    assert dlg.minimumWidth() >= 1040
    assert dlg.minimumHeight() >= 680
    assert dlg._workbench_splitter.sizes()[0] >= dlg._DESIGN_SPLITTER_LEFT
    assert dlg._parameter_content_layout is not None
    assert dlg._parameter_left_section is not None
    assert dlg._parameter_right_section is not None
    viewport_rect = dlg._body_scroll.viewport().rect()
    left_section_rect = _widget_rect_in_widget(dlg._body_scroll.viewport(), dlg._parameter_left_section)
    assert viewport_rect.contains(left_section_rect.topLeft())
    assert viewport_rect.contains(left_section_rect.bottomRight())
    _assert_workbench_geometry_is_consistent(dlg)

    dlg.deleteLater()


def test_dialog_default_size_adapts_by_resolution_class(monkeypatch):
    _get_qapp()
    _clear_dialog_ui_settings()
    dialog_cls = cad_tools.TextExportSettingsDialog

    cases = [
        (QRect(0, 0, 2560, 1600), (1440, 960)),
        (QRect(0, 0, 1920, 1080), (1440, 950)),
        (QRect(0, 0, 3840, 2160), (1440, 960)),
    ]

    for rect, expected_size in cases:
        monkeypatch.setattr(dialog_cls, "_available_geometry", lambda self, rect=rect: rect)
        dlg = dialog_cls()
        dlg.show()
        _flush_events(6)

        assert (dlg.width(), dlg.height()) == expected_size
        assert dlg.sizeHint().width() == expected_size[0]
        assert dlg.sizeHint().height() == expected_size[1]

        dlg.deleteLater()


def test_runtime_panel_mirrors_enabled_rows_and_summary_metrics():
    _get_qapp()
    dlg = cad_tools.TextExportSettingsDialog()
    dlg.show()
    _flush_events(4)
    dlg._disable_all_rows()

    assert _runtime_row_ids(dlg) == []
    assert set(dlg._runtime_metric_labels.keys()) == {
        "enabled_count",
        "total_height",
        "line_height",
        "min_line_height",
    }

    dlg._set_row_enabled("building_name", True)
    dlg._set_row_enabled("station", True)
    _flush_events(4)

    assert _runtime_row_ids(dlg) == ["building_name", "station"]
    assert _runtime_value_text(dlg, "building_name") == "35"
    assert _runtime_value_text(dlg, "station") == "2"
    assert dlg._runtime_metric_labels["enabled_count"].text() == "2"
    assert "实时汇总" in dlg._runtime_summary_label.text()

    dlg.deleteLater()


def test_xxpipe_mode_shows_fixed_read_only_five_rows_and_runtime_view():
    _get_qapp()
    defaults = {
        "elev_decimals": 3,
        "profile_row_items": [
            {"id": "station", "enabled": True},
            {"id": "building_name", "enabled": False},
            {"id": "top_elev", "enabled": True},
        ]
    }
    dlg = cad_tools.TextExportSettingsDialog(defaults=defaults, mode="xxpipe")
    dlg.show()
    _flush_events(6)

    expected_ids = [
        "building_name",
        "ip_name",
        "station",
        "centerline_elev",
        "pipe_material",
    ]
    assert _enabled_ids(dlg) == expected_ids
    assert _enabled_list_ids(dlg) == expected_ids
    assert dlg._candidate_list.count() == 0
    assert not dlg._candidate_section.isVisible()
    assert _runtime_row_ids(dlg) == expected_ids
    assert _runtime_value_text(dlg, "building_name") == "120"
    assert _runtime_value_text(dlg, "ip_name") == "72"
    assert _runtime_value_text(dlg, "station") == "42"
    assert _runtime_value_text(dlg, "centerline_elev") == "21"
    assert _runtime_value_text(dlg, "pipe_material") == "10"

    visible_button_texts = {
        widget.text()
        for widget in dlg.findChildren(QPushButton)
        if widget.isVisible() and widget.text()
    }
    assert "应用亭子口二期顶建/可研阶段模板" not in visible_button_texts
    assert "恢复推荐" not in visible_button_texts
    assert "全启用" not in visible_button_texts
    assert "全停用" not in visible_button_texts
    assert "上移" not in visible_button_texts
    assert "下移" not in visible_button_texts
    assert "置顶" not in visible_button_texts
    assert "置底" not in visible_button_texts

    assert dlg._entries["xxpipe_centerline_elev_decimals"].text() == "2"
    assert dlg._entries["xxpipe_station_decimals"].text() == "2"
    assert "elev_decimals" not in dlg._entries
    assert "station_decimals" not in dlg._entries

    widget = _find_row_widget(dlg, "building_name")
    assert not widget.checkbox.isEnabled()
    assert widget.checkbox.isHidden()
    assert widget.action_button.isHidden()
    assert widget.up_button.isHidden()
    assert widget.down_button.isHidden()
    assert widget.badge_label.isHidden()
    assert widget.position_label.text() == "120"
    assert not dlg._enabled_list.selectedItems()
    assert widget.drag_handle.isHidden()

    dlg.deleteLater()


def test_inline_move_buttons_target_their_own_row_and_respect_edges():
    _get_qapp()
    dlg = cad_tools.TextExportSettingsDialog()
    dlg.show()
    _flush_events()
    before = _enabled_ids(dlg)
    assert not _find_row_widget(dlg, before[0]).up_button.isEnabled()
    assert not _find_row_widget(dlg, before[-1]).down_button.isEnabled()
    dlg._set_current_row_id(before[-1], "enabled")
    QTest.mouseClick(_find_row_widget(dlg, before[0]).down_button, Qt.LeftButton)
    _flush_events()
    assert _enabled_ids(dlg) == [before[1], before[0], *before[2:]]
    QTest.mouseClick(_find_row_widget(dlg, before[0]).up_button, Qt.LeftButton)
    _flush_events()
    assert _enabled_ids(dlg) == before
    assert _runtime_row_ids(dlg) == before
    dlg.deleteLater()


def test_layout_details_expand_without_changing_export_settings():
    _get_qapp()
    dlg = cad_tools.TextExportSettingsDialog(mode="xxpipe")
    dlg.show()
    _flush_events()
    before = dlg._build_runtime_view_input_settings()
    assert not dlg._parameter_right_section.isVisible()
    QTest.mouseClick(dlg._runtime_toggle, Qt.LeftButton)
    _flush_events()
    assert dlg._parameter_right_section.isVisible()
    QTest.mouseClick(dlg._runtime_toggle, Qt.LeftButton)
    assert not dlg._parameter_right_section.isVisible()
    assert dlg._build_runtime_view_input_settings() == before
    dlg.deleteLater()


def test_xxpipe_mode_confirm_preserves_standard_profile_row_snapshot():
    _get_qapp()
    defaults = {
        "elev_decimals": 3,
        "profile_row_items": [
            {"id": "station", "enabled": True},
            {"id": "building_name", "enabled": False},
            {"id": "top_elev", "enabled": True},
        ]
    }
    expected_profile_row_items = cad_tools._normalize_text_export_settings(defaults)["profile_row_items"]

    dlg = cad_tools.TextExportSettingsDialog(defaults=defaults, mode="xxpipe")
    dlg.show()
    _flush_events(4)

    dlg._entries["xxpipe_centerline_elev_decimals"].setText("3")
    dlg._entries["xxpipe_station_decimals"].setText("4")
    dlg._on_confirm()

    assert dlg.result is not None
    assert dlg.result["profile_row_items"] == expected_profile_row_items
    assert dlg.result["xxpipe_centerline_elev_decimals"] == 3
    assert dlg.result["xxpipe_station_decimals"] == 4
    assert dlg.result["elev_decimals"] == 3

    dlg.deleteLater()


def test_standard_mode_confirm_preserves_station_decimals():
    _get_qapp()
    dlg = cad_tools.TextExportSettingsDialog()
    dlg.show()
    _flush_events(4)

    dlg._entries["station_decimals"].setText("4")
    dlg._on_confirm()

    assert dlg.result is not None
    assert dlg.result["station_decimals"] == 4

    dlg.deleteLater()


def test_apply_tingzikou_preset_reorders_expected_rows():
    _get_qapp()
    dlg = cad_tools.TextExportSettingsDialog()
    dlg._disable_all_rows()

    dlg._apply_tingzikou_preset()

    assert _enabled_ids(dlg) == list(cad_tools._TINGZIKOU_TEMPLATE_ROW_IDS)
    assert _enabled_list_ids(dlg) == list(cad_tools._TINGZIKOU_TEMPLATE_ROW_IDS)

    dlg.deleteLater()


def test_quick_actions_enable_disable_restore():
    _get_qapp()
    dlg = cad_tools.TextExportSettingsDialog()

    dlg._disable_all_rows()
    assert _enabled_ids(dlg) == []

    dlg._enable_all_rows()
    assert len(_enabled_ids(dlg)) == len(cad_tools._PROFILE_ROW_VISIBLE_ORDER)

    dlg._restore_recommended_rows()
    expected = [rid for rid in cad_tools._PROFILE_ROW_VISIBLE_ORDER if rid in cad_tools._PROFILE_RECOMMENDED_ROW_IDS]
    assert _enabled_ids(dlg) == expected

    dlg.deleteLater()


def test_candidate_section_expands_to_four_rows_without_search(monkeypatch):
    _get_qapp()
    _clear_dialog_ui_settings()
    large_rect = QRect(0, 0, 1600, 900)
    monkeypatch.setattr(cad_tools.TextExportSettingsDialog, "_available_geometry", lambda self: large_rect)
    dlg = cad_tools.TextExportSettingsDialog()
    dlg.show()
    assert not dlg._state.candidate_expanded
    dlg._toggle_candidate_section()
    _flush_events(4)

    assert dlg._candidate_section.isVisible()
    assert dlg._candidate_body.isVisible()
    assert not hasattr(dlg, "_candidate_search")
    assert dlg._candidate_list.count() == 4
    assert dlg._candidate_list.maximumHeight() == _expected_list_height(dlg._candidate_list, 4)
    assert dlg._candidate_list.height() == dlg._candidate_list.maximumHeight()
    assert dlg._candidate_list.verticalScrollBar().maximum() == 0
    assert _candidate_list_ids(dlg) == [
        "bd_ip_before",
        "bf_ip_after",
        "bj_station_before",
        "bl_station_after",
    ]

    dlg._toggle_candidate_section()
    _flush_events(4)
    assert not dlg._candidate_body.isVisible()

    dlg._toggle_candidate_section()
    _flush_events(4)
    assert dlg._candidate_body.isVisible()
    assert dlg._candidate_list.height() == dlg._candidate_list.maximumHeight()
    _assert_workbench_geometry_is_consistent(dlg)

    dlg.deleteLater()


def test_candidate_section_adapts_from_four_to_zero_and_back_to_four(monkeypatch):
    _get_qapp()
    _clear_dialog_ui_settings()
    large_rect = QRect(0, 0, 1600, 900)
    monkeypatch.setattr(cad_tools.TextExportSettingsDialog, "_available_geometry", lambda self: large_rect)
    dlg = cad_tools.TextExportSettingsDialog()
    dlg.show()
    assert not dlg._state.candidate_expanded
    dlg._toggle_candidate_section()
    _flush_events(6)

    assert dlg._candidate_list.count() == 4
    assert dlg._candidate_list.maximumHeight() == _expected_list_height(dlg._candidate_list, 4)
    assert dlg._candidate_list.verticalScrollBar().maximum() == 0

    dlg._set_row_enabled("bd_ip_before", True)
    _flush_events(6)
    assert len(dlg._state.enabled_row_ids) == 8
    assert len(dlg._state.all_candidate_row_ids()) == 3
    assert dlg._candidate_list.count() == 3
    assert dlg._candidate_list.maximumHeight() == _expected_list_height(dlg._candidate_list, 3)
    assert dlg._candidate_list.height() == dlg._candidate_list.maximumHeight()
    assert dlg._candidate_list.verticalScrollBar().maximum() == 0
    _assert_workbench_geometry_is_consistent(dlg)

    dlg._set_row_enabled("bf_ip_after", True)
    _flush_events(6)
    assert len(dlg._state.enabled_row_ids) == 9
    assert len(dlg._state.all_candidate_row_ids()) == 2
    assert dlg._candidate_list.count() == 2
    assert dlg._candidate_list.maximumHeight() == _expected_list_height(dlg._candidate_list, 2)
    assert dlg._candidate_list.height() == dlg._candidate_list.maximumHeight()
    assert dlg._candidate_list.verticalScrollBar().maximum() == 0
    _assert_workbench_geometry_is_consistent(dlg)

    dlg._set_row_enabled("bj_station_before", True)
    _flush_events(6)
    assert len(dlg._state.enabled_row_ids) == 10
    assert len(dlg._state.all_candidate_row_ids()) == 1
    assert dlg._candidate_list.count() == 1
    assert dlg._candidate_list.maximumHeight() == _expected_list_height(dlg._candidate_list, 1)
    assert dlg._candidate_list.height() == dlg._candidate_list.maximumHeight()
    assert dlg._candidate_list.verticalScrollBar().maximum() == 0
    _assert_workbench_geometry_is_consistent(dlg)

    dlg._set_row_enabled("bl_station_after", True)
    _flush_events(6)
    assert len(dlg._state.enabled_row_ids) == 11
    assert len(dlg._state.all_candidate_row_ids()) == 0
    assert not dlg._candidate_section.isVisible()
    _assert_workbench_geometry_is_consistent(dlg)

    dlg._set_row_enabled("bl_station_after", False)
    _flush_events(6)
    assert dlg._candidate_section.isVisible()
    assert dlg._candidate_list.count() == 1
    assert dlg._candidate_list.maximumHeight() == _expected_list_height(dlg._candidate_list, 1)

    for rid in ["bj_station_before", "bf_ip_after", "bd_ip_before"]:
        dlg._set_row_enabled(rid, False)
        _flush_events(6)
    assert dlg._candidate_list.count() == 4
    assert dlg._candidate_list.maximumHeight() == _expected_list_height(dlg._candidate_list, 4)
    assert dlg._candidate_list.verticalScrollBar().maximum() == 0
    assert _candidate_list_ids(dlg) == [
        "bd_ip_before",
        "bf_ip_after",
        "bj_station_before",
        "bl_station_after",
    ]
    _assert_workbench_geometry_is_consistent(dlg)

    dlg.deleteLater()


def test_candidate_section_caps_at_four_rows_and_scrolls_when_five_or_more_candidates(monkeypatch):
    _get_qapp()
    _clear_dialog_ui_settings()
    large_rect = QRect(0, 0, 1600, 900)
    monkeypatch.setattr(cad_tools.TextExportSettingsDialog, "_available_geometry", lambda self: large_rect)
    dlg = cad_tools.TextExportSettingsDialog()
    dlg.show()
    assert not dlg._state.candidate_expanded
    dlg._toggle_candidate_section()
    _flush_events(6)

    assert dlg._candidate_list.count() == 4
    assert dlg._candidate_list.maximumHeight() == _expected_list_height(dlg._candidate_list, 4)
    _assert_workbench_geometry_is_consistent(dlg)

    dlg._set_row_enabled("building_name", False)
    _flush_events(6)
    assert len(dlg._state.enabled_row_ids) == 6
    assert dlg._candidate_list.count() == 5
    assert dlg._candidate_list.maximumHeight() == _expected_list_height(dlg._candidate_list, 4)
    assert dlg._candidate_list.height() == dlg._candidate_list.maximumHeight()
    assert dlg._candidate_list.verticalScrollBar().maximum() > 0
    _assert_workbench_geometry_is_consistent(dlg)

    dlg._set_current_row_id("building_name", prefer_enabled=False)
    current_item, _ = dlg._find_item_in_list(dlg._candidate_list, "building_name")
    assert current_item is not None
    dlg._candidate_list.scrollToItem(current_item, QAbstractItemView.PositionAtCenter)
    _flush_events(6)
    assert dlg._candidate_list.viewport().rect().intersects(dlg._candidate_list.visualItemRect(current_item))

    dlg._set_row_enabled("building_name", True)
    _flush_events(6)
    assert dlg._candidate_list.count() == 4
    assert dlg._candidate_list.maximumHeight() == _expected_list_height(dlg._candidate_list, 4)
    assert dlg._candidate_list.verticalScrollBar().maximum() == 0
    _assert_workbench_geometry_is_consistent(dlg)

    dlg.deleteLater()


def test_sequential_candidate_clicks_move_rows_into_enabled_group():
    _get_qapp()
    dlg = cad_tools.TextExportSettingsDialog()
    dlg.show()
    _flush_events(4)
    dlg._toggle_candidate_section()
    _flush_events(4)

    for step, rid in enumerate(["bd_ip_before", "bf_ip_after", "bj_station_before"], start=1):
        widget = _find_row_widget(dlg, rid)
        QTest.mouseClick(widget.action_button, Qt.LeftButton)
        _flush_events(4)
        assert rid in _enabled_list_ids(dlg)
        assert rid not in _candidate_list_ids(dlg)
        assert dlg._enabled_caption_label.text().startswith(str(7 + step))

    dlg.deleteLater()


def test_disable_click_keeps_focus_on_adjacent_enabled_row_and_scroll_stable():
    app = _get_qapp()
    dlg = cad_tools.TextExportSettingsDialog()
    dlg.show()
    _flush_events(6)
    dlg._enable_all_rows()
    _flush_events(6)

    bar = dlg._enabled_list.verticalScrollBar()
    bar.setValue(bar.maximum())
    _flush_events(4)
    before_value = bar.value()

    QApplication.setActiveWindow(dlg)
    _flush_events()
    widget = _find_row_widget(dlg, "water_elev")
    widget.action_button.setFocus()
    QTest.mouseClick(widget.action_button, Qt.LeftButton)
    _flush_events(8)

    assert "water_elev" not in _enabled_ids(dlg)
    assert dlg._enabled_list.current_row_id() == "bottom_elev"
    assert app.focusWidget() is dlg._enabled_list
    current_item, _ = dlg._find_item_in_list(dlg._enabled_list, "bottom_elev")
    assert current_item is not None
    assert dlg._enabled_list.viewport().rect().intersects(dlg._enabled_list.visualItemRect(current_item))

    dlg.deleteLater()


def test_disabling_last_enabled_row_falls_back_to_candidate_focus_and_auto_expands_candidate_section():
    app = _get_qapp()
    dlg = cad_tools.TextExportSettingsDialog()
    dlg.show()
    _flush_events(4)

    dlg._disable_all_rows()
    dlg._set_row_enabled("station", True)
    _flush_events(4)

    QApplication.setActiveWindow(dlg)
    _flush_events()
    widget = _find_row_widget(dlg, "station")
    QTest.mouseClick(widget.action_button, Qt.LeftButton)
    _flush_events(6)

    assert _enabled_ids(dlg) == []
    assert dlg._candidate_body.isVisible()
    assert dlg._candidate_list.current_row_id() == "station"
    assert app.focusWidget() is dlg._candidate_list

    dlg.deleteLater()


def test_enabled_and_candidate_lists_are_independently_scrollable(monkeypatch):
    _get_qapp()
    _clear_dialog_ui_settings()
    small_rect = QRect(0, 0, 860, 680)
    monkeypatch.setattr(cad_tools.TextExportSettingsDialog, "_available_geometry", lambda self: small_rect)
    dlg = cad_tools.TextExportSettingsDialog()
    dlg.show()
    _flush_events(4)

    dlg._enable_all_rows()
    _flush_events(6)
    assert dlg._enabled_list.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded
    assert dlg._enabled_list.verticalScrollBar().maximum() > 0

    dlg._disable_all_rows()
    _flush_events(6)
    assert dlg._candidate_body.isVisible()
    assert dlg._candidate_list.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded
    assert dlg._candidate_list.verticalScrollBar().maximum() > 0

    dlg.deleteLater()


def test_drag_handle_only_exists_for_enabled_rows():
    _get_qapp()
    dlg = cad_tools.TextExportSettingsDialog()
    dlg._disable_all_rows()
    dlg._set_row_enabled("station", True)

    enabled_widget = _find_row_widget(dlg, "station")
    candidate_widget = _find_row_widget(dlg, "bd_ip_before")
    assert not enabled_widget.drag_handle.isHidden()
    assert candidate_widget.drag_handle.isHidden()

    dlg.deleteLater()


def test_double_click_toggles_row():
    _get_qapp()
    dlg = cad_tools.TextExportSettingsDialog()
    dlg.show()
    _flush_events(4)
    dlg._disable_all_rows()
    dlg._toggle_candidate_section()
    _flush_events(4)

    widget = _find_row_widget(dlg, "bd_ip_before")
    QTest.mouseDClick(widget.title_label, Qt.LeftButton)
    _flush_events(4)
    assert _enabled_ids(dlg) == ["bd_ip_before"]

    widget = _find_row_widget(dlg, "bd_ip_before")
    QTest.mouseDClick(widget.title_label, Qt.LeftButton)
    _flush_events(4)
    assert _enabled_ids(dlg) == []

    dlg.deleteLater()


def test_space_enables_row_and_delete_disables_row():
    _get_qapp()
    dlg = cad_tools.TextExportSettingsDialog()
    dlg.show()
    _flush_events(4)
    dlg._disable_all_rows()
    _flush_events(4)

    QApplication.setActiveWindow(dlg)
    _flush_events()
    dlg._set_current_row_id("bd_ip_before", prefer_enabled=False)
    dlg._candidate_list.setFocus()
    QTest.keyClick(dlg._candidate_list, Qt.Key_Space)
    _flush_events(4)
    assert _enabled_ids(dlg) == ["bd_ip_before"]

    dlg._set_current_row_id("bd_ip_before", prefer_enabled=True)
    dlg._enabled_list.setFocus()
    QTest.keyClick(dlg._enabled_list, Qt.Key_Delete)
    _flush_events(4)
    assert _enabled_ids(dlg) == []

    dlg.deleteLater()


def test_delete_in_parameter_entry_only_edits_text():
    _get_qapp()
    dlg = cad_tools.TextExportSettingsDialog()
    dlg.show()
    _flush_events()
    before = _enabled_ids(dlg)
    entry = dlg._entries["text_height"]
    entry.setFocus()
    entry.selectAll()
    QTest.keyClick(entry, Qt.Key_Delete)
    _flush_events()
    assert entry.text() == ""
    assert _enabled_ids(dlg) == before
    dlg.deleteLater()


def test_space_enables_row_inside_candidate_panel_when_five_candidates():
    _get_qapp()
    dlg = cad_tools.TextExportSettingsDialog()
    dlg.show()
    assert not dlg._state.candidate_expanded
    dlg._toggle_candidate_section()
    _flush_events(4)

    dlg._set_row_enabled("building_name", False)
    _flush_events(6)
    assert dlg._candidate_section.isVisible()
    assert dlg._candidate_body.isVisible()
    assert dlg._candidate_list.count() == 5
    assert dlg._candidate_list.maximumHeight() == _expected_list_height(dlg._candidate_list, 4)
    assert dlg._candidate_list.verticalScrollBar().maximum() > 0

    dlg._set_current_row_id("building_name", prefer_enabled=False)
    dlg._candidate_list.setFocus()
    QTest.keyClick(dlg._candidate_list, Qt.Key_Space)
    _flush_events(6)

    assert "building_name" in _enabled_ids(dlg)
    assert "building_name" not in _candidate_list_ids(dlg)
    assert dlg._candidate_section.isVisible()
    assert dlg._candidate_list.count() == 4
    assert dlg._candidate_list.maximumHeight() == _expected_list_height(dlg._candidate_list, 4)
    assert dlg._candidate_list.verticalScrollBar().maximum() == 0

    dlg.deleteLater()


def test_single_row_feedback_updates_lists_without_overlay(monkeypatch):
    _get_qapp()
    dlg = cad_tools.TextExportSettingsDialog()
    dlg.show()
    _flush_events(4)
    dlg._disable_all_rows()
    dlg._toggle_candidate_section()
    _flush_events(4)

    events = []

    def _fake_success(title, content, **kwargs):
        events.append(("success", title, content))

    def _fake_info(title, content, **kwargs):
        events.append(("info", title, content))

    monkeypatch.setattr(cad_tools.InfoBar, "success", staticmethod(_fake_success))
    monkeypatch.setattr(cad_tools.InfoBar, "info", staticmethod(_fake_info))

    widget = _find_row_widget(dlg, "bd_ip_before")
    QTest.mouseClick(widget.action_button, Qt.LeftButton)
    _flush_events(4)
    widget = _find_row_widget(dlg, "bd_ip_before")
    QTest.mouseClick(widget.action_button, Qt.LeftButton)
    _flush_events(4)

    assert events == []
    assert "bd_ip_before" in _candidate_list_ids(dlg)
    assert "bd_ip_before" not in _enabled_ids(dlg)

    dlg.deleteLater()


def test_confirm_writes_runtime_advanced_and_keeps_disabled_compat_value():
    _get_qapp()
    defaults = {
        "y_bottom": 66,
        "y_top": 88,
        "y_water": 99,
        "y_name": 115,
        "y_slope": 105,
        "y_ip": 77,
        "y_station": 47,
        "y_line_height": 120,
        "profile_row_items": [
            {"id": "building_name", "enabled": True},
            {"id": "slope", "enabled": False},
            {"id": "ip_name", "enabled": False},
            {"id": "station", "enabled": False},
            {"id": "top_elev", "enabled": False},
            {"id": "water_elev", "enabled": False},
            {"id": "bottom_elev", "enabled": False},
            {"id": "bd_ip_before", "enabled": False},
            {"id": "bf_ip_after", "enabled": False},
            {"id": "bj_station_before", "enabled": False},
            {"id": "bl_station_after", "enabled": False},
        ],
    }
    dlg = cad_tools.TextExportSettingsDialog(defaults=defaults)
    dlg.show()
    _flush_events(4)

    dlg._on_confirm()

    assert dlg.result is not None
    assert dlg.result["y_name"] == 5.0
    assert dlg.result["y_bottom"] == 66
    assert dlg.result["y_station"] == 47
    assert dlg.result["y_line_height"] == 120.0
    assert "bd_ip_before" not in dlg.result

    dlg.deleteLater()


def test_validation_shows_first_error_and_focuses_invalid_field(monkeypatch):
    _get_qapp()
    dlg = cad_tools.TextExportSettingsDialog()
    dlg.show()
    _flush_events(4)

    errors = []

    def _fake_error(_parent, title, content):
        errors.append((title, content))

    monkeypatch.setattr(cad_tools, "fluent_error", _fake_error)

    dlg._disable_all_rows()
    dlg._on_confirm()
    assert errors
    assert "至少选择1项行内容" in errors[-1][1]

    dlg._enable_all_rows()
    dlg._entries["scale_x"].setText("0")
    dlg._on_confirm()
    assert "比例必须大于0" in errors[-1][1]
    assert dlg._entries["scale_x"].selectedText() == "0"

    dlg.deleteLater()


def test_enabled_list_height_tracks_enabled_count_up_to_eleven_rows(monkeypatch):
    _get_qapp()
    _clear_dialog_ui_settings()
    large_rect = QRect(0, 0, 1600, 900)
    monkeypatch.setattr(cad_tools.TextExportSettingsDialog, "_available_geometry", lambda self: large_rect)

    dlg = cad_tools.TextExportSettingsDialog()
    dlg.show()
    _flush_events(6)

    assert dlg._enabled_list.maximumHeight() == _expected_list_height(dlg._enabled_list, 7)
    assert 0 < dlg._enabled_list.height() <= dlg._enabled_list.maximumHeight()
    assert dlg._candidate_section.isVisible()
    _assert_workbench_geometry_is_consistent(dlg)

    dlg._enable_all_rows()
    _flush_events(6)
    assert dlg._enabled_list.maximumHeight() == _expected_list_height(dlg._enabled_list, 11)
    assert dlg._enabled_list.height() > 400
    assert dlg._enabled_list.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded
    assert not dlg._candidate_section.isVisible()
    _assert_workbench_geometry_is_consistent(dlg)

    dlg._restore_recommended_rows()
    _flush_events(6)
    assert dlg._enabled_list.maximumHeight() == _expected_list_height(dlg._enabled_list, 7)
    assert 0 < dlg._enabled_list.height() <= dlg._enabled_list.maximumHeight()
    assert dlg._candidate_section.isVisible()
    _assert_workbench_geometry_is_consistent(dlg)

    dlg.deleteLater()


def test_persisted_small_window_is_clamped_to_new_minimum(monkeypatch):
    _get_qapp()
    _clear_dialog_ui_settings()
    dialog_cls = cad_tools.TextExportSettingsDialog
    large_rect = QRect(0, 0, 1600, 900)
    monkeypatch.setattr(dialog_cls, "_available_geometry", lambda self: large_rect)
    settings = cad_tools.QSettings(dialog_cls._UI_SETTINGS_ORG, dialog_cls._UI_SETTINGS_APP)
    settings.setValue(dialog_cls._UI_SIZE_W_KEY, 960)
    settings.setValue(dialog_cls._UI_SIZE_H_KEY, 548)

    dlg = dialog_cls()
    dlg.show()
    _flush_events(6)

    assert dlg.width() >= dialog_cls._DESIGN_MIN_WIDTH
    assert dlg.height() >= dialog_cls._DESIGN_MIN_HEIGHT
    _assert_workbench_geometry_is_consistent(dlg)

    dlg.deleteLater()


def test_small_available_geometry_still_keeps_splitter_and_footer_usable(monkeypatch):
    _get_qapp()
    small_rect = QRect(0, 0, 860, 680)
    monkeypatch.setattr(cad_tools.TextExportSettingsDialog, "_available_geometry", lambda self: small_rect)

    dlg = cad_tools.TextExportSettingsDialog()
    dlg.show()
    _flush_events(6)

    geom = dlg.geometry()
    assert geom.width() <= small_rect.width()
    assert geom.height() <= small_rect.height()
    _assert_workbench_geometry_is_consistent(dlg)

    dlg.deleteLater()
