"""Local adjustments: Lightroom-style Graduated and Radial filters.

A local adjustment is a plain dict living in the document's develop settings under
"locals", so it is undoable and saves into projects like any other setting:

    {"type": "linear", "x1": .., "y1": .., "x2": .., "y2": ..,     # 0..1 of the canvas
     "feather": 0-100, "invert": False, "settings": {"exposure": 60, ...}}
    {"type": "radial", "x1": .., "y1": .., "rx": .., "ry": .., ...}

Coordinates are fractions of the canvas, so the same filter lands in the same place
on the small preview render and on the full-resolution export.

Everything here treats those dicts as immutable: edits build new dicts, because undo
snapshots share the settings dictionary.
"""
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import QGraphicsItem

KEY = "locals"

# The sliders that make sense inside a local adjustment (a subset of the global ones).
LOCAL_KEYS = ["exposure", "contrast", "highlights", "shadows", "whites", "blacks",
              "temperature", "tint", "vibrance", "saturation", "clarity", "dehaze",
              "sharpness"]

LABELS = {"linear": "Graduated filter", "radial": "Radial filter"}
HANDLE = 14.0          # how close (in pixels on screen) counts as grabbing a handle


def new_local(kind, x1, y1, x2, y2):
    """Build a local adjustment from the drag the user just made."""
    if kind == "linear":
        loc = {"type": "linear", "x1": x1, "y1": y1, "x2": x2, "y2": y2, "feather": 100}
    else:
        loc = {"type": "radial", "x1": x1, "y1": y1,
               "rx": max(0.02, abs(x2 - x1)), "ry": max(0.02, abs(y2 - y1)), "feather": 60}
    loc["invert"] = False
    loc["settings"] = {}
    return loc


def normalize(locals_):
    """Coerce whatever came out of a saved project into clean dicts."""
    out = []
    for loc in locals_ or ():
        if not isinstance(loc, dict) or loc.get("type") not in LABELS:
            continue
        clean = {"type": loc["type"], "feather": int(loc.get("feather", 100)),
                 "invert": bool(loc.get("invert", False))}
        for k in ("x1", "y1", "x2", "y2", "rx", "ry"):
            if k in loc:
                clean[k] = float(loc[k])
        settings = loc.get("settings") or {}
        clean["settings"] = {k: int(v) for k, v in settings.items()
                             if k in LOCAL_KEYS and int(v) != 0}
        out.append(clean)
    return tuple(out)


def is_active(loc):
    return bool(loc.get("settings"))


def replaced(settings, index, new_loc):
    """A copy of `settings` with local adjustment `index` replaced (or removed if None)."""
    locs = list(settings.get(KEY, ()))
    if not 0 <= index < len(locs):
        return dict(settings)
    if new_loc is None:
        del locs[index]
    else:
        locs[index] = new_loc
    out = dict(settings)
    out[KEY] = tuple(locs)
    return out


def with_added(settings, loc):
    out = dict(settings)
    out[KEY] = tuple(settings.get(KEY, ())) + (loc,)
    return out


def edited(loc, **changes):
    """A copy of one local adjustment with some fields changed."""
    out = dict(loc)
    out["settings"] = dict(loc.get("settings") or {})
    for k, v in changes.items():
        if k == "settings":
            out["settings"] = dict(v)
        else:
            out[k] = v
    return out


