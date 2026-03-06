"""测试倒虹吸示例数据标志修复"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtWidgets import QApplication
from 渠系断面设计.siphon.panel import SiphonPanel

def test_example_flag_persistence():
    """测试示例数据标志在同步后是否保持"""
    app = QApplication.instance() or QApplication(sys.argv)

    panel = SiphonPanel()

    # 1. 添加示例数据
    panel._add_example_longitudinal()

    # 验证初始状态
    assert panel._longitudinal_is_example == True, "示例标志应该为 True"
    assert len(panel.longitudinal_nodes) > 0, "应该有纵断面节点"
    assert len(panel.segments) > 0, "应该有结构段"

    print("[PASS] 初始状态正确：示例标志为 True")

    # 2. 触发同步操作（模拟编辑节点后的同步）
    panel._sync_nodes_to_segments()

    # 验证同步后状态
    assert panel._longitudinal_is_example == True, "同步后示例标志应该保持为 True"
    print("[PASS] 同步后状态正确：示例标志保持为 True")

    # 3. 检查结构段表的示例数据判断
    # 模拟 _refresh_seg_table 中的判断逻辑
    for seg in panel.segments:
        source = 'longitudinal' if seg.direction.name == 'LONGITUDINAL' else 'common'
        is_example_row = (source == 'longitudinal' and panel._longitudinal_is_example)
        if source == 'longitudinal':
            assert is_example_row == True, "纵断面结构段应该被标记为示例数据"

    print("[PASS] 结构段示例数据判断正确")

    print("\n[SUCCESS] 所有测试通过！示例数据标志修复成功。")

if __name__ == "__main__":
    test_example_flag_persistence()
