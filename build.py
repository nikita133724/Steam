import PyInstaller.__main__

PyInstaller.__main__.run([
    'main.py',
    '--onefile',
    '--windowed',
    '--name', 'Multiaccount',
    '--add-data', 'assets:assets',   # всегда : 
    '--icon', 'NONE',
    '--clean',
    '--noconfirm'
])