import PyInstaller.__main__
import os

data_separator = ';' if os.name == 'nt' else ':'

PyInstaller.__main__.run([
    'main.py',
    '--onefile',
    '--windowed',
    '--name', 'Multiaccount',
    '--add-data', f'assets{data_separator}assets',
    '--icon', 'NONE',
    '--clean',
    '--noconfirm'
])
