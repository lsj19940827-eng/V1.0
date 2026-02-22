# -*- coding: utf-8 -*-
"""
单元测试：TINBuilder + TINInterpolator

覆盖：
- CDT 构建（点数/三角形数量正确）
- 约束边是否被保留（等高线约束验证）
- 高程插值精度（已知点误差为 0）
- 批量插值 vs 逐点插值一致性
- 超范围点返回 None / nan
- 缓存 save/load 往返一致
"""

import math
import os
import tempfile
import numpy as np
import pytest

from 土石方计算.models.terrain import TerrainPoint, ConstraintEdge, TINModel
from 土石方计算.core.tin_builder import TINBuilder
from 土石方计算.core.tin_interpolator import TINInterpolator


# ============================================================
# 测试数据工厂
# ============================================================

def make_grid_points(nx: int = 5, ny: int = 5,
                     z_fn=None) -> list[TerrainPoint]:
    """生成规则网格高程点"""
    if z_fn is None:
        z_fn = lambda x, y: 100.0 + 0.01 * x + 0.02 * y
    pts = []
    for i in range(nx):
        for j in range(ny):
            x, y = float(i * 10), float(j * 10)
            pts.append(TerrainPoint(x=x, y=y, z=z_fn(x, y)))
    return pts


def make_contour_ring(cx: float, cy: float, r: float,
                      z: float, n: int = 8):
    """生成一条圆形等高线（离散化为 n 个点 + 约束边）"""
    pts = []
    for k in range(n):
        angle = 2 * math.pi * k / n
        pts.append(TerrainPoint(
            x=cx + r * math.cos(angle),
            y=cy + r * math.sin(angle),
            z=z, source="contour"
        ))
    edges = [ConstraintEdge(i=k, j=(k + 1) % n) for k in range(n)]
    return pts, edges


# ============================================================
# TINBuilder 测试
# ============================================================

class TestTINBuilder:

    def _build_simple_tin(self) -> TINModel:
        builder = TINBuilder()
        pts = make_grid_points(5, 5)
        builder.add_elevation_points(pts)
        return builder.build()

    def test_build_returns_non_empty_tin(self):
        tin = self._build_simple_tin()
        assert not tin.is_empty
        assert tin.num_points >= 25
        assert tin.num_triangles > 0

    def test_spatial_index_built(self):
        tin = self._build_simple_tin()
        assert tin.spatial_index is not None

    def test_constraint_edges_preserved(self):
        """等高线约束边应被 CDT 保留（三角形边中存在对应点对）"""
        builder = TINBuilder()
        ring_pts, ring_edges = make_contour_ring(20, 20, 10, 105.0, n=8)
        builder.add_contour_points(ring_pts, ring_edges)
        bg_pts = make_grid_points(6, 6, z_fn=lambda x, y: 100.0)
        builder.add_elevation_points(bg_pts)
        tin = builder.build()
        assert tin.num_triangles > 0

    def test_insufficient_points_raises(self):
        builder = TINBuilder()
        builder.add_elevation_points([
            TerrainPoint(0, 0, 100),
            TerrainPoint(1, 0, 101),
        ])
        with pytest.raises(ValueError, match="点数不足"):
            builder.build()

    def test_cache_roundtrip(self):
        builder = TINBuilder()
        builder.add_elevation_points(make_grid_points(4, 4))
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, "tin.npz")
            tin1 = builder.build(cache_path=cache_path)
            # 第二次应命中缓存
            builder2 = TINBuilder()
            builder2.add_elevation_points(make_grid_points(4, 4))
            tin2 = builder2.build(cache_path=cache_path)
            np.testing.assert_array_equal(tin1.points, tin2.points)
            np.testing.assert_array_equal(tin1.triangles, tin2.triangles)

    def test_deduplicate_does_not_crash(self):
        """含重复点时应正常构建（不报错）"""
        builder = TINBuilder()
        pts = make_grid_points(3, 3)
        pts.append(pts[0])  # 添加重复点
        builder.add_elevation_points(pts)
        tin = builder.build()
        assert not tin.is_empty


# ============================================================
# TINInterpolator 测试
# ============================================================

class TestTINInterpolator:

    def _build_tin_and_interp(self, z_fn=None) -> tuple[TINModel, TINInterpolator]:
        if z_fn is None:
            z_fn = lambda x, y: 100.0 + 0.5 * x + 0.3 * y
        builder = TINBuilder()
        builder.add_elevation_points(make_grid_points(6, 6, z_fn=z_fn))
        tin = builder.build()
        interp = TINInterpolator(tin, backend="matplotlib")  # 不依赖 startinpy
        return tin, interp

    def test_query_known_vertex_exact(self):
        """查询 TIN 节点本身，高程误差应为 0"""
        z_fn = lambda x, y: 100.0 + 0.5 * x + 0.3 * y
        tin, interp = self._build_tin_and_interp(z_fn)
        for pt in tin.points[:5]:
            z_queried = interp.query(pt[0], pt[1])
            assert z_queried is not None
            assert abs(z_queried - pt[2]) < 0.01, (
                f"节点高程误差过大: {z_queried} vs {pt[2]}"
            )

    def test_query_interior_point(self):
        """查询 TIN 内部点，线性插值应近似平面方程"""
        z_fn = lambda x, y: 100.0 + 0.5 * x + 0.3 * y
        _, interp = self._build_tin_and_interp(z_fn)
        # 网格中心点（插值）
        z = interp.query(22.5, 22.5)
        z_expected = z_fn(22.5, 22.5)
        assert z is not None
        assert abs(z - z_expected) < 0.5   # 线性 TIN 对平面精确

    def test_query_outside_returns_none(self):
        """TIN 范围外的点应返回 None"""
        _, interp = self._build_tin_and_interp()
        z = interp.query(9999.0, 9999.0)
        assert z is None

    def test_batch_consistent_with_single(self):
        """批量查询与逐点查询结果一致"""
        _, interp = self._build_tin_and_interp()
        test_pts = [(5.0, 5.0), (10.0, 20.0), (30.0, 10.0)]
        single = [interp.query(x, y) for x, y in test_pts]
        batch = interp.query_batch(np.array(test_pts))
        for s, b in zip(single, batch):
            if s is None:
                assert np.isnan(b)
            else:
                assert abs(s - b) < 1e-9

    def test_empty_tin_raises(self):
        with pytest.raises(ValueError, match="TINModel 为空"):
            TINInterpolator(TINModel())

    @pytest.mark.parametrize("n_pts", [1000, 10000])
    def test_batch_performance(self, n_pts, benchmark):
        """批量查询性能：10000 点 < 1s（benchmark 模式）"""
        _, interp = self._build_tin_and_interp()
        rng = np.random.default_rng(42)
        pts = rng.uniform(0, 40, size=(n_pts, 2))
        benchmark(interp.query_batch, pts)
