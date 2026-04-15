from pathlib import Path
import subprocess
import sys

BASE_DIR = Path(__file__).resolve().parent
MAIN_FILE = BASE_DIR / "main.py"


def main() -> int:
    cmd = [
        sys.executable,
        "-m",
        "nuitka",
        "--onefile",
        "--windows-console-mode=disable",
        "--enable-plugin=pyqt6",
        "--include-data-dir=assets=assets",
        "--include-package=playwright",
        "--include-package=requests",
        "--include-package=socks",
        "--output-dir=dist",
        "--output-filename=Multiaccount.exe",
        "--assume-yes-for-downloads",
        str(MAIN_FILE),
    ]
    return subprocess.call(cmd, cwd=BASE_DIR)


if __name__ == "__main__":
    raise SystemExit(main())
