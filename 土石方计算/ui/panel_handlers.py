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
                 cache_path=None, src_files=None, filter_outliers=False):
        super().__init__()
        self._pts             = pts_xyz
        self._tp_list         = tp_list  or []
        self._edges           = edges    or []
        self._cache           = cache_path
        self._srcs            = src_files or []
        self._filter_outliers = filter_outliers

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
            if self._filter_outliers:
                self.progress.emit("过滤异常高程点（IQR法）…")
                removed = builder.filter_outliers()
                if removed > 0:
                    self.progress.emit(f"已过滤 {removed} 个异常高程点")
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
        # 读取多段纵坡表格
        dp_table = getattr(self, '_dp_table', None)
        if dp_table is not None and dp_table.rowCount() > 0:
            segments = []
            for r in range(dp_table.rowCount()):
                try:
                    s0_item = dp_table.item(r, 0)
                    e0_item = dp_table.item(r, 1)
                    i_item  = dp_table.item(r, 2)
                    s1_item = dp_table.item(r, 3)
                    s0 = float(s0_item.text()) if s0_item else 0.0
                    e0 = float(e0_item.text()) if e0_item else self._dp_e0.value()
                    i  = float(i_item.text())  if i_item  else self._dp_i.value()
                    s1 = float(s1_item.text()) if s1_item else self._dp_s1.value()
                    if s1 > s0:
                        segments.append(DesignProfileSegment(
                            start_station=s0, end_station=s1,
                            start_invert_elevation=e0, slope=i))
                except (ValueError, AttributeError):
                    continue
            if segments:
                return DesignProfile(segments=segments)
        # 回退：使用旧的单段隐藏控件
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
        # 获取纵坡覆盖范围（从多段表格的首行起始 ~ 末行终止）
        dp_table = getattr(self, '_dp_table', None)
        sta_start = 0.0
        sta_end = 10000.0
        if dp_table and dp_table.rowCount() > 0:
            try:
                s0_item = dp_table.item(0, 0)
                if s0_item: sta_start = float(s0_item.text())
            except (ValueError, AttributeError):
                pass
            try:
                last_row = dp_table.rowCount() - 1
                s1_item = dp_table.item(last_row, 3)
                if s1_item: sta_end = float(s1_item.text())
            except (ValueError, AttributeError):
                pass
        return ExcavationSlope(start_station=sta_start, end_station=sta_end,
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
        elif "桩号坐标表" in src:
            path = self._al_sta_path.text().strip()
            if not path or not os.path.isfile(path):
                raise ValueError("请先选择中心线坐标表文件（Excel/CSV）")
            col_s = self._al_col_sta.text().strip() or "桩号"
            col_x = self._al_col_x2.text().strip() or "X"
            col_y = self._al_col_y2.text().strip() or "Y"
            if path.lower().endswith(('.xlsx', '.xls')):
                from 土石方计算.io.excel_reader import ExcelTerrainReader
                sheet = self._al_sheet.text().strip() or "Sheet1"
                return ExcelTerrainReader(path).read_centerline(
                    sheet=sheet, col_station=col_s, col_x=col_x, col_y=col_y)
            else:
                from 土石方计算.io.csv_reader import CSVTerrainReader
                # CSV列名用整数索引（1-based），或默认 station=0,x=1,y=2
                def _to_idx(s, default):
                    try: return int(s) - 1
                    except ValueError: return default
                return CSVTerrainReader().read_centerline(
                    path, col_station=_to_idx(col_s, 0),
                    col_x=_to_idx(col_x, 1), col_y=_to_idx(col_y, 2))
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
                tp = ExcelTerrainReader(path).read_terrain()
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

    def _on_append_terrain(self):
        """追加地形数据到现有点集（多源合并）"""
        fmt  = self._fmt.currentText()
        path = self._terrain_path.text().strip()
        ox, oy = self._ox.value(), self._oy.value()
        if not path or not os.path.isfile(path):
            self._infobar("错误", "请先选择地形文件", "error"); return
        try:
            pts_new = None
            tp_new = []; edges_new = []
            if "CSV" in fmt or "TXT" in fmt:
                try:
                    pts_new = np.loadtxt(path, delimiter=',', comments='#')
                except ValueError:
                    pts_new = np.loadtxt(path, comments='#')
                if pts_new.ndim == 1: pts_new = pts_new.reshape(1, -1)
                pts_new = pts_new[:, :3].astype(np.float64)
            elif "DXF" in fmt:
                from 土石方计算.io.dxf_terrain_reader import DXFTerrainReader
                reader = DXFTerrainReader(path)
                layer = self._layer_name.text().strip() or None
                if "等高线" in fmt:
                    tp_new, edges_new = reader.read_contours(
                        layer=layer or "等高线", interval=self._contour_step.value())
                else:
                    tp_new = reader.read_elevation_points(layer=layer or "高程点")
                pts_new = np.array([[p.x, p.y, p.z] for p in tp_new], dtype=np.float64)
            elif "Excel" in fmt:
                from 土石方计算.io.excel_reader import ExcelTerrainReader
                tp_new = ExcelTerrainReader(path).read_terrain()
                pts_new = np.array([[p.x, p.y, p.z] for p in tp_new], dtype=np.float64)
            else:
                self._infobar("错误", f"未知格式: {fmt}", "error"); return

            if pts_new is None or len(pts_new) == 0:
                self._infobar("提示", "文件中无有效地形点", "warning"); return
            pts_new[:, 0] -= ox; pts_new[:, 1] -= oy

            # 合并到现有数据
            if self._terrain_pts is None:
                self._terrain_pts = pts_new
            else:
                self._terrain_pts = np.vstack([self._terrain_pts, pts_new])
            if tp_new:
                offset = len(getattr(self, '_terrain_tp_list', []))
                self._terrain_tp_list = list(getattr(self, '_terrain_tp_list', [])) + tp_new
                from 土石方计算.models.terrain import ConstraintEdge
                for e in edges_new:
                    self._terrain_edges.append(ConstraintEdge(i=e.i + offset, j=e.j + offset))
            if path not in getattr(self, '_terrain_src_files', []):
                self._terrain_src_files = list(getattr(self, '_terrain_src_files', [])) + [path]

            n_total = len(self._terrain_pts)
            self._terrain_lbl.setText(f"已合并 {n_total} 个高程点（+{len(pts_new)}）")
            self._btn_tin.setEnabled(True)
            self._tin_stat.setText("地形数据就绪（多源合并），等待构建 TIN")
            self._log_msg(f"追加地形数据：+{len(pts_new)} 点，合计 {n_total} 点", "OK")
            self._infobar("追加成功", f"+{len(pts_new)} 点，合计 {n_total} 点", "success")
        except Exception as exc:
            self._log_msg(f"追加地形失败: {exc}", "ERR")
            self._infobar("追加失败", str(exc)[:100], "error")

    def _on_clear_terrain(self):
        """清空全部地形数据"""
        self._terrain_pts = None
        self._terrain_tp_list = []
        self._terrain_edges = []
        self._terrain_src_files = []
        self._tin = None; self._interp = None
        self._terrain_lbl.setText("— 未载入 —")
        self._btn_tin.setEnabled(False)
        self._tin_stat.setText("尚未构建")
        self._log_msg("地形数据已清空", "INFO")

    def _on_auto_estimate_width(self):
        """根据设计断面口宽自动估算横断面半宽"""
        from 土石方计算.core.profile_cutter import ProfileCutter
        try:
            ds = self._make_design_section()
            sc = self._make_slope_cfg()
            hw = ProfileCutter.estimate_section_width(
                design_top_width=ds.top_width,
                excavation_slope_config=sc,
                margin_factor=2.0,
                extra_margin=5.0,
            )
            self._cs_hw.setValue(round(hw, 1))
            self._log_msg(f"自动估算横断面半宽: {hw:.1f} m (口宽={ds.top_width:.2f}m)", "OK")
            self._infobar("自动估算", f"横断面半宽 = {hw:.1f} m", "success")
        except Exception as exc:
            self._log_msg(f"自动估算失败: {exc}", "WARN")
            self._infobar("估算失败", str(exc)[:80], "warning")

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
        filter_outliers = getattr(self, '_tin_filter_chk', None)
        filter_outliers = filter_outliers.isChecked() if filter_outliers else False
        self._build_thread = _TINBuildThread(
            self._terrain_pts,
            tp_list=getattr(self, '_terrain_tp_list', []),
            edges=getattr(self, '_terrain_edges', []),
            cache_path=cache_path,
            src_files=getattr(self, '_terrain_src_files', []),
            filter_outliers=filter_outliers,
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
            geo_mgr = self._build_geology_manager()
            # 非对称宽度支持
            asym_chk = getattr(self, '_cs_asym_chk', None)
            if asym_chk and asym_chk.isChecked():
                lw = self._cs_lw.value()
                rw = self._cs_rw.value()
                stations = self._alignment.sample_stations(
                    self._cs_interval.value(), extra)
                self._sections = [
                    cutter.cut_cross_section(
                        self._alignment, s, lw, rw, self._cs_sample.value())
                    for s in stations
                ]
            else:
                self._sections = cutter.cut_all_cross_sections(
                    self._alignment, interval=self._cs_interval.value(),
                    extra_stations=extra,
                    half_width=self._cs_hw.value(), sample_step=self._cs_sample.value())
            from 土石方计算.models.section import BackfillConfig
            for sec in self._sections:
                inv = dp.get_invert_at_station(sec.station) or self._dp_e0.value()
                # 若有地质分层，附加地质剖面数据
                if geo_mgr and geo_mgr.layer_names:
                    ground_center = next(
                        (p[1] for p in sec.ground_points if abs(p[0]) < 0.01),
                        inv + ds.depth)
                    try:
                        sec.geology_profile = geo_mgr.get_profile_at_station(
                            sec.station, ground_center)
                    except Exception:
                        pass
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
            from 土石方计算.io.dxf_profile_exporter import LongitudinalDXFExporter, LongitudinalDXFConfig
            path = self._out_path("_纵断面.dxf")
            cfg = None
            if hasattr(self, '_ldxf_sh'):
                cfg = LongitudinalDXFConfig(
                    scale_h=1.0 / self._ldxf_sh.value(),
                    scale_v=1.0 / self._ldxf_sv.value(),
                )
            LongitudinalDXFExporter(cfg).export(self._long_data, output_path=path)
            self._log_msg(f"纵断面 DXF 导出成功: {path}", "OK")
            self._infobar("导出成功", os.path.basename(path), "success")
        except Exception as exc:
            self._log_msg(f"纵断面 DXF 失败: {exc}", "ERR"); self._infobar("失败", str(exc)[:80], "error")

    def _on_export_cs_dxf(self):
        if not self._sections:
            self._infobar("提示", "请先切割横断面", "warning"); return
        try:
            from 土石方计算.io.dxf_profile_exporter import CrossSectionDXFExporter, CrossSectionDXFConfig
            path = self._out_path("_横断面.dxf")
            cfg = None
            if hasattr(self, '_dxf_spp'):
                cfg = CrossSectionDXFConfig(
                    sections_per_page=self._dxf_spp.value(),
                    paper_width=self._dxf_pw.value(),
                    paper_height=self._dxf_ph.value(),
                    scale_h=1.0 / self._dxf_sh.value(),
                    scale_v=1.0 / self._dxf_sv.value(),
                )
            geo_mgr = self._build_geology_manager()
            geology_layers = geo_mgr.layers if geo_mgr else []
            CrossSectionDXFExporter(cfg).export(
                self._sections, geology_layers=geology_layers, output_path=path)
            self._log_msg(f"横断面 DXF 导出成功: {path}", "OK")
            self._infobar("导出成功", os.path.basename(path), "success")
        except Exception as exc:
            self._log_msg(f"横断面 DXF 失败: {exc}", "ERR"); self._infobar("失败", str(exc)[:80], "error")

    # ── 地质分层 ──────────────────────────────────────
    def _build_geology_manager(self):
        """从 UI 表格读取地质层定义，构建 GeologyLayerManager（若无层则返回 None）"""
        from 土石方计算.core.geology_layer import GeologyLayerManager
        rows = self._geo_table.rowCount()
        if rows == 0:
            return None
        mgr = GeologyLayerManager()
        manual_depths: dict[str, float] = {}  # {layer_name: constant_depth_m}
        for r in range(rows):
            name_item  = self._geo_table.item(r, 0)
            hatch_item = self._geo_table.item(r, 1)
            color_item = self._geo_table.item(r, 2)
            depth_item = self._geo_table.item(r, 3) if self._geo_table.columnCount() > 3 else None
            name = (name_item.text().strip() if name_item else "").strip()
            if not name:
                continue
            hatch = hatch_item.text().strip() if hatch_item else "ANSI31"
            try:
                color = int(color_item.text().strip()) if color_item else 8
            except ValueError:
                color = 8
            try:
                mgr.add_layer(name, color_index=color, hatch_pattern=hatch)
            except ValueError:
                pass  # 重复层名跳过
            # 读取手动统一深度
            if depth_item:
                d_txt = depth_item.text().strip()
                if d_txt:
                    try:
                        manual_depths[name] = float(d_txt)
                    except ValueError:
                        pass
        if not mgr.layer_names:
            return None
        # 优先级：手动统一深度 > Excel/DXF导入深度表
        depth_data = getattr(self, '_geology_depth_data', {})
        for layer_name in mgr.layer_names:
            if layer_name in manual_depths:
                # 手动统一深度：全线保持恒定
                d = manual_depths[layer_name]
                try:
                    mgr.set_depth_table(layer_name, [(0.0, d), (999999.0, d)])
                except (ValueError, KeyError):
                    pass
            elif layer_name in depth_data:
                try:
                    mgr.set_depth_table(layer_name, depth_data[layer_name])
                except (ValueError, KeyError):
                    pass
        return mgr

    def _on_import_geology_dxf(self):
        """从 DXF 分层线文件导入地质分层界面数据（需先定义地质层名称）"""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "选择地质分层 DXF", "", "DXF 文件 (*.dxf);;所有文件 (*)")
        if not path:
            return
        # 收集 UI 中已有的层名
        layer_names = []
        for r in range(self._geo_table.rowCount()):
            item = self._geo_table.item(r, 0)
            if item and item.text().strip():
                layer_names.append(item.text().strip())
        if not layer_names:
            self._infobar("提示", "请先在表格中添加地质层定义（层名称需与DXF图层名对应）", "warning")
            return
        try:
            from 土石方计算.io.dxf_terrain_reader import DXFTerrainReader
            reader = DXFTerrainReader(path)
            # 列出DXF图层供用户参考
            dxf_layers = reader.list_layers()
            # 尝试自动匹配：DXF图层名与地质层名相同
            layer_map = {name: name for name in layer_names if name in dxf_layers}
            if not layer_map:
                # 如果没有精确匹配，尝试模糊匹配（图层名包含地质层名）
                for geo_name in layer_names:
                    for dxf_l in dxf_layers:
                        if geo_name in dxf_l or dxf_l in geo_name:
                            layer_map[dxf_l] = geo_name
                            break
            if not layer_map:
                avail = "、".join(dxf_layers[:10])
                self._infobar("警告",
                    f"DXF图层({avail})与地质层名不匹配，请确保DXF图层名与地质层名一致",
                    "warning")
                return
            # 读取分层线
            raw = reader.read_geology_layers(layer_map)
            # 将分层线的Z坐标转换为中心线桩号处的高程
            # 简化处理：对每条分层线取Z的均值，作为该层在各桩号的深度参考
            if not hasattr(self, '_geology_depth_data'):
                self._geology_depth_data = {}
            imported = []
            for geo_name, polylines in raw.items():
                if not polylines:
                    continue
                # 收集所有点 → 按X坐标排序（近似桩号）→ 插值
                pts = [(pt[0], pt[2]) for pl in polylines for pt in pl]
                if len(pts) >= 2:
                    pts.sort(key=lambda p: p[0])
                    # 存为 (x, z) 表，稍后在断面计算时按中心线桩号插值
                    self._geology_depth_data[f"__dxf_{geo_name}"] = pts
                    imported.append(geo_name)
            if imported:
                self._geo_depth_lbl.setText(
                    f"DXF分层线已导入：{'、'.join(imported)}（含{sum(len(v) for v in raw.values())}条线）")
                self._log_msg(f"DXF地质分层导入：{', '.join(imported)}", "OK")
                self._infobar("导入成功", f"已导入 {len(imported)} 个地质层的分层线", "success")
            else:
                self._infobar("警告", "未读取到有效分层线数据", "warning")
        except Exception as exc:
            self._log_msg(f"DXF地质分层导入失败: {exc}", "ERR")
            self._infobar("导入失败", str(exc)[:80], "error")

    def _on_import_geology_excel(self):
        """从 Excel 导入地质分层深度表"""
        from PySide6.QtWidgets import QFileDialog, QInputDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "选择地质分层深度表", "", "Excel 文件 (*.xlsx);;所有文件 (*)")
        if not path:
            return
        try:
            from 土石方计算.io.excel_reader import ExcelTerrainReader
            reader = ExcelTerrainReader(path)
            # 收集 UI 中已有的层名
            layer_names = []
            for r in range(self._geo_table.rowCount()):
                item = self._geo_table.item(r, 0)
                if item and item.text().strip():
                    layer_names.append(item.text().strip())
            if not layer_names:
                self._infobar("提示", "请先在表格中添加地质层定义", "warning")
                return
            # 构建列映射 {层名: 列名}（默认列名=层名）
            col_map = {name: name for name in layer_names}
            # 读取深度表
            data = reader.read_geology_depths(
                sheet="地质分层", col_station="桩号",
                layer_columns=col_map
            )
            total_rows = sum(len(v) for v in data.values() if v)
            if total_rows == 0:
                self._infobar("警告", "未读取到有效数据，请确认工作表名（地质分层）和列名与层名一致", "warning")
                return
            if not hasattr(self, '_geology_depth_data'):
                self._geology_depth_data = {}
            self._geology_depth_data.update(data)
            loaded = [f"{k}({len(v)}行)" for k, v in data.items() if v]
            self._geo_depth_lbl.setText("已导入深度表：" + "，".join(loaded))
            self._log_msg(f"地质深度表导入: {', '.join(loaded)}", "OK")
            self._infobar("导入成功", f"共 {total_rows} 行深度数据", "success")
        except Exception as exc:
            self._log_msg(f"地质深度表导入失败: {exc}", "ERR")
            self._infobar("导入失败", str(exc)[:80], "error")

    # ── 从明渠设计模块读取断面参数 ─────────────────────
    def _on_import_from_channel_design(self):
        """
        尝试从主窗口的明渠设计面板读取当前断面参数。

        明渠设计面板使用文本框，b/h 是计算输出（input_params 仅含输入参数）。
        可读取的参数：
        - m（边坡系数，来自 m_edit 文本框）
        - 手动底宽 b（来自 b_edit，若用户手动指定）
        - 计算结果（来自 _last_result 若有）
        """
        try:
            # 沿 widget 树向上找 MainWindow
            main_win = self
            for _ in range(10):
                parent = main_win.parent()
                if parent is None:
                    break
                main_win = parent
                if hasattr(main_win, 'open_channel_panel'):
                    break

            oc_panel = getattr(main_win, 'open_channel_panel', None)
            if oc_panel is None:
                self._infobar("提示", "未找到明渠设计面板，请确保从主窗口启动程序", "warning")
                return

            imported = []

            # 读取边坡系数 m（文本框 m_edit）
            m = self._read_field(oc_panel, ['m_edit', '_m_edit', 'm_spin'])
            if m is not None and m > 0:
                self._ds_ml.setValue(m)
                self._ds_mr.setValue(m)
                imported.append(f"坡比m={m:.2f}")

            # 尝试读取 input_params（包含计算所用的输入参数）
            ip = getattr(oc_panel, 'input_params', None)

            # 尝试读取计算结果（OpenChannelPanel使用 current_result）
            last_result = (getattr(oc_panel, 'current_result', None) or
                           getattr(oc_panel, '_last_result', None) or
                           getattr(oc_panel, 'last_result', None) or
                           getattr(oc_panel, '_result', None))

            if last_result and isinstance(last_result, dict) and last_result.get('success'):
                # open_channel: b_design(底宽) + h_prime(渠道高度H=h增+Fb, 即渠深)
                # aqueduct:     B + H_total
                # tunnel:       B + H_total
                b = (last_result.get('b_design') or last_result.get('B') or
                     last_result.get('b') or last_result.get('b_calculated'))
                # 渠深取渠道高度H（设计水深+超高），不是水深h_design
                h = (last_result.get('h_prime') or   # 明渠 channel height H
                     last_result.get('H_total') or   # 渡槽/隧洞
                     last_result.get('H') or
                     last_result.get('h_design'))     # 回退到水深
                if b and float(b) > 0:
                    self._ds_b.setValue(float(b)); imported.append(f"底宽b={float(b):.2f}m")
                if h and float(h) > 0:
                    self._ds_h.setValue(float(h)); imported.append(f"渠深h={float(h):.2f}m")

            # 回退：读取手动底宽输入框（b_edit）
            if not last_result:
                b_manual = self._read_field(oc_panel, ['b_edit', '_b_edit'])
                if b_manual and b_manual > 0:
                    self._ds_b.setValue(b_manual)
                    imported.append(f"底宽(手动)={b_manual:.2f}m")

            if imported:
                self._log_msg(f"从明渠设计读取：{', '.join(imported)}", "OK")
                msg = "、".join(imported)
                note = "" if last_result else "（渠深 h 请手动填写）"
                self._infobar("读取成功", msg + note, "success")
            else:
                self._infobar("提示",
                    "明渠设计模块无可读取的参数。请先在「明渠设计」页完成计算，"
                    "或手动在此处填写渠底宽 b 和渠深 h。",
                    "info")
        except Exception as exc:
            self._log_msg(f"从明渠设计读取失败: {exc}", "WARN")
            self._infobar("读取失败", str(exc)[:80], "warning")

    # ── 从Excel导入设计底高程 ─────────────────────────────
    def _on_import_design_profile_excel(self):
        """
        从Excel文件导入纵断面设计底高程表，填入多段纵坡表格。
        Excel格式：至少包含桩号和设计底高程两列（可含表头行）。
        """
        from PySide6.QtWidgets import QFileDialog, QTableWidgetItem
        path, _ = QFileDialog.getOpenFileName(
            self, "选择设计底高程表", "",
            "Excel/CSV文件 (*.xlsx *.csv *.txt);;所有文件 (*)")
        if not path:
            return
        try:
            if path.lower().endswith(('.xlsx', '.xls')):
                from 土石方计算.io.excel_reader import ExcelTerrainReader
                table = ExcelTerrainReader(path).read_design_elevations()
            else:
                from 土石方计算.io.csv_reader import CSVTerrainReader
                table = CSVTerrainReader().read_design_elevations(path)

            if not table:
                self._infobar("警告", "未读取到有效数据，请确认文件格式（桩号/设计底高程 两列）", "warning")
                return

            stations = sorted(table.keys())
            # 将 station→elevation 表转为分段纵坡
            segments = []
            for i in range(len(stations) - 1):
                s0, s1 = stations[i], stations[i + 1]
                e0, e1 = table[s0], table[s1]
                slope = (e1 - e0) / (s1 - s0) if abs(s1 - s0) > 1e-6 else 0.0
                segments.append((s0, e0, slope, s1))

            if not segments:
                # 只有一行数据 → 单段，坡度=0
                s0 = stations[0]
                segments = [(s0, table[s0], 0.0, s0)]

            self._dp_table.setRowCount(len(segments))
            for r, (s0, e0, slope, s1) in enumerate(segments):
                self._dp_table.setItem(r, 0, QTableWidgetItem(f"{s0:.1f}"))
                self._dp_table.setItem(r, 1, QTableWidgetItem(f"{e0:.3f}"))
                self._dp_table.setItem(r, 2, QTableWidgetItem(f"{slope:.6f}"))
                self._dp_table.setItem(r, 3, QTableWidgetItem(f"{s1:.1f}"))

            self._log_msg(f"从Excel导入纵坡：{len(segments)} 段，{len(stations)} 个控制桩号", "OK")
            self._infobar("导入成功",
                f"已填入 {len(segments)} 段纵坡，共 {len(stations)} 个桩号", "success")
        except Exception as exc:
            self._log_msg(f"Excel导入纵坡失败: {exc}", "ERR")
            self._infobar("导入失败", str(exc)[:80], "error")

    # ── 从推求水面线模块读取纵坡 ─────────────────────────
    def _on_import_from_water_profile(self):
        """
        尝试从主窗口的推求水面线面板读取已计算的渠底高程序列，
        填入纵坡设计多段表格（station → invert_elevation 映射）。
        """
        try:
            main_win = self
            for _ in range(10):
                parent = main_win.parent()
                if parent is None:
                    break
                main_win = parent
                if hasattr(main_win, 'water_profile_panel'):
                    break

            wp_panel = getattr(main_win, 'water_profile_panel', None)
            if wp_panel is None:
                self._infobar("提示",
                    "未找到推求水面线面板，请确保从主窗口启动程序", "warning")
                return

            # 推求水面线模块使用 calculated_nodes (ChannelNode 列表)
            # 每个节点有 station_MC (里程桩号) + bottom_elevation (渠底高程)
            calc_nodes = getattr(wp_panel, 'calculated_nodes', None)

            if not calc_nodes:
                self._infobar("提示",
                    "推求水面线模块无计算结果。"
                    "请先在「推求水面线」页完成计算。", "info")
                return

            # 从节点提取 (station, bottom_elevation) 对
            # 跳过渐变段行和无效数据行
            pairs = []
            for node in calc_nodes:
                try:
                    if getattr(node, 'is_transition', False):
                        continue
                    station = getattr(node, 'station_MC', None)
                    be = getattr(node, 'bottom_elevation', None)
                    if station is not None and be is not None and float(be) > 0:
                        pairs.append((float(station), float(be)))
                except (TypeError, ValueError):
                    continue

            if not pairs:
                self._infobar("提示", "未读取到有效的纵断面设计高程数据", "warning")
                return

            # 构建分段：每隔采样个数取一个点作为控制桩号
            step = max(1, len(pairs) // 20)  # 最多20段
            ctrl_pts = pairs[::step]
            if pairs[-1] not in ctrl_pts:
                ctrl_pts.append(pairs[-1])

            # 填入纵坡设计表格（每行: 起始桩号/起始高程/0坡度/终止桩号）
            from PySide6.QtWidgets import QTableWidgetItem
            self._dp_table.setRowCount(len(ctrl_pts) - 1)
            for r, (p0, p1) in enumerate(zip(ctrl_pts[:-1], ctrl_pts[1:])):
                s0, e0 = p0
                s1, e1 = p1
                slope = (e1 - e0) / (s1 - s0) if abs(s1 - s0) > 1e-6 else 0.0
                self._dp_table.setItem(r, 0, QTableWidgetItem(f"{s0:.1f}"))
                self._dp_table.setItem(r, 1, QTableWidgetItem(f"{e0:.3f}"))
                self._dp_table.setItem(r, 2, QTableWidgetItem(f"{slope:.6f}"))
                self._dp_table.setItem(r, 3, QTableWidgetItem(f"{s1:.1f}"))

            n = len(ctrl_pts) - 1
            self._log_msg(f"从水面线模块读取纵断面：{n} 段，{len(pairs)} 个点", "OK")
            self._infobar("读取成功",
                f"已填入 {n} 段纵坡，共 {len(pairs)} 个控制点", "success")

        except Exception as exc:
            self._log_msg(f"从水面线读取失败: {exc}", "WARN")
            self._infobar("读取失败", str(exc)[:80], "warning")

    @staticmethod
    def _read_field(panel, attr_names: list) -> "float | None":
        """按属性名列表从面板读取数值（支持 SpinBox、LineEdit/TextEdit 两种控件）"""
        for name in attr_names:
            obj = getattr(panel, name, None)
            if obj is None:
                continue
            # SpinBox / DoubleSpinBox
            if hasattr(obj, 'value'):
                try:
                    return float(obj.value())
                except Exception:
                    continue
            # LineEdit / QLineEdit
            if hasattr(obj, 'text'):
                try:
                    txt = obj.text().strip()
                    if txt:
                        return float(txt)
                except Exception:
                    continue
        return None

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
            # 恢复设计断面参数
            ds = proj._design_section
            if ds:
                self._ds_b.setValue(ds.bottom_width)
                self._ds_h.setValue(ds.depth)
                self._ds_ml.setValue(ds.inner_slope_left)
                self._ds_mr.setValue(ds.inner_slope_right)
            # 恢复纵坡参数（多段表格）
            dp = proj._design_profile
            if dp and dp.segments:
                from PySide6.QtWidgets import QTableWidgetItem as _TWI
                dp_table = getattr(self, '_dp_table', None)
                if dp_table is not None:
                    dp_table.setRowCount(len(dp.segments))
                    for r, seg in enumerate(dp.segments):
                        dp_table.setItem(r, 0, _TWI(f"{seg.start_station:.1f}"))
                        dp_table.setItem(r, 1, _TWI(f"{seg.start_invert_elevation:.3f}"))
                        dp_table.setItem(r, 2, _TWI(f"{seg.slope:.6f}"))
                        dp_table.setItem(r, 3, _TWI(f"{seg.end_station:.1f}"))
                else:
                    seg = dp.segments[0]
                    self._dp_s0.setValue(seg.start_station)
                    self._dp_e0.setValue(seg.start_invert_elevation)
                    self._dp_i.setValue(seg.slope)
                    self._dp_s1.setValue(seg.end_station)
            # 恢复边坡参数（取第一段）
            if proj._excavation_slopes:
                sc = proj._excavation_slopes[0]
                grades = sc.left_grades
                self._slope_table.setRowCount(len(grades))
                for r, g in enumerate(grades):
                    h_txt = "∞" if g.height == math.inf else f"{g.height:.2f}"
                    from PySide6.QtWidgets import QTableWidgetItem
                    self._slope_table.setItem(r, 0, QTableWidgetItem(f"{g.ratio:.2f}"))
                    self._slope_table.setItem(r, 1, QTableWidgetItem(h_txt))
                    self._slope_table.setItem(r, 2, QTableWidgetItem(f"{g.berm_width:.2f}"))
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
