import re
import sys
from pathlib import Path
from urllib.parse import urlparse
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QDialog, QLineEdit,
    QLabel, QMessageBox, QComboBox, QFrame, QProgressBar, QSystemTrayIcon, QMenu,
    QApplication, QTextEdit
)
from PyQt6.QtCore import Qt, pyqtSignal, QEvent, QTimer
from PyQt6.QtGui import QIcon, QAction, QGuiApplication, QColor, QBrush

from src.account_overlay import AccountOverlay
from src.config import Config
from src.account_manager import AccountManager
from src.browser_runtime import BrowserRuntime
from src.logger import Logger
from src.update_manager import UpdateManager
from src.url_utils import normalize_target_url
from src.browser_bar import BrowserBarDialog
from src.launcher import launch_staged_update


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
    def __init__(self, account_name, lang, current_domain="", parent=None):
        super().__init__(parent)
        self.lang = lang
        self._normalized_domain = ""
        self.setWindowTitle(lang.get("enter_domain"))
        self.setFixedSize(400, 150)
        
        layout = QVBoxLayout()
        
        layout.addWidget(QLabel(f"{lang.get('account_name')}: {account_name}"))
        layout.addWidget(QLabel(lang.get("enter_domain")))
        
        self.domain_input = QLineEdit()
        self.domain_input.setPlaceholderText("https://example.com")
        self.domain_input.setText(current_domain or "")
        layout.addWidget(self.domain_input)
        
        btn_layout = QHBoxLayout()
        save_btn = QPushButton(lang.get("remember"))
        save_btn.clicked.connect(self._on_save)
        cancel_btn = QPushButton(lang.get("cancel"))
        cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        
        self.setLayout(layout)

    def _on_save(self):
        try:
            self._normalized_domain = normalize_target_url(self.domain_input.text())
        except ValueError:
            QMessageBox.warning(
                self,
                self.lang.get("enter_domain"),
                self.lang.get("domain_invalid", "Введите корректный URL."),
            )
            return
        self.accept()

    def get_domain(self):
        return self._normalized_domain


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


class DeleteConfirmDialog(QDialog):
    def __init__(self, lang, account_name, parent=None):
        super().__init__(parent)
        self.lang = lang
        self.setWindowTitle(lang.get("delete_account"))
        self.setFixedSize(440, 170)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel(lang.get("delete_confirm_title", "Подтвердите удаление"))
        title.setStyleSheet("font-size: 15px; font-weight: 700;")
        layout.addWidget(title)

        message = lang.get("delete_confirm_text", "Удалить аккаунт \"{account}\" без возможности отмены?")
        body = QLabel(message.format(account=account_name))
        body.setWordWrap(True)
        layout.addWidget(body)

        buttons = QHBoxLayout()
        buttons.addStretch()
        no_btn = QPushButton(lang.get("confirm_no", "Нет"))
        no_btn.clicked.connect(self.reject)
        yes_btn = QPushButton(lang.get("confirm_yes", "Да"))
        yes_btn.clicked.connect(self.accept)
        buttons.addWidget(no_btn)
        buttons.addWidget(yes_btn)
        layout.addLayout(buttons)

    def showEvent(self, event):
        super().showEvent(event)
        self._center_to_parent()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and not self.isActiveWindow():
            QApplication.beep()
            self.raise_()
            self.activateWindow()

    def _center_to_parent(self):
        parent = self.parentWidget()
        if parent is None:
            return
        parent_geometry = parent.frameGeometry()
        geometry = self.frameGeometry()
        geometry.moveCenter(parent_geometry.center())
        self.move(geometry.topLeft())


class AccountInfoDialog(QDialog):
    def __init__(self, lang, account_name, details, parent=None):
        super().__init__(parent)
        self.setWindowTitle(lang.get("account_info_title", "Информация по аккаунту"))
        self.setFixedSize(430, 260)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        title = QLabel(account_name)
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        layout.addWidget(title)

        for label, value in details:
            row = QLabel(f"<b>{label}:</b> {value}")
            row.setTextFormat(Qt.TextFormat.RichText)
            row.setWordWrap(True)
            layout.addWidget(row)

        close_btn = QPushButton(lang.get("close_account_info", "Закрыть"))
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)


class ProxyDialog(QDialog):
    detect_requested = pyqtSignal()

    def __init__(self, lang, account, parent=None):
        super().__init__(parent)
        self.lang = lang
        self.account = account
        self.detected_timezone = account.get("timezone", "Europe/Moscow")
        self.setWindowTitle(lang.get("proxy_settings"))
        self.setFixedSize(520, 250)

        layout = QVBoxLayout()
        layout.addWidget(QLabel(f"{lang.get('account_name')}: {account['name']}"))
        layout.addWidget(QLabel(lang.get("enter_proxy")))

        self.proxy_input = QLineEdit()
        self.proxy_input.setPlaceholderText(self.lang.get("proxy_placeholder", "socks5://user:pass@host:port"))
        current_proxy = account.get("proxy") or {}
        self.proxy_input.setText(account.get("proxy_raw") or current_proxy.get("server", ""))
        layout.addWidget(self.proxy_input)

        self.proxy_type = QComboBox()
        self.proxy_type.addItem("SOCKS5", "socks5")
        self.proxy_type.addItem("HTTP", "http")
        self.proxy_type.addItem("HTTPS", "https")
        current_scheme = self._detect_proxy_scheme(account)
        index = self.proxy_type.findData(current_scheme)
        self.proxy_type.setCurrentIndex(index if index >= 0 else 0)
        layout.addWidget(self.proxy_type)

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

    def _detect_proxy_scheme(self, account):
        proxy = account.get("proxy") or {}
        server = proxy.get("server", "")
        if not server or "://" not in server:
            return "socks5"
        parsed = urlparse(server)
        scheme = (parsed.scheme or "").lower()
        if scheme == "socks5h":
            scheme = "socks5"
        return scheme if scheme in {"socks5", "http", "https"} else "socks5"

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
        selected_scheme = self.proxy_type.currentData() or "socks5"
        compact = value.strip()

        if "@" in compact and ":" in compact:
            auth, hostport = compact.rsplit("@", 1)
            if ":" not in hostport:
                raise ValueError("Invalid proxy format")
            host, port = hostport.rsplit(":", 1)
            if ":" not in auth:
                raise ValueError("Invalid proxy auth")
            username, password = auth.split(":", 1)
        else:
            tokens = [token for token in re.split(r"[\s:;,\|]+", compact) if token]
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
            "server": f"{selected_scheme}://{host}:{int(port)}",
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


