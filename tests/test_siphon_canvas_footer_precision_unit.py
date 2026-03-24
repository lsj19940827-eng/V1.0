import os
import sys
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "倒虹吸水力计算系统"))

from app_渠系计算前端.siphon.canvas_view import (  # noqa: E402
    build_plan_footer_info,
    build_profile_footer_info,
)


def test_plan_footer_uses_three_decimals():
    text = build_plan_footer_info(
        plan_len=311.0,
        ip_count=8,
        bend_count=6,
        zoom=1.0,
    )

    assert text == "平面总长: 311.000m | IP点: 8 | 弯管: 6 | 缩放: 100%"


def test_profile_footer_uses_three_decimals():
    text = build_profile_footer_info(
        total_len=69.1094,
        segment_count=17,
        zoom=1.25,
    )

    assert text == "总长度: 69.109m | 结构段: 17 | 缩放: 125%"
