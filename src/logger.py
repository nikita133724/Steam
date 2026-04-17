import logging
from datetime import datetime
from pathlib import Path
import os
import re

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QTextEdit, QPushButton,
    QHBoxLayout, QComboBox
)
from PyQt6.QtCore import pyqtSignal, QObject

from src.config import Config
from src.ui_theme import apply_dialog_chrome, style_dialog_layout, mark_secondary_button


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
    clear_requested = pyqtSignal()

    def __init__(self, lang=None, theme=None, parent=None):
        super().__init__(parent)
        self.lang = dict(lang or {})
        self._theme = theme

        self.logs = []

        layout = QVBoxLayout(self)
        style_dialog_layout(layout)

        self.filter_combo = QComboBox()
        self.filter_combo.currentTextChanged.connect(self.apply_filter)
        layout.addWidget(self.filter_combo)

        self.text_edit = QTextEdit()
        self.text_edit.setObjectName("logView")
        self.text_edit.setReadOnly(True)
        layout.addWidget(self.text_edit)

        btn_layout = QHBoxLayout()

        self.clear_btn = QPushButton()
        mark_secondary_button(self.clear_btn)
        self.clear_btn.clicked.connect(self.clear_logs)

        self.close_btn = QPushButton()
        mark_secondary_button(self.close_btn)
        self.close_btn.clicked.connect(self.hide)

        btn_layout.addWidget(self.clear_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.close_btn)

        layout.addLayout(btn_layout)
        self.update_chrome(self.lang, theme)

    # FIX: Qt signal compatibility
    def apply_filter(self, *_):
        self.text_edit.clear()
        selected = self.filter_combo.currentData() or "ALL"

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
        self.clear_requested.emit()

    def set_logs(self, entries):
        self.logs = list(entries or [])
        self.apply_filter()

    def update_chrome(self, lang=None, theme=None):
        if lang is not None:
            self.lang = dict(lang or {})
        if theme is not None:
            self._theme = theme
            apply_dialog_chrome(self, theme, 760, 520, min_width=720, min_height=460)

        self.setWindowTitle(self.lang.get("dialog_logs_title", "Logs"))
        current_value = self.filter_combo.currentData() or "ALL"
        labels = [
            (self.lang.get("dialog_logs_all", "All"), "ALL"),
            (self.lang.get("dialog_logs_system", "System"), "SYSTEM"),
            (self.lang.get("dialog_logs_user", "User"), "USER"),
            (self.lang.get("dialog_logs_api", "API"), "API"),
        ]
        self.filter_combo.blockSignals(True)
        self.filter_combo.clear()
        for label, value in labels:
            self.filter_combo.addItem(label, value)
        index = self.filter_combo.findData(current_value)
        self.filter_combo.setCurrentIndex(index if index >= 0 else 0)
        self.filter_combo.blockSignals(False)
        self.clear_btn.setText(self.lang.get("dialog_logs_clear", "Clear"))
        self.close_btn.setText(self.lang.get("dialog_logs_close", "Close"))
        self.apply_filter()


class Logger:
    _instance = None
    MAX_LOG_FILES = 12
    MAX_LOG_FILE_BYTES = 1_500_000
    LOG_HISTORY_LIMIT = 3000

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
        self.log_file = log_file
        self.history = []

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)

        self.qt_handler = LogHandler()

        self.logger.addHandler(file_handler)
        self.logger.addHandler(self.qt_handler)

        self.window = None
        self._suppress_file_reload = False
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
        self.history.append((msg, tag))
        if len(self.history) > 5000:
            self.history = self.history[-self.LOG_HISTORY_LIMIT:]
        if self.window:
            self.window.append_log(msg, tag)

    def _clear_history(self):
        self.history = []
        self._suppress_file_reload = True

    def _load_recent_history_from_file(self):
        if not self.log_file.exists():
            return []

        entries = []
        current_lines = []
        current_tag = "SYSTEM"

        try:
            with open(self.log_file, "r", encoding="utf-8", errors="replace") as handle:
                for raw_line in handle.read().splitlines():
                    if raw_line.startswith("["):
                        if current_lines:
                            entries.append(("\n".join(current_lines), current_tag))
                        current_lines = [raw_line]
                        match = re.search(r"\[([^\]]+)\]\s*$", raw_line)
                        current_tag = match.group(1) if match else "SYSTEM"
                    elif current_lines:
                        current_lines.append(raw_line)
                    else:
                        current_lines = [raw_line]

            if current_lines:
                entries.append(("\n".join(current_lines), current_tag))
        except OSError:
            return []

        return entries[-self.LOG_HISTORY_LIMIT:]

    def show_window(self, lang=None, theme=None):
        if not self.history and not self._suppress_file_reload:
            self.history = self._load_recent_history_from_file()
        if self.window is None:
            self.window = LoggerWindow(lang=lang, theme=theme)
            self.window.clear_requested.connect(self._clear_history)
        else:
            self.window.update_chrome(lang=lang, theme=theme)
        self.window.set_logs(self.history)

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
