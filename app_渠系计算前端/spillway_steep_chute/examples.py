# -*- coding: utf-8 -*-
"""泄水渠与陡坡教学算例，供面板一键载入。"""

from .models import SpillwayInput


def teaching_example() -> dict[str, object]:
    """返回熊启钧棱柱体陡坡教学算例的前端输入。"""
    return SpillwayInput(
        project_name="熊启钧教学算例",
        design_flow=20.0,
        channel_width=1.0,
        side_slope=1.5,
        chute_length=80.0,
        bed_slope=0.02,
        roughness=0.014,
        start_bed_elevation=100.0,
        start_depth=1.788,
    ).to_dict()
