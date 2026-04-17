import sys
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import QLockFile, QDir, QStandardPaths
from src.app import MainWindow
from src.config import Config
from src.launcher import bootstrap_startup, ensure_windows_runtime
from src.paths import APP_ID


def main() -> int:
    bootstrap_code = bootstrap_startup(sys.argv[1:])
    if bootstrap_code is not None:
        return bootstrap_code

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass

    app = QApplication(sys.argv)
    config = Config()
    lang = config.lang
    runtime_status = ensure_windows_runtime()
    if runtime_status.get("checked") and not runtime_status.get("ok"):
        message = runtime_status.get("message") or lang.get(
            "runtime_missing",
            "Microsoft VC++ Redistributable is missing.",
        )
        manual_installer = runtime_status.get("manual_installer")
        if manual_installer:
            message += f"\n\n{lang.get('manual_installer_label', 'Manual installer')}:\n{manual_installer}"
        QMessageBox.warning(None, lang.get("dialog_warning_title", "Warning"), message)

    runtime_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.TempLocation)
    lock_file = QLockFile(QDir(runtime_dir).filePath("multiaccount.lock"))
    lock_file.setStaleLockTime(0)

    if not lock_file.tryLock(100):
        QMessageBox.information(
            None,
            lang.get("dialog_info_title", "Info"),
            lang.get("already_running", "The application is already running."),
        )
        return 0

    window = MainWindow()
    window.show()
    code = app.exec()
    lock_file.unlock()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
