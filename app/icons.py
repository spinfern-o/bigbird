"""Simple vector tool icons drawn with QPainter (no image files needed)."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF


def _canvas(draw, color):
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(color, 4.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    draw(p, color)
    p.end()
    return pm


def _hand(p, c):
    path = QPainterPath()
    path.addRoundedRect(QRectF(16, 30, 30, 24), 8, 8)
    p.drawPath(path)
    for x, top in ((18, 14), (26, 9), (34, 10), (42, 16)):
        p.drawLine(QPointF(x + 2, top), QPointF(x + 2, 32))
    p.drawLine(QPointF(17, 40), QPointF(9, 30))


def _move(p, c):
    p.drawLine(QPointF(32, 8), QPointF(32, 56))
    p.drawLine(QPointF(8, 32), QPointF(56, 32))
    for a, b, d in (((32, 8), (26, 15), (38, 15)), ((32, 56), (26, 49), (38, 49)),
                    ((8, 32), (15, 26), (15, 38)), ((56, 32), (49, 26), (49, 38))):
        p.drawPolyline(QPolygonF([QPointF(*b), QPointF(*a), QPointF(*d)]))


def _brush(p, c):
    p.drawLine(QPointF(54, 10), QPointF(28, 36))
    p.setBrush(c)
    path = QPainterPath(QPointF(28, 32))
    path.cubicTo(QPointF(18, 30), QPointF(16, 44), QPointF(10, 54))
    path.cubicTo(QPointF(24, 54), QPointF(34, 46), QPointF(32, 36))
    path.closeSubpath()
    p.drawPath(path)


def _eraser(p, c):
    p.save()
    p.translate(32, 32)
    p.rotate(-40)
    p.drawRoundedRect(QRectF(-20, -10, 40, 20), 4, 4)
    p.setBrush(c)
    p.drawRoundedRect(QRectF(-20, -10, 14, 20), 4, 4)
    p.restore()
    p.drawLine(QPointF(30, 54), QPointF(54, 54))


def _crop(p, c):
    p.drawPolyline(QPolygonF([QPointF(18, 6), QPointF(18, 46), QPointF(58, 46)]))
    p.drawPolyline(QPolygonF([QPointF(6, 18), QPointF(46, 18), QPointF(46, 58)]))


def _eyedropper(p, c):
    p.drawLine(QPointF(12, 52), QPointF(38, 26))
    p.setBrush(c)
    p.drawEllipse(QPointF(46, 18), 8, 8)
    p.drawLine(QPointF(32, 20), QPointF(44, 32))


def _text(p, c):
    f = QFont("Georgia", 40, QFont.Bold)
    p.setFont(f)
    p.drawText(QRectF(0, 0, 64, 64), Qt.AlignCenter, "T")


def _ai_remove(p, c):
    p.save()
    p.setPen(QPen(c, 3, Qt.DashLine, Qt.RoundCap))
    p.drawEllipse(QPointF(28, 34), 18, 18)
    p.restore()
    p.setBrush(c)
    for x, y in ((28, 16), (46, 34), (28, 52), (10, 34)):
        p.drawEllipse(QPointF(x, y), 4, 4)
    p.setBrush(Qt.NoBrush)
    p.drawLine(QPointF(44, 8), QPointF(56, 20))   # sparkle
    p.drawLine(QPointF(56, 8), QPointF(44, 20))


DRAWERS = {"hand": _hand, "move": _move, "brush": _brush, "eraser": _eraser,
           "crop": _crop, "eyedropper": _eyedropper, "text": _text,
           "ai_remove": _ai_remove}


def tool_icon(name):
    icon = QIcon()
    icon.addPixmap(_canvas(DRAWERS[name], QColor(210, 210, 215)), QIcon.Normal, QIcon.Off)
    icon.addPixmap(_canvas(DRAWERS[name], QColor(255, 255, 255)), QIcon.Normal, QIcon.On)
    return icon
