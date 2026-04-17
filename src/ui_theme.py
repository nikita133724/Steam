from PyQt6.QtCore import Qt


def build_dialog_stylesheet(theme):
    return """
        QDialog {
            background: %(card_bg)s;
            color: %(text)s;
            border: 1px solid %(card_border)s;
            border-radius: 16px;
            font-family: "Segoe UI";
            font-size: 13px;
        }
        QLabel {
            color: %(text)s;
        }
        QLabel#dialogTitle {
            color: %(text)s;
            font-size: 18px;
            font-weight: 700;
        }
        QLabel#dialogHint {
            color: %(muted)s;
            font-size: 12px;
        }
        QLineEdit, QComboBox, QTextEdit {
            background: %(input_bg)s;
            border: 1px solid %(input_border)s;
            border-radius: 10px;
            padding: 8px 10px;
            color: %(text)s;
        }
        QScrollArea {
            border: none;
            background: transparent;
        }
        QComboBox QAbstractItemView {
            background: %(input_bg)s;
            color: %(text)s;
            border: 1px solid %(input_border)s;
            selection-background-color: %(button_bg)s;
            selection-color: #ffffff;
        }
        QPushButton {
            background: %(button_bg)s;
            border: none;
            border-radius: 10px;
            color: #ffffff;
            font-weight: 600;
            padding: 9px 14px;
        }
        QPushButton:hover {
            background: %(button_hover)s;
        }
        QPushButton:pressed {
            background: %(button_pressed)s;
        }
        QPushButton[secondary="true"] {
            background: transparent;
            border: 1px solid %(input_border)s;
            color: %(text)s;
        }
        QPushButton[secondary="true"]:hover {
            background: %(table_header)s;
        }
        QPushButton[secondary="true"]:pressed {
            background: %(table_alt)s;
        }
        QCheckBox {
            color: %(text)s;
        }
        QMenu {
            background: %(card_bg)s;
            color: %(text)s;
            border: 1px solid %(card_border)s;
        }
        QMenu::item {
            padding: 7px 14px;
            border-radius: 6px;
        }
        QMenu::item:selected {
            background: %(table_header)s;
        }
        QScrollBar:vertical {
            width: 12px;
            margin: 2px;
            background: transparent;
        }
        QScrollBar::handle:vertical {
            min-height: 32px;
            border-radius: 6px;
            background: %(input_border)s;
        }
        QScrollBar::handle:vertical:hover {
            background: %(button_hover)s;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
            height: 0px;
            background: transparent;
        }
    """ % theme


def apply_dialog_chrome(dialog, theme, width, height, min_width=None, min_height=None):
    dialog.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
    dialog.setStyleSheet(build_dialog_stylesheet(theme))
    dialog.resize(width, height)
    dialog.setMinimumSize(min_width or width, min_height or height)


def style_dialog_layout(layout, margins=18, spacing=12):
    layout.setContentsMargins(margins, margins, margins, margins)
    layout.setSpacing(spacing)


def mark_secondary_button(button):
    button.setProperty("secondary", True)
