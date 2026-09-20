"""Right-hand side panels: Adjust (Lightroom-style develop) and Layers."""
import numpy as np
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QPushButton, QScrollArea, QSizePolicy, QSlider, QStackedWidget,
                               QToolButton, QVBoxLayout, QWidget)

from . import adjustments, curves, imageio
from .curves import CurveEditor
from .document import BLEND_MODES

SLIDER_GRADIENTS = {
    "temperature": "stop:0 #3b7dd8, stop:0.5 #cfcfcf, stop:1 #e8b923",
    "tint": "stop:0 #3fae49, stop:0.5 #cfcfcf, stop:1 #c440c9",
    "saturation": "stop:0 #8a8a8a, stop:1 #ff4f6e",
    "vibrance": "stop:0 #8a8a8a, stop:1 #ff9f1c",
    "exposure": "stop:0 #111111, stop:1 #ffffff",
}


def _add_mixer_gradients():
    """Paint each Color Mixer slider with the colors it actually produces."""
    bands = adjustments.MIXER_BANDS
    for i, (band, _label, _center, color) in enumerate(bands):
        prev_color, next_color = bands[i - 1][3], bands[(i + 1) % len(bands)][3]
        SLIDER_GRADIENTS[adjustments.mixer_key(band, "hue")] = \
            f"stop:0 {prev_color}, stop:0.5 {color}, stop:1 {next_color}"
        SLIDER_GRADIENTS[adjustments.mixer_key(band, "sat")] = f"stop:0 #8a8a8a, stop:1 {color}"
        SLIDER_GRADIENTS[adjustments.mixer_key(band, "lum")] = \
            f"stop:0 #111111, stop:0.5 {color}, stop:1 #ffffff"


_add_mixer_gradients()


def _swatch_style(color, edited):
    marker = "#6cb4ff" if edited else "#3a3a40"
    return (f"QToolButton {{ background: {color}; border: 2px solid {marker};"
            " border-radius: 5px; }"
            f"QToolButton:hover {{ background: {color}; border-color: #cfcfd4; }}"
            f"QToolButton:checked {{ background: {color}; border-color: #ffffff; }}")


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
        # A section is filled in after it is created, and Qt can keep the size it guessed
        # while the body was still empty — which squashed the sliders down to nothing.
        # Recompute once the whole panel has been built.
        QTimer.singleShot(0, self._relayout)

    def _relayout(self):
        self.body_lay.invalidate()
        self.body_lay.activate()

    def _toggle(self, on):
        self.body.setVisible(on)
        self.btn.setArrowType(Qt.DownArrow if on else Qt.RightArrow)


