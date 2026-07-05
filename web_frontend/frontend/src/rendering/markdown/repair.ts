interface OpenFence {
  marker: '`' | '~'
  length: number
}

const ARTIFACT_FIELD_MARKERS = [
  '📄',
  '📁',
  '📦',
  '📑',
  '🧾',
  '🔗',
]

export function repairAiMarkdown(content: string): string {
  const lines = content.replace(/\r\n?/g, '\n').split('\n')
  const normalized: string[] = []
  let openFence: OpenFence | null = null
  let plainBuffer: string[] = []

  function flushPlainBuffer() {
    if (plainBuffer.length === 0) return
    normalized.push(repairPlainSegment(plainBuffer.join('\n')))
    plainBuffer = []
  }

  for (const line of lines) {
    const fence = parseFenceLine(line)
    if (fence) {
      flushPlainBuffer()
      normalized.push(line)
      if (!openFence) {
        openFence = fence
      } else if (fence.marker === openFence.marker && fence.length >= openFence.length) {
        openFence = null
      }
      continue
    }

    if (openFence) {
      flushPlainBuffer()
      normalized.push(line)
      continue
    }

    plainBuffer.push(line)
  }

  flushPlainBuffer()
  return normalized.join('\n')
}

function repairPlainSegment(segment: string): string {
  const lines = segment
    .split('\n')
    .flatMap((line) => repairMarkdownLine(line).split('\n'))
    .flatMap(splitInlineCompactTableStart)
    .flatMap(expandCompactTableLine)
    .flatMap(splitInlineOrderedListItems)
    .flatMap(splitInlineUnorderedListItems)
    .map(normalizeListMarkerSpacing)

  const tableLineIndexes = findTableLineIndexes(lines)
  const repairedLines = lines
    .flatMap((line, index) => (
      tableLineIndexes.has(index)
        ? [line.trim()]
        : splitArtifactFields(line)
    ))
  return separateTableBlocks(repairedLines)
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

function repairMarkdownLine(line: string): string {
  const withBlockBreaks = line
    .replace(/([^\n\s])((?:---|\*\*\*|___)(?=#{1,6}\S))/g, '$1\n\n$2')
    .replace(/(^|\n)( {0,3}(?:---|\*\*\*|___))(?=#{1,6}\S)/g, '$1$2\n\n')
    .replace(/([^\n])(?=#{1,6}(?!#)\s?\S)/g, '$1\n\n')
    .replace(/([^\n])(?=(?:#{1,6})\s)/g, '$1\n\n')
    .replace(/([：:])(?=\|[^|\n]+\|)/g, '$1\n\n')

  return withBlockBreaks
    .split('\n')
    .map((part) => part.replace(/^( {0,3}#{1,6})(?=[^\s#])/, '$1 '))
    .join('\n')
}

function expandCompactTableLine(line: string): string[] {
  const rows = parseCompactTableRows(line)
  return rows ?? [line]
}

function splitInlineCompactTableStart(line: string): string[] {
  const start = findInlineCompactTableStart(line)
  if (start <= 0) return [line]
  const before = line.slice(0, start).trimEnd()
  const table = line.slice(start).trimStart()
  return before ? [before, table] : [table]
}

function findInlineCompactTableStart(line: string): number {
  for (let index = 1; index < line.length; index += 1) {
    if (line[index] !== '|') continue
    const candidate = line.slice(index)
    const rows = parseCompactTableRows(candidate)
    if (rows && rows.length >= 3) return index
  }
  return -1
}

function parseCompactTableRows(line: string): string[] | null {
  if (!line.includes('||')) return null
  const pipeCount = (line.match(/\|/g) || []).length
  if (pipeCount < 6) return null

  const rows = splitCompactTableCandidate(line)
    .filter(Boolean)

  if (rows.length < 2) return null
  if (isTableDelimiterRow(rows[1])) {
    if (!hasCompatibleTableShape(rows[0], rows[1])) return null
    return tableRowsWithCompatibleBody(rows)
  }
  if (!hasCompatibleTableDataShape(rows)) return null
  return [rows[0], tableDelimiterForRow(rows[0]), ...rows.slice(1)]
}

function splitCompactTableCandidate(line: string): string[] {
  return line
    .split(/\|\|+/)
    .map((row) => normalizeTableRow(row))
}

function tableRowsWithCompatibleBody(rows: string[]): string[] | null {
  const columnCount = splitTableCells(rows[0]).length
  const accepted = rows.slice(0, 2)
  const remainder: string[] = []
  let acceptingRows = true

  for (const row of rows.slice(2)) {
    if (acceptingRows && splitTableCells(row).length === columnCount) {
      accepted.push(row)
      continue
    }
    acceptingRows = false
    remainder.push(row)
  }

  if (accepted.length < 3) return null
  if (!remainder.length) return accepted
  return [...accepted, ...remainder.map(tableRowToPlainText)]
}

function tableRowToPlainText(row: string): string {
  return splitTableCells(row).join(' | ')
}

function hasCompatibleTableDataShape(rows: string[]): boolean {
  const columnCount = splitTableCells(rows[0]).length
  return columnCount >= 2 && rows.every((row) => splitTableCells(row).length === columnCount)
}

function tableDelimiterForRow(row: string): string {
  const cells = splitTableCells(row)
  return `|${cells.map(() => '---').join('|')}|`
}

function splitInlineOrderedListItems(line: string): string[] {
  const matches = [...line.matchAll(/(?:^|[^\d])(\d{1,2}[.)])(?=\S)/g)]
  if (matches.length < 2) return [line]
  return splitAtIndexes(line, matches.map((match) => Number(match.index) + (match[0].length - match[1].length)))
}

function splitInlineUnorderedListItems(line: string): string[] {
  const matches = [...line.matchAll(/(?:^|\s)([-*+])(?=\S)/g)]
  if (matches.length < 2) return [line]
  return splitAtIndexes(line, matches.map((match) => Number(match.index) + (match[0].length - match[1].length)))
}

function splitAtIndexes(line: string, indexes: number[]): string[] {
  const starts = [...indexes]
  if (starts[0] !== 0) {
    starts.unshift(0)
  }

  const parts: string[] = []
  for (let index = 0; index < starts.length; index += 1) {
    const start = starts[index]
    const end = starts[index + 1] ?? line.length
    const part = line.slice(start, end).trim()
    if (part) parts.push(part)
  }
  return parts.length > 1 ? parts : [line]
}

function normalizeListMarkerSpacing(line: string): string {
  return line
    .replace(/^(\s{0,3})([-*+])(?=\S)/, '$1$2 ')
    .replace(/^(\s{0,3}\d{1,2}[.)])(?=\S)/, '$1 ')
    .replace(/^(\s{0,3})([-*+])\s+(\[[ xX]\])(?=\S)/, '$1$2 $3 ')
}

function normalizeTableRow(row: string): string {
  const trimmed = row.trim()
  if (!trimmed || !trimmed.includes('|')) return ''
  const withLeadingPipe = trimmed.startsWith('|') ? trimmed : `|${trimmed}`
  return withLeadingPipe.endsWith('|') ? withLeadingPipe : `${withLeadingPipe}|`
}

function hasCompatibleTableShape(headerRow: string, delimiterRow: string): boolean {
  const headerCells = splitTableCells(headerRow)
  const delimiterCells = splitTableCells(delimiterRow)
  return headerCells.length >= 2 && headerCells.length === delimiterCells.length
}

function findTableLineIndexes(lines: string[]): Set<number> {
  const indexes = new Set<number>()
  for (let index = 1; index < lines.length; index += 1) {
    if (!isTableDelimiterRow(lines[index])) continue
    if (!isTableDataRow(lines[index - 1])) continue

    indexes.add(index - 1)
    indexes.add(index)
    for (let rowIndex = index + 1; rowIndex < lines.length; rowIndex += 1) {
      if (!isTableDataRow(lines[rowIndex])) break
      indexes.add(rowIndex)
    }
  }
  return indexes
}

function separateTableBlocks(lines: string[]): string[] {
  const tableLineIndexes = findTableLineIndexes(lines)
  if (!tableLineIndexes.size) return lines

  const output: string[] = []
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index]
    const isTableLine = tableLineIndexes.has(index)
    const previousIsTableLine = tableLineIndexes.has(index - 1)
    const nextIsTableLine = tableLineIndexes.has(index + 1)

    if (isTableLine && !previousIsTableLine && output.length > 0 && output[output.length - 1].trim()) {
      output.push('')
    }
    output.push(line)
    if (isTableLine && !nextIsTableLine && index < lines.length - 1 && lines[index + 1].trim()) {
      output.push('')
    }
  }
  return output
}

function isTableDataRow(line: string): boolean {
  const cells = splitTableCells(line)
  return cells.length >= 2
}

function isTableDelimiterRow(line: string): boolean {
  const cells = splitTableCells(line)
  return cells.length >= 2 && cells.every((cell) => /^:?-{3,}:?$/.test(cell))
}

function splitTableCells(line: string): string[] {
  const trimmed = line.trim()
  if (!trimmed.includes('|')) return []
  const withoutLeadingPipe = trimmed.startsWith('|') ? trimmed.slice(1) : trimmed
  const withoutOuterPipes = withoutLeadingPipe.endsWith('|')
    ? withoutLeadingPipe.slice(0, -1)
    : withoutLeadingPipe
  return withoutOuterPipes
    .split('|')
    .map((cell) => cell.trim())
}

function splitArtifactFields(line: string): string[] {
  const trimmed = line.trim()
  if (!trimmed || !ARTIFACT_FIELD_MARKERS.some((marker) => trimmed.includes(marker))) {
    return [line]
  }

  const parts = trimmed
    .replace(new RegExp(`(?!^)(${ARTIFACT_FIELD_MARKERS.map(escapeRegExp).join('|')})(?=\\s*[^：:\\n]{1,12}[：:])`, 'g'), '\n$1')
    .split('\n')
    .map((part) => part.trim())
    .filter(Boolean)

  if (parts.length <= 1) return [line]
  return parts.map((part) => (
    ARTIFACT_FIELD_MARKERS.some((marker) => part.startsWith(marker)) && /[：:]/.test(part)
      ? `- ${part}`
      : part
  ))
}

function parseFenceLine(line: string): OpenFence | null {
  const match = line.match(/^ {0,3}(`{3,}|~{3,})/)
  if (!match) return null
  const fence = match[1]
  return {
    marker: fence[0] as '`' | '~',
    length: fence.length,
  }
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}
