# -*- coding: utf-8 -*-
"""五排水库充水渠真实 Excel 的批量计算与 DXF 导出回归测试。"""

import copy
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(tempfile.gettempdir()) / "codex-mplconfig"),
)

ROOT = Path(__file__).resolve().parents[1]
WATER_PROFILE_ROOT = ROOT / "推求水面线"
for _path in (str(ROOT), str(WATER_PROFILE_ROOT), str(ROOT / "calc_渠系计算算法内核")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from PySide6.QtWidgets import QApplication

from app_渠系计算前端.batch.panel import BatchPanel
import app_渠系计算前端.batch.panel as batch_panel_mod
from app_渠系计算前端.water_profile import cad_tools
from models.data_models import ChannelNode, ProjectSettings
from models.enums import StructureType
from core.calculator import WaterProfileCalculator


WUPAI_EXCEL = ROOT / "data" / "五排水库充水渠批量计算用表.xlsx"


class _TextStub:
    """提供导出函数需要的 text() 接口。"""

    def __init__(self, value):
        self._value = value

    def text(self):
        """返回固定文本。"""
        return self._value


class _ComboStub:
    """提供导出函数需要的 currentText() 接口。"""

    def __init__(self, value):
        self._value = value

    def currentText(self):
        """返回固定下拉值。"""
        return self._value


class _InfoBarStub:
    """屏蔽界面提示，避免测试依赖真实弹窗。"""

    @staticmethod
    def success(*_args, **_kwargs):
        """忽略成功提示。"""
        return None

    @staticmethod
    def warning(*_args, **_kwargs):
        """忽略警告提示。"""
        return None

    @staticmethod
    def error(*_args, **_kwargs):
        """忽略错误提示。"""
        return None

    @staticmethod
    def info(*_args, **_kwargs):
        """忽略普通提示。"""
        return None


class _AcceptedTextDialog:
    """让 DXF 文本导出参数弹窗自动确认。"""

    def __init__(self, *_args, **_kwargs):
        self.result = {}

    def exec(self):
        """模拟用户点击确定。"""
        return cad_tools.QDialog.Accepted


def _get_qapp():
    """获取或创建 Qt 应用。"""
    return QApplication.instance() or QApplication([])


def _flush_events(rounds=4):
    """处理少量 Qt 事件，确保表格状态稳定。"""
    app = _get_qapp()
    for _ in range(max(1, rounds)):
        app.processEvents()


def _prepare_batch_panel(monkeypatch):
    """创建批量计算面板并屏蔽弹窗。"""
    _get_qapp()
    monkeypatch.setattr(batch_panel_mod, "InfoBar", _InfoBarStub)
    monkeypatch.setattr(batch_panel_mod, "fluent_batch_result", lambda *args, **kwargs: None)
    monkeypatch.setattr(batch_panel_mod, "fluent_info", lambda *args, **kwargs: None)
    monkeypatch.setattr(batch_panel_mod, "fluent_question", lambda *args, **kwargs: True)

    panel = BatchPanel()
    panel.resize(1400, 900)
    panel.show()
    _flush_events(6)
    panel._clear_input(force=True)
    _flush_events(2)
    return panel


def _load_wupai_panel(monkeypatch):
    """把五排 Excel 导入批量计算面板。"""
    assert WUPAI_EXCEL.exists(), "五排水库充水渠批量计算用表.xlsx 不存在"
    panel = _prepare_batch_panel(monkeypatch)
    panel._do_load_from_filepath(str(WUPAI_EXCEL), is_sample=False)
    _flush_events(4)
    return panel


def _sf(value, default=0.0):
    """把单元格文本转成浮点数。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _run_wupai_batch_calculation(monkeypatch):
    """执行五排 Excel 批量计算并捕获共享注册数据。"""
    panel = _load_wupai_panel(monkeypatch)
    registered_rows = []

    class _SharedManagerStub:
        """记录批量计算同步给水面线的数据。"""

        def clear_batch_results(self):
            """清空上一次注册数据。"""
            registered_rows.clear()

        def register_batch_results(self, rows):
            """保存注册数据并返回注册数量。"""
            registered_rows[:] = copy.deepcopy(rows)
            return len(rows)

    monkeypatch.setattr(batch_panel_mod, "get_shared_data_manager", lambda: _SharedManagerStub())
    panel._batch_calculate()
    _flush_events(4)
    return panel, registered_rows


def _assert_close(actual, expected, *, rel=1e-9, abs=1e-9):
    """比较两个数值字段。"""
    assert float(actual) == pytest.approx(float(expected), rel=rel, abs=abs)


def _build_settings_from_batch(panel, registered_rows):
    """从五排批量结果构造水面线项目参数。"""
    max_flow = 0.0
    if registered_rows:
        max_flow = float(
            registered_rows[0].get("Q_increased")
            or registered_rows[0].get("Q_inc")
            or registered_rows[0].get("Q")
            or 0.0
        )
    return ProjectSettings(
        channel_name=panel.channel_name_edit.text().strip(),
        channel_level=panel.channel_level_combo.currentText(),
        start_station=0.0,
        start_water_level=float(panel.start_wl_edit.text()),
        design_flow=0.2,
        max_flow=max_flow,
        design_flows=[0.2],
        max_flows=[max_flow] if max_flow > 0 else [0.2],
        roughness=0.014,
    )


def _node_from_registered_row(row):
    """把批量结果行转换成水面线节点。"""
    node = ChannelNode()
    node.flow_section = str(row.get("flow_section", "1") or "1")
    node.name = str(row.get("building_name", "") or "")
    node.structure_type = StructureType.from_string(str(row.get("section_type", "明渠-圆形") or "明渠-圆形"))
    node.x = float(row.get("coord_X", 0.0) or 0.0)
    node.y = float(row.get("coord_Y", 0.0) or 0.0)
    node.turn_radius = float(row.get("turn_radius", 0.0) or 0.0)
    node.flow = float(row.get("Q", 0.0) or 0.0)
    node.roughness = float(row.get("n", 0.014) or 0.014)
    slope_inv = float(row.get("slope_inv", 0.0) or 0.0)
    node.slope_i = 1.0 / slope_inv if slope_inv > 0 else 0.0

    d_value = float(row.get("D_design", row.get("D", 0.0)) or 0.0)
    depth = float(row.get("y_d", row.get("h_design", 0.0)) or 0.0)
    velocity = float(row.get("V_d", row.get("V_design", 0.0)) or 0.0)
    node.water_depth = depth
    node.velocity = velocity
    node.velocity_increased = float(row.get("V_i", row.get("V_increased", 0.0)) or 0.0)
    node.structure_height = d_value
    node.section_params.update(
        {
            "D": d_value,
            "A": float(row.get("A_d", row.get("A_design", 0.0)) or 0.0),
            "X": float(row.get("P_d", row.get("X_design", 0.0)) or 0.0),
            "R": float(row.get("R_d", row.get("R_design", 0.0)) or 0.0),
            "H_total": d_value,
            "use_increase": bool(row.get("_use_increase", True)),
        }
    )
    return node


def _calculate_wupai_nodes(panel, registered_rows):
    """用批量结果构造并计算水面线节点。"""
    settings = _build_settings_from_batch(panel, registered_rows)
    nodes = [_node_from_registered_row(row) for row in registered_rows]
    calculated = WaterProfileCalculator(settings).calculate_all(nodes)
    return settings, calculated


def test_wupai_excel_imports_required_inputs(monkeypatch):
    """五排真实 Excel 应导入基础信息和 15 条明渠圆形数据。"""
    panel = _load_wupai_panel(monkeypatch)

    assert panel.channel_name_edit.text().strip() == "五排"
    assert panel.channel_level_combo.currentText() == "充水渠"
    assert float(panel.start_wl_edit.text()) == pytest.approx(352.44)
    assert panel.start_station_edit.text().strip() == "0+000.000"
    assert panel.input_table.rowCount() == 15

    slopes = []
    for row in range(panel.input_table.rowCount()):
        assert panel.input_table.item(row, batch_panel_mod.COL_SECTION_TYPE).text() == "明渠-圆形"
        assert panel.input_table.item(row, batch_panel_mod.COL_BUILDING_NAME).text().strip() == "-"
        assert panel.input_table.item(row, batch_panel_mod.COL_Q).text().strip() == "0.2"
        assert panel.input_table.item(row, batch_panel_mod.COL_N).text().strip() == "0.014"
        assert panel.input_table.item(row, batch_panel_mod.COL_D).text().strip() == "1"
        assert panel.input_table.item(row, batch_panel_mod.COL_V_MIN).text().strip() == "0.1"
        assert panel.input_table.item(row, batch_panel_mod.COL_V_MAX).text().strip() == "100"
        assert panel.input_table.item(row, batch_panel_mod.COL_TURN_RADIUS).text().strip() == "10"
        assert panel.input_table.item(row, batch_panel_mod.COL_X).text().strip()
        assert panel.input_table.item(row, batch_panel_mod.COL_Y).text().strip()
        slopes.append(float(panel.input_table.item(row, batch_panel_mod.COL_SLOPE).text()))

    assert slopes[:6] == [3000.0] * 6
    assert slopes[-2:] == [2.9, 10000.0]


def test_wupai_batch_calculation_matches_circular_kernel(monkeypatch):
    """五排批量计算结果应和明渠圆形内核直接计算一致。"""
    panel, registered_rows = _run_wupai_batch_calculation(monkeypatch)

    assert panel.result_table.rowCount() == 15
    assert len(panel.batch_results) == 15
    assert len(registered_rows) == 15
    assert all(item["result"].get("success") is True for item in panel.batch_results)
    assert all(row.get("section_type") == "明渠-圆形" for row in registered_rows)

    representative_indexes = [0, 6, 8, 13, 14]
    compare_keys = [
        "D_design", "y_d", "V_d", "A_d", "P_d", "R_d",
        "Q_inc", "y_i", "V_i", "FB_d", "FB_i", "PA_d", "PA_i",
    ]
    for idx in representative_indexes:
        values = panel.batch_results[idx]["input"]
        result = panel.batch_results[idx]["result"]
        expected = batch_panel_mod.circular_calculate(
            Q=_sf(values[batch_panel_mod.COL_Q]),
            n=_sf(values[batch_panel_mod.COL_N], 0.014),
            slope_inv=_sf(values[batch_panel_mod.COL_SLOPE]),
            v_min=_sf(values[batch_panel_mod.COL_V_MIN], 0.1),
            v_max=_sf(values[batch_panel_mod.COL_V_MAX], 100.0),
            manual_D=_sf(values[batch_panel_mod.COL_D]) or None,
            increase_percent=0.0,
        )
        assert expected.get("success") is True
        for key in compare_keys:
            _assert_close(result[key], expected[key])


def test_wupai_combined_dxf_exports_real_file(monkeypatch, tmp_path):
    """五排批量结果生成的导出全部 DXF 应可打开并包含三类表格。"""
    ezdxf = pytest.importorskip("ezdxf")
    panel, registered_rows = _run_wupai_batch_calculation(monkeypatch)
    settings, calculated_nodes = _calculate_wupai_nodes(panel, registered_rows)
    assert len(calculated_nodes) == 15
    assert all(node.water_level > 0 and node.bottom_elevation > 0 for node in calculated_nodes)

    out_path = tmp_path / "wupai_combined.dxf"
    messages = []
    export_panel = SimpleNamespace(
        calculated_nodes=calculated_nodes,
        nodes=calculated_nodes,
        _text_export_settings={},
        _custom_pressurized_pipe_params={},
        channel_name_edit=_TextStub("五排"),
        channel_level_combo=_ComboStub("充水渠"),
    )
    export_panel.window = lambda: None
    export_panel._build_settings = lambda: settings
    export_panel._build_nodes_from_table = lambda: calculated_nodes

    monkeypatch.setattr(cad_tools, "TextExportSettingsDialog", _AcceptedTextDialog)
    monkeypatch.setattr(cad_tools.QFileDialog, "getSaveFileName", staticmethod(lambda *_args, **_kwargs: (str(out_path), "DXF")))
    monkeypatch.setattr(cad_tools, "fluent_question", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(cad_tools, "fluent_info", lambda *_args, **_kwargs: messages.append(("info", _args)))
    monkeypatch.setattr(cad_tools, "fluent_error", lambda *_args, **_kwargs: messages.append(("error", _args)))

    cad_tools.export_combined_dxf(export_panel)

    assert out_path.exists()
    assert [kind for kind, _ in messages if kind == "error"] == []
    doc = ezdxf.readfile(out_path)
    layer_names = {layer.dxf.name for layer in doc.layers}
    assert "断面汇总表" in layer_names
    assert "IP坐标表" in layer_names
    assert any(name.startswith("纵断面_") for name in layer_names)

    modelspace = doc.modelspace()
    assert len(modelspace) > 0
    text_values = [entity.dxf.text for entity in modelspace.query("TEXT")]
    joined_text = "\n".join(text_values)
    assert "IP坐标及弯道参数表" in joined_text
    assert "圆管涵断面尺寸及水力要素表" in joined_text
    assert "五充" in joined_text
