# -*- coding: utf-8 -*-
"""断面表格的数据列、旧格式映射与结构名称规则；不依赖 Qt。"""
import math
import os
import re
from 推求水面线.shared.shared_data_manager import normalize_section_type_name

def _column_index_to_excel_name(column_index: int) -> str:
    """把列号转换成 Excel 列名，便于提示用户。"""
    if column_index <= 0:
        return str(column_index)
    name = ""
    current = column_index
    while current > 0:
        current, remainder = divmod(current - 1, 26)
        name = chr(ord("A") + remainder) + name
    return name

SECTION_TYPES = [
    "明渠-梯形", "明渠-复式梯形", "明渠-矩形", "明渠-圆形", "明渠-U形",
    "渡槽-U形", "渡槽-矩形",
    "隧洞-圆形", "隧洞-平底圆形", "隧洞-圆拱直墙型", "隧洞-马蹄形Ⅰ型", "隧洞-马蹄形Ⅱ型",
    "暗涵-矩形", "暗涵-圆拱直墙型", "倒虹吸", "有压管道", "定向钻", "顶管",
    "充水渠", "泄水渠与陡坡",
    "分水闸", "分水口", "节制闸", "泄水闸", "退水闸",
]

PRESSURE_PIPE_LIKE_SECTION_TYPES = {"有压管道", "定向钻", "顶管"}


_PROJECT_SECTION_TYPE_ALIASES = {
    "暗涵": "暗涵-矩形",
    "暗渠": "暗涵-矩形",
    "矩形暗渠": "暗涵-矩形",
    "矩形暗涵": "暗涵-矩形",
    "暗涵-矩形": "暗涵-矩形",
    "圆拱直墙型暗涵": "暗涵-圆拱直墙型",
    "暗涵-圆拱直墙型": "暗涵-圆拱直墙型",
    "充水渠": "泄水渠与陡坡",
    "泄水渠": "泄水渠与陡坡",
    "泄水渠与陡坡": "泄水渠与陡坡",
    "陡坡": "泄水渠与陡坡",
    "泄槽": "泄水渠与陡坡",
    "陡槽": "泄水渠与陡坡",
    "泄水渠及陡坡": "泄水渠与陡坡",
}

def normalize_project_section_type(section_type):
    """将项目文件中的旧断面名称统一为当前标准口径。"""
    text = normalize_section_type_name(section_type)
    return _PROJECT_SECTION_TYPE_ALIASES.get(text, text)

def is_pressure_pipe_like_section_type(section_type) -> bool:
    """判断结构类型是否按有压管道占位语义处理。"""
    return normalize_section_type_name(section_type) in PRESSURE_PIPE_LIKE_SECTION_TYPES

def is_spillway_steep_chute_section_type(section_type) -> bool:
    """判断结构类型是否为泄水渠与陡坡。"""
    return normalize_project_section_type(section_type) == "泄水渠与陡坡"

def resolve_spillway_steep_chute_display_type(raw_type, fallback="泄水渠与陡坡") -> str:
    """保留用户填写的泄水渠类结构名，仅把计算口径归一。"""
    text = str(getattr(raw_type, "value", raw_type) or "").strip()
    if text.endswith("(连接段)"):
        text = text[:-5].strip()
    if _PROJECT_SECTION_TYPE_ALIASES.get(text) == "泄水渠与陡坡":
        return text
    fallback_text = str(getattr(fallback, "value", fallback) or "").strip()
    if fallback_text.endswith("(连接段)"):
        fallback_text = fallback_text[:-5].strip()
    if _PROJECT_SECTION_TYPE_ALIASES.get(fallback_text) == "泄水渠与陡坡":
        return fallback_text
    return ""

def is_fill_channel_section_type(section_type) -> bool:
    """旧逐行充水渠分支已停用，充水渠类名称统一走专项传参。"""
    return False






def is_gate_like_section_type(section_type) -> bool:
    """判断结构类型是否为闸类点状建筑（含分水口）。"""
    text = normalize_section_type_name(section_type)
    return "闸" in text or "分水" in text

def is_tunnel_section_type(section_type) -> bool:
    """判断结构类型是否为隧洞。"""
    return "隧洞" in normalize_section_type_name(section_type)

