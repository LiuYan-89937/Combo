interface CachedAnimationFrame {
  image: HTMLImageElement
  ready: Promise<boolean>
}

const frameCache = new Map<string, CachedAnimationFrame>()

export function preloadComboMascotFrame(source: string): Promise<boolean> {
  const cached = frameCache.get(source)
  if (cached) return cached.ready

  const image = new Image()
  const ready = new Promise<boolean>((resolve) => {
    image.addEventListener('load', async () => {
      try {
        await image.decode()
      } catch {
        // A completed load is safe to display when explicit decoding is unavailable.
      }
      resolve(true)
    }, { once: true })
    image.addEventListener('error', () => resolve(false), { once: true })
  })
  frameCache.set(source, { image, ready })
  image.src = source
  return ready
}
