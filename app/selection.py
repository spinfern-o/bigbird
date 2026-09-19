"""Selections: mask operations, marching ants, and the Marquee / Lasso / Magic Wand tools.

A selection is an HxW uint8 mask (255 = selected, soft values = partly selected), stored
on the Document. Tools build a mask and hand it to `commit(mask, mode, label)`, where mode
is "new", "add", "subtract" or "intersect".
"""
import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsItem

MODES = ("new", "add", "subtract", "intersect")


# --------------------------------------------------------------------------- mask operations

def combine(old, new, mode):
    if old is None or mode == "new":
        return new
    if mode == "add":
        return np.maximum(old, new)
    if mode == "subtract":
        return np.minimum(old, 255 - new)
    return np.minimum(old, new)  # intersect


def mode_from_modifiers(mods, default):
    """Photoshop shortcuts: Shift = add, Alt = subtract, Shift+Alt = intersect."""
    shift, alt = bool(mods & Qt.ShiftModifier), bool(mods & Qt.AltModifier)
    if shift and alt:
        return "intersect"
    if shift:
        return "add"
    if alt:
        return "subtract"
    return default


def polygon_mask(points, w, h, antialias=True):
    mask = np.zeros((h, w), np.uint8)
    if len(points) >= 3:
        pts = np.round(np.array(points, np.float64) * 16).astype(np.int32)
        cv2.fillPoly(mask, [pts], 255, cv2.LINE_AA if antialias else cv2.LINE_8, shift=4)
    return mask


def ellipse_mask(rect, w, h, antialias=True):
    mask = np.zeros((h, w), np.uint8)
    x0, y0, x1, y1 = rect
    center = (int(round((x0 + x1) / 2 * 16)), int(round((y0 + y1) / 2 * 16)))
    axes = (int(round(abs(x1 - x0) / 2 * 16)), int(round(abs(y1 - y0) / 2 * 16)))
    cv2.ellipse(mask, center, axes, 0, 0, 360, 255, -1,
                cv2.LINE_AA if antialias else cv2.LINE_8, shift=4)
    return mask


def rect_mask(rect, w, h):
    x0, y0, x1, y1 = rect
    mask = np.zeros((h, w), np.uint8)
    xa, xb = sorted((int(round(x0)), int(round(x1))))
    ya, yb = sorted((int(round(y0)), int(round(y1))))
    mask[max(0, ya):max(0, yb), max(0, xa):max(0, xb)] = 255
    return mask


def magic_wand(rgb, x, y, tolerance, contiguous=True, antialias=True):
    """Select pixels similar in color to (x, y). tolerance 0-255 per channel, like Photoshop."""
    h, w = rgb.shape[:2]
    x, y = int(np.clip(x, 0, w - 1)), int(np.clip(y, 0, h - 1))
    img = np.ascontiguousarray(rgb[..., :3])
    if contiguous:
        ff = np.zeros((h + 2, w + 2), np.uint8)
        t = (tolerance,) * 3
        cv2.floodFill(img.copy(), ff, (x, y), (0, 0, 0), t, t,
                      4 | cv2.FLOODFILL_FIXED_RANGE | cv2.FLOODFILL_MASK_ONLY | (255 << 8))
        mask = ff[1:-1, 1:-1]
    else:
        seed = img[y, x].astype(np.int16)
        mask = (np.abs(img.astype(np.int16) - seed).max(axis=2) <= tolerance).astype(np.uint8) * 255
    if antialias:
        mask = cv2.GaussianBlur(mask, (3, 3), 0.6)
    return mask


def feather(mask, radius):
    return mask if radius <= 0 else cv2.GaussianBlur(mask, (0, 0), radius / 2.0)


def _kernel(px):
    r = max(1, int(round(px)))
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))


def expand(mask, px):
    return cv2.dilate(mask, _kernel(px))


def contract(mask, px):
    return cv2.erode(mask, _kernel(px))


def smooth(mask, px):
    """Round off jagged corners and remove specks (like Select > Modify > Smooth)."""
    k = _kernel(px)
    m = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
    return cv2.morphologyEx(m, cv2.MORPH_CLOSE, k)


def border(mask, px):
    """A band of `px` width along the selection edge."""
    return cv2.subtract(cv2.dilate(mask, _kernel(px / 2)), cv2.erode(mask, _kernel(px / 2)))