def is_rect_culvert_section_type(section_type) -> bool:
    """判断结构类型是否为矩形暗涵（兼容旧值）。"""
    return normalize_section_type_name(section_type) == "暗涵-矩形"

def is_arch_culvert_section_type(section_type) -> bool:
    """判断结构类型是否为圆拱直墙型暗涵（兼容旧值）。"""
    return normalize_section_type_name(section_type) == "暗涵-圆拱直墙型"

INPUT_HEADERS = [
    "序号", "流量段", "建筑物名称", "结构形式", "X", "Y",
    "Q(m³/s)", "糙率n", "比降(1/)",
    "边坡系数m", "底宽B(m)", "暗涵高宽比H/B", "暗涵高度H(m)", "宽深比β",
    "半径R(m)", "直径D(m)",
    "矩形渡槽深宽比", "拉杆高度(m)", "倒角角度(°)", "倒角底边(m)", "圆心角(°)", "直墙高度H直(m)",
    "不淤流速", "不冲流速", "转弯半径(m)",
    "管材",
    "左上坡m1", "平台宽B1(m)", "左下坡m2", "渠底宽B2(m)", "右坡m3", "平台高差h1(m)",
    "泄水渠入口宽度(m)", "泄水渠堰上总水头(m)", "泄水渠入口连接形式", "泄水渠手动流量系数",
    "泄水渠侧收缩系数", "泄水渠动能修正系数", "泄水渠掺气系数",
    "泄水渠侧墙安全超高(m)", "泄水渠池深系数", "泄水渠整流长度系数",
]

_INPUT_HEADERS_BEFORE_AE_AF_REORDER = [
    "序号", "流量段", "建筑物名称", "结构形式", "X", "Y",
    "Q(m³/s)", "糙率n", "比降(1/)",
    "边坡系数m", "底宽B(m)", "暗涵高宽比H/B", "暗涵高度H(m)", "宽深比β",
    "半径R(m)", "直径D(m)",
    "矩形渡槽深宽比", "倒角角度(°)", "倒角底边(m)", "圆心角(°)",
    "不淤流速", "不冲流速", "转弯半径(m)",
    "管材",
    "左上坡m1", "平台宽B1(m)", "左下坡m2", "渠底宽B2(m)", "右坡m3", "平台高差h1(m)",
    "直墙高度H直(m)", "拉杆高度(m)",
]

_INPUT_HEADERS_BEFORE_RECT_CULVERT_VISIBLE_COLUMNS = [
    "序号", "流量段", "建筑物名称", "结构形式", "X", "Y",
    "Q(m³/s)", "糙率n", "比降(1/)",
    "边坡系数m", "底宽B(m)", "宽深比β",
    "半径R(m)", "直径D(m)",
    "矩形渡槽深宽比", "倒角角度(°)", "倒角底边(m)", "圆心角(°)",
    "不淤流速", "不冲流速", "转弯半径(m)",
    "管材",
    "左上坡m1", "平台宽B1(m)", "左下坡m2", "渠底宽B2(m)", "右坡m3", "平台高差h1(m)",
    "直墙高度H直(m)", "拉杆高度(m)",
]

COL_SEQ = 0

COL_SEGMENT = 1

COL_BUILDING_NAME = 2

COL_SECTION_TYPE = 3

COL_X = 4

COL_Y = 5

COL_Q = 6

COL_N = 7

COL_SLOPE = 8

COL_M = 9

COL_B = 10

COL_RECT_CULVERT_HB_RATIO = 11

COL_RECT_CULVERT_H = 12

COL_BETA = 13

COL_R = 14

COL_D = 15

COL_DUCAO_DEPTH_RATIO = 16

COL_TIE_ROD_HEIGHT = 17

COL_CHAMFER_ANGLE = 18

COL_CHAMFER_LENGTH = 19

COL_THETA = 20

COL_ARCH_H_STRAIGHT = 21

COL_V_MIN = 22

COL_V_MAX = 23

COL_TURN_RADIUS = 24

COL_PIPE_MATERIAL = 25

COL_COMPOUND_M1 = 26

