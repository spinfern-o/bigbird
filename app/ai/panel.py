"""The "AI" tab in the right-hand panel."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QSpinBox, QVBoxLayout, QWidget)

from . import cloud, models


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
    refineRemoval = Signal()
    fillRemoved = Signal()
    openSettings = Signal()

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
        row = QHBoxLayout()
        row.addWidget(QLabel("Outline points for refining"))
        self.points = QSpinBox()
        self.points.setRange(8, 5000)
        self.points.setSingleStep(25)
        self.points.setValue(150)
        self.points.setToolTip("How many dots Refine Outline starts with. More dots follow the "
                               "edge closely; fewer are quicker to adjust. You can also change "
                               "it while refining.")
        row.addWidget(self.points)
        c.lay.addWidget(self.edges)
        c.lay.addWidget(self.bg_btn)
        c.lay.addLayout(row)
        c.lay.addWidget(self.refine_btn)
        lay.addWidget(c)

        c = _Card("Remove Objects",
                  "Click the objects you want gone (a person, a sign, a bin) and the AI finds "
                  "their outlines. They're cut out so the layer below shows through, and you can "
                  "fine-tune the outline afterwards.")
        self.obj_btn = QPushButton("Select Object(s) to Remove")
        self.obj_btn.setObjectName("accent")
        self.obj_btn.clicked.connect(self.removeObject)
        self.fill_btn = QPushButton("Fill Removed Area (cloud GPU)")
        self.fill_btn.setToolTip("Fill the transparent gap left by removed objects with matching "
                                 "background. Runs on your NVIDIA cloud GPU.")
        self.fill_btn.clicked.connect(self.fillRemoved)
        row = QHBoxLayout()
        row.addWidget(QLabel("Outline points for refining"))
        self.removal_points = QSpinBox()
        self.removal_points.setRange(8, 5000)
        self.removal_points.setSingleStep(25)
        self.removal_points.setValue(150)
        self.removal_points.setToolTip("How many dots Refine Removal starts with. You can also "
                                       "change it while refining.")
        row.addWidget(self.removal_points)
        self.refine_removal_btn = QPushButton("Refine Removal…")
        self.refine_removal_btn.setToolTip("Adjust exactly what was removed: drag the dots, click "
                                           "a line to add a dot, or change the number of points.")
        self.refine_removal_btn.clicked.connect(self.refineRemoval)
        c.lay.addWidget(self.obj_btn)
        c.lay.addLayout(row)
        c.lay.addWidget(self.refine_removal_btn)
        c.lay.addWidget(self.fill_btn)
        lay.addWidget(c)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setObjectName("hintLabel")
        lay.addWidget(self.status)
        settings = QPushButton("AI Settings… (this computer or NVIDIA cloud GPU)")
        settings.clicked.connect(self.openSettings)
        lay.addWidget(settings)
        lay.addStretch(1)
        self.setWidget(root)
        self.refresh()

    def refresh(self):
        if cloud.use_cloud():
            lines = [f"Heavy AI runs on: your NVIDIA cloud GPU ({cloud.get_settings()['url']})"]
        else:
            lines = [f"Runs on: your {models.device_name()}"]
        for m in models.MODELS.values():
            if m.server_only:
                continue
            state = "✓ downloaded" if models.is_downloaded(m.key) else f"{m.size_mb} MB download"
            lines.append(f"• {m.name}: {state}")
        self.status.setText("\n".join(lines))
