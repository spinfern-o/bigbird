# PhotoForge

A beginner-friendly Windows photo editor combining Lightroom-style photo
adjustments with Photoshop-style layers and tools.

## Run it

Double-click **`PhotoForge.bat`**. The first launch creates a virtual environment and
installs dependencies automatically. You can also drag a photo onto the `.bat` file.

Or from a terminal:

```bash
.venv\Scripts\python main.py
```

## Roadmap

Planned work is split into two parallel tracks, **Track A: Selections & AI** and
**Track B: Pro Editing & Lightroom Features**, with file-ownership rules so both
can be built at the same time. See **[ROADMAP.txt](ROADMAP.txt)**.

## Features

**Develop (Lightroom-like, non-destructive)**
- ✨ Auto Enhance: exposure, tone and white balance from image statistics
- 12 one-click presets with live thumbnails of *your* photo
- Light: Exposure, Contrast, Highlights, Shadows, Whites, Blacks
- Color: Temperature, Tint, Vibrance, Saturation
- Effects: Clarity, Dehaze, Fade, Vignette, Grain · Detail: Sharpening
- Live histogram, Before/After compare (`\`)
- Opens JPG, PNG, WebP, TIFF, BMP, GIF and camera RAW (CR2/CR3/NEF/ARW/DNG/…)

**Editing (Photoshop-like)**
- Layers with opacity, 7 blend modes, show/hide, rename, reorder, merge, flatten
- Tools: Pan, Move, Brush, Eraser, Crop (with aspect-ratio presets + rule of thirds),
  Color Picker, Text
- Filters: Blur, Sharpen, Black & White, Sepia, Invert, Pixelate, Noise
- Rotate, flip, resize; add a second photo as a layer (or drag & drop it)
- Undo/redo for everything (40 steps)
- Save projects (`.pforge`, keeps layers + edits) and export JPG/PNG/WebP/TIFF

**AI tools (run locally, free and private)** in the **AI** tab and menu
- **Remove Background** (BiRefNet-lite): cuts out the subject onto a new layer
- **Refine Outline**: the cut-out edge becomes draggable dots joined by lines. Click a
  line to add a dot, right-click to delete, **More Points** for finer control. Edges you
  don't touch keep the AI's fine detail (e.g. hair).
- **Remove Object** (LaMa, or MI-GAN for slower PCs): click dots around anything, press
  Enter, and the gap is filled with matching background on a new layer
- Models download once on first use to `%LOCALAPPDATA%\PhotoForge\models`, use the GPU via
  DirectML when available, and fall back to the CPU. All are commercially licensed
  (Help → Open-source Licenses).

**Beginner help**: welcome screen, plain-English tooltips on every control,
status-bar hints for each tool, Quick Start guide (F1), double-click a slider's name to reset.

## Code layout

| File | Purpose |
|---|---|
| `app/adjustments.py` | numpy develop pipeline, presets, auto-enhance |
| `app/document.py` | layers, blend-mode compositing, undo history |
| `app/renderer.py` | fast preview while dragging + background full-res render |
| `app/canvas.py` | zoom/pan view and interactive tools |
| `app/panels.py` | Adjust panel (histogram, presets, sliders) and Layers panel |
| `app/main_window.py` | menus, toolbars, file handling |
| `app/ai/` | AI model registry/downloader, background & object removal, outline editor, AI tab |
| `app/filters.py`, `app/imageio.py`, `app/dialogs.py`, `app/theme.py`, `app/icons.py` | supporting pieces |