COL_COMPOUND_B1 = 27

COL_COMPOUND_M2 = 28

COL_COMPOUND_B2 = 29

COL_COMPOUND_M3 = 30

COL_COMPOUND_H1 = 31

COL_SPILLWAY_INLET_WEIR_WIDTH = 32

COL_SPILLWAY_INLET_HEAD = 33

COL_SPILLWAY_INLET_CONNECTION_TYPE = 34

COL_SPILLWAY_WEIR_COEFFICIENT = 35

COL_SPILLWAY_CONTRACTION_COEFFICIENT = 36

COL_SPILLWAY_ALPHA_PROFILE = 37

COL_SPILLWAY_AERATION_COEFFICIENT = 38

COL_SPILLWAY_SIDEWALL_FREEBOARD = 39

COL_SPILLWAY_POOL_DEPTH_FACTOR = 40

COL_SPILLWAY_OUTLET_RECTIFICATION_FACTOR = 41

COL_PIPE_LOCAL_LOSS = len(INPUT_HEADERS)

COL_PIPE_IN_OUT = len(INPUT_HEADERS) + 1

_LEGACY_INPUT_HEADER_COUNT_BEFORE_RECT_CULVERT_EXCEL_COLUMNS = len(_INPUT_HEADERS_BEFORE_RECT_CULVERT_VISIBLE_COLUMNS)

_RECT_CULVERT_MANUAL_H_META_KEY = "rect_culvert_manual_H"

_IMPORTED_RATIO_WARNING_TOLERANCE = 0.01

SPILLWAY_STEEP_CHUTE_PARAM_KEY = "spillway_steep_chute"

SPILLWAY_STEEP_CHUTE_ADVANCED_COLUMN_MAP = (
    ("inlet_weir_width", COL_SPILLWAY_INLET_WEIR_WIDTH),
    ("inlet_head", COL_SPILLWAY_INLET_HEAD),
    ("inlet_connection_type_label", COL_SPILLWAY_INLET_CONNECTION_TYPE),
    ("weir_coefficient", COL_SPILLWAY_WEIR_COEFFICIENT),
    ("contraction_coefficient", COL_SPILLWAY_CONTRACTION_COEFFICIENT),
    ("alpha_profile", COL_SPILLWAY_ALPHA_PROFILE),
    ("aeration_coefficient", COL_SPILLWAY_AERATION_COEFFICIENT),
    ("sidewall_freeboard_m", COL_SPILLWAY_SIDEWALL_FREEBOARD),
    ("pool_depth_factor", COL_SPILLWAY_POOL_DEPTH_FACTOR),
    ("outlet_rectification_factor", COL_SPILLWAY_OUTLET_RECTIFICATION_FACTOR),
)

SPILLWAY_STEEP_CHUTE_ADVANCED_NUMERIC_KEYS = {
    "inlet_weir_width",
    "inlet_head",
    "weir_coefficient",
    "contraction_coefficient",
    "alpha_profile",
    "aeration_coefficient",
    "sidewall_freeboard_m",
    "pool_depth_factor",
    "outlet_rectification_factor",
}

def _canonical_excel_header(value):
    """统一 Excel 表头文本，便于兼容旧模板和用户手工表。"""
    text = str(value or "").strip()
    return "".join(text.split()).replace("（", "(").replace("）", ")")

