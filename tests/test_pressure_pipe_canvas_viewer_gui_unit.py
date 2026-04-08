"""有压管道预览画布双击放大 GUI 单元测试。"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QGroupBox, QLabel, QPushButton, QFileDialog, QMessageBox

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "calc_渠系计算算法内核") not in sys.path:
    sys.path.insert(0, str(ROOT / "calc_渠系计算算法内核"))

import app_渠系计算前端.water_profile.water_profile_dialogs as dialog_mod
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
    def __init__(self, pipe_name: str, nodes, route_key: str = "", route_display_name: str = ""):
        self._routes = {}
        if route_key:
            self._routes[route_key] = {
                "display_name": route_display_name,
                "longitudinal_nodes": list(nodes),
            }
        self._configs = {
            pipe_name: SimpleNamespace(
                longitudinal_nodes=list(nodes),
                route_key=route_key,
                route_display_name=route_display_name,
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
        route_key = str(getattr(config, "route_key", "") or "").strip()
        if route_key:
            self._routes.setdefault(route_key, {})
            self._routes[route_key]["display_name"] = str(
                getattr(config, "route_display_name", "") or self._routes[route_key].get("display_name", "")
            ).strip()
            self._routes[route_key]["longitudinal_nodes"] = list(
                getattr(config, "longitudinal_nodes", []) or []
            )

    def set_route_longitudinal_nodes(self, route_key, longitudinal_nodes, route_display_name=""):
        route_key = str(route_key or "").strip()
        if not route_key:
            return
        self._routes.setdefault(route_key, {})
        self._routes[route_key]["display_name"] = str(
            route_display_name or self._routes[route_key].get("display_name", "")
        ).strip()
        self._routes[route_key]["longitudinal_nodes"] = list(longitudinal_nodes or [])

    def to_dict(self):
        return {
            "pipes": {
                key: {
                    "longitudinal_nodes": list(getattr(cfg, "longitudinal_nodes", []) or []),
                    "route_key": str(getattr(cfg, "route_key", "") or "").strip(),
                    "route_display_name": str(getattr(cfg, "route_display_name", "") or "").strip(),
                }
                for key, cfg in self._configs.items()
            },
            "routes": {
                key: {
                    "display_name": str(value.get("display_name", "") or "").strip(),
                    "longitudinal_nodes": list(value.get("longitudinal_nodes", []) or []),
                }
                for key, value in self._routes.items()
            },
        }

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


def _make_chain_descriptors(group):
    return [
        {
            "chain_id": "flow2-chain1",
            "flow_section": "2",
            "display_name": "流量段2 连续承压链1",
            "start_row_index": 0,
            "end_row_index": 2,
            "members": [
                SimpleNamespace(
                    group=group,
                    display_name=group.name,
                    structure_type="有压管道",
                    target_row_index=0,
                ),
                SimpleNamespace(
                    group=None,
                    display_name="半兽人",
                    structure_type="隧洞",
                    target_row_index=5,
                ),
            ],
        }
    ]


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


def test_pressure_pipe_config_dialog_groups_cards_by_chain():
    _get_qapp()
    group = _make_group()
    dialog = PressurePipeConfigDialog(
        pipe_groups=[group],
        manager=_FakeManager(group.name, _make_longitudinal_nodes()),
        pressure_chains=_make_chain_descriptors(group),
    )
    dialog.show()
    _flush_events(6)

    titles = [box.title() for box in dialog.findChildren(QGroupBox)]
    assert "链路: 流量段2 连续承压链1" in titles
    assert "管道: 测试管道" in titles

    label_texts = [label.text() for label in dialog.findChildren(QLabel)]
    assert any("本成员参与连续承压链计算" in text for text in label_texts)

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


def _make_route_groups(
    route_key: str = "flow2-route1",
    display_name: str = "流量段2 整线1",
    flow_section: str = "2",
):
    route_points = [
        {"x": 0.0, "y": 0.0, "turn_angle": 0.0},
        {"x": 20.0, "y": 0.0, "turn_angle": 0.0},
        {"x": 50.0, "y": 15.0, "turn_angle": 12.0},
        {"x": 80.0, "y": 15.0, "turn_angle": 0.0},
    ]
    long_nodes = _make_longitudinal_nodes()
    group1 = SimpleNamespace(
        name="穿路段",
        display_name="穿路段",
        storage_key="穿路段",
        identity=f"{flow_section}::穿路段",
        route_key=route_key,
        route_display_name=display_name,
        route_ip_points=list(route_points),
        route_start_mc=0.0,
        route_end_mc=80.0,
        route_start_row_index=1,
        route_end_row_index=5,
        segment_start_mc=0.0,
        segment_end_mc=20.0,
        group_mode="named_group",
        design_flow=1.2,
        diameter=1.0,
        material_key="钢管",
        ip_points=[route_points[0], route_points[1]],
        rows=[SimpleNamespace(section_params={"D": 1.0}, turn_radius=0.0, flow_section=flow_section) for _ in range(2)],
        row_indices=[1, 2],
    )
    group2 = SimpleNamespace(
        name="",
        display_name=f"流量段{flow_section} 第6行有压管道",
        storage_key=f"flow{flow_section}-row6",
        identity=f"flow{flow_section}-row6",
        route_key=route_key,
        route_display_name=display_name,
        route_ip_points=list(route_points),
        route_start_mc=0.0,
        route_end_mc=80.0,
        route_start_row_index=1,
        route_end_row_index=5,
        segment_start_mc=50.0,
        segment_end_mc=80.0,
        group_mode="unnamed_row_segment",
        design_flow=1.2,
        diameter=1.0,
        material_key="钢管",
        ip_points=[route_points[2], route_points[3]],
        rows=[SimpleNamespace(section_params={"D": 1.0}, turn_radius=0.0, flow_section=flow_section)],
        row_indices=[5],
        target_row_index=5,
        upstream_row_index=4,
    )
    manager = _FakeManager(group1.storage_key, long_nodes, route_key=route_key, route_display_name=display_name)
    manager.set_pipe_config(
        group2.storage_key,
        SimpleNamespace(
            longitudinal_nodes=list(long_nodes),
            route_key=route_key,
            route_display_name=display_name,
            turn_n=0.0,
            turn_R=0.0,
            force_override=False,
            radius_applied_at="",
        ),
    )
    return route_key, [group1, group2], manager


def _make_mixed_route_groups():
    route_key = "flow2-route-mixed"
    display_name = "流量段2 整线夹带隧洞"
    route_points = [
        {"x": 0.0, "y": 0.0, "turn_angle": 0.0},
        {"x": 20.0, "y": 0.0, "turn_angle": 0.0},
        {"x": 60.0, "y": 0.0, "turn_angle": 0.0},
        {"x": 100.0, "y": 0.0, "turn_angle": 0.0},
    ]
    pipe_group = SimpleNamespace(
        name="穿路段",
        display_name="穿路段",
        storage_key="flow2-mixed-pipe-a",
        identity="2::穿路段",
        route_key=route_key,
        route_display_name=display_name,
        route_ip_points=list(route_points),
        route_start_mc=0.0,
        route_end_mc=100.0,
        route_start_row_index=1,
        route_end_row_index=6,
        segment_start_mc=20.0,
        segment_end_mc=40.0,
        group_mode="named_group",
        structure_type="有压管道",
        design_flow=1.2,
        diameter=1.0,
        material_key="钢管",
        ip_points=[route_points[1], {"x": 40.0, "y": 0.0, "turn_angle": 0.0}],
        rows=[SimpleNamespace(section_params={"D": 1.0}, turn_radius=0.0, flow_section="2") for _ in range(2)],
        row_indices=[2, 3],
    )
    tunnel_group = SimpleNamespace(
        name="穿山段",
        display_name="穿山段隧洞",
        storage_key="flow2-mixed-tunnel",
        identity="flow2-mixed-tunnel",
        route_key=route_key,
        route_display_name=display_name,
        route_ip_points=list(route_points),
        route_start_mc=0.0,
        route_end_mc=100.0,
        route_start_row_index=1,
        route_end_row_index=6,
        segment_start_mc=0.0,
        segment_end_mc=20.0,
        group_mode="named_group",
        structure_type="隧洞-圆形",
        design_flow=1.2,
        diameter=2.4,
        material_key="隧洞",
        ip_points=[route_points[0], route_points[1]],
        rows=[SimpleNamespace(section_params={"D": 2.4}, turn_radius=0.0, flow_section="2") for _ in range(2)],
        row_indices=[0, 1],
        tunnel_invert_inlet=420.0,
        tunnel_slope_i=0.01,
        tunnel_invert_outlet_check=419.8,
        tunnel_section_type="圆形隧洞",
        tunnel_section_params={"D": 2.4},
    )
    pipe_group_b = SimpleNamespace(
        name="穿路段B",
        display_name="穿路段B",
        storage_key="flow2-mixed-pipe-b",
        identity="2::穿路段B",
        route_key=route_key,
        route_display_name=display_name,
        route_ip_points=list(route_points),
        route_start_mc=0.0,
        route_end_mc=100.0,
        route_start_row_index=1,
        route_end_row_index=6,
        segment_start_mc=60.0,
        segment_end_mc=100.0,
        group_mode="named_group",
        structure_type="顶管",
        design_flow=1.2,
        diameter=1.0,
        material_key="钢管",
        ip_points=[route_points[2], route_points[3]],
        rows=[SimpleNamespace(section_params={"D": 1.0}, turn_radius=0.0, flow_section="2") for _ in range(2)],
        row_indices=[4, 5],
    )
    manager = _FakeManager(route_key, [], route_key=route_key, route_display_name=display_name)
    return route_key, [tunnel_group, pipe_group, pipe_group_b], manager


def test_pressure_pipe_config_dialog_builds_single_route_card_for_xxpipe_groups():
    _get_qapp()
    route_key, groups, manager = _make_route_groups()
    dialog = PressurePipeConfigDialog(
        pipe_groups=groups,
        manager=manager,
    )
    dialog.show()
    _flush_events(6)

    assert hasattr(dialog, "_route_widgets")
    assert route_key in dialog._route_widgets
    assert len(dialog._route_widgets) == 1
    assert len(dialog._card_widgets) == 2
    assert route_key in dialog.get_longitudinal_nodes_dict()

    route_canvas = dialog._route_widgets[route_key]["canvas"]
    assert route_canvas.has_plan_data() is True

    titles = [box.title() for box in dialog.findChildren(QGroupBox)]
    assert any("整线1" in title for title in titles)
    assert any(groups[0].display_name in title for title in titles)

    dialog.close()
    dialog.deleteLater()


def test_pressure_pipe_config_dialog_hides_chain_and_segment_cards_in_xxpipe_route_mode():
    _get_qapp()
    route_key, groups, manager = _make_route_groups()
    dialog = PressurePipeConfigDialog(
        pipe_groups=groups,
        manager=manager,
        pressure_chains=_make_chain_descriptors(groups[0]),
        xxpipe_route_mode=True,
    )
    dialog.show()
    _flush_events(6)

    assert hasattr(dialog, "_route_widgets")
    assert route_key in dialog._route_widgets
    assert len(dialog._route_widgets) == 1
    assert dialog._card_widgets == {}
    assert route_key in dialog.get_longitudinal_nodes_dict()

    titles = [box.title() for box in dialog.findChildren(QGroupBox)]
    assert titles == ["链路: 流量段2 整线1"]

    label_texts = [label.text() for label in dialog.findChildren(QLabel)]
    assert any("整线卡负责统一导入平面/纵断面" in text for text in label_texts)
    assert not any("本成员参与连续承压链计算" in text for text in label_texts)
    assert not any("平面R已应用" in text for text in label_texts)

    button_texts = [btn.text() for btn in dialog.findChildren(QPushButton)]
    assert "应用到全部管道" not in button_texts

    dialog.close()
    dialog.deleteLater()


def test_pressure_pipe_config_dialog_keeps_route_card_and_tunnel_segment_cards_for_mixed_xxpipe_route():
    _get_qapp()
    route_key, groups, manager = _make_mixed_route_groups()
    dialog = PressurePipeConfigDialog(
        pipe_groups=groups,
        manager=manager,
        xxpipe_route_mode=True,
    )
    dialog.show()
    _flush_events(6)

    assert route_key in dialog._route_widgets
    assert list(dialog._card_widgets) == ["flow2-mixed-tunnel"]

    titles = [box.title() for box in dialog.findChildren(QGroupBox)]
    assert "链路: 流量段2 整线夹带隧洞" in titles
    assert "管道: 穿山段隧洞" in titles

    dialog.close()
    dialog.deleteLater()


def test_pressure_pipe_config_dialog_accept_persists_tunnel_parameters_for_mixed_xxpipe():
    _get_qapp()
    route_key, groups, manager = _make_mixed_route_groups()
    dialog = PressurePipeConfigDialog(
        pipe_groups=groups,
        manager=manager,
        xxpipe_route_mode=True,
    )
    dialog._longitudinal_data[route_key] = _make_longitudinal_nodes()
    dialog.show()
    _flush_events(6)

    widgets = dialog._card_widgets["flow2-mixed-tunnel"]
    widgets["tunnel_section_type_combo"].setCurrentText("圆拱直墙型隧洞")
    _flush_events(2)
    widgets["tunnel_invert_edit"].setText("421.5")
    widgets["tunnel_slope_edit"].setText("0.012")
    widgets["tunnel_outlet_check_edit"].setText("420.3")
    widgets["tunnel_param_a_edit"].setText("3.2")
    widgets["tunnel_param_b_edit"].setText("4.5")

    dialog.accept()
    _flush_events(4)

    tunnel_group = groups[0]
    assert dialog.result() == QDialog.Accepted
    assert tunnel_group.segment_geometry_source == "generated_tunnel"
    assert tunnel_group.tunnel_invert_inlet == pytest.approx(421.5)
    assert tunnel_group.tunnel_slope_i == pytest.approx(0.012)
    assert tunnel_group.tunnel_invert_outlet_check == pytest.approx(420.3)
    assert tunnel_group.tunnel_section_type == "圆拱直墙型隧洞"
    assert tunnel_group.tunnel_section_params == {"B": 3.2, "H": 4.5}

    saved = manager.get_pipe_config("flow2-mixed-tunnel")
    assert saved is not None
    assert saved.segment_geometry_source == "generated_tunnel"
    assert saved.tunnel_invert_inlet == pytest.approx(421.5)
    assert saved.tunnel_slope_i == pytest.approx(0.012)
    assert saved.tunnel_invert_outlet_check == pytest.approx(420.3)
    assert saved.tunnel_section_type == "圆拱直墙型隧洞"
    assert saved.tunnel_section_params == {"B": 3.2, "H": 4.5}

    dialog.close()
    dialog.deleteLater()


def test_pressure_pipe_config_dialog_rejects_missing_tunnel_parameters_before_accept(monkeypatch):
    _get_qapp()
    route_key, groups, manager = _make_mixed_route_groups()
    dialog = PressurePipeConfigDialog(
        pipe_groups=groups,
        manager=manager,
        xxpipe_route_mode=True,
    )
    dialog._longitudinal_data[route_key] = _make_longitudinal_nodes()
    dialog.show()
    _flush_events(6)

    widgets = dialog._card_widgets["flow2-mixed-tunnel"]
    widgets["tunnel_invert_edit"].setText("")
    errors = []
    monkeypatch.setattr(dialog_mod, "fluent_error", lambda *_args: errors.append(_args[2]))

    dialog.accept()
    _flush_events(2)

    assert errors
    assert "进口底高" in errors[0]
    assert dialog.result() == 0

    dialog.close()
    dialog.deleteLater()


def test_pressure_pipe_config_dialog_rejects_route_import_when_station_coverage_is_incomplete():
    _get_qapp()
    route_key, groups, manager = _make_route_groups()
    route_nodes = [
        SimpleNamespace(
            name="穿路段",
            flow_section="2",
            ip_number=1,
            structure_type=SimpleNamespace(value="有压管道"),
            in_out=SimpleNamespace(value="进"),
            station_MC=0.0,
            x=0.0,
            y=0.0,
            is_transition=False,
            is_auto_inserted_channel=False,
        ),
        SimpleNamespace(
            name="穿路段",
            flow_section="2",
            ip_number=2,
            structure_type=SimpleNamespace(value="有压管道"),
            in_out=SimpleNamespace(value=""),
            station_MC=50.0,
            x=50.0,
            y=0.0,
            is_transition=False,
            is_auto_inserted_channel=False,
        ),
        SimpleNamespace(
            name="穿路段",
            flow_section="2",
            ip_number=3,
            structure_type=SimpleNamespace(value="有压管道"),
            in_out=SimpleNamespace(value="出"),
            station_MC=80.0,
            x=80.0,
            y=0.0,
            is_transition=False,
            is_auto_inserted_channel=False,
        ),
    ]
    dialog = PressurePipeConfigDialog(
        pipe_groups=groups,
        manager=manager,
        xxpipe_route_mode=True,
        route_import_targets={
            route_key: {
                "display_name": "流量段2 整线1",
                "station_prefix": "",
                "nodes": route_nodes,
            }
        },
    )

    with pytest.raises(ValueError, match="未覆盖以下节点桩号"):
        dialog._validate_xxpipe_route_import_coverage(
            route_key,
            [
                {"chainage": 0.0, "elevation": 422.0, "turn_type": "NONE"},
                {"chainage": 40.0, "elevation": 418.0, "turn_type": "NONE"},
            ],
        )

    dialog.close()
    dialog.deleteLater()


def test_pressure_pipe_config_dialog_clears_stale_saved_route_longitudinal_cache_on_load():
    _get_qapp()
    route_key, groups, _manager = _make_route_groups(
        route_key="三清庙",
        display_name="三清庙",
        flow_section="1",
    )
    stale_nodes = [
        {
            "chainage": 0.0,
            "elevation": 422.0,
            "vertical_curve_radius": 0.0,
            "turn_type": "NONE",
            "turn_angle": 0.0,
        },
        {
            "chainage": 40.0,
            "elevation": 418.0,
            "vertical_curve_radius": 0.0,
            "turn_type": "NONE",
            "turn_angle": 0.0,
        },
    ]
    manager = _FakeManager(route_key, stale_nodes, route_key=route_key, route_display_name="三清庙")
    for group in groups:
        manager.set_pipe_config(
            group.storage_key,
            SimpleNamespace(
                longitudinal_nodes=list(stale_nodes),
                route_key=route_key,
                route_display_name="三清庙",
                turn_n=0.0,
                turn_R=0.0,
                force_override=False,
                radius_applied_at="",
            ),
        )
    route_nodes = [
        SimpleNamespace(
            name="三清庙",
            flow_section="1",
            ip_number=1,
            structure_type=SimpleNamespace(value="有压管道"),
            in_out=SimpleNamespace(value="进"),
            station_MC=0.0,
            x=0.0,
            y=0.0,
            is_transition=False,
            is_auto_inserted_channel=False,
        ),
        SimpleNamespace(
            name="三清庙",
            flow_section="1",
            ip_number=2,
            structure_type=SimpleNamespace(value="有压管道"),
            in_out=SimpleNamespace(value=""),
            station_MC=50.0,
            x=50.0,
            y=0.0,
            is_transition=False,
            is_auto_inserted_channel=False,
        ),
        SimpleNamespace(
            name="三清庙",
            flow_section="1",
            ip_number=3,
            structure_type=SimpleNamespace(value="有压管道"),
            in_out=SimpleNamespace(value="出"),
            station_MC=80.0,
            x=80.0,
            y=0.0,
            is_transition=False,
            is_auto_inserted_channel=False,
        ),
    ]
    dialog = PressurePipeConfigDialog(
        pipe_groups=groups,
        manager=manager,
        xxpipe_route_mode=True,
        route_import_targets={
            route_key: {
                "display_name": "三清庙",
                "station_prefix": "",
                "nodes": route_nodes,
            }
        },
    )
    dialog.show()
    _flush_events(6)

    assert route_key not in dialog.get_longitudinal_nodes_dict()
    assert "重新导入" in dialog._route_widgets[route_key]["hint"].text()
    saved_routes = manager.to_dict().get("routes", {})
    assert saved_routes.get(route_key, {}).get("longitudinal_nodes", []) == []
    saved_pipes = manager.to_dict().get("pipes", {})
    for group in groups:
        assert saved_pipes.get(group.storage_key, {}).get("longitudinal_nodes", []) == []

    dialog.close()
    dialog.deleteLater()


def test_pressure_pipe_config_dialog_route_import_coverage_ignores_tunnel_start_segment():
    _get_qapp()
    route_key, groups, manager = _make_mixed_route_groups()
    route_nodes = [
        SimpleNamespace(
            name="穿山段",
            flow_section="2",
            ip_number=1,
            structure_type=SimpleNamespace(value="隧洞-圆形"),
            in_out=SimpleNamespace(value="进"),
            station_MC=0.0,
            x=0.0,
            y=0.0,
            is_transition=False,
            is_auto_inserted_channel=False,
        ),
        SimpleNamespace(
            name="穿路段",
            flow_section="2",
            ip_number=2,
            structure_type=SimpleNamespace(value="有压管道"),
            in_out=SimpleNamespace(value="进"),
            station_MC=20.0,
            x=20.0,
            y=0.0,
            is_transition=False,
            is_auto_inserted_channel=False,
        ),
        SimpleNamespace(
            name="穿路段B",
            flow_section="2",
            ip_number=3,
            structure_type=SimpleNamespace(value="顶管"),
            in_out=SimpleNamespace(value="出"),
            station_MC=100.0,
            x=100.0,
            y=0.0,
            is_transition=False,
            is_auto_inserted_channel=False,
        ),
    ]
    dialog = PressurePipeConfigDialog(
        pipe_groups=groups,
        manager=manager,
        xxpipe_route_mode=True,
        route_import_targets={
            route_key: {
                "display_name": "流量段2 整线夹带隧洞",
                "station_prefix": "",
                "nodes": route_nodes,
            }
        },
    )

    dialog._validate_xxpipe_route_import_coverage(
        route_key,
        [
            {"chainage": 20.0, "elevation": 418.0, "turn_type": "NONE"},
            {"chainage": 100.0, "elevation": 410.0, "turn_type": "NONE"},
        ],
    )

    dialog.close()
    dialog.deleteLater()


def test_pressure_pipe_config_dialog_resolves_import_anchor_from_first_non_tunnel_station_fallback():
    _get_qapp()
    route_key, groups, manager = _make_mixed_route_groups()
    route_nodes = [
        SimpleNamespace(
            name="穿山段",
            flow_section="2",
            ip_number=1,
            structure_type=SimpleNamespace(value="隧洞-圆形"),
            in_out=SimpleNamespace(value="进"),
            station_MC=0.0,
            x=0.0,
            y=0.0,
            is_transition=False,
            is_auto_inserted_channel=False,
        ),
        SimpleNamespace(
            name="穿路段",
            flow_section="2",
            ip_number=2,
            structure_type=SimpleNamespace(value="有压管道"),
            in_out=SimpleNamespace(value="进"),
            station_MC=None,
            x=20.0,
            y=0.0,
            is_transition=False,
            is_auto_inserted_channel=False,
        ),
        SimpleNamespace(
            name="穿路段B",
            flow_section="2",
            ip_number=3,
            structure_type=SimpleNamespace(value="顶管"),
            in_out=SimpleNamespace(value="出"),
            station_MC=60.0,
            x=60.0,
            y=0.0,
            is_transition=False,
            is_auto_inserted_channel=False,
        ),
    ]
    dialog = PressurePipeConfigDialog(
        pipe_groups=groups,
        manager=manager,
        xxpipe_route_mode=True,
        route_import_targets={
            route_key: {
                "display_name": "流量段2 整线夹带隧洞",
                "station_prefix": "",
                "nodes": route_nodes,
            }
        },
    )

    assert dialog._resolve_xxpipe_route_import_anchor_station(
        route_key,
        groups[0].route_ip_points,
    ) == pytest.approx(20.0)

    dialog.close()
    dialog.deleteLater()


def test_pressure_pipe_config_dialog_rejects_xxpipe_import_when_coverage_is_incomplete(monkeypatch):
    _get_qapp()
    route_key, groups, _manager = _make_route_groups()
    route_nodes = [
        SimpleNamespace(
            ip_number=1,
            name="穿路段",
            flow_section="2",
            station_MC=0.0,
            x=0.0,
            y=0.0,
            structure_type=SimpleNamespace(value="有压管道"),
            pressure_pipe_row_identity="2::穿路段",
            is_transition=False,
            is_auto_inserted_channel=False,
        ),
        SimpleNamespace(
            ip_number=2,
            name="穿路段",
            flow_section="2",
            station_MC=80.0,
            x=80.0,
            y=0.0,
            structure_type=SimpleNamespace(value="有压管道"),
            pressure_pipe_row_identity="2::穿路段",
            is_transition=False,
            is_auto_inserted_channel=False,
        ),
    ]
    dialog = PressurePipeConfigDialog(
        pipe_groups=groups,
        manager=_FakeManager("unused", []),
        xxpipe_route_mode=True,
        route_import_targets={
            route_key: {
                "display_name": "流量段2 整线1",
                "station_prefix": "",
                "nodes": route_nodes,
            }
        },
    )

    class _FakePolyline:
        def get_points(self, format="xyseb"):
            return [(0.0, 0.0, 0.0, 0.0, 0.0)]

    class _FakeModelSpace:
        def query(self, _query_text):
            return [_FakePolyline()]

    class _FakeDoc:
        def modelspace(self):
            return _FakeModelSpace()

    class _FakeParser:
        @staticmethod
        def parse_longitudinal_profile(_filepath, chainage_offset=0.0):
            assert chainage_offset == 0.0
            turn_type = SimpleNamespace(name="NONE")
            return (
                [
                    SimpleNamespace(
                        chainage=0.0,
                        elevation=422.0,
                        vertical_curve_radius=0.0,
                        turn_type=turn_type,
                        turn_angle=0.0,
                        slope_before=0.0,
                        slope_after=0.0,
                        arc_center_s=None,
                        arc_center_z=None,
                        arc_end_chainage=None,
                        arc_theta_rad=None,
                    ),
                    SimpleNamespace(
                        chainage=50.0,
                        elevation=418.0,
                        vertical_curve_radius=0.0,
                        turn_type=turn_type,
                        turn_angle=0.0,
                        slope_before=0.0,
                        slope_after=0.0,
                        arc_center_s=None,
                        arc_center_z=None,
                        arc_end_chainage=None,
                        arc_theta_rad=None,
                    ),
                ],
                "测试导入",
            )

    errors = []
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *_a, **_k: ("fake.dxf", "DXF")))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *_a: errors.append(_a[2])))
    monkeypatch.setitem(sys.modules, "ezdxf", SimpleNamespace(readfile=lambda *_a, **_k: _FakeDoc()))
    monkeypatch.setitem(sys.modules, "dxf_parser", SimpleNamespace(DxfParser=_FakeParser))

    dialog._import_longitudinal_dxf(route_key, groups[0].route_ip_points)

    assert errors
    assert "未覆盖以下节点桩号" in errors[0]
    assert "IP2@0+080.000" in errors[0]
    assert route_key not in dialog.get_longitudinal_nodes_dict()

    dialog.close()
    dialog.deleteLater()


def test_pressure_pipe_config_dialog_blocks_xxpipe_accept_without_longitudinal_and_highlights_route(monkeypatch):
    _get_qapp()
    route_key, groups, _manager = _make_route_groups()
    dialog = PressurePipeConfigDialog(
        pipe_groups=groups,
        manager=_FakeManager("unused", []),
        xxpipe_route_mode=True,
    )
    dialog.show()
    _flush_events(6)

    errors = []
    monkeypatch.setattr(dialog_mod, "fluent_error", lambda *_a, **_k: errors.append(_a[2]))

    dialog.accept()
    _flush_events(4)

    assert errors
    assert "还差一步：请先为“流量段2 整线1”导入纵断面DXF，然后再开始计算。" in errors[0]
    assert "flow2-route1" not in errors[0]
    assert "flow2-row6" not in errors[0]
    assert dialog.result() != QDialog.Accepted
    assert dialog._route_widgets[route_key]["card"].property("missing_longitudinal_highlight") is True
    assert dialog._route_widgets[route_key]["btn_import"].property("missing_longitudinal_highlight") is True

    dialog.close()
    dialog.deleteLater()


def test_pressure_pipe_config_dialog_route_import_persists_manager_before_accept(monkeypatch):
    _get_qapp()
    route_key, groups, _manager = _make_route_groups()
    manager = _FakeManager("unused", [])
    route_nodes = [
        SimpleNamespace(
            name="穿路段",
            flow_section="2",
            ip_number=1,
            structure_type=SimpleNamespace(value="有压管道"),
            in_out=SimpleNamespace(value="进"),
            station_MC=0.0,
            x=0.0,
            y=0.0,
            is_transition=False,
            is_auto_inserted_channel=False,
        ),
        SimpleNamespace(
            name="穿路段",
            flow_section="2",
            ip_number=2,
            structure_type=SimpleNamespace(value="有压管道"),
            in_out=SimpleNamespace(value=""),
            station_MC=50.0,
            x=50.0,
            y=0.0,
            is_transition=False,
            is_auto_inserted_channel=False,
        ),
        SimpleNamespace(
            name="穿路段",
            flow_section="2",
            ip_number=3,
            structure_type=SimpleNamespace(value="有压管道"),
            in_out=SimpleNamespace(value="出"),
            station_MC=80.0,
            x=80.0,
            y=0.0,
            is_transition=False,
            is_auto_inserted_channel=False,
        ),
    ]
    dialog = PressurePipeConfigDialog(
        pipe_groups=groups,
        manager=manager,
        xxpipe_route_mode=True,
        route_import_targets={
            route_key: {
                "display_name": "流量段2 整线1",
                "station_prefix": "",
                "nodes": route_nodes,
            }
        },
    )

    class _FakePolyline:
        def get_points(self, format="xyseb"):
            return [(0.0, 0.0, 0.0, 0.0, 0.0)]

    class _FakeModelSpace:
        def query(self, _query_text):
            return [_FakePolyline()]

    class _FakeDoc:
        def modelspace(self):
            return _FakeModelSpace()

    class _FakeParser:
        @staticmethod
        def parse_longitudinal_profile(_filepath, chainage_offset=0.0):
            assert chainage_offset == 0.0
            turn_type = SimpleNamespace(name="NONE")
            return (
                [
                    SimpleNamespace(
                        chainage=0.0,
                        elevation=422.0,
                        vertical_curve_radius=0.0,
                        turn_type=turn_type,
                        turn_angle=0.0,
                        slope_before=0.0,
                        slope_after=0.0,
                        arc_center_s=None,
                        arc_center_z=None,
                        arc_end_chainage=None,
                        arc_theta_rad=None,
                    ),
                    SimpleNamespace(
                        chainage=50.0,
                        elevation=418.0,
                        vertical_curve_radius=0.0,
                        turn_type=turn_type,
                        turn_angle=0.0,
                        slope_before=0.0,
                        slope_after=0.0,
                        arc_center_s=None,
                        arc_center_z=None,
                        arc_end_chainage=None,
                        arc_theta_rad=None,
                    ),
                    SimpleNamespace(
                        chainage=80.0,
                        elevation=415.0,
                        vertical_curve_radius=0.0,
                        turn_type=turn_type,
                        turn_angle=0.0,
                        slope_before=0.0,
                        slope_after=0.0,
                        arc_center_s=None,
                        arc_center_z=None,
                        arc_end_chainage=None,
                        arc_theta_rad=None,
                    ),
                ],
                "测试导入",
            )

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *_a, **_k: ("fake.dxf", "DXF")))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *_a: None))
    monkeypatch.setattr(dialog_mod, "fluent_info", lambda *_args, **_kwargs: None)
    monkeypatch.setitem(sys.modules, "ezdxf", SimpleNamespace(readfile=lambda *_a, **_k: _FakeDoc()))
    monkeypatch.setitem(sys.modules, "dxf_parser", SimpleNamespace(DxfParser=_FakeParser))

    dialog._import_longitudinal_dxf(route_key, groups[0].route_ip_points)

    saved_routes = manager.to_dict().get("routes", {})
    assert route_key in dialog.get_longitudinal_nodes_dict()
    assert saved_routes.get(route_key, {}).get("longitudinal_nodes", []) == dialog.get_longitudinal_nodes_dict()[route_key]

    dialog.close()
    dialog.deleteLater()


def test_pressure_pipe_config_dialog_aggregates_missing_xxpipe_routes_without_internal_ids(monkeypatch):
    _get_qapp()
    route_key1, groups1, _manager1 = _make_route_groups()
    route_key2, groups2, _manager2 = _make_route_groups(
        route_key="flow3-route1",
        display_name="流量段3 整线1",
        flow_section="3",
    )
    dialog = PressurePipeConfigDialog(
        pipe_groups=groups1 + groups2,
        manager=_FakeManager("unused", []),
        xxpipe_route_mode=True,
    )
    dialog.show()
    _flush_events(6)

    errors = []
    monkeypatch.setattr(dialog_mod, "fluent_error", lambda *_a, **_k: errors.append(_a[2]))

    dialog.accept()
    _flush_events(4)

    assert errors
    assert "以下整线还没有导入纵断面DXF" in errors[0]
    assert "流量段2 整线1" in errors[0]
    assert "流量段3 整线1" in errors[0]
    assert route_key1 not in errors[0]
    assert route_key2 not in errors[0]
    assert "flow2-row6" not in errors[0]
    assert "flow3-row6" not in errors[0]

    dialog.close()
    dialog.deleteLater()


def test_pressure_pipe_config_dialog_clears_xxpipe_highlight_after_import_and_accepts(monkeypatch):
    _get_qapp()
    route_key, groups, _manager = _make_route_groups()
    dialog = PressurePipeConfigDialog(
        pipe_groups=groups,
        manager=_FakeManager("unused", []),
        xxpipe_route_mode=True,
    )
    dialog.show()
    _flush_events(6)

    errors = []
    monkeypatch.setattr(dialog_mod, "fluent_error", lambda *_a, **_k: errors.append(_a[2]))

    dialog.accept()
    _flush_events(4)

    dialog._longitudinal_data[route_key] = _make_longitudinal_nodes()
    dialog._update_card_data_state(route_key, show_data=True)
    _flush_events(4)
    dialog.accept()
    _flush_events(4)

    assert len(errors) == 1
    assert dialog._route_widgets[route_key]["card"].property("missing_longitudinal_highlight") in (False, None)
    assert dialog._route_widgets[route_key]["btn_import"].property("missing_longitudinal_highlight") in (False, None)
    assert dialog.result() == QDialog.Accepted

    dialog.close()
    dialog.deleteLater()


def test_pressure_pipe_config_dialog_does_not_block_non_xxpipe_accept_without_longitudinal(monkeypatch):
    _get_qapp()
    route_key, groups, _manager = _make_route_groups()
    dialog = PressurePipeConfigDialog(
        pipe_groups=groups,
        manager=_FakeManager("unused", []),
        xxpipe_route_mode=False,
    )
    dialog.show()
    _flush_events(6)

    errors = []
    monkeypatch.setattr(dialog_mod, "fluent_error", lambda *_a, **_k: errors.append(_a[2]))

    dialog.accept()
    _flush_events(4)

    assert errors == []
    assert dialog.result() == QDialog.Accepted
    assert dialog._route_widgets[route_key]["card"].property("missing_longitudinal_highlight") in (False, None)

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
