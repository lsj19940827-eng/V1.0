# -*- coding: utf-8 -*-
"""圆拱直墙型暗涵在批量页中的单元测试。"""

import os
import sys
import inspect
from pathlib import Path

import pytest
from matplotlib.figure import Figure

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

from app_渠系计算前端.batch.panel import (
    BatchPanel,
    COL_ARCH_H_STRAIGHT,
    COL_B,
    COL_BETA,
    COL_RECT_CULVERT_H,
    COL_RECT_CULVERT_HB_RATIO,
    INPUT_HEADERS,
    SECTION_TYPES,
)
import app_渠系计算前端.batch.panel as batch_panel_mod
from app_渠系计算前端.culvert.panel import CulvertPanel
import app_渠系计算前端.culvert.panel as culvert_panel_mod
from 圆拱直墙型暗涵设计 import quick_calculate_arch_culvert
from 矩形暗涵设计 import quick_calculate_rectangular_culvert


class _CulvertDummy:
    """承载暗涵面板纯逻辑方法的轻量对象。"""

    _build_arch_result_text = CulvertPanel._build_arch_result_text
    _build_culvert_result_text = CulvertPanel._build_culvert_result_text

    def __init__(self):
        self._all_results = []
        self._cases = [{"detail_checked": True}]
        self._current_case_idx = 0
        self._word_export_meta = {}
        self._word_export_purpose = ""
        self._word_export_refs = []
        self._word_export_scope = "all"
        self.section_fig = Figure()


class _FakeTable:
    """批量表格的最小替身。"""

    def __init__(self):
        self._items = {}
        self._row_count = 1

    def blockSignals(self, _blocked):
        return None

    def rowCount(self):
        return self._row_count

    def setItem(self, row, col, item):
        self._items[(row, col)] = item
        self._row_count = max(self._row_count, row + 1)

    def item(self, row, col):
        return self._items.get((row, col))


class _FakeEntry:
    """模拟参数弹窗输入框。"""

    def __init__(self, text):
        self._text = str(text)

    def text(self):
        return self._text


def _build_arch_case(**overrides):
    """构造圆拱直墙型暗涵工况字典。"""
    case = {
        "section_type": "圆拱直墙型",
        "Q": "3.0",
        "n": "0.014",
        "slope_inv": "3000",
        "v_min": "0.1",
        "v_max": "3.0",
        "inc_checked": False,
        "inc_pct": "",
        "inc_q_text": "",
        "detail_checked": True,
        "theta_deg": "150",
        "arch_B": "3.0",
        "arch_H_straight": "1.2",
    }
    case.update(overrides)
    return case


def _build_rect_case(**overrides):
    """构造矩形暗涵工况字典。"""
    case = {
        "section_type": "暗涵-矩形",
        "Q": "17.0",
        "n": "0.014",
        "slope_inv": "4000",
        "v_min": "0.1",
        "v_max": "100.0",
        "inc_checked": True,
        "inc_pct": "",
        "inc_q_text": "",
        "detail_checked": True,
        "bh": "",
        "hb": "",
        "B": "4.2",
        "H": "4.1",
    }
    case.update(overrides)
    return case



@pytest.fixture
def local_tmp_path():
    """提供可拼接路径的根目录；测试中不实际落盘。"""
    return ROOT


def test_batch_panel_calculate_single_supports_culvert_arch():
    """批量分发应把新类型送入独立的暗涵圆拱分支。"""
    panel = BatchPanel.__new__(BatchPanel)

    result = BatchPanel._calculate_single(
        panel,
        "暗涵-圆拱直墙型",
        6.0,
        0.014,
        2200.0,
        0.6,
        2.8,
        b=2.6,
        theta_deg=140.0,
        manual_increase_percent=20.0,
    )

    assert "暗涵-圆拱直墙型" in SECTION_TYPES
    assert result["success"] is True
    assert result["section_type"] == "暗涵-圆拱直墙型"
    assert result["B"] == pytest.approx(2.6)
    assert result["theta_deg"] == pytest.approx(140.0)
    assert result["H_total"] > result["h_increased"]


def test_culvert_parse_case_passes_manual_wall_height_to_kernel():
    """单项暗涵入口应把 H直 解析给内核。"""
    params = CulvertPanel._parse_case(None, _build_arch_case(), 1)

    assert params["manual_B"] == pytest.approx(3.0)
    assert params["manual_H_straight"] == pytest.approx(1.2)


