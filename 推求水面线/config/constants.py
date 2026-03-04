# -*- coding: utf-8 -*-
"""
常量配置

定义推求水面线程序中使用的各种常量。
"""

# ============================================================
# 程序信息
# ============================================================
APP_TITLE = "渠道水面线计算系统"
APP_VERSION = "V1.0"
APP_FULL_TITLE = f"{APP_TITLE} {APP_VERSION}"

# ============================================================
# 窗口尺寸
# ============================================================
WINDOW_WIDTH = 1600
WINDOW_HEIGHT = 900
WINDOW_MIN_WIDTH = 1200
WINDOW_MIN_HEIGHT = 700

# ============================================================
# 结构形式选项（用于下拉菜单）
# 与多渠段批量计算.py保持一致
# ============================================================
STRUCTURE_TYPE_OPTIONS = [
    "明渠-梯形",
    "明渠-矩形",
    "明渠-圆形",
    "渡槽-U形",
    "渡槽-矩形",
    "隧洞-圆形",
    "隧洞-圆拱直墙型",
    "隧洞-马蹄形Ⅰ型",
    "隧洞-马蹄形Ⅱ型",
    "矩形暗涵",
    "倒虹吸",
    "有压管道",
    "分水闸",
    "分水口",
    "节制闸",
    "泄水闸",
]

# ============================================================
# 渠道级别选项（用于桩号前缀生成）
# ============================================================
# 渠道级别映射：用户输入 -> 桩号缩写
# 例如：渠道名称为"南峰寺"，级别为"支渠"，则桩号前缀为"南支"
CHANNEL_LEVEL_OPTIONS = [
    "总干渠",
    "总干管",
    "分干渠",
    "分干管",
    "干渠",
    "干管",
    "支渠",
    "支管",
    "分支渠",
    "分支管",
]

# 渠道级别到桩号缩写的映射
CHANNEL_LEVEL_ABBR_MAP = {
    "总干渠": "总干",
    "总干管": "总干",
    "分干渠": "分干",
    "分干管": "分干",
    "干渠": "干",
    "干管": "干",
    "支渠": "支",
    "支管": "支",
    "分支渠": "分支",
    "分支管": "分支",
}

# 默认渠道级别
DEFAULT_CHANNEL_LEVEL = "支渠"

# ============================================================
# 数据表格列定义
# ============================================================
# 输入列（用户可编辑）
INPUT_COLUMNS = [
    {"id": "flow_section", "text": "流量段", "width": 80, "editable": True},
    {"id": "name", "text": "建筑物名称", "width": 100, "editable": True},
    {"id": "structure_type", "text": "结构形式", "width": 130, "editable": True, "type": "combobox"},
    {"id": "in_out", "text": "进出口判断", "width": 90, "editable": True},  # 允许用户手动修改
    {"id": "ip_number", "text": "IP", "width": 160, "editable": True},  # 允许用户手动修改
    {"id": "x", "text": "X", "width": 120, "editable": True, "type": "float"},
    {"id": "y", "text": "Y", "width": 120, "editable": True, "type": "float"},
    {"id": "turn_radius", "text": "转弯半径", "width": 90, "editable": True, "type": "float"},
]

# 几何结果列（只读）
GEOMETRY_RESULT_COLUMNS = [
    {"id": "turn_angle", "text": "转角", "width": 80},
    {"id": "tangent_length", "text": "切线长", "width": 80},
    {"id": "arc_length", "text": "弧长", "width": 80},
    {"id": "curve_length", "text": "弯道长度", "width": 90},
    {"id": "straight_distance", "text": "IP直线间距", "width": 110},
    {"id": "station_ip", "text": "IP点桩号", "width": 150},  # 加宽以容纳格式如"南支15+020.073"
    {"id": "station_BC", "text": "弯前BC", "width": 150},
    {"id": "station_MC", "text": "里程MC", "width": 150},
    {"id": "station_EC", "text": "弯末EC", "width": 150},
    {"id": "check_pre_curve", "text": "复核弯前长度", "width": 120},   # L72-J72 检查起弯点是否超过上一IP
    {"id": "check_post_curve", "text": "复核弯后长度", "width": 120},  # L73-J72 检查出弯点是否超过下一IP
    {"id": "check_total_length", "text": "复核总长度", "width": 110},  # L72-J71-J72 夹直线长度
]

