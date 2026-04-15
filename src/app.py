import asyncio
import sys
import re
from urllib.parse import urlparse
import requests
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QDialog, QLineEdit,
    QLabel, QMessageBox, QComboBox, QTextEdit, QFrame
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


class ProxyDialog(QDialog):
    def __init__(self, lang, account, parent=None):
        super().__init__(parent)
        self.lang = lang
        self.account = account
        self.detected_timezone = account.get("timezone", "Europe/Moscow")
        self.setWindowTitle(lang.get("proxy_settings"))
        self.setFixedSize(520, 220)

        layout = QVBoxLayout()
        layout.addWidget(QLabel(f"{lang.get('account_name')}: {account['name']}"))
        layout.addWidget(QLabel(lang.get("enter_proxy")))

        self.proxy_input = QLineEdit()
        self.proxy_input.setPlaceholderText(self.lang.get("proxy_placeholder", "socks5://user:pass@host:port"))
        current_proxy = account.get("proxy") or {}
        self.proxy_input.setText(account.get("proxy_raw") or current_proxy.get("server", ""))
        layout.addWidget(self.proxy_input)

        self.tz_label = QLabel(f"{lang.get('timezone')}: {self.detected_timezone}")
        layout.addWidget(self.tz_label)

        detect_btn = QPushButton(lang.get("detect_timezone"))
        detect_btn.clicked.connect(self.detect_timezone)
        layout.addWidget(detect_btn)

        btn_layout = QHBoxLayout()
        save_btn = QPushButton(lang.get("save"))
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton(lang.get("cancel"))
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    def _parse_proxy_url(self, value):
        parsed = urlparse(value)
        if parsed.scheme.lower() not in {"socks5", "socks5h", "http", "https"}:
            raise ValueError("Unsupported proxy scheme")
        if not parsed.hostname or not parsed.port:
            raise ValueError("Proxy host/port is required")
        return {
            "server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}",
            "username": parsed.username,
            "password": parsed.password
        }

    def _normalize_compact_proxy(self, value):
        # Поддерживаем форматы:
        # host port
        # host port login password
        # login password port host
        # host:port[:login:password]
        tokens = [token for token in re.split(r"[\s:;,\|]+", value.strip()) if token]
        if len(tokens) == 2:
            host, port = tokens
            username = password = None
        elif len(tokens) == 4 and tokens[1].isdigit():
            host, port, username, password = tokens
        elif len(tokens) == 4 and tokens[2].isdigit():
            username, password, port, host = tokens
        else:
            raise ValueError("Unsupported compact proxy format")

        if not str(port).isdigit():
            raise ValueError("Invalid proxy port")

        return {
            "server": f"socks5://{host}:{int(port)}",
            "username": username,
            "password": password
        }

    def _parse_proxy(self, value):
        if "://" in value:
            return self._parse_proxy_url(value)
        return self._normalize_compact_proxy(value)

    def get_proxy(self):
        raw = self.proxy_input.text().strip()
        if not raw:
            return None
        proxy = self._parse_proxy(raw)
        proxy["raw"] = raw
        return proxy

    def detect_timezone(self):
        try:
            proxy = self.get_proxy()
            if not proxy:
                QMessageBox.warning(self, "Proxy", self.lang.get("proxy_required"))
                return

            proxy_url = proxy["server"]
            if proxy.get("username") and proxy.get("password"):
                parsed = urlparse(proxy_url)
                proxy_url = (
                    f"{parsed.scheme}://{proxy['username']}:{proxy['password']}"
                    f"@{parsed.hostname}:{parsed.port}"
                )

            response = requests.get(
                "https://ipapi.co/timezone/",
                proxies={"http": proxy_url, "https": proxy_url},
                timeout=8
            )
            timezone = response.text.strip()
            if "/" in timezone:
                self.detected_timezone = timezone
                self.tz_label.setText(f"{self.lang.get('timezone')}: {timezone}")
            else:
                raise ValueError("Timezone not detected")
        except Exception as e:
            QMessageBox.warning(self, "Timezone", f"{self.lang.get('timezone_error')}: {e}")


