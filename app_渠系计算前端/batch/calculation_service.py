# -*- coding: utf-8 -*-
"""表1批量计算服务：输入快照到结果数据，计算过程不读取或写入控件。"""
from __future__ import annotations
import copy
import datetime
import math
from dataclasses import dataclass
from types import SimpleNamespace
from .schema import *
from . import engines
from app_渠系计算前端.increase_input_helper import (
    calculate_increase_percent_from_q, calculate_q_increased, get_auto_increase_percent,
)
from 推求水面线.shared.shared_data_manager import normalize_section_type_name


@dataclass(frozen=True)
class BatchCalculationRequest:
    """在主线程采集的数据副本；行顺序和导入尺寸标记保持原契约。"""
    rows: tuple
    use_increase: bool = True
    include_details: bool = False
    manual_qmax_by_segment: tuple = ()
    manual_heights: tuple = ()
    imported_rows: tuple = ()


@dataclass
class BatchCalculationOutcome:
    """一次完整计算的结果；过程段保留原始值供界面和报告使用。"""
    batch_results: list
    result_rows: list
    detail_parts: list
    error_details: list
    success_count: int
    fail_count: int
    skip_count: int
    total_count: int


class BatchCalculationService:
    """每次任务独立创建的无界面计算器。"""

    def __init__(self, *, engine_overrides=None, section_calculator=None, row_formatter=None):
        values = {name: getattr(engines, name) for name in engines.ENGINE_NAMES if hasattr(engines, name)}
        values.update(engine_overrides or {})
        self._engines = SimpleNamespace(**values)
        self._section_calculator = section_calculator
        self._row_formatter = row_formatter

    def calculate(self, request: BatchCalculationRequest, token=None) -> BatchCalculationOutcome:
        self._request = request
        self._manual_qmax_by_segment = dict(request.manual_qmax_by_segment)
        input_rows = copy.deepcopy(request.rows)
        batch_results = []
        success_count = 0; fail_count = 0; skip_count = 0; total_count = 0
        error_details = []  # 收集详细错误信息（与原版一致）
        result_rows = []
        detail_lines = []

        detail_lines.append("=" * 80)
        detail_lines.append("          多流量段批量水力计算 - 详细计算过程报告")
        detail_lines.append("=" * 80)
        detail_lines.append(f"计算时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        detail_lines.append(f"总计建筑物数量: {len(input_rows)}")
        detail_lines.append("-" * 80)
        detail_lines.append("")

        for row_idx, values in enumerate(input_rows):
            if token is not None:
                token.raise_if_cancelled()
            values = self._normalize_row(values, len(INPUT_HEADERS))
            raw_section_type = str(values[COL_SECTION_TYPE]).strip()
            section_type = raw_section_type
            mapped_section_type = self._map_section_type(section_type) if section_type else None
            if mapped_section_type:
                section_type = mapped_section_type
                values[COL_SECTION_TYPE] = mapped_section_type
            if not section_type:
                continue
            total_count += 1
            seq = str(values[COL_SEQ]).strip()
            segment = str(values[COL_SEGMENT]).strip()
            building_name = str(values[COL_BUILDING_NAME]).strip()

            try:
                # 倒虹吸占位行
                if section_type == "倒虹吸":
                    row_out = ["-"] * len(RESULT_HEADERS)
                    row_out[0] = seq; row_out[1] = segment; row_out[2] = building_name
                    row_out[3] = "倒虹吸"; row_out[-1] = "⏭ 占位行(不参与计算)"
                    result_rows.append(row_out)
                    pipe_material = str(values[COL_PIPE_MATERIAL]).strip() if len(values) > COL_PIPE_MATERIAL else ""
                    siphon_result = {
                        'success': True, 'section_type': '倒虹吸', 'is_siphon': True,
                        'flow_section': segment, 'building_name': building_name,
                        'coord_X': self._sf(values[COL_X], 0.0), 'coord_Y': self._sf(values[COL_Y], 0.0),
                        'Q': self._sf(values[COL_Q]), 'n': self._sf(values[COL_N], 0.014), 'slope_inv': 0,
                        'D': self._sf(values[COL_D], 0.0),  # 倒虹吸直径D用于水面线窗口默认指定管径
                        'turn_radius': self._sf(values[COL_TURN_RADIUS], 0.0) if len(values) > COL_TURN_RADIUS else 0.0,
                        'pipe_material': pipe_material,
                    }
                    batch_results.append({'input': values, 'result': siphon_result})
                    skip_count += 1
                    if request.include_details:
                        detail_lines.append(f"【项目 {total_count}】")
                        detail_lines.append((values, siphon_result))
                        detail_lines.append("\n" + "*" * 80 + "\n")
                    continue

                # 有压管道同类占位行
                if is_pressure_pipe_like_section_type(section_type):
                    row_out = ["-"] * len(RESULT_HEADERS)
                    row_out[0] = seq; row_out[1] = segment; row_out[2] = building_name
                    row_out[3] = section_type; row_out[-1] = "⏭ 占位行(不参与计算)"
                    result_rows.append(row_out)
                    # 读取有压管道专用列（col 21-23）
                    pipe_material = str(values[COL_PIPE_MATERIAL]).strip() if len(values) > COL_PIPE_MATERIAL else ""
                    local_loss_ratio = self._sf(values[COL_PIPE_LOCAL_LOSS], 0.0) if len(values) > COL_PIPE_LOCAL_LOSS else 0.0
                    in_out_raw = str(values[COL_PIPE_IN_OUT]).strip() if len(values) > COL_PIPE_IN_OUT else ""
                    ppipe_result = {
                        'success': True, 'section_type': section_type, 'is_pressure_pipe': True,
                        'flow_section': segment, 'building_name': building_name,
                        'coord_X': self._sf(values[COL_X], 0.0), 'coord_Y': self._sf(values[COL_Y], 0.0),
                        'Q': self._sf(values[COL_Q]), 'n': self._sf(values[COL_N], 0.0), 'slope_inv': 0,
                        'D': self._sf(values[COL_D], 0.0),  # 直径D用于有压管道同类结构
                        'turn_radius': self._sf(values[COL_TURN_RADIUS], 0.0) if len(values) > COL_TURN_RADIUS else 0.0,
                        'pipe_material': pipe_material,
                        'local_loss_ratio': local_loss_ratio,
                        'in_out_raw': in_out_raw,
                    }
                    batch_results.append({'input': values, 'result': ppipe_result})
                    skip_count += 1
                    if request.include_details:
                        detail_lines.append(f"【项目 {total_count}】")
                        detail_lines.append((values, ppipe_result))
                        detail_lines.append("\n" + "*" * 80 + "\n")
                    continue

                # 泄水渠与陡坡占位行：表1/表2只透传参数，表3按同名进出口成组正式计算
                if is_spillway_steep_chute_section_type(section_type):
                    design_q = self._sf(values[COL_Q])
                    if not math.isfinite(design_q) or design_q <= 0:
                        raise ValueError("流量Q必须为大于0的有限数值")
                    use_inc = request.use_increase
                    increase_percent = 0.0
                    manual_qmax = None
                    if use_inc:
                        increase_percent, manual_qmax = self._resolve_manual_increase_percent_for_segment(segment, design_q)
                        if increase_percent is None:
                            increase_percent = get_auto_increase_percent(design_q)
                    increased_q = (
                        manual_qmax if manual_qmax is not None
                        else calculate_q_increased(design_q, increase_percent)
                    )
                    if not math.isfinite(increased_q):
                        raise ValueError("加大流量必须为有限数值")
                    row_out = ["-"] * len(RESULT_HEADERS)
                    row_out[0] = seq; row_out[1] = segment; row_out[2] = building_name
                    row_out[3] = "泄水渠与陡坡"; row_out[-1] = "⏭ 表3专项计算"
                    if use_inc:
                        row_out[12] = f"{increased_q:.3f}"
                    result_rows.append(row_out)
                    display_structure_type = resolve_spillway_steep_chute_display_type(
                        raw_section_type,
                        section_type,
                    )
                    spillway_advanced_params = _extract_spillway_steep_chute_advanced_params(values)
                    spillway_payload = (
                        {"display_structure_type": display_structure_type}
                        if display_structure_type
                        else {}
                    )
                    if spillway_advanced_params:
                        spillway_payload["advanced_params"] = spillway_advanced_params
                    # 运行工况独立于高级参数，表3清空高级输入时仍须保留。
                    spillway_payload["use_increase"] = use_inc
                    spillway_payload["Q_increased"] = increased_q
                    spillway_result = {
                        'success': True,
                        'section_type': '泄水渠与陡坡',
                        'display_structure_type': display_structure_type,
                        'is_spillway_steep_chute': True,
                        'flow_section': segment,
                        'building_name': building_name,
                        'coord_X': self._sf(values[COL_X], 0.0),
                        'coord_Y': self._sf(values[COL_Y], 0.0),
                        'Q': design_q,
                        'use_increase': use_inc,
                        '_use_increase': use_inc,
                        'Q_increased': increased_q,
                        'Q_inc': increased_q,
                        'Q_max': increased_q,
                        'increase_percent': increase_percent,
                        'n': self._sf(values[COL_N], 0.014),
                        'slope_inv': self._sf(values[COL_SLOPE], 0.0),
                        'm': self._sf(values[COL_M], 0.0),
                        'b': self._sf(values[COL_B], 0.0),
                        'B': self._sf(values[COL_B], 0.0),
                        'turn_radius': self._sf(values[COL_TURN_RADIUS], 0.0) if len(values) > COL_TURN_RADIUS else 0.0,
                        SPILLWAY_STEEP_CHUTE_PARAM_KEY: spillway_payload,
                    }
                    if manual_qmax is not None:
                        spillway_result['manual_qmax_from_excel'] = manual_qmax
                    batch_results.append({'input': values, 'result': spillway_result})
                    skip_count += 1
                    if request.include_details:
                        detail_lines.append(f"【项目 {total_count}】")
                        detail_lines.append((values, spillway_result))
                        detail_lines.append("\n" + "*" * 80 + "\n")
                    continue

                # 闸·分水类占位行（分水闸/分水口/节制闸/泄水闸等）
                if "闸" in section_type or "分水" in section_type:
                    row_out = ["-"] * len(RESULT_HEADERS)
                    row_out[0] = seq; row_out[1] = segment; row_out[2] = building_name
                    row_out[3] = section_type; row_out[-1] = f"⏭ {section_type}(不参与断面计算)"
                    result_rows.append(row_out)
                    gate_result = {
                        'success': True, 'section_type': section_type, 'is_diversion_gate': True,
                        'flow_section': segment, 'building_name': building_name,
                        'coord_X': self._sf(values[COL_X], 0.0), 'coord_Y': self._sf(values[COL_Y], 0.0),
                        'Q': self._sf(values[COL_Q]), 'n': self._sf(values[COL_N], 0.014), 'slope_inv': 0,
                        'turn_radius': self._sf(values[COL_TURN_RADIUS], 0.0) if len(values) > COL_TURN_RADIUS else 0.0,
                    }
                    batch_results.append({'input': values, 'result': gate_result})
                    skip_count += 1
                    if request.include_details:
                        detail_lines.append(f"【项目 {total_count}】")
                        detail_lines.append((values, gate_result))
                        detail_lines.append("\n" + "*" * 80 + "\n")
                    continue

                # 解析输入参数
                Q = self._sf(values[COL_Q])
                n = self._sf(values[COL_N], 0.0)
                slope_inv = self._sf(values[COL_SLOPE])
                m = self._sf(values[COL_M], 0)
                b = self._sf(values[COL_B], 0)
                beta = self._sf(values[COL_BETA], 0)
                rect_hb_ratio = self._sf(values[COL_RECT_CULVERT_HB_RATIO], 0)
                R = self._sf(values[COL_R], 0)
                D = self._sf(values[COL_D], 0)
                ducao_depth_ratio = self._sf(values[COL_DUCAO_DEPTH_RATIO], 0)
                chamfer_angle = self._sf(values[COL_CHAMFER_ANGLE], 0)
                chamfer_length = self._sf(values[COL_CHAMFER_LENGTH], 0)
                theta_deg = self._sf(values[COL_THETA], 0)
                normalized_section_type = normalize_section_type_name(section_type)
                manual_H_rect = None
                rect_h_text = str(values[COL_RECT_CULVERT_H]).strip() if len(values) > COL_RECT_CULVERT_H else ""
                if rect_h_text:
                    try:
                        manual_H_rect = float(rect_h_text)
                    except ValueError as exc:
                        raise ValueError("矩形暗涵指定高度 H 输入无效") from exc
                else:
                    manual_H_rect = self._get_rect_culvert_manual_h(row_idx)
                if is_rect_culvert_section_type(normalized_section_type) and manual_H_rect is not None:
                    if manual_H_rect <= 0:
                        raise ValueError("矩形暗涵指定高度 H 必须大于0")
                    if b <= 0:
                        raise ValueError("填写高度 H 时必须同时填写底宽 B")
                    if beta > 0:
                        raise ValueError("填写高度 H 时不能同时填写宽深比 β")
                    if rect_hb_ratio > 0:
                        raise ValueError("填写高度 H 时不能同时填写高宽比 H/B")
                if is_rect_culvert_section_type(normalized_section_type) and beta > 0 and rect_hb_ratio > 0:
                    raise ValueError("宽深比 β 与高宽比 H/B 不能同时指定")
                manual_H_straight = None
                h_straight_text = (
                    str(values[COL_ARCH_H_STRAIGHT]).strip()
                    if len(values) > COL_ARCH_H_STRAIGHT and values[COL_ARCH_H_STRAIGHT] is not None
                    else ""
                )
                if h_straight_text:
                    try:
                        manual_H_straight = float(h_straight_text)
                    except ValueError as exc:
                        raise ValueError("直墙高度 H直 输入无效") from exc
                    if manual_H_straight < 0:
                        raise ValueError("直墙高度 H直 不能为负数")
                    if normalized_section_type in {"隧洞-圆拱直墙型", "暗涵-圆拱直墙型"} and b <= 0:
                        raise ValueError("填写直墙高度 H直 时必须同时填写底宽 B")
                tie_rod_height = None
                tie_rod_text = (
                    str(values[COL_TIE_ROD_HEIGHT]).strip()
                    if len(values) > COL_TIE_ROD_HEIGHT and values[COL_TIE_ROD_HEIGHT] is not None
                    else ""
                )
                if tie_rod_text and "渡槽" in normalized_section_type:
                    try:
                        tie_rod_height = float(tie_rod_text)
                    except ValueError as exc:
                        raise ValueError("拉杆高度输入无效") from exc
                    if tie_rod_height < 0:
                        raise ValueError("拉杆高度不能为负数")
                m1 = self._sf(values[COL_COMPOUND_M1], 0)
                B1 = self._sf(values[COL_COMPOUND_B1], 0)
                m2 = self._sf(values[COL_COMPOUND_M2], 0)
                B2 = self._sf(values[COL_COMPOUND_B2], 0)
                m3 = self._sf(values[COL_COMPOUND_M3], 0)
                h1 = self._sf(values[COL_COMPOUND_H1], 0)
                v_min = self._sf(values[COL_V_MIN], 0.1)
                v_max = self._sf(values[COL_V_MAX], 100)

                if Q <= 0: raise ValueError("流量Q必须大于0")
                if n <= 0: raise ValueError("糙率n必须大于0")
                if slope_inv <= 0: raise ValueError("比降必须大于0")

                # 计算分发
                use_inc = request.use_increase
                manual_increase_percent = 0 if not use_inc else None
                manual_qmax = None
                if use_inc:
                    manual_increase_percent, manual_qmax = self._resolve_manual_increase_percent_for_segment(segment, Q)
                preserve_explicit_bottom_width = self._should_preserve_explicit_bottom_width(
                    section_type, b
                )
                preserve_imported_dimensions = self._should_preserve_imported_dimensions(
                    row_idx, section_type, b
                )
                result = (self._section_calculator or self._calculate_single)(
                    section_type, Q, n, slope_inv, v_min, v_max,
                    m=m, b=b, beta=beta, R=R, D=D,
                    m1=m1, B1=B1, m2=m2, B2=B2, m3=m3, h1=h1,
                    ducao_depth_ratio=ducao_depth_ratio,
                    chamfer_angle=chamfer_angle, chamfer_length=chamfer_length,
                    theta_deg=theta_deg,
                    manual_H_straight=manual_H_straight,
                    manual_H=manual_H_rect,
                    target_HB_ratio=rect_hb_ratio if rect_hb_ratio > 0 else None,
                    tie_rod_height=tie_rod_height,
                    manual_increase_percent=manual_increase_percent,
                    preserve_explicit_bottom_width=preserve_explicit_bottom_width,
                    preserve_imported_dimensions=preserve_imported_dimensions,
                )
                if result:
                    result['_use_increase'] = use_inc
                    result['section_type'] = section_type
                    if is_fill_channel_section_type(section_type):
                        if b > 0:
                            result['B'] = b
                        result['m'] = m
                    if manual_qmax is not None and result.get('success'):
                        result['manual_qmax_from_excel'] = manual_qmax
                        result['Q_increased'] = manual_qmax
                        result['Q_inc'] = manual_qmax

                if result and result.get('success'):
                    row_out = (self._row_formatter or self._extract_result_row)(seq, segment, building_name, section_type, result,
                                                       use_increase=result.get('_use_increase', True))
                    result_rows.append(row_out)
                    batch_results.append({'input': values, 'result': result})
                    success_count += 1
                    # 详细报告
                    if request.include_details:
                        detail_lines.append(f"【项目 {total_count}】 {building_name} ({section_type})")
                        detail_lines.append((values, result))
                        detail_lines.append("\n" + "*" * 80 + "\n")
                else:
                    err = result.get('error_message', '计算失败') if result else '计算失败'
                    if "计算失败" in err:
                        error_details.append(f"序号{seq} ({building_name}): {err}")
                    row_out = ["-"] * len(RESULT_HEADERS)
                    row_out[0] = seq; row_out[1] = segment; row_out[2] = building_name
                    row_out[3] = section_type; row_out[-1] = f"✗ {err}"
                    result_rows.append(row_out)
                    fail_count += 1

            except Exception as e:
                row_out = ["-"] * len(RESULT_HEADERS)
                row_out[0] = seq; row_out[1] = segment; row_out[2] = building_name
                row_out[3] = section_type; row_out[-1] = f"错误: {str(e)}"
                result_rows.append(row_out)
                error_details.append(f"序号{seq} ({building_name or '-'}): {str(e)}")
                fail_count += 1

        if token is not None:
            token.raise_if_cancelled()
        return BatchCalculationOutcome(batch_results, result_rows, detail_lines, error_details,
                                       success_count, fail_count, skip_count, total_count)

    def _get_rect_culvert_manual_h(self, row_idx):
        return self._request.manual_heights[row_idx] if row_idx < len(self._request.manual_heights) else None

    def _should_preserve_imported_dimensions(self, row_idx, section_type, b_value):
        return (b_value > 0 and "渡槽-矩形" in section_type
                and row_idx < len(self._request.imported_rows) and self._request.imported_rows[row_idx])

    def _calculate_single(self, section_type, Q, n, slope_inv, v_min, v_max, *,
                          m=0, b=0, beta=0, R=0, D=0,
                          m1=0, B1=0, m2=0, B2=0, m3=0, h1=0,
                          ducao_depth_ratio=0, chamfer_angle=0, chamfer_length=0, theta_deg=0,
                          manual_H=None,
                          manual_H_rect=None,
                          target_HB_ratio=None,
                          manual_H_straight=None,
                          tie_rod_height=None,
                          manual_increase_percent=None,
                          preserve_explicit_bottom_width=False,
                          preserve_imported_dimensions=False):
        """根据断面类型调用对应计算引擎"""
        section_type = normalize_section_type_name(section_type)
        _inc = manual_increase_percent
        if "明渠-梯形" in section_type:
            if not self._engines.MINGQU_AVAILABLE: return {'success': False, 'error_message': '明渠计算模块未加载'}
            return self._engines.mingqu_calculate(Q=Q, m=m, n=n, slope_inv=slope_inv,
                                    v_min=v_min, v_max=v_max,
                                    manual_b=b if b > 0 else None,
                                    manual_beta=beta if beta > 0 else None,
                                    manual_increase_percent=_inc,
                                    preserve_manual_b=preserve_explicit_bottom_width)
        elif "明渠-复式梯形" in section_type:
            if not self._engines.MINGQU_AVAILABLE: return {'success': False, 'error_message': '明渠计算模块未加载'}
            return self._engines.mingqu_compound_calculate(
                Q=Q, m1=m1, B1=B1, m2=m2, B2=B2, m3=m3, h1=h1,
                n=n, slope_inv=slope_inv,
                v_min=v_min, v_max=v_max,
                manual_increase_percent=_inc
            )
        elif "明渠-矩形" in section_type or is_fill_channel_section_type(section_type):
            if not self._engines.MINGQU_AVAILABLE: return {'success': False, 'error_message': '明渠计算模块未加载'}
            return self._engines.mingqu_calculate(Q=Q, m=m if is_fill_channel_section_type(section_type) else 0, n=n, slope_inv=slope_inv,
                                    v_min=v_min, v_max=v_max,
                                    manual_b=b if b > 0 else None,
                                    manual_beta=beta if beta > 0 else None,
                                    manual_increase_percent=_inc,
                                    preserve_manual_b=preserve_explicit_bottom_width)
        elif "明渠-圆形" in section_type:
            if not self._engines.MINGQU_AVAILABLE: return {'success': False, 'error_message': '明渠计算模块未加载'}
            return self._engines.circular_calculate(Q=Q, n=n, slope_inv=slope_inv,
                                      v_min=v_min, v_max=v_max,
                                      manual_D=D if D > 0 else None,
                                      increase_percent=_inc)
        elif "明渠-U形" in section_type:
            if not self._engines.MINGQU_AVAILABLE: return {'success': False, 'error_message': '明渠计算模块未加载'}
            if R <= 0:
                return {'success': False, 'error_message': '明渠-U形需要填写半径R（列索徕12）'}
            return self._engines.mingqu_u_calculate(Q=Q, R=R, alpha_deg=chamfer_angle, theta_deg=theta_deg,
                                      n=n, slope_inv=slope_inv,
                                      v_min=v_min, v_max=v_max,
                                      manual_increase_percent=_inc)
        elif "渡槽-U形" in section_type:
            if not self._engines.DUCAO_AVAILABLE: return {'success': False, 'error_message': '渡槽计算模块未加载'}
            return self._engines.ducao_u_calculate(Q=Q, n=n, slope_inv=slope_inv,
                                     v_min=v_min, v_max=v_max,
                                     manual_R=R if R > 0 else None,
                                     tie_rod_height=tie_rod_height,
                                     manual_increase_percent=_inc)
        elif "渡槽-矩形" in section_type:
            if not self._engines.DUCAO_AVAILABLE: return {'success': False, 'error_message': '渡槽计算模块未加载'}
            if preserve_imported_dimensions:
                dr = ducao_depth_ratio if ducao_depth_ratio > 0 else None
                result = self._engines.ducao_rect_calculate(Q=Q, n=n, slope_inv=slope_inv,
                                              v_min=v_min, v_max=v_max,
                                              depth_width_ratio=dr,
                                              chamfer_angle=chamfer_angle, chamfer_length=chamfer_length,
                                              manual_increase_percent=_inc,
                                              tie_rod_height=tie_rod_height,
                                              manual_B=b if b > 0 else None)
                return self._annotate_rect_aqueduct_imported_b_result(result, b, ducao_depth_ratio)
            dr = ducao_depth_ratio if ducao_depth_ratio > 0 else 0.8
            return self._engines.ducao_rect_calculate(Q=Q, n=n, slope_inv=slope_inv,
                                        v_min=v_min, v_max=v_max,
                                        depth_width_ratio=dr,
                                        chamfer_angle=chamfer_angle, chamfer_length=chamfer_length,
                                        tie_rod_height=tie_rod_height,
                                        manual_increase_percent=_inc)
        elif "隧洞-平底圆形" in section_type:
            if not self._engines.SUIDONG_AVAILABLE: return {'success': False, 'error_message': '隙洞计算模块未加载'}
            return self._engines.suidong_flat_bottom_circular_calculate(Q=Q, n=n, slope_inv=slope_inv,
                                                          v_min=v_min, v_max=v_max,
                                                          manual_D=D if D > 0 else None,
                                                          manual_B=b if b > 0 else None,
                                                          manual_increase_percent=_inc)
        elif "隧洞-圆形" in section_type:
            if not self._engines.SUIDONG_AVAILABLE: return {'success': False, 'error_message': '隙洞计算模块未加载'}
            return self._engines.suidong_circular_calculate(Q=Q, n=n, slope_inv=slope_inv,
                                              v_min=v_min, v_max=v_max,
                                              manual_D=D if D > 0 else None,
                                              manual_increase_percent=_inc)
        elif "隧洞-圆拱直墙型" in section_type:
            if not self._engines.SUIDONG_AVAILABLE: return {'success': False, 'error_message': '隙洞计算模块未加载'}
            return self._engines.suidong_horseshoe_calculate(Q=Q, n=n, slope_inv=slope_inv,
                                               v_min=v_min, v_max=v_max,
                                               manual_B=b if b > 0 else None,
                                               theta_deg=theta_deg if theta_deg > 0 else None,
                                               manual_H_straight=manual_H_straight,
                                               manual_increase_percent=_inc)
        elif "隧洞-马蹄形" in section_type:
            if not self._engines.SUIDONG_AVAILABLE: return {'success': False, 'error_message': '隙洞计算模块未加载'}
            st = 2 if "Ⅱ型" in section_type else 1
            return self._engines.suidong_horseshoe_std_calculate(Q=Q, n=n, slope_inv=slope_inv,
                                                    v_min=v_min, v_max=v_max,
                                                    manual_r=R if R > 0 else None,
                                                    section_type=st,
                                                    manual_increase_percent=_inc)
        elif is_arch_culvert_section_type(section_type):
            if not self._engines.ARCH_CULVERT_AVAILABLE: return {'success': False, 'error_message': '圆拱直墙型暗涵模块未加载'}
            return self._engines.arch_culvert_calculate(Q=Q, n=n, slope_inv=slope_inv,
                                          v_min=v_min, v_max=v_max,
                                          manual_B=b if b > 0 else None,
                                          theta_deg=theta_deg if theta_deg > 0 else None,
                                          manual_H_straight=manual_H_straight,
                                          manual_increase_percent=_inc)
        elif is_rect_culvert_section_type(section_type):
            if not self._engines.RECT_CULVERT_AVAILABLE: return {'success': False, 'error_message': '矩形暗涵模块未加载'}
            fixed_H = manual_H if manual_H is not None else manual_H_rect
            return self._engines.rect_culvert_calculate(Q=Q, n=n, slope_inv=slope_inv,
                                          v_min=v_min, v_max=v_max,
                                          manual_B=b if b > 0 else None,
                                          manual_H=fixed_H if fixed_H is not None and fixed_H > 0 else None,
                                          target_BH_ratio=beta if beta > 0 else None,
                                          target_HB_ratio=target_HB_ratio if target_HB_ratio is not None and target_HB_ratio > 0 else None,
                                          manual_increase_percent=_inc)
        else:
            return {'success': False, 'error_message': f'不支持的断面类型: {section_type}'}

    def _extract_result_row(self, seq, segment, building_name, section_type, result, use_increase=True):
        """从计算结果中提取关键数据为一行"""
        section_type = normalize_section_type_name(section_type)
        def fmt(val, default="-"):
            if val is None or val == 0: return default
            if isinstance(val, (int, float)): return f"{val:.3f}"
            return str(val)
        def fmt_pct(val, default="-"):
            if val is None or val == 0: return default
            if isinstance(val, (int, float)): return f"{val:.1f}"
            return str(val)

        B_val = D_val = R_val = "-"
        h_design = V_design = A_design = R_hyd = chi = "-"
        Q_inc = h_inc = V_inc = "-"
        Fb_surcharge = H_total_val = "-"
        Fb_cl_d = Fb_cl_i = Fb_pct_d = Fb_pct_i = "-"

        if "明渠" in section_type or is_fill_channel_section_type(section_type):
            if "圆形" in section_type:
                D_val = result.get('D_design', result.get('D', 0))
            elif "U形" in section_type:
                R_val = result.get('R', 0)
            else:
                B_val = result.get('b_design', result.get('B', 0))
            h_design = result.get('h_design', result.get('y_d', 0))
            V_design = result.get('V_design', result.get('V_d', 0))
            A_design = result.get('A_design', result.get('A_d', 0))
            R_hyd = result.get('R_design', result.get('R_d', 0))
            chi = result.get('X_design', result.get('P_d', 0))
            Q_inc = result.get('Q_increased', result.get('Q_inc', 0))
            h_inc = result.get('h_increased', result.get('y_i', 0))
            V_inc = result.get('V_increased', result.get('V_i', 0))
            if "圆形" in section_type:
                Fb_surcharge = result.get('FB_d', 0)
                Fb_cl_d = result.get('FB_d', 0)
                Fb_cl_i = result.get('FB_i', 0)
                Fb_pct_d = result.get('PA_d', "-")
                Fb_pct_i = result.get('PA_i', "-")
                H_total_val = result.get('D', result.get('D_design', 0))
            else:
                Fb_surcharge = result.get('Fb', result.get('FB_d', 0))
                H_total_val = result.get('h_prime', 0)

        elif "渡槽" in section_type:
            if "U形" in section_type:
                R_val = result.get('R', 0)
            else:
                B_val = result.get('B', 0)
            h_design = result.get('h_design', 0)
            V_design = result.get('V_design', 0)
            A_design = result.get('A_design', 0)
            R_hyd = result.get('R_hyd_design', 0)
            chi = result.get('P_design', 0)
            Q_inc = result.get('Q_increased', 0)
            h_inc = result.get('h_increased', 0)
            V_inc = result.get('V_increased', 0)
            Fb_surcharge = result.get('Fb', 0)
            H_total_val = result.get('H_total', 0)

        elif "隧洞" in section_type:
            if "平底圆形" in section_type:
                B_val = result.get('B', 0)
                D_val = result.get('D', result.get('D_design', 0))
            elif "圆形" in section_type:
                D_val = result.get('D', result.get('D_design', 0))
            elif "圆拱直墙型" in section_type:
                B_val = result.get('B', 0)
            elif "马蹄形" in section_type:
                R_val = result.get('r', 0)
            h_design = result.get('h_design', result.get('y_d', 0))
            V_design = result.get('V_design', result.get('V_d', 0))
            A_design = result.get('A_design', result.get('A_d', 0))
            R_hyd = result.get('R_hyd_design', result.get('R_d', 0))
            chi = result.get('P_design', result.get('P_d', 0))
            Q_inc = result.get('Q_increased', result.get('Q_inc', 0))
            h_inc = result.get('h_increased', result.get('y_i', 0))
            V_inc = result.get('V_increased', result.get('V_i', 0))
            if "平底圆形" in section_type:
                H_total_val = result.get('H_total', 0)
            elif "圆形" in section_type:
                H_total_val = result.get('D', result.get('D_design', 0))
            elif "马蹄形" in section_type:
                r_v = result.get('r', 0)
                H_total_val = 2 * r_v if r_v else 0
            else:
                H_total_val = result.get('H_total', 0)
            Fb_cl_d = result.get('freeboard_hgt_design', result.get('FB_d', 0))
            Fb_cl_i = result.get('freeboard_hgt_inc', result.get('FB_i', 0))
            Fb_pct_d = result.get('freeboard_pct_design', 0)
            Fb_pct_i = result.get('freeboard_pct_inc', 0)

        elif is_arch_culvert_section_type(section_type):
            B_val = result.get('B', 0)
            h_design = result.get('h_design', 0)
            V_design = result.get('V_design', 0)
            A_design = result.get('A_design', 0)
            R_hyd = result.get('R_hyd_design', 0)
            chi = result.get('P_design', 0)
            Q_inc = result.get('Q_increased', 0)
            h_inc = result.get('h_increased', 0)
            V_inc = result.get('V_increased', 0)
            H_total_val = result.get('H_total', 0)
            Fb_cl_d = result.get('freeboard_hgt_design', 0)
            Fb_cl_i = result.get('freeboard_hgt_inc', 0)
            Fb_pct_d = result.get('freeboard_pct_design', 0)
            Fb_pct_i = result.get('freeboard_pct_inc', 0)

        elif is_rect_culvert_section_type(section_type):
            B_val = result.get('B', 0)
            h_design = result.get('h_design', 0)
            V_design = result.get('V_design', 0)
            A_design = result.get('A_design', 0)
            R_hyd = result.get('R_hyd_design', 0)
            chi = result.get('P_design', 0)
            Q_inc = result.get('Q_increased', 0)
            h_inc = result.get('h_increased', 0)
            V_inc = result.get('V_increased', 0)
            H_total_val = result.get('H', result.get('H_total', 0))
            Fb_cl_d = result.get('freeboard_hgt_design', 0)
            Fb_cl_i = result.get('freeboard_hgt_inc', 0)
            Fb_pct_d = result.get('freeboard_pct_design', 0)
            Fb_pct_i = result.get('freeboard_pct_inc', 0)

        if not use_increase:
            Q_inc = h_inc = V_inc = "—"
            Fb_surcharge = "—"
            Fb_cl_i = Fb_pct_i = "—"

        status_text = "✓ 成功"
        if result.get('preserved_manual_b') and result.get('constraint_warnings'):
            status_text = "⚠ 按显式底宽计算" if ("明渠" in section_type or is_fill_channel_section_type(section_type)) else "⚠ 按导入尺寸计算"

        return [seq, segment, building_name, section_type,
                fmt(B_val), fmt(D_val), fmt(R_val),
                fmt(h_design), fmt(V_design), fmt(A_design), fmt(R_hyd), fmt(chi),
                Q_inc if Q_inc == "—" else fmt(Q_inc),
                h_inc if h_inc == "—" else fmt(h_inc),
                V_inc if V_inc == "—" else fmt(V_inc),
                fmt(Fb_surcharge), fmt(H_total_val),
                fmt(Fb_cl_d),
                Fb_cl_i if Fb_cl_i == "—" else fmt(Fb_cl_i),
                fmt_pct(Fb_pct_d),
                Fb_pct_i if Fb_pct_i == "—" else fmt_pct(Fb_pct_i),
                status_text]

    def _map_section_type(self, raw_type):
        """将粘贴的断面类型简写映射为有效类型（与原版一致）"""
        raw_type = normalize_section_type_name(raw_type)
        mapping = {
            "梯形": "明渠-梯形", "复式梯形": "明渠-复式梯形", "矩形": "明渠-矩形", "圆形": "明渠-圆形",
            "明渠U形": "明渠-U形", "U形明渠": "明渠-U形",
            "U形": "渡槽-U形", "U形渡槽": "渡槽-U形", "矩形渡槽": "渡槽-矩形",
            "平底圆形": "隧洞-平底圆形", "平底圆形隧洞": "隧洞-平底圆形", "隧洞平底圆形": "隧洞-平底圆形",
            "圆形隧洞": "隧洞-圆形", "圆拱直墙": "隧洞-圆拱直墙型", "圆拱直墙型": "隧洞-圆拱直墙型",
            "马蹄形Ⅰ型": "隧洞-马蹄形Ⅰ型", "马蹄形Ⅱ型": "隧洞-马蹄形Ⅱ型",
            "马蹄形I型": "隧洞-马蹄形Ⅰ型", "马蹄形II型": "隧洞-马蹄形Ⅱ型",
            "暗涵": "暗涵-矩形", "暗涵-矩形": "暗涵-矩形", "暗渠": "暗涵-矩形", "矩形暗渠": "暗涵-矩形",
            "矩形暗涵": "暗涵-矩形",
            "暗涵-圆拱直墙型": "暗涵-圆拱直墙型", "圆拱直墙型暗涵": "暗涵-圆拱直墙型",
            "充水渠": "泄水渠与陡坡", "泄水渠": "泄水渠与陡坡", "泄水渠与陡坡": "泄水渠与陡坡",
            "陡坡": "泄水渠与陡坡", "泄槽": "泄水渠与陡坡", "陡槽": "泄水渠与陡坡",
            "泄水渠及陡坡": "泄水渠与陡坡",
            "退水闸": "退水闸",
        }
        if raw_type in mapping:
            return mapping[raw_type]
        if raw_type in SECTION_TYPES:
            return raw_type
        # 模糊匹配
        for key, val in mapping.items():
            if key in raw_type:
                return val
        return None

    def _sf(self, val, default=0.0):
        if not val: return default
        s = str(val).strip()
        if not s: return default
        try: return float(s)
        except ValueError: return default

    def _get_manual_qmax_for_segment(self, segment_value):
        """按流量段编号获取手工 Q加大。"""
        try:
            segment_num = int(str(segment_value).strip())
        except (TypeError, ValueError):
            return None, None
        manual_map = getattr(self, "_manual_qmax_by_segment", {}) or {}
        return segment_num, manual_map.get(segment_num)

    def _resolve_manual_increase_percent_for_segment(self, segment_value, design_q: float):
        """把手工 Q加大 反算为现有内核仍可复用的加大比例。"""
        segment_num, manual_qmax = self._get_manual_qmax_for_segment(segment_value)
        if segment_num is None or manual_qmax is None:
            return None, None
        if manual_qmax < design_q:
            raise ValueError(
                f"第{segment_num}段手工Q加大({manual_qmax:.3f})不能小于设计流量 Q({design_q:.3f})"
            )
        if math.isclose(manual_qmax, design_q, rel_tol=1e-9, abs_tol=1e-9):
            return 0.0, manual_qmax
        return calculate_increase_percent_from_q(design_q, manual_qmax), manual_qmax

    def _should_preserve_explicit_bottom_width(self, section_type: str, b_value: float) -> bool:
        if b_value <= 0:
            return False
        return "明渠-梯形" in section_type or "明渠-矩形" in section_type or is_fill_channel_section_type(section_type)

    def _annotate_rect_aqueduct_imported_b_result(self, result: dict, manual_b: float, imported_ratio: float):
        if not isinstance(result, dict):
            return result

        imported_ratio_val = imported_ratio if imported_ratio and imported_ratio > 0 else None
        result['imported_depth_width_ratio'] = imported_ratio_val
        result.setdefault('constraint_warnings', [])

        if not result.get('success'):
            result.setdefault('used_manual_b', False)
            result.setdefault('preserved_manual_b', False)
            return result

        result['used_manual_b'] = True
        result['preserved_manual_b'] = True

        warnings = list(result.get('constraint_warnings') or [])
        actual_ratio = result.get('depth_width_ratio')
        if (imported_ratio_val is not None
                and isinstance(actual_ratio, (int, float))
                and abs(actual_ratio - imported_ratio_val) > _IMPORTED_RATIO_WARNING_TOLERANCE):
            warnings.append(
                f"导入 H/B={imported_ratio_val:.3f} 仅作参考，已按导入底宽 B={manual_b:.3f} m 锁定计算；"
                f"实际 H/B={actual_ratio:.3f}。"
            )
        result['constraint_warnings'] = warnings
        return result

    def _normalize_row(self, row, length):
        row = list(row) if row else []
        if length == len(INPUT_HEADERS) and len(row) == _LEGACY_INPUT_HEADER_COUNT_BEFORE_RECT_CULVERT_EXCEL_COLUMNS:
            # 旧项目中没有“暗涵高宽比H/B”和“暗涵高度H”两列，同时 H直/拉杆高度仍在末尾。
            row = _map_input_row_by_header_order(row, _INPUT_HEADERS_BEFORE_RECT_CULVERT_VISIBLE_COLUMNS)
        while len(row) < length:
            row.append("")
        return row[:length]