_EXCEL_HEADER_ALIASES = {
    "序号": COL_SEQ,
    "流量段": COL_SEGMENT,
    "建筑物名称": COL_BUILDING_NAME,
    "结构形式": COL_SECTION_TYPE,
    "X": COL_X,
    "Y": COL_Y,
    "Q(m³/s)": COL_Q,
    "Q(m3/s)": COL_Q,
    "糙率n": COL_N,
    "比降(1/)": COL_SLOPE,
    "边坡系数m": COL_M,
    "底宽B(m)": COL_B,
    "暗涵高宽比H/B": COL_RECT_CULVERT_HB_RATIO,
    "暗涵高度H(m)": COL_RECT_CULVERT_H,
    "宽深比β": COL_BETA,
    "明渠宽深比": COL_BETA,
    "半径R(m)": COL_R,
    "直径D(m)": COL_D,
    "矩形渡槽深宽比": COL_DUCAO_DEPTH_RATIO,
    "倒角角度(°)": COL_CHAMFER_ANGLE,
    "倒角底边(m)": COL_CHAMFER_LENGTH,
    "圆心角(°)": COL_THETA,
    "不淤流速": COL_V_MIN,
    "不冲流速": COL_V_MAX,
    "转弯半径": COL_TURN_RADIUS,
    "转弯半径(m)": COL_TURN_RADIUS,
    "管材": COL_PIPE_MATERIAL,
    "左上坡m1": COL_COMPOUND_M1,
    "平台宽B1(m)": COL_COMPOUND_B1,
    "左下坡m2": COL_COMPOUND_M2,
    "渠底宽B2(m)": COL_COMPOUND_B2,
    "右坡m3": COL_COMPOUND_M3,
    "平台高差h1(m)": COL_COMPOUND_H1,
    "直墙高度H直(m)": COL_ARCH_H_STRAIGHT,
    "拉杆高度(m)": COL_TIE_ROD_HEIGHT,
    "泄水渠入口宽度(m)": COL_SPILLWAY_INLET_WEIR_WIDTH,
    "泄水渠堰上总水头(m)": COL_SPILLWAY_INLET_HEAD,
    "泄水渠入口连接形式": COL_SPILLWAY_INLET_CONNECTION_TYPE,
    "泄水渠手动流量系数": COL_SPILLWAY_WEIR_COEFFICIENT,
    "泄水渠侧收缩系数": COL_SPILLWAY_CONTRACTION_COEFFICIENT,
    "泄水渠动能修正系数": COL_SPILLWAY_ALPHA_PROFILE,
    "泄水渠掺气系数": COL_SPILLWAY_AERATION_COEFFICIENT,
    "泄水渠侧墙安全超高(m)": COL_SPILLWAY_SIDEWALL_FREEBOARD,
    "泄水渠池深系数": COL_SPILLWAY_POOL_DEPTH_FACTOR,
    "泄水渠整流长度系数": COL_SPILLWAY_OUTLET_RECTIFICATION_FACTOR,
}

def _excel_header_mapping(header_values):
    """按表头建立 Excel 源列到当前输入表列的映射。"""
    mapping = {}
    for src_idx, header in enumerate(header_values):
        target_idx = _EXCEL_HEADER_ALIASES.get(_canonical_excel_header(header))
        if target_idx is not None and target_idx not in mapping.values():
            mapping[src_idx] = target_idx
    required = {COL_SEQ, COL_SECTION_TYPE, COL_Q}
    if not required.issubset(set(mapping.values())):
        return {}
    return mapping

def _map_excel_row_by_headers(row_values, header_mapping):
    """把 Excel 行按表头映射为当前输入表结构。"""
    mapped = [""] * len(INPUT_HEADERS)
    for src_idx, target_idx in header_mapping.items():
        if src_idx < len(row_values):
            mapped[target_idx] = row_values[src_idx]
    return mapped

def _map_input_row_by_header_order(row_values, source_headers):
    """按源表头顺序把一行输入数据重排为当前输入表结构。"""
    mapped = [""] * len(INPUT_HEADERS)
    if not source_headers:
        return mapped
    for src_idx, header in enumerate(source_headers):
        target_idx = _EXCEL_HEADER_ALIASES.get(_canonical_excel_header(header))
        if target_idx is not None and src_idx < len(row_values):
            mapped[target_idx] = row_values[src_idx]
    return mapped

def _extract_spillway_steep_chute_advanced_params(values) -> dict:
    """从批量输入行提取泄水渠与陡坡专项可选参数。"""
    values = list(values or [])
    advanced = {}
    for key, col in SPILLWAY_STEEP_CHUTE_ADVANCED_COLUMN_MAP:
        if col >= len(values):
            continue
        raw = values[col]
        if raw is None or str(raw).strip() == "":
            continue
        if key in SPILLWAY_STEEP_CHUTE_ADVANCED_NUMERIC_KEYS:
            try:
                advanced[key] = float(raw)
            except (TypeError, ValueError):
                advanced[key] = str(raw).strip()
        else:
            advanced[key] = str(raw).strip()
    return advanced

