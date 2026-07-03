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

export function prepareMarkdownSource(content: string, options: { streaming?: boolean } = {}): string {
  const normalized = normalizeDisplayMarkdown(content)
  return options.streaming ? closeStreamingFence(normalized) : normalized
}

function normalizeDisplayMarkdown(content: string): string {
  const lines = content.replace(/\r\n?/g, '\n').split('\n')
  const normalized: string[] = []
  let openFence: OpenFence | null = null
  let plainBuffer: string[] = []

  function flushPlainBuffer() {
    if (plainBuffer.length === 0) return
    normalized.push(normalizePlainSegment(plainBuffer.join('\n')))
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

function normalizePlainSegment(segment: string): string {
  const lines = segment
    .split('\n')
    .flatMap((line) => normalizeMarkdownLine(line).split('\n'))
    .flatMap(expandCompactTableLine)

  const tableLineIndexes = findTableLineIndexes(lines)
  return lines
    .flatMap((line, index) => (
      tableLineIndexes.has(index)
        ? [line.trim()]
        : splitArtifactFields(line)
    ))
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

function normalizeMarkdownLine(line: string): string {
  const withBlockBreaks = line
    .replace(/([^\n\s])((?:---|\*\*\*|___)(?=#{1,6}\S))/g, '$1\n\n$2')
    .replace(/(^|\n)( {0,3}(?:---|\*\*\*|___))(?=#{1,6}\S)/g, '$1$2\n\n')
    .replace(/([^\n])(?=#{1,6}(?!#)\s?\S)/g, '$1\n\n')
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

function parseCompactTableRows(line: string): string[] | null {
  if (!line.includes('||')) return null
  const pipeCount = (line.match(/\|/g) || []).length
  if (pipeCount < 6) return null

  const rows = line
    .split(/\|\|+/)
    .map((row) => normalizeTableRow(row))
    .filter(Boolean)

  if (rows.length < 2) return null
  if (!isTableDelimiterRow(rows[1])) return null
  if (!hasCompatibleTableShape(rows[0], rows[1])) return null
  return rows
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

function closeStreamingFence(content: string): string {
  const lines = content.split('\n')
  let openFence: OpenFence | null = null
  for (const line of lines) {
    const fence = parseFenceLine(line)
    if (!fence) continue
    if (!openFence) {
      openFence = fence
    } else if (fence.marker === openFence.marker && fence.length >= openFence.length) {
      openFence = null
    }
  }
  if (!openFence) return content
  const closing = openFence.marker.repeat(openFence.length)
  return `${content}${content.endsWith('\n') ? '' : '\n'}${closing}\n`
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