class AdjustPanel(QScrollArea):
    """Histogram, one-click presets, and develop sliders."""
    settingChanged = Signal(str, int)
    curveChanged = Signal(str, object)     # (curve settings key, control points)
    presetChosen = Signal(str)
    autoRequested = Signal()
    matchRequested = Signal()
    resetRequested = Signal()
    mixerResetRequested = Signal()
    curveResetRequested = Signal()
    hint = Signal(str)               # plain-English message for the status bar

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

        self.match_btn = QPushButton("🎨 Match Style from a Photo…")
        self.match_btn.setToolTip("Pick a photo you like the look of — PhotoForge copies its "
                                  "colours and tone onto this one.\nYou can fine-tune the "
                                  "result with the sliders and the Tone Curve afterwards.")
        self.match_btn.clicked.connect(self.matchRequested)
        lay.addWidget(self.match_btn)

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
                sections[sec] = Section(sec, expanded=sec in ("Light", "Color", "Tone Curve"))
                lay.addWidget(sections[sec])
            r = SliderRow(key, label, lo, hi, tip)
            r.valueChanged.connect(self.settingChanged)
            sections[sec].body_lay.addWidget(r)
            self.rows[key] = r
        self.mixer = self._build_color_mixer()
        lay.insertWidget(lay.indexOf(sections["Color"]) + 1, self.mixer)
        self._build_tone_curve(sections["Tone Curve"])
        lay.addStretch(1)
        self.setWidget(root)

    def _build_tone_curve(self, sec):
        """Tone Curve: a draggable curve plus the two beginner Lights/Darks sliders."""
        head = QWidget()
        hl = QVBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(4)
        intro = QLabel("Drag the line up to brighten, down to darken. The left of the line is "
                       "the dark parts of your photo, the right is the bright parts.")
        intro.setWordWrap(True)
        intro.setObjectName("hintLabel")
        hl.addWidget(intro)

        chans = QHBoxLayout()
        chans.setSpacing(4)
        self.curve_btns = []
        for i, (_key, label, color) in enumerate(curves.CHANNELS):
            b = QToolButton()
            b.setText(label)
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setChecked(i == 0)
            b.setToolTip("Change the brightness of the whole photo." if i == 0 else
                         f"Change only the {label.lower()} light in the photo — a quick way to "
                         f"warm it up, cool it down or add a colour tint.")
            b.setStyleSheet(f"QToolButton {{ padding: 2px 10px; color: {color}; }}"
                            "QToolButton:checked { background: #3d4f66; color: white;"
                            " border-radius: 4px; }")
            b.clicked.connect(lambda _=False, n=i: self.curve.set_channel(n))
            chans.addWidget(b)
            self.curve_btns.append(b)
        chans.addStretch(1)
        hl.addLayout(chans)

        self.curve = CurveEditor()
        self.curve.curveChanged.connect(self.curveChanged)
        self.curve.hint.connect(self.hint)
        hl.addWidget(self.curve)
        sec.body_lay.insertWidget(0, head)

        self.curve_reset_btn = QPushButton("Reset Tone Curve")
        tip = "Put the curve back to a straight line and Lights/Darks back to zero."
        self.curve_reset_btn.setToolTip(tip)
        self.curve_reset_btn.setStatusTip(tip)
        self.curve_reset_btn.clicked.connect(self.curveResetRequested)
        sec.body_lay.addWidget(self.curve_reset_btn)

    def _build_color_mixer(self):
        """Color Mixer (HSL): pick one of eight colors, then bend only that color."""
        sec = Section("Color Mixer — tune one color at a time")
        intro = QLabel("Pick a color, then move the sliders to change only that color "
                       "in your photo — everything else stays as it is.")
        intro.setWordWrap(True)
        intro.setObjectName("hintLabel")
        sec.body_lay.addWidget(intro)

        swatches = QHBoxLayout()
        swatches.setSpacing(4)
        self.mixer_swatches = {}
        self.mixer_pages = {}
        self.mixer_stack = QStackedWidget()
        for band, label, _center, color in adjustments.MIXER_BANDS:
            tip = f"Edit the {label.lower()} parts of the photo. Nothing else is touched."
            b = QToolButton()
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setFixedSize(QSize(32, 24))
            b.setToolTip(f"{label}\n\n{tip}")
            b.setStatusTip(tip)
            b.setProperty("edited", False)
            b.setStyleSheet(_swatch_style(color, False))
            b.clicked.connect(lambda _=False, n=band: self._mixer_band_chosen(n))
            swatches.addWidget(b)
            self.mixer_swatches[band] = b

            page = QWidget()
            page_lay = QVBoxLayout(page)
            page_lay.setContentsMargins(0, 0, 0, 0)
            page_lay.setSpacing(0)
            for channel, ch_label, ch_tip in adjustments.MIXER_CHANNELS:
                key = adjustments.mixer_key(band, channel)
                lo, hi = adjustments.MIXER_RANGE
                tooltip = ch_tip.format(c=label.lower())
                r = SliderRow(key, f"{label} {ch_label}", lo, hi, tooltip)
                r.slider.setStatusTip(tooltip)
                r.valueChanged.connect(self.settingChanged)
                page_lay.addWidget(r)
                self.rows[key] = r
            self.mixer_stack.addWidget(page)
            self.mixer_pages[band] = page
        swatches.addStretch(1)
        sec.body_lay.addLayout(swatches)
        sec.body_lay.addWidget(self.mixer_stack)

        self.mixer_reset_btn = QPushButton("Reset Color Mixer")
        reset_tip = "Put every Color Mixer slider back to zero (one undo step)."
        self.mixer_reset_btn.setToolTip(reset_tip)
        self.mixer_reset_btn.setStatusTip(reset_tip)
        self.mixer_reset_btn.clicked.connect(self.mixerResetRequested)
        sec.body_lay.addWidget(self.mixer_reset_btn)

        first = adjustments.MIXER_BANDS[0][0]
        self.mixer_swatches[first].setChecked(True)
        return sec

    def _mixer_band_chosen(self, band):
        label = next(b[1] for b in adjustments.MIXER_BANDS if b[0] == band)
        self.mixer_stack.setCurrentWidget(self.mixer_pages[band])
        self.hint.emit(f"Color Mixer: editing {label}. Hue changes the shade, Saturation how "
                       f"strong it is, Luminance how bright — only for {label.lower()} areas.")

    def sync(self, settings):
        for k, r in self.rows.items():
            r.set_silently(settings.get(k, 0))
        self._sync_mixer_swatches(settings)
        self.curve.sync(settings)

    def _sync_mixer_swatches(self, settings):
        """Outline the swatches of colors that have been edited, so nothing is hidden."""
        for band, _label, _center, color in adjustments.MIXER_BANDS:
            edited = any(settings.get(adjustments.mixer_key(band, c[0]), 0)
                         for c in adjustments.MIXER_CHANNELS)
            btn = self.mixer_swatches[band]
            if btn.property("edited") != edited:  # restyling on every slider tick is wasteful
                btn.setProperty("edited", edited)
                btn.setStyleSheet(_swatch_style(color, edited))

    def set_preset_thumbs(self, base):
        """base: small RGBA uint8 preview of the current photo."""
        for name, b in self.preset_btns.items():
            out = adjustments.apply(base, adjustments.preset_settings(name), 0.1)
            b.setIcon(QIcon(QPixmap.fromImage(imageio.to_qimage(out))))


