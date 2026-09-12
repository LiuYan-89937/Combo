import { runtimeLocale, translate } from '@/i18n'
import { writeClipboardText } from '@/utils/clipboard'
import { isTauri } from '@tauri-apps/api/core'
import { open } from '@tauri-apps/plugin-shell'
import { enhanceMermaidDiagrams } from './mermaid'

const copyHandlerRoots = new WeakSet<EventTarget>()
const copyResetTimers = new WeakMap<HTMLButtonElement, number>()
const enhancedExternalLinks = new WeakSet<HTMLAnchorElement>()
const imageClickRoots = new WeakMap<EventTarget, ImageClickHolder>()

/** One rendered markdown image, as handed to the lightbox. */
export interface MarkdownImageDescriptor {
  src: string
  alt: string
}

/** Payload of a click on an image inside rendered markdown. */
export interface MarkdownImageClickEvent extends MarkdownImageDescriptor {
  /** Every image in the same `.markdown-content` block, in document order. */
  images: MarkdownImageDescriptor[]
  index: number
}

export type MarkdownImageClickHandler = (event: MarkdownImageClickEvent) => void

export interface EnhanceMarkdownOptions {
  /**
   * Called when a rendered markdown image is clicked. Without it, image clicks
   * keep their default behaviour.
   */
  onImageClick?: MarkdownImageClickHandler
}

interface ImageClickHolder {
  onImageClick?: MarkdownImageClickHandler
}

export async function enhanceRenderedMarkdown(
  root: ParentNode | null,
  options: EnhanceMarkdownOptions = {},
): Promise<void> {
  if (!root) return
  enhanceCodeCopyButtons(root)
  enhanceExternalLinks(root)
  enhanceMarkdownImages(root, options.onImageClick)
  await enhanceMermaidDiagrams(root)
}

/**
 * Delegated image-click enhancement for rendered markdown.
 *
 * Images in chat messages can only carry a resolved URL, so the click is turned
 * into a lightbox request instead of the default navigation. The listener runs
 * in the capture phase on purpose: an image that came from a markdown link sits
 * inside `<a target="_blank">`, and that anchor's own handler (external links)
 * would otherwise run first and still open a tab.
 */
function enhanceMarkdownImages(root: ParentNode, onImageClick?: MarkdownImageClickHandler): void {
  const eventRoot = root as ParentNode & EventTarget
  let holder = imageClickRoots.get(eventRoot)
  if (!holder) {
    holder = {}
    imageClickRoots.set(eventRoot, holder)
    eventRoot.addEventListener('click', event => handleMarkdownImageClick(event, holder as ImageClickHolder), true)
  }
  holder.onImageClick = onImageClick
}

function handleMarkdownImageClick(event: Event, holder: ImageClickHolder): void {
  const onImageClick = holder.onImageClick
  if (!onImageClick) return
  const target = event.target
  if (!(target instanceof HTMLImageElement)) return
  // Only markdown body images: attachment/artifact cards keep their own actions.
  const container = target.closest('.markdown-content')
  if (!container) return
  const elements = Array.from(container.querySelectorAll('img'))
  const index = elements.indexOf(target)
  if (index < 0) return
  event.preventDefault()
  event.stopPropagation()
  const images = elements.map(image => ({
    src: image.currentSrc || image.getAttribute('src') || '',
    alt: image.getAttribute('alt') || '',
  }))
  onImageClick({ ...images[index], images, index })
}

function enhanceExternalLinks(root: ParentNode): void {
  root.querySelectorAll<HTMLAnchorElement>('a[href]').forEach((anchor) => {
    if (enhancedExternalLinks.has(anchor)) return
    const url = externalHttpUrl(anchor.href)
    if (!url) return
    enhancedExternalLinks.add(anchor)
    anchor.rel = 'noopener noreferrer'
    anchor.addEventListener('click', (event) => {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
      // 别的处理器（例如图片放大链路）已经接管这次点击时，不要再开一个标签页。
      if (event.defaultPrevented) return
      event.preventDefault()
      event.stopPropagation()
      void openExternalUrl(url)
    })
  })
}

function externalHttpUrl(value: string): string | null {
  try {
    const url = new URL(value)
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : null
  } catch {
    return null
  }
}

async function openExternalUrl(url: string): Promise<void> {
  try {
    if (isTauri()) {
      await open(url)
      return
    }
    window.open(url, '_blank', 'noopener,noreferrer')
  } catch (error) {
    console.error('External link open failed:', error)
  }
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
