"use client"

import { useCallback, useRef, useState } from "react"
import { TopBar } from "@/components/top-bar"
import { ToolRail } from "@/components/tool-rail"
import { CanvasStage } from "@/components/canvas-stage"
import { EditPanel } from "@/components/edit-panel"
import {
  type Adjustments,
  DEFAULT_ADJUSTMENTS,
  type LoadedImage,
  type ToolId,
} from "@/components/types"

const MIN_ZOOM = 0.05
const MAX_ZOOM = 32

export function Editor() {
  const [image, setImage] = useState<LoadedImage | null>(null)
  const [tool, setTool] = useState<ToolId>("hand")
  const [zoom, setZoom] = useState(1)
  const [offset, setOffset] = useState({ x: 0, y: 0 })
  const [adjustments, setAdjustments] = useState<Adjustments>(DEFAULT_ADJUSTMENTS)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const clampZoom = (z: number) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z))

  const fitToView = useCallback(() => {
    setZoom(1)
    setOffset({ x: 0, y: 0 })
  }, [])

  const loadFile = useCallback((file: File) => {
    if (!file.type.startsWith("image/")) return
    const reader = new FileReader()
    reader.onload = () => {
      const src = reader.result as string
      const probe = new Image()
      probe.crossOrigin = "anonymous"
      probe.onload = () => {
        setImage({ src, name: file.name, width: probe.width, height: probe.height })
        setAdjustments(DEFAULT_ADJUSTMENTS)
        setZoom(1)
        setOffset({ x: 0, y: 0 })
      }
      probe.src = src
    }
    reader.readAsDataURL(file)
  }, [])

  const onPickFile = () => fileInputRef.current?.click()

  const onFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) loadFile(file)
    e.target.value = ""
  }

  const zoomBy = useCallback(
    (factor: number) => setZoom((z) => clampZoom(z * factor)),
    [],
  )

  return (
    <div className="flex h-dvh w-full flex-col overflow-hidden bg-background text-foreground">
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        className="sr-only"
        onChange={onFileInputChange}
      />
      <TopBar
        image={image}
        zoom={zoom}
        onOpen={onPickFile}
        onZoomIn={() => zoomBy(1.25)}
        onZoomOut={() => zoomBy(1 / 1.25)}
        onFit={fitToView}
      />
      <div className="flex min-h-0 flex-1">
        <ToolRail tool={tool} onToolChange={setTool} disabled={!image} />
        <CanvasStage
          image={image}
          tool={tool}
          zoom={zoom}
          offset={offset}
          adjustments={adjustments}
          onOffsetChange={setOffset}
          onOpen={onPickFile}
          onDropFile={loadFile}
          clampZoom={clampZoom}
          setZoom={setZoom}
        />
        <EditPanel
          image={image}
          adjustments={adjustments}
          onChange={setAdjustments}
          onReset={() => setAdjustments(DEFAULT_ADJUSTMENTS)}
        />
      </div>
    </div>
  )
}
