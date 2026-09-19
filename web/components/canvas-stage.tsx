"use client"

import { useCallback, useRef, useState } from "react"
import { EmptyState } from "@/components/empty-state"
import {
  type Adjustments,
  adjustmentsToFilter,
  type LoadedImage,
  type ToolId,
} from "@/components/types"

interface CanvasStageProps {
  image: LoadedImage | null
  tool: ToolId
  zoom: number
  offset: { x: number; y: number }
  adjustments: Adjustments
  onOffsetChange: (offset: { x: number; y: number }) => void
  onOpen: () => void
  onDropFile: (file: File) => void
  clampZoom: (z: number) => number
  setZoom: (updater: (z: number) => number) => void
}

export function CanvasStage({
  image,
  tool,
  zoom,
  offset,
  adjustments,
  onOffsetChange,
  onOpen,
  onDropFile,
  clampZoom,
  setZoom,
}: CanvasStageProps) {
  const stageRef = useRef<HTMLDivElement>(null)
  const panRef = useRef<{ startX: number; startY: number; originX: number; originY: number } | null>(
    null,
  )
  const [panning, setPanning] = useState(false)
  const [dragActive, setDragActive] = useState(false)

  const handleWheel = useCallback(
    (e: React.WheelEvent) => {
      if (!image) return
      e.preventDefault()
      const stage = stageRef.current
      if (!stage) return
      const rect = stage.getBoundingClientRect()
      // Pointer position relative to the stage center (where the image is anchored).
      const px = e.clientX - rect.left - rect.width / 2
      const py = e.clientY - rect.top - rect.height / 2
      const factor = Math.exp(-e.deltaY * 0.0015)
      setZoom((z) => {
        const next = clampZoom(z * factor)
        const ratio = next / z
        // Keep the point under the cursor fixed while scaling about the center.
        onOffsetChange({
          x: px - (px - offset.x) * ratio,
          y: py - (py - offset.y) * ratio,
        })
        return next
      })
    },
    [image, offset.x, offset.y, clampZoom, setZoom, onOffsetChange],
  )

  const canPan = tool === "hand"

  const handlePointerDown = (e: React.PointerEvent) => {
    if (!image) return
    // Pan with the Pan tool (left button) or the middle mouse button with any tool.
    if (!(canPan && e.button === 0) && e.button !== 1) return
    e.currentTarget.setPointerCapture(e.pointerId)
    panRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      originX: offset.x,
      originY: offset.y,
    }
    setPanning(true)
  }

  const handlePointerMove = (e: React.PointerEvent) => {
    if (!panRef.current) return
    onOffsetChange({
      x: panRef.current.originX + (e.clientX - panRef.current.startX),
      y: panRef.current.originY + (e.clientY - panRef.current.startY),
    })
  }

  const endPan = (e: React.PointerEvent) => {
    if (!panRef.current) return
    panRef.current = null
    setPanning(false)
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId)
    }
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragActive(false)
    const file = e.dataTransfer.files?.[0]
    if (file) onDropFile(file)
  }

  const cursor = !image
    ? "default"
    : canPan
      ? panning
        ? "grabbing"
        : "grab"
      : "default"

  return (
    <div
      ref={stageRef}
      className="checkerboard relative min-h-0 flex-1 overflow-hidden bg-canvas"
      style={{ cursor }}
      onWheel={handleWheel}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={endPan}
      onPointerCancel={endPan}
      onDragOver={(e) => {
        e.preventDefault()
        if (!dragActive) setDragActive(true)
      }}
      onDragLeave={(e) => {
        if (e.currentTarget === e.target) setDragActive(false)
      }}
      onDrop={handleDrop}
    >
      {image ? (
        <div className="absolute inset-0 flex items-center justify-center">
          <img
            src={image.src || "/placeholder.svg"}
            alt={image.name}
            draggable={false}
            className="max-w-none select-none shadow-2xl shadow-black/60"
            style={{
              transform: `translate(${offset.x}px, ${offset.y}px) scale(${zoom})`,
              transformOrigin: "center center",
              filter: adjustmentsToFilter(adjustments),
              imageRendering: zoom > 3 ? "pixelated" : "auto",
            }}
          />
        </div>
      ) : (
        <EmptyState onOpen={onOpen} dragActive={dragActive} />
      )}
    </div>
  )
}
