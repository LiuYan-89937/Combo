import DOMPurify from 'dompurify'
import hljs from 'highlight.js'
import katex from 'katex'
import { marked } from 'marked'
import { prepareMarkdownSource } from './source'
import type { MarkdownRenderOptions, MarkdownRenderResult } from './types'
import 'highlight.js/styles/github-dark.css'
import 'katex/dist/katex.min.css'

marked.setOptions({
  breaks: true,
  gfm: true,
})

marked.use({
  renderer: {
    code(code: string, infostring: string | undefined) {
      const lang = (infostring || '').trim().split(/\s+/)[0]
      if (lang === 'mermaid') {
        return `<div class="mermaid">${escapeHtml(code)}</div>`
      }
      const langClass = lang ? ` class="language-${escapeHtml(lang)}"` : ''
      return `<pre><code${langClass}>${highlightCode(code, lang)}</code></pre>`
    },
  },
})

export function renderMarkdownDocument(content: string, options: MarkdownRenderOptions = {}): MarkdownRenderResult {
  const source = prepareMarkdownSource(content, options)
  try {
    const html = marked.parse(renderMath(source), { async: false }) as string
    return {
      source,
      html: sanitizeMarkdownHtml(html),
    }
  } catch (err) {
    console.error('Markdown parse error:', err)
    return {
      source,
      html: escapeHtml(content),
    }
  }
}

export function escapeHtml(text: string): string {
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

function renderMath(content: string): string {
  const lines = content.split('\n')
  const rendered: string[] = []
  let inFence = false
  let fenceMarker = ''
  let displayMathBuffer: string[] | null = null

  for (const line of lines) {
    const fence = line.match(/^ {0,3}(`{3,}|~{3,})/)
    if (fence) {
      if (!inFence) {
        inFence = true
        fenceMarker = fence[1][0]
      } else if (fence[1][0] === fenceMarker) {
        inFence = false
        fenceMarker = ''
      }
      rendered.push(line)
      continue
    }
    if (inFence) {
      rendered.push(line)
      continue
    }

    const trimmed = line.trim()
    if (displayMathBuffer) {
      if (trimmed.endsWith('$$')) {
        displayMathBuffer.push(trimmed.slice(0, -2))
        rendered.push(renderKatexBlock(displayMathBuffer.join('\n'), true))
        displayMathBuffer = null
      } else {
        displayMathBuffer.push(line)
      }
      continue
    }
    if (trimmed.startsWith('$$') && !trimmed.slice(2).includes('$$')) {
      displayMathBuffer = [trimmed.slice(2)]
      continue
    }

    rendered.push(renderInlineMath(line))
  }

  if (displayMathBuffer) {
    rendered.push('$$')
    rendered.push(...displayMathBuffer)
  }
  return rendered.join('\n')
}

function renderInlineMath(line: string): string {
  return line
    .replace(/\\\[([\s\S]+?)\\\]/g, (_match, expression: string) => renderKatexBlock(expression, true))
    .replace(/\\\((.+?)\\\)/g, (_match, expression: string) => renderKatexBlock(expression, false))
    .replace(/\$\$([\s\S]+?)\$\$/g, (_match, expression: string) => renderKatexBlock(expression, true))
    .replace(/(^|[^\\$])\$([^$\n]+?)\$/g, (match, prefix: string, expression: string) => {
      if (!shouldRenderInlineMath(expression)) return match
      return `${prefix}${renderKatexBlock(expression, false)}`
    })
}

function shouldRenderInlineMath(expression: string): boolean {
  const text = expression.trim()
  if (!text) return false
  if (/^\d+(?:[.,]\d+)?$/.test(text)) return false
  return /[\\^_={}+\-*/]|[α-ωΑ-Ω]/.test(text)
}

function renderKatexBlock(expression: string, displayMode: boolean): string {
  const math = expression.trim()
  if (!math) return ''
  try {
    const html = katex.renderToString(math, {
      displayMode,
      throwOnError: false,
      strict: 'ignore',
    })
    return displayMode
      ? `\n<div class="math math-display">${html}</div>\n`
      : `<span class="math math-inline">${html}</span>`
  } catch (err) {
    console.error('KaTeX render error:', err)
    return escapeHtml(displayMode ? `$$${math}$$` : `$${math}$`)
  }
}

function sanitizeMarkdownHtml(html: string): string {
  return DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true, svg: true, mathMl: true },
    ADD_ATTR: ['target', 'rel', 'class'],
  })
}
