# -*- coding: utf-8 -*-
"""Qt WebEngine 兼容层。"""

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QTextBrowser

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView as _QtWebEngineView
    _WEB_ENGINE_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - 依赖环境相关
    _QtWebEngineView = None
    _WEB_ENGINE_IMPORT_ERROR = exc


class FallbackHtmlView(QTextBrowser):
    """WebEngine 不可用时的简化 HTML 视图。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.supports_scripted_html = False
        self.setOpenExternalLinks(True)
        self.setReadOnly(True)


def create_web_view(parent=None):
    """创建兼容的 HTML 视图。"""
    if _QtWebEngineView is not None:
        view = _QtWebEngineView(parent)
        view.supports_scripted_html = True
        return view
    return FallbackHtmlView(parent)


def view_supports_scripted_html(view) -> bool:
    return bool(getattr(view, "supports_scripted_html", False))


def view_can_run_javascript(view) -> bool:
    if not view_supports_scripted_html(view):
        return False
    page = getattr(view, "page", None)
    if not callable(page):
        return False
    try:
        current_page = page()
    except Exception:  # pragma: no cover - Qt runtime related
        return False
    return hasattr(current_page, "runJavaScript")


def _disconnect_pending_scroll_reset(view):
    signal = getattr(view, "loadFinished", None)
    handler = getattr(view, "_codex_scroll_reset_handler", None)
    if signal is not None and handler is not None:
        try:
            signal.disconnect(handler)
        except (RuntimeError, TypeError):
            pass
    try:
        view._codex_scroll_reset_handler = None
    except Exception:
        pass


def _disconnect_pending_anchor_scroll(view):
    signal = getattr(view, "loadFinished", None)
    handler = getattr(view, "_codex_anchor_scroll_handler", None)
    if signal is not None and handler is not None:
        try:
            signal.disconnect(handler)
        except (RuntimeError, TypeError):
            pass
    try:
        view._codex_anchor_scroll_handler = None
    except Exception:
        pass


def _reset_fallback_scroll(view):
    scrollbar = getattr(view, "verticalScrollBar", None)
    if not callable(scrollbar):
        return
    try:
        bar = scrollbar()
    except Exception:
        return
    if bar is None:
        return
    minimum = 0
    if hasattr(bar, "minimum"):
        try:
            minimum = bar.minimum()
        except Exception:
            minimum = 0
    try:
        bar.setValue(minimum)
    except Exception:
        pass


def reset_view_scroll_position(view):
    """Reset the result view to the top after HTML reloads."""
    if view is None:
        return

    if view_can_run_javascript(view):
        _disconnect_pending_scroll_reset(view)
        signal = getattr(view, "loadFinished", None)

        def _on_load_finished(ok):
            _disconnect_pending_scroll_reset(view)
            if not ok:
                return
            try:
                run_view_javascript(view, "window.scrollTo(0, 0);")
            except Exception:
                pass

        if signal is not None:
            try:
                view._codex_scroll_reset_handler = _on_load_finished
                signal.connect(_on_load_finished)
                return
            except Exception:
                _disconnect_pending_scroll_reset(view)

        try:
            run_view_javascript(view, "window.scrollTo(0, 0);")
        except Exception:
            pass
        return

    _reset_fallback_scroll(view)


def run_view_javascript(view, script: str, callback=None) -> bool:
    """Run JavaScript on a scripted view when supported."""
    if not view_can_run_javascript(view):
        if callback is not None:
            callback(None)
        return False

    page = view.page()
    if callback is not None:
        page.runJavaScript(script, callback)
    else:
        page.runJavaScript(script)
    return True


def _anchor_scroll_script(anchor: str, *, highlight: bool, smooth: bool) -> str:
    safe_anchor = str(anchor).replace("\\", "\\\\").replace("'", "\\'")
    behavior = "smooth" if smooth else "auto"
    flash = (
        f"if (window.codexFlashCase) {{ window.codexFlashCase('{safe_anchor}'); }}"
        if highlight
        else ""
    )
    return (
        "(() => {"
        f"const el = document.getElementById('{safe_anchor}');"
        "if (!el) { return false; }"
        "try {"
        f"  el.scrollIntoView({{behavior: '{behavior}', block: 'start'}});"
        "} catch (error) {"
        "  el.scrollIntoView(true);"
        "}"
        f"{flash}"
        "return true;"
        "})();"
    )


def scroll_view_to_anchor(view, anchor: str, *, highlight: bool = True,
                          smooth: bool = True, defer_until_load: bool = False) -> bool:
    """Scroll the HTML view to a named/id anchor when supported."""
    if view is None or not anchor:
        return False

    if view_can_run_javascript(view):
        script = _anchor_scroll_script(anchor, highlight=highlight, smooth=smooth)

        if defer_until_load:
            _disconnect_pending_anchor_scroll(view)
            signal = getattr(view, "loadFinished", None)

            def _on_load_finished(ok):
                _disconnect_pending_anchor_scroll(view)
                if not ok:
                    return
                try:
                    run_view_javascript(view, script)
                except Exception:
                    pass

            if signal is not None:
                try:
                    view._codex_anchor_scroll_handler = _on_load_finished
                    signal.connect(_on_load_finished)
                    return True
                except Exception:
                    _disconnect_pending_anchor_scroll(view)

        try:
            return run_view_javascript(view, script)
        except Exception:
            return False

    _disconnect_pending_anchor_scroll(view)
    scroll_to_anchor = getattr(view, "scrollToAnchor", None)
    if callable(scroll_to_anchor):
        try:
            scroll_to_anchor(str(anchor))
            return True
        except Exception:
            return False
    return False


def _base_url(base_path) -> QUrl:
    resolved = Path(base_path).resolve()
    as_posix = resolved.as_posix()
    if resolved.is_dir() and not as_posix.endswith("/"):
        as_posix += "/"
    return QUrl.fromLocalFile(as_posix)


def load_html_content(view, html_content, base_path=None, reset_scroll=True):
    """Load HTML into either QWebEngineView or fallback browser."""
    if reset_scroll and view_supports_scripted_html(view):
        reset_view_scroll_position(view)
    if view_supports_scripted_html(view) and base_path:
        view.setHtml(html_content, _base_url(base_path))
    elif view_supports_scripted_html(view):
        view.setHtml(html_content)
    else:
        view.setHtml(html_content)
    if reset_scroll and not view_supports_scripted_html(view):
        _reset_fallback_scroll(view)


def web_engine_available() -> bool:
    return _QtWebEngineView is not None


def get_web_engine_import_error():
    return _WEB_ENGINE_IMPORT_ERROR
