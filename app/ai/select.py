"""Click-to-select objects (SAM 2.1).

- Click an object to select it; the AI finds its outline.
- Click a selected object again to deselect it.
- Shift+click adds an area to the most recent object; right-click (or Alt+click) removes
  an area from the object under the cursor.
- "Smaller part" cycles a single-click object between the whole object and its parts.
"""
import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsItem

from . import tasks

DISPLAY_MAX = 1600   # overlay resolution (long edge)


class _Object:
    def __init__(self, x, y):
        self.points = [(x, y)]
        self.labels = [1]
        self.cand = 0          # which of the three candidates (single click only)
        self.logits = None     # 256x256 low-res logits of the chosen mask

    def copy(self):
        o = _Object(0, 0)
        o.points, o.labels, o.cand, o.logits = list(self.points), list(self.labels), self.cand, self.logits
        return o


class SelectionItem(QGraphicsItem):
    def __init__(self, sel):
        super().__init__()
        self.sel = sel
        self.setZValue(15)

    def boundingRect(self):
        return QRectF(0, 0, self.sel.doc_w, self.sel.doc_h)

    def paint(self, painter, option, widget=None):
        s = self.sel
        if s.overlay is not None:
            painter.drawPixmap(QRectF(0, 0, s.doc_w, s.doc_h), s.overlay,
                               QRectF(s.overlay.rect()))
        scale = painter.worldTransform().m11() or 1.0
        r = 5.0 / scale
        painter.setRenderHint(QPainter.Antialiasing)
        for obj in s.objects:
            for (x, y), lab in zip(obj.points, obj.labels):
                painter.setPen(QPen(QColor(0, 0, 0), 1.5 / scale))
                painter.setBrush(QColor(60, 220, 90) if lab else QColor(255, 60, 60))
                painter.drawEllipse(QPointF(x, y), r, r)
                painter.setPen(QPen(QColor(255, 255, 255), 1.6 / scale))
                painter.drawLine(QPointF(x - r * 0.55, y), QPointF(x + r * 0.55, y))
                if lab:
                    painter.drawLine(QPointF(x, y - r * 0.55), QPointF(x, y + r * 0.55))


class ObjectSelector:
    def __init__(self, canvas, sam):
        self.canvas = canvas
        self.sam = sam
        self.doc_w, self.doc_h = sam.w, sam.h
        f = min(1.0, DISPLAY_MAX / max(sam.w, sam.h))
        self.disp = (max(1, int(sam.w * f)), max(1, int(sam.h * f)))
        self.objects = []
        self.overlay = None
        self._history = []
        self.on_change = None
        self.item = SelectionItem(self)
        canvas.scene().addItem(self.item)

    # ------------------------------------------------------------------ state
    def remove(self):
        self.canvas.scene().removeItem(self.item)

    def count(self):
        return len(self.objects)

    def _save(self):
        self._history.append([o.copy() for o in self.objects])
        del self._history[:-100]

    def undo(self):
        if not self._history:
            return False
        self.objects = self._history.pop()
        self._refresh()
        return True

    def clear(self):
        if self.objects:
            self._save()
        self.objects = []
        self._refresh()

    def _decode(self, obj):
        scores, logits = self.sam.decode(obj.points, obj.labels)
        if len(obj.points) == 1:
            # One click is ambiguous (whole object, part, smaller part). Default to the biggest
            # candidate that is still an object (under half the photo) and that the AI has at
            # least minimal confidence in; "Smaller part" then steps down from there.
            areas = [(m > 0).mean() for m in logits]
            order = sorted(range(3), key=lambda k: -areas[k])
            ok = [k for k in order if areas[k] < 0.5 and scores[k] >= 0.1]
            start = order.index(ok[0]) if ok else order.index(int(np.argmax(scores)))
            obj.logits = logits[order[(start + obj.cand) % 3]]
        else:
            obj.logits = logits[int(np.argmax(scores))]

    def _object_at(self, x, y):
        """Index of the selected object under (x, y), topmost first."""
        u = int(np.clip(x / self.doc_w * 256, 0, 255))
        v = int(np.clip(y / self.doc_h * 256, 0, 255))
        for i in range(len(self.objects) - 1, -1, -1):
            if self.objects[i].logits[v, u] > 0:
                return i
        return None

    def smaller_part(self):
        """Cycle the latest single-click object: whole object → part → smaller part."""
        if not self.objects or len(self.objects[-1].points) != 1:
            return False
        self._save()
        obj = self.objects[-1]
        obj.cand = (obj.cand + 1) % 3
        self._decode(obj)
        self._refresh()
        return True

    # ------------------------------------------------------------------ mouse
    def press(self, pos, button, modifiers=Qt.NoModifier):
        x = float(np.clip(pos.x(), 0, self.doc_w - 1))
        y = float(np.clip(pos.y(), 0, self.doc_h - 1))
        exclude = button == Qt.RightButton or (modifiers & Qt.AltModifier)
        if button not in (Qt.LeftButton, Qt.RightButton):
            return
        hit = self._object_at(x, y)
        self._save()
        if exclude:
            target = hit if hit is not None else (len(self.objects) - 1 if self.objects else None)
            if target is None:
                self._history.pop()
                return
            obj = self.objects[target]
            obj.points.append((x, y))
            obj.labels.append(0)
            self._decode(obj)
        elif modifiers & Qt.ShiftModifier and self.objects:
            obj = self.objects[-1]
            obj.points.append((x, y))
            obj.labels.append(1)
            self._decode(obj)
        elif hit is not None:
            del self.objects[hit]          # clicking a selected object deselects it
        else:
            obj = _Object(x, y)
            self._decode(obj)
            self.objects.append(obj)
        self._refresh()

    def move(self, pos):
        pass

    def release(self):
        pass

    def double_click(self):
        pass

    def key(self, key):
        return False

    # ------------------------------------------------------------------ output
    def mask(self, w=None, h=None):
        """Union of all selected objects as a soft uint8 mask (full size by default)."""
        w, h = w or self.doc_w, h or self.doc_h
        out = np.zeros((h, w), np.uint8)
        for obj in self.objects:
            np.maximum(out, tasks.logits_to_mask(obj.logits, w, h), out=out)
        return out

    def _refresh(self):
        if self.objects:
            w, h = self.disp
            m = self.mask(w, h)
            rgba = np.zeros((h, w, 4), np.uint8)
            rgba[..., 0], rgba[..., 1], rgba[..., 2] = 255, 60, 60
            rgba[..., 3] = (m.astype(np.uint16) * 120 // 255).astype(np.uint8)
            # Solid outline around each selected area.
            edge = cv2.morphologyEx((m > 127).astype(np.uint8), cv2.MORPH_GRADIENT,
                                    np.ones((3, 3), np.uint8)) > 0
            rgba[edge] = (255, 80, 80, 255)
            img = QImage(rgba.data, w, h, w * 4, QImage.Format_RGBA8888).copy()
            self.overlay = QPixmap.fromImage(img)
        else:
            self.overlay = None
        self.item.update()
        if self.on_change:
            self.on_change()
