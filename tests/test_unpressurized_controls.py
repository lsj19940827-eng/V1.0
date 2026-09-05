"""无压坡度输入、窗口布局、结果切换和真实项目保存恢复的 GUI 回归。"""

import json
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QTextBrowser
from PySide6.QtGui import QFontDatabase, QFont

from app_渠系计算前端.pressure_pipe.slope_controls import SlopeComparisonControls
from app_渠系计算前端.pressure_pipe.panel import PressurePipePanel
from 有压管道设计 import BatchScanConfig, run_batch_scan


@pytest.fixture(scope='module')
def app():
    """为真实 QWidget 测试提供统一事件循环。"""
    application = QApplication.instance() or QApplication([])
    font_path = os.path.join(os.environ.get('WINDIR', 'C:/Windows'), 'Fonts', 'msyh.ttc')
    if os.path.isfile(font_path):
        QFontDatabase.addApplicationFont(font_path)
        application.setFont(QFont('Microsoft YaHei', 10))
    return application


@pytest.fixture
def controls(app):
    """创建并释放无压输入区。"""
    widget = SlopeComparisonControls()
    yield widget
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_switch_keeps_raw_input_and_standard_immutable(controls):
    """标准模式始终九档，自定义无效原文也须跨切换保留。"""
    assert len(controls.mode_buttons) == 2
    controls.set_mode('custom')
    controls.editor.setPlainText('600, 600, 800, invalid')
    with pytest.raises(ValueError, match='invalid'):
        controls.values()
    controls.set_mode('standard')
    assert len(controls.values()) == 9
    controls.set_mode('custom')
    assert controls.editor.toPlainText() == '600, 600, 800, invalid'
    assert 'invalid' in controls.feedback.text()
    controls.editor.setPlainText('600, 600, 800')
    assert controls.values() == [600, 800]


def test_copy_range_clear_and_undo(controls):
    """明确复制、范围生成和清空撤销的结果可预测且不损坏原文。"""
    controls.copy_button.click()
    assert controls.mode == 'custom'
    assert len(controls.values()) == 9
    original = controls.editor.toPlainText()
    controls.clear_custom()
    with pytest.raises(ValueError):
        controls.values()
    controls.undo_button.click()
    assert controls.editor.toPlainText() == original
    for edit, value in zip(controls.range_edits, ('500', '1800', '500')):
        edit.setText(value)
    controls.generate_range()
    assert controls.values() == [500, 1000, 1500]
    controls.range_edits[2].setText('0')
    controls.generate_range()
    assert controls.values() == [500, 1000, 1500]
    assert '正整数' in controls.range_feedback.text()


@pytest.mark.parametrize('width', [270, 350, 480])
def test_standard_labels_never_overlap_or_clip(controls, app, width):
    """真实布局在窄、普通和宽侧栏下必须包住每个坡度文本。"""
    controls.resize(width, 620)
    controls.show()
    app.processEvents()
    rectangles = [label.geometry() for label in controls.standard_labels]
    for index, rect in enumerate(rectangles):
        label = controls.standard_labels[index]
        assert rect.height() >= label.fontMetrics().height() + 8
        assert rect.width() >= label.fontMetrics().horizontalAdvance(label.text()) + 8
        assert controls.standard_box.rect().contains(rect)
        assert all(not rect.intersects(other) for other in rectangles[index + 1:])


def test_disabled_project_criteria_and_invalid_values(controls):
    """默认不应用预填阈值，启用后不能接受无效或空白条件。"""
    assert controls.criteria() == (None, None)
    controls.criteria_toggle.setChecked(True)
    controls.height_edit.setText('')
    controls.area_edit.setText('20')
    assert controls.criteria() == (None, 20)
    controls.area_edit.setText('nan')
    with pytest.raises(ValueError):
        controls.criteria()


def test_project_roundtrip_keeps_inputs_and_legacy_snapshot_without_tab(app, tmp_path, monkeypatch):
    """旧项目保留输入和快照，原第三页索引安全回落到批量日志。"""
    from app_渠系计算前端.pressure_pipe import panel as panel_module
    monkeypatch.setattr(panel_module, '_create_result_view', QTextBrowser)
    monkeypatch.setattr(panel_module.InfoBar, 'success', lambda **kwargs: None)
    panel = PressurePipePanel()
    restored = PressurePipePanel()
    try:
        panel.slope_controls.set_mode('custom')
        panel.slope_controls.editor.setPlainText('500,1000')
        panel.batch_unpr_cb.setChecked(True)
        panel.batch_q_start.setText('0.51')
        config = BatchScanConfig(q_values=np.array([0.51, 0.54]), slope_denominators=[500, 1000],
            diameter_values=np.array([.5, 1.2]), materials=['钢管'], output_dir=str(tmp_path),
            output_csv=False, output_pdf_charts=False, output_subplot_png=False)
        result = run_batch_scan(config)
        panel._batch_comparison_inputs = panel._comparison_input_state()
        panel._on_batch_finished(result)
        assert panel.notebook.currentIndex() == 1
        serialized = json.loads(json.dumps(panel.to_project_dict(), ensure_ascii=False, allow_nan=False))
        serialized['notebook_idx'] = 2
        serialized['unpressurized_comparison']['view'] = {'diameter': .5, 'slope': 1000}
        restored.from_project_dict(serialized)
        assert restored.batch_unpr_cb.isChecked()
        assert restored.slope_controls.editor.toPlainText() == '500,1000'
        assert restored.batch_q_start.text() == '0.51'
        assert [restored.notebook.tabText(i) for i in range(restored.notebook.count())] == ['计算结果', '批量计算日志']
        assert restored.notebook.currentIndex() == 1
        assert not hasattr(restored, 'comparison_view')
        saved = restored.to_project_dict()['unpressurized_comparison']
        assert saved['rows'] == result.comparison_rows
        assert saved['view'] == {'diameter': .5, 'slope': 1000}
        restored.slope_controls.editor.setPlainText('700')
        assert '参数已修改' in restored._comparison_status
    finally:
        for widget in (panel, restored):
            widget.close()
            widget.deleteLater()
        app.processEvents()


def test_output_options_remain_and_log_lists_files(app, monkeypatch):
    """四项输出及联动保留，完成后日志能找到各类文件。"""
    from app_渠系计算前端.pressure_pipe import panel as panel_module
    from 有压管道设计 import BatchScanResult
    monkeypatch.setattr(panel_module, '_create_result_view', QTextBrowser)
    monkeypatch.setattr(panel_module.InfoBar, 'success', lambda **kwargs: None)
    panel = PressurePipePanel()
    try:
        assert panel.out_csv_cb.text() == 'CSV 计算结果'
        assert '图表 PDF' in panel.out_pdf_cb.text()
        assert '合并 PDF' in panel.out_merged_cb.text()
        assert '子图 PNG' in panel.out_png_cb.text()
        panel.out_pdf_cb.setChecked(False)
        assert not panel.out_merged_cb.isEnabled()
        panel.out_pdf_cb.setChecked(True)
        assert panel.out_merged_cb.isEnabled()
        result = BatchScanResult(csv_path='results.csv', comparison_csv_path='detail.csv',
            generated_pdfs=['chart.pdf'], generated_pngs=['chart.png'], merged_pdf='merged.pdf')
        panel._on_batch_finished(result)
        log = panel.batch_log.toPlainText()
        assert all(name in log for name in ('results.csv', 'detail.csv', 'chart.pdf', 'chart.png', 'merged.pdf'))
        assert panel.notebook.count() == 2 and panel.notebook.currentIndex() == 1
    finally:
        panel.close()
        panel.deleteLater()
        app.processEvents()
