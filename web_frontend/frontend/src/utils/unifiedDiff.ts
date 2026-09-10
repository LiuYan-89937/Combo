import { diffLines } from 'diff'

export interface UnifiedDiffRow {
  kind: 'context' | 'added' | 'removed'
  lineNumber: number
  text: string
}

/** 折叠后的落点：一整块可见行，或一段被隐藏的未变更行。 */
export interface UnifiedDiffBlock {
  kind: 'rows' | 'gap'
  rows: UnifiedDiffRow[]
}

/** 改动前后各自保留的上下文行数。 */
export const DIFF_CONTEXT_LINES = 4
/** 短于该长度的空档不值得折叠，直接当作普通上下文。 */
const MINIMUM_GAP_LINES = 3

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

/**
 * 把整份文件的 diff 收敛成「改动 + 少量上下文」的区块，未变更的长段折叠成 gap。
 * 这样长文件里只需看改动附近，而不是从文件头翻起。
 */
export function collapseUnifiedDiff(
  rows: UnifiedDiffRow[],
  contextLines: number = DIFF_CONTEXT_LINES,
): UnifiedDiffBlock[] {
  const keep = new Array<boolean>(rows.length).fill(false)
  rows.forEach((row, index) => {
    if (row.kind === 'context') return
    const start = Math.max(0, index - contextLines)
    const end = Math.min(rows.length - 1, index + contextLines)
    for (let cursor = start; cursor <= end; cursor += 1) keep[cursor] = true
  })

  const blocks: UnifiedDiffBlock[] = []
  let pending: UnifiedDiffRow[] = []

  const flush = () => {
    if (!pending.length) return
    // 太短的空白段折叠起来反而更碎，直接展开显示。
    blocks.push(pending.length < MINIMUM_GAP_LINES
      ? { kind: 'rows', rows: pending }
      : { kind: 'gap', rows: pending })
    pending = []
  }

  rows.forEach((row, index) => {
    if (!keep[index]) {
      pending.push(row)
      return
    }
    flush()
    const last = blocks.at(-1)
    if (last && last.kind === 'rows') last.rows.push(row)
    else blocks.push({ kind: 'rows', rows: [row] })
  })
  flush()
  return blocks
}

function splitDiffLines(value: string): string[] {
  if (!value) return []
  const lines = value.split('\n')
  if (lines.at(-1) === '') lines.pop()
  return lines
}

