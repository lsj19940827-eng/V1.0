# -*- coding: utf-8 -*-
"""
枚举类型定义

定义推求水面线程序中使用的各种枚举类型。
"""

from enum import Enum


class StructureType(Enum):
    """
    结构形式枚举
    
    定义渠系中各种建筑物和渠道的类型。
    与多渠段批量计算.py保持一致。
    """
    # 明渠类型
    MINGQU_TRAPEZOIDAL = "明渠-梯形"
    MINGQU_RECTANGULAR = "明渠-矩形"
    MINGQU_CIRCULAR = "明渠-圆形"
    MINGQU_U = "明渠-U形"
    
    # 渡槽类型
    AQUEDUCT_U = "渡槽-U形"
    AQUEDUCT_RECT = "渡槽-矩形"
    
    # 隧洞类型
    TUNNEL_CIRCULAR = "隧洞-圆形"
    TUNNEL_ARCH = "隧洞-圆拱直墙型"
    TUNNEL_HORSESHOE_1 = "隧洞-马蹄形Ⅰ型"
    TUNNEL_HORSESHOE_2 = "隧洞-马蹄形Ⅱ型"
    
    # 矩形暗涵
    RECT_CULVERT = "矩形暗涵"
    
    # 分水闸/分水口（单行点状结构，标记流量段分界）
    DIVERSION_GATE = "分水闸"
    DIVERSION_OUTLET = "分水口"
    
    # 其他闸类型（点状结构，产生过闸水头损失）
    DISCHARGE_GATE = "泄水闸"
    CHECK_GATE = "节制闸"
    
    # 倒虹吸（保留用于水面线计算中的特殊处理）
    INVERTED_SIPHON = "倒虹吸"
    
    # 渐变段（用于渐变段专用行）
    TRANSITION = "渐变段"
    
    # 兼容旧版本的简化类型
    RECTANGULAR = "矩形"
    TUNNEL = "隧洞"
    AQUEDUCT = "渡槽"
    
    # 兼容别名（用于水力计算模块）
    RECTANGULAR_CHANNEL = "明渠-矩形"
    TRAPEZOIDAL_CHANNEL = "明渠-梯形"
    CIRCULAR_CHANNEL = "明渠-圆形"
    
    @classmethod
    def get_all_options(cls) -> list:
        """获取所有结构形式选项（用于下拉菜单）"""
        return [item.value for item in cls]
    
    @classmethod
    def get_special_structures(cls) -> list:
        """
        获取需要进出口标识的特殊建筑物类型
        
        隧洞、倒虹吸、渡槽、矩形暗涵需要标识进口和出口
        """
        return [
            cls.TUNNEL_CIRCULAR, cls.TUNNEL_ARCH, 
            cls.TUNNEL_HORSESHOE_1, cls.TUNNEL_HORSESHOE_2,
            cls.INVERTED_SIPHON,
            cls.AQUEDUCT_U, cls.AQUEDUCT_RECT,
            cls.RECT_CULVERT,
            # 兼容旧版本
            cls.TUNNEL, cls.AQUEDUCT
        ]
    
    @classmethod
    def is_special_structure(cls, structure_type: 'StructureType') -> bool:
        """判断是否为特殊建筑物（需要进出口标识）"""
        return structure_type in cls.get_special_structures()
    
    @classmethod
    def is_diversion_gate(cls, structure_type: 'StructureType') -> bool:
        """
        判断是否为闸类型（分水闸/分水口/泄水闸/节制闸等）
        
        匹配规则：结构形式值中包含"闸"或"分水"关键词
        
        Args:
            structure_type: 结构类型枚举值
            
        Returns:
            是否为闸类型
        """
        if structure_type is None:
            return False
        return "闸" in structure_type.value or "分水" in structure_type.value
    
    @classmethod
    def is_diversion_gate_str(cls, structure_type_str: str) -> bool:
        """
        判断字符串是否为闸类型（分水闸/分水口/泄水闸/节制闸等）
        
        Args:
            structure_type_str: 结构形式字符串
            
        Returns:
            是否为闸类型
        """
        if not structure_type_str:
            return False
        return "闸" in structure_type_str or "分水" in structure_type_str
    
    @classmethod
    def from_string(cls, value: str) -> 'StructureType':
        """从字符串转换为枚举值"""
        for item in cls:
            if item.value == value:
                return item
        raise ValueError(f"未知的结构形式: {value}")


class InOutType(Enum):
    """
    进出口标识枚举
    
    用于标识建筑物的进口、出口或普通断面。
    注意：只有"进"和"出"两种状态，第1次出现为进口，第2次出现为出口。
    """
    INLET = "进"      # 第1次出现：进口
    OUTLET = "出"     # 第2次出现：出口
    NORMAL = ""       # 普通断面（明渠等）
    
    @classmethod
    def from_count(cls, count: int, total: int = 2) -> tuple:
        """
        根据建筑物名称出现次数返回进出口标识
        
        业务规则：同一建筑物可能出现多次（因有转弯/IP点），
        只有首尾代表进出口，中间都是普通断面。
        
        Args:
            count: 该建筑物名称当前是第几次出现（1, 2, 3...）
            total: 该建筑物名称的总出现次数（默认2次）
            
        Returns:
            tuple: (进出口标识, 是否需要警告)
            - count=1: (INLET, False) - 第1次出现为进口
            - count=total: (OUTLET, False) - 最后一次出现为出口
            - 其他: (NORMAL, False) - 中间的为普通断面
        """
        if count == 1:
            return (cls.INLET, False)
        elif count == total:
            return (cls.OUTLET, False)
        else:
            # 中间出现的断面（有转弯但不是进出口）
            return (cls.NORMAL, False)
    
    @classmethod
    def from_string(cls, value: str) -> 'InOutType':
        """
        从字符串转换为枚举值
        
        Args:
            value: 字符串值（"进"、"中"、"出"或空字符串）
            
        Returns:
            对应的进出口标识枚举
        """
        for item in cls:
            if item.value == value:
                return item
        return cls.NORMAL
