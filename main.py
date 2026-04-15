import sys
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import QLockFile, QDir, QStandardPaths
from src.app import MainWindow
from src.launcher import bootstrap_startup


def main() -> int:
    bootstrap_code = bootstrap_startup(sys.argv[1:])
    if bootstrap_code is not None:
        return bootstrap_code

    app = QApplication(sys.argv)
    runtime_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.TempLocation)
    lock_file = QLockFile(QDir(runtime_dir).filePath("multiaccount.lock"))
    lock_file.setStaleLockTime(0)

    if not lock_file.tryLock(100):
        QMessageBox.information(None, "Multiaccount", "Приложение уже запущено.")
        return 0

    window = MainWindow()
    window.show()
    code = app.exec()
    lock_file.unlock()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
