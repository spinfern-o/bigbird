"""The central image view: zoom/pan plus the interactive tools."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QImage, QPainter, QPainterPath, QPen, QPixmap,
                           QRadialGradient, QTransform)
from PySide6.QtWidgets import (QGraphicsEllipseItem, QGraphicsPathItem, QGraphicsPixmapItem,
                               QGraphicsRectItem, QGraphicsScene, QGraphicsView)

from . import imageio
from .selection import MarchingAnts


class ToolState:
    def __init__(self):
        self.tool = "hand"
        self.brush_size = 40
        self.hardness = 0.8
        self.strength = 1.0
        self.color = QColor(0, 0, 0)
        self.crop_ratio = None  # width / height, or None for free


class CropRectItem(QGraphicsRectItem):
    """Crop frame with rule-of-thirds guides."""

    def paint(self, painter, option, widget=None):
        r = self.rect()
        pen = QPen(QColor(255, 255, 255, 110), 0)
        painter.setPen(pen)
        for i in (1, 2):
            x = r.left() + r.width() * i / 3
            y = r.top() + r.height() * i / 3
            painter.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            painter.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
        pen = QPen(QColor(255, 255, 255), 0)
        pen.setCosmetic(True)
        pen.setWidthF(1.5)
        painter.setPen(pen)
        painter.drawRect(r)


def _checker_brush():
    pm = QPixmap(16, 16)
    pm.fill(QColor(200, 200, 200))
    p = QPainter(pm)
    p.fillRect(0, 0, 8, 8, QColor(245, 245, 245))
    p.fillRect(8, 8, 8, 8, QColor(245, 245, 245))
    p.end()
    return QBrush(pm)


class Canvas(QGraphicsView):
    zoomChanged = Signal(float)
    strokeFinished = Signal(object, str)   # (new pixels, label)
    colorPicked = Signal(QColor)
    textRequested = Signal(QPointF)
    cropChanged = Signal(bool)
    cropApply = Signal()
    moveStarted = Signal()
    moveFinished = Signal(int, int)
    filesDropped = Signal(list)
    hint = Signal(str)
    outlineApply = Signal()
    outlineCancel = Signal()
    healFinished = Signal(object)          # uint8 mask painted with the Spot Healing Brush
    contextRequested = Signal(object)      # global position for a right-click menu

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.doc = None
        self.doc_w = self.doc_h = 0
        self.display_img = None
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.item = QGraphicsPixmapItem()
        self.item.setTransformationMode(Qt.SmoothTransformation)
        self._scene.addItem(self.item)

        self.float_item = QGraphicsPixmapItem()
        self.float_item.setZValue(5)
        self.float_item.hide()
        self._scene.addItem(self.float_item)

        self.backdrop = QGraphicsPixmapItem()
        self.backdrop.setTransformationMode(Qt.SmoothTransformation)
        self.backdrop.setZValue(12)
        self.backdrop.hide()
        self._scene.addItem(self.backdrop)

        self.crop_shade = QGraphicsPathItem()
        self.crop_shade.setBrush(QColor(0, 0, 0, 150))
        self.crop_shade.setPen(Qt.NoPen)
        self.crop_shade.setZValue(10)
        self.crop_item = CropRectItem()
        self.crop_item.setZValue(11)
        for it in (self.crop_shade, self.crop_item):
            it.hide()
            self._scene.addItem(it)
        self.crop_rect = None

        self.ring_dark = QGraphicsEllipseItem()
        self.ring_light = QGraphicsEllipseItem()
        for ring, color, width in ((self.ring_dark, QColor(0, 0, 0, 160), 3),
                                   (self.ring_light, QColor(255, 255, 255, 230), 1.2)):
            pen = QPen(color)
            pen.setCosmetic(True)
            pen.setWidthF(width)
            ring.setPen(pen)
            ring.setZValue(20)
            ring.hide()
            self._scene.addItem(ring)

        self._checker = _checker_brush()
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setFrameShape(QGraphicsView.NoFrame)

        self._pan_last = None
        self._space = False
        self._stroke = None
        self._crop_drag = None
        self._move_origin = None
        # Interactive overlay tool (outline editor, object selector, lasso, wand, ...)
        self.outline = None
        self.ants = MarchingAnts()
        self._scene.addItem(self.ants)
        self.update_cursor()

    # ------------------------------------------------------------------ display
    def set_display(self, qimg, doc_w, doc_h):
        resized = (doc_w, doc_h) != (self.doc_w, self.doc_h)
        if self._stroke and not resized:
            return  # don't wipe the live stroke preview mid-stroke
        self.doc_w, self.doc_h = doc_w, doc_h
        self.display_img = qimg
        self.item.setPixmap(QPixmap.fromImage(qimg))
        # Separate x/y scale so a rounded-down preview still covers the canvas exactly.
        self._disp_sx = doc_w / max(1, qimg.width())
        self._disp_sy = doc_h / max(1, qimg.height())
        self.item.setTransform(QTransform.fromScale(self._disp_sx, self._disp_sy))
        self._scene.setSceneRect(QRectF(0, 0, doc_w, doc_h))
        if resized:
            self.clear_crop()
            self.fit()

    def clear(self):
        self.doc = None
        self.doc_w = self.doc_h = 0
        self.item.setPixmap(QPixmap())
        self.clear_crop()
        self.ants.set_mask(None)

    def set_selection(self, mask):
        self.ants.set_mask(mask)

    def contextMenuEvent(self, e):
        if self.outline is not None and getattr(self.outline, "wants_right_click", True):
            return  # right-click is used by the active tool
        if self.doc_w:
            self.contextRequested.emit(e.globalPos())

    def drawBackground(self, painter, rect):
        painter.fillRect(rect, QColor(38, 38, 40))
        if self.doc_w:
            # Fill in exact scene coordinates (so edges line up with the image), with the
            # checker pattern counter-scaled to stay a constant size on screen.
            z = self.zoom()
            brush = QBrush(self._checker)
            brush.setTransform(QTransform.fromScale(1 / z, 1 / z))
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, False)
            painter.fillRect(QRectF(0, 0, self.doc_w, self.doc_h), brush)
            painter.restore()

    # ------------------------------------------------------------------ zoom
    def zoom(self):
        return self.transform().m11()

    def set_zoom(self, z):
        z = max(0.02, min(32.0, z))
        self.setTransform(QTransform.fromScale(z, z))
        self.zoomChanged.emit(z)

    def zoom_by(self, factor):
        self.set_zoom(self.zoom() * factor)

    def fit(self):
        if not self.doc_w:
            return
        vp = self.viewport().rect().adjusted(20, 20, -20, -20)
        z = min(vp.width() / self.doc_w, vp.height() / self.doc_h, 1.0)
        self.set_zoom(z)
        self.centerOn(self.doc_w / 2, self.doc_h / 2)

    def wheelEvent(self, e):
        if not self.doc_w:
            return
        self.zoom_by(1.2 ** (e.angleDelta().y() / 120))
        self._update_ring(self.mapToScene(e.position().toPoint()))

    # ------------------------------------------------------------------ tools
    def set_tool(self, tool):
        if self.state.tool == "crop" and tool != "crop":
            self.clear_crop()
        self.state.tool = tool
        self.update_cursor()
        self.ring_dark.hide()
        self.ring_light.hide()

    def update_cursor(self):
        t = self.state.tool
        if self._space or t == "hand":
            c = Qt.OpenHandCursor
        else:
            c = {"move": Qt.SizeAllCursor, "text": Qt.IBeamCursor,
                 "ai_remove": Qt.PointingHandCursor,
                 "ai_refine": Qt.PointingHandCursor}.get(t, Qt.CrossCursor)
        self.viewport().setCursor(c)

    def _in_doc(self, p):
        return 0 <= p.x() < self.doc_w and 0 <= p.y() < self.doc_h

    def _update_ring(self, p):
        if self.state.tool in ("brush", "eraser", "heal") and self.doc_w and not self._space:
            r = self.state.brush_size / 2
            for ring in (self.ring_dark, self.ring_light):
                ring.setRect(QRectF(p.x() - r, p.y() - r, 2 * r, 2 * r))
                ring.show()
        else:
            self.ring_dark.hide()
            self.ring_light.hide()

    def leaveEvent(self, e):
        self.ring_dark.hide()
        self.ring_light.hide()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if not self.doc_w:
            return
        p = self.mapToScene(e.position().toPoint())
        tool = self.state.tool
        if e.button() == Qt.MiddleButton or (e.button() == Qt.LeftButton and (self._space or tool == "hand")):
            self._pan_last = e.position()
            self.viewport().setCursor(Qt.ClosedHandCursor)
            return
        if self.outline is not None and e.button() in (Qt.LeftButton, Qt.RightButton):
            self.outline.press(p, e.button(), e.modifiers())
            return
        if e.button() != Qt.LeftButton:
            return
        if tool in ("brush", "eraser", "heal"):
            self._begin_stroke(p)
        elif tool == "crop":
            self._crop_press(p)
        elif tool == "eyedropper":
            self._pick(p)
        elif tool == "text" and self._in_doc(p):
            self.textRequested.emit(p)
        elif tool == "move":
            self._move_origin = p
            self.moveStarted.emit()

    def mouseMoveEvent(self, e):
        p = self.mapToScene(e.position().toPoint())
        self._update_ring(p)
        if self._pan_last is not None:
            d = e.position() - self._pan_last
            self._pan_last = e.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(d.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(d.y()))
        elif self.outline is not None:
            self.outline.move(p)
        elif self._stroke:
            self._continue_stroke(p)
        elif self._crop_drag:
            self._crop_move(p)
        elif self._move_origin is not None:
            d = p - self._move_origin
            self.float_item.setPos(round(d.x()), round(d.y()))
        elif self.state.tool == "eyedropper" and e.buttons() & Qt.LeftButton:
            self._pick(p)

    def mouseReleaseEvent(self, e):
        if self._pan_last is not None:
            self._pan_last = None
            self.update_cursor()
        elif self.outline is not None:
            self.outline.release()
        elif self._stroke:
            self._end_stroke()
        elif self._crop_drag:
            self._crop_drag = None
        elif self._move_origin is not None:
            d = self.mapToScene(e.position().toPoint()) - self._move_origin
            self._move_origin = None
            self.moveFinished.emit(round(d.x()), round(d.y()))

    def mouseDoubleClickEvent(self, e):
        if self.outline is not None and e.button() == Qt.LeftButton:
            self.outline.double_click()
        else:
            super().mouseDoubleClickEvent(e)

    def keyPressEvent(self, e):
        if self.outline is not None:
            if self.outline.key(e.key()):
                return
            if e.key() in (Qt.Key_Return, Qt.Key_Enter):
                self.outlineApply.emit()
                return
            if e.key() == Qt.Key_Escape:
                self.outlineCancel.emit()
                return
        if e.key() == Qt.Key_Space and not e.isAutoRepeat():
            self._space = True
            self.update_cursor()
            self.ring_dark.hide()
            self.ring_light.hide()
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter) and self.crop_rect is not None:
            self.cropApply.emit()
        elif e.key() == Qt.Key_Escape and self.crop_rect is not None:
            self.clear_crop()
        else:
            super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key_Space and not e.isAutoRepeat():
            self._space = False
            self.update_cursor()
        else:
            super().keyReleaseEvent(e)

    # ------------------------------------------------------------------ brush / eraser
    def _begin_stroke(self, p):
        layer = self.doc.active_layer()
        if not layer.visible:
            self.hint.emit("The selected layer is hidden. Turn it on in the Layers panel to paint on it.")
            return
        heal = self.state.tool == "heal"
        if heal:  # the healing brush paints a mask of what to fix
            img = QImage(self.doc_w, self.doc_h, QImage.Format_ARGB32_Premultiplied)
            img.fill(Qt.transparent)
        else:
            img = imageio.to_qimage(layer.pixels).convertToFormat(QImage.Format_ARGB32_Premultiplied)
        live = QPixmap(self.item.pixmap())
        r = self.state.brush_size / 2
        spacing = max(0.5, r * 0.2)
        # Per-dab alpha so that overlapping dabs add up to the chosen strength.
        overlap = max(1.0, 2 * r / spacing)
        dab_alpha = 1 - (1 - min(self.state.strength, 0.999)) ** (1 / overlap)
        if self.state.strength >= 1 or heal:
            dab_alpha = 1.0
        self._stroke = {"img": img, "live": live, "last": p, "left": spacing,
                        "spacing": spacing, "alpha": dab_alpha,
                        "erase": self.state.tool == "eraser", "heal": heal}
        self._paint_dabs([p])

    def _continue_stroke(self, p):
        s = self._stroke
        p0 = s["last"]
        d = math.hypot(p.x() - p0.x(), p.y() - p0.y())
        pts = []
        t = s["left"]
        while t <= d:
            pts.append(p0 + (p - p0) * (t / d))
            t += s["spacing"]
        s["left"] = t - d
        s["last"] = p
        if pts:
            self._paint_dabs(pts)

    def _paint_dabs(self, pts):
        s = self._stroke
        r = self.state.brush_size / 2
        hard = 1.0 if s["heal"] else self.state.hardness
        col = QColor(self.state.color)
        col.setAlphaF(s["alpha"])
        for target, sx, sy in ((s["img"], 1.0, 1.0),
                               (s["live"], 1.0 / self._disp_sx, 1.0 / self._disp_sy)):
            if s["heal"]:  # solid mask in the image, translucent red on screen
                col = QColor(255, 0, 0) if target is s["img"] else QColor(255, 60, 60, 90)
            clear = QColor(col)
            clear.setAlpha(0)
            painter = QPainter(target)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            painter.scale(sx, sy)
            if s["erase"]:
                painter.setCompositionMode(QPainter.CompositionMode_DestinationOut)
            for pt in pts:
                if hard >= 0.99:
                    painter.setBrush(col)
                else:
                    grad = QRadialGradient(pt, r)
                    grad.setColorAt(0, col)
                    grad.setColorAt(max(0.0, hard), col)
                    grad.setColorAt(1, clear)
                    painter.setBrush(QBrush(grad))
                painter.drawEllipse(pt, r, r)
            painter.end()
        self.item.setPixmap(s["live"])

    def _end_stroke(self):
        s, self._stroke = self._stroke, None
        if s["heal"]:
            self.healFinished.emit(imageio.from_qimage(s["img"])[..., 3].copy())
            return
        label = "Eraser" if s["erase"] else "Brush stroke"
        self.strokeFinished.emit(imageio.from_qimage(s["img"]), label)

    # ------------------------------------------------------------------ eyedropper
    def _pick(self, p):
        if not self.display_img or not self._in_doc(p):
            return
        f = self.display_img.width() / self.doc_w
        x = min(self.display_img.width() - 1, int(p.x() * f))
        y = min(self.display_img.height() - 1, int(p.y() * f))
        c = self.display_img.pixelColor(x, y)
        c.setAlpha(255)
        self.colorPicked.emit(c)

    # ------------------------------------------------------------------ crop
    def clear_crop(self):
        self.crop_rect = None
        self.crop_item.hide()
        self.crop_shade.hide()
        self.cropChanged.emit(False)

    def _clamp(self, p):
        return QPointF(min(max(p.x(), 0), self.doc_w), min(max(p.y(), 0), self.doc_h))

    def _crop_press(self, p):
        if self.crop_rect is not None and self.crop_rect.contains(p):
            self._crop_drag = ("move", p, QRectF(self.crop_rect))
        else:
            self._crop_drag = ("new", self._clamp(p), None)

    def _crop_move(self, p):
        mode, a, orig = self._crop_drag
        if mode == "move":
            d = p - a
            r = orig.translated(d)
            dx = max(-r.left(), min(0, self.doc_w - r.right()))
            dy = max(-r.top(), min(0, self.doc_h - r.bottom()))
            self._set_crop(r.translated(dx, dy))
            return
        p = self._clamp(p)
        w, h = p.x() - a.x(), p.y() - a.y()
        ratio = self.state.crop_ratio
        if ratio:
            sw = 1 if w >= 0 else -1
            sh = 1 if h >= 0 else -1
            if abs(w) / ratio >= abs(h):
                h = sh * abs(w) / ratio
            else:
                w = sw * abs(h) * ratio
            maxw = (self.doc_w - a.x()) if w >= 0 else a.x()
            maxh = (self.doc_h - a.y()) if h >= 0 else a.y()
            f = min(1.0, maxw / abs(w) if w else 1.0, maxh / abs(h) if h else 1.0)
            w, h = w * f, h * f
        self._set_crop(QRectF(a, QPointF(a.x() + w, a.y() + h)).normalized())

    def _set_crop(self, r):
        if r.width() < 2 or r.height() < 2:
            return
        self.crop_rect = r
        self.crop_item.setRect(r)
        path = QPainterPath()
        path.setFillRule(Qt.OddEvenFill)
        path.addRect(QRectF(0, 0, self.doc_w, self.doc_h))
        path.addRect(r)
        self.crop_shade.setPath(path)
        self.crop_item.show()
        self.crop_shade.show()
        self.cropChanged.emit(True)
        self.hint.emit(f"Crop: {int(r.width())} × {int(r.height())} px — press Enter or click "
                       "Apply to crop, Esc to cancel. Drag inside the box to move it.")

    def crop_pixels(self):
        r = self.crop_rect
        x, y = int(round(r.left())), int(round(r.top()))
        w = min(self.doc_w - x, int(round(r.width())))
        h = min(self.doc_h - y, int(round(r.height())))
        return x, y, w, h

    # ------------------------------------------------------------------ move tool
    def set_backdrop(self, qimg):
        """Show an image over the canvas (below outlines), or hide it with None."""
        if qimg is None:
            self.backdrop.hide()
            self.backdrop.setPixmap(QPixmap())
            return
        self.backdrop.setPixmap(QPixmap.fromImage(qimg))
        self.backdrop.show()

    def set_floating(self, qimg, opacity=1.0):
        if qimg is None:
            self.float_item.hide()
            self.float_item.setPos(0, 0)
            return
        self.float_item.setPixmap(QPixmap.fromImage(qimg))
        self.float_item.setOpacity(opacity)
        self.float_item.setPos(0, 0)
        self.float_item.show()

    # ------------------------------------------------------------------ drag & drop
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.filesDropped.emit(paths)
