# -*- coding: utf-8 -*-
"""计算结果顶部重点汇总的单元测试。"""

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_渠系计算前端 import result_summary
import app_渠系计算前端.open_channel.panel as open_channel_panel_mod
import app_渠系计算前端.aqueduct.panel as aqueduct_panel_mod
import app_渠系计算前端.tunnel.panel as tunnel_panel_mod
import app_渠系计算前端.culvert.panel as culvert_panel_mod


@pytest.fixture
def local_tmp_path():
    """返回虚拟路径；本测试已替换保存动作，不需要真实落盘。"""
    return Path("unused_result_summary_unit")


def _open_channel_case(use_increase=True):
    """构造明渠梯形摘要用例。"""
    params = {
        "Q": 5.0,
        "section_type": "梯形",
        "use_increase": use_increase,
        "v_min": 0.1,
        "v_max": 100.0,
    }
    result = {
        "success": True,
        "b_design": 1.3,
        "h_design": 1.57,
        "V_design": 1.11,
        "Beta_design": 0.828,
        "Q_increased": 6.0,
        "h_increased": 1.78 if use_increase else 0.0,
        "V_increased": 1.21 if use_increase else 0.0,
        "Fb": 0.52,
        "h_prime": 2.30,
        "increase_percent": 20.0,
    }
    return params, result


def _aqueduct_case():
    """构造渡槽 U 形摘要用例。"""
    return (
        {"Q": 5.0, "section_type": "U形", "use_increase": True},
        {
            "success": True,
            "R": 1.0,
            "f": 0.8,
            "B": 2.0,
            "H_total": 1.8,
            "h_design": 1.2,
            "V_design": 1.35,
            "Q_increased": 6.0,
            "h_increased": 1.45,
            "V_increased": 1.55,
            "Fb": 0.35,
            "design_tie_bottom_clearance": 0.25,
            "increased_tie_bottom_clearance": 0.35,
            "tie_rod_height": 0.30,
            "tie_bottom_height": 1.50,
            "f_R": 0.8,
            "H_B": 0.9,
        },
    )


def _tunnel_case():
    """构造隧洞圆拱直墙型摘要用例。"""
    return (
        {"Q": 5.0, "section_type": "圆拱直墙型", "use_increase": True},
        {
            "success": True,
            "B": 3.0,
            "H_total": 2.6,
            "H_straight": 1.2,
            "theta_deg": 150.0,
            "A_total": 7.2,
            "h_design": 1.5,
            "V_design": 1.4,
            "freeboard_hgt_design": 1.1,
            "freeboard_pct_design": 22.0,
            "Q_increased": 6.0,
            "h_increased": 1.8,
            "V_increased": 1.6,
            "freeboard_hgt_inc": 0.8,
            "freeboard_pct_inc": 16.0,
        },
    )


def _tunnel_flat_bottom_case():
    """构造隧洞平底圆形摘要用例。"""
    return (
        {"Q": 5.0, "section_type": "平底圆形", "use_increase": True},
        {
            "success": True,
            "D": 4.0,
            "B": 2.0,
            "H_total": 3.732,
            "A_total": 12.8,
            "h_design": 1.5,
            "V_design": 1.4,
            "freeboard_hgt_design": 2.232,
            "freeboard_pct_design": 58.0,
            "Q_increased": 6.0,
            "h_increased": 1.8,
            "V_increased": 1.6,
            "freeboard_hgt_inc": 1.932,
            "freeboard_pct_inc": 50.0,
        },
    )


def _culvert_case():
    """构造暗涵矩形摘要用例。"""
    return (
        {"Q": 5.0, "section_type": "矩形", "use_increase": True},
        {
            "success": True,
            "B": 2.4,
            "H": 2.2,
            "BH_ratio": 1.5,
            "HB_ratio": 0.9,
            "h_design": 1.4,
            "V_design": 1.25,
            "freeboard_hgt_design": 0.8,
            "freeboard_pct_design": 20.0,
            "Q_increased": 6.0,
            "h_increased": 1.6,
            "V_increased": 1.38,
            "freeboard_hgt_inc": 0.6,
            "freeboard_pct_inc": 15.0,
            "fb_min_required": 0.4,
        },
    )


