#!/bin/zsh
# Double-click this file on macOS, or run ./Phrame.command in a terminal.
set -e

cd -- "${0:A:h}"

if [[ ! -x ".venv/bin/python3" ]]; then
  echo "Setting up Phrame for the first time..."
  /usr/bin/env python3 -m venv .venv
  .venv/bin/python3 -m pip install --upgrade pip
  .venv/bin/python3 -m pip install -r requirements.txt
fi

# Locate the Cocoa plugin inside this venv. A partially installed PySide6 can
# contain Qt's Python modules but omit its platform plugins, so repair it once
# automatically before launching.
qt_plugin_dir="$(.venv/bin/python3 -c 'from pathlib import Path; import PySide6; print(Path(PySide6.__file__).resolve().parent / "Qt" / "plugins")')"
if [[ ! -f "$qt_plugin_dir/platforms/libqcocoa.dylib" ]]; then
  echo "Repairing the macOS Qt platform plugin..."
  .venv/bin/python3 -m pip install --no-cache-dir --force-reinstall PySide6
  qt_plugin_dir="$(.venv/bin/python3 -c 'from pathlib import Path; import PySide6; print(Path(PySide6.__file__).resolve().parent / "Qt" / "plugins")')"
fi

# Keep Qt on the native macOS backend even if VS Code or a shell inherited
# plugin settings from Homebrew, XQuartz, Docker, or a remote Linux session.
unset DYLD_LIBRARY_PATH
unset DYLD_FRAMEWORK_PATH
export QT_PLUGIN_PATH="$qt_plugin_dir"
export QT_QPA_PLATFORM_PLUGIN_PATH="$qt_plugin_dir/platforms"
export QT_QPA_PLATFORM=cocoa

exec .venv/bin/python3 main.py "$@"
