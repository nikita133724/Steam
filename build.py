from pathlib import Path
import subprocess
import sys

BASE_DIR = Path(__file__).resolve().parent
MAIN_FILE = BASE_DIR / "main.py"
ICON_FILE = BASE_DIR / "assets" / "icon.ico"


def main() -> int:
    data_sep = ";" if sys.platform == "win32" else ":"
    assets_src = str((BASE_DIR / "assets").resolve())
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        "Multiaccount",
        "--distpath",
        str(BASE_DIR / "dist"),
        "--workpath",
        str(BASE_DIR / "build"),
        "--specpath",
        str(BASE_DIR / "spec"),
        f"--add-data={assets_src}{data_sep}assets",
        "--collect-all",
        "playwright",
        str(MAIN_FILE),
    ]

    if sys.platform == "win32":
        cmd.append("--noconsole")

    if ICON_FILE.exists():
        cmd.extend(["--icon", str(ICON_FILE)])
    return subprocess.call(cmd, cwd=BASE_DIR)


if __name__ == "__main__":
    raise SystemExit(main())
