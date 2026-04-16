import logging
from datetime import datetime
from pathlib import Path
import os

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QTextEdit, QPushButton,
    QHBoxLayout, QComboBox
)
from PyQt6.QtCore import pyqtSignal, QObject

from src.config import Config


class LogHandler(QObject, logging.Handler):
    new_record = pyqtSignal(str, str)

    def __init__(self):
        QObject.__init__(self)
        logging.Handler.__init__(self)

        self.setFormatter(logging.Formatter(
            "[%(asctime)s] %(levelname)s [%(tag)s]\n  %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))

    def emit(self, record):
        try:
            if not hasattr(record, "tag"):
                record.tag = "SYSTEM"

            msg = self.format(record)
            self.new_record.emit(msg, record.tag)
        except Exception:
            pass


class LoggerWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Logs")
        self.setMinimumSize(700, 450)

        self.logs = []

        layout = QVBoxLayout(self)

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

    # FIX: Qt signal compatibility
    def apply_filter(self, *_):
        self.text_edit.clear()
        selected = self.filter_combo.currentText()

        for msg, tag in self.logs:
            if selected == "ALL" or tag == selected:
                self.text_edit.append(msg)

    def append_log(self, message, tag):
        self.logs.append((message, tag))

        # защита от бесконечного роста памяти
        if len(self.logs) > 5000:
            self.logs = self.logs[-3000:]

        self.apply_filter()

    def clear_logs(self):
        self.logs.clear()
        self.text_edit.clear()


class Logger:
    _instance = None
    MAX_LOG_FILES = 12
    MAX_LOG_FILE_BYTES = 1_500_000

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = Logger()
        return cls._instance

    def __init__(self):
        self.logger = logging.getLogger("Multiaccount")

        if self.logger.handlers:
            return

        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False

        config = Config()
        logs_dir = config.logs_dir
        logs_dir.mkdir(parents=True, exist_ok=True)
        self._prune_old_logs(logs_dir)

        today = datetime.now().strftime("%Y-%m-%d")
        log_file = logs_dir / f"{today}.log"
        if log_file.exists() and log_file.stat().st_size >= self.MAX_LOG_FILE_BYTES:
            timestamp = datetime.now().strftime("%H%M%S")
            log_file = logs_dir / f"{today}-{timestamp}.log"

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)

        self.qt_handler = LogHandler()

        self.logger.addHandler(file_handler)
        self.logger.addHandler(self.qt_handler)

        self.window = None
        self.qt_handler.new_record.connect(self._on_new_log)

    def _prune_old_logs(self, logs_dir: Path):
        log_files = sorted(
            (path for path in logs_dir.glob("*.log") if path.is_file()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in log_files[self.MAX_LOG_FILES:]:
            try:
                os.remove(path)
            except OSError:
                pass

    def _on_new_log(self, msg, tag):
        if self.window:
            self.window.append_log(msg, tag)

    def show_window(self):
        if self.window is None:
            self.window = LoggerWindow()

        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def _log(self, level, msg, tag="SYSTEM"):
        try:
            self.logger.log(level, msg, extra={"tag": tag})
        except Exception:
            pass

    def info(self, msg): self._log(logging.INFO, msg, "SYSTEM")
    def warning(self, msg): self._log(logging.WARNING, msg, "SYSTEM")
    def error(self, msg): self._log(logging.ERROR, msg, "SYSTEM")
    def user_action(self, msg): self._log(logging.INFO, msg, "USER")
    def api(self, msg): self._log(logging.INFO, msg, "API")