def test_culvert_parse_case_rejects_wall_height_without_bottom_width():
    """单项暗涵填写 H直 但未填写 B 时应给出明确错误。"""
    with pytest.raises(ValueError, match="底宽 B"):
        CulvertPanel._parse_case(
            None,
            _build_arch_case(arch_B="", arch_H_straight="1.2"),
            1,
        )


def test_culvert_parse_case_passes_rect_fixed_height_to_kernel():
    """单项矩形暗涵入口应把固定 H 与 B 一起解析给内核。"""
    params = CulvertPanel._parse_case(None, _build_rect_case(), 1)

    assert params["manual_B"] == pytest.approx(4.2)
    assert params["manual_H"] == pytest.approx(4.1)


def test_culvert_parse_case_rejects_rect_height_without_bottom_width():
    """单项矩形暗涵只填写 H 时应提示必须同时填写 B。"""
    with pytest.raises(ValueError, match="底宽 B"):
        CulvertPanel._parse_case(
            None,
            _build_rect_case(B="", H="4.1"),
            1,
        )


@pytest.mark.parametrize("extra", [{"bh": "1.2"}, {"hb": "0.9"}])
def test_culvert_parse_case_rejects_rect_height_with_ratio(extra):
    """固定 H 不应与宽深比或高宽比混填。"""
    with pytest.raises(ValueError, match="高度 H"):
        CulvertPanel._parse_case(
            None,
            _build_rect_case(**extra),
            1,
        )


def test_batch_panel_calculate_single_passes_culvert_arch_manual_wall_height():
    """批量页分发暗涵计算时应支持固定 H直。"""
    panel = BatchPanel.__new__(BatchPanel)

    result = BatchPanel._calculate_single(
        panel,
        "暗涵-圆拱直墙型",
        5.0,
        0.014,
        3000,
        0.1,
        3.0,
        b=3.0,
        theta_deg=150.0,
        manual_H_straight=1.2,
        manual_increase_percent=0,
    )

    assert result["success"] is True
    assert result["used_manual_H_straight"] is True
    assert result["H_straight"] == pytest.approx(1.2)


def test_batch_panel_calculate_single_passes_rect_culvert_manual_height():
    """批量页分发矩形暗涵计算时应支持固定 H。"""
    panel = BatchPanel.__new__(BatchPanel)

    result = BatchPanel._calculate_single(
        panel,
        "暗涵-矩形",
        17.0,
        0.014,
        4000,
        0.1,
        100.0,
        b=4.2,
        manual_H=4.1,
    )

    assert result["success"] is True
    assert result["B"] == pytest.approx(4.2)
    assert result["H"] == pytest.approx(4.1)
    assert "指定宽高尺寸" in result["design_method"]


def test_batch_input_headers_include_rect_culvert_visible_size_columns():
    """矩形暗涵 H/B 与 H 应作为 Excel/批量表可见列紧跟底宽 B。"""
    assert INPUT_HEADERS[COL_B] == "底宽B(m)"
    assert INPUT_HEADERS[COL_RECT_CULVERT_HB_RATIO] == "暗涵高宽比H/B"
    assert INPUT_HEADERS[COL_RECT_CULVERT_H] == "暗涵高度H(m)"
    assert INPUT_HEADERS[COL_BETA] == "宽深比β"
    assert COL_RECT_CULVERT_HB_RATIO == COL_B + 1
    assert COL_RECT_CULVERT_H == COL_B + 2
    assert COL_BETA == COL_B + 3


def test_batch_panel_calculate_single_passes_rect_culvert_hb_ratio():
    """批量页分发矩形暗涵计算时应支持 Excel/表格中的 H/B。"""
    panel = BatchPanel.__new__(BatchPanel)

    result = BatchPanel._calculate_single(
        panel,
        "暗涵-矩形",
        17.0,
        0.014,
        4000,
        0.1,
        100.0,
        b=4.2,
        target_HB_ratio=0.97619047619,
    )

    assert result["success"] is True
    assert result["B"] == pytest.approx(4.2)
    assert result["H"] == pytest.approx(4.1, abs=0.02)
    assert "指定高宽比" in result["design_method"]


