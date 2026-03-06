# -*- coding: utf-8 -*-
"""倒虹吸自动确认场景测试

场景1（应该自动确认）：
打开程序→水面线模块→打开倒虹吸→计算→关闭倒虹吸窗口
同一次程序运行中再次打开倒虹吸→应该自动确认

场景2（不应该自动确认）：
打开程序→水面线模块→打开倒虹吸→计算→关闭倒虹吸窗口→关闭主程序
重新打开程序→加载项目→打开倒虹吸→不应该自动确认
"""

import os
import sys
from uuid import uuid4

# 添加路径
_pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _pkg_root)

from PySide6.QtWidgets import QApplication
from 推求水面线.managers.siphon_manager import SiphonManager, SiphonConfig
from 渠系断面设计.siphon.panel import SiphonPanel


def _project_path():
    base = os.path.join(os.getcwd(), "data", "_test_auto_confirm")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, f"demo_project_{uuid4().hex}")


def test_scenario1_same_process_auto_confirm():
    """场景1：同一进程内再次打开应该自动确认"""
    app = QApplication.instance() or QApplication(sys.argv)

    project_path = _project_path()
    manager = SiphonManager(project_path)

    # 第一次打开倒虹吸面板
    panel1 = SiphonPanel(show_case_management=False, disable_autosave_load=True)
    panel1.edit_Q.setText("1.5")
    panel1.edit_v.setText("2.0")
    panel1.spin_num_pipes.setValue(2)

    # 模拟计算完成（标记为已确认）
    manager.mark_runtime_confirmed("虹吸A")

    # 保存配置
    config = SiphonConfig(
        name="虹吸A",
        Q=1.5,
        v_guess=2.0,
        roughness_n=0.014,
        num_pipes=2,
    )
    manager.set_siphon_config(config)
    manager.save_config()

    # 关闭面板（模拟关闭窗口）
    panel1.deleteLater()

    # 同一进程内再次打开倒虹吸面板
    panel2 = SiphonPanel(show_case_management=False, disable_autosave_load=True)

    # 加载配置（模拟 MultiSiphonDialog._config_to_panel_dict）
    from 渠系断面设计.siphon.multi_siphon_dialog import MultiSiphonDialog
    from types import SimpleNamespace
    fake_dialog = SimpleNamespace(manager=manager)

    loaded_config = manager.get_siphon_config("虹吸A")
    data = MultiSiphonDialog._config_to_panel_dict(fake_dialog, loaded_config)

    # 验证：应该包含 calculated_at（触发自动确认）
    assert 'calculated_at' in data, "场景1失败：同一进程内应该包含 calculated_at"

    # 加载到面板
    panel2.from_dict(data)

    # 验证：所有确认标志应该为 True
    assert panel2._v_user_confirmed is True, "场景1失败：拟定流速应该自动确认"
    assert panel2._num_pipes_user_confirmed is True, "场景1失败：管道根数应该自动确认"
    assert panel2._turn_n_user_confirmed is True, "场景1失败：转弯半径倍数应该自动确认"

    print("[PASS] 场景1测试通过：同一进程内再次打开自动确认")
    panel2.deleteLater()


def test_scenario2_new_process_no_auto_confirm():
    """场景2：重启程序后不应该自动确认"""
    app = QApplication.instance() or QApplication(sys.argv)

    project_path = _project_path()

    # 模拟第一次运行：计算并保存
    manager1 = SiphonManager(project_path)
    manager1.mark_runtime_confirmed("虹吸B")
    config = SiphonConfig(
        name="虹吸B",
        Q=2.0,
        v_guess=2.5,
        roughness_n=0.014,
        num_pipes=3,
        calculated_at="2026-03-05 10:00:00",  # 历史文件中残留的时间戳
    )
    manager1.set_siphon_config(config)
    manager1.save_config()

    # 清空进程内确认态（模拟程序重启）
    SiphonManager._runtime_confirmed.clear()

    # 模拟第二次运行：重新加载
    manager2 = SiphonManager(project_path)

    # 验证：进程内确认态应该为空
    assert manager2.is_runtime_confirmed("虹吸B") is False, "场景2失败：重启后不应该有进程内确认态"

    # 加载配置
    panel = SiphonPanel(show_case_management=False, disable_autosave_load=True)
    from 渠系断面设计.siphon.multi_siphon_dialog import MultiSiphonDialog
    from types import SimpleNamespace
    fake_dialog = SimpleNamespace(manager=manager2)

    loaded_config = manager2.get_siphon_config("虹吸B")
    data = MultiSiphonDialog._config_to_panel_dict(fake_dialog, loaded_config)

    # 验证：不应该包含 calculated_at（不触发自动确认）
    assert 'calculated_at' not in data, "场景2失败：重启后不应该包含 calculated_at"

    # 加载到面板
    panel.from_dict(data)

    # 验证：所有确认标志应该为 False
    assert panel._v_user_confirmed is False, "场景2失败：拟定流速不应该自动确认"
    assert panel._num_pipes_user_confirmed is False, "场景2失败：管道根数不应该自动确认"

    print("[PASS] 场景2测试通过：重启程序后不自动确认")
    panel.deleteLater()


if __name__ == '__main__':
    test_scenario1_same_process_auto_confirm()
    test_scenario2_new_process_no_auto_confirm()
    print("\n[PASS] 所有场景测试通过")
