import asyncio
import logging
import os
from playwright.async_api import async_playwright

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

async def run_server_script():
    async with async_playwright() as p:
        logger.info("Инициализация Playwright...")
        
        # Запуск с оптимизацией под Docker/Render (мало памяти)
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-dev-shm-usage", 
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-gpu"
            ]
        )
        
        # Имитация реального браузера
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 720}
        )
        
        page = await context.new_page()
        url = "https://ezcash78.casino/"
        
        try:
            logger.info(f"Переход по адресу: {url}")
            
            # Увеличиваем таймаут до 90 секунд для медленных прокси/серверов
            response = await page.goto(url, wait_until="networkidle", timeout=90000)
            
            if response:
                logger.info(f"Статус ответа: {response.status}")
            
            # Проверка заголовка
            title = await page.title()
            logger.info(f"Заголовок страницы: {title}")
            
            # Делаем скриншот для отладки (сохранится в корне проекта)
            await page.screenshot(path="debug_result.png")
            logger.info("Скриншот сохранен как debug_result.png")

            if "Cloudflare" in title or "Verify" in title or "Just a moment" in title:
                logger.warning("Внимание: Сработала защита Cloudflare/Капча. Бот заблокирован.")
            else:
                logger.info("Страница успешно загружена без видимых блокировок.")

        except Exception as e:
            logger.error(f"Произошла ошибка: {str(e)}")
            # Если упали по таймауту, все равно попробуем сделать скриншот того, что есть
            try:
                await page.screenshot(path="error_state.png")
            except:
                pass
        finally:
            logger.info("Закрытие браузера.")
            await browser.close()

if __name__ == "__main__":
    # Проверка среды (Render передает PORT, если это Web Service)
    if os.environ.get("PORT"):
        logger.info(f"Скрипт запущен в среде Render (Port: {os.environ.get('PORT')})")
    
    try:
        asyncio.run(run_server_script())
    except KeyboardInterrupt:
        logger.info("Работа остановлена пользователем.")
