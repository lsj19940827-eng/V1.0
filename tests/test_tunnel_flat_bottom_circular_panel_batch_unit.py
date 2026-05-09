# -*- coding: utf-8 -*-
"""平底圆形隧洞在单断面页与批量页中的轻量回归测试。"""

import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from matplotlib.figure import Figure
from PySide6.QtWidgets import QDialog

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(tempfile.gettempdir()) / "codex-mplconfig"),
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_渠系计算前端.batch.panel import (
    BatchPanel,
    INPUT_HEADERS,
    SECTION_TYPES,
    SectionParameterDialog,
    _HEADER_TOOLTIPS,
)
from app_渠系计算前端.tunnel.panel import TunnelPanel
import app_渠系计算前端.batch.panel as batch_panel_mod
import app_渠系计算前端.tunnel.panel as tunnel_panel_mod


class _FakeTextView:
    """模拟结果文本视图。"""

    def __init__(self):
        self.html = ""

    def setHtml(self, html):
        self.html = str(html)


class _TunnelDummy:
    """承载单断面页纯逻辑方法的轻量对象。"""

    _resolve_result_type_label = TunnelPanel._resolve_result_type_label
    _build_result_text = TunnelPanel._build_result_text

    def __init__(self):
        self.result_text = _FakeTextView()
        self._export_plain_text = ""
        self._panel_key = "tunnel"
        self._result_case_nav = None
        self._all_results = []
        self._current_case_idx = 0
        self.section_fig = Figure()
        self._word_export_scope = "all"
        self._word_export_meta = {}
        self._word_export_purpose = ""
        self._word_export_refs = []
        self.input_params = {}
        self._results_fresh = False

    def _case_result_nav_label(self, case_idx):
        return f"工况 {case_idx + 1}"

    def _build_case_nav_items(self):
        return []

    def _mark_results_fresh(self):
        self._results_fresh = True

    def _jump_to_case_result(self, _case_idx, defer_until_load=False):
        _ = defer_until_load
        return True


class _FakeTable:
    """批量表格的最小替身。"""

    def __init__(self):
        self._items = {}
        self._signals_blocked = False

    def rowCount(self):
        return 1

    def blockSignals(self, blocked):
        self._signals_blocked = bool(blocked)

    def setItem(self, row, col, item):
        self._items[(row, col)] = item

    def item(self, row, col):
        return self._items.get((row, col))


class _FakeEntry:
    """模拟参数弹窗输入框。"""

    def __init__(self, text):
        self._text = str(text)

    def text(self):
        return self._text


def _build_flat_bottom_case():
    """构造平底圆形工况字典。"""
    return {
        "section_type": "平底圆形",
        "Q": "5.0",
        "n": "0.014",
        "slope_inv": "2000",
        "v_min": "0.1",
        "v_max": "100",
        "inc_checked": True,
        "inc_pct": "",
        "detail_checked": True,
        "flat_bottom_D": "4.0",
        "flat_bottom_B": "2.0",
    }


@pytest.fixture
def local_tmp_path():
    """在项目目录下创建临时目录，避开系统临时目录权限问题。"""
    base_dir = ROOT / ".pytest_tmp" / "tunnel_flat_bottom_circle_panel_batch_unit"
    base_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(dir=base_dir))
    try:
        yield temp_dir
    finally:
        for child in temp_dir.iterdir():
            if child.is_file():
                child.unlink()
        temp_dir.rmdir()


def test_tunnel_parse_case_supports_flat_bottom_circle_calculation():
    """单断面计算入口应支持平底圆形。"""
    case = _build_flat_bottom_case()

    inp, res = TunnelPanel._parse_and_calc_case(None, case, 1)

    assert inp["section_type"] == "平底圆形"
    assert inp["manual_D"] == pytest.approx(4.0)
    assert inp["manual_B"] == pytest.approx(2.0)
    assert res["success"] is True
    assert res["D"] == pytest.approx(4.0)
    assert res["B"] == pytest.approx(2.0)


def test_tunnel_multi_case_display_keeps_flat_bottom_circle_title(monkeypatch):
    """多工况展示文本应显式保留平底圆形标题。"""
    case = _build_flat_bottom_case()
    inp, res = TunnelPanel._parse_and_calc_case(None, case, 1)
    dummy = _TunnelDummy()
    dummy._all_results = [{"input": inp, "result": res, "case": case}]

    monkeypatch.setattr(tunnel_panel_mod, "load_formula_page", lambda *_args, **_kwargs: None)

    TunnelPanel._display_all_results_legacy(dummy)

    assert "隧洞水力计算结果 - 平底圆形" in dummy._export_plain_text
    assert "隧洞水力计算结果 - 马蹄形" not in dummy._export_plain_text
    assert dummy._results_fresh is True


