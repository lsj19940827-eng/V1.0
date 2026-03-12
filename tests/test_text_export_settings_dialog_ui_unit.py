# -*- coding: utf-8 -*-
"""TextExportSettingsDialog 单列表交互单元测试。"""

import importlib.util
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


def _get_qapp():
    return QApplication.instance() or QApplication([])


def _flush_events(rounds: int = 3):
    app = _get_qapp()
    for _ in range(max(1, rounds)):
        app.processEvents()


def _load_cad_tools():
    root = Path(__file__).resolve().parents[1]
    matches = list(root.glob("*/water_profile/cad_tools.py"))
    assert matches, "未找到 cad_tools.py"
    spec = importlib.util.spec_from_file_location("cad_tools_text_export_dialog_ui_test_mod", matches[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cad_tools = _load_cad_tools()


def _enabled_ids(dlg):
    return [item["id"] for item in dlg._row_data_from_table() if item.get("enabled")]


def _visible_ids(dlg):
    out = []
    for row in range(dlg._row_list.count()):
        rid = dlg._row_list.item(row).data(Qt.UserRole)
        out.append(str(rid))
    return out


def _find_item(dlg, rid):
    for row in range(dlg._row_list.count()):
        item = dlg._row_list.item(row)
        if str(item.data(Qt.UserRole)) == rid:
            return item
    raise AssertionError(f"row id not found: {rid}")


def _find_row_widget(dlg, rid):
    widget = dlg._row_widgets.get(rid)
    if widget is None:
        raise AssertionError(f"row widget not found: {rid}")
    return widget


def test_initial_load_maps_legacy_profile_row_items_to_single_list_and_hides_be_bk():
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
    assert "be_ip_text" not in _visible_ids(dlg)
    assert "bk_station" not in _visible_ids(dlg)

    dlg.deleteLater()


def test_apply_tingzikou_preset_reorders_and_enables_expected_rows():
    _get_qapp()
    dlg = cad_tools.TextExportSettingsDialog()

    dlg._disable_all_rows()
    assert _enabled_ids(dlg) == []

    dlg._apply_tingzikou_preset()
    assert _enabled_ids(dlg) == list(cad_tools._TINGZIKOU_TEMPLATE_ROW_IDS)

    dlg.deleteLater()


def test_quick_actions_enable_disable_and_restore_recommended():
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


def test_checking_row_enables_it_and_unchecking_disables_it():
    _get_qapp()
    dlg = cad_tools.TextExportSettingsDialog()
    dlg._disable_all_rows()

    widget = _find_row_widget(dlg, "bd_ip_before")
    widget.checkbox.setChecked(True)
    _flush_events()
    assert _enabled_ids(dlg) == ["bd_ip_before"]

    widget = _find_row_widget(dlg, "bd_ip_before")
    widget.checkbox.setChecked(False)
    _flush_events()
    assert _enabled_ids(dlg) == []

    dlg.deleteLater()


def test_reorder_enabled_row_updates_order_and_keeps_disabled_rows_after_enabled_section():
    _get_qapp()
    dlg = cad_tools.TextExportSettingsDialog()

    dlg._enable_all_rows()
    before = _enabled_ids(dlg)
    dlg._reorder_enabled_row("station", 0)
    after = _enabled_ids(dlg)

    assert len(after) == len(before)
    assert after[0] == "station"
    assert set(after) == set(before)

    visible = _visible_ids(dlg)
    assert visible[: len(after)] == after

    dlg.deleteLater()


def test_move_selected_row_down_moves_item_to_next_position():
    _get_qapp()
    dlg = cad_tools.TextExportSettingsDialog()

    dlg._enable_all_rows()
    before = _enabled_ids(dlg)
    station_index = before.index("station")
    assert station_index < len(before) - 1

    dlg._set_current_row_id("station")
    dlg._move_selected_row(1)
    after = _enabled_ids(dlg)

    assert after[station_index] == before[station_index + 1]
    assert after[station_index + 1] == "station"
    assert set(after) == set(before)

    dlg.deleteLater()


def test_validation_shows_first_error_and_focuses_invalid_field(monkeypatch):
    _get_qapp()
    dlg = cad_tools.TextExportSettingsDialog()
    dlg.show()
    _flush_events()

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
    assert "必须大于0" in errors[-1][1]
    assert dlg._entries["scale_x"].selectedText() == "0"

    dlg._entries["scale_x"].setText("1000")
    dlg._on_confirm()
    assert dlg.result is not None
    assert dlg.result["scale_x"] == 1000.0

    dlg.deleteLater()


def test_row_list_has_at_least_ten_visible_rows_capacity():
    _get_qapp()
    dlg = cad_tools.TextExportSettingsDialog()
    dlg.show()
    _flush_events()

    row_h = dlg._row_list.sizeHintForRow(0)
    if row_h <= 0:
        row_h = 30
    assert dlg._row_list.minimumHeight() >= row_h * 10

    dlg.deleteLater()