def _culvert_arch_case():
    """构造暗涵圆拱直墙型摘要用例。"""
    return (
        {"Q": 5.0, "section_type": "圆拱直墙型", "use_increase": True},
        {
            "success": True,
            "B": 3.2,
            "H_total": 2.6,
            "H_straight": 1.0,
            "theta_deg": 180.0,
            "A_total": 7.1,
            "h_design": 1.55,
            "V_design": 1.46,
            "freeboard_hgt_design": 1.05,
            "freeboard_pct_design": 40.4,
            "Q_increased": 8.4,
            "h_increased": 1.72,
            "V_increased": 1.57,
            "freeboard_hgt_inc": 0.88,
            "freeboard_pct_inc": 33.8,
            "fb_min_required": 0.4,
        },
    )


@pytest.mark.parametrize(
    ("panel_key", "case_factory", "expected"),
    [
        ("open_channel", _open_channel_case, ["底宽 B", "渠道高度 H", "渠道超高"]),
        ("aqueduct", _aqueduct_case, ["内半径 R", "槽身总高 H", "槽顶超高"]),
        ("tunnel", _tunnel_case, ["直墙高度 H直", "净空比例", "总高 H"]),
        ("culvert", _culvert_case, ["宽度 B", "净空比例", "高度 H"]),
    ],
)
def test_result_summary_html_contains_core_and_structure_specific_values(panel_key, case_factory, expected):
    """四类无压面板摘要应包含核心工况值和结构特有尺寸。"""
    params, result = case_factory()

    html = result_summary.build_result_summary_html(panel_key, params, result)

    assert "重点结果汇总" in html
    assert "设计工况" in html
    assert "加大工况" in html
    assert "设计水深" in html
    assert "设计流速" in html
    assert "加大水深" in html
    assert "加大流速" in html
    for token in expected:
        assert token in html


def test_result_summary_hides_missing_increase_group_and_shows_short_note():
    """未启用加大流量时不显示一堆空值，只给出短提示。"""
    params, result = _open_channel_case(use_increase=False)

    html = result_summary.build_result_summary_html("open_channel", params, result)

    assert "未启用加大流量" in html
    assert "加大水深" not in html
    assert "加大流速" not in html


def test_tunnel_summary_shows_hb_when_total_height_and_width_exist():
    """隧洞结果摘要应在有 H 和 B 时显示高宽比。"""
    params, result = _tunnel_case()

    html = result_summary.build_result_summary_html("tunnel", params, result)
    items = result_summary.build_result_summary_word_items("tunnel", params, result)

    assert "高宽比 H/B" in html
    assert "0.867" in html
    assert ("结构尺寸 - 高宽比 H/B", "0.867") in items


def test_flat_bottom_tunnel_summary_shows_hb_when_total_height_and_width_exist():
    """平底圆形隧洞也应按总高和平底宽显示高宽比。"""
    params, result = _tunnel_flat_bottom_case()

    html = result_summary.build_result_summary_html("tunnel", params, result)
    items = result_summary.build_result_summary_word_items("tunnel", params, result)

    assert "高宽比 H/B" in html
    assert "1.866" in html
    assert ("结构尺寸 - 高宽比 H/B", "1.866") in items


def test_arch_culvert_summary_shows_hb_when_total_height_and_width_exist():
    """圆拱直墙型暗涵应按总高和宽度显示高宽比。"""
    params, result = _culvert_arch_case()

    html = result_summary.build_result_summary_html("culvert", params, result)
    items = result_summary.build_result_summary_word_items("culvert", params, result)

    assert "高宽比 H/B" in html
    assert "0.812" in html
    assert ("结构尺寸 - 高宽比 H/B", "0.812") in items


def test_culvert_summary_uses_kernel_freeboard_check_for_boundary_pass():
    """暗涵净空边界值应优先沿用内核校核结果，避免显示误判。"""
    params, result = _culvert_case()
    result.update(
        {
            "h_increased": 1.979539081221729,
            "V_increased": 1.29949317976613,
            "freeboard_hgt_inc": 0.3999723470054761,
            "freeboard_pct_inc": 16.809011390353586,
            "fb_min_required": 0.4,
            "fb_check_passed": True,
        }
    )

    html = result_summary.build_result_summary_html("culvert", params, result)
    items = result_summary.build_result_summary_word_items("culvert", params, result)

    assert "净空校核" in html
    assert "通过" in html
    assert ("校核状态 - 净空校核", "通过") in items


