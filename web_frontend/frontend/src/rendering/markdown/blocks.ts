import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import remarkParse from 'remark-parse'
import { unified } from 'unified'
import { renderMarkdownDocument } from './html'
import { prepareMarkdownSource } from './source'
import type { MarkdownRenderOptions } from './types'

export interface MarkdownBlock {
  key: string
  html: string
}

const parser = unified().use(remarkParse).use(remarkGfm).use(remarkMath)

/** Enough for the largest message; oldest entries are dropped first. */
const CACHE_LIMIT = 120

/**
 * Splits normalized markdown into its top-level blocks, keeping each block's
 * exact source text.
 *
 * Streaming re-parses on every chunk. Replacing one giant HTML string each time
 * throws away the DOM of everything already rendered: images reload and replay
 * their entrance animation, code blocks lose their scroll position, and diagrams
 * rebuild. Rendering one element per block and keying it by content means a
 * finished block is never touched again — only the block still being streamed
 * changes. (The finished message is rendered as a single document again, so
 * cross-block constructs such as reference links and footnotes are only
 * approximate while streaming.)
 */
export function splitMarkdownBlocks(source: string): { key: string; source: string }[] {
  const tree = parser.parse(source) as { children?: any[] }
  const blocks: { key: string; source: string }[] = []
  for (const node of tree.children ?? []) {
    const start = node?.position?.start?.offset
    const end = node?.position?.end?.offset
    if (typeof start !== 'number' || typeof end !== 'number' || end <= start) continue
    const text = source.slice(start, end)
    if (!text.trim()) continue
    blocks.push({ key: blockKey(String(node?.type || 'block'), text), source: text })
  }
  return blocks
}

export function renderMarkdownBlocks(
  content: string,
  options: MarkdownRenderOptions = {},
  cache?: Map<string, string>,
): MarkdownBlock[] {
  const source = prepareMarkdownSource(content, options)
  return splitMarkdownBlocks(source).map((block) => {
    const cached = cache?.get(block.key)
    if (cached !== undefined) return { key: block.key, html: cached }
    const html = renderMarkdownDocument(block.source, { ...options, streaming: false }).html
    if (cache) remember(cache, block.key, html)
    return { key: block.key, html }
  })
}

function remember(cache: Map<string, string>, key: string, html: string): void {
  if (cache.size >= CACHE_LIMIT) {
    const oldest = cache.keys().next().value
    if (oldest !== undefined) cache.delete(oldest)
  }
  cache.set(key, html)
}

/** Short stable id for a block's source text, used as its rendering key. */
function blockKey(type: string, text: string): string {
  let hash = 0x811c9dc5
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index)
    hash = Math.imul(hash, 0x01000193)
  }
  return `${type}:${text.length}:${(hash >>> 0).toString(36)}`
}
