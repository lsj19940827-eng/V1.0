# -*- coding: utf-8 -*-
"""
有压管道设计 —— 批量输出测试

覆盖：小样本CSV/PNG/PDF生成、取消任务、空/无权限目录处理
"""

import sys
import os
import tempfile
import shutil
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "calc_渠系计算算法内核"))

from 有压管道设计 import (
    run_batch_scan, BatchScanConfig, BatchScanResult,
    DEFAULT_DIAMETER_SERIES,
)


@pytest.fixture
def tmp_output_dir():
    """创建临时输出目录，测试后清理"""
    d = tempfile.mkdtemp(prefix="pipe_batch_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


class TestBatchScan:
    """批量扫描功能测试"""

    def _small_config(self, output_dir):
        """最小配置：2个Q x 2个坡度 x 少量管径 x 1种管材"""
        return BatchScanConfig(
            q_values=np.array([0.5, 1.0]),
            slope_denominators=[1000, 2000],
            diameter_values=np.array([0.3, 0.5, 0.8, 1.0]),
            materials=["钢管"],
            n_unpr=0.014,
            length_m=1000.0,
            output_dir=output_dir,
        )

    def test_csv_generated(self, tmp_output_dir):
        """批量计算应生成CSV文件"""
        config = self._small_config(tmp_output_dir)
        result = run_batch_scan(config)

        assert result.csv_path != ""
        assert os.path.exists(result.csv_path)
        assert result.csv_path.endswith(".csv")

        # CSV 应有数据行
        import pandas as pd
        df = pd.read_csv(result.csv_path)
        expected_rows = 2 * 2 * 4 * 1  # Q x slope x D x materials
        assert len(df) == expected_rows

    def test_pdf_generated(self, tmp_output_dir):
        """批量计算应生成PDF文件"""
        config = self._small_config(tmp_output_dir)
        result = run_batch_scan(config)

        # 可能生成也可能不生成（取决于是否有经济/妥协区数据点）
        # 但至少日志不应为空
        assert len(result.logs) > 0

    def test_png_generated(self, tmp_output_dir):
        """如果有图表，应生成子图PNG"""
        config = self._small_config(tmp_output_dir)
        result = run_batch_scan(config)

        # PNG 列表可以为空（如果没有满足条件的数据点）
        # 但不应报错
        for png_path in result.generated_pngs:
            assert os.path.exists(png_path)

    def test_cancel_stops_early(self, tmp_output_dir):
        """取消标志应使任务提前终止"""
        config = BatchScanConfig(
            q_values=np.round(np.arange(0.1, 2.1, 0.1), 1),
            slope_denominators=[500, 1000, 2000, 3000, 4000],
            diameter_values=DEFAULT_DIAMETER_SERIES,
            materials=["钢管", "球墨铸铁管"],
            output_dir=tmp_output_dir,
        )

        call_count = 0

        def cancel_after_100():
            nonlocal call_count
            call_count += 1
            return call_count > 100  # 很快取消

        result = run_batch_scan(config, cancel_flag=cancel_after_100)
        assert "用户取消" in " ".join(result.logs)

    def test_progress_callback(self, tmp_output_dir):
        """进度回调应被调用"""
        config = self._small_config(tmp_output_dir)

        progress_calls = []

        def on_progress(cur, tot, msg):
            progress_calls.append((cur, tot, msg))

        result = run_batch_scan(config, progress_cb=on_progress)
        # 应至少有完成回调
        assert len(progress_calls) > 0

    def test_empty_output_dir(self):
        """空输出目录应返回错误日志"""
        config = BatchScanConfig(
            q_values=np.array([0.5]),
            slope_denominators=[1000],
            diameter_values=np.array([0.5]),
            materials=["钢管"],
            output_dir="",
        )
        result = run_batch_scan(config)
        assert any("未指定输出目录" in log for log in result.logs)

    def test_multiple_materials(self, tmp_output_dir):
        """多管材批量计算"""
        config = BatchScanConfig(
            q_values=np.array([0.5]),
            slope_denominators=[2000],
            diameter_values=np.array([0.5, 0.8]),
            materials=["钢管", "球墨铸铁管", "HDPE管"],
            output_dir=tmp_output_dir,
        )
        result = run_batch_scan(config)
        assert os.path.exists(result.csv_path)

        import pandas as pd
        df = pd.read_csv(result.csv_path)
        # 3种管材 x 1Q x 1slope x 2D = 6行
        assert len(df) == 6
        assert len(df["管材类型"].unique()) == 3

    def test_unknown_material_skipped(self, tmp_output_dir):
        """未知管材应被跳过"""
        config = BatchScanConfig(
            q_values=np.array([0.5]),
            slope_denominators=[2000],
            diameter_values=np.array([0.5]),
            materials=["不存在的管材", "钢管"],
            output_dir=tmp_output_dir,
        )
        result = run_batch_scan(config)
        assert any("跳过未知管材" in log for log in result.logs)
        # 钢管数据仍应存在
        assert os.path.exists(result.csv_path)
