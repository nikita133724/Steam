import asyncio
from playwright.async_api import async_playwright
import sys
import os
from src.logger import Logger


class BrowserEngine:
    def __init__(self, config):
        self.config = config
        self.playwright = None
        self.browsers = {}          # account_id -> browser_context
        self.logger = Logger.get_instance()   # ← один раз создаём logger

    async def init(self):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(self.config.browsers_dir)
        self.playwright = await async_playwright().start()

    async def open_account(self, account, config, on_close=None):
        """Открывает аккаунт в изолированном браузере"""
        logger = self.logger                    # используем self.logger
        account_id = account["id"]

        # Проверяем, не открыт ли уже
        if account_id in self.browsers:
            logger.info(f"Account {account['name']} already open")
            return None

        profile_path = config.get_profile_path(account_id)

        # Проверяем первый запуск (нужен домен)
        domain = account.get("domain")
        if not domain:
            return {"need_domain": True}

        logger.info(f"Opening account {account['name']} with domain {domain}")

        try:
            args = ['--disable-blink-features=AutomationControlled']
            if sys.platform == 'linux':
                args.extend(['--no-sandbox', '--disable-dev-shm-usage'])
            elif sys.platform == 'win32':
                args.append('--disable-gpu')

            proxy_settings = account.get("proxy") or {}
            proxy = None
            if proxy_settings.get("server"):
                proxy = {
                    "server": proxy_settings["server"],
                }
                if proxy_settings.get("username"):
                    proxy["username"] = proxy_settings["username"]
                if proxy_settings.get("password"):
                    proxy["password"] = proxy_settings["password"]

            # Запускаем persistent context
            browser = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_path),
                headless=False,
                args=args,
                viewport=None,
                proxy=proxy,
                locale=account.get("locale", "ru-RU"),
                timezone_id=account.get("timezone", "Europe/Moscow"),
                user_agent=account.get("user_agent",
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
            )

            page = await browser.new_page()
            await page.goto(domain)

            self.browsers[account_id] = browser

            # Мониторим закрытие браузера
            asyncio.create_task(self._monitor_browser(account_id, browser, on_close))

            logger.info(f"Account {account['name']} opened successfully")
            return {"success": True}

        except Exception as e:
            logger.error(f"Failed to open account {account['name']}: {str(e)}")
            return {"error": str(e)}

    async def _monitor_browser(self, account_id, browser, on_close):
        """Следит за закрытием браузера"""
        try:
            # Ждём пока все страницы не закроются
            while len(browser.pages) > 0:
                await asyncio.sleep(1)
                try:
                    for page in browser.pages:
                        await page.evaluate("1")
                except:
                    break

            # Браузер закрыт пользователем
            await asyncio.sleep(1)
            await browser.close()

            if account_id in self.browsers:
                del self.browsers[account_id]

            if on_close:
                on_close(account_id)

        except Exception as e:
            self.logger.error(f"Monitor error: {str(e)}")   # ← исправлено

    async def close_account(self, account_id):
        """Мягкое закрытие аккаунта"""
        if account_id in self.browsers:
            browser = self.browsers[account_id]
            await asyncio.sleep(1)
            await browser.close()
            del self.browsers[account_id]

    async def close_all(self):
        """Мягкое закрытие всех браузеров"""
        for account_id, browser in list(self.browsers.items()):
            await self.close_account(account_id)

    async def shutdown(self):
        """Полная остановка движка"""
        await self.close_all()
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None

    async def check_chromium(self):
        """Проверяет установлен ли Chromium"""
        try:
            browser = await self.playwright.chromium.launch()
            await browser.close()
            return True
        except:
            return False

    async def install_chromium(self):
        """Устанавливает Chromium"""
        import subprocess
        import sys

        self.logger.info("Installing Chromium...")   # ← исправлено

        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "playwright", "install", "chromium",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            self.logger.info("Chromium installed successfully")
            return True
        else:
            self.logger.error(f"Chromium install failed: {stderr.decode()}")
            return False