def skin_tones(rgb):
    """Select skin-colored pixels (like Select > Color Range > Skin Tones)."""
    ycrcb = cv2.cvtColor(np.ascontiguousarray(rgb[..., :3]), cv2.COLOR_RGB2YCrCb)
    y, cr, cb = ycrcb[..., 0], ycrcb[..., 1].astype(np.int16), ycrcb[..., 2].astype(np.int16)
    m = ((cr >= 135) & (cr <= 180) & (cb >= 80) & (cb <= 135) & (y > 40)).astype(np.uint8) * 255
    m = smooth(m, 2)
    return cv2.GaussianBlur(m, (0, 0), 1.5)


def bbox(mask, pad=0):
    ys, xs = np.nonzero(mask > 0)
    if len(xs) == 0:
        return None
    h, w = mask.shape
    return (max(0, xs.min() - pad), max(0, ys.min() - pad),
            min(w, xs.max() + 1 + pad), min(h, ys.max() + 1 + pad))


def apply_masked(old, new, mask):
    """Blend `new` over `old` only where selected (keeps both RGB and alpha)."""
    if mask is None:
        return new
    m = (mask.astype(np.float32) / 255.0)[..., None]
    return np.clip(old.astype(np.float32) * (1 - m) + new.astype(np.float32) * m + 0.5,
                   0, 255).astype(np.uint8)


# --------------------------------------------------------------------------- marching ants

class MarchingAnts(QGraphicsItem):
    """Animated dashed outline around the current selection."""

    def __init__(self):
        super().__init__()
        self.setZValue(18)
        self.path = QPainterPath()
        self.offset = 0
        self.rect = QRectF()
        self.timer = QTimer()
        self.timer.setInterval(120)
        self.timer.timeout.connect(self._tick)

    def set_mask(self, mask):
        self.prepareGeometryChange()
        self.path = QPainterPath()
        if mask is not None:
            h, w = mask.shape
            f = min(1.0, 2000 / max(w, h))  # trace at a reduced size for speed
            small = mask if f == 1.0 else cv2.resize(mask, (max(1, int(w * f)), max(1, int(h * f))),
                                                     interpolation=cv2.INTER_AREA)
            contours, _ = cv2.findContours((small > 127).astype(np.uint8), cv2.RETR_LIST,
                                           cv2.CHAIN_APPROX_SIMPLE)
            for c in contours:
                pts = c.reshape(-1, 2).astype(np.float64) / f
                if len(pts) >= 2:
                    self.path.addPolygon(QPolygonF([QPointF(x, y) for x, y in pts]))
                    self.path.closeSubpath()
        self.rect = self.path.boundingRect().adjusted(-2, -2, 2, 2)
        if self.path.isEmpty():
            self.timer.stop()
        else:
            self.timer.start()
        self.update()

    def _tick(self):
        self.offset = (self.offset + 1) % 8
        self.update()

    def boundingRect(self):
        return self.rect

    def paint(self, painter, option, widget=None):
        if self.path.isEmpty():
            return
        pen = QPen(QColor(255, 255, 255), 1)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawPath(self.path)
        pen = QPen(QColor(0, 0, 0), 1, Qt.CustomDashLine)
        pen.setCosmetic(True)
        pen.setDashPattern([4, 4])
        pen.setDashOffset(self.offset)
        painter.setPen(pen)
        painter.drawPath(self.path)


# --------------------------------------------------------------------------- interactive tools

class _Preview(QGraphicsItem):
    """Draws the shape being made (lasso path or marquee) while the mouse is down."""

    def __init__(self):
        super().__init__()
        self.setZValue(19)
        self.points = []
        self.closed = False
        self.ellipse = False

    def boundingRect(self):
        if not self.points:
            return QRectF()
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return QRectF(min(xs) - 10, min(ys) - 10, max(xs) - min(xs) + 20, max(ys) - min(ys) + 20)

    def set(self, points, closed=False, ellipse=False):
        self.prepareGeometryChange()
        self.points, self.closed, self.ellipse = list(points), closed, ellipse
        self.update()

    def paint(self, painter, option, widget=None):
        if len(self.points) < 2:
            return
        painter.setRenderHint(QPainter.Antialiasing)
        for col, style in ((QColor(0, 0, 0), Qt.SolidLine), (QColor(255, 255, 255), Qt.DashLine)):
            pen = QPen(col, 1.2, style)
            pen.setCosmetic(True)
            painter.setPen(pen)
            if self.ellipse:
                (x0, y0), (x1, y1) = self.points[0], self.points[-1]
                painter.drawEllipse(QRectF(QPointF(x0, y0), QPointF(x1, y1)).normalized())
            else:
                poly = QPolygonF([QPointF(x, y) for x, y in self.points])
                painter.drawPolygon(poly) if self.closed else painter.drawPolyline(poly)
        if not self.closed and not self.ellipse:
            scale = painter.worldTransform().m11() or 1.0
            painter.setPen(QPen(QColor(0, 0, 0), 1 / scale))
            painter.setBrush(QColor(255, 255, 255))
            r = 3.5 / scale
            for x, y in self.anchors if hasattr(self, "anchors") else []:
                painter.drawRect(QRectF(x - r, y - r, 2 * r, 2 * r))


