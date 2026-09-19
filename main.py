"""PhotoForge — a beginner-friendly photo editor. Run: python main.py [photo]"""
import ctypes
import sys

from PySide6.QtWidgets import QApplication, QDialog

from app import state as app_state
from app import theme
from app.auth import AuthManager
from app.login_window import LoginWindow
from app.main_window import MainWindow


def _start_session(auth):
    """Show the login screen and decide how this session stores its state.

    Returns the store to use, or ``None`` if the user closed the window
    without choosing — in which case the app should not open at all.
    """
    if auth.is_logged_in:
        # Already signed in from a previous run; skip straight to the editor.
        return app_state.PersistentStore()

    gate = LoginWindow(auth)
    if gate.exec() != QDialog.Accepted:
        return None
    return app_state.PersistentStore() if auth.is_logged_in else app_state.EphemeralStore()


def main():
    if sys.platform == "win32":
        # Give the app its own taskbar entry/icon grouping instead of python.exe's.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PhotoForge.Editor")
    app = QApplication(sys.argv)
    app.setApplicationName("PhotoForge")
    theme.apply(app)

    auth = AuthManager()
    store = _start_session(auth)
    if store is None:
        return 0

    win = MainWindow(auth=auth, store=store)
    win.show()
    if len(sys.argv) > 1:
        win.load_path(sys.argv[1])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
