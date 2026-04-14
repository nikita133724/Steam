import PyInstaller.__main__
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
MAIN_FILE = BASE_DIR / "main.py"

PyInstaller.__main__.run([
    str(MAIN_FILE),

    '--onedir',
    '--windowed',
    '--clean',
    '--noconfirm',

    '--name=Multiaccount',

    f'--add-data={ASSETS_DIR};assets',

    '--distpath=dist',
    '--workpath=build',
    '--specpath=spec',

    '--collect-all=PyQt6',
    '--collect-all=playwright',

    '--hidden-import=requests',
    '--hidden-import=asyncio',
])