class _SelectTool:
    """Base for tools that build a selection. `commit(mask, mode, label)` is called when done."""
    wants_right_click = False  # False: right-click opens the selection menu

    def __init__(self, canvas, doc_w, doc_h, commit, options):
        self.canvas, self.doc_w, self.doc_h = canvas, doc_w, doc_h
        self.commit, self.options = commit, options
        self.preview = _Preview()
        canvas.scene().addItem(self.preview)
        self.mode = "new"

    def remove(self):
        self.canvas.scene().removeItem(self.preview)

    def _clamp(self, p):
        return (float(np.clip(p.x(), 0, self.doc_w)), float(np.clip(p.y(), 0, self.doc_h)))

    def undo(self):
        return False

    def move(self, pos):
        pass

    def release(self):
        pass

    def double_click(self):
        pass

    def key(self, key):
        return False


class MarqueeTool(_SelectTool):
    def press(self, pos, button, modifiers=Qt.NoModifier):
        if button != Qt.LeftButton:
            return
        self.mode = mode_from_modifiers(modifiers, self.options()["mode"])
        self.start = self._clamp(pos)
        self.end = self.start
        self.dragging = True

    def move(self, pos):
        if getattr(self, "dragging", False):
            self.end = self._clamp(pos)
            self.preview.set([self.start, (self.end[0], self.start[1]), self.end,
                              (self.start[0], self.end[1])], closed=True,
                             ellipse=self.options()["shape"] == "ellipse")
            if self.preview.ellipse:
                self.preview.set([self.start, self.end], ellipse=True)

    def release(self):
        if not getattr(self, "dragging", False):
            return
        self.dragging = False
        self.preview.set([])
        (x0, y0), (x1, y1) = self.start, self.end
        if abs(x1 - x0) < 2 or abs(y1 - y0) < 2:
            if self.mode == "new":
                self.commit(None, "new", "Deselect")  # a plain click deselects, like Photoshop
            return
        rect = (x0, y0, x1, y1)
        if self.options()["shape"] == "ellipse":
            mask = ellipse_mask(rect, self.doc_w, self.doc_h, True)
        else:
            mask = rect_mask(rect, self.doc_w, self.doc_h)
        self.commit(mask, self.mode, "Marquee")


