/**
 * useMarkdown Composable
 * Markdown 渲染和代码高亮
 */

import { marked } from 'marked'
import hljs from 'highlight.js'
import 'highlight.js/styles/github-dark.css'

interface RenderMarkdownOptions {
  streaming?: boolean
}

interface OpenFence {
  marker: '`' | '~'
  length: number
}

function escapeHtml(text: string): string {
  const map: Record<string, string> = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#039;',
  }
  return text.replace(/[&<>"']/g, (m) => map[m])
}

function highlightCode(code: string, lang?: string): string {
  if (lang && hljs.getLanguage(lang)) {
    try {
      return hljs.highlight(code, { language: lang }).value
    } catch (err) {
      console.error('Highlight error:', err)
    }
  }
  return hljs.highlightAuto(code).value
}

// 配置 marked
marked.setOptions({
  breaks: true,
  gfm: true,
})

marked.use({
  renderer: {
    code(code: string, infostring: string | undefined) {
      const lang = (infostring || '').trim().split(/\s+/)[0]
      const langClass = lang ? ` class="language-${escapeHtml(lang)}"` : ''
      return `<pre><code${langClass}>${highlightCode(code, lang)}</code></pre>`
    },
  },
})

export function useMarkdown() {
  function renderMarkdown(content: string, options: RenderMarkdownOptions = {}): string {
    try {
      const source = prepareMarkdownSource(content, options)
      return marked.parse(source, { async: false }) as string
    } catch (err) {
      console.error('Markdown parse error:', err)
      return escapeHtml(content)
    }
  }

  return {
    renderMarkdown,
    escapeHtml,
  }
}

function prepareMarkdownSource(content: string, options: RenderMarkdownOptions): string {
  const normalized = normalizeDisplayMarkdown(content)
  return options.streaming ? closeStreamingFence(normalized) : normalized
}

function normalizeDisplayMarkdown(content: string): string {
  const lines = content.replace(/\r\n?/g, '\n').split('\n')
  let openFence: OpenFence | null = null
  return lines.map((line) => {
    const fence = parseFenceLine(line)
    const insideFence = openFence !== null
    if (fence) {
      if (!openFence) {
        openFence = fence
      } else if (fence.marker === openFence.marker && fence.length >= openFence.length) {
        openFence = null
      }
      return line
    }
    return insideFence ? line : normalizeMarkdownLine(line)
  }).join('\n')
}

function normalizeMarkdownLine(line: string): string {
  const withSeparatedRules = line
    .replace(/([^\n\s])((?:---|\*\*\*|___)(?=#{1,6}\S))/g, '$1\n\n$2')
    .replace(/(^|\n)( {0,3}(?:---|\*\*\*|___))(?=#{1,6}\S)/g, '$1$2\n\n')

  return withSeparatedRules
    .split('\n')
    .map((part) => part.replace(/^( {0,3}#{1,6})(?=[^\s#])/, '$1 '))
    .join('\n')
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
