# -*- coding: utf-8 -*-
"""泄水渠与陡坡前端使用的数据整理模型，与 panel/report_export/plotting 共用。"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SpillwayInput:
    """保存一次泄水渠与陡坡计算输入。"""

    project_name: str = "未命名工程"
    design_flow: float = 20.0
    channel_width: float = 1.0
    side_slope: float = 1.5
    chute_length: float = 80.0
    bed_slope: float = 0.02
    roughness: float = 0.014
    start_bed_elevation: float = 100.0
    start_depth: float = 1.788

    def to_dict(self) -> dict[str, Any]:
        """转换为项目保存和内核调用使用的字典。"""
        return {
            "project_name": self.project_name,
            "structure_name": self.project_name,
            "section_type": "trapezoidal" if self.side_slope > 0 else "rectangular",
            "design_flow": self.design_flow,
            "Q": self.design_flow,
            "channel_width": self.channel_width,
            "b": self.channel_width,
            "side_slope": self.side_slope,
            "m": self.side_slope,
            "chute_length": self.chute_length,
            "L": self.chute_length,
            "bed_slope": self.bed_slope,
            "i": self.bed_slope,
            "roughness": self.roughness,
            "n": self.roughness,
            "start_bed_elevation": self.start_bed_elevation,
            "start_depth": self.start_depth,
            "profile_mode": "END_DEPTH_BY_LENGTH",
        }


@dataclass
class ResultViewData:
    """统一面板和导出所需的结果字段。"""

    summary: dict[str, Any] = field(default_factory=dict)
    profile_points: list[dict[str, Any]] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    formulas: list[dict[str, Any]] = field(default_factory=list)
    comparison: list[dict[str, Any]] = field(default_factory=list)


def _as_mapping(value: Any) -> dict[str, Any]:
    """把对象或字典安全转为字典。"""
    if isinstance(value, dict):
        return value
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {}


def _as_list(value: Any) -> list[Any]:
    """把常见可迭代结果安全转为列表。"""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def sanitize_formula_source(source: Any) -> str:
    """把内部开发口径转换成用户可见的计算原理来源。"""
    text = str(source or "")
    replacements = {
        "GB 50288-2018 附录 N 与 PRD 第二版口径": "GB 50288-2018 附录 N 与消力池初拟经验口径",
        "PRD 第二版出口整流段设计口径": "出口连接段整流布置校核口径",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.replace("PRD", "设计口径")


def _formula_card_for_display(item: Any) -> dict[str, Any]:
    """整理公式卡片，并统一清洗出处字段。"""
    card = _as_mapping(item)
    source = sanitize_formula_source(card.get("source") or card.get("出处") or "")
    card["source"] = source
    if "出处" in card:
        card["出处"] = source
    return card


def normalize_result(result: Any) -> ResultViewData:
    """把算法内核返回值统一成前端展示和导出结构。"""
    data = _as_mapping(result)
    summary = _as_mapping(data.get("summary") or data.get("result_summary"))
    if not summary:
        summary = {
            key: value
            for key, value in data.items()
            if key
            in {
                "工程名称",
                "设计流量",
                "陡槽长度",
                "最大流速",
                "出口水深",
                "project_name",
                "design_flow",
                "chute_length",
                "max_velocity",
                "outlet_depth",
            }
        }

    profile_source = (
        data.get("profile_points")
        or _as_mapping(data.get("profile")).get("points")
        or data.get("water_surface_profile")
        or data.get("water_profile")
    )
    profile_points = [
        _as_mapping(point)
        for point in _as_list(profile_source)
    ]
    checks = [
        _as_mapping(item)
        for item in _as_list(data.get("checks") or data.get("code_checks") or data.get("spec_checks"))
    ]
    risks = [str(item) for item in _as_list(data.get("risks") or data.get("risk_tips") or data.get("warnings"))]
    formulas = [
        _formula_card_for_display(item)
        for item in _as_list(data.get("formulas") or data.get("formula_cards") or data.get("formula_sources"))
    ]
    comparison = [
        _as_mapping(item)
        for item in _as_list(data.get("comparison") or data.get("case_comparison"))
    ]
    return ResultViewData(
        summary=summary,
        profile_points=profile_points,
        checks=checks,
        risks=risks,
        formulas=formulas,
        comparison=comparison,
    )
