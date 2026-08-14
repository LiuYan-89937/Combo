import { diffLines } from 'diff'

export interface SideBySideDiffRow {
  key: string
  kind: 'context' | 'changed'
  oldLineNumber: number | null
  newLineNumber: number | null
  oldText: string | null
  newText: string | null
}

export function buildSideBySideDiff(oldText: string, newText: string): SideBySideDiffRow[] {
  const rows: SideBySideDiffRow[] = []
  let oldLineNumber = 1
  let newLineNumber = 1
  let removed: string[] = []
  let added: string[] = []

  const flushChanged = () => {
    const count = Math.max(removed.length, added.length)
    for (let index = 0; index < count; index += 1) {
      const oldLine = removed[index] ?? null
      const newLine = added[index] ?? null
      rows.push({
        key: `change-${rows.length}`,
        kind: 'changed',
        oldLineNumber: oldLine === null ? null : oldLineNumber++,
        newLineNumber: newLine === null ? null : newLineNumber++,
        oldText: oldLine,
        newText: newLine,
      })
    }
    removed = []
    added = []
  }

  diffLines(oldText, newText).forEach((part) => {
    const lines = splitDiffLines(part.value)
    if (part.removed) {
      removed.push(...lines)
      return
    }
    if (part.added) {
      added.push(...lines)
      return
    }
    flushChanged()
    lines.forEach((line) => {
      rows.push({
        key: `context-${rows.length}`,
        kind: 'context',
        oldLineNumber: oldLineNumber++,
        newLineNumber: newLineNumber++,
        oldText: line,
        newText: line,
      })
    })
  })
  flushChanged()
  return rows
}

function splitDiffLines(value: string): string[] {
  if (!value) return []
  const lines = value.split('\n')
  if (lines.at(-1) === '') lines.pop()
  return lines
}
