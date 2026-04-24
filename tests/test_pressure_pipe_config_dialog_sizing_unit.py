"""有压管道配置弹窗默认尺寸自适应单元测试。"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication, QAbstractButton, QScrollArea

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "calc_渠系计算算法内核"))

from app_渠系计算前端.water_profile.water_profile_dialogs import PressurePipeConfigDialog


def _get_qapp():
    return QApplication.instance() or QApplication([])


def _flush_events(rounds: int = 6):
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


def test_pressure_pipe_config_dialog_keeps_action_buttons_visible_on_small_screen(monkeypatch):
    _get_qapp()
    monkeypatch.setattr(
        PressurePipeConfigDialog,
        "_available_geometry",
        lambda self: QRect(0, 0, 1600, 900),
        raising=False,
    )

    group = _make_group()
    dialog = PressurePipeConfigDialog(
        pipe_groups=[group],
        manager=_FakeManager(group.name, _make_longitudinal_nodes()),
    )
    dialog.show()
    _flush_events(8)

    scroll_areas = dialog.findChildren(QScrollArea)
    assert scroll_areas, "应存在承载管道卡片的滚动区域"
    scroll = scroll_areas[0]
    vbar = scroll.verticalScrollBar()

    buttons = {button.text(): button for button in dialog.findChildren(QAbstractButton)}
    assert "取消" in buttons
    assert "开始计算" in buttons

    max_comfort_height = int(900 * 0.85)
    assert dialog.height() <= max_comfort_height
    assert vbar.maximum() > 0
    for button_text in ("取消", "开始计算"):
        button = buttons[button_text]
        bottom_in_dialog = button.mapTo(dialog, button.rect().bottomRight()).y()
        assert button.isVisible()
        assert bottom_in_dialog <= dialog.rect().bottom()

    dialog.close()
    dialog.deleteLater()
