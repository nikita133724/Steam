import PyInstaller.__main__
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PyInstaller.__main__.run([
    os.path.join(BASE_DIR, 'main.py'),

    '--onefile',
    '--windowed',
    '--clean',
    '--noconfirm',

    '--name=Multiaccount',

    '--add-data=assets;assets',

    '--distpath=dist',
    '--workpath=build',
    '--specpath=spec',

    '--collect-submodules=PyQt6',
    '--collect-submodules=playwright',
    '--hidden-import=requests',
])