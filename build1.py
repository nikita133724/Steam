from pathlib import Path
import PyInstaller.__main__
import os

BASE_DIR = Path(__file__).resolve().parent
assets_path = BASE_DIR / "assets"

PyInstaller.__main__.run([
    str(BASE_DIR / "installer.py"),

    "--onefile",
    "--windowed",
    "--clean",
    "--noconfirm",

    "--name=MultiaccountInstaller",

    "--distpath=dist",
    "--workpath=build",
    "--specpath=spec",

    f"--add-data={assets_path.resolve()}{os.pathsep}assets",

    "--hidden-import=requests",
    "--hidden-import=urllib3",
    "--hidden-import=PyQt6.QtCore",
    "--hidden-import=PyQt6.QtWidgets",
    "--hidden-import=PyQt6.QtGui",
])