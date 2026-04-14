import PyInstaller.__main__
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
MAIN_FILE = BASE_DIR / "main.py"

PyInstaller.__main__.run([
    str(MAIN_FILE),

    '--onefile',
    '--windowed',
    '--clean',
    '--noconfirm',

    '--name=Multiaccount',

    f'--add-data={ASSETS_DIR};assets',

    '--distpath=dist',
    '--workpath=build',
    '--specpath=spec',

    '--collect-submodules=PyQt6',
    '--collect-submodules=playwright',
    '--hidden-import=requests',
])