# -*- coding: utf-8 -*-
"""钢管统一外径输入、旧内径工况等效迁移；与面板保存及内核最小外径推荐配套。"""

import math
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from qfluentwidgets import LineEdit

from calc_渠系计算算法内核.steel_pipe_design import get_steel_pipe_spec
from app_渠系计算前端.styles import INPUT_LABEL_STYLE, INPUT_HINT_STYLE


STEEL_CASE_DEFAULTS = {
    'steel_schema_version': 2, 'steel_dimensions_enabled': True,
    'steel_dimension_basis': 'outer', 'steel_lining_mm': '0',
    'steel_diameter_mm': '', 'steel_candidates_mm': '',
    'steel_migration_note': '', 'steel_migration_error': '', 'steel_legacy_input': None,
}


def normalize_steel_case(state):
    """将历史内径换成保持原净空的外径，原始输入留档，异常保留并阻止静默重算。"""
    result = dict(STEEL_CASE_DEFAULTS, **state)
    current = state.get('steel_schema_version') == 2 and state.get('steel_dimension_basis', 'outer') == 'outer'
    if not current:
        result['steel_legacy_input'] = {key: state.get(key) for key in (
            'D', 'steel_schema_version', 'steel_dimensions_enabled', 'steel_dimension_basis',
            'steel_diameter_mm', 'steel_lining_mm', 'steel_candidates_mm')}
        enabled = state.get('steel_dimensions_enabled', 'steel_schema_version' in state)
        inner = enabled and state.get('steel_dimension_basis', 'outer') == 'inner'
        old_text = str(state.get('steel_diameter_mm' if enabled else 'D', '') or '').strip()
        if not enabled:
            result['steel_lining_mm'] = '0'  # 旧纯水力计算未扣内衬，其D本身就是净内径。
        if old_text and (inner or not enabled):
            try:
                old_inner = float(old_text) * (1 if enabled else 1000)
                lining = float(result['steel_lining_mm'])
                spec = get_steel_pipe_spec(old_inner, 'inner', lining)
                result['steel_diameter_mm'] = f'{spec.outer_diameter_mm:g}'
                result['steel_migration_note'] = (
                    f'旧内径 {old_inner:g} mm 已换算为等效外径 {spec.outer_diameter_mm:g} mm，'
                    f'保留原净内径 {spec.hydraulic_inner_diameter_mm:g} mm。')
            except (TypeError, ValueError) as exc:
                result['steel_diameter_mm'] = ''
                result['steel_migration_error'] = f'旧内径“{old_text}”无法换算为外径：{exc}。请重新输入外径，或编辑后清空以自动推荐。'
        elif not enabled:
            result['steel_diameter_mm'] = ''
        if state.get('steel_candidates_mm'):
            result['steel_migration_note'] += ' 原候选序列已留档；重新计算按100 mm整数倍自动上取外径。'
    result.update(steel_schema_version=2, steel_dimensions_enabled=True,
                  steel_dimension_basis='outer', steel_candidates_mm='')
    return result


def parse_steel_state(state, *, batch=False):
    """只接受外径与内衬厚度，手动外径保留原值，自动计算使用固定整百上取规则。"""
    state = normalize_steel_case(state)
    if state.get('steel_migration_error') and not batch:
        raise ValueError(state['steel_migration_error'])
    try:
        lining = float(state.get('steel_lining_mm', '0'))
        manual_text = str(state.get('steel_diameter_mm', '') or '').strip()
        manual = float(manual_text) if manual_text and not batch else None
    except (TypeError, ValueError) as exc:
        raise ValueError('钢管外径和内衬厚度请输入数值，单位为mm') from exc
    if not math.isfinite(lining) or lining < 0:
        raise ValueError('单侧内衬厚度必须为非负有限数值')
    if manual is not None:
        get_steel_pipe_spec(manual, 'outer', lining)
    result = dict(steel_dimensions_enabled=True, steel_dimension_basis='outer',
                  steel_lining_thickness_mm=lining, steel_diameter_candidates_mm=None)
    if not batch:
        result['manual_steel_diameter_mm'] = manual
    return result


