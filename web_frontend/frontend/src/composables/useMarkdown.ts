/**
 * useMarkdown Composable
 * Markdown 渲染和代码高亮
 */

import { marked } from 'marked'
import hljs from 'highlight.js'
import 'highlight.js/styles/github-dark.css'

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
  function renderMarkdown(content: string): string {
    try {
      return marked.parse(content, { async: false }) as string
    } catch (err) {
      console.error('Markdown parse error:', err)
      return content
    }
  }

  return {
    renderMarkdown,
    escapeHtml,
  }
}