def mask_qimage(mask):
    """A layer mask (HxW uint8) as a grey RGBA QImage for thumbnails."""
    grey = np.dstack([mask, mask, mask, np.full(mask.shape, 255, np.uint8)])
    return imageio.to_qimage(grey)


class LayersPanel(QWidget):
    maskAction = Signal(str)         # "add" / "from_selection" / "invert" / "delete" / "apply"
    maskPaintToggled = Signal(bool)

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
        lay.addWidget(self._build_mask_box())

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

        self.mask_paint.toggled.connect(self.maskPaintToggled)
        self.list.currentRowChanged.connect(self._row_changed)
        self.list.itemChanged.connect(self._item_changed)
        self.opacity.valueChanged.connect(self._opacity_changed)
        self.blend.currentTextChanged.connect(self._blend_changed)
        self.setEnabled(False)

    def set_document(self, doc):
        self.doc = doc
        self.setEnabled(doc is not None)
        self.rebuild()

    def _build_mask_box(self):
        """Layer mask controls: a mask hides parts of a layer without erasing them."""
        box = QFrame()
        box.setObjectName("maskBox")
        outer = QVBoxLayout(box)
        outer.setContentsMargins(6, 4, 6, 6)
        outer.setSpacing(4)
        tip = QLabel("A mask hides parts of this layer instead of deleting them — paint it "
                     "back whenever you like.")
        tip.setWordWrap(True)
        tip.setObjectName("hintLabel")
        outer.addWidget(tip)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.mask_thumb = QLabel()
        self.mask_thumb.setFixedSize(44, 44)
        self.mask_thumb.setAlignment(Qt.AlignCenter)
        self.mask_thumb.setObjectName("maskThumb")
        self.mask_thumb.setToolTip("The mask: white areas of the layer show, black areas hide.")
        row.addWidget(self.mask_thumb)
        self.mask_btns = {}
        grid = QGridLayout()
        grid.setSpacing(4)
        for i, (key, text, tip_text) in enumerate((
                ("add", "Add Mask", "Give this layer a mask. Nothing changes until you paint "
                                    "on it or use Hide."),
                ("from_selection", "From Selection", "Turn the current selection into a mask: "
                                                     "what you selected stays visible."),
                ("invert", "Invert", "Swap what is hidden and what is shown."),
                ("delete", "Delete", "Throw the mask away — the whole layer comes back."),
                ("apply", "Apply", "Make the mask permanent: the hidden parts are erased for "
                                   "good and the mask disappears."))):
            b = QPushButton(text)
            b.setToolTip(tip_text)
            b.setStatusTip(tip_text)
            b.clicked.connect(lambda _=False, k=key: self.maskAction.emit(k))
            grid.addWidget(b, i // 3, i % 3)
            self.mask_btns[key] = b
        row.addLayout(grid, 1)
        outer.addLayout(row)

        self.mask_paint = QCheckBox("Paint on the mask (Brush hides · Eraser brings back)")
        self.mask_paint.setToolTip("While this is ticked the Brush paints the mask instead of "
                                   "the photo: brush over something to hide it, then use the "
                                   "Eraser to bring it back.")
        outer.addWidget(self.mask_paint)
        return box

    def _index_for_row(self, row):
        return len(self.doc.layers) - 1 - row

    def _thumb(self, layer):
        """The list icon: the layer, plus its mask beside it when it has one."""
        if layer.thumb_src is not layer.pixels:
            t = imageio.thumbnail(layer.pixels, 56)
            layer.thumb = QPixmap.fromImage(imageio.to_qimage(t))
            layer.thumb_src = layer.pixels
        if layer.mask is None:
            layer.mask_thumb, layer.mask_thumb_src = None, None
            return QIcon(layer.thumb)
        if layer.mask_thumb_src is not layer.mask:
            t = imageio.thumbnail(layer.mask, 56)
            layer.mask_thumb = QPixmap.fromImage(mask_qimage(t))
            layer.mask_thumb_src = layer.mask
        pair = QPixmap(120, 56)
        pair.fill(Qt.transparent)
        p = QPainter(pair)
        p.drawPixmap(0, (56 - layer.thumb.height()) // 2, layer.thumb)
        p.setPen(QColor(120, 120, 128))
        p.drawLine(60, 4, 60, 52)
        p.drawPixmap(64, (56 - layer.mask_thumb.height()) // 2, layer.mask_thumb)
        p.end()
        return QIcon(pair)

    def rebuild(self):
        self.list.blockSignals(True)
        self.list.clear()
        if self.doc:
            any_mask = any(l.mask is not None for l in self.doc.layers)
            self.list.setIconSize(QSize(120 if any_mask else 56, 56))
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
        self._sync_mask(layer)
        if self.doc:
            self.actions["del"].setEnabled(len(self.doc.layers) > 1)
            self.actions["merge"].setEnabled(self.doc.active > 0)
            self.actions["up"].setEnabled(self.doc.active < len(self.doc.layers) - 1)
            self.actions["down"].setEnabled(self.doc.active > 0)

    def _sync_mask(self, layer):
        has = layer is not None and layer.mask is not None
        for key, b in self.mask_btns.items():
            if key == "add":
                b.setEnabled(layer is not None and not has)
            elif key == "from_selection":
                b.setEnabled(layer is not None and self.doc is not None
                             and self.doc.selection is not None)
            else:
                b.setEnabled(has)
        self.mask_paint.setEnabled(has)
        if not has and self.mask_paint.isChecked():
            self.mask_paint.setChecked(False)
        if has:
            t = imageio.thumbnail(layer.mask, 40)
            self.mask_thumb.setPixmap(QPixmap.fromImage(mask_qimage(t)))
        else:
            self.mask_thumb.clear()

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
