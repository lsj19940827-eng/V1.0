# -*- coding: utf-8 -*-
"""跨模块真源、旧工程迁移及计算/导出分离的行为回归。"""

import importlib
import tempfile
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from calc_渠系计算算法内核 import 有压管道设计 as kernel
from 推求水面线.models.data_models import ChannelNode
from 推求水面线.models.pressure_pipe_override import (
    get_pressure_pipe_window_override,
    set_pressure_pipe_window_override,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def tmp_path():
    """使用仓库内受控临时目录，避开当前 Windows 用户临时目录权限限制。"""
    with tempfile.TemporaryDirectory(prefix=".pytest_domain_arch_", dir=ROOT) as location:
        path = Path(location).resolve()
        assert path.parent == ROOT.resolve()
        yield path


def _config(**changes):
    """小样本覆盖两种管材及既有显式水力内径语义。"""
    values = dict(q_values=np.array([0.5]), slope_denominators=[1000],
                  diameter_values=np.array([0.8]), materials=["钢管", "球墨铸铁管"])
    values.update(changes)
    return kernel.BatchScanConfig(**values)


def test_calculation_does_not_require_output_directory_or_export_libraries():
    """独立进程验证计算不创建目录、不加载表格/绘图依赖。"""
    script = """
import sys
from calc_渠系计算算法内核.有压管道设计 import BatchScanConfig, calculate_batch
snapshot = calculate_batch(BatchScanConfig(q_values=[0.5], slope_denominators=[],
    diameter_values=[0.8], materials=['钢管'], output_dir=''))
assert len(snapshot.rows) == 1
assert not snapshot.cancelled
assert 'pandas' not in sys.modules
assert 'matplotlib' not in sys.modules
assert 'seaborn' not in sys.modules
"""
    result = subprocess.run([sys.executable, "-B", "-c", script], cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_same_snapshot_reexports_without_solver_or_catalog(monkeypatch, tmp_path):
    """目录和输入变更后仍从原快照重导出完全相同的 CSV。"""
    config = _config()
    snapshot = kernel.calculate_batch(config)
    config.q_values[0] = 99.0
    config.materials.clear()

    def forbidden(*args, **kwargs):
        raise AssertionError("重导出不得调用数值求解器或查询产品目录")

    for name in ("evaluate_single_diameter", "get_pe_pipe_specs", "get_pipe_product_specs", "compare_flows"):
        monkeypatch.setattr(kernel, name, forbidden)
    options = dict(output_pdf_charts=False, output_subplot_png=False, output_merged_pdf=False)
    first = kernel.export_batch(snapshot, kernel.BatchExportOptions(str(tmp_path / "first"), **options))
    second = kernel.export_batch(snapshot, kernel.BatchExportOptions(str(tmp_path / "second"), **options))
    assert Path(first.csv_path).read_bytes() == Path(second.csv_path).read_bytes()
    assert Path(first.comparison_csv_path).read_bytes() == Path(second.comparison_csv_path).read_bytes()
    assert [row["Q_target (m³/s)"] for row in snapshot.rows] == [0.5, 0.5]
    assert len(snapshot.comparison_rows) == 4
    assert not first.cancelled and not second.cancelled


def test_cancelled_snapshot_cannot_export_partial_calculation(tmp_path):
    """取消状态随快照传递，导出不会把半成品保存为完整成果。"""
    count = 0

    def cancel():
        nonlocal count
        count += 1
        return count > 1

    snapshot = kernel.calculate_batch(_config(), cancel_flag=cancel)
    assert snapshot.cancelled and len(snapshot.rows) == 1
    destination = tmp_path / "cancelled"
    result = kernel.export_batch(snapshot, kernel.BatchExportOptions(str(destination)))
    assert result.cancelled
    assert not destination.exists()
    assert not result.csv_path


def test_override_has_single_runtime_source_and_legacy_file_mirror():
    """旧字段只在载入时迁移、导出时生成，运行期清除不会被副本复活。"""
    legacy = {"section_params": {"B": 2.0, "pressure_pipe_window_override":
              {"enabled": True, "identity": "old", "total_head_loss": "0.25"}}}
    node = ChannelNode.from_project_dict(legacy)
    assert get_pressure_pipe_window_override(node)["total_head_loss"] == 0.25
    assert "pressure_pipe_window_override" not in node.section_params
    assert "pressure_pipe_window_override" in legacy["section_params"]
    node.profile_row_id = "stable-row"
    saved = node.to_project_dict()
    assert saved["section_params"]["pressure_pipe_window_override"] == saved["pressure_pipe_window_override"]
    restored = ChannelNode.from_project_dict(saved)
    assert restored.profile_row_id == "stable-row"
    assert "pressure_pipe_window_override" not in restored.section_params
    set_pressure_pipe_window_override(restored, None)
    assert get_pressure_pipe_window_override(restored) == {}
    assert "pressure_pipe_window_override" not in restored.to_project_dict()["section_params"]


def test_explicit_override_wins_over_legacy_copy_and_is_detached():
    """双字段旧文件优先独立字段，返回字典与保存镜像都不能反写运行状态。"""
    node = ChannelNode(section_params={"pressure_pipe_window_override": {"enabled": True, "identity": "old"}},
                       pressure_pipe_window_override={"enabled": True, "identity": "current",
                                                      "friction_details": {"length": 5.0}})
    value = get_pressure_pipe_window_override(node)
    assert value["identity"] == "current"
    value["friction_details"]["length"] = 99.0
    saved = node.to_project_dict()
    saved["section_params"]["pressure_pipe_window_override"]["identity"] = "changed"
    assert get_pressure_pipe_window_override(node)["friction_details"]["length"] == 5.0
    assert get_pressure_pipe_window_override(node)["identity"] == "current"


@pytest.mark.parametrize("old_first", [False, True])
@pytest.mark.parametrize("frozen_paths", [False, True])
def test_siphon_qualified_and_legacy_imports_share_type_identity(old_first, frozen_paths):
    """两种加载顺序下枚举、模型和系数服务必须来自同一模块对象。"""
    script = f"""
import importlib, sys
from pathlib import Path
sys.path.insert(0, str(Path('倒虹吸水力计算系统').resolve()))
old_first = {old_first!r}
names = ('arc_geometry', 'siphon_models', 'siphon_coefficients')
first_modules = {{name: importlib.import_module(name if old_first else '倒虹吸水力计算系统.' + name)
                 for name in names}}
if {frozen_paths!r}:
    sys.frozen = True
    sys._MEIPASS = str(Path('_test_bundle').resolve())
    for name, module in first_modules.items():
        module.__file__ = str(Path(sys._MEIPASS) / (name + '.py'))
for name in names:
    second = '倒虹吸水力计算系统.' + name if old_first else name
    assert first_modules[name] is importlib.import_module(second)
"""
    result = subprocess.run([sys.executable, "-B", "-c", script], cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_missing_coefficients_fail_instead_of_changing_calculation(monkeypatch):
    """大弯径比必须查完整表，必要服务缺失不能静默换成截短表。"""
    module = importlib.import_module("推求水面线.core.pressure_pipe_calc")
    assert module.calc_bend_local_loss(1.0, 11.0, 90.0, 2.0)[0] == pytest.approx(0.23)
    monkeypatch.setattr(module, "CoefficientService", None)
    with pytest.raises(RuntimeError, match="系数服务不可用"):
        module.calc_bend_local_loss(1.0, 11.0, 90.0, 2.0)
    with pytest.raises(RuntimeError, match="系数服务不可用"):
        module.calc_fold_local_loss(45.0, 2.0)


def test_water_profile_geometry_loads_without_frontend():
    """独立进程阻止任何前端导入，表3仍可计算平底圆形几何。"""
    script = """
import sys, importlib.abc
class BlockFrontend(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('app_渠系计算前端'):
            raise AssertionError('领域计算不应导入前端: ' + fullname)
sys.meta_path.insert(0, BlockFrontend())
from 推求水面线.core.hydraulic_calc import HydraulicCalculator
from 推求水面线.models.data_models import ProjectSettings
calculator = HydraulicCalculator(ProjectSettings())
assert calculator._flat_bottom_circle_area(2.0, 1.0, 0.5) > 0
"""
    result = subprocess.run([sys.executable, "-B", "-c", script], cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_build_collection_includes_new_domain_boundaries():
    """冻结构建显式收集共享真源与快照导出，防止源码通过而打包遗漏。"""
    from tools.build import get_hidden_imports, get_verify_import_groups
    expected = {
        "calc_渠系计算算法内核.flat_bottom_circle",
        "calc_渠系计算算法内核.pressure_pipe_batch_models",
        "calc_渠系计算算法内核.pressure_pipe_batch_export",
        "倒虹吸水力计算系统.siphon_models",
        "倒虹吸水力计算系统.siphon_coefficients",
        "推求水面线.models.pressure_pipe_override",
        "推求水面线.models.profile_state",
        "推求水面线.models.profile_node_codec",
        "app_渠系计算前端.task_runner",
        "app_渠系计算前端.batch.schema",
        "app_渠系计算前端.batch.engines",
        "app_渠系计算前端.batch.calculation_service",
        "app_渠系计算前端.water_profile.table_state_adapter",
    }
    assert expected <= set(get_hidden_imports())
    assert expected <= {name for group in get_verify_import_groups().values() for name in group}
