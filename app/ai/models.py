"""Registry of approved AI models, plus downloading and loading them.

Only models whose license allows commercial use belong here (see ROADMAP.txt).
Models download on first use into %LOCALAPPDATA%\\PhotoForge\\models.
"""
import os
import threading
import urllib.request
from dataclasses import dataclass

_SAM = "https://huggingface.co/onnx-community/sam2.1-hiera-tiny-ONNX/resolve/main/onnx/"


@dataclass(frozen=True)
class ModelInfo:
    key: str
    name: str
    purpose: str
    files: tuple      # ((url, path relative to the models folder), ...)
    size_mb: int
    license: str
    homepage: str
    gpu: bool         # False = known not to work with DirectML, always use CPU


MODELS = {
    "birefnet_lite": ModelInfo(
        "birefnet_lite", "BiRefNet-lite", "Remove Background",
        (("https://huggingface.co/onnx-community/BiRefNet_lite-ONNX/resolve/main/onnx/model.onnx",
          "birefnet_lite.onnx"),),
        224, "MIT", "https://github.com/ZhengPeng7/BiRefNet", gpu=True),
    "sam2": ModelInfo(
        "sam2", "SAM 2.1 Tiny", "Select objects (click to select)",
        ((_SAM + "vision_encoder.onnx", "sam2.1_tiny/vision_encoder.onnx"),
         (_SAM + "vision_encoder.onnx_data", "sam2.1_tiny/vision_encoder.onnx_data"),
         (_SAM + "prompt_encoder_mask_decoder.onnx", "sam2.1_tiny/prompt_encoder_mask_decoder.onnx"),
         (_SAM + "prompt_encoder_mask_decoder.onnx_data",
          "sam2.1_tiny/prompt_encoder_mask_decoder.onnx_data")),
        155, "Apache 2.0", "https://github.com/facebookresearch/sam2", gpu=True),
}


class Cancelled(Exception):
    pass


def models_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "PhotoForge", "models")
    os.makedirs(d, exist_ok=True)
    return d


def _path(rel):
    return os.path.join(models_dir(), *rel.split("/"))


def is_downloaded(key):
    return all(os.path.isfile(_path(rel)) for _, rel in MODELS[key].files)


def download(key, progress=None, cancel_event=None):
    """Download a model's files. progress(done_bytes, total_bytes) is called as data arrives."""
    info = MODELS[key]
    total = info.size_mb * 1_000_000
    done = 0
    for url, rel in info.files:
        dest = _path(rel)
        if os.path.isfile(dest):
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        tmp = dest + ".part"
        req = urllib.request.Request(url, headers={"User-Agent": "PhotoForge"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r, open(tmp, "wb") as f:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise Cancelled()
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, max(total, done))
            os.replace(tmp, dest)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)


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


def _make_session(rel, use_gpu):
    import onnxruntime as ort
    opts = ort.SessionOptions()
    providers = ["CPUExecutionProvider"]
    if use_gpu:
        providers.insert(0, "DmlExecutionProvider")
        opts.enable_mem_pattern = False  # required by DirectML
        opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    return ort.InferenceSession(_path(rel), sess_options=opts, providers=providers)


def run(key, feeds, part=None, gpu=True):
    """Run a model (or one `part` file of it), preferring the GPU unless gpu=False.
    Falls back to the CPU if the GPU path fails."""
    info = MODELS[key]
    rel = next(r for _, r in info.files if r.endswith(".onnx") and (part is None or part in r))
    with _lock:
        entry = _sessions.get(rel)
        if entry is None:
            use_gpu = gpu and info.gpu and gpu_available()
            try:
                entry = (_make_session(rel, use_gpu), use_gpu)
            except Exception:
                if not use_gpu:
                    raise
                entry = (_make_session(rel, False), False)
            _sessions[rel] = entry
    session, on_gpu = entry
    try:
        return session.run(None, feeds)
    except Exception:
        if not on_gpu:
            raise
        with _lock:
            cpu = _make_session(rel, False)
            _sessions[rel] = (cpu, False)
        return cpu.run(None, feeds)
