"""Lightroom-style, non-destructive photo adjustments implemented with numpy.

All settings are integers (mostly -100..100) so they map directly onto sliders.
`apply()` takes an RGBA uint8 array and returns a new RGBA uint8 array.
"""
import numpy as np

# (section, key, label, min, max, tooltip)
SLIDERS = [
    ("Light", "exposure", "Exposure", -300, 300,
     "Makes the whole photo brighter or darker (like opening the camera's shutter longer)."),
    ("Light", "contrast", "Contrast", -100, 100,
     "Increases the difference between light and dark areas. Lower it for a softer, flatter look."),
    ("Light", "highlights", "Highlights", -100, 100,
     "Adjusts only the bright parts. Drag left to recover detail in a bright sky."),
    ("Light", "shadows", "Shadows", -100, 100,
     "Adjusts only the dark parts. Drag right to reveal detail hiding in the shadows."),
    ("Light", "whites", "Whites", -100, 100,
     "Sets how bright the brightest points are. Right = punchier, left = softer."),
    ("Light", "blacks", "Blacks", -100, 100,
     "Sets how dark the darkest points are. Left = deeper blacks, right = faded blacks."),
    ("Color", "temperature", "Temperature", -100, 100,
     "Left makes the photo cooler (bluer), right makes it warmer (more yellow/orange)."),
    ("Color", "tint", "Tint", -100, 100,
     "Left adds green, right adds magenta. Use it to fix odd color casts."),
    ("Color", "vibrance", "Vibrance", -100, 100,
     "Boosts dull colors while protecting already-strong colors and skin tones. Usually nicer than Saturation."),
    ("Color", "saturation", "Saturation", -100, 100,
     "Makes every color stronger. All the way left turns the photo black & white."),
    ("Effects", "clarity", "Clarity", -100, 100,
     "Adds punch to textures and edges in the midtones. Negative values give a soft, dreamy look."),
    ("Effects", "dehaze", "Dehaze", -100, 100,
     "Cuts through haze and fog. Negative values add atmosphere."),
    ("Effects", "fade", "Fade", 0, 100,
     "Lifts the darkest tones for a faded, matte film look."),
    ("Effects", "vignette", "Vignette", -100, 100,
     "Darkens (left) or lightens (right) the corners to draw the eye to the center."),
    ("Effects", "grain", "Grain", 0, 100,
     "Adds film-like grain texture."),
    ("Detail", "sharpness", "Sharpening", 0, 100,
     "Makes fine details crisper. A little goes a long way."),
]

# Color Mixer (HSL): eight hue bands, each with its own Hue / Saturation / Luminance.
# (key, label, center hue in degrees, swatch color shown in the panel)
MIXER_BANDS = [
    ("red", "Red", 0, "#e0463c"),
    ("orange", "Orange", 30, "#e2892c"),
    ("yellow", "Yellow", 60, "#dcc324"),
    ("green", "Green", 120, "#46a94f"),
    ("aqua", "Aqua", 180, "#2fb3bd"),
    ("blue", "Blue", 240, "#3d6fd6"),
    ("purple", "Purple", 280, "#8a4ed0"),
    ("magenta", "Magenta", 320, "#d2469c"),
]

# (key, label, tooltip; {c} is replaced with the color name, e.g. "red")
MIXER_CHANNELS = [
    ("hue", "Hue",
     "Nudges the {c} parts of the photo towards the neighbouring colors, without touching "
     "anything else. Great for turning a {c} that looks slightly off into exactly the shade you want."),
    ("sat", "Saturation",
     "Makes only the {c} parts stronger (right) or duller (left). All the way left turns just "
     "the {c} areas grey."),
    ("lum", "Luminance",
     "Makes only the {c} parts brighter (right) or darker (left). Try dragging left on Blue "
     "for a deeper sky."),
]

MIXER_RANGE = (-100, 100)


def mixer_key(band, channel):
    """The settings key for one Color Mixer slider, e.g. mixer_key("red", "hue")."""
    return f"mix_{band}_{channel}"


MIXER_DEFAULTS = {mixer_key(b[0], c[0]): 0 for b in MIXER_BANDS for c in MIXER_CHANNELS}

DEFAULTS = {key: 0 for _, key, *_ in SLIDERS}
DEFAULTS.update(MIXER_DEFAULTS)

