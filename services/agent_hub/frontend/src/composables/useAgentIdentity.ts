/*
 * Deterministic visual identity for an Agent package.
 *
 * The backend has no icon field, so we derive a stable monochrome mark from
 * `publisher/package_id`. Color/shape here is purely visual — it must never be
 * treated as an identity or safety signal.
 */

export interface AgentIdentity {
  /** One or two initials for the mark. */
  initials: string
  /** Deterministic hue used only for a subtle single-tone wash. */
  hue: number
  /** Rotation applied to the generated pattern, in degrees. */
  angle: number
  /** Seed exposed for the pattern generator. */
  seed: number
}

function hashString(input: string): number {
  let hash = 2166136261
  for (let i = 0; i < input.length; i += 1) {
    hash ^= input.charCodeAt(i)
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}

export function agentIdentity(publisher: string, packageId: string): AgentIdentity {
  const key = `${publisher}/${packageId}`.toLowerCase()
  const hash = hashString(key)

  const source = (packageId || publisher || '?').replace(/[^a-zA-Z0-9]/g, '')
  const initials = (source.slice(0, 2) || '?').toUpperCase()

  return {
    initials,
    hue: hash % 360,
    angle: hash % 8 << 5,
    seed: hash,
  }
}

/**
 * Build a compact SVG data URI: a deterministic dotted texture on a subtle
 * tinted ground. Monochrome-friendly — the tint is very low saturation so it
 * reads as texture, not brand color.
 */
export function agentTextureDataUri(identity: AgentIdentity, dark: boolean): string {
  const { seed, hue } = identity
  const ground = dark ? `hsl(${hue}, 10%, 9%)` : `hsl(${hue}, 22%, 97%)`
  const dot = dark ? `hsla(${hue}, 18%, 78%, 0.16)` : `hsla(${hue}, 26%, 30%, 0.1)`

  const cells: string[] = []
  let state = seed
  for (let y = 0; y < 5; y += 1) {
    for (let x = 0; x < 5; x += 1) {
      state = (state * 1103515245 + 12345) & 0x7fffffff
      if ((state >> 8) % 3 === 0) {
        const cx = 12 + x * 19
        const cy = 12 + y * 19
        const r = 2.5 + ((state >> 4) % 3)
        cells.push(`<circle cx="${cx}" cy="${cy}" r="${r}" fill="${dot}" />`)
      }
    }
  }

  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100"><rect width="100" height="100" fill="${ground}"/>${cells.join('')}</svg>`
  return `data:image/svg+xml,${encodeURIComponent(svg)}`
}
