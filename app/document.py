"""The document: a stack of layers, develop settings and undo history.

Layer pixel arrays are treated as immutable: every edit assigns a *new* array.
That lets undo snapshots share arrays instead of copying whole images.
"""
import time

import numpy as np
from PySide6.QtCore import QObject, Signal

from . import adjustments, imageio

BLEND_MODES = ["Normal", "Multiply", "Screen", "Overlay", "Soft Light", "Darken", "Lighten"]
MAX_UNDO = 40


def _blend(mode, cb, cs):
    if mode == "Multiply":
        return cb * cs
    if mode == "Screen":
        return cb + cs - cb * cs
    if mode == "Overlay":
        return np.where(cb <= 0.5, 2 * cb * cs, 1 - 2 * (1 - cb) * (1 - cs))
    if mode == "Soft Light":
        return (1 - 2 * cs) * cb * cb + 2 * cs * cb
    if mode == "Darken":
        return np.minimum(cb, cs)
    if mode == "Lighten":
        return np.maximum(cb, cs)
    return cs


class Layer:
    def __init__(self, name, pixels, visible=True, opacity=1.0, blend="Normal"):
        self.name = name
        self.pixels = pixels
        self.visible = visible
        self.opacity = opacity
        self.blend = blend
        self.mask = None    # HxW uint8 layer mask: 255 shows the pixel, 0 hides it
        self.thumb = None
        self.thumb_src = None
        self.mask_thumb = None
        self.mask_thumb_src = None
        self.source = None  # pixels this layer was cut from (e.g. by object removal)

    def copy(self):
        c = Layer(self.name, self.pixels, self.visible, self.opacity, self.blend)
        c.thumb, c.thumb_src, c.source = self.thumb, self.thumb_src, self.source
        c.mask, c.mask_thumb, c.mask_thumb_src = self.mask, self.mask_thumb, self.mask_thumb_src
        return c


