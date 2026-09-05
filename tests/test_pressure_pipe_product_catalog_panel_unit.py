# -*- coding: utf-8 -*-
"""DI、PCCP、FRPM 产品目录在有压管道面板中的接入与兼容回归。"""

from __future__ import annotations

import os
from dataclasses import replace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app_渠系计算前端.pressure_pipe.panel import (
    LEGACY_MATERIAL_KEY_ORDER_V1,
    PressurePipePanel,
    _pressure_pipe_report_references,
)
from app_渠系计算前端.report_meta import PRESSURE_PIPE_PRODUCT_REFERENCES
from 有压管道设计 import recommend_diameter


@pytest.fixture(scope="module")
def qapp():
    """为离屏目录面板测试提供唯一 QApplication。"""
    return QApplication.instance() or QApplication([])


@pytest.fixture
def product_panel(qapp):
    """创建并释放一个产品目录面板。"""
    widget = PressurePipePanel()
    yield widget
    widget.close()
    widget.deleteLater()
    qapp.processEvents()


def _case_for(panel, material_key, **updates):
    """构造带稳定材料键的新目录工况。"""
    case = panel._default_case()
    case.update({
        "material_key": material_key,
        "material_idx": panel._mat_keys.index(material_key),
    })
    case.update(updates)
    return case


def test_new_case_defaults_and_frozen_legacy_material_order(product_panel):
    """新工况默认启用目录和 PCCPE，旧索引顺序必须冻结。"""
    case = product_panel._default_case()
    assert case["catalog_schema_version"] == 2
    assert case["use_product_catalog"] is True
    assert case["pccp_variant"] == "PCCPE"
    assert LEGACY_MATERIAL_KEY_ORDER_V1 == (
        "HDPE管", "玻璃钢夹砂管", "球墨铸铁管",
        "预应力钢筒混凝土管", "预应力钢筒混凝土管_n014",
        "预应力钢筒混凝土管_n015", "钢管",
    )


def test_catalog_controls_follow_material_and_keep_pccp_variant_independent(product_panel):
    """目录控件应按材料显隐，PCCP 型式不由三档摩阻预设决定。"""
    product_panel.material_combo.setCurrentIndex(product_panel._mat_keys.index("球墨铸铁管"))
    assert not hasattr(product_panel, "product_catalog_cb")
    assert product_panel.product_catalog_upgrade_btn.isHidden() is True
    assert product_panel.di_class_combo.currentText() == "规范推荐"
    product_panel._save_current_case()
    assert product_panel._parse_case(product_panel._cases[0], 1).use_product_catalog is True
    assert product_panel.product_dn_edit.isHidden() is False
    assert product_panel.di_class_row.isHidden() is False
    assert product_panel.pccp_variant_row.isHidden() is True
    assert product_panel.D_edit.isHidden() is True

    product_panel.material_combo.setCurrentIndex(
        product_panel._mat_keys.index("预应力钢筒混凝土管_n015")
    )
    assert product_panel.di_class_row.isHidden() is True
    assert product_panel.pccp_variant_row.isHidden() is False
    assert product_panel._selected_pccp_variant() == "PCCPE"
    product_panel.pccp_variant_combo.setCurrentIndex(1)
    assert product_panel._selected_pccp_variant() == "PCCPL"
    assert "管型和摩阻参数可分别选择" in product_panel.product_catalog_hint.text()

    product_panel.material_combo.setCurrentIndex(product_panel._mat_keys.index("钢管"))
    assert product_panel.product_dn_edit.isHidden() is True
    assert product_panel.D_edit.isHidden() is True
    assert product_panel.steel_controls.isHidden() is False


