# -*- coding: utf-8 -*-
"""
断面计算Panel包装器

用于从渠系建筑物断面尺寸计算程序.py导入Panel类，
并添加与SharedDataManager的集成。
"""

import sys
import os

# 添加「渠系建筑物断面计算」目录到路径，以便导入其中的模块
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
parent_dir = os.path.join(_project_root, "渠系建筑物断面计算")
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# 导入标记
MODULES_LOADED = {
    'OpenChannelPanel': False,
    'AqueductPanel': False,
    'TunnelPanel': False,
    'RectangularCulvertPanel': False,
    'BatchCalculationPanel': False,
}

IMPORT_ERRORS = {}

# 尝试导入渠系建筑物断面尺寸计算程序中的组件
try:
    # 导入字体管理和工具函数
    from 渠系建筑物断面尺寸计算程序 import (
        get_display_width,
        pad_str,
        FONT_SIZE_PRESETS,
        CURRENT_FONT_SIZE,
        get_font_config,
        VIZ_MODULE_LOADED,
    )
    UTILS_LOADED = True
except (ImportError, NameError, Exception) as e:
    UTILS_LOADED = False
    IMPORT_ERRORS['utils'] = str(e)
    # 提供默认实现
    def get_display_width(s): return len(s)
    def pad_str(s, width, align='left'): return s
    FONT_SIZE_PRESETS = {"中号": {"default": 10, "small": 9, "title": 11, "result": 10}}
    CURRENT_FONT_SIZE = "中号"
    def get_font_config(): return FONT_SIZE_PRESETS["中号"]
    VIZ_MODULE_LOADED = False

# 导入Panel类
try:
    from 渠系建筑物断面尺寸计算程序 import OpenChannelPanel as _OpenChannelPanel
    MODULES_LOADED['OpenChannelPanel'] = True
except (ImportError, NameError, Exception) as e:
    _OpenChannelPanel = None
    IMPORT_ERRORS['OpenChannelPanel'] = str(e)

try:
    from 渠系建筑物断面尺寸计算程序 import AqueductPanel as _AqueductPanel
    MODULES_LOADED['AqueductPanel'] = True
except (ImportError, NameError, Exception) as e:
    _AqueductPanel = None
    IMPORT_ERRORS['AqueductPanel'] = str(e)

try:
    from 渠系建筑物断面尺寸计算程序 import TunnelPanel as _TunnelPanel
    MODULES_LOADED['TunnelPanel'] = True
except (ImportError, NameError, Exception) as e:
    _TunnelPanel = None
    IMPORT_ERRORS['TunnelPanel'] = str(e)

try:
    from 渠系建筑物断面尺寸计算程序 import RectangularCulvertPanel as _RectangularCulvertPanel
    MODULES_LOADED['RectangularCulvertPanel'] = True
except (ImportError, NameError, Exception) as e:
    _RectangularCulvertPanel = None
    IMPORT_ERRORS['RectangularCulvertPanel'] = str(e)

try:
    from 多渠段批量计算 import BatchCalculationPanel as _BatchCalculationPanel
    MODULES_LOADED['BatchCalculationPanel'] = True
except (ImportError, NameError, Exception) as e:
    _BatchCalculationPanel = None
    IMPORT_ERRORS['BatchCalculationPanel'] = str(e)

# 导入共享数据管理器
from .shared_data_manager import get_shared_data_manager


def _register_to_shared_data(panel_instance, panel_name, section_type):
    """
    将计算结果注册到SharedDataManager
    
    Args:
        panel_instance: Panel实例
        panel_name: Panel名称（如"明渠"、"渡槽"等）
        section_type: 断面类型字符串
    """
    if hasattr(panel_instance, 'current_result') and panel_instance.current_result:
        result = panel_instance.current_result
        if result.get('success', False):
            source = f"{panel_name}-{section_type}"
            manager = get_shared_data_manager()
            manager.register_result(source, result)


# 创建增强版Panel类（添加SharedDataManager集成）
# 注意：必须通过类级别方法重写（而非实例级别替换）来覆盖_calculate，
# 因为父类__init__中按钮的 command=self._calculate 在创建时就绑定了方法引用，
# 实例级别的替换发生在 super().__init__() 之后，无法影响已绑定的按钮命令。
# 而类级别的方法重写通过MRO机制，在按钮创建时就能正确解析到子类方法。

if _OpenChannelPanel is not None:
    class OpenChannelPanel(_OpenChannelPanel):
        """增强版明渠计算Panel，集成SharedDataManager"""
        
        def _calculate(self):
            """重写计算方法，在计算完成后注册结果到SharedDataManager"""
            super()._calculate()
            section_type = self.section_type_var.get() if hasattr(self, 'section_type_var') else "梯形"
            _register_to_shared_data(self, "明渠", section_type)
else:
    OpenChannelPanel = None

if _AqueductPanel is not None:
    class AqueductPanel(_AqueductPanel):
        """增强版渡槽计算Panel，集成SharedDataManager"""
        
        def _calculate(self):
            """重写计算方法，在计算完成后注册结果到SharedDataManager"""
            super()._calculate()
            section_type = self.section_type_var.get() if hasattr(self, 'section_type_var') else "U形"
            _register_to_shared_data(self, "渡槽", section_type)
else:
    AqueductPanel = None