def _smoothstep(e0, e1, x):
    t = np.clip((x - e0) / max(1e-6, e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def mask(loc, h, w):
    """The float32 0..1 strength map for one local adjustment at this image size."""
    xs = np.arange(w, dtype=np.float32)
    ys = np.arange(h, dtype=np.float32)
    if loc["type"] == "linear":
        x1, y1 = loc["x1"] * w, loc["y1"] * h
        dx, dy = loc["x2"] * w - x1, loc["y2"] * h - y1
        length = dx * dx + dy * dy
        if length < 1e-6:
            m = np.ones((h, w), np.float32)
        else:
            t = ((xs[None, :] - x1) * dx + (ys[:, None] - y1) * dy) / length
            band = max(0.02, loc.get("feather", 100) / 100.0)
            m = 1.0 - _smoothstep(0.0, 1.0, np.clip((t - 0.5) / band + 0.5, 0.0, 1.0))
    else:
        cx, cy = loc["x1"] * w, loc["y1"] * h
        rx, ry = max(1e-3, loc.get("rx", 0.2)) * w, max(1e-3, loc.get("ry", 0.2)) * h
        d = np.sqrt(((xs[None, :] - cx) / rx) ** 2 + ((ys[:, None] - cy) / ry) ** 2)
        inner = 1.0 - max(0.02, loc.get("feather", 60) / 100.0)
        m = 1.0 - _smoothstep(inner, 1.0, d)
    if loc.get("invert"):
        m = 1.0 - m
    return m.astype(np.float32)


def describe(loc, index):
    """The name shown in the list, e.g. "Radial filter 2 — Exposure, Clarity"."""
    from . import adjustments
    name = f"{LABELS[loc['type']]} {index + 1}"
    edits = [adjustments.setting_label(k) for k, v in (loc.get("settings") or {}).items() if v]
    return f"{name} — {', '.join(edits)}" if edits else f"{name} — no changes yet"


class _Overlay(QGraphicsItem):
    """Draws every local adjustment on the canvas, with the selected one highlighted."""

    def __init__(self, tool):
        super().__init__()
        self.tool = tool
        self.setZValue(15)

    def boundingRect(self):
        return QRectF(-1e5, -1e5, 2e5, 2e5)

    def paint(self, p, option, widget=None):
        z = max(1e-6, p.transform().m11())
        w, h = self.tool.doc_w, self.tool.doc_h
        for i, loc in enumerate(self.tool.locals()):
            on = i == self.tool.index
            color = QColor(255, 220, 60) if on else QColor(210, 210, 220, 150)
            pen = QPen(color)
            pen.setCosmetic(True)
            pen.setWidthF(2.0 if on else 1.2)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            if loc["type"] == "linear":
                x1, y1 = loc["x1"] * w, loc["y1"] * h
                x2, y2 = loc["x2"] * w, loc["y2"] * h
                dx, dy = x2 - x1, y2 - y1
                n = (dy, -dx)
                span = 4000 / z
                scale = span / max(1e-6, (n[0] ** 2 + n[1] ** 2) ** 0.5)
                for px, py, dashed in ((x1, y1, False), ((x1 + x2) / 2, (y1 + y2) / 2, True),
                                       (x2, y2, False)):
                    pen.setStyle(Qt.DashLine if dashed else Qt.SolidLine)
                    p.setPen(pen)
                    p.drawLine(QPointF(px - n[0] * scale, py - n[1] * scale),
                               QPointF(px + n[0] * scale, py + n[1] * scale))
                pen.setStyle(Qt.SolidLine)
                p.setPen(pen)
                p.setBrush(color)
                for px, py in ((x1, y1), (x2, y2)):
                    p.drawEllipse(QPointF(px, py), 5 / z, 5 / z)
            else:
                cx, cy = loc["x1"] * w, loc["y1"] * h
                rx, ry = loc.get("rx", 0.2) * w, loc.get("ry", 0.2) * h
                p.drawEllipse(QPointF(cx, cy), rx, ry)
                p.setBrush(color)
                p.drawEllipse(QPointF(cx, cy), 5 / z, 5 / z)
                p.setBrush(Qt.NoBrush)
                pen.setStyle(Qt.DashLine)
                p.setPen(pen)
                inner = 1.0 - max(0.02, loc.get("feather", 60) / 100.0)
                p.drawEllipse(QPointF(cx, cy), rx * inner, ry * inner)


class LocalTool:
    """Canvas tool for Graduated / Radial filters: drag to place, drag handles to adjust."""
    wants_right_click = False

    def __init__(self, canvas, doc_w, doc_h, kind, get_locals, changed, created, selected):
        self.canvas, self.doc_w, self.doc_h = canvas, doc_w, doc_h
        self.kind = kind
        self.locals = get_locals          # () -> tuple of local dicts
        self.changed = changed            # (index, loc, final) -> None
        self.created = created            # (loc) -> None
        self.selected = selected          # (index) -> None
        self.index = -1
        self.drag = None
        self.overlay = _Overlay(self)
        canvas.scene().addItem(self.overlay)

    # ------------------------------------------------------------------ helpers
    def remove(self):
        self.canvas.scene().removeItem(self.overlay)

    def refresh(self):
        self.overlay.update()

    def set_index(self, index):
        self.index = index
        self.overlay.update()

    def _norm(self, pos):
        return (float(np.clip(pos.x() / self.doc_w, 0, 1)),
                float(np.clip(pos.y() / self.doc_h, 0, 1)))

    def _near(self, pos, x, y):
        z = max(1e-6, self.canvas.zoom())
        return abs(pos.x() - x * self.doc_w) * z < HANDLE and \
            abs(pos.y() - y * self.doc_h) * z < HANDLE

    def _hit(self, pos):
        """(index, what) for the handle under the cursor, newest filters first."""
        locs = self.locals()
        for i in range(len(locs) - 1, -1, -1):
            loc = locs[i]
            if loc["type"] == "linear":
                if self._near(pos, loc["x1"], loc["y1"]):
                    return i, "p1"
                if self._near(pos, loc["x2"], loc["y2"]):
                    return i, "p2"
            else:
                if self._near(pos, loc["x1"], loc["y1"]):
                    return i, "center"
                if self._near(pos, loc["x1"] + loc.get("rx", 0.2), loc["y1"]) or \
                        self._near(pos, loc["x1"], loc["y1"] + loc.get("ry", 0.2)):
                    return i, "edge"
        return -1, None

    # ------------------------------------------------------------------ mouse
    def press(self, pos, button, modifiers=Qt.NoModifier):
        if button != Qt.LeftButton:
            return
        index, what = self._hit(pos)
        if index >= 0:
            self.selected(index)
            self.drag = (index, what, self._norm(pos), dict(self.locals()[index]))
            return
        x, y = self._norm(pos)
        loc = new_local(self.kind, x, y, x, y)
        self.created(loc)
        self.drag = (len(self.locals()) - 1, "new", (x, y), dict(loc))

    def move(self, pos):
        if self.drag is None:
            return
        index, what, start, orig = self.drag
        x, y = self._norm(pos)
        loc = None
        if what == "new":
            loc = dict(orig)
            if loc["type"] == "linear":
                loc.update(x1=start[0], y1=start[1], x2=x, y2=y)
            else:
                loc.update(rx=max(0.02, abs(x - start[0])), ry=max(0.02, abs(y - start[1])))
        elif what in ("p1", "p2"):
            loc = dict(orig)
            loc["x" + what[1]], loc["y" + what[1]] = x, y
        elif what == "center":
            loc = dict(orig)
            loc.update(x1=x, y1=y)
        elif what == "edge":
            loc = dict(orig)
            loc.update(rx=max(0.02, abs(x - orig["x1"])), ry=max(0.02, abs(y - orig["y1"])))
        if loc is not None:
            self.changed(index, loc, False)
            self.overlay.update()

    def release(self):
        if self.drag is not None:
            index = self.drag[0]
            self.drag = None
            locs = self.locals()
            if 0 <= index < len(locs):
                self.changed(index, dict(locs[index]), True)
        self.overlay.update()

    def double_click(self):
        pass

    def undo(self):
        return False

    def has_shape(self):
        return bool(self.locals())

    def key(self, key):
        if key in (Qt.Key_Delete, Qt.Key_Backspace) and self.index >= 0:
            self.changed(self.index, None, True)
            return True
        return False
