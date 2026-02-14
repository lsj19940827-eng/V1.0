# -*- coding: utf-8 -*-
"""
倒虹吸计算面板 - 推求水面线系统适配版

直接继承倒虹吸系统的核心面板，实现100%功能复刻。
以后修改倒虹吸功能只需改原系统代码，无需修改此文件。
"""

import sys
import os

# 添加倒虹吸系统路径（放在最前面，优先级最高）
SIPHON_SYSTEM_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "倒虹吸水力计算系统"
)

# 保存原始 sys.path
_original_path = sys.path.copy()

# 临时将倒虹吸系统路径放在最前面
if SIPHON_SYSTEM_PATH not in sys.path:
    sys.path.insert(0, SIPHON_SYSTEM_PATH)

# 导入核心面板
try:
    # 先导入倒虹吸系统的模块（使用完整模块名）
    import siphon_models
    import siphon_coefficients
    import siphon_hydraulics
    from siphon_core_panel import SiphonCorePanel
    
    CalculationResult = siphon_models.CalculationResult
    SIPHON_MODULES_AVAILABLE = True
except ImportError as e:
    print(f"警告: 无法导入倒虹吸系统模块: {e}")
    SIPHON_MODULES_AVAILABLE = False
    SiphonCorePanel = None
    CalculationResult = None
finally:
    # 恢复原始 sys.path（保留倒虹吸系统路径以便后续使用）
    pass


class SiphonTabPanel:
    """
    倒虹吸计算面板（推求水面线系统适配版）
    
    继承核心面板，添加与推求水面线系统的集成逻辑。
    所有功能由 SiphonCorePanel 提供，此类仅作为适配器。
    """
    
    def __new__(cls, parent, siphon_name: str, on_result_changed=None):
        """
        创建面板实例
        
        Args:
            parent: 父容器（Notebook）
            siphon_name: 倒虹吸名称
            on_result_changed: 结果变化回调 callback(siphon_name, result)
        """
        if not SIPHON_MODULES_AVAILABLE or SiphonCorePanel is None:
            raise ImportError("倒虹吸系统模块不可用，请确保倒虹吸水力计算系统已正确安装")
        
        # 包装回调函数
        def wrapped_callback(result):
            if on_result_changed:
                on_result_changed(siphon_name, result)
        
        # 直接返回核心面板实例
        panel = SiphonCorePanel(
            parent,
            siphon_name=siphon_name,
            on_result_callback=wrapped_callback
        )
        
        return panel


# 为了兼容现有代码，导出必要的类和函数
__all__ = ['SiphonTabPanel', 'SIPHON_MODULES_AVAILABLE']
