"""Right-hand side panels: Adjust (Lightroom-style develop) and Layers."""
import numpy as np
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QColorDialog, QComboBox, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
                               QScrollArea, QSizePolicy, QSlider, QToolButton, QVBoxLayout,
                               QWidget)

from . import adjustments, imageio
from .document import BLEND_MODES

SLIDER_GRADIENTS = {
    "temperature": "stop:0 #3b7dd8, stop:0.5 #cfcfcf, stop:1 #e8b923",
    "tint": "stop:0 #3fae49, stop:0.5 #cfcfcf, stop:1 #c440c9",
    "saturation": "stop:0 #8a8a8a, stop:1 #ff4f6e",
    "vibrance": "stop:0 #8a8a8a, stop:1 #ff9f1c",
    "exposure": "stop:0 #111111, stop:1 #ffffff",
}


class NoWheelSlider(QSlider):
    """Ignore the mouse wheel unless focused, so scrolling the panel doesn't nudge sliders."""

    def __init__(self, *a):
        super().__init__(*a)
        self.setFocusPolicy(Qt.StrongFocus)

    def wheelEvent(self, e):
        if self.hasFocus():
            super().wheelEvent(e)
        else:
            e.ignore()


class ColorButton(QPushButton):
    colorChanged = Signal(QColor)

    def __init__(self, color, tooltip="Click to choose a color"):
        super().__init__()
        self.setFixedSize(34, 24)
        self.setToolTip(tooltip)
        self.set_color(color)
        self.clicked.connect(self._choose)

    def set_color(self, c):
        self.color = QColor(c)
        self.setStyleSheet(f"QPushButton {{ background: {self.color.name()}; border: 2px solid #888;"
                           " border-radius: 4px; }")

    def _choose(self):
        c = QColorDialog.getColor(self.color, self, "Choose a color")
        if c.isValid():
            self.set_color(c)
            self.colorChanged.emit(c)


