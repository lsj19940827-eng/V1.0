"""有压管道预览画布双击放大 GUI 单元测试。"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QGroupBox

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "calc_渠系计算算法内核"))

from app_渠系计算前端.water_profile.water_profile_dialogs import (
    PressurePipeConfigDialog,
    SimpleProfileCanvas,
)


def _get_qapp():
    return QApplication.instance() or QApplication([])


def _flush_events(rounds: int = 4):
    app = _get_qapp()
    for _ in range(max(1, rounds)):
        app.processEvents()


def _make_ip_points():
    return [
        {"x": 0.0, "y": 0.0, "turn_angle": 0.0},
        {"x": 12.0, "y": 110.0, "turn_angle": 18.8},
        {"x": 24.0, "y": 220.0, "turn_angle": 0.0},
    ]


def _make_longitudinal_nodes():
    return [
        {
            "chainage": 0.0,
            "elevation": 422.0,
            "vertical_curve_radius": 0.0,
            "turn_type": "NONE",
            "turn_angle": 0.0,
        },
        {
            "chainage": 140.0,
            "elevation": 418.2,
            "vertical_curve_radius": 2400.0,
            "turn_type": "ARC",
            "turn_angle": 12.5,
        },
        {
            "chainage": 280.0,
            "elevation": 414.8,
            "vertical_curve_radius": 0.0,
            "turn_type": "NONE",
            "turn_angle": 0.0,
        },
    ]


class _FakeManager:
    def __init__(self, pipe_name: str, nodes):
        self._configs = {
            pipe_name: SimpleNamespace(
                longitudinal_nodes=list(nodes),
                turn_n=0.0,
                turn_R=0.0,
                force_override=False,
                radius_applied_at="",
            )
        }

    def get_pipe_config(self, pipe_name):
        return self._configs.get(pipe_name)

    def set_pipe_config(self, pipe_name, config):
        self._configs[pipe_name] = config

    def get_all_pipe_names(self):
        return list(self._configs.keys())


def _make_group(name: str = "测试管道"):
    rows = [
        SimpleNamespace(section_params={"D": 1.6}, turn_radius=0.0, flow_section="1"),
        SimpleNamespace(section_params={"D": 1.6}, turn_radius=0.0, flow_section="1"),
    ]
    return SimpleNamespace(
        name=name,
        design_flow=0.58,
        diameter=1.6,
        material_key="PE",
        ip_points=_make_ip_points(),
        rows=rows,
        row_indices=[10, 11],
    )


def _make_unnamed_group():
    rows = [
        SimpleNamespace(section_params={"D": 1.4}, turn_radius=35.0, flow_section="2"),
    ]
    return SimpleNamespace(
        name="",
        display_name="流量段2 第5行有压管道",
        storage_key="flow2-row5",
        identity="flow2-row5",
        group_mode="unnamed_row_segment",
        design_flow=1.12,
        diameter=1.4,
        material_key="球墨铸铁管",
        ip_points=[
            {"x": 0.0, "y": 0.0, "turn_angle": 0.0},
            {"x": 47.0, "y": 0.0, "turn_angle": 22.0},
        ],
        rows=rows,
        row_indices=[4],
        target_row_index=4,
        upstream_row_index=3,
    )


def _make_dialog():
    _get_qapp()
    group = _make_group()
    dialog = PressurePipeConfigDialog(
        pipe_groups=[group],
        manager=_FakeManager(group.name, _make_longitudinal_nodes()),
    )
    dialog.show()
    _flush_events(6)
    return dialog, group


def _make_unnamed_group():
    row = SimpleNamespace(section_params={"D": 1.4}, turn_radius=0.0, flow_section="2")
    return SimpleNamespace(
        name="",
        display_name="流量段2 第5行有压管道",
        storage_key="flow2-row5",
        identity="flow2-row5",
        group_mode="unnamed_row_segment",
        design_flow=1.55,
        diameter=1.4,
        material_key="球墨铸铁管",
        ip_points=_make_ip_points(),
        rows=[row],
        row_indices=[4],
        target_row_index=4,
        upstream_row_index=3,
    )


def test_simple_profile_canvas_double_click_requests_detail_view():
    _get_qapp()
    canvas = SimpleProfileCanvas(fixed_height=200)
    canvas.resize(420, 220)
    canvas.set_ip_points(_make_ip_points())
    canvas.show()
    _flush_events(4)

    signal = getattr(canvas, "open_detail_requested", None)
    assert signal is not None

    triggered = []
    signal.connect(lambda: triggered.append("open"))

    QTest.mouseDClick(canvas, Qt.LeftButton, Qt.NoModifier, QPoint(70, 70))
    _flush_events(4)

    assert triggered == ["open"]

    canvas.close()
    canvas.deleteLater()


def test_pressure_pipe_config_dialog_reuses_single_non_modal_viewer(monkeypatch):
    dialog, group = _make_dialog()
    widgets = dialog._card_widgets[group.name]
    canvas = widgets["canvas"]
    btn_preview = widgets["btn_preview"]
    btn_view_profile = widgets["btn_view_profile"]
    btn_view_plan = widgets["btn_view_plan"]

    assert canvas.get_view_mode() == "plan"
    assert btn_view_profile.isEnabled() is True

    QTest.mouseClick(btn_view_profile, Qt.LeftButton)
    _flush_events(4)
    assert canvas.get_view_mode() == "profile"

    QTest.mouseDClick(canvas, Qt.LeftButton, Qt.NoModifier, QPoint(90, 90))
    _flush_events(8)

    viewer = getattr(dialog, "_canvas_viewer", None)
    assert viewer is not None
    assert viewer.isVisible() is True
    assert viewer.isModal() is False
    assert viewer._canvas.get_view_mode() == "profile"

    first_viewer = viewer

    QTest.mouseClick(btn_view_plan, Qt.LeftButton)
    _flush_events(4)
    assert canvas.get_view_mode() == "plan"

    QTest.mouseClick(btn_preview, Qt.LeftButton)
    _flush_events(8)

    viewer = getattr(dialog, "_canvas_viewer", None)
    assert viewer is first_viewer
    assert viewer._canvas.get_view_mode() == "plan"

    if viewer is not None:
        viewer.close()
    dialog.close()
    dialog.deleteLater()


def test_pressure_pipe_config_dialog_uses_storage_key_for_unnamed_segment():
    _get_qapp()
    group = _make_unnamed_group()
    dialog = PressurePipeConfigDialog(
        pipe_groups=[group],
        manager=_FakeManager(group.storage_key, _make_longitudinal_nodes()),
    )
    dialog.show()
    _flush_events(6)

    assert group.storage_key in dialog._card_widgets
    assert dialog._resolve_pipe_label(group.storage_key) == group.display_name
    assert group.storage_key in dialog.get_longitudinal_nodes_dict()

    titles = [box.title() for box in dialog.findChildren(QGroupBox)]
    assert any(group.display_name in title for title in titles)

    dialog.close()
    dialog.deleteLater()


def test_pressure_pipe_config_dialog_uses_storage_key_for_unnamed_segments():
    _get_qapp()
    group = _make_unnamed_group()
    dialog = PressurePipeConfigDialog(
        pipe_groups=[group],
        manager=_FakeManager(group.storage_key, _make_longitudinal_nodes()),
    )
    dialog.show()
    _flush_events(6)

    assert group.storage_key in dialog._card_widgets
    assert dialog._card_widgets[group.storage_key]["display_name"] == group.display_name
    assert group.storage_key in dialog.get_longitudinal_nodes_dict()

    dialog.close()
    dialog.deleteLater()