def test_culvert_summary_still_warns_when_freeboard_really_fails():
    """暗涵净空真实不满足时，重点汇总仍应提示需注意。"""
    params, result = _culvert_case()
    result.update(
        {
            "h_increased": 2.1,
            "V_increased": 1.3,
            "freeboard_hgt_inc": 0.2,
            "freeboard_pct_inc": 8.0,
            "fb_min_required": 0.4,
            "fb_check_passed": False,
        }
    )

    items = result_summary.build_result_summary_word_items("culvert", params, result)

    assert ("校核状态 - 净空校核", "需注意") in items


def test_open_channel_summary_uses_increase_freeboard_when_increase_enabled():
    """启用加大流量时，明渠摘要只显示加大工况规范超高。"""
    params, result = _open_channel_case(use_increase=True)
    result.update({
        "h_design": 1.570,
        "h_increased": 1.714,
        "V_increased": 1.161,
        "Fb": 0.629,
        "h_prime": 2.343,
    })

    html = result_summary.build_result_summary_html("open_channel", params, result)
    items = result_summary.build_result_summary_word_items("open_channel", params, result)

    assert "加大渠道超高" in html
    assert "0.629 m" in html
    assert "设计渠道超高" not in html
    assert "0.773 m" not in html
    assert ("超高 - 加大渠道超高", "0.629 m") in items
    assert not any(name == "超高 - 设计渠道超高" for name, _value in items)


def test_open_channel_summary_uses_design_freeboard_when_increase_disabled():
    """未启用加大流量时，明渠摘要显示设计工况规范超高。"""
    params, result = _open_channel_case(use_increase=False)
    result.update({
        "h_design": 1.570,
        "h_increased": 0.0,
        "V_increased": 0.0,
        "Fb": 0.593,
    })
    result.pop("h_prime", None)

    html = result_summary.build_result_summary_html("open_channel", params, result)
    items = result_summary.build_result_summary_word_items("open_channel", params, result)

    assert "设计渠道超高" in html
    assert "0.593 m" in html
    assert "加大渠道超高" not in html
    assert ("超高 - 设计渠道超高", "0.593 m") in items


def test_aqueduct_summary_separates_top_freeboard_and_tie_bottom_clearance():
    """有拉杆时摘要应同时说明槽顶超高和拉杆底净距。"""
    params, result = _aqueduct_case()

    html = result_summary.build_result_summary_html("aqueduct", params, result)
    items = result_summary.build_result_summary_word_items("aqueduct", params, result)

    assert "设计槽顶超高" in html
    assert "设计拉杆底净距" in html
    assert "加大有效超高" in html
    assert "加大拉杆底净距" not in html
    assert ("超高 - 设计拉杆底净距", "0.250 m") in items
    assert ("超高 - 加大有效超高", "0.350 m") in items


def test_result_summary_word_items_are_flattened_for_report_table():
    """Word 报告应能复用同一套摘要数据生成二维汇总表。"""
    params, result = _tunnel_case()

    items = result_summary.build_result_summary_word_items("tunnel", params, result)

    assert ("设计工况 - 设计流量 Q", "5.000 m³/s") in items
    assert ("加大工况 - 加大流量 Q加大", "6.000 m³/s") in items
    assert any(name == "结构尺寸 - 直墙高度 H直" and value == "1.200 m" for name, value in items)
    assert ("结构尺寸 - 高宽比 H/B", "0.867") in items


class _DocStub:
    """Word 文档对象的轻量替身。"""

    def add_page_break(self):
        return None

    def save(self, filepath):
        return None


def _patch_word_helpers(monkeypatch, module, captured_tables):
    """替换 Word 导出依赖，只保留汇总表调用。"""
    monkeypatch.setattr(module, "create_engineering_report_doc", lambda **_kwargs: _DocStub())
    monkeypatch.setattr(module, "doc_add_eng_h", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "doc_add_eng_body", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "doc_add_formula", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "doc_render_calc_text_eng", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "doc_add_figure", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "doc_add_table_caption", lambda *_args, **_kwargs: None, raising=False)
    monkeypatch.setattr(module, "doc_add_styled_table", lambda *_args, **_kwargs: None, raising=False)
    monkeypatch.setattr(
        module,
        "doc_add_result_table",
        lambda _doc, items: captured_tables.append(list(items)),
        raising=False,
    )


