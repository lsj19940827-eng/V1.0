"""长会话公式缓存的容量、最近使用顺序和失败缓存回归。"""

import pytest

from app_渠系计算前端 import formula_renderer as renderer


@pytest.fixture(autouse=True)
def clean_cache(monkeypatch):
    """缩小容量以使用真实公式验证淘汰，不增加大量绘图测试耗时。"""
    renderer._svg_cache.clear()
    monkeypatch.setattr(renderer, "_MAX_SVG_CACHE_ENTRIES", 3)
    yield
    renderer._svg_cache.clear()


def test_cache_is_bounded_and_preserves_recently_used_svg():
    """连续新结果不能无限保留旧公式，命中时仍返回原 SVG。"""
    first = renderer.render_latex_svg("Q=1")
    assert first and "<svg" in first
    renderer.render_latex_svg("Q=2")
    renderer.render_latex_svg("Q=3")
    assert renderer.render_latex_svg("Q=1") == first
    renderer.render_latex_svg("Q=4")
    assert len(renderer._svg_cache) == 3
    assert ("Q=1", 14) in renderer._svg_cache
    assert ("Q=2", 14) not in renderer._svg_cache


def test_failed_formula_is_not_repeatedly_rendered(monkeypatch):
    """相同无效公式重复出现时，只尝试一次绘图并持续返回兼容的空结果。"""
    calls = []
    original_figure = renderer.Figure

    def counted_figure(*args, **kwargs):
        """统计真实图形创建次数。"""
        calls.append(True)
        return original_figure(*args, **kwargs)

    monkeypatch.setattr(renderer, "Figure", counted_figure)
    for _ in range(3):
        assert renderer.render_latex_svg(r"\unknownInvalidCommand{1}") is None
    assert len(calls) == 1
