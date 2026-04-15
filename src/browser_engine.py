import asyncio
import contextlib
import io
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

import requests
from playwright.async_api import async_playwright
from playwright.__main__ import main as playwright_cli_main
from src.device_profiles import normalize_device_profile
from src.logger import Logger

DEFAULT_TIMEZONE = "Europe/Moscow"
PROFILE_LOCK_FILES = ("SingletonCookie", "SingletonLock", "SingletonSocket")


class BrowserEngine:
    def __init__(self, config):
        self.config = config
        self.playwright = None
        self.browsers = {}
        self.logger = Logger.get_instance()
        self._ready = False

    async def init(self):
        try:
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(self.config.browsers_dir)
            self.playwright = await async_playwright().start()
            self._ready = True
            self.logger.info("Playwright initialized")
        except Exception as e:
            self.logger.error(f"Playwright init failed: {e}")
            self._ready = False

    def _ensure_ready(self):
        return self.playwright is not None and self._ready

    def default_launch_args(self):
        args = ["--disable-blink-features=AutomationControlled"]
        if sys.platform == "win32":
            args.append("--disable-gpu")
        elif sys.platform == "linux":
            args += ["--no-sandbox", "--disable-dev-shm-usage"]
        return args

    def _build_proxy_url(self, proxy_settings):
        if not proxy_settings or not proxy_settings.get("server"):
            return None

        proxy_url = proxy_settings["server"]
        username = proxy_settings.get("username")
        password = proxy_settings.get("password")
        if username or password:
            scheme, rest = proxy_url.split("://", 1)
            auth = quote(username or "", safe="")
            auth_password = quote(password or "", safe="")
            proxy_url = f"{scheme}://{auth}:{auth_password}@{rest}"
        return proxy_url

    def _ensure_proxy_dependencies(self, proxy_url):
        if not proxy_url or not proxy_url.lower().startswith("socks"):
            return
        try:
            import socks  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "SOCKS proxy support is unavailable. Install PySocks and rebuild the app."
            ) from exc

    def _request_with_proxy(self, url, proxy_settings, timeout):
        proxy_url = self._build_proxy_url(proxy_settings)
        self._ensure_proxy_dependencies(proxy_url)
        proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
        try:
            return requests.get(url, proxies=proxies, timeout=timeout)
        except requests.exceptions.InvalidSchema as exc:
            if "Missing dependencies for SOCKS support" in str(exc):
                raise RuntimeError(
                    "SOCKS proxy support is unavailable. Install PySocks and rebuild the app."
                ) from exc
            raise

    def _normalize_timezone(self, timezone):
        if isinstance(timezone, str):
            timezone = timezone.strip()
        if timezone and "/" in timezone and " " not in timezone:
            return timezone
        return DEFAULT_TIMEZONE

    def _cleanup_stale_profile_locks(self, user_data_dir):
        for filename in PROFILE_LOCK_FILES:
            try:
                (Path(user_data_dir) / filename).unlink(missing_ok=True)
            except OSError:
                pass

    def _format_launch_error(self, exc, user_data_dir, timezone_id):
        message = str(exc)
        if "Target page, context or browser has been closed" in message:
            return (
                "Browser exited during startup. Check the account profile, proxy, and "
                f"timezone. Profile: {user_data_dir}; timezone: {timezone_id}. "
                f"Original error: {message}"
            )
        return message

    def _emit_install_status(self, status_callback, message):
        if not status_callback or not message:
            return
        try:
            status_callback(message)
        except Exception:
            pass

    async def detect_timezone(self, proxy_settings):
        if not proxy_settings or not proxy_settings.get("server"):
            return None
        return await asyncio.to_thread(self._detect_timezone_sync, proxy_settings)

    def _detect_timezone_sync(self, proxy_settings):
        response = self._request_with_proxy("https://ipapi.co/timezone/", proxy_settings, timeout=8)
        response.raise_for_status()
        timezone = response.text.strip()
        if "/" not in timezone:
            raise ValueError("Timezone not detected")
        return timezone

    def _fetch_network_info_sync(self, proxy_settings):
        response = self._request_with_proxy("https://ipapi.co/json/", proxy_settings, timeout=8)
        response.raise_for_status()
        data = response.json()
        return {
            "ip": data.get("ip") or "unknown",
            "timezone": data.get("timezone") or "unknown",
            "country": data.get("country_name") or "unknown",
            "city": data.get("city") or "unknown",
        }

    async def get_network_info(self, proxy_settings):
        return await asyncio.to_thread(self._fetch_network_info_sync, proxy_settings)

    async def _apply_device_profile(self, browser, device_profile):
        profile_json = json.dumps(device_profile)
        script = """
        (() => {
          const profile = __PROFILE_JSON__;
          const patch = (obj, key, value) => {
            try {
              Object.defineProperty(obj, key, { get: () => value, configurable: true });
            } catch (e) {}
          };
          patch(Navigator.prototype, 'platform', profile.platform);
          patch(Navigator.prototype, 'maxTouchPoints', profile.maxTouchPoints);
          patch(Navigator.prototype, 'hardwareConcurrency', profile.hardwareConcurrency);
          patch(Navigator.prototype, 'deviceMemory', profile.deviceMemory);
          patch(Navigator.prototype, 'webdriver', false);
          if ('userAgentData' in Navigator.prototype) {
            patch(Navigator.prototype, 'userAgentData', {
              mobile: profile.isMobile,
              platform: profile.os,
              brands: [{ brand: profile.browserBrand, version: profile.browserVersion }],
              getHighEntropyValues: async hints => {
                const values = {
                  architecture: 'x86',
                  bitness: '64',
                  mobile: profile.isMobile,
                  model: profile.model,
                  platform: profile.os,
                  platformVersion: profile.osVersion,
                  uaFullVersion: profile.browserVersion,
                };
                const response = {};
                for (const hint of hints || [])
                  response[hint] = values[hint];
                return response;
              }
            });
          }
        })();
        """.replace("__PROFILE_JSON__", profile_json)
        await browser.add_init_script(script=script)

    async def open_account(self, account, config, on_close=None):
        if not self._ensure_ready():
            return {"error": "Browser engine not initialized"}

        account_id = account["id"]

        if account_id in self.browsers:
            self.logger.info(f"Account {account['name']} already open")
            return None

        domain = account.get("domain")
        if not domain:
            return {"need_domain": True}

        try:
            device_profile = normalize_device_profile(account.get("device_profile"))
            args = self.default_launch_args()

            proxy_settings = account.get("proxy") or {}
            proxy = None

            if proxy_settings.get("server"):
                proxy = {"server": proxy_settings["server"]}
                if proxy_settings.get("username"):
                    proxy["username"] = proxy_settings["username"]
                if proxy_settings.get("password"):
                    proxy["password"] = proxy_settings["password"]

            viewport = device_profile["viewport"]
            screen = device_profile.get("screen", viewport)
            user_data_dir = str(config.get_profile_path(account_id))
            requested_timezone = self._normalize_timezone(account.get("timezone"))

            launch_kwargs = {
                "user_data_dir": user_data_dir,
                "headless": False,
                "args": args,
                "viewport": viewport,
                "screen": screen,
                "proxy": proxy,
                "locale": account.get("locale", "ru-RU"),
                "timezone_id": requested_timezone,
                "user_agent": device_profile["user_agent"],
                "color_scheme": device_profile.get("color_scheme", "light"),
                "device_scale_factor": device_profile.get("device_scale_factor", 1),
                "is_mobile": device_profile.get("is_mobile", False),
                "has_touch": device_profile.get("has_touch", False),
            }

            try:
                browser = await self.playwright.chromium.launch_persistent_context(**launch_kwargs)
            except Exception as first_exc:
                self.logger.warning(
                    f"Primary browser launch failed for account {account['name']}: {first_exc}"
                )
                self._cleanup_stale_profile_locks(user_data_dir)

                fallback_timezone = DEFAULT_TIMEZONE
                retry_timezone = requested_timezone
                if requested_timezone != fallback_timezone:
                    retry_timezone = fallback_timezone
                    launch_kwargs["timezone_id"] = fallback_timezone
                    self.logger.warning(
                        f"Retrying browser launch for account {account['name']} with timezone "
                        f"{fallback_timezone}"
                    )
                else:
                    self.logger.warning(
                        f"Retrying browser launch for account {account['name']} after profile cleanup"
                    )

                try:
                    browser = await self.playwright.chromium.launch_persistent_context(**launch_kwargs)
                except Exception as retry_exc:
                    raise RuntimeError(
                        self._format_launch_error(retry_exc, user_data_dir, retry_timezone)
                    ) from retry_exc

                if retry_timezone != requested_timezone:
                    account["timezone"] = retry_timezone
            await self._apply_device_profile(
                browser,
                {
                    "platform": device_profile["platform"],
                    "maxTouchPoints": device_profile["max_touch_points"],
                    "hardwareConcurrency": device_profile["hardware_concurrency"],
                    "deviceMemory": device_profile["device_memory"],
                    "isMobile": device_profile["is_mobile"],
                    "model": device_profile["model"],
                    "os": device_profile["os"],
                    "osVersion": device_profile["os"].split(" ", 1)[-1],
                    "browserBrand": device_profile["browser"].split(" ", 1)[0],
                    "browserVersion": device_profile["browser"].split(" ", 1)[-1],
                },
            )

            page = browser.pages[0] if browser.pages else await browser.new_page()

            try:
                await page.goto(domain, timeout=30000)
            except Exception as e:
                self.logger.warning(f"Navigation issue: {e}")

            self.browsers[account_id] = browser

            asyncio.create_task(self._monitor_browser(account_id, browser, on_close))

            try:
                network_info = await self.get_network_info(proxy_settings)
            except Exception as exc:
                self.logger.warning(f"Network info lookup failed: {exc}")
                network_info = {}
            self.logger.info(f"Account {account['name']} opened")
            return {
                "success": True,
                "account_id": account_id,
                "overlay": {
                    "account_name": account["name"],
                    "ip": network_info.get("ip", "unknown"),
                    "timezone": account.get("timezone") or network_info.get("timezone", "unknown"),
                    "country": network_info.get("country", "unknown"),
                    "city": network_info.get("city", "unknown"),
                    "device": device_profile["label"],
                    "browser": device_profile["browser"],
                    "os": device_profile["os"],
                    "proxy": proxy_settings.get("server", "direct"),
                },
            }

        except Exception as e:
            self.logger.error(f"Open account failed: {e}")
            return {"error": str(e)}

    async def _monitor_browser(self, account_id, browser, on_close):
        try:
            while True:
                if browser.is_closed():
                    break
                await asyncio.sleep(1)

            if account_id in self.browsers:
                del self.browsers[account_id]

            if on_close:
                on_close(account_id)

        except Exception as e:
            self.logger.error(f"Monitor error: {e}")

    async def close_account(self, account_id):
        try:
            browser = self.browsers.get(account_id)
            if browser:
                await browser.close()
                del self.browsers[account_id]
                return True
            return False
        except Exception as e:
            self.logger.error(f"Close account error: {e}")
            raise

    async def close_all(self):
        for account_id in list(self.browsers.keys()):
            await self.close_account(account_id)

    async def shutdown(self):
        await self.close_all()
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None
            self._ready = False

    async def check_chromium(self):
        try:
            browser = await self.playwright.chromium.launch(
                headless=True,
                args=self.default_launch_args(),
            )
            await browser.close()
            return True
        except Exception as exc:
            self.logger.warning(f"Chromium check failed: {exc}")
            return False

    async def install_chromium(self, status_callback=None):
        self.logger.info("Installing Chromium...")
        self._emit_install_status(status_callback, "Installing Chromium...")

        for attempt in range(1, 4):
            self._emit_install_status(status_callback, f"Installing Chromium (attempt {attempt}/3)...")
            stderr = await asyncio.to_thread(self._run_playwright_install, status_callback)
            if stderr is None:
                self.logger.info("Chromium installed")
                self._emit_install_status(status_callback, "Chromium installed")
                return True

            self.logger.warning(
                f"Chromium install attempt {attempt}/3 failed: {stderr}"
            )
            self._emit_install_status(
                status_callback,
                f"Chromium install attempt {attempt}/3 failed: {stderr}",
            )
            await asyncio.sleep(1)

        self.logger.error("Chromium install failed after 3 attempts")
        self._emit_install_status(status_callback, "Chromium install failed after 3 attempts")
        return False

    def _run_playwright_install(self, status_callback=None):
        class _StreamRelay(io.TextIOBase):
            def __init__(self, emit):
                super().__init__()
                self._emit = emit
                self._buffer = ""

            def write(self, text):
                if not text:
                    return 0
                self._buffer += text
                normalized = self._buffer.replace("\r", "\n")
                parts = normalized.split("\n")
                self._buffer = parts.pop() if parts else ""
                for part in parts:
                    message = part.strip()
                    if message:
                        self._emit(message)
                return len(text)

            def flush(self):
                if self._buffer.strip():
                    self._emit(self._buffer.strip())
                self._buffer = ""

        old_argv = sys.argv[:]
        old_env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(self.config.browsers_dir)
        relay = _StreamRelay(lambda message: self._emit_install_status(status_callback, message))
        try:
            sys.argv = ["playwright", "install", "chromium"]
            with contextlib.redirect_stdout(relay), contextlib.redirect_stderr(relay):
                try:
                    playwright_cli_main()
                except SystemExit as exc:
                    relay.flush()
                    if exc.code in (0, None):
                        return None
                    return f"Playwright installer exited with code {exc.code}"
            relay.flush()
            return None
        except Exception as exc:
            relay.flush()
            return str(exc)
        finally:
            sys.argv = old_argv
            if old_env is None:
                os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
            else:
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = old_env