class Histogram(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(90)
        self.setToolTip("Histogram: shows how many pixels are dark (left) through bright (right).\n"
                        "A pile-up against either edge means detail is being lost there.")
        self.hist = None

    def set_data(self, hist):
        self.hist = hist
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(1, 1, -1, -1)
        p.fillRect(r, QColor(28, 28, 30))
        if self.hist is None:
            return
        h = self.hist
        peak = max(1.0, float(np.percentile(h[:3, 2:254], 99.5)) * 1.1)
        W, H = r.width(), r.height()
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        for row, col in ((0, QColor(200, 50, 50, 150)), (1, QColor(50, 180, 60, 150)),
                         (2, QColor(60, 90, 220, 150))):
            path = QPainterPath()
            path.moveTo(r.left(), r.bottom())
            for i in range(256):
                v = min(1.0, h[row, i] / peak)
                path.lineTo(r.left() + i * W / 255, r.bottom() - v * H)
            path.lineTo(r.right(), r.bottom())
            path.closeSubpath()
            p.fillPath(path, col)


class SliderRow(QWidget):
    valueChanged = Signal(str, int)

    def __init__(self, key, label, lo, hi, tooltip):
        super().__init__()
        self.key = key
        self.scale = 100.0 if key == "exposure" else 1.0
        lay = QGridLayout(self)
        lay.setContentsMargins(0, 2, 0 , 2)
        lay.setVerticalSpacing(1)
        self.name = QLabel(label)
        self.name.setToolTip(tooltip + "\n\nDouble-click the name to reset.")
        self.value = QLabel("0")
        self.value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.value.setMinimumWidth(44)
        self.slider = NoWheelSlider(Qt.Horizontal)
        self.slider.setRange(lo, hi)
        self.slider.setToolTip(tooltip)
        if key in SLIDER_GRADIENTS:
            self.slider.setStyleSheet(
                "QSlider::groove:horizontal { height: 4px; border-radius: 2px; background:"
                f" qlineargradient(x1:0, y1:0, x2:1, y2:0, {SLIDER_GRADIENTS[key]}); }}")
        lay.addWidget(self.name, 0, 0)
        lay.addWidget(self.value, 0, 1)
        lay.addWidget(self.slider, 1, 0, 1, 2)
        self.slider.valueChanged.connect(self._changed)
        self.name.mouseDoubleClickEvent = lambda e: self.slider.setValue(0)
        self.slider.mouseDoubleClickEvent = lambda e: self.slider.setValue(0)

    def _fmt(self, v):
        if self.scale != 1.0:
            return f"{v / self.scale:+.2f}" if v else "0.00"
        return f"{v:+d}" if v else "0"

    def _changed(self, v):
        self.value.setText(self._fmt(v))
        self.value.setStyleSheet("color: #6cb4ff;" if v else "")
        self.valueChanged.emit(self.key, v)

    def set_silently(self, v):
        self.slider.blockSignals(True)
        self.slider.setValue(v)
        self.slider.blockSignals(False)
        self.value.setText(self._fmt(v))
        self.value.setStyleSheet("color: #6cb4ff;" if v else "")


class Section(QWidget):
    def __init__(self, title, expanded=True):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.btn = QToolButton()
        self.btn.setText(title)
        self.btn.setCheckable(True)
        self.btn.setChecked(expanded)
        self.btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.btn.setObjectName("sectionHeader")
        self.btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.body = QWidget()
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(8, 4, 8, 8)
        self.body.setVisible(expanded)
        lay.addWidget(self.btn)
        lay.addWidget(self.body)
        self.btn.toggled.connect(self._toggle)

    def _toggle(self, on):
        self.body.setVisible(on)
        self.btn.setArrowType(Qt.DownArrow if on else Qt.RightArrow)


class AdjustPanel(QScrollArea):
    """Histogram, one-click presets, and develop sliders."""
    settingChanged = Signal(str, int)
    presetChosen = Signal(str)
    autoRequested = Signal()
    resetRequested = Signal()

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root = QWidget()
        lay = QVBoxLayout(root)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        self.histogram = Histogram()
        lay.addWidget(self.histogram)

        row = QHBoxLayout()
        self.auto_btn = QPushButton("✨ Auto Enhance")
        self.auto_btn.setObjectName("accent")
        self.auto_btn.setToolTip("Let PhotoForge fix brightness, contrast and color for you.\n"
                                 "You can fine-tune the result with the sliders below.")
        self.reset_btn = QPushButton("Reset All")
        self.reset_btn.setToolTip("Undo every slider and preset change (your layers stay as they are).")
        row.addWidget(self.auto_btn, 2)
        row.addWidget(self.reset_btn, 1)
        lay.addLayout(row)
        self.auto_btn.clicked.connect(self.autoRequested)
        self.reset_btn.clicked.connect(self.resetRequested)

        presets = Section("Presets — one-click looks")
        grid = QGridLayout()
        grid.setSpacing(4)
        self.preset_btns = {}
        for i, name in enumerate(adjustments.PRESETS):
            b = QToolButton()
            b.setText(name.replace("&", "&&"))
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setIconSize(QSize(84, 56))
            b.setFixedSize(QSize(96, 84))
            b.setToolTip(f"Apply the '{name}' look. This replaces your current slider settings.")
            b.setObjectName("preset")
            b.clicked.connect(lambda _=False, n=name: self.presetChosen.emit(n))
            grid.addWidget(b, i // 3, i % 3)
            self.preset_btns[name] = b
        presets.body_lay.addLayout(grid)
        lay.addWidget(presets)

        self.rows = {}
        sections = {}
        for sec, key, label, lo, hi, tip in adjustments.SLIDERS:
            if sec not in sections:
                sections[sec] = Section(sec, expanded=sec in ("Light", "Color"))
                lay.addWidget(sections[sec])
            r = SliderRow(key, label, lo, hi, tip)
            r.valueChanged.connect(self.settingChanged)
            sections[sec].body_lay.addWidget(r)
            self.rows[key] = r
        lay.addStretch(1)
        self.setWidget(root)

    def sync(self, settings):
        for k, r in self.rows.items():
            r.set_silently(settings.get(k, 0))

    def set_preset_thumbs(self, base):
        """base: small RGBA uint8 preview of the current photo."""
        for name, b in self.preset_btns.items():
            out = adjustments.apply(base, adjustments.preset_settings(name), 0.1)
            b.setIcon(QIcon(QPixmap.fromImage(imageio.to_qimage(out))))


class LayersPanel(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.doc = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)

        tip = QLabel("Layers stack like sheets of glass — the top one covers the ones below. "
                     "Tick the box to show/hide; double-click a name to rename.")
        tip.setWordWrap(True)
        tip.setObjectName("hintLabel")
        lay.addWidget(tip)

        props = QGridLayout()
        props.addWidget(QLabel("Blend"), 0, 0)
        self.blend = QComboBox()
        self.blend.addItems(BLEND_MODES)
        self.blend.setToolTip("How this layer mixes with the layers below it.\n"
                              "Multiply darkens, Screen lightens, Overlay adds contrast.")
        props.addWidget(self.blend, 0, 1)
        props.addWidget(QLabel("Opacity"), 1, 0)
        self.opacity = NoWheelSlider(Qt.Horizontal)
        self.opacity.setRange(0, 100)
        self.opacity.setToolTip("How see-through this layer is (100 = fully solid).")
        self.opacity_lbl = QLabel("100%")
        self.opacity_lbl.setMinimumWidth(40)
        props.addWidget(self.opacity, 1, 1)
        props.addWidget(self.opacity_lbl, 1, 2)
        lay.addLayout(props)

        self.list = QListWidget()
        self.list.setIconSize(QSize(56, 56))
        self.list.setSpacing(2)
        self.list.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        lay.addWidget(self.list, 1)

        btns = QHBoxLayout()
        self.actions = {}
        for key, text, tip in (("new", "+ New", "Add an empty transparent layer"),
                               ("dup", "Duplicate", "Copy the selected layer"),
                               ("up", "▲", "Move layer up"),
                               ("down", "▼", "Move layer down"),
                               ("merge", "Merge ↓", "Merge this layer into the one below"),
                               ("del", "Delete", "Delete the selected layer")):
            b = QPushButton(text)
            b.setToolTip(tip)
            btns.addWidget(b)
            self.actions[key] = b
        lay.addLayout(btns)

        self.list.currentRowChanged.connect(self._row_changed)
        self.list.itemChanged.connect(self._item_changed)
        self.opacity.valueChanged.connect(self._opacity_changed)
        self.blend.currentTextChanged.connect(self._blend_changed)
        self.setEnabled(False)

    def set_document(self, doc):
        self.doc = doc
        self.setEnabled(doc is not None)
        self.rebuild()

    def _index_for_row(self, row):
        return len(self.doc.layers) - 1 - row

    def _thumb(self, layer):
        if layer.thumb_src is not layer.pixels:
            t = imageio.thumbnail(layer.pixels, 56)
            layer.thumb = QIcon(QPixmap.fromImage(imageio.to_qimage(t)))
            layer.thumb_src = layer.pixels
        return layer.thumb

    def rebuild(self):
        self.list.blockSignals(True)
        self.list.clear()
        if self.doc:
            for layer in reversed(self.doc.layers):
                it = QListWidgetItem(self._thumb(layer), layer.name)
                it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsUserCheckable
                            | Qt.ItemIsEditable)
                it.setCheckState(Qt.Checked if layer.visible else Qt.Unchecked)
                it.setToolTip("Tick to show/hide. Double-click to rename.")
                self.list.addItem(it)
            self.list.setCurrentRow(len(self.doc.layers) - 1 - self.doc.active)
        self.list.blockSignals(False)
        self._sync_props()

    def _sync_props(self):
        layer = self.doc.active_layer() if self.doc else None
        for w in (self.opacity, self.blend):
            w.blockSignals(True)
        if layer:
            self.opacity.setValue(int(round(layer.opacity * 100)))
            self.opacity_lbl.setText(f"{int(round(layer.opacity * 100))}%")
            self.blend.setCurrentText(layer.blend)
        for w in (self.opacity, self.blend):
            w.blockSignals(False)
        if self.doc:
            self.actions["del"].setEnabled(len(self.doc.layers) > 1)
            self.actions["merge"].setEnabled(self.doc.active > 0)
            self.actions["up"].setEnabled(self.doc.active < len(self.doc.layers) - 1)
            self.actions["down"].setEnabled(self.doc.active > 0)

    def _row_changed(self, row):
        if self.doc and row >= 0:
            self.doc.active = self._index_for_row(row)
            self._sync_props()
            self.main.on_active_layer_changed()

    def _item_changed(self, it):
        i = self._index_for_row(self.list.row(it))
        layer = self.doc.layers[i]
        visible = it.checkState() == Qt.Checked
        name = it.text().strip() or layer.name
        if visible != layer.visible:
            self.doc.push_undo("Show/hide layer")
            layer.visible = visible
            self.doc.changed.emit("composite")
        elif name != layer.name:
            self.doc.push_undo("Rename layer")
            layer.name = name

    def _opacity_changed(self, v):
        layer = self.doc.active_layer()
        self.doc.push_undo("Layer opacity", coalesce=f"opacity{id(layer)}")
        layer.opacity = v / 100
        self.opacity_lbl.setText(f"{v}%")
        self.doc.changed.emit("composite")

    def _blend_changed(self, mode):
        self.doc.push_undo("Blend mode")
        self.doc.active_layer().blend = mode
        self.doc.changed.emit("composite")
