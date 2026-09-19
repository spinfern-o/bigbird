"use client"

import { useState } from "react"
import { RotateCcw } from "lucide-react"
import type { Adjustments, LoadedImage } from "@/components/types"

interface EditPanelProps {
  image: LoadedImage | null
  adjustments: Adjustments
  onChange: (a: Adjustments) => void
  onReset: () => void
}

interface SliderDef {
  key: keyof Adjustments
  label: string
  min: number
  max: number
}

const LIGHT: SliderDef[] = [
  { key: "exposure", label: "Exposure", min: -100, max: 100 },
  { key: "contrast", label: "Contrast", min: -100, max: 100 },
]

const COLOR: SliderDef[] = [
  { key: "temperature", label: "Temperature", min: -100, max: 100 },
  { key: "vibrance", label: "Vibrance", min: -100, max: 100 },
  { key: "saturation", label: "Saturation", min: -100, max: 100 },
]

const TABS = ["Develop", "Editing"] as const

export function EditPanel({ image, adjustments, onChange, onReset }: EditPanelProps) {
  const [tab, setTab] = useState<(typeof TABS)[number]>("Develop")
  const disabled = !image

  const set = (key: keyof Adjustments, value: number) =>
    onChange({ ...adjustments, [key]: value })

  const isDirty = Object.values(adjustments).some((v) => v !== 0)

  return (
    <aside className="flex w-72 shrink-0 flex-col border-l border-border bg-panel">
      <div className="flex shrink-0 border-b border-border">
        {TABS.map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={`flex-1 border-b-2 px-4 py-3 text-xs font-bold transition-colors ${
              tab === t
                ? "border-accent text-foreground"
                : "border-transparent text-muted hover:text-foreground"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {tab === "Develop" ? (
          <div className="space-y-6">
            <Section title="Light">
              {LIGHT.map((s) => (
                <Slider
                  key={s.key}
                  def={s}
                  value={adjustments[s.key]}
                  disabled={disabled}
                  onChange={(v) => set(s.key, v)}
                />
              ))}
            </Section>
            <Section title="Color">
              {COLOR.map((s) => (
                <Slider
                  key={s.key}
                  def={s}
                  value={adjustments[s.key]}
                  disabled={disabled}
                  onChange={(v) => set(s.key, v)}
                />
              ))}
            </Section>
          </div>
        ) : (
          <p className="text-xs leading-relaxed text-muted">
            Layers, brushes and filters live here in the desktop app. This browser
            preview focuses on opening an image and non-destructive develop
            adjustments.
          </p>
        )}
      </div>

      <div className="shrink-0 border-t border-border p-3">
        <button
          type="button"
          onClick={onReset}
          disabled={disabled || !isDirty}
          className="flex w-full items-center justify-center gap-2 rounded-md border border-border bg-panel-raised py-2 text-xs font-semibold text-foreground transition-colors hover:border-border-strong disabled:cursor-not-allowed disabled:opacity-40"
        >
          <RotateCcw className="h-3.5 w-3.5" />
          Reset adjustments
        </button>
      </div>
    </aside>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h2 className="mb-3 text-[11px] font-bold uppercase tracking-wider text-muted">
        {title}
      </h2>
      <div className="space-y-4">{children}</div>
    </div>
  )
}

function Slider({
  def,
  value,
  disabled,
  onChange,
}: {
  def: SliderDef
  value: number
  disabled: boolean
  onChange: (v: number) => void
}) {
  return (
    <div className={disabled ? "opacity-40" : undefined}>
      <div className="mb-1.5 flex items-center justify-between">
        <button
          type="button"
          disabled={disabled}
          onDoubleClick={() => onChange(0)}
          title="Double-click to reset"
          className="text-xs font-medium text-foreground disabled:cursor-not-allowed"
        >
          {def.label}
        </button>
        <span className="text-xs tabular-nums text-muted">{value}</span>
      </div>
      <input
        type="range"
        min={def.min}
        max={def.max}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full disabled:cursor-not-allowed"
        aria-label={def.label}
      />
    </div>
  )
}