if _TunnelPanel is not None:
    class TunnelPanel(_TunnelPanel):
        """增强版隧洞计算Panel，集成SharedDataManager"""
        
        def _calculate(self):
            """重写计算方法，在计算完成后注册结果到SharedDataManager"""
            super()._calculate()
            section_type = self.section_type_var.get() if hasattr(self, 'section_type_var') else "圆形"
            _register_to_shared_data(self, "隧洞", section_type)
else:
    TunnelPanel = None

if _RectangularCulvertPanel is not None:
    class RectangularCulvertPanel(_RectangularCulvertPanel):
        """增强版矩形暗涵计算Panel，集成SharedDataManager"""
        
        def _calculate(self):
            """重写计算方法，在计算完成后注册结果到SharedDataManager"""
            super()._calculate()
            _register_to_shared_data(self, "矩形暗涵", "矩形")
else:
    RectangularCulvertPanel = None

# 批量计算Panel包装类（添加完整数据注册）
if _BatchCalculationPanel is not None:
    class BatchCalculationPanel(_BatchCalculationPanel):
        """增强版批量计算Panel，集成SharedDataManager完整数据注册"""
        
        def __init__(self, parent):
            super().__init__(parent)
        
        def _batch_calculate(self):
            """批量计算（重写，添加完整数据注册）"""
            # 调用原始方法
            super()._batch_calculate()
            
            # 计算完成后，注册完整结果到SharedDataManager
            if hasattr(self, 'batch_results') and self.batch_results:
                self._register_enriched_batch_results()
        
        def _register_enriched_batch_results(self):
            """将批量计算结果（含完整输入参数和基础信息）注册到SharedDataManager"""
            try:
                manager = get_shared_data_manager()
                
                # 获取基础信息
                channel_name = ""
                channel_level = ""
                start_water_level = 0.0
                start_station = 0.0
                
                if hasattr(self, 'var_channel_name'):
                    channel_name = self.var_channel_name.get().strip()
                if hasattr(self, 'var_channel_level'):
                    channel_level = self.var_channel_level.get().strip()
                if hasattr(self, 'var_start_water_level'):
                    try:
                        start_water_level = float(self.var_start_water_level.get().strip())
                    except (ValueError, AttributeError):
                        start_water_level = 0.0
                if hasattr(self, 'get_start_station_value'):
                    try:
                        start_station = self.get_start_station_value()
                    except:
                        start_station = 0.0
                
                # 构造完整结果列表
                enriched_results = []
                for item in self.batch_results:
                    input_values = item.get('input', [])
                    result = item.get('result', {})
                    
                    if not result.get('success', False):
                        continue
                    
                    # 合并input和result，构造完整的数据字典
                    enriched_result = self._merge_input_and_result(
                        input_values, result,
                        channel_name, channel_level, start_water_level, start_station
                    )
                    enriched_results.append(enriched_result)
                
                # 清除旧的批量结果，注册新的完整结果
                if enriched_results:
                    manager.clear_batch_results()
                    manager.register_batch_results(enriched_results)
                
            except Exception as e:
                print(f"注册增强版批量计算结果到SharedDataManager失败: {e}")
        
        def _merge_input_and_result(self, input_values, result, 
                                     channel_name, channel_level, start_water_level, start_station):
            """
            合并输入参数和计算结果，构造完整的数据字典
            
            输入表列索引（参考多渠段批量计算.py第510-512行）：
            0:序号, 1:流量段, 2:建筑物名称, 3:结构形式, 4:X, 5:Y, 6:Q(m³/s), 
            7:糙率n, 8:比降(1/), 9:边坡系数m, 10:底宽B(m), 11:明渠宽深比, 
            12:半径R(m), 13:直径D(m), ...
            """
            merged = dict(result)  # 复制result字典
            merged['success'] = True  # 确保标记成功
            
            # 安全获取input值的辅助函数
            def safe_get(idx, default=""):
                if input_values and len(input_values) > idx and input_values[idx] is not None:
                    return input_values[idx]
                return default
            
            def safe_float(idx, default=0.0):
                val = safe_get(idx, "")
                if val == "" or val == "-":
                    return default
                try:
                    return float(val)
                except (ValueError, TypeError):
                    return default
            
            # 添加输入参数（使用coord_X/coord_Y避免与湿周X冲突）
            merged['coord_X'] = safe_float(4, 0.0)
            merged['coord_Y'] = safe_float(5, 0.0)
            merged['Q'] = safe_float(6, result.get('Q', 0))
            merged['n'] = safe_float(7, result.get('n', 0))
            merged['slope_inv'] = safe_float(8, result.get('slope_inv', 0))
            merged['m'] = safe_float(9, result.get('m', 0))
            
            # 添加流量段和建筑物名称
            merged['flow_section'] = str(safe_get(1, ""))
            merged['building_name'] = str(safe_get(2, ""))
            merged['section_type'] = str(safe_get(3, result.get('section_type', "")))
            
            # 添加基础信息
            merged['channel_name'] = channel_name
            merged['channel_level'] = channel_level
            merged['start_water_level'] = start_water_level
            merged['start_station'] = start_station
            
            return merged
else:
    BatchCalculationPanel = None


def get_loaded_modules_info() -> str:
    """获取已加载模块的信息"""
    lines = ["【断面计算模块加载状态】"]
    for name, loaded in MODULES_LOADED.items():
        status = "✓ 已加载" if loaded else f"✗ 未加载: {IMPORT_ERRORS.get(name, '未知错误')}"
        lines.append(f"  {name}: {status}")
    return "\n".join(lines)


def is_any_module_loaded() -> bool:
    """检查是否至少有一个模块加载成功"""
    return any(MODULES_LOADED.values())
