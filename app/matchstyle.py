"""Match Style: copy the look of a reference photo onto the current one.

The classic trick is per-channel histogram matching — reshape the Red, Green and
Blue tones of this photo until they are distributed like the reference's. Instead of
baking new pixels, PhotoForge fits that mapping onto the three Tone Curves and the
Saturation slider, so the result is ordinary, editable develop settings: the user can
see exactly what changed, dial it back, or keep tweaking by hand.
"""
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout,
                               QLabel, QVBoxLayout)

from . import adjustments, curves, imageio

CURVE_KEYS = ("curve_r", "curve_g", "curve_b")
MAX_SAMPLE = 360        # longest edge used for the statistics; plenty, and fast


def _sample(rgba):
    """Opaque pixels of a small copy of the image, as an (N, 3) uint8 array."""
    h, w = rgba.shape[:2]
    f = min(1.0, MAX_SAMPLE / max(1, max(w, h)))
    small = imageio.resize(rgba, max(1, int(w * f)), max(1, int(h * f)), fast=True) \
        if f < 1.0 else rgba
    flat = small.reshape(-1, small.shape[-1])
    if flat.shape[1] == 4:
        flat = flat[flat[:, 3] > 16][:, :3]
    return np.ascontiguousarray(flat)


def _mapping(src, ref):
    """256-entry level mapping that gives `src` the same distribution as `ref`."""
    sh = np.bincount(src, minlength=256).astype(np.float64)
    rh = np.bincount(ref, minlength=256).astype(np.float64)
    s_cdf = np.cumsum(sh) / max(1.0, sh.sum())
    r_cdf = np.cumsum(rh) / max(1.0, rh.sum())
    m = np.interp(s_cdf, r_cdf, np.arange(256, dtype=np.float64))
    # A histogram match can be spiky where the source has few pixels; smoothing keeps
    # the fitted curve gentle, which is what makes it look like a grade and not a glitch.
    k = np.ones(9) / 9.0
    m = np.convolve(np.pad(m, 4, mode="edge"), k, mode="valid")
    return np.maximum.accumulate(np.clip(m, 0, 255))


def _saturation(rgb):
    a = rgb.astype(np.float32)
    mx, mn = a.max(axis=1), a.min(axis=1)
    return float((np.divide(mx - mn, np.maximum(mx, 1e-6))).mean())


def match_settings(src_rgba, ref_rgba, base, strength=100, match_color=True):
    """Return develop settings that give `src_rgba` the look of `ref_rgba`.

    `base` is the document's current settings; everything in it is preserved except
    the three per-channel curves and Saturation, which this replaces. `strength`
    (0-100) blends the whole effect back towards the photo as it is now.
    """
    src, ref = _sample(src_rgba), _sample(ref_rgba)
    out = dict(base)
    out["curve_rgb"] = ()
    for key in CURVE_KEYS:
        out[key] = ()
    if src.size == 0 or ref.size == 0:
        return out
    k = max(0.0, min(100.0, float(strength))) / 100.0
    identity = np.arange(256, dtype=np.float64)

    if not match_color:
        # Tone only: one shared mapping built from brightness, on the master curve.
        lum = lambda a: (a * (0.2126, 0.7152, 0.0722)).sum(1).round().astype(np.uint8)  # noqa: E731
        m = identity + (_mapping(lum(src), lum(ref)) - identity) * k
        out["curve_rgb"] = curves.from_mapping(m)
        return out

    mapped = np.empty_like(src)
    for ch, key in enumerate(CURVE_KEYS):
        blended = identity + (_mapping(src[:, ch], ref[:, ch]) - identity) * k
        out[key] = curves.from_mapping(blended)
        mapped[:, ch] = np.clip(blended, 0, 255).astype(np.uint8)[src[:, ch]]

    # Whatever colour intensity the curves did not carry over, ask the Saturation
    # slider for — the pipeline scales chroma by (1 + saturation/100).
    have, want = _saturation(mapped), _saturation(ref)
    if have > 0.01:
        delta = int(round(np.clip((want / have - 1.0) * 100.0 * k, -60, 60)))
        out["saturation"] = int(np.clip(base.get("saturation", 0) + delta, -100, 100))
    return out