def test_tunnel_word_export_keeps_flat_bottom_circle_title(monkeypatch, local_tmp_path):
    """Word 导出应继续使用平底圆形标题。"""
    case = _build_flat_bottom_case()
    inp, res = TunnelPanel._parse_and_calc_case(None, case, 1)
    dummy = _TunnelDummy()
    dummy._all_results = [{"label": "工况1", "input": inp, "result": res, "case": case}]

    captured = {"texts": []}

    class _DocStub:
        def add_page_break(self):
            return None

        def save(self, filepath):
            Path(filepath).write_text("stub", encoding="utf-8")

    monkeypatch.setattr(tunnel_panel_mod, "load_formula_page", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tunnel_panel_mod, "create_engineering_report_doc", lambda **_kwargs: _DocStub())
    monkeypatch.setattr(tunnel_panel_mod, "doc_add_eng_h", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tunnel_panel_mod, "doc_add_formula", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tunnel_panel_mod, "doc_add_eng_body", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tunnel_panel_mod, "doc_add_result_table", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        tunnel_panel_mod,
        "add_section_comparison_word_tables",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        tunnel_panel_mod,
        "doc_render_calc_text_eng",
        lambda _doc, txt, skip_title_keyword=None: captured["texts"].append((txt, skip_title_keyword)),
    )
    monkeypatch.setattr(tunnel_panel_mod, "doc_add_figure", lambda *_args, **_kwargs: None)

    filepath = local_tmp_path / "flat_bottom_circle.docx"
    TunnelPanel._build_word_report(dummy, str(filepath))

    assert filepath.exists()
    assert captured["texts"]
    assert any("隧洞水力计算结果 - 平底圆形" in text for text, _skip in captured["texts"])


def test_batch_panel_calculate_single_supports_flat_bottom_circle():
    """批量页分发计算时应支持平底圆形。"""
    panel = BatchPanel.__new__(BatchPanel)

    result = BatchPanel._calculate_single(
        panel,
        "隧洞-平底圆形",
        5.0,
        0.014,
        2000,
        0.1,
        100.0,
        b=2.0,
        D=4.0,
        manual_increase_percent=20.0,
    )

    assert "隧洞-平底圆形" in SECTION_TYPES
    assert result["success"] is True
    assert result["B"] == pytest.approx(2.0)
    assert result["D"] == pytest.approx(4.0)
    assert result["H_total"] > 0


def test_batch_panel_open_parameter_dialog_writes_back_flat_bottom_dimensions(monkeypatch):
    """批量页参数弹窗确认后应把 D/B 回传给表格更新逻辑。"""

    class _DialogStub:
        def __init__(self, parent, section_type, current_values):
            assert section_type == "隧洞-平底圆形"
            assert current_values["b"] == "2.0"
            assert current_values["D"] == "4.0"

        def exec(self):
            return QDialog.Accepted

        def get_result(self):
            return {
                "Q": 5.0,
                "n": 0.014,
                "slope_inv": 2000.0,
                "v_min": 0.1,
                "v_max": 100.0,
                "D": 4.0,
                "B": 2.0,
            }

    captured = {}
    panel = BatchPanel.__new__(BatchPanel)
    panel.input_table = SimpleNamespace(rowCount=lambda: 1)
    panel._get_row_data = lambda _row: [""] * 6 + ["5.0", "0.014", "2000", "", "2.0", "", "", "4.0", "", "", "", "", "0.1", "100"]
    panel._normalize_row = lambda values, length: list(values[:length]) + [""] * max(0, length - len(values))
    panel._push_undo_snapshot = lambda: captured.setdefault("undo", True)
    panel._update_table_row = lambda row_idx, params, section_type: captured.update(
        {"row_idx": row_idx, "params": params, "section_type": section_type}
    )
    panel._info_parent = lambda: None

    monkeypatch.setattr(batch_panel_mod, "SectionParameterDialog", _DialogStub)

    row_data = panel._get_row_data(0)
    row_data[3] = "隧洞-平底圆形"
    panel._get_row_data = lambda _row: row_data

    BatchPanel._open_parameter_dialog_for_row(panel, 0)

    assert captured["undo"] is True
    assert captured["row_idx"] == 0
    assert captured["section_type"] == "隧洞-平底圆形"
    assert captured["params"]["B"] == pytest.approx(2.0)
    assert captured["params"]["D"] == pytest.approx(4.0)


