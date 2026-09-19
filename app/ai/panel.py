"""The "AI" tab in the right-hand panel."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QFrame, QLabel, QPushButton, QScrollArea, QVBoxLayout,
                               QWidget)

from . import models


class _Card(QFrame):
    def __init__(self, title, body):
        super().__init__()
        self.setObjectName("aiCard")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(12, 10, 12, 12)
        t = QLabel(title)
        t.setObjectName("aiCardTitle")
        b = QLabel(body)
        b.setWordWrap(True)
        b.setObjectName("hintLabel")
        self.lay.addWidget(t)
        self.lay.addWidget(b)


class AIPanel(QScrollArea):
    removeBackground = Signal()
    refineOutline = Signal()
    removeObject = Signal()

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root = QWidget()
        lay = QVBoxLayout(root)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(10)

        intro = QLabel("These AI tools run on your own computer. They're free and private, "
                       "and each model downloads once the first time you use it.")
        intro.setWordWrap(True)
        intro.setObjectName("hintLabel")
        lay.addWidget(intro)

        c = _Card("Remove Background",
                  "Finds the main subject and removes everything behind it. The result goes "
                  "on a new layer; your original is kept (hidden) underneath.")
        self.bg_btn = QPushButton("Remove Background")
        self.bg_btn.setObjectName("accent")
        self.bg_btn.clicked.connect(self.removeBackground)
        self.refine_btn = QPushButton("Refine Outline…")
        self.refine_btn.setToolTip("Adjust exactly what is kept: drag the dots, click a line "
                                   "to add a dot, or add more points for detail.")
        self.refine_btn.clicked.connect(self.refineOutline)
        self.edges = QComboBox()
        self.edges.addItem("Edges: Natural (best for hair and fur)", "natural")
        self.edges.addItem("Edges: Crisp (best for hands and objects)", "crisp")
        self.edges.setToolTip("Natural keeps soft, see-through edges like wisps of hair.\n"
                              "Crisp makes edges solid, so hands and objects don't look faded.")
        c.lay.addWidget(self.edges)
        c.lay.addWidget(self.bg_btn)
        c.lay.addWidget(self.refine_btn)
        lay.addWidget(c)

        c = _Card("Remove Object",
                  "Click dots around something you want gone (a person, a sign, a power line), "
                  "then click Remove Object. The AI fills the gap with matching background.")
        self.obj_btn = QPushButton("Outline an Object to Remove")
        self.obj_btn.setObjectName("accent")
        self.obj_btn.clicked.connect(self.removeObject)
        self.quality = QComboBox()
        self.quality.addItem("Best quality (LaMa)", "best")
        self.quality.addItem("Fast: for slower computers (MI-GAN)", "fast")
        self.quality.setToolTip("Best quality looks more natural. Fast is quicker and uses a "
                                "smaller download.")
        c.lay.addWidget(self.obj_btn)
        c.lay.addWidget(self.quality)
        lay.addWidget(c)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setObjectName("hintLabel")
        lay.addWidget(self.status)
        lay.addStretch(1)
        self.setWidget(root)
        self.refresh()

    def refresh(self):
        lines = [f"Runs on: your {models.device_name()}"]
        for m in models.MODELS.values():
            state = "✓ downloaded" if models.is_downloaded(m.key) else f"{m.size_mb} MB download"
            lines.append(f"• {m.name}: {state}")
        self.status.setText("\n".join(lines))
