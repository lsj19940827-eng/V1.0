# -*- coding: utf-8 -*-
"""圆拱直墙型暗涵在批量页中的单元测试。"""

import os
import sys
import tempfile
import inspect
from pathlib import Path

import pytest
from matplotlib.figure import Figure

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

from app_渠系计算前端.batch.panel import BatchPanel, SECTION_TYPES
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



@pytest.fixture
def local_tmp_path():
    """在项目目录下创建临时目录，避开系统临时目录权限问题。"""
    base_dir = ROOT / ".pytest_tmp" / "culvert_arch_panel_batch_unit"
    base_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(dir=base_dir))
    try:
        yield temp_dir
    finally:
        for child in temp_dir.iterdir():
            if child.is_file():
                child.unlink()
        temp_dir.rmdir()


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

    class _DocStub:
        def add_page_break(self):
            return None

        def save(self, filepath):
            Path(filepath).write_text("stub", encoding="utf-8")

    monkeypatch.setattr(culvert_panel_mod, "create_engineering_report_doc", lambda **_kwargs: _DocStub())
    monkeypatch.setattr(culvert_panel_mod, "doc_add_eng_h", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(culvert_panel_mod, "doc_add_eng_body", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(culvert_panel_mod, "doc_render_calc_text_eng", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(culvert_panel_mod, "doc_add_table_caption", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(culvert_panel_mod, "doc_add_styled_table", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(culvert_panel_mod, "doc_add_figure", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        culvert_panel_mod,
        "doc_add_formula",
        lambda _doc, formula, _label="": captured_formulas.append(formula),
    )

    filepath = local_tmp_path / "culvert-formulas.docx"
    CulvertPanel._build_word_report(dummy, str(filepath))

    assert filepath.exists()
    assert required_formula in captured_formulas
    assert forbidden_formula not in captured_formulas
