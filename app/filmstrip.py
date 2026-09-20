"""Compact recent-photo filmstrip used by the desktop editing workspace."""

from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImageReader, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class FilmstripWidget(QFrame):
    """A real, lightweight browser for recently opened local photos.

    It intentionally does not pretend to implement the roadmap's complete B6
    library workflow. Every visible action is connected to an existing editor
    operation: open, reopen a recent file, or export the active document.
    """

    pathActivated = Signal(str)
    openRequested = Signal()
    exportRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("filmstrip")
        self.setFixedHeight(124)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget()
        header.setObjectName("filmstripHeader")
        header.setFixedHeight(30)
        header_lay = QHBoxLayout(header)
        header_lay.setContentsMargins(12, 0, 8, 0)
        header_lay.setSpacing(8)

        title = QLabel("Library")
        title.setObjectName("filmstripTitle")
        self.count_label = QLabel("0 photos")
        self.count_label.setObjectName("filmstripCount")
        header_lay.addWidget(title)
        header_lay.addWidget(self.count_label)
        header_lay.addStretch(1)

        open_btn = QPushButton("Open…")
        open_btn.setObjectName("filmstripAction")
        open_btn.setToolTip("Open another photo")
        open_btn.clicked.connect(self.openRequested)
        self.export_btn = QPushButton("Export current")
        self.export_btn.setObjectName("filmstripActionAccent")
        self.export_btn.setToolTip("Export the active document")
        self.export_btn.clicked.connect(self.exportRequested)
        header_lay.addWidget(open_btn)
        header_lay.addWidget(self.export_btn)
        outer.addWidget(header)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("filmstripScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.NoFrame)

        self.items = QWidget()
        self.items.setObjectName("filmstripItems")
        self.items_lay = QHBoxLayout(self.items)
        self.items_lay.setContentsMargins(12, 8, 12, 8)
        self.items_lay.setSpacing(8)
        self.items_lay.addStretch(1)
        self.scroll.setWidget(self.items)
        outer.addWidget(self.scroll, 1)

    @staticmethod
    def _thumbnail(path: str) -> QPixmap:
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid():
            size.scale(QSize(108, 62), Qt.KeepAspectRatioByExpanding)
            reader.setScaledSize(size)
        image = reader.read()
        if not image.isNull():
            pixmap = QPixmap.fromImage(image)
            return pixmap.scaled(108, 62, Qt.KeepAspectRatioByExpanding,
                                 Qt.SmoothTransformation)

        pixmap = QPixmap(108, 62)
        pixmap.fill(QColor("#1b1b1e"))
        painter = QPainter(pixmap)
        painter.setPen(QColor("#6f6f78"))
        painter.drawText(pixmap.rect(), Qt.AlignCenter, "PROJECT")
        painter.end()
        return pixmap

    def set_paths(self, paths, current_path=None):
        while self.items_lay.count():
            item = self.items_lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        current = os.path.abspath(current_path) if current_path else None
        existing = []
        for raw in paths:
            path = os.path.abspath(str(raw))
            if os.path.isfile(path) and path not in existing:
                existing.append(path)

        for path in existing[:10]:
            button = QToolButton()
            button.setObjectName("filmThumb")
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            button.setIcon(QIcon(self._thumbnail(path)))
            button.setIconSize(QSize(108, 62))
            button.setText(os.path.basename(path))
            button.setToolTip(path)
            button.setCheckable(True)
            button.setChecked(path == current)
            button.setFixedSize(116, 82)
            button.clicked.connect(lambda _checked=False, p=path: self.pathActivated.emit(p))
            self.items_lay.addWidget(button)

        if not existing:
            empty = QLabel("Recently opened photos appear here")
            empty.setObjectName("filmstripEmpty")
            empty.setAlignment(Qt.AlignCenter)
            empty.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            self.items_lay.addWidget(empty)

        self.items_lay.addStretch(1)
        count = len(existing)
        self.count_label.setText(f"{count} photo{'s' if count != 1 else ''}")

