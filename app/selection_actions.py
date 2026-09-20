"""Main-window glue for selections: tools, Select menu, Select panel and retouching.

Mixed into MainWindow, so `self` is the main window.
"""
import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QKeySequence
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QColorDialog, QComboBox,
                               QHBoxLayout, QInputDialog, QLabel, QMenu, QMessageBox, QSizePolicy,
                               QSpinBox, QToolButton, QWidget)

from . import retouch, selection
from .selection import LassoTool, MarqueeTool, WandTool
from .selection_panel import SelectionPanel

SELECT_TOOLS = ("marquee", "lasso", "wand")

SELECT_TOOL_INFO = [
    ("marquee", "Marquee", "M", "Marquee (M): drag a rectangle or ellipse to select. "
                                "Shift adds, Alt subtracts."),
    ("lasso", "Lasso", "L", "Lasso (L): draw around what you want. Magnetic snaps to edges; "
                            "Polygonal clicks point to point (double-click or Enter to finish)."),
    ("wand", "Wand", "W", "Magic Wand (W): click a color to select similar pixels. Raise "
                          "Tolerance to select more. Shift adds, Alt subtracts."),
    ("heal", "Heal", "J", "Spot Healing Brush (J): paint over a blemish, scar or spot and "
                          "release. It's replaced with matching surrounding texture."),
]


