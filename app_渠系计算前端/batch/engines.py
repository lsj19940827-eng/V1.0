# -*- coding: utf-8 -*-
"""批量计算内核的正式包入口，不修改进程导入路径。"""

try:
    from calc_渠系计算算法内核.明渠设计 import (
        quick_calculate as mingqu_calculate,
        quick_calculate_compound_trapezoidal as mingqu_compound_calculate,
        quick_calculate_circular as circular_calculate,
        quick_calculate_u_section as mingqu_u_calculate
    )
    MINGQU_AVAILABLE = True
except ImportError:
    MINGQU_AVAILABLE = False

try:
    from calc_渠系计算算法内核.渡槽设计 import (
        quick_calculate_u as ducao_u_calculate,
        quick_calculate_rect as ducao_rect_calculate
    )
    DUCAO_AVAILABLE = True
except ImportError:
    DUCAO_AVAILABLE = False

try:
    from calc_渠系计算算法内核.隧洞设计 import (
        quick_calculate_circular as suidong_circular_calculate,
        quick_calculate_flat_bottom_circular as suidong_flat_bottom_circular_calculate,
        quick_calculate_horseshoe as suidong_horseshoe_calculate,
        quick_calculate_horseshoe_std as suidong_horseshoe_std_calculate
    )
    SUIDONG_AVAILABLE = True
except ImportError:
    SUIDONG_AVAILABLE = False

try:
    from calc_渠系计算算法内核.矩形暗涵设计 import (
        quick_calculate_rectangular_culvert as rect_culvert_calculate
    )
    RECT_CULVERT_AVAILABLE = True
except ImportError:
    RECT_CULVERT_AVAILABLE = False

try:
    from calc_渠系计算算法内核.圆拱直墙型暗涵设计 import (
        quick_calculate_arch_culvert as arch_culvert_calculate,
        get_required_freeboard_height_arch,
    )
    ARCH_CULVERT_AVAILABLE = True
except ImportError:
    ARCH_CULVERT_AVAILABLE = False

ENGINE_NAMES = ['mingqu_calculate', 'mingqu_compound_calculate', 'circular_calculate', 'mingqu_u_calculate', 'MINGQU_AVAILABLE', 'ducao_u_calculate', 'ducao_rect_calculate', 'DUCAO_AVAILABLE', 'suidong_circular_calculate', 'suidong_flat_bottom_circular_calculate', 'suidong_horseshoe_calculate', 'suidong_horseshoe_std_calculate', 'SUIDONG_AVAILABLE', 'rect_culvert_calculate', 'RECT_CULVERT_AVAILABLE', 'arch_culvert_calculate', 'get_required_freeboard_height_arch', 'ARCH_CULVERT_AVAILABLE']

# 可选内核不可用时继续导出兼容名称，由对应 AVAILABLE 标记控制提示。
for _name in ENGINE_NAMES:
    globals().setdefault(_name, None)
