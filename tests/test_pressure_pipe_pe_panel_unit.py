# -*- coding: utf-8 -*-
"""PE 管规格在有压管道面板中的输入、展示与批量配置回归。"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFileDialog

from app_渠系计算前端.pressure_pipe import panel as panel_module
from app_渠系计算前端.pressure_pipe.panel import PressurePipePanel
from 有压管道设计 import recommend_diameter


@pytest.fixture(scope="module")
def qapp():
    """为离屏面板测试提供唯一 QApplication。"""
    return QApplication.instance() or QApplication([])


@pytest.fixture
def pe_panel(qapp):
    """创建并在用例后释放 PE 面板。"""
    widget = PressurePipePanel()
    yield widget
    widget.close()
    widget.deleteLater()
    qapp.processEvents()


def test_pe_controls_and_spec_roundtrip(pe_panel):
    """PE 应使用等级、PN 和 DN，原任意内径 D 输入应隐藏。"""
    assert pe_panel._current_material_key() == "HDPE管"
    assert pe_panel.material_combo.itemText(0) == "聚乙烯（PE）管"
    assert pe_panel._mat_cbs["HDPE管"].text() == "聚乙烯（PE）管"
    assert pe_panel.pe_grade_combo.currentText() == "PE100"
    assert "PN 1 MPa" in pe_panel.pe_pn_combo.currentText()
    assert "SDR 17" in pe_panel.pe_pn_combo.currentText()
    assert pe_panel.D_edit.isHidden() is True
    assert pe_panel.pe_dn_edit.isHidden() is False

    pe_panel.pe_dn_edit.setText("355")
    pe_panel._save_current_case()
    saved_case = dict(pe_panel._cases[0])
    parsed = pe_panel._parse_case(saved_case, 1)

    assert saved_case["pe_grade"] == "PE100"
    assert saved_case["pe_pn_mpa"] == pytest.approx(1.0)
    assert saved_case["pe_dn_mm"] == "355"
    assert parsed.pe_material_grade == "PE100"
    assert parsed.pe_nominal_pressure_mpa == pytest.approx(1.0)
    assert parsed.manual_nominal_diameter_mm == pytest.approx(355.0)

    pe_panel.pe_dn_edit.setText("")
    pe_panel.pe_grade_combo.setCurrentIndex(1)
    pe_panel._save_current_case()
    pe_panel.pe_grade_combo.setCurrentIndex(0)
    pe_panel._load_case(0)

    assert pe_panel.pe_grade_combo.currentText() == "PE80"
    assert "PN 1 MPa" in pe_panel.pe_pn_combo.currentText()
    assert "SDR 13.6" in pe_panel.pe_pn_combo.currentText()


def test_pe_invalid_dn_explains_discrete_standard_sizes(pe_panel):
    """非标准 PE 公称外径应在计算前给出可理解的错误。"""
    case = pe_panel._default_case()
    case["pe_dn_mm"] = "350"

    with pytest.raises(ValueError, match="离散规格"):
        pe_panel._parse_case(case, 1)


def test_pe_learning_hint_explains_grade_pressure_and_direct_dn_mode(pe_panel):
    """选径说明随材料和外径变化，简短说明程序自动处理的内容。"""
    hint = pe_panel.pe_spec_hint.text()
    assert "PE100 为材料等级，PN 1 MPa 为公称压力" in hint
    assert "SDR 17 已按规范自动匹配" in hint
    assert "管径留空" in hint
    assert "满足流速和水损要求的最小管径" in hint
    assert "工程提醒" not in hint
    assert "PE80、PE100 表示管材的材料等级" in pe_panel.pe_grade_combo.toolTip()
    assert "按规范匹配 SDR，无需另填" in pe_panel.pe_pn_combo.toolTip()
    assert "留空时由程序按规范推荐" in pe_panel.pe_dn_edit.toolTip()

    pe_panel.pe_dn_edit.setText("355")
    assert "已指定外径 355 mm" in pe_panel.pe_spec_hint.text()
    assert "自动查取壁厚，并按内径计算水损" in pe_panel.pe_spec_hint.text()

    pe_panel.pe_dn_edit.clear()
    pe_panel.pe_grade_combo.setCurrentText("PE80")
    assert "PE80 为材料等级" in pe_panel.pe_spec_hint.text()
    assert "SDR 13.6 已按规范自动匹配" in pe_panel.pe_spec_hint.text()


def test_batch_pe_learning_hint_tracks_grade_and_pn(pe_panel):
    """批量与单次采用一致的简短说明，并随材料和压力更新。"""
    assert "PE100 为材料等级，PN 1 MPa 为公称压力" in pe_panel.batch_pe_spec_hint.text()
    assert "SDR 17 已按规范自动匹配" in pe_panel.batch_pe_spec_hint.text()
    assert "批量计算会按规范推荐" in pe_panel.batch_pe_spec_hint.text()
    assert "留空" not in pe_panel.batch_pe_spec_hint.text()

    pe_panel.batch_pe_grade_combo.setCurrentText("PE80")
    assert "PE80 为材料等级，PN 1 MPa 为公称压力" in pe_panel.batch_pe_spec_hint.text()
    assert "SDR 13.6 已按规范自动匹配" in pe_panel.batch_pe_spec_hint.text()
    assert "复核" not in pe_panel.batch_pe_spec_hint.text()


def test_nonstandard_dn_live_guidance_lists_neighbours_and_applies_upper(pe_panel):
    """输入 600 mm 时应实时建议 560/630，并由用户点击采用上邻规格。"""
    pe_panel.pe_dn_edit.setText("600")

    hint = pe_panel.pe_dn_guidance_hint.text()
    assert "600 mm 不是当前材料和压力下的标准外径" in hint
    assert "附近可选外径：500、560、630、710 mm" in hint
    assert "可先选大一档的 630 mm，再计算流速和水损" in hint
    assert pe_panel.pe_dn_edit.text() == "600"
    assert pe_panel.pe_dn_guidance_row.isHidden() is False
    assert pe_panel.pe_dn_use_upper_btn.isHidden() is False
    assert pe_panel.pe_dn_use_upper_btn.text() == "采用 630 mm"

    case = pe_panel._default_case()
    case["pe_dn_mm"] = "600"
    with pytest.raises(ValueError) as exc_info:
        pe_panel._parse_case(case, 1)
    assert "附近规范 DN（mm）：500、560、630、710" in str(exc_info.value)
    assert "建议先从上邻规格 DN=630 mm" in str(exc_info.value)

    pe_panel.pe_dn_use_upper_btn.click()

    assert pe_panel.pe_dn_edit.text() == "630"
    assert "标准外径 630 mm" in pe_panel.pe_dn_guidance_hint.text()
    assert "壁厚 37.4 mm；计算内径 555.2 mm" in pe_panel.pe_dn_guidance_hint.text()
    assert pe_panel.pe_dn_use_upper_btn.isHidden() is True


def test_pe_result_card_prioritizes_procurement_spec_and_lists_inner_diameter(pe_panel):
    """结果卡和候选表应先显示造价规格，再显示水力内径。"""
    case = pe_panel._default_case()
    case["pe_dn_mm"] = "355"
    inp = pe_panel._parse_case(case, 1)
    result = recommend_diameter(inp)
    pe_panel._all_results = [(0, inp, result)]

    html = pe_panel._build_result_card_html(0, inp, result)

    assert "造价 / 采购规格" in html
    assert "PE100给水管，DN355×21.1 mm，SDR17，PN1 MPa" in html
    assert "GB/T 13663.2—2018" in html
    assert "水力计算采用名义内径 d<sub>i</sub> = 312.8 mm" in html
    assert "公称外径 × 壁厚<br>DN×en(mm)" in html
    assert "水力内径<br>di(mm)" in html
    assert pe_panel._case_result_nav_summary(0, inp, result) == (
        "Q=0.5 · DN=355mm · di=312.8mm"
    )


def test_legacy_pe_manual_inner_diameter_survives_ui_save_and_warns(pe_panel):
    """旧项目在点击计算前的 UI 保存不得丢失原水力内径，并应安全上取和提示。"""
    legacy_case = {
        "custom_label": None,
        "Q": "0.5",
        "material_idx": 0,
        "length": "1000",
        "local_ratio": "0.15",
        "D": "0.8",
        "inc_checked": True,
        "inc_pct": "",
        "inc_mode": "percent",
        "inc_q_text": "",
    }
    pe_panel._cases = [legacy_case]
    pe_panel._current_case_idx = 0
    pe_panel._load_case(0)
    pe_panel._save_current_case()

    saved_case = pe_panel._cases[0]
    assert saved_case["legacy_pe_manual_D"] == "0.8"
    inp = pe_panel._parse_case(saved_case, 1)
    result = recommend_diameter(inp)
    candidate = result.recommended

    assert inp.manual_D == pytest.approx(0.8)
    assert candidate.nominal_outer_diameter_mm == 1000
    assert candidate.hydraulic_inner_diameter_mm == pytest.approx(881.4)
    html = pe_panel._build_result_card_html(0, inp, result)
    assert "旧项目规格迁移" in html
    assert "旧版水力内径 0.8 m 已安全上取为标准规格" in html


def test_legacy_multi_case_restore_and_copy_preserve_migration_value(pe_panel, monkeypatch):
    """旧多工况应先整体迁移再复制，不能缺新键或丢失旧 PE 水力内径。"""
    # 离屏测试不触发 Qt WebEngine 帮助页渲染，只验证项目恢复与复制数据链。
    monkeypatch.setattr(pe_panel, "_show_initial_help", lambda: None)
    old_case_1 = {
        "Q": "0.5", "material_idx": 0, "length": "1000",
        "local_ratio": "0.15", "D": "0.6", "inc_checked": True,
        "inc_pct": "", "inc_mode": "percent", "inc_q_text": "",
    }
    old_case_2 = {
        "Q": "0.8", "material_idx": 0, "length": "1200",
        "local_ratio": "0.15", "D": "0.8", "inc_checked": True,
        "inc_pct": "", "inc_mode": "percent", "inc_q_text": "",
    }

    pe_panel.from_project_dict({
        "cases": [old_case_1, old_case_2],
        "current_case_idx": 1,
    })

    assert pe_panel._cases[0]["pe_grade"] == "PE100"
    assert pe_panel._cases[1]["pe_dn_mm"] == ""
    assert pe_panel._cases[0]["legacy_pe_manual_D"] == "0.6"
    assert pe_panel._cases[1]["legacy_pe_manual_D"] == "0.8"

    pe_panel._copy_from_prev_case()

    assert pe_panel._cases[1]["legacy_pe_manual_D"] == "0.6"
    parsed = pe_panel._parse_case(pe_panel._cases[1], 2)
    assert parsed.manual_D == pytest.approx(0.6)


def test_case_copy_clears_stale_legacy_marker_for_new_pe_spec(pe_panel):
    """复制显式新 DN 时，应清除目标工况残留的旧内径迁移标记。"""
    source = pe_panel._default_case()
    source["pe_dn_mm"] = "355"
    target = pe_panel._default_case()
    target["legacy_pe_manual_D"] = "0.8"

    pe_panel._copy_case_parameters(source, target)

    assert target["pe_dn_mm"] == "355"
    assert "legacy_pe_manual_D" not in target


def test_word_references_follow_actual_pe_product_metadata():
    """PE 产品规范只随带 DN/en 的新成果进入 Word，且不会重复。"""
    common = ["通用规范", "通用规范"]
    non_pe_refs = panel_module._pressure_pipe_report_references(common, False)
    pe_refs = panel_module._pressure_pipe_report_references(common, True)

    assert non_pe_refs == ["通用规范"]
    assert pe_refs == ["通用规范", *panel_module.PE_WORD_REFERENCES]
    assert panel_module._pressure_pipe_report_references(pe_refs, True) == pe_refs

    old_candidate = SimpleNamespace(nominal_outer_diameter_mm=None)
    new_candidate = SimpleNamespace(nominal_outer_diameter_mm=355.0)
    old_results = [(0, SimpleNamespace(), SimpleNamespace(recommended=old_candidate))]
    new_results = [(0, SimpleNamespace(), SimpleNamespace(recommended=new_candidate))]
    assert panel_module._results_have_pe_product_specs(old_results) is False
    assert panel_module._results_have_pe_product_specs(new_results) is True


class _SignalStub:
    """批量线程测试用信号桩。"""

    def connect(self, _slot):
        """接受信号连接而不启动后台计算。"""


def test_batch_uses_material_catalog_and_passes_pe_selection(pe_panel, monkeypatch):
    """生产批量配置应将管径交给内核目录，并传递 PE 等级与 PN。"""
    captured = {}

    class _WorkerStub:
        """记录批量配置的后台线程桩。"""

        def __init__(self, config, _parent):
            captured["config"] = config
            self.progress = _SignalStub()
            self.finished = _SignalStub()
            self.error = _SignalStub()

        def start(self):
            """记录启动，不执行真实批量计算。"""
            captured["started"] = True

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_args: os.getcwd())
    monkeypatch.setattr(panel_module, "_BatchWorker", _WorkerStub)
    pe_panel._start_batch()

    config = captured["config"]
    assert captured["started"] is True
    assert config.diameter_values is None
    assert config.use_product_catalogs is True
    assert not hasattr(pe_panel, "batch_product_catalog_cb")
    assert config.pe_material_grade == "PE100"
    assert config.pe_nominal_pressure_mpa == pytest.approx(1.0)
