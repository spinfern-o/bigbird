"""The "Select" tab: what you can do with a selection (retouch, modify, actions)."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QSpinBox, QVBoxLayout, QWidget)

from .panels import NoWheelSlider


class _Card(QFrame):
    def __init__(self, title, body=None):
        super().__init__()
        self.setObjectName("aiCard")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(12, 10, 12, 12)
        t = QLabel(title)
        t.setObjectName("aiCardTitle")
        self.lay.addWidget(t)
        if body:
            b = QLabel(body)
            b.setWordWrap(True)
            b.setObjectName("hintLabel")
            self.lay.addWidget(b)


def _slider(lay, label, lo, hi, val, tip, suffix=""):
    row = QHBoxLayout()
    name = QLabel(label)
    name.setMinimumWidth(92)
    s = NoWheelSlider(Qt.Horizontal)
    s.setRange(lo, hi)
    s.setValue(val)
    s.setToolTip(tip)
    v = QLabel(f"{val}{suffix}")
    v.setMinimumWidth(34)
    s.valueChanged.connect(lambda x: v.setText(f"{x}{suffix}"))
    row.addWidget(name)
    row.addWidget(s, 1)
    row.addWidget(v)
    lay.addLayout(row)
    return s


class SelectionPanel(QScrollArea):
    # Every button emits `action` with a command name, handled by the main window.
    action = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root = QWidget()
        lay = QVBoxLayout(root)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(10)
        self.needs_sel = []

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setObjectName("hintLabel")
        lay.addWidget(self.status)

        def btn(text, cmd, tip, accent=False, needs=True):
            b = QPushButton(text)
            b.setToolTip(tip)
            if accent:
                b.setObjectName("accent")
            b.clicked.connect(lambda: self.action.emit(cmd))
            if needs:
                self.needs_sel.append(b)
            return b

        # ---- make a selection
        c = _Card("Make a Selection",
                  "Use Lasso (L), Magic Wand (W) or Marquee (M), or let PhotoForge pick for you. "
                  "Shift adds to a selection, Alt subtracts.")
        g = QGridLayout()
        g.addWidget(btn("Select Subject", "subject", "AI: select the main subject", needs=False), 0, 0)
        g.addWidget(btn("Skin Tones", "skin", "Select all skin-colored areas (great before "
                                              "Smooth Skin)", needs=False), 0, 1)
        g.addWidget(btn("Select All", "all", "Select the whole image (Ctrl+A)", needs=False), 1, 0)
        g.addWidget(btn("Deselect", "deselect", "Clear the selection (Ctrl+D)"), 1, 1)
        g.addWidget(btn("Inverse", "inverse", "Swap selected and unselected areas "
                                              "(Ctrl+Shift+I)"), 2, 0)
        g.addWidget(btn("Refine Edge…", "refine", "Adjust the selection edge with draggable dots"),
                    2, 1)
        c.lay.addLayout(g)
        lay.addWidget(c)

        # ---- retouch
        c = _Card("Retouch",
                  "Works inside the selection on the selected layer. Tip: select a face with "
                  "Lasso, or click Skin Tones, then use these.")
        self.spot = _slider(c.lay, "Spot size", 1, 10, 4,
                            "How big the blemishes are. Raise it for bigger spots or scars.")
        self.sens = _slider(c.lay, "Sensitivity", 0, 100, 50,
                            "Higher finds fainter spots; lower only removes obvious ones.")
        c.lay.addWidget(btn("Remove Blemishes", "blemishes",
                            "Find and remove acne, spots and small marks automatically",
                            accent=True))
        c.lay.addSpacing(6)
        self.smooth_amt = _slider(c.lay, "Smoothness", 0, 100, 50, "How much to smooth the skin.")
        self.texture = _slider(c.lay, "Keep texture", 0, 100, 40,
                               "Keeps natural pores so skin doesn't look plastic.")
        c.lay.addWidget(btn("Smooth Skin", "smooth_skin",
                            "Even out skin while keeping edges (eyes, lips) sharp"))
        c.lay.addSpacing(6)
        self.red_amt = _slider(c.lay, "Redness", 0, 100, 60, "How much redness to calm.")
        c.lay.addWidget(btn("Reduce Redness", "redness",
                            "Calm red, blotchy skin (acne redness, irritation)"))
        c.lay.addSpacing(6)
        c.lay.addWidget(btn("Heal Selection", "heal",
                            "Remove whatever is selected (a scar, mark or small object) by "
                            "blending in the surrounding texture"))
        tip = QLabel("For single spots, the Spot Healing Brush (J) is quickest: just paint over "
                     "the spot.")
        tip.setWordWrap(True)
        tip.setObjectName("hintLabel")
        c.lay.addWidget(tip)
        lay.addWidget(c)

        # ---- modify
        c = _Card("Modify Selection")
        row = QHBoxLayout()
        row.addWidget(QLabel("By"))
        self.amount = QSpinBox()
        self.amount.setRange(1, 500)
        self.amount.setValue(5)
        self.amount.setSuffix(" px")
        row.addWidget(self.amount)
        row.addStretch(1)
        c.lay.addLayout(row)
        g = QGridLayout()
        g.addWidget(btn("Feather", "feather", "Soften the selection edge"), 0, 0)
        g.addWidget(btn("Smooth", "smooth", "Round off jagged edges and remove specks"), 0, 1)
        g.addWidget(btn("Expand", "expand", "Grow the selection outward"), 1, 0)
        g.addWidget(btn("Contract", "contract", "Shrink the selection inward"), 1, 1)
        g.addWidget(btn("Border", "border", "Select a band along the edge"), 2, 0)
        c.lay.addLayout(g)
        lay.addWidget(c)

        # ---- actions
        c = _Card("Selection Actions")
        g = QGridLayout()
        g.addWidget(btn("Layer via Copy", "via_copy", "Copy the selection to a new layer (Ctrl+J)"),
                    0, 0)
        g.addWidget(btn("Layer via Cut", "via_cut", "Move the selection to a new layer "
                                                    "(Ctrl+Shift+J)"), 0, 1)
        g.addWidget(btn("Delete", "delete", "Erase the selected pixels (Delete)"), 1, 0)
        g.addWidget(btn("Fill…", "fill", "Fill the selection with a color"), 1, 1)
        g.addWidget(btn("Stroke…", "stroke", "Draw a colored outline along the selection"), 2, 0)
        g.addWidget(btn("Crop to Selection", "crop", "Crop the image to the selection"), 2, 1)
        c.lay.addLayout(g)
        note = QLabel("Filters, Brush and Eraser also only affect the selection while one is "
                      "active.")
        note.setWordWrap(True)
        note.setObjectName("hintLabel")
        c.lay.addWidget(note)
        lay.addWidget(c)
        lay.addStretch(1)
        self.setWidget(root)
        self.set_selection_info(None)

    def set_selection_info(self, info):
        has = info is not None
        for b in self.needs_sel:
            b.setEnabled(has)
        if has:
            w, h, pct = info
            self.status.setText(f"Selection: {w} × {h} px area, {pct:.1f}% of the image.")
        else:
            self.status.setText("Nothing selected yet. Choose Lasso (L), Magic Wand (W) or "
                                "Marquee (M) on the left, or use a button below.")
