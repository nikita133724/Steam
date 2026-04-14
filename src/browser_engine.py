import asyncio
from playwright.async_api import async_playwright
import sys
import os
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

            browser = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=str(config.get_profile_path(account_id)),
                headless=False,
                args=args,
                viewport=None,
                proxy=proxy,
                locale=account.get("locale", "ru-RU"),
                timezone_id=account.get("timezone", "Europe/Moscow"),
                user_agent=account.get(
                    "user_agent",
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
            )

            page = await browser.new_page()

            try:
                await page.goto(domain, timeout=30000)
            except Exception as e:
                self.logger.warning(f"Navigation issue: {e}")

            self.browsers[account_id] = browser

            asyncio.create_task(self._monitor_browser(account_id, browser, on_close))

            self.logger.info(f"Account {account['name']} opened")
            return {"success": True}

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
        except Exception as e:
            self.logger.error(f"Close account error: {e}")

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

        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "playwright", "install", "chromium",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            self.logger.info("Chromium installed")
            return True
        else:
            self.logger.error(f"Install failed: {stderr.decode()}")
            return False