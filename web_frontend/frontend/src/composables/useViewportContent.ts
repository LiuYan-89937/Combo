import { ref, watch, type Ref } from 'vue'

interface ViewportTarget {
  visibility: (visible: boolean) => void
  resize: (height: number) => void
}

// All message/record shells share observers. Only lightweight placeholders
// survive outside the viewport; unregistering the last shell releases both.
const targets = new Map<Element, ViewportTarget>()
let visibilityObserver: IntersectionObserver | null = null
let sizeObserver: ResizeObserver | null = null

function observe(element: HTMLElement, target: ViewportTarget): () => void {
  targets.set(element, target)
  visibilityObserver ??= new IntersectionObserver(entries => {
    for (const entry of entries) targets.get(entry.target)?.visibility(entry.isIntersecting)
  }, { rootMargin: `${document.documentElement.clientHeight}px 0px` })
  sizeObserver ??= new ResizeObserver(entries => {
    for (const entry of entries) {
      const height = entry.borderBoxSize[0]?.blockSize ?? entry.target.getBoundingClientRect().height
      targets.get(entry.target)?.resize(height)
    }
  })
  visibilityObserver.observe(element)
  sizeObserver.observe(element)
  return () => {
    targets.delete(element)
    visibilityObserver?.unobserve(element)
    sizeObserver?.unobserve(element)
    if (targets.size === 0) {
      visibilityObserver?.disconnect()
      sizeObserver?.disconnect()
      visibilityObserver = null
      sizeObserver = null
    }
  }
}

export function useViewportContent(element: Ref<HTMLElement | null>, keepMounted: () => boolean) {
  const mounted = ref(true)
  const height = ref<number | null>(null)
  let visible = true
  const reconcile = () => {
    const focused = element.value?.contains(document.activeElement)
    const selection = document.getSelection()
    const selected = selection && !selection.isCollapsed
      && (element.value?.contains(selection.anchorNode) || element.value?.contains(selection.focusNode))
    mounted.value = visible || keepMounted() || height.value === null || Boolean(focused || selected)
  }
  watch(element, (node, _previous, onCleanup) => {
    if (!node || typeof IntersectionObserver === 'undefined' || typeof ResizeObserver === 'undefined') return
    const unobserve = observe(node, {
      visibility(value) {
        visible = value
        // Measure once before unmounting: no guessed row heights or scroll jump.
        if (mounted.value) height.value = node.getBoundingClientRect().height
        reconcile()
      },
      resize(value) {
        if (mounted.value) height.value = value
      },
    })
    onCleanup(unobserve)
  }, { flush: 'post' })
  watch(keepMounted, reconcile)
  return { mounted, height }
}
