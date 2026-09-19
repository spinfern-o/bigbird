"use client"

import {
  Brush,
  Crop,
  Eraser,
  Hand,
  Move,
  Pipette,
  Type,
  type LucideIcon,
} from "lucide-react"
import type { ToolId } from "@/components/types"

interface ToolDef {
  id: ToolId
  label: string
  icon: LucideIcon
  hint: string
}

const TOOLS: ToolDef[] = [
  { id: "hand", label: "Pan", icon: Hand, hint: "Drag to move around the canvas" },
  { id: "move", label: "Move", icon: Move, hint: "Reposition the layer" },
  { id: "brush", label: "Brush", icon: Brush, hint: "Paint on the image" },
  { id: "eraser", label: "Eraser", icon: Eraser, hint: "Erase pixels" },
  { id: "crop", label: "Crop", icon: Crop, hint: "Trim the image" },
  { id: "picker", label: "Picker", icon: Pipette, hint: "Sample a color" },
  { id: "text", label: "Text", icon: Type, hint: "Add a text layer" },
]

interface ToolRailProps {
  tool: ToolId
  onToolChange: (tool: ToolId) => void
  disabled?: boolean
}

export function ToolRail({ tool, onToolChange, disabled }: ToolRailProps) {
  return (
    <nav
      aria-label="Tools"
      className="flex w-16 shrink-0 flex-col items-center gap-1 border-r border-border bg-rail py-2"
    >
      {TOOLS.map(({ id, label, icon: Icon, hint }) => {
        const active = tool === id
        return (
          <button
            key={id}
            type="button"
            onClick={() => onToolChange(id)}
            disabled={disabled}
            title={`${label} — ${hint}`}
            aria-pressed={active}
            className={`flex w-12 flex-col items-center gap-1 rounded-lg px-1 py-2 text-[10px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-30 ${
              active
                ? "bg-accent text-accent-foreground"
                : "text-[#cfcfd4] hover:bg-panel-raised"
            }`}
          >
            <Icon className="h-5 w-5" strokeWidth={1.75} />
            {label}
          </button>
        )
      })}
    </nav>
  )
}
