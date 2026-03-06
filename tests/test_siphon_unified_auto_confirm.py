# -*- coding: utf-8 -*-
"""倒虹吸统一架构自动确认测试

测试场景：
1. 渠系断面设计模块：单倒虹吸面板自动确认
2. 推求水面线模块：多倒虹吸窗口自动确认
3. 数据迁移：autosave 数据迁移到 SiphonManager
"""

import os
import sys
import json
from uuid import uuid4

# 添加路径
_pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _pkg_root)

from PySide6.QtWidgets import QApplication
from 推求水面线.managers.siphon_manager import SiphonManager, SiphonConfig
from 渠系断面设计.siphon.panel import SiphonPanel


def _project_path():
    base = os.path.join(os.getcwd(), "data", "_test_unified_confirm")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, f"test_project_{uuid4().hex}.ppipe")


def test_single_siphon_panel_auto_confirm():
    """测试渠系断面设计模块的单倒虹吸面板自动确认"""
    print("\n=== 测试1：渠系断面设计模块 - 单倒虹吸面板 ===")

    app = QApplication.instance() or QApplication(sys.argv)
    project_path = _project_path()

    # 创建 SiphonManager
    manager = SiphonManager(project_path)

    # 第一次打开面板
    print("1. 第一次打开面板")
    panel1 = SiphonPanel(
        show_case_management=False,
        disable_autosave_load=False,
        siphon_manager=manager,
        siphon_name="单倒虹吸"
    )

    # 设置参数
    panel1.edit_Q.setText("1.5")
    panel1.edit_v.setText("2.0")
    panel1.spin_num_pipes.setValue(2)
    panel1._v_user_confirmed = True
    panel1._num_pipes_user_confirmed = True

    # 模拟计算完成（直接调用标记方法）
    manager.mark_runtime_confirmed("单倒虹吸")
    panel1._save_to_manager()

    # 验证：已标记为确认
    assert manager.is_runtime_confirmed("单倒虹吸"), "应该标记为已确认"

    panel1.deleteLater()
    print("   [PASS] 第一次打开并计算完成")

    # 同一进程内第二次打开面板
    print("2. 同一进程内第二次打开面板")
    panel2 = SiphonPanel(
        show_case_management=False,
        disable_autosave_load=False,
        siphon_manager=manager,
        siphon_name="单倒虹吸"
    )

    # 触发加载（模拟 QTimer.singleShot）
    panel2._load_from_manager()

    # 验证：应该自动确认
    assert panel2._v_user_confirmed is True, "拟定流速应该自动确认"
    assert panel2._num_pipes_user_confirmed is True, "管道根数应该自动确认"
    assert panel2._turn_n_user_confirmed is True, "转弯半径倍数应该自动确认"

    panel2.deleteLater()
    print("   [PASS] 同一进程内第二次打开自动确认")

    # 模拟程序重启
    print("3. 模拟程序重启")
    SiphonManager._runtime_confirmed.clear()

    manager3 = SiphonManager(project_path)
    assert manager3.is_runtime_confirmed("单倒虹吸") is False, "重启后不应该有确认态"

    panel3 = SiphonPanel(
        show_case_management=False,
        disable_autosave_load=False,
        siphon_manager=manager3,
        siphon_name="单倒虹吸"
    )
    panel3._load_from_manager()

    # 验证：不应该自动确认
    assert panel3._v_user_confirmed is False, "重启后拟定流速不应该自动确认"
    assert panel3._num_pipes_user_confirmed is False, "重启后管道根数不应该自动确认"

    panel3.deleteLater()
    print("   [PASS] 重启后不自动确认")

    print("[PASS] 测试1通过：单倒虹吸面板自动确认功能正常")


def test_multi_siphon_dialog_auto_confirm():
    """测试推求水面线模块的多倒虹吸窗口自动确认"""
    print("\n=== 测试2：推求水面线模块 - 多倒虹吸窗口 ===")

    app = QApplication.instance() or QApplication(sys.argv)
    project_path = _project_path()

    # 创建 SiphonManager
    manager = SiphonManager(project_path)

    # 模拟第一次计算
    print("1. 第一次计算并标记确认")
    manager.mark_runtime_confirmed("虹吸A")
    config = SiphonConfig(
        name="虹吸A",
        Q=2.0,
        v_guess=2.5,
        roughness_n=0.014,
        num_pipes=3,
    )
    manager.set_siphon_config(config)
    manager.save_config()

    assert manager.is_runtime_confirmed("虹吸A"), "应该标记为已确认"
    print("   [PASS] 已标记确认")

    # 同一进程内再次打开
    print("2. 同一进程内再次打开")
    from 渠系断面设计.siphon.multi_siphon_dialog import MultiSiphonDialog
    from types import SimpleNamespace
    fake_dialog = SimpleNamespace(manager=manager)

    loaded_config = manager.get_siphon_config("虹吸A")
    data = MultiSiphonDialog._config_to_panel_dict(fake_dialog, loaded_config)

    # 验证：应该包含 calculated_at
    assert 'calculated_at' in data, "同一进程内应该包含 calculated_at"
    print("   [PASS] 包含 calculated_at，会触发自动确认")

    # 模拟程序重启
    print("3. 模拟程序重启")
    SiphonManager._runtime_confirmed.clear()

    manager2 = SiphonManager(project_path)
    assert manager2.is_runtime_confirmed("虹吸A") is False, "重启后不应该有确认态"

    fake_dialog2 = SimpleNamespace(manager=manager2)
    loaded_config2 = manager2.get_siphon_config("虹吸A")
    data2 = MultiSiphonDialog._config_to_panel_dict(fake_dialog2, loaded_config2)

    # 验证：不应该包含 calculated_at
    assert 'calculated_at' not in data2, "重启后不应该包含 calculated_at"
    print("   [PASS] 不包含 calculated_at，不会触发自动确认")

    print("[PASS] 测试2通过：多倒虹吸窗口自动确认功能正常")


