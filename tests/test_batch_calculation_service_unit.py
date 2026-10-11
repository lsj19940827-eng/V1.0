# -*- coding: utf-8 -*-
"""无界面批量服务的数值、导入语义和取消边界。"""
import copy
import subprocess
import sys
from pathlib import Path

import pytest

from app_渠系计算前端.batch.calculation_service import (
    BatchCalculationRequest, BatchCalculationService,
)
from app_渠系计算前端.batch.schema import (
    INPUT_HEADERS, COL_SEQ, COL_SEGMENT, COL_BUILDING_NAME, COL_SECTION_TYPE,
    COL_Q, COL_N, COL_SLOPE, COL_B, COL_M, COL_PIPE_MATERIAL,
)


def row(section="明渠-梯形", **values):
    result = [""] * len(INPUT_HEADERS)
    for col, value in {COL_SEQ: "1", COL_SEGMENT: "1", COL_BUILDING_NAME: "试验渠",
                       COL_SECTION_TYPE: section, COL_Q: "2.5", COL_N: "0.014",
                       COL_SLOPE: "2000", COL_M: "1.5", COL_B: "2"}.items():
        result[col] = value
    for col, value in values.items():
        result[int(col)] = value
    return result


def test_service_import_does_not_load_qt_or_ui():
    source = (
        "import sys; from app_渠系计算前端.batch.calculation_service import BatchCalculationService; "
        "assert not any(k.startswith(('PySide6', 'qfluentwidgets')) for k in sys.modules); "
        "assert 'app_渠系计算前端.batch.panel' not in sys.modules"
    )
    run = subprocess.run([sys.executable, "-c", source], cwd=Path(__file__).parents[1],
                         capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr


def test_request_preserves_manual_flow_and_exact_kernel_result():
    source = row()
    original = copy.deepcopy(source)
    request = BatchCalculationRequest(rows=(tuple(source),), manual_qmax_by_segment=((1, 3.2),),
                                      include_details=True)
    outcome = BatchCalculationService().calculate(request)
    result = outcome.batch_results[0]["result"]
    from calc_渠系计算算法内核.明渠设计 import quick_calculate
    expected = quick_calculate(Q=2.5, m=1.5, n=0.014, slope_inv=2000,
                               v_min=0.1, v_max=100, manual_b=2,
                               manual_increase_percent=(3.2 / 2.5 - 1) * 100,
                               preserve_manual_b=True)
    assert outcome.success_count == 1
    assert outcome.fail_count == 0
    assert result["manual_qmax_from_excel"] == 3.2
    assert result["Q_increased"] == 3.2
    assert result["h_design"] == expected["h_design"]
    assert result["b_design"] == expected["b_design"]
    assert source == original
    assert request.rows[0] == tuple(original)
    assert any(isinstance(part, tuple) and part[1]["success"] for part in outcome.detail_parts)


def test_row_failure_does_not_lose_other_rows_or_placeholder_material():
    invalid = row(**{str(COL_N): "0"})
    placeholder = row("有压管道", **{str(COL_SEQ): "2", str(COL_PIPE_MATERIAL): "钢管"})
    outcome = BatchCalculationService().calculate(BatchCalculationRequest(
        rows=(tuple(invalid), tuple(placeholder)), use_increase=False,
    ))
    assert outcome.total_count == 2
    assert outcome.fail_count == 1
    assert outcome.skip_count == 1
    assert "糙率n必须大于0" in outcome.error_details[0]
    assert outcome.batch_results[0]["result"]["pipe_material"] == "钢管"
    assert outcome.batch_results[0]["result"]["is_pressure_pipe"] is True


def test_imported_aqueduct_dimensions_are_in_request_not_widgets():
    from calc_渠系计算算法内核.渡槽设计 import quick_calculate_rect
    values = row("渡槽-矩形")
    request = BatchCalculationRequest(rows=(tuple(values),), use_increase=False, imported_rows=(True,))
    outcome = BatchCalculationService().calculate(request)
    result = outcome.batch_results[0]["result"]
    expected = quick_calculate_rect(Q=2.5, n=0.014, slope_inv=2000, v_min=0.1,
                                   v_max=100, depth_width_ratio=None, manual_B=2,
                                   chamfer_angle=0, chamfer_length=0,
                                   manual_increase_percent=0, tie_rod_height=None)
    assert result["B"] == expected["B"]
    assert result["h_design"] == expected["h_design"]
    assert result["preserved_manual_b"] is True


def test_cancellation_checkpoint_is_not_swallowed_as_row_error():
    class Cancelled(Exception):
        pass

    class Token:
        checks = 0

        def raise_if_cancelled(self):
            self.checks += 1
            if self.checks == 2:
                raise Cancelled()

    token = Token()
    request = BatchCalculationRequest(rows=(tuple(row("倒虹吸")), tuple(row("倒虹吸"))))
    with pytest.raises(Cancelled):
        BatchCalculationService().calculate(request, token)
    assert token.checks == 2
