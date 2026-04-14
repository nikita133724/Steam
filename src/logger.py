import logging
from datetime import datetime
from pathlib import Path
from src.config import Config
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QTextEdit, QPushButton, QHBoxLayout, QComboBox
)
from PyQt6.QtCore import pyqtSignal, QObject


# =========================
# LOG HANDLER (Qt + logging)
# =========================
class LogHandler(QObject, logging.Handler):
    new_record = pyqtSignal(str, str)  # message, level

    def __init__(self):
        QObject.__init__(self)
        logging.Handler.__init__(self)

        self.setFormatter(logging.Formatter(
            '[%(asctime)s] %(levelname)s [%(tag)s]\n  %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))

    def emit(self, record):
        if not hasattr(record, "tag"):
            record.tag = "SYSTEM"

        msg = self.format(record)
        self.new_record.emit(msg, record.tag)


# =========================
# LOG WINDOW (UI)
# =========================
class LoggerWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Logs")
        self.setMinimumSize(700, 450)

        self.logs = []  # (message, tag)

        layout = QVBoxLayout()

        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["ALL", "SYSTEM", "USER", "API"])
        self.filter_combo.currentTextChanged.connect(self.apply_filter)
        layout.addWidget(self.filter_combo)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        layout.addWidget(self.text_edit)

        btn_layout = QHBoxLayout()

        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.clear_logs)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.hide)

        btn_layout.addWidget(clear_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def append_log(self, message, tag):
        self.logs.append((message, tag))
        self.apply_filter()

    def apply_filter(self):
        self.text_edit.clear()
        selected = self.filter_combo.currentText()

        for msg, tag in self.logs:
            if selected == "ALL" or tag == selected:
                self.text_edit.append(msg)

    def clear_logs(self):
        self.logs.clear()
        self.text_edit.clear()


# =========================
# LOGGER SINGLETON
# =========================
class Logger:
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = Logger()
        return cls._instance

    def __init__(self):
        self.logger = logging.getLogger("Multiaccount")
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False

        if self.logger.handlers:
            return

        logs_dir = Config().logs_dir
        logs_dir.mkdir(parents=True, exist_ok=True)

        today = datetime.now().strftime('%Y-%m-%d')
        log_file = logs_dir / f"{today}.log"

        # 🧹 удалить старые логи (оставить только сегодня)
        for f in logs_dir.glob("*.log"):
            if f.name != f"{today}.log":
                try:
                    f.unlink()
                except:
                    pass

        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)

        self.qt_handler = LogHandler()

        self.logger.addHandler(file_handler)
        self.logger.addHandler(self.qt_handler)

        self.window = None

        self.qt_handler.new_record.connect(self._on_new_log)

    def _on_new_log(self, msg, tag):
        if self.window:
            self.window.append_log(msg, tag)

    def show_window(self):
        if self.window is None:
            self.window = LoggerWindow()
        self.window.show()
        self.window.raise_()

    # =========================
    # BASE LOG
    # =========================
    def _log(self, level, msg, tag="SYSTEM"):
        extra = {"tag": tag}
        self.logger.log(level, msg, extra=extra)

    # =========================
    # SYSTEM
    # =========================
    def info(self, msg):
        self._log(logging.INFO, msg, "SYSTEM")

    def warning(self, msg):
        self._log(logging.WARNING, msg, "SYSTEM")

    def error(self, msg):
        self._log(logging.ERROR, msg, "SYSTEM")

    # =========================
    # USER ACTIONS
    # =========================
    def user_action(self, msg):
        self._log(logging.INFO, msg, "USER")

    # =========================
    # API LOGS
    # =========================
    def api(self, msg):
        self._log(logging.INFO, msg, "API")