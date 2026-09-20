"""PhotoForge — a beginner-friendly photo editor. Run: python main.py [photo]"""
import ctypes
import importlib.util
import os
from pathlib import Path
import sys

# A shell or VS Code session can retain Qt paths from Homebrew, XQuartz, or a
# Linux-oriented setup.  On macOS those paths make Qt try to initialize xcb
# instead of its native Cocoa platform plugin and QApplication aborts before a
# window can be created. Point Qt directly at the plugins bundled with the
# active PySide6 installation before importing any Qt modules.
if sys.platform == "darwin":
    for variable in ("DYLD_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH"):
        os.environ.pop(variable, None)

    pyside_spec = importlib.util.find_spec("PySide6")
    if pyside_spec and pyside_spec.submodule_search_locations:
        pyside_dir = Path(next(iter(pyside_spec.submodule_search_locations)))
        plugin_dir = pyside_dir / "Qt" / "plugins"
        platform_dir = plugin_dir / "platforms"
        if (platform_dir / "libqcocoa.dylib").is_file():
            os.environ["QT_PLUGIN_PATH"] = str(plugin_dir)
            os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(platform_dir)

    os.environ["QT_QPA_PLATFORM"] = "cocoa"

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
