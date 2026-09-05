"""无压对比的配置、圆管均匀流求解与同流量结果，供批量内核和界面共用。"""

import math
import re
from functools import lru_cache

from scipy.optimize import brentq

STANDARD_SLOPES = (500, 750, 1000, 1500, 2000, 2500, 3000, 3500, 4000)
DEFAULT_ROUGHNESS = 0.014
DEFAULT_RANGE = (500, 4000, 500)
DEFAULT_CLEARANCE_HEIGHT = 0.4
DEFAULT_CLEARANCE_AREA = 15.0
MAX_CUSTOM_SLOPES = 200
FLOW_BASES = ("设计流量", "加大流量")
MODEL_NOTE = "圆管无压均匀流；多解区采用较浅水深支，不包含下游顶托影响。"


def parse_slope_text(text):
    """解析分母列表，保留错误原词供界面指出，重复值只参与一次计算。"""
    tokens = [s for s in re.split(r"[,，、;；\s]+", text.strip()) if s]
    values, invalid, duplicates = set(), [], 0
    for token in tokens:
        if not re.fullmatch(r"[0-9]+", token) or len(token) > 12 or int(token) <= 0:
            invalid.append(token)
            continue
        value = int(token)
        if value in values:
            duplicates += 1
        values.add(value)
    if len(values) > MAX_CUSTOM_SLOPES:
        invalid.append(f"最多支持 {MAX_CUSTOM_SLOPES} 个不同坡度")
    return sorted(values), invalid, duplicates


def generate_slopes(start, end, step):
    """按正整数分母生成范围，生成前检查数量，避免无限或过量分配。"""
    parsed = []
    for label, raw in zip(("起始分母", "终止分母", "分母步长"), (start, end, step)):
        value = str(raw).strip()
        if not re.fullmatch(r"[0-9]+", value) or len(value) > 12 or int(value) <= 0:
            raise ValueError(f"{label}必须是正整数")
        parsed.append(int(value))
    start, end, step = parsed
    if end < start:
        raise ValueError("终止分母不能小于起始分母")
    if (end - start) // step + 1 > MAX_CUSTOM_SLOPES:
        raise ValueError(f"一次最多生成 {MAX_CUSTOM_SLOPES} 个坡度，请增大分母步长")
    return list(range(start, end + 1, step))


def section_at_angle(theta, diameter):
    """按湿周圆心角计算过水面积、湿周和水深。"""
    area = diameter ** 2 * (theta - math.sin(theta)) / 8
    perimeter = diameter * theta / 2
    depth = diameter * (1 - math.cos(theta / 2)) / 2
    return area, perimeter, depth


@lru_cache(maxsize=1)
def peak_angle():
    """由曼宁流量对圆心角的导数求最大流量位置。"""
    return brentq(lambda t: 5 * t * (1 - math.cos(t)) - 2 * (t - math.sin(t)),
                  math.pi, 2 * math.pi, xtol=1e-13)


def normal_flow(q, diameter, roughness, slope):
    """在最大流量点之前括区间求浅水深解，区分能力不足和求解失败。"""
    for label, value in (("流量", q), ("水力内径", diameter), ("糙率", roughness), ("底坡", slope)):
        if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{label}必须为正有限数")

    def discharge(theta):
        """计算指定湿周圆心角对应的曼宁流量。"""
        if theta <= 1e-7:
            return 0.0
        area, perimeter, _ = section_at_angle(theta, diameter)
        return area * (area / perimeter) ** (2 / 3) * math.sqrt(slope) / roughness

    peak = peak_angle()
    maximum = discharge(peak)
    full = discharge(2 * math.pi)
    result = dict(status="求解失败", reason="", depth=None, velocity=None, filling=None,
                  clearance_height=None, clearance_area=None, capacity=maximum, full_capacity=full)
    if q > maximum * (1 + 1e-10):
        result.update(status="能力不足", reason="超过圆管模型最大无压流量")
        return result
    try:
        theta = peak if q >= maximum else brentq(lambda t: discharge(t) - q, 0, peak, xtol=1e-13)
        area, _, depth = section_at_angle(theta, diameter)
        if area <= 0 or not math.isclose(discharge(theta), q, rel_tol=1e-7, abs_tol=1e-12):
            raise ValueError("流量残差未满足精度要求")
        result.update(status="可形成均匀流", depth=depth, velocity=q / area,
                      filling=depth / diameter, clearance_height=diameter - depth,
                      clearance_area=100 * (1 - area / (math.pi * diameter ** 2 / 4)))
    except (ValueError, RuntimeError, OverflowError, ZeroDivisionError) as exc:
        result["reason"] = f"求解失败：{exc}"
    return result


def compare_flows(candidate, q, denominator, roughness, height_limit=None, area_limit=None):
    """以同一内径分别对设计/加大流量计算有压参照及无压结果。"""
    rows = []
    factor = 1 + candidate.increase_pct / 100
    # 两种流量均使用同一水力内径，有压损失由批量内核按该材料指数补齐。
    for basis, flow in zip(FLOW_BASES, (q, q * factor)):
        result = normal_flow(flow, candidate.D, roughness, 1 / denominator)
        warnings = []
        if result["depth"] is not None:
            if height_limit is not None and result["clearance_height"] < height_limit:
                warnings.append(f"净空高度低于项目设定 {height_limit:g} m")
            if area_limit is not None and result["clearance_area"] < area_limit:
                warnings.append(f"净空面积低于项目设定 {area_limit:g}%")
        result.update(basis=basis, flow=flow, design_flow=q, diameter=candidate.D,
                      denominator=denominator, roughness=roughness,
                      pressure_velocity=flow / (math.pi * candidate.D ** 2 / 4),
                      criteria="；".join(warnings) or ("满足所设净空条件" if height_limit is not None or area_limit is not None else "未设置净空判据")
                      if result["depth"] is not None else "无法判定净空",
                      height_limit=height_limit, area_limit=area_limit,
                      model=MODEL_NOTE)
        rows.append(result)
    return rows


def preferred_diameter(rows):
    """优先展示可用底坡最多的最小内径，全无可用结果时展示扫描上限。"""
    from .unpressurized_selection import selection_summary
    profiles = selection_summary(rows)["profiles"]
    available = [diameter for diameter, profile in profiles.items() if profile["count"]]
    if available:
        return min(available, key=lambda diameter: (-profiles[diameter]["count"], diameter))
    return max(r["diameter"] for r in rows)


COMPARISON_COLUMNS = {
    "material": "管材", "specification": "产品规格", "diameter": "水力内径 (m)",
    "design_flow": "设计流量 (m³/s)", "basis": "流量口径", "flow": "本次流量 (m³/s)",
    "denominator": "底坡分母", "roughness": "无压糙率", "status": "输水能力判断",
    "depth": "水深 (m)", "filling": "充满度", "velocity": "无压流速 (m/s)",
    "capacity": "模型最大无压流量 (m³/s)", "full_capacity": "满管参照流量 (m³/s)",
    "pressure_velocity": "同流量有压流速 (m/s)", "pressure_loss": "同流量有压总水损 (m/km)",
    "pressure_loss_lower": "同流量有压总水损下限 (m/km)",
    "clearance_height": "净空高度 (m)", "clearance_area": "净空面积 (%)",
    "height_limit": "项目净空高度下限 (m)", "area_limit": "项目净空面积下限 (%)",
    "criteria": "项目净空判定", "reason": "计算说明", "model": "模型条件", "category": "有压候选类别",
}
