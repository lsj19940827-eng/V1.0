# -*- coding: utf-8 -*-
"""
土石方工程量计算模块

Phase 1 — 核心算法层（无 UI 依赖）

顶层入口：EarthworkProject — 组织所有子模块协作的门面类（Facade）

典型工作流：
    1. 导入地形数据（DXF / CSV / Excel）→ 构建 TIN
    2. 导入/配置中心线
    3. 导入/配置设计断面 + 纵坡
    4. 配置开挖边坡 + 地质分层
    5. 切割断面（纵断面 + 横断面）
    6. 计算面积 + 工程量
    7. 导出 Excel 表格 + DXF 图纸

示例::

    proj = EarthworkProject(name="南峰寺支渠土石方")
    proj.load_terrain_from_dxf("terrain.dxf", contour_layer="等高线")
    proj.build_tin()
    proj.load_centerline_from_dxf("centerline.dxf")
    proj.set_design_profile_from_excel("design_profile.xlsx")
    proj.add_excavation_slope(ExcavationSlope(...))
    proj.run_all_sections(interval=20.0)
    proj.export_excel("土石方计算成果.xlsx")
    proj.export_cross_section_dxf("横断面图.dxf")
"""

from __future__ import annotations
import os
import json
import math
from typing import Optional

from 土石方计算.models.terrain import TerrainPoint, ConstraintEdge, TINModel
from 土石方计算.models.alignment import Alignment
from 土石方计算.models.section import (
    ExcavationSlope, SlopeGrade,
    BackfillConfig,
    DesignSection, DesignProfile,
    GeologyLayer,
    CrossSectionData, LongitudinalData,
    VolumeResult,
)
from 土石方计算.core.tin_builder import TINBuilder
from 土石方计算.core.tin_interpolator import TINInterpolator
from 土石方计算.core.profile_cutter import ProfileCutter
from 土石方计算.core.cross_section import CrossSectionCalculator
from 土石方计算.core.volume_calculator import VolumeCalculator
from 土石方计算.core.geology_layer import GeologyLayerManager
from 土石方计算.io.dxf_terrain_reader import DXFTerrainReader
from 土石方计算.io.csv_reader import CSVTerrainReader
from 土石方计算.io.excel_reader import ExcelTerrainReader
from 土石方计算.io.excel_exporter import EarthworkExcelExporter
from 土石方计算.io.dxf_profile_exporter import (
    CrossSectionDXFExporter, CrossSectionDXFConfig,
    LongitudinalDXFExporter, LongitudinalDXFConfig,
)


