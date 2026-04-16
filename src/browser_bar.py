from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QLabel


class BrowserBarDialog(QDialog):
    def __init__(self, runtime, lang: dict, account_id: int, account_name: str, parent=None):
        super().__init__(parent)
        self.runtime = runtime
        self.lang = lang
        self.account_id = account_id

        self.setWindowTitle(f"{account_name} #{account_id}")
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setMinimumWidth(620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        hint = QLabel(lang.get("browser_bar_hint", "Navigation"))
        layout.addWidget(hint)

        row = QHBoxLayout()
        row.setSpacing(8)
        layout.addLayout(row)

        self.back_btn = QPushButton(lang.get("browser_bar_back", "Back"))
        self.back_btn.clicked.connect(self._on_back)
        row.addWidget(self.back_btn)

        self.forward_btn = QPushButton(lang.get("browser_bar_forward", "Forward"))
        self.forward_btn.clicked.connect(self._on_forward)
        row.addWidget(self.forward_btn)

        self.reload_btn = QPushButton(lang.get("browser_bar_reload", "Reload"))
        self.reload_btn.clicked.connect(self._on_reload)
        row.addWidget(self.reload_btn)

        self.address = QLineEdit()
        self.address.setPlaceholderText("https://example.com")
        self.address.returnPressed.connect(self._on_go)
        row.addWidget(self.address, 1)

        self.go_btn = QPushButton(lang.get("browser_bar_go", "Go"))
        self.go_btn.clicked.connect(self._on_go)
        row.addWidget(self.go_btn)

        self.timer = QTimer(self)
        self.timer.setInterval(1500)
        self.timer.timeout.connect(self._refresh_url)
        self.timer.start()
        QTimer.singleShot(150, self._refresh_url)

    def closeEvent(self, event):
        try:
            self.timer.stop()
        except Exception:
            pass
        return super().closeEvent(event)

    def _refresh_url(self):
        self.runtime.get_account_url(
            self.account_id,
            on_success=self._apply_url,
            on_error=lambda _msg: None,
        )

    def _apply_url(self, url):
        if not url:
            return
        # Don't fight user while typing.
        if self.address.hasFocus():
            return
        self.address.setText(str(url))

    def _set_busy(self, busy: bool):
        for widget in (self.back_btn, self.forward_btn, self.reload_btn, self.address, self.go_btn):
            widget.setEnabled(not busy)

    def _on_back(self):
        self._set_busy(True)
        self.runtime.back_account(
            self.account_id,
            on_success=lambda _ok: self._set_busy(False),
            on_error=lambda _msg: self._set_busy(False),
        )

    def _on_forward(self):
        self._set_busy(True)
        self.runtime.forward_account(
            self.account_id,
            on_success=lambda _ok: self._set_busy(False),
            on_error=lambda _msg: self._set_busy(False),
        )

    def _on_reload(self):
        self._set_busy(True)
        self.runtime.reload_account(
            self.account_id,
            on_success=lambda _ok: self._set_busy(False),
            on_error=lambda _msg: self._set_busy(False),
        )

    def _on_go(self):
        value = (self.address.text() or "").strip()
        if not value:
            return
        self._set_busy(True)
        self.runtime.navigate_account(
            self.account_id,
            value,
            on_success=lambda _ok: self._set_busy(False),
            on_error=lambda _msg: self._set_busy(False),
        )
