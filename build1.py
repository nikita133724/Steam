import PyInstaller.__main__
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
assets_path = str(BASE_DIR / "assets")

PyInstaller.__main__.run([
    os.path.join(BASE_DIR, "installer.py"),

    "--onefile",
    "--windowed",
    "--clean",
    "--noconfirm",

    "--name=MultiaccountInstaller",

    "--distpath=dist",
    "--workpath=build",
    "--specpath=spec",

    f"--add-data={assets_path}{os.pathsep}assets",

    "--hidden-import=requests",
    "--hidden-import=urllib3",
    "--hidden-import=PyQt6.QtCore",
    "--hidden-import=PyQt6.QtWidgets",
    "--hidden-import=PyQt6.QtGui",
])