@pytest.mark.parametrize(
    ("material_key", "product_dn", "variant", "family", "expected_d"),
    [
        ("球墨铸铁管", "300", "PCCPE", "DI", 0.3056),
        ("预应力钢筒混凝土管", "1600", "PCCPE", "PCCP", 1.6),
        ("预应力钢筒混凝土管_n014", "600", "PCCPL", "PCCP", 0.6),
        ("玻璃钢夹砂管", "2800", "PCCPE", "FRPM", 2.8),
    ],
)
def test_parse_and_calculate_product_catalog_case(
    product_panel, material_key, product_dn, variant, family, expected_d,
):
    """面板解析应把公称口径、DI等级和 PCCP 型式传入核心。"""
    case = _case_for(
        product_panel,
        material_key,
        product_dn_mm=product_dn,
        pccp_variant=variant,
        ductile_iron_class="PREFERRED",
        use_product_catalog=True,
    )
    parsed = product_panel._parse_case(case, 1)
    result = recommend_diameter(parsed)
    candidate = result.recommended

    assert parsed.manual_product_diameter_mm == pytest.approx(float(product_dn))
    assert parsed.pccp_variant == variant
    assert candidate is not None
    assert candidate.product_family == family
    assert candidate.D == pytest.approx(expected_d)
    if family == "PCCP":
        assert candidate.product_variant == variant


@pytest.mark.parametrize("edited_d", ["0.55", "0.6"])
def test_legacy_non_pe_case_keeps_hydraulic_d_until_user_enables_catalog(product_panel, edited_d):
    """缺少目录版本的旧 DI 工况必须继续按水力内径 D 解析。"""
    legacy_case = {
        "Q": "0.5",
        "material_idx": 2,
        "length": "1000",
        "local_ratio": "0.15",
        "D": "0.55",
        "inc_checked": True,
        "inc_pct": "",
        "inc_mode": "percent",
        "inc_q_text": "",
    }
    normalized = product_panel._normalized_case_data(legacy_case)
    parsed = product_panel._parse_case(normalized, 1)

    assert normalized["material_key"] == "球墨铸铁管"
    assert normalized["use_product_catalog"] is False
    assert normalized["legacy_product_manual_D"] == "0.55"
    assert parsed.use_product_catalog is False
    assert parsed.manual_D == pytest.approx(0.55)
    result = recommend_diameter(parsed)
    assert result.recommended is not None
    assert result.recommended.product_family is None
    assert result.recommended.D == pytest.approx(0.55)

    product_panel._cases = [normalized]
    product_panel._current_case_idx = 0
    product_panel._load_case(0)
    assert product_panel.product_catalog_upgrade_btn.isHidden() is False
    assert product_panel.D_edit.text() == "0.55"
    product_panel.D_edit.setText(edited_d)
    product_panel.product_catalog_upgrade_btn.click()
    assert product_panel.product_catalog_upgrade_btn.isHidden() is True
    assert product_panel.D_edit.isHidden() is True
    product_panel.product_dn_edit.clear()
    product_panel._save_current_case()
    migrated_case = product_panel._cases[0]
    assert migrated_case["legacy_product_manual_D"] == edited_d

    migrated = product_panel._parse_case(migrated_case, 1)
    migrated_result = recommend_diameter(migrated)
    assert migrated.manual_D == pytest.approx(float(edited_d))
    assert migrated_result.recommended is not None
    assert migrated_result.recommended.product_family == "DI"
    assert migrated_result.recommended.D >= float(edited_d)
    assert any(
        "旧版水力内径" in flag and "安全上取" in flag
        for flag in migrated_result.recommended.flags
    )


def test_material_key_has_priority_and_product_references_are_dynamic(product_panel):
    """稳定材料键应优先于旧索引，报告只追加实际采用的产品依据。"""
    normalized = product_panel._normalized_case_data({
        "material_key": "玻璃钢夹砂管",
        "material_idx": 0,
        "catalog_schema_version": 1,
    })
    assert normalized["material_key"] == "玻璃钢夹砂管"
    assert normalized["material_idx"] == product_panel._mat_keys.index("玻璃钢夹砂管")

    references = _pressure_pipe_report_references(
        ["基础依据"], False, {"DI", "FRPM"}
    )
    assert references[0] == "基础依据"
    assert all(item in references for item in PRESSURE_PIPE_PRODUCT_REFERENCES["DI"])
    assert all(item in references for item in PRESSURE_PIPE_PRODUCT_REFERENCES["FRPM"])
    assert all(item not in references for item in PRESSURE_PIPE_PRODUCT_REFERENCES["PCCP"])


