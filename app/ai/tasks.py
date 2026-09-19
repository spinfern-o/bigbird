"""The actual AI operations. Pure numpy in and out, so they can run on any thread."""
import cv2
import numpy as np

from . import models

_MEAN = np.array([0.485, 0.456, 0.406], np.float32)
_STD = np.array([0.229, 0.224, 0.225], np.float32)


def _normalize(rgb, size):
    x = cv2.resize(rgb, (size, size), interpolation=cv2.INTER_AREA).astype(np.float32)
    x = ((x / 255.0 - _MEAN) / _STD).transpose(2, 0, 1)[None]
    return np.ascontiguousarray(x, np.float32)


# --------------------------------------------------------------------------- background

def remove_background(rgba):
    """Return an HxW uint8 mask: 255 = subject (keep), 0 = background."""
    h, w = rgba.shape[:2]
    logits = models.run("birefnet_lite", {"input_image": _normalize(rgba[..., :3], 1024)})[0]
    prob = 1.0 / (1.0 + np.exp(-logits[0, 0]))
    prob = cv2.resize(prob, (w, h), interpolation=cv2.INTER_LINEAR)
    return np.clip(prob * 255 + 0.5, 0, 255).astype(np.uint8)


def crisp_edges(mask):
    """Turn the AI's soft, uncertain edges solid (for hands, products, objects).
    Pixels the AI is at least ~60% sure about become fully kept; below ~20% are removed."""
    a = mask.astype(np.float32) / 255.0
    t = np.clip((a - 0.2) / 0.4, 0.0, 1.0)
    return (t * t * (3 - 2 * t) * 255 + 0.5).astype(np.uint8)


# --------------------------------------------------------------------------- object selection (SAM 2.1)

class SamImage:
    """The photo analysed once by SAM's image encoder; clicks are then decoded instantly."""

    def __init__(self, rgba):
        self.h, self.w = rgba.shape[:2]
        # SAM 2.1 takes the whole photo squeezed to 1024x1024.
        x = cv2.resize(rgba[..., :3], (1024, 1024), interpolation=cv2.INTER_LINEAR)
        x = ((x.astype(np.float32) / 255.0 - _MEAN) / _STD).transpose(2, 0, 1)[None]
        e0, e1, e2 = models.run("sam2", {"pixel_values": np.ascontiguousarray(x, np.float32)},
                                part="vision_encoder")
        self.emb = {"image_embeddings.0": e0, "image_embeddings.1": e1, "image_embeddings.2": e2}

    def decode(self, points, labels):
        """points: [(x, y)] in photo pixels; labels: 1 = include, 0 = exclude.
        Returns (scores[3], low-res logits[3, 256, 256]) for three candidate masks."""
        p = np.array(points, np.float32) * [1024.0 / self.w, 1024.0 / self.h]
        feeds = {"input_points": p[None, None].astype(np.float32),
                 "input_labels": np.array(labels, np.int64)[None, None],
                 "input_boxes": np.zeros((1, 0, 4), np.float32), **self.emb}
        # The small decoder is faster on the CPU than the round trip to the GPU.
        iou, masks, _ = models.run("sam2", feeds, part="mask_decoder", gpu=False)
        return iou[0, 0], masks[0, 0]


def logits_to_mask(logits, w, h):
    """Upscale SAM's 256x256 logits to w x h and return a soft-edged uint8 mask."""
    up = cv2.resize(logits.astype(np.float32), (w, h), interpolation=cv2.INTER_LINEAR)
    return (255.0 / (1.0 + np.exp(-np.clip(up * 2.0, -30, 30))) + 0.5).astype(np.uint8)


# --------------------------------------------------------------------------- fill (LaMa)

def fill_box(mask):
    """A square crop around the area to fill, with context, as (x0, y0, x1, y1)."""
    H, W = mask.shape
    ys, xs = np.nonzero(mask > 127)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    side = int(max(y1 - y0, x1 - x0) * 1.8) + 32
    side = min(max(side, 512), max(H, W))
    cy, cx = (y0 + y1) // 2, (x0 + x1) // 2
    top = int(np.clip(cy - side // 2, 0, max(0, H - side)))
    left = int(np.clip(cx - side // 2, 0, max(0, W - side)))
    return left, top, min(W, left + side), min(H, top + side)


def lama_fill(rgb, mask):
    """Fill mask>127 in an RGB crop with LaMa (fixed 512x512); returns an RGB crop."""
    h, w = mask.shape
    img = cv2.resize(rgb, (512, 512), interpolation=cv2.INTER_AREA if h > 512 else cv2.INTER_CUBIC)
    m = (cv2.resize(mask, (512, 512), interpolation=cv2.INTER_NEAREST) > 127).astype(np.float32)
    img = img.astype(np.float32).transpose(2, 0, 1)[None] / 255.0
    m = m[None, None]
    out = models.run("lama", {"image": np.ascontiguousarray(img * (1 - m), np.float32),
                              "mask": np.ascontiguousarray(m)})[0]
    out = np.clip(out[0].transpose(1, 2, 0), 0, 255).astype(np.uint8)
    return cv2.resize(out, (w, h), interpolation=cv2.INTER_CUBIC)
