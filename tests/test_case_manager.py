# -*- coding: utf-8 -*-
"""倒虹吸工况管理功能测试"""
import os
import sys
import json
import tempfile
import shutil
from pathlib import Path

# 设置控制台编码
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from 渠系断面设计.siphon.case_manager import CaseManager, CaseInfo


def test_case_manager():
    """测试工况管理器基本功能"""
    print("=" * 60)
    print("测试：工况管理器基本功能")
    print("=" * 60)

    # 创建临时目录
    temp_dir = tempfile.mkdtemp()
    print(f"临时目录: {temp_dir}")

    try:
        # 1. 初始化管理器
        manager = CaseManager(temp_dir)
        assert len(manager.cases) == 0, "初始应该没有工况"
        print("✓ 初始化成功")

        # 2. 创建工况
        case1 = manager.create_case()
        assert case1.name == "工况1", "第一个工况应该命名为'工况1'"
        assert len(manager.cases) == 1
        print(f"✓ 创建工况: {case1.name}")

        case2 = manager.create_case()
        assert case2.name == "工况2"
        assert len(manager.cases) == 2
        print(f"✓ 创建工况: {case2.name}")

        # 3. 重命名工况
        manager.rename_case(case1, "测试工况A")
        assert case1.name == "测试工况A"
        assert os.path.exists(os.path.join(temp_dir, "测试工况A.siphon.json"))
        print(f"✓ 重命名工况: {case1.name}")

        # 4. 复制工况
        case3 = manager.duplicate_case(case1)
        assert case3.name == "测试工况A_副本"
        assert len(manager.cases) == 3
        print(f"✓ 复制工况: {case3.name}")

        # 5. 保存和加载数据
        test_data = {
            'Q': 10.0,
            'v_guess': 2.0,
            'n': 0.014,
            'test_field': 'test_value'
        }
        manager.save_case_data(case1, test_data)
        loaded_data = manager.load_case_data(case1)
        assert loaded_data['Q'] == 10.0
        assert loaded_data['test_field'] == 'test_value'
        assert loaded_data['case_name'] == "测试工况A"
        print("✓ 保存和加载数据成功")

        # 6. 重新排序
        new_order = [case2, case3, case1]
        manager.reorder_cases(new_order)
        assert manager.cases[0] == case2
        assert manager.cases[1] == case3
        assert manager.cases[2] == case1
        print("✓ 重新排序成功")

        # 7. 删除工况
        manager.delete_case(case2)
        assert len(manager.cases) == 2
        assert not os.path.exists(case2.file_path)
        print(f"✓ 删除工况: {case2.name}")

        print("\n" + "=" * 60)
        print("所有测试通过！")
        print("=" * 60)

    finally:
        # 清理临时目录
        shutil.rmtree(temp_dir)
        print(f"\n清理临时目录: {temp_dir}")


if __name__ == '__main__':
    test_case_manager()
