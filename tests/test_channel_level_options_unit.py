# -*- coding: utf-8 -*-
"""渠道级别枚举与桩号前缀映射单测。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))

from config.constants import CHANNEL_LEVEL_ABBR_MAP, CHANNEL_LEVEL_OPTIONS
from models.data_models import ProjectSettings


def test_channel_level_options_include_fill_and_drain_channels():
    assert "充水渠" in CHANNEL_LEVEL_OPTIONS
    assert "泄水渠" in CHANNEL_LEVEL_OPTIONS


def test_project_settings_station_prefix_supports_fill_and_drain_channels():
    assert CHANNEL_LEVEL_ABBR_MAP["充水渠"] == "充"
    assert CHANNEL_LEVEL_ABBR_MAP["泄水渠"] == "泄"

    fill_settings = ProjectSettings(channel_name="罗寂寺", channel_level="充水渠")
    drain_settings = ProjectSettings(channel_name="罗寂寺", channel_level="泄水渠")

    assert fill_settings.get_station_prefix() == "罗充"
    assert drain_settings.get_station_prefix() == "罗泄"