# 水力输入列（用户可编辑/可导入）- 设计流量下的参数
HYDRAULIC_INPUT_COLUMNS = [
    {"id": "bottom_width", "text": "底宽\nB", "width": 70, "editable": True, "type": "float"},  # 明渠梯形、明渠矩形、矩形暗涵、隧洞圆拱直墙型、渡槽矩形
    {"id": "diameter", "text": "直径\nD", "width": 70, "editable": True, "type": "float"},  # 明渠圆形、隧洞圆形
    {"id": "section_radius", "text": "半径", "width": 60, "editable": True, "type": "float"},  # 渡槽-U形、隧洞-马蹄形Ⅰ型、隧洞-马蹄形Ⅱ型
    {"id": "side_slope", "text": "边坡系数\nm", "width": 80, "editable": True, "type": "float"},
    {"id": "roughness", "text": "糙率\nn", "width": 60, "editable": True, "type": "float"},
    {"id": "bottom_slope", "text": "底坡\n1/i", "width": 60, "editable": True, "type": "float"},
    {"id": "flow_design", "text": "流量\nQ设计", "width": 70, "editable": True, "type": "float"},
]

# 水力结果列（只读）- 设计流量下的参数
HYDRAULIC_RESULT_COLUMNS = [
    {"id": "water_depth_design", "text": "水深\nh设计", "width": 75},
    {"id": "cross_section_area", "text": "过水断面面积\nA", "width": 110},
    {"id": "wetted_perimeter", "text": "湿周\nX", "width": 65},
    {"id": "hydraulic_radius", "text": "水力半径\nR", "width": 80},
    {"id": "velocity_design", "text": "流速\nv设计", "width": 75},
]

# 水头损失列（只读，与 panel.py NODE_ALL_HEADERS 保持一致）
HEAD_LOSS_COLUMNS = [
    {"id": "transition_length", "text": "渐变段长度L", "width": 90},
    {"id": "head_loss_transition", "text": "渐变段水头损失", "width": 110},
    {"id": "head_loss_bend", "text": "弯道水头损失", "width": 100},
    {"id": "head_loss_friction", "text": "沿程水头损失", "width": 100},
    {"id": "head_loss_reserve", "text": "预留水头损失", "width": 100, "editable": True, "type": "float"},
    {"id": "head_loss_gate", "text": "过闸水头损失", "width": 100, "editable": True, "type": "float"},
    {"id": "head_loss_siphon", "text": "倒虹吸/有压管道水头损失", "width": 140},
    {"id": "head_loss_total", "text": "总水头损失", "width": 90},
    {"id": "head_loss_cumulative", "text": "累计总水头损失", "width": 110},
]

# 水位高程列（只读）
ELEVATION_COLUMNS = [
    {"id": "water_level", "text": "水位", "width": 80},
    {"id": "bottom_elevation", "text": "渠底高程", "width": 80},
    {"id": "top_elevation", "text": "渠顶高程", "width": 80},
]

# 所有列（合并）
ALL_COLUMNS = (
    INPUT_COLUMNS 
    + GEOMETRY_RESULT_COLUMNS 
    + HYDRAULIC_INPUT_COLUMNS 
    + HYDRAULIC_RESULT_COLUMNS 
    + HEAD_LOSS_COLUMNS 
    + ELEVATION_COLUMNS
)

# ============================================================
# 数值精度
# ============================================================
COORDINATE_PRECISION = 9        # 坐标小数位数
ANGLE_PRECISION = 9             # 角度小数位数
LENGTH_PRECISION = 9            # 长度小数位数（内部计算精度）
STATION_DISPLAY_PRECISION = 3   # 桩号显示小数位数
ELEVATION_PRECISION = 3         # 高程小数位数
HEAD_LOSS_PRECISION = 6         # 水头损失小数位数
VELOCITY_PRECISION = 3          # 流速小数位数
SLOPE_PRECISION = 6             # 坡度小数位数

# ============================================================
# 计算常量
# ============================================================
GRAVITY = 9.81                  # 重力加速度 (m/s²)
ZERO_TOLERANCE = 1e-9           # 零值容差

# ============================================================
# 默认值
# ============================================================
DEFAULT_ROUGHNESS = 0.014       # 默认糙率（明渠/渡槽/隧洞/暗涵等）
DEFAULT_SIPHON_ROUGHNESS = 0.014  # 默认倒虹吸糙率
DEFAULT_TURN_RADIUS = 100.0     # 默认转弯半径 (m)
DEFAULT_GATE_HEAD_LOSS = 0.1    # 默认过闸水头损失 (m)，用于闸类型（分水闸/分水口/泄水闸/节制闸等）
DEFAULT_SIPHON_TURN_RADIUS_N = 3.0  # 倒虹吸默认转弯半径倍数（R = n × D，n默认取3）

