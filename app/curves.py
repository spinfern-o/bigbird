"""Tone Curve: the curve maths and the draggable curve widget.

A curve is stored in the document's develop settings as a tuple of (x, y) control
points, each 0-255, e.g. ((0, 0), (128, 160), (255, 255)). An empty tuple means
"untouched" (a straight line), which keeps `adjustments.is_default` simple and
makes projects saved before curves existed load unchanged.
"""
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

# (settings key, label, line color drawn in the widget)
CHANNELS = [
    ("curve_rgb", "RGB", "#e8e8ee"),
    ("curve_r", "Red", "#e0463c"),
    ("curve_g", "Green", "#46a94f"),
    ("curve_b", "Blue", "#3d6fd6"),
]
KEYS = [c[0] for c in CHANNELS]
DEFAULTS = {k: () for k in KEYS}

# The beginner-friendly region sliders that ride on top of the curve.
REGION_SLIDERS = [
    ("Tone Curve", "curve_lights", "Lights", -100, 100,
     "Brightens or darkens the brighter half of the photo, leaving the darks alone."),
    ("Tone Curve", "curve_darks", "Darks", -100, 100,
     "Brightens or darkens the darker half of the photo, leaving the brights alone."),
]

_X = np.arange(256, dtype=np.float32) / 255.0


def normalize(points):
    """Coerce loaded JSON (lists of lists) into a clean, sorted tuple of int pairs."""
    if not points:
        return ()
    out = []
    for p in points:
        try:
            x, y = int(round(float(p[0]))), int(round(float(p[1])))
        except (TypeError, ValueError, IndexError):
            continue
        out.append((max(0, min(255, x)), max(0, min(255, y))))
    out.sort(key=lambda p: p[0])
    return tuple(out)


def is_identity(points):
    """True when these control points describe a straight line (no change)."""
    pts = normalize(points)
    return not pts or all(x == y for x, y in pts)


def _monotone(xs, ys, x):
    """Monotone cubic (Fritsch-Carlson) interpolation: smooth, and it never overshoots.

    Plain splines can bulge past the control points and clip highlights the user
    never asked to clip, which is why photo curves use the monotone variant.
    """
    n = len(xs)
    if n == 1:
        return np.full_like(x, ys[0])
    h = np.diff(xs)
    h[h == 0] = 1e-6
    delta = np.diff(ys) / h
    m = np.empty(n, np.float32)
    m[0], m[-1] = delta[0], delta[-1]
    if n > 2:
        m[1:-1] = (delta[:-1] + delta[1:]) * 0.5
    for i in range(n - 1):
        if delta[i] == 0:
            m[i] = m[i + 1] = 0.0
        else:
            a, b = m[i] / delta[i], m[i + 1] / delta[i]
            s = a * a + b * b
            if s > 9.0:                       # keep the segment monotone
                t = 3.0 / np.sqrt(s)
                m[i], m[i + 1] = t * a * delta[i], t * b * delta[i]
    idx = np.clip(np.searchsorted(xs, x) - 1, 0, n - 2)
    x0, x1 = xs[idx], xs[idx + 1]
    y0, y1 = ys[idx], ys[idx + 1]
    hh = x1 - x0
    t = (x - x0) / hh
    t2, t3 = t * t, t * t * t
    return ((2 * t3 - 3 * t2 + 1) * y0 + (t3 - 2 * t2 + t) * hh * m[idx]
            + (-2 * t3 + 3 * t2) * y1 + (t3 - t2) * hh * m[idx + 1])


def _bell(x, center, width):
    return np.exp(-(((x - center) / width) ** 2)).astype(np.float32)


def curve_lut(points, lights=0, darks=0):
    """A 256-entry float32 lookup table (input 0-255 -> output 0..1), or None for identity."""
    pts = normalize(points)
    straight = is_identity(pts)
    if straight and not lights and not darks:
        return None
    y = _X.copy()
    if not straight:
        xs = np.array([p[0] for p in pts], np.float32) / 255.0
        ys = np.array([p[1] for p in pts], np.float32) / 255.0
        # Values outside the first/last control point keep their own shape, shifted by
        # the nearest point, so dragging an end point moves that end of the range too.
        y = _monotone(xs, ys, np.clip(_X, xs[0], xs[-1]))
        y = y + np.where(_X < xs[0], _X - xs[0], 0) + np.where(_X > xs[-1], _X - xs[-1], 0)
    if lights:
        y = y + (lights / 100.0) * 0.25 * _bell(_X, 0.70, 0.26)
    if darks:
        y = y + (darks / 100.0) * 0.25 * _bell(_X, 0.28, 0.24)
    return np.clip(y, 0.0, 1.0).astype(np.float32)


