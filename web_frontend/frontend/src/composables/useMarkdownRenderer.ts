import { nextTick, onBeforeUnmount, onMounted, onUpdated, type Ref } from 'vue'
import {
  enhanceRenderedMarkdown,
  renderMarkdownBlocks,
  renderMarkdownDocument,
  type MarkdownBlock,
  type MarkdownRenderOptions,
} from '@/rendering/markdown'
import type { MarkdownImageClickHandler } from '@/rendering/markdown/dom'

export interface UseMarkdownRendererOptions {
  /** Forwarded to the enhancement step so markdown images can open the viewer. */
  onImageClick?: MarkdownImageClickHandler
}

export function useMarkdownRenderer(
  rootRef: Ref<ParentNode | null>,
  options: UseMarkdownRendererOptions = {},
) {
  /**
   * Streaming renders block by block so that finished blocks keep their DOM.
   * The cache lives on the renderer instance, so options that differ per
   * message (image resolution, surface) can never leak between messages.
   */
  const blockCache = new Map<string, string>()

  function renderMarkdown(content: string, options: MarkdownRenderOptions = {}): string {
    return renderMarkdownDocument(content, options).html
  }

  function renderStreamingBlocks(
    content: string,
    options: MarkdownRenderOptions = {},
  ): MarkdownBlock[] {
    return renderMarkdownBlocks(content, options, blockCache)
  }

  function refreshMarkdownEnhancements() {
    nextTick(() => {
      void enhanceRenderedMarkdown(rootRef.value, { onImageClick: options.onImageClick })
    })
  }

  onMounted(refreshMarkdownEnhancements)
  onUpdated(refreshMarkdownEnhancements)
  onBeforeUnmount(() => {
    blockCache.clear()
  })

  return {
    renderMarkdown,
    renderStreamingBlocks,
    refreshMarkdownEnhancements,
  }
}
