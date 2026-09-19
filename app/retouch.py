"""Retouching: blemish removal, healing, skin smoothing and redness reduction.

All functions work on an RGB uint8 image and a selection mask (HxW uint8, 255 = selected)
and only process the selection's bounding box, so they stay fast on big photos.
"""
import cv2
import numpy as np

from . import selection


def _odd(n):
    n = max(3, int(n))
    return n if n % 2 else n + 1


# --------------------------------------------------------------------------- healing

def heal(rgb, mask):
    """Remove what's under `mask` by blending in texture from a nearby matching area
    (like Photoshop's healing brush). Falls back to smooth inpainting when needed."""
    out = rgb.copy()
    h, w = mask.shape
    binary = (mask > 64).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if area < 2:
            continue
        comp = (labels[y:y + bh, x:x + bw] == i).astype(np.uint8)
        pad = max(4, int(max(bw, bh) * 0.35))
        comp = cv2.dilate(comp, np.ones((3, 3), np.uint8))
        best = _best_source(out, binary, x, y, bw, bh, pad)
        region = np.zeros((h, w), np.uint8)
        region[y:y + bh, x:x + bw] = comp * 255
        done = False
        if best is not None:
            dx, dy = best
            # Source image shifted so the matching area lines up with the blemish.
            src = np.roll(np.roll(out, -dy, axis=0), -dx, axis=1)
            x0, y0 = max(0, x - pad), max(0, y - pad)
            x1, y1 = min(w, x + bw + pad), min(h, y + bh + pad)
            m = region[y0:y1, x0:x1]
            if 0 < x0 and 0 < y0 and x1 < w and y1 < h:
                try:
                    # (seamlessClone overwrites the mask it's given, so pass a copy)
                    patch = cv2.seamlessClone(np.ascontiguousarray(src[y0:y1, x0:x1]),
                                              np.ascontiguousarray(out[y0:y1, x0:x1]), m.copy(),
                                              ((x1 - x0) // 2, (y1 - y0) // 2), cv2.NORMAL_CLONE)
                    sel = m[..., None] > 0
                    # seamlessClone centres on the mask's bounding box, so place it by box
                    out[y0:y1, x0:x1] = np.where(sel, patch, out[y0:y1, x0:x1])
                    done = True
                except cv2.error:
                    done = False
        if not done:
            x0, y0 = max(0, x - pad * 2), max(0, y - pad * 2)
            x1, y1 = min(w, x + bw + pad * 2), min(h, y + bh + pad * 2)
            sub = np.ascontiguousarray(out[y0:y1, x0:x1])
            fixed = cv2.inpaint(sub, region[y0:y1, x0:x1], max(3, pad // 2), cv2.INPAINT_TELEA)
            out[y0:y1, x0:x1] = fixed
    # Soft edge: blend by the (possibly feathered) mask.
    m = (mask.astype(np.float32) / 255.0)[..., None]
    return np.clip(rgb * (1 - m) + out * m + 0.5, 0, 255).astype(np.uint8)


def _best_source(img, hole, x, y, bw, bh, pad):
    """Find an offset to a nearby clean area whose surroundings match the blemish's."""
    h, w = hole.shape
    x0, y0, x1, y1 = x - pad, y - pad, x + bw + pad, y + bh + pad
    if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
        return None
    ring = cv2.dilate(hole[y0:y1, x0:x1], np.ones((2 * pad + 1, 2 * pad + 1), np.uint8)) \
        - hole[y0:y1, x0:x1]
    ring = ring > 0
    target = img[y0:y1, x0:x1].astype(np.int16)
    best, best_score = None, None
    d = int(max(bw, bh) * 1.3) + pad
    for ang in range(0, 360, 30):
        for dist in (d, int(d * 1.6)):
            dx = int(round(np.cos(np.radians(ang)) * dist))
            dy = int(round(np.sin(np.radians(ang)) * dist))
            sx0, sy0, sx1, sy1 = x0 + dx, y0 + dy, x1 + dx, y1 + dy
            if sx0 < 1 or sy0 < 1 or sx1 > w - 1 or sy1 > h - 1:
                continue
            if hole[sy0:sy1, sx0:sx1].any():
                continue  # don't copy another blemish
            cand = img[sy0:sy1, sx0:sx1].astype(np.int16)
            score = np.abs(cand - target)[ring].mean()
            if best_score is None or score < best_score:
                best, best_score = (dx, dy), score
    return best


# --------------------------------------------------------------------------- blemishes

def find_blemishes(rgb, sel, spot_size, sensitivity):
    """Detect small dark/red spots (acne, spots, small scars) inside the selection.
    spot_size: the largest spot diameter in pixels. sensitivity: 0-100.
    Returns a uint8 mask of the spots."""
    box = selection.bbox(sel, int(spot_size * 2))
    if box is None:
        return np.zeros(sel.shape, np.uint8)
    x0, y0, x1, y1 = box
    crop = np.ascontiguousarray(rgb[y0:y1, x0:x1, :3])
    lab = cv2.cvtColor(crop, cv2.COLOR_RGB2LAB)
    L, A = lab[..., 0], lab[..., 1]
    k = _odd(spot_size * 3)
    # Local "clean skin" estimate: the median ignores spots smaller than about k/2.
    L_bg = cv2.medianBlur(L, min(k, 255))
    A_bg = cv2.medianBlur(A, min(k, 255))
    t = np.interp(sensitivity, [0, 100], [22, 5])       # darker than surroundings by t levels
    tr = np.interp(sensitivity, [0, 100], [14, 4])      # redder than surroundings
    dark = L_bg.astype(np.int16) - L.astype(np.int16) > t
    red = A.astype(np.int16) - A_bg.astype(np.int16) > tr
    cand = ((dark | red) & (sel[y0:y1, x0:x1] > 127)).astype(np.uint8)
    cand = cv2.morphologyEx(cand, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(cand, 8)
    # Keep spots between "bigger than a pore" and "smaller than an eye or nostril".
    area, size = stats[:, cv2.CC_STAT_AREA], stats[:, [cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT]].max(1)
    min_area = max(4.0, np.pi * (spot_size / 6) ** 2)
    max_area = np.pi * (spot_size / 2) ** 2 * 1.6
    good = (area >= min_area) & (area <= max_area) & (size <= spot_size * 1.5)
    # Blemishes are only mildly darker than the skin around them; pupils, nostrils and
    # eyebrow hairs are far darker, so leave very dark spots alone.
    darkness = (L_bg.astype(np.float32) - L.astype(np.float32)).ravel()
    counts = np.maximum(1, np.bincount(labels.ravel(), minlength=n))
    mean_dark = np.bincount(labels.ravel(), weights=darkness, minlength=n) / counts
    good &= mean_dark < 70
    good[0] = False  # background label
    keep = good[labels].astype(np.uint8)
    keep = cv2.dilate(keep, np.ones((5, 5), np.uint8))
    out = np.zeros(sel.shape, np.uint8)
    out[y0:y1, x0:x1] = keep * 255
    return out


def remove_blemishes(rgb, sel, spot_size, sensitivity):
    """Returns (new_rgb, number_of_spots_removed)."""
    spots = find_blemishes(rgb, sel, spot_size, sensitivity)
    n = cv2.connectedComponents((spots > 0).astype(np.uint8))[0] - 1
    if n <= 0:
        return rgb, 0
    box = selection.bbox(spots, int(spot_size))
    x0, y0, x1, y1 = box
    crop = np.ascontiguousarray(rgb[y0:y1, x0:x1, :3])
    fixed = cv2.inpaint(crop, spots[y0:y1, x0:x1], max(3, spot_size // 3), cv2.INPAINT_TELEA)
    # Add back a little fine grain so healed spots don't look plastic.
    grain = crop.astype(np.float32) - cv2.GaussianBlur(crop, (0, 0), 1.2).astype(np.float32)
    shift = np.roll(grain, (spot_size, spot_size), axis=(0, 1))
    fixed = np.clip(fixed + 0.6 * shift, 0, 255).astype(np.uint8)
    m = cv2.GaussianBlur(spots[y0:y1, x0:x1], (0, 0), 1.2).astype(np.float32)[..., None] / 255
    out = rgb.copy()
    out[y0:y1, x0:x1, :3] = np.clip(crop * (1 - m) + fixed * m + 0.5, 0, 255).astype(np.uint8)
    return out, n


# --------------------------------------------------------------------------- skin

def _guided(I, r, eps):
    """Edge-preserving smoothing (self-guided filter), fast for any radius."""
    k = (2 * r + 1, 2 * r + 1)
    mean = cv2.blur(I, k)
    var = cv2.blur(I * I, k) - mean * mean
    a = var / (var + eps)
    b = mean - a * mean
    return cv2.blur(a, k) * I + cv2.blur(b, k)


def smooth_skin(rgb, sel, amount, texture):
    """amount 0-100: how much to smooth. texture 0-100: how much fine pore detail to keep."""
    box = selection.bbox(sel, 8)
    if box is None or amount <= 0:
        return rgb
    x0, y0, x1, y1 = box
    crop = rgb[y0:y1, x0:x1, :3].astype(np.float32) / 255.0
    size = np.sqrt((sel > 127).sum())
    r = int(np.clip(size * (0.006 + 0.012 * amount / 100), 2, 40))
    eps = (0.01 + 0.05 * amount / 100) ** 2
    smooth = np.dstack([_guided(crop[..., c], r, eps) for c in range(3)])
    fine = crop - cv2.GaussianBlur(crop, (0, 0), 1.0)
    result = smooth + fine * (texture / 100.0)
    strength = min(1.0, amount / 70.0)
    m = (sel[y0:y1, x0:x1].astype(np.float32) / 255.0)[..., None] * strength
    out = rgb.copy()
    blended = crop * (1 - m) + result * m
    out[y0:y1, x0:x1, :3] = np.clip(blended * 255 + 0.5, 0, 255).astype(np.uint8)
    return out


def reduce_redness(rgb, sel, amount):
    """Calm red, blotchy areas (acne redness, irritation) toward the surrounding skin tone."""
    box = selection.bbox(sel, 2)
    if box is None or amount <= 0:
        return rgb
    x0, y0, x1, y1 = box
    crop = np.ascontiguousarray(rgb[y0:y1, x0:x1, :3])
    lab = cv2.cvtColor(crop, cv2.COLOR_RGB2LAB).astype(np.float32)
    a = lab[..., 1]
    m = sel[y0:y1, x0:x1] > 127
    target = np.median(a[m]) if m.any() else 128
    excess = np.clip(a - target, 0, None)
    lab[..., 1] = a - excess * (amount / 100.0)
    fixed = cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB)
    w = (sel[y0:y1, x0:x1].astype(np.float32) / 255.0)[..., None]
    out = rgb.copy()
    out[y0:y1, x0:x1, :3] = np.clip(crop * (1 - w) + fixed * w + 0.5, 0, 255).astype(np.uint8)
    return out
