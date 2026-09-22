#!/bin/zsh
# Double-click this file on macOS, or run ./Phrame.command in a terminal.
set -e

cd -- "${0:A:h}"

venv_dir=".venv"

# PySide6's macOS Cocoa plugin is not reliable with brand-new Python releases.
# Prefer a stable interpreter, while allowing an explicit override for advanced
# users and CI. Keep this list in descending preference order.
python_cmd="${PHRAME_PYTHON:-}"
if [[ -z "$python_cmd" ]]; then
  for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      candidate_version="$($candidate -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
      candidate_major="${candidate_version%%.*}"
      candidate_minor="${candidate_version#*.}"
      if (( candidate_major == 3 && candidate_minor >= 10 && candidate_minor <= 13 )); then
        python_cmd="$(command -v "$candidate")"
        break
      fi
    fi
  done
fi

if [[ -z "$python_cmd" || ! -x "$python_cmd" ]]; then
  cat <<'EOF'
Phrame needs Python 3.10 through 3.13 on macOS.

Install Python 3.13 with Homebrew:
  brew install python@3.13

Then run ./Phrame.command again.
EOF
  exit 1
fi

# Rebuild a virtual environment made with an unsupported Python version. This
# fixes the Qt "cocoa" plugin failure caused by a Python 3.14 environment.
if [[ -x "$venv_dir/bin/python3" ]]; then
  venv_version="$("$venv_dir/bin/python3" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
  venv_major="${venv_version%%.*}"
  venv_minor="${venv_version#*.}"
  if [[ "$venv_major" != "3" ]] || (( venv_minor < 10 || venv_minor > 13 )); then
    echo "Rebuilding Phrame's environment (Python $venv_version is not supported)..."
    rm -rf -- "$venv_dir"
  fi
fi

if [[ ! -x "$venv_dir/bin/python3" ]]; then
  echo "Setting up Phrame for the first time..."
  "$python_cmd" -m venv "$venv_dir"
  "$venv_dir/bin/python3" -m pip install --upgrade pip
  "$venv_dir/bin/python3" -m pip install -r requirements.txt
fi

# Locate the Cocoa plugin inside this venv. A partially installed PySide6 can
# contain Qt's Python modules but omit its platform plugins, so repair it once
# automatically before launching.
qt_plugin_dir="$("$venv_dir/bin/python3" -c 'from pathlib import Path; import PySide6; print(Path(PySide6.__file__).resolve().parent / "Qt" / "plugins")')"
if [[ ! -f "$qt_plugin_dir/platforms/libqcocoa.dylib" ]]; then
  echo "Repairing the macOS Qt platform plugin..."
  "$venv_dir/bin/python3" -m pip install --no-cache-dir --force-reinstall PySide6
  qt_plugin_dir="$("$venv_dir/bin/python3" -c 'from pathlib import Path; import PySide6; print(Path(PySide6.__file__).resolve().parent / "Qt" / "plugins")')"
fi

# Keep Qt on the native macOS backend even if VS Code or a shell inherited
# plugin settings from Homebrew, XQuartz, Docker, or a remote Linux session.
unset DYLD_LIBRARY_PATH
unset DYLD_FRAMEWORK_PATH
export QT_PLUGIN_PATH="$qt_plugin_dir"
export QT_QPA_PLATFORM_PLUGIN_PATH="$qt_plugin_dir/platforms"
export QT_QPA_PLATFORM=cocoa

exec "$venv_dir/bin/python3" main.py "$@"
