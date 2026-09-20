"""PhotoForge — a beginner-friendly photo editor. Run: python main.py [photo]"""
import ctypes
import sys

from PySide6.QtWidgets import QApplication

from app import theme
from app.auth import AuthManager
from app.main_window import MainWindow


def main():
    if sys.platform == "win32":
        # Give the app its own taskbar entry/icon grouping instead of python.exe's.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PhotoForge.Editor")

    app = QApplication(sys.argv)
    app.setApplicationName("PhotoForge")
    theme.apply(app)

    # The editor opens straight away: open a photo and start editing without an
    # account. Signing in (the Log in button, top right) is only needed for the
    # cloud features — saving projects to your account and opening them on
    # another computer. A saved session is picked up automatically.
    auth = AuthManager()
    win = MainWindow(auth=auth)
    win.show()
    if len(sys.argv) > 1:
        win.load_path(sys.argv[1])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
