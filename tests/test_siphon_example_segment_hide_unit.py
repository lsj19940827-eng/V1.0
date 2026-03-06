"""
测试倒虹吸示例数据状态下结构段隐藏功能

验证点：
1. 示例状态下，_get_all_display_segments() 应过滤纵断面段
2. 示例状态下，结构段表格不显示纵断面段
3. 导入DXF后，纵断面段正常显示
4. 用户编辑操作不应清除示例标志
"""
import sys
import os
from pathlib import Path

# 设置UTF-8编码
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtWidgets import QApplication, QWidget
import 渠系断面设计.siphon.panel as siphon_panel_mod

# 导入需要的类型
try:
    from siphon_models import SegmentDirection
except ImportError:
    # 如果导入失败，从面板模块获取
    SegmentDirection = siphon_panel_mod.SegmentDirection


class _FakeWebEngineView(QWidget):
    """测试替身：避免无头环境下 QWebEngineView 崩溃。"""
    def setHtml(self, *_args, **_kwargs):
        return None


# 替换 QWebEngineView
siphon_panel_mod.QWebEngineView = _FakeWebEngineView


def test_example_segments_hidden():
    """测试示例状态下纵断面段被隐藏"""
    app = QApplication.instance() or QApplication(sys.argv)
    panel = siphon_panel_mod.SiphonPanel()

    # 添加示例纵断面数据
    panel._add_example_longitudinal()

    # 验证示例标志已设置
    assert panel._longitudinal_is_example == True, "示例标志应为True"

    # 验证纵断面段已生成
    long_segs = [s for s in panel.segments if s.direction != SegmentDirection.COMMON]
    assert len(long_segs) > 0, "应该有纵断面段"

    # 验证 _get_all_display_segments() 过滤了纵断面段
    display_segs = panel._get_all_display_segments()
    display_long = [s for s, source in display_segs if source == 'longitudinal']
    assert len(display_long) == 0, "示例状态下不应显示纵断面段"

    # 验证只显示通用构件
    display_common = [s for s, source in display_segs if source == 'common']
    assert len(display_common) > 0, "应该显示通用构件"

    print("✓ 示例状态下纵断面段被正确隐藏")


def test_example_flag_persistence():
    """测试示例标志在各种操作下保持不变"""
    app = QApplication.instance() or QApplication(sys.argv)
    panel = siphon_panel_mod.SiphonPanel()

    # 添加示例纵断面数据
    panel._add_example_longitudinal()
    assert panel._longitudinal_is_example == True

    # 模拟节点表编辑（触发同步）
    panel._sync_nodes_to_segments()
    assert panel._longitudinal_is_example == True, "同步操作不应清除示例标志"

    # 模拟手动编辑节点表
    if panel.long_table.rowCount() > 0:
        item = panel.long_table.item(0, 0)
        if item:
            original_text = item.text()
            item.setText("999.99")
            panel._on_long_table_edited()
            assert panel._longitudinal_is_example == True, "编辑节点表不应清除示例标志"
            item.setText(original_text)

    print("✓ 示例标志在各种操作下保持不变")


def test_segments_visible_after_dxf_import():
    """测试导入DXF后纵断面段正常显示"""
    app = QApplication.instance() or QApplication(sys.argv)
    panel = siphon_panel_mod.SiphonPanel()

    # 添加示例数据
    panel._add_example_longitudinal()
    assert panel._longitudinal_is_example == True

    # 模拟导入DXF（清除示例标志）
    panel._longitudinal_is_example = False

    # 验证纵断面段现在可见
    display_segs = panel._get_all_display_segments()
    display_long = [s for s, source in display_segs if source == 'longitudinal']
    assert len(display_long) > 0, "导入DXF后应显示纵断面段"

    print("✓ 导入DXF后纵断面段正常显示")


def test_table_display_consistency():
    """测试表格显示与数据状态一致"""
    app = QApplication.instance() or QApplication(sys.argv)
    panel = siphon_panel_mod.SiphonPanel()

    # 添加示例数据
    panel._add_example_longitudinal()
    panel._refresh_seg_table()

    # 统计表格中的纵断面行
    long_rows = 0
    for row in range(panel.seg_table.rowCount()):
        cat_item = panel.seg_table.item(row, 0)
        if cat_item and "纵断面" in cat_item.text():
            long_rows += 1

    assert long_rows == 0, "示例状态下表格不应显示纵断面行"

    # 验证纵断面段数据确实存在（只是被隐藏了）
    long_segs = [s for s in panel.segments if s.direction != SegmentDirection.COMMON]
    assert len(long_segs) > 0, "纵断面段数据应该存在"

    print("✓ 表格显示与数据状态一致")


if __name__ == '__main__':
    test_example_segments_hidden()
    test_example_flag_persistence()
    test_segments_visible_after_dxf_import()
    test_table_display_consistency()
    print("\n所有测试通过！")
