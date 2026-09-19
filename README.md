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

## Account sign-in

PhotoForge has a **Log in** button in the top toolbar. It signs you in through a
web page (so credentials never live in the desktop app) using the standard
native-app loopback flow:

1. The app opens the sign-in page in your default browser (e.g. Safari).
2. You sign in there (email + password, backed by Supabase).
3. The browser hands the session back to the app on a local `127.0.0.1`
   callback, and the button switches to show your email.

The sign-in web app lives in **[`web/`](web/)** (Next.js) and is deployed
separately on Vercel. Point the desktop app at your deployment with the
`BIGBIRD_WEB_URL` environment variable; it defaults to `http://localhost:3000`
for local development.

**Deployment (Vercel):** the website is the `web/` app, not `main.py`. In the
Vercel project set **Root Directory = `web`** and **Framework Preset = Next.js**.
The Supabase environment variables (`NEXT_PUBLIC_SUPABASE_URL`,
`NEXT_PUBLIC_SUPABASE_ANON_KEY`) are provided by the Supabase integration.

The same Vercel deployment also hosts the **cloud AI proxy** at `/api/edit`
(`web/app/api/edit/route.ts`), which holds the NVIDIA key so it never ships
inside the desktop app. Set these in the Vercel project:

| Variable | Notes |
|---|---|
| `NVIDIA_API_KEY` | **Never** prefix with `NEXT_PUBLIC_` -- that would inline it into the browser bundle and publish it. |
| `NIM_ENDPOINT` | Full NVIDIA NIM invoke URL; confirm the current path on build.nvidia.com. |

Point the desktop app at it with `PHOTOFORGE_CLOUD_URL`
(default `http://localhost:3000/api/edit` for development).

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
- **Select Object(s) to Remove** (SAM 2.1 Tiny): click objects and the AI finds their
  outlines (click again to deselect, Shift+click to add an area, right-click to exclude one,
  **Smaller Part** to pick part of an object). **Remove Selected** makes them transparent on
  a new layer so the layer below shows through, then opens **Refine Removal** so you can
  adjust the outline with dots. Filling the gap is planned as a cloud feature.
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
