import asyncio
from playwright.async_api import async_playwright
from playwright.__main__ import main as playwright_cli_main
import sys
import os
from urllib.parse import quote

import requests
from src.device_profiles import normalize_device_profile
from src.logger import Logger


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

    async def detect_timezone(self, proxy_settings):
        if not proxy_settings or not proxy_settings.get("server"):
            return None
        return await asyncio.to_thread(self._detect_timezone_sync, proxy_settings)

    def _detect_timezone_sync(self, proxy_settings):
        proxy_url = self._build_proxy_url(proxy_settings)
        response = requests.get(
            "https://ipapi.co/timezone/",
            proxies={"http": proxy_url, "https": proxy_url},
            timeout=8,
        )
        response.raise_for_status()
        timezone = response.text.strip()
        if "/" not in timezone:
            raise ValueError("Timezone not detected")
        return timezone

    def _fetch_network_info_sync(self, proxy_settings):
        proxy_url = self._build_proxy_url(proxy_settings)
        proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
        response = requests.get("https://ipapi.co/json/", proxies=proxies, timeout=8)
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
            args = ['--disable-blink-features=AutomationControlled']

            if sys.platform == "win32":
                args.append("--disable-gpu")
            elif sys.platform == "linux":
                args += ["--no-sandbox", "--disable-dev-shm-usage"]

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
            browser = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=str(config.get_profile_path(account_id)),
                headless=False,
                args=args,
                viewport=viewport,
                screen=screen,
                proxy=proxy,
                locale=account.get("locale", "ru-RU"),
                timezone_id=account.get("timezone", "Europe/Moscow"),
                user_agent=device_profile["user_agent"],
                color_scheme=device_profile.get("color_scheme", "light"),
                device_scale_factor=device_profile.get("device_scale_factor", 1),
                is_mobile=device_profile.get("is_mobile", False),
                has_touch=device_profile.get("has_touch", False),
            )
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

            page = await browser.new_page()

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
                    "timezone": account.get("timezone", network_info.get("timezone", "unknown")),
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
            browser = await self.playwright.chromium.launch()
            await browser.close()
            return True
        except:
            return False

    async def install_chromium(self):
        self.logger.info("Installing Chromium...")

        for attempt in range(1, 4):
            stderr = await asyncio.to_thread(self._run_playwright_install)
            if stderr is None:
                self.logger.info("Chromium installed")
                return True

            self.logger.warning(
                f"Chromium install attempt {attempt}/3 failed: {stderr}"
            )
            await asyncio.sleep(1)

        self.logger.error("Chromium install failed after 3 attempts")
        return False

    def _run_playwright_install(self):
        old_argv = sys.argv[:]
        old_env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(self.config.browsers_dir)
        try:
            sys.argv = ["playwright", "install", "chromium"]
            try:
                playwright_cli_main()
            except SystemExit as exc:
                if exc.code in (0, None):
                    return None
                return f"Playwright installer exited with code {exc.code}"
            return None
        except Exception as exc:
            return str(exc)
        finally:
            sys.argv = old_argv
            if old_env is None:
                os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
            else:
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = old_env
