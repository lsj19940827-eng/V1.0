"""Mouse navigation shared by the longitudinal profile previews."""
from __future__ import annotations

MOUSE_NAVIGATION_HINT = "滚轮缩放，按住鼠标左键拖动，双击还原视图。"


def wheel_steps(event):
    pixels = event.pixelDelta().y()
    return pixels / 40 if pixels else event.angleDelta().y() / 120


def scaled_zoom(zoom, steps):
    return max(.05, min(1000., zoom * 1.2 ** max(-12., min(12., steps))))


def zoom_limits(limits, anchor, factor):
    return tuple(anchor + (edge - anchor) * factor for edge in limits)
