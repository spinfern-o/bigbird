import os

import numpy as np

from PySide6.QtCore import QSettings, QSize, Qt, QThreadPool, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QImage, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDockWidget, QFileDialog, QHBoxLayout,
                               QInputDialog, QLabel, QMainWindow, QMessageBox, QPushButton,
                               QSizePolicy, QSlider, QSpinBox, QStackedWidget, QTabWidget, QToolBar, QVBoxLayout, QWidget)

from . import adjustments, filters, imageio
from .auth import AuthManager
from .canvas import Canvas, ToolState
from .cloud_dialogs import CloudProjectsDialog, run_cloud
from . import cloud_projects
from .dialogs import ExportDialog, NewImageDialog, ResizeDialog, TextDialog
from .document import Document
from .icons import tool_icon
from .panels import AdjustPanel, ColorButton, LayersPanel, NoWheelSlider
from .renderer import Renderer
from .selection import apply_masked
from .selection_actions import SELECT_TOOL_INFO, SelectionActions
from .ai import cloud as ai_cloud, models as ai_models, tasks as ai_tasks
from .ai.connection import CloudConnection
from .ai.settings_dialog import AISettingsDialog
from .ai.outline import OutlineEditor, solidify, trace_mask
from .ai.object_select import ObjectSelector
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
    ("ai_remove", "Remove", "R", "Select to Remove (R): click the objects you want gone and the "
                                 "AI finds their outlines. Press Enter to remove them."),
]
TOOLS[1:1] = SELECT_TOOL_INFO[:3]         # Marquee, Lasso, Wand after Pan
TOOLS.insert(TOOLS.index(next(t for t in TOOLS if t[0] == "eraser")) + 1, SELECT_TOOL_INFO[3])
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