def test_autosave_migration():
    """测试 autosave 数据迁移到 SiphonManager"""
    print("\n=== 测试3：autosave 数据迁移 ===")

    import json
    app = QApplication.instance() or QApplication(sys.argv)

    # 使用独立的项目路径，避免与测试1冲突
    project_path = _project_path()

    # 创建旧的 autosave 数据
    print("1. 创建旧的 autosave 数据")
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    data_dir = os.path.join(root, 'data')
    os.makedirs(data_dir, exist_ok=True)
    autosave_path = os.path.join(data_dir, 'siphon_autosave.json')

    # 先删除旧的 autosave 文件（避免被之前的测试污染）
    if os.path.exists(autosave_path):
        os.remove(autosave_path)
        print(f"   [DEBUG] 已删除旧的 autosave 文件")

    old_data = {
        'version': '1.0',
        'saved_at': '2026-03-05 10:00:00',
        'data': {
            'Q': 1.8,
            'v_guess': 2.2,
            'n': 0.014,
            'num_pipes': 2,
        }
    }

    with open(autosave_path, 'w', encoding='utf-8') as f:
        json.dump(old_data, f, indent=2, ensure_ascii=False)

    # 验证写入的数据
    with open(autosave_path, 'r', encoding='utf-8') as f:
        verify_data = json.load(f)
    print(f"   [DEBUG] 写入的 autosave 数据 Q={verify_data['data']['Q']}")

    print("   [PASS] 已创建旧数据")

    # 创建面板并触发迁移
    print("2. 创建面板触发迁移")
    manager = SiphonManager(project_path)

    # 确保 manager 中没有旧数据（删除可能存在的配置文件）
    if os.path.exists(manager._config_path):
        os.remove(manager._config_path)
        print(f"   [DEBUG] 已删除旧配置文件: {manager._config_path}")
        # 重新创建 manager
        manager = SiphonManager(project_path)

    assert manager.get_siphon_config("单倒虹吸") is None, "开始前应该没有数据"

    panel = SiphonPanel(
        show_case_management=False,
        disable_autosave_load=False,
        siphon_manager=manager,
        siphon_name="单倒虹吸"
    )

    # 触发加载（会自动迁移）
    panel._load_from_manager()

    # 调试：检查保存前的内存数据
    print(f"   [DEBUG] 保存前 _config 中的数据: {manager._config.get('siphons', {}).get('单倒虹吸', {}).get('Q')}")

    # 验证：数据已迁移到 SiphonManager
    config = manager.get_siphon_config("单倒虹吸")
    assert config is not None, "应该已迁移数据"
    print(f"   [DEBUG] 迁移后的 Q 值: {config.Q}, 类型: {type(config.Q)}")
    print(f"   [DEBUG] 迁移后的 v_guess 值: {config.v_guess}, 类型: {type(config.v_guess)}")
    print(f"   [DEBUG] 迁移后的 num_pipes 值: {config.num_pipes}, 类型: {type(config.num_pipes)}")

    # 调试：检查配置文件内容
    import json
    if os.path.exists(manager._config_path):
        with open(manager._config_path, 'r', encoding='utf-8') as f:
            file_data = json.load(f)
        print(f"   [DEBUG] 配置文件中的 Q 值: {file_data.get('siphons', {}).get('单倒虹吸', {}).get('Q')}")

    assert config.Q == 1.8, f"流量应该正确迁移，实际值: {config.Q}"
    assert config.v_guess == 2.2, "拟定流速应该正确迁移"
    assert config.num_pipes == 2, "管道根数应该正确迁移"

    panel.deleteLater()

    # 清理
    if os.path.exists(autosave_path):
        os.remove(autosave_path)

    print("   [PASS] 数据迁移成功")
    print("[PASS] 测试3通过：autosave 数据迁移功能正常")


if __name__ == '__main__':
    test_single_siphon_panel_auto_confirm()
    test_multi_siphon_dialog_auto_confirm()
    test_autosave_migration()
    print("\n" + "="*50)
    print("[PASS] 所有测试通过：统一架构自动确认功能正常")
    print("="*50)
