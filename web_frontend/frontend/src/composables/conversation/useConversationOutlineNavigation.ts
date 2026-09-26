import { onBeforeUnmount, ref, type Ref } from 'vue'

interface OutlineNavigationHost {
  messageList: Ref<HTMLElement | null>
  scrollContainer: () => HTMLElement | null
  scrollTo: (top: number) => void
  stopFollowingLatest: () => void
}

export function useConversationOutlineNavigation(host: OutlineNavigationHost) {
  const activeAnchorId = ref<string | null>(null)
  let frame: number | null = null

  function anchors(): HTMLElement[] {
    return Array.from(host.messageList.value?.querySelectorAll<HTMLElement>('[data-anchor-id]') ?? [])
  }

  function scheduleUpdate(): void {
    if (frame !== null) return
    frame = window.requestAnimationFrame(() => {
      frame = null
      update()
    })
  }

  function update(): void {
    const container = host.scrollContainer()
    const items = anchors()
    if (!container || !items.length) {
      activeAnchorId.value = null
      return
    }

    const threshold = container.getBoundingClientRect().top + 96
    let left = 0
    let right = items.length - 1
    while (left <= right) {
      const middle = (left + right) >>> 1
      if (items[middle].getBoundingClientRect().top <= threshold) left = middle + 1
      else right = middle - 1
    }
    activeAnchorId.value = items[Math.max(0, right)].dataset.anchorId ?? null
  }

  function jump(anchorId: string): boolean {
    const container = host.scrollContainer()
    const anchor = anchors().find(element => element.dataset.anchorId === anchorId)
    if (!container || !anchor) return false
    host.stopFollowingLatest()
    const offset = anchor.getBoundingClientRect().top - container.getBoundingClientRect().top
    host.scrollTo(Math.max(0, container.scrollTop + offset - 12))
    activeAnchorId.value = anchorId
    return true
  }

  function reset(): void {
    activeAnchorId.value = null
  }

  onBeforeUnmount(() => {
    if (frame !== null) window.cancelAnimationFrame(frame)
  })

  return { activeAnchorId, anchors, scheduleUpdate, jump, reset }
}