def apply_curves(rgb, s):
    """Apply the RGB + per-channel curves in settings `s` to a float 0..1 image."""
    master = curve_lut(s.get("curve_rgb", ()), s.get("curve_lights", 0), s.get("curve_darks", 0))
    per = [curve_lut(s.get(k, ())) for k in ("curve_r", "curve_g", "curve_b")]
    if master is None and all(p is None for p in per):
        return rgb
    # The lookup tables are indexed 0-255, so this quantises the input a little, but it
    # turns the whole stage into one array lookup per channel instead of per-pixel maths.
    idx = np.clip(rgb * 255.0 + 0.5, 0, 255).astype(np.uint8)
    out = np.empty_like(rgb)
    for ch in range(3):
        lut = master
        if per[ch] is not None:
            lut = per[ch] if master is None else \
                master[np.clip(per[ch] * 255.0 + 0.5, 0, 255).astype(np.uint8)]
        out[..., ch] = rgb[..., ch] if lut is None else lut[idx[..., ch]]
    return out


def from_mapping(mapping, max_points=7, tolerance=2.0):
    """Fit a few control points to a 256-entry 0..255 mapping (used by Match Style).

    Starts with the two end points and keeps adding the input level where the curve
    is furthest from the target, so the result is the smallest curve that still
    matches — and few enough points that it stays easy to edit by hand afterwards.
    """
    target = np.maximum.accumulate(np.clip(np.asarray(mapping, np.float32), 0, 255))
    pts = [(0, int(round(target[0]))), (255, int(round(target[255])))]
    for _ in range(max_points - 2):
        lut = curve_lut(tuple(pts))
        have = _X * 255.0 if lut is None else lut * 255.0
        err = np.abs(have - target)
        err[[p[0] for p in pts]] = 0
        x = int(err.argmax())
        if err[x] <= tolerance or any(abs(px - x) < 8 for px, _ in pts):
            break
        pts.append((x, int(round(target[x]))))
        pts.sort()
    return normalize(pts)