def test_di_result_card_prioritizes_procurement_spec_and_derived_inner_diameter(product_panel):
    """DI 结果卡应同时列采购规格、换算内径、上下限水损和标准依据。"""
    case = _case_for(
        product_panel,
        "球墨铸铁管",
        product_dn_mm="800",
        use_product_catalog=True,
    )
    parsed = product_panel._parse_case(case, 1)
    result = recommend_diameter(parsed)
    html = product_panel._build_result_card_html(0, parsed, result)

    assert "造价 / 采购规格" in html
    assert "球墨铸铁管 DN800" in html
    assert "GB/T 17457—2019" in html
    assert "GB/T 13295—2026" in html
    assert "水力计算采用" in html
    assert "d<sub>i</sub> =" in html
    assert "f 下限" in html
    assert "f 上限" in html


def test_frpm_result_card_exposes_end_inner_diameter_range_and_tolerance(product_panel):
    """FRPM 一级结果应显示管端内径范围和相对设计值允许偏差。"""
    case = _case_for(
        product_panel,
        "玻璃钢夹砂管",
        product_dn_mm="2800",
        use_product_catalog=True,
    )
    parsed = product_panel._parse_case(case, 1)
    result = recommend_diameter(parsed)
    html = product_panel._build_result_card_html(0, parsed, result)

    assert "管端内直径允许范围" in html
    assert "2795～2820 mm" in html
    assert "相对所选设计内径值允许偏差" in html
    assert "±6 mm" in html


@pytest.mark.parametrize("old_class", ["K8", "K9", "K10"])
def test_legacy_k_selection_survives_load_save_until_explicit_reselection(product_panel, old_class):
    """旧 K 等级在载入、保存和复制后仍保留，必须主动选 C 等级才能重算。"""
    case = _case_for(product_panel, "球墨铸铁管", catalog_schema_version=1,
                     ductile_iron_class=old_class, product_dn_mm="300")
    product_panel._cases = [case]
    product_panel._current_case_idx = 0
    product_panel._load_case(0)
    assert product_panel._selected_di_class() == old_class
    assert "需重新选级" in product_panel.product_catalog_hint.text()
    product_panel._save_current_case()
    saved = product_panel._cases[0]
    assert saved["ductile_iron_class"] == old_class
    copied = product_panel._default_case()
    product_panel._copy_case_parameters(saved, copied)
    with pytest.raises(ValueError, match="新版已删除 K"):
        product_panel._parse_case(copied, 1)
    product_panel.di_class_combo.setCurrentIndex(product_panel._di_class_options.index("C40"))
    product_panel._save_current_case()
    parsed = product_panel._parse_case(product_panel._cases[0], 1)
    assert recommend_diameter(parsed).recommended.product_standard == "GB/T 13295—2026"


def test_saved_2019_result_keeps_original_report_references(product_panel):
    """恢复旧成果时按快照列旧依据，混合新旧成果时才并列两个版本。"""
    case = _case_for(product_panel, "球墨铸铁管", product_dn_mm="300")
    parsed = product_panel._parse_case(case, 1)
    current = recommend_diameter(parsed)
    old_candidate = replace(
        current.recommended, product_standard="GB/T 13295—2019",
        product_spec_id="DI|K9|CML|DN300", class_code="K9",
        product_standard_references=("T/CWHIDA 0002—2018", "GB/T 13295—2019"),
    )
    old = replace(current, recommended=old_candidate)
    snapshots = [(0, parsed, old)]
    references = _pressure_pipe_report_references([], False, {"DI"}, all_results=snapshots)
    assert any("13295-2019" in ref for ref in references)
    assert not any("13295-2026" in ref for ref in references)
    references = _pressure_pipe_report_references(
        [], False, {"DI"}, all_results=snapshots + [(1, parsed, current)],
    )
    assert sum("13295-2019" in ref for ref in references) == 1
    assert sum("13295-2026" in ref for ref in references) == 1


@pytest.mark.parametrize('field', ['Q', 'length', 'local_ratio'])
@pytest.mark.parametrize('value', ['nan', 'inf', '-inf'])
def test_product_panel_rejects_nonfinite_hydraulic_inputs(product_panel, field, value):
    """界面解析直接拦截非有限数，不把错误留到成果阶段。"""
    case = _case_for(product_panel, '球墨铸铁管', product_dn_mm='300')
    case[field] = value
    with pytest.raises(ValueError, match='有限数值'):
        product_panel._parse_case(case, 1)
