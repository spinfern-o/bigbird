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

# Keep Qt on the native macOS backend even if VS Code or a shell inherited
# plugin settings from Homebrew, XQuartz, Docker, or a remote Linux session.
unset QT_PLUGIN_PATH
unset QT_QPA_PLATFORM_PLUGIN_PATH
unset DYLD_LIBRARY_PATH
unset DYLD_FRAMEWORK_PATH
export QT_QPA_PLATFORM=cocoa

exec .venv/bin/python3 main.py "$@"
