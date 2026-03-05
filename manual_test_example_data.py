# -*- coding: utf-8 -*-
"""
手动测试倒虹吸示例数据增强功能

运行此脚本后，手动验证以下内容：
1. 纵断面节点表显示13个节点（灰色斜体）
2. 结构段表显示通用构件 + 12个纵断面段（纵断面段为灰色斜体）
3. 两个表格上方都显示黄色提示标签
4. 点击"导入纵断面DXF"时弹出确认对话框
5. 编辑任意节点后，灰色斜体和提示标签消失
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication

def main():
    app = QApplication(sys.argv)

    from 渠系断面设计.siphon.panel import SiphonPanel

    # 创建倒虹吸面板
    panel = SiphonPanel(show_case_management=False)
    panel.setWindowTitle("倒虹吸示例数据测试")
    panel.resize(1400, 900)
    panel.show()

    # 打印验证信息
    print("\n" + "=" * 60)
    print("倒虹吸示例数据增强 - 手动测试")
    print("=" * 60)
    print(f"纵断面节点数量: {len(panel.longitudinal_nodes)}")
    print(f"示例标志: {panel._longitudinal_is_example}")

    from 渠系断面设计.siphon.siphon_models import SegmentDirection
    long_segs = [s for s in panel.segments if s.direction != SegmentDirection.COMMON]
    print(f"纵断面结构段数量: {len(long_segs)}")

    if hasattr(panel, 'long_hint_label'):
        print(f"纵断面提示标签可见: {panel.long_hint_label.isVisible()}")

    if hasattr(panel, 'seg_hint_label'):
        print(f"结构段提示标签可见: {panel.seg_hint_label.isVisible()}")

    print("\n请手动验证以下内容：")
    print("1. 纵断面节点表显示13个节点（灰色斜体）")
    print("2. 结构段表显示通用构件 + 12个纵断面段（纵断面段为灰色斜体）")
    print("3. 两个表格上方都显示黄色提示标签")
    print("4. 点击'导入纵断面DXF'时弹出确认对话框")
    print("5. 编辑任意节点后，灰色斜体和提示标签消失")
    print("=" * 60 + "\n")

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
