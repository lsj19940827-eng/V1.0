# -*- coding: utf-8 -*-
"""Unit tests for shared multi-case DXF export helpers."""

import importlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(tempfile.gettempdir()) / "codex-mplconfig"),
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ezdxf = pytest.importorskip("ezdxf")
dxf_multi_export = importlib.import_module("app_\u6e20\u7cfb\u8ba1\u7b97\u524d\u7aef.dxf_multi_export")


def _get_qapp():
    return QApplication.instance() or QApplication([])


def _flush_events(rounds=4):
    app = _get_qapp()
    for _ in range(max(1, rounds)):
        app.processEvents()


def _entry(case_idx, label, *, valid=True, invalid_reason=None):
    return dxf_multi_export.DxfExportCaseEntry(
        case_idx=case_idx,
        label=label,
        input_params={"Q": case_idx + 1},
        result={"success": valid, "w": 80 + case_idx * 20, "h": 40 + case_idx * 10} if valid else None,
        is_valid=valid,
        invalid_reason=invalid_reason,
    )


def _polyline_points(entity):
    return [(float(x), float(y)) for x, y in entity.get_points("xy")]


@pytest.fixture
def local_tmp_path():
    base_dir = ROOT / ".pytest_tmp" / "multi_case_dxf_export_unit"
    base_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(dir=base_dir))
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_multi_case_dialog_checked_scope_can_be_empty_but_disables_confirm():
    _get_qapp()
    entries = [
        _entry(0, "圆形 · Q=10"),
        _entry(1, "马蹄形标准Ⅰ型 · Q=20"),
    ]
    dialog = dxf_multi_export.MultiCaseDxfExportDialog(
        module_title="隧洞断面",
        case_entries=entries,
        current_case_idx=1,
    )

    dialog._scope_checked.setChecked(True)
    _flush_events(2)
    assert dialog.checked_case_indexes() == [1]

    dialog._checkboxes[1].setChecked(False)
    _flush_events(2)

    assert dialog.checked_case_indexes() == []
    assert dialog._ok_button.isEnabled() is False
    assert "请至少勾选一个工况" in dialog._hint_label.text()

    dialog.close()
    dialog.deleteLater()
    _flush_events(2)


def test_select_case_entries_current_uses_exact_current_case_idx():
    entries = [
        _entry(2, "工况3"),
        _entry(0, "工况1"),
        _entry(1, "工况2"),
    ]

    selected = dxf_multi_export.select_case_entries(
        entries,
        scope="current",
        current_case_idx=1,
        checked_case_indexes=[0, 2],
    )

    assert [entry.case_idx for entry in selected] == [1]


def test_export_combined_case_dxf_applies_grid_offsets_titles_and_prefixed_layers(local_tmp_path):
    path = local_tmp_path / "combined_cases.dxf"
    entries = [
        _entry(0, "方案A"),
        _entry(1, "方案B"),
        _entry(2, "方案C"),
    ]

    def _draw_case(msp, result, input_params, scale_denom=100, layer_prefix="", title=""):
        _ = (input_params, scale_denom, layer_prefix)
        width = float(result["w"])
        height = float(result["h"])
        msp.add_lwpolyline(
            [(0.0, 0.0), (width, 0.0), (width, height), (0.0, height), (0.0, 0.0)],
            dxfattribs={"layer": "轮廓线"},
        )
        title_y = height + 12.0
        msp.add_text(
            title,
            dxfattribs={
                "layer": "参数文字",
                "height": 5.0,
                "insert": (width / 2.0, title_y),
                "align_point": (width / 2.0, title_y),
                "halign": 1,
            },
        )
        return (width, height + 17.0)

    saved_path = dxf_multi_export.export_combined_case_dxf(
        str(path),
        entries,
        scale_denom=100,
        draw_case=_draw_case,
    )

    assert saved_path == str(path)

    doc = ezdxf.readfile(saved_path)
    msp = doc.modelspace()

    for idx, label in enumerate(("方案A", "方案B", "方案C"), start=1):
        outline_layer = f"工况{idx}_轮廓线"
        text_layer = f"工况{idx}_参数文字"
        assert outline_layer in doc.layers
        assert text_layer in doc.layers
        texts = [
            entity.dxf.text
            for entity in msp
            if entity.dxftype() == "TEXT" and entity.dxf.layer == text_layer
        ]
        assert any(f"工况 {idx}｜{label}" in text for text in texts)

    outlines = {
        layer: next(
            entity for entity in msp if entity.dxftype() == "LWPOLYLINE" and entity.dxf.layer == layer
        )
        for layer in ("工况1_轮廓线", "工况2_轮廓线", "工况3_轮廓线")
    }
    points_1 = _polyline_points(outlines["工况1_轮廓线"])
    points_2 = _polyline_points(outlines["工况2_轮廓线"])
    points_3 = _polyline_points(outlines["工况3_轮廓线"])

    max_x_1 = max(x for x, _y in points_1)
    min_x_2 = min(x for x, _y in points_2)
    min_y_1 = min(y for _x, y in points_1)
    max_y_3 = max(y for _x, y in points_3)

    assert min_x_2 > max_x_1
    assert max_y_3 < min_y_1
