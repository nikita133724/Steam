import os
import sys
import requests
import zipfile
import subprocess

APP_NAME = "mutiacc"
GITHUB_REPO_ZIP = "https://github.com/nikita133724/Steam/archive/refs/heads/main.zip"

APP_DIR = os.path.join(os.getenv("LOCALAPPDATA"), APP_NAME)
APP_EXE = os.path.join(APP_DIR, "mutliacc-main", "AccountFlow.exe")


# ------------------------
# Утилиты
# ------------------------

def ensure_dir():
    if not os.path.exists(APP_DIR):
        os.makedirs(APP_DIR)


def download_file(url, path):
    print("Скачивание:", url)
    r = requests.get(url, stream=True)

    with open(path, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)


def unzip(zip_path, extract_to):
    print("Распаковка...")
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_to)


# ------------------------
# Проверки
# ------------------------

def is_app_installed():
    return os.path.exists(APP_EXE)


def is_webview2_installed():
    # простая проверка
    path = os.path.join(os.environ["ProgramFiles(x86)"], "Microsoft", "EdgeWebView")
    return os.path.exists(path)


def install_webview2():
    print("Установка WebView2...")

    url = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
    installer_path = os.path.join(APP_DIR, "webview2.exe")

    download_file(url, installer_path)

    subprocess.run([installer_path, "/silent", "/install"], check=True)


# ------------------------
# Установка приложения
# ------------------------

def install_app():
    print("Установка приложения...")

    zip_path = os.path.join(APP_DIR, "app.zip")

    download_file(GITHUB_REPO_ZIP, zip_path)
    unzip(zip_path, APP_DIR)

    os.remove(zip_path)


# ------------------------
# Запуск
# ------------------------

def run_app():
    print("Запуск приложения...")
    subprocess.Popen(APP_EXE)


# ------------------------
# MAIN
# ------------------------

def main():
    ensure_dir()

    # 1. Проверка WebView2
    if not is_webview2_installed():
        install_webview2()

    # 2. Проверка приложения
    if not is_app_installed():
        install_app()

    # 3. Запуск
    run_app()


if __name__ == "__main__":
    main()