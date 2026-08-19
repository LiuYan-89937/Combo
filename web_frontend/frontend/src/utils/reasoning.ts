export const REASONING_INTENSITY_MIN = 1
export const REASONING_INTENSITY_DEFAULT = 2
export const REASONING_INTENSITY_MAX = 3

export function normalizeReasoningIntensity(value: unknown): number {
  const intensity = Number(value)
  if (!Number.isInteger(intensity)) return REASONING_INTENSITY_DEFAULT
  if (intensity < REASONING_INTENSITY_MIN || intensity > REASONING_INTENSITY_MAX) {
    return REASONING_INTENSITY_DEFAULT
  }
  return intensity
}