PRESETS = {
    "Original": {},
    "Vivid": {"contrast": 20, "vibrance": 40, "saturation": 10, "clarity": 15},
    "Bright & Airy": {"exposure": 40, "shadows": 40, "highlights": -30, "contrast": -10,
                      "vibrance": 15, "temperature": -5},
    "Warm Glow": {"temperature": 30, "tint": 5, "exposure": 10, "highlights": -20, "vibrance": 15},
    "Cool Breeze": {"temperature": -30, "contrast": 10, "vibrance": 10},
    "Matte Film": {"fade": 50, "contrast": -15, "saturation": -15, "temperature": 10, "grain": 20},
    "Vintage": {"temperature": 25, "fade": 40, "saturation": -30, "vignette": -30, "grain": 30,
                "contrast": 10},
    "Dramatic": {"contrast": 40, "clarity": 50, "highlights": -40, "shadows": 20, "vignette": -40,
                 "saturation": -20},
    "Soft Portrait": {"clarity": -30, "highlights": -10, "shadows": 15, "vibrance": 10,
                      "temperature": 8},
    "B&W Classic": {"saturation": -100, "contrast": 20, "clarity": 10},
    "B&W Noir": {"saturation": -100, "contrast": 60, "blacks": -30, "vignette": -50, "grain": 25},
    "Clear Skies": {"highlights": -60, "dehaze": 30, "vibrance": 25, "temperature": -8},
    # --- looks built on the Color Mixer (HSL) ---
    "Teal & Orange": {"contrast": 15, "temperature": 10, "vibrance": 10,
                      "mix_red_hue": 8, "mix_red_sat": 12,
                      "mix_orange_sat": 30, "mix_orange_lum": 8,
                      "mix_yellow_hue": -35, "mix_yellow_sat": 15,
                      "mix_green_hue": 45, "mix_green_sat": -25,
                      "mix_aqua_sat": 30, "mix_aqua_lum": -10,
                      "mix_blue_hue": -45, "mix_blue_sat": 25, "mix_blue_lum": -15},
    "Golden Sunset": {"temperature": 20, "contrast": 12, "highlights": -15,
                      "mix_red_sat": 25, "mix_red_lum": 5,
                      "mix_orange_hue": -12, "mix_orange_sat": 35, "mix_orange_lum": 12,
                      "mix_yellow_hue": -25, "mix_yellow_sat": 25,
                      "mix_magenta_sat": 20,
                      "mix_blue_lum": -30, "mix_blue_sat": 15},
    "Lush Greens": {"vibrance": 15, "contrast": 8,
                    "mix_yellow_hue": 30, "mix_yellow_sat": 15, "mix_yellow_lum": -10,
                    "mix_green_hue": 15, "mix_green_sat": 35, "mix_green_lum": -18,
                    "mix_aqua_sat": 20},
    "Deep Blue Sky": {"dehaze": 20, "contrast": 10,
                      "mix_aqua_sat": 30, "mix_aqua_lum": -20,
                      "mix_blue_hue": -10, "mix_blue_sat": 35, "mix_blue_lum": -35,
                      "mix_purple_sat": 15},
}


def preset_settings(name):
    s = dict(DEFAULTS)
    s.update(PRESETS.get(name, {}))
    return s


def is_default(s):
    return all(s.get(k, 0) == 0 for k in DEFAULTS)


def mixer_is_default(s):
    return all(s.get(k, 0) == 0 for k in MIXER_DEFAULTS)


def setting_label(key):
    """Human-readable name for a settings key, used for undo steps."""
    if key in MIXER_DEFAULTS:
        _, band, channel = key.split("_")
        band_label = next(b[1] for b in MIXER_BANDS if b[0] == band)
        channel_label = next(c[1] for c in MIXER_CHANNELS if c[0] == channel)
        return f"{band_label} {channel_label}"
    return key.title()


# --------------------------------------------------------------------------- helpers

def _smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _lum(rgb):
    return rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722


def _box1d(a, r, axis):
    """Box blur of radius r along an axis using cumulative sums (cost independent of r)."""
    n = a.shape[axis]
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r + 1, r)
    c = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis, dtype=np.float32)
    hi = [slice(None)] * a.ndim
    lo = [slice(None)] * a.ndim
    hi[axis] = slice(2 * r + 1, 2 * r + 1 + n)
    lo[axis] = slice(0, n)
    return (c[tuple(hi)] - c[tuple(lo)]) * (1.0 / (2 * r + 1))


def blur(a, sigma):
    """Fast approximate gaussian blur (three box passes) over the first two axes."""
    r = max(1, int(round(sigma)))
    out = a.astype(np.float32, copy=False)
    for _ in range(3):
        out = _box1d(out, r, 0)
        out = _box1d(out, r, 1)
    return out


# --------------------------------------------------------------------- color mixer

_MIX_BINS = 256          # hue resolution of the lookup tables below
_MIX_HUE_DEGREES = 30.0  # how far a hue slider at 100 shifts a color, in degrees
_MIX_LUM_AMOUNT = 0.75   # how far a luminance slider at 100 pushes towards white/black


