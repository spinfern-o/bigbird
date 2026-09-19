"""Run AI jobs on a background thread with a progress dialog, downloading models first."""
import threading
import time

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtWidgets import QMessageBox, QProgressDialog

from . import cloud, models


class _Signals(QObject):
    progress = Signal(int, int)
    done = Signal(object)
    failed = Signal(str)


class _Job(QRunnable):
    def __init__(self, fn, signals):
        super().__init__()
        self.fn, self.signals = fn, signals

    def run(self):
        try:
            result = self.fn(lambda d, t: self.signals.progress.emit(d, t))
        except models.Cancelled:
            result = models.Cancelled
        except Exception as e:  # report every failure to the user instead of crashing
            try:
                self.signals.failed.emit(f"{type(e).__name__}: {e}")
            except RuntimeError:
                pass
            return
        try:
            self.signals.done.emit(result)
        except RuntimeError:
            pass


def run_ai(parent, model_keys, title, busy_text, fn, on_done):
    """Download any missing models (with a cancellable progress bar), then run fn()
    in the background and call on_done(result) on the UI thread."""
    missing = [k for k in model_keys if not models.is_downloaded(k)]
    if missing:
        size = sum(models.MODELS[k].size_mb for k in missing)
        names = ", ".join(models.MODELS[k].name for k in missing)
        r = QMessageBox.question(
            parent, title,
            f"This feature uses the free AI model {names} ({size} MB).\n\n"
            "It downloads once, then runs on your computer. Your photos never leave "
            "your PC.\n\nDownload it now?")
        if r != QMessageBox.Yes:
            return
        _download_then(parent, missing, title,
                       lambda: _run(parent, title, busy_text, fn, on_done))
    else:
        _run(parent, title, busy_text, fn, on_done)


def _download_then(parent, keys, title, then):
    dlg = QProgressDialog("Downloading AI model…", "Cancel", 0, 1000, parent)
    dlg.setWindowTitle(title)
    dlg.setWindowModality(Qt.WindowModal)
    dlg.setMinimumDuration(0)
    dlg.setAutoClose(False)
    dlg.setAutoReset(False)
    cancel = threading.Event()
    dlg.canceled.connect(cancel.set)
    sig = _Signals(parent)
    start = time.monotonic()

    def work(_):
        for k in keys:
            models.download(k, lambda d, t, k=k: sig.progress.emit(d, t), cancel)
        return True

    def progress(d, t):
        mb, total = d / 1e6, t / 1e6
        rate = mb / max(0.1, time.monotonic() - start)
        dlg.setLabelText(f"Downloading AI model…\n{mb:.0f} of {total:.0f} MB  ({rate:.1f} MB/s)")
        dlg.setValue(int(1000 * d / max(1, t)))

    def done(result):
        dlg.close()
        if result is not models.Cancelled:
            then()

    def failed(msg):
        dlg.close()
        QMessageBox.warning(parent, title, "The download didn't finish. Check your internet "
                            f"connection and try again.\n\n{msg}")

    sig.progress.connect(progress)
    sig.done.connect(done)
    sig.failed.connect(failed)
    dlg.show()
    QThreadPool.globalInstance().start(_Job(work, sig))


def _run(parent, title, busy_text, fn, on_done):
    place = cloud.where() or ("your " + models.device_name())
    dlg = QProgressDialog(busy_text + "\n(running on " + place + ")",
                          None, 0, 0, parent)
    dlg.setWindowTitle(title)
    dlg.setWindowModality(Qt.WindowModal)
    dlg.setMinimumDuration(0)
    dlg.setCancelButton(None)
    sig = _Signals(parent)

    def done(result):
        dlg.close()
        on_done(result)

    def failed(msg):
        dlg.close()
        QMessageBox.warning(parent, title, f"Sorry, that didn't work.\n\n{msg}")

    sig.done.connect(done)
    sig.failed.connect(failed)
    dlg.show()
    QThreadPool.globalInstance().start(_Job(lambda _p: fn(), sig))