class Document(QObject):
    # kind: "structure" (layer list), "composite" (layer props), "pixels", "adjust", "all"
    changed = Signal(str)
    historyChanged = Signal()

    def __init__(self, width, height, layers, path=None):
        super().__init__()
        self.width, self.height = width, height
        self.layers = layers
        self.active = len(layers) - 1
        self.adjust = dict(adjustments.DEFAULTS)
        self.path = path
        self.dirty = False
        self.selection = None  # HxW uint8 mask (255 = selected) or None
        self._undo, self._redo = [], []

    @classmethod
    def from_image(cls, pixels, name="Background", path=None):
        h, w = pixels.shape[:2]
        return cls(w, h, [Layer(name, pixels)], path)

    @classmethod
    def blank(cls, w, h, color=(255, 255, 255, 255)):
        px = np.empty((h, w, 4), np.uint8)
        px[:] = color
        return cls(w, h, [Layer("Background", px)])

    # ------------------------------------------------------------------ history
    def _snapshot(self):
        return ([l.copy() for l in self.layers], dict(self.adjust), self.active,
                self.width, self.height, self.selection)

    def _restore(self, snap):
        layers, adj, self.active, self.width, self.height, self.selection = snap
        self.layers = [l.copy() for l in layers]
        self.adjust = dict(adj)

    def push_undo(self, label, coalesce=None):
        """Record the current state before a change. Calls with the same `coalesce`
        key within 1.5s are merged into one step (e.g. dragging a slider)."""
        now = time.monotonic()
        if coalesce and self._undo:
            last = self._undo[-1]
            if last[1] == coalesce and now - last[2] < 1.5:
                self._undo[-1] = (last[0], coalesce, now, last[3])
                return
        self._undo.append((label, coalesce, now, self._snapshot()))
        del self._undo[:-MAX_UNDO]
        self._redo.clear()
        self.dirty = True
        self.historyChanged.emit()

    def undo_label(self):
        return self._undo[-1][0] if self._undo else None

    def redo_label(self):
        return self._redo[-1][0] if self._redo else None

    def undo(self):
        if not self._undo:
            return
        label, _, _, snap = self._undo.pop()
        self._redo.append((label, None, 0, self._snapshot()))
        self._restore(snap)
        self.dirty = True
        self.historyChanged.emit()
        self.changed.emit("all")

    def redo(self):
        if not self._redo:
            return
        label, _, _, snap = self._redo.pop()
        self._undo.append((label, None, 0, self._snapshot()))
        self._restore(snap)
        self.dirty = True
        self.historyChanged.emit()
        self.changed.emit("all")

    # ------------------------------------------------------------------ rendering
    def active_layer(self):
        return self.layers[self.active] if self.layers else None

    def composite(self, exclude=None):
        """Flatten visible layers into one RGBA uint8 image."""
        vis = [l for i, l in enumerate(self.layers)
               if l.visible and l.opacity > 0 and i != exclude]
        H, W = self.height, self.width
        if not vis:
            return np.zeros((H, W, 4), np.uint8)
        if len(vis) == 1 and vis[0].opacity >= 1 and vis[0].mask is None:
            return vis[0].pixels
        out = np.empty((H, W, 4), np.uint8)
        step = max(1, 2_000_000 // W)  # process in row bands to limit memory use
        for y0 in range(0, H, step):
            y1 = min(H, y0 + step)
            acc_c = np.zeros((y1 - y0, W, 3), np.float32)
            acc_a = np.zeros((y1 - y0, W, 1), np.float32)
            for l in vis:
                src = l.pixels[y0:y1].astype(np.float32) * (1 / 255)
                cs, sa = src[..., :3], src[..., 3:4] * l.opacity
                if l.mask is not None:      # the layer mask hides pixels without erasing them
                    sa = sa * (l.mask[y0:y1, :, None].astype(np.float32) * (1 / 255))
                if l.blend == "Normal":
                    mixed = cs
                else:
                    cb = np.divide(acc_c, acc_a, out=np.zeros_like(acc_c), where=acc_a > 0)
                    mixed = (1 - acc_a) * cs + acc_a * _blend(l.blend, cb, cs)
                acc_c = mixed * sa + acc_c * (1 - sa)
                acc_a = sa + acc_a * (1 - sa)
            rgb = np.divide(acc_c, acc_a, out=np.zeros_like(acc_c), where=acc_a > 0)
            out[y0:y1, :, :3] = np.clip(rgb * 255 + 0.5, 0, 255).astype(np.uint8)
            out[y0:y1, :, 3] = np.clip(acc_a[..., 0] * 255 + 0.5, 0, 255).astype(np.uint8)
        return out

    def render_final(self):
        return adjustments.apply(self.composite(), self.adjust, 1.0)

    # ------------------------------------------------------------------ layer ops
    def _unique_name(self, base):
        names = {l.name for l in self.layers}
        i = 1
        while f"{base} {i}" in names:
            i += 1
        return f"{base} {i}"

    def add_layer(self, pixels=None, name=None, label="New layer"):
        self.push_undo(label)
        if pixels is None:
            pixels = np.zeros((self.height, self.width, 4), np.uint8)
        self.layers.insert(self.active + 1, Layer(name or self._unique_name("Layer"), pixels))
        self.active += 1
        self.changed.emit("structure")

    def place_image(self, pixels, name):
        """Add an image as a new layer, scaled to fit and centered on the canvas."""
        h, w = pixels.shape[:2]
        f = min(1.0, self.width / w, self.height / h)
        if f < 1.0:
            w, h = max(1, int(w * f)), max(1, int(h * f))
            pixels = imageio.resize(pixels, w, h)
        canvas = np.zeros((self.height, self.width, 4), np.uint8)
        x, y = (self.width - w) // 2, (self.height - h) // 2
        canvas[y:y + h, x:x + w] = pixels
        self.add_layer(canvas, name, label="Place image")

    def duplicate_layer(self):
        self.push_undo("Duplicate layer")
        src = self.layers[self.active]
        dup = src.copy()
        dup.name = src.name + " copy"
        self.layers.insert(self.active + 1, dup)
        self.active += 1
        self.changed.emit("structure")

    def delete_layer(self):
        if len(self.layers) <= 1:
            return False
        self.push_undo("Delete layer")
        del self.layers[self.active]
        self.active = max(0, self.active - 1)
        self.changed.emit("structure")
        return True

    def move_layer(self, delta):
        j = self.active + delta
        if not 0 <= j < len(self.layers):
            return
        self.push_undo("Reorder layers")
        L = self.layers
        L[self.active], L[j] = L[j], L[self.active]
        self.active = j
        self.changed.emit("structure")

    def merge_down(self):
        if self.active == 0:
            return False
        self.push_undo("Merge down")
        tmp = Document(self.width, self.height,
                       [self.layers[self.active - 1], self.layers[self.active]])
        below = self.layers[self.active - 1]
        merged = Layer(below.name, np.array(tmp.composite()))
        del self.layers[self.active]
        self.active -= 1
        self.layers[self.active] = merged
        self.changed.emit("structure")
        return True

    def flatten(self):
        self.push_undo("Flatten image")
        self.layers = [Layer("Background", np.array(self.composite()))]
        self.active = 0
        self.changed.emit("structure")

    def add_result_layer(self, pixels, name, label, hide_others=False):
        """Put an AI result on a new top layer (one undo step)."""
        self.push_undo(label)
        if hide_others:
            for l in self.layers:
                l.visible = False
        self.layers.append(Layer(name, pixels))
        self.active = len(self.layers) - 1
        self.changed.emit("structure")

    def add_derived_layer(self, pixels, name, label, source):
        """Put an edited copy of layer `source` right above it and hide the original."""
        self.push_undo(label)
        self.layers[source].visible = False
        layer = Layer(name, pixels)
        layer.source = self.layers[source].pixels
        self.layers.insert(source + 1, layer)
        self.active = source + 1
        self.changed.emit("structure")

    def set_layer_pixels(self, pixels, label, index=None):
        self.push_undo(label)
        self.layers[self.active if index is None else index].pixels = pixels
        self.changed.emit("pixels")

    def shift_layer(self, dx, dy):
        src = self.layers[self.active].pixels
        H, W = src.shape[:2]
        out = np.zeros_like(src)
        sx0, sx1 = max(0, -dx), min(W, W - dx)
        sy0, sy1 = max(0, -dy), min(H, H - dy)
        if sx1 > sx0 and sy1 > sy0:
            out[sy0 + dy:sy1 + dy, sx0 + dx:sx1 + dx] = src[sy0:sy1, sx0:sx1]
        self.set_layer_pixels(out, "Move layer")

    # ------------------------------------------------------------------ image ops
    def _map_all(self, fn, label):
        self.push_undo(label)
        for l in self.layers:
            l.pixels = np.ascontiguousarray(fn(l.pixels))
            if l.mask is not None:
                l.mask = np.ascontiguousarray(fn(l.mask))
            l.source = None
        if self.selection is not None:
            self.selection = np.ascontiguousarray(fn(self.selection))
        self.height, self.width = self.layers[0].pixels.shape[:2]
        self.changed.emit("all")

    def crop(self, x, y, w, h):
        self._map_all(lambda p: p[y:y + h, x:x + w].copy(), "Crop")

    def rotate(self, clockwise):
        self._map_all(lambda p: np.rot90(p, -1 if clockwise else 1), "Rotate")

    def flip(self, horizontal):
        self._map_all(lambda p: p[:, ::-1] if horizontal else p[::-1], "Flip")

    def resize(self, w, h):
        self._map_all(lambda p: imageio.resize(p, w, h), "Resize image")

    # ------------------------------------------------------------------ selection
    def set_selection(self, mask, label):
        """Replace the selection (None or an empty mask deselects)."""
        if mask is not None and not (mask > 0).any():
            mask = None
        if mask is None and self.selection is None:
            return
        self.push_undo(label)
        self.selection = None if mask is None else np.ascontiguousarray(mask, np.uint8)
        self.changed.emit("selection")

    def layer_via_selection(self, cut):
        """Photoshop's Layer via Copy / Layer via Cut."""
        self.push_undo("Layer via Cut" if cut else "Layer via Copy")
        sel = self.selection.astype(np.uint16)
        src = self.layers[self.active]
        new = src.pixels.copy()
        new[..., 3] = (new[..., 3] * sel // 255).astype(np.uint8)
        if cut:
            rest = src.pixels.copy()
            rest[..., 3] = (rest[..., 3] * (255 - sel) // 255).astype(np.uint8)
            src.pixels = rest
        self.layers.insert(self.active + 1, Layer(self._unique_name("Layer"), new))
        self.active += 1
        self.changed.emit("structure")

    # ------------------------------------------------------------------ layer masks
    def add_mask(self, from_selection=False, label="Add layer mask"):
        """Give the active layer a mask. Without a selection it starts fully visible."""
        layer = self.active_layer()
        if layer is None or layer.mask is not None:
            return False
        self.push_undo(label)
        if from_selection and self.selection is not None:
            layer.mask = np.ascontiguousarray(self.selection, np.uint8)
        else:
            layer.mask = np.full((self.height, self.width), 255, np.uint8)
        self.changed.emit("structure")
        return True

    def set_mask(self, mask, label, coalesce=None):
        layer = self.active_layer()
        if layer is None:
            return
        self.push_undo(label, coalesce)
        layer.mask = None if mask is None else np.ascontiguousarray(mask, np.uint8)
        self.changed.emit("structure")

    def delete_mask(self):
        """Throw the mask away; the layer goes back to being fully visible."""
        layer = self.active_layer()
        if layer is None or layer.mask is None:
            return False
        self.set_mask(None, "Delete layer mask")
        return True

    def apply_mask(self):
        """Bake the mask into the layer's own transparency, then drop it."""
        layer = self.active_layer()
        if layer is None or layer.mask is None:
            return False
        self.push_undo("Apply layer mask")
        px = layer.pixels.copy()
        px[..., 3] = (px[..., 3].astype(np.uint16) * layer.mask // 255).astype(np.uint8)
        layer.pixels = px
        layer.mask = None
        self.changed.emit("pixels")
        return True

    def invert_mask(self):
        layer = self.active_layer()
        if layer is None or layer.mask is None:
            return False
        self.set_mask(255 - layer.mask, "Invert layer mask")
        return True

    def set_adjustments(self, settings, label, coalesce=None):
        self.push_undo(label, coalesce)
        self.adjust = dict(settings)
        self.changed.emit("adjust")
