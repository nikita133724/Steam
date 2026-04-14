import PyInstaller.__main__
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MAIN_FILE = BASE_DIR / "main.py"
assets_path = str(BASE_DIR / "assets")

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


    f"--add-data={assets_path}{os.pathsep}assets",

    # PyQt6 + Playwright сборка
    "--collect-all=PyQt6",
    "--collect-all=playwright",

    "--hidden-import=requests",
    "--hidden-import=asyncio",
])