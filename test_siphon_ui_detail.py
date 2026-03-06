"""详细测试倒虹吸示例数据标志和UI显示"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtWidgets import QApplication
from 渠系断面设计.siphon.panel import SiphonPanel

def test_example_flag_and_ui():
    """测试示例数据标志和UI显示"""
    app = QApplication.instance() or QApplication(sys.argv)

    panel = SiphonPanel()

    print("=== 测试1: 初始状态（无数据） ===")
    print(f"_longitudinal_is_example = {panel._longitudinal_is_example}")
    print(f"longitudinal_nodes count = {len(panel.longitudinal_nodes)}")
    print(f"segments count = {len(panel.segments)}")

    # 添加示例数据
    print("\n=== 测试2: 添加示例数据后 ===")
    panel._add_example_longitudinal()

    print(f"_longitudinal_is_example = {panel._longitudinal_is_example}")
    print(f"longitudinal_nodes count = {len(panel.longitudinal_nodes)}")
    print(f"segments count = {len(panel.segments)}")

    # 检查提示标签可见性
    if hasattr(panel, 'seg_hint_label'):
        print(f"seg_hint_label.isVisible() = {panel.seg_hint_label.isVisible()}")

    if hasattr(panel, 'long_hint_label'):
        print(f"long_hint_label.isVisible() = {panel.long_hint_label.isVisible()}")

    # 检查结构段的示例标记
    print("\n=== 测试3: 检查结构段示例标记 ===")
    display_segments = panel._get_all_display_segments()
    for i, (seg, source) in enumerate(display_segments):
        is_example = (source == 'longitudinal' and panel._longitudinal_is_example)
        print(f"Segment {i}: source={source}, is_example={is_example}, type={seg.segment_type.value}")

    # 手动触发同步
    print("\n=== 测试4: 手动触发同步后 ===")
    panel._sync_nodes_to_segments()

    print(f"_longitudinal_is_example = {panel._longitudinal_is_example}")

    if hasattr(panel, 'seg_hint_label'):
        print(f"seg_hint_label.isVisible() = {panel.seg_hint_label.isVisible()}")

    # 最终验证
    if panel._longitudinal_is_example:
        print("\n[SUCCESS] 示例标志保持正确")
    else:
        print("\n[FAILED] 示例标志被错误清除")

if __name__ == "__main__":
    test_example_flag_and_ui()
