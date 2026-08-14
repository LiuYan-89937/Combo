import { describe, expect, it } from 'vitest'
import { formatBytes, formatCount, formatDate, shortHash } from '@/composables/useFormat'

describe('formatBytes', () => {
  it('handles zero and invalid input', () => {
    expect(formatBytes(0)).toBe('0 B')
    expect(formatBytes(null)).toBe('—')
    expect(formatBytes(undefined)).toBe('—')
    expect(formatBytes(-5)).toBe('—')
  })

  it('scales through units', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(1536)).toBe('1.5 KB')
    expect(formatBytes(200 * 1024 * 1024)).toBe('200 MB')
    expect(formatBytes(3 * 1024 * 1024 * 1024)).toBe('3 GB')
  })
})

describe('formatCount', () => {
  it('compacts large numbers', () => {
    expect(formatCount(0)).toBe('0')
    expect(formatCount(999)).toBe('999')
    expect(formatCount(1200)).toBe('1.2k')
    expect(formatCount(1_500_000)).toBe('1.5M')
    expect(formatCount(null)).toBe('0')
  })
})

describe('formatDate', () => {
  it('returns a dash for empty or invalid values', () => {
    expect(formatDate('', 'en')).toBe('—')
    expect(formatDate('not-a-date', 'en')).toBe('—')
    expect(formatDate(null, 'zh')).toBe('—')
  })

  it('formats a valid ISO date', () => {
    expect(formatDate('2026-01-15T00:00:00Z', 'en')).toContain('2026')
  })
})

describe('shortHash', () => {
  it('shortens long hashes and passes through short ones', () => {
    const full = 'a'.repeat(64)
    expect(shortHash(full)).toBe(`${'a'.repeat(8)}…${'a'.repeat(6)}`)
    expect(shortHash('abc')).toBe('abc')
    expect(shortHash(null)).toBe('—')
  })
})
