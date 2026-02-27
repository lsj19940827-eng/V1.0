# -*- coding: utf-8 -*-
"""
共享样式常量 —— 所有模块面板统一使用
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, Property, Signal
from PySide6.QtGui import QFont


class CollapsibleGroupBox(QWidget):
    """可折叠的 GroupBox，点击标题栏切换展开/折叠。

    折叠后仅显示标题行（约24px高），展开后显示完整内容。
    """

    def __init__(self, title: str, parent=None, collapsed=False):
        super().__init__(parent)
        self._collapsed = collapsed

        # 标题栏
        self._header = QLabel()
        self._header.setCursor(Qt.PointingHandCursor)
        self._header.setFixedHeight(26)
        self._header.mousePressEvent = lambda e: self.toggle()

        # 内容容器
        self._content = QWidget()

        # 布局
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._header)
        lay.addWidget(self._content)

        self._title = title
        self._update_header()

        if collapsed:
            self._content.setVisible(False)

    def _update_header(self):
        arrow = "▶" if self._collapsed else "▼"
        self._header.setText(f"  {arrow}  {self._title}")
        self._header.setStyleSheet(
            "QLabel {"
            "  font-size: 13px; font-weight: bold; color: #1976D2;"
            "  background: #EEF2F7; border: 1px solid #E0E0E0;"
            "  border-radius: 4px; padding: 2px 6px;"
            "}"
            "QLabel:hover { background: #E3EBF5; }"
        )

    toggled = Signal(bool)  # collapsed state

    def toggle(self):
        self._collapsed = not self._collapsed
        self._content.setVisible(not self._collapsed)
        self._update_header()
        self.toggled.emit(self._collapsed)

    def set_collapsed(self, collapsed: bool):
        if self._collapsed != collapsed:
            self.toggle()

    def is_collapsed(self) -> bool:
        return self._collapsed

    def content_widget(self) -> QWidget:
        """返回内容容器，调用方在此容器上设置布局和子控件。"""
        return self._content

    def content_layout(self):
        """返回内容容器的布局（如已设置）。"""
        return self._content.layout()

# ============================================================
# 颜色常量
# ============================================================
P = "#1976D2"       # 主色（蓝）
S = "#2E7D32"       # 成功色（绿）
W = "#F57C00"       # 警告色（橙）
E = "#D32F2F"       # 错误色（红）
BG = "#F5F7FA"      # 背景色
CARD = "#FFFFFF"    # 卡片背景
BD = "#E0E0E0"      # 边框色
T1 = "#212121"      # 主文字色
T2 = "#424242"      # 次文字色


# ============================================================
# 全局QSS样式（仅覆盖QFluentWidgets不接管的原生组件）
# ============================================================
GLOBAL_STYLE = f"""
QMainWindow {{ background: {BG}; }}
QGroupBox {{
    font-family: 'Microsoft YaHei', sans-serif;
    font-size: 14px; font-weight: bold; color: {P};
    border: 1px solid {BD}; border-radius: 6px;
    margin-top: 12px; padding: 14px 10px 10px 10px; background: {CARD};
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; background: {CARD}; }}
QLabel {{ font-family: 'Microsoft YaHei', sans-serif; color: {T1}; font-size: 13px; }}
QTextEdit {{ border: 1px solid {BD}; border-radius: 4px; background: #f5f5f5; }}
QTabWidget::pane {{ border: 1px solid {BD}; border-radius: 4px; background: {CARD}; }}
QTabBar::tab {{ background: #E8EAF6; color: {T1}; padding: 8px 18px; margin-right: 2px; border-top-left-radius: 4px; border-top-right-radius: 4px; font-size: 12px; }}
QTabBar::tab:selected {{ background: {P}; color: white; font-weight: bold; }}
QStatusBar {{ background: {CARD}; border-top: 1px solid {BD}; font-size: 11px; color: {T2}; }}
"""


# ============================================================
# 附录E HTML表格样式
# ============================================================
AE_CSS = """
<style>
table.ae { border-collapse:collapse; width:96%; margin:8px auto; font-family:'Microsoft YaHei',sans-serif; font-size:10pt; }
table.ae th { background:#f0f0f0; color:#1a1a1a; padding:6px 8px; border:1px solid #e0e0e0; text-align:center; font-weight:bold; }
table.ae td { padding:5px 8px; border:1px solid #e0e0e0; text-align:center; color:#333; }
tr.even { background:#fff; } tr.odd { background:#fafafa; }
tr.sel { background:#d6eaf8; color:#0055a3; font-weight:bold; }
tr.err { background:#fdf0e7; color:#a34400; }
pre { margin:0; padding:0; white-space:pre-wrap; font-family:Consolas,'Courier New',monospace; font-size:11pt; }
</style>
"""


# ============================================================
# 侧边导航栏样式
# ============================================================
def auto_resize_table(table):
    """根据内容自适应表格列宽，剩余空间按比例分配。
    应在表格数据填充完毕后调用；窗口resize时也应调用。"""
    table.resizeColumnsToContents()
    # 补偿 resizeColumnsToContents 在冻结列表格等场景下可能宽度不足的问题：
    # 用字体度量逐列校验，确保每列至少能完整显示表头和数据内容。
    fm = table.fontMetrics()
    _pad = 26
    _row_count = table.rowCount()
    _step = max(1, _row_count // 60)
    for c in range(table.columnCount()):
        needed = 0
        hi = table.horizontalHeaderItem(c)
        if hi:
            needed = fm.horizontalAdvance(hi.text()) + _pad + 4
        for r in range(0, _row_count, _step):
            it = table.item(r, c)
            if it:
                txt = it.text()
                if txt:
                    w = fm.horizontalAdvance(txt) + _pad
                    if w > needed:
                        needed = w
        if needed > table.columnWidth(c):
            table.setColumnWidth(c, needed)
    header = table.horizontalHeader()
    col_count = header.count()
    if col_count == 0:
        return
    total_content_w = sum(header.sectionSize(c) for c in range(col_count))
    available_w = table.viewport().width()
    if available_w <= 0:
        available_w = table.width() - table.verticalHeader().width() - 4
    if available_w > total_content_w and total_content_w > 0:
        extra = available_w - total_content_w
        for c in range(col_count):
            cur = header.sectionSize(c)
            ratio = cur / total_content_w
            table.setColumnWidth(c, cur + int(extra * ratio))


NAV_STYLE = f"""
#navPanel {{
    background: #F7F8FA;
    border-right: 1px solid #DFE3EA;
}}
#navBrandCard {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FFFFFF, stop:1 #F9FAFC);
    border: 1px solid #E7EAF0;
    border-radius: 12px;
}}
#navBrandLogo {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FCFEFF, stop:1 #F2F5FA);
    border: 1px solid #DCE3EE;
    border-radius: 11px;
}}
#navTitle {{
    font-size: 18px;
    font-weight: 700;
    color: #0F172A;
    padding: 4px 10px 0px 10px;
    qproperty-alignment: AlignHCenter;
}}
#navSubtitle {{
    font-size: 15px;
    font-weight: 600;
    color: #3B4A63;
    padding: 0px 10px 2px 10px;
    qproperty-alignment: AlignHCenter;
}}
#navVersion {{
    font-size: 11px;
    font-weight: 700;
    color: #0A84FF;
    background: #ECF4FF;
    border: 1px solid #D7E7FF;
    border-radius: 10px;
    padding: 2px 10px;
    margin-top: 4px;
    qproperty-alignment: AlignHCenter;
}}
"""


# ============================================================
# QFluentWidgets 风格消息框辅助函数
# ============================================================

def fluent_info(parent, title, content):
    """信息/警告提示（仅确定按钮），替代 QMessageBox.warning / information"""
    from qfluentwidgets import MessageBox
    from PySide6.QtWidgets import QTextEdit
    w = MessageBox(title, content, parent)
    w.yesButton.setText("确定")
    w.cancelButton.hide()
    if len(content) > 500 or content.count('\n') > 15:
        w.contentLabel.hide()
        te = QTextEdit()
        te.setPlainText(content)
        te.setReadOnly(True)
        te.setMinimumHeight(280)
        te.setMaximumHeight(420)
        te.setStyleSheet(
            "QTextEdit { border: 1px solid #e0e0e0; border-radius: 6px;"
            " background: #fafafa; padding: 8px;"
            " font-family: 'Microsoft YaHei', 'Consolas', monospace;"
            " font-size: 13px; line-height: 1.5; }"
        )
        w.textLayout.addWidget(te)
        w.widget.setFixedWidth(880)
    w.exec()


def fluent_batch_result(parent, title, summary, details):
    """批量计算结果弹窗：左右分栏 + 可调整大小。
    summary: 汇总文本（总计/成功/失败/跳过）
    details: 详细失败原因文本
    """
    from PySide6.QtWidgets import (
        QDialog, QHBoxLayout, QVBoxLayout, QTextEdit,
        QLabel, QSplitter, QFrame,
    )
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont

    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumSize(900, 480)
    dlg.resize(1200, 620)
    dlg.setSizeGripEnabled(True)

    main_lay = QVBoxLayout(dlg)
    main_lay.setContentsMargins(20, 16, 20, 16)
    main_lay.setSpacing(12)

    title_lbl = QLabel(title)
    title_lbl.setFont(QFont("Microsoft YaHei", 13, QFont.Weight.Bold))
    title_lbl.setStyleSheet("color: #1a1a2e; padding-bottom: 4px;")
    main_lay.addWidget(title_lbl)

    splitter = QSplitter(Qt.Orientation.Horizontal)
    splitter.setHandleWidth(6)
    splitter.setStyleSheet("QSplitter::handle { background: #dde1e7; border-radius: 3px; }")

    # ---- 左侧：汇总 ----
    left_w = QFrame()
    left_w.setStyleSheet(
        "QFrame { background: #f5f7fa; border: 1px solid #dde1e7; border-radius: 8px; }"
    )
    left_lay = QVBoxLayout(left_w)
    left_lay.setContentsMargins(12, 10, 12, 10)
    left_lay.setSpacing(6)

    lbl_sum = QLabel("计算汇总")
    lbl_sum.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
    lbl_sum.setStyleSheet("color: #333; background: transparent; border: none;")
    left_lay.addWidget(lbl_sum)

    te_sum = QTextEdit()
    te_sum.setReadOnly(True)
    te_sum.setPlainText(summary)
    te_sum.setStyleSheet(
        "QTextEdit { border: none; background: transparent; padding: 4px;"
        " font-family: 'Microsoft YaHei'; font-size: 14px; line-height: 1.8; }"
    )
    left_lay.addWidget(te_sum)
    splitter.addWidget(left_w)

    # ---- 右侧：详细错误 ----
    right_w = QFrame()
    right_w.setStyleSheet(
        "QFrame { background: #fffbf0; border: 1px solid #ffe0a0; border-radius: 8px; }"
    )
    right_lay = QVBoxLayout(right_w)
    right_lay.setContentsMargins(12, 10, 12, 10)
    right_lay.setSpacing(6)

    lbl_det = QLabel("详细失败原因及建议")
    lbl_det.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
    lbl_det.setStyleSheet("color: #8b4000; background: transparent; border: none;")
    right_lay.addWidget(lbl_det)

    te_det = QTextEdit()
    te_det.setReadOnly(True)
    te_det.setPlainText(details)
    te_det.setStyleSheet(
        "QTextEdit { border: none; background: transparent; padding: 4px;"
        " font-family: 'Microsoft YaHei', 'Consolas', monospace; font-size: 13px; }"
    )
    right_lay.addWidget(te_det)
    splitter.addWidget(right_w)

    splitter.setSizes([320, 760])
    main_lay.addWidget(splitter, 1)

    try:
        from qfluentwidgets import PrimaryPushButton
        ok_btn = PrimaryPushButton("确定")
    except Exception:
        from PySide6.QtWidgets import QPushButton
        ok_btn = QPushButton("确定")
    ok_btn.setFixedWidth(120)
    ok_btn.clicked.connect(dlg.accept)

    btn_lay = QHBoxLayout()
    btn_lay.addStretch()
    btn_lay.addWidget(ok_btn)
    main_lay.addLayout(btn_lay)

    dlg.exec()


def fluent_error(parent, title, content):
    """错误提示（仅确定按钮），替代 QMessageBox.critical"""
    from qfluentwidgets import MessageBox
    w = MessageBox(title, content, parent)
    w.yesButton.setText("确定")
    w.cancelButton.hide()
    w.exec()


def fluent_question(parent, title, content, yes_text="是", no_text="否"):
    """询问对话框（是/否），替代 QMessageBox.question
    返回 True 表示点击了"是"按钮"""
    from qfluentwidgets import MessageBox
    w = MessageBox(title, content, parent)
    w.yesButton.setText(yes_text)
    w.cancelButton.setText(no_text)
    return bool(w.exec())


def fluent_select(parent, title, content, items, default_index=0):
    """下拉选择对话框，替代 QInputDialog.getItem
    返回 (selected_text, ok) 元组"""
    from qfluentwidgets import MessageBox, ComboBox
    w = MessageBox(title, content, parent)
    combo = ComboBox()
    combo.addItems(items)
    combo.setCurrentIndex(default_index)
    combo.setFixedWidth(200)
    w.textLayout.addWidget(combo)
    w.yesButton.setText("确定")
    w.cancelButton.setText("取消")
    ok = bool(w.exec())
    return combo.currentText(), ok


# QDialog 统一样式（让弹窗中的 QGroupBox / QLabel 等组件风格一致）
DIALOG_STYLE = f"""
QDialog {{
    background: {CARD};
}}
QGroupBox {{
    font-family: 'Microsoft YaHei', sans-serif;
    font-size: 14px; font-weight: bold; color: {P};
    border: 1px solid {BD}; border-radius: 6px;
    margin-top: 12px; padding: 14px 10px 10px 10px; background: {CARD};
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; background: {CARD}; }}
QLabel {{ font-family: 'Microsoft YaHei', sans-serif; color: {T1}; font-size: 13px; }}
QTextEdit {{ border: 1px solid {BD}; border-radius: 4px; background: #f5f5f5; }}
"""


# ============================================================
# 输入面板组件样式（四个断面计算面板统一使用）
# ============================================================
INPUT_LABEL_STYLE = f"font-family: 'Microsoft YaHei', sans-serif; font-size: 13px; color: {T1};"
INPUT_SECTION_STYLE = f"font-family: 'Microsoft YaHei', sans-serif; font-size: 14px; font-weight: bold; color: {P};"
INPUT_HINT_STYLE = f"font-family: 'Microsoft YaHei', sans-serif; font-size: 11px; color: {T2};"
