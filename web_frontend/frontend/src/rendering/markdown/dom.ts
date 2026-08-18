import mermaid from 'mermaid'
import { runtimeLocale, translate } from '@/i18n'
import { writeClipboardText } from '@/utils/clipboard'

let mermaidInitialized = false
const copyHandlerRoots = new WeakSet<EventTarget>()
const copyResetTimers = new WeakMap<HTMLButtonElement, number>()

export async function enhanceRenderedMarkdown(root: ParentNode | null): Promise<void> {
  if (!root) return
  enhanceCodeCopyButtons(root)
  await renderMermaidDiagrams(root)
}

function enhanceCodeCopyButtons(root: ParentNode): void {
  const label = translate(runtimeLocale(), 'markdown.copyCode')
  root.querySelectorAll<HTMLButtonElement>('[data-markdown-copy="true"]').forEach((button) => {
    if (!button.classList.contains('is-copied')) {
      button.title = label
      button.setAttribute('aria-label', label)
    }
  })
  const eventRoot = root as ParentNode & EventTarget
  if (copyHandlerRoots.has(eventRoot)) return
  eventRoot.addEventListener('click', handleCodeCopyClick)
  copyHandlerRoots.add(eventRoot)
}

function handleCodeCopyClick(event: Event): void {
  const target = event.target
  if (!(target instanceof Element)) return
  const button = target.closest<HTMLButtonElement>('[data-markdown-copy="true"]')
  if (!button) return
  const code = button.closest('.markdown-code-block')?.querySelector('pre code')
  if (!code) return
  event.preventDefault()
  event.stopPropagation()
  void copyCode(button, code.textContent || '')
}

async function copyCode(button: HTMLButtonElement, content: string): Promise<void> {
  try {
    await writeClipboardText(content)
  } catch (error) {
    console.error('Code block copy failed:', error)
    return
  }
  const copiedLabel = translate(runtimeLocale(), 'markdown.codeCopied')
  button.classList.add('is-copied')
  button.title = copiedLabel
  button.setAttribute('aria-label', copiedLabel)
  const icon = button.querySelector<HTMLElement>('span')
  if (icon) icon.textContent = '✓'
  const existingTimer = copyResetTimers.get(button)
  if (existingTimer !== undefined) window.clearTimeout(existingTimer)
  const timer = window.setTimeout(() => {
    const label = translate(runtimeLocale(), 'markdown.copyCode')
    button.classList.remove('is-copied')
    button.title = label
    button.setAttribute('aria-label', label)
    if (icon) icon.textContent = '⧉'
    copyResetTimers.delete(button)
  }, 1600)
  copyResetTimers.set(button, timer)
}

async function renderMermaidDiagrams(root: ParentNode): Promise<void> {
  const nodes = Array.from(root.querySelectorAll<HTMLElement>('.mermaid:not([data-processed="true"])'))
  if (nodes.length === 0) return
  if (!mermaidInitialized) {
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: 'strict',
      theme: 'neutral',
    })
    mermaidInitialized = true
  }
  nodes.forEach((node) => {
    node.dataset.processed = 'true'
  })
  try {
    await mermaid.run({ nodes })
  } catch (err) {
    console.error('Mermaid render error:', err)
  }
}
