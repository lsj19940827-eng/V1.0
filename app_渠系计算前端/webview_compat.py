# -*- coding: utf-8 -*-
"""Qt WebEngine 兼容层。

当 `PySide6.QtWebEngineWidgets` 因环境缺失或 DLL 装载失败不可用时，
退化为只读 HTML 视图，避免主程序在导入阶段直接崩溃。
"""

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
        self.setOpenExternalLinks(True)
        self.setReadOnly(True)


def create_web_view(parent=None):
    """创建兼容的 HTML 视图。"""
    if _QtWebEngineView is not None:
        return _QtWebEngineView(parent)
    return FallbackHtmlView(parent)


def web_engine_available() -> bool:
    return _QtWebEngineView is not None


def get_web_engine_import_error():
    return _WEB_ENGINE_IMPORT_ERROR

