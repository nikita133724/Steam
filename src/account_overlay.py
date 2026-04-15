from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget


class AccountOverlay(QWidget):
    def __init__(self, title: str, details: list[tuple[str, str]], slot_index: int = 0):
        super().__init__(None)
        self.setWindowTitle(title)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(6)

        card = QWidget(self)
        card.setStyleSheet(
            "background: rgba(15, 22, 33, 0.82);"
            "border: 1px solid rgba(122, 162, 255, 0.40);"
            "border-radius: 14px;"
            "color: #f1f5ff;"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 12, 12, 12)
        card_layout.setSpacing(4)

        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 14px; font-weight: 700; color: #ffffff;")
        card_layout.addWidget(title_label)

        for label, value in details:
            row = QLabel(f"<b>{label}:</b> {value}")
            row.setTextFormat(Qt.TextFormat.RichText)
            row.setWordWrap(True)
            row.setStyleSheet("font-size: 12px; color: #d7e4ff;")
            card_layout.addWidget(row)

        layout.addWidget(card)
        self.adjustSize()
        self.reposition(slot_index)

    def reposition(self, slot_index: int):
        screen = self.screen()
        if screen:
            geometry = screen.availableGeometry()
            margin = 18
            x = geometry.x() + geometry.width() - self.width() - margin
            y = geometry.y() + margin + slot_index * (self.height() + 10)
            self.move(max(x, margin), max(y, margin))
