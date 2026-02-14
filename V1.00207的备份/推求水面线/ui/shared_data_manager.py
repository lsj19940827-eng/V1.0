# -*- coding: utf-8 -*-
"""
共享数据管理器 - 跨模块断面参数共享

用于在渠系建筑物断面计算结果和推求水面线系统之间传递数据。
当用户在断面计算标签页完成计算后，计算结果会被注册到这个管理器中。
然后在推求水面线系统中，用户可以直接从已有的计算结果中导入断面参数。
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
import time


@dataclass
class SectionResult:
    """断面计算结果"""
    source: str              # 来源标识（如"明渠-梯形"、"渡槽-U形"等）
    timestamp: float         # 计算时间戳
    section_type: str        # 断面类型（梯形、矩形、圆形、U形等）
    
    # 基本参数
    Q: float = 0.0           # 设计流量 (m³/s)
    n: float = 0.0           # 糙率
    slope_inv: float = 0.0   # 坡降倒数 (1/i)
    
    # 坐标信息（批量计算时使用）
    coord_X: float = 0.0     # X坐标
    coord_Y: float = 0.0     # Y坐标
    
    # 断面尺寸
    B: Optional[float] = None       # 底宽 (m)
    h: Optional[float] = None       # 水深 (m)
    m: Optional[float] = None       # 边坡系数
    D: Optional[float] = None       # 直径 (m) - 圆形断面
    R: Optional[float] = None       # 半径 (m) - U形断面
    
    # 计算结果
    A: float = 0.0           # 过水面积 (m²)
    V: float = 0.0           # 流速 (m/s)
    X: float = 0.0           # 湿周 (m)
    R_hydraulic: float = 0.0 # 水力半径 (m)
    
    # 加大流量工况
    Q_max: float = 0.0       # 加大流量 (m³/s)
    h_max: float = 0.0       # 加大水深 (m)
    V_max: float = 0.0       # 加大流速 (m/s)
    
    # 超高和净空（用于验证）
    Fb: float = 0.0          # 超高 (m)
    clearance_design: float = 0.0  # 设计净空高度 (m)
    clearance_max: float = 0.0     # 加大净空高度 (m)
    
    # 基础信息（批量计算专用）
    channel_name: str = ""        # 渠道名称
    channel_level: str = ""       # 渠道类型（支渠/干渠等）
    start_water_level: float = 0.0  # 起始水位 (m)
    start_station: float = 0.0    # 起始桩号
    flow_section: str = ""        # 流量段编号
    building_name: str = ""       # 建筑物名称
    
    # 原始结果字典（用于导出完整数据）
    raw_result: Dict = field(default_factory=dict)
    
    def get_display_info(self) -> str:
        """获取用于显示的参数信息"""
        if self.section_type in ('梯形', '矩形') or (self.B is not None and self.h is not None):
            m_str = f", m={self.m:.1f}" if self.m else ""
            return f"B={self.B:.2f}m, h={self.h:.2f}m{m_str}"
        elif self.section_type == '圆形' and self.D is not None:
            return f"D={self.D:.2f}m, h={self.h:.2f}m"
        elif self.section_type == 'U形' and self.R is not None:
            return f"R={self.R:.2f}m, h={self.h:.2f}m"
        else:
            return f"Q={self.Q:.2f}m³/s, V={self.V:.2f}m/s"
    
    def to_node_params(self) -> Dict[str, Any]:
        """转换为推求水面线节点参数格式"""
        params = {
            'flow': self.Q,
            'roughness': self.n,
            'water_depth': self.h,
            'velocity': self.V,
            'x': self.coord_X,
            'y': self.coord_Y,
            'flow_section': self.flow_section,
            'name': self.building_name,
            'section_params': {
                'B': self.B,
                'm': self.m,
                'D': self.D,
                'R_circle': self.R,
                'A': self.A,
                'X': self.X,
                'R': self.R_hydraulic,
            }
        }
        # 计算比降
        if self.slope_inv and self.slope_inv > 0:
            params['slope_i'] = 1.0 / self.slope_inv
        
        return params


class SharedDataManager:
    """
    单例模式：管理跨模块断面参数共享
    
    主要功能：
    1. 缓存各断面计算标签页的计算结果
    2. 提供给推求水面线系统导入断面参数
    3. 支持多个计算结果的管理和选择
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_data_storage()
        return cls._instance
    
    def _init_data_storage(self):
        """初始化数据存储"""
        self._results: Dict[str, SectionResult] = {}  # 计算结果缓存
        self._batch_results: List[SectionResult] = []  # 批量计算结果
        self._listeners: List[callable] = []          # 数据变化监听器
    
    def register_result(self, source: str, result: Dict[str, Any]) -> bool:
        """
        注册计算结果
        
        Args:
            source: 来源标识，如"明渠-梯形"、"渡槽-U形"等
            result: 计算结果字典
            
        Returns:
            是否注册成功
        """
        if not result.get('success', False):
            return False
        
        try:
            section_result = self._extract_section_result(source, result)
            if section_result:
                self._results[source] = section_result
                self._notify_listeners('single', source, section_result)
                return True
        except Exception as e:
            print(f"注册计算结果失败: {e}")
        
        return False
    
    def register_batch_results(self, results: List[Dict[str, Any]]) -> int:
        """
        注册批量计算结果
        
        Args:
            results: 批量计算结果列表
            
        Returns:
            成功注册的数量
        """
        self._batch_results.clear()
        count = 0
        
        for i, result in enumerate(results):
            if result.get('success', False):
                source = f"批量计算-{i+1}"
                section_result = self._extract_section_result(source, result)
                if section_result:
                    self._batch_results.append(section_result)
                    count += 1
        
        if count > 0:
            self._notify_listeners('batch', 'batch_results', self._batch_results)
        
        return count
    
    def _extract_section_result(self, source: str, result: Dict) -> Optional[SectionResult]:
        """从计算结果中提取断面参数"""
        try:
            section_type = result.get('section_type', '')
            
            # 判断是否为批量计算结果（检测特征字段）
            is_batch = 'coord_X' in result or 'channel_name' in result or 'flow_section' in result
            
            # 倒虹吸特殊处理：不参与水力计算，只记录位置和名称信息
            is_siphon = result.get('is_siphon', False) or section_type == "倒虹吸"
            if is_siphon:
                return SectionResult(
                    source=source,
                    timestamp=time.time(),
                    section_type="倒虹吸",
                    Q=result.get('Q', 0.0),
                    n=result.get('n', 0.014),
                    slope_inv=0,
                    coord_X=result.get('coord_X', 0.0),
                    coord_Y=result.get('coord_Y', 0.0),
                    flow_section=str(result.get('flow_section', '')),
                    building_name=str(result.get('building_name', '')),
                    raw_result=result
                )
            
            # 分水闸/分水口特殊处理：不参与断面计算，只记录位置和名称信息
            is_diversion_gate = result.get('is_diversion_gate', False) or "分水" in section_type
            if is_diversion_gate:
                return SectionResult(
                    source=source,
                    timestamp=time.time(),
                    section_type=section_type,
                    Q=result.get('Q', 0.0),
                    n=result.get('n', 0.014),
                    slope_inv=0,
                    coord_X=result.get('coord_X', 0.0),
                    coord_Y=result.get('coord_Y', 0.0),
                    flow_section=str(result.get('flow_section', '')),
                    building_name=str(result.get('building_name', '')),
                    raw_result=result
                )
            
            section_result = SectionResult(
                source=source,
                timestamp=time.time(),
                section_type=section_type,
                Q=result.get('Q', result.get('Q_design', 0)),
                n=result.get('n', result.get('roughness', 0)),
                slope_inv=result.get('slope_inv', 0),
                V=result.get('V_design', result.get('v_design', 0)),
                A=result.get('A_design', result.get('area_design', 0)),
                raw_result=result
            )
            
            # 提取坐标信息（批量计算时使用）
            if is_batch:
                section_result.coord_X = result.get('coord_X', 0.0)
                section_result.coord_Y = result.get('coord_Y', 0.0)
                section_result.flow_section = str(result.get('flow_section', ''))
                section_result.building_name = str(result.get('building_name', ''))
                section_result.channel_name = str(result.get('channel_name', ''))
                section_result.channel_level = str(result.get('channel_level', ''))
                section_result.start_water_level = result.get('start_water_level', 0.0)
                section_result.start_station = result.get('start_station', 0.0)
            
            # 提取断面尺寸
            # 梯形、矩形断面（包括明渠、渡槽、隧洞-圆拱直墙型、矩形暗涵等）
            if section_type in ('梯形', '矩形') or 'b_design' in result or 'B' in result:
                section_result.B = result.get('b_design', result.get('B', None))
                section_result.h = result.get('h_design', result.get('h', None))
                # 梯形边坡系数
                if "梯形" in section_type or section_type == '梯形':
                    section_result.m = result.get('m', 0)
            
            # 圆形断面（明渠-圆形、隧洞-圆形）
            if section_type == '圆形' or '圆形' in section_type or 'D' in result or 'D_design' in result:
                section_result.D = result.get('D', result.get('D_design', None))
                section_result.h = result.get('h_design', result.get('water_depth', None))
            
            # U形断面（渡槽-U形）
            if section_type == 'U形' or 'U形' in section_type or ('R' in result and 'U' in str(result.get('section_type', ''))):
                section_result.R = result.get('R', result.get('R_design', None))
                section_result.h = result.get('h_design', result.get('water_depth', None))
            
            # 马蹄形隧洞（半径用小写 'r' 存储）
            if "马蹄形" in section_type or 'r' in result:
                section_result.R = result.get('r', result.get('R_design', None))
                section_result.h = result.get('h_design', result.get('water_depth', None))
            
            # 提取水力参数
            section_result.X = result.get('X_design', result.get('wetted_perimeter', result.get('P_design', 0)))
            section_result.R_hydraulic = result.get('R_hyd_design', result.get('hydraulic_radius', result.get('R_design', 0)))
            
            # 提取加大流量工况
            section_result.Q_max = result.get('Q_increased', result.get('Q_max', 0))
            section_result.h_max = result.get('h_increased', result.get('h_max', 0))
            section_result.V_max = result.get('V_increased', result.get('V_max', 0))
            
            # 提取超高和净空
            section_result.Fb = result.get('Fb', result.get('FB_d', 0))
            section_result.clearance_design = result.get('clearance_design', 0)
            section_result.clearance_max = result.get('clearance_max', 0)
            
            return section_result
            
        except Exception as e:
            print(f"提取断面参数失败: {e}")
            return None
    
    def get_available_sources(self) -> List[str]:
        """获取所有可用的计算结果来源"""
        return list(self._results.keys())
    
    def get_result(self, source: str) -> Optional[SectionResult]:
        """获取指定来源的计算结果"""
        return self._results.get(source)
    
    def get_batch_results(self) -> List[SectionResult]:
        """获取批量计算结果"""
        return self._batch_results.copy()
    
    def get_all_results(self) -> Dict[str, SectionResult]:
        """获取所有计算结果"""
        return self._results.copy()
    
    def clear_result(self, source: str) -> None:
        """清除指定来源的计算结果"""
        if source in self._results:
            del self._results[source]
    
    def clear_batch_results(self) -> None:
        """清除批量计算结果"""
        self._batch_results.clear()
    
    def clear_all(self) -> None:
        """清除所有计算结果"""
        self._results.clear()
        self._batch_results.clear()
    
    def add_listener(self, callback: callable) -> None:
        """添加数据变化监听器"""
        if callback not in self._listeners:
            self._listeners.append(callback)
    
    def remove_listener(self, callback: callable) -> None:
        """移除数据变化监听器"""
        if callback in self._listeners:
            self._listeners.remove(callback)
    
    def _notify_listeners(self, event_type: str, source: str, data: Any) -> None:
        """通知所有监听器数据已更新"""
        for listener in self._listeners:
            try:
                listener(event_type, source, data)
            except Exception as e:
                print(f"通知监听器失败: {e}")
    
    def get_result_count(self) -> int:
        """获取已缓存的单项计算结果数量"""
        return len(self._results)
    
    def get_batch_count(self) -> int:
        """获取批量计算结果数量"""
        return len(self._batch_results)
    
    def get_summary(self) -> str:
        """获取当前缓存数据的摘要信息"""
        lines = []
        
        if self._results:
            lines.append("【单项计算结果】")
            for source, result in self._results.items():
                lines.append(f"  {source}: {result.get_display_info()}")
        
        if self._batch_results:
            lines.append(f"【批量计算结果】共 {len(self._batch_results)} 条")
        
        if not lines:
            return "暂无计算结果"
        
        return "\n".join(lines)


# 全局单例获取函数
_shared_data_manager: Optional[SharedDataManager] = None

def get_shared_data_manager() -> SharedDataManager:
    """获取共享数据管理器单例"""
    global _shared_data_manager
    if _shared_data_manager is None:
        _shared_data_manager = SharedDataManager()
    return _shared_data_manager