class LassoTool(_SelectTool):
    """Freehand (drag), Polygonal (click points) and Magnetic (snaps to edges)."""

    def __init__(self, canvas, doc_w, doc_h, commit, options, edges_fn):
        super().__init__(canvas, doc_w, doc_h, commit, options)
        self.points = []
        self.active = False
        self.edges_fn = edges_fn     # returns an edge-strength map (computed lazily)
        self.preview.anchors = []

    @property
    def wants_right_click(self):
        return self.active  # while drawing, right-click removes the last point

    def _kind(self):
        return self.options()["lasso"]

    def _snap(self, p):
        """Magnetic: move the point to the strongest edge nearby."""
        edges = self.edges_fn()
        r = int(max(4, 10 / (self.canvas.zoom() or 1)))
        x, y = int(p[0]), int(p[1])
        x0, y0 = max(0, x - r), max(0, y - r)
        x1, y1 = min(self.doc_w, x + r + 1), min(self.doc_h, y + r + 1)
        if x1 <= x0 or y1 <= y0:
            return p
        win = edges[y0:y1, x0:x1].astype(np.float32)
        yy, xx = np.mgrid[y0:y1, x0:x1]
        score = win - 0.6 * np.hypot(xx - p[0], yy - p[1]) * (win.max() / (2 * r + 1e-6))
        k = int(np.argmax(score))
        return (float(xx.flat[k]), float(yy.flat[k]))

    def press(self, pos, button, modifiers=Qt.NoModifier):
        p = self._clamp(pos)
        kind = self._kind()
        if button == Qt.RightButton:
            if self.active and kind != "freehand" and len(self.points) > 1:
                self.points.pop()
                self.preview.set(self.points)
            return
        if button != Qt.LeftButton:
            return
        if not self.active:
            self.mode = mode_from_modifiers(modifiers, self.options()["mode"])
            self.active = True
            self.points = [p]
            self.preview.anchors = [p]
            self.dragging = kind == "freehand"
            return
        if kind == "polygonal":
            first = self.points[0]
            tol = 8 / (self.canvas.zoom() or 1)
            if len(self.points) >= 3 and np.hypot(p[0] - first[0], p[1] - first[1]) <= tol:
                self._finish()
                return
            self.points.append(p)
            self.preview.set(self.points)
        elif kind == "magnetic":
            first = self.points[0]
            tol = 8 / (self.canvas.zoom() or 1)
            if len(self.points) >= 3 and np.hypot(p[0] - first[0], p[1] - first[1]) <= tol:
                self._finish()
                return
            self.preview.anchors.append(self.points[-1])

    def move(self, pos):
        if not self.active:
            return
        p = self._clamp(pos)
        kind = self._kind()
        if kind == "freehand" and getattr(self, "dragging", False):
            last = self.points[-1]
            if np.hypot(p[0] - last[0], p[1] - last[1]) >= 1.5 / (self.canvas.zoom() or 1):
                self.points.append(p)
                self.preview.set(self.points)
        elif kind == "magnetic":
            q = self._snap(p)
            last = self.points[-1]
            step = 3 / (self.canvas.zoom() or 1)
            if np.hypot(q[0] - last[0], q[1] - last[1]) >= step:
                self.points.append(q)
                # drop an anchor every so often, like Photoshop
                a = self.preview.anchors[-1]
                if np.hypot(q[0] - a[0], q[1] - a[1]) > 40 / (self.canvas.zoom() or 1):
                    self.preview.anchors.append(q)
            self.preview.set(self.points)
        elif kind == "polygonal":
            self.preview.set(self.points + [p])

    def release(self):
        if self.active and self._kind() == "freehand" and getattr(self, "dragging", False):
            self._finish()

    def double_click(self):
        if self.active and self._kind() != "freehand":
            self._finish()

    def key(self, key):
        if not self.active:
            return False
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self._finish()
            return True
        if key == Qt.Key_Escape:
            self._reset()
            return True
        if key in (Qt.Key_Backspace, Qt.Key_Delete) and len(self.points) > 1:
            if self._kind() == "magnetic":
                a = self.preview.anchors[-2] if len(self.preview.anchors) > 1 else self.points[0]
                while len(self.points) > 1 and self.points[-1] != a:
                    self.points.pop()
                if len(self.preview.anchors) > 1:
                    self.preview.anchors.pop()
            else:
                self.points.pop()
            self.preview.set(self.points)
            return True
        return False

    def _reset(self):
        self.active = False
        self.dragging = False
        self.points = []
        self.preview.anchors = []
        self.preview.set([])

    def _finish(self):
        pts = self.points
        mode = self.mode
        self._reset()
        if len(pts) < 3:
            return
        self.commit(polygon_mask(pts, self.doc_w, self.doc_h, self.options()["antialias"]),
                    mode, "Lasso")


class WandTool(_SelectTool):
    def __init__(self, canvas, doc_w, doc_h, commit, options, sample_fn):
        super().__init__(canvas, doc_w, doc_h, commit, options)
        self.sample_fn = sample_fn  # returns the RGB(A) image to sample colors from

    def press(self, pos, button, modifiers=Qt.NoModifier):
        if button != Qt.LeftButton:
            return
        o = self.options()
        mode = mode_from_modifiers(modifiers, o["mode"])
        x, y = self._clamp(pos)
        mask = magic_wand(self.sample_fn(o["sample_all"]), x, y, o["tolerance"],
                          o["contiguous"], o["antialias"])
        self.commit(mask, mode, "Magic Wand")
