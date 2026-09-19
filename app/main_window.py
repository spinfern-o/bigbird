import os

import numpy as np

from PySide6.QtCore import QSize, Qt, QThreadPool, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QImage, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDockWidget, QFileDialog, QHBoxLayout,
                               QInputDialog, QLabel, QMainWindow, QMessageBox, QPushButton,
                               QSizePolicy, QSlider, QStackedWidget, QTabWidget, QToolBar, QVBoxLayout, QWidget)

from . import adjustments, filters, imageio
from .canvas import Canvas, ToolState
from .dialogs import ExportDialog, NewImageDialog, ResizeDialog, TextDialog
from .document import Document
from .icons import tool_icon
from .panels import AdjustPanel, ColorButton, LayersPanel, NoWheelSlider
from .renderer import Renderer
from .ai import models as ai_models, tasks as ai_tasks
from .ai.outline import OutlineEditor, merge_refined, trace_mask
from .ai.panel import AIPanel
from .ai.runner import run_ai

APP_NAME = "PhotoForge"

TOOLS = [
    ("hand", "Pan", "H", "Pan (H): drag to move around the photo. Scroll the mouse wheel to zoom.\n"
                          "Tip: hold Space with any tool to pan temporarily."),
    ("move", "Move", "V", "Move (V): drag to move the selected layer — great for text or pasted images."),
    ("brush", "Brush", "B", "Brush (B): paint on the selected layer. Use [ and ] to change the size."),
    ("eraser", "Eraser", "E", "Eraser (E): erase parts of the selected layer to reveal what's below."),
    ("crop", "Crop", "C", "Crop (C): drag a box around the part you want to keep, then press Enter."),
    ("eyedropper", "Picker", "I", "Color Picker (I): click the photo to pick up a color for the brush."),
    ("text", "Text", "T", "Text (T): click where you want to add text."),
    ("ai_remove", "Remove", "R", "Remove Object (R): click dots around something to erase it, "
                                 "then press Enter. AI fills in the background."),
]
TOOL_HINTS = {k: tip for k, _, _, tip in TOOLS}
TOOL_HINTS["ai_refine"] = ("Refine Outline: the bright area is kept, the darkened area is "
                           "removed. Drag dots, click a line to add a dot, right-click a dot to "
                           "delete it. Press Enter to apply.")
OUTLINE_TOOLS = ("ai_remove", "ai_refine")

CROP_RATIOS = [("Free", None), ("Original", "orig"), ("Square 1:1", 1.0), ("Portrait 4:5", 0.8),
               ("Photo 3:2", 1.5), ("Photo 2:3", 2 / 3), ("Wide 16:9", 16 / 9), ("Tall 9:16", 9 / 16)]