def _mixer_luts(s):
    """Three 256-entry lookup tables (hue shift, saturation, luminance), indexed by hue bin.

    Each band's value is spread over the hue circle by interpolating between the band
    centers, so a color sitting between two bands is affected by both (the weights always
    add up to 1). Returns None when every Color Mixer slider is still at zero.
    """
    if mixer_is_default(s):
        return None
    centers = np.array([b[2] for b in MIXER_BANDS], np.float32)
    x = (np.arange(_MIX_BINS, dtype=np.float32) + 0.5) * (360.0 / _MIX_BINS)
    luts = []
    for channel, _label, _tip in MIXER_CHANNELS:
        vals = np.array([s.get(mixer_key(b[0], channel), 0) / 100.0 for b in MIXER_BANDS],
                        np.float32)
        luts.append(np.interp(x, centers, vals, period=360).astype(np.float32))
    return luts


def _color_mixer(rgb, luts):
    """Per-color Hue/Saturation/Luminance, done in HSL space. rgb is float32 0..1."""
    hue_lut, sat_lut, lum_lut = luts
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx, mn = rgb.max(axis=2), rgb.min(axis=2)
    chroma = mx - mn
    L = (mx + mn) * 0.5
    safe = np.maximum(chroma, 1e-6)
    hue = np.where(mx == r, ((g - b) / safe) % 6.0,
                   np.where(mx == g, (b - r) / safe + 2.0, (r - g) / safe + 4.0)) * 60.0
    hue = np.where(chroma > 1e-6, hue, 0.0).astype(np.float32)
    # Near-grey pixels have a meaningless hue, so fade the effect out for them.
    weight = _smoothstep(0.02, 0.12, chroma).astype(np.float32)
    idx = np.clip((hue * (_MIX_BINS / 360.0)).astype(np.int32), 0, _MIX_BINS - 1)

    S = np.divide(chroma, np.maximum(1.0 - np.abs(2.0 * L - 1.0), 1e-6),
                  out=np.zeros_like(chroma), where=chroma > 1e-6)
    np.clip(S, 0.0, 1.0, out=S)

    hue = (hue + hue_lut[idx] * (_MIX_HUE_DEGREES * weight)) % 360.0
    sat = sat_lut[idx] * weight
    S = np.where(sat >= 0, S + sat * (1.0 - S), S * (1.0 + sat))
    lum = lum_lut[idx] * weight * _MIX_LUM_AMOUNT
    L = np.clip(np.where(lum >= 0, L + lum * (1.0 - L), L * (1.0 + lum)), 0.0, 1.0)

    # HSL -> RGB (the compact f(n) form: no per-sector branching).
    a = S * np.minimum(L, 1.0 - L)
    hp = hue * (1 / 30.0)
    out = np.empty_like(rgb)
    for ch, n in ((0, 0.0), (1, 8.0), (2, 4.0)):
        k = (n + hp) % 12.0
        out[..., ch] = L - a * np.clip(np.minimum(k - 3.0, 9.0 - k), -1.0, 1.0)
    return out


# --------------------------------------------------------------------------- pipeline