def changes(base, new):
    """A short plain-English summary of what Match Style changed."""
    bits = []
    for key, label in zip(CURVE_KEYS, ("Red", "Green", "Blue")):
        if not curves.is_identity(new.get(key, ())):
            bits.append(label)
    parts = []
    if bits:
        parts.append("Tone Curve: " + ", ".join(bits))
    if not curves.is_identity(new.get("curve_rgb", ())):
        parts.append("Tone Curve: RGB")
    if new.get("saturation", 0) != base.get("saturation", 0):
        parts.append(f"Saturation {new['saturation']:+d}")
    return " · ".join(parts) or "nothing to copy — the photos already look alike"


class MatchStyleDialog(QDialog):
    """Preview the reference look, with a Strength slider, before applying it."""

    def __init__(self, parent, preview_rgba, ref_rgba, base):
        super().__init__(parent)
        from .panels import NoWheelSlider      # imported here to avoid a circular import

        self.setWindowTitle("Match Style from a Photo")
        self.preview_rgba, self.ref_rgba, self.base = preview_rgba, ref_rgba, dict(base)
        # The curves are what Match Style writes, so the statistics have to come from the
        # photo as it looks *before* the curve stage — i.e. the current settings minus curves.
        self.base_nc = dict(base)
        self.base_nc.update({k: () for k in curves.DEFAULTS})
        self.base_nc.update(curve_lights=0, curve_darks=0)
        self.src_img = adjustments.apply(preview_rgba, self.base_nc)
        self.settings = dict(base)
        lay = QVBoxLayout(self)
        intro = QLabel("PhotoForge copied the colours and tone of your reference photo onto this "
                       "one. Drag Strength down for a gentler version. Everything it does lands "
                       "on the Tone Curve and Saturation, so you can keep editing afterwards.")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        grid = QGridLayout()
        self.before_lbl = QLabel()
        self.after_lbl = QLabel()
        self.ref_lbl = QLabel()
        for col, (title, widget) in enumerate((("This photo now", self.before_lbl),
                                               ("With the new look", self.after_lbl),
                                               ("Reference photo", self.ref_lbl))):
            cap = QLabel(title)
            cap.setAlignment(Qt.AlignHCenter)
            cap.setObjectName("hintLabel")
            widget.setAlignment(Qt.AlignCenter)
            widget.setMinimumSize(210, 150)
            grid.addWidget(widget, 0, col)
            grid.addWidget(cap, 1, col)
        lay.addLayout(grid)

        row = QHBoxLayout()
        row.addWidget(QLabel("Strength"))
        self.strength = NoWheelSlider(Qt.Horizontal)
        self.strength.setRange(0, 100)
        self.strength.setValue(80)
        self.strength.setToolTip("100 matches the reference as closely as possible; lower values "
                                 "keep more of your photo's own look.")
        row.addWidget(self.strength, 1)
        self.strength_lbl = QLabel("80%")
        self.strength_lbl.setMinimumWidth(42)
        row.addWidget(self.strength_lbl)
        lay.addLayout(row)

        self.colors = QCheckBox("Match colours too (uncheck to copy only brightness and contrast)")
        self.colors.setChecked(True)
        lay.addWidget(self.colors)
        self.summary = QLabel()
        self.summary.setObjectName("hintLabel")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Apply Look")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        self.strength.valueChanged.connect(self._recompute)
        self.colors.toggled.connect(self._recompute)
        self._show(self.before_lbl, adjustments.apply(preview_rgba, base))
        self._show(self.ref_lbl, ref_rgba)
        self._recompute()

    @staticmethod
    def _show(label, rgba):
        thumb = imageio.thumbnail(rgba, 200)
        label.setPixmap(QPixmap.fromImage(imageio.to_qimage(thumb)))

    def _recompute(self):
        self.strength_lbl.setText(f"{self.strength.value()}%")
        self.settings = match_settings(self.src_img, self.ref_rgba, self.base_nc,
                                       self.strength.value(), self.colors.isChecked())
        self._show(self.after_lbl, adjustments.apply(self.preview_rgba, self.settings))
        self.summary.setText("Changed: " + changes(self.base, self.settings))
