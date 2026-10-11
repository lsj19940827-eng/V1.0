# -*- coding: utf-8 -*-
"""有压批量计算与导出之间的数据契约；不依赖绘图库或界面。"""

import copy
from dataclasses import dataclass, field
from typing import List, Optional
import numpy as np

PLOT_FLOW_UNIT_M3_PER_S = r"m$^3$/s"


@dataclass
class BatchScanConfig:
    """批量扫描配置"""
    q_values: np.ndarray
    slope_denominators: List[int]
    diameter_values: Optional[np.ndarray]
    materials: List[str]           # 管材键名列表
    n_unpr: float = 0.014
    length_m: float = 1000.0
    local_loss_ratio: float = 0.15  # 局部损失比例
    output_dir: str = ""
    # ===== 输出选项 (可按需开启/关闭) =====
    output_csv: bool = True           # CSV计算结果：包含所有工况的原始数据，便于后续分析
    output_pdf_charts: bool = True    # 无压能力/充满度/流速对比图与有压优选点图
    output_merged_pdf: bool = True    # 合并PDF：将所有图表合并成一个完整文档
    output_subplot_png: bool = True   # 子图PNG：每个Q值生成独立的高清PNG图片(300DPI)
    pe_material_grade: str = "PE100"  # PE 批量扫描材料等级
    pe_nominal_pressure_mpa: float = 1.0  # PE 批量扫描公称压力 (MPa)
    use_product_catalogs: bool = True  # 非 PE 目录管材是否扫描规范离散规格
    ductile_iron_class: str = "PREFERRED"  # 球墨铸铁管等级选择
    pccp_variant: str = "PCCPE"  # PCCP 产品型式
    steel_dimensions_enabled: bool = False  # 保持旧批量脚本接口兼容
    steel_dimension_basis: str = "outer"
    steel_lining_thickness_mm: float = 0.0
    steel_diameter_candidates_mm: Optional[tuple[float, ...]] = None
    unpr_clearance_height: Optional[float] = None  # 项目自定净空高度下限
    unpr_clearance_area: Optional[float] = None  # 项目自定净空面积百分比下限


@dataclass(frozen=True)
class BatchCalculationSnapshot:
    """一次扫描的数值快照；导出只读取快照，不重新求解或查询目录。"""

    rows: tuple[dict, ...] = ()
    comparison_rows: tuple[dict, ...] = ()
    logs: tuple[str, ...] = ()
    has_unpressurized: bool = False
    cancelled: bool = False

    @classmethod
    def from_rows(cls, rows, comparison_rows, logs, *, has_unpressurized, cancelled=False):
        """与计算阶段的可变容器断开引用，便于重复导出。"""
        return cls(tuple(copy.deepcopy(rows)), tuple(copy.deepcopy(comparison_rows)), tuple(logs),
                   bool(has_unpressurized), bool(cancelled))


@dataclass(frozen=True)
class BatchExportOptions:
    """纯输出选项，不能借重导出改变水力输入。"""

    output_dir: str
    output_csv: bool = True
    output_pdf_charts: bool = True
    output_merged_pdf: bool = True
    output_subplot_png: bool = True

    @classmethod
    def from_config(cls, config: BatchScanConfig):
        """保留旧批量配置调用方式。"""
        return cls(**{name: getattr(config, name) for name in cls.__dataclass_fields__})


@dataclass
class BatchScanResult:
    """批量扫描结果"""
    csv_path: str = ""
    generated_pngs: List[str] = field(default_factory=list)
    generated_pdfs: List[str] = field(default_factory=list)
    merged_pdf: str = ""
    logs: List[str] = field(default_factory=list)
    comparison_rows: List[dict] = field(default_factory=list)
    comparison_csv_path: str = ""
    cancelled: bool = False  # 明确区分完整结果与中途取消。


