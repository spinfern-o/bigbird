#!/usr/bin/env bash
# One-time setup of the PhotoForge GPU server on a cloud GPU machine (e.g. NVIDIA Brev).
# Run from anywhere:  bash server/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."

# Ubuntu images often lack the venv module; install it automatically if needed.
if ! python3 -m venv --help >/dev/null 2>&1 || ! python3 -c "import ensurepip" 2>/dev/null; then
    PYV="$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
    echo "Installing python${PYV}-venv (needs sudo)..."
    sudo -n apt-get update -qq && sudo -n apt-get install -y -qq "python${PYV}-venv" python3-venv         || { echo "ERROR: couldn't install python${PYV}-venv (sudo needs a password?)"; exit 1; }
fi
[ -x .venv-server/bin/pip ] || { rm -rf .venv-server; python3 -m venv .venv-server; }
.venv-server/bin/python -m pip install --upgrade pip
.venv-server/bin/python -m pip install -r server/requirements.txt

echo "Downloading AI models (~380 MB)..."
.venv-server/bin/python - <<'EOF'
from app.ai import models
for key, info in models.MODELS.items():
    if not models.is_downloaded(key):
        print("  ", info.name)
        models.download(key)
EOF

.venv-server/bin/python - <<'EOF'
import onnxruntime as ort
if hasattr(ort, "preload_dlls"):
    ort.preload_dlls()
providers = ort.get_available_providers()
print("ONNX Runtime providers:", providers)
if "CUDAExecutionProvider" not in providers:
    print("WARNING: CUDA isn't available, so the server will run on the CPU (slow).")
EOF

echo
echo "Setup done. Make the server start automatically (recommended):"
echo "  export PHOTOFORGE_TOKEN='<the access token from PhotoForge > AI Settings>'"
echo "  bash server/install_service.sh"
