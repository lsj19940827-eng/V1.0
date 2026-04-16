# -*- coding: utf-8 -*-
"""纵断面导出空名称轻提示单测。"""

import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace


def _load_cad_tools():
    root = Path(__file__).resolve().parents[1]
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    matches = list(root.glob("*/water_profile/cad_tools.py"))
    assert matches, "未找到 cad_tools.py"
    spec = importlib.util.spec_from_file_location("cad_tools_optional_name_notice_test_mod", matches[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cad_tools = _load_cad_tools()


class _InfoBarSpy:
    calls = []

    @classmethod
    def reset(cls):
        cls.calls = []

    @classmethod
    def info(cls, title, content, **kwargs):
        cls.calls.append({"title": title, "content": content, "kwargs": kwargs})


def _make_node(structure_type, *, name=""):
    return SimpleNamespace(
        structure_type=SimpleNamespace(value=structure_type),
        name=name,
        is_transition=False,
        is_auto_inserted_channel=False,
    )


def test_build_optional_blank_name_notice_skips_open_channel_rows():
    notice = cad_tools._build_optional_blank_name_notice(
        [_make_node("明渠-圆形", name="")],
        action_name="导出",
    )

    assert notice == ""


def test_build_optional_blank_name_notice_includes_culvert_rows():
    notice = cad_tools._build_optional_blank_name_notice(
        [_make_node("暗涵-矩形", name="")],
        action_name="导出",
    )

    assert "建议补充名称" in notice
    assert "第1行（暗涵-矩形）" in notice


def test_show_optional_blank_name_notice_uses_infobar(monkeypatch):
    popup_calls = []
    monkeypatch.setattr(cad_tools, "InfoBar", _InfoBarSpy)
    monkeypatch.setattr(cad_tools, "InfoBarPosition", SimpleNamespace(TOP="TOP"))
    monkeypatch.setattr(cad_tools, "fluent_info", lambda *args, **kwargs: popup_calls.append((args, kwargs)))
    _InfoBarSpy.reset()

    cad_tools._show_optional_blank_name_notice(
        None,
        [_make_node("暗涵-圆拱直墙型", name="")],
        action_name="导出",
    )

    assert len(_InfoBarSpy.calls) == 1
    assert "建议补充名称" in _InfoBarSpy.calls[0]["content"]
    assert popup_calls == []
