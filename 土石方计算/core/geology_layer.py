# -*- coding: utf-8 -*-
"""
地质分层管理器

负责：
1. 管理用户自定义地质层定义（名称/颜色/填充图案）
2. 从 DXF 分层线或桩号深度表构建各断面的地质分层剖面
3. 在横断面切割时提供分层界面高程
"""

from __future__ import annotations
import numpy as np
from typing import Optional

from 土石方计算.models.section import GeologyLayer, GeologySectionProfile


class GeologyLayerManager:
    """
    地质分层管理器

    Usage
    -----
    >>> mgr = GeologyLayerManager()
    >>> mgr.add_layer("残坡积层", color_index=3, hatch_pattern="ANSI31")
    >>> mgr.add_layer("强风化层", color_index=4, hatch_pattern="ANSI37")
    >>> # 从桩号深度表设置分层界面
    >>> mgr.set_depth_table("残坡积层", [(0, 2.0), (100, 2.5), (200, 1.8)])
    >>> profile = mgr.get_profile_at_station(50.0, ground_elevation=125.3)
    """

    # AutoCAD 标准填充图案（按地质类型预设）
    HATCH_PATTERNS = {
        "土方":    "ANSI31",    # 45° 斜线
        "软石":    "ANSI32",
        "硬石":    "AR-CONC",   # 混凝土/碎石
        "回填":    "DOTS",
        "default": "ANSI31",
    }

    def __init__(self):
        self._layers: list[GeologyLayer] = []   # 从下到上的层序
        self._depth_tables: dict[str, list[tuple[float, float]]] = {}
        # {layer_name: [(station, thickness_from_surface), ...]}

    # ------------------------------------------------------------------
    # 层定义管理
    # ------------------------------------------------------------------

    def add_layer(
        self,
        name: str,
        color_index: int = 8,
        hatch_pattern: str = "ANSI31",
        hatch_scale: float = 1.0,
        hatch_angle: float = 0.0,
        insert_above: Optional[str] = None,
    ) -> None:
        """
        添加地质层定义。

        Parameters
        ----------
        name : 层名称（用户自定义，如「残坡积层」「强风化层」）
        color_index : ACI 颜色编号
        hatch_pattern : AutoCAD 填充图案名
        insert_above : 若指定，则插入到该层的上方；否则追加到最顶层
        """
        if any(l.name == name for l in self._layers):
            raise ValueError(f"地质层「{name}」已存在")
        layer = GeologyLayer(
            name=name,
            color_index=color_index,
            hatch_pattern=hatch_pattern,
            hatch_scale=hatch_scale,
            hatch_angle=hatch_angle,
        )
        if insert_above and any(l.name == insert_above for l in self._layers):
            idx = next(i for i, l in enumerate(self._layers) if l.name == insert_above)
            self._layers.insert(idx + 1, layer)
        else:
            self._layers.append(layer)

    def remove_layer(self, name: str) -> None:
        self._layers = [l for l in self._layers if l.name != name]
        self._depth_tables.pop(name, None)

    def reorder_layers(self, names: list[str]) -> None:
        """重新排序地质层（从下到上）"""
        existing = {l.name: l for l in self._layers}
        self._layers = [existing[n] for n in names if n in existing]

    @property
    def layer_names(self) -> list[str]:
        return [l.name for l in self._layers]

    @property
    def layers(self) -> list[GeologyLayer]:
        return list(self._layers)

    # ------------------------------------------------------------------
    # 分层厚度数据
    # ------------------------------------------------------------------

    def set_depth_table(
        self,
        layer_name: str,
        table: list[tuple[float, float]],
    ) -> None:
        """
        设置某地质层的厚度沿桩号变化表。

        Parameters
        ----------
        layer_name : 层名称
        table : [(station, thickness_m), ...]，桩号+层厚（m），按桩号升序
        """
        if not any(l.name == layer_name for l in self._layers):
            raise ValueError(f"地质层「{layer_name}」未定义，请先调用 add_layer()")
        self._depth_tables[layer_name] = sorted(table, key=lambda r: r[0])

    def get_layer_thickness_at_station(
        self, layer_name: str, station: float
    ) -> float:
        """
        插值查询某地质层在指定桩号处的厚度（m）。
        超出范围时取最近端点值。
        """
        table = self._depth_tables.get(layer_name, [])
        if not table:
            return 0.0
        stations = np.array([r[0] for r in table])
        thicknesses = np.array([r[1] for r in table])
        return float(np.interp(station, stations, thicknesses))

    # ------------------------------------------------------------------
    # 横断面地质剖面生成
    # ------------------------------------------------------------------

    def get_profile_at_station(
        self,
        station: float,
        ground_elevation: float,
    ) -> GeologySectionProfile:
        """
        生成指定桩号处的地质分层剖面（各层顶面高程）。

        从地面向下，依次累计各层厚度得到各层底面高程（即下一层顶面高程）。
        层序从下到上：self._layers[0] 在最底部。

        Parameters
        ----------
        station : 桩号（m）
        ground_elevation : 该断面中心线处地面高程（m）

        Returns
        -------
        GeologySectionProfile — 各层顶面高程（从下到上）
        """
        top_elevations: list[float] = []
        cur_elev = ground_elevation

        # 从顶层（最接近地面）向下累计
        for layer in reversed(self._layers):
            thickness = self.get_layer_thickness_at_station(layer.name, station)
            cur_elev -= thickness
            top_elevations.insert(0, cur_elev + thickness)

        # 修正：top_elevations[i] 是第 i 层的顶面高程
        # 重新计算：第 0 层（最底层）顶面 = ground - sum(所有层厚)
        top_elevations_correct: list[float] = []
        depth = 0.0
        for layer in self._layers:   # 从下到上
            thickness = self.get_layer_thickness_at_station(layer.name, station)
            top = ground_elevation - depth
            top_elevations_correct.append(top)
            depth += thickness

        return GeologySectionProfile(
            station=station,
            layer_names=self.layer_names,
            top_elevations=top_elevations_correct,
        )

    # ------------------------------------------------------------------
    # DXF 导入（接口，由 io/dxf_terrain_reader.py 实现后回调）
    # ------------------------------------------------------------------

    def import_from_dxf_layers(
        self,
        layer_elevation_data: dict[str, list[tuple[float, float, float]]],
    ) -> None:
        """
        从 DXF 中提取的分层面高程数据初始化深度表。

        Parameters
        ----------
        layer_elevation_data : {layer_name: [(x, y, z), ...]}
            每层的高程点（来自 DXF 分层线）。
            此方法将高程点投影到中心线桩号后建立深度表。
            （完整实现依赖中心线，此处为接口预留）
        """
        raise NotImplementedError(
            "DXF 分层导入需要配合 CenterlineAlignment 使用，"
            "请使用 EarthworkProject.import_geology_from_dxf() 方法"
        )
