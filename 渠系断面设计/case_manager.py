# -*- coding: utf-8 -*-
"""
多工况管理共享UI组件模块

提供工况标签芯片、流式布局、虚线添加按钮等可复用组件，
供有压管道、明渠、渡槽、隧洞、矩形暗涵、倒虹吸等面板共享使用。
"""

from PySide6.QtWidgets import (
    QLayout, QPushButton, QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QWidget,
)
from PySide6.QtCore import Qt, QRect, QPoint, QSize, Signal
from PySide6.QtGui import QPainter, QPen, QColor


# ============================================================
# 常量
# ============================================================
MAX_CASES = 10

_SUB = '₀₁₂₃₄₅₆₇₈₉'

def _sub(n):
    """将数字转为下标 Unicode 字符，如 12 → '₁₂'"""
    return ''.join(_SUB[int(d)] for d in str(n))


# ============================================================
# 工况标签样式
# ============================================================
CASE_TAG_ACTIVE_SS = (
    "QPushButton{background:#0078d4;border:2px solid #0078d4;border-radius:14px;"
    "color:#fff;font-size:12px;font-weight:600;padding:2px 14px;}"
    "QPushButton:hover{background:#106ebe;border-color:#106ebe;}"
)
CASE_TAG_INACTIVE_SS = (
    "QPushButton{background:#f0f0f0;border:2px solid transparent;border-radius:14px;"
    "color:#666;font-size:12px;font-weight:500;padding:2px 14px;}"
    "QPushButton:hover{background:#e8f4fd;color:#0078d4;}"
)
CASE_QUICK_SS = (
    "QPushButton{padding:4px 10px;border:1px solid #d0d0d0;border-radius:6px;"
    "background:#fff;font-size:11px;color:#555;}"
    "QPushButton:hover{border-color:#0078d4;color:#0078d4;background:#f0f7ff;}"
)


# ============================================================
# FlowLayout — 自动换行流式布局
# ============================================================
class FlowLayout(QLayout):
    """自动换行流式布局"""

    def __init__(self, parent=None, spacing=4):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        er = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = er.x(), er.y(), 0
        sp = self._spacing
        right = er.x() + er.width()
        for item in self._items:
            isz = item.sizeHint()
            nxt = x + isz.width()
            if nxt > right and line_h > 0:
                x = er.x()
                y += line_h + sp
                line_h = 0
                nxt = x + isz.width()
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), isz))
            x = nxt + sp
            line_h = max(line_h, isz.height())
        return y + line_h - rect.y() + m.bottom()


# ============================================================
# RenameDialog — 自定义重命名对话框（自适应大小 + 中文按钮）
# ============================================================
class RenameDialog(QDialog):
    """自定义重命名对话框，自适应窗口大小，中文按钮"""
    
    def __init__(self, title, label, default_text="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        
        # 主布局
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 16, 20, 16)
        
        # 提示标签
        lbl = QLabel(label)
        lbl.setStyleSheet("font-size: 13px; color: #333;")
        layout.addWidget(lbl)
        
        # 输入框
        self.line_edit = QLineEdit(default_text)
        self.line_edit.setMinimumWidth(280)
        self.line_edit.setStyleSheet(
            "QLineEdit { padding: 8px 10px; border: 1px solid #ccc; "
            "border-radius: 4px; font-size: 13px; }"
            "QLineEdit:focus { border-color: #0078d4; }"
        )
        self.line_edit.selectAll()
        layout.addWidget(self.line_edit)
        
        # 按钮区域
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.addStretch()
        
        # 确定按钮
        self.ok_btn = QPushButton("确定")
        self.ok_btn.setFixedSize(80, 32)
        self.ok_btn.setCursor(Qt.PointingHandCursor)
        self.ok_btn.setStyleSheet(
            "QPushButton { background: #0078d4; color: white; border: none; "
            "border-radius: 4px; font-size: 13px; font-weight: 500; }"
            "QPushButton:hover { background: #106ebe; }"
            "QPushButton:pressed { background: #005a9e; }"
        )
        self.ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.ok_btn)
        
        # 取消按钮
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setFixedSize(80, 32)
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.setStyleSheet(
            "QPushButton { background: #f0f0f0; color: #333; border: 1px solid #ccc; "
            "border-radius: 4px; font-size: 13px; }"
            "QPushButton:hover { background: #e5e5e5; border-color: #999; }"
            "QPushButton:pressed { background: #d5d5d5; }"
        )
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(btn_layout)
        
        # 自适应大小
        self.adjustSize()
        self.setMinimumWidth(max(320, self.sizeHint().width()))
    
    def text(self):
        return self.line_edit.text()
    
    @staticmethod
    def getText(parent, title, label, default_text=""):
        """静态方法，替代 QInputDialog.getText"""
        dlg = RenameDialog(title, label, default_text, parent)
        # 居中显示在父窗口
        if parent:
            # 获取顶层窗口
            top_parent = parent.window() if hasattr(parent, 'window') else parent
            if top_parent:
                parent_geo = top_parent.geometry()
                dlg_size = dlg.sizeHint()
                x = parent_geo.x() + (parent_geo.width() - dlg_size.width()) // 2
                y = parent_geo.y() + (parent_geo.height() - dlg_size.height()) // 2
                dlg.move(x, y)
        
        result = dlg.exec()
        return dlg.text(), result == QDialog.Accepted


# ============================================================
# CaseTagChip — 工况标签芯片（单击切换 + 双击重命名）
# ============================================================
class CaseTagChip(QPushButton):
    """工况标签芯片 — 单击切换工况，双击重命名"""
    switched = Signal(int)
    renamed = Signal(int, str)

    def __init__(self, index, label_text, active=False, parent=None):
        super().__init__(label_text, parent)
        self.case_index = index
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(28)
        self.setMaximumWidth(200)
        self.setStyleSheet(CASE_TAG_ACTIVE_SS if active else CASE_TAG_INACTIVE_SS)
        self.clicked.connect(lambda: self.switched.emit(self.case_index))

    def mouseDoubleClickEvent(self, event):
        text, ok = RenameDialog.getText(
            self, "重命名工况",
            "请输入工况名称:",
            self.text()
        )
        if ok and text.strip():
            self.renamed.emit(self.case_index, text.strip())
        # 不调用 super() 避免双击同时触发 clicked


# ============================================================
# DashedButton — 虚线圆角按钮（"+ 添加"）
# ============================================================
class DashedButton(QPushButton):
    """虚线圆角按钮 — 用 paintEvent 手绘，绕开 QSS dashed+border-radius 渲染 bug"""
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self._hovered = False
        self.setMouseTracking(True)
        self.setStyleSheet(
            "QPushButton{background:transparent;border:none;"
            "color:#999;font-size:12px;padding:3px 10px;}"
        )

    def enterEvent(self, event):
        self._hovered = True
        self.setStyleSheet(
            "QPushButton{background:#f0f7ff;border:none;"
            "color:#0078d4;font-size:12px;padding:3px 10px;}"
        )
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.setStyleSheet(
            "QPushButton{background:transparent;border:none;"
            "color:#999;font-size:12px;padding:3px 10px;}"
        )
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor("#0078d4") if self._hovered else QColor("#ccc"))
        pen.setStyle(Qt.DashLine)
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 10, 10)
        p.end()
