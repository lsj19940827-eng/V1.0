"""Show a choice as plain text when there is only one available item."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget


class ChoiceDisplay(QWidget):
    def __init__(self, combo, *, wrap=False):
        super().__init__()
        self.combo = combo
        self.label = QLabel()
        self.label.setTextFormat(Qt.PlainText)
        self.label.setWordWrap(wrap)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.combo, 1)
        layout.addWidget(self.label, 1)
        self.combo.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def refresh(self):
        multiple = self.combo.count() > 1
        self.combo.setVisible(multiple)
        self.label.setVisible(not multiple)
        if not multiple:
            self.label.setText(self.combo.currentText() or self.combo.placeholderText())
