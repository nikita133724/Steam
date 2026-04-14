import os
import sys
import time
import hashlib
import requests
import subprocess

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel,
    QProgressBar, QPushButton
)
from PyQt6.QtCore import QThread, pyqtSignal


APP_NAME = "Multiaccount"
APP_DIR = os.path.join(os.getenv("LOCALAPPDATA"), APP_NAME)
APP_EXE = os.path.join(APP_DIR, "Multiaccount.exe")
TEMP_EXE = APP_EXE + ".part"

MANIFEST_URL = "https://github.com/nikita133724/Steam/releases/latest/download/manifest.json"


def create_session():
    session = requests.Session()

    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[500, 502, 503, 504]
    )

    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    return session


class DownloadWorker(QThread):
    progress = pyqtSignal(int, float)
    status = pyqtSignal(str)
    error = pyqtSignal(str)
    done = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.running = True

    def stop(self):
        self.running = False

    def run(self):
        try:
            session = create_session()

            self.status.emit("Loading manifest...")

            r = session.get(MANIFEST_URL, timeout=15)
            r.raise_for_status()
            data = r.json()

            url = data["url"]
            expected_hash = data.get("sha256")

            self.status.emit("Downloading...")

            with session.get(url, stream=True, timeout=30) as r:
                r.raise_for_status()

                total = int(r.headers.get("content-length", 0))

                downloaded = 0
                start = time.time()

                with open(TEMP_EXE, "wb") as f:
                    for chunk in r.iter_content(8192):
                        if not self.running:
                            self.status.emit("Cancelled")
                            return

                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)

                            elapsed = time.time() - start
                            speed = (downloaded / 1024 / 1024) / max(elapsed, 0.1)
                            percent = int(downloaded * 100 / max(total, 1))

                            self.progress.emit(percent, speed)

            # VERIFY
            if expected_hash:
                self.status.emit("Verifying...")

                h = hashlib.sha256()
                with open(TEMP_EXE, "rb") as f:
                    for chunk in iter(lambda: f.read(8192), b""):
                        h.update(chunk)

                if h.hexdigest().lower() != expected_hash.lower():
                    raise ValueError("SHA256 mismatch")

            os.makedirs(APP_DIR, exist_ok=True)

            # 🔥 FIX: безопасная замена
            if os.path.exists(APP_EXE):
                os.remove(APP_EXE)

            os.replace(TEMP_EXE, APP_EXE)

            self.done.emit()

        except Exception as e:
            self.error.emit(str(e))


class InstallerWindow(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Multiaccount Installer")
        self.setFixedSize(420, 220)

        layout = QVBoxLayout()

        self.title = QLabel("Installing Multiaccount...")
        layout.addWidget(self.title)

        self.bar = QProgressBar()
        layout.addWidget(self.bar)

        self.speed = QLabel("Speed: 0 MB/s")
        layout.addWidget(self.speed)

        self.status = QLabel("Starting...")
        layout.addWidget(self.status)

        self.btn = QPushButton("Cancel")
        self.btn.clicked.connect(self.cancel)
        layout.addWidget(self.btn)

        self.setLayout(layout)

        self.worker = DownloadWorker()
        self.worker.progress.connect(self.on_progress)
        self.worker.status.connect(self.status.setText)
        self.worker.error.connect(self.on_error)
        self.worker.done.connect(self.finish)
        self.worker.start()

    def on_progress(self, p, speed):
        self.bar.setValue(p)
        self.speed.setText(f"Speed: {speed:.2f} MB/s")

    def cancel(self):
        self.worker.stop()
        self.status.setText("Cancelling...")
        self.close()

    def on_error(self, msg):
        self.status.setText(f"Error: {msg}")

    def finish(self):
        self.status.setText("Launching...")
        subprocess.Popen([APP_EXE], cwd=APP_DIR)
        self.close()


def main():
    app = QApplication(sys.argv)
    w = InstallerWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()