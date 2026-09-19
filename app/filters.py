"""Photoshop-style destructive filters applied to a single layer (RGBA uint8 in/out)."""
import numpy as np
from PIL import Image, ImageFilter


def _keep_alpha(src, rgb):
    out = src.copy()
    out[..., :3] = rgb
    return out


def gaussian_blur(px, radius):
    im = Image.fromarray(px).filter(ImageFilter.GaussianBlur(radius))
    return np.array(im)


def sharpen(px, amount=120):
    rgb = Image.fromarray(px[..., :3].copy())
    rgb = rgb.filter(ImageFilter.UnsharpMask(radius=2, percent=amount, threshold=2))
    return _keep_alpha(px, np.array(rgb))


def black_and_white(px):
    f = px[..., :3].astype(np.float32)
    L = f[..., 0] * 0.2126 + f[..., 1] * 0.7152 + f[..., 2] * 0.0722
    return _keep_alpha(px, np.clip(L + 0.5, 0, 255).astype(np.uint8)[..., None])


def sepia(px):
    f = px[..., :3].astype(np.float32)
    m = np.array([[0.393, 0.769, 0.189],
                  [0.349, 0.686, 0.168],
                  [0.272, 0.534, 0.131]], np.float32)
    return _keep_alpha(px, np.clip(f @ m.T, 0, 255).astype(np.uint8))


def invert(px):
    return _keep_alpha(px, 255 - px[..., :3])


def pixelate(px, block):
    h, w = px.shape[:2]
    small = Image.fromarray(px).resize((max(1, w // block), max(1, h // block)),
                                       Image.Resampling.BOX)
    return np.array(small.resize((w, h), Image.Resampling.NEAREST))


def add_noise(px, amount):
    rng = np.random.default_rng()
    noise = rng.normal(0, amount * 2.55, px.shape[:2])[..., None]
    return _keep_alpha(px, np.clip(px[..., :3] + noise, 0, 255).astype(np.uint8))
