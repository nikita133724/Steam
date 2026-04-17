import asyncio
import contextlib
from datetime import datetime, timezone
import io
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
import time
import re
from urllib.parse import quote, urlparse

import requests
from playwright.async_api import async_playwright
from playwright.__main__ import main as playwright_cli_main
from src.device_profiles import normalize_device_profile
from src.logger import Logger
from src.url_utils import normalize_target_url

DEFAULT_TIMEZONE = "Europe/Moscow"
PROFILE_LOCK_FILES = ("SingletonCookie", "SingletonLock", "SingletonSocket")
NAVIGATION_TIMEOUT_MS = 15000
LOAD_STATE_TIMEOUT_MS = 8000
PROXY_PREFLIGHT_TIMEOUT_S = 2.5


class BrowserEngine:
    def __init__(self, config):
        self.config = config
        self.playwright = None
        self.browsers = {}
        self.logger = Logger.get_instance()
        self._ready = False
        self._browser_close_notified = set()
        self._closed_context_ids = set()

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
        args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-default-apps",
            "--disable-features=Translate,msEdgeSidebarV2,OptimizationGuideModelDownloading,MediaRouter,AutofillServerCommunication,InterestFeedContentSuggestions",
            "--disable-popup-blocking",
            "--disable-sync",
            "--hide-crash-restore-bubble",
            "--metrics-recording-only",
            "--no-default-browser-check",
            "--no-first-run",
            "--password-store=basic",
        ]
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

    def _proxy_endpoint(self, proxy_settings):
        server = (proxy_settings or {}).get("server", "")
        if not server:
            return None, None
        parsed = urlparse(server)
        if not parsed.hostname or not parsed.port:
            return None, None
        return parsed.hostname, int(parsed.port)

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

    def _browser_brand_version(self, browser_name):
        value = (browser_name or "").strip()
        if value.startswith("Mobile Safari "):
            return "Safari", value.replace("Mobile Safari ", "", 1)
        if value.startswith("Safari "):
            return "Safari", value.replace("Safari ", "", 1)
        if value.startswith("Chrome Mobile "):
            return "Google Chrome", value.replace("Chrome Mobile ", "", 1)
        if value.startswith("Chrome "):
            return "Google Chrome", value.replace("Chrome ", "", 1)
        if value.startswith("Edge "):
            return "Microsoft Edge", value.replace("Edge ", "", 1)
        if value.startswith("Firefox "):
            return "Firefox", value.replace("Firefox ", "", 1)
        head, _, tail = value.partition(" ")
        return head or "Unknown", tail or "0"

    def _with_window_size_arg(self, args, screen):
        if any(arg.startswith("--window-size=") for arg in args):
            return list(args)
        width = int(screen.get("width", 1280))
        height = int(screen.get("height", 720))
        width = max(width, 1)
        height = max(height, 1)
        return [*args, f"--window-size={width},{height}"]

    def _launch_window_size(self, device_profile):
        viewport = device_profile.get("viewport") or {}
        width = int(viewport.get("width", 1280))
        height = int(viewport.get("height", 720))
        chrome_width = 16 if sys.platform == "win32" else 12
        chrome_height = 96 if sys.platform == "win32" else 88
        return {
            "width": max(width + chrome_width, 360),
            "height": max(height + chrome_height, 420),
        }

    def _emit_install_status(self, status_callback, message):
        if not status_callback or not message:
            return
        try:
            status_callback(message)
        except Exception:
            pass

    def _is_disposable_page(self, page):
        try:
            current_url = (page.url or "").strip().lower()
        except Exception:
            return False
        return current_url in {"", "about:blank", "chrome://newtab/", "edge://newtab/"}

    async def _pick_primary_page(self, browser):
        try:
            pages = list(browser.pages)
        except Exception:
            return None
        for page in pages:
            if page.is_closed():
                continue
            if not self._is_disposable_page(page):
                return page
        for page in pages:
            if page.is_closed():
                continue
            return page
        return await browser.new_page()

    async def _cleanup_extra_pages(self, browser, primary_page):
        try:
            pages = list(browser.pages)
        except Exception:
            return
        for page in pages:
            if page is primary_page or page.is_closed():
                continue
            if self._is_disposable_page(page):
                try:
                    await page.close()
                except Exception:
                    pass

    def _parse_ipinfo(self, proxy_settings):
        response = self._request_with_proxy("https://ipinfo.io/json", proxy_settings, timeout=8)
        if response.status_code == 429:
            raise RuntimeError("IPinfo rate limit")
        response.raise_for_status()
        data = response.json()
        return {
            "ip": data.get("ip") or "unknown",
            "timezone": data.get("timezone") or "unknown",
            "country": data.get("country") or "unknown",
            "city": data.get("city") or "unknown",
            "region": data.get("region") or "unknown",
            "org": data.get("org") or "unknown",
            "source": "ipinfo",
        }

    def _parse_ipapi_co(self, proxy_settings):
        response = self._request_with_proxy("https://ipapi.co/json/", proxy_settings, timeout=8)
        response.raise_for_status()
        data = response.json()
        if data.get("error"):
            raise RuntimeError(data.get("reason") or "ipapi.co failed")
        return {
            "ip": data.get("ip") or "unknown",
            "timezone": data.get("timezone") or "unknown",
            "country": data.get("country_name") or data.get("country") or "unknown",
            "city": data.get("city") or "unknown",
            "region": data.get("region") or "unknown",
            "org": data.get("org") or data.get("asn") or "unknown",
            "source": "ipapi.co",
        }

    def _parse_ip_api(self, proxy_settings):
        response = self._request_with_proxy(
            "http://ip-api.com/json/?fields=status,message,query,country,city,regionName,timezone,org,isp",
            proxy_settings,
            timeout=8,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("status") != "success":
            raise RuntimeError(data.get("message") or "ip-api failed")
        return {
            "ip": data.get("query") or "unknown",
            "timezone": data.get("timezone") or "unknown",
            "country": data.get("country") or "unknown",
            "city": data.get("city") or "unknown",
            "region": data.get("regionName") or "unknown",
            "org": data.get("org") or data.get("isp") or "unknown",
            "source": "ip-api",
        }

    def _resolve_network_info_sync(self, proxy_settings):
        providers = (
            ("ipinfo", self._parse_ipinfo),
            ("ipapi.co", self._parse_ipapi_co),
            ("ip-api", self._parse_ip_api),
        )
        errors = []
        for name, provider in providers:
            try:
                info = provider(proxy_settings)
                info["alive"] = True
                return info
            except Exception as exc:
                errors.append(f"{name}: {exc}")
        return {
            "ip": "unknown",
            "timezone": "unknown",
            "country": "unknown",
            "city": "unknown",
            "region": "unknown",
            "org": "unknown",
            "source": "none",
            "alive": False,
            "error": "; ".join(errors),
        }

    def _ping_proxy_sync(self, proxy_settings, timeout=3.0, attempts=1):
        host, port = self._proxy_endpoint(proxy_settings)
        if not host or not port:
            return {"alive": False, "ping_ms": None, "error": "proxy endpoint is invalid"}

        samples = []
        for _ in range(max(1, attempts)):
            started = time.perf_counter()
            try:
                with socket.create_connection((host, port), timeout=timeout):
                    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
                    samples.append(elapsed_ms)
            except OSError as exc:
                last_error = str(exc)
                continue
        if not samples:
            return {"alive": False, "ping_ms": None, "error": last_error if "last_error" in locals() else "timeout"}

        avg = round(sum(samples) / len(samples), 1)
        return {"alive": True, "ping_ms": avg, "samples": len(samples)}

    async def detect_timezone(self, proxy_settings):
        if not proxy_settings or not proxy_settings.get("server"):
            return None
        return await asyncio.to_thread(self._detect_timezone_sync, proxy_settings)

    def _detect_timezone_sync(self, proxy_settings):
        ping_info = self._ping_proxy_sync(
            proxy_settings,
            timeout=PROXY_PREFLIGHT_TIMEOUT_S,
            attempts=1,
        )
        if not ping_info.get("alive"):
            raise RuntimeError(ping_info.get("error") or "proxy is offline")
        info = self._resolve_network_info_sync(proxy_settings)
        timezone = info.get("timezone", "")
        if "/" not in timezone:
            raise ValueError("Timezone not detected")
        return timezone

    def _fetch_network_info_sync(self, proxy_settings):
        ping_info = self._ping_proxy_sync(
            proxy_settings,
            timeout=PROXY_PREFLIGHT_TIMEOUT_S,
            attempts=1,
        )
        if not ping_info.get("alive"):
            return {
                "ip": "unknown",
                "timezone": "unknown",
                "country": "unknown",
                "city": "unknown",
                "region": "unknown",
                "org": "unknown",
                "source": "none",
                "alive": False,
                "error": ping_info.get("error") or "proxy is offline",
                "ping_ms": None,
            }
        return self._resolve_network_info_sync(proxy_settings)

    async def get_network_info(self, proxy_settings):
        return await asyncio.to_thread(self._fetch_network_info_sync, proxy_settings)

    def _probe_proxy_sync(self, proxy_settings):
        checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        ping_info = self._ping_proxy_sync(
            proxy_settings,
            timeout=PROXY_PREFLIGHT_TIMEOUT_S,
            attempts=1,
        )
        if not ping_info.get("alive"):
            return {
                "alive": False,
                "checked_at": checked_at,
                "ip": "unknown",
                "timezone": "unknown",
                "country": "unknown",
                "city": "unknown",
                "region": "unknown",
                "org": "unknown",
                "source": "none",
                "error": ping_info.get("error") or "proxy is offline",
                "ping_ms": None,
            }

        network_info = self._resolve_network_info_sync(proxy_settings)
        return {
            "alive": bool(network_info.get("alive")),
            "checked_at": checked_at,
            "ip": network_info.get("ip", "unknown"),
            "timezone": network_info.get("timezone", "unknown"),
            "country": network_info.get("country", "unknown"),
            "city": network_info.get("city", "unknown"),
            "region": network_info.get("region", "unknown"),
            "org": network_info.get("org", "unknown"),
            "source": network_info.get("source", "none"),
            "error": network_info.get("error", ""),
            "ping_ms": ping_info.get("ping_ms"),
        }

    async def probe_proxy(self, proxy_settings):
        return await asyncio.to_thread(self._probe_proxy_sync, proxy_settings)

    async def ping_proxy(self, proxy_settings):
        return await asyncio.to_thread(self._ping_proxy_sync, proxy_settings)

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
          patch(Navigator.prototype, 'language', profile.language);
          patch(Navigator.prototype, 'languages', profile.languages);
          patch(Navigator.prototype, 'vendor', profile.vendor);
          patch(Navigator.prototype, 'plugins', profile.plugins);
          patch(Navigator.prototype, 'pdfViewerEnabled', true);
          patch(Navigator.prototype, 'webdriver', false);
          patch(window, 'devicePixelRatio', profile.deviceScaleFactor);

          if (window.screen) {
            patch(window.screen, 'width', profile.screen.width);
            patch(window.screen, 'height', profile.screen.height);
            patch(window.screen, 'availWidth', profile.screen.width);
            patch(window.screen, 'availHeight', profile.screen.height);
            patch(window.screen, 'colorDepth', 24);
            patch(window.screen, 'pixelDepth', 24);
          }

          if (window.screen && window.screen.orientation) {
            patch(window.screen.orientation, 'type', profile.orientationType);
            patch(window.screen.orientation, 'angle', profile.orientationAngle);
          }

          try {
            const query = navigator.permissions?.query?.bind(navigator.permissions);
            if (query) {
              navigator.permissions.query = parameters => {
                if (parameters && parameters.name === 'notifications') {
                  return Promise.resolve({ state: Notification.permission });
                }
                return query(parameters);
              };
            }
          } catch (e) {}

          if (!window.chrome) {
            Object.defineProperty(window, 'chrome', {
              value: { runtime: {}, app: {} },
              configurable: true
            });
          }

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

    async def _notify_browser_closed(self, account_id, on_close):
        if account_id in self._browser_close_notified:
            return
        self._browser_close_notified.add(account_id)
        try:
            self._closed_context_ids.add(account_id)
            self.browsers.pop(account_id, None)
            if on_close:
                on_close(account_id)
        finally:
            self._browser_close_notified.discard(account_id)

    def _attach_close_listener(self, account_id, browser, on_close):
        loop = asyncio.get_running_loop()

        def _on_close(*_args):
            loop.create_task(self._notify_browser_closed(account_id, on_close))

        try:
            browser.on("close", _on_close)
        except Exception as exc:
            self.logger.warning(f"Failed to attach browser close listener for {account_id}: {exc}")

    async def open_account(self, account, config, on_close=None):
        if not self._ensure_ready():
            return {"error": "Browser engine not initialized"}

        account_id = account["id"]

        if account_id in self.browsers:
            browser = self.browsers[account_id]
            page = await self._pick_primary_page(browser)
            if page is None:
                await self._notify_browser_closed(account_id, on_close)
                return {"error": "Browser window is no longer available. Try launching the account again."}
            try:
                await page.bring_to_front()
            except Exception:
                pass
            self.logger.info(f"Account {account['name']} already open, focused existing window")
            return {"success": True, "account_id": account_id, "already_open": True}

        domain = account.get("domain")
        if not domain:
            return {"need_domain": True}
        try:
            domain = normalize_target_url(domain)
        except ValueError as exc:
            return {"error": f"Invalid account domain: {exc}"}
        account["domain"] = domain

        try:
            device_profile = normalize_device_profile(account.get("device_profile"))
            args = self.default_launch_args()

            proxy_settings = account.get("proxy") or {}
            proxy = None
            allow_insecure_https = self.config.should_ignore_https_errors() and bool(proxy_settings.get("server"))

            if proxy_settings.get("server"):
                preflight = self._ping_proxy_sync(
                    proxy_settings,
                    timeout=PROXY_PREFLIGHT_TIMEOUT_S,
                    attempts=1,
                )
                if not preflight.get("alive"):
                    return {
                        "error": (
                            "Proxy did not respond quickly enough. "
                            f"Check it before launch. Details: {preflight.get('error') or 'timeout'}"
                        )
                    }
                proxy = {"server": proxy_settings["server"]}
                if proxy_settings.get("username"):
                    proxy["username"] = proxy_settings["username"]
                if proxy_settings.get("password"):
                    proxy["password"] = proxy_settings["password"]
            if allow_insecure_https:
                args.append("--ignore-certificate-errors")

            viewport = device_profile["viewport"]
            screen = device_profile.get("screen", viewport)
            args = self._with_window_size_arg(args, self._launch_window_size(device_profile))
            user_data_dir = str(config.get_profile_path(account_id))
            requested_timezone = self._normalize_timezone(account.get("timezone"))

            launch_kwargs = {
                "user_data_dir": user_data_dir,
                "headless": False,
                "args": args,
                "no_viewport": True,
                "proxy": proxy,
                "locale": account.get("locale", "ru-RU"),
                "timezone_id": requested_timezone,
                "user_agent": device_profile["user_agent"],
                "color_scheme": device_profile.get("color_scheme", "light"),
                "ignore_https_errors": allow_insecure_https,
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
            self._closed_context_ids.discard(account_id)
            self._attach_close_listener(account_id, browser, on_close)
            browser_brand, browser_version = self._browser_brand_version(device_profile["browser"])
            await self._apply_device_profile(
                browser,
                {
                    "browserBrand": browser_brand,
                    "browserVersion": browser_version,
                    "platform": device_profile["platform"],
                    "maxTouchPoints": device_profile["max_touch_points"],
                    "hardwareConcurrency": device_profile["hardware_concurrency"],
                    "deviceMemory": device_profile["device_memory"],
                    "isMobile": device_profile["is_mobile"],
                    "model": device_profile["model"],
                    "os": device_profile["os"],
                    "osVersion": device_profile["os"].split(" ", 1)[-1],
                    "screen": screen,
                    "deviceScaleFactor": device_profile.get("device_scale_factor", 1),
                    "language": account.get("locale", "ru-RU"),
                    "languages": [account.get("locale", "ru-RU"), "en-US", "en"],
                    "vendor": "Google Inc.",
                    "plugins": [1, 2, 3, 4, 5],
                    "orientationType": "portrait-primary" if device_profile.get("is_mobile") else "landscape-primary",
                    "orientationAngle": 0,
                },
            )

            page = await self._pick_primary_page(browser)

            try:
                await page.goto(domain, timeout=NAVIGATION_TIMEOUT_MS, wait_until="domcontentloaded")
                await page.wait_for_load_state("domcontentloaded", timeout=LOAD_STATE_TIMEOUT_MS)
            except Exception as e:
                self.logger.warning(f"Navigation issue: {e}")

            await self._cleanup_extra_pages(browser, page)
            try:
                await page.bring_to_front()
            except Exception:
                pass

            self.browsers[account_id] = browser

            network_info = dict(account.get("proxy_status") or {})
            needs_lookup = bool(proxy_settings) and (
                not network_info.get("ip")
                or network_info.get("ip") == "unknown"
                or not network_info.get("timezone")
                or network_info.get("timezone") == "unknown"
            )
            if needs_lookup:
                try:
                    network_info = await self.get_network_info(proxy_settings)
                except Exception as exc:
                    self.logger.warning(f"Network info lookup failed: {exc}")
                    network_info = dict(account.get("proxy_status") or {})
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

    async def close_account(self, account_id):
        try:
            browser = self.browsers.get(account_id)
            if browser:
                await browser.close()
                self.browsers.pop(account_id, None)
                return True
            return False
        except Exception as e:
            self.logger.error(f"Close account error: {e}")
            raise

    async def _primary_page_for_account(self, account_id):
        browser = self.browsers.get(account_id)
        if not browser or account_id in self._closed_context_ids:
            return None
        try:
            return await self._pick_primary_page(browser)
        except Exception:
            await self._notify_browser_closed(account_id, None)
            return None

    async def get_account_url(self, account_id):
        page = await self._primary_page_for_account(account_id)
        if not page:
            return None
        try:
            return page.url
        except Exception:
            return None

    async def navigate_account(self, account_id, url: str):
        page = await self._primary_page_for_account(account_id)
        if not page:
            return False
        try:
            target = normalize_target_url(url)
        except ValueError:
            return False
        try:
            await page.goto(target, timeout=NAVIGATION_TIMEOUT_MS, wait_until="domcontentloaded")
            await self._cleanup_extra_pages(self.browsers[account_id], page)
            await page.bring_to_front()
            return True
        except Exception as exc:
            self.logger.warning(f"Account navigation failed: {exc}")
            return False

    async def back_account(self, account_id):
        page = await self._primary_page_for_account(account_id)
        if not page:
            return False
        try:
            await page.go_back(timeout=15000, wait_until="domcontentloaded")
            await page.bring_to_front()
            return True
        except Exception:
            return False

    async def forward_account(self, account_id):
        page = await self._primary_page_for_account(account_id)
        if not page:
            return False
        try:
            await page.go_forward(timeout=15000, wait_until="domcontentloaded")
            await page.bring_to_front()
            return True
        except Exception:
            return False

    async def reload_account(self, account_id):
        page = await self._primary_page_for_account(account_id)
        if not page:
            return False
        try:
            await page.reload(timeout=NAVIGATION_TIMEOUT_MS, wait_until="domcontentloaded")
            await page.bring_to_front()
            return True
        except Exception:
            return False

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

    def _extract_percent(self, message):
        match = re.search(r"(\d{1,3})%", message or "")
        if not match:
            return None
        try:
            value = int(match.group(1))
        except ValueError:
            return None
        return max(0, min(100, value))

    def _friendly_install_status(self, message):
        lower = (message or "").lower()
        if "chrome for testing" in lower or "downloading chromium" in lower:
            return "Downloading browser..."
        if "ffmpeg" in lower:
            return "Downloading media dependencies..."
        if "headless shell" in lower:
            return "Downloading browser components..."
        if "downloaded to" in lower:
            return "Verifying downloaded files..."
        return message

    async def install_chromium(self, status_callback=None, progress_callback=None, log_callback=None):
        self.logger.info("Installing Chromium...")
        self._emit_install_status(status_callback, "Installing Chromium...")
        if progress_callback:
            progress_callback(0)

        for attempt in range(1, 4):
            self._emit_install_status(status_callback, f"Installing Chromium (attempt {attempt}/3)...")
            stderr = await asyncio.to_thread(
                self._run_playwright_install,
                status_callback,
                progress_callback,
                log_callback,
            )
            if stderr is None:
                self.logger.info("Chromium installed")
                self._emit_install_status(status_callback, "Chromium installed")
                if progress_callback:
                    progress_callback(100)
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

    def _run_playwright_install(self, status_callback=None, progress_callback=None, log_callback=None):
        class _StreamRelay(io.TextIOBase):
            def __init__(self, handle_line):
                super().__init__()
                self._handle_line = handle_line
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
                        self._handle_line(message)
                return len(text)

            def flush(self):
                if self._buffer.strip():
                    self._handle_line(self._buffer.strip())
                self._buffer = ""

        old_argv = sys.argv[:]
        old_env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(self.config.browsers_dir)
        original_popen = subprocess.Popen

        def _handle_message(message):
            if log_callback:
                try:
                    log_callback(message)
                except Exception:
                    pass
            friendly = self._friendly_install_status(message)
            self._emit_install_status(status_callback, friendly)
            percent = self._extract_percent(message)
            if percent is not None and progress_callback:
                try:
                    progress_callback(percent)
                except Exception:
                    pass

        def _popen_no_console(*args, **kwargs):
            if sys.platform == "win32":
                kwargs["creationflags"] = kwargs.get("creationflags", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            return original_popen(*args, **kwargs)

        relay = _StreamRelay(_handle_message)
        try:
            sys.argv = ["playwright", "install", "chromium"]
            subprocess.Popen = _popen_no_console
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
            subprocess.Popen = original_popen
            sys.argv = old_argv
            if old_env is None:
                os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
            else:
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = old_env
