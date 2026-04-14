import PyInstaller.__main__
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

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

    "--add-data=assets;assets",

    "--hidden-import=requests",
    "--hidden-import=urllib3",
    "--hidden-import=PyQt6.QtCore",
    "--hidden-import=PyQt6.QtWidgets",
    "--hidden-import=PyQt6.QtGui",
])