"""用蒋家沟原始 Excel 验证连接段自动推荐，不向推荐结果注入工程参数。"""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch


def main():
    root = Path(__file__).resolve().parents[1]
    source = root / '蒋家沟、鲜店水库充水渠批量计算用表.xlsx'
    output = root / 'outputs/jiangjiagou_auto_rule_20260918'
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    sys.stdout.reconfigure(encoding='utf-8')
    for path in (root, root/'calc_渠系计算算法内核', root/'推求水面线', root/'倒虹吸水力计算系统'):
        sys.path.insert(0, str(path))
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
    from PySide6.QtCore import QTimer
    from qfluentwidgets import InfoBar
    import ezdxf
    import app_渠系计算前端.batch.panel as bm
    import app_渠系计算前端.water_profile.panel as wm
    import app_渠系计算前端.water_profile.water_profile_dialogs as dm
    import app_渠系计算前端.water_profile.cad_tools as cad
    from app_渠系计算前端.project_manager import ProjectManager
    from shared.shared_data_manager import get_shared_data_manager

    app = QApplication.instance() or QApplication([])
    unexpected = []
    def notice(*args, **kwargs):
        print(' | '.join(a for a in args if isinstance(a, str)), flush=True)
        return True
    for module in (bm, wm, dm):
        for name in ('fluent_info', 'fluent_error', 'fluent_warning', 'fluent_success', 'fluent_question'):
            if hasattr(module, name): setattr(module, name, notice)
    for name in ('info', 'warning', 'error', 'success'):
        setattr(InfoBar, name, staticmethod(notice))
    for name in ('information', 'warning', 'critical', 'question'):
        setattr(QMessageBox, name, staticmethod(notice))
    def stop_dialog():
        widget = app.activeModalWidget()
        if widget:
            unexpected.append(type(widget).__name__)
            widget.reject()
    watchdog = QTimer(); watchdog.timeout.connect(stop_dialog); watchdog.start(500)
    bm.BatchPanel._save_user_prefs = lambda self: None
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    get_shared_data_manager().clear_batch_results()
    water = wm.WaterProfilePanel()
    water._batch_backend._do_load_from_filepath(str(source), is_sample=True, sample_title='蒋家沟自动规则验证', sample_desc='')
    water._sync_batch_settings()
    water._run_section_batch_calculate()
    assert water.node_table.rowCount() == 21
    originals = water._build_nodes_from_table()
    calculator = wm.WaterProfileCalculator(water._build_settings())
    source_froudes = [calculator._reference_froude(n) for n in originals[-3:]]
    assert all(fr > 1 for fr in source_froudes)
    calculator.preprocess_nodes(originals)
    recommendations = []
    # 首段和两座倒虹吸前后的五处物理空隙，逐一核对参数及长度压缩结果。
    for gap_index in (5, 8, 10, 13, 15):
        left, right = originals[gap_index:gap_index+2]
        ref = calculator._find_reference_segment_same_section_v2(originals, gap_index, gap_index, gap_index+1)
        layout = calculator._should_insert_open_channel(left, right, originals)
        assert ref and ref['slope_inv'] == 2000
        recommendations.append({
            'gap_index': gap_index,
            'upstream': left.name + '(' + left.get_structure_type_str() + ')',
            'downstream': right.name + '(' + right.get_structure_type_str() + ')',
            'reference': copy.deepcopy(ref), 'layout': layout,
            'display_source': dm.describe_transition_gap_source({'reference_segment': ref, 'flow_section': '1'}),
        })
    assert recommendations[0]['reference']['section_family'] == 'culvert'
    assert all(r['reference']['slope_borrowed_from_tunnel'] for r in recommendations[1:])
    assert all(r['layout']['use_merged_transition'] for r in recommendations[1:])
    def accept_recommendations(dialog):
        # 使用产品窗口自己的预填、确认及水深计算，不修改结构或坡降单元格。
        dialog._on_ok()
        assert dialog.get_result().slope_inv == 2000
        return QDialog.Accepted
    with patch.object(dm.OpenChannelDialog, 'exec', accept_recommendations):
        water._insert_transitions()

    def verify(nodes):
        fillers = [n for n in nodes if n.is_auto_inserted_channel]
        assert len(fillers) == 1
        assert fillers[0].get_structure_type_str() in ('暗涵-矩形', '矩形暗涵')
        assert all(n.slope_i == 1/2000 for n in fillers)
        merged = [n for i,n in enumerate(nodes) if n.is_transition
                  and any('倒虹吸' in neighbour.get_structure_type_str() for neighbour in nodes[max(0,i-1):i+2])]
        assert len(merged) == 4
        assert all(n.slope_i == 1/2000 for n in merged)
        sources = [n for n in nodes if not n.is_transition and not n.is_auto_inserted_channel]
        assert len(sources) == 21
        assert [1/n.slope_i for n in sources[-3:]] == [3.5, 1.6, 5.0]
        assert all(abs(n.station_MC-old.station_MC)<0.002 for n, old in zip(sources, originals))
        return fillers
    nodes = water._build_nodes_from_table()
    verify(nodes)
    output.mkdir(parents=True, exist_ok=True)
    project = output/'蒋家沟充水渠_自动补段规则验证.qxproj'
    manager = ProjectManager()
    manager._get_panel = lambda slot, **kwargs: water if slot == 'water_profile_panel' else None
    manager._save_to_file(str(project))
    data = json.loads(project.read_text(encoding='utf-8'))
    restored = wm.WaterProfilePanel()
    restored.from_project_dict(data['merged_panel'], skip_dirty_signal=True)
    verify(restored._build_nodes_from_table())
    assert not restored.calculated_nodes

    # 隔离诊断仅检查连接段坡降传播和导出坐标，不写入待完成倒虹吸计算的工程。
    calculated = calculator.calculate_all(copy.deepcopy(nodes))
    verify(calculated)
    for rec in recommendations:
        old_left = originals[rec['gap_index']]
        old_right = originals[rec['gap_index']+1]
        def find_original(old):
            return next(n for n in calculated if not n.is_auto_inserted_channel and not n.is_transition
                        and abs(n.x-old.x)<1e-7 and abs(n.y-old.y)<1e-7)
        left, right = find_original(old_left), find_original(old_right)
        rec['water_drop_without_siphon_loss'] = left.water_level-right.water_level
        assert abs(rec['water_drop_without_siphon_loss']) < 0.2
    doc = ezdxf.new('R2010')
    for layer in ('表格线框', '文字标注', '渠底高程线', '渠顶高程线', '设计水位线'):
        doc.layers.new(layer)
    valid = [n for n in calculated if not n.is_transition]
    cad._draw_profile_on_msp(doc.modelspace(), calculated, valid, {'scale_x': 1000, 'scale_y': 1000}, '')
    vertex_counts = {}
    for layer, attr in [('渠底高程线','bottom_elevation'), ('渠顶高程线','top_elevation'), ('设计水位线','water_level')]:
        exported = [(float(p[0]),float(p[1])) for e in doc.modelspace().query('LWPOLYLINE') if e.dxf.layer==layer for p in e.get_points()]
        expected = [(n.station_MC,getattr(n,attr)) for n in valid if getattr(n,attr)]
        assert len(exported)==len(expected)
        assert all(abs(a-c)<1e-8 and abs(b-d)<1e-8 for (a,b),(c,d) in zip(exported,expected))
        vertex_counts[layer] = len(exported)
    assert not doc.audit().errors
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    assert not unexpected
    evidence = {
        'source': str(source), 'source_sha256': source_hash,
        'original_rows': 21, 'tail_froude_numbers': source_froudes,
        'recommendations': recommendations, 'project_reload_verified': True,
        'dxf_coordinate_vertex_counts': vertex_counts,
        'diagnostic_limit': '诊断计算未计两座倒虹吸最终水损；工程保存于补段完成状态，不含正式水面线成果。',
    }
    (output/'验证记录.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(evidence, ensure_ascii=False, indent=2), flush=True)
    print('VERIFIED', project, flush=True)


if __name__ == '__main__':
    main()
