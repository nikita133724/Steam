from __future__ import annotations

import asyncio
from concurrent.futures import TimeoutError
import threading

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from src.browser_engine import BrowserEngine


class TaskRelay(QObject):
    success = pyqtSignal(object)
    error = pyqtSignal(str)


class BrowserRuntime(QThread):
    browser_closed = pyqtSignal(int)
    browser_status = pyqtSignal(str)
    browser_installing = pyqtSignal(bool)

    def __init__(self, config, logger):
        super().__init__()
        self.config = config
        self.logger = logger
        self.loop: asyncio.AbstractEventLoop | None = None
        self.engine: BrowserEngine | None = None
        self._started = threading.Event()
        self._relays: list[TaskRelay] = []

    def _lang(self, key, default):
        return self.config.lang.get(key, default)

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.engine = BrowserEngine(self.config)
        self._started.set()

        try:
            self.loop.run_forever()
        finally:
            pending = asyncio.all_tasks(self.loop)
            for task in pending:
                task.cancel()
            if pending:
                self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            self.loop.close()

    def _ensure_started(self):
        if not self.isRunning():
            self.start()
        self._started.wait()

    def submit(self, coro, on_success=None, on_error=None):
        self._ensure_started()

        relay = TaskRelay()
        self._relays.append(relay)

        def cleanup():
            if relay in self._relays:
                self._relays.remove(relay)
            relay.deleteLater()

        relay.success.connect(on_success or (lambda _: None))
        relay.error.connect(on_error or (lambda _: None))
        relay.success.connect(lambda _: cleanup())
        relay.error.connect(lambda _: cleanup())

        future = asyncio.run_coroutine_threadsafe(coro, self.loop)

        def done_callback(done_future):
            try:
                relay.success.emit(done_future.result())
            except Exception as exc:
                relay.error.emit(str(exc))

        future.add_done_callback(done_callback)
        return future

    def initialize(self, on_success=None, on_error=None):
        async def setup():
            self.browser_status.emit(self._lang("browser_status_wait", "Preparing browser runtime..."))
            await self.engine.init()
            if not self.engine or not self.engine._ensure_ready():
                return {
                    "error": self._lang(
                        "browser_engine_failed",
                        "Browser engine failed to initialize",
                    ),
                    "ready": False,
                }

            self.browser_status.emit(self._lang("browser_status_check", "Checking Chromium..."))
            if not await self.engine.check_chromium():
                self.logger.info("Chromium not found, installing...")
                self.browser_installing.emit(True)
                installed = await self.engine.install_chromium(
                    status_callback=self.browser_status.emit,
                )
                self.browser_installing.emit(False)
                if not installed:
                    return {"error": self._lang("browser_install_failed", "Chromium install failed"), "ready": False}
                self.browser_status.emit(self._lang("browser_status_recheck", "Rechecking Chromium..."))
                if not await self.engine.check_chromium():
                    return {
                        "error": self._lang(
                            "browser_install_recheck_failed",
                            "Chromium was installed, but browser startup check still fails",
                        ),
                        "ready": False,
                    }
            self.logger.info("Browser engine ready")
            self.browser_status.emit("")
            return {"success": True, "ready": True}

        return self.submit(setup(), on_success=on_success, on_error=on_error)

    def open_account(self, account, on_success=None, on_error=None):
        return self.submit(
            self.engine.open_account(account, self.config, on_close=self.browser_closed.emit),
            on_success=on_success,
            on_error=on_error,
        )

    def close_account(self, account_id, on_success=None, on_error=None):
        return self.submit(
            self.engine.close_account(account_id),
            on_success=on_success,
            on_error=on_error,
        )

    def detect_timezone(self, proxy_settings, on_success=None, on_error=None):
        return self.submit(
            self.engine.detect_timezone(proxy_settings),
            on_success=on_success,
            on_error=on_error,
        )

    def get_network_info(self, proxy_settings, on_success=None, on_error=None):
        return self.submit(
            self.engine.get_network_info(proxy_settings),
            on_success=on_success,
            on_error=on_error,
        )

    def probe_proxy(self, proxy_settings, on_success=None, on_error=None):
        return self.submit(
            self.engine.probe_proxy(proxy_settings),
            on_success=on_success,
            on_error=on_error,
        )

    def ping_proxy(self, proxy_settings, on_success=None, on_error=None):
        return self.submit(
            self.engine.ping_proxy(proxy_settings),
            on_success=on_success,
            on_error=on_error,
        )

    def get_account_url(self, account_id, on_success=None, on_error=None):
        return self.submit(
            self.engine.get_account_url(account_id),
            on_success=on_success,
            on_error=on_error,
        )

    def navigate_account(self, account_id, url, on_success=None, on_error=None):
        return self.submit(
            self.engine.navigate_account(account_id, url),
            on_success=on_success,
            on_error=on_error,
        )

    def back_account(self, account_id, on_success=None, on_error=None):
        return self.submit(
            self.engine.back_account(account_id),
            on_success=on_success,
            on_error=on_error,
        )

    def forward_account(self, account_id, on_success=None, on_error=None):
        return self.submit(
            self.engine.forward_account(account_id),
            on_success=on_success,
            on_error=on_error,
        )

    def reload_account(self, account_id, on_success=None, on_error=None):
        return self.submit(
            self.engine.reload_account(account_id),
            on_success=on_success,
            on_error=on_error,
        )

    def shutdown_sync(self, timeout: float = 15.0):
        if not self.isRunning():
            return

        self._ensure_started()
        future = asyncio.run_coroutine_threadsafe(self.engine.shutdown(), self.loop)
        try:
            future.result(timeout=timeout)
        except TimeoutError:
            self.logger.error("Timed out while shutting down browser runtime")
        except Exception as exc:
            self.logger.error(f"Browser runtime shutdown failed: {exc}")
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.wait(5000)
