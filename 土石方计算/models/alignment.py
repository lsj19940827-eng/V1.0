# -*- coding: utf-8 -*-
"""
渠道中心线（Alignment）数据模型

包含：
- AlignmentPoint   — 中心线上的一个节点（平面坐标 + 累计桩号）
- ChainageBreak    — 断链记录（桩号跳跃/重叠）
- Alignment        — 完整中心线对象（节点序列 + 桩号/坐标互查）
"""

from __future__ import annotations
from dataclasses import dataclass, field
import math
import numpy as np
from typing import Optional


@dataclass
class AlignmentPoint:
    """中心线上的一个节点"""
    x: float
    y: float
    station: float  # 累计桩号（m）


@dataclass
class ChainageBreak:
    """
    断链记录

    在 break_station 处，实际桩号从 actual_station_before 跳到
    actual_station_after（短链为负跳，长链为正跳）。
    """
    break_station: float      # 断链位置的连续里程（m）
    actual_station_before: float
    actual_station_after: float

    @property
    def delta(self) -> float:
        return self.actual_station_after - self.actual_station_before


class Alignment:
    """
    渠道中心线

    支持两种来源（由 classmethod 构建）：
    1. from_polyline_points(pts)  — DXF LWPOLYLINE 折点列表 [(x, y), ...]
    2. from_station_table(rows)   — 桩号坐标表 [(station, x, y), ...]

    核心功能
    --------
    get_xy_at_station(station)       → (x, y)
    get_tangent_angle_at_station(s)  → 切线方向角（弧度，从+X轴逆时针）
    get_station_at_xy(x, y)          → 最近点桩号（近似）
    get_normal_direction(station)    → 法线方向角（垂直于切线）
    """

    def __init__(self, points: list[AlignmentPoint],
                 chainage_breaks: Optional[list[ChainageBreak]] = None):
        if len(points) < 2:
            raise ValueError("中心线至少需要 2 个节点")
        self._points = points
        self._breaks: list[ChainageBreak] = chainage_breaks or []

        # 预计算：numpy 数组加速插值
        self._stations = np.array([p.station for p in points])
        self._xs = np.array([p.x for p in points])
        self._ys = np.array([p.y for p in points])

    # ------------------------------------------------------------------
    # 构造方法
    # ------------------------------------------------------------------

    @classmethod
    def from_polyline_points(
        cls,
        pts: list[tuple[float, float]],
        start_station: float = 0.0,
        chainage_breaks: Optional[list[ChainageBreak]] = None
    ) -> "Alignment":
        """
        从 DXF 多段线折点列表构建中心线，自动计算累计桩号。

        Parameters
        ----------
        pts : list of (x, y)
        start_station : 起始桩号（默认 0.0）
        """
        if len(pts) < 2:
            raise ValueError("至少需要 2 个折点")
        ap_list: list[AlignmentPoint] = []
        s = start_station
        for i, (x, y) in enumerate(pts):
            if i > 0:
                dx = x - pts[i - 1][0]
                dy = y - pts[i - 1][1]
                s += math.hypot(dx, dy)
            ap_list.append(AlignmentPoint(x=x, y=y, station=s))
        return cls(ap_list, chainage_breaks)

    @classmethod
    def from_station_table(
        cls,
        rows: list[tuple[float, float, float]],
        chainage_breaks: Optional[list[ChainageBreak]] = None
    ) -> "Alignment":
        """
        从桩号坐标表构建中心线。

        Parameters
        ----------
        rows : list of (station, x, y)，按桩号升序排列
        """
        if len(rows) < 2:
            raise ValueError("至少需要 2 行")
        rows_sorted = sorted(rows, key=lambda r: r[0])
        ap_list = [AlignmentPoint(x=r[1], y=r[2], station=r[0])
                   for r in rows_sorted]
        return cls(ap_list, chainage_breaks)

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def total_length(self) -> float:
        """中心线总长（连续里程，m）"""
        return float(self._stations[-1] - self._stations[0])

    @property
    def start_station(self) -> float:
        return float(self._stations[0])

    @property
    def end_station(self) -> float:
        return float(self._stations[-1])

    @property
    def points(self) -> list[AlignmentPoint]:
        return list(self._points)

    # ------------------------------------------------------------------
    # 核心查询
    # ------------------------------------------------------------------

    def get_xy_at_station(self, station: float) -> tuple[float, float]:
        """
        给定桩号，返回平面坐标 (x, y)（线性插值）。

        桩号超出范围时夹紧到端点。
        """
        s = float(np.clip(station, self._stations[0], self._stations[-1]))
        x = float(np.interp(s, self._stations, self._xs))
        y = float(np.interp(s, self._stations, self._ys))
        return x, y

    def get_tangent_angle_at_station(self, station: float) -> float:
        """
        给定桩号，返回切线方向角（弧度，arctan2(dy, dx)，从+X轴逆时针）。

        超出范围时使用最近端点处的切线方向。
        """
        eps = 0.5  # 差分步长 (m)
        s0 = max(self._stations[0], station - eps)
        s1 = min(self._stations[-1], station + eps)
        if s1 <= s0:
            s0 = self._stations[0]
            s1 = self._stations[0] + eps
        x0, y0 = self.get_xy_at_station(s0)
        x1, y1 = self.get_xy_at_station(s1)
        return math.atan2(y1 - y0, x1 - x0)

    def get_normal_direction(self, station: float) -> float:
        """
        给定桩号，返回法线方向角（切线方向 + π/2，即指向左侧）。
        """
        return self.get_tangent_angle_at_station(station) + math.pi / 2

    def get_station_at_xy(self, x: float, y: float) -> float:
        """
        给定平面坐标，返回中心线上最近点的桩号（近似投影法）。
        """
        pt = np.array([x, y])
        pts_xy = np.column_stack([self._xs, self._ys])
        # 逐段投影
        best_s = self._stations[0]
        best_dist = float("inf")
        for i in range(len(self._points) - 1):
            a = pts_xy[i]
            b = pts_xy[i + 1]
            ab = b - a
            seg_len = np.linalg.norm(ab)
            if seg_len < 1e-10:
                continue
            t = np.clip(np.dot(pt - a, ab) / (seg_len ** 2), 0.0, 1.0)
            proj = a + t * ab
            dist = np.linalg.norm(pt - proj)
            if dist < best_dist:
                best_dist = dist
                best_s = self._stations[i] + t * seg_len
        return float(best_s)

    def sample_stations(
        self,
        interval: float,
        extra_stations: Optional[list[float]] = None
    ) -> list[float]:
        """
        按固定间距生成桩号列表（含起终点 + 额外桩号）。

        Parameters
        ----------
        interval : 桩号间距（m）
        extra_stations : 额外必须包含的桩号
        """
        start = self.start_station
        end = self.end_station
        stations = list(np.arange(start, end + 1e-9, interval))
        if abs(stations[-1] - end) > 1e-6:
            stations.append(end)
        if extra_stations:
            stations.extend(extra_stations)
        return sorted(set(round(s, 6) for s in stations
                          if start - 1e-6 <= s <= end + 1e-6))
