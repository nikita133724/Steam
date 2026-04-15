import sys
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import QLockFile, QDir, QStandardPaths
from src.app import MainWindow


def main():
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
    sys.exit(code)


if __name__ == "__main__":
    main()
