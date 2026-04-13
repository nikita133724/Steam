import PyInstaller.__main__
import os

PyInstaller.__main__.run([
    'main.py',
    '--onefile',
    '--windowed',
    '--name', 'Multiaccount',
    '--add-data', 'assets;assets',
    '--icon', 'NONE',
    '--clean',
    '--noconfirm'
])
