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
    MINGQU_COMPOUND_TRAPEZOIDAL = "明渠-复式梯形"
    MINGQU_RECTANGULAR = "明渠-矩形"
    MINGQU_CIRCULAR = "明渠-圆形"
    MINGQU_U = "明渠-U形"
    
    # 渡槽类型
    AQUEDUCT_U = "渡槽-U形"
    AQUEDUCT_RECT = "渡槽-矩形"
    
    # 隧洞类型
    TUNNEL_CIRCULAR = "隧洞-圆形"
    TUNNEL_FLAT_BOTTOM_CIRCULAR = "隧洞-平底圆形"
    TUNNEL_ARCH = "隧洞-圆拱直墙型"
    TUNNEL_HORSESHOE_1 = "隧洞-马蹄形Ⅰ型"
    TUNNEL_HORSESHOE_2 = "隧洞-马蹄形Ⅱ型"
    
    # 暗涵类型
    RECT_CULVERT = "暗涵-矩形"
    CULVERT_ARCH = "暗涵-圆拱直墙型"
    
    # 分水闸/分水口（单行点状结构，标记流量段分界）
    DIVERSION_GATE = "分水闸"
    DIVERSION_OUTLET = "分水口"
    
    # 其他闸类型（点状结构，产生过闸水头损失）
    DISCHARGE_GATE = "泄水闸"
    RETURN_WATER_GATE = "退水闸"
    CHECK_GATE = "节制闸"
    
    # 倒虹吸（保留用于水面线计算中的特殊处理）
    INVERTED_SIPHON = "倒虹吸"
    
    # 有压管道（类似倒虹吸，参与批量计算和水面线推求）
    PRESSURE_PIPE = "有压管道"

    # xx管专用管道结构
    DIRECTIONAL_DRILL = "定向钻"
    PIPE_JACKING = "顶管"
    
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
    def get_pressure_pipe_like_structures(cls) -> list:
        """获取按有压管道语义处理的结构类型。"""
        return [
            cls.PRESSURE_PIPE,
            cls.DIRECTIONAL_DRILL,
            cls.PIPE_JACKING,
        ]

    @classmethod
    def is_pressure_pipe_like(cls, structure_type) -> bool:
        """判断结构类型是否按有压管道语义处理。"""
        if structure_type is None:
            return False
        value = structure_type.value if hasattr(structure_type, "value") else str(structure_type)
        return cls.is_pressure_pipe_like_str(value)

    @classmethod
    def is_pressure_pipe_like_str(cls, structure_type_str: str) -> bool:
        """判断结构形式字符串是否为有压管道同类。"""
        text = str(structure_type_str or "").strip()
        if not text:
            return False
        return text in {item.value for item in cls.get_pressure_pipe_like_structures()}
    
    @classmethod
    def get_special_structures(cls) -> list:
        """
        获取需要进出口标识的特殊建筑物类型
        
        隧洞、倒虹吸、渡槽、矩形暗涵需要标识进口和出口
        """
        return [
            cls.TUNNEL_CIRCULAR, cls.TUNNEL_FLAT_BOTTOM_CIRCULAR, cls.TUNNEL_ARCH,
            cls.TUNNEL_HORSESHOE_1, cls.TUNNEL_HORSESHOE_2,
            cls.INVERTED_SIPHON,
            cls.PRESSURE_PIPE,
            cls.DIRECTIONAL_DRILL,
            cls.PIPE_JACKING,
            cls.AQUEDUCT_U, cls.AQUEDUCT_RECT,
            cls.RECT_CULVERT,
            cls.CULVERT_ARCH,
            # 兼容旧版本
            cls.TUNNEL, cls.AQUEDUCT
        ]
    
    @classmethod
    def is_special_structure(cls, structure_type: 'StructureType') -> bool:
        """判断是否为特殊建筑物（需要进出口标识）"""
        return structure_type in cls.get_special_structures()

    @classmethod
    def get_silent_optional_name_structures(cls) -> list:
        """获取允许名称留空且不提示的结构类型。"""
        return [
            cls.MINGQU_TRAPEZOIDAL,
            cls.MINGQU_COMPOUND_TRAPEZOIDAL,
            cls.MINGQU_RECTANGULAR,
            cls.MINGQU_CIRCULAR,
            cls.MINGQU_U,
            cls.PRESSURE_PIPE,
        ]

    @classmethod
    def get_warn_optional_name_structures(cls) -> list:
        """获取允许名称留空但建议补充名称的结构类型。"""
        return [
            cls.RECT_CULVERT,
            cls.CULVERT_ARCH,
        ]

    @classmethod
    def get_optional_name_structures(cls) -> list:
        """获取允许建筑物名称留空的结构类型。"""
        return cls.get_silent_optional_name_structures() + cls.get_warn_optional_name_structures()

    @classmethod
    def allows_empty_name(cls, structure_type) -> bool:
        """判断结构类型是否允许建筑物名称留空。"""
        if structure_type is None:
            return False
        value = structure_type.value if hasattr(structure_type, "value") else str(structure_type)
        return value in {item.value for item in cls.get_optional_name_structures()}

    @classmethod
    def warns_on_empty_name(cls, structure_type) -> bool:
        """判断结构类型留空时是否只做轻提示。"""
        if structure_type is None:
            return False
        value = structure_type.value if hasattr(structure_type, "value") else str(structure_type)
        return value in {item.value for item in cls.get_warn_optional_name_structures()}
    
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
        text = str(value or "").strip()
        alias_map = {
            "暗涵-矩形": cls.RECT_CULVERT,
            "矩形暗涵": cls.RECT_CULVERT,
            "暗渠": cls.RECT_CULVERT,
            "矩形暗渠": cls.RECT_CULVERT,
            "暗涵-圆拱直墙型": cls.CULVERT_ARCH,
            "圆拱直墙型暗涵": cls.CULVERT_ARCH,
            "暗涵圆拱直墙型": cls.CULVERT_ARCH,
        }
        if text in alias_map:
            return alias_map[text]
        for item in cls:
            if item.value == text:
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