class StartupOverlay(QFrame):
    def __init__(self, lang, parent=None):
        super().__init__(parent)
        self.lang = lang
        self.setObjectName("startupOverlay")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(14)

        self.badge = QLabel(lang.get("startup_badge", "Подготовка"))
        self.badge.setObjectName("startupBadge")
        layout.addWidget(self.badge, alignment=Qt.AlignmentFlag.AlignCenter)

        self.title = QLabel(lang.get("startup_title", "Подготовка Multiaccount"))
        self.title.setObjectName("startupTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title)

        self.subtitle = QLabel(lang.get("startup_subtitle", "Подготавливаем браузерный runtime и проверяем обновления."))
        self.subtitle.setObjectName("startupSubtitle")
        self.subtitle.setWordWrap(True)
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.subtitle)

        self.status = QLabel(lang.get("browser_status_wait", "Preparing browser runtime..."))
        self.status.setObjectName("startupStatus")
        self.status.setWordWrap(True)
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status)

        self.progress = QProgressBar()
        self.progress.setObjectName("browserProgress")
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(True)
        layout.addWidget(self.progress)

        self.logs_toggle = QPushButton(lang.get("startup_show_logs", "Показать логи"))
        layout.addWidget(self.logs_toggle, alignment=Qt.AlignmentFlag.AlignCenter)

        self.logs = QTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setVisible(False)
        self.logs.setMinimumHeight(160)
        layout.addWidget(self.logs)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.retry_btn = QPushButton(lang.get("startup_retry", "Повторить"))
        self.retry_btn.setVisible(False)
        buttons.addWidget(self.retry_btn)
        self.close_btn = QPushButton(lang.get("startup_close", "Закрыть"))
        self.close_btn.setVisible(False)
        buttons.addWidget(self.close_btn)
        buttons.addStretch()
        layout.addLayout(buttons)

    def reset(self, title, subtitle, badge=None):
        self.badge.setText(badge or self.lang.get("startup_badge", "Подготовка"))
        self.title.setText(title)
        self.subtitle.setText(subtitle)
        self.status.setText(subtitle)
        self.progress.setRange(0, 0)
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        self.logs.clear()
        self.logs.setVisible(False)
        self.logs_toggle.setText(self.lang.get("startup_show_logs", "Показать логи"))
        self.retry_btn.setVisible(False)
        self.close_btn.setVisible(False)

    def set_status(self, message):
        self.status.setText(message)

    def set_progress(self, value):
        if value is None or value < 0:
            self.progress.setRange(0, 0)
            return
        self.progress.setRange(0, 100)
        self.progress.setValue(max(0, min(100, int(value))))

    def append_log(self, message):
        if not message:
            return
        self.logs.append(message)

    def toggle_logs(self):
        visible = not self.logs.isVisible()
        self.logs.setVisible(visible)
        self.logs_toggle.setText(
            self.lang.get("startup_hide_logs", "Скрыть логи")
            if visible
            else self.lang.get("startup_show_logs", "Показать логи")
        )

