# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from 渠系断面设计.siphon.panel import SiphonPanel
from 渠系断面设计.siphon.siphon_models import SegmentDirection

def test_example_data_display():
    print("\n=== Test 1: Example Data Display ===")
    app = QApplication.instance() or QApplication(sys.argv)
    panel = SiphonPanel(show_case_management=False)

    assert len(panel.longitudinal_nodes) == 13
    print(f"[OK] Longitudinal nodes: {len(panel.longitudinal_nodes)}")

    long_segs = [s for s in panel.segments if s.direction != SegmentDirection.COMMON]
    assert len(long_segs) == 12
    print(f"[OK] Longitudinal segments: {len(long_segs)}")

    assert panel._longitudinal_is_example == True
    print(f"[OK] Example flag: True")

    if hasattr(panel, 'long_hint_label'):
        assert panel.long_hint_label.isVisible() == True
        print("[OK] Long hint label visible")

    if hasattr(panel, 'seg_hint_label'):
        assert panel.seg_hint_label.isVisible() == True
        print("[OK] Seg hint label visible")

    panel.close()
    print("Test 1 PASSED\n")

def test_serialization():
    print("=== Test 2: Serialization ===")
    app = QApplication.instance() or QApplication(sys.argv)
    panel = SiphonPanel(show_case_management=False)

    data = panel.to_dict()
    assert 'longitudinal_nodes' not in data
    print("[OK] Example data not saved")

    panel2 = SiphonPanel(show_case_management=False)
    panel2.longitudinal_nodes = []
    panel2.from_dict(data)

    assert len(panel2.longitudinal_nodes) == 13
    assert panel2._longitudinal_is_example == True
    print("[OK] Example data auto-loaded")

    panel.close()
    panel2.close()
    print("Test 2 PASSED\n")

def test_edit_clears_flag():
    print("=== Test 3: Edit Clears Flag ===")
    app = QApplication.instance() or QApplication(sys.argv)
    panel = SiphonPanel(show_case_management=False)

    assert panel._longitudinal_is_example == True
    panel._on_long_table_edited()
    assert panel._longitudinal_is_example == False
    print("[OK] Flag cleared after edit")

    panel.close()
    print("Test 3 PASSED\n")

if __name__ == "__main__":
    try:
        test_example_data_display()
        test_serialization()
        test_edit_clears_flag()
        print("=" * 50)
        print("ALL TESTS PASSED!")
        print("=" * 50)
    except Exception as e:
        print(f"\n[FAIL] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