class EarthworkProject:
    """
    土石方工程量计算项目（门面类）

    管理地形数据、中心线、设计参数、断面计算结果和成果导出的完整生命周期。
    项目状态可序列化为 `project.earthwork.json`，大数据缓存存于 `.cache/` 子目录。

    Attributes
    ----------
    name : 项目名称
    project_dir : 项目文件所在目录（存放 JSON 和缓存）
    """

    PROJECT_FILE_SUFFIX = ".earthwork.json"
    CACHE_DIR = ".cache"

    def __init__(self, name: str = "未命名项目", project_dir: str = "."):
        self.name = name
        self.project_dir = os.path.abspath(project_dir)

        # ---- 地形数据 ----
        self._terrain_points: list[TerrainPoint] = []
        self._constraint_edges: list[ConstraintEdge] = []
        self._terrain_source_files: list[str] = []
        self._tin: Optional[TINModel] = None
        self._interpolator: Optional[TINInterpolator] = None

        # ---- 中心线 ----
        self._alignment: Optional[Alignment] = None

        # ---- 设计参数 ----
        self._design_section: Optional[DesignSection] = None
        self._design_profile: Optional[DesignProfile] = None
        self._excavation_slopes: list[ExcavationSlope] = []
        self._backfill_config: BackfillConfig = BackfillConfig()

        # ---- 地质分层 ----
        self._geology_mgr: GeologyLayerManager = GeologyLayerManager()

        # ---- 断面计算结果 ----
        self._longitudinal: Optional[LongitudinalData] = None
        self._cross_sections: list[CrossSectionData] = []
        self._volume_result: Optional[VolumeResult] = None

    # ==================================================================
    # 地形数据导入
    # ==================================================================

    def load_terrain_from_dxf(
        self,
        path: str,
        contour_layer: Optional[str] = None,
        elevation_point_layer: Optional[str] = None,
        contour_interval: float = 1.0,
    ) -> None:
        """
        从 DXF 文件导入地形数据。

        Parameters
        ----------
        path : DXF 文件路径
        contour_layer : 等高线图层名（None 表示读取所有图层）
        elevation_point_layer : 高程点图层名（None 表示跳过）
        contour_interval : 等高线离散化间距（m）
        """
        reader = DXFTerrainReader(path)
        pts, edges = reader.read_contours(
            layer=contour_layer, interval=contour_interval
        )
        self._terrain_points.extend(pts)
        self._constraint_edges.extend(edges)

        if elevation_point_layer is not None:
            elev_pts = reader.read_elevation_points(layer=elevation_point_layer)
            self._terrain_points.extend(elev_pts)

        if path not in self._terrain_source_files:
            self._terrain_source_files.append(path)
        self._invalidate_tin()

    def load_terrain_from_csv(
        self,
        path: str,
        delimiter: str = ",",
        col_x: int = 0,
        col_y: int = 1,
        col_z: int = 2,
        skip_rows: int = 0,
    ) -> None:
        """从 CSV/TXT 文件导入地形点"""
        reader = CSVTerrainReader()
        pts = reader.read_terrain(path, delimiter=delimiter,
                                   col_x=col_x, col_y=col_y, col_z=col_z,
                                   skip_rows=skip_rows)
        self._terrain_points.extend(pts)
        if path not in self._terrain_source_files:
            self._terrain_source_files.append(path)
        self._invalidate_tin()

    def load_terrain_from_excel(
        self,
        path: str,
        sheet: str = "Sheet1",
        col_x: str = "X",
        col_y: str = "Y",
        col_z: str = "Z",
    ) -> None:
        """从 Excel 文件导入地形点"""
        reader = ExcelTerrainReader(path)
        pts = reader.read_terrain(sheet=sheet, col_x=col_x,
                                   col_y=col_y, col_z=col_z)
        self._terrain_points.extend(pts)
        if path not in self._terrain_source_files:
            self._terrain_source_files.append(path)
        self._invalidate_tin()

    def clear_terrain(self) -> None:
        """清空所有地形数据"""
        self._terrain_points.clear()
        self._constraint_edges.clear()
        self._terrain_source_files.clear()
        self._invalidate_tin()

    @property
    def terrain_point_count(self) -> int:
        return len(self._terrain_points)

    # ==================================================================
    # TIN 构建
    # ==================================================================

    def build_tin(
        self,
        use_cache: bool = True,
        cache_name: str = "terrain",
    ) -> TINModel:
        """
        构建约束 Delaunay 三角网。

        Parameters
        ----------
        use_cache : 是否启用缓存（源文件未变化时直接加载缓存）
        cache_name : 缓存文件名（不含扩展名）

        Returns
        -------
        TINModel
        """
        if not self._terrain_points:
            raise RuntimeError("尚未导入地形数据，请先调用 load_terrain_from_* 方法")

        cache_path = None
        if use_cache:
            cache_dir = os.path.join(self.project_dir, self.CACHE_DIR)
            cache_path = os.path.join(cache_dir, f"{cache_name}.npz")

        builder = TINBuilder()
        builder.add_contour_points(self._terrain_points, self._constraint_edges)
        self._tin = builder.build(
            cache_path=cache_path,
            source_files=self._terrain_source_files,
        )
        self._interpolator = TINInterpolator(self._tin)
        return self._tin

    @property
    def tin(self) -> Optional[TINModel]:
        return self._tin

    @property
    def is_tin_built(self) -> bool:
        return self._tin is not None and not self._tin.is_empty

    # ==================================================================
    # 中心线
    # ==================================================================

    def load_centerline_from_dxf(
        self, path: str, layer: Optional[str] = None
    ) -> None:
        """从 DXF 文件读取中心线（取最长多段线）"""
        reader = DXFTerrainReader(path)
        pts = reader.read_centerline(layer=layer)
        if len(pts) < 2:
            raise ValueError(f"DXF 中未找到足够的中心线折点（图层={layer!r}）")
        self._alignment = Alignment.from_polyline_points(pts)

    def load_centerline_from_csv(
        self,
        path: str,
        delimiter: str = ",",
        col_station: int = 0,
        col_x: int = 1,
        col_y: int = 2,
        skip_rows: int = 1,
    ) -> None:
        """从 CSV 桩号坐标表读取中心线"""
        reader = CSVTerrainReader()
        self._alignment = reader.read_centerline(
            path, delimiter=delimiter,
            col_station=col_station, col_x=col_x, col_y=col_y,
            skip_rows=skip_rows,
        )

    def set_alignment(self, alignment: Alignment) -> None:
        """直接设置中心线对象"""
        self._alignment = alignment

    @property
    def alignment(self) -> Optional[Alignment]:
        return self._alignment

    # ==================================================================
    # 设计参数配置
    # ==================================================================

    def set_design_section(self, design: DesignSection) -> None:
        """设置渠道设计断面参数"""
        self._design_section = design

    def set_design_profile(self, profile: DesignProfile) -> None:
        """设置纵断面设计（纵坡参数）"""
        self._design_profile = profile

    def set_design_profile_from_excel(
        self,
        path: str,
        sheet: str = "设计底高程",
        col_station: str = "桩号",
        col_elevation: str = "设计底高程",
    ) -> None:
        """从 Excel 表格读取纵断面设计底高程"""
        reader = ExcelTerrainReader(path)
        table = reader.read_design_elevations(
            sheet=sheet, col_station=col_station, col_elevation=col_elevation
        )
        self._design_profile = DesignProfile(
            station_elevation_table=table, source="excel"
        )

    def add_excavation_slope(self, slope: ExcavationSlope) -> None:
        """添加一段开挖边坡配置（分桩号段指定）"""
        self._excavation_slopes.append(slope)

    def set_backfill_config(self, config: BackfillConfig) -> None:
        self._backfill_config = config

    # ==================================================================
    # 地质分层配置
    # ==================================================================

    @property
    def geology(self) -> GeologyLayerManager:
        """返回地质分层管理器（直接操作）"""
        return self._geology_mgr

    # ==================================================================
    # 断面切割 & 工程量计算
    # ==================================================================

    def run_longitudinal(
        self,
        step: float = 1.0,
        extra_stations: Optional[list[float]] = None,
    ) -> LongitudinalData:
        """
        生成纵断面地面线（+ 设计底高程，若已设置）。

        Returns
        -------
        LongitudinalData
        """
        self._check_ready(need_tin=True, need_alignment=True)
        cutter = ProfileCutter(self._interpolator)
        self._longitudinal = cutter.cut_longitudinal(
            self._alignment,
            step=step,
            design_profile=self._design_profile,
            extra_stations=extra_stations,
        )
        return self._longitudinal

    def run_cross_sections(
        self,
        interval: float = 20.0,
        extra_stations: Optional[list[float]] = None,
        half_width: Optional[float] = None,
        sample_step: float = 0.5,
    ) -> list[CrossSectionData]:
        """
        生成全线横断面地面线，并计算面积（若设计参数已配置）。

        Returns
        -------
        list[CrossSectionData]
        """
        self._check_ready(need_tin=True, need_alignment=True)
        cutter = ProfileCutter(self._interpolator)

        # 自动估算半宽
        if half_width is None and self._design_section:
            half_width = ProfileCutter.estimate_section_width(
                self._design_section.top_width
            )
        elif half_width is None:
            half_width = 30.0

        self._cross_sections = cutter.cut_all_cross_sections(
            self._alignment,
            interval=interval,
            extra_stations=extra_stations,
            half_width=half_width,
            sample_step=sample_step,
        )

        # 若设计参数已配置，计算面积
        if self._design_section and self._design_profile and self._excavation_slopes:
            self._compute_section_areas()

        return self._cross_sections

    def run_all_sections(
        self,
        interval: float = 20.0,
        longitudinal_step: float = 1.0,
        extra_stations: Optional[list[float]] = None,
        half_width: Optional[float] = None,
    ) -> None:
        """
        一键执行：纵断面 + 横断面切割 + 面积计算 + 体积计算。
        """
        self.run_longitudinal(step=longitudinal_step,
                               extra_stations=extra_stations)
        self.run_cross_sections(interval=interval,
                                extra_stations=extra_stations,
                                half_width=half_width)
        if (self._cross_sections
                and all(s.area_result for s in self._cross_sections)):
            self.compute_volumes()

    def compute_volumes(
        self,
        compute_tin_volume: bool = False,
    ) -> VolumeResult:
        """
        计算全线土石方工程量（平均断面法 + 棱台法，可选 TIN 体积法）。
        """
        if not self._cross_sections:
            raise RuntimeError("请先调用 run_cross_sections()")
        calc = VolumeCalculator()
        self._volume_result = calc.compute_all(
            self._cross_sections, self._alignment,
            compute_tin_volume=compute_tin_volume,
        )
        return self._volume_result

    # ==================================================================
    # 成果导出
    # ==================================================================

    def export_excel(self, output_path: str) -> None:
        """导出全部计算成果到 Excel 文件"""
        exporter = EarthworkExcelExporter()
        exporter.export(
            output_path=output_path,
            long_data=self._longitudinal,
            sections=self._cross_sections if self._cross_sections else None,
            volume_result=self._volume_result,
            project_name=self.name,
        )

    def export_cross_section_dxf(
        self,
        output_path: str,
        config: Optional[CrossSectionDXFConfig] = None,
    ) -> None:
        """导出横断面批量 DXF 图纸"""
        if not self._cross_sections:
            raise RuntimeError("请先调用 run_cross_sections()")
        exporter = CrossSectionDXFExporter(config)
        exporter.export(
            self._cross_sections,
            geology_layers=self._geology_mgr.layers,
            output_path=output_path,
        )

    # ==================================================================
    # 项目文件序列化
    # ==================================================================

    def save(self, path: Optional[str] = None) -> str:
        """
        保存项目参数到 JSON 文件（不含 TIN/断面大数据，那些在缓存中）。

        Returns
        -------
        实际保存路径
        """
        if path is None:
            safe_name = self.name.replace("/", "_").replace("\\", "_")
            path = os.path.join(self.project_dir, f"{safe_name}{self.PROJECT_FILE_SUFFIX}")

        data = {
            "name": self.name,
            "version": "1.0",
            "terrain_sources": self._terrain_source_files,
            "design_section": self._serialize_design_section(),
            "design_profile": self._serialize_design_profile(),
            "excavation_slopes": [self._serialize_slope(s)
                                   for s in self._excavation_slopes],
            "backfill": {
                "mode": self._backfill_config.mode.value,
                "thickness": self._backfill_config.thickness,
                "include_slope_backfill": self._backfill_config.include_slope_backfill,
            },
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return path

    @classmethod
    def load(cls, path: str) -> "EarthworkProject":
        """从 JSON 文件加载项目（恢复所有参数，不自动重建 TIN）"""
        from 土石方计算.models.section import BackfillMode
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        proj = cls(
            name=data.get("name", "未命名项目"),
            project_dir=os.path.dirname(os.path.abspath(path)),
        )
        proj._terrain_source_files = data.get("terrain_sources", [])
        proj._design_section = cls._deserialize_design_section(
            data.get("design_section", {}))
        proj._design_profile = cls._deserialize_design_profile(
            data.get("design_profile", {}))
        proj._excavation_slopes = [
            cls._deserialize_slope(s)
            for s in data.get("excavation_slopes", [])
            if s.get("left_grades")  # 跳过不完整的旧格式记录
        ]
        bf_data = data.get("backfill", {})
        if bf_data:
            from 土石方计算.models.section import BackfillConfig
            try:
                proj._backfill_config = BackfillConfig(
                    mode=BackfillMode(bf_data.get("mode", "fixed_thickness")),
                    thickness=bf_data.get("thickness", 0.3),
                    include_slope_backfill=bf_data.get("include_slope_backfill", True),
                )
            except (ValueError, KeyError):
                pass
        return proj

    # ==================================================================
    # 内部辅助
    # ==================================================================

    def _check_ready(self, need_tin: bool = False,
                     need_alignment: bool = False) -> None:
        if need_tin and not self.is_tin_built:
            raise RuntimeError("TIN 尚未构建，请先调用 build_tin()")
        if need_alignment and self._alignment is None:
            raise RuntimeError("中心线尚未设置，请先调用 load_centerline_*() 或 set_alignment()")

    def _invalidate_tin(self) -> None:
        """地形数据变更后使 TIN 和插值器失效"""
        self._tin = None
        self._interpolator = None
        self._longitudinal = None
        self._cross_sections = []
        self._volume_result = None

    def _get_slope_for_station(self, station: float) -> Optional[ExcavationSlope]:
        """查找覆盖指定桩号的开挖边坡配置"""
        for slope in self._excavation_slopes:
            if slope.start_station <= station <= slope.end_station:
                return slope
        return None

    def _compute_section_areas(self) -> None:
        """对所有横断面计算设计线和面积"""
        calc = CrossSectionCalculator()
        for sec in self._cross_sections:
            invert_elev = (
                self._design_profile.get_invert_at_station(sec.station)
                if self._design_profile else None
            )
            slope_cfg = self._get_slope_for_station(sec.station)
            if invert_elev is None or slope_cfg is None:
                continue
            # 地质剖面（若地质分层管理器有数据）
            ground_center = next(
                (p[1] for p in sec.ground_points if abs(p[0]) < 0.01),
                float("nan"),
            )
            if not math.isnan(ground_center):
                geo_profile = self._geology_mgr.get_profile_at_station(
                    sec.station, ground_center
                )
                sec.geology_profile = geo_profile

            calc.compute(
                sec,
                self._design_section,
                slope_cfg,
                invert_elev,
                self._backfill_config,
            )

    def _serialize_design_section(self) -> dict:
        ds = self._design_section
        if ds is None:
            return {}
        return {
            "channel_type": ds.channel_type.value,
            "bottom_width": ds.bottom_width,
            "depth": ds.depth,
            "inner_slope_left": ds.inner_slope_left,
            "inner_slope_right": ds.inner_slope_right,
            "freeboard": ds.freeboard,
            "lining_thickness": ds.lining_thickness,
            "name": ds.name,
        }

    @staticmethod
    def _serialize_slope(slope: ExcavationSlope) -> dict:
        def _grade(g: SlopeGrade) -> dict:
            return {
                "ratio": g.ratio,
                "height": g.height if g.height != math.inf else "inf",
                "berm_width": g.berm_width,
            }
        return {
            "start_station": slope.start_station,
            "end_station": slope.end_station,
            "left_grades": [_grade(g) for g in slope.left_grades],
            "right_grades": [_grade(g) for g in slope.right_grades],
            "platform_enabled": slope.platform_enabled,
            "platform_width": slope.platform_width,
        }

    def _serialize_design_profile(self) -> dict:
        dp = self._design_profile
        if dp is None:
            return {}
        if dp.station_elevation_table:
            return {
                "source": dp.source,
                "station_elevation_table": {
                    str(k): v for k, v in dp.station_elevation_table.items()
                },
            }
        return {
            "source": dp.source,
            "segments": [
                {
                    "start_station": seg.start_station,
                    "end_station": seg.end_station,
                    "start_invert_elevation": seg.start_invert_elevation,
                    "slope": seg.slope,
                }
                for seg in dp.segments
            ],
        }

    @staticmethod
    def _deserialize_design_section(data: dict):
        from 土石方计算.models.section import DesignSection, ChannelType
        if not data:
            return None
        return DesignSection(
            channel_type=ChannelType(data.get("channel_type", "trapezoidal")),
            bottom_width=data.get("bottom_width", 0.0),
            depth=data.get("depth", 0.0),
            inner_slope_left=data.get("inner_slope_left", 1.0),
            inner_slope_right=data.get("inner_slope_right", 1.0),
            freeboard=data.get("freeboard", 0.0),
            lining_thickness=data.get("lining_thickness", 0.0),
            name=data.get("name", ""),
        )

    @staticmethod
    def _deserialize_slope(data: dict) -> "ExcavationSlope":
        def _grade(d: dict) -> "SlopeGrade":
            h = d.get("height", math.inf)
            if h == "inf":
                h = math.inf
            return SlopeGrade(
                ratio=d.get("ratio", 1.0),
                height=float(h),
                berm_width=d.get("berm_width", 0.0),
            )
        return ExcavationSlope(
            start_station=data["start_station"],
            end_station=data["end_station"],
            left_grades=[_grade(g) for g in data.get("left_grades", [])],
            right_grades=[_grade(g) for g in data.get("right_grades", [])],
            platform_enabled=data.get("platform_enabled", False),
            platform_width=data.get("platform_width", 2.0),
        )

    @staticmethod
    def _deserialize_design_profile(data: dict):
        from 土石方计算.models.section import DesignProfile, DesignProfileSegment
        if not data:
            return None
        if "station_elevation_table" in data:
            table = {float(k): v
                     for k, v in data["station_elevation_table"].items()}
            return DesignProfile(
                station_elevation_table=table,
                source=data.get("source", "excel"),
            )
        segments = [
            DesignProfileSegment(
                start_station=s["start_station"],
                end_station=s["end_station"],
                start_invert_elevation=s["start_invert_elevation"],
                slope=s["slope"],
            )
            for s in data.get("segments", [])
        ]
        return DesignProfile(segments=segments, source=data.get("source", "manual"))


# 公共导出（方便 from 土石方计算 import ...）
__all__ = [
    "EarthworkProject",
    # models
    "TerrainPoint", "ConstraintEdge", "TINModel",
    "Alignment",
    "SlopeGrade", "ExcavationSlope", "BackfillConfig",
    "DesignSection", "DesignProfile",
    "GeologyLayer",
    # core
    "TINBuilder", "TINInterpolator",
    "ProfileCutter", "CrossSectionCalculator",
    "VolumeCalculator", "GeologyLayerManager",
    # io
    "DXFTerrainReader", "CSVTerrainReader", "ExcelTerrainReader",
    "EarthworkExcelExporter",
    "CrossSectionDXFExporter", "CrossSectionDXFConfig",
    "LongitudinalDXFExporter", "LongitudinalDXFConfig",
]
