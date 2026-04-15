import re
from urllib.parse import urlparse
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QDialog, QLineEdit,
    QLabel, QMessageBox, QComboBox, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal

from src.account_overlay import AccountOverlay
from src.config import Config
from src.account_manager import AccountManager
from src.browser_runtime import BrowserRuntime
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
    detect_requested = pyqtSignal()

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
        detect_btn.clicked.connect(self.detect_requested.emit)
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

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.config = Config()
        self.account_manager = AccountManager(self.config)
        self.browser_runtime = BrowserRuntime(self.config, Logger.get_instance())
        self.browser_ready = False
        self.logger = Logger.get_instance()
        self.browser_runtime.browser_closed.connect(self.on_browser_close)
        self.open_account_ids = set()
        self.overlays = {}
        
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
        self.browser_runtime.initialize(
            on_success=self._on_init_browser_done,
            on_error=self._on_async_error,
        )

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

        self.browser_runtime.shutdown_sync()
        self._finish_cleanup(True)

    def _finish_cleanup(self, _):
        self.config.clear_runtime_data()
        self.account_manager.reset_accounts()
        self.browser_ready = False
        self.open_account_ids.clear()
        self._clear_overlays()
        self.browser_runtime = BrowserRuntime(self.config, self.logger)
        self.browser_runtime.browser_closed.connect(self.on_browser_close)
        self.browser_status.setText(self.config.lang.get("cleanup_restart"))
        self.browser_status.setStyleSheet("background:#5d2834;border:1px solid #8e3f4f;color:#ffe3e8;border-radius:10px;padding:5px 10px;font-weight:600;")
        self.refresh_table()
        QMessageBox.information(
            self,
            self.config.lang.get("cleanup_data"),
            f"{self.config.lang.get('cleanup_done')} {self.config.lang.get('cleanup_restart')}"
        )

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
            status = lang.get("status_active") if acc["id"] in self.open_account_ids else lang.get("status_inactive")
            proxy_title = f"{status} | {proxy_data.get('server', '—')}"
            self.table.setItem(i, 3, QTableWidgetItem(proxy_title))
            
            # Кнопки действий
            actions = QWidget()
            actions_layout = QHBoxLayout(actions)
            actions_layout.setContentsMargins(5, 0, 5, 0)
            
            open_btn = QPushButton(lang.get("open_account"))
            open_btn.setEnabled(self.browser_ready)
            open_btn.clicked.connect(lambda _, a=acc: self.open_account(a))

            close_btn = QPushButton(lang.get("close_account"))
            close_btn.setEnabled(acc["id"] in self.open_account_ids)
            close_btn.clicked.connect(lambda _, aid=acc["id"]: self.close_account(aid))
            
            edit_proxy_btn = QPushButton(lang.get("proxy"))
            edit_proxy_btn.clicked.connect(lambda _, a=acc: self.edit_proxy(a))

            delete_btn = QPushButton(lang.get("delete_account"))
            delete_btn.clicked.connect(lambda _, a=acc: self.delete_account(a))
            
            actions_layout.addWidget(open_btn)
            actions_layout.addWidget(close_btn)
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
            self.browser_runtime.close_account(
                account["id"],
                on_success=lambda _result, aid=account["id"]: self._finalize_delete_account(aid),
                on_error=lambda message, aid=account["id"]: self._delete_after_error(aid, message),
            )

    def close_account(self, account_id):
        self.browser_runtime.close_account(
            account_id,
            on_success=lambda _result: None,
            on_error=lambda message: self.logger.warning(f"Close account failed: {message}"),
        )

    def _finalize_delete_account(self, account_id):
        self.open_account_ids.discard(account_id)
        self._close_overlay(account_id)
        self.account_manager.delete_account(account_id)
        self.refresh_table()

    def _delete_after_error(self, account_id, message):
        self.logger.warning(f"Account close before delete failed: {message}")
        self._finalize_delete_account(account_id)

    def edit_proxy(self, account):
        lang = self.config.lang
        dialog = ProxyDialog(lang, account, self)
        dialog.detect_requested.connect(lambda: self._detect_timezone_for_dialog(dialog))
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

        if not self.browser_ready:
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

        self.logger.info(f"Opening account: {account['name']}")
        if account.get("proxy"):
            self.browser_runtime.detect_timezone(
                account["proxy"],
                on_success=lambda timezone, acc=account: self._open_account_with_timezone(acc, timezone),
                on_error=lambda message, acc=account: self._open_account_without_timezone(acc, message),
            )
            return

        self._submit_open_account(account)

    def _open_account_with_timezone(self, account, timezone):
        if timezone:
            self.account_manager.update_proxy(account["id"], account.get("proxy"), timezone=timezone)
            account["timezone"] = timezone
        self._submit_open_account(account)

    def _open_account_without_timezone(self, account, message):
        self.logger.warning(f"Timezone sync failed for account {account['name']}: {message}")
        self._submit_open_account(account)

    def _submit_open_account(self, account):
        self.browser_runtime.open_account(
            dict(account),
            on_success=self._handle_open_result,
            on_error=lambda message: QMessageBox.critical(self, "Error", message),
        )

    def _handle_open_result(self, result):
        if result and result.get("error"):
            QMessageBox.critical(self, "Error", result["error"])
            return
        if result and result.get("success"):
            account_id = result.get("account_id")
            if account_id is not None:
                self.open_account_ids.add(account_id)
                self._show_overlay(account_id, result.get("overlay") or {})
                self.refresh_table()
    
    def on_browser_close(self, account_id):
        self.open_account_ids.discard(account_id)
        self._close_overlay(account_id)
        self.refresh_table()
        self.logger.info(f"Account {account_id} closed by user")

    def _overlay_details(self, overlay):
        return [
            (self.config.lang.get("overlay_ip", "IP"), overlay.get("ip", "unknown")),
            (self.config.lang.get("overlay_timezone", "Timezone"), overlay.get("timezone", "unknown")),
            (self.config.lang.get("overlay_location", "Location"), f"{overlay.get('city', 'unknown')}, {overlay.get('country', 'unknown')}"),
            (self.config.lang.get("overlay_device", "Device"), overlay.get("device", "unknown")),
            (self.config.lang.get("overlay_os", "OS"), overlay.get("os", "unknown")),
            (self.config.lang.get("overlay_browser", "Browser"), overlay.get("browser", "unknown")),
        ]

    def _show_overlay(self, account_id, overlay):
        self._close_overlay(account_id)
        title = f"{overlay.get('account_name', 'Account')} #{account_id}"
        widget = AccountOverlay(title, self._overlay_details(overlay), slot_index=len(self.overlays))
        self.overlays[account_id] = widget
        self._reposition_overlays()
        widget.show()

    def _close_overlay(self, account_id):
        widget = self.overlays.pop(account_id, None)
        if widget:
            widget.close()
        self._reposition_overlays()

    def _clear_overlays(self):
        for account_id in list(self.overlays.keys()):
            self._close_overlay(account_id)

    def _reposition_overlays(self):
        for index, account_id in enumerate(sorted(self.overlays.keys())):
            self.overlays[account_id].reposition(index)

    def _detect_timezone_for_dialog(self, dialog):
        try:
            proxy = dialog.get_proxy()
        except ValueError:
            QMessageBox.warning(self, "Proxy", self.config.lang.get("proxy_invalid"))
            return

        if not proxy:
            QMessageBox.warning(self, "Proxy", self.config.lang.get("proxy_required"))
            return

        dialog.tz_label.setText(f"{self.config.lang.get('timezone')}: ...")
        self.browser_runtime.detect_timezone(
            proxy,
            on_success=lambda timezone, dlg=dialog: self._apply_dialog_timezone(dlg, timezone),
            on_error=lambda message, dlg=dialog: self._show_dialog_timezone_error(dlg, message),
        )

    def _apply_dialog_timezone(self, dialog, timezone):
        if timezone:
            dialog.detected_timezone = timezone
            dialog.tz_label.setText(f"{self.config.lang.get('timezone')}: {timezone}")

    def _show_dialog_timezone_error(self, dialog, message):
        dialog.tz_label.setText(f"{self.config.lang.get('timezone')}: {dialog.detected_timezone}")
        QMessageBox.warning(self, "Timezone", f"{self.config.lang.get('timezone_error')}: {message}")
    
    def closeEvent(self, event):
        try:
            self._clear_overlays()
            self.browser_runtime.shutdown_sync()
        except Exception as e:
            self.logger.error(f"Shutdown error: {e}")

        self.logger.info("Application closed")
        event.accept()
