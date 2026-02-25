# -*- coding: utf-8 -*-
"""
结构形式分类选择面板

双击"结构形式"单元格时弹出，按类别展示所有可用的结构类型。
用户点击对应按钮即可选中，直观且美观。
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QWidget, QScrollArea,
    QGraphicsDropShadowEffect
)
from PySide6.QtCore import Qt, Signal, QSize, QPropertyAnimation, QEasingCurve, QPoint
from PySide6.QtGui import QFont, QColor, QCursor

from 渠系断面设计.styles import P, S, W, E, BG, CARD, BD, T1, T2


# ============================================================
# 结构类型分类定义
# ============================================================
STRUCTURE_CATEGORIES = [
    {
        "name": "明渠",
        "icon": "🏞",
        "color": "#1976D2",
        "items": ["明渠-梯形", "明渠-矩形", "明渠-圆形", "明渠-U形"],
        "desc": "开敞式渠道断面",
    },
    {
        "name": "渡槽",
        "icon": "🌉",
        "color": "#00897B",
        "items": ["渡槽-U形", "渡槽-矩形"],
        "desc": "跨越障碍的输水建筑物",
    },
    {
        "name": "隧洞",
        "icon": "🚇",
        "color": "#5E35B1",
        "items": ["隧洞-圆形", "隧洞-圆拱直墙型", "隧洞-马蹄形Ⅰ型", "隧洞-马蹄形Ⅱ型"],
        "desc": "穿越山体的输水建筑物",
    },
    {
        "name": "暗涵",
        "icon": "📦",
        "color": "#6D4C41",
        "items": ["矩形暗涵"],
        "desc": "封闭式矩形输水通道",
    },
    {
        "name": "闸",
        "icon": "🚧",
        "color": "#E65100",
        "items": ["分水闸", "分水口", "节制闸", "泄水闸"],
        "desc": "流量段分界 / 过闸水头损失",
    },
    {
        "name": "倒虹吸",
        "icon": "⬇",
        "color": "#AD1457",
        "items": ["倒虹吸"],
        "desc": "穿越河流/道路的压力管道",
    },
]


class _CategoryTab(QPushButton):
    """顶部分类标签按钮"""

    def __init__(self, name, icon_text, color, parent=None):
        super().__init__(parent)
        self.category_name = name
        self._color = color
        self._active = False
        self.setText(f"{icon_text} {name}")
        self.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setFixedHeight(36)
        self.setMinimumWidth(72)
        self._update_style()

    def set_active(self, active):
        self._active = active
        self._update_style()

    def _update_style(self):
        if self._active:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: {self._color}; color: white;
                    border: none; border-radius: 6px;
                    padding: 4px 14px; font-size: 13px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {T1};
                    border: 1px solid {BD}; border-radius: 6px;
                    padding: 4px 14px; font-size: 13px;
                }}
                QPushButton:hover {{
                    background: {self._color}22; color: {self._color};
                    border-color: {self._color};
                }}
            """)


class _ItemCard(QPushButton):
    """单个结构类型卡片按钮"""

    double_clicked = Signal(str)

    def __init__(self, text, color, parent=None):
        super().__init__(text, parent)
        self._color = color
        self._item_text = text
        self.setFont(QFont("Microsoft YaHei", 11))
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setFixedSize(150, 48)
        self.setStyleSheet(f"""
            QPushButton {{
                background: white; color: {T1};
                border: 1.5px solid {BD}; border-radius: 8px;
                padding: 6px 12px; font-size: 13px;
            }}
            QPushButton:hover {{
                background: {color}15; color: {color};
                border-color: {color}; font-weight: bold;
            }}
            QPushButton:pressed {{
                background: {color}30;
            }}
        """)
        # 悬浮阴影
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(8)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(0, 0, 0, 30))
        self.setGraphicsEffect(shadow)

    def mouseDoubleClickEvent(self, event):
        """双击卡片发射 double_clicked 信号"""
        self.double_clicked.emit(self._item_text)
        event.accept()