class CurveEditor(QWidget):
    """A draggable tone curve. Click the line to add a point, right-click one to delete it."""
    curveChanged = Signal(str, object)     # (settings key, points tuple)
    hint = Signal(str)

    MARGIN = 8

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(230)
        self.setMouseTracking(True)
        self.channel = 0
        self.points = {k: () for k in KEYS}
        self.hist = None
        self._drag = None
        self.setToolTip(
            "Tone Curve: the line maps the photo's current brightness (left to right) to a new\n"
            "brightness (bottom to top). Drag it up to brighten, down to darken.\n\n"
            "Click the line to add a point · drag a point to bend the curve ·\n"
            "right-click or double-click a point to delete it.")

    # ---------------------------------------------------------------- data
    def key(self):
        return KEYS[self.channel]

    def set_channel(self, index):
        self.channel = index
        self.update()
        name = CHANNELS[index][1]
        self.hint.emit("Tone Curve: editing overall brightness. Drag the line up to brighten."
                       if index == 0 else
                       f"Tone Curve: editing the {name} channel only — this shifts the colour of "
                       f"the photo. Lifting the left end fades the photo with {name.lower()}.")

    def sync(self, settings):
        for k in KEYS:
            self.points[k] = normalize(settings.get(k, ()))
        self.update()

    def set_histogram(self, hist):
        """hist: the (4, 256) array from the renderer, drawn faintly behind the curve."""
        self.hist = hist
        self.update()

    def _current(self):
        pts = self.points[self.key()]
        return list(pts) if pts else [(0, 0), (255, 255)]

    def _commit(self, pts):
        pts = normalize(pts)
        if len(pts) == 2 and pts[0] == (0, 0) and pts[1] == (255, 255):
            pts = ()                       # back to a straight line
        self.points[self.key()] = pts
        self.curveChanged.emit(self.key(), pts)
        self.update()

    def reset_channel(self):
        self._commit([(0, 0), (255, 255)])

    # ---------------------------------------------------------------- geometry
    def _plot(self):
        m = self.MARGIN
        side = min(self.width() - 2 * m, self.height() - 2 * m)
        return QRectF(m, self.height() - m - side, side, side)

    def _to_widget(self, x, y):
        r = self._plot()
        return QPointF(r.left() + x / 255.0 * r.width(), r.bottom() - y / 255.0 * r.height())

    def _to_curve(self, pos):
        r = self._plot()
        x = (pos.x() - r.left()) / max(1.0, r.width()) * 255.0
        y = (r.bottom() - pos.y()) / max(1.0, r.height()) * 255.0
        return int(round(max(0, min(255, x)))), int(round(max(0, min(255, y))))

    def _hit(self, pos):
        for i, (x, y) in enumerate(self._current()):
            if (self._to_widget(x, y) - pos).manhattanLength() < 14:
                return i
        return None

    # ---------------------------------------------------------------- events
    def mousePressEvent(self, e):
        pts = self._current()
        i = self._hit(e.position())
        if e.button() == Qt.RightButton:
            if i is not None and 0 < i < len(pts) - 1:
                del pts[i]
                self._commit(pts)
            return
        if e.button() != Qt.LeftButton:
            return
        if i is None:
            if not self._plot().adjusted(-6, -6, 6, 6).contains(e.position()):
                return
            x, _ = self._to_curve(e.position())
            if any(abs(px - x) < 6 for px, _ in pts):
                return
            lut = curve_lut(self.points[self.key()])
            y = int(round((lut[x] if lut is not None else x / 255.0) * 255))
            pts.append((x, y))
            pts.sort()
            i = pts.index((x, y))
            self._commit(pts)
        self._drag = i

    def mouseMoveEvent(self, e):
        if self._drag is None:
            self.setCursor(Qt.PointingHandCursor if self._hit(e.position()) is not None
                           else Qt.CrossCursor)
            return
        pts = self._current()
        i = self._drag
        x, y = self._to_curve(e.position())
        if i == 0:
            x = 0
        elif i == len(pts) - 1:
            x = 255
        else:                               # keep the control points in order
            x = max(pts[i - 1][0] + 4, min(pts[i + 1][0] - 4, x))
        pts[i] = (x, y)
        self._commit(pts)

    def mouseReleaseEvent(self, e):
        self._drag = None

    def mouseDoubleClickEvent(self, e):
        pts = self._current()
        i = self._hit(e.position())
        if i is not None and 0 < i < len(pts) - 1:
            del pts[i]
            self._commit(pts)

    def leaveEvent(self, e):
        self.unsetCursor()

    # ---------------------------------------------------------------- painting
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self._plot()
        p.fillRect(r, QColor(24, 24, 26))

        if self.hist is not None:
            row = (3, 0, 1, 2)[self.channel]
            h = np.asarray(self.hist)[row]
            peak = max(1.0, float(np.percentile(h[2:254], 99.5)) * 1.1)
            path = QPainterPath()
            path.moveTo(r.left(), r.bottom())
            for i in range(256):
                path.lineTo(r.left() + i * r.width() / 255.0,
                            r.bottom() - min(1.0, h[i] / peak) * r.height() * 0.9)
            path.lineTo(r.right(), r.bottom())
            path.closeSubpath()
            p.fillPath(path, QColor(255, 255, 255, 28))

        p.setPen(QPen(QColor(255, 255, 255, 26), 1))
        for i in range(1, 4):
            x = r.left() + r.width() * i / 4
            y = r.top() + r.height() * i / 4
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
        p.setPen(QPen(QColor(255, 255, 255, 45), 1, Qt.DashLine))
        p.drawLine(r.bottomLeft(), r.topRight())
        p.setPen(QPen(QColor(90, 90, 96), 1))
        p.drawRect(r)

        color = QColor(CHANNELS[self.channel][2])
        lut = curve_lut(self.points[self.key()])
        path = QPainterPath()
        for i in range(256):
            y = (lut[i] * 255.0) if lut is not None else i
            pt = self._to_widget(i, y)
            path.moveTo(pt) if i == 0 else path.lineTo(pt)
        p.setPen(QPen(color, 2))
        p.drawPath(path)

        p.setPen(QPen(QColor(20, 20, 22), 1.5))
        p.setBrush(color)
        for x, y in self._current():
            p.drawEllipse(self._to_widget(x, y), 4.5, 4.5)