def test_four_word_reports_insert_key_result_summary_table(monkeypatch, local_tmp_path):
    """四个目标面板的 Word 报告应在每个工况计算过程前加入重点汇总表。"""
    captured = {}

    open_params, open_result = _open_channel_case()
    open_dummy = type("_OpenDummy", (), {})()
    open_dummy._all_results = [(0, open_params, open_result)]
    open_dummy._current_case_idx = 0
    open_dummy._word_export_meta = {}
    open_dummy._word_export_purpose = ""
    open_dummy._word_export_refs = []
    open_dummy._word_export_scope = "all"
    open_dummy.input_params = open_params
    open_dummy.current_result = open_result
    open_dummy._export_plain_text = "明渠水力计算结果\n"
    open_dummy._update_result_display = lambda _result: None
    captured["open"] = []
    _patch_word_helpers(monkeypatch, open_channel_panel_mod, captured["open"])
    open_channel_panel_mod.OpenChannelPanel._build_word_report(open_dummy, str(local_tmp_path / "open.docx"))

    aqueduct_params, aqueduct_result = _aqueduct_case()
    aqueduct_dummy = type("_AqueductDummy", (), {})()
    aqueduct_dummy._all_results = [(0, aqueduct_params, aqueduct_result)]
    aqueduct_dummy._current_case_idx = 0
    aqueduct_dummy._word_export_meta = {}
    aqueduct_dummy._word_export_purpose = ""
    aqueduct_dummy._word_export_refs = []
    aqueduct_dummy._word_export_scope = "all"
    aqueduct_dummy.input_params = aqueduct_params
    aqueduct_dummy.current_result = aqueduct_result
    aqueduct_dummy._export_plain_text = "渡槽水力计算结果\n"
    aqueduct_dummy._update_result_display = lambda _result: None
    captured["aqueduct"] = []
    _patch_word_helpers(monkeypatch, aqueduct_panel_mod, captured["aqueduct"])
    aqueduct_panel_mod.AqueductPanel._build_word_report(aqueduct_dummy, str(local_tmp_path / "aqueduct.docx"))

    tunnel_params, tunnel_result = _tunnel_case()
    tunnel_dummy = type("_TunnelDummy", (), {})()
    tunnel_dummy._all_results = [
        {"label": "工况1", "input": tunnel_params, "result": tunnel_result, "case": tunnel_params}
    ]
    tunnel_dummy._current_case_idx = 0
    tunnel_dummy._word_export_meta = {}
    tunnel_dummy._word_export_purpose = ""
    tunnel_dummy._word_export_refs = []
    tunnel_dummy._word_export_scope = "all"
    tunnel_dummy._build_result_text = lambda _res, _type_label, _detail, _inp: "隧洞水力计算结果\n"
    captured["tunnel"] = []
    _patch_word_helpers(monkeypatch, tunnel_panel_mod, captured["tunnel"])
    tunnel_panel_mod.TunnelPanel._build_word_report(tunnel_dummy, str(local_tmp_path / "tunnel.docx"))

    culvert_params, culvert_result = _culvert_case()
    culvert_dummy = type("_CulvertDummy", (), {})()
    culvert_dummy._all_results = [(0, culvert_params, culvert_result)]
    culvert_dummy._cases = [{"detail_checked": True}]
    culvert_dummy._current_case_idx = 0
    culvert_dummy._word_export_meta = {}
    culvert_dummy._word_export_purpose = ""
    culvert_dummy._word_export_refs = []
    culvert_dummy._word_export_scope = "all"
    culvert_dummy._build_culvert_result_text = lambda _params, _result, _detail, _case_num=None: "暗涵水力计算结果\n"
    captured["culvert"] = []
    _patch_word_helpers(monkeypatch, culvert_panel_mod, captured["culvert"])
    culvert_panel_mod.CulvertPanel._build_word_report(culvert_dummy, str(local_tmp_path / "culvert.docx"))

    for panel_key, tables in captured.items():
        assert tables, f"{panel_key} 未写入重点结果汇总表"
        flat_names = [name for table in tables for name, _value in table]
        assert any(name.startswith("设计工况 - 设计流量") for name in flat_names)
