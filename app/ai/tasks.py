"""The actual AI operations. Pure numpy in and out, so they can run on any thread."""
import cv2
import numpy as np

from . import models

_MEAN = np.array([0.485, 0.456, 0.406], np.float32)
_STD = np.array([0.229, 0.224, 0.225], np.float32)


def remove_background(rgba):
    """Return an HxW uint8 mask: 255 = subject (keep), 0 = background."""
    h, w = rgba.shape[:2]
    x = cv2.resize(rgba[..., :3], (1024, 1024), interpolation=cv2.INTER_AREA).astype(np.float32)
    x = ((x / 255.0 - _MEAN) / _STD).transpose(2, 0, 1)[None]
    logits = models.run("birefnet_lite", {"input_image": np.ascontiguousarray(x, np.float32)})[0]
    prob = 1.0 / (1.0 + np.exp(-logits[0, 0]))
    prob = cv2.resize(prob, (w, h), interpolation=cv2.INTER_LINEAR)
    return np.clip(prob * 255 + 0.5, 0, 255).astype(np.uint8)


def crisp_edges(mask):
    """Turn the AI's soft, uncertain edges solid (for hands, products, objects).
    Pixels the AI is at least ~60% sure about become fully kept; below ~20% are removed."""
    a = mask.astype(np.float32) / 255.0
    t = np.clip((a - 0.2) / 0.4, 0.0, 1.0)
    return (t * t * (3 - 2 * t) * 255 + 0.5).astype(np.uint8)


def grow_mask(mask, pixels):
    """Expand a mask outward; inpainting works much better with a little margin."""
    k = max(1, int(round(pixels))) * 2 + 1
    return cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))


def _inpaint_lama(rgb, hole):
    """LaMa works at a fixed 512x512, so inpaint a square crop around the hole."""
    H, W = hole.shape
    ys, xs = np.nonzero(hole)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    # Square crop with generous context around the hole (at least 512 px when possible).
    side = int(max(y1 - y0, x1 - x0) * 1.8) + 32
    side = min(max(side, 512), max(H, W))
    cy, cx = (y0 + y1) // 2, (x0 + x1) // 2
    top = int(np.clip(cy - side // 2, 0, max(0, H - side)))
    left = int(np.clip(cx - side // 2, 0, max(0, W - side)))
    bottom, right = min(H, top + side), min(W, left + side)
    crop = rgb[top:bottom, left:right]
    cmask = hole[top:bottom, left:right]
    ch, cw = crop.shape[:2]

    img = cv2.resize(crop, (512, 512), interpolation=cv2.INTER_AREA if ch > 512 else cv2.INTER_CUBIC)
    m = (cv2.resize(cmask, (512, 512), interpolation=cv2.INTER_NEAREST) > 127).astype(np.float32)
    img = img.astype(np.float32).transpose(2, 0, 1)[None] / 255.0
    m = m[None, None]
    out = models.run("lama", {"image": np.ascontiguousarray(img * (1 - m), np.float32),
                              "mask": np.ascontiguousarray(m)})[0]
    out = np.clip(out[0].transpose(1, 2, 0), 0, 255).astype(np.uint8)
    out = cv2.resize(out, (cw, ch), interpolation=cv2.INTER_CUBIC)
    result = rgb.copy()
    result[top:bottom, left:right] = out
    return result


def _inpaint_migan(rgb, hole):
    known = np.where(hole > 127, 0, 255).astype(np.uint8)
    out = models.run("migan", {"image": np.ascontiguousarray(rgb.transpose(2, 0, 1)[None]),
                               "mask": np.ascontiguousarray(known[None, None])})[0]
    return out[0].transpose(1, 2, 0)


def remove_object(rgba, mask, quality="best"):
    """Fill the area where mask > 0. Returns an RGBA layer containing only the patch."""
    h, w = mask.shape
    grow = max(4.0, 0.004 * np.hypot(h, w))
    hole = grow_mask((mask > 127).astype(np.uint8) * 255, grow)
    if not hole.any():
        raise ValueError("Nothing is outlined.")
    rgb = np.ascontiguousarray(rgba[..., :3])
    filled = _inpaint_migan(rgb, hole) if quality == "fast" else _inpaint_lama(rgb, hole)
    # Soft-edged alpha so the patch blends into the photo.
    alpha = cv2.GaussianBlur(grow_mask(hole, grow * 0.5), (0, 0), max(1.0, grow * 0.5))
    out = np.zeros((h, w, 4), np.uint8)
    out[..., :3] = filled
    out[..., 3] = alpha
    return out
