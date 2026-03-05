#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试倒虹吸面板的示例数据加载

验证从DXF解析的示例数据是否能正常加载和显示
"""

import sys
import os

# 添加路径
_pkg_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _pkg_root)
sys.path.insert(0, os.path.join(_pkg_root, '倒虹吸水力计算系统'))

from PySide6.QtWidgets import QApplication
from 渠系断面设计.siphon.panel import SiphonPanel

def test_example_data():
    """测试示例数据加载"""
    print("=" * 60)
    print("测试倒虹吸面板示例数据加载")
    print("=" * 60)

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    # 创建面板
    panel = SiphonPanel()

    # 验证示例数据
    print(f"\n[OK] 面板创建成功")
    print(f"[OK] 纵断面节点数量: {len(panel.longitudinal_nodes)}")
    print(f"[OK] 是否为示例数据: {panel._longitudinal_is_example}")
    print(f"[OK] 结构段数量: {len(panel.segments)}")

    # 显示节点详情
    print("\n纵断面节点详情:")
    for i, node in enumerate(panel.longitudinal_nodes):
        info = f"  [{i:2d}] 桩号={node.chainage:8.2f}m, 高程={node.elevation:8.2f}m"
        if hasattr(node, 'turn_type') and node.turn_type:
            from siphon_models import TurnType
            if node.turn_type != TurnType.NONE:
                info += f", 类型={node.turn_type.name}"
                if node.vertical_curve_radius:
                    info += f", R={node.vertical_curve_radius:.2f}m"
                if node.turn_angle:
                    info += f", 转角={node.turn_angle:.2f}°"
        print(info)

    # 显示结构段详情
    print("\n结构段详情:")
    for i, seg in enumerate(panel.segments):
        info = f"  [{i:2d}] {seg.segment_type.name:12s}"
        if seg.length:
            info += f", L={seg.length:8.2f}m"
        if seg.radius:
            info += f", R={seg.radius:.2f}m"
        if seg.angle:
            info += f", α={seg.angle:.2f}°"
        info += f", 方向={seg.direction.name}"
        print(info)

    # 验证数据完整性
    print("\n数据完整性检查:")
    checks = [
        (len(panel.longitudinal_nodes) == 13, "节点数量正确 (13个)"),
        (panel._longitudinal_is_example == True, "示例标志正确"),
        (len(panel.segments) > 0, "结构段已生成"),
        (panel.longitudinal_nodes[0].chainage < 0.01, "起点桩号已归零"),
        (panel.longitudinal_nodes[-1].chainage > 240, "终点桩号合理"),
    ]

    all_passed = True
    for passed, desc in checks:
        status = "[OK]" if passed else "[FAIL]"
        print(f"  {status} {desc}")
        if not passed:
            all_passed = False

    if all_passed:
        print("\n" + "=" * 60)
        print("[OK] 所有测试通过！示例数据加载正常")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("[FAIL] 部分测试失败，请检查")
        print("=" * 60)
        return False

    # 显示面板（可选）
    print("\n提示：关闭窗口以结束测试")
    panel.show()
    app.exec()

    return True

if __name__ == "__main__":
    try:
        success = test_example_data()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n[FAIL] 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
