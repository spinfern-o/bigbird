"use client"

import { ImagePlus, Maximize2, Minus, Plus } from "lucide-react"
import type { LoadedImage } from "@/components/types"

interface TopBarProps {
  image: LoadedImage | null
  zoom: number
  onOpen: () => void
  onZoomIn: () => void
  onZoomOut: () => void
  onFit: () => void
}

export function TopBar({ image, zoom, onOpen, onZoomIn, onZoomOut, onFit }: TopBarProps) {
  return (
    <header className="flex h-12 shrink-0 items-center justify-between border-b border-border bg-panel-raised px-3">
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2">
          <span
            className="grid h-6 w-6 place-items-center rounded-md bg-accent text-[13px] font-black text-accent-foreground"
            aria-hidden="true"
          >
            B
          </span>
          <span className="text-sm font-semibold tracking-tight">Bigbird</span>
          <span className="rounded bg-panel px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-muted">
            Web
          </span>
        </div>
        {image && (
          <span className="ml-2 max-w-[240px] truncate text-xs text-muted" title={image.name}>
            {image.name} · {image.width}×{image.height}
          </span>
        )}
      </div>

      <div className="flex items-center gap-2">
        <div className="flex items-center gap-1 rounded-md border border-border bg-panel p-0.5">
          <button
            type="button"
            onClick={onZoomOut}
            disabled={!image}
            className="grid h-7 w-7 place-items-center rounded text-muted transition-colors hover:bg-panel-raised hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
            aria-label="Zoom out"
          >
            <Minus className="h-4 w-4" />
          </button>
          <span className="w-12 text-center text-xs tabular-nums text-foreground">
            {Math.round(zoom * 100)}%
          </span>
          <button
            type="button"
            onClick={onZoomIn}
            disabled={!image}
            className="grid h-7 w-7 place-items-center rounded text-muted transition-colors hover:bg-panel-raised hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
            aria-label="Zoom in"
          >
            <Plus className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={onFit}
            disabled={!image}
            className="grid h-7 w-7 place-items-center rounded text-muted transition-colors hover:bg-panel-raised hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
            aria-label="Fit to screen"
          >
            <Maximize2 className="h-4 w-4" />
          </button>
        </div>

        <button
          type="button"
          onClick={onOpen}
          className="flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-xs font-semibold text-accent-foreground transition-colors hover:bg-accent-hover"
        >
          <ImagePlus className="h-4 w-4" />
          Open image
        </button>
      </div>
    </header>
  )
}