RESULT_HEADERS = [
    "序号", "流量段", "建筑物名称", "结构形式",
    "底宽B(m)", "直径D(m)", "半径R(m)",
    "h设计(m)", "V设计(m/s)", "A设计(m²)", "R水力(m)", "湿周χ(m)",
    "Q加大(m³/s)", "h加大(m)", "V加大(m/s)",
    "加大有效超高Fb(m)", "建筑物总高H(含拉杆)(m)",
    "设计净空高度(m)", "加大净空高度(m)",
    "设计净空比例(%)", "加大净空比例(%)",
    "状态",
]

__all__ = ['_column_index_to_excel_name', 'SECTION_TYPES', 'PRESSURE_PIPE_LIKE_SECTION_TYPES', '_PROJECT_SECTION_TYPE_ALIASES', 'normalize_project_section_type', 'is_pressure_pipe_like_section_type', 'is_spillway_steep_chute_section_type', 'resolve_spillway_steep_chute_display_type', 'is_fill_channel_section_type', 'is_gate_like_section_type', 'is_tunnel_section_type', 'is_rect_culvert_section_type', 'is_arch_culvert_section_type', 'INPUT_HEADERS', '_INPUT_HEADERS_BEFORE_AE_AF_REORDER', '_INPUT_HEADERS_BEFORE_RECT_CULVERT_VISIBLE_COLUMNS', 'COL_SEQ', 'COL_SEGMENT', 'COL_BUILDING_NAME', 'COL_SECTION_TYPE', 'COL_X', 'COL_Y', 'COL_Q', 'COL_N', 'COL_SLOPE', 'COL_M', 'COL_B', 'COL_RECT_CULVERT_HB_RATIO', 'COL_RECT_CULVERT_H', 'COL_BETA', 'COL_R', 'COL_D', 'COL_DUCAO_DEPTH_RATIO', 'COL_TIE_ROD_HEIGHT', 'COL_CHAMFER_ANGLE', 'COL_CHAMFER_LENGTH', 'COL_THETA', 'COL_ARCH_H_STRAIGHT', 'COL_V_MIN', 'COL_V_MAX', 'COL_TURN_RADIUS', 'COL_PIPE_MATERIAL', 'COL_COMPOUND_M1', 'COL_COMPOUND_B1', 'COL_COMPOUND_M2', 'COL_COMPOUND_B2', 'COL_COMPOUND_M3', 'COL_COMPOUND_H1', 'COL_SPILLWAY_INLET_WEIR_WIDTH', 'COL_SPILLWAY_INLET_HEAD', 'COL_SPILLWAY_INLET_CONNECTION_TYPE', 'COL_SPILLWAY_WEIR_COEFFICIENT', 'COL_SPILLWAY_CONTRACTION_COEFFICIENT', 'COL_SPILLWAY_ALPHA_PROFILE', 'COL_SPILLWAY_AERATION_COEFFICIENT', 'COL_SPILLWAY_SIDEWALL_FREEBOARD', 'COL_SPILLWAY_POOL_DEPTH_FACTOR', 'COL_SPILLWAY_OUTLET_RECTIFICATION_FACTOR', 'COL_PIPE_LOCAL_LOSS', 'COL_PIPE_IN_OUT', '_LEGACY_INPUT_HEADER_COUNT_BEFORE_RECT_CULVERT_EXCEL_COLUMNS', '_RECT_CULVERT_MANUAL_H_META_KEY', '_IMPORTED_RATIO_WARNING_TOLERANCE', 'SPILLWAY_STEEP_CHUTE_PARAM_KEY', 'SPILLWAY_STEEP_CHUTE_ADVANCED_COLUMN_MAP', 'SPILLWAY_STEEP_CHUTE_ADVANCED_NUMERIC_KEYS', '_canonical_excel_header', '_EXCEL_HEADER_ALIASES', '_excel_header_mapping', '_map_excel_row_by_headers', '_map_input_row_by_header_order', '_extract_spillway_steep_chute_advanced_params', 'RESULT_HEADERS']