class SelectionActions:
    # ------------------------------------------------------------------ setup
    def _build_selection(self):
        self._sel_opts = {"mode": "new", "shape": "rect", "lasso": "freehand", "tolerance": 32,
                          "contiguous": True, "sample_all": True, "antialias": True}
        self._edges_cache = None
        self.sel_panel = SelectionPanel()
        self.tabs.addTab(self.sel_panel, "Select")
        self.sel_panel.action.connect(self._sel_command)
        self.canvas.healFinished.connect(self._heal_stroke)
        self.canvas.contextRequested.connect(self._sel_context_menu)
        self.canvas.strokeFinished.disconnect()
        self.canvas.strokeFinished.connect(self._stroke_finished)
        self._build_select_menu()
        self._build_select_options()

    def _build_select_menu(self):
        A = self._act
        acts = {
            "all": A("All", lambda: self._sel_command("all"), "Ctrl+A"),
            "deselect": A("Deselect", lambda: self._sel_command("deselect"), "Ctrl+D"),
            "inverse": A("Inverse", lambda: self._sel_command("inverse"), "Ctrl+Shift+I"),
            "subject": A("Subject (AI)", lambda: self._sel_command("subject")),
            "skin": A("Skin Tones", lambda: self._sel_command("skin")),
            "redeye": A("Remove Red Eye", lambda: self._sel_command("redeye")),
            "feather": A("Feather…", lambda: self._sel_command("feather_ask"), "Shift+F6"),
            "expand": A("Expand…", lambda: self._sel_command("expand_ask")),
            "contract": A("Contract…", lambda: self._sel_command("contract_ask")),
            "smooth": A("Smooth…", lambda: self._sel_command("smooth_ask")),
            "border": A("Border…", lambda: self._sel_command("border_ask")),
            "refine": A("Refine Edge…", lambda: self._sel_command("refine")),
            "via_copy": A("Layer via Copy", lambda: self._sel_command("via_copy"), "Ctrl+J"),
            "via_cut": A("Layer via Cut", lambda: self._sel_command("via_cut"), "Ctrl+Shift+J"),
            "delete": A("Clear Selected Pixels", lambda: self._sel_command("delete"), "Delete"),
            "fill": A("Fill…", lambda: self._sel_command("fill"), "Shift+F5"),
            "stroke": A("Stroke…", lambda: self._sel_command("stroke")),
            "crop": A("Crop to Selection", lambda: self._sel_command("crop")),
        }
        self.sel_actions = acts
        # Ctrl+J copies the selection to a layer (or duplicates the layer when nothing is
        # selected), like Photoshop.
        self.a_layer_dup.setShortcut(QKeySequence())
        m = QMenu("&Select", self)
        self.menuBar().insertMenu(self.ai_menu.menuAction(), m)
        for k in ("all", "deselect", "inverse", None, "subject", "skin", "redeye", None):
            m.addSeparator() if k is None else m.addAction(acts[k])
        mod = m.addMenu("Modify")
        for k in ("feather", "expand", "contract", "smooth", "border"):
            mod.addAction(acts[k])
        m.addAction(acts["refine"])
        m.addSeparator()
        for k in ("via_copy", "via_cut", "delete", "fill", "stroke", "crop"):
            m.addAction(acts[k])
        self.doc_actions += list(acts.values())
        for a in acts.values():
            a.setEnabled(self.doc is not None)

    def _build_select_options(self):
        def group(name, tools):
            w = QWidget()
            w.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
            lay = QHBoxLayout(w)
            lay.setContentsMargins(8, 0, 8, 0)
            lay.setSpacing(8)
            self.opt_groups[name] = self.opts.addWidget(w)
            self.opt_groups[name].setVisible(False)
            self.opt_group_tools[name] = tools
            return lay

        lay = group("selmode", SELECT_TOOLS)
        lay.addWidget(QLabel("Mode"))
        self.selmode_group = QButtonGroup(self)
        for i, (mode, text, tip) in enumerate((
                ("new", "New", "Replace the selection"),
                ("add", "Add", "Add to the selection (or hold Shift)"),
                ("subtract", "Subtract", "Remove from the selection (or hold Alt)"),
                ("intersect", "Intersect", "Keep only the overlap (or hold Shift+Alt)"))):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.setCheckable(True)
            b.setChecked(i == 0)
            self.selmode_group.addButton(b, i)
            lay.addWidget(b)
        self.selmode_group.idClicked.connect(
            lambda i: self._sel_opts.__setitem__("mode", selection.MODES[i]))

        lay = group("marquee", ("marquee",))
        shape = QComboBox()
        shape.addItem("Rectangle", "rect")
        shape.addItem("Ellipse", "ellipse")
        shape.currentIndexChanged.connect(
            lambda i: self._sel_opts.__setitem__("shape", shape.itemData(i)))
        lay.addWidget(QLabel("Shape"))
        lay.addWidget(shape)

        lay = group("lasso", ("lasso",))
        kind = QComboBox()
        for text, key in (("Freehand: drag around it", "freehand"),
                          ("Magnetic: snaps to edges", "magnetic"),
                          ("Polygonal: click corners", "polygonal")):
            kind.addItem(text, key)
        kind.setToolTip("Freehand: hold the mouse and draw.\nMagnetic: click once, then move "
                        "along the edge; it snaps to the edge. Click the start point, "
                        "double-click or press Enter to finish.\nPolygonal: click each corner.")
        kind.currentIndexChanged.connect(
            lambda i: self._sel_opts.__setitem__("lasso", kind.itemData(i)))
        lay.addWidget(QLabel("Type"))
        lay.addWidget(kind)

        lay = group("wand", ("wand",))
        lay.addWidget(QLabel("Tolerance"))
        tol = QSpinBox()
        tol.setRange(0, 255)
        tol.setValue(32)
        tol.setToolTip("How different a color can be and still be selected (0 = exact match).")
        tol.valueChanged.connect(lambda v: self._sel_opts.__setitem__("tolerance", v))
        lay.addWidget(tol)
        for text, key, tip in (
                ("Contiguous", "contiguous", "Only select touching pixels. Turn off to select "
                                             "that color everywhere."),
                ("Sample all layers", "sample_all", "Use what you see, not just the selected "
                                                    "layer."),
                ("Anti-alias", "antialias", "Smooth the selection edge.")):
            chk = QCheckBox(text)
            chk.setChecked(self._sel_opts[key])
            chk.setToolTip(tip)
            chk.toggled.connect(lambda on, k=key: self._sel_opts.__setitem__(k, on))
            lay.addWidget(chk)

        lay = group("heal", ("heal",))
        lay.addWidget(QLabel("Size"))
        self.heal_size = NoWheelSlider_(self)
        lay.addWidget(self.heal_size)
        self.heal_size_lbl = QLabel()
        lay.addWidget(self.heal_size_lbl)
        self.heal_size.valueChanged.connect(self._heal_size_changed)
        self.heal_size.setValue(30)
        hint = QLabel("Paint over a spot and release. Use [ and ] to resize.")
        hint.setObjectName("hintLabel")
        lay.addWidget(hint)

    def _heal_size_changed(self, v):
        self.heal_size_lbl.setText(f"{v} px")
        if self.state.tool == "heal":
            self.state.brush_size = v

    # ------------------------------------------------------------------ tools
    def _on_tool_selected(self, key):
        """Called by select_tool: install the interactive selection tool, if any."""
        if key == "heal":
            self.state.brush_size = self.heal_size.value()
        elif key in ("brush", "eraser", "clone"):
            self.state.brush_size = self.size_slider.value()
        if key not in SELECT_TOOLS or not self.doc:
            return
        if self.canvas.outline is not None:
            self._end_outline()
        self._edges_cache = None
        d = self.doc
        opts = lambda: self._sel_opts  # noqa: E731
        if key == "marquee":
            tool = MarqueeTool(self.canvas, d.width, d.height, self._sel_commit, opts)
        elif key == "lasso":
            tool = LassoTool(self.canvas, d.width, d.height, self._sel_commit, opts, self._edges)
        else:
            tool = WandTool(self.canvas, d.width, d.height, self._sel_commit, opts, self._sample)
        self.canvas.outline = tool
        self._outline_mode = "seltool"
        self.canvas.setFocus()

    def _edges(self):
        if self._edges_cache is None:
            gray = cv2.cvtColor(np.ascontiguousarray(self.doc.composite()[..., :3]),
                                cv2.COLOR_RGB2GRAY)
            gray = cv2.GaussianBlur(gray, (0, 0), 1.0)
            mag = cv2.magnitude(cv2.Sobel(gray, cv2.CV_32F, 1, 0), cv2.Sobel(gray, cv2.CV_32F, 0, 1))
            self._edges_cache = mag
        return self._edges_cache

    def _sample(self, sample_all):
        return self.doc.composite() if sample_all else self.doc.active_layer().pixels

    def _sel_commit(self, mask, mode, label):
        d = self.doc
        if mask is None:
            if d.selection is not None:
                d.set_selection(None, "Deselect")
            return
        new = selection.combine(d.selection, mask, mode)
        if mode != "new":
            label = {"add": "Add to selection", "subtract": "Subtract from selection",
                     "intersect": "Intersect selection"}[mode]
        d.set_selection(new, label)

    def _selection_changed(self, from_tool=True):
        sel = self.doc.selection if self.doc else None
        self.canvas.set_selection(sel)
        if sel is None:
            self.sel_panel.set_selection_info(None)
            return
        box = selection.bbox(sel)
        if box is None:
            self.sel_panel.set_selection_info(None)
            return
        x0, y0, x1, y1 = box
        pct = 100.0 * (sel > 127).mean()
        self.sel_panel.set_selection_info((x1 - x0, y1 - y0, pct))
        if from_tool and self.tabs.currentWidget() is not self.sel_panel:
            self.tabs.setCurrentWidget(self.sel_panel)

    # ------------------------------------------------------------------ commands
    def _need_selection(self):
        if self.doc is None or self.doc.selection is None:
            self.hint_lbl.setText("Make a selection first: Lasso (L), Magic Wand (W) or "
                                  "Marquee (M).")
            return None
        return self.doc.selection

    def _target_layer(self):
        layer = self.doc.active_layer()
        if not layer.visible:
            QMessageBox.information(self, "PhotoForge",
                                    f"The selected layer '{layer.name}' is hidden. Show it or "
                                    "select another layer in the Layers tab first.")
            return None
        return layer

    def _sel_command(self, cmd):
        d = self.doc
        if d is None:
            return
        p = self.sel_panel
        amt = p.amount.value()
        ov = self.canvas.outline
        if cmd == "delete" and ov is not None and ov.key(Qt.Key_Delete):
            return  # the Delete key went to the active tool (e.g. remove the last lasso point)
        if cmd == "all":
            d.set_selection(np.full((d.height, d.width), 255, np.uint8), "Select all")
        elif cmd == "deselect":
            if d.selection is not None:
                d.set_selection(None, "Deselect")
        elif cmd == "subject":
            self._select_subject()
        elif cmd == "redeye":
            self._do_redeye(d.selection)
        elif cmd == "skin":
            mask = selection.skin_tones(d.composite())
            if (mask > 127).mean() < 0.001:
                self.hint_lbl.setText("No skin tones found in this image.")
                return
            d.set_selection(mask, "Select skin tones")
        elif cmd.endswith("_ask"):
            sel = self._need_selection()
            if sel is None:
                return
            name = cmd[:-4]
            v, ok = QInputDialog.getInt(self, name.title(), f"{name.title()} by (pixels):",
                                        amt, 1, 500)
            if ok:
                p.amount.setValue(v)
                self._sel_command(name)
        elif cmd in ("inverse", "feather", "expand", "contract", "smooth", "border"):
            sel = self._need_selection()
            if sel is None:
                return
            fn = {"inverse": lambda m: 255 - m,
                  "feather": lambda m: selection.feather(m, amt),
                  "expand": lambda m: selection.expand(m, amt),
                  "contract": lambda m: selection.contract(m, amt),
                  "smooth": lambda m: selection.smooth(m, amt),
                  "border": lambda m: selection.border(m, amt)}[cmd]
            d.set_selection(fn(sel), cmd.title() + " selection")
        elif cmd == "refine":
            sel = self._need_selection()
            if sel is not None:
                self._start_refine("sel_refine", sel, np.array(d.composite()))
        elif cmd == "via_copy":
            if d.selection is None:
                d.duplicate_layer()
            else:
                d.layer_via_selection(cut=False)
        elif cmd in ("via_cut", "delete", "fill", "stroke", "crop", "blemishes", "smooth_skin",
                     "redness", "heal"):
            sel = self._need_selection()
            if sel is None:
                return
            getattr(self, "_do_" + cmd)(sel)

    def _do_redeye(self, sel):
        """Fix flash red-eye. With nothing selected, the whole photo is searched."""
        d = self.doc
        whole = sel is None
        if whole:
            sel = np.full((d.height, d.width), 255, np.uint8)
        n = self._retouch("Remove red eye", lambda rgb, s: retouch.remove_red_eye(rgb, s), sel)
        if n:
            self.hint_lbl.setText(f"Fixed {n} red eye{'s' if n != 1 else ''}. Ctrl+Z to undo.")
        elif n == 0:
            self.hint_lbl.setText(
                "No red eyes found" + (" in the photo. Try selecting around the eyes first "
                                       "(Marquee, M) and trying again."
                                       if whole else " in the selection."))

    def _do_via_cut(self, sel):
        if self._target_layer():
            self.doc.layer_via_selection(cut=True)

    def _do_delete(self, sel):
        layer = self._target_layer()
        if layer:
            px = layer.pixels.copy()
            px[..., 3] = (px[..., 3].astype(np.uint16) * (255 - sel) // 255).astype(np.uint8)
            self.doc.set_layer_pixels(px, "Clear selection")

    def _do_fill(self, sel):
        layer = self._target_layer()
        if not layer:
            return
        c = QColorDialog.getColor(self.state.color, self, "Fill the selection with…")
        if not c.isValid():
            return
        solid = layer.pixels.copy()
        solid[..., :3] = (c.red(), c.green(), c.blue())
        solid[..., 3] = 255
        self.doc.set_layer_pixels(selection.apply_masked(layer.pixels, solid, sel), "Fill")

    def _do_stroke(self, sel):
        layer = self._target_layer()
        if not layer:
            return
        width, ok = QInputDialog.getInt(self, "Stroke", "Line width (pixels):", 4, 1, 200)
        if not ok:
            return
        c = QColorDialog.getColor(self.state.color, self, "Stroke color")
        if not c.isValid():
            return
        band = selection.border(sel, width)
        solid = layer.pixels.copy()
        solid[..., :3] = (c.red(), c.green(), c.blue())
        solid[..., 3] = 255
        self.doc.set_layer_pixels(selection.apply_masked(layer.pixels, solid, band), "Stroke")

    def _do_crop(self, sel):
        box = selection.bbox(sel)
        if box:
            x0, y0, x1, y1 = box
            self.doc.crop(x0, y0, x1 - x0, y1 - y0)

    def _retouch(self, label, fn, sel):
        layer = self._target_layer()
        if not layer:
            return None
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            rgb = np.ascontiguousarray(layer.pixels[..., :3])
            result = fn(rgb, sel)
        finally:
            QApplication.restoreOverrideCursor()
        new_rgb, extra = result if isinstance(result, tuple) else (result, None)
        if new_rgb is rgb:
            return extra
        px = layer.pixels.copy()
        px[..., :3] = new_rgb
        self.doc.set_layer_pixels(px, label)
        return extra

    def _spot_px(self, sel):
        box = selection.bbox(sel)
        diag = np.hypot(box[2] - box[0], box[3] - box[1]) if box else 500
        return int(max(4, self.sel_panel.spot.value() * 0.008 * diag))

    def _do_blemishes(self, sel):
        size = self._spot_px(sel)
        sens = self.sel_panel.sens.value()
        n = self._retouch("Remove blemishes",
                          lambda rgb, s: retouch.remove_blemishes(rgb, s, size, sens), sel)
        if n == 0:
            self.hint_lbl.setText("No blemishes found. Try raising Sensitivity or Spot size.")
        elif n:
            self.hint_lbl.setText(f"Removed {n} blemish{'es' if n != 1 else ''}. Ctrl+Z to "
                                  "undo, or use the Spot Healing Brush (J) for any left.")

    def _do_smooth_skin(self, sel):
        p = self.sel_panel
        self._retouch("Smooth skin", lambda rgb, s: retouch.smooth_skin(
            rgb, s, p.smooth_amt.value(), p.texture.value()), sel)
        self.hint_lbl.setText("Skin smoothed. Toggle Ctrl+Z / Ctrl+Y to compare before and after.")

    def _do_redness(self, sel):
        self._retouch("Reduce redness", lambda rgb, s: retouch.reduce_redness(
            rgb, s, self.sel_panel.red_amt.value()), sel)

    def _do_heal(self, sel):
        if (sel > 127).mean() > 0.25:
            r = QMessageBox.question(
                self, "Heal Selection",
                "Healing works best on small areas (spots, scars, small objects). This "
                "selection is large, so the result may look smeared.\n\nContinue anyway?")
            if r != QMessageBox.Yes:
                return
        self._retouch("Heal selection", retouch.heal, sel)

    # ------------------------------------------------------------------ select subject
    def _select_subject(self):
        from .ai import cloud
        from .ai.outline import solidify
        from .ai.runner import run_ai
        comp = np.array(self.doc.composite())

        def done(mask):
            self.doc.set_selection(solidify(mask, mask, 1.0), "Select subject")

        run_ai(self, cloud.models_needed(["birefnet_lite"]), "Select Subject",
               "Finding the subject…", lambda: cloud.remove_background(comp), done)

    # ------------------------------------------------------------------ brushes
    def _stroke_finished(self, px, label):
        layer = self.doc.active_layer()
        if self.doc.selection is not None:
            px = selection.apply_masked(layer.pixels, px, self.doc.selection)
        self.doc.set_layer_pixels(px, label)

    def _heal_stroke(self, mask):
        layer = self._target_layer()
        if layer is None or not (mask > 0).any():
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            soft = cv2.GaussianBlur(mask, (0, 0), 1.2)
            rgb = retouch.heal(np.ascontiguousarray(layer.pixels[..., :3]), soft)
        finally:
            QApplication.restoreOverrideCursor()
        px = layer.pixels.copy()
        px[..., :3] = rgb
        if self.doc.selection is not None:
            px = selection.apply_masked(layer.pixels, px, self.doc.selection)
        self.doc.set_layer_pixels(px, "Spot healing")

    # ------------------------------------------------------------------ context menu
    def _sel_context_menu(self, global_pos):
        if self.doc is None:
            return
        m = QMenu(self)
        a = self.sel_actions
        has = self.doc.selection is not None
        if has:
            for k in ("deselect", "inverse", None, "feather", "refine", None, "via_copy",
                      "via_cut", "delete", "fill", "stroke", "crop"):
                m.addSeparator() if k is None else m.addAction(a[k])
            m.addSeparator()
            for text, cmd in (("Remove Blemishes", "blemishes"), ("Smooth Skin", "smooth_skin"),
                              ("Remove Red Eye", "redeye"), ("Heal Selection", "heal")):
                act = QAction(text, m)
                act.triggered.connect(lambda _=False, c=cmd: self._sel_command(c))
                m.addAction(act)
        else:
            for k in ("all",):
                m.addAction(a[k])
            m.addAction(a["subject"])
            m.addAction(a["skin"])
            m.addAction(a["redeye"])
        m.exec(global_pos)


def NoWheelSlider_(parent):
    from .panels import NoWheelSlider
    s = NoWheelSlider(Qt.Horizontal)
    s.setRange(2, 400)
    s.setFixedWidth(130)
    s.setToolTip("Brush size. Make it a little bigger than the spot.")
    return s
