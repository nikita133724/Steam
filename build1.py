import PyInstaller.__main__
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PyInstaller.__main__.run([
    os.path.join(BASE_DIR, 'installer.py'),

    '--onefile',
    '--clean',
    '--noconfirm',

    '--name=MultiaccountInstaller',

    '--distpath=dist',
    '--workpath=build',
    '--specpath=spec',

    '--hidden-import=requests',
])