def test_batch_panel_update_table_row_writes_back_flat_bottom_dimensions():
    """批量表格回填时应把平底圆形的 B/D 写回正确列。"""
    panel = BatchPanel.__new__(BatchPanel)
    panel.input_table = _FakeTable()
    panel._get_row_data = lambda _row: [""] * len(INPUT_HEADERS)
    panel._normalize_row = lambda values, length: list(values[:length]) + [""] * max(0, length - len(values))

    BatchPanel._update_table_row(
        panel,
        0,
        {
            "Q": 5.0,
            "n": 0.014,
            "slope_inv": 2000.0,
            "v_min": 0.1,
            "v_max": 100.0,
            "D": 4.0,
            "B": 2.0,
        },
        "隧洞-平底圆形",
    )

    header_index = {header: idx for idx, header in enumerate(INPUT_HEADERS)}
    assert panel.input_table.item(0, header_index["底宽B(m)"]).text() == "2.0"
    assert panel.input_table.item(0, header_index["直径D(m)"]).text() == "4.0"


def test_batch_panel_tooltips_and_aliases_require_fixed_d_and_b_for_flat_bottom_circle():
    """批量页提示与导入别名都应统一按 D+B 口径处理。"""
    panel = BatchPanel.__new__(BatchPanel)

    assert "平底圆形" in _HEADER_TOOLTIPS["底宽B(m)"]
    assert "固定填写 D + B" in _HEADER_TOOLTIPS["底宽B(m)"]
    assert "平底圆形" in _HEADER_TOOLTIPS["直径D(m)"]
    assert "固定填写 D + B" in _HEADER_TOOLTIPS["直径D(m)"]
    assert BatchPanel._map_section_type(panel, "平底圆形") == "隧洞-平底圆形"
    assert BatchPanel._map_section_type(panel, "平底圆形隧洞") == "隧洞-平底圆形"


def test_section_parameter_dialog_validates_flat_bottom_circle_d_and_b(monkeypatch):
    """平底圆形参数弹窗应校验 D/B 口径。"""
    dialog = SectionParameterDialog.__new__(SectionParameterDialog)
    dialog.section_type = "隧洞-平底圆形"
    dialog.result = None
    dialog._entries = {
        "Q": _FakeEntry("5.0"),
        "n": _FakeEntry("0.014"),
        "slope_inv": _FakeEntry("2000"),
        "v_min": _FakeEntry("0.1"),
        "v_max": _FakeEntry("100"),
        "D": _FakeEntry("4.0"),
        "B": _FakeEntry("2.0"),
    }
    accepted = []
    dialog.accept = lambda: accepted.append(True)
    info_messages = []
    monkeypatch.setattr(batch_panel_mod, "fluent_info", lambda _parent, _title, content: info_messages.append(content))
    monkeypatch.setattr(batch_panel_mod, "fluent_error", lambda *_args, **_kwargs: None)

    SectionParameterDialog._on_confirm(dialog)

    assert accepted == [True]
    assert dialog.result["D"] == pytest.approx(4.0)
    assert dialog.result["B"] == pytest.approx(2.0)
    assert info_messages == []


def test_section_parameter_dialog_rejects_flat_bottom_circle_when_b_exceeds_d(monkeypatch):
    """平底圆形参数弹窗应拦截 B 大于 D 的输入。"""
    dialog = SectionParameterDialog.__new__(SectionParameterDialog)
    dialog.section_type = "隧洞-平底圆形"
    dialog.result = None
    dialog._entries = {
        "Q": _FakeEntry("5.0"),
        "n": _FakeEntry("0.014"),
        "slope_inv": _FakeEntry("2000"),
        "v_min": _FakeEntry("0.1"),
        "v_max": _FakeEntry("100"),
        "D": _FakeEntry("4.0"),
        "B": _FakeEntry("4.5"),
    }
    info_messages = []
    dialog.accept = lambda: None
    monkeypatch.setattr(batch_panel_mod, "fluent_info", lambda _parent, _title, content: info_messages.append(content))
    monkeypatch.setattr(batch_panel_mod, "fluent_error", lambda *_args, **_kwargs: None)

    SectionParameterDialog._on_confirm(dialog)

    assert dialog.result is None
    assert info_messages == ["平底圆形的平底宽 B 不能大于直径 D"]
