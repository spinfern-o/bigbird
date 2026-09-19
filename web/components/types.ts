export type ToolId =
  | "hand"
  | "move"
  | "brush"
  | "eraser"
  | "crop"
  | "picker"
  | "text"

export interface Adjustments {
  exposure: number
  contrast: number
  saturation: number
  temperature: number
  vibrance: number
}

export const DEFAULT_ADJUSTMENTS: Adjustments = {
  exposure: 0,
  contrast: 0,
  saturation: 0,
  temperature: 0,
  vibrance: 0,
}

/** Translate the develop adjustments into an equivalent CSS filter string. */
export function adjustmentsToFilter(a: Adjustments): string {
  const brightness = 1 + a.exposure / 100
  const contrast = 1 + a.contrast / 100
  const saturate = 1 + (a.saturation + a.vibrance / 2) / 100
  // Warm/cool cast approximated with sepia + a hue nudge.
  const warmth = Math.abs(a.temperature) / 100
  const sepia = a.temperature > 0 ? warmth * 0.5 : 0
  const hue = a.temperature < 0 ? warmth * 25 : 0
  return [
    `brightness(${brightness.toFixed(3)})`,
    `contrast(${contrast.toFixed(3)})`,
    `saturate(${Math.max(0, saturate).toFixed(3)})`,
    `sepia(${sepia.toFixed(3)})`,
    `hue-rotate(${hue.toFixed(1)}deg)`,
  ].join(" ")
}

export interface LoadedImage {
  src: string
  name: string
  width: number
  height: number
}
