# -*- coding: utf-8 -*-
"""倒虹吸画布独立查看器。"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout

from qfluentwidgets import PushButton

from app_渠系计算前端.siphon.canvas_view import PipelineCanvas


class SiphonCanvasViewerDialog(QDialog):
    """用于大图查看的非模态倒虹吸视图窗口。"""

    view_mode_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setModal(False)
        self.setWindowFlag(Qt.Window, True)
        self.setWindowTitle("倒虹吸走向大图查看")
        self.resize(1040, 820)
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        tb = QHBoxLayout()
        tb.setSpacing(6)

        self.btn_view_profile = PushButton("纵断面")
        self.btn_view_profile.clicked.connect(lambda: self._change_view_mode("profile"))
        tb.addWidget(self.btn_view_profile)

        self.btn_view_plan = PushButton("平面图")
        self.btn_view_plan.clicked.connect(lambda: self._change_view_mode("plan"))
        tb.addWidget(self.btn_view_plan)

        tb.addStretch()

        self.lbl_zoom = QLabel("100%")
        self.lbl_zoom.setStyleSheet("color:#555555;font-size:12px;")
        tb.addWidget(self.lbl_zoom)

        self.btn_fit = PushButton("适配全图")
        self.btn_fit.clicked.connect(self._fit_to_content)
        tb.addWidget(self.btn_fit)

        self.btn_zoom_in = PushButton("＋")
        self.btn_zoom_in.clicked.connect(self._zoom_in)
        tb.addWidget(self.btn_zoom_in)

        self.btn_zoom_out = PushButton("－")
        self.btn_zoom_out.clicked.connect(self._zoom_out)
        tb.addWidget(self.btn_zoom_out)

        self.btn_reset = PushButton("重置视图")
        self.btn_reset.clicked.connect(self._zoom_reset)
        tb.addWidget(self.btn_reset)

        self.btn_close = PushButton("关闭")
        self.btn_close.clicked.connect(self.close)
        tb.addWidget(self.btn_close)

        lay.addLayout(tb)

        self.canvas = PipelineCanvas(self)
        self.canvas.setMinimumHeight(480)
        self.canvas.zoom_changed.connect(self._update_zoom_label)
        lay.addWidget(self.canvas, 1)

    def sync_from_panel(self, *, view_mode: str, segments, plan_segments,
                        plan_feature_points, plan_total_length,
                        longitudinal_nodes, longitudinal_is_example,
                        fit_to_content: bool = True):
        self.canvas.set_data(
            segments=segments,
            plan_segments=plan_segments,
            plan_feature_points=plan_feature_points,
            plan_total_length=plan_total_length,
            longitudinal_nodes=longitudinal_nodes,
            longitudinal_is_example=longitudinal_is_example,
        )
        if view_mode in ("profile", "plan"):
            self.canvas.set_view_mode(view_mode)
        else:
            self.canvas.auto_select_view()
        if fit_to_content:
            self.canvas.fit_to_content()
        self._resize_for_content()
        self._update_zoom_label()

    def show_and_focus(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def _change_view_mode(self, mode: str):
        self.canvas.set_view_mode(mode)
        self.canvas.fit_to_content()
        self.view_mode_changed.emit(mode)
        self._resize_for_content()

    def _fit_to_content(self):
        self.canvas.fit_to_content()
        self._resize_for_content()

    def _zoom_in(self):
        self.canvas.zoom_in()

    def _zoom_out(self):
        self.canvas.zoom_out()

    def _zoom_reset(self):
        self.canvas.zoom_reset()

    def _update_zoom_label(self, _zoom=None):
        self.lbl_zoom.setText(f"{int(self.canvas._zoom * 100)}%")

    def _resize_for_content(self):
        bounds = self.canvas.content_bounds()
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        max_w = max(860, int(available.width() * 0.84))
        max_h = max(680, int(available.height() * 0.88))

        if not bounds:
            self.resize(min(1040, max_w), min(820, max_h))
            return

        dw = max(bounds[1] - bounds[0], 1.0)
        dh = max(bounds[3] - bounds[2], 1.0)
        aspect = dw / dh

        if aspect <= 0.75:
            target_w, target_h = 920, 980
        elif aspect >= 2.4:
            target_w, target_h = 1280, 760
        else:
            target_w, target_h = 1080, 860

        self.resize(min(target_w, max_w), min(target_h, max_h))
