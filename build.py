import PyInstaller.__main__
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MAIN_FILE = BASE_DIR / "main.py"

PyInstaller.__main__.run([
    str(MAIN_FILE),

    "--onefile",
    "--windowed",
    "--clean",
    "--noconfirm",

    "--name=Multiaccount",

    "--distpath=dist",
    "--workpath=build",
    "--specpath=spec",

    # 🔥 FIX: assets теперь упакованы
    "--add-data=assets;assets",

    # PyQt6 + Playwright сборка
    "--collect-all=PyQt6",
    "--collect-all=playwright",

    "--hidden-import=requests",
    "--hidden-import=asyncio",
])