import asyncio
from playwright.async_api import async_playwright
from pathlib import Path
import sys

class BrowserEngine:
    def __init__(self):
        self.playwright = None
        self.browsers = {}  # account_id -> browser_context
    
    async def init(self):
        self.playwright = await async_playwright().start()
    
    async def open_account(self, account, config, on_close=None):
        """Открывает аккаунт в изолированном браузере"""
        logger = Logger.get_instance()
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
            # Запускаем persistent context (сохраняет всё в profile_path)
            browser = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_path),
                headless=False,
                args = ['--disable-blink-features=AutomationControlled']
                if sys.platform == 'linux':
                    args.extend(['--no-sandbox', '--disable-dev-shm-usage'])
                elif sys.platform == 'win32':
                    args.append('--disable-gpu')

                viewport=None,  # Используем сохранённый размер или дефолт
                locale=account.get("locale", "ru-RU"),
                timezone_id=account.get("timezone", "Europe/Moscow"),
                user_agent=account.get("user_agent", 
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
            )
            
            page = await browser.new_page()
            await page.goto(domain)
            
            self.browsers[account_id] = browser
            
            # Мониторим закрытие
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
                # Проверяем, открыты ли ещё страницы
                try:
                    for page in browser.pages:
                        await page.evaluate("1")
                except:
                    break
            
            # Браузер закрыт пользователем
            await asyncio.sleep(1)  # Даём время на сохранение данных
            await browser.close()
            
            if account_id in self.browsers:
                del self.browsers[account_id]
            
            if on_close:
                on_close(account_id)
                
        except Exception as e:
            Logger.get_instance().error(f"Monitor error: {str(e)}")
    
    async def close_account(self, account_id):
        """Мягкое закрытие аккаунта"""
        if account_id in self.browsers:
            browser = self.browsers[account_id]
            await asyncio.sleep(1)  # Даём сохраниться
            await browser.close()
            del self.browsers[account_id]
    
    async def close_all(self):
        """Мягкое закрытие всех браузеров"""
        for account_id, browser in list(self.browsers.items()):
            await self.close_account(account_id)
    
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
        
        Logger.get_instance().info("Installing Chromium...")
        
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "playwright", "install", "chromium",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            Logger.get_instance().info("Chromium installed successfully")
            return True
        else:
            Logger.get_instance().error(f"Chromium install failed: {stderr.decode()}")
            return False


# Импорт логгера здесь чтобы избежать циклического импорта
from src.logger import Logger