# ============================================================
# 局部损失系数（参考值，后续可调整）
# ============================================================
LOCAL_LOSS_COEFFICIENTS = {
    "隧洞": {"进口": 0.5, "出口": 1.0},
    "渡槽": {"进口": 0.3, "出口": 0.5},
    "倒虹吸": {"进口": 0.0, "出口": 0.0},  # 倒虹吸水损由外部导入
    "矩形暗涵": {"进口": 0.5, "出口": 1.0},
}

# ============================================================
# 渐变段配置（表K.1.2）—— 渡槽/隧洞
# ============================================================
# 渡槽/隧洞渐变段形式选项（表K.1.2）
TRANSITION_FORM_OPTIONS = [
    "曲线形反弯扭曲面",
    "直线形扭曲面",
    "圆弧直墙",
    "八字形",
    "直角形",
]

# ============================================================
# 倒虹吸渐变段配置（表L.1.2）
# ============================================================
# 倒虹吸渐变段型式选项（表L.1.2）
SIPHON_TRANSITION_FORM_OPTIONS = [
    "反弯扭曲面",
    "直线扭曲面",
    "1/4圆弧",
    "方头型",
]

# 倒虹吸渐变段局部损失系数表（表L.1.2）
SIPHON_TRANSITION_ZETA_COEFFICIENTS = {
    "进口": {
        "反弯扭曲面": 0.10,
        "直线扭曲面": 0.20,   # 取均值，范围0.05~0.30
        "1/4圆弧": 0.15,
        "方头型": 0.30,
    },
    "出口": {
        "反弯扭曲面": 0.20,
        "直线扭曲面": 0.40,   # 取均值，范围0.30~0.50
        "1/4圆弧": 0.25,
        "方头型": 0.75,
    }
}

# 倒虹吸渐变段型式与渡槽/隧洞渐变段型式的对应关系
# 表L.1.2 → 表K.1.2
SIPHON_TO_TRANSITION_FORM_MAP = {
    "反弯扭曲面": "曲线形反弯扭曲面",
    "直线扭曲面": "直线形扭曲面",
    # "1/4圆弧" 和 "方头型" 在表K.1.2中无直接对应
}

# 渐变段局部损失系数表（表K.1.2）
TRANSITION_ZETA_COEFFICIENTS = {
    "进口": {
        "曲线形反弯扭曲面": 0.1,
        "圆弧直墙": 0.2,
        "八字形": 0.3,
        "直角形": 0.4,
        # "直线形扭曲面"需要根据θ角度线性插值，范围0~0.1 (θ: 15°~37°)
    },
    "出口": {
        "曲线形反弯扭曲面": 0.2,
        "圆弧直墙": 0.5,
        "八字形": 0.5,
        "直角形": 0.75,
        # "直线形扭曲面"需要根据θ角度线性插值，范围0.1~0.17 (θ: 15°~37°)
    }
}

# 直线形扭曲面ζ系数插值范围
TRANSITION_TWISTED_ZETA_RANGE = {
    "进口": {"min_theta": 15, "max_theta": 37, "min_zeta": 0.0, "max_zeta": 0.1},
    "出口": {"min_theta": 15, "max_theta": 37, "min_zeta": 0.1, "max_zeta": 0.17},
}

# 渐变段长度计算系数
TRANSITION_LENGTH_COEFFICIENTS = {
    "进口": 2.5,  # 进口：L = 2.5 × |B1 - B2|
    "出口": 3.5,  # 出口：L = 3.5 × |B1 - B2|
}

# 渐变段长度约束条件
TRANSITION_LENGTH_CONSTRAINTS = {
    "渡槽": {
        "进口": {"depth_multiplier": 6, "description": "6倍渠道设计水深"},
        "出口": {"depth_multiplier": 8, "description": "8倍渠道设计水深"},
    },
    "隧洞": {
        "进口": {"depth_multiplier": 5, "tunnel_multiplier": 3, "description": "5倍渠道水深或3倍洞径"},
        "出口": {"depth_multiplier": 5, "tunnel_multiplier": 3, "description": "5倍渠道水深或3倍洞径"},
    },
    "倒虹吸": {
        "进口": {"depth_multiplier": 5, "description": "上游渠道设计水深的3~5倍（取大值5倍）"},
        "出口": {"depth_multiplier": 6, "description": "下游渠道设计水深的4~6倍（取大值6倍）"},
    },
    "矩形暗涵": {
        "进口": {"description": "仅基础公式 L=k×|B₁-B₂|"},
        "出口": {"description": "仅基础公式 L=k×|B₁-B₂|"},
    },
}

# ============================================================
# 文件对话框过滤器
# ============================================================
EXCEL_FILE_TYPES = [
    ("Excel文件", "*.xlsx *.xls"),
    ("所有文件", "*.*"),
]

CSV_FILE_TYPES = [
    ("CSV文件", "*.csv"),
    ("所有文件", "*.*"),
]
