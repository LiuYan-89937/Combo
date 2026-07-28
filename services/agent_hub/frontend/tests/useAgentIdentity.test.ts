import { describe, expect, it } from 'vitest'
import { agentIdentity, agentTextureDataUri } from '@/composables/useAgentIdentity'

describe('agentIdentity', () => {
  it('is deterministic for the same key', () => {
    const a = agentIdentity('liuyan', 'my-agent')
    const b = agentIdentity('liuyan', 'my-agent')
    expect(a).toEqual(b)
  })

  it('differs across keys', () => {
    const a = agentIdentity('liuyan', 'agent-one')
    const b = agentIdentity('liuyan', 'agent-two')
    expect(a.seed).not.toBe(b.seed)
  })

  it('derives uppercase initials and a hue in range', () => {
    const id = agentIdentity('acme', 'weather-bot')
    expect(id.initials).toBe('WE')
    expect(id.hue).toBeGreaterThanOrEqual(0)
    expect(id.hue).toBeLessThan(360)
  })

  it('falls back to a placeholder for empty ids', () => {
    const id = agentIdentity('', '')
    expect(id.initials).toBe('?')
  })
})

describe('agentTextureDataUri', () => {
  it('returns a stable svg data uri', () => {
    const id = agentIdentity('acme', 'weather-bot')
    const light = agentTextureDataUri(id, false)
    const dark = agentTextureDataUri(id, true)
    expect(light.startsWith('data:image/svg+xml,')).toBe(true)
    expect(dark).not.toBe(light)
    expect(agentTextureDataUri(id, false)).toBe(light)
  })
})
