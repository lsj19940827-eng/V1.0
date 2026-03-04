# -*- coding: utf-8 -*-
"""Unit tests for open-channel circular case parsing."""

import importlib


def test_parse_circular_case_uses_manual_d_key():
    mod = importlib.import_module(
        "\u6e20\u7cfb\u65ad\u9762\u8bbe\u8ba1.open_channel.panel"
    )
    panel_cls = mod.OpenChannelPanel

    case = {
        "section_type": "\u5706\u5f62",
        "Q": "5.0",
        "n": "0.014",
        "slope_inv": "3000",
        "v_min": "0.1",
        "v_max": "100.0",
        "inc_checked": True,
        "inc_pct": "",
        "detail_checked": True,
        "D": "2.8",
    }

    params, result = panel_cls._parse_and_calc_case(object(), case, 1)

    assert params["section_type"] == "\u5706\u5f62"
    assert params["manual_D"] == 2.8
    assert "manual_b" not in params
    assert result.get("success") is True
