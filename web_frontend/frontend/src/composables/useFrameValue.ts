import { onBeforeUnmount, shallowRef, watch } from 'vue'

/** Coalesce streamed values to paint frames; terminal values flush immediately. */
export function useFrameValue<T>(source: () => T, streaming: () => boolean) {
  const value = shallowRef<T>(source())
  let frame: number | null = null
  const cancel = () => {
    if (frame !== null) cancelAnimationFrame(frame)
    frame = null
  }
  watch([source, streaming], () => {
    if (!streaming()) {
      cancel()
      value.value = source()
    } else if (frame === null) {
      frame = requestAnimationFrame(() => {
        frame = null
        value.value = source()
      })
    }
  }, { flush: 'sync' })
  onBeforeUnmount(cancel)
  return value
}
