# -*- coding: utf-8 -*-
"""泄水渠与陡坡工况对比数据整理。"""

from typing import Any

from .models import normalize_result


def build_comparison_rows(result: Any) -> list[dict[str, Any]]:
    """从计算结果中提取工况对比行。"""
    view_data = normalize_result(result)
    if view_data.comparison:
        return view_data.comparison
    summary = view_data.summary
    if not summary:
        return []
    return [
        {
            "case": summary.get("工程名称") or summary.get("project_name") or "当前工况",
            "Q": summary.get("设计流量") or summary.get("design_flow") or "",
            "max_v": summary.get("最大流速") or summary.get("max_velocity") or "",
            "status": "通过" if not view_data.risks else "需复核",
        }
    ]
