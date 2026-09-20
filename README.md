# Phrame

> **Professional control. Instant AI editing. One creative workspace.**

Phrame ends the choice between clunky professional software and limited AI tools.
It combines Lightroom-style nondestructive adjustments, Photoshop-style layers
and selections, and local or NVIDIA-powered AI in one desktop editor.

Unlike prompt-only editors, Phrame keeps creators in control. Users can make
precise manual changes, use AI for difficult or repetitive work, refine the
result directly on the canvas, and continue editing without flattening the
project.

## Why Phrame is different

- **A complete editor, not an AI wrapper:** Layers, selections, retouching,
  filters, undo history, and professional adjustments work alongside AI.
- **Local when possible, cloud when useful:** Lightweight models run privately
  on the device, while generative operations can use NVIDIA-backed infrastructure.
- **AI results stay editable:** Selections, outlines, masks, and layers let users
  correct or refine what AI produces.
- **Built for accessibility:** Familiar creative-software patterns,
  plain-language guidance, and one-click tools reduce the learning curve without
  removing advanced control.

## Run it

Launch Phrame by double-clicking **`PhotoForge.bat`**. The first launch creates a virtual environment and
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

Phrame now shows the **account screen first** every time the desktop app
starts. Login happens in the user's default web browser (Safari, Chrome, Edge,
etc.), so credentials never live in the desktop app:

1. Launch Phrame and click **Log in**.
2. The app opens `https://www.phrame.tech/desktop-login` in the default browser.
3. Sign in there. If you need an account, use **Create one** on that page.
4. After creating an account, close the browser tab, return to Phrame, and
   click **Log in** again.
5. A successful login returns the session to the app through a local
   `127.0.0.1` callback and opens the editor.

The sign-in web app lives in **[`web/`](web/)** (Next.js) and is deployed
separately on Vercel. Production defaults to `https://www.phrame.tech`.
Set `BIGBIRD_WEB_URL=http://localhost:3000` only when testing the web app
locally.

**Deployment (Vercel):** the website is the `web/` app, not `main.py`. In the
Vercel project set **Root Directory = `web`** and **Framework Preset = Next.js**.
The Supabase environment variables (`NEXT_PUBLIC_SUPABASE_URL`,
`NEXT_PUBLIC_SUPABASE_ANON_KEY`) are provided by the Supabase integration.
This project intentionally does not use signup email verification. In Supabase
Auth settings, **Confirm email must be disabled**; otherwise Supabase itself
will still send confirmation mail even though the Phrame signup page no
longer asks the user to verify.

The same Vercel deployment also hosts the **cloud AI proxy** at `/api/edit`
(`web/app/api/edit/route.ts`), which holds the NVIDIA key so it never ships
inside the desktop app. Set these in the Vercel project:

| Variable | Notes |
|---|---|
| `NVIDIA_QWEN_IMAGE_EDIT_KEY` | The NVIDIA key. **Never** prefix with `NEXT_PUBLIC_` -- that would inline it into the browser bundle and publish it. `NVIDIA_API_KEY` is accepted as a fallback. |
| `NIM_ENDPOINT` | Full NVIDIA NIM invoke URL; confirm the current path on build.nvidia.com. |

The desktop app defaults to `https://www.phrame.tech/api/edit`. Override it with
`PHOTOFORGE_CLOUD_URL=http://localhost:3000/api/edit` for local development.

## Cloud projects

Signed-in users can use **File → Save to Cloud…** and **File → Open from Cloud…**.
Projects stay private in the Supabase `projects` Storage bucket and metadata table.

The required table, private bucket, grants, and row-level-security policies live in
`supabase/migrations/20260919223500_cloud_projects.sql`. Apply that migration to the
same Supabase project used by the login site before enabling cloud saves. The policies
restrict both metadata rows and Storage paths to the authenticated user's UUID.

The desktop client ships only the public Supabase anon/publishable key. It never ships a
service-role key. For staging, `PHOTOFORGE_SUPABASE_URL` and
`PHOTOFORGE_SUPABASE_ANON_KEY` can override the production client configuration.

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

**Selections & retouching (like Photoshop)**
- **Marquee (M)** rectangle/ellipse, **Lasso (L)** Freehand / Magnetic (snaps to edges) /
  Polygonal, **Magic Wand (W)** with Tolerance, Contiguous, Sample All Layers, Anti-alias
- New / Add / Subtract / Intersect (or Shift / Alt / Shift+Alt), animated marching ants
- **Select** menu, right-click menu and **Select** tab: Select Subject (AI), Skin Tones, All,
  Deselect, Inverse, Feather, Expand, Contract, Smooth, Border, Refine Edge (dots), Layer via
  Copy/Cut, Delete, Fill, Stroke, Crop to Selection
- **Retouch inside a selection:** Remove Blemishes (auto-detects acne, spots and small scars,
  leaves pupils alone), Smooth Skin (edge-preserving, keeps pore texture), Reduce Redness,
  Heal Selection
- **Spot Healing Brush (J):** paint over a spot and it's replaced with matching texture
- Filters, Brush and Eraser only affect the selection while one is active

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

**Optional Brev acceleration:** AI → AI Settings can run Remove Background, Select Subject,
and SAM object selection on the project's NVIDIA Brev GPU instead of the laptop. This is
only an accelerator for the same approved local models. Generative editing/fill remains on
the signed-in `phrame.tech/api/edit` → NVIDIA NIM path described above.
Setup and troubleshooting: [server/README.md](server/README.md).

**App persistence**: Phrame remembers the last local folder, up to 10 recent files
(File → Open Recent), and the window size/position with Qt QSettings.

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
| `app/selection.py`, `app/selection_actions.py`, `app/selection_panel.py` | selection tools, Select menu/tab |
| `app/retouch.py` | blemish removal, healing, skin smoothing, redness |
| `app/filters.py`, `app/imageio.py`, `app/dialogs.py`, `app/theme.py`, `app/icons.py` | supporting pieces |
