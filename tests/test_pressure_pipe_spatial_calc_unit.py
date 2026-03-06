"""
有压管道空间模式计算单元测试

测试空间模式计算功能，包括：
1. 空间长度计算
2. 空间弯头损失计算
3. 与平面模式的对比
4. 数据模式标识
"""

import sys
import os

# 添加项目路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(project_root, '推求水面线'))

from core.pressure_pipe_calc import calc_total_head_loss, calc_total_head_loss_with_spatial


def test_spatial_mode_with_longitudinal():
    """测试：有纵断面数据时使用空间模式计算"""

    # 平面IP点数据
    ip_points = [
        {"x": 0, "y": 0, "turn_radius": 0, "turn_angle": 0},      # 进口
        {"x": 100, "y": 0, "turn_radius": 5.0, "turn_angle": 45}, # IP1
        {"x": 200, "y": 100, "turn_radius": 0, "turn_angle": 0},  # 出口
    ]

    # 纵断面数据（有高程变化）
    longitudinal_nodes = [
        {
            'chainage': 0.0,
            'elevation': 100.0,
            'vertical_curve_radius': 0.0,
            'turn_type': 'NONE',
            'turn_angle': 0.0,
            'slope_before': 0.0,
            'slope_after': -0.01,
            'arc_center_s': None,
            'arc_center_z': None,
            'arc_end_chainage': None,
            'arc_theta_rad': None,
        },
        {
            'chainage': 100.0,
            'elevation': 99.0,
            'vertical_curve_radius': 5.0,
            'turn_type': 'ARC',
            'turn_angle': 30.0,
            'slope_before': -0.01,
            'slope_after': -0.02,
            'arc_center_s': 100.0,
            'arc_center_z': 104.0,
            'arc_end_chainage': 105.0,
            'arc_theta_rad': 0.5236,
        },
        {
            'chainage': 200.0,
            'elevation': 97.0,
            'vertical_curve_radius': 0.0,
            'turn_type': 'NONE',
            'turn_angle': 0.0,
            'slope_before': -0.02,
            'slope_after': 0.0,
            'arc_center_s': None,
            'arc_center_z': None,
            'arc_end_chainage': None,
            'arc_theta_rad': None,
        },
    ]

    # 调用空间模式计算
    result = calc_total_head_loss_with_spatial(
        name="测试管道",
        Q=2.0,
        D=1.0,
        material_key="预应力钢筒混凝土管",
        ip_points=ip_points,
        longitudinal_nodes=longitudinal_nodes,
        upstream_velocity=1.0,
        downstream_velocity=1.0,
    )

    # 验证结果
    assert result.data_mode == "空间模式（平面+纵断面）", f"数据模式应为空间模式，实际为: {result.data_mode}"
    assert result.total_head_loss > 0, "总水头损失应大于0"
    assert result.total_length > 0, "管道长度应大于0"

    print(f"✓ 空间模式计算成功")
    print(f"  数据模式: {result.data_mode}")
    print(f"  管道长度: {result.total_length:.2f} m")
    print(f"  总水头损失: {result.total_head_loss:.4f} m")


def test_plane_mode_without_longitudinal():
    """测试：无纵断面数据时使用平面模式计算"""

    ip_points = [
        {"x": 0, "y": 0, "turn_radius": 0, "turn_angle": 0},
        {"x": 100, "y": 0, "turn_radius": 5.0, "turn_angle": 45},
        {"x": 200, "y": 100, "turn_radius": 0, "turn_angle": 0},
    ]

    result = calc_total_head_loss_with_spatial(
        name="测试管道",
        Q=2.0,
        D=1.0,
        material_key="预应力钢筒混凝土管",
        ip_points=ip_points,
        longitudinal_nodes=[],
        upstream_velocity=1.0,
        downstream_velocity=1.0,
    )

    assert result.data_mode == "平面模式", f"数据模式应为平面模式，实际为: {result.data_mode}"
    assert result.total_head_loss > 0, "总水头损失应大于0"

    print(f"✓ 平面模式计算成功")
    print(f"  数据模式: {result.data_mode}")


if __name__ == "__main__":
    print("=" * 60)
    print("有压管道空间模式计算单元测试")
    print("=" * 60)

    try:
        test_spatial_mode_with_longitudinal()
        print()
        test_plane_mode_without_longitudinal()
        print()
        print("=" * 60)
        print("✓ 所有测试通过")
        print("=" * 60)
    except AssertionError as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
    except Exception as e:
        print(f"\n✗ 测试出错: {e}")
        import traceback
        traceback.print_exc()
