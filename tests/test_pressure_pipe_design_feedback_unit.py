# -*- coding: utf-8 -*-
"""有压管道设计反馈项的界面级轻量回归。"""

from types import SimpleNamespace

from app_渠系计算前端.pressure_pipe.panel import PressurePipePanel


class _Recorder:
    """记录界面桩接收到的值。"""

    def __init__(self):
        self.values = []

    def append(self, value):
        self.values.append(value)

    def setMaximum(self, value):
        self.maximum = value

    def setValue(self, value):
        self.value = value

    def setText(self, value):
        self.text = value


def test_batch_progress_is_written_to_log_and_deduplicated():
    """后台进度应实时进入批量日志，相邻重复消息只显示一次。"""
    panel = PressurePipePanel.__new__(PressurePipePanel)
    panel.batch_progress = _Recorder()
    panel.batch_status_label = _Recorder()
    panel.batch_log = _Recorder()
    panel._last_batch_log_message = ""

    PressurePipePanel._on_batch_progress(panel, 30, 1000, "计算中 球墨铸铁管 Q=0.5")
    PressurePipePanel._on_batch_progress(panel, 31, 1000, "计算中 球墨铸铁管 Q=0.5")
    PressurePipePanel._on_batch_progress(panel, 300, 1000, "计算完成，保存CSV...")

    assert panel.batch_log.values == [
        "计算中 球墨铸铁管 Q=0.5",
        "计算完成，保存CSV...",
    ]
    assert panel.batch_progress.maximum == 1000
    assert panel.batch_progress.value == 300
    assert panel.batch_status_label.text == "计算完成，保存CSV..."


def test_ductile_iron_result_card_lists_upper_and_lower_values():
    """球墨铸铁管结果卡和候选表均应出现 f 上下限值。"""
    panel = PressurePipePanel.__new__(PressurePipePanel)
    candidate = SimpleNamespace(
        D=0.8,
        V_press=1.0,
        hf_friction_km=2.0,
        hf_local_km=0.3,
        hf_total_km=2.3,
        h_loss_total_m=4.6,
        hf_friction_lower_km=1.7,
        hf_local_lower_km=0.255,
        hf_total_lower_km=1.955,
        h_loss_total_lower_m=3.91,
        category="经济",
        flags=[],
    )
    result = SimpleNamespace(
        recommended=candidate,
        category="经济",
        reason="",
        top_candidates=[candidate],
        auto_recommended=None,
    )
    inp = SimpleNamespace(Q=0.5, material_key="球墨铸铁管", length_m=2000.0)
    panel._all_results = [(0, inp, result)]
    panel._increase_summary_lines = lambda *_args: []

    html = PressurePipePanel._build_result_card_html(panel, 0, inp, result)

    assert "总水损（f 上限 / 下限）" in html
    assert "2.3000 / 1.9550 m/km" in html
    assert "管长折算（f 上限 / 下限）" in html
    assert "4.6000 / 3.9100 m" in html
    assert "hf<br>上限 / 下限" in html
    assert "2.0000<br>1.7000" in html
