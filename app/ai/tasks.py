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
