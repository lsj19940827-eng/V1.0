# -*- coding: utf-8 -*-
"""验证泄水渠占位行到表3的加大工况传递和工程恢复。"""

import copy
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault("CODEX_FORCE_QTEXTBROWSER", "1")
ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "推求水面线"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from PySide6.QtWidgets import QApplication

import app_渠系计算前端.batch.panel as batch_module
import app_渠系计算前端.water_profile.panel as water_module
from core.calculator import WaterProfileCalculator
from core.spillway_steep_chute_adapter import SPILLWAY_STEEP_CHUTE_PARAM_KEY
from models.data_models import ChannelNode, ProjectSettings
from models.enums import StructureType


@pytest.fixture
def panels(monkeypatch):
    """使用真实表格和共享数据转换，屏蔽测试期间的通知。"""
    app = QApplication.instance() or QApplication([])
    notices = SimpleNamespace(**{name: lambda *args, **kwargs: None for name in ("success", "warning", "error", "info")})
    monkeypatch.setattr(batch_module, "InfoBar", notices)
    monkeypatch.setattr(batch_module, "fluent_batch_result", lambda *args, **kwargs: None)
    monkeypatch.setattr(batch_module, "fluent_info", lambda *args, **kwargs: None)
    monkeypatch.setattr(water_module, "InfoBar", notices)
    manager = batch_module.get_shared_data_manager()
    monkeypatch.setattr(manager, "_batch_results", [])
    monkeypatch.setattr(manager, "_listeners", [])
    monkeypatch.setattr(water_module, "get_shared_data_manager", lambda: manager)
    batch = batch_module.BatchPanel()
    batch._clear_input(force=True)
    batch.detail_cb.setChecked(False)
    water = water_module.WaterProfilePanel()
    yield batch, water, manager
    for panel in (batch, water):
        panel.close()
        panel.deleteLater()
    app.processEvents()


def _add_spillway_row(batch, *, segment=1, q=0.7, x=0.0):
    row = [""] * len(batch_module.INPUT_HEADERS)
    row[0:4] = [str(batch.input_table.rowCount() + 1), str(segment), "", "泄水渠"]
    row[4:11] = [str(x), "0", str(q), "0.014", "20", "0", "1"]
    batch._add_row(row)
    batch._renumber()


@pytest.mark.parametrize(
    ("enabled", "manual", "expected"),
    [(True, None, 0.91), (True, 0.95, 0.95), (True, 0.7, 0.7), (False, 0.95, 0.7)],
)
def test_spillway_batch_flow_survives_shared_import_and_project_restore(panels, enabled, manual, expected):
    """自动、手工、等流量和关闭加大四种情况均须原值传递到表3。"""
    batch, water, manager = panels
    _add_spillway_row(batch)
    _add_spillway_row(batch, x=40.0)
    batch.inc_cb.setChecked(enabled)
    if manual is not None:
        batch._manual_qmax_by_segment = {1: manual}
    batch._batch_calculate()
    assert len(batch.batch_results) == 2
    result = batch.batch_results[0]["result"]
    assert result["use_increase"] is enabled
    assert result["Q_increased"] == pytest.approx(expected)
    assert batch.result_table.item(0, 12).text() == (f"{expected:.3f}" if enabled else "-")

    saved_batch = copy.deepcopy(batch.to_project_dict())
    batch.from_project_dict(saved_batch, skip_dirty_signal=True)
    shared = manager.get_batch_results()
    assert len(shared) == 2
    assert shared[0].use_increase is enabled
    assert shared[0].Q_max == pytest.approx(expected)

    water._import_from_batch()
    settings = water._build_settings()
    assert settings.max_flows == pytest.approx([expected])
    nodes = water._build_nodes_from_table()
    assert len(nodes) == 2
    calculator = WaterProfileCalculator(settings)
    calculator._hydrate_spillway_steep_chute_flow_context(nodes)
    for node in nodes:
        payload = node.section_params[SPILLWAY_STEEP_CHUTE_PARAM_KEY]
        assert payload["use_increase"] is enabled
        assert payload["Q_increased"] == pytest.approx(expected)
        restored = ChannelNode.from_project_dict(node.to_project_dict())
        assert restored.section_params[SPILLWAY_STEEP_CHUTE_PARAM_KEY]["Q_increased"] == pytest.approx(expected)
        assert restored.section_params[SPILLWAY_STEEP_CHUTE_PARAM_KEY]["use_increase"] is enabled


def test_spillway_batch_manual_flows_remain_specific_to_each_segment(panels):
    """两个流量段不得相互串用手工加大流量。"""
    batch, water, _manager = panels
    _add_spillway_row(batch, segment=1, q=0.7)
    _add_spillway_row(batch, segment=2, q=5.0, x=40.0)
    batch.inc_cb.setChecked(True)
    batch._manual_qmax_by_segment = {1: 0.95, 2: 6.8}
    batch._batch_calculate()
    water._import_from_batch()
    settings = water._build_settings()
    nodes = water._build_nodes_from_table()
    assert settings.max_flows == pytest.approx([0.95, 6.8])
    WaterProfileCalculator(settings)._hydrate_spillway_steep_chute_flow_context(nodes)
    assert [node.section_params[SPILLWAY_STEEP_CHUTE_PARAM_KEY]["Q_increased"] for node in nodes] == pytest.approx([0.95, 6.8])


def test_spillway_batch_rejects_manual_flow_below_design(panels):
    """专项占位行也执行与普通断面相同的手工加大流量校验。"""
    batch, _water, _manager = panels
    _add_spillway_row(batch)
    batch.inc_cb.setChecked(True)
    batch._manual_qmax_by_segment = {1: 0.6}
    batch._batch_calculate()
    assert batch.batch_results == []
    assert "不能小于设计流量" in batch.result_table.item(0, batch.result_table.columnCount() - 1).text()


def test_spillway_recalculation_uses_current_settings_and_honors_disabled_flag():
    """当前项目工况覆盖上次值，但关闭加大仍按设计流量传递。"""
    nodes = []
    for segment, enabled in ((1, True), (2, False)):
        node = ChannelNode(structure_type=StructureType.SPILLWAY_STEEP_CHUTE)
        node.flow_section = str(segment)
        node.flow = 0.7
        node.section_params = {
            "use_increase": enabled,
            SPILLWAY_STEEP_CHUTE_PARAM_KEY: {"Q_increased": 0.91, "advanced_params": {"freeboard": 0.4}},
        }
        nodes.append(node)
    calculator = WaterProfileCalculator(ProjectSettings(max_flows=[0.98, 1.2]))
    calculator._hydrate_spillway_steep_chute_flow_context(nodes)
    assert [node.section_params[SPILLWAY_STEEP_CHUTE_PARAM_KEY]["Q_increased"] for node in nodes] == pytest.approx([0.98, 0.7])
    assert all(node.section_params[SPILLWAY_STEEP_CHUTE_PARAM_KEY]["advanced_params"] == {"freeboard": 0.4} for node in nodes)
