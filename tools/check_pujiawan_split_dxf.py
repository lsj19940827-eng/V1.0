r"""蒲家湾原始 Excel 与两段轴线 DXF 的真实面板集成验证。

自动确认文件选择和参数弹窗，计算、回写、导出和工程持久化均调用产品入口。
示例：.venv\Scripts\python.exe tools/check_pujiawan_split_dxf.py --excel <xlsx> --dxf <dxf> --output <目录>
"""
import os
import sys
import json
import argparse
import hashlib
from pathlib import Path
from unittest.mock import patch

def main():
    ROOT = Path(__file__).resolve().parents[1]
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu'
    sys.stdout.reconfigure(encoding='utf-8')
    for p in (ROOT, ROOT/'calc_渠系计算算法内核', ROOT/'推求水面线', ROOT/'倒虹吸水力计算系统'):
        sys.path.insert(0, str(p))
    from PySide6.QtWidgets import QApplication, QMessageBox, QFileDialog, QDialog
    from PySide6.QtCore import QTimer
    from qfluentwidgets import InfoBar
    import app_渠系计算前端.batch.panel as bm
    import app_渠系计算前端.water_profile.panel as wm
    import app_渠系计算前端.water_profile.water_profile_dialogs as dm
    import app_渠系计算前端.water_profile.cad_tools as cad
    from managers.pressure_pipe_manager import PressurePipeManager
    from shared.shared_data_manager import get_shared_data_manager

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--excel', type=Path, default=ROOT/'data/蒲家湾支管批量计算用表.xlsx')
    parser.add_argument('--dxf', type=Path, default=ROOT/'data/蒲家湾支管纵剖线_分段）.dxf')
    parser.add_argument('--output', type=Path, default=ROOT/'outputs/pujiawan_split_20260918')
    args=parser.parse_args()
    OUT,EXCEL,DXF=args.output,args.excel,args.dxf
    source_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (EXCEL,DXF)}
    messages=[]
    app = QApplication.instance() or QApplication([])
    def stop_unhandled_dialog():
        widget=app.activeModalWidget()
        if widget is not None:
            messages.append('UNHANDLED_DIALOG '+type(widget).__name__)
            print(messages[-1],widget.windowTitle(),flush=True)
            widget.reject()
    watchdog=QTimer();watchdog.timeout.connect(stop_unhandled_dialog);watchdog.start(1000)
    messages=[]
    def notice(*args, **kwargs):
        msg=' | '.join(str(x) for x in args if isinstance(x,str))
        print('NOTICE',msg,flush=True);messages.append(msg)
    def question(*args, **kwargs):
        notice(*args,**kwargs);return True
    for mod in (bm,wm,dm,cad):
        for name in ('fluent_info','fluent_error','fluent_warning','fluent_success'):
            if hasattr(mod,name):setattr(mod,name,notice)
        if hasattr(mod,'fluent_question'):mod.fluent_question=question
    for name in ('info','warning','error','success'):
        setattr(InfoBar,name,staticmethod(notice))
    for name in ('information','warning','critical','question'):
        setattr(QMessageBox,name,staticmethod(question))
    bm.BatchPanel._save_user_prefs=lambda self:None
    shared=get_shared_data_manager();shared.clear_batch_results()
    water=wm.WaterProfilePanel();batch=water._batch_backend
    water._pressure_pipe_manager=PressurePipeManager()
    water._show_pressure_pipe_calc_summary_dialog=lambda data,results=None: water._apply_pressure_pipe_results(results or {},data)
    def flush():
        for _ in range(8):app.processEvents()
    print('STAGE import',flush=True)
    batch._do_load_from_filepath(str(EXCEL),is_sample=True,sample_title='蒲家湾实测',sample_desc='');flush()
    expected_count=sum(1 for r in __import__('openpyxl').load_workbook(EXCEL,data_only=True).active.iter_rows(min_row=3,values_only=True) if r[3]); print('INPUTS',batch.input_table.rowCount(),'EXPECTED',expected_count,flush=True)
    water._sync_batch_settings()
    water._run_section_batch_calculate();flush()
    print('BATCH_RESULTS',len(batch.batch_results),flush=True)
    print('WATER_INPUTS',water.node_table.rowCount(),flush=True)
    water._insert_transitions();flush()
    nodes=water._build_nodes_from_table()
    print('NODES',len(nodes),'READY',water._has_transition_topology_ready(nodes),flush=True)
    context=water._prepare_pressure_pipe_dialog_context(nodes,settings=water._build_settings(),show_xxpipe_warning=False)
    print('ROUTES',list(context['route_import_targets']), 'GROUPS',len(context['pipe_groups']),flush=True)
    diagnostics={}
    def config_exec(self):
        for key,route in self._route_contexts.items():
            ips=route.get('ip_points') or []
            print('IMPORT_ROUTE',key,'CONTEXT_KEYS',list(route),flush=True)
            with patch.object(QFileDialog,'getOpenFileName',return_value=(str(DXF),'DXF')):
                self._import_longitudinal_dxf(key,ips)
            state=self._collect_xxpipe_route_import_coverage_state(key,self._longitudinal_data.get(key,[]))
            diagnostics[key]=state
            print('COVERAGE',json.dumps(state,ensure_ascii=False,default=str),flush=True)
        self.accept()
        accepted=self.result()==QDialog.Accepted
        print('DIALOG_ACCEPTED',accepted,flush=True)
        assert accepted, '纵断面配置未通过正式校验'
        return self.result()
    with patch.object(dm.PressurePipeConfigDialog,'exec',config_exec):
        water._open_pressure_pipe_calculator();flush()
    records=water._pressure_pipe_calc_records
    print('RECORDS',len(records.get('records',[])),'FAIL',[(x.get('display_name'),x.get('error')) for x in records.get('records',[]) if x.get('status')=='failed'],flush=True)
    assert records.get('records') and all(r.get('status') != 'failed' for r in records['records'])
    water._calculate();flush()
    print('CALCULATED',len(water.calculated_nodes or []),flush=True)
    print('STAGE export',flush=True)
    def profile_exec(self):
        self._on_confirm()
        return QDialog.Accepted if self.result else QDialog.Rejected
    def summary_exec(self):
        self._on_generate()
        return self.result()
    export_path = OUT/'蒲家湾支管_全部表格.dxf'
    OUT.mkdir(exist_ok=True,parents=True)
    previous_mtime=export_path.stat().st_mtime_ns if export_path.exists() else 0
    cad.fluent_question=lambda *a,**kw:False
    with patch.object(cad.TextExportSettingsDialog,'exec',profile_exec), patch.object(cad.SectionSummaryDialog,'exec',summary_exec), patch.object(QFileDialog,'getSaveFileName',return_value=(str(export_path),'DXF')):
        water._cad_combined_dxf()
    assert export_path.exists() and export_path.stat().st_mtime_ns>previous_mtime
    print('EXPORTED',export_path.exists(),flush=True)
    if export_path.exists():
        import ezdxf
        doc=ezdxf.readfile(export_path)
        print('DXF_AUDIT',len(doc.audit().errors),'ENTITIES',len(doc.modelspace()),flush=True)
        assert not doc.audit().errors
        source_lines=list(ezdxf.readfile(DXF).modelspace().query('LWPOLYLINE'))
        lines=[e for e in doc.modelspace().query('LWPOLYLINE') if e.dxf.layer=='纵断面_管中心线']
        assert len(lines)==2
        assert all(any(e.dxf.layer==layer for e in doc.modelspace()) for layer in ('断面汇总表','IP坐标表'))
        split_plan=cad.plan_xxpipe_tunnel_split(water.calculated_nodes)
        spans=cad._build_xxpipe_subtable_station_spans(split_plan['xxpipe_station_spans'],2000)
        for source,line,span in zip(source_lines,lines,spans):
            source_points=list(source.get_points('xyb'))
            points=list(line.get_points('xyb'))
            assert len(points)==len(source_points)
            assert all(b[0]>=a[0] for a,b in zip(points,points[1:]))
            for original,drawn in zip(source_points,points):
                assert abs((drawn[1]-points[0][1])-(original[1]-source_points[0][1]))<1e-8
                source_station=original[0]-source_lines[0].get_points('xy')[0][0]
                clamped_station=min(max(source_station,span['source_start_mc']),span['source_end_mc'])
                expected_x=(span['plot_start_mc']+clamped_station-span['source_start_mc'])/2
                assert abs(drawn[0]-expected_x)<1e-3,(drawn[0],expected_x)
                assert drawn[2]==original[2]
        print('AXIS_VERIFIED', [len(line) for line in lines], 'NO_BACKTRACK',True,flush=True)
    plan=cad.plan_xxpipe_tunnel_split(water.calculated_nodes)
    print('SPLIT_SPANS',plan['xxpipe_station_spans'],flush=True)
    from app_渠系计算前端.project_manager import ProjectManager
    project_manager=ProjectManager()
    project_manager._get_panel=lambda slot,**kw:water if slot=='water_profile_panel' else None
    project_manager._pressure_pipe_manager=water._pressure_pipe_manager
    project_path=OUT/f'蒲家湾支管_原始{expected_count}行_分段纵剖验证.qxproj'
    project_manager._save_to_file(str(project_path))
    project_data=json.loads(project_path.read_text(encoding='utf-8'))
    restored=wm.WaterProfilePanel()
    restored._pressure_pipe_manager=PressurePipeManager()
    restored._pressure_pipe_manager.from_dict(project_data['pressure_pipe_manager_data'])
    restored.from_project_dict(project_data['merged_panel'],skip_dirty_signal=True)
    assert restored.node_table.rowCount()==expected_count
    assert len(restored.calculated_nodes)==expected_count
    restored_context=restored._prepare_pressure_pipe_dialog_context(restored._build_nodes_from_table(),settings=restored._build_settings(),show_xxpipe_warning=False)
    assert len(restored_context['route_import_targets'])==1
    print('PROJECT_RELOAD', restored.node_table.rowCount(), 'ROUTES',len(restored_context['route_import_targets']),flush=True)
    assert len(batch.batch_results)==water.node_table.rowCount()==len(water.calculated_nodes)==expected_count
    assert len(diagnostics)==1
    assert all(not d['missing_targets'] and not d['station_errors'] for d in diagnostics.values())
    portal_idx=next(i for i,n in enumerate(water.calculated_nodes) if '隧洞' in n.get_structure_type_str()); portal=water.calculated_nodes[portal_idx]
    approach=next(r for r in records['records'] if r.get('target_row_index')==portal_idx)
    assert abs(portal.head_loss_friction-approach['friction_loss'])<1e-9
    assert portal.get_structure_type_str()=='隧洞-圆拱直墙型'
    assert 'D' not in portal.section_params or not portal.section_params['D']
    assert not any('UNHANDLED_DIALOG' in msg for msg in messages)
    print('PORTAL_LOSS_VERIFIED',portal.head_loss_friction,'TUNNEL_LOSS',water.calculated_nodes[portal_idx+1].head_loss_friction,flush=True)
    assert source_hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (EXCEL,DXF)}
    (OUT/'验证记录.json').write_text(json.dumps({'source_sha256':source_hashes,'excel':str(EXCEL),'dxf':str(DXF),'input_rows':expected_count,'table3_rows':water.node_table.rowCount(),'coverage':diagnostics,'split_spans':plan['xxpipe_station_spans'],'records':records,'dxf_entities':len(doc.modelspace()),'source_vertices':[len(e) for e in source_lines],'export_vertices':[len(e) for e in lines],'project_reloaded':True,'messages':messages},ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    restored.close()
    print('DONE',flush=True)
    water.close();batch.close()


if __name__ == "__main__":
    main()