def apply(rgba, s, detail_scale=1.0):
    """Apply develop settings `s` to an RGBA uint8 image.

    detail_scale is (current resolution / full resolution); it keeps pixel-sized
    effects like sharpening roughly consistent between preview and export.
    """
    if is_default(s):
        return rgba
    g = lambda k: s.get(k, 0) / 100.0
    h, w = rgba.shape[:2]

    # White balance + exposure (in approximately linear light), then whites/blacks
    # (a levels adjustment). All per-channel, so they fold into one lookup table each.
    ev, temp, tint = s.get("exposure", 0) / 100.0, g("temperature"), g("tint")
    gains = np.array([1 + 0.25 * temp + 0.05 * tint,
                      1 - 0.2 * tint,
                      1 - 0.25 * temp + 0.05 * tint]) * (2.0 ** ev)
    bp, wp = -0.12 * g("blacks"), 1.0 - 0.2 * g("whites")
    lin = (np.arange(256) / 255.0) ** 2.2
    rgb = np.empty((h, w, 3), np.float32)
    for ch in range(3):
        lut = ((lin * gains[ch]) ** (1 / 2.2) - bp) / (wp - bp)
        rgb[..., ch] = lut.astype(np.float32)[rgba[..., ch]]

    # Highlights / shadows: luminance-masked brightening or darkening.
    hl, sh = g("highlights"), g("shadows")
    if hl or sh:
        L = _lum(rgb)
        delta = hl * 0.3 * _smoothstep(0.45, 1.0, L) + sh * 0.3 * (1.0 - _smoothstep(0.0, 0.55, L))
        rgb += delta[..., None]

    np.clip(rgb, 0.0, 1.0, out=rgb)

    # Contrast: an S-curve that keeps pure black, mid grey and pure white fixed.
    c = g("contrast")
    if c:
        rgb = rgb - (0.8 * c) * np.sin(2 * np.pi * rgb) / (2 * np.pi)

    # Clarity: midtone local contrast.
    cl = g("clarity")
    if cl:
        L = _lum(rgb)
        detail = L - blur(L, max(h, w) * 0.012)
        mid = 1.0 - (2.0 * L - 1.0) ** 2
        rgb += (cl * 0.9 * detail * mid)[..., None]

    # Dehaze.
    dz = g("dehaze")
    if dz > 0:
        k = 0.12 * dz
        rgb = (rgb - k) * (1.0 / (1.0 - k))
        L = _lum(rgb)[..., None]
        rgb = L + (rgb - L) * (1 + 0.25 * dz)
    elif dz < 0:
        k = -0.35 * dz
        rgb = rgb * (1 - k) + 0.75 * k

    # Vibrance (protects already saturated colors) and saturation.
    vb, sat = g("vibrance"), g("saturation")
    if vb or sat:
        L = _lum(rgb)[..., None]
        factor = 1.0 + sat
        if vb:
            r, gg, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
            dull = 1.0 - (np.maximum(np.maximum(r, gg), b) - np.minimum(np.minimum(r, gg), b))
            factor = factor * np.maximum(0.0, 1.0 + vb * dull * dull)[..., None]
        rgb = L + (rgb - L) * factor

    np.clip(rgb, 0.0, 1.0, out=rgb)

    # Color Mixer: hue / saturation / luminance for eight color bands.
    luts = _mixer_luts(s)
    if luts is not None:
        rgb = _color_mixer(rgb, luts)

    fd = g("fade")
    if fd:
        inv = 1.0 - rgb
        rgb = rgb + (fd * 0.25) * inv * inv * inv

    vg = g("vignette")
    if vg:
        yy = (np.arange(h, dtype=np.float32) - h / 2) / (h / 2)
        xx = (np.arange(w, dtype=np.float32) - w / 2) / (w / 2)
        d = np.sqrt(yy[:, None] ** 2 + xx[None, :] ** 2) / np.sqrt(2)
        mask = (_smoothstep(0.3, 1.0, d) * abs(vg) * 0.85)[..., None]
        rgb = rgb * (1 - mask) if vg < 0 else rgb + (1 - rgb) * mask

    shp = g("sharpness")
    if shp:  # sharpen luminance only: faster and avoids color fringes
        L = _lum(rgb)
        rgb += ((shp * 1.5) * (L - blur(L, max(1.0, 1.2 * detail_scale))))[..., None]

    gr = g("grain")
    if gr:
        rng = np.random.default_rng(1234)
        noise = rng.standard_normal((h, w), dtype=np.float32) * (0.07 * gr)
        rgb += noise[..., None]

    out = np.empty_like(rgba)
    out[..., :3] = np.clip(rgb * 255.0 + 0.5, 0, 255).astype(np.uint8)
    out[..., 3] = rgba[..., 3]
    return out


def auto_settings(rgba):
    """Pick sensible exposure / tone / white-balance values from the image statistics."""
    rgb = rgba[::2, ::2, :3].astype(np.float32) / 255.0
    L = _lum(rgb)
    p1, med, p99 = np.percentile(L, [1, 50, 99])
    s = {}
    med = max(med, 0.02)
    s["exposure"] = int(np.clip(2.2 * np.log2(0.46 / med) * 0.6, -1.5, 1.5) * 100)
    s["whites"] = int(np.clip((0.97 - p99) * 250, 0, 50)) if p99 < 0.97 else 0
    s["blacks"] = -int(np.clip((p1 - 0.02) * 250, 0, 40)) if p1 > 0.02 else 0
    s["highlights"] = -25 if p99 > 0.98 else 0
    s["shadows"] = 20 if med < 0.35 else 5
    s["contrast"] = 10
    s["vibrance"] = 20
    # Grey-world white balance, computed on midtones in linear light.
    m = (L > 0.15) & (L < 0.85)
    if m.sum() > 100:
        lin = rgb[m] ** 2.2
        r, gch, b = lin.mean(axis=0)
        t = (b - r) / (0.25 * (r + b) + 1e-6)
        s["temperature"] = int(np.clip(t * 0.5 * 100, -40, 40))
        avg_rb = (r + b) / 2
        tn = (gch - avg_rb) / (0.2 * gch + 0.05 * avg_rb + 1e-6)
        s["tint"] = int(np.clip(tn * 0.5 * 100, -30, 30))
    return s
