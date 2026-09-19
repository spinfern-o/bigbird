"""Loading/saving images and converting between numpy arrays and QImage."""
import io
import json
import os
import zipfile

import numpy as np
from PIL import Image, ImageOps
from PySide6.QtGui import QImage

try:
    import rawpy
except ImportError:  # RAW support is optional
    rawpy = None

RAW_EXTS = {".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".rw2", ".raf", ".pef", ".srw"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
PROJECT_EXT = ".pforge"

OPEN_FILTER = ("All supported (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff *.gif *{} {});;"
               "Photos (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff *.gif);;"
               "Camera RAW ({});;PhotoForge project (*{})").format(
    PROJECT_EXT, " ".join("*" + e for e in sorted(RAW_EXTS)),
    " ".join("*" + e for e in sorted(RAW_EXTS)), PROJECT_EXT)


def load_image(path):
    """Return an HxWx4 uint8 RGBA array."""
    ext = os.path.splitext(path)[1].lower()
    if ext in RAW_EXTS:
        if rawpy is None:
            raise RuntimeError("Camera RAW support requires the 'rawpy' package.")
        with rawpy.imread(path) as raw:
            rgb = raw.postprocess(use_camera_wb=True, output_bps=8)
        alpha = np.full(rgb.shape[:2] + (1,), 255, np.uint8)
        return np.ascontiguousarray(np.concatenate([rgb, alpha], axis=2))
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        return np.array(im.convert("RGBA"))


def save_image(rgba, path, quality=92):
    ext = os.path.splitext(path)[1].lower()
    im = Image.fromarray(rgba)
    if ext in (".jpg", ".jpeg", ".bmp"):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.getchannel("A"))
        if ext == ".bmp":
            bg.save(path)
        else:
            bg.save(path, quality=quality, optimize=True, subsampling=0 if quality >= 90 else 2)
    elif ext == ".webp":
        im.save(path, quality=quality)
    elif ext in (".tif", ".tiff"):
        im.save(path, compression="tiff_lzw")
    else:
        im.save(path)


def to_qimage(arr):
    arr = np.ascontiguousarray(arr)
    h, w = arr.shape[:2]
    return QImage(arr.data, w, h, w * 4, QImage.Format_RGBA8888).copy()


def from_qimage(img):
    img = img.convertToFormat(QImage.Format_RGBA8888)
    w, h = img.width(), img.height()
    buf = np.frombuffer(img.constBits(), np.uint8, count=img.sizeInBytes())
    return buf.reshape(h, img.bytesPerLine())[:, :w * 4].reshape(h, w, 4).copy()


def thumbnail(arr, size):
    im = Image.fromarray(arr)
    im.thumbnail((size, size), Image.Resampling.BILINEAR, reducing_gap=2.0)
    return np.array(im)


def resize(arr, w, h, fast=False):
    im = Image.fromarray(arr)
    method = Image.Resampling.BILINEAR if fast else Image.Resampling.LANCZOS
    return np.array(im.resize((w, h), method, reducing_gap=2.0 if fast else None))


# --------------------------------------------------------------------------- projects

def save_project(doc, path):
    """`path` may be a filename or a file-like object (used for cloud saves)."""
    meta = {"version": 1, "width": doc.width, "height": doc.height, "active": doc.active,
            "adjust": doc.adjust, "layers": []}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:
        for i, layer in enumerate(doc.layers):
            name = f"layer{i}.png"
            buf = io.BytesIO()
            Image.fromarray(layer.pixels).save(buf, "PNG", compress_level=1)
            z.writestr(name, buf.getvalue())
            meta["layers"].append({"name": layer.name, "visible": layer.visible,
                                   "opacity": layer.opacity, "blend": layer.blend, "file": name})
        z.writestr("project.json", json.dumps(meta, indent=1))


def load_project(path):
    """`path` may be a filename or a file-like object (used for cloud opens)."""
    from .document import Document, Layer
    with zipfile.ZipFile(path) as z:
        meta = json.loads(z.read("project.json"))
        layers = []
        for info in meta["layers"]:
            with Image.open(io.BytesIO(z.read(info["file"]))) as im:
                px = np.array(im.convert("RGBA"))
            layers.append(Layer(info["name"], px, info["visible"], info["opacity"], info["blend"]))
    doc = Document(meta["width"], meta["height"], layers)
    doc.active = min(meta.get("active", 0), len(layers) - 1)
    doc.adjust.update(meta.get("adjust", {}))
    return doc