class MainWindow(QMainWindow):
    THEME_STYLES = {
        "dark": {
            "window_bg_1": "#0f1117",
            "window_bg_2": "#171c28",
            "text": "#f2f5ff",
            "card_bg": "rgba(24, 29, 40, 0.94)",
            "card_border": "#2b3446",
            "muted": "#94a4c3",
            "table_bg": "#151b28",
            "table_alt": "#1a2232",
            "table_border": "#2a3750",
            "table_grid": "#273246",
            "table_header": "#20293a",
            "table_text": "#e9efff",
            "input_bg": "#182131",
            "input_border": "#2e3e5a",
            "button_bg": "#2f63ff",
            "button_hover": "#4b78ff",
            "button_pressed": "#2754de",
            "button_disabled": "#495978",
            "button_disabled_text": "#b9c4da",
            "progress_bg": "#121a2a",
            "progress_border": "#31415d",
            "progress_chunk_1": "#4b78ff",
            "progress_chunk_2": "#00d0ff",
        },
        "light": {
            "window_bg_1": "#f4f0e8",
            "window_bg_2": "#e9e2d6",
            "text": "#243041",
            "card_bg": "rgba(255, 251, 245, 0.96)",
            "card_border": "#d6cbbb",
            "muted": "#6c7786",
            "table_bg": "#fffaf2",
            "table_alt": "#f6efe4",
            "table_border": "#dccfbc",
            "table_grid": "#ddd1bf",
            "table_header": "#ede3d5",
            "table_text": "#223043",
            "input_bg": "#fffdf8",
            "input_border": "#cdbfae",
            "button_bg": "#c26a3d",
            "button_hover": "#d07b4f",
            "button_pressed": "#ad5c34",
            "button_disabled": "#d4c7b8",
            "button_disabled_text": "#86796c",
            "progress_bg": "#efe4d4",
            "progress_border": "#cdbfae",
            "progress_chunk_1": "#c26a3d",
            "progress_chunk_2": "#f0b46f",
        },
        "neutral": {
            "window_bg_1": "#d9ddd7",
            "window_bg_2": "#c7cdc5",
            "text": "#25302b",
            "card_bg": "rgba(245, 247, 243, 0.95)",
            "card_border": "#aab4ab",
            "muted": "#5f6c64",
            "table_bg": "#edf0ea",
            "table_alt": "#e4e8e1",
            "table_border": "#b5beb5",
            "table_grid": "#bcc4bc",
            "table_header": "#d7ddd5",
            "table_text": "#24312b",
            "input_bg": "#f6f8f3",
            "input_border": "#aab4ab",
            "button_bg": "#476c5c",
            "button_hover": "#567d6c",
            "button_pressed": "#3d5d50",
            "button_disabled": "#b8c0b8",
            "button_disabled_text": "#667169",
            "progress_bg": "#e3e7e1",
            "progress_border": "#aab4ab",
            "progress_chunk_1": "#476c5c",
            "progress_chunk_2": "#89a58f",
        },
    }

    def __init__(self):
        super().__init__()
        
        self.config = Config()
        self.account_manager = AccountManager(self.config)
        self.browser_runtime = BrowserRuntime(self.config, Logger.get_instance())
        self.browser_ready = False
        self.logger = Logger.get_instance()
        self._attach_browser_runtime(self.browser_runtime)
        self.open_account_ids = set()
        self.account_pending_actions = {}
        self.overlays = {}
        self.browser_bars = {}
        self.account_runtime_info = {}
        self.proxy_ping_state = {}
        self._proxy_ping_cycle_active = False
        self._proxy_ping_pending = 0
        self._proxy_ping_dirty = False
        self._proxy_monitor_started = False
        self._startup_retry = None
        self._startup_overlay_active = False
        self.app_version = self._load_app_version()
        self._tray_icon = None
        self.current_theme = self.config.get_theme()

        self._init_app_icon()

        self.setup_ui()
        self._setup_startup_overlay()
        self._begin_startup_sequence()

    def _init_app_icon(self) -> None:
        icon_path = self.config.resource_path("assets/icon.ico")
        if not icon_path.exists():
            return

        icon = QIcon(str(icon_path))
        if icon.isNull():
            return

        self.setWindowIcon(icon)
        try:
            qt_app = QApplication.instance()
            if qt_app is not None:
                qt_app.setWindowIcon(icon)
        except Exception:
            pass

        self._init_tray_icon(icon)

    def _init_tray_icon(self, icon: QIcon) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        tray = QSystemTrayIcon(icon, self)
        tray.setToolTip("Multiaccount")

        menu = QMenu(self)
        action_show = QAction("Show", self)
        action_show.triggered.connect(self._show_from_tray)
        menu.addAction(action_show)

        action_quit = QAction("Quit", self)
        action_quit.triggered.connect(self._quit_from_tray)
        menu.addAction(action_quit)

        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        self._tray_icon = tray

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._show_from_tray()

    def _show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit_from_tray(self) -> None:
        try:
            if self._tray_icon is not None:
                self._tray_icon.hide()
        finally:
            QApplication.quit()
    
    def show_language_dialog(self):
        dialog = LanguageDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            lang = dialog.get_language()
            self.config.set_language(lang)
            self.config.data["first_run"] = False
            self.config.save_config()
    
    def setup_ui(self):
        lang = self.config.lang
        theme = self.THEME_STYLES[self.current_theme]
        
        self.setWindowTitle(lang.get("window_title", "Multiaccount"))
        self.setMinimumSize(860, 560)
        
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        self.setStyleSheet("""
            QMainWindow, QWidget#central {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 %(window_bg_1)s,stop:1 %(window_bg_2)s);
                color: %(text)s;
                font-size: 13px;
            }
            QFrame#topCard, QFrame#tableCard {
                background: %(card_bg)s;
                border: 1px solid %(card_border)s;
                border-radius: 14px;
            }
            QLabel#title {
                font-size: 26px;
                font-weight: 700;
                color: %(text)s;
            }
            QLabel#statusBadge {
                background: #3b4461;
                border: 1px solid #576386;
                border-radius: 10px;
                padding: 5px 10px;
                color: #e5ecff;
                font-weight: 600;
            }
            QLabel#statusHint, QLabel#footerLabel {
                color: %(muted)s;
                font-size: 12px;
            }
            QProgressBar#browserProgress {
                border: 1px solid %(progress_border)s;
                border-radius: 8px;
                background: %(progress_bg)s;
                min-height: 12px;
                max-height: 12px;
                text-align: center;
            }
            QProgressBar#browserProgress::chunk {
                border-radius: 7px;
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 %(progress_chunk_1)s,stop:1 %(progress_chunk_2)s);
            }
            QTableWidget {
                background: %(table_bg)s;
                alternate-background-color: %(table_alt)s;
                border: 1px solid %(table_border)s;
                border-radius: 10px;
                gridline-color: %(table_grid)s;
                color: %(table_text)s;
                selection-background-color: %(button_bg)s;
                selection-color: #ffffff;
            }
            QTableWidget::item {
                color: %(table_text)s;
                padding: 4px;
            }
            QHeaderView::section {
                background: %(table_header)s;
                color: %(table_text)s;
                padding: 8px;
                border: none;
                border-bottom: 1px solid %(card_border)s;
            }
            QPushButton {
                background: %(button_bg)s;
                border: none;
                border-radius: 10px;
                padding: 9px 14px;
                color: #f8fbff;
                font-weight: 600;
            }
            QPushButton:hover { background: %(button_hover)s; }
            QPushButton:pressed { background: %(button_pressed)s; }
            QPushButton:disabled { background: %(button_disabled)s; color: %(button_disabled_text)s; }
            QLineEdit, QComboBox {
                background: %(input_bg)s;
                border: 1px solid %(input_border)s;
                border-radius: 8px;
                padding: 7px;
                color: %(text)s;
            }
            QFrame#startupOverlay {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 %(window_bg_1)s,
                    stop:1 %(window_bg_2)s);
                border: 1px solid %(card_border)s;
                border-radius: 18px;
            }
            QLabel#startupBadge {
                background: %(button_bg)s;
                color: #ffffff;
                border-radius: 10px;
                padding: 6px 12px;
                font-weight: 700;
            }
            QLabel#startupTitle {
                color: %(text)s;
                font-size: 26px;
                font-weight: 800;
            }
            QLabel#startupSubtitle, QLabel#startupStatus {
                color: %(muted)s;
                font-size: 14px;
            }
            QTextEdit {
                background: %(input_bg)s;
                border: 1px solid %(input_border)s;
                border-radius: 10px;
                color: %(text)s;
                padding: 8px;
            }
        """ % theme)

        top_card = QFrame()
        top_card.setObjectName("topCard")
        top_layout = QHBoxLayout(top_card)
        top_layout.setContentsMargins(16, 14, 16, 14)

        title_layout = QVBoxLayout()
        title = QLabel(lang.get("window_title", "Multiaccount"))
        title.setObjectName("title")
        title_layout.addWidget(title)
        top_layout.addLayout(title_layout)

        top_layout.addStretch()
        self.browser_status = QLabel(lang.get("browser_status_init", "Browser initializing..."))
        self.browser_status.setObjectName("statusBadge")
        self.browser_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.browser_status.setVisible(False)
        top_layout.addWidget(self.browser_status)
        layout.addWidget(top_card)

        browser_info_card = QFrame()
        browser_info_card.setObjectName("topCard")
        browser_info_layout = QVBoxLayout(browser_info_card)
        browser_info_layout.setContentsMargins(16, 12, 16, 12)
        browser_info_layout.setSpacing(8)

        self.browser_status_hint = QLabel(lang.get("browser_status_wait", "Preparing browser runtime..."))
        self.browser_status_hint.setObjectName("statusHint")
        self.browser_status_hint.setWordWrap(True)
        self.browser_status_hint.setVisible(False)
        browser_info_layout.addWidget(self.browser_status_hint)

        self.browser_progress = QProgressBar()
        self.browser_progress.setObjectName("browserProgress")
        self.browser_progress.setTextVisible(False)
        self.browser_progress.setVisible(False)
        browser_info_layout.addWidget(self.browser_progress)

        layout.addWidget(browser_info_card)

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

        self.language_select = QComboBox()
        self.language_select.addItem("Русский", "ru")
        self.language_select.addItem("English", "en")
        self.language_select.setCurrentIndex(self.language_select.findData(self.config.data.get("language") or "ru"))
        self.language_select.currentIndexChanged.connect(self._on_language_changed)
        btn_layout.addWidget(self.language_select)

        self.theme_select = QComboBox()
        self.theme_select.addItem(lang.get("theme_dark", "Dark"), "dark")
        self.theme_select.addItem(lang.get("theme_light", "Light"), "light")
        self.theme_select.addItem(lang.get("theme_neutral", "Neutral"), "neutral")
        self.theme_select.setCurrentIndex(self.theme_select.findData(self.current_theme))
        self.theme_select.currentIndexChanged.connect(self._on_theme_changed)
        btn_layout.addWidget(self.theme_select)
        
        btn_layout.addStretch()
        controls_layout.addLayout(btn_layout)
        layout.addWidget(controls_card)

        health_card = QFrame()
        health_card.setObjectName("topCard")
        health_layout = QHBoxLayout(health_card)
        health_layout.setContentsMargins(16, 10, 16, 10)
        health_layout.setSpacing(14)

        self.health_online = QLabel(f"{lang.get('health_online', 'Online')}: 0")
        self.health_online.setObjectName("statusHint")
        self.health_offline = QLabel(f"{lang.get('health_offline', 'Offline')}: 0")
        self.health_offline.setObjectName("statusHint")
        self.health_avg_ping = QLabel(f"{lang.get('health_avg_ping', 'Avg ping')}: —")
        self.health_avg_ping.setObjectName("statusHint")

        health_layout.addWidget(self.health_online)
        health_layout.addWidget(self.health_offline)
        health_layout.addWidget(self.health_avg_ping)
        health_layout.addStretch()
        layout.addWidget(health_card)
        
        # Таблица аккаунтов
        table_card = QFrame()
        table_card.setObjectName("tableCard")
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(14, 14, 14, 14)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(58)
        self.table.setHorizontalHeaderLabels([
            "ID", 
            lang.get("account_name"), 
            lang.get("domain"),
            lang.get("status_column", "Статус"),
            lang.get("proxy"),
            lang.get("timezone", "Тайм-зона"),
            ""
        ])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 52)
        self.table.setColumnWidth(1, 170)
        self.table.setColumnWidth(2, 240)
        self.table.setColumnWidth(3, 110)
        self.table.setColumnWidth(4, 300)
        self.table.setColumnWidth(5, 140)
        self.table.setColumnWidth(6, 520)
        table_layout.addWidget(self.table)
        layout.addWidget(table_card, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(4, 0, 4, 0)
        self.version_label = QLabel(
            f"{lang.get('version_label', 'Version')}: {self.app_version}"
        )
        self.version_label.setObjectName("footerLabel")
        footer.addWidget(self.version_label)
        footer.addStretch()
        layout.addLayout(footer)
        
        self._apply_initial_window_geometry()
        self.refresh_table()

    def _setup_startup_overlay(self):
        central = self.centralWidget()
        if central is None:
            return
        self.startup_overlay = StartupOverlay(self.config.lang, central)
        self.startup_overlay.logs_toggle.clicked.connect(self.startup_overlay.toggle_logs)
        self.startup_overlay.retry_btn.clicked.connect(self._retry_startup_action)
        self.startup_overlay.close_btn.clicked.connect(self.close)
        self._reposition_startup_overlay()
        self.startup_overlay.show()

    def _reposition_startup_overlay(self):
        central = self.centralWidget()
        if central is None or not hasattr(self, "startup_overlay"):
            return
        margin = 16
        self.startup_overlay.setGeometry(
            margin,
            margin,
            max(320, central.width() - margin * 2),
            max(220, central.height() - margin * 2),
        )
        self.startup_overlay.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_startup_overlay()

    def _show_startup_overlay(self, title, subtitle, badge=None):
        self._startup_overlay_active = True
        self.startup_overlay.reset(title, subtitle, badge=badge)
        self._reposition_startup_overlay()
        self.startup_overlay.show()
        self.startup_overlay.raise_()

    def _show_startup_error(self, title, message, retry_action=None):
        self._show_startup_overlay(title, message, badge=self.config.lang.get("startup_error_badge", "Ошибка"))
        self.startup_overlay.set_status(message)
        self.startup_overlay.retry_btn.setVisible(retry_action is not None)
        self.startup_overlay.close_btn.setVisible(True)
        self._startup_retry = retry_action

    def _retry_startup_action(self):
        callback = self._startup_retry
        self._startup_retry = None
        if callback:
            callback()

    def _append_startup_log(self, message):
        if not hasattr(self, "startup_overlay"):
            return
        self.startup_overlay.append_log(message)

    def _set_startup_progress(self, value):
        if not hasattr(self, "startup_overlay") or not self._startup_overlay_active:
            return
        self.startup_overlay.set_progress(value)

    def _begin_startup_sequence(self, skip_update_check=False):
        self.browser_ready = False
        self._show_startup_overlay(
            self.config.lang.get("startup_title", "Подготовка Multiaccount"),
            self.config.lang.get("startup_subtitle", "Подготавливаем браузерный runtime и проверяем обновления."),
            badge=self.config.lang.get("startup_badge", "Подготовка"),
        )
        self._startup_retry = None
        if skip_update_check or not self._should_check_for_updates():
            self.init_browser()
            return
        self.browser_runtime.check_for_update(
            sys.executable,
            on_success=self._on_update_check_result,
            on_error=self._on_update_check_error,
        )

    def _should_check_for_updates(self):
        return sys.platform == "win32" and bool(getattr(sys, "frozen", False))

    def _on_update_check_result(self, result):
        if result and result.get("update_available"):
            version = result.get("latest_version", "")
            self._show_startup_overlay(
                self.config.lang.get("update_title", "Доступно обновление"),
                self.config.lang.get("update_subtitle", "Скачиваем новую версию приложения."),
                badge=self.config.lang.get("update_badge", "Обновление"),
            )
            self.browser_runtime.download_update(
                sys.executable,
                result["manifest"],
                on_success=self._on_update_download_done,
                on_error=self._on_update_download_error,
            )
            self._append_startup_log(
                self.config.lang.get("update_found_log", "Найдена новая версия: {version}").format(version=version)
            )
            return
        self.init_browser()

    def _on_update_check_error(self, message):
        self._append_startup_log(message)
        self.init_browser()

    def _on_update_download_done(self, result):
        if not result or not result.get("success"):
            self._show_startup_error(
                self.config.lang.get("update_error_title", "Ошибка обновления"),
                self.config.lang.get("update_error_text", "Не удалось скачать обновление."),
                retry_action=self._begin_startup_sequence,
            )
            return
        self.startup_overlay.set_status(self.config.lang.get("update_status_finish", "Завершение обновления..."))
        self.startup_overlay.set_progress(100)
        if launch_staged_update(Path(sys.executable)):
            QTimer.singleShot(150, QApplication.instance().quit)
            return
        self._show_startup_error(
            self.config.lang.get("update_error_title", "Ошибка обновления"),
            self.config.lang.get("update_restart_failed", "Не удалось запустить обновление."),
            retry_action=self._begin_startup_sequence,
        )

    def _on_update_download_error(self, message):
        self._show_startup_error(
            self.config.lang.get("update_error_title", "Ошибка обновления"),
            message,
            retry_action=self._begin_startup_sequence,
        )

    def _finish_startup(self):
        self._startup_overlay_active = False
        self.startup_overlay.hide()
        if self.config.data.get("first_run", True):
            self.config.data["first_run"] = False
            self.config.save_config()
        if not self._proxy_monitor_started:
            self._start_proxy_monitor()
            self._proxy_monitor_started = True
        self._check_all_proxies_on_startup()
    
    def init_browser(self):
        self._show_startup_overlay(
            self.config.lang.get("startup_title", "Подготовка Multiaccount"),
            self.config.lang.get("browser_status_init", "Браузер инициализируется..."),
            badge=self.config.lang.get("startup_badge", "Подготовка"),
        )
        self._set_browser_busy(True, self.config.lang.get("browser_status_init", "Browser initializing..."))
        self.browser_runtime.initialize(
            on_success=self._on_init_browser_done,
            on_error=self._on_async_error,
        )

    def _on_init_browser_done(self, result):
        if result and result.get("error"):
            self.browser_ready = False
            self.browser_status.setText(self.config.lang.get("browser_status_error", "Browser init error"))
            self.browser_status.setVisible(True)
            self.browser_status_hint.setText(result["error"])
            self.browser_status_hint.setVisible(True)
            self._set_browser_busy(False)
            self._show_startup_error(
                self.config.lang.get("startup_error_title", "Ошибка подготовки"),
                result["error"],
                retry_action=lambda: self._begin_startup_sequence(skip_update_check=True),
            )
            self.refresh_table()
            return
        self.browser_ready = bool(result and result.get("ready"))
        self.browser_status.setText(
            self.config.lang.get("browser_status_ready", "Browser ready")
            if self.browser_ready
            else self.config.lang.get("browser_status_error", "Browser init error")
        )
        if self.browser_ready:
            self.browser_status.setVisible(False)
            self.browser_status_hint.setText("")
            self.browser_status_hint.setVisible(False)
        else:
            self.browser_status.setVisible(True)
            self.browser_status_hint.setVisible(True)
        self._set_browser_busy(False)
        if self.browser_ready:
            self._finish_startup()
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
        self.account_pending_actions.clear()
        self.account_runtime_info.clear()
        self.proxy_ping_state.clear()
        self._clear_overlays()
        self.browser_runtime = BrowserRuntime(self.config, self.logger)
        self._attach_browser_runtime(self.browser_runtime)
        self.browser_status.setText(self.config.lang.get("browser_status_init", "Browser initializing..."))
        self.browser_status.setVisible(False)
        self.browser_status_hint.setText(self.config.lang.get("browser_status_wait", "Preparing browser runtime..."))
        self.browser_status_hint.setVisible(False)
        self.refresh_table()
        self._begin_startup_sequence(skip_update_check=True)
        QMessageBox.information(
            self,
            self.config.lang.get("cleanup_data"),
            self.config.lang.get("cleanup_done")
        )

    def _on_async_error(self, message):
        self.logger.error(f"Async worker failed: {message}")
        self.browser_status_hint.setText(message)
        self.browser_status_hint.setVisible(True)
        self._set_browser_busy(False)
        if self._startup_overlay_active:
            self._show_startup_error(
                self.config.lang.get("startup_error_title", "Ошибка подготовки"),
                message,
                retry_action=lambda: self._begin_startup_sequence(skip_update_check=True),
            )

    def _on_language_changed(self):
        if not hasattr(self, "language_select"):
            return
        language = self.language_select.currentData()
        if not language or language == (self.config.data.get("language") or "ru"):
            return
        self.config.set_language(language)
        self.config.data["first_run"] = False
        self.config.save_config()
        self._rebuild_ui()

    def _on_theme_changed(self):
        if not hasattr(self, "theme_select"):
            return
        theme = self.theme_select.currentData()
        if not theme or theme == self.current_theme:
            return
        self.current_theme = theme
        self.config.set_theme(theme)
        self._rebuild_ui()

    def _rebuild_ui(self):
        central = self.centralWidget()
        if central is not None:
            central.deleteLater()
        self.setup_ui()
        self._setup_startup_overlay()
        if not self._startup_overlay_active:
            self.startup_overlay.hide()

    def _start_proxy_monitor(self):
        self.proxy_ping_timer = QTimer(self)
        self.proxy_ping_timer.setInterval(5000)
        self.proxy_ping_timer.timeout.connect(self._run_proxy_ping_cycle)
        self.proxy_ping_timer.start()
        QTimer.singleShot(700, self._run_proxy_ping_cycle)

    def _account_by_id(self, account_id):
        for account in self.account_manager.get_accounts():
            if account["id"] == account_id:
                return account
        return None

    def _check_all_proxies_on_startup(self):
        for account in self.account_manager.get_accounts():
            if account.get("proxy"):
                self._probe_account_proxy(account["id"], account.get("proxy"))

    def _probe_account_proxy(self, account_id, proxy):
        self.browser_runtime.probe_proxy(
            proxy,
            on_success=lambda result, aid=account_id: self._on_proxy_probe_result(aid, result),
            on_error=lambda message, aid=account_id: self._on_proxy_probe_error(aid, message),
        )

    def _on_proxy_probe_result(self, account_id, result):
        account = self._account_by_id(account_id)
        if account is None:
            return
        normalized = dict(result or {})
        normalized.setdefault("alive", False)
        normalized.setdefault("ip", "unknown")
        normalized.setdefault("city", "unknown")
        normalized.setdefault("country", "unknown")
        normalized.setdefault("timezone", "unknown")
        normalized.setdefault("org", "unknown")
        normalized.setdefault("source", "none")
        normalized.setdefault("error", "")
        account["proxy_status"] = normalized
        if normalized.get("timezone") and normalized["timezone"] != "unknown":
            account["timezone"] = normalized["timezone"]
        self.account_manager.update_proxy_status(account_id, normalized)
        self.refresh_table()

    def _on_proxy_probe_error(self, account_id, message):
        fallback = {
            "alive": False,
            "ip": "unknown",
            "city": "unknown",
            "country": "unknown",
            "timezone": "unknown",
            "org": "unknown",
            "source": "none",
            "error": str(message),
        }
        self._on_proxy_probe_result(account_id, fallback)

    def _run_proxy_ping_cycle(self):
        if self._proxy_ping_cycle_active:
            return
        accounts = [a for a in self.account_manager.get_accounts() if a.get("proxy")]
        if not accounts:
            self.proxy_ping_state.clear()
            self.refresh_table()
            return

        self._proxy_ping_cycle_active = True
        self._proxy_ping_pending = len(accounts)
        self._proxy_ping_dirty = False

        for account in accounts:
            self.browser_runtime.ping_proxy(
                account.get("proxy"),
                on_success=lambda result, aid=account["id"]: self._on_proxy_ping_result(aid, result),
                on_error=lambda message, aid=account["id"]: self._on_proxy_ping_error(aid, message),
            )

    def _on_proxy_ping_result(self, account_id, result):
        normalized = dict(result or {})
        normalized.setdefault("alive", False)
        normalized.setdefault("ping_ms", None)
        normalized.setdefault("error", "")
        self.proxy_ping_state[account_id] = normalized
        self._proxy_ping_dirty = True
        self._finish_proxy_ping_request()

    def _on_proxy_ping_error(self, account_id, message):
        self.proxy_ping_state[account_id] = {
            "alive": False,
            "ping_ms": None,
            "error": str(message),
        }
        self._proxy_ping_dirty = True
        self._finish_proxy_ping_request()

    def _finish_proxy_ping_request(self):
        self._proxy_ping_pending -= 1
        if self._proxy_ping_pending > 0:
            return
        self._proxy_ping_cycle_active = False
        self._proxy_ping_pending = 0
        if self._proxy_ping_dirty:
            self.refresh_table()

    def _proxy_quality_color(self, ping_ms, alive):
        if ping_ms is not None:
            if ping_ms <= 180:
                return QColor("#31d08f")
            if ping_ms <= 380:
                return QColor("#ffd166")
            return QColor("#ff6b6b")
        if alive is False:
            return QColor("#ff6b6b")
        return QColor("#dce7ff")

    def _pending_action_label(self, action):
        labels = {
            "opening": self.config.lang.get("status_opening", "Запуск"),
            "closing": self.config.lang.get("status_closing", "Закрытие"),
            "deleting": self.config.lang.get("status_deleting", "Удаление"),
        }
        return labels.get(action)

    def _status_brushes(self, is_open, pending_action=None):
        if pending_action == "opening":
            return QBrush(QColor("#4b3611")), QBrush(QColor("#ffd88a"))
        if pending_action == "closing":
            return QBrush(QColor("#24344a")), QBrush(QColor("#9fd0ff"))
        if pending_action == "deleting":
            return QBrush(QColor("#4a1f28")), QBrush(QColor("#ffb3c1"))
        if is_open:
            return QBrush(QColor("#163628")), QBrush(QColor("#8cf0bf"))
        return QBrush(QColor("#2b313c")), QBrush(QColor("#c9d3e4"))

    def _set_account_pending_action(self, account_id, action):
        if action:
            self.account_pending_actions[account_id] = action
        else:
            self.account_pending_actions.pop(account_id, None)

    def _get_account_pending_action(self, account_id):
        return self.account_pending_actions.get(account_id)

    def _clear_account_pending_action(self, account_id):
        self.account_pending_actions.pop(account_id, None)

    def _is_account_busy(self, account_id):
        return self._get_account_pending_action(account_id) is not None

    def _short_proxy_label(self, server):
        value = (server or "—").strip()
        if len(value) <= 34:
            return value
        return f"{value[:18]}...{value[-11:]}"

    def _build_proxy_item(self, account):
        proxy = account.get("proxy") or {}
        if not proxy:
            return QTableWidgetItem("—")

        proxy_status = account.get("proxy_status") or {}
        ping_state = self.proxy_ping_state.get(account["id"]) or {}
        city = proxy_status.get("city", "unknown")
        country = proxy_status.get("country", "unknown")
        location = f"{city}, {country}" if city != "unknown" or country != "unknown" else "unknown"
        ping_ms = ping_state.get("ping_ms")
        ping_text = f"{ping_ms:.1f} ms" if isinstance(ping_ms, (float, int)) else self.config.lang.get("ping_no_data", "no ping")
        alive = ping_state.get("alive")
        if alive is None:
            alive = proxy_status.get("alive")
        if alive is True:
            indicator = self.config.lang.get("proxy_alive", "alive")
        elif alive is False:
            indicator = self.config.lang.get("proxy_dead", "offline")
        else:
            indicator = self.config.lang.get("proxy_unknown", "unknown")
        headline = f"{indicator}  {location}"
        secondary = f"{self._short_proxy_label(proxy.get('server', '—'))}  {ping_text}"
        text = f"{headline}\n{secondary}"
        item = QTableWidgetItem(text)
        item.setToolTip(
            f"source: {proxy_status.get('source', 'none')}\n"
            f"server: {proxy.get('server', '—')}\n"
            f"ip: {proxy_status.get('ip', 'unknown')}\n"
            f"org: {proxy_status.get('org', 'unknown')}\n"
            f"error: {proxy_status.get('error', '') or ping_state.get('error', '') or '-'}"
        )
        item.setForeground(QBrush(self._proxy_quality_color(ping_ms, alive)))
        return item

    def _update_health_panel(self):
        accounts = self.account_manager.get_accounts()
        online = 0
        offline = 0
        pings = []
        for account in accounts:
            if not account.get("proxy"):
                continue
            ping_state = self.proxy_ping_state.get(account["id"]) or {}
            proxy_status = account.get("proxy_status") or {}
            alive = ping_state.get("alive")
            if alive is None:
                alive = proxy_status.get("alive")
            if alive:
                online += 1
            else:
                offline += 1
            ping_ms = ping_state.get("ping_ms")
            if isinstance(ping_ms, (float, int)):
                pings.append(float(ping_ms))

        avg_ping = round(sum(pings) / len(pings), 1) if pings else None
        self.health_online.setText(f"{self.config.lang.get('health_online', 'Online')}: {online}")
        self.health_offline.setText(f"{self.config.lang.get('health_offline', 'Offline')}: {offline}")
        if avg_ping is None:
            self.health_avg_ping.setText(f"{self.config.lang.get('health_avg_ping', 'Avg ping')}: —")
        else:
            self.health_avg_ping.setText(f"{self.config.lang.get('health_avg_ping', 'Avg ping')}: {avg_ping} ms")
    
    def refresh_table(self):
        lang = self.config.lang
        accounts = self.account_manager.get_accounts()
        
        self.table.setRowCount(len(accounts))
        
        for i, acc in enumerate(accounts):
            id_item = QTableWidgetItem(str(acc["id"]))
            id_item.setTextAlignment(int(Qt.AlignmentFlag.AlignCenter))
            self.table.setItem(i, 0, id_item)

            name_item = QTableWidgetItem(acc["name"])
            profile = acc.get("device_profile") or {}
            name_item.setToolTip(
                f"{profile.get('label', 'unknown')}\n"
                f"{profile.get('os', 'unknown')} / {profile.get('browser', 'unknown')}"
            )
            self.table.setItem(i, 1, name_item)
            
            domain = acc.get("domain") or "—"
            domain_item = QTableWidgetItem(domain)
            domain_item.setToolTip(domain)
            self.table.setItem(i, 2, domain_item)
            proxy_data = acc.get("proxy") or {}
            pending_action = self._get_account_pending_action(acc["id"])
            is_open = acc["id"] in self.open_account_ids
            status = self._pending_action_label(pending_action)
            if not status:
                status = lang.get("status_active") if is_open else lang.get("status_inactive")
            status_item = QTableWidgetItem(status)
            status_item.setTextAlignment(int(Qt.AlignmentFlag.AlignCenter))
            status_bg, status_fg = self._status_brushes(is_open, pending_action)
            status_item.setBackground(status_bg)
            status_item.setForeground(status_fg)
            self.table.setItem(i, 3, status_item)
            proxy_item = self._build_proxy_item(acc)
            self.table.setItem(i, 4, proxy_item)
            timezone_item = QTableWidgetItem(acc.get("timezone") or "—")
            timezone_item.setToolTip(acc.get("timezone") or "—")
            self.table.setItem(i, 5, timezone_item)
            
            # Кнопки действий
            actions = QWidget()
            actions_layout = QHBoxLayout(actions)
            actions_layout.setContentsMargins(5, 0, 5, 0)
            actions_layout.setSpacing(8)
            is_busy = pending_action is not None
            
            open_btn = QPushButton(lang.get("open_account"))
            open_btn.setEnabled(self.browser_ready and not is_open and not is_busy)
            open_btn.clicked.connect(lambda _, a=acc: self.open_account(a))

            close_btn = QPushButton(lang.get("close_account"))
            close_btn.setEnabled(is_open and not is_busy)
            close_btn.clicked.connect(lambda _, aid=acc["id"]: self.close_account(aid))
            
            edit_proxy_btn = QPushButton(lang.get("proxy"))
            edit_proxy_btn.setEnabled(not is_busy and not is_open)
            edit_proxy_btn.clicked.connect(lambda _, a=acc: self.edit_proxy(a))

            info_btn = QPushButton(lang.get("account_info", "Информация\nпо аккаунту"))
            info_btn.clicked.connect(lambda _, a=acc: self.show_account_info(a))

            delete_btn = QPushButton(lang.get("delete_account"))
            delete_btn.setEnabled(not is_busy)
            delete_btn.clicked.connect(lambda _, a=acc: self.delete_account(a))
            
            actions_layout.addWidget(open_btn)
            actions_layout.addWidget(close_btn)
            actions_layout.addWidget(edit_proxy_btn)
            actions_layout.addWidget(info_btn)
            actions_layout.addSpacing(8)
            actions_layout.addWidget(delete_btn)
            actions_layout.addStretch()
            
            self.table.setCellWidget(i, 6, actions)
        self._update_health_panel()
    
    def add_account(self):
        lang = self.config.lang
        dialog = AddAccountDialog(lang, self)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            name = dialog.get_name()
            self.account_manager.add_account(name)
            self.refresh_table()
            self.logger.info(f"Added account: {name}")

    def show_account_info(self, account):
        account_id = account["id"]
        if account_id in self.open_account_ids:
            self.browser_runtime.get_account_url(
                account_id,
                on_success=lambda url, aid=account_id: self._show_account_info_dialog(aid, url),
                on_error=lambda _msg, aid=account_id: self._show_account_info_dialog(aid, None),
            )
            return
        self._show_account_info_dialog(account_id, None)

    def _show_account_info_dialog(self, account_id, current_url):
        account = self._account_by_id(account_id)
        if account is None:
            return
        info = dict(self.account_runtime_info.get(account_id, {}))
        proxy_data = account.get("proxy") or {}
        proxy_status = account.get("proxy_status") or {}
        ping_state = self.proxy_ping_state.get(account_id) or {}
        device_profile = account.get("device_profile") or {}
        ping_ms = ping_state.get("ping_ms")
        ping_text = (
            f"{ping_ms:.1f} ms"
            if isinstance(ping_ms, (float, int))
            else self.config.lang.get("ping_no_data", "no ping")
        )
        city = proxy_status.get("city") or info.get("city", "unknown")
        country = proxy_status.get("country") or info.get("country", "unknown")
        resolved_url = current_url or account.get("domain") or "unknown"
        details = [
            (self.config.lang.get("overlay_ip", "IP"), proxy_status.get("ip", info.get("ip", "unknown"))),
            (self.config.lang.get("current_url", "Current URL"), resolved_url),
            (
                self.config.lang.get("overlay_timezone", "Timezone"),
                account.get("timezone") or proxy_status.get("timezone", info.get("timezone", "unknown")),
            ),
            (
                self.config.lang.get("overlay_location", "Location"),
                f"{city}, {country}",
            ),
            (
                self.config.lang.get("overlay_device", "Device"),
                info.get("device", device_profile.get("label", "unknown")),
            ),
            (self.config.lang.get("profile_kind", "Profile type"), device_profile.get("kind", "unknown")),
            (self.config.lang.get("profile_model", "Model"), device_profile.get("model", "unknown")),
            (self.config.lang.get("overlay_os", "OS"), info.get("os", device_profile.get("os", "unknown"))),
            (self.config.lang.get("overlay_browser", "Browser"), info.get("browser", device_profile.get("browser", "unknown"))),
            (
                self.config.lang.get("profile_viewport", "Viewport"),
                f"{device_profile.get('viewport', {}).get('width', '?')}x{device_profile.get('viewport', {}).get('height', '?')}",
            ),
            (
                self.config.lang.get("profile_hardware", "Hardware"),
                f"{device_profile.get('hardware_concurrency', '?')} cores / {device_profile.get('device_memory', '?')} GB",
            ),
            (self.config.lang.get("proxy", "Proxy"), proxy_data.get("server", "direct")),
            (self.config.lang.get("proxy_ping", "Ping"), ping_text),
            (self.config.lang.get("proxy_source", "Source"), proxy_status.get("source", "none")),
            (self.config.lang.get("proxy_org", "Organization"), proxy_status.get("org", "unknown")),
        ]
        dialog = AccountInfoDialog(self.config.lang, account["name"], details, self)
        dialog.exec()

    def show_browser_bar(self, account):
        account_id = account["id"]
        if account_id not in self.open_account_ids:
            return

        existing = self.browser_bars.get(account_id)
        if existing is not None:
            try:
                existing.raise_()
                existing.activateWindow()
            except Exception:
                pass
            return

        dialog = BrowserBarDialog(
            self.browser_runtime,
            self.config.lang,
            account_id,
            account.get("name", "Account"),
            parent=self,
        )
        self.browser_bars[account_id] = dialog
        dialog.finished.connect(lambda _code, aid=account_id: self.browser_bars.pop(aid, None))
        dialog.show()

    def regenerate_account_profile(self, account):
        if self._is_account_busy(account["id"]):
            return
        if account["id"] in self.open_account_ids:
            QMessageBox.information(
                self,
                self.config.lang.get("profile_busy_title", "Профиль занят"),
                self.config.lang.get(
                    "profile_busy_text",
                    "Сначала закройте аккаунт, затем обновите профиль устройства.",
                ),
            )
            return

        profile = self.account_manager.regenerate_device_profile(account["id"])
        if not profile:
            return
        account["device_profile"] = profile
        account["user_agent"] = profile["user_agent"]
        self.refresh_table()
        self.logger.info(f"Account {account['name']} switched to profile {profile['id']}")
    
    def delete_account(self, account):
        if self._is_account_busy(account["id"]):
            return
        dialog = DeleteConfirmDialog(self.config.lang, account["name"], self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._set_account_pending_action(account["id"], "deleting")
            self.refresh_table()
            self.browser_runtime.close_account(
                account["id"],
                on_success=lambda _result, aid=account["id"]: self._finalize_delete_account(aid),
                on_error=lambda message, aid=account["id"]: self._delete_after_error(aid, message),
            )

    def close_account(self, account_id):
        if self._is_account_busy(account_id) or account_id not in self.open_account_ids:
            return
        self._set_account_pending_action(account_id, "closing")
        self.refresh_table()
        self.browser_runtime.close_account(
            account_id,
            on_success=lambda _result, aid=account_id: self._handle_close_result(aid),
            on_error=lambda message, aid=account_id: self._handle_close_error(aid, message),
        )

    def _finalize_delete_account(self, account_id):
        self._clear_account_pending_action(account_id)
        self.open_account_ids.discard(account_id)
        self.account_runtime_info.pop(account_id, None)
        self.proxy_ping_state.pop(account_id, None)
        self.account_manager.delete_account(account_id)
        self.refresh_table()

    def _delete_after_error(self, account_id, message):
        self.logger.warning(f"Account close before delete failed: {message}")
        self._finalize_delete_account(account_id)

    def _handle_close_result(self, account_id):
        self._clear_account_pending_action(account_id)
        self.open_account_ids.discard(account_id)
        self.account_runtime_info.pop(account_id, None)
        self.refresh_table()

    def _handle_close_error(self, account_id, message):
        self._clear_account_pending_action(account_id)
        self.refresh_table()
        self.logger.warning(f"Close account failed: {message}")

    def edit_proxy(self, account):
        if self._is_account_busy(account["id"]) or account["id"] in self.open_account_ids:
            return
        lang = self.config.lang
        dialog = ProxyDialog(lang, account, self)
        dialog.detect_requested.connect(lambda: self._detect_timezone_for_dialog(dialog))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                proxy = dialog.get_proxy()
                if proxy:
                    self.browser_runtime.probe_proxy(
                        proxy,
                        on_success=lambda result, acc=account, px=proxy: self._apply_proxy_change(acc, px, result),
                        on_error=lambda message, acc=account, px=proxy: self._apply_proxy_change(
                            acc,
                            px,
                            {
                                "alive": False,
                                "ip": "unknown",
                                "city": "unknown",
                                "country": "unknown",
                                "timezone": "unknown",
                                "org": "unknown",
                                "source": "none",
                                "error": str(message),
                                "ping_ms": None,
                            },
                        ),
                    )
                else:
                    self._apply_proxy_change(account, None, {})
            except ValueError:
                QMessageBox.warning(self, "Proxy", lang.get("proxy_invalid"))

    def _apply_proxy_change(self, account, proxy, probe_result):
        status = dict(probe_result or {})
        if proxy:
            timezone = status.get("timezone")
            if timezone and timezone != "unknown":
                account["timezone"] = timezone
            self.account_manager.update_proxy(account["id"], proxy, timezone=account.get("timezone"))
        else:
            self.account_manager.update_proxy(account["id"], None)
            self.proxy_ping_state.pop(account["id"], None)

        self.account_manager.update_proxy_status(account["id"], status)
        account["proxy"] = proxy
        account["proxy_raw"] = (proxy or {}).get("raw")
        account["proxy_status"] = status
        if status.get("timezone") and status["timezone"] != "unknown":
            account["timezone"] = status["timezone"]
        if status.get("ping_ms") is not None:
            self.proxy_ping_state[account["id"]] = {
                "alive": bool(status.get("alive")),
                "ping_ms": status.get("ping_ms"),
                "error": status.get("error", ""),
            }
        self.refresh_table()
        if proxy and not status.get("alive", False):
            QMessageBox.warning(
                self,
                self.config.lang.get("proxy", "Proxy"),
                self.config.lang.get("proxy_unreachable", "Прокси сохранен, но проверка не пройдена."),
            )
        self.logger.info(
            f"Proxy updated for account {account['name']} "
            f"(alive: {status.get('alive', False)}, timezone: {account.get('timezone', 'unknown')})"
        )

    def _ensure_account_domain(self, account):
        normalized_domain = None
        current_domain = (account.get("domain") or "").strip()
        if current_domain:
            try:
                normalized_domain = normalize_target_url(current_domain)
            except ValueError:
                normalized_domain = None

        while not normalized_domain:
            domain_dialog = DomainDialog(
                account["name"],
                self.config.lang,
                current_domain=current_domain,
                parent=self,
            )
            if domain_dialog.exec() != QDialog.DialogCode.Accepted:
                return None
            normalized_domain = domain_dialog.get_domain()
            current_domain = normalized_domain

        if account.get("domain") != normalized_domain:
            self.account_manager.update_domain(account["id"], normalized_domain)
            account["domain"] = normalized_domain
            self.refresh_table()
        return normalized_domain
    
    def open_account(self, account):
        lang = self.config.lang

        if self._is_account_busy(account["id"]) or account["id"] in self.open_account_ids:
            return
        if not self.browser_ready:
            QMessageBox.information(self, "Info", lang.get("cleanup_restart"))
            return
        
        if not self._ensure_account_domain(account):
            return

        self.logger.info(f"Opening account: {account['name']}")
        if account.get("proxy"):
            proxy_status = account.get("proxy_status") or {}
            timezone = proxy_status.get("timezone")
            if timezone and timezone != "unknown":
                account["timezone"] = timezone

        self._submit_open_account(account)

    def _submit_open_account(self, account):
        self._set_account_pending_action(account["id"], "opening")
        self.refresh_table()
        self.browser_runtime.open_account(
            dict(account),
            on_success=self._handle_open_result,
            on_error=lambda message, aid=account["id"]: self._handle_open_error(aid, message),
        )

    def _handle_open_result(self, result):
        account_id = result.get("account_id") if result else None
        if account_id is not None:
            self._clear_account_pending_action(account_id)
        if result and result.get("error"):
            QMessageBox.critical(self, "Error", result["error"])
            self.refresh_table()
            return
        if result and result.get("success"):
            if account_id is not None:
                self.open_account_ids.add(account_id)
                overlay_info = result.get("overlay") or {}
                self.account_runtime_info[account_id] = overlay_info
                self.refresh_table()

    def _handle_open_error(self, account_id, message):
        self._clear_account_pending_action(account_id)
        self.refresh_table()
        QMessageBox.critical(self, "Error", message)
    
    def on_browser_close(self, account_id):
        self._clear_account_pending_action(account_id)
        self.open_account_ids.discard(account_id)
        self.account_runtime_info.pop(account_id, None)
        bar = self.browser_bars.pop(account_id, None)
        if bar is not None:
            try:
                bar.close()
            except Exception:
                pass
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
            if hasattr(self, "proxy_ping_timer"):
                self.proxy_ping_timer.stop()
            self.browser_runtime.shutdown_sync()
        except Exception as e:
            self.logger.error(f"Shutdown error: {e}")

        self.logger.info("Application closed")
        event.accept()

    def _attach_browser_runtime(self, runtime):
        runtime.browser_closed.connect(self.on_browser_close)
        runtime.browser_status.connect(self._on_browser_runtime_status)
        runtime.browser_installing.connect(self._on_browser_installing_changed)
        runtime.browser_progress.connect(self._on_browser_runtime_progress)
        runtime.browser_log.connect(self._on_browser_runtime_log)

    def _on_browser_runtime_status(self, message):
        self.browser_status_hint.setText(message)
        self.browser_status_hint.setVisible(bool(message))
        if self._startup_overlay_active and message:
            self.startup_overlay.set_status(message)

    def _on_browser_installing_changed(self, installing):
        self._set_browser_busy(installing, self.browser_status_hint.text())

    def _on_browser_runtime_progress(self, value):
        self._set_startup_progress(value)

    def _on_browser_runtime_log(self, message):
        self._append_startup_log(message)

    def _set_browser_busy(self, busy, message=None):
        if message:
            self.browser_status_hint.setText(message)
            self.browser_status_hint.setVisible(True)
        self.browser_progress.setVisible(busy)
        if busy:
            self.browser_progress.setRange(0, 0)
        else:
            self.browser_progress.setRange(0, 1)
            self.browser_progress.setValue(1)
            if not self.browser_status_hint.text().strip():
                self.browser_status_hint.setVisible(False)

    def _load_app_version(self):
        manager = UpdateManager(current_exe=Path(sys.executable))
        return manager.read_local_version()

    def _apply_initial_window_geometry(self):
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        width = max(860, int(available.width() * 0.5))
        height = max(560, int(available.height() * 0.5))
        width = min(width, max(860, available.width() - 40))
        height = min(height, max(560, available.height() - 40))
        self.resize(width, height)
        self.move(
            available.x() + (available.width() - width) // 2,
            available.y() + (available.height() - height) // 2,
        )