def test_batch_panel_update_table_row_writes_back_culvert_arch_wall_height():
    """批量参数弹窗回填暗涵时应写回 H直 追加列。"""
    panel = BatchPanel.__new__(BatchPanel)
    panel.input_table = _FakeTable()
    panel._get_row_data = lambda _row: [""] * len(INPUT_HEADERS)
    panel._normalize_row = lambda values, length: list(values[:length]) + [""] * max(0, length - len(values))

    BatchPanel._update_table_row(
        panel,
        0,
        {
            "Q": 3.0,
            "n": 0.014,
            "slope_inv": 3000.0,
            "v_min": 0.1,
            "v_max": 3.0,
            "B": 3.0,
            "theta": 150.0,
            "H_straight": 1.2,
        },
        "暗涵-圆拱直墙型",
    )

    assert panel.input_table.item(0, COL_B).text() == "3.0"
    assert panel.input_table.item(0, batch_panel_mod.COL_THETA).text() == "150.0"
    assert panel.input_table.item(0, COL_ARCH_H_STRAIGHT).text() == "1.2"


def test_batch_panel_map_section_type_reads_culvert_arch_aliases():
    """表1导入时应识别圆拱直墙型暗涵的旧写法。"""
    panel = BatchPanel.__new__(BatchPanel)

    assert BatchPanel._map_section_type(panel, "暗涵-圆拱直墙型") == "暗涵-圆拱直墙型"
    assert BatchPanel._map_section_type(panel, "圆拱直墙型暗涵") == "暗涵-圆拱直墙型"


def test_section_parameter_dialog_accepts_culvert_arch_theta_and_b(monkeypatch):
    """参数弹窗应支持圆拱直墙型暗涵的 B 与圆心角输入。"""
    dialog = batch_panel_mod.SectionParameterDialog.__new__(batch_panel_mod.SectionParameterDialog)
    dialog.section_type = "暗涵-圆拱直墙型"
    dialog.result = None
    dialog._entries = {
        "Q": type("_E", (), {"text": lambda self: "6.0"})(),
        "n": type("_E", (), {"text": lambda self: "0.014"})(),
        "slope_inv": type("_E", (), {"text": lambda self: "2200"})(),
        "v_min": type("_E", (), {"text": lambda self: "0.6"})(),
        "v_max": type("_E", (), {"text": lambda self: "2.8"})(),
        "theta": type("_E", (), {"text": lambda self: "140"})(),
        "B": type("_E", (), {"text": lambda self: "2.6"})(),
    }
    accepted = []
    dialog.accept = lambda: accepted.append(True)
    info_messages = []
    monkeypatch.setattr(batch_panel_mod, "fluent_info", lambda _parent, _title, content: info_messages.append(content))
    monkeypatch.setattr(batch_panel_mod, "fluent_error", lambda *_args, **_kwargs: None)

    batch_panel_mod.SectionParameterDialog._on_confirm(dialog)

    assert accepted == [True]
    assert dialog.result["B"] == pytest.approx(2.6)
    assert dialog.result["theta"] == pytest.approx(140.0)
    assert info_messages == []