class SteelPipeControls(QWidget):
    """仅提供公称外径和内衬厚度输入，所有新工况统一外径语义。"""

    changed = Signal()

    def __init__(self, parent=None, *, batch=False):
        """创建可复用输入区，壁厚按规范构造最小值自动确定。"""
        super().__init__(parent)
        self.batch = batch
        self.dimensions_enabled = True
        self._restoring = False
        self._migration = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        self.diameter_edit = LineEdit()
        self.diameter_edit.setPlaceholderText('留空推荐最小公称外径')
        self.diameter_row, self.diameter_label = self._row(layout, '指定公称外径 DN (mm):', self.diameter_edit)
        self.diameter_row.setVisible(not batch)
        self.lining_edit = LineEdit()
        self.lining_edit.setText('0')
        self.lining_edit.setToolTip('从钢管内径另扣的单侧内衬厚度；0表示本次不计内衬占用。')
        self._row(layout, '单侧内衬厚 (mm):', self.lining_edit)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet(INPUT_HINT_STYLE)
        layout.addWidget(self.hint)
        self.diameter_edit.textChanged.connect(self._diameter_changed)
        self.lining_edit.textChanged.connect(self._on_changed)
        self._refresh()

    def _row(self, layout, title, control):
        """将标签和输入排列成一行，与主面板保持一致。"""
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        label = QLabel(title)
        label.setStyleSheet(INPUT_LABEL_STYLE)
        line.addWidget(label)
        line.addWidget(control, 1)
        layout.addWidget(row)
        return row, label

    def _diameter_changed(self, *_args):
        """用户重新编辑外径后清除迁移阻塞，原输入留档不删除。"""
        if not self._restoring:
            self._migration['steel_migration_error'] = ''
            self._migration['steel_migration_note'] = ''
        self._on_changed()

    def _on_changed(self, *_args):
        """输入变化后解释当前尺寸，并通知面板旧结果待重算。"""
        if not self._restoring:
            self._refresh()
            self.changed.emit()

    def _refresh(self):
        """显示外径上取规则，指定尺寸时立即显示壁厚和净内径。"""
        text = '先求最小水力内径，再补内衬和壁厚；公称外径按100 mm整数倍向上取值。壁厚按 SL/T 281—2020 第8.1.1条取构造最小值，至少6 mm。'
        try:
            parsed = parse_steel_state(self.state(), batch=self.batch)
            manual = parsed.get('manual_steel_diameter_mm')
            if manual is not None:
                spec = get_steel_pipe_spec(manual, 'outer', parsed['steel_lining_thickness_mm'])
                text += f' 当前单侧壁厚 {spec.nominal_wall_thickness_mm:g} mm，水力内径 {spec.hydraulic_inner_diameter_mm:g} mm。'
        except ValueError as exc:
            text += f' 请检查：{exc}'
        self.hint.setText(text + ' ' + self._migration.get('steel_migration_note', ''))

    def state(self):
        """保存原输入文本与迁移记录，自动候选序列不再作为用户输入。"""
        return dict(STEEL_CASE_DEFAULTS, **self._migration,
                    steel_lining_mm=self.lining_edit.text(), steel_diameter_mm=self.diameter_edit.text())

    def set_state(self, state):
        """恢复时先迁移历史输入，再一次刷新，避免恢复动作清除迁移记录。"""
        state = normalize_steel_case(state)
        self._restoring = True
        self._migration = {key: state[key] for key in ('steel_migration_note', 'steel_migration_error', 'steel_legacy_input')}
        self.lining_edit.setText(str(state['steel_lining_mm']))
        self.diameter_edit.setText(str(state['steel_diameter_mm']))
        self._restoring = False
        self._refresh()
