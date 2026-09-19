"""PhotoForge — a beginner-friendly photo editor. Run: python main.py [photo]"""
import ctypes
import sys

from PySide6.QtWidgets import QApplication, QDialog

from app import theme
from app.auth import AuthManager
from app.login_window import LoginWindow
from app.main_window import MainWindow


def main():
    if sys.platform == "win32":
        # Give the app its own taskbar entry/icon grouping instead of python.exe's.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PhotoForge.Editor")

    app = QApplication(sys.argv)
    app.setApplicationName("PhotoForge")
    theme.apply(app)

    # The account screen is always the first UI shown, including in packaged
    # builds. Login itself happens in the user's default browser.
    auth = AuthManager()
    login = LoginWindow(auth)
    if login.exec() != QDialog.Accepted:
        return

    win = MainWindow()
    win.show()
    if len(sys.argv) > 1:
        win.load_path(sys.argv[1])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