class StructureTypeSelector(QDialog):
    """
    结构形式分类选择弹窗

    用法：
        dlg = StructureTypeSelector(parent)
        dlg.set_current(current_type)  # 可选，高亮当前值
        if dlg.exec() == QDialog.Accepted:
            selected = dlg.selected_type
    """

    type_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_type = ""
        self._category_tabs = []
        self._category_panels = {}
        self._item_cards = {}
        self._init_ui()

    def _init_ui(self):
        self.setWindowTitle("选择结构形式")
        # 使用标准对话框模式，避免 Qt.Popup 与 exec() 混用导致 Esc/焦点行为不稳定
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(520, 340)
        self.setFocusPolicy(Qt.StrongFocus)

        # 外层容器（带圆角和阴影）
        container = QFrame(self)
        container.setObjectName("selectorContainer")
        container.setStyleSheet(f"""
            #selectorContainer {{
                background: {CARD};
                border: 1px solid {BD};
                border-radius: 12px;
            }}
        """)
        shadow = QGraphicsDropShadowEffect(container)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 60))
        container.setGraphicsEffect(shadow)

        outer_lay = QVBoxLayout(self)
        outer_lay.setContentsMargins(12, 12, 12, 12)
        outer_lay.addWidget(container)

        main_lay = QVBoxLayout(container)
        main_lay.setContentsMargins(16, 14, 16, 14)
        main_lay.setSpacing(10)

        # 标题栏
        title_lay = QHBoxLayout()
        title_lbl = QLabel("选择结构形式")
        title_lbl.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        title_lbl.setStyleSheet(f"color: {T1};")
        title_lay.addWidget(title_lbl)
        title_lay.addStretch()

        hint_lbl = QLabel("单击选择 · 双击确认 · Esc 取消")
        hint_lbl.setFont(QFont("Microsoft YaHei", 9))
        hint_lbl.setStyleSheet(f"color: {T2};")
        title_lay.addWidget(hint_lbl)
        main_lay.addLayout(title_lay)

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"background: {BD}; max-height: 1px;")
        main_lay.addWidget(line)

        # 分类标签行
        tab_lay = QHBoxLayout()
        tab_lay.setSpacing(6)
        for cat in STRUCTURE_CATEGORIES:
            tab = _CategoryTab(cat["name"], cat["icon"], cat["color"], self)
            tab.clicked.connect(lambda checked=False, c=cat["name"]: self._switch_category(c))
            self._category_tabs.append(tab)
            tab_lay.addWidget(tab)
        tab_lay.addStretch()
        main_lay.addLayout(tab_lay)

        # 类别描述
        self._desc_label = QLabel("")
        self._desc_label.setFont(QFont("Microsoft YaHei", 9))
        self._desc_label.setStyleSheet(f"color: {T2}; padding: 0 2px;")
        main_lay.addWidget(self._desc_label)

        # 卡片区域（用 QScrollArea 以防内容溢出）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")

        self._cards_container = QWidget()
        self._cards_layout = QVBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(0)

        # 为每个分类创建一个面板
        for cat in STRUCTURE_CATEGORIES:
            panel = QWidget()
            grid = QGridLayout(panel)
            grid.setContentsMargins(4, 4, 4, 4)
            grid.setSpacing(10)
            col_count = 3  # 每行3个
            for i, item_name in enumerate(cat["items"]):
                card = _ItemCard(item_name, cat["color"], panel)
                card.clicked.connect(lambda checked=False, t=item_name: self._on_item_clicked(t))
                card.double_clicked.connect(self._on_item_double_clicked)
                grid.addWidget(card, i // col_count, i % col_count)
                self._item_cards[item_name] = card
            panel.setVisible(False)
            self._category_panels[cat["name"]] = panel
            self._cards_layout.addWidget(panel)

        self._cards_layout.addStretch()
        scroll.setWidget(self._cards_container)
        main_lay.addWidget(scroll, 1)

        # 底部按钮栏（确定 / 取消）
        btn_lay = QHBoxLayout()
        btn_lay.setSpacing(12)
        btn_lay.addStretch()

        self._btn_cancel = QPushButton("取消")
        self._btn_cancel.setFont(QFont("Microsoft YaHei", 10))
        self._btn_cancel.setCursor(QCursor(Qt.PointingHandCursor))
        self._btn_cancel.setFixedSize(90, 36)
        self._btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background: white; color: {T1};
                border: 1px solid {BD}; border-radius: 6px;
            }}
            QPushButton:hover {{ background: #F5F5F5; }}
        """)
        self._btn_cancel.clicked.connect(self._on_cancel)
        btn_lay.addWidget(self._btn_cancel)

        self._btn_ok = QPushButton("确定")
        self._btn_ok.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        self._btn_ok.setCursor(QCursor(Qt.PointingHandCursor))
        self._btn_ok.setFixedSize(90, 36)
        self._btn_ok.setEnabled(False)  # 未选中时禁用
        self._btn_ok.setStyleSheet(f"""
            QPushButton {{
                background: {P}; color: white;
                border: none; border-radius: 6px;
            }}
            QPushButton:hover {{ background: {S}; }}
            QPushButton:disabled {{
                background: {BD}; color: {T2};
            }}
        """)
        self._btn_ok.clicked.connect(self._on_confirm)
        btn_lay.addWidget(self._btn_ok)

        main_lay.addLayout(btn_lay)

        # 默认选中第一个分类
        self._switch_category(STRUCTURE_CATEGORIES[0]["name"])

    def showEvent(self, event):
        """确保弹窗打开后立即获得焦点，Esc 操作更稳定。"""
        super().showEvent(event)
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.ActiveWindowFocusReason)

    # ── 拖动支持（无标题栏窗口） ──
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and getattr(self, '_drag_pos', None) is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def keyPressEvent(self, event):
        """Esc 取消：清空选中并关闭。QDialog 默认 Esc→reject()，
        这里覆写确保 selected_type 也被清空。"""
        if event.key() == Qt.Key_Escape:
            self.selected_type = ""
            self.reject()
            event.accept()
            return
        super().keyPressEvent(event)

    def _switch_category(self, category_name):
        """切换分类"""
        for tab in self._category_tabs:
            tab.set_active(tab.category_name == category_name)
        for name, panel in self._category_panels.items():
            panel.setVisible(name == category_name)
        # 更新描述
        for cat in STRUCTURE_CATEGORIES:
            if cat["name"] == category_name:
                self._desc_label.setText(cat["desc"])
                break

    def _on_item_clicked(self, type_name):
        """单击卡片：高亮选中，启用确定按钮"""
        # 重置所有卡片样式
        for name, card in self._item_cards.items():
            cat_color = "#999"
            for cat in STRUCTURE_CATEGORIES:
                if name in cat["items"]:
                    cat_color = cat["color"]
                    break
            card.setStyleSheet(f"""
                QPushButton {{
                    background: white; color: {T1};
                    border: 1.5px solid {BD}; border-radius: 8px;
                    padding: 6px 12px; font-size: 13px;
                }}
                QPushButton:hover {{
                    background: {cat_color}15; color: {cat_color};
                    border-color: {cat_color}; font-weight: bold;
                }}
                QPushButton:pressed {{
                    background: {cat_color}30;
                }}
            """)
        # 高亮当前选中
        cat_color = P
        for cat in STRUCTURE_CATEGORIES:
            if type_name in cat["items"]:
                cat_color = cat["color"]
                break
        if type_name in self._item_cards:
            self._item_cards[type_name].setStyleSheet(f"""
                QPushButton {{
                    background: {cat_color}20; color: {cat_color};
                    border: 2px solid {cat_color}; border-radius: 8px;
                    padding: 6px 12px; font-size: 13px; font-weight: bold;
                }}
                QPushButton:hover {{
                    background: {cat_color}30;
                }}
            """)
        self.selected_type = type_name
        self._btn_ok.setEnabled(True)

    def _on_item_double_clicked(self, type_name):
        """双击卡片：直接确认（与点击确定按钮等效）"""
        self.selected_type = type_name
        self.type_selected.emit(type_name)
        self.accept()

    def _on_cancel(self):
        """点击取消按钮"""
        self.selected_type = ""
        self.reject()

    def _on_confirm(self):
        """点击确定按钮"""
        if self.selected_type:
            self.type_selected.emit(self.selected_type)
            self.accept()

    def set_current(self, current_type):
        """高亮当前值并自动切换到对应分类"""
        if not current_type:
            return
        for cat in STRUCTURE_CATEGORIES:
            if current_type in cat["items"]:
                self._switch_category(cat["name"])
                break
        # 高亮当前选中的卡片，并设置 selected_type + 启用确定按钮
        if current_type in self._item_cards:
            self.selected_type = current_type
            self._btn_ok.setEnabled(True)
            card = self._item_cards[current_type]
            cat_color = P
            for cat in STRUCTURE_CATEGORIES:
                if current_type in cat["items"]:
                    cat_color = cat["color"]
                    break
            card.setStyleSheet(f"""
                QPushButton {{
                    background: {cat_color}20; color: {cat_color};
                    border: 2px solid {cat_color}; border-radius: 8px;
                    padding: 6px 12px; font-size: 13px; font-weight: bold;
                }}
                QPushButton:hover {{
                    background: {cat_color}30;
                }}
            """)
