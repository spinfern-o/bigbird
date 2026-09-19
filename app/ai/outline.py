"""Editable outline made of dots (vertices) joined by lines.

Used to mark an object to remove, or to refine what a background removal kept.
- Click empty space to place dots; click the first dot (or double-click) to close the shape.
- Drag a dot to move it. Click on a line to add a dot there.
- Right-click a dot to delete it.
- "More points" adds a dot in the middle of every line; "Fewer points" removes every other dot.
Several shapes can exist; a shape inside another shape cuts a hole in it.
"""
import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsItem

HANDLE_PX = 5.0    # dot radius on screen
HIT_PX = 9.0       # how close (on screen) a click must be to grab a dot or line


def _dist_to_segment(p, a, b):
    ab = b - a
    denom = float(ab @ ab)
    t = 0.0 if denom == 0 else float(np.clip((p - a) @ ab / denom, 0, 1))
    proj = a + t * ab
    return float(np.hypot(*(p - proj))), proj


class OutlineItem(QGraphicsItem):
    """Draws the shapes: tinted fill, connecting lines and dots at a constant screen size."""

    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.setZValue(15)

    def boundingRect(self):
        e = self.editor
        return QRectF(-50, -50, e.doc_w + 100, e.doc_h + 100)

    def paint(self, painter, option, widget=None):
        e = self.editor
        scale = painter.worldTransform().m11() or 1.0
        r = HANDLE_PX / scale
        painter.setRenderHint(QPainter.Antialiasing)

        path = QPainterPath()
        path.setFillRule(Qt.OddEvenFill)
        for poly in e.polys:
            if len(poly) >= 3:
                path.addPolygon(QPolygonF([QPointF(x, y) for x, y in poly]))
                path.closeSubpath()
        fill = QColor(e.color)
        fill.setAlpha(70)
        painter.fillPath(path, fill)

        for i, poly in enumerate(e.polys + ([e.open] if e.open else [])):
            closed = i < len(e.polys)
            pts = [QPointF(x, y) for x, y in poly]
            for width, col in ((3.2, QColor(0, 0, 0, 170)), (1.6, e.color)):
                pen = QPen(col, width)
                pen.setCosmetic(True)
                painter.setPen(pen)
                if closed:
                    painter.drawPolygon(QPolygonF(pts))
                else:
                    painter.drawPolyline(QPolygonF(pts))
            for j, pt in enumerate(pts):
                hot = e.hover == (i, j) or e.drag == (i, j)
                first_open = not closed and j == 0 and len(pts) >= 3
                painter.setPen(QPen(QColor(0, 0, 0), 1.2 / scale))
                painter.setBrush(QColor(255, 220, 0) if hot or first_open else QColor(255, 255, 255))
                rr = r * (1.35 if hot or first_open else 1.0)
                painter.drawEllipse(pt, rr, rr)


