"""从茶亭原始表验证自动补段、参数来源和工程往返，不生成正式水面线成果。"""

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch


def main():
    root = Path(__file__).resolve().parents[1]
    source = root / 'data/茶亭支渠批量计算.xlsx'
    output = root / 'outputs/chating_connection_automation_20261003'
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    sys.stdout.reconfigure(encoding='utf-8')
    for path in (root, root / 'calc_渠系计算算法内核', root / '推求水面线', root / '倒虹吸水力计算系统'):
        sys.path.insert(0, str(path))
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QFont, QFontDatabase
    from qfluentwidgets import InfoBar
    import app_渠系计算前端.batch.panel as bm
    import app_渠系计算前端.water_profile.panel as wm
    import app_渠系计算前端.water_profile.water_profile_dialogs as dm
    from app_渠系计算前端.project_manager import ProjectManager
    from shared.shared_data_manager import get_shared_data_manager
    from 推求水面线.core.length_statistics import displayed_length, summarize_length_records, validate_length_records

    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    app.setFont(QFont('Microsoft YaHei', 10))
    unexpected, errors = [], []
    def notice(*args, **kwargs):
        print(' | '.join(a for a in args if isinstance(a, str)), flush=True)
        return True
    def error(*args, **kwargs):
        errors.append([str(arg) for arg in args if isinstance(arg, str)])
        return notice(*args, **kwargs)
    for module in (bm, wm, dm):
        for name in ('fluent_info', 'fluent_error', 'fluent_warning', 'fluent_success', 'fluent_question'):
            if hasattr(module, name):
                setattr(module, name, error if name == 'fluent_error' else notice)
    for name in ('info', 'warning', 'error', 'success'):
        setattr(InfoBar, name, staticmethod(error if name == 'error' else notice))
    for name in ('information', 'warning', 'critical', 'question'):
        setattr(QMessageBox, name, staticmethod(error if name == 'critical' else notice))
    def stop_dialog():
        widget = app.activeModalWidget()
        if widget:
            unexpected.append(type(widget).__name__)
            widget.reject()
    watchdog = QTimer()
    watchdog.timeout.connect(stop_dialog)
    watchdog.start(500)
    bm.BatchPanel._save_user_prefs = lambda self: None
    get_shared_data_manager().clear_batch_results()
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    water = wm.WaterProfilePanel()
    water._batch_backend._do_load_from_filepath(str(source), is_sample=True, sample_title='茶亭连接段验证', sample_desc='')
    water._sync_batch_settings()
    water._run_section_batch_calculate()
    originals = water._build_nodes_from_table()
    assert len(originals) == 281
    calc = wm.WaterProfileCalculator(water._build_settings())
    calc.preprocess_nodes(originals)
    gaps = calc.pre_scan_open_channels(originals)
    print('GAPS', json.dumps([{k: gap.get(k) for k in ('index', 'prev_name', 'next_name', 'available_length', 'has_reference')} for gap in gaps], ensure_ascii=False), flush=True)
    assert len(gaps) == 8 and all(gap['has_reference'] for gap in gaps)
    assert [gap['reference_segment']['section_family'] for gap in gaps] == ['open_channel'] * 7 + ['culvert']
    output.mkdir(parents=True, exist_ok=True)
    def accept_recommendations(dialog):
        dialog.resize(1460, 590)
        dialog.show()
        app.processEvents()
        dialog.grab().save(str(output / '批量补段预填.png'))
        dialog._on_ok()
        assert dialog.result['mode'] == dialog.RESULT_TABLE_EDIT
        return QDialog.Accepted
    with patch.object(dm.BatchChannelConfirmDialog, 'exec', accept_recommendations):
        water._insert_transitions()
    single = dm.OpenChannelDialog(None, upstream_channel=gaps[0]['reference_segment'],
                                  available_length=gaps[0]['available_length'],
                                  prev_structure=gaps[0]['prev_struct'], next_structure=gaps[0]['next_struct'],
                                  flow_section=gaps[0]['flow_section'], flow=gaps[0]['flow'])
    single.show()
    app.processEvents()
    single.grab().save(str(output / '逐一补段预填.png'))
    single.hide()
    single.deleteLater()

    def verify(panel, expected_width=2.0):
        nodes = panel._build_nodes_from_table()
        fillers = [node for node in nodes if node.is_auto_inserted_channel]
        original_nodes = [node for node in nodes if not node.is_transition and not node.is_auto_inserted_channel]
        assert len(original_nodes) == 281
        assert len(fillers) == 8
        assert all(node.connection_source_details.get('gap_key') for node in fillers)
        for new, old in zip(original_nodes, originals):
            assert (new.name, new.get_structure_type_str(), new.x, new.y) == (old.name, old.get_structure_type_str(), old.x, old.y)
            assert abs(new.station_MC - old.station_MC) < 0.002
        for node in fillers[:-1]:
            assert node.get_structure_type_str() == '明渠-矩形'
            assert node.section_params['B'] == expected_width
            assert node.structure_height > node.connection_source_details['water_depth_increased']
            assert node.slope_i == 1 / 3000
        assert fillers[-1].get_structure_type_str() == '暗涵-矩形'
        for gap in gaps:
            left = originals[gap['index']]
            right = originals[gap['index'] + 1]
            start = next(i for i, n in enumerate(nodes) if n.name == left.name and n.x == left.x and n.y == left.y and not n.is_transition and not n.is_auto_inserted_channel)
            end = next(i for i, n in enumerate(nodes) if n.name == right.name and n.x == right.x and n.y == right.y and not n.is_transition and not n.is_auto_inserted_channel)
            additions = nodes[start + 1:end]
            used = sum(n.transition_length if n.is_transition else n.stat_length for n in additions)
            assert abs(used - (right.station_MC - left.station_MC)) < 0.003
        return nodes, fillers

    def verify_statistics(panel, snapshot=False):
        current = panel._build_nodes_from_table()
        panel._rebuild_calculation_summary_state(current)
        if panel._last_building_stats_error:
            print('LENGTH_CONFLICT', panel._last_building_stats_error, flush=True)
        assert not panel._last_building_stats_error, panel._last_building_stats_error
        records = panel._last_building_lengths
        summary = panel._last_type_summary
        assert summary == summarize_length_records(records)
        check = validate_length_records(current, records, summary, tolerance=1e-8)
        assert check['ok'], check
        # 独立按原始进出口节点核对具名建筑物，不能仅靠汇总自校验。
        source_groups = {}
        for node in current:
            kind = node.get_structure_type_str()
            if node.is_transition or node.is_auto_inserted_channel or '闸' in kind or not node.name or node.name == '-':
                continue
            source_groups.setdefault((node.name, kind), []).append(node.station_MC)
        for (name, kind), stations in source_groups.items():
            matched = [r for r in records if r['name'] == name and r['structure_type'] == kind]
            assert matched, (name, kind)
            assert math.isclose(math.fsum(r['length'] for r in matched), max(stations) - min(stations), abs_tol=1e-8), name
        assert all(r['structure_type'] != '未划分连接段' for r in records)
        dialog = dm.BuildingLengthDialog(None, records, check['channel_total'], summary)
        formatted = dialog.formatted_view
        display_total = math.fsum(displayed_length(r) for r in records)
        for row in range(dialog.detail_table.rowCount()):
            if not dialog.detail_table.item(row, 3).text():
                continue
            length = float(dialog.detail_table.item(row, 3).text())
            stations = [dialog.detail_table.item(row, col).text().split('+') for col in (1, 2)]
            start, end = [float(km) * 1000 + float(metres) for km, metres in stations]
            assert math.isclose(length, end - start, abs_tol=1e-8)
        assert math.isclose(float(dialog.summary_table.item(dialog.summary_table.rowCount() - 1, 3).text()), display_total, abs_tol=1e-8)
        assert math.isclose(math.fsum(float(row[3]) for row in formatted._table_data if row[3]), display_total, abs_tol=1e-8)
        if snapshot:
            dialog.resize(1180, 760)
            dialog.show()
            app.processEvents()
            dialog.grab().save(str(output / '建筑物长度排版表.png'))
            dialog.tab_widget.setCurrentIndex(1)
            app.processEvents()
            dialog.grab().save(str(output / '建筑物长度汇总.png'))
        dialog.close()
        dialog.deleteLater()
        return {'records': copy.deepcopy(records), 'summary': copy.deepcopy(summary),
                'channel_total': check['channel_total'], 'display_total': display_total,
                'named_buildings_checked': len(source_groups)}

    nodes, fillers = verify(water)
    statistics = verify_statistics(water, snapshot=True)
    # 批量编辑使前一缺口合并时，后面各行仍须按原始端点取自己的参数。
    narrowed = wm.WaterProfilePanel()
    narrowed.from_project_dict(water.to_project_dict(), skip_dirty_signal=True)
    def accept_changed_widths(dialog):
        dialog._set_cell(0, 5, '0.2')
        dialog._set_cell(1, 5, '2.7')
        dialog._on_ok()
        assert dialog.result['mode'] == dialog.RESULT_TABLE_EDIT
        return QDialog.Accepted
    with patch.object(dm.BatchChannelConfirmDialog, 'exec', accept_changed_widths):
        narrowed._insert_transitions()
    narrowed_fillers = [n for n in narrowed._build_nodes_from_table() if n.is_auto_inserted_channel]
    assert not any(n.connection_source_details['gap_key'] == gaps[0]['gap_key'] for n in narrowed_fillers)
    next_filler = next(n for n in narrowed_fillers if n.connection_source_details['gap_key'] == gaps[1]['gap_key'])
    assert next_filler.section_params['B'] == 2.7
    # 模拟用户建立模板，同时单独指定一处；保存、重开再插入须保留优先级。
    template = copy.deepcopy(fillers[0].connection_source_details)
    template.update(bottom_width=2.4, source_kind='user_template', user_modified=False)
    template.pop('gap_key', None)
    water._settings.connection_channel_templates['1'] = template
    key = fillers[1].connection_source_details['gap_key']
    water._settings.connection_channel_overrides[key] = dict(template, bottom_width=2.7, source_kind='user_override', user_modified=True)
    manager = ProjectManager()
    manager._get_panel = lambda slot, **kwargs: water if slot == 'water_profile_panel' else None
    with tempfile.TemporaryDirectory(prefix='chating_connections_') as temp:
        project = Path(temp) / '茶亭连接段验证.qxproj'
        manager._save_to_file(str(project))
        data = json.loads(project.read_text(encoding='utf-8'))
        restored = wm.WaterProfilePanel()
        restored.from_project_dict(data['merged_panel'], skip_dirty_signal=True)
        verify(restored)
        assert verify_statistics(restored) == statistics
        current_settings = restored._build_settings()
        restored_calc = wm.WaterProfileCalculator(current_settings)
        source_nodes = [n for n in restored._build_nodes_from_table() if not n.is_transition and not n.is_auto_inserted_channel]
        restored_calc.preprocess_nodes(source_nodes)
        restored_gaps = restored_calc.pre_scan_open_channels(source_nodes)
        print('RESTORED', json.dumps([(g['prev_name'], g['next_name'], g['reference_segment']['bottom_width'], g['reference_segment'].get('source_kind')) for g in restored_gaps], ensure_ascii=False), flush=True)
        for gap in restored_gaps:
            ref = gap['reference_segment']
            if ref['section_family'] == 'culvert':
                assert ref['bottom_width'] == 2
            else:
                assert ref['bottom_width'] == (2.7 if gap['gap_key'] == key else 2.4)
        def accept_restored(dialog):
            dialog._on_ok()
            assert dialog.result['mode'] == dialog.RESULT_TABLE_EDIT
            return QDialog.Accepted
        with patch.object(dm.BatchChannelConfirmDialog, 'exec', accept_restored):
            restored._insert_transitions()
        restored_fillers = [n for n in restored._build_nodes_from_table() if n.is_auto_inserted_channel]
        assert len(restored_fillers) == len(restored_gaps)
        for node in restored_fillers:
            if node.get_structure_type_str() == '明渠-矩形':
                assert node.section_params['B'] == (2.7 if node.connection_source_details['gap_key'] == key else 2.4)
        verify_statistics(restored)
        assert not restored.calculated_nodes
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    assert not unexpected, unexpected
    assert not errors, errors
    evidence = {
        'source': str(source), 'source_sha256': source_hash, 'original_rows': len(originals),
        'result_rows': len(nodes), 'connections': [
            {'upstream': gap['prev_name'], 'downstream': gap['next_name'],
             'reference': gap['reference_segment'], 'remaining_length': node.stat_length,
             'structure_type': node.get_structure_type_str(), 'depth': node.water_depth,
             'height': node.structure_height}
            for gap, node in zip(gaps, fillers)
        ],
        'project_roundtrip_verified': True, 'template_and_single_override_reinsert_verified': True,
        'batch_edit_merged_gap_key_mapping_verified': True,
        'building_length_audit': statistics,
        'length_statistics_project_roundtrip_verified': True,
        'scope': '验证到补段插入完成；未运行倒虹吸水力计算，未生成正式水面线成果。',
    }
    (output / '验证记录.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'rows': len(nodes), 'connections': [
        {k: item[k] for k in ('upstream', 'downstream', 'remaining_length', 'depth', 'height')}
        for item in evidence['connections']
    ], 'roundtrip': True}, ensure_ascii=False), flush=True)
    print('VERIFIED', output, flush=True)


if __name__ == '__main__':
    main()
