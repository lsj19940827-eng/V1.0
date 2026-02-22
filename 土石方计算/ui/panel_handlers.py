# -*- coding: utf-8 -*-
"""
土石方面板事件处理器 Mixin + TIN 构建后台线程
"""
from __future__ import annotations
import os, math, traceback
import numpy as np
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QTableWidgetItem, QFileDialog


def _fmt_station(s: float) -> str:
    km = int(s // 1000); m = s - km * 1000
    return f"K{km}+{m:07.3f}"


class _TINBuildThread(QThread):
    progress = Signal(str)
    finished = Signal(object)
    error    = Signal(str)

    def __init__(self, pts_xyz, tp_list=None, edges=None,
                 cache_path=None, src_files=None):
        super().__init__()
        self._pts      = pts_xyz
        self._tp_list  = tp_list  or []
        self._edges    = edges    or []
        self._cache    = cache_path
        self._srcs     = src_files or []

    def run(self):
        try:
            from 土石方计算.core.tin_builder import TINBuilder
            from 土石方计算.models.terrain import TerrainPoint, TINModel
            builder = TINBuilder()
            if self._tp_list:
                self.progress.emit("载入地形点及约束边…")
                builder.add_contour_points(self._tp_list, self._edges)
            else:
                self.progress.emit("转换地形点…")
                tp = [TerrainPoint(x=float(p[0]), y=float(p[1]), z=float(p[2]))
                      for p in self._pts]
                builder.add_elevation_points(tp)
            try:
                self.progress.emit("执行约束 Delaunay 三角剖分（CDT）…")
                if self._cache:
                    import os as _os
                    _os.makedirs(_os.path.dirname(self._cache), exist_ok=True)
                tin = builder.build(cache_path=self._cache,
                                    source_files=self._srcs)
            except ImportError:
                self.progress.emit("triangle 未安装，回退到 scipy.Delaunay（无约束边）…")
                from scipy.spatial import Delaunay, KDTree
                pts = (np.array([[p.x, p.y, p.z] for p in self._tp_list], dtype=np.float64)
                       if self._tp_list else self._pts)
                tri = Delaunay(pts[:, :2])
                tin = TINModel(points=pts, triangles=tri.simplices.astype(int))
                tin.spatial_index = KDTree(pts[:, :2])
            self.finished.emit(tin)
        except Exception:
            self.error.emit(traceback.format_exc())


class _EarthworkPanelHandlers:
    """所有事件处理器（Mixin）—— 通过 self 访问 EarthworkPanel 的控件和状态"""

    # ── 辅助：从 UI 读取计算配置 ──────────────────────────────
    def _make_design_section(self):
        from 土石方计算.models.section import DesignSection, ChannelType
        return DesignSection(channel_type=ChannelType.TRAPEZOIDAL,
                             bottom_width=self._ds_b.value(), depth=self._ds_h.value(),
                             inner_slope_left=self._ds_ml.value(), inner_slope_right=self._ds_mr.value())

    def _make_design_profile(self):
        from 土石方计算.models.section import DesignProfile, DesignProfileSegment
        return DesignProfile(segments=[DesignProfileSegment(
            start_station=self._dp_s0.value(), end_station=self._dp_s1.value(),
            start_invert_elevation=self._dp_e0.value(), slope=self._dp_i.value())])

    def _make_slope_cfg(self):
        from 土石方计算.models.section import ExcavationSlope, SlopeGrade
        grades = []
        for r in range(self._slope_table.rowCount()):
            try:
                m = float((self._slope_table.item(r, 0) or type('', (), {'text': lambda s: '1.0'})()).text())
                h_txt = (self._slope_table.item(r, 1).text() if self._slope_table.item(r, 1) else '').strip()
                h = math.inf if h_txt in ('', '∞', 'inf', 'Inf') else float(h_txt)
                bw = float(self._slope_table.item(r, 2).text()) if self._slope_table.item(r, 2) else 0.0
                grades.append(SlopeGrade(ratio=m, height=h, berm_width=bw))
            except (ValueError, AttributeError):
                continue
        if not grades:
            grades = [SlopeGrade(ratio=1.0, height=math.inf, berm_width=0.0)]
        return ExcavationSlope(start_station=self._dp_s0.value(), end_station=self._dp_s1.value(),
                               left_grades=grades, right_grades=grades)

    def _build_alignment(self):
        from 土石方计算.models.alignment import Alignment
        src = self._al_src.currentText()
        if "DXF" in src:
            path = self._al_path.text().strip()
            if not path or not os.path.isfile(path):
                raise ValueError("请先选择中心线 DXF 文件")
            from 土石方计算.io.dxf_terrain_reader import DXFTerrainReader
            layer = self._al_layer.text().strip() or "中心线"
            pts = DXFTerrainReader(path).read_centerline(layer=layer)
            if not pts:
                raise ValueError(f"DXF 中未找到图层 '{layer}' 的中心线")
            return Alignment.from_polyline_points(pts)
        else:
            x0, y0 = self._al_x0.value(), self._al_y0.value()
            x1, y1 = self._al_x1.value(), self._al_y1.value()
            if abs(x0 - x1) < 1e-6 and abs(y0 - y1) < 1e-6:
                raise ValueError("起点和终点重合，请输入有效坐标")
            return Alignment.from_polyline_points([(x0, y0), (x1, y1)])

    # ── Tab 1：载入地形 ───────────────────────────────────────
    def _on_load_terrain(self):
        fmt  = self._fmt.currentText()
        path = self._terrain_path.text().strip()
        ox, oy = self._ox.value(), self._oy.value()
        if not path or not os.path.isfile(path):
            self._infobar("错误", "请先选择地形文件", "error"); return
        try:
            if "CSV" in fmt or "TXT" in fmt:
                try:
                    pts = np.loadtxt(path, delimiter=',', comments='#')
                except ValueError:
                    pts = np.loadtxt(path, comments='#')
                if pts.ndim == 1: pts = pts.reshape(1, -1)
                # 跳过非数值表头（如第一行是文字则重试）
                if pts.shape[1] < 3:
                    raise ValueError(f"至少需要 3 列 (X,Y,Z)，当前 {pts.shape[1]} 列")
                pts = pts[:, :3].astype(np.float64)
            elif "DXF" in fmt:
                from 土石方计算.io.dxf_terrain_reader import DXFTerrainReader
                reader = DXFTerrainReader(path)
                layer = self._layer_name.text().strip() or None
                if "等高线" in fmt:
                    tp, edges = reader.read_contours(
                        layer=layer or "等高线",
                        interval=self._contour_step.value()
                    )
                    self._terrain_tp_list = tp
                    self._terrain_edges   = edges
                else:
                    tp = reader.read_elevation_points(layer=layer or "高程点")
                    self._terrain_tp_list = tp
                    self._terrain_edges   = []
                self._terrain_src_files = [path]
                pts = np.array([[p.x, p.y, p.z] for p in tp], dtype=np.float64)
            elif "Excel" in fmt:
                from 土石方计算.io.excel_reader import ExcelTerrainReader
                tp = ExcelTerrainReader(path).read_terrain_points()
                pts = np.array([[p.x, p.y, p.z] for p in tp], dtype=np.float64)
            else:
                raise ValueError(f"未知格式: {fmt}")

            if len(pts) < 4:
                raise ValueError(f"地形点数太少 ({len(pts)})，至少需要 4 个点")
            pts[:, 0] -= ox; pts[:, 1] -= oy
            self._terrain_pts = pts
            if not getattr(self, '_terrain_tp_list', []):
                self._terrain_tp_list = []; self._terrain_edges = []
            if not getattr(self, '_terrain_src_files', []):
                self._terrain_src_files = [path] if path else []
            self._terrain_lbl.setText(f"已载入 {len(pts)} 个高程点")
            self._btn_tin.setEnabled(True)
            self._tin_stat.setText("地形数据就绪，等待构建 TIN")
            self._log_msg(f"地形载入成功：{len(pts)} 点（{os.path.basename(path)}）", "OK")
            self._infobar("载入成功", f"共 {len(pts)} 个高程点", "success")
        except Exception as exc:
            self._log_msg(f"地形载入失败: {exc}", "ERR")
            self._infobar("载入失败", str(exc)[:100], "error")
            self._terrain_lbl.setText("载入失败")

    # ── Tab 2：构建 TIN ───────────────────────────────────────
    def _on_build_tin(self):
        if self._terrain_pts is None:
            self._infobar("提示", "请先载入地形数据", "warning"); return
        if self._build_thread and self._build_thread.isRunning(): return
        self._btn_tin.setEnabled(False)
        self._tin_prog.setVisible(True)
        self._tin_prog_lbl.setText("正在构建…")
        self._log_msg("开始构建 TIN 地形模型…", "INFO")
        cache_path = None
        if getattr(self, '_project_dir', ''):
            cache_dir = os.path.join(self._project_dir, '.cache')
            cache_path = os.path.join(cache_dir, 'terrain.npz')
        self._build_thread = _TINBuildThread(
            self._terrain_pts,
            tp_list=getattr(self, '_terrain_tp_list', []),
            edges=getattr(self, '_terrain_edges', []),
            cache_path=cache_path,
            src_files=getattr(self, '_terrain_src_files', []),
        )
        self._build_thread.progress.connect(self._on_tin_progress)
        self._build_thread.finished.connect(self._on_tin_done)
        self._build_thread.error.connect(self._on_tin_error)
        self._build_thread.start()

    def _on_tin_progress(self, msg: str):
        self._tin_prog_lbl.setText(msg); self._log_msg(msg, "INFO")

    def _on_tin_done(self, tin):
        from 土石方计算.core.tin_interpolator import TINInterpolator
        self._tin = tin
        try:
            self._interp = TINInterpolator(tin, backend="auto")
        except Exception as exc:
            self._log_msg(f"TINInterpolator 初始化失败: {exc}", "WARN")
            self._interp = None
        self._tin_prog.setVisible(False)
        n_pts = len(tin.points); n_tri = len(tin.triangles)
        self._tin_stat.setText("✅ TIN 构建完成")
        self._tin_info.setText(f"点数：{n_pts:,}\n三角形：{n_tri:,}\n范围：{tin.get_bbox()}")
        self._btn_tin.setEnabled(True)
        self._btn_long.setEnabled(True)
        self._btn_cs.setEnabled(True)
        self._log_msg(f"TIN 构建完成：{n_pts} 点 / {n_tri} 三角形", "OK")
        self._infobar("TIN 完成", f"{n_pts} 点 / {n_tri} 三角形", "success")
        # 预览
        try:
            ax = self._tin_canvas.axes; ax.cla()
            pts = tin.points
            sub = min(len(tin.triangles), 20000)
            from matplotlib.tri import Triangulation
            tri_obj = Triangulation(pts[:, 0], pts[:, 1], tin.triangles[:sub, :3])
            ax.triplot(tri_obj, 'b-', lw=0.3, alpha=0.4)
            sc = ax.scatter(pts[:, 0], pts[:, 1], c=pts[:, 2], cmap='terrain', s=1, zorder=3)
            self._tin_canvas.fig.colorbar(sc, ax=ax, label='高程 (m)', shrink=0.7)
            ax.set_aspect('equal'); ax.set_title(f"TIN：{n_pts} 点 / {n_tri} 三角形")
            ax.set_xlabel("X (m)"); ax.set_ylabel("Y (m)")
            self._tin_canvas.redraw()
        except Exception as exc:
            self._log_msg(f"TIN 预览生成失败: {exc}", "WARN")

    def _on_tin_error(self, msg: str):
        self._tin_prog.setVisible(False); self._btn_tin.setEnabled(True)
        self._tin_stat.setText("❌ 构建失败")
        self._log_msg(f"TIN 构建失败:\n{msg}", "ERR")
        self._infobar("构建失败", "详情见日志", "error")

    # ── Tab 3：断面切割 ───────────────────────────────────────
    def _on_cut_long(self):
        if self._interp is None:
            self._infobar("提示", "请先构建 TIN", "warning"); return
        try:
            al = self._build_alignment()
            self._alignment = al
            from 土石方计算.core.profile_cutter import ProfileCutter
            cutter = ProfileCutter(self._interp)
            dp = self._make_design_profile()
            extra = self._parse_extra_stations()
            self._long_data = cutter.cut_longitudinal(al, step=self._long_step.value(),
                                                       design_profile=dp, extra_stations=extra)
            n = len(self._long_data.stations)
            self._long_stat.setText(f"已生成 {n} 个纵断面桩号")
            self._log_msg(f"纵断面生成完成：{n} 个桩号", "OK")
            self._plot_longitudinal()
            self._tabs.setCurrentIndex(2)
            self._sec_tabs.setCurrentIndex(0)
        except Exception as exc:
            self._log_msg(f"纵断面生成失败: {exc}", "ERR")
            self._infobar("失败", str(exc)[:100], "error")

    def _plot_longitudinal(self):
        ld = self._long_data
        if not ld: return
        ax = self._long_canvas.axes; ax.cla()
        ax.plot(ld.stations, ld.ground_elevations, 'b-', lw=1.5, label='地面高程')
        des = [d if d is not None else float('nan') for d in ld.design_elevations]
        if any(d == d for d in des):
            ax.plot(ld.stations, des, 'r--', lw=1.5, label='设计底高程')
        ax.set_xlabel("桩号 (m)"); ax.set_ylabel("高程 (m)")
        ax.set_title("纵断面图"); ax.legend(); ax.grid(True, alpha=0.3)
        self._long_canvas.redraw()

    def _on_cut_sections(self):
        if self._interp is None:
            self._infobar("提示", "请先构建 TIN", "warning"); return
        try:
            if self._alignment is None:
                self._alignment = self._build_alignment()
            from 土石方计算.core.profile_cutter import ProfileCutter
            from 土石方计算.core.cross_section import CrossSectionCalculator
            cutter = ProfileCutter(self._interp)
            calc   = CrossSectionCalculator()
            dp = self._make_design_profile()
            ds = self._make_design_section()
            sc = self._make_slope_cfg()
            extra = self._parse_extra_stations()
            self._sections = cutter.cut_all_cross_sections(
                self._alignment, interval=self._cs_interval.value(),
                extra_stations=extra,
                half_width=self._cs_hw.value(), sample_step=self._cs_sample.value())
            from 土石方计算.models.section import BackfillConfig
            for sec in self._sections:
                inv = dp.get_invert_at_station(sec.station) or self._dp_e0.value()
                calc.compute(sec, ds, sc, inv, BackfillConfig())
            n = len(self._sections)
            self._cs_stat.setText(f"已切割 {n} 个横断面")
            self._btn_vol.setEnabled(True)
            self._btn_xlsx.setEnabled(True)
            self._btn_long_dxf.setEnabled(True)
            self._btn_cs_dxf.setEnabled(True)
            self._log_msg(f"横断面切割完成：{n} 个断面", "OK")
            self._sec_idx = 0
            self._refresh_cs_plot()
            self._tabs.setCurrentIndex(2)
            self._sec_tabs.setCurrentIndex(1)
        except Exception as exc:
            self._log_msg(f"横断面切割失败: {exc}", "ERR")
            self._infobar("失败", str(exc)[:100], "error")

    def _refresh_cs_plot(self):
        if not self._sections: return
        idx = max(0, min(self._sec_idx, len(self._sections) - 1))
        sec = self._sections[idx]
        total = len(self._sections)
        self._sec_lbl.setText(f"{_fmt_station(sec.station)}  ({idx+1}/{total})")
        ax = self._cs_canvas.axes; ax.cla()
        if sec.ground_points:
            gx, gz = zip(*sec.ground_points)
            ax.plot(gx, gz, 'b-', lw=1.5, label='地面线')
        if sec.design_points:
            dx, dz = zip(*sec.design_points)
            ax.plot(dx, dz, 'r-', lw=1.5, label='设计断面')
        if sec.excavation_boundary and len(sec.excavation_boundary) >= 3:
            ex, ez = zip(*sec.excavation_boundary)
            ax.fill(ex, ez, alpha=0.15, color='orange')
            ax.plot(list(ex)+[ex[0]], list(ez)+[ez[0]], 'g--', lw=1.0, label='开挖边界')
        ar = sec.area_result
        info = f"挖深={ar.cut_depth:.2f}m  开挖面积={ar.excavation_total:.2f}m²" if ar else ""
        ax.set_title(f"横断面 {_fmt_station(sec.station)}\n{info}", fontsize=9)
        ax.set_xlabel("偏距 (m)"); ax.set_ylabel("高程 (m)")
        ax.legend(fontsize=8); ax.grid(True, alpha=0.3)
        self._cs_canvas.redraw()

    def _sec_prev(self):
        if self._sections and self._sec_idx > 0:
            self._sec_idx -= 1; self._refresh_cs_plot()

    def _sec_next(self):
        if self._sections and self._sec_idx < len(self._sections) - 1:
            self._sec_idx += 1; self._refresh_cs_plot()

    # ── Tab 4：工程量计算 ─────────────────────────────────────
    def _on_compute_volume(self):
        if not self._sections:
            self._infobar("提示", "请先切割横断面", "warning"); return
        try:
            from 土石方计算.core.volume_calculator import VolumeCalculator
            vc = VolumeCalculator()
            self._volume_result = vc.compute_all(self._sections, self._alignment)
            res = self._volume_result
            tbl = self._vol_table
            segs = res.segments
            tbl.setRowCount(len(segs))
            for r, seg in enumerate(segs):
                vals = [_fmt_station(seg.station_start), _fmt_station(seg.station_end),
                        f"{seg.length:.1f}",
                        f"{seg.excavation_avg:.1f}", f"{seg.excavation_prismatoid:.1f}",
                        f"{seg.fill_avg:.1f}", f"{seg.fill_prismatoid:.1f}"]
                for c, v in enumerate(vals):
                    item = QTableWidgetItem(v); item.setTextAlignment(0x0004 | 0x0080)
                    tbl.setItem(r, c, item)
            tbl.resizeColumnsToContents()
            diff = VolumeCalculator.comparison_table(res)["diff_exc_pct"]
            self._vol_summary.setText(
                f"开挖总量（平均断面法）：{res.total_excavation_avg:.1f} m³    "
                f"（棱台法）：{res.total_excavation_prismatoid:.1f} m³    "
                f"两法差异：{diff:.2f}%    "
                f"回填总量：{res.total_fill_avg:.1f} m³")
            self._vol_stat.setText("✅ 计算完成")
            self._log_msg(f"工程量计算完成：开挖 {res.total_excavation_avg:.0f} m³", "OK")
            self._infobar("计算完成", f"开挖 {res.total_excavation_avg:.0f} m³", "success")
        except Exception as exc:
            self._log_msg(f"工程量计算失败: {exc}", "ERR")
            self._infobar("失败", str(exc)[:100], "error")

    # ── Tab 5：成果导出 ───────────────────────────────────────
    def _out_path(self, suffix: str) -> str:
        base = self._out_dir.text().strip() or os.getcwd()
        name = self._proj_name.text().strip() or "土石方计算"
        os.makedirs(base, exist_ok=True)
        return os.path.join(base, name + suffix)

    def _on_export_excel(self):
        if not self._sections:
            self._infobar("提示", "请先切割横断面", "warning"); return
        try:
            from 土石方计算.io.excel_exporter import EarthworkExcelExporter
            path = self._out_path("_土石方成果.xlsx")
            EarthworkExcelExporter().export(
                output_path=path,
                long_data=self._long_data,
                sections=self._sections,
                volume_result=self._volume_result,
                project_name=self._proj_name.text().strip() or "土石方计算")
            self._log_msg(f"Excel 导出成功: {path}", "OK")
            self._infobar("导出成功", os.path.basename(path), "success")
        except Exception as exc:
            self._log_msg(f"Excel 导出失败: {exc}", "ERR"); self._infobar("失败", str(exc)[:80], "error")

    def _on_export_long_dxf(self):
        if self._long_data is None:
            self._infobar("提示", "请先生成纵断面", "warning"); return
        try:
            from 土石方计算.io.dxf_profile_exporter import LongitudinalDXFExporter
            path = self._out_path("_纵断面.dxf")
            LongitudinalDXFExporter().export(self._long_data, output_path=path)
            self._log_msg(f"纵断面 DXF 导出成功: {path}", "OK")
            self._infobar("导出成功", os.path.basename(path), "success")
        except Exception as exc:
            self._log_msg(f"纵断面 DXF 失败: {exc}", "ERR"); self._infobar("失败", str(exc)[:80], "error")

    def _on_export_cs_dxf(self):
        if not self._sections:
            self._infobar("提示", "请先切割横断面", "warning"); return
        try:
            from 土石方计算.io.dxf_profile_exporter import CrossSectionDXFExporter
            path = self._out_path("_横断面.dxf")
            CrossSectionDXFExporter().export(self._sections, output_path=path)
            self._log_msg(f"横断面 DXF 导出成功: {path}", "OK")
            self._infobar("导出成功", os.path.basename(path), "success")
        except Exception as exc:
            self._log_msg(f"横断面 DXF 失败: {exc}", "ERR"); self._infobar("失败", str(exc)[:80], "error")

    # ── 关键梁号解析 ─────────────────────────────────
    def _parse_extra_stations(self):
        txt = getattr(self, '_extra_sta_edit', None)
        if txt is None: return None
        txt = txt.text().strip().replace('，', ',')
        if not txt: return None
        result = []
        for p in txt.split(','):
            p = p.strip()
            if p:
                try: result.append(float(p))
                except ValueError: pass
        return result if result else None

    # ── 项目文件 ───────────────────────────────────
    def _on_open_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "打开土石方项目", "", "土石方项目 (*.earthwork.json);;所有文件 (*)")
        if not path: return
        try:
            from 土石方计算 import EarthworkProject
            proj = EarthworkProject.load(path)
            self._project_dir = proj.project_dir
            self._proj_name.setText(proj.name)
            self._out_dir.setText(proj.project_dir)
            if proj._terrain_source_files:
                self._terrain_path.setText(proj._terrain_source_files[0])
                self._terrain_src_files = list(proj._terrain_source_files)
            self._log_msg(f"项目已加载: {path}", "OK")
            self._infobar("项目已加载", os.path.basename(path), "success")
        except Exception as exc:
            self._log_msg(f"项目加载失败: {exc}", "ERR")
            self._infobar("加载失败", str(exc)[:80], "error")

    def _on_save_project(self):
        proj_name = self._proj_name.text().strip() or "土石方计算"
        default_dir = getattr(self, '_project_dir', '') or self._out_dir.text().strip() or os.getcwd()
        default_path = os.path.join(default_dir, f"{proj_name}.earthwork.json")
        path, _ = QFileDialog.getSaveFileName(
            self, "保存土石方项目", default_path,
            "土石方项目 (*.earthwork.json);;所有文件 (*)")
        if not path: return
        try:
            from 土石方计算 import EarthworkProject
            proj_dir = os.path.dirname(os.path.abspath(path))
            proj = EarthworkProject(name=proj_name, project_dir=proj_dir)
            proj._terrain_source_files = list(getattr(self, '_terrain_src_files', []))
            proj._design_section  = self._make_design_section()
            proj._design_profile  = self._make_design_profile()
            proj._excavation_slopes = [self._make_slope_cfg()]
            proj.save(path)
            self._project_dir = proj_dir
            self._log_msg(f"项目已保存: {path}", "OK")
            self._infobar("项目已保存", os.path.basename(path), "success")
        except Exception as exc:
            self._log_msg(f"项目保存失败: {exc}", "ERR")
            self._infobar("保存失败", str(exc)[:80], "error")
