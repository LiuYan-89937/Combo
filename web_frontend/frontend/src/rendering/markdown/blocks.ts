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
    blocks.push({ key: `${start}:${blockKey(String(node?.type || 'block'), text)}`, source: text })
  }
  return blocks
}

export function renderMarkdownBlocks(
  content: string,
  options: MarkdownRenderOptions = {},
  cache?: Map<string, MarkdownBlock>,
): MarkdownBlock[] {
  const source = prepareMarkdownSource(content, options)
  const blocks = splitMarkdownBlocks(source)
  // Retain only the current document, never previous revisions of a growing
  // paragraph/code block. Cache space is proportional to displayed content.
  const keys = new Set(blocks.map(block => block.key))
  if (cache) {
    for (const key of cache.keys()) if (!keys.has(key)) cache.delete(key)
  }
  return blocks.map((block) => {
    const cached = cache?.get(block.key)
    if (cached !== undefined) return cached
    const html = renderMarkdownDocument(block.source, { ...options, streaming: false }).html
    const rendered = { key: block.key, html }
    cache?.set(block.key, rendered)
    return rendered
  })
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
