# -*- coding: utf-8 -*-
"""Unit tests for local HTML loading compatibility helpers."""

import importlib.util
from pathlib import Path


def _load_webview_module():
    module_path = next(cand for cand in Path(".").glob("app_*/webview_compat.py")).resolve()
    spec = importlib.util.spec_from_file_location("webview_compat_module", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakePage:
    def __init__(self):
        self.calls = []

    def runJavaScript(self, script, callback=None):
        self.calls.append((script, callback))
        if callback is not None:
            callback('{"ready": true}')


class _FakeSignal:
    def __init__(self):
        self._handlers = []

    def connect(self, handler):
        self._handlers.append(handler)

    def disconnect(self, handler):
        self._handlers.remove(handler)

    def emit(self, *args):
        for handler in list(self._handlers):
            handler(*args)


class _FakeScrollBar:
    def __init__(self, value=17):
        self._value = value

    def minimum(self):
        return 0

    def setValue(self, value):
        self._value = value

    def value(self):
        return self._value


class _FakeScriptedView:
    supports_scripted_html = True

    def __init__(self):
        self.calls = []
        self._page = _FakePage()
        self.loadFinished = _FakeSignal()

    def setHtml(self, html_content, base_url=None):
        self.calls.append((html_content, base_url))
        self.loadFinished.emit(True)

    def page(self):
        return self._page


class _FakeFallbackView:
    supports_scripted_html = False

    def __init__(self):
        self.calls = []
        self._scrollbar = _FakeScrollBar()
        self.anchors = []

    def setHtml(self, html_content):
        self.calls.append((html_content,))

    def verticalScrollBar(self):
        return self._scrollbar

    def scrollToAnchor(self, anchor):
        self.anchors.append(anchor)


def test_load_html_content_passes_base_url_to_scripted_views():
    module = _load_webview_module()
    view = _FakeScriptedView()

    module.load_html_content(view, "<html></html>", base_path=Path("."))

    assert len(view.calls) == 1
    assert view.calls[0][0] == "<html></html>"
    assert view.calls[0][1].isLocalFile() is True
    assert view.page().calls[-1][0] == "window.scrollTo(0, 0);"


def test_load_html_content_uses_plain_set_html_for_fallback_views():
    module = _load_webview_module()
    view = _FakeFallbackView()

    module.load_html_content(view, "<html>fallback</html>", base_path=Path("."))

    assert view.calls == [("<html>fallback</html>",)]
    assert view.verticalScrollBar().value() == 0


def test_run_view_javascript_uses_page_when_available():
    module = _load_webview_module()
    view = _FakeScriptedView()
    results = []

    started = module.run_view_javascript(view, "1 + 1", callback=results.append)

    assert started is True
    assert view.page().calls[0][0] == "1 + 1"
    assert results == ['{"ready": true}']


def test_run_view_javascript_gracefully_rejects_fallback_views():
    module = _load_webview_module()
    view = _FakeFallbackView()
    results = []

    started = module.run_view_javascript(view, "1 + 1", callback=results.append)

    assert started is False
    assert results == [None]


def test_scroll_view_to_anchor_uses_scroll_to_anchor_for_fallback_views():
    module = _load_webview_module()
    view = _FakeFallbackView()

    started = module.scroll_view_to_anchor(view, "case-result-culvert-2")

    assert started is True
    assert view.anchors == ["case-result-culvert-2"]


def test_scroll_view_to_anchor_defers_until_scripted_view_load():
    module = _load_webview_module()
    view = _FakeScriptedView()

    started = module.scroll_view_to_anchor(
        view,
        "case-result-open-channel-1",
        defer_until_load=True,
    )

    assert started is True
    assert view.page().calls == []

    view.loadFinished.emit(True)

    assert len(view.page().calls) == 1
    assert "case-result-open-channel-1" in view.page().calls[0][0]
