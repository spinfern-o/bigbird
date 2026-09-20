"""The Local tab: Graduated and Radial filters that only affect part of the photo."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QHBoxLayout, QLabel, QListWidget,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from . import adjustments, local_adjust
from .panels import NoWheelSlider, SliderRow


class LocalPanel(QScrollArea):
    """Pick a filter, then move the sliders — they only change the area you marked."""
    addRequested = Signal(str)        # "linear" / "radial"
    chosen = Signal(int)
    settingChanged = Signal(str, int)
    optionChanged = Signal(str, int)  # "feather" / "invert"
    deleteRequested = Signal()
    hint = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._syncing = False
        root = QWidget()
        lay = QVBoxLayout(root)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        intro = QLabel("Change just one part of the photo. A <b>Graduated filter</b> fades across "
                       "the picture — perfect for darkening a bright sky. A <b>Radial filter</b> "
                       "affects an oval — perfect for brightening a face.")
        intro.setWordWrap(True)
        intro.setObjectName("hintLabel")
        lay.addWidget(intro)

        row = QHBoxLayout()
        for kind, text, tip in (
                ("linear", "+ Graduated", "Then drag across the photo, from where the effect "
                                          "should be strongest to where it should fade away."),
                ("radial", "+ Radial", "Then drag on the photo to draw an oval around the part "
                                       "you want to change.")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setStatusTip(tip)
            b.clicked.connect(lambda _=False, k=kind: self.addRequested.emit(k))
            row.addWidget(b)
        lay.addLayout(row)

        self.list = QListWidget()
        self.list.setMaximumHeight(110)
        self.list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.list.setToolTip("Your filters. Click one to edit it; drag its dots on the photo to "
                             "move or resize it.")
        self.list.currentRowChanged.connect(self._row_changed)
        lay.addWidget(self.list)

        opts = QHBoxLayout()
        self.invert = QCheckBox("Flip which side is affected")
        self.invert.setToolTip("Swap the area this filter changes for everything else.")
        self.invert.toggled.connect(lambda on: self._option("invert", int(on)))
        opts.addWidget(self.invert)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setToolTip("Remove the selected filter (Ctrl+Z brings it back).")
        self.delete_btn.clicked.connect(self.deleteRequested)
        opts.addWidget(self.delete_btn)
        lay.addLayout(opts)

        feather = QHBoxLayout()
        feather.addWidget(QLabel("Softness"))
        self.feather = NoWheelSlider(Qt.Horizontal)
        self.feather.setRange(0, 100)
        self.feather.setValue(100)
        self.feather.setToolTip("How gradually the effect fades out at the edge. High is soft "
                                "and invisible; low gives a sharper edge.")
        self.feather.valueChanged.connect(lambda v: self._option("feather", v))
        feather.addWidget(self.feather, 1)
        self.feather_lbl = QLabel("100%")
        self.feather_lbl.setMinimumWidth(42)
        feather.addWidget(self.feather_lbl)
        lay.addLayout(feather)

        self.rows = {}
        by_key = {k: (label, lo, hi, tip) for _sec, k, label, lo, hi, tip in adjustments.SLIDERS}
        for key in local_adjust.LOCAL_KEYS:
            label, lo, hi, tip = by_key[key]
            r = SliderRow(key, label, lo, hi, tip + "\n\nHere it only affects the filter's area.")
            r.valueChanged.connect(self._slider_changed)
            lay.addWidget(r)
            self.rows[key] = r
        lay.addStretch(1)
        self.setWidget(root)
        self.sync(None, -1)

    def _row_changed(self, row):
        if not self._syncing:
            self.chosen.emit(row)

    def _slider_changed(self, key, value):
        if not self._syncing:
            self.settingChanged.emit(key, value)

    def _option(self, name, value):
        """Ignore the value changes that sync() itself makes, or every redraw is an edit."""
        if name == "feather":
            self.feather_lbl.setText(f"{value}%")
        if not self._syncing:
            self.optionChanged.emit(name, value)

    def sync(self, settings, index):
        """Redraw the list and show the selected filter's values."""
        self._syncing = True
        locs = list((settings or {}).get(local_adjust.KEY, ()))
        self.list.clear()
        for i, loc in enumerate(locs):
            self.list.addItem(local_adjust.describe(loc, i))
        if not locs:
            self.list.addItem("No filters yet — add one above, then drag on the photo.")
            self.list.item(0).setFlags(Qt.NoItemFlags)
        elif 0 <= index < len(locs):
            self.list.setCurrentRow(index)
        loc = locs[index] if 0 <= index < len(locs) else None
        for key, r in self.rows.items():
            r.set_silently((loc or {}).get("settings", {}).get(key, 0))
            r.setEnabled(loc is not None)
        self.feather.setValue(int((loc or {}).get("feather", 100)))
        self.feather_lbl.setText(f"{self.feather.value()}%")
        self.invert.setChecked(bool((loc or {}).get("invert", False)))
        for wdg in (self.feather, self.invert, self.delete_btn):
            wdg.setEnabled(loc is not None)
        self._syncing = False
