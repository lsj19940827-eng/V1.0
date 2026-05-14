# -*- coding: utf-8 -*-
"""泄水渠与陡坡前端面板的独立单元测试。"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-software-rasterizer")
os.environ.setdefault("CODEX_FORCE_QTEXTBROWSER", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QGroupBox, QLineEdit, QPushButton, QTabWidget
from qfluentwidgets import LineEdit as FluentLineEdit

from app_渠系计算前端.spillway_steep_chute import SpillwaySteepChutePanel
import app_渠系计算前端.spillway_steep_chute.panel as panel_mod


def _app():
    """获取测试用 Qt 应用实例。"""
    return QApplication.instance() or QApplication([])


def _flush_events(rounds=3):
    """处理 Qt 事件，确保控件状态完成同步。"""
    app = _app()
    for _ in range(max(1, rounds)):
        app.processEvents()


def _fake_result():
    """构造算法内核返回的最小成功结果。"""
    return {
        "success": True,
        "summary": {
            "工程名称": "熊启钧教学算例",
            "设计流量": "12.50 立方米/秒",
            "陡槽长度": "120.00 米",
        },
        "profile_points": [
            {"x": 0.0, "bed_elevation": 100.0, "water_elevation": 101.20, "depth": 1.20},
            {"x": 120.0, "bed_elevation": 88.0, "water_elevation": 88.80, "depth": 0.80},
        ],
        "checks": [
            {"name": "流速校核", "result": "通过", "message": "设计流速在建议范围内"},
        ],
        "risks": ["出口需复核消能防冲。"],
        "formulas": [
            {"name": "明渠恒定流能量方程", "source": "水力学教材", "latex": r"E_1=E_2+h_f"},
        ],
        "comparison": [
            {"case": "设计流量", "Q": 12.5, "max_v": 5.6, "status": "通过"},
        ],
    }


def _principle_html(panel):
    """读取计算原理页当前渲染文本。"""
    return panel.principle_view.toHtml() if hasattr(panel.principle_view, "toHtml") else panel.principle_view.toPlainText()


def test_principle_inline_html_renders_engineering_subscripts_and_escapes_html():
    """计算原理普通说明里的工程符号应显示下标，且先转义 HTML。"""
    rendered = panel_mod.render_principle_inline_html(
        "h_s、h_k、h_m、E_s、Q_过流、b_c、H_0、Fr_1、α_e、H_侧墙、L_Δb、h_下游，"
        "控制水深h_s、建议H_侧墙，<script>alert(1)</script>"
    )

    for expected in [
        "h<sub>s</sub>",
        "h<sub>k</sub>",
        "h<sub>m</sub>",
        "E<sub>s</sub>",
        "Q<sub>过流</sub>",
        "b<sub>c</sub>",
        "H<sub>0</sub>",
        "Fr<sub>1</sub>",
        "α<sub>e</sub>",
        "H<sub>侧墙</sub>",
        "L<sub>Δb</sub>",
        "h<sub>下游</sub>",
        "控制水深h<sub>s</sub>",
        "建议H<sub>侧墙</sub>",
    ]:
        assert expected in rendered
    assert "<script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered


def test_package_exports_spillway_steep_chute_panel():
    """独立包应直接导出面板类，供主界面后续接线。"""
    assert SpillwaySteepChutePanel.__name__ == "SpillwaySteepChutePanel"


def test_panel_builds_required_tabs_and_primary_actions():
    """面板应提供左输入、右结果和主要操作入口。"""
    _app()
    panel = SpillwaySteepChutePanel()

    tabs = panel.findChild(QTabWidget)
    tab_titles = [tabs.tabText(i) for i in range(tabs.count())]
    assert tab_titles == [
        "计算原理",
        "结果汇总",
        "沿程水面线",
        "纵断面图",
        "规范校核",
        "工况对比",
    ]

    button_texts = {button.text() for button in panel.findChildren(QPushButton)}
    assert {"载入教学算例", "清空", "计算", "导出计算书", "导出表格"} <= button_texts
    assert "导出文档" not in button_texts

    panel.deleteLater()


def test_first_default_case_is_named_case_1():
    """第一个默认工况应显示为工况1，而不是旧的设计工况。"""
    _app()
    panel = SpillwaySteepChutePanel()

    assert panel._cases[0].get("custom_label") is None
    case_view = panel._case_view(panel._cases[0], 0)
    assert case_view["label"] == "工况1"
    assert case_view["compact_label"] == "1. 工况1"
    assert "设计工况" not in case_view["tooltip"]
    assert panel._collect_inputs()["custom_label"] == "工况1"

    panel.deleteLater()


def test_principle_page_shows_preview_before_calculation():
    """面板初始状态应先展示计算原理预览，而不是只等计算完成。"""
    _app()
    panel = SpillwaySteepChutePanel()

    rendered = _principle_html(panel)

    assert "正常水深" in rendered
    assert "临界水深" in rendered
    assert "水面线逐段计算" in rendered
    assert "Q=20.0" in rendered
    assert "计算后生成" in rendered
    assert "完成计算后，这里会" not in rendered

    panel.deleteLater()


def test_principle_preview_uses_loaded_example_inputs_before_calculation():
    """载入教学算例后，未计算的计算原理页也应带入当前输入值。"""
    _app()
    panel = SpillwaySteepChutePanel()

    panel.load_teaching_example()
    rendered = _principle_html(panel)

    assert "熊启钧教学算例" in rendered
    assert "Q=20.0" in rendered
    assert "L=80.0" in rendered
    assert "计算后生成" in rendered
    assert panel.current_result is None

    panel.deleteLater()


def test_principle_preview_returns_after_input_change(monkeypatch):
    """已有结果被输入变更清空后，计算原理页应回到当前输入预览。"""
    _app()
    panel = SpillwaySteepChutePanel()
    panel.load_teaching_example()
    monkeypatch.setattr(panel_mod, "quick_calculate_spillway_steep_chute", lambda **_params: _fake_result())
    panel.calculate()

    panel._input_fields["design_flow"].setText("18.5")
    _flush_events()
    rendered = _principle_html(panel)

    assert panel.current_result is None
    assert "Q=18.5" in rendered
    assert "计算后生成" in rendered

    panel.deleteLater()


def test_input_sidebar_uses_fluent_fields_and_card_container():
    """输入栏应与明渠、渡槽一致使用 Fluent 输入框和白色卡片容器。"""
    _app()
    panel = SpillwaySteepChutePanel()

    assert isinstance(panel._input_group, QGroupBox)
    for key in ("project_name", "design_flow", "channel_width", "roughness"):
        field = panel._input_fields[key]
        assert isinstance(field, FluentLineEdit)
        assert type(field) is not QLineEdit

    panel.deleteLater()


def test_mode_visibility_keeps_manual_flow_cases_hidden_and_shows_auto_hint():
    """新手和专业模式都不再展示手填分级流量，只展示自动分级说明。"""
    _app()
    panel = SpillwaySteepChutePanel()

    assert panel._combo_fields["ui_mode_label"].currentText() == "新手模式"
    assert panel._input_fields["flow_cases_text"].isHidden()
    assert all(widget.isHidden() for widget in panel._input_rows["flow_cases_text"])
    assert "依据规范" in panel.auto_flow_hint.text()
    assert "水跃计算" in panel.auto_flow_hint.text()
    assert "10%" in panel.auto_flow_hint.text()
    assert "1%" in panel.auto_flow_hint.text()
    assert "初筛" in panel.auto_flow_hint.text()
    assert "加密" in panel.auto_flow_hint.text()
    assert "自动" in panel.auto_flow_hint.text()
    assert panel._combo_fields["profile_mode_label"].isHidden()

    mode = panel._combo_fields["ui_mode_label"]
    mode.setCurrentIndex(mode.findText("专业模式"))

    assert panel._input_fields["flow_cases_text"].isHidden()
    assert all(widget.isHidden() for widget in panel._input_rows["flow_cases_text"])
    assert not panel._combo_fields["profile_mode_label"].isHidden()

    panel.deleteLater()


def test_panel_project_roundtrip_preserves_inputs_and_results(monkeypatch):
    """项目保存恢复应包含输入、结果和当前页签。"""
    _app()
    panel = SpillwaySteepChutePanel()
    changed = []
    panel.data_changed.connect(lambda: changed.append("changed"))

    panel.load_teaching_example()
    assert changed

    monkeypatch.setattr(panel_mod, "quick_calculate_spillway_steep_chute", lambda **_params: _fake_result())
    panel.calculate()

    state = panel.to_project_dict()
    assert state["panel_key"] == "spillway_steep_chute"
    assert state["input_params"]["project_name"] == "熊启钧教学算例"
    assert state["current_result"]["success"] is True

    restored = SpillwaySteepChutePanel()
    restored.from_project_dict(state)
    restored_state = restored.to_project_dict()
    assert restored_state["input_params"] == state["input_params"]
    assert restored_state["current_result"] == state["current_result"]

    panel.deleteLater()
    restored.deleteLater()


def test_panel_calculate_calls_kernel_and_fills_summary(monkeypatch):
    """计算入口应调用算法内核，并把结果写到汇总文本。"""
    _app()
    panel = SpillwaySteepChutePanel()
    panel.load_teaching_example()
    received = {}

    def fake_calculate(**params):
        received.update(params)
        return _fake_result()

    monkeypatch.setattr(panel_mod, "quick_calculate_spillway_steep_chute", fake_calculate)
    panel.calculate()

    assert received["project_name"] == "熊启钧教学算例"
    assert received["design_flow"] == pytest.approx(20.0)
    assert "设计流量" in panel.summary_text.toPlainText()
    assert "熊启钧教学算例" in panel.summary_text.toPlainText()
    assert panel.profile_table.rowCount() == 2

    panel.deleteLater()


def test_collect_inputs_auto_generates_ten_percent_flow_cases_and_increase_case():
    """默认开启加大流量时，应自动生成10%递增流量并加入加大流量。"""
    _app()
    panel = SpillwaySteepChutePanel()

    panel._input_fields["design_flow"].setText("20.0")
    params = panel._collect_inputs()

    assert params["inc_mode"] == "percent"
    assert params["increase_percent"] == pytest.approx(15.0)
    assert params["Q_increased"] == pytest.approx(23.0)
    assert params["flow_case_refinement"] == {
        "enabled": True,
        "coarse_step_ratio": 0.10,
        "refine_step_ratio": 0.01,
    }
    assert [case["name"] for case in params["flow_cases"]] == [
        "10%设计流量",
        "20%设计流量",
        "30%设计流量",
        "40%设计流量",
        "50%设计流量",
        "60%设计流量",
        "70%设计流量",
        "80%设计流量",
        "90%设计流量",
        "100%设计流量",
        "加大流量",
    ]
    assert [case["Q"] for case in params["flow_cases"]] == pytest.approx(
        [2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 23.0]
    )

    panel.deleteLater()


def test_collect_inputs_rejects_invalid_q_increased():
    """按Q加大输入无效时应给出明确校验。"""
    _app()
    panel = SpillwaySteepChutePanel()
    panel._input_fields["design_flow"].setText("20.0")
    panel.inc_mode_q_rb.setChecked(True)
    panel.inc_q_edit.setText("20.0")

    with pytest.raises(ValueError, match="加大流量 Q加大必须大于设计流量 Q"):
        panel._collect_inputs()

    panel.deleteLater()


def test_legacy_manual_flow_cases_text_is_ignored_after_restore():
    """旧工程里的手填分级流量字段不再参与计算，也不应导致报错。"""
    _app()
    panel = SpillwaySteepChutePanel()

    panel.from_project_dict(
        {
            "input_params": {
                "project_name": "旧工程",
                "design_flow": 20.0,
                "flow_cases_text": "10, abc, 20",
            }
        }
    )

    params = panel._collect_inputs()

    assert panel._input_fields["flow_cases_text"].text() == ""
    assert len(params["flow_cases"]) == 11
    assert params["flow_cases"][0] == {"name": "10%设计流量", "Q": 2.0}

    panel.deleteLater()


def test_project_restore_maps_legacy_increase_flow_to_q_mode():
    """旧工程只有 increase_flow 时，应恢复为按Q加大模式。"""
    _app()
    panel = SpillwaySteepChutePanel()

    panel.from_project_dict(
        {
            "input_params": {
                "project_name": "旧工程",
                "design_flow": 20.0,
                "use_increase": True,
                "increase_flow": "25.0",
            }
        }
    )

    assert panel.inc_mode_q_rb.isChecked() is True
    assert panel.inc_q_edit.text() == "25.0"
    assert panel._collect_inputs()["Q_increased"] == pytest.approx(25.0)

    panel.deleteLater()


def test_panel_calculate_supports_kernel_dict_signature(monkeypatch):
    """任务 A 内核使用单个 input_data 参数时，面板也应能调用。"""
    _app()
    panel = SpillwaySteepChutePanel()
    panel.load_teaching_example()
    received = {}

    def fake_calculate(input_data):
        received.update(input_data)
        return _fake_result()

    monkeypatch.setattr(panel_mod, "quick_calculate_spillway_steep_chute", fake_calculate)
    panel.calculate()

    assert received["project_name"] == "熊启钧教学算例"
    assert received["design_flow"] == pytest.approx(20.0)
    assert panel.current_result["success"] is True

    panel.deleteLater()


def test_principle_page_sanitizes_internal_prd_sources_and_shows_full_flow():
    """计算原理页应清洗内部来源，并展示完整计算流程。"""
    _app()
    panel = SpillwaySteepChutePanel()
    panel.current_result = {
        "input_params": {"Q": 20.0, "n": 0.014, "i": 0.02},
        "summary": {
            "设计流量": "20.000 立方米/秒",
            "正常水深": "1.084 米",
            "临界水深": "1.749 米",
            "坡型": "陡坡",
            "末端水深": "1.180 米",
        },
        "hydraulic": {
            "section_type": "trapezoidal",
            "slope_type": "steep",
            "normal": {"area_m2": 5.2, "hydraulic_radius_m": 0.9, "velocity_ms": 3.8},
            "critical": {"area_m2": 6.3, "hydraulic_radius_m": 0.86, "water_top_width_m": 6.2, "velocity_ms": 3.1},
            "start": {"area_m2": 6.3, "hydraulic_radius_m": 0.86, "water_top_width_m": 6.2, "depth_m": 1.749},
        },
        "profile": {"end_depth_m": 1.18, "water_profile_name": "陡坡降水曲线"},
        "start_control": {"source": "manual", "depth_m": 1.749},
        "aeration_and_sidewall": {"aeration_coefficient": 1.2, "freeboard_m": 0.4},
        "hydraulic_jump": {"pre_jump_depth_m": 1.18, "pre_jump_froude": 2.4, "control_depth_m": 1.5},
        "formulas": [
            {
                "name": "出口整流段",
                "source": "PRD 第二版出口整流段设计口径",
                "latex": r"L_r=\max(L_{\Delta b},\eta h_c'',L_{\min})",
            }
        ]
    }

    panel._refresh_principle_page()
    rendered = panel.principle_view.toHtml() if hasattr(panel.principle_view, "toHtml") else panel.principle_view.toPlainText()

    assert "PRD" not in rendered
    assert "出口连接段整流布置校核口径" in rendered
    for keyword in ["正常水深", "临界水深", "坡型判别", "水面线逐段计算", "掺气水深", "水跃与消力池"]:
        assert keyword in rendered
    for forbidden in [r"\begin{cases}", r"\end{cases}", r"\frac", r"\quad", r"\text{", "trapezoidal", "manual", "backwater", "control", "wall", "cap"]:
        assert forbidden not in rendered
    for keyword in ["起点控制水深", "入口过流能力", "掺气水深与侧墙高度", "水跃与消力池"]:
        assert keyword in rendered
    for forbidden in ["h_s 为", "h_k 为", "h_m 为", "E_s 为", "Q_过流 为", "b_c 为", "H_0 为"]:
        assert forbidden not in rendered
    assert rendered.count("vertical-align:sub") >= 7
    for expected_subscript in [">s</span>", ">k</span>", ">m</span>", ">过流</span>", ">c</span>", ">0</span>"]:
        assert expected_subscript in rendered

    panel.deleteLater()


def test_latex_html_fallback_does_not_show_formula_source(monkeypatch):
    """公式渲染失败时不应把 LaTeX 源码展示给用户。"""
    monkeypatch.setattr(panel_mod, "render_latex_svg", lambda *_args, **_kwargs: None)

    rendered = SpillwaySteepChutePanel._latex_html(r"h_s=\begin{cases}h_k\\h_m\end{cases}")

    assert "该公式暂无法渲染" in rendered
    assert r"\begin{cases}" not in rendered
    assert r"\end{cases}" not in rendered


def test_refresh_plot_configures_canvas_before_drawing(monkeypatch):
    """纵断面图刷新前应先按当前可视区域调整画布宽度。"""
    _app()
    panel = SpillwaySteepChutePanel()
    called = []
    monkeypatch.setattr(
        panel_mod,
        "configure_section_grid_canvas",
        lambda target, case_count: called.append((target, case_count)),
        raising=False,
    )
    panel.current_result = _fake_result()

    panel._refresh_plot()

    assert called == [(panel, 1)]

    panel.deleteLater()


def test_input_change_invalidates_previous_results(monkeypatch):
    """参数变更后应清空旧结果，避免保存和导出过期成果。"""
    _app()
    panel = SpillwaySteepChutePanel()
    monkeypatch.setattr(panel_mod, "quick_calculate_spillway_steep_chute", lambda **_params: _fake_result())

    panel.calculate()
    assert panel.current_result is not None

    panel._input_fields["project_name"].setText("修改后的工程")

    assert panel.current_result is None
    assert panel._all_results == []
    assert panel.to_project_dict()["current_result"] is None

    panel.deleteLater()


def test_clear_preserves_inputs_and_cases_but_removes_results(monkeypatch):
    """清空按钮只清结果，不应清掉用户输入和多工况。"""
    _app()
    panel = SpillwaySteepChutePanel()
    monkeypatch.setattr(panel_mod, "quick_calculate_spillway_steep_chute", lambda **_params: _fake_result())
    panel._add_case()
    panel._input_fields["project_name"].setText("清空保留工程")
    panel._input_fields["design_flow"].setText("31.5")
    panel._input_fields["channel_width"].setText("4.2")
    panel.calculate()
    _flush_events()

    expected_inputs = {
        "project_name": panel._input_fields["project_name"].text(),
        "design_flow": panel._input_fields["design_flow"].text(),
        "channel_width": panel._input_fields["channel_width"].text(),
    }
    expected_case_count = len(panel._cases)
    expected_case_idx = panel._current_case_idx

    panel._clear()
    _flush_events()

    assert {
        "project_name": panel._input_fields["project_name"].text(),
        "design_flow": panel._input_fields["design_flow"].text(),
        "channel_width": panel._input_fields["channel_width"].text(),
    } == expected_inputs
    assert len(panel._cases) == expected_case_count
    assert panel._current_case_idx == expected_case_idx
    assert panel._all_results == []
    assert panel.input_params == {}
    assert panel.current_result is None
    assert panel.profile_table.rowCount() == 0
    assert panel.check_table.rowCount() == 0

    panel.deleteLater()


def test_project_roundtrip_keeps_current_case_result(monkeypatch):
    """多工况恢复后，当前结果应跟随当前工况，而不是固定到第一个工况。"""
    _app()
    panel = SpillwaySteepChutePanel()
    panel._cases = [
        {**panel._default_case(), "project_name": "工况一", "custom_label": "工况一", "design_flow": 12.0},
        {**panel._default_case(), "project_name": "工况二", "custom_label": "工况二", "design_flow": 24.0},
    ]
    panel._load_case(1)

    def fake_calculate(**params):
        result = _fake_result()
        result["summary"] = {"工程名称": params["project_name"], "设计流量": f"{params['design_flow']:.2f} 立方米/秒"}
        return result

    monkeypatch.setattr(panel_mod, "quick_calculate_spillway_steep_chute", fake_calculate)
    panel.calculate()
    panel._switch_case(1)
    state = panel.to_project_dict()

    restored = SpillwaySteepChutePanel()
    restored.from_project_dict(state)

    assert restored._current_case_idx == 1
    assert restored.current_result["summary"]["工程名称"] == "工况二"

    panel.deleteLater()
    restored.deleteLater()


def test_project_save_preserves_raw_cases_when_current_input_is_invalid():
    """项目保存遇到临时非法输入时，仍应保存原始工况和旧结果。"""
    _app()
    panel = SpillwaySteepChutePanel()
    panel.current_result = _fake_result()
    panel._all_results = [(0, {"project_name": "旧结果"}, _fake_result())]

    panel._input_fields["design_flow"].setText("12.")
    panel._input_fields["roughness"].setText("临时输入")

    state = panel.to_project_dict()

    assert state["panel_key"] == "spillway_steep_chute"
    assert state["cases"][0]["roughness"] == "临时输入"
    assert state["current_result"] is None
    assert state["input_params"] == {}
    assert "input_params_error" in state

    panel.deleteLater()


def test_reset_to_default_clears_cases_results_and_inputs(monkeypatch):
    """新建项目时，泄水渠与陡坡面板应能恢复默认空状态。"""
    _app()
    panel = SpillwaySteepChutePanel()
    monkeypatch.setattr(panel_mod, "quick_calculate_spillway_steep_chute", lambda **_params: _fake_result())
    panel.calculate()
    panel._input_fields["project_name"].setText("旧工程")

    panel.reset_to_default()

    assert len(panel._cases) == 1
    assert panel.current_result is None
    assert panel._all_results == []
    assert panel._input_fields["project_name"].text() == "未命名工程"
    assert panel._case_view(panel._cases[0], 0)["label"] == "工况1"
    assert panel.summary_text.toPlainText() == ""

    panel.deleteLater()


def test_export_word_uses_confirm_dialog_scope_and_report_metadata(monkeypatch, tmp_path):
    """多工况导出应走报告确认流程，并按选择导出全部工况。"""
    _app()
    panel = SpillwaySteepChutePanel()
    panel._cases = [
        {**panel._default_case(), "project_name": "工况一", "custom_label": "工况一", "design_flow": 12.0},
        {**panel._default_case(), "project_name": "工况二", "custom_label": "工况二", "design_flow": 24.0},
    ]
    panel._load_case(0)

    def fake_calculate(**params):
        result = _fake_result()
        result["summary"] = {"工程名称": params["project_name"], "设计流量": f"{params['design_flow']:.2f} 立方米/秒"}
        return result

    class FakeDialog:
        def __init__(self, module_key, calc_title, auto_purpose, parent=None, n_cases=1, current_case_label=""):
            self.module_key = module_key
            self.auto_purpose = auto_purpose
            self.n_cases = n_cases
            self.current_case_label = current_case_label

        def exec(self):
            return panel_mod.QDialog.Accepted

        def get_meta(self):
            return SimpleNamespace(project_name="项目设置工程")

        def get_calc_purpose(self):
            return "确认后的计算目的"

        def get_references(self):
            return ["确认后的依据"]

        def get_export_scope(self):
            return "all"

    captured = {}
    opened = []
    save_dialog = {}
    output_path = tmp_path / "out"
    monkeypatch.setattr(panel_mod, "quick_calculate_spillway_steep_chute", fake_calculate)
    monkeypatch.setattr(panel_mod, "ExportConfirmDialog", FakeDialog)
    monkeypatch.setattr(panel_mod, "load_meta", lambda: SimpleNamespace(project_name="项目设置工程"))

    def fake_save_dialog(parent, title, default_path, file_filter):
        save_dialog.update({"parent": parent, "title": title, "default_path": default_path, "file_filter": file_filter})
        return str(output_path), ""

    monkeypatch.setattr(panel_mod.QFileDialog, "getSaveFileName", fake_save_dialog)
    monkeypatch.setattr(panel_mod, "ask_open_file", lambda path, parent=None: opened.append((path, parent)), raising=False)
    monkeypatch.setattr(
        panel_mod,
        "export_spillway_steep_chute_word",
        lambda path, payload, **kwargs: captured.update({"path": path, "payload": payload, "kwargs": kwargs}),
    )

    panel.calculate()
    panel.export_word()

    assert save_dialog["title"] == "导出计算书"
    assert Path(save_dialog["default_path"]).name == "工况一等2个工况_泄水渠与陡坡计算书.docx"
    assert captured["path"] == str(output_path.with_suffix(".docx"))
    assert opened == [(str(output_path.with_suffix(".docx")), panel)]
    assert [case["label"] for case in captured["payload"]["export_cases"]] == ["工况一", "工况二"]
    assert captured["kwargs"]["calc_purpose"] == "确认后的计算目的"
    assert captured["kwargs"]["references"] == ["确认后的依据"]
    assert captured["kwargs"]["meta"].project_name == "项目设置工程"

    panel.deleteLater()


def test_export_excel_adds_xlsx_suffix_and_asks_to_open(monkeypatch, tmp_path):
    """导出表格应补全 xlsx 后缀，并在保存成功后询问是否打开。"""
    _app()
    panel = SpillwaySteepChutePanel()
    panel.current_result = _fake_result()
    panel.input_params = {"project_name": "默认命名工程"}
    captured = {}
    opened = []
    save_dialog = {}
    output_path = tmp_path / "spillway_table"

    def fake_save_dialog(parent, title, default_path, file_filter):
        save_dialog.update({"parent": parent, "title": title, "default_path": default_path, "file_filter": file_filter})
        return str(output_path), ""

    monkeypatch.setattr(panel_mod.QFileDialog, "getSaveFileName", fake_save_dialog)
    monkeypatch.setattr(panel_mod, "ask_open_file", lambda path, parent=None: opened.append((path, parent)), raising=False)
    monkeypatch.setattr(
        panel_mod,
        "export_spillway_steep_chute_excel",
        lambda path, payload: captured.update({"path": path, "payload": payload}),
    )

    panel.export_excel()

    assert save_dialog["title"] == "导出表格"
    assert Path(save_dialog["default_path"]).name == "工况1_泄水渠与陡坡计算表.xlsx"
    assert captured["path"] == str(output_path.with_suffix(".xlsx"))
    assert captured["payload"] == panel.current_result
    assert opened == [(str(output_path.with_suffix(".xlsx")), panel)]

    panel.deleteLater()