def test_section_parameter_dialog_accepts_culvert_arch_wall_height(monkeypatch):
    """批量参数弹窗应校验并返回暗涵 H直。"""
    dialog = batch_panel_mod.SectionParameterDialog.__new__(batch_panel_mod.SectionParameterDialog)
    dialog.section_type = "暗涵-圆拱直墙型"
    dialog.result = None
    dialog._entries = {
        "Q": _FakeEntry("3.0"),
        "n": _FakeEntry("0.014"),
        "slope_inv": _FakeEntry("3000"),
        "v_min": _FakeEntry("0.1"),
        "v_max": _FakeEntry("3.0"),
        "theta": _FakeEntry("150"),
        "B": _FakeEntry("3.0"),
        "H_straight": _FakeEntry("1.2"),
    }
    accepted = []
    dialog.accept = lambda: accepted.append(True)
    monkeypatch.setattr(batch_panel_mod, "fluent_info", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(batch_panel_mod, "fluent_error", lambda *_args, **_kwargs: None)

    batch_panel_mod.SectionParameterDialog._on_confirm(dialog)

    assert accepted == [True]
    assert dialog.result["B"] == pytest.approx(3.0)
    assert dialog.result["theta"] == pytest.approx(150.0)
    assert dialog.result["H_straight"] == pytest.approx(1.2)


def test_section_parameter_dialog_accepts_rect_culvert_fixed_height(monkeypatch):
    """批量参数弹窗应支持矩形暗涵固定 H。"""
    dialog = batch_panel_mod.SectionParameterDialog.__new__(batch_panel_mod.SectionParameterDialog)
    dialog.section_type = "暗涵-矩形"
    dialog.result = None
    dialog._entries = {
        "Q": _FakeEntry("17.0"),
        "n": _FakeEntry("0.014"),
        "slope_inv": _FakeEntry("4000"),
        "v_min": _FakeEntry("0.1"),
        "v_max": _FakeEntry("100.0"),
        "BH_ratio_rect": _FakeEntry(""),
        "HB_ratio_rect": _FakeEntry(""),
        "B_rect": _FakeEntry("4.2"),
        "H_rect": _FakeEntry("4.1"),
    }
    accepted = []
    dialog.accept = lambda: accepted.append(True)
    monkeypatch.setattr(batch_panel_mod, "fluent_info", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(batch_panel_mod, "fluent_error", lambda *_args, **_kwargs: None)

    batch_panel_mod.SectionParameterDialog._on_confirm(dialog)

    assert accepted == [True]
    assert dialog.result["B_rect"] == pytest.approx(4.2)
    assert dialog.result["H_rect"] == pytest.approx(4.1)


def test_section_parameter_dialog_accepts_rect_culvert_hb_ratio(monkeypatch):
    """批量参数弹窗应支持矩形暗涵 B + H/B。"""
    dialog = batch_panel_mod.SectionParameterDialog.__new__(batch_panel_mod.SectionParameterDialog)
    dialog.section_type = "暗涵-矩形"
    dialog.result = None
    dialog._entries = {
        "Q": _FakeEntry("17.0"),
        "n": _FakeEntry("0.014"),
        "slope_inv": _FakeEntry("4000"),
        "v_min": _FakeEntry("0.1"),
        "v_max": _FakeEntry("100.0"),
        "BH_ratio_rect": _FakeEntry(""),
        "HB_ratio_rect": _FakeEntry("0.976"),
        "B_rect": _FakeEntry("4.2"),
        "H_rect": _FakeEntry(""),
    }
    accepted = []
    dialog.accept = lambda: accepted.append(True)
    monkeypatch.setattr(batch_panel_mod, "fluent_info", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(batch_panel_mod, "fluent_error", lambda *_args, **_kwargs: None)

    batch_panel_mod.SectionParameterDialog._on_confirm(dialog)

    assert accepted == [True]
    assert dialog.result["B_rect"] == pytest.approx(4.2)
    assert dialog.result["HB_ratio_rect"] == pytest.approx(0.976)


@pytest.mark.parametrize(
    "entries, message",
    [
        ({"BH_ratio_rect": "1.2", "HB_ratio_rect": "0.976", "B_rect": "4.2", "H_rect": ""}, "H/B"),
        ({"BH_ratio_rect": "", "HB_ratio_rect": "0.976", "B_rect": "4.2", "H_rect": "4.1"}, "高度 H"),
    ],
)
def test_section_parameter_dialog_rejects_rect_culvert_ratio_conflicts(monkeypatch, entries, message):
    """矩形暗涵 H、H/B、β 在批量弹窗中应按规则互斥。"""
    dialog = batch_panel_mod.SectionParameterDialog.__new__(batch_panel_mod.SectionParameterDialog)
    dialog.section_type = "暗涵-矩形"
    dialog.result = None
    dialog._entries = {
        "Q": _FakeEntry("17.0"),
        "n": _FakeEntry("0.014"),
        "slope_inv": _FakeEntry("4000"),
        "v_min": _FakeEntry("0.1"),
        "v_max": _FakeEntry("100.0"),
        **{key: _FakeEntry(value) for key, value in entries.items()},
    }
    errors = []
    dialog.accept = lambda: None
    monkeypatch.setattr(batch_panel_mod, "fluent_info", lambda _parent, _title, content: errors.append(content))
    monkeypatch.setattr(batch_panel_mod, "fluent_error", lambda *_args, **_kwargs: None)

    batch_panel_mod.SectionParameterDialog._on_confirm(dialog)

    assert errors
    assert message in errors[0]


def test_section_parameter_dialog_rejects_rect_height_without_bottom_width(monkeypatch):
    """批量参数弹窗中矩形暗涵 H 有值时 B 必填。"""
    dialog = batch_panel_mod.SectionParameterDialog.__new__(batch_panel_mod.SectionParameterDialog)
    dialog.section_type = "暗涵-矩形"
    dialog.result = None
    dialog._entries = {
        "Q": _FakeEntry("17.0"),
        "n": _FakeEntry("0.014"),
        "slope_inv": _FakeEntry("4000"),
        "v_min": _FakeEntry("0.1"),
        "v_max": _FakeEntry("100.0"),
        "BH_ratio_rect": _FakeEntry(""),
        "HB_ratio_rect": _FakeEntry(""),
        "B_rect": _FakeEntry(""),
        "H_rect": _FakeEntry("4.1"),
    }
    errors = []
    dialog.accept = lambda: None
    monkeypatch.setattr(batch_panel_mod, "fluent_info", lambda _parent, _title, content: errors.append(content))
    monkeypatch.setattr(batch_panel_mod, "fluent_error", lambda *_args, **_kwargs: None)

    batch_panel_mod.SectionParameterDialog._on_confirm(dialog)

    assert errors
    assert "底宽 B" in errors[0]


def test_batch_panel_rect_culvert_height_row_metadata_roundtrips():
    """矩形暗涵固定 H 应能作为隐藏行参数保存和读取。"""
    panel = BatchPanel.__new__(BatchPanel)
    panel.input_table = _FakeTable()

    BatchPanel._set_rect_culvert_manual_h(panel, 0, 4.1)

    assert BatchPanel._get_rect_culvert_manual_h(panel, 0) == pytest.approx(4.1)


def test_section_parameter_dialog_rejects_culvert_arch_wall_height_without_bottom_width(monkeypatch):
    """批量弹窗中暗涵 H直 有值时 B 必填。"""
    dialog = batch_panel_mod.SectionParameterDialog.__new__(batch_panel_mod.SectionParameterDialog)
    dialog.section_type = "暗涵-圆拱直墙型"
    dialog.result = None
    dialog._entries = {
        "Q": _FakeEntry("3.0"),
        "n": _FakeEntry("0.014"),
        "slope_inv": _FakeEntry("3000"),
        "v_min": _FakeEntry("0.1"),
        "v_max": _FakeEntry("3.0"),
        "theta": _FakeEntry("150"),
        "B": _FakeEntry(""),
        "H_straight": _FakeEntry("1.2"),
    }
    errors = []
    dialog.accept = lambda: None
    monkeypatch.setattr(batch_panel_mod, "fluent_info", lambda _parent, _title, content: errors.append(content))
    monkeypatch.setattr(batch_panel_mod, "fluent_error", lambda *_args, **_kwargs: None)

    batch_panel_mod.SectionParameterDialog._on_confirm(dialog)

    assert dialog.result is None
    assert errors == ["填写直墙高度 H直 时必须同时填写底宽 B"]


def test_culvert_panel_uses_section_type_label():
    """输入区应使用“断面类型”而不是旧的“子类型”文案。"""
    source = inspect.getsource(culvert_panel_mod.CulvertPanel._build_input)

    assert "断面类型:" in source
    assert "子类型:" not in source


def test_culvert_arch_result_text_uses_culvert_freeboard_wording():
    """圆拱直墙型暗涵文本应使用暗涵净空口径，不再沿用隧洞 15% 文案。"""
    params = {
        "Q": 6.0,
        "n": 0.014,
        "slope_inv": 2200.0,
        "v_min": 0.6,
        "v_max": 2.8,
        "use_increase": True,
        "manual_increase": None,
        "section_type": "暗涵-圆拱直墙型",
        "theta_deg": 140.0,
    }
    result = quick_calculate_arch_culvert(
        6.0,
        0.014,
        2200.0,
        0.6,
        2.8,
        theta_deg=140.0,
        manual_B=2.6,
        manual_increase_percent=20.0,
    )

    text = CulvertPanel._build_culvert_result_text(_CulvertDummy(), params, result, True)

    assert "净空面积应为总面积的10%~30%" in text
    assert "要求 10%~30%" in text
    assert "≥ 15%" not in text


def test_culvert_arch_result_text_explains_wall_height_source():
    """暗涵圆拱直墙型结果应说明 H直 来源。"""
    params = {
        "Q": 5.0,
        "n": 0.014,
        "slope_inv": 3000.0,
        "v_min": 0.1,
        "v_max": 3.0,
        "use_increase": False,
        "manual_increase": 0.0,
        "section_type": "暗涵-圆拱直墙型",
        "theta_deg": 150.0,
        "manual_H_straight": 1.2,
    }
    result = quick_calculate_arch_culvert(
        5.0,
        0.014,
        3000.0,
        0.1,
        3.0,
        theta_deg=150.0,
        manual_B=3.0,
        manual_H_straight=1.2,
        manual_increase_percent=0.0,
    )

    text = CulvertPanel._build_culvert_result_text(_CulvertDummy(), params, result, False)

    assert "H直" in text
    assert "按用户输入固定" in text


def test_culvert_arch_section_plot_marks_water_depth_label():
    """圆拱直墙型暗涵断面图应标注水深。"""
    dummy = _CulvertDummy()
    fig = Figure()
    ax = fig.subplots()

    CulvertPanel._draw_arch(
        dummy,
        ax,
        B=3.2,
        H_total=3.6,
        theta_rad=3.141592653589793,
        h_w=1.2,
        V=1.20,
        Q=5.0,
        title="设计流量",
    )

    labels = [text.get_text() for text in ax.texts]
    assert "h=1.20m" in labels


@pytest.mark.parametrize(
    ("params", "result", "required_formula", "forbidden_formula"),
    [
        (
            {
                "Q": 5.0,
                "n": 0.014,
                "slope_inv": 2000.0,
                "v_min": 0.1,
                "v_max": 100.0,
                "use_increase": True,
                "manual_increase": None,
                "section_type": "矩形",
            },
            quick_calculate_rectangular_culvert(
                Q=5.0,
                n=0.014,
                slope_inv=2000.0,
                v_min=0.1,
                v_max=100.0,
                target_BH_ratio=None,
                target_HB_ratio=None,
                manual_B=None,
                manual_increase_percent=None,
            ),
            r"A = B \cdot h",
            r"R_{拱} = \frac{B}{2\sin(\theta/2)}",
        ),
        (
            {
                "Q": 6.0,
                "n": 0.014,
                "slope_inv": 2200.0,
                "v_min": 0.6,
                "v_max": 2.8,
                "use_increase": True,
                "manual_increase": None,
                "section_type": "暗涵-圆拱直墙型",
                "theta_deg": 140.0,
            },
            quick_calculate_arch_culvert(
                6.0,
                0.014,
                2200.0,
                0.6,
                2.8,
                theta_deg=140.0,
                manual_B=2.6,
                manual_increase_percent=20.0,
            ),
            r"R_{拱} = \frac{B}{2\sin(\theta/2)}",
            r"A = B \cdot h",
        ),
    ],
)
def test_culvert_word_report_base_formulas_follow_section_subtype(
    monkeypatch,
    local_tmp_path,
    params,
    result,
    required_formula,
    forbidden_formula,
):
    """Word 计算书基础公式应按矩形/圆拱直墙型分别输出。"""
    dummy = _CulvertDummy()
    dummy._all_results = [(0, params, result)]

    captured_formulas = []
    saved_paths = []

    class _DocStub:
        def add_page_break(self):
            return None

        def save(self, filepath):
            saved_paths.append(Path(filepath))

    monkeypatch.setattr(culvert_panel_mod, "create_engineering_report_doc", lambda **_kwargs: _DocStub())
    monkeypatch.setattr(culvert_panel_mod, "doc_add_eng_h", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(culvert_panel_mod, "doc_add_eng_body", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(culvert_panel_mod, "doc_render_calc_text_eng", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(culvert_panel_mod, "doc_add_table_caption", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(culvert_panel_mod, "doc_add_styled_table", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(culvert_panel_mod, "doc_add_result_table", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(culvert_panel_mod, "doc_add_figure", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        culvert_panel_mod,
        "doc_add_formula",
        lambda _doc, formula, _label="": captured_formulas.append(formula),
    )

    filepath = local_tmp_path / "culvert-formulas.docx"
    CulvertPanel._build_word_report(dummy, str(filepath))

    assert saved_paths == [filepath]
    assert required_formula in captured_formulas
    assert forbidden_formula not in captured_formulas
