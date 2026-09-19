"""Small dialogs: new canvas, resize, add text, export."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFontComboBox,
                               QFormLayout, QLabel, QPlainTextEdit, QSlider, QSpinBox,
                               QVBoxLayout, QHBoxLayout)

from .panels import ColorButton

SIZE_PRESETS = [
    ("Custom", None),
    ("Instagram post (1080 × 1080)", (1080, 1080)),
    ("Instagram portrait (1080 × 1350)", (1080, 1350)),
    ("Story / Reel (1080 × 1920)", (1080, 1920)),
    ("Full HD wallpaper (1920 × 1080)", (1920, 1080)),
    ("4K wallpaper (3840 × 2160)", (3840, 2160)),
    ("YouTube thumbnail (1280 × 720)", (1280, 720)),
    ("Print 4×6 in @300dpi (1800 × 1200)", (1800, 1200)),
    ("Letter page @300dpi (2550 × 3300)", (2550, 3300)),
]


def _buttons(dlg, ok_text="OK"):
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bb.button(QDialogButtonBox.Ok).setText(ok_text)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    return bb


class NewImageDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Blank Canvas")
        form = QFormLayout(self)
        self.preset = QComboBox()
        for name, _ in SIZE_PRESETS:
            self.preset.addItem(name)
        self.w = QSpinBox(maximum=20000, minimum=1, value=1920, suffix=" px")
        self.h = QSpinBox(maximum=20000, minimum=1, value=1080, suffix=" px")
        self.bg = QComboBox()
        self.bg.addItems(["White", "Black", "Transparent"])
        form.addRow("Size preset", self.preset)
        form.addRow("Width", self.w)
        form.addRow("Height", self.h)
        form.addRow("Background", self.bg)
        form.addRow(_buttons(self, "Create"))
        self.preset.currentIndexChanged.connect(self._preset)

    def _preset(self, i):
        size = SIZE_PRESETS[i][1]
        if size:
            self.w.setValue(size[0])
            self.h.setValue(size[1])

    def result_values(self):
        color = {"White": (255, 255, 255, 255), "Black": (0, 0, 0, 255),
                 "Transparent": (0, 0, 0, 0)}[self.bg.currentText()]
        return self.w.value(), self.h.value(), color


class ResizeDialog(QDialog):
    def __init__(self, w, h, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Resize Image")
        self.ratio = w / h
        form = QFormLayout(self)
        form.addRow(QLabel(f"Current size: {w} × {h} px"))
        self.w = QSpinBox(maximum=30000, minimum=1, value=w, suffix=" px")
        self.h = QSpinBox(maximum=30000, minimum=1, value=h, suffix=" px")
        self.keep = QCheckBox("Keep proportions")
        self.keep.setChecked(True)
        self.pct = QSpinBox(minimum=1, maximum=1000, value=100, suffix=" %")
        form.addRow("Scale", self.pct)
        form.addRow("Width", self.w)
        form.addRow("Height", self.h)
        form.addRow(self.keep)
        form.addRow(_buttons(self, "Resize"))
        self._w0, self._h0 = w, h
        self._busy = False
        self.w.valueChanged.connect(self._w_changed)
        self.h.valueChanged.connect(self._h_changed)
        self.pct.valueChanged.connect(self._pct_changed)

    def _guard(fn):
        def wrap(self, v):
            if self._busy:
                return
            self._busy = True
            fn(self, v)
            self._busy = False
        return wrap

    @_guard
    def _w_changed(self, v):
        if self.keep.isChecked():
            self.h.setValue(max(1, round(v / self.ratio)))

    @_guard
    def _h_changed(self, v):
        if self.keep.isChecked():
            self.w.setValue(max(1, round(v * self.ratio)))

    @_guard
    def _pct_changed(self, v):
        self.w.setValue(max(1, round(self._w0 * v / 100)))
        self.h.setValue(max(1, round(self._h0 * v / 100)))


class TextDialog(QDialog):
    def __init__(self, color, default_size, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Text")
        lay = QVBoxLayout(self)
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("Type your text here…")
        self.text.setMinimumHeight(90)
        lay.addWidget(self.text)
        form = QFormLayout()
        self.font = QFontComboBox()
        self.font.setCurrentFont(QFont("Segoe UI"))
        self.size = QSpinBox(minimum=4, maximum=2000, value=default_size, suffix=" px")
        row = QHBoxLayout()
        self.bold = QCheckBox("Bold")
        self.bold.setChecked(True)
        self.italic = QCheckBox("Italic")
        self.shadow = QCheckBox("Drop shadow")
        row.addWidget(self.bold)
        row.addWidget(self.italic)
        row.addWidget(self.shadow)
        self.color = ColorButton(color)
        form.addRow("Font", self.font)
        form.addRow("Size", self.size)
        form.addRow("Color", self.color)
        form.addRow("Style", row)
        lay.addLayout(form)
        lay.addWidget(QLabel("Tip: the text goes on its own layer, so you can move it later with "
                             "the Move tool."))
        lay.addWidget(_buttons(self, "Add Text"))
        self.text.setFocus()

    def qfont(self):
        f = QFont(self.font.currentFont())
        f.setPixelSize(self.size.value())
        f.setBold(self.bold.isChecked())
        f.setItalic(self.italic.isChecked())
        return f


class ExportDialog(QDialog):
    FORMATS = [("JPEG — best for photos", ".jpg"), ("PNG — keeps transparency", ".png"),
               ("WebP — small files for the web", ".webp"), ("TIFF — for printing", ".tif")]

    def __init__(self, w, h, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export Image")
        self.ratio = w / h
        form = QFormLayout(self)
        self.fmt = QComboBox()
        for name, _ in self.FORMATS:
            self.fmt.addItem(name)
        self.quality = QSlider(Qt.Horizontal)
        self.quality.setRange(40, 100)
        self.quality.setValue(92)
        self.q_lbl = QLabel("92")
        qrow = QHBoxLayout()
        qrow.addWidget(self.quality)
        qrow.addWidget(self.q_lbl)
        self.quality.valueChanged.connect(lambda v: self.q_lbl.setText(str(v)))
        self.size = QComboBox()
        self.size.addItems(["Full size", "Long edge 4096 px", "Long edge 2048 px",
                            "Long edge 1080 px (social media)"])
        form.addRow("Format", self.fmt)
        form.addRow("Quality", qrow)
        form.addRow("Size", self.size)
        form.addRow(QLabel(f"Full size is {w} × {h} px."))
        form.addRow(_buttons(self, "Choose where to save…"))
        self.fmt.currentIndexChanged.connect(
            lambda i: self.quality.setEnabled(self.FORMATS[i][1] in (".jpg", ".webp")))

    def ext(self):
        return self.FORMATS[self.fmt.currentIndex()][1]

    def long_edge(self):
        return [None, 4096, 2048, 1080][self.size.currentIndex()]
