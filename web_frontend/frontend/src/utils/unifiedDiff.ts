import { diffLines } from 'diff'

export interface UnifiedDiffRow {
  kind: 'context' | 'added' | 'removed'
  lineNumber: number
  text: string
}

export function buildUnifiedDiff(oldText: string, newText: string): UnifiedDiffRow[] {
  const rows: UnifiedDiffRow[] = []
  let oldLineNumber = 1
  let newLineNumber = 1

  diffLines(oldText, newText).forEach((part) => {
    splitDiffLines(part.value).forEach((text) => {
      if (part.removed) {
        rows.push({ kind: 'removed', lineNumber: oldLineNumber, text })
        oldLineNumber += 1
        return
      }
      if (part.added) {
        rows.push({ kind: 'added', lineNumber: newLineNumber, text })
        newLineNumber += 1
        return
      }
      rows.push({ kind: 'context', lineNumber: newLineNumber, text })
      oldLineNumber += 1
      newLineNumber += 1
    })
  })
  return rows
}

function splitDiffLines(value: string): string[] {
  if (!value) return []
  const lines = value.split('\n')
  if (lines.at(-1) === '') lines.pop()
  return lines
}
