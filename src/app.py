import asyncio
import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QDialog, QLineEdit,
    QLabel, QMessageBox, QComboBox, QTextEdit
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QIcon

from src.config import Config
from src.account_manager import AccountManager
from src.browser_engine import BrowserEngine
from src.logger import Logger


class LanguageDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Welcome / Добро пожаловать")
        self.setFixedSize(300, 150)
        
        layout = QVBoxLayout()
        
        layout.addWidget(QLabel("Select language / Выберите язык:"))
        
        self.combo = QComboBox()
        self.combo.addItem("Русский", "ru")
        self.combo.addItem("English", "en")
        layout.addWidget(self.combo)
        
        btn = QPushButton("OK")
        btn.clicked.connect(self.accept)
        layout.addWidget(btn)
        
        self.setLayout(layout)
    
    def get_language(self):
        return self.combo.currentData()


class DomainDialog(QDialog):
    def __init__(self, account_name, lang, parent=None):
        super().__init__(parent)
        self.setWindowTitle(lang.get("enter_domain"))
        self.setFixedSize(400, 150)
        
        layout = QVBoxLayout()
        
        layout.addWidget(QLabel(f"{lang.get('account_name')}: {account_name}"))
        layout.addWidget(QLabel(lang.get("enter_domain")))
        
        self.domain_input = QLineEdit()
        self.domain_input.setPlaceholderText("https://example.com")
        layout.addWidget(self.domain_input)
        
        btn_layout = QHBoxLayout()
        save_btn = QPushButton(lang.get("remember"))
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton(lang.get("cancel"))
        cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        
        self.setLayout(layout)
    
    def get_domain(self):
        return self.domain_input.text()


class AddAccountDialog(QDialog):
    def __init__(self, lang, parent=None):
        super().__init__(parent)
        self.lang = lang
        self.setWindowTitle(lang.get("add_account"))
        self.setFixedSize(300, 150)
        
        layout = QVBoxLayout()
        
        layout.addWidget(QLabel(lang.get("account_name")))
        
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Account 1")
        layout.addWidget(self.name_input)
        
        btn_layout = QHBoxLayout()
        save_btn = QPushButton(lang.get("save"))
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton(lang.get("cancel"))
        cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        
        self.setLayout(layout)
    
    def get_name(self):
        return self.name_input.text() or "Unnamed"


class AsyncWorker(QThread):
    finished = pyqtSignal(object)
    
    def __init__(self, coro):
        super().__init__()
        self.coro = coro
    
    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(self.coro)
        self.finished.emit(result)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.config = Config()
        self.account_manager = AccountManager(self.config)
        self.browser_engine = None
        self.logger = Logger.get_instance()
        
        # Проверяем первый запуск
        if self.config.data.get("first_run", True):
            self.show_language_dialog()
        
        self.setup_ui()
        self.init_browser()
    
    def show_language_dialog(self):
        dialog = LanguageDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            lang = dialog.get_language()
            self.config.set_language(lang)
            self.config.data["first_run"] = False
            self.config.save_config()
    
    def setup_ui(self):
        lang = self.config.lang
        
        self.setWindowTitle(lang.get("window_title", "Multiaccount"))
        self.setMinimumSize(800, 500)
        
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        # Кнопки управления
        btn_layout = QHBoxLayout()
        
        self.add_btn = QPushButton(lang.get("add_account"))
        self.add_btn.clicked.connect(self.add_account)
        btn_layout.addWidget(self.add_btn)
        
        self.logs_btn = QPushButton(lang.get("logs"))
        self.logs_btn.clicked.connect(self.logger.show_window)
        btn_layout.addWidget(self.logs_btn)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        # Таблица аккаунтов
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels([
            "ID", 
            lang.get("account_name"), 
            lang.get("domain"),
            ""
        ])
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        
        self.refresh_table()
    
    def init_browser(self):
        async def setup():
            self.browser_engine = BrowserEngine()
            await self.browser_engine.init()
            
            # Проверяем Chromium
            if not await self.browser_engine.check_chromium():
                self.logger.info("Chromium not found, installing...")
                await self.browser_engine.install_chromium()
            
            self.logger.info("Browser engine ready")
        
        self.run_async(setup())
    
    def run_async(self, coro):
        self.worker = AsyncWorker(coro)
        self.worker.finished.connect(lambda _: None)
        self.worker.start()
    
    def refresh_table(self):
        lang = self.config.lang
        accounts = self.account_manager.get_accounts()
        
        self.table.setRowCount(len(accounts))
        
        for i, acc in enumerate(accounts):
            self.table.setItem(i, 0, QTableWidgetItem(str(acc["id"])))
            self.table.setItem(i, 1, QTableWidgetItem(acc["name"]))
            
            domain = acc.get("domain") or "—"
            self.table.setItem(i, 2, QTableWidgetItem(domain))
            
            # Кнопки действий
            actions = QWidget()
            actions_layout = QHBoxLayout(actions)
            actions_layout.setContentsMargins(5, 0, 5, 0)
            
            open_btn = QPushButton(lang.get("open_account"))
            open_btn.clicked.connect(lambda _, a=acc: self.open_account(a))
            
            delete_btn = QPushButton(lang.get("delete_account"))
            delete_btn.clicked.connect(lambda _, a=acc: self.delete_account(a))
            
            actions_layout.addWidget(open_btn)
            actions_layout.addWidget(delete_btn)
            actions_layout.addStretch()
            
            self.table.setCellWidget(i, 3, actions)
    
    def add_account(self):
        lang = self.config.lang
        dialog = AddAccountDialog(lang, self)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            name = dialog.get_name()
            self.account_manager.add_account(name)
            self.refresh_table()
            self.logger.info(f"Added account: {name}")
    
    def delete_account(self, account):
        lang = self.config.lang
        
        reply = QMessageBox.question(
            self,
            lang.get("delete_account"),
            f"Delete {account['name']}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # Закрываем браузер если открыт
            if self.browser_engine:
                asyncio.create_task(self.browser_engine.close_account(account["id"]))
            
            self.account_manager.delete_account(account["id"])
            self.refresh_table()
    
    def open_account(self, account):
        lang = self.config.lang
        
        # Проверяем домен
        if not account.get("domain"):
            domain_dialog = DomainDialog(account["name"], lang, self)
            if domain_dialog.exec() == QDialog.DialogCode.Accepted:
                domain = domain_dialog.get_domain()
                if domain:
                    self.account_manager.update_domain(account["id"], domain)
                    self.refresh_table()
                    account["domain"] = domain
                else:
                    return
        
        # Открываем браузер
        async def do_open():
            result = await self.browser_engine.open_account(
                account, 
                self.config,
                on_close=lambda aid: self.on_browser_close(aid)
            )
            
            if result and result.get("need_domain"):
                # Не должно произойти, но на всякий случай
                pass
            elif result and result.get("error"):
                QMessageBox.critical(self, "Error", result["error"])
        
        self.run_async(do_open())
        self.logger.info(f"Opening account: {account['name']}")
    
    def on_browser_close(self, account_id):
        self.logger.info(f"Account {account_id} closed by user")
    
    def closeEvent(self, event):
        # Мягкое закрытие всех браузеров
        if self.browser_engine:
            async def close_all():
                await self.browser_engine.close_all()
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(close_all())
        
        self.logger.info("Application closed")
        event.accept()
