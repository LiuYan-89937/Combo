import { repairAiMarkdown } from './repair'

interface OpenFence {
  marker: '`' | '~'
  length: number
}

export function prepareMarkdownSource(content: string, options: { streaming?: boolean } = {}): string {
  const normalized = repairAiMarkdown(content)
  if (!options.streaming) return normalized
  return completeStreamingTable(closeStreamingFence(normalized))
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

/**
 * GFM only recognizes a table once its delimiter row (`| --- |`) has arrived, so
 * while a table streams in, its header and first rows render as one ordinary
 * paragraph with visible pipes and only then snap into a table. Completing the
 * missing delimiter row keeps it a table from its first row, so all that keeps
 * growing afterwards is the row list.
 *
 * Only the trailing table is touched — everything already finished stays byte
 * for byte identical, which is also what lets completed blocks keep their DOM.
 */
function completeStreamingTable(content: string): string {
  const lines = content.split('\n')
  const start = trailingTableStart(lines)
  if (start < 0) return content

  const header = lines[start]
  const columns = tableColumnCount(header)
  if (columns < 2) return content
  if (isIndentedCode(header)) return content
  // A quoted table needs its delimiter prefixed with `>`, so leave blockquotes alone.
  if (header.trimStart().startsWith('>')) return content

  const delimiter = delimiterCells(lines[start + 1])
  if (delimiter) {
    if (delimiter.length === columns) return content
    lines[start + 1] = delimiterRow(columns)
    return lines.join('\n')
  }

  // A lone line is only completed when it already looks like a row (`| a | b`);
  // a single prose line that merely contains a pipe is left alone.
  if (start === lines.length - 1 && !header.trimStart().startsWith('|')) return content
  lines.splice(start + 1, 0, delimiterRow(columns))
  return lines.join('\n')
}

/** Index of the first line of the trailing run of pipe lines, or -1. */
function trailingTableStart(lines: string[]): number {
  let end = lines.length - 1
  while (end >= 0 && !lines[end].trim()) end -= 1
  if (end < 0) return -1

  let start = end
  while (start > 0 && lines[start - 1].trim() && lines[start - 1].includes('|')) start -= 1
  if (!lines[start].includes('|')) return -1
  // A fence marker can never be part of a table, so a trailing unterminated
  // code block never matches here.
  if (parseFenceLine(lines[start])) return -1
  return start
}

/** Number of cells in a row, ignoring escaped pipes. */
function tableColumnCount(line: string): number {
  const trimmed = line.trim()
  if (!trimmed.includes('|')) return 0
  const cells = splitCells(trimmed)
  return cells.length
}

/** Delimiter cells (`---`, `:--:`, ...) of a row, or null when it is not one. */
function delimiterCells(line: string | undefined): string[] | null {
  if (line === undefined || !line.includes('-')) return null
  const cells = splitCells(line.trim())
  if (cells.length === 0) return null
  return cells.every(cell => /^:?-+:?$/.test(cell.trim())) ? cells : null
}

function splitCells(line: string): string[] {
  const cells: string[] = []
  let current = ''
  for (let index = 0; index < line.length; index += 1) {
    const char = line[index]
    if (char === '\\' && line[index + 1] === '|') {
      current += '\\|'
      index += 1
      continue
    }
    if (char === '|') {
      cells.push(current)
      current = ''
      continue
    }
    current += char
  }
  cells.push(current)
  // A leading/trailing pipe produces an empty first/last cell that is not a column.
  if (cells.length > 1 && !cells[0].trim()) cells.shift()
  if (cells.length > 1 && !cells[cells.length - 1].trim()) cells.pop()
  return cells
}

function delimiterRow(columns: number): string {
  return `| ${Array.from({ length: columns }, () => '---').join(' | ')} |`
}

/** Four or more leading spaces make it an indented code block, not a table. */
function isIndentedCode(line: string): boolean {
  return /^ {4}/.test(line)
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
