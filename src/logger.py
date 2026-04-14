import logging
import sys
from datetime import datetime
from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QTextEdit, QPushButton, QHBoxLayout
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject


class LogHandler(QObject, logging.Handler):
    new_record = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.setFormatter(logging.Formatter(
            '[%(asctime)s] %(levelname)s\n  %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
    
    def emit(self, record):
        msg = self.format(record)
        self.new_record.emit(msg)


class LoggerWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Logs")
        self.setMinimumSize(600, 400)
        
        layout = QVBoxLayout()
        
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
    
    def append_log(self, message):
        self.text_edit.append(message)
    
    def clear_logs(self):
        self.text_edit.clear()


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
        
        # File handler
        logs_dir = Path.home() / "Multiaccount" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_file = logs_dir / f"{datetime.now().strftime('%Y-%m-%d')}.log"
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        
        # Qt handler
        self.qt_handler = LogHandler()
        
        self.logger.addHandler(file_handler)
        self.logger.addHandler(self.qt_handler)
        
        self.window = LoggerWindow()
        self.qt_handler.new_record.connect(self.window.append_log)
    
    def info(self, msg):
        self.logger.info(msg)
    
    def error(self, msg):
        self.logger.error(msg)
    
    def debug(self, msg):
        self.logger.debug(msg)
    
    def show_window(self):
        self.window.show()
        self.window.raise_()
    
    def get_handler(self):
        return self.qt_handler
