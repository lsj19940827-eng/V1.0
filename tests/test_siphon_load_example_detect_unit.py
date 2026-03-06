# -*- coding: utf-8 -*-
"""测试加载旧数据时自动检测示例数据"""
import sys
import os
from pathlib import Path

if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtWidgets import QApplication, QWidget
import 渠系断面设计.siphon.panel as siphon_panel_mod

try:
    from siphon_models import SegmentDirection
except ImportError:
    SegmentDirection = siphon_panel_mod.SegmentDirection


class _FakeWebEngineView(QWidget):
    def setHtml(self, *_args, **_kwargs):
        return None


siphon_panel_mod.QWebEngineView = _FakeWebEngineView


def test_load_example_data_detection():
    """测试加载包含示例数据的旧工况时自动检测"""
    app = QApplication.instance() or QApplication(sys.argv)
    panel = siphon_panel_mod.SiphonPanel()

    # 添加示例数据
    panel._add_example_longitudinal()
    assert panel._longitudinal_is_example == True

    # 模拟保存（示例数据不会被保存）
    data = panel.to_dict()
    assert 'longitudinal_nodes' not in data, "示例数据不应被保存"

    # 创建新面板并加载（应自动添加示例数据）
    panel2 = siphon_panel_mod.SiphonPanel()
    panel2.from_dict(data)
    assert panel2._longitudinal_is_example == True, "加载后应自动添加示例数据"

    print("✓ 加载空数据时自动添加示例数据")


def test_load_saved_example_as_real():
    """测试加载被错误保存为真实数据的示例数据"""
    app = QApplication.instance() or QApplication(sys.argv)
    panel = siphon_panel_mod.SiphonPanel()

    # 添加示例数据
    panel._add_example_longitudinal()

    # 模拟旧bug：强制清除标志并保存
    panel._longitudinal_is_example = False
    data = panel.to_dict()

    # 验证示例数据被保存了
    assert 'longitudinal_nodes' in data, "示例数据应被保存（模拟旧bug）"
    assert len(data['longitudinal_nodes']) == 13

    # 创建新面板并加载
    panel2 = siphon_panel_mod.SiphonPanel()
    panel2.from_dict(data)

    # 验证自动检测为示例数据
    assert panel2._longitudinal_is_example == True, "应自动检测为示例数据"

    # 验证结构段表隐藏纵断面段
    display_segs = panel2._get_all_display_segments()
    display_long = [s for s, source in display_segs if source == 'longitudinal']
    assert len(display_long) == 0, "示例状态下不应显示纵断面段"

    print("✓ 自动检测并修复被错误保存的示例数据")


if __name__ == '__main__':
    test_load_example_data_detection()
    test_load_saved_example_as_real()
    print("\n所有测试通过！")