class OutlineEditor:
    def __init__(self, canvas, color):
        self.canvas = canvas
        self.color = QColor(color)
        self.doc_w, self.doc_h = canvas.doc_w, canvas.doc_h
        self.polys = []      # closed shapes: lists of [x, y]
        self.open = []       # shape currently being drawn
        self.hover = None    # (poly index, vertex index)
        self.drag = None
        self._history = []
        self._drag_moved = False
        self.on_change = None
        self.item = OutlineItem(self)
        canvas.scene().addItem(self.item)

    # ------------------------------------------------------------------ state
    def remove(self):
        self.canvas.scene().removeItem(self.item)

    def has_shape(self):
        return any(len(p) >= 3 for p in self.polys)

    def point_count(self):
        return sum(len(p) for p in self.polys) + len(self.open)

    def _save(self):
        self._history.append(([list(map(list, p)) for p in self.polys], [list(v) for v in self.open]))
        del self._history[:-100]

    def undo(self):
        if not self._history:
            return False
        polys, self.open = self._history.pop()
        self.polys = polys
        self._changed()
        return True

    def _changed(self):
        self.item.update()
        if self.on_change:
            self.on_change()

    def set_polys(self, polys):
        self._save()
        self.polys = [list(map(list, p)) for p in polys if len(p) >= 3]
        self.open = []
        self._changed()

    def clear(self):
        if self.polys or self.open:
            self._save()
        self.polys, self.open = [], []
        self._changed()

    def more_points(self):
        """Insert a dot halfway along every line so the outline can follow curves."""
        self._save()
        out = []
        for poly in self.polys:
            new = []
            for k, a in enumerate(poly):
                b = poly[(k + 1) % len(poly)]
                new += [a, [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]]
            out.append(new)
        self.polys = out
        self._changed()

    def fewer_points(self):
        self._save()
        self.polys = [p[::2] if len(p) >= 8 else p for p in self.polys]
        self._changed()

    # ------------------------------------------------------------------ hit testing
    def _tol(self):
        return HIT_PX / (self.canvas.zoom() or 1.0)

    def _all(self):
        return self.polys + ([self.open] if self.open else [])

    def _vertex_at(self, p):
        best, tol = None, self._tol()
        for i, poly in enumerate(self._all()):
            for j, (x, y) in enumerate(poly):
                d = np.hypot(x - p[0], y - p[1])
                if d <= tol and (best is None or d < best[0]):
                    best = (d, i, j)
        return None if best is None else (best[1], best[2])

    def _edge_at(self, p):
        best, tol = None, self._tol()
        pp = np.array(p, float)
        for i, poly in enumerate(self.polys):
            n = len(poly)
            for j in range(n):
                a, b = np.array(poly[j], float), np.array(poly[(j + 1) % n], float)
                d, proj = _dist_to_segment(pp, a, b)
                if d <= tol and (best is None or d < best[0]):
                    best = (d, i, j + 1, proj)
        return None if best is None else best[1:]

    def _clamp(self, p):
        return [float(np.clip(p[0], 0, self.doc_w)), float(np.clip(p[1], 0, self.doc_h))]

    # ------------------------------------------------------------------ mouse
    def press(self, pos, button):
        p = self._clamp((pos.x(), pos.y()))
        hit = self._vertex_at(p)
        if button == Qt.RightButton:
            if hit:
                self._delete_vertex(*hit)
            elif self.open:
                self._save()
                self.open.pop()
                self._changed()
            return
        if hit:
            i, j = hit
            if i == len(self.polys) and j == 0 and len(self.open) >= 3:
                self._close_open()
                return
            self._save()
            self.drag = hit
            self._drag_moved = False
            return
        if not self.open:
            edge = self._edge_at(p)
            if edge:
                i, j, proj = edge
                self._save()
                self.polys[i].insert(j, [float(proj[0]), float(proj[1])])
                self.drag = (i, j)
                self._changed()
                return
        self._save()
        self.open.append(p)
        self._changed()

    def move(self, pos):
        p = self._clamp((pos.x(), pos.y()))
        if self.drag:
            i, j = self.drag
            self._all()[i][j] = p
            self._drag_moved = True
            self.item.update()
            return
        hover = self._vertex_at(p)
        if hover != self.hover:
            self.hover = hover
            self.item.update()

    def release(self):
        if self.drag:
            if not self._drag_moved and self._history:
                self._history.pop()  # a click without dragging isn't a change
            self.drag = None
            self._changed()

    def double_click(self):
        if len(self.open) >= 3:
            self._close_open()

    def key(self, key):
        if key in (Qt.Key_Backspace, Qt.Key_Delete):
            if self.open:
                self._save()
                self.open.pop()
                self._changed()
                return True
            if self.hover:
                self._delete_vertex(*self.hover)
                return True
        return False

    def _close_open(self):
        self._save()
        self.polys.append(self.open)
        self.open = []
        self._changed()

    def _delete_vertex(self, i, j):
        self._save()
        target = self._all()[i]
        del target[j]
        if i < len(self.polys) and len(target) < 3:
            del self.polys[i]
        self.hover = None
        self._changed()

    # ------------------------------------------------------------------ conversion
    def rasterize(self, feather=0.0):
        """Return an HxW uint8 mask of the shapes (anti-aliased, optionally feathered)."""
        w, h = self.doc_w, self.doc_h
        img = QImage(w, h, QImage.Format_Grayscale8)
        img.fill(0)
        path = QPainterPath()
        path.setFillRule(Qt.OddEvenFill)
        for poly in self.polys:
            path.addPolygon(QPolygonF([QPointF(x, y) for x, y in poly]))
            path.closeSubpath()
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillPath(path, QColor(255, 255, 255))
        p.end()
        buf = np.frombuffer(img.constBits(), np.uint8, count=img.sizeInBytes())
        mask = buf.reshape(h, img.bytesPerLine())[:, :w].copy()
        if feather > 0:
            mask = cv2.GaussianBlur(mask, (0, 0), feather)
        return mask


def trace_mask(mask, max_shapes=12):
    """Turn a mask into editable polygons (outer outlines and holes).
    Returns (polygons, tolerance): how far the dots may stray from the true edge."""
    h, w = mask.shape
    binary = (mask > 127).astype(np.uint8)
    contours, _ = cv2.findContours(binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    min_area = 0.0005 * h * w
    contours = sorted((c for c in contours if cv2.contourArea(c) >= min_area),
                      key=cv2.contourArea, reverse=True)[:max_shapes]
    polys, tol = [], 1.0
    for c in contours:
        eps = max(1.0, 0.0018 * cv2.arcLength(c, True))
        approx = cv2.approxPolyDP(c, eps, True).reshape(-1, 2)
        if len(approx) >= 3:
            polys.append([[float(x) + 0.5, float(y) + 0.5] for x, y in approx])
            tol = max(tol, eps)
    return polys, tol


def merge_refined(orig_alpha, outline_mask, tol):
    """Keep the AI's fine edge (e.g. hair) wherever the outline still follows it,
    and use the user's outline only where they actually changed something."""
    a = orig_alpha > 127
    p = outline_mask > 127
    diff = (a != p).astype(np.uint8)
    r = max(1, int(round(tol * 1.5)))
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    changed = cv2.morphologyEx(diff, cv2.MORPH_OPEN, k)   # drop thin approximation slivers
    if not changed.any():
        return orig_alpha.copy()
    changed = cv2.dilate(changed, k).astype(np.float32)
    w = cv2.GaussianBlur(changed, (0, 0), r)            # blend smoothly between the two
    out = orig_alpha.astype(np.float32) * (1 - w) + outline_mask.astype(np.float32) * w
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)
