import os
import requests
import subprocess
import hashlib

APP_NAME = "Multiaccount"
APP_DIR = os.path.join(os.getenv("LOCALAPPDATA"), APP_NAME)
APP_EXE = os.path.join(APP_DIR, "Multiaccount.exe")
TEMP_EXE = APP_EXE + ".tmp"

MANIFEST_URL = "https://github.com/nikita133724/Steam/releases/latest/download/manifest.json"

def ensure_dir():
    os.makedirs(APP_DIR, exist_ok=True)

def get_download_url():
    r = requests.get(MANIFEST_URL, timeout=10)
    r.raise_for_status()

    data = r.json()

    if "url" not in data:
        raise ValueError("Manifest missing 'url'")

    return data["url"], data.get("sha256")

def verify_sha256(file_path, expected_hash):
    sha256 = hashlib.sha256()

    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)

    return sha256.hexdigest().lower() == expected_hash.lower()
    
def download_exe():
    print("Downloading exe...")

    url, expected_hash = get_download_url()

    r = requests.get(url, stream=True)
    r.raise_for_status()

    with open(TEMP_EXE, "wb") as f:
        for chunk in r.iter_content(8192):
            if chunk:
                f.write(chunk)

    if expected_hash:
        if not verify_sha256(TEMP_EXE, expected_hash):
            os.remove(TEMP_EXE)
            raise ValueError("EXE hash mismatch!")

    os.replace(TEMP_EXE, APP_EXE)

def is_installed():
    return os.path.exists(APP_EXE)


def run_app():
    print("Running app...")
    subprocess.Popen([APP_EXE], cwd=APP_DIR, shell=False)

def main():
    try:
        ensure_dir()

        if not is_installed():
            download_exe()

        run_app()

    except Exception as e:
        print(f"Installer error: {e}")
        input("Press Enter to exit...")

if __name__ == "__main__":
    main()