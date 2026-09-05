"""从无压计算快照筛选逐底坡规格，供结果汇总、管径筛选及交叉表共用。"""

import math
from collections import defaultdict

from .unpressurized_comparison import FLOW_BASES


def _finite(value):
    """检查快照数值完整性，避免缺失或非有限值被视为通过。"""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def row_verdict(row):
    """分别判断模型可解、项目条件满足、能力不足及待核查。"""
    if row is None:
        return False, "待核查：缺少工况结果"
    if row.get("status") == "能力不足":
        return False, "能力不足"
    if row.get("status") != "可形成均匀流" or not _finite(row.get("depth")):
        return False, "待核查：" + (row.get("reason") or "求解失败或结果不完整")
    checked = False
    failures = []
    for limit, actual, name in (("height_limit", "clearance_height", "净空高度"),
                                ("area_limit", "clearance_area", "净空面积")):
        threshold = row.get(limit)
        if threshold is None:
            continue
        checked = True
        if not _finite(threshold) or not _finite(row.get(actual)):
            return False, f"待核查：{name}结果不完整"
        if row[actual] < threshold:
            failures.append(name + "不足")
    return (False, "、".join(failures)) if failures else (True, "满足所设条件" if checked else "模型可解")


def has_increased_flow(rows):
    """依据已保存的实际流量识别加大工况，不臆测旧项目开关。"""
    return any(row["basis"] == FLOW_BASES[1] and row["flow"] > row["design_flow"] for row in rows)


def selection_summary(rows, *, both=True, denominator=None):
    """按每档底坡筛选最小可用已扫描内径，同时保留所有失败和缺失原因。"""
    grouped = defaultdict(dict)
    representatives = {}
    for row in rows:
        grouped[(row["diameter"], row["denominator"])][row["basis"]] = row
        representatives[row["diameter"]] = row
    slopes = sorted({r["denominator"] for r in rows if denominator is None or r["denominator"] == denominator})
    diameters = sorted(representatives)
    increased = has_increased_flow(rows)
    required = FLOW_BASES if both and increased else FLOW_BASES[:1]
    cells, summaries = {}, []
    for slope in slopes:
        for diameter in diameters:
            by_basis = grouped[(diameter, slope)]
            verdicts = {basis: row_verdict(by_basis.get(basis)) for basis in FLOW_BASES}
            passed = all(verdicts[basis][0] for basis in required)
            failures = [f"{basis}：{verdicts[basis][1]}" for basis in required if not verdicts[basis][0]]
            label = ("满足所设条件" if any(verdicts[b][1] == "满足所设条件" for b in required)
                     else "模型可解") if passed else "；".join(failures)
            cells[(diameter, slope)] = dict(passed=passed, label=label, verdicts=verdicts)
        available = [d for d in diameters if cells[(d, slope)]["passed"]]
        selected = min(available) if available else None
        pending_smaller = selected is not None and any(
            "待核查" in cells[(d, slope)]["label"] for d in diameters if d < selected)
        summaries.append(dict(denominator=slope, diameter=selected,
                              pending_smaller=pending_smaller,
                              pending=any("待核查" in cells[(d, slope)]["label"] for d in diameters),
                              reference=selected if selected is not None else (max(diameters) if diameters else None)))
    profiles = {}
    for diameter in diameters:
        selected_cells = [cells[(diameter, slope)] for slope in slopes]
        count = sum(cell["passed"] for cell in selected_cells)
        pending = any("待核查" in cell["label"] for cell in selected_cells)
        label = (f"全部 {len(slopes)} 档可用" if count == len(slopes) and count else
                 f"{count}/{len(slopes)} 档可用" if count else "所选底坡均无已确认可用结果")
        if pending:
            label += "；存在待核查"
        profiles[diameter] = dict(count=count, label=label, row=representatives[diameter])
    return dict(slopes=slopes, diameters=diameters, cells=cells, summaries=summaries,
                profiles=profiles, increased=increased)


def criteria_description(rows):
    """显示快照实际采用的净空条件，防止输入区的新值误用于旧结果。"""
    limits = {(r.get("height_limit"), r.get("area_limit")) for r in rows}
    if not limits or limits == {(None, None)}:
        return "未设置净空条件；可用仅表示模型可解。"
    if len(limits) != 1:
        return "结果含不同净空条件，逐项按各自计算快照判断，请先核对明细。"
    height, area = next(iter(limits))
    parts = []
    if height is not None:
        parts.append(f"净空高度至少 {height:g} m")
    if area is not None:
        parts.append(f"净空面积至少 {area:g}%")
    return "所设条件：" + "；".join(parts) + "。"
