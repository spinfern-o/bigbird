"use client"

import { ImagePlus, MousePointer2, SlidersHorizontal, Upload } from "lucide-react"

interface EmptyStateProps {
  onOpen: () => void
  dragActive: boolean
}

const STEPS = [
  {
    icon: Upload,
    title: "Open a photo",
    body: "Click the button below or drag an image straight onto this canvas. JPG, PNG, WebP and GIF all work.",
  },
  {
    icon: MousePointer2,
    title: "Move around",
    body: "Scroll to zoom toward your cursor. Pick the Pan tool on the left and drag to reposition.",
  },
  {
    icon: SlidersHorizontal,
    title: "Develop it",
    body: "Use the panel on the right to adjust exposure, contrast, color and warmth in real time.",
  },
]

export function EmptyState({ onOpen, dragActive }: EmptyStateProps) {
  return (
    <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-6">
      <div
        className={`pointer-events-auto w-full max-w-xl rounded-2xl border-2 border-dashed p-8 text-center transition-colors ${
          dragActive ? "border-accent bg-accent/5" : "border-border-strong bg-panel/40"
        }`}
      >
        <div className="mx-auto mb-5 grid h-14 w-14 place-items-center rounded-xl bg-accent/15 text-accent">
          <ImagePlus className="h-7 w-7" />
        </div>
        <h1 className="text-2xl font-bold tracking-tight text-balance">
          Start editing in Bigbird
        </h1>
        <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-muted text-pretty">
          {dragActive
            ? "Drop your image to load it onto the canvas."
            : "There is nothing here yet. Load a photo to get a central canvas with zoom, pan and live adjustments."}
        </p>

        <ol className="mt-7 grid gap-3 text-left sm:grid-cols-3">
          {STEPS.map(({ icon: Icon, title, body }, i) => (
            <li
              key={title}
              className="rounded-lg border border-border bg-panel px-3 py-3"
            >
              <div className="mb-2 flex items-center gap-2">
                <span className="grid h-6 w-6 place-items-center rounded-md bg-panel-raised text-accent">
                  <Icon className="h-3.5 w-3.5" />
                </span>
                <span className="text-[11px] font-semibold uppercase tracking-wider text-muted">
                  Step {i + 1}
                </span>
              </div>
              <p className="text-xs font-semibold text-foreground">{title}</p>
              <p className="mt-1 text-[11px] leading-relaxed text-muted">{body}</p>
            </li>
          ))}
        </ol>

        <button
          type="button"
          onClick={onOpen}
          className="mt-7 inline-flex items-center gap-2 rounded-lg bg-accent px-5 py-2.5 text-sm font-semibold text-accent-foreground transition-colors hover:bg-accent-hover"
        >
          <ImagePlus className="h-4 w-4" />
          Open image
        </button>
      </div>
    </div>
  )
}
