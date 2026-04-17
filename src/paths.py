from pathlib import Path
import os
import sys

APP_NAME = "Multiaccount"
EXE_NAME = "Multiaccount.exe"
APP_ID = "Multiaccount.Desktop"


def _local_appdata() -> Path:
    value = os.getenv("LOCALAPPDATA")
    if value:
        return Path(value)
    return Path.home() / "AppData" / "Local"


def get_install_dir() -> Path:
    if sys.platform == "win32":
        return _local_appdata() / "Programs" / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}" / "program"


def get_data_dir() -> Path:
    if sys.platform == "win32":
        return _local_appdata() / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}"


def get_installed_exe() -> Path:
    return get_install_dir() / EXE_NAME
