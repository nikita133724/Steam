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

    # assets
    '--add-data=assets;assets',

    # стабильные папки сборки
    '--distpath=dist',
    '--workpath=build',
    '--specpath=spec',

    # важные зависимости (Playwright)
    '--hidden-import=playwright',
    '--hidden-import=playwright.async_api',
])