class WelcomeWidget(QWidget):
    def __init__(self, main):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addStretch(2)
        title = QLabel(APP_NAME)
        title.setObjectName("welcomeTitle")
        title.setAlignment(Qt.AlignCenter)
        sub = QLabel("Edit your photos like a pro — no experience needed.")
        sub.setObjectName("welcomeSub")
        sub.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)
        lay.addWidget(sub)
        lay.addSpacing(24)
        row = QHBoxLayout()
        row.addStretch(1)
        open_btn = QPushButton("📂  Open a Photo…")
        open_btn.setObjectName("bigAccent")
        new_btn = QPushButton("＋  New Blank Canvas…")
        new_btn.setObjectName("big")
        open_btn.clicked.connect(main.open_file)
        new_btn.clicked.connect(main.new_image)
        row.addWidget(open_btn)
        row.addSpacing(12)
        row.addWidget(new_btn)
        row.addStretch(1)
        lay.addLayout(row)
        drop = QLabel("…or drag and drop a photo anywhere onto this window")
        drop.setObjectName("welcomeHint")
        drop.setAlignment(Qt.AlignCenter)
        lay.addSpacing(10)
        lay.addWidget(drop)
        lay.addSpacing(36)

        steps = QHBoxLayout()
        steps.addStretch(1)
        for n, head, body in (("1", "Open", "Open a photo (JPG, PNG, even camera RAW)."),
                              ("2", "Pick a look", "Click a Preset or ✨ Auto Enhance."),
                              ("3", "Fine-tune", "Drag sliders. Hover anything for help."),
                              ("4", "Export", "Save a copy — your original is never changed.")):
            card = QLabel(f"<div style='font-size:22px; color:#6cb4ff'><b>{n}</b></div>"
                          f"<b>{head}</b><br><span style='color:#aaa'>{body}</span>")
            card.setObjectName("stepCard")
            card.setWordWrap(True)
            card.setFixedWidth(180)
            card.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            steps.addWidget(card)
        steps.addStretch(1)
        lay.addLayout(steps)
        lay.addStretch(3)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.resize(1440, 900)
        self.setAcceptDrops(True)
        self.doc = None
        self.state = ToolState()
        self._moving = False

        self.canvas = Canvas(self.state)
        self.renderer = Renderer(self.canvas)
        self.welcome = WelcomeWidget(self)
        self.center = QStackedWidget()
        self.center.addWidget(self.welcome)
        self.center.addWidget(self.canvas)
        self.setCentralWidget(self.center)

        self.adjust_panel = AdjustPanel()
        self.layers_panel = LayersPanel(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.adjust_panel, "Adjust")
        self.tabs.addTab(self.layers_panel, "Layers")
        self.ai_panel = AIPanel()
        self.tabs.addTab(self.ai_panel, "AI")
        self.tabs.setMinimumWidth(372)
        self.tabs.setMaximumWidth(420)
        side = QDockWidget("Panels", self)
        side.setWidget(self.tabs)
        side.setTitleBarWidget(QWidget())
        side.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self.addDockWidget(Qt.RightDockWidgetArea, side)

        self._thumb_timer = QTimer(self, singleShot=True, interval=400)
        self._thumb_timer.timeout.connect(self._update_preset_thumbs)

        self._build_actions()
        self._build_menus()
        self._build_toolbars()
        self._build_statusbar()
        self._connect()
        self._build_ai()
        self.set_document(None)
        self.select_tool("hand")

    # ================================================================== UI construction
    def _act(self, text, slot, shortcut=None, tip=None, checkable=False):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if tip:
            a.setToolTip(tip)
            a.setStatusTip(tip)
        a.setCheckable(checkable)
        a.triggered.connect(slot)
        return a

    def _build_actions(self):
        A = self._act
        self.a_new = A("New Blank Canvas…", self.new_image, "Ctrl+N")
        self.a_open = A("Open…", self.open_file, "Ctrl+O", "Open a photo or project")
        self.a_place = A("Add Photo as Layer…", self.place_image, "Ctrl+Shift+O",
                         "Put another photo on top of this one as a new layer")
        self.a_save = A("Save Project", self.save_project, "Ctrl+S",
                        "Save everything (layers + edits) so you can keep working later")
        self.a_save_as = A("Save Project As…", lambda: self.save_project(True), "Ctrl+Shift+S")
        self.a_export = A("Export Image…", self.export_image, "Ctrl+E",
                          "Save a finished JPG/PNG to share or print")
        self.a_quit = A("Exit", self.close, "Ctrl+Q")
        self.a_undo = A("Undo", self.undo, QKeySequence.Undo, "Undo the last change (Ctrl+Z)")
        self.a_redo = A("Redo", self.redo, "Ctrl+Y", "Redo (Ctrl+Y)")
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, self.redo)
        self.a_reset = A("Reset All Adjustments", self.reset_adjustments)
        self.a_auto = A("✨ Auto Enhance", self.auto_enhance, "Ctrl+Shift+A",
                        "Automatically improve brightness, contrast and color")
        self.a_compare = A("Before / After", self.toggle_compare, "\\",
                           "Show the original photo without adjustments (\\)", checkable=True)
        self.a_fit = A("Fit on Screen", lambda: self.canvas.fit(), "Ctrl+0")
        self.a_100 = A("Actual Pixels (100%)", lambda: self.canvas.set_zoom(1.0), "Ctrl+1")
        self.a_zin = A("Zoom In", lambda: self.canvas.zoom_by(1.25), "Ctrl+=")
        self.a_zout = A("Zoom Out", lambda: self.canvas.zoom_by(0.8), "Ctrl+-")
        self.a_rot_l = A("Rotate Left", lambda: self.doc.rotate(False), "Ctrl+[")
        self.a_rot_r = A("Rotate Right", lambda: self.doc.rotate(True), "Ctrl+]")
        self.a_flip_h = A("Flip Horizontal", lambda: self.doc.flip(True))
        self.a_flip_v = A("Flip Vertical", lambda: self.doc.flip(False))
        self.a_resize = A("Resize Image…", self.resize_image, "Ctrl+Alt+I")
        self.a_crop = A("Crop Tool", lambda: self.select_tool("crop"))
        self.a_flatten = A("Flatten Image", lambda: self.doc.flatten())
        self.a_layer_new = A("New Layer", lambda: self.doc.add_layer(), "Ctrl+Shift+N")
        self.a_layer_dup = A("Duplicate Layer", lambda: self.doc.duplicate_layer(), "Ctrl+J")
        self.a_layer_del = A("Delete Layer", lambda: self.doc.delete_layer())
        self.a_layer_merge = A("Merge Down", lambda: self.doc.merge_down(), "Ctrl+Shift+E")
        self.a_tips = A("Quick Start Guide", self.show_tips, "F1")
        self.a_keys = A("Keyboard Shortcuts", self.show_shortcuts)

        self.doc_actions = [self.a_place, self.a_save, self.a_save_as, self.a_export, self.a_reset,
                            self.a_auto, self.a_compare, self.a_fit, self.a_100, self.a_zin,
                            self.a_zout, self.a_rot_l, self.a_rot_r, self.a_flip_h, self.a_flip_v,
                            self.a_resize, self.a_crop, self.a_flatten, self.a_layer_new,
                            self.a_layer_dup, self.a_layer_del, self.a_layer_merge]

        self.tool_group = QActionGroup(self)
        self.tool_group.setExclusionPolicy(QActionGroup.ExclusionPolicy.ExclusiveOptional)
        self.tool_actions = {}
        for key, label, sc, tip in TOOLS:
            a = QAction(tool_icon(key), label, self, checkable=True)
            a.setShortcut(QKeySequence(sc))
            a.setToolTip(tip)
            a.triggered.connect(lambda _=False, k=key: self.select_tool(k))
            self.tool_group.addAction(a)
            self.tool_actions[key] = a

        self.filter_actions = []
        for label, fn in (("Blur…", self.filter_blur), ("Sharpen", self.filter_sharpen),
                          ("Black && White", lambda: self._filter("Black & White", filters.black_and_white)),
                          ("Sepia", lambda: self._filter("Sepia", filters.sepia)),
                          ("Invert Colors", lambda: self._filter("Invert", filters.invert)),
                          ("Pixelate…", self.filter_pixelate), ("Add Noise…", self.filter_noise)):
            a = QAction(label, self)
            a.triggered.connect(fn)
            self.filter_actions.append(a)
        self.doc_actions += self.filter_actions

    def _build_menus(self):
        mb = self.menuBar()
        m = mb.addMenu("&File")
        for a in (self.a_new, self.a_open, self.a_place, None, self.a_save, self.a_save_as,
                  self.a_export, None, self.a_quit):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu("&Edit")
        for a in (self.a_undo, self.a_redo, None, self.a_reset):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu("&Image")
        for a in (self.a_auto, None, self.a_crop, self.a_rot_l, self.a_rot_r, self.a_flip_h,
                  self.a_flip_v, None, self.a_resize, self.a_flatten):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu("&Layer")
        for a in (self.a_layer_new, self.a_layer_dup, self.a_layer_merge, self.a_layer_del):
            m.addAction(a)
        m = mb.addMenu("Fil&ters")
        note = m.addAction("Filters change the selected layer")
        note.setEnabled(False)
        m.addSeparator()
        for a in self.filter_actions:
            m.addAction(a)
        m = mb.addMenu("&View")
        for a in (self.a_compare, None, self.a_fit, self.a_100, self.a_zin, self.a_zout):
            m.addSeparator() if a is None else m.addAction(a)
        self.ai_menu = mb.addMenu("&AI")
        m = mb.addMenu("&Help")
        m.addAction(self.a_tips)
        m.addAction(self.a_keys)
        m.addSeparator()
        m.addAction(self._act("Open-source Licenses…", self.show_licenses))

    def _build_toolbars(self):
        # Left: tools
        tb = QToolBar("Tools")
        tb.setObjectName("toolsBar")
        tb.setMovable(False)
        tb.setIconSize(QSize(28, 28))
        tb.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        for a in self.tool_actions.values():
            tb.addAction(a)
        self.addToolBar(Qt.LeftToolBarArea, tb)
        self.tools_bar = tb

        # Top: main actions
        top = QToolBar("Main")
        top.setMovable(False)
        top.setToolButtonStyle(Qt.ToolButtonTextOnly)
        for a in (self.a_open, self.a_export, None, self.a_undo, self.a_redo, None,
                  self.a_zout, self.a_fit, self.a_zin, None, self.a_compare, self.a_auto):
            top.addSeparator() if a is None else top.addAction(a)
        self.addToolBar(Qt.TopToolBarArea, top)
        self.addToolBarBreak(Qt.TopToolBarArea)

        # Second row: options for the current tool
        self.opts = QToolBar("Tool Options")
        self.opts.setObjectName("optionsBar")
        self.opts.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, self.opts)
        self.opt_title = QLabel()
        self.opt_title.setObjectName("optTitle")
        self.opts.addWidget(self.opt_title)
        self.opt_groups = {}

        def group(name):
            w = QWidget()
            w.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
            lay = QHBoxLayout(w)
            lay.setContentsMargins(8, 0, 8, 0)
            lay.setSpacing(8)
            self.opt_groups[name] = self.opts.addWidget(w)
            return lay

        def slider(lay, label, lo, hi, val, tip, fn, suffix=""):
            lay.addWidget(QLabel(label))
            s = NoWheelSlider(Qt.Horizontal)
            s.setRange(lo, hi)
            s.setValue(val)
            s.setFixedWidth(130)
            s.setToolTip(tip)
            v = QLabel(f"{val}{suffix}")
            v.setMinimumWidth(42)
            s.valueChanged.connect(lambda x: (v.setText(f"{x}{suffix}"), fn(x)))
            lay.addWidget(s)
            lay.addWidget(v)
            return s

        lay = group("paint")
        self.size_slider = slider(lay, "Size", 1, 1000, self.state.brush_size,
                                  "Brush size in pixels. Shortcut: [ and ]",
                                  lambda x: setattr(self.state, "brush_size", x), " px")
        slider(lay, "Hardness", 0, 100, int(self.state.hardness * 100),
               "Hard = crisp edge, soft = feathered edge.",
               lambda x: setattr(self.state, "hardness", x / 100), "%")
        slider(lay, "Strength", 1, 100, 100, "How strongly each stroke paints or erases.",
               lambda x: setattr(self.state, "strength", x / 100), "%")

        lay = group("color")
        lay.addWidget(QLabel("Color"))
        self.color_btn = ColorButton(self.state.color, "Brush and text color. Click to change, or "
                                                        "use the Color Picker tool.")
        self.color_btn.colorChanged.connect(lambda c: setattr(self.state, "color", QColor(c)))
        lay.addWidget(self.color_btn)

        lay = group("crop")
        lay.addWidget(QLabel("Shape"))
        self.ratio_combo = QComboBox()
        for name, _ in CROP_RATIOS:
            self.ratio_combo.addItem(name)
        self.ratio_combo.setToolTip("Lock the crop box to a shape, or choose Free.")
        self.ratio_combo.currentIndexChanged.connect(self._ratio_changed)
        lay.addWidget(self.ratio_combo)
        self.crop_apply_btn = QPushButton("Apply Crop")
        self.crop_apply_btn.setObjectName("accent")
        self.crop_apply_btn.clicked.connect(self.apply_crop)
        self.crop_cancel_btn = QPushButton("Cancel")
        self.crop_cancel_btn.clicked.connect(self.canvas.clear_crop)
        lay.addWidget(self.crop_apply_btn)
        lay.addWidget(self.crop_cancel_btn)
        lay.addSpacing(16)
        for text, a in (("Rotate Left", self.a_rot_l), ("Rotate Right", self.a_rot_r),
                        ("Flip", self.a_flip_h)):
            b = QPushButton(text)
            b.clicked.connect(a.trigger)
            lay.addWidget(b)
        self.crop_apply_btn.setEnabled(False)
        self.crop_cancel_btn.setEnabled(False)

        lay = group("info")
        self.opt_info = QLabel()
        self.opt_info.setObjectName("hintLabel")
        lay.addWidget(self.opt_info)

    def _build_statusbar(self):
        sb = self.statusBar()
        self.hint_lbl = QLabel()
        self.size_lbl = QLabel()
        self.zoom_lbl = QLabel()
        sb.addWidget(self.hint_lbl, 1)
        sb.addPermanentWidget(self.size_lbl)
        sb.addPermanentWidget(self.zoom_lbl)

    def _connect(self):
        c = self.canvas
        c.zoomChanged.connect(lambda z: self.zoom_lbl.setText(f"  Zoom {z * 100:.0f}%  "))
        c.strokeFinished.connect(lambda px, label: self.doc.set_layer_pixels(px, label))
        c.colorPicked.connect(self._color_picked)
        c.textRequested.connect(self.add_text)
        c.cropChanged.connect(self._crop_changed)
        c.cropApply.connect(self.apply_crop)
        c.moveStarted.connect(self._move_started)
        c.moveFinished.connect(self._move_finished)
        c.filesDropped.connect(self._files_dropped)
        c.hint.connect(self.hint_lbl.setText)
        self.renderer.histogramReady.connect(self.adjust_panel.histogram.set_data)
        self.renderer.proxyReady.connect(self._thumb_timer.start)
        ap = self.adjust_panel
        ap.settingChanged.connect(self._setting_changed)
        ap.presetChosen.connect(self._preset_chosen)
        ap.autoRequested.connect(self.auto_enhance)
        ap.resetRequested.connect(self.reset_adjustments)
        lp = self.layers_panel.actions
        lp["new"].clicked.connect(self.a_layer_new.trigger)
        lp["dup"].clicked.connect(self.a_layer_dup.trigger)
        lp["del"].clicked.connect(self.a_layer_del.trigger)
        lp["merge"].clicked.connect(self.a_layer_merge.trigger)
        lp["up"].clicked.connect(lambda: self.doc.move_layer(1))
        lp["down"].clicked.connect(lambda: self.doc.move_layer(-1))
        QShortcut(QKeySequence("]"), self, lambda: self._bump_size(1.2))
        QShortcut(QKeySequence("["), self, lambda: self._bump_size(1 / 1.2))

    # ================================================================== document state
    def set_document(self, doc):
        if self.doc:
            self.doc.changed.disconnect(self._doc_changed)
            self.doc.historyChanged.disconnect(self._history_changed)
        if self.canvas.outline is not None:
            self._end_outline()
            self.select_tool("hand")
        self.doc = doc
        self.canvas.doc = doc
        if doc:
            doc.changed.connect(self._doc_changed)
            doc.historyChanged.connect(self._history_changed)
            self.center.setCurrentWidget(self.canvas)
            self.canvas.doc_w = self.canvas.doc_h = 0  # force a fit on first display
        else:
            self.canvas.clear()
            self.center.setCurrentWidget(self.welcome)
        self.a_compare.setChecked(False)
        self.renderer.show_original = False
        self.renderer.set_document(doc)
        self.layers_panel.set_document(doc)
        self.adjust_panel.sync(doc.adjust if doc else adjustments.DEFAULTS)
        self.adjust_panel.setEnabled(doc is not None)
        for a in self.doc_actions + list(self.tool_actions.values()):
            a.setEnabled(doc is not None)
        self._ratio_changed(self.ratio_combo.currentIndex())
        self._history_changed()
        self._update_labels()
        if doc:
            self.hint_lbl.setText("Tip: try a Preset on the right, or click ✨ Auto Enhance. "
                                  "Scroll to zoom, hold Space and drag to pan.")

    def _doc_changed(self, kind):
        ed = self.canvas.outline
        if ed is not None and (ed.doc_w, ed.doc_h) != (self.doc.width, self.doc.height):
            self.select_tool("hand")
        if kind == "adjust":
            self.renderer.update()
            self.adjust_panel.sync(self.doc.adjust)
            return
        self.renderer.invalidate()
        if kind in ("structure", "pixels", "all"):
            self.layers_panel.rebuild()
        if kind == "all":
            self.adjust_panel.sync(self.doc.adjust)
            self._ratio_changed(self.ratio_combo.currentIndex())
        self._update_labels()

    def _history_changed(self):
        d = self.doc
        u, r = (d.undo_label(), d.redo_label()) if d else (None, None)
        self.a_undo.setEnabled(bool(u))
        self.a_redo.setEnabled(bool(r))
        self.a_undo.setToolTip(f"Undo: {u} (Ctrl+Z)" if u else "Nothing to undo")
        self.a_redo.setToolTip(f"Redo: {r} (Ctrl+Y)" if r else "Nothing to redo")
        self._update_labels()

    def _update_labels(self):
        d = self.doc
        if not d:
            self.setWindowTitle(APP_NAME)
            self.size_lbl.setText("")
            self.zoom_lbl.setText("")
            return
        name = getattr(d, "display_name", "Untitled")
        self.setWindowTitle(f"{name}{' •' if d.dirty else ''} — {APP_NAME}")
        self.size_lbl.setText(f"  {d.width} × {d.height} px  ·  {len(d.layers)} layer"
                              f"{'s' if len(d.layers) != 1 else ''}  ")

    def on_active_layer_changed(self):
        layer = self.doc.active_layer()
        self.hint_lbl.setText(f"Selected layer: {layer.name}. Brush, eraser, move and filters "
                              "work on this layer.")

    # ================================================================== tools
    def select_tool(self, key):
        if key in self.tool_actions:
            self.tool_actions[key].setChecked(True)
        elif self.tool_group.checkedAction():
            self.tool_group.checkedAction().setChecked(False)
        self.canvas.set_tool(key)
        if key not in OUTLINE_TOOLS and self.canvas.outline is not None:
            self._end_outline()
        label = "Refine Outline" if key == "ai_refine" else next(
            l for k, l, _, _ in TOOLS if k == key)
        self.opt_title.setText(f"  {label}  ")
        show = {"paint": key in ("brush", "eraser"), "color": key in ("brush", "text", "eyedropper"),
                "crop": key == "crop",
                "info": key in ("hand", "move", "text", "eyedropper"),
                "outline": key in OUTLINE_TOOLS}
        for name, act in self.opt_groups.items():
            act.setVisible(show[name])
        self.opt_info.setText(TOOL_HINTS[key].split(": ", 1)[1])
        self.hint_lbl.setText(TOOL_HINTS[key])
        if key == "crop":
            self.canvas.setFocus()
        if key == "ai_remove" and self.doc:
            self._start_outline("ai_remove")

    def _bump_size(self, f):
        s = self.state.brush_size
        new = max(s + 1, round(s * f)) if f > 1 else min(s - 1, round(s * f))
        self.size_slider.setValue(max(1, min(1000, new)))

    def _color_picked(self, c):
        self.state.color = QColor(c)
        self.color_btn.set_color(c)
        self.hint_lbl.setText(f"Picked color {c.name().upper()} — the Brush and Text tools will use it.")

    def _ratio_changed(self, i):
        r = CROP_RATIOS[i][1]
        if r == "orig":
            r = self.doc.width / self.doc.height if self.doc else None
        self.state.crop_ratio = r

    def _crop_changed(self, has):
        self.crop_apply_btn.setEnabled(has)
        self.crop_cancel_btn.setEnabled(has)

    def apply_crop(self):
        if self.canvas.crop_rect is None:
            return
        x, y, w, h = self.canvas.crop_pixels()
        self.canvas.clear_crop()
        if w > 0 and h > 0:
            self.doc.crop(x, y, w, h)
            self.hint_lbl.setText(f"Cropped to {w} × {h} px. Press Ctrl+Z to undo.")

    def _move_started(self):
        layer = self.doc.active_layer()
        if not layer.visible:
            self.hint_lbl.setText("The selected layer is hidden — show it in the Layers panel first.")
            return
        self._moving = True
        self.renderer.exclude = self.doc.active
        self.renderer.invalidate()
        self.canvas.set_floating(imageio.to_qimage(layer.pixels), layer.opacity)

    def _move_finished(self, dx, dy):
        if not self._moving:
            return
        self._moving = False
        self.canvas.set_floating(None)
        self.renderer.exclude = None
        if dx or dy:
            self.doc.shift_layer(dx, dy)
        else:
            self.renderer.invalidate()

    def add_text(self, pos):
        dlg = TextDialog(self.state.color, max(24, self.doc.height // 12), self)
        if dlg.exec() != QDialog.Accepted:
            return
        text = dlg.text.toPlainText().strip()
        if not text:
            return
        img = QImage(self.doc.width, self.doc.height, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setRenderHint(QPainter.Antialiasing)
        font = dlg.qfont()
        p.setFont(font)
        rect = img.rect().adjusted(int(pos.x()), int(pos.y()), 0, 0)
        if dlg.shadow.isChecked():
            off = max(2, font.pixelSize() // 18)
            p.setPen(QColor(0, 0, 0, 170))
            p.drawText(rect.translated(off, off), Qt.AlignLeft | Qt.AlignTop, text)
        p.setPen(dlg.color.color)
        p.drawText(rect, Qt.AlignLeft | Qt.AlignTop, text)
        p.end()
        self.state.color = QColor(dlg.color.color)
        self.color_btn.set_color(self.state.color)
        name = "Text: " + text.splitlines()[0][:24]
        self.doc.add_layer(imageio.from_qimage(img), name, label="Add text")
        self.hint_lbl.setText("Text added on its own layer. Use the Move tool (V) to reposition it.")

    # ================================================================== adjustments
    def _setting_changed(self, key, value):
        self.doc.push_undo(f"{key.title()} adjustment", coalesce="adj:" + key)
        self.doc.adjust[key] = value
        self.renderer.request_update()

    def _preset_chosen(self, name):
        self.doc.set_adjustments(adjustments.preset_settings(name), f"Preset: {name}")
        self.hint_lbl.setText(f"Applied the '{name}' preset. Fine-tune it with the sliders, "
                              "or press \\ to compare with the original.")

    def auto_enhance(self):
        if not self.doc:
            return
        s = dict(self.doc.adjust)
        s.update(adjustments.auto_settings(self.renderer.proxy))
        self.doc.set_adjustments(s, "Auto Enhance")
        self.tabs.setCurrentWidget(self.adjust_panel)
        self.hint_lbl.setText("Auto Enhance applied. Tweak any slider you like, or Ctrl+Z to undo.")

    def reset_adjustments(self):
        if self.doc and not adjustments.is_default(self.doc.adjust):
            self.doc.set_adjustments(adjustments.DEFAULTS, "Reset adjustments")

    def toggle_compare(self, on):
        self.renderer.show_original = on
        self.renderer.update()
        self.hint_lbl.setText("Showing the ORIGINAL (before). Press \\ again to see your edits."
                              if on else "Showing your edits (after).")

    def _update_preset_thumbs(self):
        if self.renderer.proxy is not None:
            self.adjust_panel.set_preset_thumbs(imageio.thumbnail(self.renderer.proxy, 88))

    # ================================================================== filters
    def _filter(self, label, fn):
        layer = self.doc.active_layer()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.doc.set_layer_pixels(fn(layer.pixels), label)
        finally:
            QApplication.restoreOverrideCursor()
        self.hint_lbl.setText(f"{label} applied to layer '{layer.name}'. Ctrl+Z to undo.")

    def filter_blur(self):
        r, ok = QInputDialog.getDouble(self, "Blur", "Blur radius (pixels):", 4.0, 0.5, 200, 1)
        if ok:
            self._filter("Blur", lambda px: filters.gaussian_blur(px, r))

    def filter_sharpen(self):
        self._filter("Sharpen", filters.sharpen)

    def filter_pixelate(self):
        n, ok = QInputDialog.getInt(self, "Pixelate", "Block size (pixels):", 12, 2, 500)
        if ok:
            self._filter("Pixelate", lambda px: filters.pixelate(px, n))

    def filter_noise(self):
        n, ok = QInputDialog.getInt(self, "Add Noise", "Amount (1–100):", 10, 1, 100)
        if ok:
            self._filter("Add noise", lambda px: filters.add_noise(px, n))

    def resize_image(self):
        dlg = ResizeDialog(self.doc.width, self.doc.height, self)
        if dlg.exec() == QDialog.Accepted:
            w, h = dlg.w.value(), dlg.h.value()
            if (w, h) != (self.doc.width, self.doc.height):
                QApplication.setOverrideCursor(Qt.WaitCursor)
                try:
                    self.doc.resize(w, h)
                finally:
                    QApplication.restoreOverrideCursor()

    # ================================================================== files
    def _confirm_discard(self):
        if not self.doc or not self.doc.dirty:
            return True
        r = QMessageBox.question(
            self, APP_NAME, "You have unsaved changes. Save them as a project first?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if r == QMessageBox.Save:
            return self.save_project()
        return r == QMessageBox.Discard

    def new_image(self):
        if not self._confirm_discard():
            return
        dlg = NewImageDialog(self)
        if dlg.exec() == QDialog.Accepted:
            w, h, color = dlg.result_values()
            doc = Document.blank(w, h, color)
            doc.display_name = "Untitled"
            self.set_document(doc)

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open a photo", self._last_dir(),
                                              imageio.OPEN_FILTER)
        if path:
            self.load_path(path)

    def _last_dir(self):
        return getattr(self, "_dir", os.path.expanduser("~/Pictures"))

    def load_path(self, path):
        if not self._confirm_discard():
            return
        self._dir = os.path.dirname(path)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            if path.lower().endswith(imageio.PROJECT_EXT):
                doc = imageio.load_project(path)
                doc.path = path
            else:
                doc = Document.from_image(imageio.load_image(path))
            doc.display_name = os.path.basename(path)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, APP_NAME, f"Sorry, that file couldn't be opened.\n\n{e}")
            return
        QApplication.restoreOverrideCursor()
        self.set_document(doc)

    def place_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Add a photo as a new layer", self._last_dir(),
                                              imageio.OPEN_FILTER)
        if path:
            self._place_path(path)

    def _place_path(self, path):
        try:
            px = imageio.load_image(path)
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Couldn't open that file.\n\n{e}")
            return
        self.doc.place_image(px, os.path.splitext(os.path.basename(path))[0])
        self.hint_lbl.setText("Photo added as a new layer. Use Move (V) to position it and the "
                              "Layers tab to change opacity or blend mode.")

    def _files_dropped(self, paths):
        path = paths[0]
        ext = os.path.splitext(path)[1].lower()
        if ext not in imageio.IMAGE_EXTS | imageio.RAW_EXTS | {imageio.PROJECT_EXT}:
            QMessageBox.information(self, APP_NAME, "That doesn't look like a photo I can open.")
            return
        if self.doc and ext != imageio.PROJECT_EXT:
            box = QMessageBox(self)
            box.setWindowTitle(APP_NAME)
            box.setText("What would you like to do with this photo?")
            layer_btn = box.addButton("Add as a Layer", QMessageBox.AcceptRole)
            open_btn = box.addButton("Open Instead", QMessageBox.ActionRole)
            box.addButton(QMessageBox.Cancel)
            box.exec()
            if box.clickedButton() == layer_btn:
                self._place_path(path)
            elif box.clickedButton() == open_btn:
                self.load_path(path)
        else:
            self.load_path(path)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self._files_dropped(paths)

    def save_project(self, save_as=False):
        if not self.doc:
            return False
        path = self.doc.path
        if save_as or not path:
            base = os.path.splitext(getattr(self.doc, "display_name", "Untitled"))[0]
            path, _ = QFileDialog.getSaveFileName(
                self, "Save project", os.path.join(self._last_dir(), base + imageio.PROJECT_EXT),
                f"PhotoForge project (*{imageio.PROJECT_EXT})")
            if not path:
                return False
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            imageio.save_project(self.doc, path)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, APP_NAME, f"Couldn't save the project.\n\n{e}")
            return False
        QApplication.restoreOverrideCursor()
        self.doc.path = path
        self.doc.display_name = os.path.basename(path)
        self.doc.dirty = False
        self._update_labels()
        self.hint_lbl.setText(f"Project saved to {path}")
        return True

    def export_image(self):
        dlg = ExportDialog(self.doc.width, self.doc.height, self)
        if dlg.exec() != QDialog.Accepted:
            return
        ext = dlg.ext()
        base = os.path.splitext(getattr(self.doc, "display_name", "Untitled"))[0]
        path, _ = QFileDialog.getSaveFileName(
            self, "Export image", os.path.join(self._last_dir(), f"{base}_edited{ext}"),
            f"Image (*{ext})")
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ext
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            out = self.doc.render_final()
            edge = dlg.long_edge()
            h, w = out.shape[:2]
            if edge and max(w, h) > edge:
                f = edge / max(w, h)
                out = imageio.resize(out, max(1, round(w * f)), max(1, round(h * f)))
            imageio.save_image(out, path, dlg.quality.value())
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, APP_NAME, f"Export failed.\n\n{e}")
            return
        QApplication.restoreOverrideCursor()
        self.hint_lbl.setText(f"Exported to {path}")
        QMessageBox.information(self, APP_NAME, f"Your image was saved to:\n{path}")

    # ================================================================== AI tools
    def _build_ai(self):
        A = self._act
        self.a_ai_bg = A("Remove Background", self.ai_remove_background, "Ctrl+Alt+B",
                         "AI: cut out the main subject")
        self.a_ai_refine = A("Refine Outline…", self.ai_refine_outline, None,
                             "Adjust the edge of a cut-out with draggable dots")
        self.a_ai_obj = A("Remove Object…", lambda: self.select_tool("ai_remove"), None,
                          "AI: outline something with dots and erase it")
        for a in (self.a_ai_bg, self.a_ai_refine, self.a_ai_obj):
            self.ai_menu.addAction(a)
            self.doc_actions.append(a)
            a.setEnabled(self.doc is not None)
        p = self.ai_panel
        p.removeBackground.connect(self.ai_remove_background)
        p.refineOutline.connect(self.ai_refine_outline)
        p.removeObject.connect(lambda: self.select_tool("ai_remove"))
        self.canvas.outlineApply.connect(self._outline_apply)
        self.canvas.outlineCancel.connect(lambda: self.select_tool("hand"))

        # Tool-options group shown while editing an outline.
        w = QWidget()
        w.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(8, 0, 8, 0)
        lay.setSpacing(8)
        self.outline_info = QLabel()
        self.outline_info.setObjectName("hintLabel")
        lay.addWidget(self.outline_info)
        for text, tip, method in (
                ("More Points", "Add a dot in the middle of every line for finer control",
                 "more_points"),
                ("Fewer Points", "Remove every other dot to simplify the outline", "fewer_points"),
                ("Clear", "Remove all dots and start over", "clear")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, m=method: self._outline_call(m))
            lay.addWidget(b)
        self.crisp_chk = QCheckBox("Crisp edges")
        self.crisp_chk.setToolTip("Make the AI's soft edges solid everywhere, e.g. if a hand "
                                  "or object looks faded. Leave off for hair and fur.")
        lay.addWidget(self.crisp_chk)
        self.feather_lbl = QLabel("Edge softness")
        lay.addWidget(self.feather_lbl)
        self.feather = NoWheelSlider(Qt.Horizontal)
        self.feather.setRange(0, 20)
        self.feather.setValue(1)
        self.feather.setFixedWidth(90)
        self.feather.setToolTip("0 = crisp edge. Higher values blend the edge more softly.")
        lay.addWidget(self.feather)
        self.outline_apply_btn = QPushButton()
        self.outline_apply_btn.setObjectName("accent")
        self.outline_apply_btn.clicked.connect(self._outline_apply)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(lambda: self.select_tool("hand"))
        lay.addWidget(self.outline_apply_btn)
        lay.addWidget(cancel)
        self.opt_groups["outline"] = self.opts.addWidget(w)
        self.opt_groups["outline"].setVisible(False)

    def _outline_call(self, method):
        if self.canvas.outline is not None:
            getattr(self.canvas.outline, method)()
            self.canvas.setFocus()

    def _start_outline(self, mode):
        if self.canvas.outline is not None:
            self._end_outline()
        color = QColor(255, 70, 70) if mode == "ai_remove" else QColor(40, 200, 255)
        ed = OutlineEditor(self.canvas, color, dim_outside=mode == "ai_refine")
        ed.on_change = self._outline_changed
        self.canvas.outline = ed
        self._outline_mode = mode
        refine = mode == "ai_refine"
        self.outline_apply_btn.setText("Apply Outline" if refine else "Remove Object")
        self.feather.setVisible(refine)
        self.feather_lbl.setVisible(refine)
        self.crisp_chk.setVisible(refine)
        self.canvas.setFocus()
        self._outline_changed()
        return ed

    def _end_outline(self):
        self.canvas.outline.remove()
        self.canvas.outline = None
        self.canvas.set_backdrop(None)

    def _outline_changed(self):
        ed = self.canvas.outline
        if ed is None:
            return
        n = ed.point_count()
        if ed.open:
            msg = f"{n} dots. Click the first (yellow) dot or double-click to close the shape"
        elif not ed.has_shape():
            msg = "Click around the object to place dots"
        else:
            msg = f"{n} dots. Drag to adjust, click a line to add a dot, right-click to delete"
        self.outline_info.setText(msg)
        self.outline_apply_btn.setEnabled(ed.has_shape())

    def _outline_apply(self):
        ed = self.canvas.outline
        if ed is None or not ed.has_shape():
            self.hint_lbl.setText("Close the outline first: click the first (yellow) dot.")
            return
        if self._outline_mode == "ai_remove":
            self._ai_remove_object(ed.rasterize())
        else:
            layer = self.doc.active_layer()
            px = layer.pixels.copy()
            base = self._refine_alpha
            if self.crisp_chk.isChecked():
                base = ai_tasks.crisp_edges(base)
            px[..., 3] = merge_refined(base, ed.rasterize(self.feather.value()),
                                       self._refine_tol)
            self.doc.set_layer_pixels(px, "Refine outline")
            self.select_tool("hand")
            self.hint_lbl.setText("Outline applied. Ctrl+Z to undo.")

    def ai_remove_background(self):
        if not self.doc:
            return
        comp = np.array(self.doc.composite())

        crisp = self.ai_panel.edges.currentData() == "crisp"

        def done(mask):
            if crisp:
                mask = ai_tasks.crisp_edges(mask)
            px = comp.copy()
            px[..., 3] = np.minimum(px[..., 3], mask)
            self.doc.add_result_layer(px, "Cutout", "Remove background", hide_others=True)
            self.ai_panel.refresh()
            self.hint_lbl.setText("Background removed! Your original is kept (hidden) in Layers. "
                                  "Not perfect? Click AI → Refine Outline to adjust the edge.")

        run_ai(self, ["birefnet_lite"], "Remove Background", "Finding the subject…",
               lambda: ai_tasks.remove_background(comp), done)

    def ai_refine_outline(self):
        if not self.doc:
            return
        alpha = self.doc.active_layer().pixels[..., 3]
        if alpha.min() > 250:
            QMessageBox.information(
                self, "Refine Outline",
                "The selected layer has no transparent areas to refine.\n\n"
                "Use Remove Background first, then select the Cutout layer.")
            return
        polys, self._refine_tol = trace_mask(alpha)
        self._refine_alpha = alpha
        if not polys:
            QMessageBox.information(self, "Refine Outline", "This layer is almost empty.")
            return
        self.select_tool("ai_refine")
        ed = self._start_outline("ai_refine")
        # Show the whole, uncut photo so it's clear what is kept and what is removed.
        full = self.doc.active_layer().pixels.copy()
        full[..., 3] = 255
        self.canvas.set_backdrop(imageio.to_qimage(full))
        self.crisp_chk.setChecked(self.ai_panel.edges.currentData() == "crisp")
        ed.set_polys(polys)
        ed._history.clear()
        self._outline_changed()

    def _ai_remove_object(self, mask):
        comp = np.array(self.doc.composite())
        quality = self.ai_panel.quality.currentData()
        key = "lama" if quality == "best" else "migan"

        def done(patch):
            self.doc.add_result_layer(patch, "Object removed", "Remove object")
            if self.canvas.outline is not None:
                self.canvas.outline.clear()
            self.ai_panel.refresh()
            self.hint_lbl.setText("Object removed (on its own layer). Outline another object, "
                                  "or pick another tool when you're done.")

        run_ai(self, [key], "Remove Object", "Filling in the background…",
               lambda: ai_tasks.remove_object(comp, mask, quality), done)

    def show_licenses(self):
        rows = "".join(
            f"<tr><td><b>{m.name}</b></td><td>&nbsp;{m.purpose}</td><td>&nbsp;{m.license}</td>"
            f"<td>&nbsp;<a href='{m.homepage}'>{m.homepage}</a></td></tr>"
            for m in ai_models.MODELS.values())
        libs = ("PySide6 / Qt (LGPL v3), NumPy (BSD), Pillow (MIT-CMU), OpenCV (Apache 2.0), "
                "ONNX Runtime (MIT), rawpy (MIT) / LibRaw (LGPL 2.1 / CDDL)")
        box = QMessageBox(self)
        box.setWindowTitle("Open-source Licenses")
        box.setTextFormat(Qt.RichText)
        box.setText(f"<h3>AI models</h3><table>{rows}</table>"
                    f"<h3>Libraries</h3><p>{libs}</p>"
                    "<p>PhotoForge thanks the authors of these projects. Full license texts "
                    "are available at each project's homepage.</p>")
        box.exec()

    # ================================================================== misc
    def undo(self):
        if self.canvas.outline is not None and self.canvas.outline.undo():
            return
        if self.doc:
            self.doc.undo()

    def redo(self):
        if self.doc:
            self.doc.redo()

    def show_tips(self):
        QMessageBox.information(self, "Quick Start Guide", """
<h3>Welcome to PhotoForge!</h3>
<p><b>Quick fixes (like Lightroom)</b> — the <b>Adjust</b> tab on the right:</p>
<ul>
<li><b>✨ Auto Enhance</b> fixes brightness and color in one click.</li>
<li><b>Presets</b> apply a complete look. The thumbnails preview your own photo.</li>
<li><b>Sliders</b> fine-tune things. Hover a slider to learn what it does; double-click its name to reset it.</li>
<li>Press <b>\\</b> to compare before and after.</li>
</ul>
<p><b>Creative editing (like Photoshop)</b> — the tools on the left and the <b>Layers</b> tab:</p>
<ul>
<li><b>Crop</b> to straighten up your framing, with handy shapes for Instagram and prints.</li>
<li><b>Brush / Eraser</b> paint on the selected layer.</li>
<li><b>Text</b> adds captions on their own layer; move them with the <b>Move</b> tool.</li>
<li><b>File → Add Photo as Layer</b> to combine images, then play with Opacity and Blend.</li>
<li><b>Filters</b> menu: blur, sharpen, black &amp; white, sepia and more.</li>
</ul>
<p><b>Nothing is permanent:</b> Ctrl+Z undoes anything. Your original file is never changed —
use <b>Export</b> to save a finished copy, or <b>Save Project</b> to keep working later.</p>
""")

    def show_shortcuts(self):
        rows = "".join(f"<tr><td><b>{k}</b></td><td>&nbsp;&nbsp;{v}</td></tr>" for k, v in (
            ("Ctrl+O / Ctrl+E", "Open / Export"), ("Ctrl+S", "Save project"),
            ("Ctrl+Z / Ctrl+Y", "Undo / Redo"), ("\\", "Before / After"),
            ("Mouse wheel", "Zoom"), ("Space + drag", "Pan"), ("Ctrl+0 / Ctrl+1", "Fit / 100%"),
            ("H V B E C I T", "Pan, Move, Brush, Eraser, Crop, Picker, Text"),
            ("[ / ]", "Smaller / bigger brush"), ("Enter / Esc", "Apply / cancel crop"),
            ("Ctrl+J", "Duplicate layer"), ("Ctrl+Shift+A", "Auto Enhance")))
        QMessageBox.information(self, "Keyboard Shortcuts", f"<table>{rows}</table>")

    def closeEvent(self, e):
        if self._confirm_discard():
            QThreadPool.globalInstance().waitForDone(5000)
            e.accept()
        else:
            e.ignore()