class AsyncWorker(QThread):
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)
    
    def __init__(self, coro):
        super().__init__()
        self.coro = coro
    
    def run(self):
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self.coro)
            self.finished.emit(result)
        except Exception as e:
            self.failed.emit(str(e))
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            loop.close()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.config = Config()
        self.account_manager = AccountManager(self.config)
        self.browser_engine = None
        self.browser_ready = False
        self.logger = Logger.get_instance()
        self._workers = []
        
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
        self.setMinimumSize(1080, 680)
        
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        self.setStyleSheet("""
            QMainWindow, QWidget#central {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #0f1117,stop:1 #171c28);
                color: #f2f5ff;
                font-size: 13px;
            }
            QFrame#topCard, QFrame#tableCard {
                background: rgba(24, 29, 40, 0.94);
                border: 1px solid #2b3446;
                border-radius: 14px;
            }
            QLabel#title {
                font-size: 26px;
                font-weight: 700;
                color: #f5f8ff;
            }
            QLabel#subtitle {
                color: #94a4c3;
                font-size: 13px;
            }
            QLabel#statusBadge {
                background: #3b4461;
                border: 1px solid #576386;
                border-radius: 10px;
                padding: 5px 10px;
                color: #e5ecff;
                font-weight: 600;
            }
            QTableWidget {
                background: #151b28;
                alternate-background-color: #1a2232;
                border: 1px solid #2a3750;
                border-radius: 10px;
                gridline-color: #273246;
                selection-background-color: #2f63ff;
                selection-color: #ffffff;
            }
            QHeaderView::section {
                background: #20293a;
                color: #d9e4ff;
                padding: 8px;
                border: none;
                border-bottom: 1px solid #2d3a52;
            }
            QPushButton {
                background: #2f63ff;
                border: none;
                border-radius: 10px;
                padding: 9px 14px;
                color: #f8fbff;
                font-weight: 600;
            }
            QPushButton:hover { background: #4b78ff; }
            QPushButton:pressed { background: #2754de; }
            QPushButton:disabled { background: #495978; color: #b9c4da; }
            QLineEdit, QComboBox {
                background: #182131;
                border: 1px solid #2e3e5a;
                border-radius: 8px;
                padding: 7px;
                color: #ecf1ff;
            }
        """)

        top_card = QFrame()
        top_card.setObjectName("topCard")
        top_layout = QHBoxLayout(top_card)
        top_layout.setContentsMargins(16, 14, 16, 14)

        title_layout = QVBoxLayout()
        title = QLabel(lang.get("window_title", "Multiaccount"))
        title.setObjectName("title")
        subtitle = QLabel(lang.get("subtitle", "Manage isolated multi-account browser sessions"))
        subtitle.setObjectName("subtitle")
        title_layout.addWidget(title)
        title_layout.addWidget(subtitle)
        top_layout.addLayout(title_layout)

        top_layout.addStretch()
        self.browser_status = QLabel(lang.get("browser_status_init", "Browser initializing..."))
        self.browser_status.setObjectName("statusBadge")
        self.browser_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_layout.addWidget(self.browser_status)
        layout.addWidget(top_card)

        controls_card = QFrame()
        controls_card.setObjectName("topCard")
        controls_layout = QVBoxLayout(controls_card)
        controls_layout.setContentsMargins(16, 12, 16, 12)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        
        self.add_btn = QPushButton(lang.get("add_account"))
        self.add_btn.clicked.connect(self.add_account)
        btn_layout.addWidget(self.add_btn)
        
        self.logs_btn = QPushButton(lang.get("logs"))
        self.logs_btn.clicked.connect(self.logger.show_window)
        btn_layout.addWidget(self.logs_btn)

        self.cleanup_btn = QPushButton(lang.get("cleanup_data"))
        self.cleanup_btn.clicked.connect(self.cleanup_data)
        btn_layout.addWidget(self.cleanup_btn)
        
        btn_layout.addStretch()
        controls_layout.addLayout(btn_layout)
        layout.addWidget(controls_card)
        
        # Таблица аккаунтов
        table_card = QFrame()
        table_card.setObjectName("tableCard")
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(14, 14, 14, 14)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(46)
        self.table.setHorizontalHeaderLabels([
            "ID", 
            lang.get("account_name"), 
            lang.get("domain"),
            lang.get("proxy"),
            ""
        ])
        self.table.horizontalHeader().setStretchLastSection(True)
        table_layout.addWidget(self.table)
        layout.addWidget(table_card, 1)
        
        self.refresh_table()
    
    def init_browser(self):
        async def setup():
            self.browser_engine = BrowserEngine(self.config)
            await self.browser_engine.init()
            
            # Проверяем Chromium
            if not await self.browser_engine.check_chromium():
                self.logger.info("Chromium not found, installing...")
                installed = await self.browser_engine.install_chromium()
                if not installed:
                    return {"error": "Chromium install failed", "ready": False}
            
            self.logger.info("Browser engine ready")
            return {"success": True, "ready": True}
        
        self.run_async(setup(), on_success=self._on_init_browser_done)

    def _on_init_browser_done(self, result):
        if result and result.get("error"):
            self.browser_ready = False
            self.browser_status.setText(self.config.lang.get("browser_status_error", "Browser init error"))
            QMessageBox.warning(self, "Browser", result["error"])
            self.refresh_table()
            return
        self.browser_ready = bool(result and result.get("ready"))
        self.browser_status.setText(
            self.config.lang.get("browser_status_ready", "Browser ready")
            if self.browser_ready
            else self.config.lang.get("browser_status_error", "Browser init error")
        )
        if self.browser_ready:
            self.browser_status.setStyleSheet("background:#1f5b46;border:1px solid #2f8768;color:#d4ffe8;border-radius:10px;padding:5px 10px;font-weight:600;")
        else:
            self.browser_status.setStyleSheet("background:#5d2834;border:1px solid #8e3f4f;color:#ffe3e8;border-radius:10px;padding:5px 10px;font-weight:600;")
        self.refresh_table()

    def cleanup_data(self):
        lang = self.config.lang
        reply = QMessageBox.question(
            self,
            lang.get("cleanup_data"),
            lang.get("cleanup_confirm"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        async def do_cleanup():
            if self.browser_engine:
                await self.browser_engine.shutdown()
            return True

        self.cleanup_worker = AsyncWorker(do_cleanup())
        self.cleanup_worker.finished.connect(self._finish_cleanup)
        self.cleanup_worker.start()

    def _finish_cleanup(self, _):
        self.config.clear_runtime_data()
        self.account_manager.reset_accounts()
        self.browser_engine = None
        self.refresh_table()
        QMessageBox.information(
            self,
            self.config.lang.get("cleanup_data"),
            f"{self.config.lang.get('cleanup_done')} {self.config.lang.get('cleanup_restart')}"
        )
    
   
    def run_async(self, coro, on_success=None, on_error=None):
        try:
            worker = AsyncWorker(coro)
            self._workers.append(worker)

            def cleanup():
                if worker in self._workers:
                    self._workers.remove(worker)

            worker.finished.connect(on_success or (lambda _: None))
            worker.failed.connect(on_error or self._on_async_error)
            worker.finished.connect(lambda _: cleanup())
            worker.failed.connect(lambda _: cleanup())
            worker.start()
        except Exception as e:
            self.logger.error(f"Async error: {e}")

    def _on_async_error(self, message):
        self.logger.error(f"Async worker failed: {message}")
    
    def refresh_table(self):
        lang = self.config.lang
        accounts = self.account_manager.get_accounts()
        
        self.table.setRowCount(len(accounts))
        
        for i, acc in enumerate(accounts):
            self.table.setItem(i, 0, QTableWidgetItem(str(acc["id"])))
            self.table.setItem(i, 1, QTableWidgetItem(acc["name"]))
            
            domain = acc.get("domain") or "—"
            self.table.setItem(i, 2, QTableWidgetItem(domain))
            proxy_data = acc.get("proxy") or {}
            proxy_title = proxy_data.get("server", "—")
            self.table.setItem(i, 3, QTableWidgetItem(proxy_title))
            
            # Кнопки действий
            actions = QWidget()
            actions_layout = QHBoxLayout(actions)
            actions_layout.setContentsMargins(5, 0, 5, 0)
            
            open_btn = QPushButton(lang.get("open_account"))
            open_btn.setEnabled(self.browser_ready)
            open_btn.clicked.connect(lambda _, a=acc: self.open_account(a))
            
            edit_proxy_btn = QPushButton(lang.get("proxy"))
            edit_proxy_btn.clicked.connect(lambda _, a=acc: self.edit_proxy(a))

            delete_btn = QPushButton(lang.get("delete_account"))
            delete_btn.clicked.connect(lambda _, a=acc: self.delete_account(a))
            
            actions_layout.addWidget(open_btn)
            actions_layout.addWidget(edit_proxy_btn)
            actions_layout.addWidget(delete_btn)
            actions_layout.addStretch()
            
            self.table.setCellWidget(i, 4, actions)
    
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
                self.run_async(self.browser_engine.close_account(account["id"]))
            
            self.account_manager.delete_account(account["id"])
            self.refresh_table()

    def edit_proxy(self, account):
        lang = self.config.lang
        dialog = ProxyDialog(lang, account, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                proxy = dialog.get_proxy()
                self.account_manager.update_proxy(
                    account["id"],
                    proxy,
                    timezone=dialog.detected_timezone if proxy else None
                )
                account["proxy"] = proxy
                account["proxy_raw"] = (proxy or {}).get("raw")
                if proxy:
                    account["timezone"] = dialog.detected_timezone
                self.refresh_table()
                self.logger.info(
                    f"Proxy updated for account {account['name']} "
                    f"(timezone: {dialog.detected_timezone})"
                )
            except ValueError:
                QMessageBox.warning(self, "Proxy", lang.get("proxy_invalid"))
    
    def open_account(self, account):
        lang = self.config.lang

        if not self.browser_engine:
            QMessageBox.information(self, "Info", lang.get("cleanup_restart"))
            return
        
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
            return await self.browser_engine.open_account(
                account, 
                self.config,
                on_close=lambda aid: self.on_browser_close(aid)
            )

        self.run_async(
            do_open(),
            on_success=lambda result: self._handle_open_result(result),
            on_error=lambda message: QMessageBox.critical(self, "Error", message)
        )
        self.logger.info(f"Opening account: {account['name']}")

    def _handle_open_result(self, result):
        if result and result.get("error"):
            QMessageBox.critical(self, "Error", result["error"])
    
    def on_browser_close(self, account_id):
        self.logger.info(f"Account {account_id} closed by user")
    
    def closeEvent(self, event):
        loop = None
        try:
            if self.browser_engine:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self.browser_engine.shutdown())
        except Exception as e:
            self.logger.error(f"Shutdown error: {e}")
        finally:
            if loop is not None:
                loop.close()

        self.logger.info("Application closed")
        event.accept()
