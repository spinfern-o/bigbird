#!/usr/bin/env bash
# One-time setup of the PhotoForge GPU server on a cloud GPU machine (e.g. NVIDIA Brev).
# Run from anywhere:  bash server/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m venv .venv-server
.venv-server/bin/python -m pip install --upgrade pip
.venv-server/bin/python -m pip install -r server/requirements.txt

echo "Downloading AI models (~590 MB)..."
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
echo "Setup done. Start the server with:"
echo "  export PHOTOFORGE_TOKEN='<the access token from PhotoForge > AI Settings>'"
echo "  bash server/start.sh"
