"""Turns a Document into what's shown on the canvas.

While sliders move we render a small proxy (fast); once things settle, a
full-resolution render runs on a background thread and replaces it.
"""
import numpy as np
from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

from . import adjustments, imageio

PROXY_MAX = 1280


class _JobSignals(QObject):
    done = Signal(int, object)


class _HiResJob(QRunnable):
    def __init__(self, gen, comp, settings, signals):
        super().__init__()
        self.gen, self.comp, self.settings, self.signals = gen, comp, settings, signals

    def run(self):
        out = adjustments.apply(self.comp, self.settings, 1.0)
        try:
            self.signals.done.emit(self.gen, imageio.to_qimage(out))
        except RuntimeError:  # app closed while rendering
            pass


class Renderer(QObject):
    histogramReady = Signal(object)   # (4, 256) array: R, G, B, luminance
    proxyReady = Signal()             # new proxy base (e.g. for preset thumbnails)

    def __init__(self, canvas):
        super().__init__()
        self.canvas = canvas
        self.doc = None
        self.comp = None
        self.proxy = None
        self.show_original = False
        self.exclude = None
        self._gen = 0
        self._signals = _JobSignals()
        self._signals.done.connect(self._hi_done)
        self._hi_timer = QTimer(self, singleShot=True, interval=250)
        self._hi_timer.timeout.connect(self._start_hi)
        # Coalesces rapid slider moves: only the latest value gets rendered.
        self._update_timer = QTimer(self, singleShot=True, interval=0)
        self._update_timer.timeout.connect(self.update)

    def set_document(self, doc):
        self.doc = doc
        self.comp = self.proxy = None
        self._gen += 1
        if doc:
            self.invalidate()

    def invalidate(self):
        """Layers changed: recomposite, then redraw."""
        if not self.doc:
            return
        self.comp = self.doc.composite(self.exclude)
        h, w = self.comp.shape[:2]
        f = min(1.0, PROXY_MAX / max(w, h))
        if f < 1.0:
            self.proxy = imageio.resize(self.comp, max(1, int(w * f)), max(1, int(h * f)), fast=True)
        else:
            self.proxy = self.comp
        self.proxyReady.emit()
        self.update()

    def request_update(self):
        self._update_timer.start()

    def update(self):
        """Adjustments changed: redraw from the cached composite."""
        if not self.doc or self.comp is None:
            return
        self._gen += 1
        self._hi_timer.stop()
        s = self.doc.adjust
        if self.show_original or adjustments.is_default(s):
            self._show(self.comp)
            self._histogram(self.proxy)
            return
        scale = self.proxy.shape[1] / self.comp.shape[1]
        out = adjustments.apply(self.proxy, s, scale)
        self._show(out)
        self._histogram(out)
        if self.proxy is not self.comp:
            self._hi_timer.start()

    def _show(self, arr):
        self.canvas.set_display(imageio.to_qimage(arr), self.doc.width, self.doc.height)

    def _start_hi(self):
        QThreadPool.globalInstance().start(
            _HiResJob(self._gen, self.comp, dict(self.doc.adjust), self._signals))

    def _hi_done(self, gen, qimg):
        if gen == self._gen and self.doc:
            self.canvas.set_display(qimg, self.doc.width, self.doc.height)

    def _histogram(self, arr):
        a = arr[::2, ::2]
        mask = a[..., 3] > 0
        rgb = a[..., :3][mask]
        if rgb.size == 0:
            self.histogramReady.emit(np.zeros((4, 256)))
            return
        lum = (rgb[:, 0] * 0.2126 + rgb[:, 1] * 0.7152 + rgb[:, 2] * 0.0722).astype(np.uint8)
        hist = np.stack([np.bincount(rgb[:, 0], minlength=256),
                         np.bincount(rgb[:, 1], minlength=256),
                         np.bincount(rgb[:, 2], minlength=256),
                         np.bincount(lum, minlength=256)]).astype(np.float32)
        self.histogramReady.emit(hist)
