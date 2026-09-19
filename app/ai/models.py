"""Registry of approved AI models, plus downloading and loading them.

Only models whose license allows commercial use belong here (see ROADMAP.txt).
Models download on first use into %LOCALAPPDATA%\\PhotoForge\\models.
"""
import os
import threading
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelInfo:
    key: str
    name: str
    purpose: str
    url: str
    filename: str
    size_mb: int
    license: str
    homepage: str
    gpu: bool  # False = known not to work with DirectML, always use CPU


MODELS = {
    "birefnet_lite": ModelInfo(
        "birefnet_lite", "BiRefNet-lite", "Remove Background",
        "https://huggingface.co/onnx-community/BiRefNet_lite-ONNX/resolve/main/onnx/model.onnx",
        "birefnet_lite.onnx", 224, "MIT", "https://github.com/ZhengPeng7/BiRefNet", gpu=True),
    "lama": ModelInfo(
        "lama", "LaMa (big-lama)", "Remove Object: best quality",
        "https://huggingface.co/Carve/LaMa-ONNX/resolve/main/lama_fp32.onnx",
        "lama_fp32.onnx", 208, "Apache 2.0", "https://github.com/advimman/lama", gpu=False),
    "migan": ModelInfo(
        "migan", "MI-GAN", "Remove Object: fast",
        "https://huggingface.co/andraniksargsyan/migan/resolve/main/migan_pipeline_v2.onnx",
        "migan_pipeline_v2.onnx", 28, "MIT", "https://github.com/Picsart-AI-Research/MI-GAN",
        gpu=True),
}


class Cancelled(Exception):
    pass


def models_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "PhotoForge", "models")
    os.makedirs(d, exist_ok=True)
    return d


def model_path(key):
    return os.path.join(models_dir(), MODELS[key].filename)


def is_downloaded(key):
    return os.path.isfile(model_path(key))


def download(key, progress=None, cancel_event=None):
    """Download a model. progress(done_bytes, total_bytes) is called as data arrives."""
    info = MODELS[key]
    dest = model_path(key)
    tmp = dest + ".part"
    req = urllib.request.Request(info.url, headers={"User-Agent": "PhotoForge"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or info.size_mb * 1_000_000)
            done = 0
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise Cancelled()
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return dest


# --------------------------------------------------------------------------- sessions

_sessions = {}
_lock = threading.Lock()


def gpu_available():
    try:
        import onnxruntime as ort
        return "DmlExecutionProvider" in ort.get_available_providers()
    except ImportError:
        return False


def device_name():
    return "graphics card (DirectML)" if gpu_available() else "processor (CPU)"


def _make_session(key, use_gpu):
    import onnxruntime as ort
    opts = ort.SessionOptions()
    providers = ["CPUExecutionProvider"]
    if use_gpu:
        providers.insert(0, "DmlExecutionProvider")
        opts.enable_mem_pattern = False  # required by DirectML
        opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    return ort.InferenceSession(model_path(key), sess_options=opts, providers=providers)


def run(key, feeds):
    """Run a model, preferring the GPU; falls back to the CPU if the GPU path fails."""
    with _lock:
        entry = _sessions.get(key)
        if entry is None:
            use_gpu = MODELS[key].gpu and gpu_available()
            try:
                entry = (_make_session(key, use_gpu), use_gpu)
            except Exception:
                if not use_gpu:
                    raise
                entry = (_make_session(key, False), False)
            _sessions[key] = entry
    session, on_gpu = entry
    try:
        return session.run(None, feeds)
    except Exception:
        if not on_gpu:
            raise
        with _lock:
            cpu = _make_session(key, False)
            _sessions[key] = (cpu, False)
        return cpu.run(None, feeds)
