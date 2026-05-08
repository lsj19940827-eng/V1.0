# -*- coding: utf-8 -*-
"""为明渠、渡槽、隧洞、暗涵生成计算结果顶部重点汇总。"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
import math
import re
from typing import Iterable, List, Sequence


_FREEBOARD_HEIGHT_TOL = 1e-3
_FREEBOARD_PCT_TOL = 0.1


@dataclass(frozen=True)
class SummaryItem:
    """表示汇总卡中的一个指标。"""

    label: str
    value: str
    status: str = ""


@dataclass(frozen=True)
class SummaryGroup:
    """表示汇总卡中的一组指标。"""

    title: str
    items: Sequence[SummaryItem]


def _panel_key(value) -> str:
    """统一面板标识。"""
    return str(value or "").strip().replace("-", "_").lower()


def _num(value):
    """把输入安全转换为浮点数。"""
    try:
        if value is None or value == "":
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _has_positive(value) -> bool:
    """判断数值是否为正数。"""
    number = _num(value)
    return number is not None and number > 0


def _fmt(value, digits=3, unit="") -> str:
    """格式化普通数值。"""
    number = _num(value)
    if number is None:
        return ""
    text = f"{number:.{digits}f}"
    return f"{text} {unit}" if unit else text


def _fmt_m(value) -> str:
    """格式化米单位。"""
    return _fmt(value, 3, "m")


def _fmt_m2(value) -> str:
    """格式化平方米单位。"""
    return _fmt(value, 3, "m²")


def _fmt_flow(value) -> str:
    """格式化流量单位。"""
    return _fmt(value, 3, "m³/s")


def _fmt_velocity(value) -> str:
    """格式化流速单位。"""
    return _fmt(value, 3, "m/s")


def _fmt_pct(value) -> str:
    """格式化百分比。"""
    return _fmt(value, 1, "%")


def _fmt_ratio(value) -> str:
    """格式化无量纲比值。"""
    return _fmt(value, 3, "")


def _height_width_ratio(height, width):
    """按结构总高和宽度计算 H/B。"""
    H = _num(height)
    B = _num(width)
    if H is None or B is None or B <= 0:
        return None
    return H / B


def _bool_or_none(value):
    """读取明确的布尔校核结果。"""
    if isinstance(value, bool):
        return value
    return None


def _item(label: str, value: str, status: str = "") -> SummaryItem | None:
    """创建非空指标项。"""
    value_text = str(value or "").strip()
    if not value_text:
        return None
    return SummaryItem(label, value_text, str(status or "").strip())


def _append(items: list[SummaryItem], label: str, value: str, status: str = ""):
    """向指标列表追加非空项。"""
    one = _item(label, value, status)
    if one is not None:
        items.append(one)


def _use_increase(params: dict) -> bool:
    """判断是否启用加大流量。"""
    return bool(params.get("use_increase", True))


def _has_increase_result(result: dict) -> bool:
    """判断加大工况是否有可展示结果。"""
    return _has_positive(result.get("h_increased")) and _has_positive(result.get("V_increased"))


def _increase_note(params: dict, result: dict) -> str:
    """生成加大工况缺失时的短提示。"""
    if not _use_increase(params):
        return "未启用加大流量"
    if not _has_increase_result(result):
        return "加大工况无可用结果"
    return ""


def _design_group(params: dict, result: dict) -> SummaryGroup:
    """生成设计工况通用指标组。"""
    items: list[SummaryItem] = []
    _append(items, "设计流量 Q", _fmt_flow(params.get("Q")))
    _append(items, "设计水深 h", _fmt_m(result.get("h_design")))
    _append(items, "设计流速 V", _fmt_velocity(result.get("V_design")))
    return SummaryGroup("设计工况", items)


def _increase_group(params: dict, result: dict) -> SummaryGroup | None:
    """生成加大工况通用指标组。"""
    if not _use_increase(params) or not _has_increase_result(result):
        return None
    items: list[SummaryItem] = []
    _append(items, "加大流量 Q加大", _fmt_flow(result.get("Q_increased", params.get("Q"))))
    _append(items, "加大水深 h加大", _fmt_m(result.get("h_increased")))
    _append(items, "加大流速 V加大", _fmt_velocity(result.get("V_increased")))
    return SummaryGroup("加大工况", items)


def _clearance_group(result: dict) -> SummaryGroup | None:
    """生成净空指标组。"""
    items: list[SummaryItem] = []
    _append(items, "设计净空高度", _fmt_m(result.get("freeboard_hgt_design")))
    _append(items, "设计净空比例", _fmt_pct(result.get("freeboard_pct_design")))
    _append(items, "加大净空高度", _fmt_m(result.get("freeboard_hgt_inc")))
    _append(items, "加大净空比例", _fmt_pct(result.get("freeboard_pct_inc")))
    if not items:
        return None
    return SummaryGroup("净空", items)


def _freeboard_group(panel_key: str, params: dict, result: dict) -> SummaryGroup | None:
    """生成超高指标组。"""
    items: list[SummaryItem] = []
    if panel_key == "open_channel":
        h_design = result.get("h_design")
        Fb = result.get("Fb")
        if _use_increase(params) and _has_increase_result(result) and _has_positive(Fb):
            _append(items, "加大渠道超高", _fmt_m(result.get("Fb")))
        elif not _use_increase(params):
            design_fb = _num(Fb)
            if design_fb is None or design_fb <= 0:
                h_design_num = _num(h_design)
                design_fb = 0.25 * h_design_num + 0.2 if h_design_num and h_design_num > 0 else None
            _append(items, "设计渠道超高", _fmt_m(design_fb))
    elif panel_key == "aqueduct":
        h_design = result.get("h_design")
        total_h = result.get("H_total")
        if _has_positive(total_h) and _has_positive(h_design):
            _append(items, "设计槽顶超高", _fmt_m(_num(total_h) - _num(h_design)))
        if _has_positive(result.get("tie_rod_height")):
            design_clearance = result.get("design_tie_bottom_clearance")
            if not _has_positive(design_clearance):
                tie_bottom = _num(result.get("tie_bottom_height"))
                h_design_num = _num(h_design)
                design_clearance = tie_bottom - h_design_num if tie_bottom is not None and h_design_num is not None else None
            _append(items, "设计拉杆底净距", _fmt_m(design_clearance))
        if _use_increase(params) and _has_increase_result(result):
            if _has_positive(result.get("tie_rod_height")):
                _append(items, "加大有效超高", _fmt_m(result.get("increased_tie_bottom_clearance", result.get("Fb"))))
            else:
                _append(items, "加大槽身超高(有效)", _fmt_m(result.get("Fb")))
    if not items:
        return None
    return SummaryGroup("超高", items)


def _open_channel_size_group(params: dict, result: dict) -> SummaryGroup:
    """生成明渠结构尺寸指标组。"""
    stype = str(params.get("section_type", "") or result.get("section_type", "") or "梯形")
    items: list[SummaryItem] = []
    if stype == "复式梯形":
        _append(items, "渠底宽 B2", _fmt_m(params.get("B2")))
        _append(items, "平台宽 B1", _fmt_m(params.get("B1")))
    elif stype == "圆形":
        _append(items, "直径 D", _fmt_m(result.get("D_design", result.get("D"))))
    elif stype == "U形":
        _append(items, "半径 R", _fmt_m(result.get("R")))
        _append(items, "圆心角 θ", _fmt(result.get("theta_deg"), 1, "°"))
        _append(items, "弧底宽 b_arc", _fmt_m(result.get("b_arc")))
    else:
        _append(items, "底宽 B", _fmt_m(result.get("b_design")))
        _append(items, "宽深比 β", _fmt_ratio(result.get("Beta_design")))
    _append(items, "渠道高度 H", _fmt_m(result.get("h_prime")))
    return SummaryGroup("结构尺寸", items)


def _aqueduct_size_group(params: dict, result: dict) -> SummaryGroup:
    """生成渡槽结构尺寸指标组。"""
    stype = str(params.get("section_type", "") or result.get("section_type", "") or "U形")
    items: list[SummaryItem] = []
    if stype == "U形":
        _append(items, "内半径 R", _fmt_m(result.get("R")))
        _append(items, "槽宽 B", _fmt_m(result.get("B")))
        _append(items, "直段高度 f", _fmt_m(result.get("f")))
        _append(items, "槽身总高 H(含拉杆)", _fmt_m(result.get("H_total")))
    else:
        _append(items, "槽宽 B", _fmt_m(result.get("B")))
        _append(items, "槽身总高 H(含拉杆)", _fmt_m(result.get("H_total")))
        B = _num(result.get("B"))
        H = _num(result.get("H_total"))
        _append(items, "H/B", _fmt_ratio((H / B) if B else None))
        if result.get("has_chamfer"):
            _append(items, "倒角角度", _fmt(result.get("chamfer_angle"), 1, "°"))
            _append(items, "倒角底边长", _fmt_m(result.get("chamfer_length")))
    if _has_positive(result.get("tie_rod_height")):
        _append(items, "拉杆自身高度", _fmt_m(result.get("tie_rod_height")))
        _append(items, "拉杆底控制高", _fmt_m(result.get("tie_bottom_height")))
    return SummaryGroup("结构尺寸", items)


def _arch_metrics(result: dict) -> tuple[float | None, float | None]:
    """计算圆拱直墙断面的拱半径和拱高。"""
    B = _num(result.get("B"))
    theta_deg = _num(result.get("theta_deg")) or 180.0
    if not B or B <= 0:
        return None, None
    theta_rad = math.radians(theta_deg)
    sin_half = math.sin(theta_rad / 2.0)
    if abs(sin_half) <= 1e-9:
        return None, None
    r_arch = (B / 2.0) / sin_half
    h_arch = r_arch * (1.0 - math.cos(theta_rad / 2.0))
    return r_arch, h_arch


def _tunnel_size_group(params: dict, result: dict) -> SummaryGroup:
    """生成隧洞结构尺寸指标组。"""
    stype = str(params.get("section_type", "") or result.get("section_type", "") or "圆形")
    items: list[SummaryItem] = []
    if stype == "平底圆形":
        _append(items, "直径 D", _fmt_m(result.get("D")))
        _append(items, "平底宽 B", _fmt_m(result.get("B")))
        _append(items, "总高 H", _fmt_m(result.get("H_total")))
        _append(items, "高宽比 H/B", _fmt_ratio(_height_width_ratio(result.get("H_total"), result.get("B"))))
    elif stype == "圆形":
        _append(items, "直径 D", _fmt_m(result.get("D")))
    elif stype == "圆拱直墙型":
        r_arch, h_arch = _arch_metrics(result)
        _append(items, "底宽 B", _fmt_m(result.get("B")))
        _append(items, "总高 H", _fmt_m(result.get("H_total")))
        _append(items, "高宽比 H/B", _fmt_ratio(_height_width_ratio(result.get("H_total"), result.get("B"))))
        _append(items, "直墙高度 H直", _fmt_m(result.get("H_straight")))
        _append(items, "拱半径 R拱", _fmt_m(r_arch))
        _append(items, "拱高 H拱", _fmt_m(h_arch))
    else:
        _append(items, "半径 r", _fmt_m(result.get("r")))
        _append(items, "等效直径 2r", _fmt_m(result.get("D_equiv")))
    _append(items, "断面总面积 A总", _fmt_m2(result.get("A_total")))
    return SummaryGroup("结构尺寸", items)


def _culvert_size_group(params: dict, result: dict) -> SummaryGroup:
    """生成暗涵结构尺寸指标组。"""
    stype = str(params.get("section_type", "") or result.get("section_type", "") or "矩形")
    items: list[SummaryItem] = []
    if "圆拱直墙" in stype:
        r_arch, h_arch = _arch_metrics(result)
        _append(items, "宽度 B", _fmt_m(result.get("B")))
        _append(items, "总高 H", _fmt_m(result.get("H_total")))
        _append(items, "高宽比 H/B", _fmt_ratio(_height_width_ratio(result.get("H_total"), result.get("B"))))
        _append(items, "直墙高度 H直", _fmt_m(result.get("H_straight")))
        _append(items, "拱顶圆心角 θ", _fmt(result.get("theta_deg"), 1, "°"))
        _append(items, "拱半径 R拱", _fmt_m(r_arch))
        _append(items, "拱高 H拱", _fmt_m(h_arch))
    else:
        _append(items, "宽度 B", _fmt_m(result.get("B")))
        _append(items, "高度 H", _fmt_m(result.get("H")))
        _append(items, "宽深比 β", _fmt_ratio(result.get("BH_ratio")))
        _append(items, "高宽比 H/B", _fmt_ratio(result.get("HB_ratio")))
    _append(items, "断面总面积 A总", _fmt_m2(result.get("A_total")))
    return SummaryGroup("结构尺寸", items)


def _status_group(panel_key: str, params: dict, result: dict) -> SummaryGroup:
    """生成简短校核状态组。"""
    items: list[SummaryItem] = []
    v_min = _num(params.get("v_min"))
    v_max = _num(params.get("v_max"))
    v_design = _num(result.get("V_design"))
    if v_min is not None and v_max is not None and v_design is not None:
        status = "通过" if v_min <= v_design <= v_max else "需注意"
        _append(items, "设计流速校核", f"{_fmt_velocity(v_design)}（{status}）", status)
    if panel_key in {"tunnel", "culvert"}:
        pct_key = "freeboard_pct_inc" if _use_increase(params) and _has_increase_result(result) else "freeboard_pct_design"
        hgt_key = "freeboard_hgt_inc" if _use_increase(params) and _has_increase_result(result) else "freeboard_hgt_design"
        kernel_check = _bool_or_none(result.get("fb_check_passed"))
        if kernel_check is not None:
            status = "通过" if kernel_check else "需注意"
            _append(items, "净空校核", status, status)
        else:
            pct = _num(result.get(pct_key))
            hgt = _num(result.get(hgt_key))
            if pct is not None or hgt is not None:
                min_pct = 15.0 if panel_key == "tunnel" else 10.0
                max_pct = None if panel_key == "tunnel" else 30.0
                pct_ok = pct is None or (
                    pct >= min_pct - _FREEBOARD_PCT_TOL
                    and (max_pct is None or pct <= max_pct + _FREEBOARD_PCT_TOL)
                )
                min_hgt = _num(result.get("fb_min_required")) or 0.4
                hgt_ok = hgt is None or hgt >= min_hgt - _FREEBOARD_HEIGHT_TOL
                status = "通过" if pct_ok and hgt_ok else "需注意"
                _append(items, "净空校核", status, status)
    if panel_key in {"open_channel", "aqueduct"}:
        fb = _num(result.get("Fb"))
        if fb is not None:
            _append(items, "超高校核", "见完整校核过程", "")
    if not items:
        return SummaryGroup("校核状态", [SummaryItem("状态", "见完整计算过程")])
    return SummaryGroup("校核状态", items)


def build_result_summary_groups(panel_key: str, params: dict, result: dict) -> list[SummaryGroup]:
    """生成指定面板的重点结果汇总分组。"""
    if not result or not result.get("success", True):
        return []
    normalized = _panel_key(panel_key)
    params = params or {}
    result = result or {}
    groups: list[SummaryGroup] = [_design_group(params, result)]
    inc_group = _increase_group(params, result)
    if inc_group is not None:
        groups.append(inc_group)
    if normalized == "open_channel":
        groups.extend([_open_channel_size_group(params, result)])
        freeboard = _freeboard_group(normalized, params, result)
        if freeboard:
            groups.append(freeboard)
    elif normalized == "aqueduct":
        groups.extend([_aqueduct_size_group(params, result)])
        freeboard = _freeboard_group(normalized, params, result)
        if freeboard:
            groups.append(freeboard)
    elif normalized == "tunnel":
        groups.extend([_tunnel_size_group(params, result)])
        clearance = _clearance_group(result)
        if clearance:
            groups.append(clearance)
    elif normalized == "culvert":
        groups.extend([_culvert_size_group(params, result)])
        clearance = _clearance_group(result)
        if clearance:
            groups.append(clearance)
    groups.append(_status_group(normalized, params, result))
    return [group for group in groups if group.items]


def _note_html(note: str) -> str:
    """生成短提示 HTML。"""
    if not note:
        return ""
    return (
        '<div style="margin:8px 0 0;padding:8px 10px;border-radius:6px;'
        'background:#fff8e1;border:1px solid #ffe0a3;color:#795548;font-size:12px;">'
        f"{escape(note)}</div>"
    )


def build_result_summary_html(panel_key: str, params: dict, result: dict) -> str:
    """生成可直接嵌入结果详情页的重点汇总 HTML。"""
    groups = build_result_summary_groups(panel_key, params, result)
    if not groups:
        return ""
    note = _increase_note(params or {}, result or {})
    parts = [
        '<div class="codex-result-summary-card" style="margin:0 0 16px 0;'
        'padding:14px 16px;border:1px solid #cfe0f5;border-radius:10px;'
        'background:linear-gradient(180deg,#f8fbff,#ffffff);'
        'box-shadow:0 2px 8px rgba(21,101,192,0.08);'
        'font-family:Microsoft YaHei,Arial,sans-serif;">',
        '<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;'
        'margin-bottom:10px;">',
        '<div style="font-size:16px;font-weight:800;color:#1565c0;">重点结果汇总</div>',
        '<div style="font-size:12px;color:#6b7a90;">用于快速查看，完整过程见下方</div>',
        "</div>",
        '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;">',
    ]
    for group in groups:
        parts.append(
            '<div style="border:1px solid #e3edf9;border-radius:8px;background:#ffffff;'
            'padding:10px 12px;">'
        )
        parts.append(
            f'<div style="font-size:13px;font-weight:700;color:#1f4e79;'
            f'margin-bottom:6px;">{escape(group.title)}</div>'
        )
        for item in group.items:
            status_color = "#2e7d32" if item.status == "通过" else "#c77700" if item.status == "需注意" else "#23374d"
            parts.append(
                '<div style="display:flex;justify-content:space-between;gap:10px;'
                'padding:4px 0;border-top:1px dashed #edf2f7;">'
                f'<span style="font-size:12px;color:#667085;">{escape(item.label)}</span>'
                f'<span style="font-size:13px;font-weight:700;color:{status_color};text-align:right;">'
                f'{escape(item.value)}</span></div>'
            )
        parts.append("</div>")
    parts.extend(["</div>", _note_html(note), "</div>"])
    return "".join(parts)


def build_result_summary_word_items(panel_key: str, params: dict, result: dict) -> list[tuple[str, str]]:
    """生成 Word 二列表格需要的扁平汇总项。"""
    items: list[tuple[str, str]] = []
    for group in build_result_summary_groups(panel_key, params, result):
        for item in group.items:
            items.append((f"{group.title} - {item.label}", item.value))
    note = _increase_note(params or {}, result or {})
    if note:
        items.append(("加大工况 - 状态", note))
    return items


def prepend_result_summary_to_html(panel_key: str, params: dict, result: dict, html: str) -> str:
    """把重点汇总卡插入已有完整 HTML 的 body 顶部。"""
    if not html or "codex-result-summary-card" in html:
        return html
    card = build_result_summary_html(panel_key, params, result)
    if not card:
        return html
    body_match = re.search(r"(<body[^>]*>)", html, flags=re.IGNORECASE)
    if body_match:
        insert_at = body_match.end()
        return html[:insert_at] + card + html[insert_at:]
    return card + html


def prepend_result_summary_to_body(panel_key: str, params: dict, result: dict, body_html: str) -> str:
    """把重点汇总卡插入已有 body 片段顶部。"""
    if body_html and "codex-result-summary-card" in body_html:
        return body_html
    card = build_result_summary_html(panel_key, params, result)
    if not card:
        return body_html
    return card + (body_html or "")
