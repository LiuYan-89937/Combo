import { nextTick, watch, type Ref, type WatchSource } from 'vue'

/** Follow content updates only when the reader was already at the bottom. */
export function usePinnedScroll(elementRef: Ref<HTMLElement | null>, source: WatchSource) {
  let interactionRevision = 0
  let following = true
  const atBottom = (element: HTMLElement) => (
    element.scrollHeight - element.scrollTop - element.clientHeight <= 1
  )

  watch(elementRef, (element, _previous, onCleanup) => {
    interactionRevision += 1
    following = true
    if (!element) return

    // Cancel scheduled following as soon as input arrives, before the browser
    // applies the gesture. Scroll position alone cannot detect that interval.
    const suspend = () => {
      interactionRevision += 1
      following = false
    }
    const onWheel = (event: WheelEvent) => {
      if (event.deltaY !== 0) suspend()
    }
    const onKeydown = (event: KeyboardEvent) => {
      if (['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End', ' '].includes(event.key)) suspend()
    }
    const onScroll = () => { following = atBottom(element) }
    element.addEventListener('wheel', onWheel, { passive: true })
    element.addEventListener('touchstart', suspend, { passive: true })
    element.addEventListener('pointerdown', suspend, { passive: true })
    element.addEventListener('keydown', onKeydown)
    element.addEventListener('scroll', onScroll, { passive: true })
    onCleanup(() => {
      element.removeEventListener('wheel', onWheel)
      element.removeEventListener('touchstart', suspend)
      element.removeEventListener('pointerdown', suspend)
      element.removeEventListener('keydown', onKeydown)
      element.removeEventListener('scroll', onScroll)
    })
  }, { flush: 'post', immediate: true })

  watch(source, () => {
    const element = elementRef.value
    if (!element || !following) return
    // scrollTop can be fractional; scrollHeight/clientHeight are rounded.
    if (!atBottom(element)) return
    const revision = interactionRevision
    const previousTop = element.scrollTop
    nextTick(() => {
      if (!following || interactionRevision !== revision
        || elementRef.value !== element || element.scrollTop < previousTop) return
      element.scrollTop = element.scrollHeight
    })
  }, { flush: 'pre' })
}
