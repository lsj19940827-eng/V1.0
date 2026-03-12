"""WaterProfilePanel 与断面批量输入区联动的回归测试。"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace


def _load_panel_class():
    panel_path = next(Path(".").glob("**/water_profile/panel.py")).resolve()
    spec = importlib.util.spec_from_file_location("wp_panel_mod_sync_test", panel_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.WaterProfilePanel


class _FakeLineEdit:
    def __init__(self, text=""):
        self._text = text

    def text(self):
        return self._text

    def setText(self, text):
        self._text = str(text)


class _FakeComboBox:
    def __init__(self, items, current=""):
        self._items = list(items)
        self._current = current if current in self._items else (self._items[0] if self._items else "")

    def currentText(self):
        return self._current

    def findText(self, text):
        try:
            return self._items.index(text)
        except ValueError:
            return -1

    def setCurrentIndex(self, index):
        self._current = self._items[index]


def test_sync_batch_settings_updates_global_and_flow_fields():
    WaterProfilePanel = _load_panel_class()
    panel = WaterProfilePanel.__new__(WaterProfilePanel)

    panel.channel_name_edit = _FakeLineEdit("默认名")
    panel.channel_level_combo = _FakeComboBox(["总干渠", "干渠", "支渠"], current="支渠")
    panel.start_wl_edit = _FakeLineEdit("100.0")
    panel.start_station_edit = _FakeLineEdit("0+000.000")
    panel._section_flow_segments_edit = _FakeLineEdit("5.0, 4.0, 3.0")
    panel.design_flow_edit = _FakeLineEdit("")
    panel.max_flow_edit = _FakeLineEdit("")

    callback_state = {"called": False}

    def _mark_design_change():
        callback_state["called"] = True
        panel.max_flow_edit.setText("auto-filled")

    panel._on_design_flow_changed = _mark_design_change

    bp = SimpleNamespace(
        channel_name_edit=_FakeLineEdit("龙塘"),
        channel_level_combo=_FakeComboBox(["总干渠", "干渠", "支渠"], current="干渠"),
        start_wl_edit=_FakeLineEdit("2392.271"),
        start_station_edit=_FakeLineEdit("0+000.000"),
        flow_segments_edit=_FakeLineEdit("4.6, 4.0, 3.2"),
    )
    panel._batch_backend = bp

    WaterProfilePanel._sync_batch_settings(panel)

    assert panel.channel_name_edit.text() == "龙塘"
    assert panel.channel_level_combo.currentText() == "干渠"
    assert panel.start_wl_edit.text() == "2392.271"
    assert panel.start_station_edit.text() == "0+000.000"
    assert panel._section_flow_segments_edit.text() == "4.6, 4.0, 3.2"
    assert panel.design_flow_edit.text() == "4.6, 4.0, 3.2"
    assert callback_state["called"] is True
    assert panel.max_flow_edit.text() == "auto-filled"


def test_load_section_sample_triggers_sync_after_loading():
    WaterProfilePanel = _load_panel_class()
    panel = WaterProfilePanel.__new__(WaterProfilePanel)

    state = {"loaded": False, "synced": False, "marked": False, "switched": False}

    class _FakeBatchBackend:
        def _add_sample_data(self):
            state["loaded"] = True

    class _FakeTable:
        @staticmethod
        def rowCount():
            return 1

    panel._batch_backend = _FakeBatchBackend()
    panel._tab_section_input = object()
    panel._section_input_table = _FakeTable()
    panel._sync_batch_settings = lambda: state.__setitem__("synced", True)
    panel._switch_workspace_tab = lambda _tab: state.__setitem__("switched", True)
    panel._mark_section_results_stale = lambda _msg: state.__setitem__("marked", True)

    WaterProfilePanel._load_section_sample_1(panel)

    assert state["loaded"] is True
    assert state["synced"] is True
    assert state["switched"] is True
    assert state["marked"] is True