class MainWindow(SelectionActions, QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("PhotoForge", "PhotoForge")
        self.resize(1440, 900)
        geometry = self.settings.value("window/geometry")
        if geometry:
            self.restoreGeometry(geometry)
        self._dir = self.settings.value("files/last_dir", os.path.expanduser("~/Pictures"))
        recent = self.settings.value("files/recent", [])
        if isinstance(recent, str):
            recent = [recent] if recent else []
        self._recent = [str(p) for p in (recent or [])][:10]
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

        self.auth = AuthManager(self)
        self.auth.authChanged.connect(self._update_auth_ui)

        self._build_actions()
        self._build_menus()
        self._build_toolbars()
        self._build_statusbar()
        self._connect()
        self._build_ai()
        self._build_selection()
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
        self.a_cloud_save = A("Save to Cloud…", self.cloud_save, "Ctrl+Alt+S",
                              "Save this project to your phrame.tech account")
        self.a_cloud_open = A("Open from Cloud…", self.cloud_open, "Ctrl+Alt+O",
                              "Open a project saved in your phrame.tech account")
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

        self.doc_actions = [self.a_place, self.a_save, self.a_save_as, self.a_cloud_save,
                            self.a_export, self.a_reset,
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
        self.file_menu = m
        for a in (self.a_new, self.a_open, self.a_place):
            m.addAction(a)
        self.recent_menu = m.addMenu("Open Recent")
        self._refresh_recent_menu()
        m.addSeparator()
        for a in (self.a_cloud_open, self.a_cloud_save):
            m.addAction(a)
        m.addSeparator()
        for a in (self.a_save, self.a_save_as, self.a_export):
            m.addAction(a)
        m.addSeparator()
        m.addAction(self.a_quit)
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
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        top.addWidget(spacer)
        self.login_btn = QPushButton("Log in")
        self.login_btn.setObjectName("loginBtn")
        self.login_btn.setToolTip("Sign in to your PhotoForge account in your web browser")
        self.login_btn.clicked.connect(self._on_login_clicked)
        top.addWidget(self.login_btn)
        self.addToolBar(Qt.TopToolBarArea, top)
        self._update_auth_ui(self.auth.is_logged_in)
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
        self.opt_group_tools = {}  # extra option groups -> tools that show them

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

    # ================================================================== account
    def _on_login_clicked(self):
        if self.auth.is_logged_in:
            name = self.auth.email or "your account"
            if QMessageBox.question(self, "Log out",
                                    f"Log out of {name}?") == QMessageBox.Yes:
                self.auth.logout()
            return
        self.auth.login()
        self.statusBar().showMessage(
            "Opening your web browser to sign in… return here when you're done.", 8000)

    def _update_auth_ui(self, logged_in):
        if logged_in:
            email = self.auth.email or "Account"
            self.login_btn.setText(f"●  {email}")
            self.login_btn.setToolTip(f"Signed in as {email}. Click to log out.")
            self.statusBar().showMessage(f"Signed in as {email}.", 6000)
        else:
            self.login_btn.setText("Log in")
            self.login_btn.setToolTip("Sign in to your PhotoForge account in your web browser")

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
        ap.mixerResetRequested.connect(self.reset_color_mixer)
        ap.hint.connect(self.hint_lbl.setText)
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
        if kind == "selection":
            self._selection_changed()
            return
        if kind == "all":
            self._selection_changed(from_tool=False)
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
                "outline": key == "ai_refine", "select": key == "ai_remove"}
        for name, act in self.opt_groups.items():
            act.setVisible(show[name] if name in show else key in self.opt_group_tools.get(name, ()))
        self.opt_info.setText(TOOL_HINTS[key].split(": ", 1)[1])
        self.hint_lbl.setText(TOOL_HINTS[key])
        if key == "crop":
            self.canvas.setFocus()
        if key == "ai_remove" and self.doc:
            self._start_select()
        self._on_tool_selected(key)

    def _bump_size(self, f):
        s = self.state.brush_size
        if self.state.tool == "heal":
            new = max(s + 1, round(s * f)) if f > 1 else min(s - 1, round(s * f))
            self.heal_size.setValue(max(2, min(400, new)))
            return
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
        self.doc.push_undo(f"{adjustments.setting_label(key)} adjustment", coalesce="adj:" + key)
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

    def reset_color_mixer(self):
        """Put every Color Mixer slider back to zero in a single undo step."""
        if self.doc and not adjustments.mixer_is_default(self.doc.adjust):
            s = dict(self.doc.adjust)
            s.update(adjustments.MIXER_DEFAULTS)
            self.doc.set_adjustments(s, "Reset Color Mixer")
            self.hint_lbl.setText("Color Mixer reset — your other sliders are untouched. "
                                  "Ctrl+Z to undo.")

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
            new = fn(layer.pixels)
            if self.doc.selection is not None:
                new = apply_masked(layer.pixels, new, self.doc.selection)
            self.doc.set_layer_pixels(new, label)
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
        return self._dir or os.path.expanduser("~/Pictures")

    def _refresh_recent_menu(self):
        if not hasattr(self, "recent_menu"):
            return
        self.recent_menu.clear()
        existing = [p for p in self._recent if os.path.exists(p)]
        if existing != self._recent:
            self._recent = existing
            self.settings.setValue("files/recent", self._recent)
        if not self._recent:
            empty = self.recent_menu.addAction("No recent files")
            empty.setEnabled(False)
            return
        for path in self._recent:
            action = self.recent_menu.addAction(os.path.basename(path))
            action.setToolTip(path)
            action.triggered.connect(lambda _=False, p=path: self.load_path(p))
        self.recent_menu.addSeparator()
        clear = self.recent_menu.addAction("Clear Recent Files")
        clear.triggered.connect(self._clear_recent_files)

    def _clear_recent_files(self):
        self._recent = []
        self.settings.setValue("files/recent", [])
        self._refresh_recent_menu()

    def _add_recent_file(self, path):
        path = os.path.abspath(path)
        self._recent = [p for p in self._recent if p != path]
        self._recent.insert(0, path)
        self._recent = self._recent[:10]
        self.settings.setValue("files/recent", self._recent)
        self._refresh_recent_menu()

    def _remember_dir(self, path):
        directory = os.path.dirname(os.path.abspath(path))
        if directory:
            self._dir = directory
            self.settings.setValue("files/last_dir", directory)

    def load_path(self, path):
        if not self._confirm_discard():
            return
        self._remember_dir(path)
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
        self._add_recent_file(path)
        self.set_document(doc)

    def place_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Add a photo as a new layer", self._last_dir(),
                                              imageio.OPEN_FILTER)
        if path:
            self._remember_dir(path)
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
        self._remember_dir(path)
        self._add_recent_file(path)
        self._update_labels()
        self.hint_lbl.setText(f"Project saved to {path}")
        return True

    # ------------------------------------------------------------------ cloud projects
    def _cloud_api(self):
        """Return the signed-in cloud API, or start login and ask the user to retry."""
        if not self.auth.is_logged_in:
            if QMessageBox.question(
                self, "Cloud projects",
                "Cloud projects are saved to your phrame.tech account.\n\nLog in now?"
            ) == QMessageBox.Yes:
                self.auth.login()
            return None
        return cloud_projects.Api(self.auth)

    def cloud_save(self):
        api = self._cloud_api()
        if api is None or not self.doc:
            return

        default = os.path.splitext(getattr(self.doc, "display_name", "Untitled"))[0]
        name, ok = QInputDialog.getText(self, "Save to Cloud", "Project name:", text=default)
        name = name.strip()
        if not ok or not name:
            return

        doc = self.doc
        cloud_user_id = api.user_id()
        project_id = getattr(doc, "cloud_id", None)
        if getattr(doc, "cloud_user_id", None) != cloud_user_id:
            project_id = None
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            data = cloud_projects.project_bytes(doc)
            thumb = cloud_projects.thumbnail_jpeg(doc)
        except Exception as e:
            QMessageBox.warning(self, "Save to Cloud", f"Couldn't prepare this project.\n\n{e}")
            return
        finally:
            QApplication.restoreOverrideCursor()

        def done(row):
            doc.cloud_id = row.get("id")
            doc.cloud_user_id = cloud_user_id
            doc.display_name = name
            doc.dirty = False
            self._update_labels()
            self.hint_lbl.setText(
                f"Saved '{name}' to your phrame.tech account "
                f"({len(data) / 1048576:.1f} MB)."
            )

        run_cloud(
            self,
            "Save to Cloud",
            f"Uploading '{name}'…",
            lambda: api.save_project(name, data, thumb, doc.width, doc.height, project_id),
            done,
        )

    def cloud_open(self):
        api = self._cloud_api()
        if api is None:
            return

        def show(rows):
            dlg = CloudProjectsDialog(self, api, rows)
            dlg.load_thumbs()
            if dlg.exec() == QDialog.Accepted and dlg.chosen:
                self._cloud_download(api, dlg.chosen)

        run_cloud(self, "Open from Cloud", "Loading your projects…", api.list_projects, show)

    def _cloud_download(self, api, row):
        if not self._confirm_discard():
            return

        def done(data):
            import io
            try:
                doc = imageio.load_project(io.BytesIO(data))
            except Exception as e:
                QMessageBox.warning(
                    self,
                    "Open from Cloud",
                    f"That project couldn't be opened.\n\n{e}",
                )
                return
            doc.display_name = row["name"]
            doc.cloud_id = row["id"]
            doc.cloud_user_id = api.user_id()
            self.set_document(doc)
            self.hint_lbl.setText(f"Opened '{row['name']}' from your phrame.tech account.")

        run_cloud(
            self,
            "Open from Cloud",
            f"Downloading '{row['name']}'…",
            lambda: api.download_project(row["file_path"]),
            done,
        )

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
        self._remember_dir(path)
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
        self.a_ai_obj = A("Select Object(s) to Remove…", lambda: self.select_tool("ai_remove"),
                          None, "AI: click objects to select them, then remove them")
        self.a_ai_refine_rm = A("Refine Removal…", self.ai_refine_removal, None,
                                "Adjust what was removed with draggable dots")
        self.a_ai_settings = A("AI Settings…", self.ai_settings, None,
                               "Optionally accelerate local AI on the Brev NVIDIA GPU")
        self.cloud_conn = CloudConnection(self)
        self.cloud_conn.changed.connect(self._cloud_changed)
        self.cloud_lbl = QPushButton()
        self.cloud_lbl.setFlat(True)
        self.cloud_lbl.setCursor(Qt.PointingHandCursor)
        self.cloud_lbl.clicked.connect(self.ai_settings)
        self.statusBar().addPermanentWidget(self.cloud_lbl)
        self._cloud_changed(self.cloud_conn.state, self.cloud_conn.message)
        QTimer.singleShot(400, self.cloud_conn.start)
        for a in (self.a_ai_bg, self.a_ai_refine, self.a_ai_obj, self.a_ai_refine_rm):
            self.ai_menu.addAction(a)
            self.doc_actions.append(a)
            a.setEnabled(self.doc is not None)
        self.ai_menu.addSeparator()
        self.ai_menu.addAction(self.a_ai_settings)
        p = self.ai_panel
        p.removeBackground.connect(self.ai_remove_background)
        p.refineOutline.connect(self.ai_refine_outline)
        p.removeObject.connect(lambda: self.select_tool("ai_remove"))
        p.refineRemoval.connect(self.ai_refine_removal)
        p.openSettings.connect(self.ai_settings)
        self.canvas.outlineApply.connect(self._outline_apply)
        self.canvas.outlineCancel.connect(self._outline_cancel)
        self._outline_mode = None
        self._removal = None

        def group(name):
            w = QWidget()
            w.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
            lay = QHBoxLayout(w)
            lay.setContentsMargins(8, 0, 8, 0)
            lay.setSpacing(8)
            self.opt_groups[name] = self.opts.addWidget(w)
            self.opt_groups[name].setVisible(False)
            return lay

        # ---- options while selecting objects to remove
        lay = group("select")
        self.select_info = QLabel()
        self.select_info.setObjectName("hintLabel")
        lay.addWidget(self.select_info)
        self.smaller_btn = QPushButton("Smaller Part")
        self.smaller_btn.setToolTip("Selected too much? Switch the last object between the whole "
                                    "object and smaller parts of it.")
        self.smaller_btn.clicked.connect(self._smaller_part)
        clear = QPushButton("Clear")
        clear.setToolTip("Deselect everything")
        clear.clicked.connect(lambda: self._outline_call("clear"))
        self.remove_sel_btn = QPushButton("Remove Selected")
        self.remove_sel_btn.setObjectName("accent")
        self.remove_sel_btn.setToolTip("Make the selected objects transparent (Enter)")
        self.remove_sel_btn.clicked.connect(self._outline_apply)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(lambda: self.select_tool("hand"))
        for b in (self.smaller_btn, clear, self.remove_sel_btn, cancel):
            lay.addWidget(b)

        # ---- options while refining an outline (cut-out or removal)
        lay = group("outline")
        self.outline_info = QLabel()
        self.outline_info.setObjectName("hintLabel")
        lay.addWidget(self.outline_info)
        for text, tip, method in (
                ("More Points", "Use more dots for finer control", "more_points"),
                ("Fewer Points", "Use fewer dots to simplify the outline", "fewer_points")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, m=method: self._outline_call(m))
            lay.addWidget(b)
        self.points_lbl = QLabel("Points")
        self.points_spin = QSpinBox()
        self.points_spin.setRange(8, 5000)
        self.points_spin.setSingleStep(25)
        self.points_spin.setKeyboardTracking(False)
        self.points_spin.setToolTip("How many dots to use for the outline. More dots follow the "
                                    "edge more closely; fewer are quicker to adjust.\n"
                                    "Changing this re-traces the original edge, so no detail is lost.")
        self.points_spin.valueChanged.connect(self._points_changed)
        lay.addWidget(self.points_lbl)
        lay.addWidget(self.points_spin)
        self.crisp_chk = QCheckBox("Crisp edges")
        self.crisp_chk.setToolTip("Make the AI's soft edges solid everywhere, e.g. if a hand "
                                  "or object looks faded. Leave off for hair and fur.")
        lay.addWidget(self.crisp_chk)
        lay.addWidget(QLabel("Edge softness"))
        self.feather = NoWheelSlider(Qt.Horizontal)
        self.feather.setRange(0, 20)
        self.feather.setValue(1)
        self.feather.setFixedWidth(90)
        self.feather.setToolTip("0 = crisp edge. Higher values blend the edge more softly.")
        lay.addWidget(self.feather)
        self.outline_apply_btn = QPushButton("Apply Outline")
        self.outline_apply_btn.setObjectName("accent")
        self.outline_apply_btn.clicked.connect(self._outline_apply)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(lambda: self.select_tool("hand"))
        lay.addWidget(self.outline_apply_btn)
        lay.addWidget(cancel)

    def _outline_call(self, method):
        if self.canvas.outline is not None:
            getattr(self.canvas.outline, method)()
            self.canvas.setFocus()

    def _end_outline(self):
        self.canvas.outline.remove()
        self.canvas.outline = None
        self.canvas.set_backdrop(None)
        self._outline_mode = None

    def _outline_cancel(self):
        if self._outline_mode == "seltool":
            return  # Esc with a selection tool does nothing special (Ctrl+D deselects)
        self.select_tool("hand")

    def _outline_apply(self):
        mode = self._outline_mode
        if mode == "seltool":
            return
        if mode == "ai_select":
            self._remove_selected()
            return
        ed = self.canvas.outline
        if ed is None or not ed.has_shape():
            return
        if mode == "sel_refine":
            self.doc.set_selection(ed.result_mask(self.feather.value()), "Refine selection edge")
            self.select_tool("lasso")
            self.hint_lbl.setText("Selection edge refined. Ctrl+Z to undo.")
            return
        if mode == "ai_refine_removal":
            src, index = self._removal
            removed = ed.result_mask(self.feather.value())
            px = src.copy()
            px[..., 3] = (src[..., 3].astype(np.uint16) * (255 - removed) // 255).astype(np.uint8)
            if index < len(self.doc.layers):
                self.doc.set_layer_pixels(px, "Refine removal", index=index)
            self.select_tool("hand")
            self.hint_lbl.setText("Removal outline applied. Ctrl+Z to undo.")
        else:
            layer = self.doc.active_layer()
            px = layer.pixels.copy()
            base = ai_tasks.crisp_edges(ed.ref) if self.crisp_chk.isChecked() else None
            px[..., 3] = ed.result_mask(self.feather.value(), base)
            self.doc.set_layer_pixels(px, "Refine outline")
            self.select_tool("hand")
            self.hint_lbl.setText("Outline applied. Ctrl+Z to undo.")

    # ------------------------------------------------------------------ refine outline
    def _start_refine(self, mode, ref_mask, backdrop):
        """Show draggable dots around ref_mask over the full, uncut photo."""
        self.select_tool("ai_refine")
        if self.canvas.outline is not None:
            self._end_outline()
        removal = mode == "ai_refine_removal"
        ed = OutlineEditor(self.canvas, QColor(255, 70, 70) if removal else QColor(40, 200, 255),
                           shade="inside" if removal else "outside")
        ed.on_change = self._outline_changed
        self.canvas.outline = ed
        self._outline_mode = mode
        self.crisp_chk.setVisible(mode == "ai_refine")
        full = backdrop.copy()
        full[..., 3] = 255
        self.canvas.set_backdrop(imageio.to_qimage(full))
        spin = self.ai_panel.removal_points if removal else self.ai_panel.points
        ed.load_mask(ref_mask, spin.value())
        self.opt_title.setText({"ai_refine_removal": "  Refine Removal  ",
                                "sel_refine": "  Refine Selection Edge  "}.get(
            mode, "  Refine Outline  "))
        self.canvas.setFocus()
        self._outline_changed()
        return ed

    def _outline_changed(self):
        ed = self.canvas.outline
        if ed is None or self._outline_mode in ("ai_select", "seltool"):
            return
        n = ed.point_count()
        what = {"ai_refine_removal": "removed (darkened red)",
                "sel_refine": "selected"}.get(self._outline_mode, "kept")
        self.outline_info.setText(f"{n} dots. Area {what}. Drag dots, click a line to add one, "
                                  "right-click to delete")
        self.outline_apply_btn.setEnabled(ed.has_shape())
        self.points_spin.blockSignals(True)
        self.points_spin.setValue(n)
        self.points_spin.blockSignals(False)

    def _points_changed(self, n):
        if self.canvas.outline is not None and self._outline_mode not in ("ai_select", "seltool"):
            self.canvas.outline.set_point_count(n)
            self.canvas.setFocus()

    def ai_refine_outline(self):
        if not self.doc:
            return
        layer = self.doc.active_layer()
        alpha = layer.pixels[..., 3]
        if alpha.min() > 250:
            QMessageBox.information(
                self, "Refine Outline",
                "The selected layer has no transparent areas to refine.\n\n"
                "Use Remove Background first, then select the Cutout layer.")
            return
        polys, _ = trace_mask(alpha)
        if not polys:
            QMessageBox.information(self, "Refine Outline", "This layer is almost empty.")
            return
        self._start_refine("ai_refine", alpha, layer.pixels)
        self.crisp_chk.setChecked(self.ai_panel.edges.currentData() == "crisp")

    # ------------------------------------------------------------------ remove background
    def ai_remove_background(self):
        if not self.doc:
            return
        comp = np.array(self.doc.composite())
        crisp = self.ai_panel.edges.currentData() == "crisp"

        def done(mask):
            # Anything the AI mostly kept becomes fully solid inside; only the edge stays soft.
            mask = solidify(mask, mask, 1.0)
            if crisp:
                mask = ai_tasks.crisp_edges(mask)
            px = comp.copy()
            px[..., 3] = np.minimum(px[..., 3], mask)
            self.doc.add_result_layer(px, "Cutout", "Remove background", hide_others=True)
            self.ai_panel.refresh()
            self.hint_lbl.setText("Background removed! Your original is kept (hidden) in Layers. "
                                  "Not perfect? Click AI → Refine Outline to adjust the edge.")

        run_ai(self, ai_cloud.models_needed(["birefnet_lite"]), "Remove Background",
               "Finding the subject…", lambda: ai_cloud.remove_background(comp), done)

    # ------------------------------------------------------------------ select & remove objects
    def _start_select(self):
        """Analyse the photo once (SAM image encoder); then clicks select objects instantly."""
        comp = np.array(self.doc.composite())
        token = object()
        self._select_token = token

        def done(sam):
            if self._select_token is not token or self.state.tool != "ai_remove" or not self.doc:
                return
            if self.canvas.outline is not None:
                self._end_outline()
            sel = ObjectSelector(self.canvas, sam)
            sel.on_change = self._select_changed
            sel.on_error = lambda msg: QMessageBox.warning(self, "Select Objects", msg)
            self.canvas.outline = sel
            self._outline_mode = "ai_select"
            self.ai_panel.refresh()
            self.canvas.setFocus()
            self._select_changed()

        self.select_info.setText("Getting ready…")
        self.remove_sel_btn.setEnabled(False)
        self.smaller_btn.setEnabled(False)
        run_ai(self, ai_cloud.models_needed(["sam2"]), "Select Objects", "Looking at the photo…",
               lambda: ai_cloud.sam_image(comp), done)

    def _select_changed(self):
        sel = self.canvas.outline
        if sel is None or self._outline_mode != "ai_select":
            return
        n = sel.count()
        if n == 0:
            msg = "Click the object(s) you want to remove"
        else:
            msg = (f"{n} object{'s' if n != 1 else ''} selected. Click more, click one again to "
                   "deselect, Shift+click to add an area, right-click to exclude an area")
        self.select_info.setText(msg)
        self.remove_sel_btn.setEnabled(n > 0)
        self.smaller_btn.setEnabled(n > 0 and len(sel.objects[-1].points) == 1)

    def _smaller_part(self):
        if self._outline_mode == "ai_select":
            self.canvas.outline.smaller_part()
            self.canvas.setFocus()

    def ai_settings(self):
        AISettingsDialog(self, self.cloud_conn).exec()
        self.ai_panel.refresh()

    def _cloud_changed(self, state, message):
        text = {"connected": "☁ GPU connected", "connecting": "☁ Connecting…",
                "offline": "☁ GPU off: using this PC", "local": "💻 AI on this PC"}[state]
        self.cloud_lbl.setText(text)
        self.cloud_lbl.setToolTip(message + "\nClick for AI Settings.")
        self.ai_panel.refresh()
        if state in ("connected", "offline", "connecting"):
            self.hint_lbl.setText(message)

    def ai_refine_removal(self):
        """Re-open the removal outline of an "Objects removed" layer."""
        if not self.doc:
            return
        layers = self.doc.layers
        index = self.doc.active
        if layers[index].source is None:  # fall back to the topmost removal layer
            index = next((i for i in range(len(layers) - 1, -1, -1)
                          if layers[i].source is not None), None)
        if index is None:
            QMessageBox.information(
                self, "Refine Removal",
                "There's no removed object to refine yet.\n\n"
                "Use Select Object(s) to Remove first.")
            return
        self.doc.active = index
        self.layers_panel.rebuild()
        layer = layers[index]
        src_a = layer.source[..., 3].astype(np.float32)
        cur_a = layer.pixels[..., 3].astype(np.float32)
        removed = np.where(src_a > 0, 255 - cur_a * 255 / np.maximum(src_a, 1), 0)
        removed = np.clip(removed + 0.5, 0, 255).astype(np.uint8)
        if not (removed > 127).any():
            QMessageBox.information(self, "Refine Removal", "Nothing is removed on this layer.")
            return
        self._removal = (layer.source, index)
        self._start_refine("ai_refine_removal", removed, layer.source)

    def _layer_for_mask(self, mask):
        """The topmost visible layer that actually has pixels where the objects are."""
        sel = mask > 127
        for i in range(len(self.doc.layers) - 1, -1, -1):
            layer = self.doc.layers[i]
            if layer.visible and layer.pixels[..., 3][sel].mean() > 128:
                return i
        return self.doc.active

    def _remove_selected(self):
        sel = self.canvas.outline
        if sel is None or not sel.count():
            return
        mask = solidify(sel.mask(), sel.mask(), 1.0)
        index = self._layer_for_mask(mask)
        src = self.doc.layers[index].pixels
        px = src.copy()
        px[..., 3] = (src[..., 3].astype(np.uint16) * (255 - mask) // 255).astype(np.uint8)
        n = sel.count()
        self.doc.add_derived_layer(px, "Objects removed", f"Remove {n} object{'s' * (n != 1)}",
                                   index)
        self._removal = (src, index + 1)
        self._start_refine("ai_refine_removal", mask, src)
        self.hint_lbl.setText(
            "Removed! The area is now transparent, so the layer below shows through. Adjust the "
            "red outline if needed and press Enter, or pick another tool to keep it as is.")

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
            self.settings.setValue("window/geometry", self.saveGeometry())
            self.settings.setValue("files/last_dir", self._dir)
            self.settings.setValue("files/recent", self._recent)
            self.settings.sync()
            self.cloud_conn.stop()
            QThreadPool.globalInstance().waitForDone(5000)
            e.accept()
        else:
            e.ignore()
